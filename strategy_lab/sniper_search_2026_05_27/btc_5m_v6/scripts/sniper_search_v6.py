"""
SNIPER SEARCH V6 — BTC 5m (Kelly sizing + early/pre-window entries + composable gates)
=====================================================================================

Universe: master_gate_features_v2.parquet, BTC 5m subset (33,646 fires, May 1 → May 25)

V6 changes vs V5:
  - Loss streak ≤ 14 OK if $/tr compensates
  - Drop $250 testing entirely. Max stake $25, min $5 (Kelly-driven).
  - Pre-window signal anchor: use microprice at offset=15 (proxy for ws_s−ε) joined to fires at offset∈{30,60}.
  - Early-fire offsets {30, 45, 60} prioritized.
  - Conviction buckets via Option B (empirical WR per # extra gates passing).
  - Kelly-25 fractional stake from p,b: stake ∈ [$5, $25].
  - Primary objective: lockbox_dpt × sqrt(lockbox_n), tiebreaker DD then loss_streak.

Search paths:
  P1_prewindow — gates at ws_s anchor (mp_skew/mp_skew_change_500ms/f7_rsi_at_ws) + early fire offsets
  P2_early_offset — restrict to offset∈{30,45,60} and run composable gate stacks
  P3_combined — pre-window gate + early-offset filter + R4/R5 master gates
  P4_compare_late — same gate stacks at offset∈{120,150,180,210,240} for comparison

Output:
  all_candidates_v6.csv — every candidate evaluated (with conviction & kelly cols)
  top_5_candidates_v6.csv
  kelly_stake_table_{sleeve_id}.csv — per top sleeve
  SNIPER_BTC_5M_V6_REPORT.md
  cumulative_pnl_kelly_vs_const_{sleeve_id}.png — top candidates
"""
import sys
import os
import io
import json
import itertools
from pathlib import Path
import numpy as np
import pandas as pd

# Force UTF-8 stdout on Windows for unicode-safe printing
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
except Exception:
    pass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(r"C:/Users/alexandre bandarra/Desktop/global")
OUT = ROOT / "strategy_lab/sniper_search_2026_05_27/btc_5m_v6"
OUT.mkdir(parents=True, exist_ok=True)

MG_PATH = ROOT / "data/v4/canonical/_results/master_gate_features_v2.parquet"
MP_PATH = ROOT / "data/v4/canonical/_results/microprice_panel.parquet"

ASSET, TF, WINDOW_S = "BTC", "5m", 300

# V6 sniper bar
V6 = dict(
    n_min_28d=30, n_max_28d=2000,
    wr_min=0.65,
    dpt_25_min=4.0,
    dd_25_max=500.0,
    loss_streak_max=14,
    sharpe_min=1.5,
    bootstrap_p_max=0.05,
)

STAKE_MIN = 5.0
STAKE_MAX = 25.0
KELLY_FRAC = 0.25
PNL_SCALE = 1.0  # master_gate already at $25 stake
DAYS_TOTAL = 24.8

# Gate pool from master gate features
ALL_GATES = [
    "g_rf_with","g_ribbon_agrees","g_stoch_with","g_mfi_with","g_cci_with",
    "g_bb_pos_with","g_tr_above_ema50","g_tr_above_ema200","g_tr_above_ema800",
    "g_tr_above_pp","g_tr_stack_with","g_tr_within_adr","g_tight_ribbon",
    "g_within_dev","g_dev_extreme","g_markov_with",
    "g_vol_expanding","g_vol_contracting","g_vol_high","g_hurst_trending","g_hurst_reverting",
    "g_book_slope_steep_against","g_trend_slope_with","g_trend_slope_strong_with",
    "g_imb5_strong_with","g_queue_top_high","g_imb_change_with","g_vwap_ge_50_le_85",
    "g_mp_no_extreme","g_mp_change_with","g_mp_skew_with",
    "g_lm_high_stat","g_lm_extreme_against","g_hawkes_imbalance_with",
    "g_flow_with_and_no_whale","g_coinbase_basis_extreme_against","g_hl_liq_cascade_with",
]

