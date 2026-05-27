"""Compute all gates on the BTC 15m master panel.

CRITICAL: g_trend_slope_with is REBUILT from the bug-fixed regime panel
(trend_slope_30m column). The old gate was derived from leaky panel.

Output: data/v4/canonical/_results/sniper_btc15m_gated.parquet
"""
import time, os
import numpy as np
import pandas as pd

RES = "data/v4/canonical/_results"
IN = f"{RES}/sniper_btc15m_master.parquet"
OUT = f"{RES}/sniper_btc15m_gated.parquet"

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)

log("loading master panel")
df = pd.read_parquet(IN)
log(f"rows: {len(df)}, cols: {len(df.columns)}")

dir_up = (df["direction"] == "UP")
dir_dn = (df["direction"] == "DOWN")
ds = np.where(dir_up, 1, -1)

def g(cond):
    """Convert bool series to int8 with NaN->0."""
    return cond.fillna(False).astype("int8").values

# ============================================================
# R1 — base gates
# ============================================================

# RF / range filter
if "rf_dir" in df.columns:
    rf_with = ((df["rf_dir"] > 0) & dir_up) | ((df["rf_dir"] < 0) & dir_dn)
    df["g_rf_with"] = g(rf_with)
    if "rf_dir_age" in df.columns:
        df["g_rf_fresh"] = g(rf_with & (df["rf_dir_age"].abs() <= 30))
        df["g_rf_aged"] = g(rf_with & (df["rf_dir_age"].abs() > 30))
    if "rf_dist_bps" in df.columns:
        df["g_rf_strong"] = g(rf_with & (df["rf_dist_bps"].abs() > 10))

# TR EMA stack
if "tr_ema_stack_score" in df.columns:
    df["g_tr_stack_with"] = g(
        ((df["tr_ema_stack_score"] >= 1) & dir_up) |
        ((df["tr_ema_stack_score"] <= -1) & dir_dn)
    )
    df["g_tr_stack_full_with"] = g(
        ((df["tr_ema_stack_score"] == 2) & dir_up) |
        ((df["tr_ema_stack_score"] == -2) & dir_dn)
    )

# tr_pvsra
if "tr_pvsra" in df.columns:
    df["g_tr_pvsra_with"] = g(
        ((df["tr_pvsra"] > 0) & dir_up) | ((df["tr_pvsra"] < 0) & dir_dn)
    )

# above EMAs
for ema in ("ema50", "ema200", "ema800"):
    col = f"tr_close_vs_{ema}"
    if col in df.columns:
        df[f"g_tr_above_{ema}"] = g(
            ((df[col] > 0) & dir_up) | ((df[col] < 0) & dir_dn)
        )

# above PP
if "tr_above_pp" in df.columns:
    df["g_tr_above_pp"] = g(
        ((df["tr_above_pp"] > 0) & dir_up) | ((df["tr_above_pp"] == 0) & dir_dn)
    )

# Sessions
if "tr_within_adr" in df.columns:
    df["g_tr_within_adr"] = g(df["tr_within_adr"] > 0)

if all(c in df.columns for c in ("tr_in_london", "tr_in_ny", "tr_eu_brinks", "tr_us_brinks")):
    df["g_tr_in_active_session"] = g(
        (df["tr_in_london"] > 0) | (df["tr_in_ny"] > 0) |
        (df["tr_eu_brinks"] > 0) | (df["tr_us_brinks"] > 0)
    )

# Above cloud
if "tr_ema_cloud_pos" in df.columns:
    df["g_tr_above_cloud"] = g(
        ((df["tr_ema_cloud_pos"] > 1.0) & dir_up) | ((df["tr_ema_cloud_pos"] < 0.0) & dir_dn)
    )

# Ribbon
if "ribbon_color" in df.columns:
    df["g_ribbon_agrees"] = g(
        (df["ribbon_color"].isin([1, 4]) & dir_up) |
        (df["ribbon_color"].isin([2, 3]) & dir_dn)
    )
