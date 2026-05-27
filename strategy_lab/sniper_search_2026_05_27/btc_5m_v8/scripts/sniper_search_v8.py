"""
SNIPER SEARCH V8 — BTC 5m (FULL 32.66d window)
==============================================
V8 paths (per _BRIEF_V8.md):
  J — 2-asset confluence (ETH/SOL trend agrees with BTC direction)
  K — TOD specialization (4 buckets — asia_morning, european_morning, us_afternoon, us_evening)
  L — 1h grandparent regime gate (range_filter_1h)
  M — offset=0 fires (SKIPPED — v8 build not available, only v3 offsets 30..270)
  O — HL gates (funding extreme + liq cascade + OI)
  Q — 5m + 15m cross-tf confluence (parent 15m regime aligns)

Universe: _sniper_btc_5m_enriched.parquet (155,370 rows, 32.66d)
  Includes: g_within_dev, g_dev_extreme, g_rf_*, g_tr_*, g_ribbon_*, g_bb/stoch/mfi/cci,
            g_sms_*, g_trend_slope*, g_mp_*, g_hurst*, g_markov*, g_vol*, g_hawkes*,
            g_lm_*, g_hl_liq_cascade_with, g_within_dev, g_dev_extreme, etc.
Cross-asset panels: regime_panel_5m_v2_fixed (BTC/ETH/SOL, 28d)
HL panels: hyperliquid_funding (BTC, 32+d), hyperliquid_metrics (BTC OI, ~30d)
1h grandparent: range_filter_1h (BTC, 22.1d)

Stake: constant $25
Output:
  all_candidates_v8.csv
  top_5_candidates_v8.csv
  SNIPER_BTC_5M_V8_REPORT.md
  cumulative PnL PNGs per top
"""
import sys, os, io, itertools
from pathlib import Path
import numpy as np
import pandas as pd

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
except Exception:
    pass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(r"C:/Users/alexandre bandarra/Desktop/global")
OUT = ROOT / "strategy_lab/sniper_search_2026_05_27/btc_5m_v8"
SAND = OUT / "_sandbox"
PNG = OUT / "png"
SCRIPTS = OUT / "scripts"
for d in [OUT, SAND, PNG, SCRIPTS]:
    d.mkdir(parents=True, exist_ok=True)

ENR_PATH = ROOT / "data/v4/canonical/_results/_sniper_btc_5m_enriched.parquet"
R5_PATH = ROOT / "data/v4/canonical/_results/regime_panel_5m_v2_fixed.parquet"
R15_PATH = ROOT / "data/v4/canonical/_results/regime_panel_15m_v2_fixed.parquet"
RF1H_PATH = ROOT / "data/v4/canonical/_results/range_filter_1h.parquet"
HL_FUND_PATH = ROOT / "data/v4/canonical/hyperliquid_funding.parquet"
HL_MET_PATH = ROOT / "data/v4/canonical/hyperliquid_metrics.parquet"

ASSET, TF, WINDOW_S = "BTC", "5m", 300
STAKE = 25.0
DAYS_TOTAL = 32.66  # v3 full window

# V8 sniper bar (per BRIEF §3)
V8 = dict(
    n_min_full=30, n_max_full=2000,
    wr_min=0.65,
    dpt_25_min=4.0,
    dd_25_max=500.0,
    loss_streak_max=14,
    sharpe_min=1.5,
    bootstrap_p_max=0.05,
)

# Strong gate library (V7 proven set)
STRONG_GATES = [
    "g_trend_slope_strong_with", "g_mp_no_extreme", "g_mp_skew_with", "g_mp_change_with",
    "g_imb5_strong_with", "g_queue_top_high", "g_hawkes_imbalance_with",
    "g_within_dev", "g_dev_extreme",
    "g_tr_above_ema200", "g_tr_above_ema800", "g_ribbon_agrees", "g_rf_with",
    "g_lm_high_stat", "g_hl_liq_cascade_with", "g_vol_high", "g_markov_with",
    "g_hurst_trending",
]


# ==========================================================================
# Data loading
# ==========================================================================
def load_universe():
    print("Loading _sniper_btc_5m_enriched (full 32.66d) ...")
    df = pd.read_parquet(ENR_PATH)
    df = df.sort_values("fire_us").reset_index(drop=True)
    df["fire_dt"] = pd.to_datetime(df["fire_us"], unit="us", utc=True)
    df["fire_date"] = df["fire_dt"].dt.date
    # dir_sign sometimes missing — derive
    if "dir_sign" not in df.columns or df["dir_sign"].isna().any():
        df["dir_sign"] = np.where(df["direction"].astype(str).str.lower().str.startswith("up"), 1, -1).astype(np.int8)
    if "won_int" not in df.columns or df["won_int"].isna().any():
        df["won_int"] = df["won"].fillna(0).astype(np.int8)
    g_cols = [c for c in df.columns if c.startswith("g_")]
    for c in g_cols:
        df[c] = df[c].fillna(0).astype(np.int8)
    print(f"  rows={len(df):,}, days_span={DAYS_TOTAL:.2f}, WR_base={df['won_int'].mean():.4f}, "
          f"dpt_25_base=${df['pnl_legacy_usd'].mean():+.3f}")
    print(f"  offsets={sorted(df['fire_offset_s'].unique())}")
    return df


