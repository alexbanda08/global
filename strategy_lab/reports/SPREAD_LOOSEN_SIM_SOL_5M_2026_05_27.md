# SPREAD-LOOSEN SIMULATION — SOL 5m Sleeves

**Date:** 2026-05-27  **Spread: 0.025 → 0.03**  **Notional:** $5  **Fee model:** LegacyConfig (2%-on-profit)

## Methodology

- **Fire universe:** combined REF (s6_joined_all, May 1–21) + prefix_fires (Apr 24–30) + oos_fires_SOL_5m (May 21–25)
- **Books:** `load_orderbook_l25_streaming('sol', subsample_1hz=False)` — native 10Hz per CLAUDE.md
- **Spread metric:** same-token bid-ask `ask0 - bid0` on the BUY-side token (per `engine_v2.fill_at_book`)
- **Gate approximations:** production gates mapped to closest backtest-panel equivalents (see table Notes column)
  - `g_rf_strict_align` → `g_rf_with`
  - `g_tr_partial_stack_with` → `g_tr_stack_with`
  - `g_depth_250_strict` → not available (treated as pass-all)
  - `g_hod_us_afternoon` → `g_tr_in_active_session` (proxy)
  - F7/BTC-trend/Hurst gates → not available (treated as pass-all)
- **Note:** gate approximations make absolute metrics unreliable vs live; **delta metrics (PROPOSED vs CURRENT) remain valid** since same fires are tested at both thresholds

## Summary

- Sleeves tested: 10 / 10
- Sleeves that IMPROVE (new fires with positive delta metrics): 0
- Sleeves NEUTRAL (no new fires or marginal): 10
- Sleeves that DEGRADE (new fires hurt metrics): 0

**Top 3 PnL gainers from loosening:**
  - `poly_sniper_v5_sol_5m_f7_mp_ema200_vwap_v6`: Δn=+163, ΔWR=+0.0%, Δ$/tr=-0.001, ΔPnL=-1.40 → LOOSEN_WITH_CAVEAT
  - `poly_sniper_v5_sol_5m_btctrend_cci_hurstrev_v7`: Δn=+166, ΔWR=+0.0%, Δ$/tr=-0.002, ΔPnL=-4.09 → LOOSEN_WITH_CAVEAT
  - `poly_sniper_v5_sol_5m_rf_tr_pp_mid`: Δn=+54, ΔWR=-0.0%, Δ$/tr=-0.001, ΔPnL=-4.40 → LOOSEN_WITH_CAVEAT

**Top 3 PnL losers from loosening:**
  - `poly_sniper_v5_sol_5m_j_2asset_trending_cci_rf_ema200_v8`: Δn=+250, ΔWR=+0.1%, Δ$/tr=-0.002, ΔPnL=-12.52 → LOOSEN_WITH_CAVEAT
  - `poly_sniper_v5_sol_5m_rf_tr_partial_mid`: Δn=+106, ΔWR=-0.0%, Δ$/tr=-0.004, ΔPnL=-21.67 → LOOSEN_WITH_CAVEAT
  - `poly_sniper_v5_sol_5m_depth_up_hod_session`: Δn=+123, ΔWR=+0.0%, Δ$/tr=-0.004, ΔPnL=-77.30 → LOOSEN_WITH_CAVEAT

## Per-Sleeve Comparison Table

| Sleeve | n_old | WR_old | $/tr_old | PnL_old | DD_old | n_new | WR_new | $/tr_new | PnL_new | DD_new | Δn | ΔWR | Δ$/tr | ΔPnL | ΔDD | REC |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `depth_up_hod_session` | 16034 | 51.1% | -0.125 | -2008.08 | 3393.43 | 16157 | 51.2% | -0.129 | -2085.39 | 3447.14 | +123 | +0.0% | -0.004 | -77.30 | +53.71 | **LOOSEN_WITH_CAVEAT** |
| `rf_tr_pp_mid` | 3629 | 76.8% | -0.024 | -85.43 | 573.95 | 3683 | 76.8% | -0.024 | -89.82 | 582.88 | +54 | -0.0% | -0.001 | -4.40 | +8.93 | **LOOSEN_WITH_CAVEAT** |
| `rf_tr_partial_mid` | 7142 | 77.1% | +0.100 | +715.91 | 388.74 | 7248 | 77.0% | +0.096 | +694.24 | 403.79 | +106 | -0.0% | -0.004 | -21.67 | +15.05 | **LOOSEN_WITH_CAVEAT** |
| `cci_f7_mfi_partial_vwap_v6` | 8282 | 75.4% | +0.130 | +1077.44 | 301.46 | 8419 | 75.4% | +0.127 | +1072.22 | 316.61 | +137 | +0.0% | -0.003 | -5.22 | +15.15 | **LOOSEN_WITH_CAVEAT** |
| `f7_mp_ema200_vwap_v6` | 10891 | 73.7% | +0.080 | +866.30 | 498.55 | 11054 | 73.8% | +0.078 | +864.90 | 510.85 | +163 | +0.0% | -0.001 | -1.40 | +12.30 | **LOOSEN_WITH_CAVEAT** |
| `f7_mfi_ema200_vwap_v6` | 8383 | 75.4% | +0.116 | +971.56 | 326.35 | 8518 | 75.4% | +0.113 | +962.86 | 341.50 | +135 | +0.0% | -0.003 | -8.70 | +15.15 | **LOOSEN_WITH_CAVEAT** |
| `btctrend_cci_hurstrev_v7` | 10717 | 73.6% | +0.092 | +985.27 | 483.26 | 10883 | 73.7% | +0.090 | +981.18 | 493.25 | +166 | +0.0% | -0.002 | -4.09 | +9.99 | **LOOSEN_WITH_CAVEAT** |
| `btcf7_f7overb_ema800_vwap_v7` | 10777 | 73.7% | +0.078 | +840.01 | 509.57 | 10938 | 73.7% | +0.076 | +832.91 | 523.48 | +161 | +0.0% | -0.002 | -7.09 | +13.91 | **LOOSEN_WITH_CAVEAT** |
| `btcf7against_cci_hurstrev_mfi_v8` | 8282 | 75.4% | +0.130 | +1077.44 | 301.46 | 8419 | 75.4% | +0.127 | +1072.22 | 316.61 | +137 | +0.0% | -0.003 | -5.22 | +15.15 | **LOOSEN_WITH_CAVEAT** |
| `j_2asset_trending_cci_rf_ema200_v8` | 18968 | 69.2% | +0.091 | +1721.51 | 407.12 | 19218 | 69.3% | +0.089 | +1708.99 | 434.59 | +250 | +0.1% | -0.002 | -12.52 | +27.48 | **LOOSEN_WITH_CAVEAT** |

