# VectorBT MEGA indicator sweep — underlying crypto direction — auto

~45 indicator families (TA-Lib + custom) × params × modes + 2-indicator combos. IS=first60%, OOS=last40%, fee=5bps/flip. Per series: best-20 by IS-Sharpe, OOS-confirmed, vs shuffled null.

## BTCUSDT_15m  (n=307582, 2017-08-17→2026-05-31, strat=400245, null_p95=1.17)
| strategy | IS Sharpe | ntr | VAL Sharpe | OOS Sharpe |
|---|--:|--:|--:|--:|
| MAx_KAMA_50_200&MAx_TEMA_50_200&CCI_rev_20_-150_150 | 2.12 | 3089 | -1.47 | -1.01 |
| CCI_rev_14_-150_150&MAx_DEMA_50_100&RSI_mom_28_35_65 | 2.03 | 3404 | -1.44 | -2.38 |
| MAx_DEMA_50_100&KELT_brk_20_2.5&WILLR_rev_7_-90_-10 | 2.02 | 5650 | -1.67 | -2.76 |
| MAx_DEMA_50_100&MAx_SMA_50_100&WILLR_rev_7_-90_-10 | 2.01 | 6978 | -1.51 | -2.97 |
| WILLR_rev_7_-90_-10|RSI_mom_28_20_80|or | 1.95 | 7294 | -1.87 | -2.65 |
| RSI_mom_28_20_80|WILLR_rev_7_-90_-10|or | 1.95 | 7294 | -1.87 | -2.65 |
| MAx_TEMA_50_100&MAx_EMA_50_200&WILLR_rev_7_-90_-10 | 1.87 | 4420 | -1.66 | -2.42 |
| MAx_TEMA_50_200&WILLR_rev_7_-90_-10&MAx_SMA_50_200 | 1.85 | 5000 | -1.72 | -2.39 |
| WILLR_rev_14_-90_-10&MAx_DEMA_50_100&RSI_mom_21_35_65 | 1.84 | 3774 | -1.20 | -1.86 |
| MAx_TEMA_50_200&WILLR_rev_7_-90_-10&MAx_SMA_20_100 | 1.83 | 7214 | -2.24 | -3.00 |
| STOCH_rev_21&MAx_DEMA_50_100&MFI_mom_28_25_75 | 1.82 | 3318 | -0.76 | -2.04 |
| CCI_rev_14_-150_150&MAx_TEMA_50_200&RSI_mom_14_30_70 | 1.82 | 3945 | -1.14 | -1.95 |

## BTCUSDT_1d  (n=3210, 2017-08-17→2026-05-31, strat=400231, null_p95=1.52)
| strategy | IS Sharpe | ntr | VAL Sharpe | OOS Sharpe |
|---|--:|--:|--:|--:|
| MAx_KAMA_50_100&CMO_mom_21_-50_50&MAx_TEMA_20_50 | 1.91 | 22 | 0.82 | 0.78 ✅ |
| RSI_mom_21_25_75&MAx_TEMA_20_50&MAx_KAMA_50_100 | 1.91 | 22 | 0.82 | 0.78 ✅ |
| MAx_TEMA_20_50&MAx_TRIMA_50_200&MAx_KAMA_50_100 | 1.88 | 34 | 0.63 | 1.10 ✅ |
| MAx_WMA_8_34&CMF_20&MFI_rev_7_25_75 | 1.74 | 78 | -0.76 | -0.92 |
| MFI_rev_7_25_75&STOCH_cross_21&MOM_14 | 1.74 | 178 | -0.24 | 0.52 |
| MAx_KAMA_50_100&RSI_mom_28_30_70&MAx_TEMA_13_48 | 1.73 | 34 | 1.18 | 0.43 ✅ |
| CMO_mom_28_-40_40&MAx_KAMA_10_30&MAx_KAMA_50_100 | 1.72 | 32 | 0.48 | 0.42 ✅ |
| RSI_mom_7_25_75&CMF_20&FORCE | 1.72 | 199 | 0.48 | -0.27 |
| CMF_50&MFI_rev_7_25_75&MAx_WMA_8_34 | 1.72 | 76 | -1.17 | 0.22 |
| CMF_20&MFI_rev_7_25_75&FORCE | 1.67 | 120 | -0.60 | -0.81 |
| MAx_DEMA_20_200&CMF_50&MAx_KAMA_50_100 | 1.65 | 37 | 0.80 | 0.36 ✅ |
| AROON_20&MAx_T3_20_200&ADXDI_14_20 | 1.65 | 12 | -0.33 | -0.39 |