# ==========================================================================
# Path J — 2-asset / 3-asset confluence (cross-asset trend agreement)
# ==========================================================================
def build_cross_asset_gates(df):
    """Asof join regime_panel_5m_v2_fixed BTC/ETH/SOL trend_slope_30m at fire_us-1s."""
    print("\nLoading regime_panel_5m_v2_fixed (cross-asset trend) ...")
    r5 = pd.read_parquet(R5_PATH)
    out = df.copy()
    fus = df["fire_us"].values
    lookup_us = fus - 1_000_000  # 1s causal epsilon
    for asset in ["BTC", "ETH", "SOL"]:
        ra = r5[r5["asset"] == asset].sort_values("ts_us").reset_index(drop=True)
        if len(ra) == 0:
            print(f"  warn: regime_panel_5m has no {asset}")
            out[f"trend_slope_30m_{asset}"] = np.nan
            out[f"regime_label_{asset}"] = None
            continue
        ts = ra["ts_us"].values
        sl = ra["trend_slope_30m"].values
        lb = ra["regime_label"].values
        idx = np.searchsorted(ts, lookup_us, side="right") - 1
        idx = np.clip(idx, 0, len(ra) - 1)
        out[f"trend_slope_30m_{asset}"] = sl[idx]
        out[f"regime_label_{asset}"] = lb[idx]
        # mark valid: lookup must be >= first ts
        out.loc[lookup_us < ts[0], f"trend_slope_30m_{asset}"] = np.nan
        out.loc[lookup_us < ts[0], f"regime_label_{asset}"] = None

    # 2-asset confluence: BTC + ETH trend slope sign agrees with direction
    btc_ts = out["trend_slope_30m_BTC"].values
    eth_ts = out["trend_slope_30m_ETH"].values
    sol_ts = out["trend_slope_30m_SOL"].values
    dsign = out["dir_sign"].values

    out["g_2asset_btc_eth_with"] = (
        (np.sign(btc_ts) == dsign) & (np.sign(eth_ts) == dsign) & np.isfinite(btc_ts) & np.isfinite(eth_ts)
    ).astype(np.int8)
    out["g_2asset_btc_sol_with"] = (
        (np.sign(btc_ts) == dsign) & (np.sign(sol_ts) == dsign) & np.isfinite(btc_ts) & np.isfinite(sol_ts)
    ).astype(np.int8)
    out["g_2asset_eth_sol_with"] = (
        (np.sign(eth_ts) == dsign) & (np.sign(sol_ts) == dsign) & np.isfinite(eth_ts) & np.isfinite(sol_ts)
    ).astype(np.int8)
    # 3-asset unanimity
    out["g_3asset_unanimity_with"] = (
        (np.sign(btc_ts) == dsign) & (np.sign(eth_ts) == dsign) & (np.sign(sol_ts) == dsign)
        & np.isfinite(btc_ts) & np.isfinite(eth_ts) & np.isfinite(sol_ts)
    ).astype(np.int8)
    # 2-asset agreement (any two of three agree with direction)
    sig_btc = (np.sign(btc_ts) == dsign).astype(np.int8)
    sig_eth = (np.sign(eth_ts) == dsign).astype(np.int8)
    sig_sol = (np.sign(sol_ts) == dsign).astype(np.int8)
    valid = np.isfinite(btc_ts) & np.isfinite(eth_ts) & np.isfinite(sol_ts)
    out["g_xa_majority_with"] = ((sig_btc + sig_eth + sig_sol) >= 2).astype(np.int8) * valid.astype(np.int8)

    for g in ["g_2asset_btc_eth_with", "g_2asset_btc_sol_with", "g_2asset_eth_sol_with",
              "g_3asset_unanimity_with", "g_xa_majority_with"]:
        print(f"  {g}: on_rate={out[g].mean():.4f} n_pos={(out[g]==1).sum()}")
    return out


