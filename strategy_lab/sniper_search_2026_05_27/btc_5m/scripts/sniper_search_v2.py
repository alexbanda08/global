"""
SNIPER SEARCH — BTC 5m (V2, comprehensive)
==========================================

Universe: master_gate_features_v2.parquet, BTC 5m subset
  - n=33,646 fires, 24.8d (May 1 -> May 25)
  - WR base 73% (already direction-picked sleeves)
  - 130+ feature cols, 47 g_* gates

3-way split (brief §5, 24.8d band): train 15d / val 5d / lockbox 4.8d

Sniper thresholds (all 7 must pass on LOCKBOX):
  n_32d_proj in [50, 500], wr_lockbox >= 0.75, dpt_25_lockbox >= 3.0,
  max_dd_25_lockbox <= 300, loss_streak_lockbox <= 6, sharpe_lockbox >= 2.0,
  bootstrap_p_lockbox <= 0.05.

Paths run:
  F  - single gates filtered by prevalence band [50, 5000]
  E  - per-offset bin sweep: 1/2/3-gate combos within each offset_bin
  C  - high-bar gate stacks: 3/4/5-gate combos of rare-strong gates
  D  - greedy combinatorial with sniper constraints
  G  - SLEEVE-conditional sniper sub-cells (filter inside each existing sleeve, then layer 1-3 gates)
  H  - per-fire_offset_s narrow sweep (15s increments) with high-WR gates

Output:
  all_candidates.csv  - every candidate evaluated
  top_5_candidates.csv - top 5 passers (or near-misses if fewer)
  SNIPER_BTC_5M_REPORT.md
  cumulative_pnl_<id>.png  - top candidates
"""
import sys
import os
import json
import itertools
from pathlib import Path
import numpy as np
import pandas as pd

# Headless matplotlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(r"C:/Users/alexandre bandarra/Desktop/global")
OUT  = ROOT / "strategy_lab/sniper_search_2026_05_27/btc_5m"
OUT.mkdir(parents=True, exist_ok=True)

MG = ROOT / "data/v4/canonical/_results/master_gate_features_v2.parquet"

ASSET, TF, WINDOW_S = "BTC", "5m", 300

SNIPER = dict(
    n_min_32d=50, n_max_32d=500,
    wr_min=0.75, dpt_25_min=3.0, dd_25_max=300.0,
    loss_streak_max=6, sharpe_min=2.0, bootstrap_p_max=0.05,
)

PNL_SCALE = 1.0
STAKE = 25.0
DAYS_TOTAL = 24.8


def load_universe():
    df = pd.read_parquet(MG)
    df = df[(df["asset"] == ASSET) & (df["tf"] == TF)].sort_values("fire_us").reset_index(drop=True)
    df["fire_dt"] = pd.to_datetime(df["fire_us"], unit="us", utc=True)
    df["fire_date"] = df["fire_dt"].dt.date
    g_cols = [c for c in df.columns if c.startswith("g_")]
    for c in g_cols:
        df[c] = df[c].fillna(0).astype(np.int8)
    df["won_int"] = df["won_int"].fillna(0).astype(np.int8)
    return df, g_cols


