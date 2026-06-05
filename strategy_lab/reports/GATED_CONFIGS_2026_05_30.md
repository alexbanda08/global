# Gated Sleeve Configs — 2026-05-30

Gates chosen only from single-gate walkforward generalization pass (h1_d AND h2_d both improved).
Stack constraints: retained n ≥ 40 (or 50% of fires), test-half gated mean > test-half base mean, ≤3 gates.
All metrics on full resolved set with stack applied. Bootstrap CI = 2.5th pct, 2000 resamples.

## Ranked Table (by gated total pnl_usd, descending)

| Rank | Sleeve | Base Total | Stack | Gated n / Base n | Gated WR% | Gated Mean | Gated Total | CI-lo | Test-half Base Mean | Test-half Gated Mean | Verdict |
|------|--------|-----------|-------|------------------|-----------|------------|-------------|-------|---------------------|----------------------|---------|
| 1 | ALL_5m_phase1_kelly | +$249 | `keep_EU` | 256 / 858 | 57.4% | +$8.87 | **+$2272** | −$0.37 | −$1.81 | +$15.75 | GATE |
| 2 | sol_5m_rf_tr_partial_mid | +$93 | `drop_US` | 224 / 371 | 74.1% | +$0.74 | **+$166** | +$0.16 | +$0.50 | +$1.00 | GATE |
| 3 | sol_5m_f7_mfi_ema200_vwap_v6 | +$0 | `evcap_0.75\|dir_UP` | 152 / 418 | 73.7% | +$0.58 | **+$88** | +$0.03 | −$0.04 | +$0.94 | GATE |
| 4 | eth_5m_l_ema50_hurst_grandparent_v8 | +$72 | `evcap_0.70` | 57 / 78 | 71.9% | +$1.35 | **+$77** | +$0.25 | +$0.65 | +$1.34 | GATE |
| 5 | eth_5m_bb_mp_hurst_band_v6_vL | +$46 | `depth_1000` | 113 / 122 | 74.3% | +$0.56 | **+$64** | −$0.03 | +$0.29 | +$0.48 | GATE |
| 6 | eth_5m_bb_mp_hurst_band_v6 | +$50 | `evcap_0.70\|depth_1000` | 70 / 107 | 74.3% | +$0.85 | **+$59** | +$0.03 | +$0.47 | +$0.67 | GATE |
| 7 | btc_5m_parent15m_notrang_ts_mpskew_v7 | +$5 | `evcap_0.80\|vsum_1.30` | 80 / 176 | 76.3% | +$0.76 | **+$61** | −$0.00 | +$0.17 | +$0.62 | GATE |
| 8 | sol_5m_cci_f7_mfi_partial_vwap_v6 | +$33 | `evcap_0.80\|drop_US` | 40 / 60 | 85.0% | +$1.26 | **+$51** | +$0.33 | +$0.19 | +$1.08 | GATE |
| 9 | sol_5m_btcf7_f7overb_ema800_vwap_v7 | +$12 | `evcap_0.70` | 139 / 222 | 61.9% | +$0.32 | **+$45** | −$0.39 | −$0.17 | −$0.07 | GATE* |
| 10 | eth_5m_cloud_vwap_hurstmp_v7 | +$32 | `evcap_0.70\|depth_1000` | 60 / 93 | 71.7% | +$0.68 | **+$41** | −$0.26 | +$0.39 | +$0.65 | GATE |
| 11 | eth_5m_cloud_ribbon_mp_hurst_v6 | +$14 | `evcap_0.70` | 44 / 84 | 75.0% | +$0.83 | **+$37** | −$0.21 | +$0.22 | +$0.87 | GATE |
| 12 | ALL_5m_S3_prewindow | +$323 | `drop_US` | 178 / 300 | 57.3% | +$2.55 | **+$455** | −$1.03 | +$0.27 | +$3.19 | GATE |
| 13 | btc_5m_l_1hrf_imb5_ribbon_v8 | −$139 | `xspread_0.22` | 136 / 506 | 96.3% | +$0.18 | **+$24** | −$0.03 | −$0.56 | +$0.09 | GATE (salvaged) |
| 14 | btc_15m_ema50_ema800_off600_down | +$53 | UNGATED | 61 / 61 | 80.3% | +$0.86 | **+$53** | −$0.29 | — | — | KEEP |
| 15 | btc_15m_vwapprem_ema50_mpskew_off600_v6 | +$3 | `vsum_1.25` | 36 / 46 | 97.2% | +$0.33 | **+$12** | −$0.06 | +$0.02 | +$0.51 | GATE |
| 16 | eth_5m_tr200_mp_sms_active_off120 | +$10 | UNGATED | 17 / 17 | 88.2% | +$0.61 | **+$10** | −$0.47 | — | — | KEEP |
| 17 | eth_5m_v5repl_off120_v6 | +$10 | UNGATED | 17 / 17 | 88.2% | +$0.61 | **+$10** | −$0.47 | — | — | KEEP |
| 18 | btc_5m_up_a2_hlcascade50k_v9 | +$13 | UNGATED | 8 / 8 | 50.0% | +$1.63 | **+$13** | −$3.71 | — | — | KEEP (low n) |
| 19 | sol_5m_j_2asset_trending_cci_rf_ema200_v8 | +$13 | UNGATED | 233 / 233 | 73.8% | +$0.06 | **+$13** | −$0.39 | — | — | KEEP (no gen. gate) |
| 20 | btc_5m_q_parent15mslope_ts_imb5_v8 | −$930 | (best: `vsum_1.30\|depth_1000\|dir_DOWN`) | 367 / 1232 | 80.1% | −$0.05 | −$18 | −$0.32 | −$0.93 | −$0.46 | **KILL** |
| 21 | btc_5m_ts_mpskew_any_off30 | −$93 | (no valid stack) | 120 / 120 | 54.2% | −$0.77 | −$93 | −$1.48 | — | — | **KILL** |

