# SPREAD-LOOSEN SIM: ETH 5m + 15m Sleeves

**Generated:** 2026-05-27  |  **Stake:** $5  |  **Fees:** LegacyConfig (2% on profit)  |  **L25:** native 10Hz
**Current filter:** same-token bid-ask ≤ 0.020  |  **Proposed:** ≤ 0.025

Book miss / spread NaN fires are excluded from both scenarios.

---

## ETH 5m Sleeves

| Sleeve | curr_n | curr_WR | curr_$/tr | curr_PnL | curr_DD | curr_t | prop_n | prop_WR | prop_$/tr | prop_PnL | prop_DD | prop_t | Δn | ΔPNL | Verdict |
|--------|--------|--------|--------|--------|--------|--------|--------|--------|--------|--------|--------|--------|--------|--------|
| tr200_mp_sms_active_off120 | 113 | 88.5% | +0.808 | +91.33 | -11.06 | +3.16 | 117 | 88.0% | +0.775 | +90.72 | -11.06 | +3.07 | +4 | -0.61 | **KEEP** |
| tr200_mp_mpnx_sms_off120 | 15 | 73.3% | +0.610 | +9.15 | -9.39 | +0.62 | 15 | 73.3% | +0.610 | +9.15 | -9.39 | +0.62 | +0 | +0.00 | **NO_CHANGE** |
| cloud_mp_sms_active_off120 | 117 | 86.3% | +0.843 | +98.65 | -18.73 | +2.63 | 121 | 86.0% | +0.810 | +98.04 | -18.73 | +2.58 | +4 | -0.61 | **KEEP** |
| cloud_ribbon_mp_hurst_v6 | 442 | 81.7% | +0.926 | +409.36 | -44.65 | +5.90 | 460 | 81.7% | +0.927 | +426.38 | -41.80 | +6.05 | +18 | +17.02 | **LOOSEN** |
| v5repl_off120_v6 | 113 | 88.5% | +0.808 | +91.33 | -11.06 | +3.16 | 117 | 88.0% | +0.775 | +90.72 | -11.06 | +3.07 | +4 | -0.61 | **KEEP** |
| bb_mp_hurst_band_v6 | 143 | 74.8% | +2.148 | +307.17 | -27.12 | +5.67 | 150 | 74.7% | +2.114 | +317.16 | -27.12 | +5.74 | +7 | +9.99 | **LOOSEN** |
| cloud_vwap_hurstmp_v7 | 144 | 72.9% | +1.966 | +283.13 | -37.12 | +5.11 | 151 | 72.8% | +1.941 | +293.12 | -42.02 | +5.19 | +7 | +9.99 | **LOOSEN** |
| ema50_hurst_parent15mrang_v7 | 685 | 79.7% | +0.816 | +558.99 | -32.32 | +6.30 | 710 | 79.6% | +0.805 | +571.26 | -30.42 | +6.33 | +25 | +12.28 | **LOOSEN** |
| v6c3_parent15mrang_v7 | 401 | 81.8% | +0.975 | +391.01 | -54.35 | +5.85 | 417 | 81.8% | +0.972 | +405.50 | -52.72 | +5.97 | +16 | +14.49 | **LOOSEN** |
| ema200_vwap_regimerang_xa3_v7 | 90 | 73.3% | +1.988 | +178.94 | -15.69 | +4.05 | 96 | 71.9% | +1.855 | +178.11 | -15.69 | +3.87 | +6 | -0.83 | **KEEP** |
| k_hurst_ts_cci_tod_euus_v8 | 3681 | 81.3% | +0.274 | +1008.83 | -161.43 | +3.84 | 3782 | 81.3% | +0.295 | +1116.55 | -163.40 | +4.19 | +101 | +107.72 | **LOOSEN** |
| l_ema50_hurst_grandparent_v8 | 21882 | 61.8% | -0.067 | -1473.60 | -3108.93 | -1.50 | 22476 | 61.7% | -0.075 | -1696.51 | -3333.02 | -1.72 | +594 | -222.91 | **KEEP** |
| lq_ema50_hurst_grandparent_prev15m_v8 | 2680 | 81.9% | +0.369 | +987.62 | -120.81 | +4.38 | 2749 | 81.9% | +0.376 | +1034.43 | -107.55 | +4.54 | +69 | +46.81 | **LOOSEN** |