# V6 strong gate library — the "atoms" that compose into stacks
STRONG_GATES = [
    "g_trend_slope_strong_with","g_mp_no_extreme","g_mp_skew_with","g_mp_change_with",
    "g_imb5_strong_with","g_queue_top_high","g_hawkes_imbalance_with",
    "g_within_dev","g_dev_extreme",
    "g_tr_above_ema200","g_tr_above_ema800","g_ribbon_agrees","g_rf_with",
    "g_lm_high_stat","g_hl_liq_cascade_with","g_vol_high","g_markov_with",
    "g_hurst_trending",
]


def load_universe():
    print("Loading master_gate_features_v2 BTC 5m ...")
    mg = pd.read_parquet(MG_PATH)
    df = mg[(mg["asset"] == ASSET) & (mg["tf"] == TF)].copy()
    df = df.sort_values("fire_us").reset_index(drop=True)
    df["fire_dt"] = pd.to_datetime(df["fire_us"], unit="us", utc=True)
    df["fire_date"] = df["fire_dt"].dt.date
    g_cols = [c for c in df.columns if c.startswith("g_")]
    for c in g_cols:
        df[c] = df[c].fillna(0).astype(np.int8)
    df["won_int"] = df["won_int"].fillna(0).astype(np.int8)
    print(f"  rows={len(df):,}, WR_base={df['won_int'].mean():.4f}, dpt_25_base=${df['pnl_legacy_usd'].mean():+.3f}")
    print(f"  offsets={sorted(df['fire_offset_s'].unique())}")
    print(f"  dates {df['fire_dt'].min().date()} -> {df['fire_dt'].max().date()}")
    return df, g_cols


def build_prewindow_features(df):
    """Join microprice features computed at the EARLIEST offset for each slug
    as a proxy for pre-window signal. Anchor offset = min available for that slug,
    which is typically offset=15. The fire still HAPPENS at its native fire_offset_s.
    """
    print("\nLoading microprice_panel for pre-window features ...")
    mp = pd.read_parquet(MP_PATH)
    mp_b = mp[(mp["asset"] == ASSET) & (mp["tf"] == TF)].copy()

    # Per slug, find earliest offset and use those microprice values as "pre-window"
    mp_b = mp_b.sort_values(["slug", "fire_offset_s"])
    earliest = mp_b.groupby("slug", as_index=False).first()[
        ["slug", "fire_offset_s", "mp_skew", "mp_skew_500ms", "mp_skew_change_500ms",
         "mp_up_dev_bps", "mp_dn_dev_bps", "mp_up_dev_change_500ms", "mp_dn_dev_change_500ms",
         "mp_weighted_skew", "mp_imbalance"]
    ].rename(columns={
        "fire_offset_s": "pw_anchor_offset_s",
        "mp_skew": "pw_mp_skew",
        "mp_skew_500ms": "pw_mp_skew_500ms",
        "mp_skew_change_500ms": "pw_mp_skew_change_500ms",
        "mp_up_dev_bps": "pw_mp_up_dev_bps",
        "mp_dn_dev_bps": "pw_mp_dn_dev_bps",
        "mp_up_dev_change_500ms": "pw_mp_up_dev_change_500ms",
        "mp_dn_dev_change_500ms": "pw_mp_dn_dev_change_500ms",
        "mp_weighted_skew": "pw_mp_weighted_skew",
        "mp_imbalance": "pw_mp_imbalance",
    })
    print(f"  earliest-offset table: {len(earliest):,} unique slugs, anchor offset modal = {earliest['pw_anchor_offset_s'].mode().iloc[0]}")
    print(f"  pre-window anchor offset distribution: {earliest['pw_anchor_offset_s'].value_counts().head(5).to_dict()}")

    df = df.merge(earliest, on="slug", how="left")
    print(f"  joined: {df['pw_mp_skew'].notna().mean():.4f} coverage on pw_mp_skew")

    # Direction-aware pre-window gates
    # dir_sign: +1 UP, -1 DOWN
    pw_skew_with = ((df["pw_mp_skew"] * df["dir_sign"]) > 0).astype(np.int8)
    df["g_pw_mp_skew_with"] = pw_skew_with

    pw_change_with = ((df["pw_mp_skew_change_500ms"] * df["dir_sign"]) > 0).astype(np.int8)
    df["g_pw_mp_change_with"] = pw_change_with

    # Pre-window microprice not extreme (tradability proxy at ws_s anchor)
    df["g_pw_mp_no_extreme"] = (
        (df["pw_mp_up_dev_bps"].abs() < 150) & (df["pw_mp_dn_dev_bps"].abs() < 150)
    ).fillna(False).astype(np.int8)

    # F7 RSI extreme gate at ws_s
    rsi = df["f7_rsi_at_ws"]
    f7_extreme_up = (rsi > 70) & (df["dir_sign"] == 1)
    f7_extreme_dn = (rsi < 30) & (df["dir_sign"] == -1)
    df["g_f7_rsi_extreme_with"] = (f7_extreme_up | f7_extreme_dn).fillna(False).astype(np.int8)

    f7_strong_up = (rsi > 60) & (df["dir_sign"] == 1)
    f7_strong_dn = (rsi < 40) & (df["dir_sign"] == -1)
    df["g_f7_rsi_strong_with"] = (f7_strong_up | f7_strong_dn).fillna(False).astype(np.int8)

    f7_neutral = (rsi >= 40) & (rsi <= 60)
    df["g_f7_rsi_neutral"] = f7_neutral.fillna(False).astype(np.int8)

    # Reverse: F7 RSI mean-reversion gate (overbought + DOWN signal or oversold + UP signal)
    f7_rev_up = (rsi < 30) & (df["dir_sign"] == 1)
    f7_rev_dn = (rsi > 70) & (df["dir_sign"] == -1)
    df["g_f7_rsi_reversion"] = (f7_rev_up | f7_rev_dn).fillna(False).astype(np.int8)

    print(f"  g_pw_mp_skew_with on rate: {df['g_pw_mp_skew_with'].mean():.4f}")
    print(f"  g_pw_mp_no_extreme on rate: {df['g_pw_mp_no_extreme'].mean():.4f}")
    print(f"  g_f7_rsi_strong_with on rate: {df['g_f7_rsi_strong_with'].mean():.4f}")
    return df