# ==========================================================================
# Path L — 1h grandparent (range_filter_1h)
# ==========================================================================
def build_grandparent_1h(df):
    """g_1h_rf_with: BTC 1h range filter direction agrees with sleeve direction."""
    print("\nLoading range_filter_1h BTC ...")
    rf = pd.read_parquet(RF1H_PATH)
    rf_btc = rf[rf["asset"] == ASSET].sort_values("ts_us").reset_index(drop=True)
    if len(rf_btc) == 0:
        df["g_1h_rf_with"] = 0
        return df
    fus = df["fire_us"].values
    lookup_us = fus - 1_000_000
    ts = rf_btc["ts_us"].values
    rd = rf_btc["rf_dir"].values
    idx = np.searchsorted(ts, lookup_us, side="right") - 1
    idx = np.clip(idx, 0, len(rf_btc) - 1)
    rf_dir_h = rd[idx]
    valid = lookup_us >= ts[0]
    df["rf_dir_1h"] = np.where(valid, rf_dir_h, 0)
    df["g_1h_rf_with"] = ((df["rf_dir_1h"].astype(int) * df["dir_sign"].astype(int)) > 0).astype(np.int8)
    print(f"  g_1h_rf_with on_rate: {df['g_1h_rf_with'].mean():.4f}")
    return df


# ==========================================================================
# Path Q — 5m + 15m parent regime confluence
# ==========================================================================
def build_parent_15m(df):
    """g_parent_15m_regime_with: 15m regime trending matches direction."""
    print("\nLoading regime_panel_15m_v2_fixed BTC ...")
    r15 = pd.read_parquet(R15_PATH)
    r15_btc = r15[r15["asset"] == ASSET].sort_values("ts_us").reset_index(drop=True)
    fus = df["fire_us"].values
    lookup_us = fus - 1_000_000
    ts = r15_btc["ts_us"].values
    lab = r15_btc["regime_label"].values
    slope = r15_btc["trend_slope_30m"].values
    idx = np.searchsorted(ts, lookup_us, side="right") - 1
    idx = np.clip(idx, 0, len(r15_btc) - 1)
    valid = lookup_us >= ts[0]
    parent_label = np.where(valid, lab[idx], None)
    parent_slope = np.where(valid, slope[idx], np.nan)
    df["parent_15m_regime"] = parent_label
    df["parent_15m_slope"] = parent_slope

    dsign = df["dir_sign"].values
    p_up = (parent_label == "trending_up") & (dsign == 1)
    p_dn = (parent_label == "trending_dn") & (dsign == -1)
    df["g_parent_15m_regime_with"] = (p_up | p_dn).astype(np.int8)
    df["g_parent_15m_slope_with"] = ((parent_slope * dsign) > 0).astype(np.int8)
    df["g_parent_15m_not_ranging"] = (parent_label != "ranging").astype(np.int8) & valid.astype(np.int8)
    print(f"  g_parent_15m_regime_with: {df['g_parent_15m_regime_with'].mean():.4f}")
    print(f"  g_parent_15m_slope_with: {df['g_parent_15m_slope_with'].mean():.4f}")
    print(f"  g_parent_15m_not_ranging: {df['g_parent_15m_not_ranging'].mean():.4f}")
    return df


# ==========================================================================
# Path K — TOD specialization (UTC hour-of-day buckets)
# ==========================================================================
def build_tod_buckets(df):
    """4 TOD buckets per UTC hour."""
    hod = df["fire_dt"].dt.hour.values
    df["hod"] = hod
    df["g_tod_asia"] = ((hod >= 0) & (hod < 7)).astype(np.int8)
    df["g_tod_eu_morning"] = ((hod >= 7) & (hod < 13)).astype(np.int8)
    df["g_tod_us_afternoon"] = ((hod >= 13) & (hod < 19)).astype(np.int8)
    df["g_tod_us_evening"] = ((hod >= 19) & (hod < 24)).astype(np.int8)
    for g in ["g_tod_asia", "g_tod_eu_morning", "g_tod_us_afternoon", "g_tod_us_evening"]:
        sub = df[df[g] == 1]
        wr = sub["won_int"].mean() if len(sub) else 0
        dpt = sub["pnl_legacy_usd"].mean() if len(sub) else 0
        print(f"  {g}: n={len(sub)} wr={wr:.3f} dpt=${dpt:+.3f}")
    return df


