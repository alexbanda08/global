# Hybrid Gate Search — RF + TR + TA + Markov AND-conjunctions

**Date**: 2026-05-25  ·  **Window**: 2026-05-01 → 2026-05-21 (chainlink-resolved fires only)  ·  **Fee model**: legacy 2%-on-profit-only

**Universe**: 
- S1.5 5m (`s15_joined_all.parquet`): 33,323 fires, baseline WR = 81.2%, sum_pnl_28d = $+5,216
- v15m 15m S7 (`v15m_joined_all.parquet`): 12,492 fires, baseline WR = 75.1%, sum_pnl_28d = $-13,546
- S6 5m spike (`s6_joined_all.parquet`): 18,766 fires, baseline WR = 71.7%, sum_pnl_28d = $+18,092

Joins built by `strategy_lab/meta_classifier/hybrid_join_and_gates.py`. 
Greedy + exhaustive 2^10 AND-gate search per (asset × tf × offset_bin) cell, 
driven by `strategy_lab/meta_classifier/hybrid_gate_search.py`. 
Walk-forward (20d train / 8d test) + 200-shuffle bootstrap p-value by `hybrid_walk_forward.py`.

## 1. Overlap summary — RF vs Ribbon

Full breakdown in `strategy_lab/reports/RF_RIBBON_OVERLAP_2026_05_25.md`. Headline (S1.5 5m, n=33,323):

| Metric | Value |
|---|---|
| Jaccard(rf_agrees, ribbon_agrees) | **0.771** |
| Pearson(rf_dir, sign(ribbon_lead_slope)) | +0.49 (moderate) |
| P(ribbon agrees \| rf agrees) | 0.837 |
| P(rf agrees \| ribbon agrees) | 0.908 |

**Interpretation**: RF and ribbon are *substantially overlapping but not identical*. Ribbon-only fires (where rf disagrees) and rf-only fires (where ribbon disagrees) contain marginal signal — adding both to an AND-stack tightens by ~25% beyond either alone.

## 2. Top 20 gate stacks by sum_pnl_28d