## BTCUSDT_1h  (n=76909, 2017-08-17→2026-05-31, strat=400245, null_p95=1.51)
| strategy | IS Sharpe | ntr | VAL Sharpe | OOS Sharpe |
|---|--:|--:|--:|--:|
| WILLR_rev_7_-90_-10&MAx_DEMA_10_30&RSI_mom_14_20_80 | 2.08 | 1306 | -0.14 | -1.19 |
| MAx_DEMA_8_34&RSI_mom_14_20_80&WILLR_rev_7_-90_-10 | 1.98 | 1292 | 0.09 | -1.32 |
| DONCH_brk_20&MAx_TEMA_20_50&MAx_EMA_50_100 | 1.96 | 1093 | 0.40 | -1.04 |
| DONCH_brk_20&MFI_mom_7_20_80&KELT_brk_20_2.5 | 1.91 | 709 | 1.09 | -1.12 |
| CCI_rev_20_-200_200&CMO_mom_7_-50_50&RSI_mom_28_35_65 | 1.91 | 400 | -0.55 | -1.78 |
| MFI_mom_14_25_75&RSI_mom_28_25_75&RSI_mom_14_20_80 | 1.87 | 403 | -0.14 | -0.03 |
| RSI_mom_14_25_75&DONCH_brk_20&MAx_TEMA_20_50 | 1.87 | 983 | 0.99 | -1.31 |
| VORTEX_21&RSI_mom_21_30_70&MAx_TEMA_20_50 | 1.86 | 2225 | 0.63 | -0.64 |
| CMO_mom_21_-50_50&MAx_TEMA_20_50&MFI_mom_7_25_75 | 1.85 | 1586 | 1.10 | -0.81 |
| MFI_mom_7_20_80&MFI_mom_14_25_75&RSI_mom_14_20_80 | 1.85 | 931 | 0.94 | -0.52 |
| RSI_mom_14_20_80&RSI_mom_14_25_75&MAx_TEMA_20_50 | 1.85 | 1307 | 1.19 | -0.77 |
| MAx_TEMA_20_50&CMO_mom_14_-50_50&CMO_mom_21_-50_50 | 1.84 | 1223 | 1.01 | -0.77 |

## BTCUSDT_4h  (n=19242, 2017-08-17→2026-05-31, strat=400243, null_p95=1.5)
| strategy | IS Sharpe | ntr | VAL Sharpe | OOS Sharpe |
|---|--:|--:|--:|--:|
| RSI_mom_14_25_75&RSI_mom_21_20_80&MAx_EMA_5_20 | 1.80 | 288 | 0.32 | -0.71 |
| RSI_mom_28_25_75&CMO_mom_14_-50_50&MAx_SMA_5_20 | 1.78 | 350 | 0.86 | -0.77 |
| CMO_mom_14_-50_50&MAx_EMA_5_20&RSI_mom_28_25_75 | 1.75 | 304 | 0.47 | -0.60 |
| RSI_mom_21_20_80&FORCE&RSI_mom_21_30_70 | 1.75 | 588 | -0.14 | -1.37 |
| KELT_brk_20_2.5&RSI_mom_21_20_80&MAx_WMA_5_20 | 1.75 | 352 | 1.08 | -1.16 |
| MAx_WMA_9_21&MFI_mom_14_25_75&MFI_rev_7_25_75 | 1.75 | 382 | 0.33 | -1.09 |
| CMO_mom_21_-40_40&MAx_SMA_5_20&RSI_mom_21_20_80 | 1.74 | 320 | 0.46 | -0.71 |
| CMO_mom_14_-50_50&MAx_SMA_20_200&MAx_SMA_5_20 | 1.74 | 551 | 0.17 | -0.27 |
| MAx_SMA_5_20&MAx_EMA_50_200&MAx_TRIMA_50_200 | 1.74 | 529 | 0.09 | -0.42 |
| RSI_mom_28_25_75&RSI_mom_14_25_75&MAx_TEMA_20_50 | 1.74 | 256 | 0.60 | -0.67 |
| RSI_mom_14_25_75&MAx_WMA_5_20&MAx_EMA_50_200 | 1.73 | 601 | 0.24 | -0.55 |
| MAx_T3_8_34&MAx_SMA_5_20&MFI_rev_7_25_75 | 1.73 | 484 | -1.08 | -1.62 |

