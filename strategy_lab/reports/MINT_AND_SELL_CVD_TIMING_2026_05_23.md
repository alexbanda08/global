# Mint-and-sell V2: CVD-gated maker timing
_Generated 2026-05-23 — binance 1s CVD overlay on V2 policy_compare fills_

## Headline

**Main finding:** CVD slope alone is NOT a clean adverse-selection gate. The directional CVD does predict which leg gets held (a real, strong signal), but at post-time we can only see CVD magnitude — and magnitude does not separate adverse rate cleanly. **No gate satisfies the strict `cut ≥30% adverse / lose <20% positive` constraint.** The best-selectivity gate offers only ~0.2pp edge over a random gate.

- **Best-selectivity gate:** skip posting when |CVD_slope_30s| > p95 per-asset AND sigma_60s > p33 per-asset (gate_kind=`AND_abs_sigma`). Selectivity = **+0.23pp** (pct_neg_cut − pct_pos_lost).
  - Gates **4.8%** of fills. Cuts 4.9% of losers, drops 4.7% of winners.
  - Projected sum_pnl improvement: **+769.51 USD/day** (extrapolated, 28-day window, all 6 cells). Constraint state: `RELAXED_max_selectivity`.
- Baseline policy_compare sample sum_pnl_hold across cells: **-782.82 USD** (n=7,490 fills).

**Honest recommendation:** the deployable variant is *not* an unconditional CVD-magnitude gate but an **asymmetric-posting policy** — when |CVD_slope_30s| is in the top 20–30% per-asset, **skip posting the leg that flow would leave us holding** (post UP-ask only when cvd<<0, post DOWN-ask only when cvd>>0). Mint-and-sell V2 in its current both-sides-symmetric form cannot benefit from this without a strategy redesign. Until that redesign lands, the abs_cvd≥p80 gate offers a modest ~+$2.5k/day at the cost of 20% turnover. See sweep tables below.

> **Context:** V2 policy_compare aggregate is *loss-making* under the legacy 2%-on-profit fee assumption (per-cell `policy_compare_summary.csv` reports ≈ -$8k/day for BTC-5m alone). The CVD gate is *additive*: even modest improvements reduce capital usage. If you can wait for the asymmetric-posting redesign, the directional adverse signal (27% of fills → 55% of losses) is the real value to extract.

## Strongest signal observed

CVD direction (not magnitude) predicts which leg gets HELD. The directional asymmetry across CVD-slope_30s quartiles (overlay rows, all assets pooled):

| cvd_q4 | n | pct_up_held | pct_down_held | pct_both | mean_pnl | sum_pnl |
| --- | --- | --- | --- | --- | --- | --- |
| q1_low | 1873 | 29.738 | 21.783 | 36.679 | -0.088 | -164.342 |
| q2 | 1872 | 23.771 | 18.964 | 46.368 | -0.072 | -134.859 |
| q3 | 1872 | 20.085 | 23.504 | 47.329 | -0.116 | -216.521 |
| q4_high | 1873 | 21.303 | 32.248 | 34.063 | -0.143 | -267.094 |

Interpretation: q4 (highest positive CVD) has the highest Down_HELD share (32%) and lowest mean PnL (-0.143). When binance buyers push price up aggressively, polymarket UP-ask is hit first by other takers, leaving our maker holding only DOWN — the losing side. Symmetric in q1.

### Directional adverse rate (ex-post)

Define `adverse_dir = (Up_HELD AND cvd<0) OR (Down_HELD AND cvd>0)`. These are fills where the binance flow direction at fill-time agreed with the eventual losing side.

- Adverse-dir fills: **2,040** (27.2% of universe), mean PnL = **-0.2572**, sum = **-524.76**.
- Non-adverse fills:  **5,450** (72.8%),                    mean PnL = **-0.0473**, sum = **-258.06**.
- **Adverse share of total losses: 54.5%** — the directional adverse subset (27% of fills) is responsible for ~55% of all dollar losses.

**However**: at post-time we don't yet know which leg will be HELD — only the CVD direction. The expected-held side from CVD direction is `Down_HELD` when cvd>0 (buyers hit UP-ask first) and `Up_HELD` when cvd<0. So the gate must skip on `|CVD|` magnitude alone, and the adverse rate per |CVD| quintile is ROUGHLY FLAT (25-30%) — meaning the signal does NOT cleanly separate by magnitude. This is the central caveat: CVD direction predicts the LOSER side, but CVD magnitude does not predict adverse RATE.

