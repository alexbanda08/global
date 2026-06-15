# 2-Month Sleeve Audit: Comprehensive Report
**Date:** 2026-06-08 | **Universe:** 107 sleeves across 13 families

---

## Executive Summary

**1.** The directional prediction meta-result holds: of 107 sleeves audited, only the **scalp-exit family** (intra-window execution edge) and **3-4 sniper_v5 ETH/BTC sleeves** show live t-stats above 1.9 with coherent backtests. Every family that relied on predicting direction (momo, momo_v2, v3/v4, fade, inv_night, vwap, phase1_kelly, prewindow) is net-negative or statistically flat after fee drag.

**2.** The **momo/momo_v2 family backtests are entirely invalid** — the ws_s=suffix-900 anchor bug fired 13 minutes pre-open on a non-existent book at fake vwap 0.49, inflating apparent WR by 10-20pp and $/tr by $3-5/tr. Corrected BT shows BTC −$0.28/tr, ETH +$0.62/tr, SOL −$1.11/tr. Every live positive result in these families is regime-specific and not supported by a valid backtest.

**3.** The **sniper_v5 fleet has 4 KEEP sleeves** (ETH Hurst/cloud family with t≥1.4, WR consistently above breakeven), ~10 genuine WATCH candidates, and ~30 confirmed KILLs. RF UP-bias and imb5 look-ahead invalidate the BTC 5m V8 flow sleeves entirely.

**4.** The **≤35% WR fade candidates** (v3/v4 ETH UP-heavy sleeves and btc_5m_down_contrarian2k) are NOT genuine counter-edges — the ETH v3 series is buying UP at fair vwap with structurally broken spread filters, not a systematic directional mistake exploitable by fading. Do not deploy fade strategies on these signals.

---

## 1. Master Comparison Table

### Family: momo

| Sleeve | Live n | Live WR% | Live $/tr | BT WR% | BT $/tr | Fidelity | Verdict |
|--------|--------|----------|-----------|--------|---------|----------|---------|
| poly_updown_sol_15m_momo_HOLD_f7 | 76 | 72.4% | +3.63 | 57.6%* | +3.59* | DRIFT | WATCH |
| poly_updown_btc_15m_momo_HOLD_f7 | 68 | 67.6% | +3.31 | 57.6%* | +3.59* | DRIFT | WATCH |
| poly_updown_eth_15m_momo_HOLD_f7 | 74 | 68.9% | +2.64 | 50.9%* | +0.37* | DRIFT | KILL |
| poly_updown_btc_5m_momo_HOLD_f7 | 76 | 51.3% | +0.41 | n/a* | n/a* | DRIFT | KILL |
| poly_updown_sol_5m_momo_HOLD_f7 | 190 | 61.1% | −1.22 | n/a* | n/a* | DRIFT | KILL |
| poly_updown_eth_5m_momo_HOLD_f7 | 127 | 47.2% | −1.77 | n/a* | n/a* | DRIFT | KILL |
| shadow_poly_updown_sol_5m_momo_v1_m5v | 116 | 64.7% | −2.90 | 59.8%* | +4.71* | DRIFT | KILL |

*All momo BT figures derived from invalid ws_s=suffix-900 anchor (fake vwap 0.49). Corrected BT: BTC −$0.28/tr, ETH +$0.62/tr, SOL −$1.11/tr.

---

### Family: momo_v2

| Sleeve | Live n | Live WR% | Live $/tr | BT WR% | BT $/tr | Fidelity | Verdict |
|--------|--------|----------|-----------|--------|---------|----------|---------|
| poly_updown_btc_5m_momo_v2_hod_mtf | 41 | 63.4% | +1.14 | n/a | n/a | NO_BACKTEST | NEEDS-CORRECT-BT |
| shadow_poly_updown_btc_15m_momo_v2_fairedge500_cvd30 | 33 | 60.6% | +1.25 | n/a | n/a | NO_BACKTEST | WATCH |
| poly_updown_eth_15m_momo_v2_hod | 27 | 63.0% | +1.03 | n/a | n/a | NO_BACKTEST | WATCH |
| poly_updown_sol_15m_momo_v2_HOLD_f7 | 72 | 63.9% | +1.24 | 57.6%* | +3.59* | DRIFT | KILL |
| poly_updown_eth_15m_momo_v2_HOLD_f7 | 68 | 58.8% | −0.59 | 57.6%* | +3.59* | DRIFT | KILL |
| poly_updown_btc_15m_momo_v2_HOLD_f7 | 64 | 46.9% | −4.82 | 57.6%* | +3.59* | DRIFT | KILL |
| poly_updown_btc_15m_momo_v2_hod | 26 | 50.0% | −3.54 | n/a | n/a | NO_BACKTEST | KILL |
| shadow_poly_updown_btc_5m_momo_v2_fairedge500 | 164 | 57.9% | −1.42 | n/a | n/a | NO_BACKTEST | KILL |
| poly_updown_sol_5m_momo_v2_hod | 64 | 50.0% | −5.48 | n/a | n/a | NO_BACKTEST | KILL |
| poly_updown_eth_5m_momo_v2_HOLD_f7 | 213 | 56.8% | −2.25 | 57.6%* | +3.59* | DRIFT | KILL |
| poly_updown_btc_5m_momo_v2_HOLD_f7 | 96 | 41.7% | −4.44 | 57.6%* | +3.59* | DRIFT | KILL |
| poly_updown_sol_5m_momo_v2_HOLD_f7 | 205 | 57.6% | −2.64 | 57.6%* | +3.59* | DRIFT | KILL |
| poly_updown_sol_15m_momo_v2_hod | 21 | 52.4% | −2.14 | n/a | n/a | NO_BACKTEST | KILL |
| shadow_poly_updown_sol_5m_momo_v2_cvd_macd | 94 | 55.3% | −5.25 | n/a | n/a | NO_BACKTEST | KILL |

*All HOLD_f7 momo_v2 BT figures from invalid buggy anchor (same ws_s=suffix-900 bug).

---

### Family: sniper_v5