# ==========================================================================
# Path O — HL gates (funding extreme + OI change)
# ==========================================================================
def build_hl_gates(df):
    """HL funding extreme (contrarian) + OI shift agree-with-direction."""
    print("\nLoading HL funding (BTC) ...")
    hf = pd.read_parquet(HL_FUND_PATH)
    hf_btc = hf[hf["symbol"] == ASSET].copy()
    hf_btc["funding_rate"] = pd.to_numeric(hf_btc["funding_rate"], errors="coerce")
    hf_btc = hf_btc.sort_values("funding_time_us").reset_index(drop=True)
    fus = df["fire_us"].values
    lookup_us = fus - 1_000_000
    ts = hf_btc["funding_time_us"].values
    fr = hf_btc["funding_rate"].values
    idx = np.searchsorted(ts, lookup_us, side="right") - 1
    idx = np.clip(idx, 0, len(hf_btc) - 1)
    valid = lookup_us >= ts[0]
    f_h = np.where(valid, fr[idx], np.nan)
    df["hl_funding_rate"] = f_h
    # Contrarian: positive funding (crowded longs) + DOWN direction
    # HL funding scale is ~1e-5; use ~75th percentile threshold
    dsign = df["dir_sign"].values
    pos_fund = f_h > 5e-6  # ~75th pct
    neg_fund = f_h < -5e-6
    df["g_hl_funding_extreme_with"] = (
        ((pos_fund & (dsign == -1)) | (neg_fund & (dsign == 1))) & np.isfinite(f_h)
    ).astype(np.int8)
    # Pro-trend: funding sign agrees with direction (momentum-with)
    df["g_hl_funding_with"] = (
        ((pos_fund & (dsign == 1)) | (neg_fund & (dsign == -1))) & np.isfinite(f_h)
    ).astype(np.int8)
    print(f"  g_hl_funding_extreme_with on_rate: {df['g_hl_funding_extreme_with'].mean():.4f}")
    print(f"  g_hl_funding_with on_rate: {df['g_hl_funding_with'].mean():.4f}")

    print("Loading HL metrics (BTC OI/funding running) ...")
    hm = pd.read_parquet(HL_MET_PATH, columns=["time_exchange_us", "symbol", "open_interest"])
    hm_btc = hm[hm["symbol"] == ASSET].copy()
    hm_btc["open_interest"] = pd.to_numeric(hm_btc["open_interest"], errors="coerce")
    hm_btc = hm_btc.dropna(subset=["open_interest"]).sort_values("time_exchange_us").reset_index(drop=True)
    if len(hm_btc) > 0:
        ts = hm_btc["time_exchange_us"].values
        oi = hm_btc["open_interest"].values
        # OI at fire_us and at fire_us - 1h
        idx_now = np.searchsorted(ts, lookup_us, side="right") - 1
        idx_1h = np.searchsorted(ts, lookup_us - 3600_000_000, side="right") - 1
        idx_now = np.clip(idx_now, 0, len(hm_btc) - 1)
        idx_1h = np.clip(idx_1h, 0, len(hm_btc) - 1)
        v_now = lookup_us >= ts[0]
        v_1h = (lookup_us - 3600_000_000) >= ts[0]
        oi_now = np.where(v_now, oi[idx_now], np.nan)
        oi_1h = np.where(v_1h, oi[idx_1h], np.nan)
        oi_chg = (oi_now - oi_1h) / np.where(oi_1h > 0, oi_1h, np.nan)
        df["hl_oi_chg_1h"] = oi_chg
        # Gate: OI rising > 2% in 1h AND direction sign agrees with recent BTC 5m slope sign
        rising = oi_chg > 0.02
        falling = oi_chg < -0.02
        # Use BTC trend_slope as the direction reference for OI alignment
        sl_btc = df.get("trend_slope_30m_BTC", pd.Series(np.zeros(len(df)))).values
        df["g_hl_oi_rising_with"] = (
            ((rising & (np.sign(sl_btc) == dsign)) | (falling & (np.sign(sl_btc) == dsign)))
            & np.isfinite(oi_chg)
        ).astype(np.int8)
        print(f"  g_hl_oi_rising_with on_rate: {df['g_hl_oi_rising_with'].mean():.4f}")
    else:
        df["g_hl_oi_rising_with"] = 0
    return df


# ==========================================================================
# Splits + metrics
# ==========================================================================
def split_60_20_20(df):
    """60% train / 20% val / 20% lockbox by fire_us (chronological)."""
    df = df.sort_values("fire_us").reset_index(drop=True)
    ts_min = df["fire_us"].min()
    ts_max = df["fire_us"].max()
    span = ts_max - ts_min
    cut1 = ts_min + int(span * 0.60)
    cut2 = ts_min + int(span * 0.80)
    tr = df[df["fire_us"] < cut1].copy()
    va = df[(df["fire_us"] >= cut1) & (df["fire_us"] < cut2)].copy()
    lb = df[df["fire_us"] >= cut2].copy()
    days_tr = (tr["fire_us"].max() - tr["fire_us"].min()) / 86400e6
    days_va = (va["fire_us"].max() - va["fire_us"].min()) / 86400e6
    days_lb = (lb["fire_us"].max() - lb["fire_us"].min()) / 86400e6
    return tr, va, lb, days_tr, days_va, days_lb