*GATE* = holdout test passes (gated test mean > base test mean), even if CI-lo negative.
`sol_5m_btcf7_f7overb_ema800_vwap_v7` marked GATE* — both halves improve (−0.17→−0.07) but both still negative in test half; CI-lo negative. Monitor with caution.

---

## Special Case Deep Dives

### btc_5m_l_1hrf_imb5_ribbon_v8 (baseline −$139, 74.5% WR)

| Stack | n | WR% | Mean PnL | Total PnL | CI-lo | H1 Mean | H2 Mean | Both Halves Positive | Net Positive |
|-------|---|-----|----------|-----------|-------|---------|---------|----------------------|-------------|
| `vsum_1.30` | 391 | 79.3% | −$0.040 | −$15.7 | −$0.33 | +$0.143 | −$0.236 | NO | NO |
| `vsum_1.30 \| depth_1000` | 390 | 79.5% | −$0.027 | −$10.7 | −$0.28 | +$0.143 | −$0.211 | NO | NO |
| `xspread_0.25` | 196 | 85.7% | −$0.181 | −$35.5 | −$0.49 | +$0.130 | −$0.533 | NO | NO |
| `vsum_1.25` | 196 | 85.7% | −$0.181 | −$35.5 | −$0.49 | +$0.130 | −$0.533 | NO | NO |
| **`xspread_0.22`** | **136** | **96.3%** | **+$0.176** | **+$24.0** | **−$0.030** | **+$0.252** | **+$0.086** | **YES** | **YES** |

**Verdict:** SALVAGED via `cross_spread ≤ 0.22`. Only this tighter threshold flips both halves positive. n=136 (27% of fires retained). CI-lo barely negative (−$0.030) — needs live confirmation.

### btc_5m_q_parent15mslope_ts_imb5_v8 (baseline −$930, n=1232)

Best achievable ≤2-gate stack: `dir_DOWN | vsum_1.30` → n=371, mean=−$0.090, total=−$33.
Best ≤3-gate (all validated): `vsum_1.30 | depth_1000 | dir_DOWN` → n=367, mean=−$0.050, total=−$18.5.
No stack achieves mean_pnl ≥ 0. **VERDICT: KILL.**

### btc_5m_ts_mpskew_any_off30 (baseline −$93, n=120)

Zero gates generalized in walkforward. No stack passes both halves positive. Best achievable: `dir_DOWN | vsum_1.30` → n=37, mean=−$0.155. **VERDICT: KILL (unsalvageable).**

---

*Generated 2026-05-30 by `strategy_lab/_opt_2026_05_30/05_final_gated_configs.py`*