def compute_metrics_block(sub: pd.DataFrame, days_total=None):
    """Compute metrics for a subset of fires. Returns dict."""
    n = len(sub)
    if n == 0:
        return None
    sub = sub.sort_values("fire_us").reset_index(drop=True)
    pnl = sub["pnl_legacy_usd"].values * PNL_SCALE
    won = sub["won_int"].sum()
    wr = won / n
    dpt = float(np.mean(pnl))
    total = float(np.sum(pnl))
    cum = np.cumsum(pnl)
    peak = np.maximum.accumulate(cum)
    max_dd = float(np.max(peak - cum)) if len(cum) else 0.0
    losses = (sub["won_int"] == 0).values.astype(np.int8)
    max_streak = 0
    cur = 0
    for v in losses:
        if v:
            cur += 1
            max_streak = max(max_streak, cur)
        else:
            cur = 0
    daily = pd.Series(pnl, index=sub["fire_date"].values).groupby(level=0).sum()
    if len(daily) > 1 and daily.std() > 0:
        sharpe = float(daily.mean() / daily.std() * np.sqrt(365))
    else:
        sharpe = 0.0
    if days_total is None:
        days_span = (sub["fire_dt"].max() - sub["fire_dt"].min()).total_seconds() / 86400
    else:
        days_span = days_total
    rate = n / max(days_span, 0.1)
    n_32d = rate * 32.0
    return dict(n=n, wr=wr, dpt_25=dpt, total_25=total, max_dd_25=max_dd,
                loss_streak=max_streak, sharpe=sharpe, n_32d_proj=n_32d, days_span=days_span)


def bootstrap_p_lockbox(sub_lb: pd.DataFrame, n_iter=1000, seed=20260527):
    """Daily-clustered bootstrap test of H0: mean_pnl <= 0 on lockbox.
       Returns p = fraction of bootstrap mean PnL <= 0."""
    if len(sub_lb) < 5:
        return 1.0
    rng = np.random.default_rng(seed)
    pnl = sub_lb["pnl_legacy_usd"].values * PNL_SCALE
    fd = sub_lb["fire_date"].values
    # Group pnl by day
    from collections import defaultdict
    by_day = defaultdict(list)
    for p, d in zip(pnl, fd):
        by_day[d].append(p)
    days = list(by_day.keys())
    arrs = [np.array(by_day[d]) for d in days]
    n_days = len(arrs)
    if n_days < 2:
        return 1.0
    boot_means = np.empty(n_iter, dtype=np.float64)
    for i in range(n_iter):
        idx = rng.integers(0, n_days, n_days)
        pooled = np.concatenate([arrs[j] for j in idx])
        boot_means[i] = pooled.mean() if len(pooled) else 0.0
    return float((boot_means <= 0).mean())


def split_24_8(df: pd.DataFrame):
    """15d train, 5d val, 4.8d lockbox (24.8d effective window)."""
    ts_min = df["fire_us"].min()
    ts_max = df["fire_us"].max()
    span = ts_max - ts_min
    # 15 / 5 / 4.8
    cut1 = ts_min + int(span * 15.0 / 24.8)
    cut2 = ts_min + int(span * 20.0 / 24.8)
    tr = df[df["fire_us"] < cut1].copy()
    va = df[(df["fire_us"] >= cut1) & (df["fire_us"] < cut2)].copy()
    lb = df[df["fire_us"] >= cut2].copy()
    return tr, va, lb