def compute_metrics(sub, days_total=None, pnl_col="pnl_legacy_usd"):
    n = len(sub)
    if n == 0:
        return None
    sub = sub.sort_values("fire_us").reset_index(drop=True)
    pnl = sub[pnl_col].values
    won_col = "won_int" if "won_int" in sub.columns else "won"
    won = int(sub[won_col].sum())
    wr = won / n
    dpt = float(np.mean(pnl))
    total = float(np.sum(pnl))
    cum = np.cumsum(pnl)
    peak = np.maximum.accumulate(cum)
    max_dd = float(np.max(peak - cum)) if len(cum) else 0.0
    losses = (sub[won_col] == 0).values.astype(np.int8)
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
        days_span = (sub["fire_us"].max() - sub["fire_us"].min()) / 86400e6
    else:
        days_span = days_total
    rate = n / max(days_span, 0.1)
    n_32d = rate * 32.66
    return dict(n=n, wr=wr, dpt_25=dpt, total_25=total, max_dd_25=max_dd,
                loss_streak=max_streak, sharpe=sharpe, n_32d_proj=n_32d,
                days_span=max(days_span, 0.1))


def bootstrap_p(sub, n_iter=1000, seed=20260527, pnl_col="pnl_legacy_usd"):
    if len(sub) < 5:
        return 1.0
    rng = np.random.default_rng(seed)
    pnl = sub[pnl_col].values
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


def passes_v8(row):
    n32 = row["n_32d_proj_lockbox"]
    if not (V8["n_min_full"] <= n32 <= V8["n_max_full"]):
        return False, "n_32d_out_of_band"
    if row["wr_lockbox"] < V8["wr_min"]:
        return False, "wr_lockbox_low"
    if row["dpt_25_lockbox"] < V8["dpt_25_min"]:
        return False, "dpt_lockbox_low"
    if row["max_dd_25_lockbox"] > V8["dd_25_max"]:
        return False, "dd_lockbox_high"
    if row["loss_streak_lockbox"] > V8["loss_streak_max"]:
        return False, "loss_streak_long"
    if row["sharpe_lockbox"] < V8["sharpe_min"]:
        return False, "sharpe_lockbox_low"
    if row["bootstrap_p_lockbox"] > V8["bootstrap_p_max"]:
        return False, "bootstrap_p_high"
    return True, "PASS"


def evaluate_candidate(df, mask, sleeve_id, path_id, gate_stack, splits, days_lb):
    """Evaluate a mask. Returns dict with n_train/val/lockbox/full + WR + dpt + sharpe + bootstrap."""
    n_full = int(mask.sum())
    if n_full < 30:
        return None
    tr, va, lb, days_tr, days_va, _days_lb = splits
    fus = df["fire_us"].values
    tr_idx = (fus >= tr["fire_us"].min()) & (fus <= tr["fire_us"].max())
    va_idx = (fus >= va["fire_us"].min()) & (fus <= va["fire_us"].max())
    lb_idx = (fus >= lb["fire_us"].min()) & (fus <= lb["fire_us"].max())
    m = mask.values if isinstance(mask, pd.Series) else mask
    sub_tr = df[m & tr_idx]
    sub_va = df[m & va_idx]
    sub_lb = df[m & lb_idx]
    sub_full = df[m]
    if len(sub_lb) < 10 or len(sub_tr) < 10:
        return None
    won_col = "won_int" if "won_int" in df.columns else "won"
    m_lb = compute_metrics(sub_lb, days_total=days_lb)
    m_full = compute_metrics(sub_full, days_total=DAYS_TOTAL)
    boot_lb = bootstrap_p(sub_lb, 1000)
    return dict(
        sleeve_id=sleeve_id, path=path_id, gate_stack=gate_stack,
        n_full=n_full, n_train=int(len(sub_tr)),
        n_val=int(len(sub_va)), n_lockbox=int(len(sub_lb)),
        wr_train=float(sub_tr[won_col].mean()) if len(sub_tr) else 0.0,
        wr_val=float(sub_va[won_col].mean()) if len(sub_va) else 0.0,
        wr_lockbox=m_lb["wr"], wr_full=m_full["wr"],
        dpt_25_train=float(sub_tr["pnl_legacy_usd"].mean()) if len(sub_tr) else 0.0,
        dpt_25_val=float(sub_va["pnl_legacy_usd"].mean()) if len(sub_va) else 0.0,
        dpt_25_lockbox=m_lb["dpt_25"], dpt_25_full=m_full["dpt_25"],
        sum_25_lockbox=m_lb["total_25"], sum_25_full=m_full["total_25"],
        max_dd_25_lockbox=m_lb["max_dd_25"], max_dd_25_full=m_full["max_dd_25"],
        loss_streak_lockbox=m_lb["loss_streak"], loss_streak_full=m_full["loss_streak"],
        sharpe_lockbox=m_lb["sharpe"], sharpe_full=m_full["sharpe"],
        n_32d_proj_lockbox=m_lb["n_32d_proj"],
        n_32d_proj_full=m_full["n_32d_proj"],
        bootstrap_p_lockbox=boot_lb,
        # Projections per BRIEF §0
        proj_32d=m_lb["dpt_25"] * (m_lb["n"] / max(m_lb["days_span"], 0.1)) * 32.66,
        proj_full=m_full["dpt_25"] * (m_full["n"] / max(m_full["days_span"], 0.1)) * 32.66,
        proj_honest=min(
            m_lb["dpt_25"] * (m_lb["n"] / max(m_lb["days_span"], 0.1)) * 32.66,
            m_full["dpt_25"] * (m_full["n"] / max(m_full["days_span"], 0.1)) * 32.66,
        ),
        objective=m_lb["dpt_25"] * np.sqrt(max(m_lb["n"], 1)),
    )