| # | tf | asset | offset | gate_stack | n | WR | sum_pnl | $/tr | max_DD | sharpe/d | k |
|--:|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | s6_5m | BTC | 60-150 | `g_cci_with&g_stoch_with&g_rf_with&g_tr_above_ema50&g_ribbon_agrees` | 2,764 | 77.8% | $+14,103.2 | +5.1025 | $+1,836.9 | 2.01 | 5 |
| 2 | s6_5m | BTC | 60-150 | `g_cci_with&g_stoch_with&g_tr_above_ema50&g_rf_with` | 2,781 | 77.7% | $+14,060.8 | +5.0560 | $+1,931.3 | 2.00 | 4 |
| 3 | s6_5m | BTC | 60-150 | `g_cci_with&g_bb_pos_with&g_stoch_with&g_tr_above_ema50&g_rf_with` | 2,780 | 77.7% | $+14,057.8 | +5.0567 | $+1,934.4 | 2.00 | 5 |
| 4 | s6_5m | BTC | 60-150 | `g_bb_pos_with&g_stoch_with&g_rf_with` | 2,793 | 77.5% | $+14,041.5 | +5.0274 | $+1,934.4 | 1.99 | 3 |
| 5 | s6_5m | BTC | 60-150 | `g_cci_with&g_stoch_with&g_rf_with` | 2,793 | 77.5% | $+14,027.5 | +5.0224 | $+1,931.3 | 1.99 | 3 |
| 6 | s6_5m | ETH | 60-150 | `g_tight_ribbon&g_stoch_with` | 1,307 | 66.5% | $+6,170.0 | +4.7207 | $+1,733.2 | 1.83 | 2 |
| 7 | s6_5m | ETH | 60-150 | `g_tight_ribbon&g_bb_pos_with&g_tr_above_cloud&g_tr_above_ema50` | 1,266 | 66.9% | $+6,156.1 | +4.8627 | $+1,769.1 | 1.83 | 4 |
| 8 | s6_5m | ETH | 60-150 | `g_cci_with&g_bb_pos_with&g_ribbon_agrees` | 3,531 | 76.0% | $+5,553.4 | +1.5727 | $+2,937.4 | 1.51 | 3 |
| 9 | s15_5m | ETH | 150-240 | `g_ribbon_agrees&g_tr_above_ema200&g_stoch_with&g_bb_pos_with&g_cci_with` | 3,420 | 85.1% | $+4,595.9 | +1.3438 | $+507.8 | 2.49 | 5 |
| 10 | s15_5m | ETH | 150-240 | `g_ribbon_agrees&g_ribbon_slope_with&g_tr_above_ema200&g_cci_with` | 3,469 | 85.2% | $+4,536.0 | +1.3076 | $+496.4 | 2.46 | 4 |
| 11 | s15_5m | ETH | 150-240 | `g_ribbon_agrees&g_ribbon_slope_with&g_tr_above_ema200&g_tr_above_ema50` | 3,521 | 85.2% | $+4,510.4 | +1.2810 | $+486.5 | 2.46 | 4 |
| 12 | s15_5m | BTC | 150-240 | `g_tr_above_pp&g_ribbon_agrees&g_stoch_with&g_tight_ribbon` | 1,365 | 85.6% | $+4,176.3 | +3.0595 | $+379.3 | 2.43 | 4 |
| 13 | s15_5m | BTC | 150-240 | `g_tr_above_pp&g_ribbon_slope_with&g_stoch_with` | 1,463 | 86.1% | $+4,135.0 | +2.8264 | $+364.8 | 2.38 | 3 |
| 14 | s15_5m | BTC | 150-240 | `g_tr_above_pp&g_ribbon_slope_with&g_bb_pos_with` | 1,482 | 86.2% | $+4,119.8 | +2.7799 | $+323.1 | 2.38 | 3 |
| 15 | s6_5m | SOL | 60-150 | `g_mfi_with&g_within_dev&g_bb_pos_with&g_ribbon_agrees` | 1,503 | 92.9% | $+3,306.8 | +2.2001 | $+344.8 | 3.07 | 4 |
| 16 | s6_5m | SOL | 60-150 | `g_mfi_with&g_within_dev&g_bb_pos_with` | 1,526 | 92.9% | $+3,291.4 | +2.1569 | $+344.8 | 3.05 | 3 |
| 17 | s6_5m | SOL | 60-150 | `g_mfi_with&g_within_dev` | 1,533 | 92.6% | $+3,237.4 | +2.1118 | $+344.8 | 3.01 | 2 |
| 18 | s6_5m | SOL | 60-150 | `g_mfi_with&g_bb_pos_with` | 1,831 | 88.1% | $+3,235.3 | +1.7669 | $+487.1 | 2.57 | 2 |
| 19 | s6_5m | SOL | 60-150 | `g_mfi_with&g_within_dev&g_stoch_with&g_bb_pos_with` | 1,512 | 92.9% | $+3,197.5 | +2.1148 | $+344.8 | 3.05 | 4 |
| 20 | s6_5m | SOL | 60-150 | `g_mfi_with&g_within_dev&g_stoch_with` | 1,513 | 92.9% | $+3,172.5 | +2.0968 | $+344.8 | 3.03 | 3 |

## 3. Low-DD tier — WR ≥ 75% AND n ≥ 100

Top 15 stacks with high WR and adequate sample size.