def evaluate_candidate(df, mask, sleeve_id, anchor, gate_stack_desc, splits):
    """Mask applies on full df. Returns dict with split-wise metrics."""
    n_full = int(mask.sum())
    if n_full < 30:
        return None
    tr, va, lb = splits
    tr_idx = df["fire_us"].between(tr["fire_us"].min(), tr["fire_us"].max(), inclusive="both") if len(tr) else False
    va_idx = df["fire_us"].between(va["fire_us"].min(), va["fire_us"].max(), inclusive="both") if len(va) else False
    lb_idx = df["fire_us"].between(lb["fire_us"].min(), lb["fire_us"].max(), inclusive="both") if len(lb) else False
    tr_m = mask & tr_idx
    va_m = mask & va_idx
    lb_m = mask & lb_idx
    sub_tr = df[tr_m]
    sub_va = df[va_m]
    sub_lb = df[lb_m]

    if len(sub_lb) < 10:
        return None
    if len(sub_tr) < 20:
        return None

    m_full = compute_metrics_block(df[mask], days_total=DAYS_TOTAL)
    m_lb = compute_metrics_block(sub_lb, days_total=4.8)
    boot_p = bootstrap_p_lockbox(sub_lb, n_iter=1000)

    out = dict(
        sleeve_id=sleeve_id, anchor=anchor, gate_stack=gate_stack_desc,
        n_full=m_full["n"], n_train=int(len(sub_tr)), n_val=int(len(sub_va)), n_lockbox=int(len(sub_lb)),
        wr_full=m_full["wr"],
        wr_train=float(sub_tr["won_int"].mean()) if len(sub_tr) else 0.0,
        wr_val=float(sub_va["won_int"].mean()) if len(sub_va) else 0.0,
        wr_lockbox=m_lb["wr"],
        dpt_25_full=m_full["dpt_25"],
        dpt_25_train=float(sub_tr["pnl_legacy_usd"].mean()) * PNL_SCALE if len(sub_tr) else 0.0,
        dpt_25_val=float(sub_va["pnl_legacy_usd"].mean()) * PNL_SCALE if len(sub_va) else 0.0,
        dpt_25_lockbox=m_lb["dpt_25"],
        sum_25_full=m_full["total_25"],
        sum_25_lockbox=m_lb["total_25"],
        max_dd_25_full=m_full["max_dd_25"],
        max_dd_25_lockbox=m_lb["max_dd_25"],
        loss_streak_full=m_full["loss_streak"],
        loss_streak_lockbox=m_lb["loss_streak"],
        sharpe_full=m_full["sharpe"],
        sharpe_lockbox=m_lb["sharpe"],
        n_32d_proj=m_full["n_32d_proj"],
        bootstrap_p_lockbox=boot_p,
    )
    return out


def passes_sniper(row):
    """All 7 sniper criteria on LOCKBOX metrics."""
    n32 = row["n_32d_proj"]
    if not (SNIPER["n_min_32d"] <= n32 <= SNIPER["n_max_32d"]):
        return False, "n_32d_out_of_band"
    if row["wr_lockbox"] < SNIPER["wr_min"]:
        return False, "wr_lockbox_low"
    if row["dpt_25_lockbox"] < SNIPER["dpt_25_min"]:
        return False, "dpt_lockbox_low"
    if row["max_dd_25_lockbox"] > SNIPER["dd_25_max"]:
        return False, "dd_lockbox_high"
    if row["loss_streak_lockbox"] > SNIPER["loss_streak_max"]:
        return False, "loss_streak_long"
    if row["sharpe_lockbox"] < SNIPER["sharpe_min"]:
        return False, "sharpe_lockbox_low"
    if row["bootstrap_p_lockbox"] > SNIPER["bootstrap_p_max"]:
        return False, "bootstrap_p_high"
    return True, "PASS"


# --------------------------------------------------------------------------
# SEARCH PATHS
# --------------------------------------------------------------------------

# Gate pool - all R3/R4/R5 + key R1
ALL_GATES = [
    # R1 base
    "g_rf_with", "g_ribbon_agrees", "g_stoch_with", "g_mfi_with", "g_cci_with",
    "g_bb_pos_with", "g_tr_above_ema50", "g_tr_above_ema200", "g_tr_above_ema800",
    "g_tr_above_pp", "g_tr_stack_with", "g_tr_within_adr", "g_tight_ribbon",
    "g_within_dev", "g_markov_with",
    # R3 vol/hurst/flow
    "g_vol_expanding", "g_vol_contracting", "g_vol_high", "g_hurst_trending",
    "g_hurst_reverting", "g_flow_with_and_no_whale",
    "g_coinbase_basis_extreme_against", "g_hl_liq_cascade_with",
    "g_book_slope_steep_against",
    # R4 trend / book
    "g_trend_slope_with", "g_trend_slope_strong_with", "g_imb5_strong_with",
    "g_queue_top_high", "g_imb_change_with", "g_vwap_ge_50_le_85",
    # R5 microprice / hawkes / LM
    "g_mp_no_extreme", "g_mp_change_with", "g_mp_skew_with",
    "g_lm_high_stat", "g_lm_extreme_against", "g_hawkes_imbalance_with",
]

