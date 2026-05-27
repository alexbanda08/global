"""TASK 1 cont. — compute ALL ~36 gates as direction-aware booleans.

Convention: gate=True means "GO / signal aligned WITH bet direction".
NaN handling: NaN -> gate is NaN (we'll treat NaN as 'inactive' in stacking,
allowing the trade through but logging coverage).

Input: data/v4/canonical/_results/master_gate_features.parquet
Output: data/v4/canonical/_results/master_gate_features.parquet (overwrites with gate cols).
"""
import os, time, sys
import numpy as np
import pandas as pd

RES = "data/v4/canonical/_results"
FP = f"{RES}/master_gate_features.parquet"

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)

log("loading master_gate_features")
df = pd.read_parquet(FP)
log(f"rows={len(df):,} cols={len(df.columns)}")

# direction sign
ds = df['dir_sign'].values  # +1 for UP, -1 for DOWN

def sgn(s):
    return np.sign(s).astype(float)

# ---- R1 gates ----
log("computing R1 gates")
# rf_with: rf_dir agrees with direction
if 'rf_dir' in df.columns:
    df['g_rf_with'] = (np.sign(df['rf_dir'].fillna(0)) * ds > 0).astype(float)
    df.loc[df['rf_dir'].isna(), 'g_rf_with'] = np.nan

# ribbon_color: 1=bull, 4=bull, 2=bear, 3=bear (per spec)
if 'ribbon_color' in df.columns:
    bull_colors = df['ribbon_color'].isin([1, 4])
    bear_colors = df['ribbon_color'].isin([2, 3])
    g = np.where(ds > 0, bull_colors, bear_colors).astype(float)
    g = np.where(df['ribbon_color'].isna(), np.nan, g)
    df['g_ribbon_agrees'] = g

# stoch_with: stoch_k_60s>50 for UP, <50 for DOWN
if 'stoch_k_60s' in df.columns:
    g = np.where(ds > 0, df['stoch_k_60s'] > 50, df['stoch_k_60s'] < 50).astype(float)
    g = np.where(df['stoch_k_60s'].isna(), np.nan, g)
    df['g_stoch_with'] = g

# mfi_with
if 'mfi_60s' in df.columns:
    g = np.where(ds > 0, df['mfi_60s'] > 50, df['mfi_60s'] < 50).astype(float)
    g = np.where(df['mfi_60s'].isna(), np.nan, g)
    df['g_mfi_with'] = g

# cci_with: cci_60s > 0 for UP, < 0 for DOWN
if 'cci_60s' in df.columns:
    g = np.where(ds > 0, df['cci_60s'] > 0, df['cci_60s'] < 0).astype(float)
    g = np.where(df['cci_60s'].isna(), np.nan, g)
    df['g_cci_with'] = g

# bb_pos_with: bb_pos > 0.5 for UP, < 0.5 for DOWN
if 'bb_pos_60s' in df.columns:
    g = np.where(ds > 0, df['bb_pos_60s'] > 0.5, df['bb_pos_60s'] < 0.5).astype(float)
    g = np.where(df['bb_pos_60s'].isna(), np.nan, g)
    df['g_bb_pos_with'] = g

# tr_above_ema50: close > tr_ema_50 for UP, < for DOWN; use tr_close_vs_ema50 (signed)
if 'tr_close_vs_ema50' in df.columns:
    g = np.where(ds > 0, df['tr_close_vs_ema50'] > 0, df['tr_close_vs_ema50'] < 0).astype(float)
    g = np.where(df['tr_close_vs_ema50'].isna(), np.nan, g)
    df['g_tr_above_ema50'] = g

# tr_above_ema200
if 'tr_close_vs_ema200' in df.columns:
    g = np.where(ds > 0, df['tr_close_vs_ema200'] > 0, df['tr_close_vs_ema200'] < 0).astype(float)
    g = np.where(df['tr_close_vs_ema200'].isna(), np.nan, g)
    df['g_tr_above_ema200'] = g

# tr_above_ema800
if 'tr_close_vs_ema800' in df.columns:
    g = np.where(ds > 0, df['tr_close_vs_ema800'] > 0, df['tr_close_vs_ema800'] < 0).astype(float)
    g = np.where(df['tr_close_vs_ema800'].isna(), np.nan, g)
    df['g_tr_above_ema800'] = g