## ETHUSDT_15m  (n=307582, 2017-08-17→2026-05-31, strat=400245, null_p95=1.25)
| strategy | IS Sharpe | ntr | VAL Sharpe | OOS Sharpe |
|---|--:|--:|--:|--:|
| MAx_SMA_20_100|RSI_mom_28_20_80|or | 1.84 | 2065 | 0.26 | 0.30 |
| RSI_mom_28_20_80|MAx_SMA_20_100|or | 1.84 | 2065 | 0.26 | 0.30 |
| RSI_mom_28_20_80|MAx_WMA_50_100|or | 1.84 | 1949 | 0.41 | 0.50 ✅ |
| MAx_WMA_50_100|RSI_mom_28_20_80|or | 1.84 | 1949 | 0.41 | 0.50 ✅ |
| RSI_mom_28_20_80|MAx_SMA_20_100|and | 1.83 | 2054 | 0.26 | 0.30 |
| MAx_SMA_20_100|RSI_mom_28_20_80|and | 1.83 | 2054 | 0.26 | 0.30 |
| RSI_mom_28_20_80|MAx_WMA_50_100|and | 1.82 | 1946 | 0.41 | 0.50 ✅ |
| MAx_WMA_50_100|RSI_mom_28_20_80|and | 1.82 | 1946 | 0.41 | 0.50 ✅ |
| MAx_T3_20_50&RSI_mom_28_20_80&RSI_mom_21_20_80 | 1.78 | 1809 | 0.47 | 0.15 |
| RSI_mom_28_20_80|MFI_mom_28_25_75|or | 1.77 | 569 | 0.62 | 0.37 ✅ |
| MFI_mom_28_25_75|RSI_mom_28_20_80|and | 1.77 | 565 | 0.62 | 0.37 ✅ |
| RSI_mom_28_20_80|MFI_mom_28_25_75|and | 1.77 | 565 | 0.62 | 0.37 ✅ |

## ETHUSDT_1d  (n=3210, 2017-08-17→2026-05-31, strat=400220, null_p95=1.4)
| strategy | IS Sharpe | ntr | VAL Sharpe | OOS Sharpe |
|---|--:|--:|--:|--:|
| MAx_TEMA_20_50|MAx_TRIMA_50_100|or | 1.96 | 63 | 0.27 | 0.62 |
| MAx_TRIMA_50_100|MAx_TEMA_20_50|or | 1.96 | 63 | 0.27 | 0.62 |
| MAx_KAMA_5_20&WILLR_mom_28_-80_-20&STOCH_rev_14 | 1.95 | 42 | -0.23 | 0.88 |
| MAx_TEMA_20_50|TRIX_30|or | 1.88 | 66 | 0.21 | 0.34 |
| TRIX_30|MAx_TEMA_20_50|or | 1.88 | 66 | 0.21 | 0.34 |
| MAx_KAMA_20_200&MAx_TRIMA_50_100&MAx_TEMA_20_50 | 1.85 | 52 | 0.63 | 0.50 ✅ |
| MAx_TEMA_20_50&WILLR_mom_21_-90_-10&MAx_TRIMA_50_100 | 1.85 | 53 | 0.17 | 0.85 |
| WILLR_mom_21_-90_-10&MAx_TRIMA_50_100&MAx_TEMA_20_50 | 1.85 | 53 | 0.17 | 0.85 |
| WILLR_mom_21_-90_-10&MAx_TEMA_20_50&MAx_TRIMA_50_100 | 1.85 | 53 | 0.17 | 0.85 |
| MAx_TRIMA_50_100&MAx_T3_5_20&MAx_DEMA_8_34 | 1.85 | 81 | 0.12 | 0.87 |
| MAx_WMA_13_48&MAx_DEMA_8_34&MAx_TRIMA_50_100 | 1.84 | 83 | 0.08 | 0.99 |
| MAx_DEMA_8_34|MAx_TRIMA_50_100|or | 1.83 | 100 | 0.14 | 0.73 |