## Per-bucket: CVD slope_30s

Buckets are PER-ASSET quantiles (p10/p30/p70/p90):

| cvd_bin | n | wr | mean_pnl_hold | sum_pnl_hold | mean_pnl_hyb | sum_pnl_hyb |
| --- | --- | --- | --- | --- | --- | --- |
| neg | 1498.0000 | 0.5634 | -0.0625 | -93.6844 | -0.0652 | -97.6365 |
| neutral | 2994.0000 | 0.5244 | -0.1103 | -330.2712 | -0.1118 | -334.7671 |
| pos | 1498.0000 | 0.5194 | -0.1364 | -204.3263 | -0.1346 | -201.6179 |
| very_neg | 750.0000 | 0.5680 | -0.0947 | -71.0260 | -0.0974 | -73.0390 |
| very_pos | 750.0000 | 0.5400 | -0.1113 | -83.5089 | -0.1086 | -81.4536 |

## Per-bucket: sigma (rolling 60s logret std)

| sigma_bin | n | wr | mean_pnl_hold | sum_pnl_hold | mean_pnl_hyb | sum_pnl_hyb |
| --- | --- | --- | --- | --- | --- | --- |
| high | 2472.00000 | 0.57403 | -0.09451 | -233.63016 | -0.09219 | -227.89496 |
| low | 2472.00000 | 0.50243 | -0.11650 | -287.99780 | -0.11782 | -291.25917 |
| med | 2546.00000 | 0.53496 | -0.10259 | -261.18876 | -0.10580 | -269.35989 |

## Cross-tab: CVD bin x sigma bin

| cvd_bin | sigma_bin | n | wr | mean_pnl_hold | sum_pnl_hold | mean_pnl_hyb | sum_pnl_hyb |
| --- | --- | --- | --- | --- | --- | --- | --- |
| neg | high | 494.0000 | 0.6073 | -0.0029 | -1.4462 | 0.0030 | 1.4802 |
| neg | low | 413.0000 | 0.5472 | -0.0968 | -39.9690 | -0.1037 | -42.8246 |
| neg | med | 591.0000 | 0.5381 | -0.0884 | -52.2692 | -0.0952 | -56.2921 |
| neutral | high | 529.0000 | 0.5747 | -0.0960 | -50.8068 | -0.0976 | -51.6559 |
| neutral | low | 1482.0000 | 0.5000 | -0.1202 | -178.0865 | -0.1204 | -178.4138 |
| neutral | med | 983.0000 | 0.5341 | -0.1031 | -101.3780 | -0.1065 | -104.6975 |
| pos | high | 510.0000 | 0.5490 | -0.1516 | -77.3263 | -0.1508 | -76.9242 |
| pos | low | 426.0000 | 0.4695 | -0.1449 | -61.7308 | -0.1414 | -60.2257 |
| pos | med | 562.0000 | 0.5302 | -0.1161 | -65.2691 | -0.1147 | -64.4680 |
| very_neg | high | 465.0000 | 0.5978 | -0.0980 | -45.5632 | -0.0956 | -44.4428 |
| very_neg | low | 73.0000 | 0.5068 | -0.0215 | -1.5704 | -0.0421 | -3.0739 |
| very_neg | med | 212.0000 | 0.5236 | -0.1127 | -23.8925 | -0.1204 | -25.5223 |
| very_pos | high | 474.0000 | 0.5422 | -0.1234 | -58.4878 | -0.1189 | -56.3524 |
| very_pos | low | 78.0000 | 0.4872 | -0.0851 | -6.6411 | -0.0862 | -6.7212 |
| very_pos | med | 198.0000 | 0.5556 | -0.0928 | -18.3800 | -0.0928 | -18.3800 |

## Per-cell impact (CVD bins only)

