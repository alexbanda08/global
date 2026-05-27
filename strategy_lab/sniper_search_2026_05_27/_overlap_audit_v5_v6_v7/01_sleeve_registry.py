"""V5 + V6 + V7 Sleeve Registry — declarative definition of every sleeve to audit.

Each sleeve = (version, sleeve_id, asset, tf, offsets, direction, gate_stack, panel_source).
Panel source = best parquet that contains all needed gates for the sleeve.
Saved to: sleeve_registry.csv
"""
import os
import pandas as pd

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
OUT = f"{ROOT}/strategy_lab/sniper_search_2026_05_27/_overlap_audit_v5_v6_v7"
os.makedirs(OUT, exist_ok=True)

# ----- Per-market panel paths (richest gate set per market) -----
PANEL = {
    ("BTC", "5m"):  f"{ROOT}/strategy_lab/sniper_search_2026_05_27/btc_5m_v7/_sandbox/universe_v7.parquet",
    ("BTC", "15m"): f"{ROOT}/data/v4/canonical/_results/sniper_btc15m_v7_gated.parquet",
    ("ETH", "5m"):  f"{ROOT}/data/v4/canonical/_results/_sniper_eth5m_v7_universe.parquet",
    ("ETH", "15m"): f"{ROOT}/strategy_lab/sniper_search_2026_05_27/eth_15m_v7/eth_15m_enriched_v7.parquet",
    ("SOL", "5m"):  f"{ROOT}/strategy_lab/sniper_search_2026_05_27/sol_5m_v7/_panel_sol_5m_v7.parquet",
    ("SOL", "15m"): f"{ROOT}/strategy_lab/sniper_search_2026_05_27/sol_15m_v7/sol_15m_v7_universe.parquet",
}

# Fallback: V3 oos fires panels — covers basic V5 gates
V3_PANEL = {
    ("BTC", "5m"):  f"{ROOT}/data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_BTC_5m_full_v3.parquet",
    ("BTC", "15m"): f"{ROOT}/data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_BTC_15m_full_v3.parquet",
    ("ETH", "5m"):  f"{ROOT}/data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_ETH_5m_full_v3.parquet",
    ("ETH", "15m"): f"{ROOT}/data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_ETH_15m_full_v3.parquet",
    ("SOL", "5m"):  f"{ROOT}/data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_SOL_5m_full_v3.parquet",
    ("SOL", "15m"): f"{ROOT}/data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_SOL_15m_full_v3.parquet",
}

# ------------- Gate aliasing — V5/V6 spec -> available panel col -------------
# Some spec-level gate names don't exist verbatim; provide best-effort mapping.
# Multiple aliases attempted; first match in panel wins.
GATE_ALIAS = {
    "g_mp_no_extreme":       ["g_mp_no_extreme", "g_mp_no_extreme_100", "g_mp_no_extreme_150"],
    "g_mp_no_extreme_150":   ["g_mp_no_extreme_150", "g_mp_no_extreme"],
    "g_tr_above_cloud":      ["g_tr_above_cloud"],
    "g_above_1h_dailyvwap_with": ["g_above_1h_dailyvwap_with"],
    "g_dir_up":              ["g_dir_up"],
    "g_dir_down":            ["g_dir_down", "g_dir_dn"],
    "g_offset_early":        ["g_offset_early"],
    "g_off_60_240":          ["g_off_60_240"],
    "g_hod_european_morning":["g_hod_european_morning", "g_hod_european", "g_hod_eu_morning"],
    "g_hod_us_afternoon":    ["g_hod_us_afternoon"],
    "g_rf_strict_align":     ["g_rf_strict_align", "g_rf_full_align"],
    "g_tr_partial_stack_with": ["g_tr_partial_stack_with"],
    "g_tr_stack_full_with":  ["g_tr_stack_full_with"],
    "g_sms_liq_reclaim_with":["g_sms_liq_reclaim_with"],
    "g_tr_in_active_session":["g_tr_in_active_session"],
    "g_entry_vwap_in_band":  ["g_entry_vwap_in_band", "g_vwap_in_30_75", "g_vwap_in_25_60", "g_entry_vwap_in_10_65"],
    "g_entry_vwap_in_30_70": ["g_entry_vwap_in_30_70", "g_vwap_30_70"],
    "g_vwap_in_45_85":       ["g_vwap_in_45_85"],
    "g_vwap_in_55_80":       ["g_vwap_in_55_80"],
    "g_vwap_premium":        ["g_vwap_premium"],
    "g_f7_rsi_with":         ["g_f7_rsi_with", "g_f7_with", "g_f7_v7_with"],
    "g_cci_strong_with":     ["g_cci_strong_with"],
    "g_pw_trend_slope_with": ["g_pw_trend_slope_with"],
    "g_hawkes_imb_loose_with": ["g_hawkes_imb_loose_with"],
    "g_mp_imbalance_with":   ["g_mp_imbalance_with"],
    "g_trend_slope_with":    ["g_trend_slope_with"],
    "g_mp_skew_strong_with": ["g_mp_skew_strong_with"],
    "g_regime_stack_with":   ["g_regime_stack_with", "g_regime_stack_full_with", "g_regime_trending_with"],
    "g_hurst_trending":      ["g_hurst_trending", "g_hurst_trending_vh"],
    "g_vol_high":            ["g_vol_high", "g_vol_high_vh"],
}

