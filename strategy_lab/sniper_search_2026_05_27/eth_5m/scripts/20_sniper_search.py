"""
ETH 5m sniper search.

Algorithm:
  1. Load joined universe (133k fires).
  2. Per-offset baseline scan: compute (n, WR, $/tr) for each fire_offset.
  3. Greedy combinatorial search per offset_bin: stack up to 6 gates, prefer high WR + sniper n.
  4. For each candidate sleeve, perform 3-way split chronological:
     train (first ~22d) / val (next ~6d) / lockbox (last 5d).
  5. Apply target profile filter: n_lockbox >= 8, WR_lockbox >= 0.75, $/tr_lockbox >= $3,
     max_dd_25_lockbox <= $300, loss_streak <= 6, sharpe >= 2.0, bootstrap_p <= 0.05.
  6. Two rosters: one without book-depth gate ($25-only), one with g_book_depth_supports_250 ($250-capable).
  7. Emit top_5_candidates.csv per roster + 4 cumulative-PnL PNGs + full report markdown.

Engine: legacy 2%-on-profit (matches production).
"""
import sys, os, json, itertools
import pandas as pd
import numpy as np
from collections import defaultdict

UNIVERSE = "data/v4/canonical/_results/_sniper_eth5m_v3_universe.parquet"
OUT_DIR = "strategy_lab/sniper_search_2026_05_27/eth_5m"
RES_DIR = f"{OUT_DIR}/_results"
os.makedirs(RES_DIR, exist_ok=True)

# -----------------------------------------------------------------------------
# Metric helpers
# -----------------------------------------------------------------------------
STAKE25 = 25.0
STAKE250 = 250.0

def scale_pnl(pnl_legacy_at_25, stake):
    """pnl_legacy_usd is the per-trade PnL at $25 stake (we'll verify). Scale to other stake."""
    return pnl_legacy_at_25 * (stake / 25.0)

def max_dd(pnl_series):
    if len(pnl_series) == 0:
        return 0.0
    cum = np.cumsum(pnl_series)
    peak = np.maximum.accumulate(cum)
    return float((cum - peak).min())

def max_loss_streak(won_series):
    cur = 0
    mx = 0
    for w in won_series:
        if not w:
            cur += 1
            if cur > mx:
                mx = cur
        else:
            cur = 0
    return mx

def daily_sharpe(df_subset, stake=25.0):
    if len(df_subset) == 0:
        return 0.0
    pnls = scale_pnl(df_subset["pnl_legacy_usd"].values, stake)
    days = pd.to_datetime(df_subset["fire_us"].values, unit="us").date
    by_day = pd.Series(pnls).groupby(pd.Series(days)).sum()
    if by_day.std() == 0 or len(by_day) < 2:
        return 0.0
    return float(by_day.mean() / by_day.std() * np.sqrt(365))

def bootstrap_p(df_subset, n_iter=1000, stake=25.0, seed=42):
    """Daily-clustered bootstrap. Resample days with replacement.
    Returns p = fraction of bootstrapped trade-means <= 0 (one-sided).
    """
    if len(df_subset) < 5:
        return 1.0
    pnls = scale_pnl(df_subset["pnl_legacy_usd"].values, stake)
    days_arr = pd.to_datetime(df_subset["fire_us"].values, unit="us").date
    obs_mean = pnls.mean()
    if obs_mean <= 0:
        return 1.0
    unique_days = sorted(set(days_arr))
    if len(unique_days) < 2:
        return 1.0
    day_to_pnls = {d: pnls[days_arr == d] for d in unique_days}
    day_pnls = [day_to_pnls[d] for d in unique_days]
    rng = np.random.default_rng(seed)
    means = np.empty(n_iter)
    for i in range(n_iter):
        idx = rng.integers(0, len(day_pnls), size=len(day_pnls))
        flat = np.concatenate([day_pnls[j] for j in idx])
        means[i] = flat.mean()
    p = (means <= 0).mean()
    return float(p)