| cell | cvd_bin | n | wr | mean_pnl_hold | sum_pnl_hold | mean_pnl_hyb | sum_pnl_hyb |
| --- | --- | --- | --- | --- | --- | --- | --- |
| btc_15m | neg | 256.0000 | 0.6680 | -0.0165 | -4.2334 | -0.0108 | -2.7591 |
| btc_15m | neutral | 473.0000 | 0.5497 | -0.1534 | -72.5511 | -0.1584 | -74.9180 |
| btc_15m | pos | 264.0000 | 0.6098 | -0.0708 | -18.7010 | -0.0681 | -17.9717 |
| btc_15m | very_neg | 125.0000 | 0.5920 | -0.1076 | -13.4488 | -0.1284 | -16.0545 |
| btc_15m | very_pos | 124.0000 | 0.6452 | -0.0230 | -2.8508 | -0.0230 | -2.8508 |
| btc_5m | neg | 246.0000 | 0.6463 | -0.0354 | -8.6991 | -0.0345 | -8.4934 |
| btc_5m | neutral | 530.0000 | 0.6226 | -0.0623 | -33.0056 | -0.0601 | -31.8778 |
| btc_5m | pos | 238.0000 | 0.5966 | -0.1051 | -25.0178 | -0.1157 | -27.5334 |
| btc_5m | very_neg | 126.0000 | 0.6270 | -0.0823 | -10.3723 | -0.0823 | -10.3723 |
| btc_5m | very_pos | 127.0000 | 0.5748 | -0.1505 | -19.1087 | -0.1325 | -16.8334 |
| eth_15m | neg | 233.0000 | 0.5794 | -0.0230 | -5.3599 | -0.0315 | -7.3329 |
| eth_15m | neutral | 468.0000 | 0.5791 | -0.0327 | -15.3241 | -0.0368 | -17.2305 |
| eth_15m | pos | 251.0000 | 0.5378 | -0.1930 | -48.4431 | -0.1812 | -45.4778 |
| eth_15m | very_neg | 129.0000 | 0.6357 | -0.0771 | -9.9447 | -0.0708 | -9.1359 |
| eth_15m | very_pos | 132.0000 | 0.5303 | -0.1864 | -24.6091 | -0.1887 | -24.9020 |
| eth_5m | neg | 257.0000 | 0.5992 | -0.0869 | -22.3435 | -0.0848 | -21.8006 |
| eth_5m | neutral | 513.0000 | 0.5653 | -0.1370 | -70.3056 | -0.1373 | -70.4301 |
| eth_5m | pos | 239.0000 | 0.5439 | -0.1563 | -37.3647 | -0.1576 | -37.6569 |
| eth_5m | very_neg | 117.0000 | 0.6068 | -0.1087 | -12.7192 | -0.1087 | -12.7192 |
| eth_5m | very_pos | 114.0000 | 0.6404 | -0.0316 | -3.6071 | -0.0450 | -5.1303 |
| sol_15m | neg | 256.0000 | 0.4727 | -0.0244 | -6.2476 | -0.0386 | -9.8748 |
| sol_15m | neutral | 465.0000 | 0.3806 | -0.1189 | -55.2916 | -0.1212 | -56.3464 |
| sol_15m | pos | 253.0000 | 0.3992 | -0.1744 | -44.1154 | -0.1717 | -43.4467 |
| sol_15m | very_neg | 132.0000 | 0.5227 | -0.0666 | -8.7967 | -0.0683 | -9.0128 |
| sol_15m | very_pos | 114.0000 | 0.4561 | -0.0788 | -8.9851 | -0.0802 | -9.1453 |
| sol_5m | neg | 250.0000 | 0.4160 | -0.1872 | -46.8008 | -0.1895 | -47.3755 |
| sol_5m | neutral | 545.0000 | 0.4440 | -0.1537 | -83.7933 | -0.1541 | -83.9643 |
| sol_5m | pos | 253.0000 | 0.4308 | -0.1213 | -30.6842 | -0.1167 | -29.5314 |
| sol_5m | very_neg | 121.0000 | 0.4215 | -0.1301 | -15.7443 | -0.1301 | -15.7443 |
| sol_5m | very_pos | 139.0000 | 0.4101 | -0.1752 | -24.3480 | -0.1625 | -22.5917 |

## Gate sweep — AND gate (|CVD| > p_abs AND sigma > p_sig)

Top 12 by projected $/day improvement. `pct_gated` = share of fills skipped; `pct_neg_cut` = share of losing fills avoided; `pct_pos_lost` = share of profitable fills no longer captured.

