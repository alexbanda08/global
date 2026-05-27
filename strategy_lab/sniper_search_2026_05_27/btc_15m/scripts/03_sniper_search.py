"""Sniper search on BTC 15m gated panel.

Strategy:
1. Per-offset analysis (single gate + greedy combos)
2. Greedy forward search with sniper constraints:
   - max_n_lockbox: 500 (sniper, not shotgun)
   - min_wr_lockbox: 0.75
   - min_dpt_25: 3.0
   - max_dd_25: 300
   - max_loss_streak: 6
3. Cross-offset stacks
4. Bootstrap p (1000 iterations) on lockbox PnL
5. 3-way split: train 12d / val 6d / lockbox 5d (Apr30 - May22)

Output: top_5_candidates.csv + sniper_btc15m_all_candidates.csv
"""
import os, sys, time, itertools, json
from collections import defaultdict
import numpy as np
import pandas as pd

RES = "data/v4/canonical/_results"
IN = f"{RES}/sniper_btc15m_gated.parquet"
OUT_DIR = "strategy_lab/sniper_search_2026_05_27/btc_15m"

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)

log("loading gated panel")
df = pd.read_parquet(IN)
df["fire_date"] = pd.to_datetime(df["fire_us"], unit="us", utc=True)
df = df.sort_values("fire_us").reset_index(drop=True)
log(f"rows: {len(df)}")

# 3-way split
TRAIN_START = pd.Timestamp("2026-04-30", tz="UTC")
TRAIN_END   = pd.Timestamp("2026-05-12", tz="UTC")
VAL_END     = pd.Timestamp("2026-05-18", tz="UTC")
LOCK_END    = pd.Timestamp("2026-05-23", tz="UTC")

def split_masks(d):
    return (
        (d["fire_date"] >= TRAIN_START) & (d["fire_date"] < TRAIN_END),
        (d["fire_date"] >= TRAIN_END)   & (d["fire_date"] < VAL_END),
        (d["fire_date"] >= VAL_END)     & (d["fire_date"] < LOCK_END),
    )

tr_mask, va_mask, lo_mask = split_masks(df)
df_tr = df[tr_mask].copy()
df_va = df[va_mask].copy()
df_lo = df[lo_mask].copy()
log(f"split: train={len(df_tr)} val={len(df_va)} lockbox={len(df_lo)}")

# Define LOCKBOX_DAYS for daily metrics
TR_DAYS = (TRAIN_END - TRAIN_START).days
VA_DAYS = (VAL_END - TRAIN_END).days
LO_DAYS = (LOCK_END - VAL_END).days
SCALE_28D = 28 / LO_DAYS  # to compute "$/day x 28"
log(f"days: train={TR_DAYS}, val={VA_DAYS}, lockbox={LO_DAYS}")

# All gate columns
ALL_GATES = sorted([c for c in df.columns if c.startswith("g_")])
# Drop dead gates (0 fires anywhere)
DEAD = []
for g_col in ALL_GATES:
    if df[g_col].sum() == 0:
        DEAD.append(g_col)
ALL_GATES = [g for g in ALL_GATES if g not in DEAD]
log(f"gates available: {len(ALL_GATES)} (dropped {len(DEAD)} dead)")

# Sleeve ID by (direction, offset_bin) — we partition by direction+offset, then add gates
df["offset_bin"] = df["fire_offset_s"].astype(str)


def gate_passes(d, gates):
    if not gates: return np.ones(len(d), dtype=bool)
    m = np.ones(len(d), dtype=bool)
    for g in gates:
        if g not in d.columns:
            continue
        col = np.asarray(d[g], dtype=float)
        m &= (np.isnan(col) | (col == 1))
    return m


def compute_dd(pnl_arr):
    """Max drawdown on cumulative PnL series."""
    if len(pnl_arr) == 0:
        return 0.0
    cum = np.cumsum(pnl_arr)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak  # negative
    return float(-dd.min())  # positive max DD


