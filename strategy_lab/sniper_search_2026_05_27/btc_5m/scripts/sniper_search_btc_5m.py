"""
SNIPER SEARCH — BTC 5m
======================
Mission: find n=50-500/32d sleeves with WR>=75%, $/tr>=$3, DD<=$300, loss streak<=6, Sharpe>=2.0,
bootstrap p<=0.05 on lockbox.

Universe: data/v4/canonical/_results/master_gate_features_v2.parquet
  (filtered to BTC 5m: 33,646 fires over 24.8d)

Approach paths tested:
  A. Pre-window proxy: use existing offset bins (0-60 ≈ early) with high-bar gates
  B. Beginning of window: 0-60s offset, mine R6 LL finding (BTC S6 + 12 gates -> WR 79.9%, $/tr 8.03, n=219)
  C. High-bar gate stacks: stack the rare/strong gates
  D. Master combinatorial under sniper n_cap
  E. Per-offset bin sweep

Validation:
  - Time-based chronological split: 15d train / 5d val / 5d lockbox
  - Bootstrap p: 1000-iter daily-clustered on lockbox PnL
  - All 7 thresholds must pass on LOCKBOX (not train)
  - DD uses sleeve's actual gated fires, $25 stake
  - Fee model: legacy 2%-on-profit (matches production)

Output:
  - top_5_candidates.csv
  - SNIPER_BTC_5M_REPORT.md
  - cumulative_pnl_{candidate_id}.png (top candidates)
"""

import sys
import json
import itertools
from pathlib import Path

import numpy as np
import pandas as pd

# -------------------------------------------------------------------- paths
ROOT = Path(r"C:/Users/alexandre bandarra/Desktop/global")
OUT = ROOT / "strategy_lab/sniper_search_2026_05_27/btc_5m"
OUT.mkdir(parents=True, exist_ok=True)

MASTER = ROOT / "data/v4/canonical/_results/master_gate_features_v2.parquet"

# -------------------------------------------------------------------- config
ASSET = "BTC"
TF = "5m"
WINDOW_S = 300

# Sniper thresholds (must pass ALL on lockbox)
SNIPER = dict(
    n_min_32d=50,
    n_max_32d=500,
    wr_min=0.75,
    dpt_25_min=3.0,
    dd_25_max=300.0,
    loss_streak_max=6,
    sharpe_min=2.0,
    bootstrap_p_max=0.05,
)

STAKE = 25.0  # $25 per trade (informational only — pnl_legacy_usd already at $25 stake)
FEE_LEGACY = 0.02  # 2% on winning leg only
# IMPORTANT: pnl_legacy_usd in master_gate_features_v2 is ALREADY at $25 stake
# (verified: lost trades = -$25 flat). Do NOT multiply by stake again.
PNL_SCALE = 1.0  # pnl_legacy_usd is already at $25 stake

RNG = np.random.default_rng(20260527)


# -------------------------------------------------------------------- helpers
def load_universe():
    df = pd.read_parquet(MASTER)
    df = df[(df["asset"] == ASSET) & (df["tf"] == TF)].copy()
    df = df.sort_values("fire_us").reset_index(drop=True)
    df["fire_dt"] = pd.to_datetime(df["fire_us"], unit="us", utc=True)
    df["fire_date"] = df["fire_dt"].dt.date
    # Coerce ints
    g_cols = [c for c in df.columns if c.startswith("g_")]
    for c in g_cols:
        df[c] = df[c].fillna(0).astype(int)
    df["won_int"] = df["won_int"].fillna(0).astype(int)
    # pnl at $25 stake (legacy: 2% on profit only)
    # if won: stake * (1 - entry_vwap) * 0.98 — but we don't have entry_vwap in master_gate_features
    # use pnl_legacy_usd which is at $1 stake (or similar); scale to $25
    # Verify pnl_legacy_usd is at $1 (then 25x for $25 stake)
    return df, g_cols


def legacy_pnl_25(row):
    """Legacy fee model: 2% on profit only. Need entry vwap to compute."""
    # Without entry_vwap here, we just scale pnl_legacy_usd by 25.
    return None