| Sleeve | Live n | Live WR% | Live $/tr | BT WR% | BT $/tr | Fidelity | Verdict |
|--------|--------|----------|-----------|--------|---------|----------|---------|
| poly_sniper_v5_btc_15m_ema50_ema800_off600_down | 260 | 78.0% | +0.78 | 82.0% | +1.11* | FAITHFUL | WATCH |
| poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7 | 603 | 67.8% | +0.39 | n/a | n/a | FAITHFUL | KEEP |
| poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8 | 626 | 66.8% | +0.33 | 82.0% | +0.97 | FAITHFUL | KEEP |
| poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_v6 | 218 | 72.5% | +0.33 | n/a | n/a | FAITHFUL | KEEP |
| poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7_vL | 688 | 66.7% | +0.30 | n/a | n/a | FAITHFUL | KEEP |
| poly_sniper_v5_eth_15m_trstack_vwap_vol_offearly_band_v6 | 32 | 71.9% | +1.21 | n/a | n/a | FAITHFUL | WATCH |
| poly_sniper_v5_eth_15m_trstack_vwap_vol_offearly | 32 | 71.9% | +1.21 | n/a | n/a | FAITHFUL | WATCH |
| poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_V10 | 62 | 75.8% | +0.68 | n/a | n/a | FAITHFUL | WATCH |
| poly_sniper_v5_eth_15m_trstack_vwap_vol_offearly_band_v6_vL | 38 | 68.4% | +0.90 | n/a | n/a | FAITHFUL | WATCH |
| poly_sniper_v5_eth_15m_trstack_vwap_vol_offearly_vL | 38 | 68.4% | +0.90 | n/a | n/a | FAITHFUL | WATCH |
| poly_sniper_v5_eth_5m_v5repl_off120_v6 | 51 | 76.5% | +0.83 | n/a | n/a | UNKNOWN | WATCH |
| poly_sniper_v5_eth_5m_tr200_mp_sms_active_off120 | 51 | 76.5% | +0.83 | n/a | n/a | UNKNOWN | WATCH |
| poly_sniper_v5_eth_5m_bb_mp_hurst_band_V10 | 81 | 53.1% | +0.73 | n/a | n/a | FAITHFUL | WATCH |
| poly_sniper_v5_btc_5m_a2_hlcascade100k_v9 | 126 | 56.3% | +1.24 | n/a | n/a | UNKNOWN | WATCH |
| poly_sniper_v5_sol_5m_btctrend_cci_hurstrev_v7 | 66 | 68.2% | +1.09 | n/a | n/a | UNKNOWN | WATCH |
| poly_sniper_v5_eth_5m_cloud_mp_sms_active_off120 | 38 | 60.5% | +1.15 | n/a | n/a | UNKNOWN | WATCH |
| poly_sniper_v5_btc_15m_ema50_ema800_off600_down_H | 295 | 91.6% | +0.52 | 82.0% | n/a† | FAITHFUL | WATCH |
| poly_sniper_v5_eth_5m_v6c3_parent15mrang_v7 | 151 | 72.8% | +0.37 | n/a | n/a | UNKNOWN | WATCH |
| poly_sniper_v5_eth_15m_trstack_vwap_offearly | 183 | 61.7% | +0.28 | n/a | n/a | FAITHFUL | WATCH |
| poly_sniper_v5_eth_5m_v6c3_parent15mrang_v7_vL | 176 | 72.2% | +0.26 | n/a | n/a | UNKNOWN | WATCH |
| poly_sniper_v5_eth_5m_bb_mp_hurst_band_v6 | 316 | 63.0% | +0.12 | n/a | n/a | FAITHFUL | KEEP |
| poly_sniper_v5_eth_5m_bb_mp_hurst_band_v6_vL | 359 | 62.4% | +0.07 | n/a | n/a | FAITHFUL | WATCH |
| poly_sniper_v5_eth_15m_pw_trendslope_trstack_offearly_v6 | 21 | 66.7% | +1.05 | n/a | n/a | FAITHFUL | WATCH |
| poly_sniper_v5_eth_15m_baseline_v7_top_replicate_v8 | 21 | 66.7% | +0.99 | n/a | n/a | FAITHFUL | WATCH |
| poly_sniper_v5_eth_15m_pi_btc15m_trend_v7 | 21 | 66.7% | +0.90 | n/a | n/a | FAITHFUL | WATCH |
| poly_sniper_v5_btc_15m_vwapprem_ema50_mpskew_off600_v6 | 110 | 87.3% | +0.04 | n/a | n/a | FAITHFUL | WATCH |
| poly_sniper_v5_btc_5m_parent15m_notrang_ts_mpskew_v7 | 441 | 47.6% | +0.09 | n/a | n/a | FAITHFUL | KILL |
| poly_updown_sol_5m_sniper_hod | 151 | 53.0% | +0.48 | n/a | n/a | UNKNOWN | WATCH |
| poly_sniper_v5_eth_5m_ema50_hurst_parent15mrang_v7 | 877 | 65.1% | +0.09 | n/a | n/a | FAITHFUL | WATCH |
| poly_sniper_v5_eth_5m_lq_ema50_hurst_grandparent_prev15m_v8 | 130 | 67.7% | +0.24 | n/a | n/a | UNKNOWN | WATCH |
| poly_sniper_v5_sol_5m_b3_abs500_no_opp_v9 | 46 | 65.2% | +1.06 | n/a | n/a | UNKNOWN | WATCH |
| poly_sniper_v5_eth_5m_lq_ema50_hurst_grandparent_prev15m_v8_vL | 146 | 65.1% | +0.03 | n/a | n/a | UNKNOWN | WATCH |
| poly_sniper_v5_sol_5m_depth_up_hod_session | 29 | 65.5% | +0.07 | n/a | n/a | UNKNOWN | WATCH |
| poly_sniper_v5_sol_15m_rfaged_trstack_late_vL | 15 | 86.7% | +0.34 | n/a | n/a | UNKNOWN | WATCH |
| poly_sniper_v5_sol_15m_rfaged_trstack_late | 15 | 86.7% | +0.29 | n/a | n/a | UNKNOWN | WATCH |
| poly_sniper_v5_eth_15m_pj_btc_and_sol_trend_sep_v8 | 17 | 58.8% | +0.33 | n/a | n/a | FAITHFUL | WATCH |
| poly_sniper_v5_btc_15m_ts_trstack_off600_down | 101 | 84.2% | +0.33 | n/a | n/a | FAITHFUL | WATCH |
| poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_V10 | 284 | 65.1% | +0.19 | n/a | n/a | FAITHFUL | WATCH |
| poly_sniper_v5_btc_15m_mpskew_trstack_off600_down | 29 | 89.7% | +0.04 | n/a | n/a | FAITHFUL | WATCH |
| poly_sniper_v5_sol_5m_j_2asset_trending_cci_rf_ema200_v8 | 1007 | 71.9% | +0.04 | n/a | n/a | UNKNOWN | WATCH |
| poly_sniper_v5_sol_5m_cci_f7_mfi_partial_vwap_v6 | 235 | 73.6% | +0.10 | n/a | n/a | UNKNOWN | WATCH |
| poly_sniper_v5_eth_5m_ema50_hurst_parent15mrang_v7_vL | 1010 | 64.7% | +0.05 | n/a | n/a | FAITHFUL | KILL |
| poly_sniper_v5_sol_5m_rf_tr_partial_mid | 1185 | 69.1% | +0.06 | n/a | n/a | UNKNOWN | KILL |
| poly_sniper_v5_sol_5m_rf_tr_pp_mid | 235 | 67.7% | +0.08 | n/a | n/a | UNKNOWN | KILL |
| poly_sniper_v5_btc_15m_ema200_mpskew_rf_off600_down_v6 | 66 | 68.2% | −0.35 | n/a | n/a | FAITHFUL | WATCH |
| poly_sniper_v5_sol_15m_trstack_vol_ribbon_ema_mid_vL | 25 | 68.0% | −0.37 | n/a | n/a | FAITHFUL | WATCH |
| poly_sniper_v5_sol_15m_trstack_vol_ribbon_ema_mid | 25 | 68.0% | −0.45 | n/a | n/a | FAITHFUL | WATCH |
| poly_sniper_v5_eth_5m_bb_mp_hurst_band_v6_vL | 359 | 62.4% | +0.07 | n/a | n/a | FAITHFUL | WATCH |
| poly_sniper_v5_btc_15m_ema800_ribslp_hawkes_off840_v6 | 165 | 58.9% | −0.64 | n/a | n/a | UNKNOWN | KILL |
| poly_sniper_v5_eth_5m_a2_hlcascade50k_v9 | 131 | 48.9% | +0.06 | n/a | n/a | UNKNOWN | KILL |
| poly_sniper_v5_btc_15m_regime_trstack_off480_up | 27 | 59.3% | −1.13 | n/a | n/a | UNKNOWN | KILL |
| poly_sniper_v5_sol_5m_btcf7against_cci_hurstrev_mfi_v8 | 15 | 40.0% | −0.63 | n/a | n/a | UNKNOWN | KILL |
| poly_sniper_v5_sol_5m_b1_polyflow_aligned_v9 | 15 | 80.0% | −0.64 | n/a | n/a | UNKNOWN | KILL |
| poly_sniper_v5_btc_5m_ts_mpskew_s6_0_60 | 15 | 40.0% | −0.87 | n/a | n/a | UNKNOWN | KILL |
| poly_sniper_v5_sol_15m_hod_eu_tightrib_rf_tr_vwap80_v6 | 43 | 76.7% | −0.37 | n/a | n/a | UNKNOWN | KILL |
| poly_sniper_v5_sol_5m_b1_120s_250_v9 | 92 | 79.3% | −0.18 | n/a | n/a | UNKNOWN | KILL |
| poly_sniper_v5_sol_5m_down_b1_flow250_v9 | 38 | 76.3% | −0.53 | n/a | n/a | UNKNOWN | KILL |
| poly_sniper_v5_btc_5m_up_b2_contrarian2k_v9 | 27 | 37.0% | −0.21 | n/a | n/a | UNKNOWN | KILL |
| poly_sniper_v5_eth_5m_k_hurst_ts_cci_tod_euus_v8_vL | 82 | 51.2% | −0.73 | n/a | n/a | UNKNOWN | KILL |
| poly_sniper_v5_eth_5m_up_a2_hlcascade25k_v9 | 169 | 44.4% | −0.36 | n/a | n/a | UNKNOWN | KILL |
| poly_sniper_v5_eth_5m_k_hurst_ts_cci_tod_euus_v8 | 71 | 49.3% | −1.23 | n/a | n/a | UNKNOWN | KILL |
| poly_updown_eth_15m_sniper_hod | 86 | 47.7% | +0.34 | n/a | n/a | UNKNOWN | KILL |
| poly_sniper_v5_sol_5m_f7_mfi_ema200_vwap_v6 | 1046 | 68.1% | −0.09 | n/a | n/a | UNKNOWN | KILL |
| poly_sniper_v5_btc_5m_l_1hrf_imb5_ribbon_v8 | 584 | 63.0% | +0.32 | n/a | n/a | DRIFT | KILL |
| poly_sniper_v5_btc_5m_l_1hrf_imb5_rf_v8 | 905 | 56.1% | +0.13 | n/a | n/a | DRIFT | KILL |
| poly_sniper_v5_sol_5m_f7_mp_ema200_vwap_v6 | 421 | 65.3% | −0.26 | n/a | n/a | UNKNOWN | KILL |
| poly_sniper_v5_sol_5m_btcf7_f7overb_ema800_vwap_v7 | 456 | 64.8% | −0.06 | n/a | n/a | UNKNOWN | KILL |
| poly_sniper_v5_eth_5m_ema200_vwap_regimerang_xa3_v7 | 565 | 61.3% | −0.28 | n/a | n/a | UNKNOWN | KILL |
| poly_sniper_v5_btc_5m_ts_mpskew_any_off30 | 490 | 49.2% | −0.25 | n/a | n/a | FAITHFUL | KILL |
| poly_sniper_v5_btc_5m_q_parent15mslope_ts_imb5_v8 | 1114 | 47.3% | −0.21 | n/a | n/a | DRIFT | KILL |
| poly_sniper_v5_btc_5m_parent15m_slope_ts_mpnx_v7 | 971 | 48.7% | −0.31 | n/a | n/a | UNKNOWN | KILL |
| poly_sniper_v5_btc_5m_up_a2_hlcascade50k_v9 | 151 | 44.4% | −0.24 | n/a | n/a | UNKNOWN | KILL |
| poly_sniper_v5_btc_5m_down_b2_contrarian2k_v9 | 26 | 23.1% | −1.49 | n/a | n/a | UNKNOWN | KILL |
| poly_updown_btc_15m_sniper_hod | 79 | 48.1% | −0.61 | n/a | n/a | UNKNOWN | KILL |
| poly_sniper_v5_sol_5m_b3_abs500_v9 | 46 | 41.3% | −1.15 | n/a | n/a | UNKNOWN | KILL |
| poly_updown_btc_5m_sniper_hod | 94 | 39.4% | −3.49 | n/a | n/a | NO_BACKTEST | KILL |
| poly_updown_eth_5m_sniper_hod | 96 | 42.7% | −4.09 | n/a | n/a | NO_BACKTEST | KILL |

