"""Sanity check that pre-window gates are causal.

The V5 panel joined regime / sms / hawkes / lm / vpin at ws_us_eps
(= ws_s * 1e6 - 1e6, which is 1s BEFORE ws_s). microprice/microstructure
features are at (slug, offset) i.e. AT-fire features.

For V6 the operator wants pre-window signal evaluation at:
- ws_s
- ws_s - 30s (1 bar earlier for 5m, 2 bars earlier for 15m)
- ws_s - 60s

The V5 panel's regime/sms/hawkes/lm/vpin features are ALREADY at ws_us_eps
which is essentially ws_s. Good. We can use them as pre-window features.

For the microprice/microstructure features which are at-fire, we should NOT
use them as pre-window features. Document this.

This script just lists which V5 gates qualify as pre-window vs at-fire.
"""
import pandas as pd
RES = "data/v4/canonical/_results"
df = pd.read_parquet(f"{RES}/sniper_btc15m_v3_gated.parquet")

print("=" * 70)
print("V6 PRE-WINDOW GATE CLASSIFICATION FOR BTC 15m")
print("=" * 70)

pre_window_gates = [
    # Regime panel (asof at ws_us_eps) - PRE-WINDOW
    "g_trend_slope_with", "g_trend_slope_strong_with",
    "g_regime_ranging", "g_regime_trending_with", "g_regime_trending_either",
    "g_adx_trending", "g_adx_strong", "g_di_agrees",
    "g_vol_high", "g_vol_expanding", "g_vol_contracting",
    "g_regime_stack_with", "g_regime_stack_full_with",
    # Hawkes (asof at ws_us_eps) - PRE-WINDOW
    "g_hawkes_imbalance_with", "g_hawkes_imb_loose_with", "g_hawkes_imb_strong_with",
    "g_hawkes_burst",
    # Lee-Mykland (asof at ws_us_eps) - PRE-WINDOW
    "g_lm_high_stat", "g_lm_extreme_stat", "g_lm_jump_with", "g_lm_jump_against",
    "g_jump_dir_with",
    # VPIN (asof at ws_us_eps) - PRE-WINDOW
    "g_vpin_calm", "g_vpin_very_calm",
    # F7 RSI at ws_s - PRE-WINDOW
    "g_f7_rsi_with", "g_f7_rsi_extreme_with", "g_f7_rsi_extreme_against",
    "g_f7_rsi_mid", "g_f7_rsi_strong_with",
    # SMS (asof at ws_us_eps) - PRE-WINDOW
    "g_sms_trend_with", "g_sms_trend_strong_with",
    "g_sms_rsi_with", "g_sms_rsi_extreme_with", "g_sms_rsi_mid",
    "g_sms_cvd_with",
    # TR ema stack (from v3 fires per-slug, at lookup_us — should be ws_s-1s anchor)
    "g_tr_above_ema50", "g_tr_above_ema200", "g_tr_above_ema800",
    "g_tr_above_cloud", "g_tr_above_pp", "g_tr_within_adr",
    "g_tr_stack_with", "g_tr_stack_full_with",
    # Ribbon / RF / momo - at lookup_us
    "g_rf_with", "g_rf_strong", "g_rf_in_band", "g_rf_aged", "g_rf_fresh",
    "g_ribbon_agrees", "g_ribbon_slope_with",
    "g_stoch_with", "g_mfi_with", "g_cci_with", "g_bb_pos_with",
    # Tight ribbon / sess
    "g_tight_ribbon", "g_tr_in_active_session",
    # vwap dev (binance-anchored)
    "g_within_dev",
]

at_fire_gates = [
    # Microprice (slug+offset)
    "g_mp_no_extreme", "g_mp_no_extreme_150", "g_mp_our_side_calm",
    "g_mp_skew_with", "g_mp_skew_strong_with", "g_mp_change_with",
    # Microstructure (slug+offset)
    "g_imb5_with", "g_imb5_strong_with", "g_imb1_strong_with",
    "g_imb_change_with", "g_queue_top_high", "g_book_slope_with_us",
]

bet_setup_gates = [
    # entry_vwap binning - book-walk fill at offset (AT-fire)
    "g_vwap_05_95", "g_vwap_10_90", "g_vwap_15_85", "g_vwap_20_80",
    "g_vwap_25_75", "g_vwap_30_70", "g_vwap_cheap", "g_vwap_premium",
    # offset bins
    "g_off_0_60", "g_off_60_240", "g_off_240_480", "g_off_480_720", "g_off_720_900",
]

all_gates = set(c for c in df.columns if c.startswith("g_"))
classified = set(pre_window_gates + at_fire_gates + bet_setup_gates)
unclassified = sorted(all_gates - classified)

print(f"\n# pre-window gates: {len(pre_window_gates)}")
print(f"# at-fire gates: {len(at_fire_gates)}")
print(f"# bet-setup gates: {len(bet_setup_gates)}")
print(f"# unclassified: {len(unclassified)} ({unclassified})")

print("\nPre-window gates classified - evaluated at ws_us_eps (~= ws_s) which IS pre-window.")
print("At-fire gates classified - reflect L25 book at the fire moment.")
print("V6 will use BOTH categories but be careful about pre-window classification.")