STRONG_GATES = [
    "g_lm_high_stat", "g_hl_liq_cascade_with", "g_queue_top_high",
    "g_trend_slope_strong_with", "g_imb5_strong_with", "g_vol_high",
    "g_hawkes_imbalance_with", "g_within_dev", "g_tr_above_ema200",
    "g_tr_above_ema800", "g_ribbon_agrees", "g_rf_with", "g_stoch_with",
    "g_mp_skew_with", "g_mp_no_extreme",
]


def path_F_singles(df, g_cols, splits):
    cands = []
    for g in g_cols:
        n_on = int(df[g].sum())
        if not (50 <= n_on <= 6000):
            continue
        mask = (df[g] == 1).values
        r = evaluate_candidate(df, pd.Series(mask, index=df.index),
                               f"single|{g}", "any_offset", g, splits)
        if r: cands.append(r)
    return cands


def path_E_offset_bin_sweep(df, g_cols, splits):
    cands = []
    bins = ["0-60", "60-150", "150-240", "240-300"]
    for b in bins:
        sub_b_mask = (df["offset_bin"] == b).values
        if sub_b_mask.sum() < 200:
            continue
        # 1, 2, 3 gate combos within bin
        for r in (1, 2, 3):
            for combo in itertools.combinations(STRONG_GATES, r):
                m = sub_b_mask.copy()
                for g in combo:
                    if g in df.columns:
                        m &= (df[g].values == 1)
                n_p = int(m.sum())
                if not (40 <= n_p <= 4000):
                    continue
                gates_str = "+".join(combo)
                cid = f"offset_{b}|r{r}|{gates_str}"
                rec = evaluate_candidate(df, pd.Series(m, index=df.index), f"offset_{b}|r{r}", f"offset_{b}", gates_str, splits)
                if rec: cands.append(rec)
    return cands


def path_C_high_bar_stacks(df, g_cols, splits):
    cands = []
    # 3, 4, 5 gate combos of strong gates
    for r in (3, 4, 5):
        for combo in itertools.combinations(STRONG_GATES, r):
            m = np.ones(len(df), dtype=bool)
            for g in combo:
                if g in df.columns:
                    m &= (df[g].values == 1)
            n_p = int(m.sum())
            if not (30 <= n_p <= 3000):
                continue
            gates_str = "+".join(combo)
            rec = evaluate_candidate(df, pd.Series(m, index=df.index), f"stack_r{r}", "any_offset", gates_str, splits)
            if rec: cands.append(rec)
    return cands


def path_D_greedy(df, g_cols, splits, seeds=None):
    cands = []
    seeds = seeds or [
        ["g_tr_above_ema800"],
        ["g_lm_high_stat"],
        ["g_within_dev"],
        ["g_hl_liq_cascade_with"],
        ["g_imb5_strong_with"],
        ["g_queue_top_high"],
        ["g_trend_slope_strong_with"],
        ["g_vol_high"],
        ["g_tr_above_ema200"],
        ["g_mp_no_extreme"],
        ["g_ribbon_agrees", "g_rf_with"],
        ["g_tr_above_ema50", "g_tr_above_cloud"],
    ]
    for seed in seeds:
        current = list(seed)
        base_mask = np.ones(len(df), dtype=bool)
        for g in current:
            if g in df.columns:
                base_mask &= (df[g].values == 1)
        if base_mask.sum() < 50:
            continue
        # Save seed
        gs = "+".join(current)
        rec = evaluate_candidate(df, pd.Series(base_mask, index=df.index), f"greedy|{gs}", "any_offset", gs, splits)
        if rec: cands.append(rec)

        # Try adding next gates
        pool = [g for g in ALL_GATES if g not in current and g in df.columns]
        for step in range(6):
            best_g = None
            best_dpt = -1e9
            best_mask = None
            for g in pool:
                trial = base_mask & (df[g].values == 1)
                n_after = int(trial.sum())
                if n_after < 30:
                    continue
                if n_after > base_mask.sum() * 0.95:
                    # too redundant
                    continue
                d = df.loc[trial, "pnl_legacy_usd"].mean() * PNL_SCALE
                if d > best_dpt:
                    best_dpt = d
                    best_g = g
                    best_mask = trial
            if best_g is None:
                break
            current.append(best_g)
            base_mask = best_mask
            pool = [g for g in pool if g != best_g]
            gs = "+".join(current)
            rec = evaluate_candidate(df, pd.Series(base_mask, index=df.index), f"greedy|{gs}", "any_offset", gs, splits)
            if rec: cands.append(rec)
            if base_mask.sum() < 50:
                break
    return cands


