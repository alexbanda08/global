# Shadow fleet bleeders — last 7 days (corrected dedup metric) — 2026-06-08

Source: vps3 `trading.events_2026_06`, last 7d, deduped one row per (sleeve_id, condition_id), `fill_method<>'synthetic'`,
`pnl_usd` = 0.07-curve. n>=15, total_pnl<0. ALL `mode=paper` (vps3 shadow; real capital runs on Ireland).
Use the dedup metric, NOT raw events.pnl_usd (`[[project_sleeve_pnl_metric]]`).

## Complete bleeder list (sorted worst → least)
| sleeve_id | n | total | $/tr | t | WR |
|---|---|---|---|---|---|
| poly_updown_sol_5m_momo_v2_HOLD_f7 | 131 | −510.1 | −3.89 | −2.47 | 0.61 |
| shadow_poly_updown_sol_5m_momo_v2_cvd_macd | 90 | −489.6 | −5.44 | −2.71 | 0.56 |
| shadow_poly_updown_btc_5m_fade_sniper | 273 | −488.2 | −1.79 | −1.24 | 0.49 |
| shadow_poly_updown_sol_5m_fade_sniper | 278 | −465.8 | −1.68 | −1.18 | 0.52 |
| poly_updown_btc_5m_vwap_off240_m1v | 128 | −396.1 | −3.09 | −1.30 | 0.52 |
| shadow_poly_updown_ALL_5m_phase1_kelly_fe1000_V10 | 876 | −370.1 | −0.42 | −0.32 | 0.51 |
| poly_fast_taker_lagv2_eth_5m | 544 | −323.8 | −0.60 | −1.08 | 0.95 |
| poly_updown_eth_5m_momo_v2_HOLD_f7 | 153 | −289.9 | −1.90 | −1.17 | 0.61 |
| shadow_poly_updown_btc_5m_momo_v2_fairedge500 | 151 | −289.4 | −1.92 | −1.11 | 0.57 |
| shadow_poly_updown_sol_5m_momo_v1_m5v | 108 | −285.1 | −2.64 | −1.51 | 0.66 |
| poly_updown_btc_5m_vwap_off90_cross | 143 | −281.2 | −1.97 | −1.13 | 0.61 |
| shadow_poly_updown_sol_15m_fade_momo_v2 | 74 | −270.8 | −3.66 | −1.01 | 0.38 |
| poly_fast_taker_lagv2_btc_5m | 873 | −267.1 | −0.31 | −0.61 | 0.89 |
| poly_updown_btc_15m_momo_v2_HOLD_f7 | 49 | −266.2 | −5.43 | −1.76 | 0.47 |
| poly_sniper_v5_btc_5m_parent15m_slope_ts_mpnx_v7 | 925 | −221.3 | −0.24 | −1.22 | 0.49 |
| poly_updown_sol_5m_vwap_off60 | 109 | −212.5 | −1.95 | −0.80 | 0.56 |
| poly_updown_sol_5m_momo_v2_hod | 41 | −209.2 | −5.10 | −1.69 | 0.56 |
| poly_updown_sol_5m_momo_HOLD_f7 | 104 | −202.5 | −1.95 | −1.14 | 0.69 |
| poly_updown_sol_5m_v3_2 | 68 | −185.7 | −2.73 | −1.08 | 0.49 |
| poly_updown_btc_5m_vwap_off60_f7_cross | 100 | −168.9 | −1.69 | −0.76 | 0.55 |
| shadow_poly_updown_eth_15m_fade_sniper | 151 | −147.5 | −0.98 | −0.50 | 0.52 |
| poly_fast_taker_lagv2_eth_15m | 76 | −129.6 | −1.71 | −1.49 | 0.93 |
| poly_sniper_v5_btc_5m_parent15m_notrang_ts_mpskew_v7 | 429 | −129.3 | −0.30 | −0.92 | 0.48 |
| poly_sniper_v5_btc_5m_q_parent15mslope_ts_imb5_v8 | 1070 | −104.7 | −0.10 | −0.42 | 0.47 |
| poly_updown_eth_15m_momo_v2_HOLD_f7 | 48 | −103.7 | −2.16 | −0.74 | 0.58 |
| poly_fast_taker_b2_nomerge_eth_5m | 561 | −91.3 | −0.16 | −2.35 | 0.56 |
| poly_sniper_v5_btc_5m_ts_mpskew_any_off30 | 466 | −88.8 | −0.19 | −0.78 | 0.50 |
| poly_sniper_v5_eth_5m_a2_hlcascade50k_v9 | 120 | −86.6 | −0.72 | −1.35 | 0.42 |
| shadow_poly_updown_sol_5m_fade_momo_v2 | 77 | −86.3 | −1.12 | −0.40 | 0.51 |
| poly_updown_sol_5m_v3_3 | 42 | −86.2 | −2.05 | −0.62 | 0.50 |
| poly_updown_btc_5m_v4 | 27 | −78.8 | −2.92 | −0.86 | 0.44 |
| poly_sniper_v5_sol_5m_f7_mp_ema200_vwap_v6 | 396 | −76.1 | −0.19 | −1.08 | 0.66 |
| poly_updown_sol_5m_v3 | 51 | −75.7 | −1.49 | −0.49 | 0.51 |
| poly_sniper_v5_sol_5m_f7_mfi_ema200_vwap_v6 | 619 | −74.9 | −0.12 | −0.87 | 0.67 |
| poly_sniper_v5_eth_5m_ema200_vwap_regimerang_xa3_v7 | 331 | −61.0 | −0.18 | −0.83 | 0.63 |
| shadow_scalp_exit_eth_5m_control_v1 | 52 | −59.1 | −1.14 | −1.73 | — |
| poly_updown_btc_5m_sniper_hod | 33 | −50.0 | −1.52 | −0.51 | 0.39 |
| poly_sniper_v5_eth_5m_up_a2_hlcascade25k_v9 | 157 | −49.2 | −0.31 | −0.67 | 0.45 |
| poly_updown_btc_15m_momo_v2_hod | 17 | −48.9 | −2.88 | −0.54 | 0.53 |
| poly_sniper_v5_sol_5m_rf_tr_partial_mid | 739 | −43.8 | −0.06 | −0.32 | 0.68 |
| shadow_scalp_exit_btc_5m_control_v1 | 136 | −41.9 | −0.31 | −0.69 | 1.00 |
| poly_updown_eth_15m_momo_v2_hod | 20 | −32.6 | −1.63 | −0.36 | 0.60 |
| poly_fast_taker_lagv2_btc_15m | 267 | −30.0 | −0.11 | −0.15 | 0.98 |
| poly_sniper_v5_eth_5m_k_hurst_ts_cci_tod_euus_v8 | 37 | −29.6 | −0.80 | −1.04 | 0.51 |
| shadow_disagr_hawkes_sol_5m_dn | 20 | −27.7 | −1.38 | −0.53 | 0.85 |
| poly_sniper_v5_sol_5m_btcf7_f7overb_ema800_vwap_v7 | 268 | −26.8 | −0.10 | −0.42 | 0.63 |
| poly_sniper_v5_btc_5m_up_a2_hlcascade50k_v9 | 136 | −25.9 | −0.19 | −0.38 | 0.46 |
| poly_sniper_v5_btc_15m_ema200_mpskew_rf_off600_down_v6 | 60 | −24.0 | −0.40 | −0.65 | 0.67 |
| poly_sniper_v5_sol_5m_b1_120s_250_v9 | 89 | −23.7 | −0.27 | −0.88 | 0.79 |
| poly_sniper_v5_btc_5m_down_b2_contrarian2k_v9 | 23 | −23.6 | −1.03 | −0.61 | 0.26 |
| poly_updown_sol_5m_v3_1 | 43 | −23.6 | −0.55 | −0.17 | 0.53 |
| poly_sniper_v5_btc_15m_ts_trstack_off600_down | 66 | −22.7 | −0.34 | −1.08 | 0.80 |
| poly_sniper_v5_btc_5m_up_b2_contrarian2k_v9 | 22 | −21.8 | −0.99 | −0.73 | 0.32 |
| poly_sniper_v5_sol_5m_down_b1_flow250_v9 | 37 | −21.2 | −0.57 | −1.32 | 0.76 |
| shadow_poly_updown_ALL_5m_S3_prewindow | 114 | −20.9 | −0.18 | −0.08 | 0.52 |
| kalshi_sniper_btc_15m_ema50_ema800_off600_down | 227 | −19.1 | −0.08 | −0.37 | 0.80 |
| poly_sniper_v5_btc_15m_regime_trstack_off480_up | 16 | −18.8 | −1.18 | −1.22 | 0.56 |
| poly_fast_taker_b2_nomerge_btc_5m | 855 | −16.3 | −0.02 | −0.33 | 0.59 |
| poly_sniper_v5_sol_5m_cci_f7_mfi_partial_vwap_v6 | 140 | −15.9 | −0.11 | −0.43 | 0.72 |
| poly_updown_eth_5m_v3_3 | 16 | −14.4 | −0.90 | −0.18 | 0.44 |
| poly_updown_eth_5m_v3_2 | 16 | −14.4 | −0.90 | −0.18 | 0.44 |
| poly_updown_eth_5m_vwap_off210_f7_m1v | 66 | −14.1 | −0.21 | −0.07 | 0.58 |
| kalshi_sniper_btc_15m_ema50_ema800_off600_down_H | 209 | −13.6 | −0.07 | −0.28 | 0.78 |
| shadow_scalp_exit_btc_15m_control_v1 | 39 | −13.2 | −0.34 | −0.42 | — |
| poly_sniper_v5_btc_5m_ts_mpskew_s6_0_60 | 15 | −13.0 | −0.87 | −0.58 | 0.40 |
| poly_sniper_v5_sol_5m_btcf7against_cci_hurstrev_mfi_v8 | 15 | −9.4 | −0.63 | −0.37 | 0.40 |
| shadow_oracle_settle_eth_5m | 37 | −9.4 | −0.26 | −0.81 | 0.86 |
| poly_sniper_v5_sol_15m_trstack_vol_ribbon_ema_mid | 25 | −9.4 | −0.38 | −0.53 | 0.68 |
| poly_sniper_v5_sol_15m_trstack_vol_ribbon_ema_mid_vL | 25 | −9.1 | −0.37 | −0.51 | 0.68 |
| poly_updown_eth_5m_v3 | 24 | −8.8 | −0.37 | −0.09 | 0.54 |
| poly_sniper_v5_eth_5m_lq_ema50_hurst_grandparent_prev15m_v8_vL | 124 | −8.6 | −0.07 | −0.20 | 0.65 |
| poly_sniper_v5_eth_5m_k_hurst_ts_cci_tod_euus_v8_vL | 44 | −7.1 | −0.16 | −0.16 | 0.52 |
| poly_sniper_v5_btc_15m_ema50_ema800_off600_down_H | 189 | −6.9 | −0.04 | −0.15 | 0.91 |
| poly_updown_sol_15m_momo_v2_HOLD_f7 | 49 | −6.3 | −0.13 | −0.05 | 0.65 |
| shadow_oracle_settle_sol_5m | 56 | −5.5 | −0.10 | −0.43 | 0.89 |
| poly_sniper_v5_btc_15m_vwapprem_ema50_mpskew_off600_v6 | 102 | −4.0 | −0.04 | −0.19 | 0.86 |
| poly_sniper_v5_btc_15m_mpskew_trstack_off600_down | 25 | −4.0 | −0.16 | −0.42 | 0.88 |
| poly_sniper_v5_sol_5m_depth_up_hod_session | 24 | −1.3 | −0.05 | −0.07 | 0.63 |

## Family rollup (≈ 7d bleed)
momo/momo_v2 ≈ −$2,600 (dominant) · fade ≈ −$1,400 · vwap_off ≈ −$1,070 · lagv2 ≈ −$750 (UP-bias bug, 89–98% WR) ·
phase1_kelly −$370 · v3/v4 ≈ −$450 · sniper_v5 no-RF controls ≈ −$455.

## Kill priority
1. **lagv2 ×4** — the RF UP-bias bug (`RF_GATE_UP_BIAS_AUDIT_2026_06_08`), high-WR-low-edge. + `btc_5m_l_1hrf_imb5_rf_v8` (positive this week by luck, same bomb).
2. **momo_v2 HOLD/cvd/hod/fairedge** — dominant bleed, persistent.
3. **fade ×N** — confirmed anti-edge (already on kill list).
4. **vwap_off, phase1_kelly, v3/v4** — legacy/dead.
Note: the scalp `_control_v1` sleeves bleeding is BY DESIGN (controls = no entry_band, baseline to beat).
All paper — killing costs nothing live; it cleans the fleet + stops misleading paper PnL.