def split_28d(df: pd.DataFrame):
    """15d train / 5d val / 4.8d lockbox (24.8d effective)."""
    ts_min = df["fire_us"].min()
    ts_max = df["fire_us"].max()
    span = ts_max - ts_min
    cut1 = ts_min + int(span * 15.0 / 24.8)
    cut2 = ts_min + int(span * 20.0 / 24.8)
    tr = df[df["fire_us"] < cut1].copy()
    va = df[(df["fire_us"] >= cut1) & (df["fire_us"] < cut2)].copy()
    lb = df[df["fire_us"] >= cut2].copy()
    return tr, va, lb


def kelly_stake(p, vwap, frac=KELLY_FRAC):
    """Kelly-fraction stake clamped to [STAKE_MIN, STAKE_MAX]."""
    if not (0 < p < 1) or not (0 < vwap < 1):
        return STAKE_MIN
    b = (1 - vwap) * 0.98 / vwap
    if b <= 0:
        return STAKE_MIN
    f_full = (p * b - (1 - p)) / b
    if f_full <= 0:
        return STAKE_MIN
    f = frac * f_full
    stake = float(np.clip(f * STAKE_MAX, STAKE_MIN, STAKE_MAX))
    return stake


def compute_metrics(sub, days_total=None):
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
    n_28d = rate * 28.0
    return dict(n=n, wr=wr, dpt_25=dpt, total_25=total, max_dd_25=max_dd,
                loss_streak=max_streak, sharpe=sharpe, n_28d_proj=n_28d, days_span=days_span)