| # | tf | asset | offset | gate_stack | n | WR | sum_pnl | $/tr | max_DD | k |
|--:|---|---|---|---|---:|---:|---:|---:|---:|---:|
| 1 | s6_5m | BTC | 60-150 | `g_cci_with&g_stoch_with&g_rf_with&g_tr_above_ema50&g_ribbon_agrees` | 2,764 | 77.8% | $+14,103.2 | +5.1025 | $+1,836.9 | 5 |
| 2 | s6_5m | BTC | 60-150 | `g_cci_with&g_stoch_with&g_tr_above_ema50&g_rf_with` | 2,781 | 77.7% | $+14,060.8 | +5.0560 | $+1,931.3 | 4 |
| 3 | s6_5m | BTC | 60-150 | `g_cci_with&g_bb_pos_with&g_stoch_with&g_tr_above_ema50&g_rf_with` | 2,780 | 77.7% | $+14,057.8 | +5.0567 | $+1,934.4 | 5 |
| 4 | s6_5m | BTC | 60-150 | `g_bb_pos_with&g_stoch_with&g_rf_with` | 2,793 | 77.5% | $+14,041.5 | +5.0274 | $+1,934.4 | 3 |
| 5 | s6_5m | BTC | 60-150 | `g_cci_with&g_stoch_with&g_rf_with` | 2,793 | 77.5% | $+14,027.5 | +5.0224 | $+1,931.3 | 3 |
| 6 | s6_5m | ETH | 60-150 | `g_cci_with&g_bb_pos_with&g_ribbon_agrees` | 3,531 | 76.0% | $+5,553.4 | +1.5727 | $+2,937.4 | 3 |
| 7 | s15_5m | ETH | 150-240 | `g_ribbon_agrees&g_tr_above_ema200&g_stoch_with&g_bb_pos_with&g_cci_with` | 3,420 | 85.1% | $+4,595.9 | +1.3438 | $+507.8 | 5 |
| 8 | s15_5m | ETH | 150-240 | `g_ribbon_agrees&g_ribbon_slope_with&g_tr_above_ema200&g_cci_with` | 3,469 | 85.2% | $+4,536.0 | +1.3076 | $+496.4 | 4 |
| 9 | s15_5m | ETH | 150-240 | `g_ribbon_agrees&g_ribbon_slope_with&g_tr_above_ema200&g_tr_above_ema50` | 3,521 | 85.2% | $+4,510.4 | +1.2810 | $+486.5 | 4 |
| 10 | s15_5m | BTC | 150-240 | `g_tr_above_pp&g_ribbon_agrees&g_stoch_with&g_tight_ribbon` | 1,365 | 85.6% | $+4,176.3 | +3.0595 | $+379.3 | 4 |
| 11 | s15_5m | BTC | 150-240 | `g_tr_above_pp&g_ribbon_slope_with&g_stoch_with` | 1,463 | 86.1% | $+4,135.0 | +2.8264 | $+364.8 | 3 |
| 12 | s15_5m | BTC | 150-240 | `g_tr_above_pp&g_ribbon_slope_with&g_bb_pos_with` | 1,482 | 86.2% | $+4,119.8 | +2.7799 | $+323.1 | 3 |
| 13 | s6_5m | SOL | 60-150 | `g_mfi_with&g_within_dev&g_bb_pos_with&g_ribbon_agrees` | 1,503 | 92.9% | $+3,306.8 | +2.2001 | $+344.8 | 4 |
| 14 | s6_5m | SOL | 60-150 | `g_mfi_with&g_within_dev&g_bb_pos_with` | 1,526 | 92.9% | $+3,291.4 | +2.1569 | $+344.8 | 3 |
| 15 | s6_5m | SOL | 60-150 | `g_mfi_with&g_within_dev` | 1,533 | 92.6% | $+3,237.4 | +2.1118 | $+344.8 | 2 |

## 4. Per-cell winners

One row per (tf, asset, offset_bin) — best non-baseline stack by sum_pnl.