## Gate Approximation Notes

| Sleeve | Approx Gates Used | Production Gates (not in panel) |
|---|---|---|
| `depth_up_hod_session` | g_tr_in_active_session | depth+hod+session → g_tr_in_active_session proxy; g_depth_250_strict absent |
| `rf_tr_pp_mid` | g_rf_with, g_tr_above_ema200, g_tr_above_pp, g_tr_stack_with | g_rf_strict_align→g_rf_with, g_tr_partial_stack_with→g_tr_stack_with |
| `rf_tr_partial_mid` | g_rf_with, g_tr_stack_with | g_rf_strict_align→g_rf_with, g_tr_partial_stack_with→g_tr_stack_with |
| `cci_f7_mfi_partial_vwap_v6` | g_cci_with, g_mfi_with, g_tr_stack_with | F7 RSI gate not in panel; vwap_lt_mid not in panel; g_tr_partial→g_tr_stack |
| `f7_mp_ema200_vwap_v6` | g_tr_above_ema200, g_tr_stack_with | F7 gate+mp not in panel; vwap_lt_mid not in panel |
| `f7_mfi_ema200_vwap_v6` | g_mfi_with, g_tr_above_ema200, g_tr_stack_with | F7 gate not in panel; vwap_lt_mid not in panel |
| `btctrend_cci_hurstrev_v7` | g_cci_with, g_tr_stack_with | BTC trend gate not in panel; Hurst rev not in panel |
| `btcf7_f7overb_ema800_vwap_v7` | g_tr_above_ema800, g_tr_stack_with | BTC F7 + F7 overbought not in panel; vwap not in panel |
| `btcf7against_cci_hurstrev_mfi_v8` | g_cci_with, g_mfi_with, g_tr_stack_with | BTC F7 against + Hurst not in panel |
| `j_2asset_trending_cci_rf_ema200_v8` | g_cci_with, g_rf_with, g_tr_above_ema200 | 2-asset trending (BTC+SOL) not in panel |

**Important:** Absolute WR/$/tr numbers are NOT directly comparable to production live PnL because:
1. Gate approximations let through more fires than production (especially v6/v7/v8 which have F7/BTC-trend/Hurst gates)
2. The delta metrics (Δn, ΔWR, Δ$/tr, ΔPnL) between 0.025 and 0.030 are valid — same fires tested both ways
3. A positive ΔPnL means the marginal fires (spread in 0.025–0.030] add value

## Recommendation Summary

| Sleeve | Recommendation | Rationale |
|---|---|---|
| `depth_up_hod_session` | **LOOSEN_WITH_CAVEAT** | Δn=+123 fires, mixed signal ΔWR=+0.0%, Δ$/tr=-0.004 |
| `rf_tr_pp_mid` | **LOOSEN_WITH_CAVEAT** | Δn=+54 fires, mixed signal ΔWR=-0.0%, Δ$/tr=-0.001 |
| `rf_tr_partial_mid` | **LOOSEN_WITH_CAVEAT** | Δn=+106 fires, mixed signal ΔWR=-0.0%, Δ$/tr=-0.004 |
| `cci_f7_mfi_partial_vwap_v6` | **LOOSEN_WITH_CAVEAT** | Δn=+137 fires, mixed signal ΔWR=+0.0%, Δ$/tr=-0.003 |
| `f7_mp_ema200_vwap_v6` | **LOOSEN_WITH_CAVEAT** | Δn=+163 fires, mixed signal ΔWR=+0.0%, Δ$/tr=-0.001 |
| `f7_mfi_ema200_vwap_v6` | **LOOSEN_WITH_CAVEAT** | Δn=+135 fires, mixed signal ΔWR=+0.0%, Δ$/tr=-0.003 |
| `btctrend_cci_hurstrev_v7` | **LOOSEN_WITH_CAVEAT** | Δn=+166 fires, mixed signal ΔWR=+0.0%, Δ$/tr=-0.002 |
| `btcf7_f7overb_ema800_vwap_v7` | **LOOSEN_WITH_CAVEAT** | Δn=+161 fires, mixed signal ΔWR=+0.0%, Δ$/tr=-0.002 |
| `btcf7against_cci_hurstrev_mfi_v8` | **LOOSEN_WITH_CAVEAT** | Δn=+137 fires, mixed signal ΔWR=+0.0%, Δ$/tr=-0.003 |
| `j_2asset_trending_cci_rf_ema200_v8` | **LOOSEN_WITH_CAVEAT** | Δn=+250 fires, mixed signal ΔWR=+0.1%, Δ$/tr=-0.002 |

---
*Generated 2026-05-27 by spread_loosen_sol_5m_2026_05_27.py*