def bootstrap_p(sub, n_iter=1000, seed=20260527):
    if len(sub) < 5:
        return 1.0
    rng = np.random.default_rng(seed)
    pnl = sub["pnl_legacy_usd"].values * PNL_SCALE
    fd = sub["fire_date"].values
    from collections import defaultdict
    by_day = defaultdict(list)
    for p, d in zip(pnl, fd):
        by_day[d].append(p)
    arrs = [np.array(by_day[d]) for d in by_day]
    n_days = len(arrs)
    if n_days < 2:
        return 1.0
    boot = np.empty(n_iter, dtype=np.float64)
    for i in range(n_iter):
        idx = rng.integers(0, n_days, n_days)
        pooled = np.concatenate([arrs[j] for j in idx])
        boot[i] = pooled.mean() if len(pooled) else 0.0
    return float((boot <= 0).mean())


def evaluate_candidate(df, mask, sleeve_id, anchor, gate_stack, splits, extra_gates_for_conviction=None):
    """Evaluate a gate mask. Returns dict with metrics and Kelly stats."""
    n_full = int(mask.sum())
    if n_full < 30:
        return None
    tr, va, lb = splits
    tr_ts_min = tr["fire_us"].min() if len(tr) else 0
    tr_ts_max = tr["fire_us"].max() if len(tr) else 0
    va_ts_min = va["fire_us"].min() if len(va) else 0
    va_ts_max = va["fire_us"].max() if len(va) else 0
    lb_ts_min = lb["fire_us"].min() if len(lb) else 0
    lb_ts_max = lb["fire_us"].max() if len(lb) else 0

    fus = df["fire_us"].values
    tr_idx = (fus >= tr_ts_min) & (fus <= tr_ts_max)
    va_idx = (fus >= va_ts_min) & (fus <= va_ts_max)
    lb_idx = (fus >= lb_ts_min) & (fus <= lb_ts_max)
    m = mask.values if isinstance(mask, pd.Series) else mask
    sub_tr = df[m & tr_idx]
    sub_va = df[m & va_idx]
    sub_lb = df[m & lb_idx]

    if len(sub_lb) < 10 or len(sub_tr) < 20:
        return None

    m_full = compute_metrics(df[m], days_total=DAYS_TOTAL)
    m_lb = compute_metrics(sub_lb, days_total=4.8)
    boot = bootstrap_p(sub_lb, 1000)

    out = dict(
        sleeve_id=sleeve_id, anchor=anchor, gate_stack=gate_stack,
        n_full=m_full["n"], n_train=int(len(sub_tr)),
        n_val=int(len(sub_va)), n_lockbox=int(len(sub_lb)),
        wr_train=float(sub_tr["won_int"].mean()) if len(sub_tr) else 0.0,
        wr_val=float(sub_va["won_int"].mean()) if len(sub_va) else 0.0,
        wr_lockbox=m_lb["wr"],
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
        n_28d_proj=m_full["n_28d_proj"],
        bootstrap_p_lockbox=boot,
    )
    # Sharpe-flavored objective
    out["objective"] = out["dpt_25_lockbox"] * np.sqrt(max(out["n_lockbox"], 1))
    return out


def passes_v6(row):
    n28 = row["n_28d_proj"]
    if not (V6["n_min_28d"] <= n28 <= V6["n_max_28d"]):
        return False, "n_28d_out_of_band"
    if row["wr_lockbox"] < V6["wr_min"]:
        return False, "wr_lockbox_low"
    if row["dpt_25_lockbox"] < V6["dpt_25_min"]:
        return False, "dpt_lockbox_low"
    if row["max_dd_25_lockbox"] > V6["dd_25_max"]:
        return False, "dd_lockbox_high"
    if row["loss_streak_lockbox"] > V6["loss_streak_max"]:
        return False, "loss_streak_long"
    if row["sharpe_lockbox"] < V6["sharpe_min"]:
        return False, "sharpe_lockbox_low"
    if row["bootstrap_p_lockbox"] > V6["bootstrap_p_max"]:
        return False, "bootstrap_p_high"
    return True, "PASS"


# --------------------------------------------------------------------------
# SEARCH PATHS
# --------------------------------------------------------------------------

PREWINDOW_GATES = [
    "g_pw_mp_skew_with", "g_pw_mp_change_with", "g_pw_mp_no_extreme",
    "g_f7_rsi_strong_with", "g_f7_rsi_neutral", "g_f7_rsi_extreme_with",
]