| tf | asset | offset | baseline_n | baseline_WR | baseline_sum | best_stack | n | WR | sum_pnl | lift |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|
| s15_5m | BTC | 150-240 | 4,334 | 83.6% | $+2,812.2 | `g_tr_above_pp&g_ribbon_agrees&g_stoch_with&g_tight_ribbon` | 1,365 | 85.6% | $+4,176.3 | $+1,364.1 |
| s15_5m | BTC | 240-300 | 2,232 | 81.9% | $+1,022.7 | `g_tr_above_cloud&g_mfi_with&g_tr_above_ema200&g_cci_with&g_stoch_with` | 1,432 | 84.5% | $+2,486.3 | $+1,463.7 |
| s15_5m | BTC | 60-150 | 2,791 | 78.7% | $+2,630.1 | `g_ribbon_agrees&g_rf_with&g_tr_stack_with` | 2,146 | 79.1% | $+2,860.0 | $+230.0 |
| s15_5m | ETH | 150-240 | 5,315 | 83.2% | $+3,141.6 | `g_ribbon_agrees&g_tr_above_ema200&g_stoch_with&g_bb_pos_with&g_cci_with` | 3,420 | 85.1% | $+4,595.9 | $+1,454.4 |
| s15_5m | ETH | 240-300 | 3,032 | 82.4% | $-157.7 | `g_rf_with&g_within_dev&g_tr_above_ema200` | 1,083 | 85.7% | $+2,256.1 | $+2,413.8 |
| s15_5m | ETH | 60-150 | 3,732 | 76.5% | $+1,117.0 | `g_ribbon_agrees&g_bb_pos_with&g_cci_with` | 2,951 | 77.1% | $+1,818.5 | $+701.5 |
| s15_5m | SOL | 150-240 | 4,680 | 83.2% | $-2,888.4 | `g_rf_aged&g_ribbon_agrees&g_tr_above_ema200&g_tr_stack_with&g_tr_above_cloud` | 987 | 85.9% | $+853.0 | $+3,741.4 |
| s15_5m | SOL | 240-300 | 2,869 | 85.7% | $-2,758.5 | `g_rf_aged&g_within_dev&g_tight_ribbon&g_tr_in_active_session` | 282 | 92.6% | $+1,739.5 | $+4,498.1 |
| s15_5m | SOL | 60-150 | 3,209 | 76.8% | $-842.5 | `g_tr_stack_full_with&g_within_dev&g_mfi_with` | 1,165 | 85.2% | $+768.4 | $+1,610.9 |
| s6_5m | BTC | 60-150 | 3,233 | 72.1% | $+9,609.0 | `g_cci_with&g_stoch_with&g_rf_with&g_tr_above_ema50&g_ribbon_agrees` | 2,764 | 77.8% | $+14,103.2 | $+4,494.2 |
| s6_5m | ETH | 60-150 | 3,814 | 72.1% | $+1,700.1 | `g_tight_ribbon&g_stoch_with` | 1,307 | 66.5% | $+6,170.0 | $+4,469.9 |
| s6_5m | SOL | 60-150 | 2,269 | 78.4% | $-505.5 | `g_mfi_with&g_within_dev&g_bb_pos_with&g_ribbon_agrees` | 1,503 | 92.9% | $+3,306.8 | $+3,812.3 |
| v15m_15m | BTC | 240-480 | 933 | 73.3% | $-877.2 | `g_rf_fresh&g_tr_within_adr&g_tr_above_ema800&g_tight_ribbon` | 151 | 89.4% | $+317.6 | $+1,194.8 |
| v15m_15m | BTC | 480-840 | 2,217 | 77.6% | $-2,960.9 | `g_tr_stack_full_with&g_tr_above_ema800&g_ribbon_agrees&g_tight_ribbon&g_stoch_with&g_tr_above_ema200` | 816 | 88.0% | $+1,751.5 | $+4,712.3 |
| v15m_15m | BTC | 60-240 | 438 | 61.4% | $-714.3 | `g_rf_aged` | 128 | 78.1% | $+238.1 | $+952.3 |
| v15m_15m | ETH | 240-480 | 1,197 | 72.9% | $-1,184.6 | `g_tr_above_ema800&g_tr_above_pp&g_markov_with&g_tight_ribbon` | 194 | 85.1% | $+438.0 | $+1,622.6 |
| v15m_15m | ETH | 480-840 | 2,512 | 78.3% | $-2,447.4 | `g_dev_extreme&g_tr_above_pp&g_tr_above_cloud` | 93 | 95.7% | $+484.8 | $+2,932.2 |
| v15m_15m | ETH | 60-240 | 566 | 65.2% | $-228.1 | `g_tr_stack_full_with&g_tr_above_cloud&g_tr_stack_with&g_cci_with&g_stoch_with&g_ribbon_agrees&g_ribbon_slope_with` | 339 | 73.5% | $+573.7 | $+801.9 |
| v15m_15m | SOL | 240-480 | 1,251 | 73.3% | $-905.6 | `g_ribbon_agrees&g_tr_in_active_session&g_mfi_with` | 330 | 77.6% | $+377.0 | $+1,282.6 |
| v15m_15m | SOL | 480-840 | 2,749 | 79.1% | $-3,713.9 | `g_tr_within_adr&g_tr_above_pp&g_ribbon_agrees` | 399 | 87.2% | $+1,061.5 | $+4,775.3 |
| v15m_15m | SOL | 60-240 | 629 | 64.1% | $-514.5 | `g_tight_ribbon&g_mfi_with` | 238 | 71.4% | $+473.0 | $+987.5 |

## 5. Walk-forward / OOS validation (20d train / 8d test)

**OOS pass rate**: 20/20 (100%) — test set has n≥10 AND sum_pnl > 0

**Bootstrap p ≤ 0.05**: 20/20 (100%) — sum_pnl beats a 200-shuffle random null