# ==========================================================================
# Path J — Confluence sleeves (alone + stacked)
# ==========================================================================
def path_J(df, splits, days_lb):
    print("\n[J] 2-asset / 3-asset confluence ...")
    cands = []
    XA_GATES = ["g_2asset_btc_eth_with", "g_2asset_btc_sol_with", "g_2asset_eth_sol_with",
                "g_3asset_unanimity_with", "g_xa_majority_with"]
    for xag in XA_GATES:
        if xag not in df.columns:
            continue
        m_xa = (df[xag].values == 1)
        if m_xa.sum() < 50:
            continue
        # Alone
        rec = evaluate_candidate(df, pd.Series(m_xa, index=df.index),
                                 f"J_{xag}_alone", "J_confluence", xag, splits, days_lb)
        if rec:
            cands.append(rec)
        # + 1 strong gate
        for g in STRONG_GATES:
            if g not in df.columns or g == xag:
                continue
            m = m_xa & (df[g].values == 1)
            if m.sum() < 30:
                continue
            rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                     f"J_{xag}+{g}", "J_confluence", f"{xag}+{g}", splits, days_lb)
            if rec:
                cands.append(rec)
        # + 2 strong gates
        for combo in itertools.combinations(STRONG_GATES, 2):
            if xag in combo:
                continue
            m = m_xa.copy()
            for g in combo:
                if g in df.columns:
                    m &= (df[g].values == 1)
            if m.sum() < 30:
                continue
            gs = f"{xag}+{'+'.join(combo)}"
            rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                     f"J_{gs}", "J_confluence", gs, splits, days_lb)
            if rec:
                cands.append(rec)
    print(f"  +{len(cands)} candidates")
    return cands


# ==========================================================================
# Path K — TOD specialization (best V7 stacks within each TOD bucket)
# ==========================================================================
def path_K(df, splits, days_lb):
    print("\n[K] TOD specialization ...")
    cands = []
    TOD_GATES = ["g_tod_asia", "g_tod_eu_morning", "g_tod_us_afternoon", "g_tod_us_evening"]
    # Best V7 stacks (top 3) — test each within each TOD bucket
    BEST_STACKS = [
        ["g_parent_15m_regime_with", "g_within_dev", "g_hurst_trending"],
        ["g_parent_15m_slope_with", "g_trend_slope_strong_with", "g_mp_no_extreme"],
        ["g_parent_15m_not_ranging", "g_trend_slope_strong_with", "g_mp_skew_with"],
        ["g_trend_slope_strong_with", "g_mp_no_extreme"],
        ["g_trend_slope_strong_with", "g_within_dev"],
        ["g_hurst_trending", "g_trend_slope_strong_with"],
        ["g_parent_15m_regime_with"],
    ]
    for tod in TOD_GATES:
        m_tod = (df[tod].values == 1)
        if m_tod.sum() < 200:
            continue
        # TOD alone
        rec = evaluate_candidate(df, pd.Series(m_tod, index=df.index),
                                 f"K_{tod}_alone", "K_tod", tod, splits, days_lb)
        if rec:
            cands.append(rec)
        # TOD + each best stack
        for stack in BEST_STACKS:
            if not all(g in df.columns for g in stack):
                continue
            m = m_tod.copy()
            for g in stack:
                m &= (df[g].values == 1)
            if m.sum() < 30:
                continue
            gs = f"{tod}+{'+'.join(stack)}"
            rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                     f"K_{gs}", "K_tod", gs, splits, days_lb)
            if rec:
                cands.append(rec)
        # TOD + every (1-2) strong gate combo from STRONG_GATES (lighter sweep — only singletons)
        for g in STRONG_GATES:
            if g not in df.columns:
                continue
            m = m_tod & (df[g].values == 1)
            if m.sum() < 30:
                continue
            gs = f"{tod}+{g}"
            rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                     f"K_{gs}", "K_tod", gs, splits, days_lb)
            if rec:
                cands.append(rec)
    print(f"  +{len(cands)} candidates")
    return cands