def path_P1_prewindow(df, splits):
    """Search using pre-window gates as PRIMARY filters. Compose with up to 2 master gates."""
    cands = []
    PW_PRIMARY = ["g_pw_mp_skew_with", "g_pw_mp_no_extreme", "g_pw_mp_change_with",
                  "g_f7_rsi_strong_with", "g_f7_rsi_neutral"]
    for pw1 in PW_PRIMARY:
        if pw1 not in df.columns:
            continue
        m_pw = (df[pw1].values == 1)
        if m_pw.sum() < 100:
            continue
        # 0 extra gates (just PW)
        rec = evaluate_candidate(df, pd.Series(m_pw, index=df.index),
                                 f"prewindow|{pw1}", "ws_s", pw1, splits)
        if rec: cands.append(rec)

        # 1 extra master gate
        for g in STRONG_GATES:
            if g in df.columns:
                m = m_pw & (df[g].values == 1)
                if m.sum() < 50:
                    continue
                gs = f"{pw1}+{g}"
                rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                         f"prewindow|{gs}", "ws_s", gs, splits)
                if rec: cands.append(rec)

        # 2 extra master gates
        for combo in itertools.combinations(STRONG_GATES, 2):
            m = m_pw.copy()
            for g in combo:
                if g in df.columns:
                    m &= (df[g].values == 1)
            if m.sum() < 30:
                continue
            gs = f"{pw1}+{'+'.join(combo)}"
            rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                     f"prewindow|{gs}", "ws_s", gs, splits)
            if rec: cands.append(rec)
    return cands


def path_P2_early_offset(df, splits):
    """Restrict to offset∈{30, 45, 60} and run composable stacks."""
    cands = []
    for off_bin_name, off_set in [("early30", [30]), ("early45", [45]),
                                   ("early60", [60]), ("early3060", [30, 60]),
                                   ("early304560", [30, 45, 60])]:
        m_off = df["fire_offset_s"].isin(off_set).values
        if m_off.sum() < 200:
            continue
        # Single strong gate
        for g in STRONG_GATES:
            if g in df.columns:
                m = m_off & (df[g].values == 1)
                if m.sum() < 50:
                    continue
                rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                         f"off_{off_bin_name}|{g}",
                                         f"offset_{off_bin_name}", g, splits)
                if rec: cands.append(rec)
        # 2-gate
        for combo in itertools.combinations(STRONG_GATES, 2):
            m = m_off.copy()
            for g in combo:
                if g in df.columns:
                    m &= (df[g].values == 1)
            if m.sum() < 40:
                continue
            gs = "+".join(combo)
            rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                     f"off_{off_bin_name}|r2|{gs}",
                                     f"offset_{off_bin_name}", gs, splits)
            if rec: cands.append(rec)
        # 3-gate
        for combo in itertools.combinations(STRONG_GATES, 3):
            m = m_off.copy()
            for g in combo:
                if g in df.columns:
                    m &= (df[g].values == 1)
            if m.sum() < 30:
                continue
            gs = "+".join(combo)
            rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                     f"off_{off_bin_name}|r3|{gs}",
                                     f"offset_{off_bin_name}", gs, splits)
            if rec: cands.append(rec)
    return cands


def path_P3_combined(df, splits):
    """PW gate × early offset × 1-2 master gates."""
    cands = []
    PW = ["g_pw_mp_skew_with", "g_pw_mp_no_extreme", "g_pw_mp_change_with",
          "g_f7_rsi_strong_with"]
    for off_bin_name, off_set in [("e30", [30]), ("e60", [60]), ("e3060", [30, 60])]:
        m_off = df["fire_offset_s"].isin(off_set).values
        for pw in PW:
            m_pw = m_off & (df[pw].values == 1)
            if m_pw.sum() < 60:
                continue
            # PW only inside offset
            rec = evaluate_candidate(df, pd.Series(m_pw, index=df.index),
                                     f"pw_off_{off_bin_name}|{pw}",
                                     f"ws_s+offset_{off_bin_name}", pw, splits)
            if rec: cands.append(rec)
            # +1 master gate
            for g in STRONG_GATES:
                if g in df.columns:
                    m = m_pw & (df[g].values == 1)
                    if m.sum() < 30:
                        continue
                    gs = f"{pw}+{g}"
                    rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                             f"pw_off_{off_bin_name}|r1|{gs}",
                                             f"ws_s+offset_{off_bin_name}", gs, splits)
                    if rec: cands.append(rec)
            # +2 master gates
            for combo in itertools.combinations(STRONG_GATES, 2):
                m = m_pw.copy()
                for g in combo:
                    if g in df.columns:
                        m &= (df[g].values == 1)
                if m.sum() < 30:
                    continue
                gs = f"{pw}+{'+'.join(combo)}"
                rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                         f"pw_off_{off_bin_name}|r2|{gs}",
                                         f"ws_s+offset_{off_bin_name}", gs, splits)
                if rec: cands.append(rec)
    return cands