## ETHUSDT_1h  (n=76909, 2017-08-17→2026-05-31, strat=400245, null_p95=1.41)
| strategy | IS Sharpe | ntr | VAL Sharpe | OOS Sharpe |
|---|--:|--:|--:|--:|
| KST&MAx_TRIMA_20_100&VORTEX_14 | 1.99 | 2815 | 0.70 | -0.59 |
| RSI_mom_21_20_80&KELT_brk_20_2.5&KST | 1.91 | 1173 | -0.35 | 0.11 |
| KST&COPPOCK&MAx_TRIMA_20_100 | 1.88 | 2478 | 1.00 | -0.72 |
| KST|MAx_TRIMA_20_100|or | 1.88 | 2525 | 0.87 | -0.80 |
| MAx_TRIMA_20_100|KST|or | 1.88 | 2525 | 0.87 | -0.80 |
| KST|MAx_TRIMA_20_100|and | 1.88 | 2522 | 0.87 | -0.80 |
| MAx_TRIMA_20_100|KST|and | 1.88 | 2522 | 0.87 | -0.80 |
| KST&KST&MAx_TRIMA_20_100 | 1.88 | 2522 | 0.87 | -0.80 |
| MAx_TRIMA_20_100&KST&MAx_WMA_9_21 | 1.87 | 2537 | 0.72 | -0.50 |
| KST|MAx_WMA_50_100|or | 1.84 | 2424 | 0.69 | -0.38 |
| MAx_WMA_50_100|KST|or | 1.84 | 2424 | 0.69 | -0.38 |
| MAx_WMA_50_100|KST|and | 1.84 | 2421 | 0.69 | -0.38 |

## ETHUSDT_4h  (n=19242, 2017-08-17→2026-05-31, strat=400241, null_p95=1.5)
| strategy | IS Sharpe | ntr | VAL Sharpe | OOS Sharpe |
|---|--:|--:|--:|--:|
| CMO_mom_28_-40_40&MAx_SMA_50_200&MAx_SMA_5_20 | 2.07 | 447 | 0.56 | 0.37 ✅ |
| KELT_brk_20_2.0&MAx_TRIMA_50_200&HULL_100 | 2.05 | 647 | 0.70 | 0.81 ✅ |
| HULL_100&KELT_brk_20_2.0&MAx_TRIMA_50_200 | 2.05 | 647 | 0.70 | 0.81 ✅ |
| COPPOCK&MAx_SMA_50_200&RSI_mom_14_20_80 | 2.04 | 379 | 0.43 | 0.17 |
| MAx_EMA_20_200&MAx_SMA_5_20&CMO_mom_28_-40_40 | 2.02 | 475 | 0.51 | 0.26 |
| MAx_TRIMA_50_200&MAx_SMA_9_21&RSI_mom_14_20_80 | 2.00 | 395 | -0.04 | 0.24 |
| MAx_TRIMA_9_21&MAx_SMA_50_200&CMO_mom_28_-40_40 | 2.00 | 473 | 0.07 | 0.40 |
| MAx_TRIMA_50_200&RSI_mom_14_20_80&LINREGSLOPE_20 | 1.99 | 377 | 0.25 | 0.13 |
| MAx_WMA_10_30&RSI_mom_14_20_80&MAx_SMA_50_200 | 1.99 | 359 | 0.37 | 0.10 |
| RSI_mom_14_20_80&MAx_EMA_50_200&LINREGSLOPE_20 | 1.98 | 401 | 0.34 | 0.17 |
| CMO_mom_28_-40_40&MAx_SMA_9_21&MAx_EMA_50_200 | 1.97 | 419 | 0.09 | 0.24 |
| CMO_mom_21_-50_50&MAx_EMA_20_200&MAx_SMA_5_20 | 1.97 | 480 | 0.55 | 0.50 ✅ |