def resolve_gate(spec_gate, panel_cols):
    """Return the first alias of spec_gate that exists in panel_cols, or None."""
    aliases = GATE_ALIAS.get(spec_gate, [spec_gate])
    for a in aliases:
        if a in panel_cols:
            return a
    return None

# ===================== SLEEVE REGISTRY =====================
# Format: dict with keys: version, sleeve_id, asset, tf, offsets (list), direction, gates (list)
SLEEVES = []

# ---------------------------- V5 (16 sleeves) ----------------------------
SLEEVES += [
    dict(version="V5", sleeve_id="BTC_5M_TS_MPSKEW_S6_0_60_V5", asset="BTC", tf="5m",
         offsets=[30], direction="BOTH",
         gates=["g_trend_slope_strong_with","g_mp_skew_with"]),
    dict(version="V5", sleeve_id="BTC_5M_TS_MPSKEW_ANY_OFFSET30_V5", asset="BTC", tf="5m",
         offsets=[30], direction="BOTH",
         gates=["g_trend_slope_strong_with","g_mp_skew_with"]),
    dict(version="V5", sleeve_id="ETH_5M_TR200_MP_SMS_ACTIVE_OFF120_V5", asset="ETH", tf="5m",
         offsets=[120], direction="BOTH",
         gates=["g_tr_above_ema200","g_mp_skew_with","g_sms_liq_reclaim_with","g_tr_in_active_session"]),
    dict(version="V5", sleeve_id="ETH_5M_TR200_MP_MPNX_SMS_OFF120_V5", asset="ETH", tf="5m",
         offsets=[120], direction="BOTH",
         gates=["g_tr_above_ema200","g_mp_skew_with","g_mp_no_extreme","g_sms_liq_reclaim_with"]),
    dict(version="V5", sleeve_id="ETH_5M_CLOUD_MP_SMS_ACTIVE_OFF120_V5", asset="ETH", tf="5m",
         offsets=[120], direction="BOTH",
         gates=["g_tr_above_cloud","g_mp_skew_with","g_sms_liq_reclaim_with","g_tr_in_active_session"]),
    dict(version="V5", sleeve_id="SOL_5M_DEPTH_UP_HOD_SESSION_V5", asset="SOL", tf="5m",
         offsets=[30,60,90], direction="UP",
         gates=["g_depth_250_strict","g_hod_us_afternoon","g_tr_in_active_session"]),
    dict(version="V5", sleeve_id="SOL_5M_RF_TR_PP_MID_V5", asset="SOL", tf="5m",
         offsets=[90,120,150,180], direction="BOTH",
         gates=["g_rf_strict_align","g_tr_above_ema200","g_tr_above_pp","g_tr_partial_stack_with"]),
    dict(version="V5", sleeve_id="SOL_5M_RF_TR_PARTIAL_MID_V5", asset="SOL", tf="5m",
         offsets=[90,120,150,180], direction="BOTH",
         gates=["g_rf_strict_align","g_tr_partial_stack_with"]),
    dict(version="V5", sleeve_id="BTC_15M_TS_TRSTACK_OFF600_DOWN_V5", asset="BTC", tf="15m",
         offsets=[600], direction="DOWN",
         gates=["g_tr_stack_full_with","g_trend_slope_with"]),
    dict(version="V5", sleeve_id="BTC_15M_REGIME_TRSTACK_OFF480_UP_V5", asset="BTC", tf="15m",
         offsets=[480], direction="UP",
         gates=["g_regime_stack_with","g_tr_stack_full_with"]),
    dict(version="V5", sleeve_id="BTC_15M_MPSKEW_TRSTACK_OFF600_DOWN_V5", asset="BTC", tf="15m",
         offsets=[600], direction="DOWN",
         gates=["g_mp_skew_strong_with","g_tr_stack_full_with"]),
    dict(version="V5", sleeve_id="BTC_15M_EMA50_EMA800_OFF600_DOWN_V5", asset="BTC", tf="15m",
         offsets=[600], direction="DOWN",
         gates=["g_tr_above_ema50","g_tr_above_ema800"]),
    dict(version="V5", sleeve_id="ETH_15M_TRSTACK_VWAP_VOL_OFFEARLY_V5", asset="ETH", tf="15m",
         offsets=[0,30,60], direction="BOTH",
         gates=["g_tr_stack_full_with","g_above_1h_dailyvwap_with","g_offset_early","g_vol_high"]),
    dict(version="V5", sleeve_id="ETH_15M_TRSTACK_VWAP_OFFEARLY_V5", asset="ETH", tf="15m",
         offsets=[0,30,60], direction="BOTH",
         gates=["g_tr_stack_full_with","g_offset_early","g_above_1h_dailyvwap_with"]),
    dict(version="V5", sleeve_id="SOL_15M_TRSTACK_VOL_RIBBON_EMA_MID_V5", asset="SOL", tf="15m",
         offsets=[120,180,240], direction="BOTH",
         gates=["g_tr_stack_full_with","g_vol_high","g_ribbon_agrees","g_tr_above_ema200","g_tr_above_ema800"]),
    dict(version="V5", sleeve_id="SOL_15M_RFAGED_TRSTACK_LATE_V5", asset="SOL", tf="15m",
         offsets=[480,600,720,840], direction="BOTH",
         gates=["g_rf_aged","g_tr_stack_full_with","g_tr_stack_with"]),
]