# ==========================================================================
# Path L — 1h grandparent stacks
# ==========================================================================
def path_L(df, splits, days_lb):
    print("\n[L] 1h grandparent stacks ...")
    cands = []
    if "g_1h_rf_with" not in df.columns:
        return cands
    m_h = (df["g_1h_rf_with"].values == 1)
    if m_h.sum() < 50:
        return cands
    # Alone
    rec = evaluate_candidate(df, pd.Series(m_h, index=df.index),
                             "L_g_1h_rf_with_alone", "L_grandparent_1h", "g_1h_rf_with",
                             splits, days_lb)
    if rec:
        cands.append(rec)
    # Stacked with 15m parent + strong gates
    for combo in itertools.combinations(STRONG_GATES + ["g_parent_15m_regime_with", "g_parent_15m_slope_with"], 2):
        m = m_h.copy()
        for g in combo:
            if g in df.columns:
                m &= (df[g].values == 1)
        if m.sum() < 30:
            continue
        gs = f"g_1h_rf_with+{'+'.join(combo)}"
        rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                 f"L_{gs}", "L_grandparent_1h", gs, splits, days_lb)
        if rec:
            cands.append(rec)
    print(f"  +{len(cands)} candidates")
    return cands


# ==========================================================================
# Path O — HL funding + OI stacks
# ==========================================================================
def path_O(df, splits, days_lb):
    print("\n[O] HL funding + OI ...")
    cands = []
    HL_GATES = ["g_hl_funding_extreme_with", "g_hl_funding_with", "g_hl_oi_rising_with",
                "g_hl_liq_cascade_with"]
    for hg in HL_GATES:
        if hg not in df.columns:
            continue
        m_h = (df[hg].values == 1)
        if m_h.sum() < 100:
            continue
        rec = evaluate_candidate(df, pd.Series(m_h, index=df.index),
                                 f"O_{hg}_alone", "O_hl", hg, splits, days_lb)
        if rec:
            cands.append(rec)
        for g in STRONG_GATES:
            if g not in df.columns or g == hg:
                continue
            m = m_h & (df[g].values == 1)
            if m.sum() < 30:
                continue
            gs = f"{hg}+{g}"
            rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                     f"O_{gs}", "O_hl", gs, splits, days_lb)
            if rec:
                cands.append(rec)
    print(f"  +{len(cands)} candidates")
    return cands


# ==========================================================================
# Path Q — 5m + 15m parent confluence (V7 BASELINE — re-validate on full window)
# ==========================================================================
def path_Q(df, splits, days_lb):
    print("\n[Q] 5m + 15m parent confluence (V7 winners re-validated) ...")
    cands = []
    PARENT_GATES = ["g_parent_15m_regime_with", "g_parent_15m_slope_with", "g_parent_15m_not_ranging"]
    for pg in PARENT_GATES:
        if pg not in df.columns:
            continue
        m_p = (df[pg].values == 1)
        if m_p.sum() < 50:
            continue
        rec = evaluate_candidate(df, pd.Series(m_p, index=df.index),
                                 f"Q_{pg}_alone", "Q_parent_15m", pg, splits, days_lb)
        if rec:
            cands.append(rec)
        for g in STRONG_GATES:
            if g not in df.columns:
                continue
            m = m_p & (df[g].values == 1)
            if m.sum() < 30:
                continue
            gs = f"{pg}+{g}"
            rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                     f"Q_{gs}", "Q_parent_15m", gs, splits, days_lb)
            if rec:
                cands.append(rec)
        for combo in itertools.combinations(STRONG_GATES, 2):
            m = m_p.copy()
            for g in combo:
                if g in df.columns:
                    m &= (df[g].values == 1)
            if m.sum() < 30:
                continue
            gs = f"{pg}+{'+'.join(combo)}"
            rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                     f"Q_{gs}", "Q_parent_15m", gs, splits, days_lb)
            if rec:
                cands.append(rec)
    print(f"  +{len(cands)} candidates")
    return cands