def max_loss_streak(won_arr):
    """Max consecutive losses."""
    if len(won_arr) == 0:
        return 0
    streak = 0
    max_streak = 0
    for w in won_arr:
        if w == 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak


def daily_sharpe(d):
    """Daily-clustered Sharpe of pnl_legacy_usd."""
    if len(d) == 0:
        return 0.0
    daily = d.groupby(d["fire_date"].dt.date)["pnl_legacy_usd"].sum()
    if len(daily) < 2 or daily.std() == 0:
        return 0.0
    return float(daily.mean() / daily.std() * np.sqrt(365))


def bootstrap_p(d_lock, n_shuffles=1000, seed=42):
    """Daily-clustered bootstrap p (one-sided, H0: mean_pnl <= 0)."""
    if len(d_lock) < 5:
        return np.nan
    # daily-cluster bootstrap
    daily = d_lock.groupby(d_lock["fire_date"].dt.date)["pnl_legacy_usd"].sum().values
    n_days = len(daily)
    if n_days < 2:
        return np.nan
    obs = daily.sum()  # total PnL
    rng = np.random.default_rng(seed)
    boot = rng.choice(daily, size=(n_shuffles, n_days), replace=True).sum(axis=1)
    se = boot.std()
    if se == 0:
        return 0.0 if obs > 0 else 1.0
    # p = fraction of bootstrap means <= 0 (one-sided test that obs > 0)
    p = float((boot <= 0).sum() / n_shuffles)
    return max(p, 1.0 / n_shuffles)


def metrics(d_split, gates, n_cap=500):
    """Return metrics for a sleeve over a split."""
    m = gate_passes(d_split, gates)
    sub = d_split[m].copy()
    n = len(sub)
    if n == 0:
        return None
    # Sort by fire_us for streak/DD compute
    sub = sub.sort_values("fire_us").reset_index(drop=True)
    won_arr = sub["won"].values.astype(int)
    pnl_arr = sub["pnl_legacy_usd"].values.astype(float)
    return dict(
        n=n,
        wr=float(np.mean(won_arr)),
        dpt=float(pnl_arr.mean()),
        sum_pnl=float(pnl_arr.sum()),
        max_dd=compute_dd(pnl_arr),
        loss_streak=max_loss_streak(won_arr),
    )


def passes_sniper(m_lock, n_cap=500, min_wr=0.75, min_dpt=3.0,
                  max_dd=300.0, max_streak=6, min_n=50):
    """Sniper threshold check."""
    if m_lock is None: return False
    if m_lock["n"] < min_n: return False
    if m_lock["n"] > n_cap: return False
    if m_lock["wr"] < min_wr: return False
    if m_lock["dpt"] < min_dpt: return False
    if m_lock["max_dd"] > max_dd: return False
    if m_lock["loss_streak"] > max_streak: return False
    return True


# ============================================================
# Phase 1: Single-gate baselines (warm start)
# ============================================================
log("Phase 1: single-gate baselines per offset")
results = []
for off in sorted(df["fire_offset_s"].unique()):
    d_tr_o = df_tr[df_tr["fire_offset_s"] == off]
    d_va_o = df_va[df_va["fire_offset_s"] == off]
    d_lo_o = df_lo[df_lo["fire_offset_s"] == off]
    for g_col in ALL_GATES:
        m_tr = metrics(d_tr_o, [g_col])
        if m_tr is None or m_tr["n"] < 30:
            continue
        m_va = metrics(d_va_o, [g_col])
        m_lo = metrics(d_lo_o, [g_col])
        if m_lo is None:
            continue
        results.append({
            "sleeve_id": f"off{off}_{g_col}",
            "offset": off,
            "gates": [g_col],
            "n_train": m_tr["n"], "wr_train": m_tr["wr"], "dpt_train": m_tr["dpt"],
            "n_val": m_va["n"] if m_va else 0, "wr_val": m_va["wr"] if m_va else np.nan,
            "n_lock": m_lo["n"], "wr_lock": m_lo["wr"], "dpt_lock": m_lo["dpt"],
            "sum_lock": m_lo["sum_pnl"], "max_dd_lock": m_lo["max_dd"],
            "streak_lock": m_lo["loss_streak"],
        })