if "ribbon_lead_slope_bps" in df.columns:
    df["g_ribbon_slope_with"] = g(
        ((df["ribbon_lead_slope_bps"] > 0) & dir_up) |
        ((df["ribbon_lead_slope_bps"] < 0) & dir_dn)
    )
if "ribbon_compression_bps" in df.columns:
    df["g_tight_ribbon"] = g(df["ribbon_compression_bps"] < 2.0)

# Oscillators
if "bb_pos_60s" in df.columns:
    df["g_bb_pos_with"] = g(
        ((df["bb_pos_60s"] > 0.5) & dir_up) | ((df["bb_pos_60s"] < 0.5) & dir_dn)
    )
if "stoch_k_60s" in df.columns:
    df["g_stoch_with"] = g(
        ((df["stoch_k_60s"] > 50) & dir_up) | ((df["stoch_k_60s"] < 50) & dir_dn)
    )
if "mfi_60s" in df.columns:
    df["g_mfi_with"] = g(
        ((df["mfi_60s"] > 50) & dir_up) | ((df["mfi_60s"] < 50) & dir_dn)
    )
if "cci_60s" in df.columns:
    df["g_cci_with"] = g(
        ((df["cci_60s"] > 0) & dir_up) | ((df["cci_60s"] < 0) & dir_dn)
    )

# vwap_since_open dev gates (vwap_since_open_bps already exists)
if "vwap_since_open_bps" in df.columns:
    dev = df["vwap_since_open_bps"]
    df["g_within_dev"] = g(
        (dev.abs() > 5.0) & (((dev > 0) & dir_up) | ((dev < 0) & dir_dn))
    )
    df["g_dev_extreme"] = g(
        (dev.abs() > 15.0) & (((dev > 0) & dir_up) | ((dev < 0) & dir_dn))
    )
    df["g_vwap_ge_50_le_85"] = g((dev.abs() >= 50) & (dev.abs() <= 85))

# ============================================================
# R3 — vol / regime / hurst / flow
# ============================================================

# Vol regime (use realized_vol_60m percentile within recent window — use simple cutoffs)
if "realized_vol_60m" in df.columns:
    rv = df["realized_vol_60m"]
    rv_med = rv.median()
    rv_q75 = rv.quantile(0.75)
    rv_q25 = rv.quantile(0.25)
    df["g_vol_high"] = g(rv > rv_q75)
    df["g_vol_expanding"] = g(rv > rv_med)
    df["g_vol_contracting"] = g(rv < rv_q25)

# Coinbase basis (not present in BTC 15m panel) — skip

# ============================================================
# R4 — REBUILT g_trend_slope_with (CRITICAL)
# ============================================================
if "trend_slope_30m" in df.columns:
    ts30 = df["trend_slope_30m"]
    # g_trend_slope_with: slope sign agrees with BET direction
    cond = ((ts30 > 0) & dir_up) | ((ts30 < 0) & dir_dn)
    df["g_trend_slope_with"] = g(cond & ts30.notna())
    # strong: top quartile of |slope| in same direction
    abs_slope = ts30.abs()
    thr = abs_slope.quantile(0.75)
    cond_strong = ((ts30 > thr) & dir_up) | ((ts30 < -thr) & dir_dn)
    df["g_trend_slope_strong_with"] = g(cond_strong & ts30.notna())

# Imbalance gates - up_imb5 / dn_imb5 from microstructure_panel are PER-DIRECTION token
# For directional gate: use up_imb5 if betting UP, dn_imb5 if DOWN
if "up_imb5" in df.columns and "dn_imb5" in df.columns:
    imb_dir = np.where(dir_up, df["up_imb5"], df["dn_imb5"])
    df["g_imb5_strong_with"] = g(pd.Series(imb_dir > 0.3, index=df.index))

if "up_queue_top_bid" in df.columns and "dn_queue_top_bid" in df.columns:
    q = np.where(dir_up, df["up_queue_top_bid"], df["dn_queue_top_bid"])
    q_med = pd.Series(q).median()
    df["g_queue_top_high"] = g(pd.Series(q > q_med, index=df.index))