# tr_above_pp: close > tr_PP for UP, < for DOWN
if 'tr_close_vs_PP' in df.columns:
    g = np.where(ds > 0, df['tr_close_vs_PP'] > 0, df['tr_close_vs_PP'] < 0).astype(float)
    g = np.where(df['tr_close_vs_PP'].isna(), np.nan, g)
    df['g_tr_above_pp'] = g

# tr_stack_with: ema stack score agrees (positive for bull stack, negative for bear)
if 'tr_ema_stack_score' in df.columns:
    g = np.where(ds > 0, df['tr_ema_stack_score'] > 0, df['tr_ema_stack_score'] < 0).astype(float)
    g = np.where(df['tr_ema_stack_score'].isna(), np.nan, g)
    df['g_tr_stack_with'] = g

# tr_within_adr
if 'tr_within_adr' in df.columns:
    df['g_tr_within_adr'] = df['tr_within_adr'].astype(float)
elif 'tr_close_vs_adr_high' in df.columns and 'tr_close_vs_adr_low' in df.columns:
    g = ((df['tr_close_vs_adr_high'] < 0) & (df['tr_close_vs_adr_low'] > 0)).astype(float)
    g = np.where(df['tr_close_vs_adr_high'].isna(), np.nan, g)
    df['g_tr_within_adr'] = g

# tight_ribbon: ribbon_compression_bps < 2
if 'ribbon_compression_bps' in df.columns:
    g = (df['ribbon_compression_bps'].abs() < 2.0).astype(float)
    g = np.where(df['ribbon_compression_bps'].isna(), np.nan, g)
    df['g_tight_ribbon'] = g

# within_dev: |dev_bps| <= 50 (from master panel)
if 'dev_bps' in df.columns:
    g = (df['dev_bps'].abs() <= 50).astype(float)
    g = np.where(df['dev_bps'].isna(), np.nan, g)
    df['g_within_dev'] = g

# dev_extreme: |dev_bps| > 100
if 'dev_bps' in df.columns:
    g = (df['dev_bps'].abs() > 100).astype(float)
    g = np.where(df['dev_bps'].isna(), np.nan, g)
    df['g_dev_extreme'] = g

# markov_with: rsi/F7-like — use trend_strength_raw sign
if 'trend_strength_raw' in df.columns:
    g = np.where(ds > 0, df['trend_strength_raw'] > 0, df['trend_strength_raw'] < 0).astype(float)
    g = np.where(df['trend_strength_raw'].isna(), np.nan, g)
    df['g_markov_with'] = g

# ---- R3 gates ----
log("computing R3 gates")
# vol_expanding: rv_60s > rv_300s (recent realized vol expanding)
if 'rv_60s' in df.columns and 'rv_300s' in df.columns:
    g = (df['rv_60s'] > df['rv_300s']).astype(float)
    g = np.where(df['rv_60s'].isna() | df['rv_300s'].isna(), np.nan, g)
    df['g_vol_expanding'] = g
# vol_contracting (R4): rv_60s < rv_900s
if 'rv_60s' in df.columns and 'rv_900s' in df.columns:
    g = (df['rv_60s'] < df['rv_900s']).astype(float)
    g = np.where(df['rv_60s'].isna() | df['rv_900s'].isna(), np.nan, g)
    df['g_vol_contracting'] = g
# vol_high: rv_pct_24h > 0.75 (top quartile)
if 'rv_pct_24h' in df.columns:
    g = (df['rv_pct_24h'] > 0.75).astype(float)
    g = np.where(df['rv_pct_24h'].isna(), np.nan, g)
    df['g_vol_high'] = g

# hurst_trending: hurst > 0.55 (if present); else use trend_slope_30m sign with direction
if 'trend_slope_30m' in df.columns:
    g = np.where(ds > 0, df['trend_slope_30m'] > 0, df['trend_slope_30m'] < 0).astype(float)
    g = np.where(df['trend_slope_30m'].isna(), np.nan, g)
    df['g_hurst_trending'] = g

