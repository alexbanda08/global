"""Compute gates on the v3 BTC 15m panel.

Adds R3/R4/R5/R7 gates on top of the 23 R1 gates already pre-computed in the
v3 fires file.

CRITICAL: g_trend_slope_with is computed from trend_slope_30m which came
from regime_panel_15m_v2_fixed (bug-fixed). Per brief, this is the
load-bearing gate for the 15m family.

Output: data/v4/canonical/_results/sniper_btc15m_v3_gated.parquet
"""
import os, time
import numpy as np
import pandas as pd

RES = "data/v4/canonical/_results"
IN = f"{RES}/sniper_btc15m_v3_panel.parquet"
OUT = f"{RES}/sniper_btc15m_v3_gated.parquet"

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)


log("loading v3 panel")
df = pd.read_parquet(IN)
log(f"rows: {len(df)}, cols: {len(df.columns)}")

dir_up = (df["direction"] == "UP")
dir_dn = (df["direction"] == "DOWN")
ds = np.where(dir_up, 1, -1)


def g(cond):
    return cond.fillna(False).astype("int8").values


# ============================================================
# R4 - trend slope (rebuilt from regime_panel_15m_v2_fixed)
# ============================================================
if "trend_slope_30m" in df.columns:
    ts30 = df["trend_slope_30m"]
    cond = ((ts30 > 0) & dir_up) | ((ts30 < 0) & dir_dn)
    df["g_trend_slope_with"] = g(cond & ts30.notna())
    abs_slope = ts30.abs()
    thr = abs_slope.quantile(0.75)
    cond_strong = ((ts30 > thr) & dir_up) | ((ts30 < -thr) & dir_dn)
    df["g_trend_slope_strong_with"] = g(cond_strong & ts30.notna())
    log(f"trend_slope_with thr (75th pct of |trend_slope_30m|): {thr:.6f}")

# Regime label gates (labels: ranging / trending_up / trending_dn)
if "regime_label" in df.columns:
    rl = df["regime_label"].astype(str)
    df["g_regime_ranging"] = g(rl == "ranging")
    df["g_regime_trending_with"] = g(((rl == "trending_up") & dir_up) | ((rl == "trending_dn") & dir_dn))
    df["g_regime_trending_either"] = g(rl.isin(["trending_up", "trending_dn"]))

# ADX gates
if "adx_14" in df.columns:
    df["g_adx_trending"] = g(df["adx_14"] > 25)
    df["g_adx_strong"] = g(df["adx_14"] > 30)

# DI agree with dir
if "plus_di_14" in df.columns and "minus_di_14" in df.columns:
    pd_di = df["plus_di_14"]
    md_di = df["minus_di_14"]
    df["g_di_agrees"] = g(((pd_di > md_di) & dir_up) | ((pd_di < md_di) & dir_dn))

# realized vol regime
if "realized_vol_60m" in df.columns:
    rv = df["realized_vol_60m"]
    rv_med = rv.median()
    rv_q75 = rv.quantile(0.75)
    rv_q25 = rv.quantile(0.25)
    df["g_vol_high"] = g(rv > rv_q75)
    df["g_vol_expanding"] = g(rv > rv_med)
    df["g_vol_contracting"] = g(rv < rv_q25)

# regime tr ema stack
if "regime_tr_ema_stack_score" in df.columns:
    rs = df["regime_tr_ema_stack_score"]
    df["g_regime_stack_with"] = g(((rs >= 1) & dir_up) | ((rs <= -1) & dir_dn))
    df["g_regime_stack_full_with"] = g(((rs == 2) & dir_up) | ((rs == -2) & dir_dn))


# ============================================================
# R5 - microprice
# ============================================================
if "mp_up_dev_bps" in df.columns and "mp_dn_dev_bps" in df.columns:
    df["g_mp_no_extreme"] = g(((df["mp_up_dev_bps"].abs() < 100) & (df["mp_dn_dev_bps"].abs() < 100)).fillna(False))
    df["g_mp_no_extreme_150"] = g(((df["mp_up_dev_bps"].abs() < 150) & (df["mp_dn_dev_bps"].abs() < 150)).fillna(False))
    # Our side calm (entry side has low dev → cheap to fill)
    mp_dev_dir = np.where(dir_up, df["mp_up_dev_bps"], df["mp_dn_dev_bps"])
    df["g_mp_our_side_calm"] = g(pd.Series(np.abs(mp_dev_dir) < 80, index=df.index).fillna(False))