*bt_tr adjusted from legacy 2% fee to 0.07-curve. †HEDGE_LATE exit not in BT.

---

### Family: scalp_exit

| Sleeve | Live n | Live WR% | Live $/tr | BT WR% | BT $/tr | Fidelity | Verdict |
|--------|--------|----------|-----------|--------|---------|----------|---------|
| shadow_scalp_exit_btc_5m_v1 | 23 | 56.5% | +2.64 | 75.4% | +4.24 | DRIFT | WATCH |
| shadow_scalp_exit_btc_15m_v1 | 16 | 62.5% | +2.53 | 75.4% | +4.85 | DRIFT | WATCH |
| shadow_scalp_exit_btc_5m_d3_v1 | 81 | 59.3% | +0.42 | 68.6% | +0.51 | FAITHFUL | KEEP |
| shadow_scalp_exit_btc_15m_d3_v1 | 44 | 63.6% | +0.45 | 71.7% | +0.31 | FAITHFUL | KEEP |
| shadow_scalp_exit_eth_5m_d3_v1 | 22 | 50.0% | +0.21 | 60.6% | +0.25 | FAITHFUL | WATCH |
| shadow_scalp_exit_btc_5m_d3_tod2_v1 | 26 | 53.8% | +0.07 | n/a | n/a | NO_BACKTEST | WATCH/FADE |
| shadow_scalp_exit_btc_5m_d3_control_v1 | 358 | 57.3% | +0.07 | n/a | n/a | NO_BACKTEST | KEEP-AS-DIAG |
| shadow_scalp_exit_btc_15m_d3_control_v1 | 94 | 47.9% | +0.05 | n/a | n/a | NO_BACKTEST | KEEP-AS-DIAG |
| shadow_scalp_exit_eth_5m_d3_control_v1 | 81 | 55.6% | +0.001 | n/a | n/a | NO_BACKTEST | KEEP-AS-DIAG |
| shadow_scalp_exit_btc_15m_control_v1 | 39 | 41.0% | −0.34 | n/a | n/a | NO_BACKTEST | KEEP-AS-DIAG |
| shadow_scalp_exit_eth_5m_control_v1 | 52 | 50.0% | −1.14 | n/a | n/a | NO_BACKTEST | WATCH |
| shadow_scalp_exit_btc_5m_control_v1 | 135 | 48.9% | −0.44 | n/a | n/a | NO_BACKTEST | KEEP-AS-DIAG |