def path_P4_late_compare(df, splits):
    """Same composable stacks at LATE offsets — to determine PW/early vs late winner."""
    cands = []
    for off_bin_name, off_set in [("L150", [150]), ("L180", [180]),
                                   ("L210", [210]), ("L240", [240]),
                                   ("L_late", [150, 180, 210, 240])]:
        m_off = df["fire_offset_s"].isin(off_set).values
        if m_off.sum() < 200:
            continue
        for combo in itertools.combinations(STRONG_GATES, 2):
            m = m_off.copy()
            for g in combo:
                if g in df.columns:
                    m &= (df[g].values == 1)
            if m.sum() < 40:
                continue
            gs = "+".join(combo)
            rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                     f"off_{off_bin_name}|r2|{gs}",
                                     f"offset_{off_bin_name}", gs, splits)
            if rec: cands.append(rec)
        for combo in itertools.combinations(STRONG_GATES, 3):
            m = m_off.copy()
            for g in combo:
                if g in df.columns:
                    m &= (df[g].values == 1)
            if m.sum() < 30:
                continue
            gs = "+".join(combo)
            rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                     f"off_{off_bin_name}|r3|{gs}",
                                     f"offset_{off_bin_name}", gs, splits)
            if rec: cands.append(rec)
    return cands


# --------------------------------------------------------------------------
# Conviction bucket + Kelly variable-stake simulation
# --------------------------------------------------------------------------