if "mp_skew" in df.columns:
    df["g_mp_skew_with"] = g(((df["mp_skew"] > 0.05) & dir_up) | ((df["mp_skew"] < -0.05) & dir_dn))
    df["g_mp_skew_strong_with"] = g(((df["mp_skew"] > 0.2) & dir_up) | ((df["mp_skew"] < -0.2) & dir_dn))

if "mp_skew_change_500ms" in df.columns:
    chg = df["mp_skew_change_500ms"]
    df["g_mp_change_with"] = g(((chg > 0) & dir_up) | ((chg < 0) & dir_dn))

# Imbalance: per-direction
if "up_imb5" in df.columns and "dn_imb5" in df.columns:
    imb_dir = np.where(dir_up, df["up_imb5"], df["dn_imb5"])
    df["g_imb5_strong_with"] = g(pd.Series(imb_dir > 0.3, index=df.index))
    df["g_imb5_with"] = g(pd.Series(imb_dir > 0.0, index=df.index))
if "up_imb1" in df.columns and "dn_imb1" in df.columns:
    imb1_dir = np.where(dir_up, df["up_imb1"], df["dn_imb1"])
    df["g_imb1_strong_with"] = g(pd.Series(imb1_dir > 0.3, index=df.index))

if "up_queue_top_bid" in df.columns and "dn_queue_top_bid" in df.columns:
    q = np.where(dir_up, df["up_queue_top_bid"], df["dn_queue_top_bid"])
    q_med = pd.Series(q).median()
    df["g_queue_top_high"] = g(pd.Series(q > q_med, index=df.index))

if "up_imb5_change_500ms" in df.columns:
    chg_up = df["up_imb5_change_500ms"]
    chg_dn = df.get("dn_imb5_change_500ms", -df["up_imb5_change_500ms"])
    chg_dir = np.where(dir_up, chg_up, chg_dn)
    df["g_imb_change_with"] = g(pd.Series(chg_dir > 0, index=df.index))

# book slope steep with our direction
if "up_bid_slope" in df.columns and "up_ask_slope" in df.columns:
    diff_up = df["up_bid_slope"] - df["up_ask_slope"]
    diff_dn = df["dn_bid_slope"] - df["dn_ask_slope"]
    diff_dir = np.where(dir_up, diff_up, diff_dn)
    df["g_book_slope_with_us"] = g(pd.Series(diff_dir > pd.Series(diff_dir).quantile(0.75), index=df.index))


# ============================================================
# Lee-Mykland
# ============================================================
if "lm_L_stat" in df.columns:
    abs_L = df["lm_L_stat"].abs()
    Lq75 = abs_L.quantile(0.75)
    Lq90 = abs_L.quantile(0.90)
    df["g_lm_high_stat"] = g((abs_L > Lq75).fillna(False))
    df["g_lm_extreme_stat"] = g((abs_L > Lq90).fillna(False))
    # Jump direction agreeing
    L = df["lm_L_stat"]
    df["g_lm_jump_with"] = g(((L > Lq75) & dir_up) | ((L < -Lq75) & dir_dn))
    df["g_lm_jump_against"] = g(((L > Lq75) & dir_dn) | ((L < -Lq75) & dir_up))

if "jump_dir_01" in df.columns:
    jd = df["jump_dir_01"]
    df["g_jump_dir_with"] = g(((jd > 0) & dir_up) | ((jd < 0) & dir_dn))


# ============================================================
# Hawkes
# ============================================================
if "hawkes_lambda_imbalance" in df.columns:
    hki = df["hawkes_lambda_imbalance"]
    df["g_hawkes_imbalance_with"] = g(((hki > 0.1) & dir_up) | ((hki < -0.1) & dir_dn))
    df["g_hawkes_imb_loose_with"] = g(((hki > 0.05) & dir_up) | ((hki < -0.05) & dir_dn))
    df["g_hawkes_imb_strong_with"] = g(((hki > 0.2) & dir_up) | ((hki < -0.2) & dir_dn))

if "hawkes_recent_burst" in df.columns:
    df["g_hawkes_burst"] = g(df["hawkes_recent_burst"] > 0)

# vpin filters (skip when toxic flow)
if "vpin_zscore" in df.columns:
    df["g_vpin_calm"] = g(df["vpin_zscore"].abs() < 1.0)
    df["g_vpin_very_calm"] = g(df["vpin_zscore"].abs() < 0.5)