# book_slope_steep_against (R3): bid_slope >> ask_slope = bullish (selling deep, buyers thin), so against = mean-revert
if 'up_bid_slope' in df.columns and 'up_ask_slope' in df.columns:
    # for UP bets we want book leaning UP — bid_slope > ask_slope on UP token
    diff_up = df['up_bid_slope'] - df['up_ask_slope']
    diff_dn = df['dn_bid_slope'] - df['dn_ask_slope']
    # gate = book steepness AGAINST our direction (a fader)
    g = np.where(ds > 0, diff_up < diff_up.quantile(0.25), diff_dn < diff_dn.quantile(0.25)).astype(float)
    g = np.where(df['up_bid_slope'].isna(), np.nan, g)
    df['g_book_slope_steep_against'] = g

# ---- R4 gates ----
log("computing R4 gates")
# trend_slope_with
if 'trend_slope_30m' in df.columns:
    g = np.where(ds > 0, df['trend_slope_30m'] > 0, df['trend_slope_30m'] < 0).astype(float)
    g = np.where(df['trend_slope_30m'].isna(), np.nan, g)
    df['g_trend_slope_with'] = g

# trend_slope_strong_with: |slope| > 75th percentile and aligned
if 'trend_slope_30m' in df.columns:
    abs_slope = df['trend_slope_30m'].abs()
    thr = abs_slope.quantile(0.75)
    g = (((ds > 0) & (df['trend_slope_30m'] > thr)) | ((ds < 0) & (df['trend_slope_30m'] < -thr))).astype(float)
    g = np.where(df['trend_slope_30m'].isna(), np.nan, g)
    df['g_trend_slope_strong_with'] = g

# imb5_strong_with: large book imbalance on side we bet
if 'up_imb5' in df.columns and 'dn_imb5' in df.columns:
    # imb > 0.3 on side we bet
    g = np.where(ds > 0, df['up_imb5'] > 0.3, df['dn_imb5'] > 0.3).astype(float)
    mask_nan = (ds > 0) & df['up_imb5'].isna() | (ds < 0) & df['dn_imb5'].isna()
    g = np.where(mask_nan, np.nan, g)
    df['g_imb5_strong_with'] = g

# queue_top_high
if 'up_queue_top_bid' in df.columns:
    qmed_up = df['up_queue_top_bid'].median()
    g = (df['up_queue_top_bid'] > qmed_up).astype(float)
    g = np.where(df['up_queue_top_bid'].isna(), np.nan, g)
    df['g_queue_top_high'] = g

# imb_change_with
if 'up_imb5_change_500ms' in df.columns:
    chg = df['up_imb5_change_500ms']
    g = np.where(ds > 0, chg > 0, chg < 0).astype(float)
    g = np.where(chg.isna(), np.nan, g)
    df['g_imb_change_with'] = g

# vwap_ge_50_le_85 — vwap_since_open_bps  (use dev_bps from master)
if 'vwap_since_open_bps' in df.columns:
    v = df['vwap_since_open_bps'].abs()
    g = ((v >= 50) & (v <= 85)).astype(float)
    g = np.where(v.isna(), np.nan, g)
    df['g_vwap_ge_50_le_85'] = g

# ---- R5 gates ----
log("computing R5 gates")
# mp_no_extreme: |mp_skew| < 50bps  (Stoikov microprice — universal tradability)
if 'mp_skew' in df.columns:
    g = (df['mp_skew'].abs() < 50).astype(float)
    g = np.where(df['mp_skew'].isna(), np.nan, g)
    df['g_mp_no_extreme'] = g

# mp_change_with: mp_skew_change_500ms aligned with direction
if 'mp_skew_change_500ms' in df.columns:
    g = np.where(ds > 0, df['mp_skew_change_500ms'] > 0, df['mp_skew_change_500ms'] < 0).astype(float)
    g = np.where(df['mp_skew_change_500ms'].isna(), np.nan, g)
    df['g_mp_change_with'] = g

# mp_skew_with: mp_skew aligned
if 'mp_skew' in df.columns:
    g = np.where(ds > 0, df['mp_skew'] > 0, df['mp_skew'] < 0).astype(float)
    g = np.where(df['mp_skew'].isna(), np.nan, g)
    df['g_mp_skew_with'] = g