def build_conviction_buckets(df, base_mask, conviction_gates, splits):
    """For a SURVIVING sleeve (already passing the base mask), partition
    the gated fires by number of EXTRA conviction gates passing.

    Returns: dict per bucket with empirical_p, stake_kelly, n, dpt.
    Empirical p is computed on TRAIN+VAL only (avoid lockbox leak)."""
    tr, va, lb = splits
    # Combine train+val for empirical p estimation
    trva_ts_min = min(tr["fire_us"].min(), va["fire_us"].min()) if len(tr) and len(va) else (tr["fire_us"].min() if len(tr) else 0)
    trva_ts_max = max(tr["fire_us"].max(), va["fire_us"].max()) if len(tr) and len(va) else (tr["fire_us"].max() if len(tr) else 0)
    fus = df["fire_us"].values
    trva_idx = (fus >= trva_ts_min) & (fus <= trva_ts_max)

    sub_trva = df[base_mask & trva_idx].copy()
    sub_lb = df[base_mask & (fus >= lb["fire_us"].min()) & (fus <= lb["fire_us"].max())].copy()

    # Conviction = # of extra gates passing
    n_extra = len([g for g in conviction_gates if g in df.columns])
    if n_extra == 0:
        # only base mask — single bucket
        p_trva = sub_trva["won_int"].mean() if len(sub_trva) else 0.5
        avg_vwap = sub_trva["pnl_legacy_usd"].abs().mean() / 25.0  # rough proxy
        # vwap from won-pnl: for won, pnl = (1-vwap) * shares * 0.98; for lost pnl=-vwap*shares
        # entry_vwap is NOT in master_gate. Use median 0.55 as default.
        vwap_est = 0.55
        stake = kelly_stake(p_trva, vwap_est)
        return {0: dict(n_extra=0, n_trva=len(sub_trva), p_trva=p_trva, vwap_est=vwap_est, stake=stake)}

    # Count extra gates passing per row
    extra_mask_arr = np.zeros(len(df), dtype=np.int16)
    for g in conviction_gates:
        if g in df.columns:
            extra_mask_arr = extra_mask_arr + df[g].values.astype(np.int16)

    sub_trva["n_extra"] = extra_mask_arr[base_mask & trva_idx]
    sub_lb["n_extra"] = extra_mask_arr[base_mask & (fus >= lb["fire_us"].min()) & (fus <= lb["fire_us"].max())]

    buckets = {}
    for k in range(n_extra + 1):
        sub_k = sub_trva[sub_trva["n_extra"] == k]
        sub_k_lb = sub_lb[sub_lb["n_extra"] == k]
        n_k = len(sub_k)
        if n_k < 5:
            continue
        p_k = sub_k["won_int"].mean()
        # vwap estimate per bucket using legacy pnl arithmetic:
        # won: pnl = (1-vwap)*shares*0.98; lost: pnl = -vwap*shares; shares ≈ 25/vwap
        # Avg of won-pnl ≈ 25*(1-vwap)/vwap * 0.98; avg of lost-pnl ≈ -25
        # So vwap ≈ 25*0.98 / (avg_won_pnl + 25*0.98)
        wons = sub_k[sub_k["won_int"] == 1]["pnl_legacy_usd"]
        if len(wons) > 0:
            avg_won = wons.mean()
            vwap_est = (25.0 * 0.98) / (avg_won + 25.0 * 0.98) if (avg_won + 25.0 * 0.98) > 0 else 0.55
            vwap_est = float(np.clip(vwap_est, 0.05, 0.95))
        else:
            vwap_est = 0.55
        stake = kelly_stake(p_k, vwap_est)
        # Also compute LB n and p (for validation)
        n_k_lb = len(sub_k_lb)
        p_k_lb = sub_k_lb["won_int"].mean() if n_k_lb > 0 else 0.0
        dpt_lb_const = sub_k_lb["pnl_legacy_usd"].mean() if n_k_lb > 0 else 0.0
        buckets[k] = dict(
            n_extra=k, n_trva=n_k, p_trva=p_k, vwap_est=vwap_est, stake=stake,
            n_lb=n_k_lb, p_lb=p_k_lb, dpt_25_lb_const=dpt_lb_const,
        )
    return buckets


def simulate_kelly_lockbox(df, base_mask, conviction_gates, buckets, splits):
    """Replay the lockbox PnL using variable Kelly stake. Returns (sum_const, sum_kelly, kelly_pnl_series)."""
    tr, va, lb = splits
    fus = df["fire_us"].values
    lb_idx = (fus >= lb["fire_us"].min()) & (fus <= lb["fire_us"].max())
    sub_lb = df[base_mask & lb_idx].sort_values("fire_us").reset_index(drop=True).copy()
    if len(sub_lb) == 0:
        return 0.0, 0.0, sub_lb

    # Compute n_extra per row
    n_extra = np.zeros(len(sub_lb), dtype=np.int16)
    for g in conviction_gates:
        if g in sub_lb.columns:
            n_extra += sub_lb[g].values.astype(np.int16)
    sub_lb["n_extra"] = n_extra

    # Stake per row from buckets dict (fallback to STAKE_MIN if bucket not seen)
    stakes = np.full(len(sub_lb), STAKE_MIN, dtype=np.float64)
    for k, info in buckets.items():
        stakes[n_extra == k] = info["stake"]
    sub_lb["stake_kelly"] = stakes

    # PnL at variable stake = (legacy_pnl @ $25) × (stake / 25)
    sub_lb["pnl_kelly"] = sub_lb["pnl_legacy_usd"] * (stakes / 25.0)
    sub_lb["pnl_const"] = sub_lb["pnl_legacy_usd"]
    sum_const = float(sub_lb["pnl_const"].sum())
    sum_kelly = float(sub_lb["pnl_kelly"].sum())
    return sum_const, sum_kelly, sub_lb