# ==========================================================================
# Plot cum PnL
# ==========================================================================
def plot_cumpnl(df_sub, sleeve_id, out_path):
    sub = df_sub.sort_values("fire_us").reset_index(drop=True)
    if len(sub) < 5:
        return
    cum = sub["pnl_legacy_usd"].cumsum().values
    dt = pd.to_datetime(sub["fire_us"], unit="us", utc=True)
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7), sharex=True,
                                    gridspec_kw={"height_ratios": [3, 1]})
    ax1.plot(dt, cum, lw=1.5, color="navy", label=f"Cum PnL (sum=${cum[-1]:+.1f})")
    ax1.set_title(f"BTC 5m V8 — {sleeve_id}\nn={len(sub)}, $/tr=${sub['pnl_legacy_usd'].mean():+.2f}")
    ax1.set_ylabel("Cumulative PnL ($25 stake)")
    ax1.grid(alpha=0.3)
    ax1.legend()
    ax2.fill_between(dt, 0, -dd, color="firebrick", alpha=0.4,
                     label=f"DD (max=${dd.max():.1f})")
    ax2.set_ylabel("Drawdown ($)")
    ax2.grid(alpha=0.3)
    ax2.legend()
    fig.autofmt_xdate()
    fig.savefig(out_path, dpi=100, bbox_inches="tight")
    plt.close(fig)


# ==========================================================================
# Main
# ==========================================================================
def main():
    print("=" * 72)
    print("SNIPER SEARCH V8 — BTC 5m (full 32.66d)")
    print("=" * 72)
    cache = SAND / "universe_v8.parquet"
    if cache.exists() and os.environ.get("V8_FORCE_REBUILD", "0") != "1":
        print("Loading cached universe_v8.parquet ...")
        df = pd.read_parquet(cache)
        df["fire_dt"] = pd.to_datetime(df["fire_us"], unit="us", utc=True)
        df["fire_date"] = df["fire_dt"].dt.date
    else:
        df = load_universe()
        df = build_cross_asset_gates(df)
        df = build_parent_15m(df)
        df = build_grandparent_1h(df)
        df = build_tod_buckets(df)
        df = build_hl_gates(df)
        df.to_parquet(cache)
        print(f"Cached universe to {cache}")

    splits = split_60_20_20(df)
    tr, va, lb, days_tr, days_va, days_lb = splits
    print(f"\nSplit train={len(tr):,} ({days_tr:.1f}d, {tr['fire_dt'].min().date()} -> {tr['fire_dt'].max().date()})")
    print(f"      val={len(va):,} ({days_va:.1f}d, {va['fire_dt'].min().date()} -> {va['fire_dt'].max().date()})")
    print(f"      lockbox={len(lb):,} ({days_lb:.1f}d, {lb['fire_dt'].min().date()} -> {lb['fire_dt'].max().date()})")

    all_cands = []
    all_cands.extend(path_Q(df, splits, days_lb))  # baseline V7-winner re-validation
    all_cands.extend(path_J(df, splits, days_lb))
    all_cands.extend(path_K(df, splits, days_lb))
    all_cands.extend(path_L(df, splits, days_lb))
    all_cands.extend(path_O(df, splits, days_lb))

    print(f"\nTotal candidates: {len(all_cands)}")
    cdf = pd.DataFrame(all_cands)
    statuses = cdf.apply(passes_v8, axis=1)
    cdf["pass"] = [s[0] for s in statuses]
    cdf["fail_reason"] = [s[1] for s in statuses]
    cdf = cdf.sort_values(["pass", "proj_honest", "objective"], ascending=[False, False, False])
    cdf.to_csv(OUT / "all_candidates_v8.csv", index=False)
    print(f"Wrote all_candidates_v8.csv ({len(cdf)} rows)")

    passers = cdf[cdf["pass"]].copy()
    print(f"\nPassers (all V8 criteria): {len(passers)}")
    if len(passers) > 0:
        cols = ["sleeve_id", "path", "gate_stack", "n_lockbox", "n_full",
                "wr_lockbox", "wr_full", "dpt_25_lockbox", "dpt_25_full",
                "proj_32d", "proj_full", "proj_honest",
                "max_dd_25_lockbox", "loss_streak_lockbox", "sharpe_lockbox",
                "bootstrap_p_lockbox"]
        print(passers[cols].head(20).to_string(index=False))

    # Dedup by metric signature (drop near-identical)
    if len(passers) > 0:
        sig_cols = ["n_full", "wr_lockbox", "dpt_25_lockbox", "loss_streak_lockbox"]
        passers["_sig"] = passers[sig_cols].apply(lambda r: hash(tuple(np.round(r.values, 3))), axis=1)
        deduped = passers.drop_duplicates("_sig").drop(columns=["_sig"]).sort_values("proj_honest", ascending=False)
    else:
        deduped = passers
    print(f"\nAfter metric-sig dedup: {len(deduped)}")

    # Save universe to sandbox for finalize
    print("\nSaving state to sandbox ...")
    return df, cdf, deduped, splits


if __name__ == "__main__":
    df, cdf, deduped, splits = main()
    deduped.to_csv(OUT / "_deduped_passers_v8.csv", index=False)