# lm_high_stat: L_stat > 5 (high jump stat in window)
if 'L_stat' in df.columns:
    g = (df['L_stat'] > 5).astype(float)
    g = np.where(df['L_stat'].isna(), np.nan, g)
    df['g_lm_high_stat'] = g
# lm_extreme_against (R5 KILL gate): jump_dir_extreme against direction
if 'jump_dir_extreme' in df.columns:
    g = np.where(ds > 0, df['jump_dir_extreme'] < 0, df['jump_dir_extreme'] > 0).astype(float)
    g = np.where(df['jump_dir_extreme'].isna(), np.nan, g)
    df['g_lm_extreme_against'] = g

# hawkes_imbalance_with
if 'hawkes_lambda_imbalance' in df.columns:
    g = np.where(ds > 0, df['hawkes_lambda_imbalance'] > 0, df['hawkes_lambda_imbalance'] < 0).astype(float)
    g = np.where(df['hawkes_lambda_imbalance'].isna(), np.nan, g)
    df['g_hawkes_imbalance_with'] = g

# hy_cb_with_dir: cross_a_dev_bp (coinbase basis HY) aligned with direction
if 'cross_a_dev_bp' in df.columns:
    g = np.where(ds > 0, df['cross_a_dev_bp'] > 0, df['cross_a_dev_bp'] < 0).astype(float)
    g = np.where(df['cross_a_dev_bp'].isna(), np.nan, g)
    df['g_hy_cb_with_dir'] = g

# flow_no_whale: not present — proxy with mlofi_skew sign or none. Use mlofi_skew_l5_60s aligned
if 'mlofi_skew_l5_60s' in df.columns:
    g = np.where(ds > 0, df['mlofi_skew_l5_60s'] > 0, df['mlofi_skew_l5_60s'] < 0).astype(float)
    g = np.where(df['mlofi_skew_l5_60s'].isna(), np.nan, g)
    df['g_flow_with_and_no_whale'] = g

# coinbase_basis_extreme_against: cross_a_dev_bp extreme (>q90) against direction
if 'cross_a_dev_bp' in df.columns:
    a = df['cross_a_dev_bp']
    g_extreme = (a.abs() > a.abs().quantile(0.9)).astype(float)
    g_against = np.where(ds > 0, a < 0, a > 0).astype(float)
    g = g_extreme * g_against
    g = np.where(a.isna(), np.nan, g)
    df['g_coinbase_basis_extreme_against'] = g

# hl_liq_cascade_with: proxy via hawkes_recent_burst aligned
if 'hawkes_recent_burst' in df.columns:
    # burst is unsigned; combine with lambda_imbalance for direction
    g_burst = (df['hawkes_recent_burst'] > df['hawkes_recent_burst'].quantile(0.75)).astype(float)
    if 'hawkes_lambda_imbalance' in df.columns:
        g_lambda_with = np.where(ds > 0, df['hawkes_lambda_imbalance'] > 0, df['hawkes_lambda_imbalance'] < 0).astype(float)
        g = g_burst * g_lambda_with
    else:
        g = g_burst
    g = np.where(df['hawkes_recent_burst'].isna(), np.nan, g)
    df['g_hl_liq_cascade_with'] = g

# Count gates
gates = [c for c in df.columns if c.startswith('g_')]
log(f"computed {len(gates)} gates: {gates}")

# Coverage per gate
log("gate coverage:")
for g in sorted(gates):
    cov_total = df[g].notna().mean()
    if cov_total > 0:
        rate = (df[g] == 1).sum() / df[g].notna().sum()
    else:
        rate = 0
    print(f"  {g:42s} cov={cov_total*100:5.1f}%  active_rate={rate*100:5.1f}%")

# Sanity: WR when each gate is TRUE
log("WR when gate TRUE:")
for g in sorted(gates):
    sub = df[df[g] == 1]
    if len(sub) > 100:
        wr = sub['won_int'].mean() * 100
        pt = sub['pnl_legacy_usd'].mean()
        n = len(sub)
        print(f"  {g:42s} n={n:6d}  WR={wr:5.2f}%  $/tr={pt:+.3f}")

df.to_parquet(FP, index=False)
log(f"WROTE {FP}  size={os.path.getsize(FP)/1e6:.1f} MB")