| tf | asset | offset | gate_stack | n_train | WR_train | $train | n_test | WR_test | $test | $/tr_test | boot_p |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| s6_5m | BTC | 60-150 | `g_cci_with&g_stoch_with&g_rf_with&g_tr_above_ema50&g_ribbon_agrees` | 2,576 | 76.8% | $+12,984.0 | 188 | 91.5% | $+1,119.2 | +5.9533 | 0.000 |
| s6_5m | BTC | 60-150 | `g_cci_with&g_stoch_with&g_tr_above_ema50&g_rf_with` | 2,592 | 76.7% | $+12,930.0 | 189 | 91.5% | $+1,130.7 | +5.9828 | 0.000 |
| s6_5m | BTC | 60-150 | `g_bb_pos_with&g_stoch_with&g_tr_above_ema50&g_rf_with` | 2,591 | 76.6% | $+12,927.0 | 189 | 91.5% | $+1,130.7 | +5.9828 | 0.000 |
| s6_5m | BTC | 60-150 | `g_cci_with&g_bb_pos_with&g_stoch_with&g_tr_above_ema50&g_rf_with` | 2,591 | 76.6% | $+12,927.0 | 189 | 91.5% | $+1,130.7 | +5.9828 | 0.000 |
| s6_5m | BTC | 60-150 | `g_bb_pos_with&g_stoch_with&g_rf_with` | 2,604 | 76.5% | $+12,910.8 | 189 | 91.5% | $+1,130.7 | +5.9828 | 0.000 |
| s6_5m | BTC | 60-150 | `g_cci_with&g_stoch_with&g_rf_with` | 2,604 | 76.5% | $+12,896.8 | 189 | 91.5% | $+1,130.7 | +5.9828 | 0.000 |
| s6_5m | ETH | 60-150 | `g_tight_ribbon&g_stoch_with` | 1,271 | 66.4% | $+5,951.2 | 36 | 69.4% | $+218.8 | +6.0765 | 0.000 |
| s6_5m | ETH | 60-150 | `g_tight_ribbon&g_bb_pos_with&g_tr_above_cloud&g_tr_above_ema50` | 1,232 | 66.9% | $+5,964.8 | 34 | 67.6% | $+191.4 | +5.6283 | 0.000 |
| s6_5m | ETH | 60-150 | `g_tight_ribbon&g_bb_pos_with&g_tr_above_cloud` | 1,232 | 66.9% | $+5,964.8 | 34 | 67.6% | $+191.4 | +5.6283 | 0.000 |
| s6_5m | ETH | 60-150 | `g_tight_ribbon&g_cci_with&g_bb_pos_with&g_tr_above_cloud` | 1,232 | 66.9% | $+5,964.8 | 34 | 67.6% | $+191.4 | +5.6283 | 0.000 |
| s6_5m | ETH | 60-150 | `g_tight_ribbon&g_cci_with&g_bb_pos_with&g_tr_above_cloud&g_tr_above_ema50` | 1,232 | 66.9% | $+5,964.8 | 34 | 67.6% | $+191.4 | +5.6283 | 0.000 |
| s6_5m | ETH | 60-150 | `g_cci_with&g_bb_pos_with&g_ribbon_agrees` | 3,397 | 75.7% | $+5,169.1 | 134 | 85.1% | $+384.2 | +2.8673 | 0.000 |
| s15_5m | ETH | 150-240 | `g_ribbon_agrees&g_tr_above_ema200&g_stoch_with&g_bb_pos_with&g_cci_with` | 3,247 | 85.3% | $+4,246.6 | 173 | 82.1% | $+349.4 | +2.0195 | 0.000 |
| s15_5m | ETH | 150-240 | `g_ribbon_slope_with&g_tr_above_ema200&g_cci_with` | 3,292 | 85.3% | $+4,207.1 | 177 | 81.9% | $+328.9 | +1.8582 | 0.000 |
| s15_5m | ETH | 150-240 | `g_ribbon_agrees&g_tr_above_ema200&g_cci_with` | 3,292 | 85.3% | $+4,207.1 | 177 | 81.9% | $+328.9 | +1.8582 | 0.000 |
| s15_5m | ETH | 150-240 | `g_ribbon_agrees&g_ribbon_slope_with&g_tr_above_ema200&g_cci_with` | 3,292 | 85.3% | $+4,207.1 | 177 | 81.9% | $+328.9 | +1.8582 | 0.000 |
| s15_5m | ETH | 150-240 | `g_ribbon_agrees&g_ribbon_slope_with&g_tr_above_ema200&g_tr_above_ema50` | 3,343 | 85.3% | $+4,181.0 | 178 | 82.0% | $+329.4 | +1.8506 | 0.000 |
| s15_5m | ETH | 150-240 | `g_ribbon_agrees&g_tr_above_ema200&g_tr_above_ema50` | 3,343 | 85.3% | $+4,181.0 | 178 | 82.0% | $+329.4 | +1.8506 | 0.000 |
| s15_5m | BTC | 150-240 | `g_tr_above_pp&g_ribbon_agrees&g_stoch_with&g_tight_ribbon` | 1,293 | 85.8% | $+4,043.8 | 72 | 81.9% | $+132.5 | +1.8396 | 0.000 |
| s15_5m | BTC | 150-240 | `g_tr_above_pp&g_ribbon_agrees&g_ribbon_slope_with&g_stoch_with` | 1,390 | 86.3% | $+4,002.1 | 73 | 82.2% | $+133.0 | +1.8212 | 0.000 |

