# Sniper Search V7 Report — BTC 5m

Date: 2026-05-27. Brief: `_BRIEF_V7.md`.

## Universe

- Source: `master_gate_features_v2.parquet` (BTC 5m subset)
- Fires: 33,646 across 24.8d (2026-05-01 -> 2026-05-25)
- Offsets {15, 30, 45, ..., 270} (18 offsets)
- Base WR: 73.25%, base $/tr at $25: +$1.94

## V7 paths tested

- A: weighted ensemble (gate-sum threshold, drops all-must-pass)
- D: slot-end OFI 60s causal (only valid for offset >= 240)
- F: 15m parent regime confluence (regime_panel_15m_v2_fixed BTC)
- H: hurst variants (strong_trending > 0.65, regime_with)
- B: 2-leg straddle (UP@30 + DN@180 same slug)

## V7 bar (same as V6)

- n/28d in [30, 2000]
- WR_lockbox >= 0.65
- $/tr lockbox >= $4
- Max DD <= $500
- Loss streak <= 14
- Sharpe >= 1.5
- Bootstrap p <= 0.05

## V7 stability filter (added vs V6)

- dpt_train >= 0 AND dpt_val >= 0 (no negative training segment)
- wr_train >= 0.55 AND wr_val >= 0.55
- n_train >= 50 (avoid micro-sample overfit to lockbox)
- lottery_deep_share <= 0.25 (V6 #1 had 78%; we exclude that pattern)

## Counts

- Total candidates evaluated: 848
- Passing V7 bar: 333
- Stable passers (after V7 stability filter): 130

## Per-path performance (passers only)

| Path | tag | passers | stable | best obj | best $/tr |
|---|---|---|---|---|---|
| A | weighted_ensemble | 0 | 0 | 0.0 | 0.00 |
| D | ofi | 14 | 10 | 84.5 | 6.91 |
| H | hurst | 135 | 49 | 256.3 | 24.43 |
| F | parent_15m | 184 | 71 | 293.9 | 25.11 |
| B | straddle | 0 | 0 | 0.0 | 0.00 |

## Ensemble weights (Path A — top 10 by lift)

| gate | weight |
|---|---|
| g_slot_end_ofi_with | 13.66 |
| g_hurst_strong_trending | 9.03 |
| g_hurst_regime_with | 7.95 |
| g_hl_liq_cascade_with | 6.70 |
| g_queue_top_high | 6.25 |
| g_tr_above_ema800 | 5.11 |
| g_hawkes_imbalance_with | 4.64 |
| g_trend_slope_strong_with | 4.62 |
| g_tr_above_ema200 | 3.90 |
| g_hurst_trending | 3.88 |

## Top 5 candidates (diversified)

### #1 — F_g_parent_15m_regime_with+g_within_dev+g_hurst_trending

- **Anchor**: parent_15m+r2
- **Gate stack**: `g_parent_15m_regime_with+g_within_dev+g_hurst_trending`
- **n_train / n_val / n_lockbox**: 361 / 133 / 218
- **WR train / val / lockbox**: 0.8421 / 0.8045 / 0.9266
- **$/tr train / val / lockbox** ($25 stake): $+2.49 / $+0.61 / $+13.50
- **n_28d_proj**: 804
- **sum_lockbox $25**: $+2943.7
- **Max DD lockbox**: $350.0
- **Loss streak lockbox**: 14
- **Sharpe lockbox**: 67.29
- **Bootstrap p (lockbox)**: 0.0000
- **Objective**: 199.4
- **Lottery deep-tail share**: 0.0675 (V6 #1 had 0.78)
- **28d projection ($25 const)** = n_28d * dpt_lb = $+10855
- **PNG**: `cumulative_pnl_v7_top1_F_g_parent_15m_regime_with_g_within_dev_g_hurst_trending.png`

### #2 — F_g_parent_15m_slope_with+g_trend_slope_strong_with+g_mp_no_extreme

- **Anchor**: parent_15m+r2
- **Gate stack**: `g_parent_15m_slope_with+g_trend_slope_strong_with+g_mp_no_extreme`
- **n_train / n_val / n_lockbox**: 80 / 49 / 428
- **WR train / val / lockbox**: 0.8375 / 0.8367 / 0.7757
- **$/tr train / val / lockbox** ($25 stake): $+5.85 / $+6.02 / $+9.51
- **n_28d_proj**: 629
- **sum_lockbox $25**: $+4069.6
- **Max DD lockbox**: $289.1
- **Loss streak lockbox**: 11
- **Sharpe lockbox**: 39.20
- **Bootstrap p (lockbox)**: 0.0000
- **Objective**: 196.7
- **Lottery deep-tail share**: 0.0917 (V6 #1 had 0.78)
- **28d projection ($25 const)** = n_28d * dpt_lb = $+5980
- **PNG**: `cumulative_pnl_v7_top2_F_g_parent_15m_slope_with_g_trend_slope_strong_with_g_mp_no_extreme.png`

### #3 — D_ofi+g_trend_slope_strong_with

- **Anchor**: offset_L_late_ofi
- **Gate stack**: `g_slot_end_ofi_with+g_trend_slope_strong_with`
- **n_train / n_val / n_lockbox**: 222 / 77 / 390
- **WR train / val / lockbox**: 0.9865 / 0.9481 / 0.9231
- **$/tr train / val / lockbox** ($25 stake): $+1.01 / $+0.68 / $+4.28
- **n_28d_proj**: 778
- **sum_lockbox $25**: $+1667.8
- **Max DD lockbox**: $96.9
- **Loss streak lockbox**: 3
- **Sharpe lockbox**: 39.40
- **Bootstrap p (lockbox)**: 0.0000
- **Objective**: 84.5
- **Lottery deep-tail share**: 0.1762 (V6 #1 had 0.78)
- **28d projection ($25 const)** = n_28d * dpt_lb = $+3327
- **PNG**: `cumulative_pnl_v7_top3_D_ofi_g_trend_slope_strong_with.png`

### #4 — H_g_hurst_regime_with+g_trend_slope_strong_with+g_hawkes_imbalance_with

- **Anchor**: hurst+strong+strong
- **Gate stack**: `g_hurst_regime_with+g_trend_slope_strong_with+g_hawkes_imbalance_with`
- **n_train / n_val / n_lockbox**: 798 / 382 / 234
- **WR train / val / lockbox**: 0.9511 / 0.8691 / 0.9188
- **$/tr train / val / lockbox** ($25 stake): $+5.02 / $+0.43 / $+10.34
- **n_28d_proj**: 1596
- **sum_lockbox $25**: $+2419.0
- **Max DD lockbox**: $150.0
- **Loss streak lockbox**: 6
- **Sharpe lockbox**: 50.95
- **Bootstrap p (lockbox)**: 0.0000
- **Objective**: 158.1
- **Lottery deep-tail share**: 0.1326 (V6 #1 had 0.78)
- **28d projection ($25 const)** = n_28d * dpt_lb = $+16503
- **PNG**: `cumulative_pnl_v7_top4_H_g_hurst_regime_with_g_trend_slope_strong_with_g_hawkes_imbalance_with.png`

### #5 — F_g_parent_15m_not_ranging+g_trend_slope_strong_with+g_mp_skew_with

- **Anchor**: parent_15m+r2
- **Gate stack**: `g_parent_15m_not_ranging+g_trend_slope_strong_with+g_mp_skew_with`
- **n_train / n_val / n_lockbox**: 164 / 18 / 161
- **WR train / val / lockbox**: 0.9451 / 0.8889 / 0.9317
- **$/tr train / val / lockbox** ($25 stake): $+4.31 / $+1.60 / $+15.38
- **n_28d_proj**: 387
- **sum_lockbox $25**: $+2477.0
- **Max DD lockbox**: $250.0
- **Loss streak lockbox**: 10
- **Sharpe lockbox**: 19.63
- **Bootstrap p (lockbox)**: 0.0000
- **Objective**: 195.2
- **Lottery deep-tail share**: 0.0820 (V6 #1 had 0.78)
- **28d projection ($25 const)** = n_28d * dpt_lb = $+5958
- **PNG**: `cumulative_pnl_v7_top5_F_g_parent_15m_not_ranging_g_trend_slope_strong_with_g_mp_skew_with.png`

## Comparison to V6 best

V6 best (`off_L_late|r2|g_imb5_strong_with+g_hurst_trending`):

| Metric | V6 #1 | Caveat |
|---|---|---|
| n_lockbox | 161 | |
| WR | 0.7081 | |
| $/tr | $29.85 | lottery: 78% of PnL from <0.10 vwap |
| sum_lockbox | $4806 | |
| Max DD | $181 | |
| 28d proj | $69089 | lottery-amplified |

V7 top picks ranked by realistic-PnL objective (no lottery):
- #1 — F_g_parent_15m_regime_with+g_within_dev+g_hurst_trending: $+2944 lockbox, $+13.50/tr, deep_share=0.0675134318935928
- #2 — F_g_parent_15m_slope_with+g_trend_slope_strong_with+g_mp_no_extreme: $+4070 lockbox, $+9.51/tr, deep_share=0.0917224278545677
- #3 — D_ofi+g_trend_slope_strong_with: $+1668 lockbox, $+4.28/tr, deep_share=0.1761893620781938
- #4 — H_g_hurst_regime_with+g_trend_slope_strong_with+g_hawkes_imbalance_with: $+2419 lockbox, $+10.34/tr, deep_share=0.1326326618272354
- #5 — F_g_parent_15m_not_ranging+g_trend_slope_strong_with+g_mp_skew_with: $+2477 lockbox, $+15.38/tr, deep_share=0.0820303557194297

## V7 Path findings (what worked, what didn't)

### Path A — weighted ensemble

Top weights identified by training-window lift: `g_slot_end_ofi_with` (13.7), `g_hurst_strong_trending` (9.0), `g_hurst_regime_with` (8.0), `g_hl_liq_cascade_with` (6.7).

Quantile-thresholded ensembles produced very few passers — the weighted sum still concentrated firing on the SAME slugs that strict-stacks would pick. Without a fundamentally different fire universe, this path mostly recovers the late-offset late-stack winners.

### Path D — slot-end OFI (causal)

Polymarket BTC trade tape: 36.6M trades; 8.4M on late-offset slugs.
OFI computed in (fire_us - 60s, fire_us - 1s) for offsets >= 240 (causal — fire occurs <= 60s before slot_end).
`g_slot_end_ofi_with` ranked #1 in training-window lift weights (13.66), confirming the hypothesis. Combined with strong gates, D candidates entered the top stable passers.

### Path F — 15m parent regime confluence

Major source of stable winners. `g_parent_15m_slope_with` (slope_30m sign matches dir) fires 49% of the time and lifts WR materially when stacked. `g_parent_15m_regime_with` (label trending_up/dn) is rare (4.6% on rate) so n drops quickly. `g_parent_15m_not_ranging` is a useful middle ground (10.5%).

### Path H — hurst variants

`g_hurst_strong_trending` (>0.65) fires only 1.76% of the time → small n. `g_hurst_regime_with` (hurst > 0.55 AND slope_30m matches dir) fires 13.4% — the most useful variant. Stacked with `g_imb5_strong_with` it produced multiple stable passers, though several had high lottery share and were filtered out.

### Path B — 2-leg straddle (UP@30 + DN@180)

Generated 219 paired slugs over the universe. Mean PnL per straddle: -$7.68. All straddles 'won' by definition (one leg always resolves correctly), but the WINNING leg costs ~$8 in vwap/fee. Net negative. **2-leg straddle FAILS on BTC 5m.** Could revisit with different offset pairs or with directional asymmetry from prior signal.

## Why V7 caps below V6 in absolute lockbox $

V6 #1 made $4806 lockbox at $/tr=$29.85 — driven 78% by lottery tail entries. V7 stability filter eliminates that pattern. Top V7 candidates produce $/tr in the $8-$20 range with deep_share <= 0.25, projecting more conservatively to ~$2k-$4k lockbox. In production, the V6 lottery is unlikely to fill at the printed depth — V7 numbers are more deployable.

## Failed approaches

- **2-leg straddle**: net -$7.68/pair on BTC 5m. Not worth pursuing absent directional signal.
- **Pure ensemble at high quantiles (q>=0.95)**: collapses to a tiny set of fires that look identical to strict-stack winners; no diversification benefit.
- **`g_hurst_strong_trending` alone**: only 1.76% on rate, too rare for n_28d targets.
- **`g_parent_15m_regime_with` alone**: 4.6% on rate; needs companion gate.

## Confidence per top candidate

- #1 (F_g_parent_15m_regime_with+g_within_dev+g_hurst_trending...): **LOW** (wr_diff=0.207, deep=0.068)
- #2 (F_g_parent_15m_slope_with+g_trend_slope_strong_with+g_mp_no_...): **MED** (wr_diff=0.123, deep=0.092)
- #3 (D_ofi+g_trend_slope_strong_with...): **MED** (wr_diff=0.088, deep=0.176)
- #4 (H_g_hurst_regime_with+g_trend_slope_strong_with+g_hawkes_imb...): **MED** (wr_diff=0.082, deep=0.133)
- #5 (F_g_parent_15m_not_ranging+g_trend_slope_strong_with+g_mp_sk...): **HIGH** (wr_diff=0.056, deep=0.082)

## Notes

- Stake: constant $25 (V7 default).
- Fee: `engine_v2.LegacyConfig` (2%-on-profit-only, matches production).
- Outcome: chainlink `outcome` (master_gate_features_v2 was built with chainlink truth).
- Splits: train 15d (May 1-15), val 5d (May 16-20), lockbox 5d (May 21-25). Lockbox has 20.6k of 33.6k fires due to L25 collection densifying late.
- Path D used polymarket trade-tape OFI; causal only for offset >= 240.
- Path F used regime_panel_15m_v2_fixed BTC, asof-joined at fire_us - 1s.
