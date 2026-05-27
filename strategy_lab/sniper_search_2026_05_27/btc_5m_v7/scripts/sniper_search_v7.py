"""
SNIPER SEARCH V7 — BTC 5m
=========================
V7 paths (per _BRIEF_V7.md §8 for BTC 5m):
  A — Weighted ensembles (gate-sum threshold, no "all-must-pass")
  D — Slot-end OFI for late offsets (causality: only fires at offset >= 240s
      for 5m can see OFI in (slot_end-60s, slot_end), but here slot_end - fire_us
      must be <= 60s. For 5m (window=300), fire at offset 240 means 60s pre-close OK.)
  H — Hurst variants: strong_trending > 0.65, reverting < 0.40, regime_with
  F — 15m parent regime confluence (regime_panel_15m_v2_fixed BTC)
  B — 2-leg straddle sleeves (UP at offset=30 + DOWN at offset=180 on same slug)

Universe: master_gate_features_v2.parquet, BTC 5m subset (33,646 fires, May 1 -> May 25)
Stake: constant $25
Target: lockbox $/tr * sqrt(n), no lottery artifact

Output:
  all_candidates_v7.csv
  top_5_candidates_v7.csv
  SNIPER_BTC_5M_V7_REPORT.md
  cumulative_pnl_v7_{sleeve_id}.png
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
OUT = ROOT / "strategy_lab/sniper_search_2026_05_27/btc_5m_v7"
SAND = OUT / "_sandbox"
OUT.mkdir(parents=True, exist_ok=True)
SAND.mkdir(parents=True, exist_ok=True)

MG_PATH = ROOT / "data/v4/canonical/_results/master_gate_features_v2.parquet"
MP_PATH = ROOT / "data/v4/canonical/_results/microprice_panel.parquet"
R15_PATH = ROOT / "data/v4/canonical/_results/regime_panel_15m_v2_fixed.parquet"
TRADES_PATH = ROOT / "data/v4/canonical/trades_polymarket/btc.parquet"

ASSET, TF, WINDOW_S = "BTC", "5m", 300
STAKE = 25.0
DAYS_TOTAL = 24.8  # master_gate_features_v2 effective window

# V7 sniper bar (same as V6 for compatibility)
V7 = dict(
    n_min_28d=30, n_max_28d=2000,
    wr_min=0.65,
    dpt_25_min=4.0,
    dd_25_max=500.0,
    loss_streak_max=14,
    sharpe_min=1.5,
    bootstrap_p_max=0.05,
)

# Strong gate library (same as V6, plus new variants)
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
    print("Loading master_gate_features_v2 BTC 5m ...")
    mg = pd.read_parquet(MG_PATH)
    df = mg[(mg["asset"] == ASSET) & (mg["tf"] == TF)].copy()
    df = df.sort_values("fire_us").reset_index(drop=True)
    df["fire_dt"] = pd.to_datetime(df["fire_us"], unit="us", utc=True)
    df["fire_date"] = df["fire_dt"].dt.date
    # slot_start_us = fire_us - fire_offset_s * 1_000_000
    df["slot_start_us"] = df["fire_us"] - df["fire_offset_s"].astype(np.int64) * 1_000_000
    df["slot_end_us"] = df["slot_start_us"] + WINDOW_S * 1_000_000
    df["ws_s"] = (df["slot_start_us"] // 1_000_000) - WINDOW_S
    g_cols = [c for c in df.columns if c.startswith("g_")]
    for c in g_cols:
        df[c] = df[c].fillna(0).astype(np.int8)
    df["won_int"] = df["won_int"].fillna(0).astype(np.int8)
    print(f"  rows={len(df):,}, WR_base={df['won_int'].mean():.4f}, "
          f"dpt_25_base=${df['pnl_legacy_usd'].mean():+.3f}")
    print(f"  offsets={sorted(df['fire_offset_s'].unique())}")
    return df


# ==========================================================================
# Path H: Hurst variants
# ==========================================================================
def build_hurst_variants(df):
    """Add stronger/reverting hurst gates + regime-with hurst."""
    h300 = df["hurst_300s"]
    df["g_hurst_strong_trending"] = (h300 > 0.65).fillna(False).astype(np.int8)
    df["g_hurst_reverting_strict"] = (h300 < 0.40).fillna(False).astype(np.int8)
    # Hurst trending + direction aligned: hurst > 0.55 AND trend_slope_30m sign matches direction
    h_ok = (h300 > 0.55).fillna(False)
    slope_with = (df["trend_slope_30m"] * df["dir_sign"]) > 0
    df["g_hurst_regime_with"] = (h_ok & slope_with).astype(np.int8)
    print(f"  g_hurst_strong_trending on rate: {df['g_hurst_strong_trending'].mean():.4f}")
    print(f"  g_hurst_reverting_strict on rate: {df['g_hurst_reverting_strict'].mean():.4f}")
    print(f"  g_hurst_regime_with on rate: {df['g_hurst_regime_with'].mean():.4f}")
    return df


# ==========================================================================
# Path F: 15m parent regime confluence
# ==========================================================================
def build_parent_15m(df):
    """Asof-join BTC 15m regime panel. Gate fires only when parent 15m regime
    agrees with direction."""
    print("\nLoading regime_panel_15m_v2_fixed BTC ...")
    r15 = pd.read_parquet(R15_PATH)
    r15 = r15[r15["asset"] == ASSET].sort_values("ts_us").reset_index(drop=True)
    # ts_us is END of bar; for fire at ws_s+0 (slot_start), parent bar must end <= ws_s
    # We use fire_us as the asof anchor: find the 15m bar whose end is <= fire_us - 1s
    df = df.sort_values("fire_us").reset_index(drop=True)
    lookup_us = df["fire_us"].values - 1_000_000  # 1s epsilon
    r15_ts = r15["ts_us"].values
    r15_label = r15["regime_label"].values
    r15_slope = r15["trend_slope_30m"].values
    idx = np.searchsorted(r15_ts, lookup_us, side="right") - 1
    idx = np.clip(idx, 0, len(r15) - 1)
    valid = idx >= 0
    parent_label = np.where(valid, r15_label[idx], None)
    parent_slope = np.where(valid, r15_slope[idx], np.nan)
    df["parent_15m_regime"] = parent_label
    df["parent_15m_slope_30m"] = parent_slope

    # Gate: parent regime aligns with direction
    p_up = (df["parent_15m_regime"] == "trending_up") & (df["dir_sign"] == 1)
    p_dn = (df["parent_15m_regime"] == "trending_dn") & (df["dir_sign"] == -1)
    df["g_parent_15m_regime_with"] = (p_up | p_dn).astype(np.int8)
    # Looser: any non-ranging + slope agrees with direction
    slope_with = (df["parent_15m_slope_30m"] * df["dir_sign"]) > 0
    df["g_parent_15m_slope_with"] = slope_with.fillna(False).astype(np.int8)
    # Anti-rangebound: skip when parent is ranging (conservative)
    df["g_parent_15m_not_ranging"] = (df["parent_15m_regime"] != "ranging").astype(np.int8)
    print(f"  g_parent_15m_regime_with on rate: {df['g_parent_15m_regime_with'].mean():.4f}")
    print(f"  g_parent_15m_slope_with on rate: {df['g_parent_15m_slope_with'].mean():.4f}")
    print(f"  g_parent_15m_not_ranging on rate: {df['g_parent_15m_not_ranging'].mean():.4f}")
    return df


# ==========================================================================
# Path D: Slot-end OFI (causal validation)
# ==========================================================================
def build_slot_end_ofi(df):
    """For 5m fires with offset >= 240 (i.e. fire_us is within 60s of slot_end),
    compute OFI in the LAST (fire_us - slot_end) seconds before fire_us.

    To preserve causality: feature uses trades in [fire_us - 60s, fire_us - 1s].
    Then we test if direction == sign(OFI).

    For fires at offset < 240: this gate is not applicable (would not be causal
    relative to slot_end-60s). Set to 0 / NA for those.
    """
    print("\nLoading polymarket BTC trade tape ...")
    tr = pd.read_parquet(TRADES_PATH, columns=["timestamp_us", "slug", "outcome", "size", "side", "price"])
    # outcome: 'Up' or 'Down'; side: 'buy' or 'sell'
    # OFI: signed flow on UP token; buy_UP minus sell_UP minus buy_DOWN + sell_DOWN
    # Simpler: Up_buy - Up_sell - Down_buy + Down_sell = "net UP pressure" in USD
    print(f"  trades: {len(tr):,} rows")
    # filter to slugs that appear in df + slot_end within trade range
    fires_late = df[df["fire_offset_s"] >= 240].copy()
    slugs_late = set(fires_late["slug"].unique())
    tr = tr[tr["slug"].isin(slugs_late)].copy()
    print(f"  filtered to late-offset slugs: {len(tr):,} trades on {tr['slug'].nunique()} slugs")
    tr = tr.sort_values(["slug", "timestamp_us"]).reset_index(drop=True)

    # Compute signed_up_usd per trade
    notional = tr["size"].astype(float) * tr["price"].astype(float)
    sign_outcome = np.where(tr["outcome"].str.lower() == "up", 1.0, -1.0)
    sign_side = np.where(tr["side"].str.lower() == "buy", 1.0, -1.0)
    tr["signed_up_usd"] = sign_outcome * sign_side * notional

    # For each LATE fire, sum signed_up_usd over (fire_us - 60s, fire_us - 1s)
    # Use per-slug groupby and asof
    fire_ofi = np.full(len(df), np.nan)
    fire_ofi_total_usd = np.full(len(df), np.nan)
    # Build per-slug index
    slug_groups = tr.groupby("slug")
    late_idx = df.index[df["fire_offset_s"] >= 240].tolist()
    n_done = 0
    for i in late_idx:
        slug = df.at[i, "slug"]
        if slug not in slug_groups.groups:
            continue
        g = slug_groups.get_group(slug)
        t_lo = df.at[i, "fire_us"] - 60_000_000  # 60s window
        t_hi = df.at[i, "fire_us"] - 1_000_000   # 1s epsilon causal
        mask = (g["timestamp_us"].values >= t_lo) & (g["timestamp_us"].values <= t_hi)
        if not mask.any():
            continue
        fire_ofi[i] = float(g.loc[g.index[mask], "signed_up_usd"].sum())
        fire_ofi_total_usd[i] = float((g.loc[g.index[mask], "size"] * g.loc[g.index[mask], "price"]).sum())
        n_done += 1
    print(f"  computed slot-end OFI for {n_done} late-offset fires (offset >= 240)")

    df["slot_end_ofi_60s"] = fire_ofi
    df["slot_end_ofi_total_usd"] = fire_ofi_total_usd
    # Gate: OFI aligns with direction AND total volume > threshold (filter low-conviction)
    ofi_with_dir = (df["slot_end_ofi_60s"] * df["dir_sign"]) > 0
    ofi_strong = df["slot_end_ofi_60s"].abs() > 50.0  # $50 net pressure
    df["g_slot_end_ofi_with"] = (ofi_with_dir & ofi_strong).fillna(False).astype(np.int8)
    # Looser version
    df["g_slot_end_ofi_with_weak"] = (ofi_with_dir & (df["slot_end_ofi_60s"].abs() > 10.0)).fillna(False).astype(np.int8)
    print(f"  g_slot_end_ofi_with rate (over all fires): {df['g_slot_end_ofi_with'].mean():.4f}")
    n_late = (df["fire_offset_s"] >= 240).sum()
    n_late_on = ((df["fire_offset_s"] >= 240) & (df["g_slot_end_ofi_with"] == 1)).sum()
    print(f"  among late offset fires ({n_late}): {n_late_on} pass OFI gate ({n_late_on / max(n_late, 1):.4f})")
    return df


# ==========================================================================
# Path B: 2-leg straddle (UP at offset=30 + DOWN at offset=180 on same slug)
# ==========================================================================
def build_straddle(df):
    """For each slug, combine an UP@offset=30 fire with a DOWN@offset=180 fire.
    Sum PnLs. Return synthetic 2-leg PnL per slug.
    """
    # Note: master_gate has direction picked by sleeve, so a given slug may only have
    # one direction at each offset. Need to look at v3 fires for both directions.
    # For now: use master_gate and pair existing UP fires at off=30 with DOWN at off=180.
    up30 = df[(df["fire_offset_s"] == 30) & (df["dir_sign"] == 1)][["slug", "fire_us", "pnl_legacy_usd", "won_int"]].rename(
        columns={"fire_us": "fire_us_up", "pnl_legacy_usd": "pnl_up", "won_int": "won_up"}
    )
    dn180 = df[(df["fire_offset_s"] == 180) & (df["dir_sign"] == -1)][["slug", "fire_us", "pnl_legacy_usd", "won_int"]].rename(
        columns={"fire_us": "fire_us_dn", "pnl_legacy_usd": "pnl_dn", "won_int": "won_dn"}
    )
    straddle = up30.merge(dn180, on="slug", how="inner")
    if len(straddle) == 0:
        print("  no UP@30 + DOWN@180 pairs found")
        return df, None
    straddle["pnl_straddle"] = straddle["pnl_up"] + straddle["pnl_dn"]
    straddle["won_straddle"] = ((straddle["won_up"] + straddle["won_dn"]) >= 1).astype(np.int8)
    straddle["fire_us"] = straddle["fire_us_dn"]  # use later leg as anchor
    straddle["fire_dt"] = pd.to_datetime(straddle["fire_us"], unit="us", utc=True)
    straddle["fire_date"] = straddle["fire_dt"].dt.date
    print(f"  straddle (UP30 + DN180): n={len(straddle):,}, mean_pnl=${straddle['pnl_straddle'].mean():+.3f}, "
          f"won_either_rate={straddle['won_straddle'].mean():.3f}")
    return df, straddle


# ==========================================================================
# Splits + metrics
# ==========================================================================
def split_28d(df):
    ts_min = df["fire_us"].min()
    ts_max = df["fire_us"].max()
    span = ts_max - ts_min
    cut1 = ts_min + int(span * 15.0 / 24.8)
    cut2 = ts_min + int(span * 20.0 / 24.8)
    tr = df[df["fire_us"] < cut1].copy()
    va = df[(df["fire_us"] >= cut1) & (df["fire_us"] < cut2)].copy()
    lb = df[df["fire_us"] >= cut2].copy()
    return tr, va, lb


def compute_metrics(sub, days_total=None, pnl_col="pnl_legacy_usd"):
    n = len(sub)
    if n == 0:
        return None
    sub = sub.sort_values("fire_us").reset_index(drop=True)
    pnl = sub[pnl_col].values
    won = sub["won_int"].sum() if "won_int" in sub.columns else (sub["won_straddle"].sum() if "won_straddle" in sub.columns else 0)
    wr = won / n
    dpt = float(np.mean(pnl))
    total = float(np.sum(pnl))
    cum = np.cumsum(pnl)
    peak = np.maximum.accumulate(cum)
    max_dd = float(np.max(peak - cum)) if len(cum) else 0.0
    won_col = "won_int" if "won_int" in sub.columns else "won_straddle"
    losses = (sub[won_col] == 0).values.astype(np.int8)
    max_streak = 0
    cur = 0
    for v in losses:
        if v:
            cur += 1; max_streak = max(max_streak, cur)
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


def passes_v7(row):
    n28 = row["n_28d_proj"]
    if not (V7["n_min_28d"] <= n28 <= V7["n_max_28d"]):
        return False, "n_28d_out_of_band"
    if row["wr_lockbox"] < V7["wr_min"]:
        return False, "wr_lockbox_low"
    if row["dpt_25_lockbox"] < V7["dpt_25_min"]:
        return False, "dpt_lockbox_low"
    if row["max_dd_25_lockbox"] > V7["dd_25_max"]:
        return False, "dd_lockbox_high"
    if row["loss_streak_lockbox"] > V7["loss_streak_max"]:
        return False, "loss_streak_long"
    if row["sharpe_lockbox"] < V7["sharpe_min"]:
        return False, "sharpe_lockbox_low"
    if row["bootstrap_p_lockbox"] > V7["bootstrap_p_max"]:
        return False, "bootstrap_p_high"
    return True, "PASS"


def evaluate_candidate(df, mask, sleeve_id, anchor, gate_stack, splits, pnl_col="pnl_legacy_usd",
                       extra=None):
    n_full = int(mask.sum())
    if n_full < 30:
        return None
    tr, va, lb = splits
    fus = df["fire_us"].values
    tr_idx = (fus >= tr["fire_us"].min()) & (fus <= tr["fire_us"].max())
    va_idx = (fus >= va["fire_us"].min()) & (fus <= va["fire_us"].max())
    lb_idx = (fus >= lb["fire_us"].min()) & (fus <= lb["fire_us"].max())
    m = mask.values if isinstance(mask, pd.Series) else mask
    sub_tr = df[m & tr_idx]
    sub_va = df[m & va_idx]
    sub_lb = df[m & lb_idx]
    if len(sub_lb) < 10 or len(sub_tr) < 20:
        return None
    m_full = compute_metrics(df[m], days_total=DAYS_TOTAL, pnl_col=pnl_col)
    m_lb = compute_metrics(sub_lb, days_total=4.8, pnl_col=pnl_col)
    boot = bootstrap_p(sub_lb, 1000, pnl_col=pnl_col)
    won_col = "won_int" if "won_int" in df.columns else "won_straddle"
    out = dict(
        sleeve_id=sleeve_id, anchor=anchor, gate_stack=gate_stack,
        n_full=m_full["n"], n_train=int(len(sub_tr)),
        n_val=int(len(sub_va)), n_lockbox=int(len(sub_lb)),
        wr_train=float(sub_tr[won_col].mean()) if len(sub_tr) else 0.0,
        wr_val=float(sub_va[won_col].mean()) if len(sub_va) else 0.0,
        wr_lockbox=m_lb["wr"],
        dpt_25_train=float(sub_tr[pnl_col].mean()) if len(sub_tr) else 0.0,
        dpt_25_val=float(sub_va[pnl_col].mean()) if len(sub_va) else 0.0,
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
    out["objective"] = out["dpt_25_lockbox"] * np.sqrt(max(out["n_lockbox"], 1))
    if extra is not None:
        out.update(extra)
    return out


# ==========================================================================
# Lottery audit (V7 critical: filter out vwap-tail concentration)
# ==========================================================================
def lottery_audit(df_sub, pnl_col="pnl_legacy_usd"):
    """Estimate lottery concentration. Returns:
      - top5_pct_pnl_share = fraction of total PnL from top 5% of fires
      - n_deep_tail = # of fires with vwap < 0.10 (estimated)
      - deep_tail_pnl_share = fraction of total PnL from those
    """
    if len(df_sub) == 0:
        return {"top5_share": 0.0, "n_deep_tail": 0, "deep_tail_share": 0.0}
    pnl = df_sub[pnl_col].values
    total_pos = pnl[pnl > 0].sum() if (pnl > 0).any() else 1.0
    sorted_pos = np.sort(pnl[pnl > 0])[::-1] if (pnl > 0).any() else np.array([0.0])
    top5n = max(1, int(0.05 * len(pnl)))
    top5_share = float(sorted_pos[:top5n].sum() / max(total_pos, 0.01))
    # Estimate vwap: won-leg pnl ~ (1-vwap)/vwap*25*0.98
    # Deep-tail: pnl > $40 at $25 stake means vwap < ~0.38; pnl > $200 means vwap < 0.11
    n_deep = (pnl > 200).sum()
    deep_share = float(pnl[pnl > 200].sum() / max(total_pos, 0.01))
    return {"top5_share": top5_share, "n_deep_tail": int(n_deep), "deep_tail_share": deep_share}


# ==========================================================================
# Path A: Weighted ensemble search
# ==========================================================================
def path_A_weighted_ensemble(df, splits):
    """Compute training-window weights per gate, then sum-threshold."""
    cands = []
    print("\n[A] Weighted ensemble ...")
    tr, va, lb = splits

    # Subset of gates including new V7 variants
    AVAIL_GATES = [g for g in STRONG_GATES + [
        "g_hurst_strong_trending", "g_hurst_reverting_strict", "g_hurst_regime_with",
        "g_parent_15m_regime_with", "g_parent_15m_slope_with", "g_parent_15m_not_ranging",
        "g_slot_end_ofi_with",
    ] if g in df.columns]
    print(f"  gate pool: {len(AVAIL_GATES)}")

    # Compute per-gate WR-lift on TRAIN+VAL
    fus = df["fire_us"].values
    trva_idx = (fus >= tr["fire_us"].min()) & (fus <= va["fire_us"].max())
    base_wr = df.loc[trva_idx, "won_int"].mean()
    weights = {}
    for g in AVAIL_GATES:
        m_g = (df[g].values == 1) & trva_idx
        n_g = m_g.sum()
        if n_g < 100:
            continue
        wr_g = df.loc[m_g, "won_int"].mean()
        lift = wr_g - base_wr
        # weight = max(0, lift * 100) -- positive lift only, scaled
        weights[g] = max(0.0, lift * 100)
    # Drop zero-weight gates
    weights = {k: v for k, v in weights.items() if v > 0.5}
    print(f"  weights (top 10 by lift):")
    for g, w in sorted(weights.items(), key=lambda kv: -kv[1])[:10]:
        print(f"    {g}: {w:.2f}")

    if len(weights) == 0:
        return cands

    # Compute gate sum per row
    gate_sum = np.zeros(len(df), dtype=np.float64)
    for g, w in weights.items():
        gate_sum += df[g].values.astype(np.float64) * w
    df["_gate_sum"] = gate_sum
    max_sum = sum(weights.values())
    print(f"  max gate_sum: {max_sum:.2f}, achieved: {gate_sum.max():.2f}")

    # Test different thresholds (deciles of gate_sum)
    for q in [0.70, 0.80, 0.85, 0.90, 0.93, 0.95, 0.97]:
        thr = np.quantile(gate_sum[gate_sum > 0], q) if (gate_sum > 0).any() else 0
        m = gate_sum >= thr
        if m.sum() < 50:
            continue
        rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                 f"A_ensemble_q{int(q*100)}_thr{thr:.1f}",
                                 "weighted_ensemble",
                                 f"sum>={thr:.1f}", splits)
        if rec:
            # Add lottery audit
            sub_lb = df[m & (fus >= lb["fire_us"].min()) & (fus <= lb["fire_us"].max())]
            audit = lottery_audit(sub_lb)
            rec.update({"lottery_top5_share": audit["top5_share"],
                        "lottery_n_deep": audit["n_deep_tail"],
                        "lottery_deep_share": audit["deep_tail_share"]})
            cands.append(rec)

    # Also test ensemble + offset stratification
    for off_bin_name, off_set in [("L_late", [150, 180, 210, 240])]:
        m_off = df["fire_offset_s"].isin(off_set).values
        if m_off.sum() < 200:
            continue
        for q in [0.75, 0.85, 0.90, 0.95]:
            base = gate_sum[m_off]
            if not (base > 0).any():
                continue
            thr = np.quantile(base[base > 0], q)
            m = m_off & (gate_sum >= thr)
            if m.sum() < 40:
                continue
            rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                     f"A_ensemble_off_{off_bin_name}_q{int(q*100)}",
                                     f"weighted_ensemble+offset_{off_bin_name}",
                                     f"sum>={thr:.1f}", splits)
            if rec:
                sub_lb = df[m & (fus >= lb["fire_us"].min()) & (fus <= lb["fire_us"].max())]
                audit = lottery_audit(sub_lb)
                rec.update({"lottery_top5_share": audit["top5_share"],
                            "lottery_n_deep": audit["n_deep_tail"],
                            "lottery_deep_share": audit["deep_tail_share"]})
                cands.append(rec)
    print(f"  +{len(cands)} candidates")
    return cands, weights


# ==========================================================================
# Path D: Slot-end OFI sleeves
# ==========================================================================
def path_D_slot_end_ofi(df, splits):
    """Test sleeves using g_slot_end_ofi_with (only valid for offset>=240).
    Combine with 1-2 other strong gates."""
    print("\n[D] Slot-end OFI sleeves ...")
    cands = []
    if "g_slot_end_ofi_with" not in df.columns:
        return cands
    fus = df["fire_us"].values
    # Restrict to offset >= 240
    m_late = df["fire_offset_s"].isin([240, 255, 270]).values
    print(f"  late-offset fires: {m_late.sum()}")
    m_base = m_late & (df["g_slot_end_ofi_with"].values == 1)
    print(f"  with strong OFI: {m_base.sum()}")
    if m_base.sum() < 50:
        # Try weak OFI version
        m_base = m_late & (df["g_slot_end_ofi_with_weak"].values == 1)
        print(f"  with weak OFI: {m_base.sum()}")

    if m_base.sum() < 30:
        return cands

    # OFI alone
    rec = evaluate_candidate(df, pd.Series(m_base, index=df.index),
                             "D_ofi_alone_off240plus", "offset_L_late_ofi",
                             "g_slot_end_ofi_with", splits)
    if rec:
        sub_lb = df[m_base & (fus >= splits[2]["fire_us"].min()) & (fus <= splits[2]["fire_us"].max())]
        audit = lottery_audit(sub_lb)
        rec.update({"lottery_top5_share": audit["top5_share"],
                    "lottery_n_deep": audit["n_deep_tail"],
                    "lottery_deep_share": audit["deep_tail_share"]})
        cands.append(rec)

    # OFI + 1 strong gate
    for g in STRONG_GATES:
        if g not in df.columns:
            continue
        m = m_base & (df[g].values == 1)
        if m.sum() < 30:
            continue
        gs = f"g_slot_end_ofi_with+{g}"
        rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                 f"D_ofi+{g}", "offset_L_late_ofi", gs, splits)
        if rec:
            sub_lb = df[m & (fus >= splits[2]["fire_us"].min()) & (fus <= splits[2]["fire_us"].max())]
            audit = lottery_audit(sub_lb)
            rec.update({"lottery_top5_share": audit["top5_share"],
                        "lottery_n_deep": audit["n_deep_tail"],
                        "lottery_deep_share": audit["deep_tail_share"]})
            cands.append(rec)

    # OFI + 2 strong gates (combinatorial)
    for combo in itertools.combinations(STRONG_GATES, 2):
        m = m_base.copy()
        for g in combo:
            if g in df.columns:
                m &= (df[g].values == 1)
        if m.sum() < 25:
            continue
        gs = f"g_slot_end_ofi_with+{'+'.join(combo)}"
        rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                 f"D_ofi+{'+'.join(combo)}",
                                 "offset_L_late_ofi", gs, splits)
        if rec:
            sub_lb = df[m & (fus >= splits[2]["fire_us"].min()) & (fus <= splits[2]["fire_us"].max())]
            audit = lottery_audit(sub_lb)
            rec.update({"lottery_top5_share": audit["top5_share"],
                        "lottery_n_deep": audit["n_deep_tail"],
                        "lottery_deep_share": audit["deep_tail_share"]})
            cands.append(rec)
    print(f"  +{len(cands)} candidates")
    return cands


# ==========================================================================
# Path H: Hurst variants
# ==========================================================================
def path_H_hurst(df, splits):
    """Test g_hurst_strong_trending and g_hurst_regime_with in combos."""
    print("\n[H] Hurst variants ...")
    cands = []
    fus = df["fire_us"].values
    HURST_GATES = ["g_hurst_strong_trending", "g_hurst_regime_with", "g_hurst_reverting_strict"]
    for hg in HURST_GATES:
        if hg not in df.columns:
            continue
        m_h = (df[hg].values == 1)
        if m_h.sum() < 100:
            continue
        # Alone
        rec = evaluate_candidate(df, pd.Series(m_h, index=df.index),
                                 f"H_{hg}_alone", "hurst_only", hg, splits)
        if rec:
            sub_lb = df[m_h & (fus >= splits[2]["fire_us"].min()) & (fus <= splits[2]["fire_us"].max())]
            audit = lottery_audit(sub_lb)
            rec.update({"lottery_top5_share": audit["top5_share"],
                        "lottery_n_deep": audit["n_deep_tail"],
                        "lottery_deep_share": audit["deep_tail_share"]})
            cands.append(rec)
        # + 1 strong gate
        for g in STRONG_GATES:
            if g in df.columns and g != hg:
                m = m_h & (df[g].values == 1)
                if m.sum() < 50:
                    continue
                gs = f"{hg}+{g}"
                rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                         f"H_{gs}", "hurst+strong", gs, splits)
                if rec:
                    sub_lb = df[m & (fus >= splits[2]["fire_us"].min()) & (fus <= splits[2]["fire_us"].max())]
                    audit = lottery_audit(sub_lb)
                    rec.update({"lottery_top5_share": audit["top5_share"],
                                "lottery_n_deep": audit["n_deep_tail"],
                                "lottery_deep_share": audit["deep_tail_share"]})
                    cands.append(rec)
        # + 2 strong gates
        for combo in itertools.combinations(STRONG_GATES, 2):
            if hg in combo:
                continue
            m = m_h.copy()
            for g in combo:
                if g in df.columns:
                    m &= (df[g].values == 1)
            if m.sum() < 30:
                continue
            gs = f"{hg}+{'+'.join(combo)}"
            rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                     f"H_{gs}", "hurst+strong+strong", gs, splits)
            if rec:
                sub_lb = df[m & (fus >= splits[2]["fire_us"].min()) & (fus <= splits[2]["fire_us"].max())]
                audit = lottery_audit(sub_lb)
                rec.update({"lottery_top5_share": audit["top5_share"],
                            "lottery_n_deep": audit["n_deep_tail"],
                            "lottery_deep_share": audit["deep_tail_share"]})
                cands.append(rec)
    print(f"  +{len(cands)} candidates")
    return cands


# ==========================================================================
# Path F: 15m parent regime confluence
# ==========================================================================
def path_F_parent_15m(df, splits):
    """Gate fires only when parent 15m regime aligns. Stack with 1-2 other gates."""
    print("\n[F] Parent 15m regime confluence ...")
    cands = []
    fus = df["fire_us"].values
    PARENT_GATES = ["g_parent_15m_regime_with", "g_parent_15m_slope_with", "g_parent_15m_not_ranging"]
    for pg in PARENT_GATES:
        if pg not in df.columns:
            continue
        m_p = (df[pg].values == 1)
        if m_p.sum() < 100:
            continue
        # Alone
        rec = evaluate_candidate(df, pd.Series(m_p, index=df.index),
                                 f"F_{pg}_alone", "parent_15m_only", pg, splits)
        if rec:
            sub_lb = df[m_p & (fus >= splits[2]["fire_us"].min()) & (fus <= splits[2]["fire_us"].max())]
            audit = lottery_audit(sub_lb)
            rec.update({"lottery_top5_share": audit["top5_share"],
                        "lottery_n_deep": audit["n_deep_tail"],
                        "lottery_deep_share": audit["deep_tail_share"]})
            cands.append(rec)
        # + 1 strong gate
        for g in STRONG_GATES:
            if g in df.columns:
                m = m_p & (df[g].values == 1)
                if m.sum() < 50:
                    continue
                gs = f"{pg}+{g}"
                rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                         f"F_{gs}", "parent_15m+strong", gs, splits)
                if rec:
                    sub_lb = df[m & (fus >= splits[2]["fire_us"].min()) & (fus <= splits[2]["fire_us"].max())]
                    audit = lottery_audit(sub_lb)
                    rec.update({"lottery_top5_share": audit["top5_share"],
                                "lottery_n_deep": audit["n_deep_tail"],
                                "lottery_deep_share": audit["deep_tail_share"]})
                    cands.append(rec)
        # + 2 strong gates
        for combo in itertools.combinations(STRONG_GATES, 2):
            m = m_p.copy()
            for g in combo:
                if g in df.columns:
                    m &= (df[g].values == 1)
            if m.sum() < 30:
                continue
            gs = f"{pg}+{'+'.join(combo)}"
            rec = evaluate_candidate(df, pd.Series(m, index=df.index),
                                     f"F_{gs}", "parent_15m+r2", gs, splits)
            if rec:
                sub_lb = df[m & (fus >= splits[2]["fire_us"].min()) & (fus <= splits[2]["fire_us"].max())]
                audit = lottery_audit(sub_lb)
                rec.update({"lottery_top5_share": audit["top5_share"],
                            "lottery_n_deep": audit["n_deep_tail"],
                            "lottery_deep_share": audit["deep_tail_share"]})
                cands.append(rec)
    print(f"  +{len(cands)} candidates")
    return cands


# ==========================================================================
# Path B: 2-leg straddle
# ==========================================================================
def path_B_straddle(straddle, splits):
    """Evaluate the 2-leg straddle as a synthetic sleeve and gate variants."""
    print("\n[B] 2-leg straddle ...")
    cands = []
    if straddle is None or len(straddle) == 0:
        return cands
    # Compute splits for straddle
    tr_min = splits[0]["fire_us"].min()
    tr_max = splits[0]["fire_us"].max()
    va_max = splits[1]["fire_us"].max()
    lb_min = splits[2]["fire_us"].min()
    lb_max = splits[2]["fire_us"].max()

    s = straddle.sort_values("fire_us").reset_index(drop=True)
    fus = s["fire_us"].values
    s_tr = s[(fus >= tr_min) & (fus <= tr_max)]
    s_va = s[(fus > tr_max) & (fus <= va_max)]
    s_lb = s[(fus >= lb_min) & (fus <= lb_max)]

    if len(s_lb) < 10:
        return cands

    m_full = compute_metrics(s, days_total=DAYS_TOTAL, pnl_col="pnl_straddle")
    m_lb = compute_metrics(s_lb, days_total=4.8, pnl_col="pnl_straddle")
    boot = bootstrap_p(s_lb, 1000, pnl_col="pnl_straddle")

    rec = dict(
        sleeve_id="B_straddle_UP30_DN180",
        anchor="straddle_2leg",
        gate_stack="no_gates",
        n_full=m_full["n"],
        n_train=int(len(s_tr)),
        n_val=int(len(s_va)),
        n_lockbox=int(len(s_lb)),
        wr_train=float(s_tr["won_straddle"].mean()) if len(s_tr) else 0.0,
        wr_val=float(s_va["won_straddle"].mean()) if len(s_va) else 0.0,
        wr_lockbox=m_lb["wr"],
        dpt_25_train=float(s_tr["pnl_straddle"].mean()) if len(s_tr) else 0.0,
        dpt_25_val=float(s_va["pnl_straddle"].mean()) if len(s_va) else 0.0,
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
    rec["objective"] = rec["dpt_25_lockbox"] * np.sqrt(max(rec["n_lockbox"], 1))
    cands.append(rec)
    print(f"  straddle: n={rec['n_full']}, wr_lb={rec['wr_lockbox']:.3f}, "
          f"dpt_lb=${rec['dpt_25_lockbox']:+.2f}, sum_lb=${rec['sum_25_lockbox']:+.1f}")
    return cands


# ==========================================================================
# Cumulative PnL plot
# ==========================================================================
def plot_cumpnl(df_sub, sleeve_id, out_path, pnl_col="pnl_legacy_usd"):
    sub = df_sub.sort_values("fire_us").reset_index(drop=True)
    if len(sub) < 5:
        return
    cum = sub[pnl_col].cumsum().values
    dt = pd.to_datetime(sub["fire_us"], unit="us", utc=True)
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7), sharex=True,
                                    gridspec_kw={"height_ratios": [3, 1]})
    ax1.plot(dt, cum, lw=1.5, color="navy", label=f"Cum PnL (sum=${cum[-1]:+.1f})")
    ax1.set_title(f"BTC 5m V7 — {sleeve_id}\nn={len(sub)}, $/tr=${sub[pnl_col].mean():+.2f}")
    ax1.set_ylabel("Cumulative PnL ($25 stake)")
    ax1.grid(alpha=0.3)
    ax1.legend()
    ax2.fill_between(dt, 0, -dd, color="firebrick", alpha=0.4, label=f"DD (max=${dd.max():.1f})")
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
    print("SNIPER SEARCH V7 — BTC 5m")
    print("=" * 72)
    df = load_universe()
    df = build_hurst_variants(df)
    df = build_parent_15m(df)
    # Path D requires loading Polymarket trades — heavier. Cache to sandbox first.
    cache_d = SAND / "df_with_ofi.parquet"
    if cache_d.exists():
        print("\nLoading cached df with OFI ...")
        df = pd.read_parquet(cache_d)
        # restore fire_dt
        df["fire_dt"] = pd.to_datetime(df["fire_us"], unit="us", utc=True)
        df["fire_date"] = df["fire_dt"].dt.date
    else:
        df = build_slot_end_ofi(df)
        df.to_parquet(cache_d)
    df, straddle = build_straddle(df)

    splits = split_28d(df)
    tr, va, lb = splits
    print(f"\nSplit train={len(tr):,} ({tr['fire_dt'].min().date()} -> {tr['fire_dt'].max().date()})")
    print(f"      val={len(va):,} ({va['fire_dt'].min().date()} -> {va['fire_dt'].max().date()})")
    print(f"      lockbox={len(lb):,} ({lb['fire_dt'].min().date()} -> {lb['fire_dt'].max().date()})")

    all_cands = []

    A_cands, weights = path_A_weighted_ensemble(df, splits)
    all_cands.extend(A_cands)

    D_cands = path_D_slot_end_ofi(df, splits)
    all_cands.extend(D_cands)

    H_cands = path_H_hurst(df, splits)
    all_cands.extend(H_cands)

    F_cands = path_F_parent_15m(df, splits)
    all_cands.extend(F_cands)

    B_cands = path_B_straddle(straddle, splits)
    all_cands.extend(B_cands)

    print(f"\nTotal candidates: {len(all_cands)}")
    cdf = pd.DataFrame(all_cands)
    statuses = cdf.apply(passes_v7, axis=1)
    cdf["pass"] = [s[0] for s in statuses]
    cdf["fail_reason"] = [s[1] for s in statuses]
    cdf = cdf.sort_values(["pass", "objective", "dpt_25_lockbox"], ascending=[False, False, False])
    cdf.to_csv(OUT / "all_candidates_v7.csv", index=False)
    print(f"Wrote all_candidates_v7.csv ({len(cdf)} rows)")

    passers = cdf[cdf["pass"]].copy()
    print(f"\nPassers (all 7 V7 criteria): {len(passers)}")
    if len(passers) > 0:
        cols = ["sleeve_id", "anchor", "gate_stack", "n_lockbox", "n_28d_proj",
                "wr_lockbox", "dpt_25_lockbox", "max_dd_25_lockbox",
                "loss_streak_lockbox", "sharpe_lockbox", "bootstrap_p_lockbox",
                "objective"]
        if "lottery_deep_share" in passers.columns:
            cols.append("lottery_deep_share")
        print(passers[cols].head(30).to_string(index=False))

    # Dedup by metric signature
    sig_cols = ["n_full", "wr_lockbox", "dpt_25_lockbox", "loss_streak_lockbox"]
    passers["_sig"] = passers[sig_cols].apply(lambda r: hash(tuple(np.round(r.values, 4))), axis=1)
    deduped = passers.drop_duplicates("_sig").drop(columns=["_sig"])
    deduped = deduped.sort_values("objective", ascending=False)
    print(f"\nAfter metric-sig dedup: {len(deduped)}")

    # Save weights (for transparency)
    pd.DataFrame([(g, w) for g, w in sorted(weights.items(), key=lambda kv: -kv[1])],
                 columns=["gate", "weight"]).to_csv(OUT / "ensemble_weights.csv", index=False)
    print(f"Wrote ensemble_weights.csv ({len(weights)} gates)")

    # Save dataframe state for finalization
    df.to_parquet(SAND / "universe_v7.parquet")
    return df, cdf, deduped, splits, straddle


if __name__ == "__main__":
    main()