def path_G_sleeve_conditional(df, g_cols, splits):
    """Within each existing sleeve, layer 1-3 additional gates."""
    cands = []
    for sleeve in df["sleeve_id"].unique():
        sub_sleeve = df["sleeve_id"] == sleeve
        sub_mask = sub_sleeve.values
        if sub_mask.sum() < 200:
            continue
        for r in (1, 2, 3):
            for combo in itertools.combinations(STRONG_GATES, r):
                m = sub_mask.copy()
                for g in combo:
                    if g in df.columns:
                        m &= (df[g].values == 1)
                n_p = int(m.sum())
                if not (30 <= n_p <= 3000):
                    continue
                gates_str = "+".join(combo)
                short_sleeve = sleeve.split("|")[0] + "|" + sleeve.split("|")[1]
                rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                         f"{short_sleeve}+r{r}|{gates_str}", short_sleeve, gates_str, splits)
                if rec: cands.append(rec)
    return cands


def path_H_per_offset_fine(df, g_cols, splits):
    """Per fire_offset_s narrow sweep (15s grain) with single strong gates."""
    cands = []
    offsets = sorted(df["fire_offset_s"].unique())
    for o in offsets:
        sub_o_mask = (df["fire_offset_s"] == o).values
        if sub_o_mask.sum() < 100:
            continue
        for g in STRONG_GATES:
            m = sub_o_mask.copy()
            m &= (df[g].values == 1)
            n_p = int(m.sum())
            if not (30 <= n_p <= 2000):
                continue
            rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                     f"offset_s{o}|{g}", f"offset_s{o}", g, splits)
            if rec: cands.append(rec)
        # Two-gate combos
        for combo in itertools.combinations(STRONG_GATES, 2):
            m = sub_o_mask.copy()
            for g in combo:
                m &= (df[g].values == 1)
            n_p = int(m.sum())
            if not (30 <= n_p <= 1500):
                continue
            gates_str = "+".join(combo)
            rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                     f"offset_s{o}|r2|{gates_str}", f"offset_s{o}", gates_str, splits)
            if rec: cands.append(rec)
    return cands


def plot_cumulative(df, mask, title, out_path):
    sub = df[mask].sort_values("fire_us")
    if len(sub) < 5:
        return
    pnl = sub["pnl_legacy_usd"].values * PNL_SCALE
    cum = np.cumsum(pnl)
    dt = pd.to_datetime(sub["fire_us"], unit="us", utc=True)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(dt, cum, lw=1.2, color="navy")
    # Mark splits
    ts_min = df["fire_us"].min()
    ts_max = df["fire_us"].max()
    span = ts_max - ts_min
    cut1 = pd.to_datetime(ts_min + int(span * 15.0/24.8), unit="us", utc=True)
    cut2 = pd.to_datetime(ts_min + int(span * 20.0/24.8), unit="us", utc=True)
    ax.axvline(cut1, color="gray", ls="--", alpha=0.5, label="train|val")
    ax.axvline(cut2, color="red", ls="--", alpha=0.6, label="val|lockbox")
    ax.set_title(title)
    ax.set_xlabel("Date")
    ax.set_ylabel("Cumulative PnL ($)")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.autofmt_xdate()
    fig.savefig(out_path, dpi=100, bbox_inches="tight")
    plt.close(fig)