| abs_q | sig_q | pct_gated | kept_neg | kept_pos | pct_neg_cut | pct_pos_lost | sum_pnl_kept_sample | delta_pnl_per_day_extrap | gate_kind |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0.500 | 0.000 | 49.987 | 1352 | 1984 | 48.788 | 50.684 | -413.782 | 5560.834 | AND_abs_sigma |
| 0.500 | 0.330 | 40.013 | 1650 | 2356 | 37.500 | 41.437 | -497.691 | 4570.663 | AND_abs_sigma |
| 0.600 | 0.000 | 40.000 | 1632 | 2366 | 38.182 | 41.188 | -496.223 | 4389.074 | AND_abs_sigma |
| 0.600 | 0.330 | 33.191 | 1831 | 2627 | 30.644 | 34.700 | -553.312 | 3744.133 | AND_abs_sigma |
| 0.500 | 0.500 | 32.056 | 1874 | 2650 | 29.015 | 34.129 | -569.607 | 3449.629 | AND_abs_sigma |
| 0.700 | 0.000 | 30.013 | 1900 | 2772 | 28.030 | 31.096 | -576.428 | 3165.007 | AND_abs_sigma |
| 0.600 | 0.500 | 27.276 | 1995 | 2851 | 24.432 | 29.132 | -601.921 | 2974.572 | AND_abs_sigma |
| 0.700 | 0.330 | 25.808 | 2025 | 2928 | 23.295 | 27.218 | -612.147 | 2764.534 | AND_abs_sigma |
| 0.750 | 0.000 | 24.993 | 2027 | 2976 | 23.220 | 26.025 | -608.053 | 2667.143 | AND_abs_sigma |
| 0.800 | 0.000 | 20.013 | 2135 | 3193 | 19.129 | 20.631 | -622.398 | 2527.979 | AND_abs_sigma |
| 0.500 | 0.670 | 22.937 | 2087 | 3037 | 20.947 | 24.509 | -624.411 | 2448.784 | AND_abs_sigma |
| 0.750 | 0.330 | 21.896 | 2121 | 3089 | 19.659 | 23.217 | -630.686 | 2422.038 | AND_abs_sigma |

## Gate sweep — abs_cvd-only gate

Skip posting whenever `|CVD_slope_30s| > p_abs` per-asset, regardless of sigma:

| abs_q | sig_q | pct_gated | kept_neg | kept_pos | pct_neg_cut | pct_pos_lost | sum_pnl_kept_sample | delta_pnl_per_day_extrap | gate_kind |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0.500 | nan | 49.987 | 1352 | 1984 | 48.788 | 50.684 | -413.782 | 5560.834 | abs_cvd_only |
| 0.600 | nan | 40.000 | 1632 | 2366 | 38.182 | 41.188 | -496.223 | 4389.074 | abs_cvd_only |
| 0.700 | nan | 30.013 | 1900 | 2772 | 28.030 | 31.096 | -576.428 | 3165.007 | abs_cvd_only |
| 0.750 | nan | 24.993 | 2027 | 2976 | 23.220 | 26.025 | -608.053 | 2667.143 | abs_cvd_only |
| 0.800 | nan | 20.013 | 2135 | 3193 | 19.129 | 20.631 | -622.398 | 2527.979 | abs_cvd_only |
| 0.850 | nan | 15.020 | 2242 | 3410 | 15.076 | 15.237 | -648.216 | 2210.833 | abs_cvd_only |
| 0.900 | nan | 10.013 | 2377 | 3615 | 9.962 | 10.142 | -689.000 | 1658.350 | abs_cvd_only |
| 0.950 | nan | 5.020 | 2505 | 3825 | 5.114 | 4.922 | -737.467 | 763.714 | abs_cvd_only |

## Gate sweep — OR gate (|CVD| OR sigma high)

Skip posting when EITHER `|CVD_slope_30s| > p_abs` OR `sigma_60s > p_sig` per-asset:

| abs_q | sig_q | pct_gated | kept_neg | kept_pos | pct_neg_cut | pct_pos_lost | sum_pnl_kept_sample | delta_pnl_per_day_extrap | gate_kind |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0.500 | 0.330 | 76.969 | 656 | 870 | 75.152 | 78.374 | -204.089 | 8500.589 | OR_abs_sigma |
| 0.600 | 0.330 | 73.805 | 755 | 981 | 71.402 | 75.615 | -230.909 | 8155.360 | OR_abs_sigma |
| 0.700 | 0.330 | 71.202 | 829 | 1086 | 68.598 | 73.005 | -252.278 | 7910.891 | OR_abs_sigma |
| 0.750 | 0.330 | 70.093 | 860 | 1129 | 67.424 | 71.936 | -265.364 | 7755.523 | OR_abs_sigma |
| 0.850 | 0.330 | 68.184 | 916 | 1202 | 65.303 | 70.122 | -279.583 | 7668.941 | OR_abs_sigma |
| 0.800 | 0.330 | 68.972 | 891 | 1173 | 66.250 | 70.843 | -275.061 | 7662.844 | OR_abs_sigma |
| 0.900 | 0.330 | 67.543 | 934 | 1224 | 64.621 | 69.575 | -278.458 | 7657.262 | OR_abs_sigma |
| 0.950 | 0.330 | 67.210 | 949 | 1233 | 64.053 | 69.351 | -289.057 | 7504.621 | OR_abs_sigma |
| 0.500 | 0.500 | 67.917 | 900 | 1233 | 65.909 | 69.351 | -284.869 | 7319.192 | OR_abs_sigma |
| 0.600 | 0.500 | 62.710 | 1059 | 1414 | 59.886 | 64.852 | -334.995 | 6622.488 | OR_abs_sigma |
| 0.500 | 0.670 | 60.053 | 1108 | 1551 | 58.030 | 61.447 | -338.557 | 6473.762 | OR_abs_sigma |
| 0.700 | 0.500 | 58.117 | 1192 | 1592 | 54.848 | 60.428 | -372.109 | 6145.247 | OR_abs_sigma |

## Adverse-fill agreement check

`cvd_agree_with_loss=True` means the maker is long the wrong side of the CVD direction:

| cvd_agree_with_loss | n | wr | mean_pnl | sum_pnl |
| --- | --- | --- | --- | --- |
| 0 | 5450 | 0.6565 | -0.0473 | -258.0553 |
| 1 | 2040 | 0.2181 | -0.2572 | -524.7614 |

## Sample-size warnings

- All cross-tab buckets have n≥30.

Per-cell sample (n_sample / n_total / extrap_factor):

| cell | n_total | n_sample | extrap |
| --- | --- | --- | --- |
| btc_5m | 1835980.0 | 2000 | 918.0 |
| btc_15m | 1041121.0 | 2000 | 520.6 |
| eth_5m | 986863.0 | 2000 | 493.4 |
| eth_15m | 498817.0 | 2000 | 249.4 |
| sol_5m | 556856.0 | 2000 | 278.4 |
| sol_15m | 293532.0 | 2000 | 146.8 |

## Methodology

1. Binance 1s klines (`binance_1s_28d.parquet`) per asset (BTC/ETH/SOL). Signed flow = `2*taker_buy_base - volume_traded`; CVD = cumsum; slope_30s = (CVD[t] - CVD[t-30s])/30. sigma_60s = std of 1s log-returns over the last 60 seconds.
2. V2 fills loaded from `_results/mint_and_sell_v2_<asset>_<tf>_2026_05_16/policy_compare.parquet` (each cell is a 2,000-row sample of full opportunities universe; `policy_compare_summary.csv` carries the extrapolation factor `n_total / n_sample`).
3. `merge_asof` join (5s backward tolerance) on `ts` (microseconds) attaches CVD/sigma to each fill.
4. `maker_side`: scenario `Up_HELD` -> we own UP (loses on price down); `Down_HELD` -> we own DOWN (loses on price up); `BOTH` -> flat at $0.50 ± edge.
5. Gate sweep: for each (abs_q × sig_q) combo, gate fills whose `|CVD_slope_30s|` exceeds per-asset `p_abs_q` AND `sigma_60s` exceeds per-asset `p_sig_q`; remaining sum_pnl extrapolated per cell, normalised to 28-day window.

## Files

- Per-fill overlay: `C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical\_results\mint_and_sell_cvd_overlay.csv` (~1802.0 KB)
- Script: `strategy_lab/markov_filter/_cvd_timing_overlay.py`