def compute_metrics(sub: pd.DataFrame, stake=STAKE, days_total=24.8):
    """Compute all sniper metrics for a filtered sleeve subset."""
    n = len(sub)
    if n == 0:
        return None

    sub = sub.sort_values("fire_us").reset_index(drop=True)
    # pnl_legacy_usd is already at $25 stake (verified — lost trades exactly -$25)
    pnl_25 = sub["pnl_legacy_usd"].values * PNL_SCALE
    wins = sub["won_int"].sum()
    wr = wins / n
    dpt = float(np.mean(pnl_25))
    total = float(np.sum(pnl_25))

    # Cumulative + drawdown
    cum = np.cumsum(pnl_25)
    peak = np.maximum.accumulate(cum)
    dd_series = peak - cum
    max_dd = float(np.max(dd_series)) if len(dd_series) else 0.0

    # Loss streak
    losses = (sub["won_int"] == 0).values.astype(int)
    max_streak = 0
    cur = 0
    for v in losses:
        if v:
            cur += 1
            if cur > max_streak:
                max_streak = cur
        else:
            cur = 0

    # Sharpe (daily approx): group by date
    sub_d = sub.copy()
    sub_d["pnl_25"] = pnl_25
    daily = sub_d.groupby("fire_date")["pnl_25"].sum()
    if len(daily) > 1 and daily.std() > 0:
        sharpe = float(daily.mean() / daily.std() * np.sqrt(365))
    else:
        sharpe = 0.0

    # Project n to 32d
    days_span = (sub["fire_dt"].max() - sub["fire_dt"].min()).total_seconds() / 86400
    rate = n / max(days_span, 0.1)
    n_32d = rate * 32.0

    return dict(
        n=n,
        wr=wr,
        dpt_25=dpt,
        total_25=total,
        max_dd_25=max_dd,
        loss_streak=max_streak,
        sharpe=sharpe,
        n_32d_proj=n_32d,
        days_span=days_span,
    )


def bootstrap_p_lockbox(sub_lb: pd.DataFrame, n_iter=1000, seed=42):
    """Daily-clustered bootstrap on lockbox PnL. p = P(mean_25 <= 0) under resampled days."""
    if len(sub_lb) < 5:
        return 1.0
    rng = np.random.default_rng(seed)
    sub_lb = sub_lb.copy()
    sub_lb["pnl_25"] = sub_lb["pnl_legacy_usd"].values * PNL_SCALE
    daily = sub_lb.groupby("fire_date")
    by_day_arrays = [g["pnl_25"].values for _, g in daily]
    n_days = len(by_day_arrays)
    if n_days < 2:
        return 1.0
    boot_means = np.zeros(n_iter)
    for i in range(n_iter):
        idx = rng.integers(0, n_days, n_days)
        pooled = np.concatenate([by_day_arrays[j] for j in idx])
        boot_means[i] = pooled.mean() if len(pooled) else 0.0
    # one-sided test: H0 mean<=0 ; p = fraction <= 0
    p = (boot_means <= 0).mean()
    return float(p)


def split_train_val_lockbox(df: pd.DataFrame, ratios=(15, 5, 5)):
    """Time-based chronological split."""
    ts_min = df["fire_us"].min()
    ts_max = df["fire_us"].max()
    span = ts_max - ts_min
    total = sum(ratios)
    cut1 = ts_min + int(span * ratios[0] / total)
    cut2 = ts_min + int(span * (ratios[0] + ratios[1]) / total)
    train = df[df["fire_us"] < cut1].copy()
    val = df[(df["fire_us"] >= cut1) & (df["fire_us"] < cut2)].copy()
    lockbox = df[df["fire_us"] >= cut2].copy()
    return train, val, lockbox