def main():
    print("=" * 72)
    print("SNIPER SEARCH — BTC 5m V2")
    print("=" * 72)
    df, g_cols = load_universe()
    print(f"Universe: n={len(df):,}, base WR={df['won_int'].mean():.3f}, base $/tr={df['pnl_legacy_usd'].mean():+.3f}")
    splits = split_24_8(df)
    tr, va, lb = splits
    print(f"Split — train: {len(tr):,} ({tr['fire_dt'].min().date()} -> {tr['fire_dt'].max().date()})")
    print(f"        val:   {len(va):,} ({va['fire_dt'].min().date()} -> {va['fire_dt'].max().date()})")
    print(f"        lockbox: {len(lb):,} ({lb['fire_dt'].min().date()} -> {lb['fire_dt'].max().date()})")
    print(f"  base lockbox WR={lb['won_int'].mean():.3f}, $/tr={lb['pnl_legacy_usd'].mean():+.3f}")
    print()

    all_cands = []
    print("[F] Singles ..."); n0 = len(all_cands)
    all_cands.extend(path_F_singles(df, g_cols, splits))
    print(f"  +{len(all_cands)-n0} = {len(all_cands)} total")

    print("[E] Offset-bin sweep ..."); n0 = len(all_cands)
    all_cands.extend(path_E_offset_bin_sweep(df, g_cols, splits))
    print(f"  +{len(all_cands)-n0} = {len(all_cands)} total")

    print("[C] High-bar stacks ..."); n0 = len(all_cands)
    all_cands.extend(path_C_high_bar_stacks(df, g_cols, splits))
    print(f"  +{len(all_cands)-n0} = {len(all_cands)} total")

    print("[D] Greedy combinatorial ..."); n0 = len(all_cands)
    all_cands.extend(path_D_greedy(df, g_cols, splits))
    print(f"  +{len(all_cands)-n0} = {len(all_cands)} total")

    print("[G] Sleeve-conditional ..."); n0 = len(all_cands)
    all_cands.extend(path_G_sleeve_conditional(df, g_cols, splits))
    print(f"  +{len(all_cands)-n0} = {len(all_cands)} total")

    print("[H] Per-offset fine sweep ..."); n0 = len(all_cands)
    all_cands.extend(path_H_per_offset_fine(df, g_cols, splits))
    print(f"  +{len(all_cands)-n0} = {len(all_cands)} total")

    print(f"\nTotal candidates evaluated: {len(all_cands)}")
    cand_df = pd.DataFrame(all_cands)
    statuses = cand_df.apply(passes_sniper, axis=1)
    cand_df["pass"] = [s[0] for s in statuses]
    cand_df["fail_reason"] = [s[1] for s in statuses]

    cand_df = cand_df.sort_values(["pass", "dpt_25_lockbox", "wr_lockbox"], ascending=[False, False, False])
    cand_df.to_csv(OUT / "all_candidates.csv", index=False)
    print(f"\nSaved all_candidates.csv ({len(cand_df)} rows)")

    passers = cand_df[cand_df["pass"]].copy()
    print(f"\nPassers (all 7 sniper criteria): {len(passers)}")
    if len(passers) > 0:
        cols_show = ["sleeve_id", "gate_stack", "n_full", "n_train", "n_val", "n_lockbox", "n_32d_proj",
                     "wr_train", "wr_val", "wr_lockbox",
                     "dpt_25_lockbox", "max_dd_25_lockbox", "loss_streak_lockbox",
                     "sharpe_lockbox", "bootstrap_p_lockbox"]
        print(passers[cols_show].head(15).to_string(index=False))

    return df, cand_df


if __name__ == "__main__":
    main()