## SOLUSDT_15m  (n=203403, 2020-08-11→2026-05-31, strat=400245, null_p95=1.7)
| strategy | IS Sharpe | ntr | VAL Sharpe | OOS Sharpe |
|---|--:|--:|--:|--:|
| RSI_rev_14_30_70&MAx_EMA_50_100&RSI_mom_28_30_70 | 2.08 | 878 | 1.48 | -0.43 |
| CMO_rev_14_-40_40&RSI_mom_28_30_70&MAx_EMA_50_100 | 2.08 | 878 | 1.48 | -0.43 |
| MAx_TRIMA_20_200&WILLR_rev_28_-90_-10&MAx_TEMA_50_100 | 1.90 | 1298 | -1.49 | -1.95 |
| MAx_EMA_50_100&CMO_rev_14_-40_40&RSI_mom_21_30_70 | 1.88 | 962 | 0.69 | -0.03 |
| CMO_mom_28_-40_40&RSI_rev_14_30_70&MAx_DEMA_50_200 | 1.87 | 608 | 0.85 | 0.33 ✅ |
| MAx_EMA_50_100&RSI_rev_14_30_70&RSI_mom_14_20_80 | 1.84 | 900 | 0.98 | -1.13 |
| RSI_mom_28_30_70&RSI_rev_14_30_70&MAx_TRIMA_20_200 | 1.84 | 924 | 1.45 | -0.60 |
| BB_rev_20_2.5&MAx_EMA_50_100&RSI_rev_14_30_70 | 1.83 | 1192 | 0.69 | -1.62 |
| MAx_EMA_50_200&MFI_rev_21_25_75&MFI_rev_21_20_80 | 1.83 | 954 | 0.19 | -1.14 |
| RSI_rev_14_30_70&CMO_mom_28_-40_40&MAx_SMA_20_200 | 1.82 | 882 | 1.67 | -0.26 |
| RSI_rev_21_35_65&MAx_EMA_20_200&BB_rev_20_2.5 | 1.79 | 1088 | -0.17 | -2.33 |
| CMO_mom_28_-50_50&MAx_WMA_50_200&RSI_rev_14_30_70 | 1.75 | 828 | 1.72 | -0.73 |

## SOLUSDT_1d  (n=2120, 2020-08-11→2026-05-31, strat=400203, null_p95=1.58)
| strategy | IS Sharpe | ntr | VAL Sharpe | OOS Sharpe |
|---|--:|--:|--:|--:|
| MAx_DEMA_10_30&MAx_TRIMA_13_48&CMF_50 | 2.39 | 63 | 1.37 | 0.71 ✅ |
| MAx_TRIMA_13_48&HULL_20&MAx_DEMA_10_30 | 2.32 | 122 | 1.35 | 0.74 ✅ |
| MAx_TRIMA_13_48&MAx_TRIMA_10_50&HULL_20 | 2.32 | 199 | 0.99 | 0.41 ✅ |
| HULL_20&MAx_DEMA_10_30&TRIX_30 | 2.29 | 82 | 1.03 | 0.18 |
| TRIX_30&MAx_DEMA_10_30&HULL_20 | 2.29 | 82 | 1.03 | 0.18 |
| MAx_SMA_10_50&HULL_20&MAx_TRIMA_10_50 | 2.29 | 191 | 0.94 | 0.56 ✅ |
| MAx_TRIMA_9_21&MAx_TRIMA_13_48&ADOSC | 2.29 | 101 | 1.32 | -0.43 |
| MAx_DEMA_10_30&HULL_20&WILLR_mom_14_-90_-10 | 2.28 | 143 | 1.02 | 0.86 ✅ |
| HULL_20&MAx_SMA_10_50&MAx_DEMA_10_30 | 2.27 | 119 | 1.25 | 0.68 ✅ |
| HULL_20&MAx_TRIMA_9_21&MAx_SMA_10_50 | 2.27 | 155 | 1.23 | 0.38 ✅ |
| ROC_30&WILLR_mom_14_-90_-10&MAx_DEMA_10_30 | 2.19 | 76 | 1.21 | 0.47 ✅ |
| MOM_30&MAx_DEMA_10_30&CMF_50 | 2.19 | 80 | 1.50 | 0.49 ✅ |