if "up_imb5_change_500ms" in df.columns:
    chg = df["up_imb5_change_500ms"]
    df["g_imb_change_with"] = g(((chg > 0) & dir_up) | ((chg < 0) & dir_dn))

# Book slope steep against (acts as filter — high slope means market is loaded against us)
if "up_bid_slope" in df.columns and "up_ask_slope" in df.columns:
    diff_up = df["up_bid_slope"] - df["up_ask_slope"]
    diff_dn = df["dn_bid_slope"] - df["dn_ask_slope"]
    # "steep against" = book leaning AGAINST us — use as skip filter inverted
    # g_book_slope_steep_against fires when book IS against us → bad signal
    # For a positive sleeve we'd want NOT this; but we leave as fire-if-against
    diff_steep_against = np.where(dir_up, diff_up < diff_up.quantile(0.25),
                                  diff_dn < diff_dn.quantile(0.25))
    df["g_book_slope_steep_against"] = g(pd.Series(diff_steep_against, index=df.index))
    # ADD: g_book_slope_with_us = inverse (positive selector)
    diff_with_us = np.where(dir_up, diff_up > diff_up.quantile(0.75),
                            diff_dn > diff_dn.quantile(0.75))
    df["g_book_slope_with_us"] = g(pd.Series(diff_with_us, index=df.index))

# ============================================================
# R5 — microprice / lee-mykland / hawkes
# ============================================================

# g_mp_no_extreme (universal tradability filter): mp |dev| < 100bps on both sides
if "mp_up_dev_bps" in df.columns and "mp_dn_dev_bps" in df.columns:
    no_extreme = (df["mp_up_dev_bps"].abs() < 100) & (df["mp_dn_dev_bps"].abs() < 100)
    df["g_mp_no_extreme"] = g(no_extreme.fillna(False))
    # Looser 150bps version
    df["g_mp_no_extreme_150"] = g(
        ((df["mp_up_dev_bps"].abs() < 150) & (df["mp_dn_dev_bps"].abs() < 150)).fillna(False)
    )

# mp_skew_with_dir: skew agreeing with direction
if "mp_skew" in df.columns:
    df["g_mp_skew_with"] = g(
        ((df["mp_skew"] > 0.05) & dir_up) | ((df["mp_skew"] < -0.05) & dir_dn)
    )
if "mp_skew_change_500ms" in df.columns:
    chg = df["mp_skew_change_500ms"]
    df["g_mp_change_with"] = g(((chg > 0) & dir_up) | ((chg < 0) & dir_dn))

# lee-mykland L_stat high (active markets only) — uses ws_s asof
if "lm_L_stat" in df.columns:
    Lq = df["lm_L_stat"].abs().quantile(0.75)
    df["g_lm_high_stat"] = g((df["lm_L_stat"].abs() > Lq).fillna(False))
    df["g_lm_extreme_against"] = g(
        (df["lm_L_stat"].abs() > Lq) &
        (((df["lm_L_stat"] > 0) & dir_dn) | ((df["lm_L_stat"] < 0) & dir_up))
    )

# Jump direction agreeing (rare gate)
if "jump_dir_01" in df.columns:
    df["g_jump_dir_with"] = g(
        ((df["jump_dir_01"] > 0) & dir_up) | ((df["jump_dir_01"] < 0) & dir_dn)
    )

# Hawkes imbalance with
if "hawkes_lambda_imbalance" in df.columns:
    df["g_hawkes_imbalance_with"] = g(
        ((df["hawkes_lambda_imbalance"] > 0.1) & dir_up) |
        ((df["hawkes_lambda_imbalance"] < -0.1) & dir_dn)
    )
    df["g_hawkes_imb_with_loose"] = g(
        ((df["hawkes_lambda_imbalance"] > 0.05) & dir_up) |
        ((df["hawkes_lambda_imbalance"] < -0.05) & dir_dn)
    )

# VPIN regime filter (skip when vpin is extreme — toxic flow)
if "vpin_zscore" in df.columns:
    df["g_vpin_calm"] = g(df["vpin_zscore"].abs() < 1.0)