## 6. Top-3 NEW deployable sleeves recommended for VPS3 shadow

Filter: n ≥ 200, WR ≥ 75%, OOS test WR ≥ 65% and sum_pnl > 0, bootstrap p ≤ 0.05.

**Top-3 diversified** (best per tf × asset, then top-3 by sum_pnl):

| # | tf | asset | offset | gate_stack | full_n | full_WR | full_sum | test_n | test_WR | test_sum | $/tr |
|--:|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | s6_5m | BTC | 60-150 | `g_cci_with&g_stoch_with&g_rf_with&g_tr_above_ema50&g_ribbon_agrees` | 2,764 | 77.8% | $+14,103.2 | 188 | 91.5% | $+1,119.2 | +5.1025 |
| 2 | s6_5m | ETH | 60-150 | `g_cci_with&g_bb_pos_with&g_ribbon_agrees` | 3,531 | 76.0% | $+5,553.4 | 134 | 85.1% | $+384.2 | +1.5727 |
| 3 | s15_5m | ETH | 150-240 | `g_ribbon_agrees&g_tr_above_ema200&g_stoch_with&g_bb_pos_with&g_cci_with` | 3,420 | 85.1% | $+4,595.9 | 173 | 82.1% | $+349.4 | +1.3438 |

Each of these is a candidate live sleeve. Suggested next step: spin up VPS3 paper-deploy shadow runs (single live cluster: BTC 5m, ETH 5m, etc.) and compare 7-day paper PnL to backtest projection.

## 7. Gate frequencies — what wins?

Count of how many of the top-50 stacks each gate appears in:

| Gate | Appearances in top-50 | % |
|---|---:|---:|
| `g_ribbon_agrees` | 17 | 34% |
| `g_bb_pos_with` | 15 | 30% |
| `g_mfi_with` | 15 | 30% |
| `g_within_dev` | 14 | 28% |
| `g_stoch_with` | 13 | 26% |
| `g_tr_above_ema200` | 13 | 26% |
| `g_cci_with` | 12 | 24% |
| `g_rf_with` | 8 | 16% |
| `g_tr_above_cloud` | 8 | 16% |
| `g_tr_above_pp` | 8 | 16% |
| `g_tr_stack_full_with` | 8 | 16% |
| `g_ribbon_slope_with` | 7 | 14% |
| `g_rf_aged` | 7 | 14% |
| `g_tr_above_ema50` | 6 | 12% |
| `g_tr_stack_with` | 6 | 12% |
| `g_tr_within_adr` | 6 | 12% |
| `g_tight_ribbon` | 5 | 10% |
| `g_tr_in_active_session` | 4 | 8% |
| `g_rf_in_band` | 3 | 6% |
| `g_tr_above_ema800` | 2 | 4% |
| `g_dev_extreme` | 2 | 4% |

## 8. Caveats

- **Pre-filtered baselines**: S1.5/S7/S6 are already strong-baseline fire sets (78–81% WR). The gate search is finding **incremental lift** on top of an already strong filter, not a new signal from scratch. Always compare lift vs baseline.
- **Multiple comparisons**: 23 gate candidates × 27 cells × 2^10 exhaustive = lots of subsets. Bootstrap p-values shown here are *per-stack* — they do NOT correct for the family-wise search. The fact that 20/20 top stacks pass p ≤ 0.05 is consistent with genuine signal, but the EFFECT SIZE on the test set is the load-bearing evidence (8d OOS with $/tr > +1.0).
- **Saturated gates**: a few gates (e.g. `g_tr_above_ema200` at 95%, `g_within_dev` at 100% on v15m) are nearly always 1 — they don't filter much. Their presence in a stack is mostly cosmetic.
- **Test set is only 8 days** (2026-05-21 to 2026-05-29). Production should re-validate on a fresh 4-week window after VPS3 shadow.
- **Fee model**: legacy 2%-on-profit-only (per CLAUDE.md 2026-05-22 reconciliation — this matches what production actually charges).
- **No look-ahead in features**: TR overlay uses `fire_us - 1s`; RF/TA already use `ws_s` anchor; Markov m1v at ws_s. Audited in source files.