## SOLUSDT_1h  (n=50855, 2020-08-11→2026-05-31, strat=400243, null_p95=1.54)
| strategy | IS Sharpe | ntr | VAL Sharpe | OOS Sharpe |
|---|--:|--:|--:|--:|
| MAx_EMA_20_100&CMO_mom_28_-50_50&MFI_rev_14_25_75 | 2.56 | 368 | 0.31 | -1.63 |
| MAx_WMA_20_200&MFI_rev_14_25_75&RSI_mom_28_25_75 | 2.52 | 346 | 0.58 | -1.30 |
| MFI_rev_14_25_75&CCI_mom_40_-200_200&RSI_mom_28_25_75 | 2.41 | 292 | 0.76 | 0.22 |
| WILLR_mom_21_-80_-20&MAx_EMA_13_48&MFI_rev_14_25_75 | 2.40 | 736 | 0.77 | -0.11 |
| MAx_DEMA_20_200&MFI_rev_14_25_75&BB_brk_20_2.5 | 2.30 | 492 | -0.62 | -1.29 |
| MFI_rev_14_25_75&MAx_EMA_10_30&MAx_T3_10_50 | 2.25 | 780 | 0.56 | -1.53 |
| MFI_rev_14_20_80&RSI_mom_14_30_70&RSI_mom_28_25_75 | 2.22 | 196 | 0.11 | -0.23 |
| MFI_rev_14_25_75|MAx_EMA_20_100|or | 2.21 | 727 | 0.49 | -2.07 |
| MAx_EMA_20_100|MFI_rev_14_25_75|or | 2.21 | 727 | 0.49 | -2.07 |
| MFI_rev_14_25_75&RSI_mom_14_30_70&MAx_WMA_20_200 | 2.21 | 516 | 0.91 | -1.09 |
| MAx_WMA_20_200&RSI_mom_14_30_70&MFI_rev_14_25_75 | 2.21 | 516 | 0.91 | -1.09 |
| MAx_WMA_50_100&KELT_brk_20_2.5&MFI_rev_14_25_75 | 2.20 | 474 | 0.77 | -0.55 |

## SOLUSDT_4h  (n=12719, 2020-08-11→2026-05-31, strat=400235, null_p95=1.75)
| strategy | IS Sharpe | ntr | VAL Sharpe | OOS Sharpe |
|---|--:|--:|--:|--:|
| MAx_SMA_20_100&STOCH_rev_14&MAx_DEMA_10_50 | 2.48 | 162 | 1.07 | -0.63 |
| MAx_KAMA_13_48&MAx_DEMA_10_50&STOCH_rev_14 | 2.47 | 202 | 0.80 | -0.66 |
| HT_TREND&MAx_DEMA_13_48&WILLR_rev_7_-80_-20 | 2.45 | 460 | -1.12 | 0.56 |
| STOCH_rev_14&MAx_T3_8_34&MAx_TEMA_50_200 | 2.44 | 292 | 1.29 | 0.23 |
| WILLR_rev_7_-80_-20|HT_TREND|and | 2.39 | 590 | -0.68 | 0.39 |
| HT_TREND|WILLR_rev_7_-80_-20|and | 2.39 | 590 | -0.68 | 0.39 |
| HT_TREND&WILLR_rev_7_-80_-20&MAx_WMA_10_30 | 2.31 | 514 | -0.93 | 0.77 |
| STOCH_rev_14&MAx_T3_10_30&MAx_SMA_20_100 | 2.29 | 222 | 1.77 | 0.37 ✅ |
| HT_TREND&MAx_TEMA_50_100&WILLR_rev_7_-80_-20 | 2.28 | 420 | -1.07 | 1.09 |
| MAx_WMA_20_50&MAx_TEMA_50_200&STOCH_rev_14 | 2.27 | 264 | 0.96 | 0.08 |
| WILLR_rev_7_-80_-20&HT_TREND&CCI_mom_20_-150_150 | 2.24 | 466 | -0.88 | 0.60 |
| MAx_EMA_10_50&STOCH_rev_14&MAx_T3_8_34 | 2.24 | 316 | 1.24 | 0.17 |