# ---------------------------- V6 (14 selected) ----------------------------
SLEEVES += [
    dict(version="V6", sleeve_id="ETH_5M_CLOUD_RIBBON_MP_HURST_V6", asset="ETH", tf="5m",
         offsets=[60], direction="BOTH",
         gates=["g_tr_above_cloud","g_ribbon_agrees","g_mp_skew_with","g_hurst_trending"]),
    dict(version="V6", sleeve_id="ETH_5M_V5_REPL_OFF120_V6", asset="ETH", tf="5m",
         offsets=[120], direction="BOTH",
         gates=["g_tr_above_ema200","g_mp_skew_with","g_sms_liq_reclaim_with","g_tr_in_active_session"]),
    dict(version="V6", sleeve_id="ETH_5M_BB_MP_HURST_BAND_V6", asset="ETH", tf="5m",
         offsets=[60], direction="BOTH",
         gates=["g_bb_pos_with","g_mp_skew_with","g_hurst_trending","g_entry_vwap_in_band"]),
    dict(version="V6", sleeve_id="SOL_5M_CCI_F7_MFI_PARTIAL_VWAP_V6", asset="SOL", tf="5m",
         offsets=[30,60,90,120,150,180,210,240], direction="BOTH",
         gates=["g_cci_strong_with","g_f7_rsi_with","g_mfi_with","g_tr_partial_stack_with","g_vwap_in_45_85"]),
    dict(version="V6", sleeve_id="SOL_5M_F7_MP_EMA200_VWAP_V6", asset="SOL", tf="5m",
         offsets=[30,60,90,120,150,180,210,240], direction="BOTH",
         gates=["g_f7_rsi_with","g_mp_no_extreme_150","g_tr_above_ema200","g_vwap_in_55_80"]),
    dict(version="V6", sleeve_id="SOL_5M_F7_MFI_EMA200_VWAP_V6", asset="SOL", tf="5m",
         offsets=[30,60,90,120,150,180,210,240], direction="BOTH",
         gates=["g_f7_rsi_with","g_mfi_with","g_tr_above_ema200","g_vwap_in_55_80"]),
    dict(version="V6", sleeve_id="ETH_15M_TRSTACK_VWAP_VOL_OFFEARLY_BAND_V6", asset="ETH", tf="15m",
         offsets=[0,30,60], direction="BOTH",
         gates=["g_tr_stack_full_with","g_above_1h_dailyvwap_with","g_offset_early","g_vol_high","g_entry_vwap_in_30_70"]),
    dict(version="V6", sleeve_id="ETH_15M_PW_TRENDSLOPE_TRSTACK_VWAP_VOL_OFFEARLY_V6", asset="ETH", tf="15m",
         offsets=[0,30,60], direction="BOTH",
         gates=["g_tr_stack_full_with","g_above_1h_dailyvwap_with","g_offset_early","g_vol_high","g_pw_trend_slope_with"]),
    dict(version="V6", sleeve_id="BTC_15M_VWAPPREM_EMA50_MPSKEW_OFF600_V6", asset="BTC", tf="15m",
         offsets=[600], direction="BOTH",
         gates=["g_vwap_premium","g_tr_above_ema50","g_mp_skew_with"]),
    dict(version="V6", sleeve_id="BTC_15M_EMA200_MPSKEW_RF_OFF600_DOWN_V6", asset="BTC", tf="15m",
         offsets=[600], direction="DOWN",
         gates=["g_tr_above_ema200","g_mp_skew_strong_with","g_rf_with"]),
    dict(version="V6", sleeve_id="BTC_15M_EMA800_RIBSLP_HAWKES_OFF840_V6", asset="BTC", tf="15m",
         offsets=[840], direction="BOTH",
         gates=["g_tr_above_ema800","g_ribbon_slope_with","g_hawkes_imb_loose_with"]),
    dict(version="V6", sleeve_id="SOL_15M_HOD_EU_OFF60_240_RF_TR_VWAP80_V6", asset="SOL", tf="15m",
         offsets=[60,120,240], direction="BOTH",
         gates=["g_hod_european_morning","g_off_60_240","g_rf_with","g_tr_stack_with"]),  # vwap<0.80 applied separately below
    dict(version="V6", sleeve_id="SOL_15M_HOD_EU_OFF60_240_RF_TR_VWAP30_70_V6", asset="SOL", tf="15m",
         offsets=[60,120,240], direction="BOTH",
         gates=["g_hod_european_morning","g_off_60_240","g_rf_with","g_tr_stack_with","g_entry_vwap_in_30_70"]),
    dict(version="V6", sleeve_id="SOL_15M_HOD_EU_TIGHTRIB_RF_TR_VWAP80_V6", asset="SOL", tf="15m",
         offsets=None, direction="BOTH",   # all offsets
         gates=["g_hod_european_morning","g_rf_with","g_tight_ribbon","g_tr_stack_with"]),  # vwap<0.80 below
]