def evaluate_candidate(df, mask, sleeve_id, anchor, gate_stack_desc, splits=None):
    """Full evaluation of a sleeve. Returns dict with all metrics, or None if too few."""
    sub = df[mask]
    if len(sub) < 20:
        return None
    m_full = compute_metrics(sub)
    if m_full is None:
        return None

    # train/val/lockbox metrics
    if splits is None:
        train, val, lockbox = split_train_val_lockbox(df)
    else:
        train, val, lockbox = splits

    train_mask = mask & df["fire_us"].between(train["fire_us"].min(), train["fire_us"].max(), inclusive="both")
    val_mask = mask & df["fire_us"].between(val["fire_us"].min(), val["fire_us"].max(), inclusive="both")
    lb_mask = mask & df["fire_us"].between(lockbox["fire_us"].min(), lockbox["fire_us"].max(), inclusive="both")

    sub_tr = df[train_mask]
    sub_va = df[val_mask]
    sub_lb = df[lb_mask]

    m_lb = compute_metrics(sub_lb)

    boot_p = bootstrap_p_lockbox(sub_lb) if len(sub_lb) >= 10 else 1.0

    out = dict(
        sleeve_id=sleeve_id,
        anchor=anchor,
        gate_stack=gate_stack_desc,
        n_full=m_full["n"],
        n_train=len(sub_tr),
        n_val=len(sub_va),
        n_lockbox=len(sub_lb),
        wr_full=m_full["wr"],
        wr_train=sub_tr["won_int"].mean() if len(sub_tr) else 0.0,
        wr_val=sub_va["won_int"].mean() if len(sub_va) else 0.0,
        wr_lockbox=m_lb["wr"] if m_lb else 0.0,
        dpt_25_full=m_full["dpt_25"],
        dpt_25_train=(sub_tr["pnl_legacy_usd"].mean() * PNL_SCALE) if len(sub_tr) else 0.0,
        dpt_25_val=(sub_va["pnl_legacy_usd"].mean() * PNL_SCALE) if len(sub_va) else 0.0,
        dpt_25_lockbox=m_lb["dpt_25"] if m_lb else 0.0,
        sum_25_full=m_full["total_25"],
        sum_25_lockbox=m_lb["total_25"] if m_lb else 0.0,
        max_dd_25_full=m_full["max_dd_25"],
        max_dd_25_lockbox=m_lb["max_dd_25"] if m_lb else 0.0,
        loss_streak_full=m_full["loss_streak"],
        loss_streak_lockbox=m_lb["loss_streak"] if m_lb else 0,
        sharpe_full=m_full["sharpe"],
        sharpe_lockbox=m_lb["sharpe"] if m_lb else 0.0,
        n_32d_proj=m_full["n_32d_proj"],
        bootstrap_p_lockbox=boot_p,
    )
    return out


def passes_sniper(row):
    """Apply the 7 sniper thresholds against LOCKBOX metrics."""
    n32 = row["n_32d_proj"]
    if not (SNIPER["n_min_32d"] <= n32 <= SNIPER["n_max_32d"]):
        return False, "n_32d_out_of_band"
    if row["wr_lockbox"] < SNIPER["wr_min"]:
        return False, "wr_lockbox_too_low"
    if row["dpt_25_lockbox"] < SNIPER["dpt_25_min"]:
        return False, "dpt_lockbox_too_low"
    if row["max_dd_25_lockbox"] > SNIPER["dd_25_max"]:
        return False, "dd_lockbox_too_high"
    if row["loss_streak_lockbox"] > SNIPER["loss_streak_max"]:
        return False, "loss_streak_lockbox_too_long"
    if row["sharpe_lockbox"] < SNIPER["sharpe_min"]:
        return False, "sharpe_lockbox_too_low"
    if row["bootstrap_p_lockbox"] > SNIPER["bootstrap_p_max"]:
        return False, "bootstrap_p_lockbox_too_high"
    return True, "PASS"