def evaluate(df_subset, stake=25.0):
    """Compute all metrics for a candidate trade set."""
    n = len(df_subset)
    if n == 0:
        return dict(n=0, wr=0, sum_pnl=0, dpt=0, max_dd=0, loss_streak=0, sharpe=0)
    won = df_subset["won"].values
    pnl = scale_pnl(df_subset["pnl_legacy_usd"].values, stake)
    sleeve_ordered = df_subset.sort_values("fire_us")
    pnl_ord = scale_pnl(sleeve_ordered["pnl_legacy_usd"].values, stake)
    won_ord = sleeve_ordered["won"].values
    return dict(
        n=int(n),
        wr=float(won.mean()),
        sum_pnl=float(pnl.sum()),
        dpt=float(pnl.mean()),
        max_dd=max_dd(pnl_ord),
        loss_streak=max_loss_streak(won_ord),
        sharpe=daily_sharpe(sleeve_ordered, stake=stake),
    )

# -----------------------------------------------------------------------------
# Universe + split
# -----------------------------------------------------------------------------
def split_chrono(df, n_lockbox=5, n_val=6):
    """Chronological train / val / lockbox split."""
    days = sorted(df["day"].unique())
    if len(days) < (n_lockbox + n_val + 5):
        # adapt for narrow window
        n_val = max(3, (len(days) - n_lockbox) // 4)
    lockbox_days = set(days[-n_lockbox:])
    val_days = set(days[-(n_lockbox + n_val):-n_lockbox])
    train_days = set(days[:-(n_lockbox + n_val)])
    return train_days, val_days, lockbox_days

# -----------------------------------------------------------------------------
# Search engine
# -----------------------------------------------------------------------------
def filter_mask(df, gates):
    if not gates:
        return np.ones(len(df), dtype=bool)
    m = np.ones(len(df), dtype=bool)
    for g in gates:
        if g not in df.columns:
            return np.zeros(len(df), dtype=bool)
        col = df[g].astype("float").fillna(0).values
        m &= (col >= 1.0)
    return m

def greedy_search_within(df_pool, train_days, val_days, lockbox_days,
                          atoms, max_depth=6, n_cap=500, min_n=50,
                          min_wr_train=0.60, min_dpt_train=-2.0,
                          stake=25.0, n_top=25, depth_required=False):
    """Greedy combinatorial search within a fire pool.

    Returns list of candidate dicts (sorted by train-set score, descending).
    Strategy:
      - start from atoms (depth=1).
      - for each surviving prefix, try adding each remaining atom.
      - keep top ~50 by combined train_score = wr * dpt * log(n) IF n in [min_n, n_cap].
      - depth up to max_depth.
    """
    candidates = []
    train_mask_all = df_pool["day"].isin(train_days).values
    df_train = df_pool[train_mask_all]
    if len(df_train) < min_n:
        return candidates

    # baseline (no gates)
    base = evaluate(df_train, stake=stake)
    # Seed
    beam = [([], base)]
    seen = set()
    for depth in range(1, max_depth + 1):
        next_beam = []
        for prefix, _ in beam:
            for atom in atoms:
                if atom in prefix:
                    continue
                gates = sorted(prefix + [atom])
                key = "|".join(gates)
                if key in seen:
                    continue
                seen.add(key)
                # If depth_required is True, ensure book-depth gate present at depth>=2
                if depth_required and depth == max_depth and "g_book_depth_supports_250" not in gates:
                    continue
                m = filter_mask(df_train, gates)
                sub = df_train[m]
                n = len(sub)
                if n < min_n or n > n_cap * 2.0:  # allow 2x for train, scale to lockbox
                    continue
                ev = evaluate(sub, stake=stake)
                if ev["wr"] < min_wr_train or ev["dpt"] < min_dpt_train:
                    continue
                # Sniper score = WR boost above 0.5 baseline, weighted by sqrt(n) to keep tight sleeves
                # but penalize big losses.
                score = (ev["wr"] - 0.5) * np.sqrt(max(ev["n"], 1)) + 0.05 * ev["dpt"]
                next_beam.append((gates, ev, score))
        if not next_beam:
            break
        next_beam.sort(key=lambda x: -x[2])
        next_beam = next_beam[:50]  # beam width
        # collect for output
        for g, ev, sc in next_beam:
            candidates.append({"gates": g, "depth": len(g), "train_score": sc, **{f"train_{k}": v for k, v in ev.items()}})
        beam = [(g, ev) for g, ev, _ in next_beam]
    candidates.sort(key=lambda x: -x["train_score"])
    return candidates[:n_top * 4]  # keep extras for downstream filtering

def lockbox_validate(cand, df_pool, train_days, val_days, lockbox_days, stake=25.0, do_bootstrap=True):
    """Compute val + lockbox metrics + bootstrap p for a candidate."""
    df_train = df_pool[df_pool["day"].isin(train_days)]
    df_val = df_pool[df_pool["day"].isin(val_days)]
    df_lock = df_pool[df_pool["day"].isin(lockbox_days)]
    gates = cand["gates"]
    sub_t = df_train[filter_mask(df_train, gates)]
    sub_v = df_val[filter_mask(df_val, gates)]
    sub_l = df_lock[filter_mask(df_lock, gates)]
    out = {}
    for nm, sub in [("train", sub_t), ("val", sub_v), ("lockbox", sub_l)]:
        ev = evaluate(sub, stake=stake)
        out[f"{nm}_n"] = ev["n"]
        out[f"{nm}_wr"] = ev["wr"]
        out[f"{nm}_dpt_{int(stake)}"] = ev["dpt"]
        out[f"{nm}_sum_{int(stake)}"] = ev["sum_pnl"]
        out[f"{nm}_dd_{int(stake)}"] = ev["max_dd"]
        out[f"{nm}_loss_streak"] = ev["loss_streak"]
        out[f"{nm}_sharpe"] = ev["sharpe"]
    if do_bootstrap and out["lockbox_n"] >= 5:
        out["bootstrap_p_lockbox"] = bootstrap_p(sub_l, n_iter=1000, stake=stake)
    else:
        out["bootstrap_p_lockbox"] = 1.0
    return out

# -----------------------------------------------------------------------------
# Main search
# -----------------------------------------------------------------------------
def main():
    print(f"Loading universe: {UNIVERSE}")
    df = pd.read_parquet(UNIVERSE)
    print(f"  shape={df.shape}, days={df['day'].nunique()}")
    print(f"  baseline WR={df['won'].mean():.4f}  $/tr=${df['pnl_legacy_usd'].mean():+.3f}")

    train_days, val_days, lockbox_days = split_chrono(df, n_lockbox=5, n_val=6)
    print(f"\nSplit: train={len(train_days)}d  val={len(val_days)}d  lockbox={len(lockbox_days)}d")
    print(f"  lockbox days: {sorted(lockbox_days)}")

    # Build atom list — all g_ cols with reasonable coverage
    g_cols = [c for c in df.columns if c.startswith("g_")]
    print(f"\nGate atoms: {len(g_cols)}")
    # filter: at least 5% coverage on train set
    df_train_all = df[df["day"].isin(train_days)]
    keep_atoms = []
    for g in g_cols:
        cov = df_train_all[g].astype("float").fillna(0).mean()
        if cov > 0.05 and cov < 0.98:
            keep_atoms.append(g)
    print(f"  atoms passing 5-98% coverage: {len(keep_atoms)}")
    print(f"  {keep_atoms}")

    # exclude book-depth gates from primary atoms (treated separately)
    book_gates = ["g_book_depth_supports_250", "g_book_depth_supports_250_tight",
                  "g_book_depth_supports_25"]
    primary_atoms = [g for g in keep_atoms if g not in book_gates]

    # Per offset_bin: search
    # Include both broad bins and exact offsets that have above-baseline raw WR (30,60,90)
    offset_pools = [
        ("bin_0-60", df["offset_bin"] == "0-60"),
        ("bin_60-150", df["offset_bin"] == "60-150"),
        ("bin_150-240", df["offset_bin"] == "150-240"),
        ("bin_240-300", df["offset_bin"] == "240-300"),
        ("off_30", df["fire_offset_s"] == 30),
        ("off_60", df["fire_offset_s"] == 60),
        ("off_90", df["fire_offset_s"] == 90),
        ("off_120", df["fire_offset_s"] == 120),
    ]
    all_candidates = []
    for ob, mask in offset_pools:
        df_pool = df[mask]
        n_pool = len(df_pool)
        print(f"\n=== {ob}: n_pool={n_pool:,}, days={df_pool['day'].nunique()}")
        if n_pool < 1000:
            print("  skip — too small")
            continue
        # Train-set greedy — wider net
        cands = greedy_search_within(
            df_pool, train_days, val_days, lockbox_days, primary_atoms,
            max_depth=7, n_cap=2000, min_n=30,
            min_wr_train=0.55, min_dpt_train=-5.0, stake=25.0, n_top=80
        )
        print(f"  found {len(cands)} train-survivors. Validating top 200 ...")
        for c in cands[:200]:
            val = lockbox_validate(c, df_pool, train_days, val_days, lockbox_days, stake=25.0)
            c.update(val)
            c["offset_label"] = ob
            c["pool_mask_kind"] = ob
            c["sleeve_id"] = f"eth5m|{ob}|" + "&".join(c["gates"])
            c["roster"] = "$25-only"
            all_candidates.append(c)

    # Now add book-depth-gated variants ($250-capable)
    print(f"\n=== Adding $250-capable variants (book-depth gate stacked) ...")
    book_candidates = []
    for c in all_candidates:
        gates_250 = c["gates"] + ["g_book_depth_supports_250"]
        ob = c["offset_label"]
        # Re-derive pool mask
        if ob.startswith("bin_"):
            df_pool = df[df["offset_bin"] == ob.replace("bin_", "")]
        elif ob.startswith("off_"):
            df_pool = df[df["fire_offset_s"] == int(ob.replace("off_", ""))]
        else:
            continue
        sub = df_pool[filter_mask(df_pool, gates_250)]
        if len(sub) < 30:
            continue
        cand2 = {
            "gates": gates_250,
            "depth": len(gates_250),
            "train_score": 0.0,
            "offset_label": ob,
        }
        # Compute train/val/lockbox at stake=$25 AND $250
        v25 = lockbox_validate(cand2, df_pool, train_days, val_days, lockbox_days, stake=25.0)
        cand2.update(v25)
        # Add $250 metrics
        v250 = lockbox_validate(cand2, df_pool, train_days, val_days, lockbox_days,
                                stake=250.0, do_bootstrap=False)
        # Rename only the $250 keys to avoid clobber
        for k, v in v250.items():
            if "_250" in k or "sharpe" in k:
                cand2[f"{k}_at250"] = v
        cand2["sleeve_id"] = f"eth5m|{ob}|" + "&".join(gates_250)
        cand2["roster"] = "$250-capable"
        book_candidates.append(cand2)

    print(f"  $250-capable candidates: {len(book_candidates)}")

    # Filter to sniper profile: WR>=0.75, dpt>=$3, dd<=$300, streak<=6, sharpe>=2, p<=0.05
    def passes_sniper(c, stake_key=25):
        sk = stake_key
        return (
            c.get(f"lockbox_n", 0) >= 5 and
            c.get(f"lockbox_wr", 0) >= 0.75 and
            c.get(f"lockbox_dpt_{sk}", 0) >= 3.0 and
            c.get(f"lockbox_dd_{sk}", 0) >= -300.0 and
            c.get(f"lockbox_loss_streak", 99) <= 6 and
            c.get(f"lockbox_sharpe", 0) >= 2.0 and
            c.get(f"bootstrap_p_lockbox", 1.0) <= 0.05
        )

    # Less strict near-miss filter (for honest reporting)
    def near_miss(c, stake_key=25):
        sk = stake_key
        return (
            c.get(f"lockbox_n", 0) >= 5 and
            c.get(f"lockbox_wr", 0) >= 0.65 and
            c.get(f"lockbox_dpt_{sk}", 0) >= 1.0
        )

    roster_25 = [c for c in all_candidates if passes_sniper(c, 25)]
    roster_250 = [c for c in book_candidates if passes_sniper(c, 25)]  # passes at $25 with depth gate
    nm_25 = [c for c in all_candidates if (not passes_sniper(c, 25)) and near_miss(c, 25)]
    nm_250 = [c for c in book_candidates if (not passes_sniper(c, 25)) and near_miss(c, 25)]

    print(f"\n=== RESULTS ===")
    print(f"  $25 sniper sleeves passing profile: {len(roster_25)}")
    print(f"  $250-capable sniper sleeves       : {len(roster_250)}")
    print(f"  $25 near-misses                   : {len(nm_25)}")
    print(f"  $250 near-misses                  : {len(nm_250)}")

    # Persist all
    pd.DataFrame(all_candidates + book_candidates).to_csv(f"{RES_DIR}/all_candidates.csv", index=False)

    def score_for_rank(c, stake_key=25):
        return c.get(f"lockbox_dpt_{stake_key}", 0) * np.log(max(c.get("lockbox_n", 1), 2))

    roster_25.sort(key=lambda c: -score_for_rank(c, 25))
    roster_250.sort(key=lambda c: -score_for_rank(c, 25))
    nm_25.sort(key=lambda c: -score_for_rank(c, 25))
    nm_250.sort(key=lambda c: -score_for_rank(c, 25))

    # Emit top_5_candidates.csv per roster (combined)
    top25 = roster_25[:5]
    top250 = roster_250[:5]
    rows = []
    for c in top25 + top250:
        rows.append({
            "sleeve_id": c["sleeve_id"],
            "roster": c["roster"],
            "anchor": c["offset_label"],
            "gate_stack": "&".join(c["gates"]),
            "n_train": c.get("train_n", 0),
            "n_val": c.get("val_n", 0),
            "n_lockbox": c.get("lockbox_n", 0),
            "wr_train": round(c.get("train_wr", 0), 4),
            "wr_val": round(c.get("val_wr", 0), 4),
            "wr_lockbox": round(c.get("lockbox_wr", 0), 4),
            "dpt_25": round(c.get("lockbox_dpt_25", 0), 3),
            "sum_25_lockbox": round(c.get("lockbox_sum_25", 0), 2),
            "max_dd_25": round(c.get("lockbox_dd_25", 0), 2),
            "loss_streak": c.get("lockbox_loss_streak", 0),
            "sharpe": round(c.get("lockbox_sharpe", 0), 3),
            "bootstrap_p_lockbox": round(c.get("bootstrap_p_lockbox", 1), 4),
        })
    pd.DataFrame(rows).to_csv(f"{RES_DIR}/top_5_candidates.csv", index=False)

    # Also emit near-miss CSV
    nm_rows = []
    for c in (nm_25 + nm_250)[:30]:
        nm_rows.append({
            "sleeve_id": c["sleeve_id"],
            "roster": c["roster"],
            "n_lockbox": c.get("lockbox_n", 0),
            "wr_lockbox": round(c.get("lockbox_wr", 0), 4),
            "dpt_25_lockbox": round(c.get("lockbox_dpt_25", 0), 3),
            "dd_25_lockbox": round(c.get("lockbox_dd_25", 0), 2),
            "loss_streak": c.get("lockbox_loss_streak", 0),
            "sharpe": round(c.get("lockbox_sharpe", 0), 3),
            "boot_p": round(c.get("bootstrap_p_lockbox", 1), 4),
            "gate_stack": "&".join(c["gates"]),
        })
    pd.DataFrame(nm_rows).to_csv(f"{RES_DIR}/near_misses.csv", index=False)

    # Save full state for downstream report-builder
    state = dict(
        days=df["day"].nunique(),
        train_days=sorted([str(d) for d in train_days]),
        val_days=sorted([str(d) for d in val_days]),
        lockbox_days=sorted([str(d) for d in lockbox_days]),
        n_atoms=len(primary_atoms),
        atoms=primary_atoms,
        n_candidates_total=len(all_candidates),
        n_candidates_250=len(book_candidates),
        n_pass_25=len(roster_25),
        n_pass_250=len(roster_250),
        n_near_miss_25=len(nm_25),
        n_near_miss_250=len(nm_250),
    )
    with open(f"{RES_DIR}/search_state.json", "w") as f:
        json.dump(state, f, indent=2, default=str)
    print(f"\nwrote: {RES_DIR}/top_5_candidates.csv")
    print(f"       {RES_DIR}/near_misses.csv")
    print(f"       {RES_DIR}/all_candidates.csv")
    print(f"       {RES_DIR}/search_state.json")

if __name__ == "__main__":
    main()