# ============================================================
# F7 RSI at ws_s
# ============================================================
if "f7_rsi_at_ws" in df.columns:
    r = df["f7_rsi_at_ws"]
    df["g_f7_rsi_with"] = g(((r > 50) & dir_up) | ((r < 50) & dir_dn))
    df["g_f7_rsi_extreme_with"] = g(((r > 70) & dir_up) | ((r < 30) & dir_dn))
    df["g_f7_rsi_extreme_against"] = g(((r > 70) & dir_dn) | ((r < 30) & dir_up))  # contrarian
    df["g_f7_rsi_mid"] = g((r >= 40) & (r <= 60))
    df["g_f7_rsi_strong_with"] = g(((r > 60) & dir_up) | ((r < 40) & dir_dn))


# ============================================================
# SMS-based
# ============================================================
if "sms_trend_strength" in df.columns:
    ts_sms = df["sms_trend_strength"]
    df["g_sms_trend_with"] = g(((ts_sms > 0) & dir_up) | ((ts_sms < 0) & dir_dn))
    df["g_sms_trend_strong_with"] = g(((ts_sms > 3) & dir_up) | ((ts_sms < -3) & dir_dn))

if "sms_rsi_14" in df.columns:
    r = df["sms_rsi_14"]
    df["g_sms_rsi_with"] = g(((r > 50) & dir_up) | ((r < 50) & dir_dn))
    df["g_sms_rsi_mid"] = g((r >= 40) & (r <= 60))
    df["g_sms_rsi_extreme_with"] = g(((r > 70) & dir_up) | ((r < 30) & dir_dn))

if "sms_cvd_sign" in df.columns:
    cs = df["sms_cvd_sign"]
    df["g_sms_cvd_with"] = g(((cs > 0) & dir_up) | ((cs < 0) & dir_dn))


# ============================================================
# vwap deviation gates
# ============================================================
if "vwap_since_open_bps" in df.columns:
    dev = df["vwap_since_open_bps"]
    df["g_within_dev_5"] = g((dev.abs() > 5.0) & (((dev > 0) & dir_up) | ((dev < 0) & dir_dn)))
    df["g_within_dev_15"] = g((dev.abs() > 15.0) & (((dev > 0) & dir_up) | ((dev < 0) & dir_dn)))
    df["g_dev_extreme"] = g((dev.abs() > 30.0) & (((dev > 0) & dir_up) | ((dev < 0) & dir_dn)))
    df["g_vwap_ge_50_le_85"] = g((dev.abs() >= 50) & (dev.abs() <= 85))

# entry_vwap range filters (vwap reasonable means cheap-side or middle bets)
ev = df["entry_vwap"]
df["g_vwap_05_95"] = g((ev >= 0.05) & (ev <= 0.95))  # exclude lottery tickets
df["g_vwap_10_90"] = g((ev >= 0.10) & (ev <= 0.90))
df["g_vwap_15_85"] = g((ev >= 0.15) & (ev <= 0.85))
df["g_vwap_20_80"] = g((ev >= 0.20) & (ev <= 0.80))
df["g_vwap_25_75"] = g((ev >= 0.25) & (ev <= 0.75))
df["g_vwap_30_70"] = g((ev >= 0.30) & (ev <= 0.70))
df["g_vwap_cheap"] = g((ev >= 0.20) & (ev < 0.50))      # bet cheaper than 50/50 -> high payoff if win
df["g_vwap_premium"] = g((ev >= 0.50) & (ev <= 0.80))   # bet pricier -> high WR if signal works


# ============================================================
# Offset bin gates (early/mid/late)
# ============================================================
off = df["fire_offset_s"].astype(int)
df["g_off_0_60"]    = g(off <= 60)     # earliest available for 15m
df["g_off_60_240"]  = g((off >= 60) & (off <= 240))
df["g_off_240_480"] = g((off >= 240) & (off <= 480))
df["g_off_480_720"] = g((off >= 480) & (off <= 720))
df["g_off_720_900"] = g((off >= 720))


# ============================================================
# Save
# ============================================================
gate_cols = [c for c in df.columns if c.startswith("g_")]
log(f"final gate count: {len(gate_cols)}")
df.to_parquet(OUT, index=False)
log(f"WROTE -> {OUT} ({os.path.getsize(OUT)/1e6:.1f} MB)")

# Coverage summary
print()
print("=== Gate fire rates ===")
for c in sorted(gate_cols):
    pct = df[c].mean() * 100
    n = df[c].sum()
    print(f"  {c:38s}: n={n:>6d} ({pct:5.1f}%)")