# -------------------------------------------------------------------- search loops
def path_b_re_mine_0_60(df, g_cols, splits):
    """Path B: re-mine BTC S6 0-60s + R1/R3/R4 gates (R6 LL finding context)."""
    sub = df[df["fire_offset_s"] <= 60].copy()
    print(f"[Path B] 0-60s offset slice: n={len(sub)} fires")
    if len(sub) < 100:
        return []

    # Use sleeve_id 's6_5m|0-60|...' as base, layer additional gates
    s6_base = sub[sub["sleeve_id"].str.startswith("s6_5m|0-60")].copy()
    print(f"  s6_5m 0-60 base: n={len(s6_base)} fires")
    s15_base = sub[sub["sleeve_id"].str.startswith("s15_5m|0-60")].copy()
    print(f"  s15_5m 0-60 base: n={len(s15_base)} fires")

    candidates = []
    # Strong-single gates with high WR
    strong_gates = [
        "g_lm_high_stat",
        "g_hl_liq_cascade_with",
        "g_queue_top_high",
        "g_trend_slope_strong_with",
        "g_imb5_strong_with",
        "g_hawkes_imbalance_with",
        "g_vol_high",
        "g_mp_skew_with",
        "g_within_dev",
        "g_tr_above_ema200",
        "g_tr_above_ema800",
        "g_vol_expanding",
        "g_ribbon_agrees",
        "g_rf_with",
        "g_stoch_with",
        "g_bb_pos_with",
    ]
    for base_df, base_name in [(s6_base, "s6_5m|0-60"), (s15_base, "s15_5m|0-60")]:
        if len(base_df) < 100:
            continue
        # Try 1-gate, 2-gate, 3-gate combos
        for r in (1, 2, 3, 4):
            for combo in itertools.combinations(strong_gates, r):
                mask_local = np.ones(len(base_df), dtype=bool)
                for g in combo:
                    if g in base_df.columns:
                        mask_local &= base_df[g].values == 1
                if mask_local.sum() < 30:
                    continue
                # Re-index mask back to full df
                idx = base_df.index[mask_local]
                full_mask = pd.Series(False, index=df.index)
                full_mask.loc[idx] = True
                sleeve_id = f"{base_name}|sniper_B_r{r}"
                gates_str = "+".join(combo)
                res = evaluate_candidate(df, full_mask, sleeve_id, "offset_0_60", gates_str, splits=splits)
                if res:
                    candidates.append(res)
    return candidates


def path_c_high_bar_stacks(df, g_cols, splits):
    """Path C: high-bar 4-6 strict gate stacks (rare gates first)."""
    rare_strong = [
        "g_lm_high_stat",            # 4.8% prev, WR 82.6%, +$10.32
        "g_hl_liq_cascade_with",     # 9.3%, WR 86.8%, +$3.22
        "g_imb5_strong_with",        # 9.0%, WR 75%, +$7.12
        "g_trend_slope_strong_with", # 21.8%, WR 82.4%, +$5.55
        "g_vol_high",                # 20.0%, WR 79.4%, +$2.98
        "g_queue_top_high",          # 23.8%, WR 83.1%, +$3.09
        "g_book_slope_steep_against",# 0.1%, WR 78.7%, +$9.38
        "g_hawkes_imbalance_with",   # 37.5%, WR 83.0%, +$1.64
        "g_within_dev",              # 42.8%, WR 79.8%, +$2.13
        "g_tr_above_ema200",         # 39.5%, WR 82.3%
        "g_ribbon_agrees",
        "g_rf_with",
        "g_stoch_with",
    ]
    candidates = []
    # 2-,3-,4-gate combos
    for r in (2, 3, 4, 5):
        for combo in itertools.combinations(rare_strong, r):
            mask = np.ones(len(df), dtype=bool)
            for g in combo:
                if g in df.columns:
                    mask &= df[g].values == 1
            n_passing = int(mask.sum())
            if n_passing < 30 or n_passing > 4000:  # band of interest
                continue
            sleeve_id = f"all_btc_5m|stack_r{r}"
            gates_str = "+".join(combo)
            res = evaluate_candidate(df, pd.Series(mask, index=df.index), sleeve_id, "any_offset", gates_str, splits=splits)
            if res:
                candidates.append(res)
    return candidates