# ---------------------------- V7 top candidates (per market) ----------------------------
# Source: each market's top_5_candidates_v7.csv gate_stack column.
# Some gate stacks reference NEW V7-only gates which are present in the corresponding V7 panel.
# We parse the gate_stack column verbatim and join on the V7 panel.

V7_TOP = []
# BTC 5M V7
V7_TOP += [
    dict(version="V7", sleeve_id="BTC_5M_V7_T1_PARENT15M_REGIME", asset="BTC", tf="5m",
         offsets=None, direction="BOTH",
         gates=["g_parent_15m_regime_with","g_within_dev","g_hurst_trending"]),
    dict(version="V7", sleeve_id="BTC_5M_V7_T2_PARENT15M_SLOPE", asset="BTC", tf="5m",
         offsets=None, direction="BOTH",
         gates=["g_parent_15m_slope_with","g_trend_slope_strong_with","g_mp_no_extreme"]),
    dict(version="V7", sleeve_id="BTC_5M_V7_T3_OFI_TS", asset="BTC", tf="5m",
         offsets=None, direction="BOTH",
         gates=["g_slot_end_ofi_with","g_trend_slope_strong_with"]),
    dict(version="V7", sleeve_id="BTC_5M_V7_T4_HURST_TS_HAWKES", asset="BTC", tf="5m",
         offsets=None, direction="BOTH",
         gates=["g_hurst_regime_with","g_trend_slope_strong_with","g_hawkes_imbalance_with"]),
    dict(version="V7", sleeve_id="BTC_5M_V7_T5_PARENT15M_NOTRANGING_MPSKEW", asset="BTC", tf="5m",
         offsets=None, direction="BOTH",
         gates=["g_parent_15m_not_ranging","g_trend_slope_strong_with","g_mp_skew_with"]),
]
# ETH 5M V7 (from _results/top_5_candidates_v7.csv)
V7_TOP += [
    dict(version="V7", sleeve_id="ETH_5M_V7_C1_CLOUD_VWAP_HURST_MP", asset="ETH", tf="5m",
         offsets=[60], direction="BOTH",
         gates=["g_tr_above_cloud","g_entry_vwap_in_band","g_hurst_mp_trend_with"]),
    dict(version="V7", sleeve_id="ETH_5M_V7_C2_EMA50_HURST_PARENT_RANGING", asset="ETH", tf="5m",
         offsets=[60], direction="BOTH",
         gates=["g_tr_above_ema50","g_hurst_trending","g_parent15m_ranging"]),
    dict(version="V7", sleeve_id="ETH_5M_V7_C3_V6C3_PARENT_RANGING", asset="ETH", tf="5m",
         offsets=[60], direction="BOTH",
         gates=["g_tr_above_cloud","g_ribbon_agrees","g_mp_skew_with","g_hurst_trending","g_parent15m_ranging"]),
    dict(version="V7", sleeve_id="ETH_5M_V7_C4_XA_3SOURCE_PARENT_RANGING", asset="ETH", tf="5m",
         offsets=[90], direction="BOTH",
         gates=["g_tr_above_ema200","g_entry_vwap_in_band","g_regime_ranging_at_ws","g_xa_3source_trend_with"]),
    dict(version="V7", sleeve_id="ETH_5M_V7_C5_CLOUD_HURST_VWAP_PARENT", asset="ETH", tf="5m",
         offsets=[60], direction="BOTH",
         gates=["g_tr_above_cloud","g_hurst_trending","g_entry_vwap_in_band","g_parent15m_ranging"]),
]
# SOL 5M V7
V7_TOP += [
    dict(version="V7", sleeve_id="SOL_5M_V7_S1_BTC_TREND_CCI_HURST_REV", asset="SOL", tf="5m",
         offsets=None, direction="BOTH",
         gates=["g_btc_trend_30m_with","g_cci_extreme_with","g_hurst_reverting"]),
    dict(version="V7", sleeve_id="SOL_5M_V7_S2_BTC_F7_OVERBOUGHT_EMA800_VWAP", asset="SOL", tf="5m",
         offsets=None, direction="BOTH",
         gates=["g_btc_f7_with","g_f7_v7_overbought","g_tr_above_ema800","g_vwap_in_45_85"]),
    dict(version="V7", sleeve_id="SOL_5M_V7_S3_BTC_F7_AGAINST_CCI_HURST_REV", asset="SOL", tf="5m",
         offsets=None, direction="BOTH",
         gates=["g_btc_f7_against","g_cci_extreme_with","g_hurst_reverting"]),
    dict(version="V7", sleeve_id="SOL_5M_V7_S4_CCI_F7_OVERSOLD_MFI_STOCH", asset="SOL", tf="5m",
         offsets=None, direction="BOTH",
         gates=["g_cci_extreme_with","g_f7_v7_oversold","g_mfi_strong_with","g_stoch_strong_with"]),
    dict(version="V7", sleeve_id="SOL_5M_V7_S5_CCI_F7_OVERSOLD_MFI_STOCH_LIGHT", asset="SOL", tf="5m",
         offsets=None, direction="BOTH",
         gates=["g_cci_extreme_with","g_f7_v7_oversold","g_mfi_with","g_stoch_strong_with"]),
]
# BTC 15M V7 (only 4 unique passes; the 5th had n_lockbox=0)
V7_TOP += [
    dict(version="V7", sleeve_id="BTC_15M_V7_BASELINE", asset="BTC", tf="15m",
         offsets=[600], direction="DOWN",
         gates=["g_tr_above_ema200","g_mp_skew_strong_with","g_rf_with"]),
    dict(version="V7", sleeve_id="BTC_15M_V7_PLUS_ETH_SLOPE", asset="BTC", tf="15m",
         offsets=[600], direction="DOWN",
         gates=["g_tr_above_ema200","g_mp_skew_strong_with","g_rf_with","g_eth_slope_with"]),
    dict(version="V7", sleeve_id="BTC_15M_V7_PLUS_PARENT_1H_RANGING", asset="BTC", tf="15m",
         offsets=[600], direction="DOWN",
         gates=["g_tr_above_ema200","g_mp_skew_strong_with","g_rf_with","g_parent_1h_ranging"]),
    # exp1 (hurst_reverting) has n=0 lockbox, omitted
]
# ETH 15M V7
V7_TOP += [
    dict(version="V7", sleeve_id="ETH_15M_V7_PI_S1_BTC_15M_TREND", asset="ETH", tf="15m",
         offsets=[60], direction="BOTH",
         gates=["g_tr_stack_full_with","g_above_1h_dailyvwap_with","g_offset_early","g_vol_high","g_pw_btc_15m_trend_with"]),
    dict(version="V7", sleeve_id="ETH_15M_V7_PI_S1_TS_AND_BTC_15M", asset="ETH", tf="15m",
         offsets=[60], direction="BOTH",
         gates=["g_tr_stack_full_with","g_above_1h_dailyvwap_with","g_offset_early","g_vol_high","g_pw_trend_slope_with","g_pw_btc_15m_trend_with"]),
    dict(version="V7", sleeve_id="ETH_15M_V7_PG_RV_ABOVE_MED", asset="ETH", tf="15m",
         offsets=[60], direction="BOTH",
         gates=["g_tr_stack_full_with","g_above_1h_dailyvwap_with","g_offset_early","g_vol_high","g_pw_trend_slope_with","g_rv_60_above_med"]),
    dict(version="V7", sleeve_id="ETH_15M_V7_PG_VOL_EXTREME_CORE", asset="ETH", tf="15m",
         offsets=[60], direction="BOTH",
         gates=["g_tr_stack_full_with","g_above_1h_dailyvwap_with","g_offset_early","g_vol_extreme_high","g_pw_trend_slope_with"]),
    dict(version="V7", sleeve_id="ETH_15M_V7_PG_VOL_EXTREME_TS", asset="ETH", tf="15m",
         offsets=[60], direction="BOTH",
         gates=["g_tr_stack_full_with","g_above_1h_dailyvwap_with","g_offset_early","g_vol_high","g_pw_trend_slope_with","g_vol_extreme_high"]),
]
# SOL 15M V7 — note the "V6+g_..." gate stack means V6 BASE (HOD_EU + off_60_240 + rf + tr_stack) is prepended
# V6 base sleeve = SOL_15M_HOD_EU_OFF60_240_RF_TR_VWAP80_V6 = g_hod_european_morning + g_off_60_240 + g_rf_with + g_tr_stack_with
V6_BASE_SOL15M = ["g_hod_european_morning","g_off_60_240","g_rf_with","g_tr_stack_with"]
V7_TOP += [
    dict(version="V7", sleeve_id="SOL_15M_V7_S3_XADX_ETHVOLLOW", asset="SOL", tf="15m",
         offsets=[60,120,240], direction="BOTH",
         gates=V6_BASE_SOL15M + ["g_BTC_adx_strong","g_ETH_adx_strong","g_ETH_vol_low"]),
    dict(version="V7", sleeve_id="SOL_15M_V7_S1_BTC_ADX_VOLLOW", asset="SOL", tf="15m",
         offsets=[60,120,240], direction="BOTH",
         gates=V6_BASE_SOL15M + ["g_BTC_tr_stack_with","g_BTC_adx_strong","g_BTC_vol_low"]),
    dict(version="V7", sleeve_id="SOL_15M_V7_S1_BTC_ADX_VOLLOW_V2", asset="SOL", tf="15m",
         offsets=[60,120,240], direction="BOTH",
         gates=V6_BASE_SOL15M + ["g_ETH_tr_stack_with","g_BTC_adx_strong","g_BTC_vol_low"]),
    dict(version="V7", sleeve_id="SOL_15M_V7_S5_BTC_SLOPE_STR", asset="SOL", tf="15m",
         offsets=[60,120,240], direction="BOTH",
         gates=V6_BASE_SOL15M + ["g_BTC_slope_with","g_BTC_slope_strong_with"]),
    dict(version="V7", sleeve_id="SOL_15M_V7_S5_BTC_SLOPE_STR_V2", asset="SOL", tf="15m",
         offsets=[60,120,240], direction="BOTH",
         gates=V6_BASE_SOL15M + ["g_BTC_slope_strong_with"]),
]
SLEEVES += V7_TOP

# Save to CSV
rows = []
for s in SLEEVES:
    rows.append(dict(
        version=s["version"],
        sleeve_id=s["sleeve_id"],
        asset=s["asset"],
        tf=s["tf"],
        offsets=str(s["offsets"]) if s["offsets"] is not None else "ALL",
        direction=s["direction"],
        n_gates=len(s["gates"]),
        gate_stack="|".join(s["gates"]),
    ))
df = pd.DataFrame(rows)
df.to_csv(f"{OUT}/sleeve_registry.csv", index=False)
print(f"SAVED {len(df)} sleeves -> {OUT}/sleeve_registry.csv")
print()
print(df.groupby("version")["sleeve_id"].count())
print()
print(df.groupby(["version","asset","tf"])["sleeve_id"].count())