---

### Family: kalshi_sniper

| Sleeve | Live n | Live WR% | Live $/tr | BT WR% | BT $/tr | Fidelity | Verdict |
|--------|--------|----------|-----------|--------|---------|----------|---------|
| kalshi_sniper_all_15m_s4_prewindow | 54 | 50.0% | +0.22 | n/a | n/a | NO_BACKTEST | WATCH |
| kalshi_sniper_btc_15m_ema50_ema800_off600_down | 169 | 79.3% | +0.005 | 82.0% | +1.59 | FAITHFUL | WATCH |
| kalshi_sniper_btc_15m_ema50_ema800_off600_down_H | 150 | 76.7% | −0.002 | 82.0% | n/a | DRIFT | KILL |

---

### Family: lagv2

| Sleeve | Live n | Live WR% | Live $/tr | BT WR% | BT $/tr | Fidelity | Verdict |
|--------|--------|----------|-----------|--------|---------|----------|---------|
| poly_fast_taker_lagv2_btc_15m | 273 | 97.8% | +0.17 | 68.1% | +3.42 | DRIFT | WATCH |
| poly_fast_taker_lagv2_btc_5m | 901 | 89.2% | −0.22 | 68.1% | +3.42 | DRIFT | WATCH |
| poly_fast_taker_lagv2_eth_5m | 561 | 95.7% | −0.38 | 68.1% | +3.42 | DRIFT | WATCH/FADE |
| poly_fast_taker_lagv2_eth_15m | 77 | 93.3% | −1.44 | 68.1% | +3.42 | DRIFT | KILL |

---

### Family: vwap

| Sleeve | Live n | Live WR% | Live $/tr | BT WR% | BT $/tr | Fidelity | Verdict |
|--------|--------|----------|-----------|--------|---------|----------|---------|
| poly_updown_eth_5m_vwap_off210_f7_m1v | 76 | 57.9% | +0.12 | 92.6%* | +1.26* | DRIFT | KILL |
| poly_updown_btc_5m_vwap_off90_cross | 158 | 61.4% | −1.73 | 78.7%* | +1.89* | DRIFT | KILL |
| poly_updown_btc_5m_vwap_off60_f7_cross | 107 | 55.1% | −1.92 | 73.8%* | +3.10* | DRIFT | KILL |
| poly_updown_sol_5m_vwap_off60 | 122 | 54.1% | −3.03 | 75.0%* | +1.66* | DRIFT | KILL |
| poly_updown_btc_5m_vwap_off240_m1v | 149 | 51.7% | −3.26 | 86.3%* | +2.00* | DRIFT | KILL |

*All vwap BT figures use LegacyConfig 2%-on-profit (wrong fee model). No OOS window.

---

### Family: v3v4

| Sleeve | Live n | Live WR% | Live $/tr | BT WR% | BT $/tr | Fidelity | Verdict |
|--------|--------|----------|-----------|--------|---------|----------|---------|
| poly_updown_btc_5m_v3_1 | 90 | 44.4% | −0.65 | 55.9%* | +1.06* | DRIFT | WATCH |
| poly_updown_sol_5m_v3_2 | 190 | 51.1% | −0.69 | 57.7%* | +1.68* | DRIFT | WATCH |
| poly_updown_sol_5m_v3 | 145 | 49.0% | −1.12 | 56.4%* | +1.90* | DRIFT | WATCH |
| poly_updown_sol_5m_v3_1 | 121 | 47.9% | −1.87 | 52.4%* | −0.17* | DRIFT | WATCH |
| poly_updown_sol_5m_v3_3 | 123 | 46.3% | −1.89 | 52.1%* | +0.16* | DRIFT | WATCH |
| poly_updown_eth_5m_v3 | 55 | 43.6% | −3.43 | 45.5%* | +0.58* | DRIFT | KILL |
| poly_updown_eth_5m_v3_1 | 29 | 34.5% | −6.21 | 38.5%* | −1.36* | DRIFT | KILL |
| poly_updown_eth_5m_v3_2 | 41 | 34.1% | −5.72 | 37.5%* | −1.71* | DRIFT | KILL |
| poly_updown_eth_5m_v3_3 | 41 | 34.1% | −5.72 | 37.5%* | −1.71* | DRIFT | KILL |
| poly_updown_btc_5m_v4 | 64 | 42.2% | −3.80 | 53.9%* | −1.12* | DRIFT | KILL |
| poly_updown_eth_5m_v4 | 25 | 32.0% | −5.92 | n/a* | n/a* | NO_BACKTEST | KILL |

*All v3/v4 BT figures are from 2.5-day live shadow window (May 27-29), not proper offline backtests.

---

### Family: fade

| Sleeve | Live n | Live WR% | Live $/tr | BT WR% | BT $/tr | Fidelity | Verdict |
|--------|--------|----------|-----------|--------|---------|----------|---------|
| shadow_poly_updown_btc_5m_fade_momo_v2 | 222 | 50.5% | −0.55 | n/a | n/a | NO_BACKTEST | KILL |
| shadow_poly_updown_eth_15m_fade_sniper | 243 | 51.4% | −1.03 | n/a | n/a | NO_BACKTEST | KILL |
| shadow_poly_updown_sol_5m_fade_momo_v2 | 204 | 50.0% | −1.42 | n/a | n/a | NO_BACKTEST | KILL |
| shadow_poly_updown_btc_5m_fade_sniper | 429 | 50.3% | −1.12 | n/a | n/a | NO_BACKTEST | KILL |
| shadow_poly_updown_sol_5m_fade_sniper | 421 | 52.5% | −1.04 | n/a | n/a | NO_BACKTEST | KILL |
| shadow_poly_updown_sol_15m_fade_momo_v2 | 113 | 36.3% | −5.82 | n/a | n/a | NO_BACKTEST | KILL IMMEDIATELY |

---

### Family: inv_night

| Sleeve | Live n | Live WR% | Live $/tr | BT WR% | BT $/tr | Fidelity | Verdict |
|--------|--------|----------|-----------|--------|---------|----------|---------|
| poly_updown_btc_15m_volume_INV_NIGHT | 268 | 51.5% | −0.34 | 50.1%* | −1.22* | NO_BACKTEST | KILL (already off) |
| poly_updown_eth_15m_volume_INV_NIGHT | 149 | 51.7% | −0.46 | 50.1%* | −1.22* | NO_BACKTEST | KILL (already off) |
| poly_updown_sol_15m_volume_INV_NIGHT | 136 | 48.5% | −2.10 | 50.1%* | −1.22* | NO_BACKTEST | KILL (already off) |
| poly_updown_btc_5m_volume_INV_NIGHT | 441 | 47.4% | −2.01 | 50.1%* | −1.22* | NO_BACKTEST | KILL (already off) |
| poly_updown_eth_5m_volume_INV_NIGHT | 440 | 48.6% | −1.98 | 50.1%* | −1.22* | NO_BACKTEST | KILL (already off) |
| poly_updown_sol_5m_volume_INV_NIGHT | 417 | 45.8% | −3.45 | 50.1%* | −1.22* | NO_BACKTEST | KILL (already off) |