## Survivors (IS>null_p95 AND VAL>0.3 AND OOS>0.3 — positive in ALL three independent periods)

| series | strategy | IS | VAL | OOS |
|---|---|--:|--:|--:|
| BTCUSDT_1d | MAx_KAMA_50_100&CMO_mom_21_-50_50&MAx_TEMA_20_50 | 1.91 | 0.82 | 0.78 |
| BTCUSDT_1d | RSI_mom_21_25_75&MAx_TEMA_20_50&MAx_KAMA_50_100 | 1.91 | 0.82 | 0.78 |
| BTCUSDT_1d | MAx_TEMA_20_50&MAx_TRIMA_50_200&MAx_KAMA_50_100 | 1.88 | 0.63 | 1.10 |
| BTCUSDT_1d | MAx_KAMA_50_100&RSI_mom_28_30_70&MAx_TEMA_13_48 | 1.73 | 1.18 | 0.43 |
| BTCUSDT_1d | CMO_mom_28_-40_40&MAx_KAMA_10_30&MAx_KAMA_50_100 | 1.72 | 0.48 | 0.42 |
| BTCUSDT_1d | MAx_DEMA_20_200&CMF_50&MAx_KAMA_50_100 | 1.65 | 0.80 | 0.36 |
| ETHUSDT_15m | RSI_mom_28_20_80|MAx_WMA_50_100|or | 1.84 | 0.41 | 0.50 |
| ETHUSDT_15m | MAx_WMA_50_100|RSI_mom_28_20_80|or | 1.84 | 0.41 | 0.50 |
| ETHUSDT_15m | RSI_mom_28_20_80|MAx_WMA_50_100|and | 1.82 | 0.41 | 0.50 |
| ETHUSDT_15m | MAx_WMA_50_100|RSI_mom_28_20_80|and | 1.82 | 0.41 | 0.50 |
| ETHUSDT_15m | RSI_mom_28_20_80|MFI_mom_28_25_75|or | 1.77 | 0.62 | 0.37 |
| ETHUSDT_15m | MFI_mom_28_25_75|RSI_mom_28_20_80|and | 1.77 | 0.62 | 0.37 |
| ETHUSDT_15m | RSI_mom_28_20_80|MFI_mom_28_25_75|and | 1.77 | 0.62 | 0.37 |
| ETHUSDT_1d | MAx_KAMA_20_200&MAx_TRIMA_50_100&MAx_TEMA_20_50 | 1.85 | 0.63 | 0.50 |
| ETHUSDT_4h | CMO_mom_28_-40_40&MAx_SMA_50_200&MAx_SMA_5_20 | 2.07 | 0.56 | 0.37 |
| ETHUSDT_4h | KELT_brk_20_2.0&MAx_TRIMA_50_200&HULL_100 | 2.05 | 0.70 | 0.81 |
| ETHUSDT_4h | HULL_100&KELT_brk_20_2.0&MAx_TRIMA_50_200 | 2.05 | 0.70 | 0.81 |
| ETHUSDT_4h | CMO_mom_21_-50_50&MAx_EMA_20_200&MAx_SMA_5_20 | 1.97 | 0.55 | 0.50 |
| SOLUSDT_15m | CMO_mom_28_-40_40&RSI_rev_14_30_70&MAx_DEMA_50_200 | 1.87 | 0.85 | 0.33 |
| SOLUSDT_1d | MAx_DEMA_10_30&MAx_TRIMA_13_48&CMF_50 | 2.39 | 1.37 | 0.71 |
| SOLUSDT_1d | MAx_TRIMA_13_48&HULL_20&MAx_DEMA_10_30 | 2.32 | 1.35 | 0.74 |
| SOLUSDT_1d | MAx_TRIMA_13_48&MAx_TRIMA_10_50&HULL_20 | 2.32 | 0.99 | 0.41 |
| SOLUSDT_1d | MAx_SMA_10_50&HULL_20&MAx_TRIMA_10_50 | 2.29 | 0.94 | 0.56 |
| SOLUSDT_1d | MAx_DEMA_10_30&HULL_20&WILLR_mom_14_-90_-10 | 2.28 | 1.02 | 0.86 |
| SOLUSDT_1d | HULL_20&MAx_SMA_10_50&MAx_DEMA_10_30 | 2.27 | 1.25 | 0.68 |
| SOLUSDT_1d | HULL_20&MAx_TRIMA_9_21&MAx_SMA_10_50 | 2.27 | 1.23 | 0.38 |
| SOLUSDT_1d | ROC_30&WILLR_mom_14_-90_-10&MAx_DEMA_10_30 | 2.19 | 1.21 | 0.47 |
| SOLUSDT_1d | MOM_30&MAx_DEMA_10_30&CMF_50 | 2.19 | 1.50 | 0.49 |
| SOLUSDT_4h | STOCH_rev_14&MAx_T3_10_30&MAx_SMA_20_100 | 2.29 | 1.77 | 0.37 |