## ETH 15m Sleeves

| Sleeve | curr_n | curr_WR | curr_$/tr | curr_PnL | curr_DD | curr_t | prop_n | prop_WR | prop_$/tr | prop_PnL | prop_DD | prop_t | Δn | ΔPNL | Verdict |
|--------|--------|--------|--------|--------|--------|--------|--------|--------|--------|--------|--------|--------|--------|--------|
| trstack_vwap_vol_offearly | 104 | 77.9% | +1.461 | +151.93 | -20.00 | +4.01 | 105 | 78.1% | +1.477 | +155.06 | -20.00 | +4.09 | +1 | +3.13 | **LOOSEN** |
| trstack_vwap_offearly | 449 | 67.9% | +0.649 | +291.46 | -45.09 | +3.41 | 453 | 67.8% | +0.635 | +287.73 | -45.09 | +3.34 | +4 | -3.73 | **KEEP** |
| trstack_vwap_vol_offearly_band_v6 | 88 | 73.9% | +1.505 | +132.46 | -20.00 | +3.50 | 89 | 74.2% | +1.524 | +135.59 | -20.00 | +3.58 | +1 | +3.13 | **LOOSEN** |
| pw_trendslope_trstack_offearly_v6 | 61 | 80.3% | +1.739 | +106.05 | -12.12 | +3.74 | 61 | 80.3% | +1.739 | +106.05 | -12.12 | +3.74 | +0 | +0.00 | **NO_CHANGE** |
| pi_btc15m_trend_v7 | 62 | 82.3% | +1.926 | +119.39 | -15.00 | +4.34 | 62 | 82.3% | +1.926 | +119.39 | -15.00 | +4.34 | +0 | +0.00 | **NO_CHANGE** |
| baseline_v7_top_replicate_v8 | 62 | 82.3% | +1.926 | +119.39 | -15.00 | +4.34 | 62 | 82.3% | +1.926 | +119.39 | -15.00 | +4.34 | +0 | +0.00 | **NO_CHANGE** |
| pj_btc_and_sol_trend_sep_v8 | 49 | 79.6% | +1.730 | +84.78 | -12.12 | +3.28 | 49 | 79.6% | +1.730 | +84.78 | -12.12 | +3.28 | +0 | +0.00 | **NO_CHANGE** |

---

## Summary

- **ETH 5m LOOSEN:** 7/13 sleeves
- **ETH 15m LOOSEN:** 2/7 sleeves

**LOOSEN candidates (5m):**
- cloud_ribbon_mp_hurst_v6: +18 fires, ΔPNL=+17.02, WR 81.7%→81.7%
- bb_mp_hurst_band_v6: +7 fires, ΔPNL=+9.99, WR 74.8%→74.7%
- cloud_vwap_hurstmp_v7: +7 fires, ΔPNL=+9.99, WR 72.9%→72.8%
- ema50_hurst_parent15mrang_v7: +25 fires, ΔPNL=+12.28, WR 79.7%→79.6%
- v6c3_parent15mrang_v7: +16 fires, ΔPNL=+14.49, WR 81.8%→81.8%
- k_hurst_ts_cci_tod_euus_v8: +101 fires, ΔPNL=+107.72, WR 81.3%→81.3%
- lq_ema50_hurst_grandparent_prev15m_v8: +69 fires, ΔPNL=+46.81, WR 81.9%→81.9%

**LOOSEN candidates (15m):**
- trstack_vwap_vol_offearly: +1 fires, ΔPNL=+3.13, WR 77.9%→78.1%
- trstack_vwap_vol_offearly_band_v6: +1 fires, ΔPNL=+3.13, WR 73.9%→74.2%

_Simulation completed in 78s_