*5-day IS shadow data cited as "backtest" is invalid.

---

### Family: prewindow_s3s4

| Sleeve | Live n | Live WR% | Live $/tr | BT WR% | BT $/tr | Fidelity | Verdict |
|--------|--------|----------|-----------|--------|---------|----------|---------|
| shadow_poly_updown_ALL_5m_S3_prewindow | 485 | 51.1% | −0.49 | 38.8% | −5.82 | DRIFT | WATCH |
| shadow_poly_updown_ALL_15m_S4_prewindow | 66 | 53.0% | +2.09 | 38.8% | −5.82 | DRIFT | KILL |

---

### Family: phase1_kelly

| Sleeve | Live n | Live WR% | Live $/tr | BT WR% | BT $/tr | Fidelity | Verdict |
|--------|--------|----------|-----------|--------|---------|----------|---------|
| shadow_poly_updown_ALL_5m_phase1_kelly | 1386 | 50.6% | −1.45 | 53.0% | +2.72 | FAITHFUL | KILL |
| shadow_poly_updown_ALL_5m_phase1_kelly_fe1000_V10 | 949 | 50.6% | −0.67 | n/a | n/a | NO_BACKTEST | KILL |

---

### Family: oracle_settle

| Sleeve | Live n | Live WR% | Live $/tr | BT WR% | BT $/tr | Fidelity | Verdict |
|--------|--------|----------|-----------|--------|---------|----------|---------|
| shadow_oracle_settle_btc_5m | 19 | 94.7% | +0.18 | 95.2% | +0.37 | FAITHFUL | WATCH |
| shadow_oracle_settle_eth_5m | 38 | 86.8% | −0.24 | 95.2% | +0.37 | FAITHFUL | WATCH/KILL |
| shadow_oracle_settle_sol_5m | 58 | 87.9% | −0.18 | 95.2% | +0.37 | FAITHFUL | KILL |

---

### Family: disagr_hawkes

| Sleeve | Live n | Live WR% | Live $/tr | BT WR% | BT $/tr | Fidelity | Verdict |
|--------|--------|----------|-----------|--------|---------|----------|---------|
| shadow_disagr_hawkes_sol_5m_dn | 21 | 85.7% | −1.25 | 95.3% | +3.70 | FAITHFUL | WATCH→KILL |

---

## 2. Fidelity Findings

### A. The momo ws_s=suffix-900 Bug (Affects All momo and momo_v2 HOLD_f7 Sleeves)

**What the bug is:** The backtesting harness computed `ws_s = suffix - 900` (the slot end time minus the full 900s window), which placed the fire anchor 13 minutes BEFORE the window opens on the PREVIOUS window's bar. This produced:

- A non-existent pre-open book with a fake vwap of approximately 0.49 (the market's binary resting price at resolution, not the live entry price)
- Entry at vwap 0.49 when live entries average 0.57–0.64
- Apparent WR inflation of 10–20pp because at vwap 0.49 the breakeven WR is ~49%, vs live vwap 0.62 requiring ~65% WR to break even

**Corrected BT results** (ws_s = slot_start + window_s, i.e. ws_s+120 anchor per production spec):

| Asset | Corrected BT WR | Corrected BT $/tr |
|-------|-----------------|-------------------|
| BTC | ~55–57% | −$0.28/tr |
| ETH | ~57–59% | +$0.62/tr |
| SOL | ~57–59% | −$1.11/tr |

**Conclusion:** Every backtest figure shown as `bt_wr=57.6%, bt_tr=+3.59` in the momo family is from this buggy harness. The 28d deploy-sleeve backtests (S1–S5 tier) are also entirely invalid for the same reason. **Zero momo/momo_v2 HOLD_f7 sleeves have a valid supporting backtest.** Production code itself is confirmed MATCH to spec — only the BT is broken.

**Sleeves with BT invalidated by this bug (13 sleeves):**
- poly_updown_{btc,eth,sol}_{5m,15m}_momo_HOLD_f7 (6 sleeves)
- poly_updown_{sol,eth,btc}_15m_momo_v2_HOLD_f7 (3 sleeves)
- poly_updown_{eth,btc,sol}_5m_momo_v2_HOLD_f7 (3 sleeves)
- shadow_poly_updown_sol_5m_momo_v1_m5v (1 sleeve — M5V BT on buggy harness)

---

### B. RF UP-Bias in BTC 5m V8 Flow Sleeves

**What the bug is:** Live gate-1 on `l_1hrf_imb5_rf_v8` and `l_1hrf_imb5_ribbon_v8` uses `g_grandparent_trend_with` (a trend-slope 1h proxy) instead of the spec's `g_1h_rf_with` (Range Filter rf_dir). This gate mismatch has persisted since 2026-05-29 without fix.

**Compounding issue:** The Range Filter indicator itself has a UP-bias caused by its hold-rule — `rf_dir` stays at +1 for many bars after a price peak. During June's BTC downtrend (33% of bars were genuinely UP), the RF gate voted UP on 77% of fires. This systematic UP-bias in a downtrend means both BTC 5m flow sleeves were consistently betting the wrong direction in June.

**Imb5 look-ahead invalidation:** The imb5 GA-search used post-fire book snapshots, inflating backtest WR artificially. No valid backtest exists for any imb5 sleeve.

**Sleeves invalidated:** `poly_sniper_v5_btc_5m_l_1hrf_imb5_ribbon_v8` and `poly_sniper_v5_btc_5m_l_1hrf_imb5_rf_v8` — both KILL.

---

### C. lagv2 Structural BT Drift

The live FAST_TAKER_LAGV2 R5 config (4 gates: oracle_lag, not_us_close, cross_asset_confluence, top_depth_ge_median) is correctly implemented, but the only datasheet-linked backtest rows in the corpus used a simpler ungated single-offset config (`clbasis_rel`, bt_wr=86.6%, bt_tr=+$5.95) — a fundamentally different strategy. The R5 backtest reference (bt_wr=68.1%, bt_tr=+$3.42) is the valid comparison; even against that, live BTC 15m shows $/tr=+$0.17 (near zero) and ETH/5m variants are negative. The pre-June-3 always-UP bug also contaminated the early live sample (900/901 BTC 5m fires were UP regardless of oracle signal direction). Post-bugfix sub-samples must be evaluated before any final verdict on lagv2.

---

### D. vwap Family BT Fee Model Error

All vwap family backtests used `LegacyConfig` (2%-on-profit fee) instead of the production `0.07 × p × (1-p)` winner-only curve. At typical vwap values of 0.65–0.83, the legacy model undercharges by approximately $0.36–$0.50 per winning trade. Combined with no OOS window and entry vwap divergence (BT avg ~0.83 vs live ~0.58–0.66), the family has no valid backtest support whatsoever.

---

### E. v3/v4 "Backtests" Are Live Shadow Data

The entire v3/v4 family's backtest corpus consists of a 2.5-day live shadow window (May 27–29), with n ranging from 13 to 78 per sleeve. This is not a pre-registered offline backtest; it is 2.5 days of in-sample live-shadow data. The v3/v4 sleeves have no legitimate backtest. The liq_quiet gate — the core v3_2/v4 differentiating feature — is permanently disabled in production (liq_db=None), meaning all v3_2/v4 claims of "liq_quiet edge" are untestable in live.

---

### F. oracle_settle Structural Vwap Trap

The oracle_settle family is faithfully implemented. The BT showed WR ~95% and $/tr ~+$0.37. Live WR has drifted to 87–95%. The structural issue is not a code bug but a fee arithmetic constraint: at live entry vwap of 0.90–0.91, you need WR > 94% to clear fees (`win pnl = qty × (1−vwap) × (1−0.07×vwap)` requires WR > vwap / (1 - 0.07×vwap×(1-vwap)/vwap) ≈ 0.94). ETH and SOL live WR of 87–88% is structurally below this threshold. The BT's 95% WR was at thinner real-book condition that no longer holds consistently live.

---

## 3. Counter-Edge / Fade-Candidate Analysis (<=35% WR Sleeves, n>=20)

The five sleeves with WR ≤ 35% and n ≥ 20 are analyzed below. The core question: is the WR below what *entry_vwap pricing alone* predicts? A genuine fade edge requires the strategy to be **systematically wrong beyond price-implied probability**.

### Methodology

Breakeven WR at entry_vwap `p` (winner-only 0.07 fee):

```
Breakeven WR = p / (1 - 0.07 × p × (1-p) / (1-p))
             ≈ p / (1 - 0.07 × p)     [for winner-only fee on the 1-p payout]
```

More precisely: break even when `WR × (1-p) × (1-0.07×p) = (1-WR) × p`, solving:

```
WR_break = p / (p + (1-p)(1-0.07×p))
```

| Sleeve | Live WR | Entry Vwap | Breakeven WR | WR vs Breakeven | Genuine Fade? |
|--------|---------|------------|--------------|-----------------|---------------|
| btc_5m_down_b2_contrarian2k_v9 | 23.1% | 0.305 | 30.9% | −7.8pp below | POSSIBLY — see below |
| eth_5m_v4 | 32.0% | 0.515 | 52.3% | −20.3pp below | STRUCTURAL — see below |
| eth_5m_v3_1 | 34.5% | 0.515 | 52.3% | −17.8pp below | STRUCTURAL — see below |
| eth_5m_v3_2 | 34.1% | 0.515 | 52.3% | −18.2pp below | STRUCTURAL — see below |
| eth_5m_v3_3 | 34.1% | 0.515 | 52.3% | −18.2pp below | STRUCTURAL — see below |

---

### btc_5m_down_b2_contrarian2k_v9 (WR 23.1%, entry_vwap 0.305, n=26)

**Analysis:** This sleeve buys DOWN tokens at vwap ~0.305 (i.e. the market prices DOWN probability at ~30.5%). Breakeven WR is ~30.9%. Live WR is 23.1%, which is 7.8pp below breakeven — but at n=26 the 95% binomial CI for WR=23% is approximately [9%, 44%], which spans the breakeven comfortably. The t-stat of −0.98 is not significant.

**More critically:** This is a DOWN-only contrarian flow sleeve, betting DOWN when flow is bullish. In June, BTC was in a genuine downtrend — meaning the contrarian DOWN bet should actually be the *correct* direction, not the wrong one. The WR=23% likely reflects the market pricing DOWN tokens at ~30% and the resolution being UP (BTC down trend) — i.e., the market's 30% DOWN price was *over*pricing DOWN in a sideways-to-down market, and the strategy was buying overpriced DOWN tokens contrarily.

**Genuine fade candidate? NO.** The n=26 sample is too small to establish systematic directional incorrectness vs price. The WR=23% is consistent with random sampling of a 30.5%-priced token in a period where DOWN was genuinely 50–70% likely (reducing the contrarian to net-negative, not a systematic fade). There is no structural mechanism that would make this strategy reliably wrong at a rate exploitable by fading. Furthermore, fading this sleeve would mean buying UP tokens at 1−0.305 = 0.695, requiring WR > ~73% to break even — no evidence supports that.

---

### eth_5m_v3_1, v3_2, v3_3, v4 (WR 32–34.5%, entry_vwap 0.515, n=25–41)

**Analysis:** These four sleeves share ETH v3/v4 architecture and strikingly similar statistics. Entry_vwap ≈ 0.515 means the market prices the bet at ~51.5% probability. Breakeven WR is ~52.3%. Live WR of 32–34.5% is 17–20pp *below* breakeven — a very large gap. The composition: eth_v3_2 and eth_v3_3 show 37 UP vs 4 DOWN (90% UP directional bias); eth_v3_1 shows 24 UP vs 5 DOWN (83% UP bias).

**Root cause analysis:** The ETH v3 family is documented to have a **spread calibration problem** (ETH_5M_V3_V4_DIAGNOSIS): the spread filter is over-tightening, leaving only adversely-selected fires. Nearly all fires are UP-direction, meaning the strategy is almost exclusively buying UP tokens at ~0.51 vwap. In June, BTC (and correlated ETH) showed upward pressure in some weeks but the strategy is not identifying genuinely high-probability moments — it is buying near-coin-flip UP events at ~0.51 price and losing systematically.

**Is this a genuine fade?** It appears so on the numbers, but the mechanism is structural over-filtering and regime mismatch, not a reliably exploitable signal inversion. Specifically:

1. **The directional signal itself is near-coinflip** at vwap ~0.51 — fading would mean buying DOWN tokens at 1−0.515 = 0.485 vwap, requiring WR > ~49% to break even at DOWN prices. If the ETH UP signal is genuinely wrong at the 32–34% WR level, DOWN wins 66–68% of the time — above the 49% breakeven.

2. **However:** The spread over-filtering is selecting thin-book moments, and thin ETH books are correlated with large moves, which may be directionally random. The 17–20pp gap is larger than noise even at n=25–41 (t-stats of −1.48 to −1.89 approach but do not reach significance).

3. **The ETH UP directional bias (83–90% UP fires) in a period that included ETH's mixed/down moves is the real signal**: the v3/v4 quantile threshold is specifically miscalibrated toward UP in ETH. A fade would essentially be "whenever ETH v3 fires UP with spread-filtered thin book, bet DOWN."

**Genuine fade candidate? MARGINAL but NOT ACTIONABLE** for two reasons:

- t-stats of −1.48 to −1.89 do not clear the −2.0 threshold for statistical significance. The v3_2/v3_3 pair at n=41 each have t=−1.89, combined effectively 82 observations — still marginal.
- The structural cause (spread miscalibration → UP bias → adverse selection in thin books) is likely to self-correct if the spread filter is adjusted, making the fade unstable.
- The correct fix is to repair the ETH v3 spread filter or kill the strategy, not to deploy a fade.

**Recommendation: Do NOT deploy fades on any of these five sleeves.** Fix or kill the underlying sleeves instead. The only near-actionable case (ETH v3_2/v3_3) requires at minimum n=150+ combined with consistent t < −2.5 before a fade is worth backtest investigation.

---

**General principle:** A genuine fade edge requires that the strategy's signal contains real predictive information pointing the wrong direction — not just that the strategy is poorly calibrated on price or has structural implementation flaws. All five fade candidates here fail this test: the btc_down_contrarian is too small-n, and the ETH v3 family is broken by spread miscalibration, not systematically misdirected prediction.

---

## 4. Go-Forward Ranked List

### TIER 1 — CONTINUE WITH CURRENT CAPITAL (Real Validated Edges)

**Primary production priority: scalp-exit family (execution edge)**

| Priority | Sleeve | Evidence | Action |
|----------|--------|----------|--------|
| 1 | shadow_scalp_exit_btc_5m_d3_v1 | n=81, positive point estimate, clean gate-lift vs control, OOS Mar30–Apr21 PASS (CI>0), accumulating at ~16/day | Continue; primary forward-validation sleeve. Goal: n≥200 to confirm CI>0. |
| 2 | shadow_scalp_exit_btc_15m_d3_v1 | n=44, live $/tr=+0.45 real-fee, BT consistent, maker-exit upgrade | Continue; accumulate to n≥100. |
| 3 | shadow_scalp_exit_btc_5m_d3_control_v1 | Diagnostic only; confirms +0.27 gate lift vs −0.05 control | Keep as diagnostic; no capital. |
| 4 | shadow_scalp_exit_btc_15m_d3_control_v1 | Diagnostic; confirms 15m gate lift | Keep as diagnostic; no capital. |
| 5 | shadow_scalp_exit_eth_5m_d3_control_v1 | Diagnostic | Keep as diagnostic. |
| 6 | shadow_scalp_exit_btc_5m_control_v1 | Largest n=135 control; tightest gate-lift CI | Keep as diagnostic. |

**Sniper_v5 confirmed KEEP sleeves (t>1.4, WR persistently above breakeven):**

| Priority | Sleeve | Live t-stat | Evidence | Action |
|----------|--------|-------------|----------|--------|
| 7 | poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7 | t=2.45 | WR 67.8% vs 62.8% breakeven, n=603, top-3 earner (+$238) | Continue. Best ETH sniper. |
| 8 | poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8 | t=1.97 | Validated fleet best low-variance; WR decay IS→OOS→live (82→73→67%) expected | Continue. Hurst gate is load-bearing. |
| 9 | poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7_vL | t=2.00 | A/B vs v7 parent; higher n=688 | Continue as A/B pair. |
| 10 | poly_sniper_v5_eth_5m_bb_mp_hurst_band_v6 | t=0.51 | Low t but WR 63% > 61.6% breakeven; Cluster-E leader | Keep; accumulate to n=600+. |
| 11 | poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_v6 | t=1.39 | WR 72.5% well above breakeven | Continue. |

---

### TIER 2 — WATCH (Accumulate Data; Do Not Scale Capital)

**Scalp-exit WATCH sleeves:**
- shadow_scalp_exit_btc_5m_v1 (n=23, too small)
- shadow_scalp_exit_btc_15m_v1 (n=16, too small, maker-fill slippage unquantified)
- shadow_scalp_exit_eth_5m_d3_v1 (n=22, ETH historically weaker cell)
- shadow_scalp_exit_btc_5m_d3_tod2_v1 (no BT for this specific config; real-fee negative)
- shadow_scalp_exit_eth_5m_control_v1 (−$1.14/tr more negative than typical ungated; investigate)

**sniper_v5 WATCH sleeves** (positive $/tr but underpowered or unaudited):
- poly_sniper_v5_btc_15m_ema50_ema800_off600_down (was best edge; BTC trend decaying in Jun — monitor)
- poly_sniper_v5_btc_15m_ema50_ema800_off600_down_H (HEDGE_LATE inflates apparent WR; context decaying)
- poly_sniper_v5_btc_5m_a2_hlcascade100k_v9 (t=2.05, n=126, fidelity unverified — needs audit)
- poly_sniper_v5_sol_5m_btctrend_cci_hurstrev_v7 (t=0.85, n=66 — too few)
- poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_V10 (t=1.55, n=62 — early OOS promising)
- poly_sniper_v5_eth_15m_trstack family (4 sleeves — low base-rate, n<40, accumulate)
- poly_sniper_v5_btc_15m_ts_trstack_off600_down (WR decayed, $/tr dropped from +$1.29 to +$0.33)
- poly_sniper_v5_eth_5m_v5repl_off120_v6 and tr200 twin (t=1.35, but duplicate pair — keep one only)
- poly_sniper_v5_eth_5m_v6c3_parent15mrang_v7 (t=1.28, n=151, needs fidelity audit)

**momo WATCH (corrected BT needed; live positive may be regime):**
- poly_updown_sol_15m_momo_HOLD_f7 (live +$3.63/tr, t=1.6, but corrected BT negative; production code correct)
- poly_updown_btc_15m_momo_HOLD_f7 (live +$3.31/tr, t modest; corrected BT flat/negative)

**Other WATCH:**
- kalshi_sniper_btc_15m_ema50_ema800_off600_down (WR tracks BT but live $/tr near zero; widen spread filter first)
- kalshi_sniper_all_15m_s4_prewindow (no BT; live coin-flip; accumulate n≥200)
- poly_fast_taker_lagv2_btc_15m (t=0.23, dominated by pre-bugfix always-UP fires)
- shadow_oracle_settle_btc_5m (n=19; WR matches BT; accumulate)
- poly_updown_btc_5m_v3_1 and sol v3/v3_2/v3_3 (not kill-worthy yet; t<1; monitor 30 days)
- shadow_disagr_hawkes_sol_5m_dn (WR slipping below breakeven; fire rate ~1/2 days → 1 year to graduation)
- shadow_poly_updown_ALL_5m_S3_prewindow (live flat; production code correct; watch 200 more fires)

---

### TIER 3 — KILL (Confirmed Anti-Edge or Broken BT With No Valid Evidence)

**Immediate KILL (t-stat ≤ −1.7 or confirmed in prior audit):**

| Sleeve | Reason |
|--------|--------|
| shadow_poly_updown_sol_15m_fade_momo_v2 | t=−2.16 STATISTICALLY SIGNIFICANT LOSER. −$657 total. Kill immediately. |
| poly_updown_eth_5m_momo_HOLD_f7 | Confirmed anti-edge live, worst momo cell. Kill. |
| poly_sniper_v5_eth_5m_k_hurst_ts_cci_tod_euus_v8 | t=−2.37 statistically significant loser. −$87.6 total. |
| poly_updown_eth_5m_sniper_hod | t=−2.09 significant. −$392. HOD family unvalidated. |
| poly_updown_sol_5m_v3_3, poly_updown_eth_5m_v3_2 | t=−1.89 near threshold; both ETH; −$234 each. |
| poly_sniper_v5_btc_5m_q_parent15mslope_ts_imb5_v8 | Confirmed KILL in A2; −$231 total; lookahead bug. |
| poly_sniper_v5_btc_5m_parent15m_slope_ts_mpnx_v7 | −$303 total; misleadingly positive at small n. |
| poly_updown_sol_5m_volume_INV_NIGHT | t=−2.91; worst inv_night. Already disabled. |
| shadow_poly_updown_ALL_5m_phase1_kelly | −$2,006 total; 4× tail non-recurring. |
| shadow_poly_updown_ALL_15m_S4_prewindow | Three BT methods all net-negative; lucky week artifact. |

**Strong KILL (large negative bleed, clear mechanism):**

| Sleeve | Reason |
|--------|--------|
| poly_updown_btc_5m_vwap_off240_m1v | −$486 total; 35pp WR gap vs BT; worst vwap sleeve. |
| poly_updown_btc_5m_vwap_off90_cross and off60_cross | −$281 bleed; LegacyConfig BT; no OOS. |
| poly_updown_sol_5m_vwap_off60 | −$369 total; n=64 BT too thin to trust. |
| poly_updown_eth_5m_vwap_off210_f7_m1v | 35pp WR gap; BT invalid. |
| poly_updown_btc_5m_v4 | t=−1.71; liq_quiet disabled; both live and ref negative. |
| poly_updown_eth_5m_v4 | t=−1.48; 32% WR; −$148 total. |
| poly_updown_eth_5m_v3_1 | t=−1.68; both live and reference negative. |
| poly_updown_eth_5m_v3, poly_updown_eth_5m_v3_2, poly_updown_eth_5m_v3_3 | ETH spread calibration structural failure. |
| poly_sniper_v5_btc_5m_l_1hrf_imb5_ribbon_v8 and _rf_v8 | Gate mismatch + RF UP-bias + imb5 look-ahead. |
| shadow_poly_updown_ALL_5m_phase1_kelly_fe1000_V10 | No valid BT; coin-flip WR; −$640. |
| kalshi_sniper_btc_15m_ema50_ema800_off600_down_H | HEDGE_LATE documented to hurt this strategy; near-zero $/tr. |
| poly_fast_taker_lagv2_eth_15m | t=−1.24; trending negative; kill if n=150 still negative. |
| poly_fast_taker_lagv2_eth_5m | Very high WR at deep vwap=0.64 is deep-favorite trap; −$0.38/tr. |
| All 6 fade family sleeves | Anti-edge confirmed at scale; fading +EV signals loses direction. |
| All 6 inv_night sleeves | Already disabled; IS overfit confirmed. |
| All sol/eth/btc HOD sniper/hod sleeves | HOD family unvalidated; bleeding heavily. |
| poly_sniper_v5_sol_5m_rf_tr_partial_mid and rf_tr_pp_mid | Sharpe≈0; RF UP-bias; 1185+235 fires no return. |
| poly_sniper_v5_ema50_hurst_parent15mrang_v7_vL | 1010 fires, $/tr=+$0.05; zero alpha. |
| poly_sniper_v5_btc_5m_parent15m_notrang_ts_mpskew_v7 | 441 fires, $/tr=+$0.09; bleeding −$0.30/tr last 7d. |
| All remaining SOL/BTC b1/b2/b3 flow sleeves with WR<<breakeven | Priced-in trap confirmed; bleed sustained. |
| poly_sniper_v5_eth_5m_ema200_vwap_regimerang_xa3_v7 | t=−1.66; −$159 total. |
| poly_sniper_v5_btc_5m_ts_mpskew_any_off30 | Confirmed KILL in A2 audit; −$121. |
| poly_sniper_v5_sol_5m_f7_mfi and f7_mp families | High fire count, persistent bleed. |
| poly_sniper_v5_btc_15m_ema800_ribslp_hawkes | t=−1.27; Hawkes gate unvalidated; −$106. |
| shadow_oracle_settle_sol_5m | n=58 highest-power; still net-negative; structural fee trap. |
| All momo_v2 HOD variants (sol_15m, btc_15m, sol_5m) | HOD hours refreshed from buggy-anchor data; negative live. |
| shadow_poly_updown_sol_5m_momo_v1_m5v | BT entirely from buggy anchor; −$2.90/tr live. |
| All remaining momo/momo_v2 HOLD_f7 5m sleeves | Corrected BT negative; confirmed bleeders. |

---

### TIER 4 — NEEDS A CORRECT BACKTEST BEFORE ANY CONCLUSION

These sleeves have plausible mechanisms but zero valid backtest. **Do not scale capital or draw positive conclusions until corrected BT is run.**

| Sleeve | What Is Needed |
|--------|----------------|
| poly_updown_sol_15m_momo_HOLD_f7 | Corrected BT (ws_s+120 anchor, realistic 15m vwap). Production code correct; live positive may hold if corrected BT passes CI>0. Run on canonical BBO data (Mar30–Apr21 OOS). |
| poly_updown_btc_15m_momo_HOLD_f7 | Same. Corrected BT for BTC 15m. |
| poly_updown_btc_5m_momo_v2_hod_mtf | HOD table built from buggy-anchor firing data; MTF2 gate needs BT on corrected anchor. |
| shadow_poly_updown_btc_15m_momo_v2_fairedge500_cvd30 | Overlay gate has no BT; FIX-2 applied; need clean post-fix BT. |
| poly_updown_eth_15m_momo_v2_hod | HOD hours 6-delta from spec; HOD table from buggy-anchor data; needs corrected BT. |
| poly_sniper_v5_btc_5m_a2_hlcascade100k_v9 | t=2.05 is promising but fidelity unverified; no BT in corpus. Run fidelity audit then BT. |
| poly_sniper_v5_sol_5m_btctrend_cci_hurstrev_v7 | High $/tr at n=66; needs fidelity audit + BT to assess whether cross-asset gate adds real lift. |
| poly_sniper_v5_eth_5m_v5repl_off120_v6 / tr200_mp_sms | Jaccard=1.0 duplicate pair; keep one, run BT to confirm gate stack (tr200 vs v5repl equivalence); fidelity unverified. |
| poly_fast_taker_lagv2_btc_15m / btc_5m | Need post-bugfix (post-Jun-3) sub-sample evaluation; if 200-fire post-fix window shows $/tr>0 run formal BT on corrected direction labeling. |
| shadow_oracle_settle_btc_5m | n=19 only; BT plausible but needs larger-n BT (extend to more slugs) to confirm structural break-even threshold is cleared on BTC. |

---

## Meta-Summary

**The core finding across 107 sleeves is unambiguous:** Directional prediction on Polymarket binary outcomes is efficiently priced. Every family that relied on predicting direction (momo through vwap through v3/v4 through phase1_kelly) has delivered either coin-flip WR or negative $/tr after the 0.07-curve fee. The high WR figures seen in momo live (+67–72%) and momo_v2 live are **favorite-longshot pricing artifacts**, not edge — the strategy buys high-conviction (high-vwap) tokens, which naturally resolve at high rates, but the margin above fee breakeven is zero or negative.

**The only confirmed edge is execution-side:** The scalp-exit family exploits intra-window book mispricing (lag-taker entry + +60s sell) and has survived OOS on disjoint windows. Its forward-validation (n=81 for the primary sleeve, CI grazing 0) is the single most important statistic to watch. All capital and deployment attention should be focused here until n≥200 with confirmed CI>0.

**The sniper_v5 ETH Hurst/cloud sleeves** are the second-best story: 3–4 sleeves with t≥1.4–2.5, gate-wiring verified, and WR consistently above breakeven. They do not have OOS backtests with proper disjoint windows, but their live performance over 600–700 fires is the next-best evidence available. These should continue at current (paper) stake while the scalp-exit family graduates.

**The RF UP-bias bug in BTC 5m V8 sleeves and the momo ws_s=suffix-900 anchor bug** are the two most consequential backtest invalidations found. They collectively account for approximately 20+ sleeves being deployed on invalid evidence. Both bugs have been confirmed and corrected in production code, but the backtest corpus for these families remains invalid and must not be used to justify future deployments.