⚠️ Even all-3-positive among millions of combos can be chance. **Confirm on a 4th window (the 6-month API) before any sizing.**

_Re-confirm any survivor on a 3rd window before sizing. This is underlying edge (Binance/HL), not Polymarket._
---

## VERDICT (2026-06-03) — 29 survivors / 4.8M strategies ≈ multiple-testing noise

**4,802,841 strategies** searched (45-indicator zoo + 2/3-way combos), 12 series, 8.8y. 29 passed
IS>null AND VAL>0.3 AND OOS>0.3. Honest read:

1. **29 / 4.8M is roughly chance.** With ~4.8M tries and a 3-period-positive filter, dozens of false
   positives are expected. The survivors' OOS Sharpes are **modest (0.36–1.10)** and the per-series null
   floors are 1.2–1.75 — the survivors barely clear them. This is precisely what **DSR / PBO** (ml4t/diagnostic,
   queued next session) exist to adjudicate; treat all 29 as UNCONFIRMED until run through DSR.
2. **The only mild pattern: survivors cluster on DAILY (1d) MA-trend combos** (BTC/ETH/SOL 1d: KAMA/TEMA/TRIMA
   crossovers + CMO/RSI momentum, OOS Sharpe 0.4–1.1). Daily trend-following is the one classic weak anomaly
   (trend/momentum premium) — *possibly* a hair of real signal, but it is **DAILY spot/perp, NOT intraday and
   NOT Polymarket-applicable** (poly is 5m/15m). Intraday survivors (15m/1h/4h) are sparse and weaker (OOS 0.37–0.81).
3. **No strong, intraday, poly-relevant edge.** Consistent with the whole session: crypto direction is efficient;
   the 45-indicator × 4.8M-combo sweep, like the GPU LSTM and kline→poly, confirms it rather than overturns it.

**Action next session:** run the 29 (esp. the BTC/ETH/SOL 1d trend cluster) through **DSR + PBO + CPCV**
(ml4t/diagnostic). If the daily-trend cluster survives DSR, it's a *separate* tradeable underlying strategy
(Binance/HL daily), not a poly signal. Nothing here changes the poly picture — the exit-scalp stays the edge.