def plot_kelly_vs_const(sub_lb, sleeve_id, out_path):
    sub_lb = sub_lb.sort_values("fire_us").reset_index(drop=True)
    if len(sub_lb) < 5:
        return
    cum_const = sub_lb["pnl_const"].cumsum().values
    cum_kelly = sub_lb["pnl_kelly"].cumsum().values
    dt = pd.to_datetime(sub_lb["fire_us"], unit="us", utc=True)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(dt, cum_const, lw=1.5, color="navy", label=f"Const $25 (sum=${cum_const[-1]:.0f})")
    ax.plot(dt, cum_kelly, lw=1.5, color="firebrick", label=f"Kelly-25 (sum=${cum_kelly[-1]:.0f})")
    ax.set_title(f"BTC 5m V6 — {sleeve_id}\nLockbox: variable Kelly stake vs constant $25")
    ax.set_xlabel("Date")
    ax.set_ylabel("Cumulative PnL ($)")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.autofmt_xdate()
    fig.savefig(out_path, dpi=100, bbox_inches="tight")
    plt.close(fig)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    print("=" * 72)
    print("SNIPER SEARCH V6 — BTC 5m")
    print("=" * 72)
    df, g_cols = load_universe()
    df = build_prewindow_features(df)
    splits = split_28d(df)
    tr, va, lb = splits
    print(f"\nSplit train={len(tr):,} ({tr['fire_dt'].min().date()} -> {tr['fire_dt'].max().date()})")
    print(f"      val={len(va):,} ({va['fire_dt'].min().date()} -> {va['fire_dt'].max().date()})")
    print(f"      lockbox={len(lb):,} ({lb['fire_dt'].min().date()} -> {lb['fire_dt'].max().date()})")
    print(f"  base lockbox WR={lb['won_int'].mean():.3f} dpt=${lb['pnl_legacy_usd'].mean():+.3f}")

    all_cands = []
    print("\n[P1] Pre-window ..."); n0 = len(all_cands)
    all_cands.extend(path_P1_prewindow(df, splits))
    print(f"  +{len(all_cands)-n0} = {len(all_cands)} total")

    print("[P2] Early offset ..."); n0 = len(all_cands)
    all_cands.extend(path_P2_early_offset(df, splits))
    print(f"  +{len(all_cands)-n0} = {len(all_cands)} total")

    print("[P3] PW × early × master ..."); n0 = len(all_cands)
    all_cands.extend(path_P3_combined(df, splits))
    print(f"  +{len(all_cands)-n0} = {len(all_cands)} total")

    print("[P4] Late offset compare ..."); n0 = len(all_cands)
    all_cands.extend(path_P4_late_compare(df, splits))
    print(f"  +{len(all_cands)-n0} = {len(all_cands)} total")

    print(f"\nTotal candidates: {len(all_cands)}")
    cdf = pd.DataFrame(all_cands)
    statuses = cdf.apply(passes_v6, axis=1)
    cdf["pass"] = [s[0] for s in statuses]
    cdf["fail_reason"] = [s[1] for s in statuses]
    cdf = cdf.sort_values(["pass", "objective", "dpt_25_lockbox"], ascending=[False, False, False])
    cdf.to_csv(OUT / "all_candidates_v6.csv", index=False)
    print(f"Wrote all_candidates_v6.csv ({len(cdf)} rows)")

    passers = cdf[cdf["pass"]].copy()
    print(f"\nPassers (all 7 V6 criteria): {len(passers)}")
    if len(passers) > 0:
        cols = ["sleeve_id", "anchor", "gate_stack", "n_lockbox", "n_28d_proj",
                "wr_lockbox", "dpt_25_lockbox", "max_dd_25_lockbox",
                "loss_streak_lockbox", "sharpe_lockbox", "bootstrap_p_lockbox",
                "objective"]
        print(passers[cols].head(30).to_string(index=False))

    # Cache the universe for Kelly stage (use df with PW features)
    df.to_parquet(OUT / "_sandbox/universe_with_pw.parquet")
    print(f"\nCached universe to {OUT / '_sandbox/universe_with_pw.parquet'}")
    return df, cdf, splits


if __name__ == "__main__":
    main()