def path_d_master_combinatorial(df, g_cols, splits, n_cap=500):
    """Path D: greedy combinatorial with sniper constraints (n<=cap)."""
    # Greedy: start with full universe (n=33k), pick next gate that maximizes dpt_lockbox while keeping all sniper constraints
    candidates = []
    # Initial pool of gates with positive lift and reasonable prevalence
    gate_pool = [g for g in g_cols if df[g].sum() > 30 and df[g].sum() < 25000]
    # Sort by single-gate lift
    lifts = []
    for g in gate_pool:
        m = df[g] == 1
        if m.sum() == 0:
            continue
        lift = df[m]["pnl_legacy_usd"].mean() - df["pnl_legacy_usd"].mean()
        lifts.append((g, lift, m.sum()))
    lifts.sort(key=lambda x: -x[1])
    top_gates = [g for g, _, _ in lifts[:18]]
    # Greedy build: add gates one at a time
    current = []
    base_mask = np.ones(len(df), dtype=bool)
    for step in range(8):
        best_g = None
        best_dpt = -1e9
        best_mask = None
        for g in top_gates:
            if g in current:
                continue
            trial = base_mask & (df[g].values == 1)
            n_after = trial.sum()
            if n_after < 30:
                continue
            d = df[trial]["pnl_legacy_usd"].mean() * PNL_SCALE
            if d > best_dpt and n_after >= 30:
                best_dpt = d
                best_g = g
                best_mask = trial
        if best_g is None:
            break
        current.append(best_g)
        base_mask = best_mask
        sleeve_id = f"greedy_step{step+1}"
        gates_str = "+".join(current)
        res = evaluate_candidate(df, pd.Series(base_mask, index=df.index), sleeve_id, "any_offset", gates_str, splits=splits)
        if res:
            candidates.append(res)
        print(f"  greedy step {step+1}: +{best_g} -> n={int(base_mask.sum())}, dpt={best_dpt:.3f}")
        if base_mask.sum() < 50:
            break
    return candidates


def path_e_per_offset_sweep(df, g_cols, splits):
    """Path E: per-offset bin sweep, 2-3 gate combos within each bin."""
    candidates = []
    bins = ["0-60", "60-150", "150-240", "240-300"]
    strong = [
        "g_lm_high_stat",
        "g_hl_liq_cascade_with",
        "g_queue_top_high",
        "g_trend_slope_strong_with",
        "g_imb5_strong_with",
        "g_vol_high",
        "g_hawkes_imbalance_with",
        "g_within_dev",
        "g_tr_above_ema200",
        "g_tr_above_ema800",
        "g_ribbon_agrees",
        "g_rf_with",
        "g_stoch_with",
        "g_mp_skew_with",
    ]
    for b in bins:
        sub_b = df[df["offset_bin"] == b]
        if len(sub_b) < 200:
            continue
        for r in (1, 2, 3):
            for combo in itertools.combinations(strong, r):
                mask = (df["offset_bin"] == b).values
                for g in combo:
                    if g in df.columns:
                        mask &= df[g].values == 1
                n_pass = int(mask.sum())
                if n_pass < 30 or n_pass > 4000:
                    continue
                sleeve_id = f"offset_{b}|r{r}"
                gates_str = "+".join(combo)
                res = evaluate_candidate(df, pd.Series(mask, index=df.index), sleeve_id, f"offset_{b}", gates_str, splits=splits)
                if res:
                    candidates.append(res)
    return candidates


def path_f_singles_filtered(df, g_cols, splits):
    """Path F: any single high-WR rare gate, see if anything stands alone."""
    candidates = []
    for g in g_cols:
        if df[g].sum() == 0 or df[g].sum() > 5000:
            continue
        mask = (df[g] == 1).values
        sleeve_id = f"single|{g}"
        res = evaluate_candidate(df, pd.Series(mask, index=df.index), sleeve_id, "any_offset", g, splits=splits)
        if res:
            candidates.append(res)
    return candidates