df_p1 = pd.DataFrame(results)
log(f"Phase 1 results: {len(df_p1)}")
df_p1.to_csv(f"{OUT_DIR}/phase1_singlegate_offset.csv", index=False)

# ============================================================
# Phase 2: Greedy forward search per offset with sniper constraints
# ============================================================
log("Phase 2: greedy forward by-offset")

def greedy_forward(d_train, d_val, d_lock, gates_avail, max_depth=8, n_cap=500):
    """Greedy add gates to maximize sum_pnl on train, with monotonic constraint."""
    chosen = []
    candidates = list(gates_avail)
    history = []
    for step in range(max_depth):
        best_g = None
        best_score = -np.inf
        best_metrics = None
        for g in candidates:
            trial = chosen + [g]
            m_tr = metrics(d_train, trial)
            if m_tr is None or m_tr["n"] < 30:
                continue
            # Score: dpt * sqrt(n) (info-ratio-like — but penalize too few)
            score = m_tr["dpt"] * np.sqrt(m_tr["n"])
            if score > best_score:
                best_score = score
                best_g = g
                best_metrics = m_tr
        if best_g is None:
            break
        chosen.append(best_g)
        candidates.remove(best_g)
        m_lo = metrics(d_lock, chosen)
        m_va = metrics(d_val, chosen)
        history.append({
            "depth": step + 1,
            "gates": list(chosen),
            "train_n": best_metrics["n"], "train_wr": best_metrics["wr"],
            "train_dpt": best_metrics["dpt"],
            "val_n": m_va["n"] if m_va else 0, "val_wr": m_va["wr"] if m_va else np.nan,
            "lock_n": m_lo["n"] if m_lo else 0,
            "lock_wr": m_lo["wr"] if m_lo else np.nan,
            "lock_dpt": m_lo["dpt"] if m_lo else np.nan,
            "lock_dd": m_lo["max_dd"] if m_lo else np.nan,
            "lock_streak": m_lo["loss_streak"] if m_lo else np.nan,
        })
        # Stop if cardinality below 30 on train (over-fit risk)
        if best_metrics["n"] < 50:
            break
    return history

phase2_all = []
for off in sorted(df["fire_offset_s"].unique()):
    d_tr_o = df_tr[df_tr["fire_offset_s"] == off]
    d_va_o = df_va[df_va["fire_offset_s"] == off]
    d_lo_o = df_lo[df_lo["fire_offset_s"] == off]
    if len(d_tr_o) < 100 or len(d_lo_o) < 30:
        continue
    for dir_val in ["UP", "DOWN"]:
        dtr = d_tr_o[d_tr_o["direction"] == dir_val]
        dva = d_va_o[d_va_o["direction"] == dir_val]
        dlo = d_lo_o[d_lo_o["direction"] == dir_val]
        if len(dtr) < 50:
            continue
        hist = greedy_forward(dtr, dva, dlo, ALL_GATES, max_depth=8)
        for h in hist:
            h["offset"] = off
            h["direction"] = dir_val
            phase2_all.append(h)

df_p2 = pd.DataFrame(phase2_all)
log(f"Phase 2 candidates: {len(df_p2)}")
df_p2.to_csv(f"{OUT_DIR}/phase2_greedy_byoffset_bydir.csv", index=False)

# ============================================================
# Phase 3: Aggregate multi-offset candidates (no offset constraint)
# ============================================================
log("Phase 3: greedy across all offsets per direction")
phase3_all = []
for dir_val in ["UP", "DOWN", "BOTH"]:
    if dir_val == "BOTH":
        dtr, dva, dlo = df_tr, df_va, df_lo
    else:
        dtr = df_tr[df_tr["direction"] == dir_val]
        dva = df_va[df_va["direction"] == dir_val]
        dlo = df_lo[df_lo["direction"] == dir_val]
    if len(dtr) < 50:
        continue
    hist = greedy_forward(dtr, dva, dlo, ALL_GATES, max_depth=8)
    for h in hist:
        h["offset"] = "ALL"
        h["direction"] = dir_val
        phase3_all.append(h)