# ============================================================
# F7 RSI gates (at ws_s)
# ============================================================
if "f7_rsi_at_ws" in df.columns:
    r = df["f7_rsi_at_ws"]
    # bullish: RSI > 50, mid range; bearish: < 50
    df["g_f7_rsi_with"] = g(((r > 50) & dir_up) | ((r < 50) & dir_dn))
    # extreme RSI agreement
    df["g_f7_rsi_extreme_with"] = g(((r > 70) & dir_up) | ((r < 30) & dir_dn))
    df["g_f7_rsi_mid"] = g((r >= 40) & (r <= 60))
    df["g_f7_rsi_strong_with"] = g(((r > 60) & dir_up) | ((r < 40) & dir_dn))

# ============================================================
# Markov regime (m1v not in hybrid_features, but sms has trend_strength_raw)
# ============================================================
if "sms_trend_strength" in df.columns:
    ts = df["sms_trend_strength"]
    df["g_sms_trend_with"] = g(((ts > 0) & dir_up) | ((ts < 0) & dir_dn))
    df["g_sms_trend_strong_with"] = g(((ts > 3) & dir_up) | ((ts < -3) & dir_dn))

if "sms_rsi_14" in df.columns:
    r = df["sms_rsi_14"]
    df["g_sms_rsi_with"] = g(((r > 50) & dir_up) | ((r < 50) & dir_dn))
    df["g_sms_rsi_mid"] = g((r >= 40) & (r <= 60))
    df["g_sms_rsi_extreme_with"] = g(((r > 70) & dir_up) | ((r < 30) & dir_dn))

if "sms_cvd_sign" in df.columns:
    cs = df["sms_cvd_sign"]
    df["g_sms_cvd_with"] = g(((cs > 0) & dir_up) | ((cs < 0) & dir_dn))

# SMS BOS / CHOCH
if "sms_bos_buy" in df.columns and "sms_bos_sell" in df.columns:
    df["g_sms_bos_with"] = g(
        ((df["sms_bos_buy"] > 0) & dir_up) | ((df["sms_bos_sell"] > 0) & dir_dn)
    )

# regime label gates
if "regime_label" in df.columns:
    rl = df["regime_label"].astype(str)
    df["g_regime_trending"] = g(rl == "trending")
    df["g_regime_ranging"] = g(rl == "ranging")
    df["g_regime_breakout"] = g(rl == "breakout")
    df["g_regime_compressing"] = g(rl == "compressing")

# adx > 25 (trending)
if "adx_14" in df.columns:
    df["g_adx_trending"] = g(df["adx_14"] > 25)
    df["g_adx_strong"] = g(df["adx_14"] > 30)

# session brink filter
if "tr_eu_brinks" in df.columns and "tr_us_brinks" in df.columns:
    df["g_in_eu_us_brinks"] = g((df["tr_eu_brinks"] > 0) | (df["tr_us_brinks"] > 0))

# Microprice extreme dev for OUR side (entry-side liquidity check)
if "mp_up_dev_bps" in df.columns and "mp_dn_dev_bps" in df.columns:
    mp_dev_dir = np.where(dir_up, df["mp_up_dev_bps"], df["dn_mp_dev_bps"] if "dn_mp_dev_bps" in df.columns else df["mp_dn_dev_bps"])
    df["g_mp_our_side_calm"] = g(pd.Series(np.abs(mp_dev_dir) < 80, index=df.index).fillna(False))

# Save
log(f"final cols: {len(df.columns)}")
gate_cols = [c for c in df.columns if c.startswith("g_")]
log(f"gate cols: {len(gate_cols)} - {gate_cols}")
df.to_parquet(OUT, index=False)
log(f"DONE: {OUT} ({os.path.getsize(OUT)/1e6:.1f} MB)")

# Summary
print()
print("=== Gate fire counts ===")
for c in sorted(gate_cols):
    pct = df[c].mean() * 100
    print(f"  {c:35s}: {df[c].sum():>6d} ({pct:5.1f}%)")