# -------------------------------------------------------------------- main
def main():
    print("=" * 70)
    print("SNIPER SEARCH — BTC 5m")
    print("=" * 70)
    df, g_cols = load_universe()
    print(f"Universe: {len(df)} fires, base WR={df['won_int'].mean():.3f}, base $/tr={df['pnl_legacy_usd'].mean()*PNL_SCALE:+.2f}")
    print()

    splits = split_train_val_lockbox(df)
    tr, va, lb = splits
    print(f"Splits — train: {len(tr)} ({tr.iloc[0].fire_dt.date()} -> {tr.iloc[-1].fire_dt.date()})")
    print(f"         val:   {len(va)} ({va.iloc[0].fire_dt.date()} -> {va.iloc[-1].fire_dt.date()})")
    print(f"         lockbox: {len(lb)} ({lb.iloc[0].fire_dt.date()} -> {lb.iloc[-1].fire_dt.date()})")
    print()

    all_cands = []

    print("[Path F] singles ...")
    all_cands.extend(path_f_singles_filtered(df, g_cols, splits))
    print(f"  {len(all_cands)} cands so far")

    print("[Path B] re-mine 0-60s ...")
    new_b = path_b_re_mine_0_60(df, g_cols, splits)
    all_cands.extend(new_b)
    print(f"  +{len(new_b)} = {len(all_cands)}")

    print("[Path C] high-bar gate stacks ...")
    new_c = path_c_high_bar_stacks(df, g_cols, splits)
    all_cands.extend(new_c)
    print(f"  +{len(new_c)} = {len(all_cands)}")

    print("[Path D] master combinatorial greedy ...")
    new_d = path_d_master_combinatorial(df, g_cols, splits)
    all_cands.extend(new_d)
    print(f"  +{len(new_d)} = {len(all_cands)}")

    print("[Path E] per-offset bin sweep ...")
    new_e = path_e_per_offset_sweep(df, g_cols, splits)
    all_cands.extend(new_e)
    print(f"  +{len(new_e)} = {len(all_cands)}")

    print()
    print(f"Total candidates evaluated: {len(all_cands)}")

    if not all_cands:
        print("No candidates found.")
        return

    cand_df = pd.DataFrame(all_cands)
    # Apply sniper screens to lockbox metrics
    statuses = cand_df.apply(passes_sniper, axis=1)
    cand_df["pass"] = [s[0] for s in statuses]
    cand_df["fail_reason"] = [s[1] for s in statuses]

    # Save full grid
    cand_df.to_csv(OUT / "all_candidates.csv", index=False)
    print(f"Saved {len(cand_df)} candidates to all_candidates.csv")

    # Passers
    passers = cand_df[cand_df["pass"]].copy()
    print(f"Passers (all 7 sniper criteria): {len(passers)}")
    if len(passers) > 0:
        passers = passers.sort_values(["dpt_25_lockbox", "wr_lockbox"], ascending=[False, False])
        print(passers[["sleeve_id", "gate_stack", "n_lockbox", "wr_lockbox", "dpt_25_lockbox", "max_dd_25_lockbox", "loss_streak_lockbox", "sharpe_lockbox", "bootstrap_p_lockbox", "n_32d_proj"]].head(10))

    # Top 5 passers (or near-misses if fewer)
    if len(passers) >= 5:
        top = passers.head(5).copy()
    else:
        # take all passers + best near-misses by lockbox dpt
        near_miss = cand_df[~cand_df["pass"]].copy()
        # require at minimum: wr_lockbox >= 0.70 and dpt_lockbox > 0
        near_miss = near_miss[(near_miss["wr_lockbox"] >= 0.70) & (near_miss["dpt_25_lockbox"] > 0)]
        near_miss = near_miss.sort_values(["dpt_25_lockbox", "wr_lockbox"], ascending=[False, False])
        top = pd.concat([passers, near_miss.head(5 - len(passers))], ignore_index=True)

    # Output top 5
    top_cols = [
        "sleeve_id", "anchor", "gate_stack",
        "n_train", "n_val", "n_lockbox", "n_32d_proj",
        "wr_train", "wr_val", "wr_lockbox",
        "dpt_25_train", "dpt_25_val", "dpt_25_lockbox",
        "sum_25_lockbox", "max_dd_25_lockbox", "loss_streak_lockbox",
        "sharpe_lockbox", "bootstrap_p_lockbox",
        "pass", "fail_reason",
    ]
    top[top_cols].to_csv(OUT / "top_5_candidates.csv", index=False)
    print(f"\nTop 5 saved to top_5_candidates.csv")
    print(top[top_cols])


if __name__ == "__main__":
    main()