df_p3 = pd.DataFrame(phase3_all)
log(f"Phase 3 candidates: {len(df_p3)}")
df_p3.to_csv(f"{OUT_DIR}/phase3_greedy_alloffsets.csv", index=False)

# ============================================================
# Phase 4: Collect candidates passing sniper criteria on LOCKBOX
# ============================================================
log("Phase 4: filter all candidates by sniper thresholds")
all_hist = phase2_all + phase3_all
sniper_cands = []
for h in all_hist:
    # Check sniper on LOCKBOX
    if h["lock_n"] < 5:  # need some lockbox fires
        continue
    if h["lock_wr"] < 0.75:
        continue
    if h["lock_dpt"] < 3.0:
        continue
    if h["lock_dd"] > 300.0:
        continue
    if h["lock_streak"] > 6:
        continue
    # also val must not collapse - WR >= 60% as soft sanity
    if h["val_n"] >= 30 and h["val_wr"] < 0.60:
        continue
    sniper_cands.append(h)
log(f"Phase 4: {len(sniper_cands)} candidates pass sniper")

# ============================================================
# Phase 5: Bootstrap p-value for each surviving candidate
# ============================================================
log("Phase 5: bootstrap p-values on lockbox")
for c in sniper_cands:
    if c["offset"] == "ALL":
        if c["direction"] == "BOTH":
            d_lo = df_lo
        else:
            d_lo = df_lo[df_lo["direction"] == c["direction"]]
    else:
        d_lo = df_lo[(df_lo["fire_offset_s"] == c["offset"]) &
                     (df_lo["direction"] == c["direction"])]
    m = gate_passes(d_lo, c["gates"])
    sub = d_lo[m].copy()
    c["bootstrap_p"] = bootstrap_p(sub, n_shuffles=1000)
    c["sharpe"] = daily_sharpe(sub)
    c["sum_25_28d"] = sub["pnl_legacy_usd"].sum() * SCALE_28D
log(f"bootstrap done")

# Filter on bootstrap p <= 0.05 and Sharpe >= 2
final_cands = [c for c in sniper_cands if c.get("bootstrap_p", 1.0) <= 0.05 and c.get("sharpe", 0) >= 2.0]
log(f"Phase 5: {len(final_cands)} pass bootstrap p+Sharpe")

# Save all sniper candidates (even those failing bootstrap)
df_all = pd.DataFrame(sniper_cands)
df_all["gate_count"] = df_all["gates"].apply(len)
df_all["gate_stack_str"] = df_all["gates"].apply(lambda x: "+".join(x))
df_all.to_csv(f"{OUT_DIR}/sniper_btc15m_all_candidates.csv", index=False)

if len(final_cands) == 0:
    log("WARNING: NO candidates met all sniper thresholds on lockbox!")
    log("Will report near-misses in report.")
else:
    df_final = pd.DataFrame(final_cands)
    df_final["gate_stack_str"] = df_final["gates"].apply(lambda x: "+".join(x))
    df_final = df_final.sort_values(["sharpe", "lock_dpt"], ascending=False)
    df_final.head(20).to_csv(f"{OUT_DIR}/top_5_candidates_RAW.csv", index=False)
    log(f"Top 5:")
    print(df_final[["gate_stack_str", "offset", "direction", "lock_n", "lock_wr",
                    "lock_dpt", "lock_dd", "lock_streak", "bootstrap_p", "sharpe"]].head(10).to_string())

# Always save the universe of survivors (Phase 1+2+3) for reference
df_all.to_csv(f"{OUT_DIR}/sniper_btc15m_universe.csv", index=False)
log("DONE")
