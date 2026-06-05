# DSR + PBO of the Mega-Sweep 1d-Trend MA Cluster — DEAD (multiple-testing noise)

**Date:** 2026-06-04 · **Step:** HANDOFF_2026_06_04 §D-4
**Script:** `strategy_lab/autoresearch/dsr_pbo_1d_cluster_2026_06_04.py`
**One line:** The "mildly interesting" 1d-trend MA cluster from the 4.8M-combo VBT mega-sweep is
**multiple-testing noise**. 0/25 survivors per asset pass Deflated Sharpe at the real trial count
(~400k/series); PBO > 0.5 on all three assets (IS selection is *counterproductive* OOS). **Not a
standalone daily strategy — do not ml4t/backtest it.**

## Method
- Reconstructed the EXACT survivor positions by reusing `vbt_mega_sweep.gen_single` + the sweep's own
  combine semantics (`&`=3-way agree, `|and`/`|gate`/`|or`). Reconstruction validated: recomputed OOS
  annualized Sharpe matches the stored JSON value to 2 decimals for **75/75** survivors (25 × 3 assets).
- OOS window = sweep's `lr[cut2:]` (final 25%; 803 bars BTC/ETH, 530 SOL), fee 5bps/flip.
- **DSR:** `deflated_sharpe_ratio_from_statistics(observed_sharpe=periodic, n_samples=OOS_bars,
  n_trials=n_strat_series, variance_trials=var(periodic across cluster))`. n_trials = the per-series
  search count (≈400,231 / 400,220 / 400,203). Pooled 4.8M variant also computed.
- **PBO:** CSCV — 8 contiguous blocks, C(8,4)=70 IS/OOS combinations, per-strategy Sharpe on each
  side, `compute_pbo` over the reconstructed cluster (rank stability among survivors).

## Result
| series | OOS bars | n_strat | DSR survivors | PBO |
|---|---|---|---|---|
| BTCUSDT_1d | 803 | 400,231 | **0 / 25** | **0.557** |
| ETHUSDT_1d | 803 | 400,220 | **0 / 25** | **0.886** |
| SOLUSDT_1d | 530 | 400,203 | **0 / 25** | **0.700** |

- **DSR:** every survivor's deflated probability collapses to ~0 once the ~400k search is priced in.
  Best raw OOS annualized Sharpes (BTC ≤1.10, SOL ≤0.86) are far below the multiple-testing expected-max.
- **PBO > 0.5 everywhere:** even *within* the pre-filtered cluster, the in-sample-best ranks below the
  OOS median more often than not — the selection is overfit, not just unprofitable.

## Verdict
Consistent with the whole session: **selection/prediction is efficient at every scale.** 4.8M combos →
29 nominal survivors → 0 survive honest deflation. The 1d MA cluster joins the dead list
(387k scalp selectors, 415 GPU nets, GPU-LSTM, Kronos, microstructure direction). No standalone daily
strategy here; `ml4t/backtest` not warranted. The only real edge remains the EXECUTION exit-scalp.

## Files
- `strategy_lab/autoresearch/dsr_pbo_1d_cluster_2026_06_04.py`
- Inputs: `_data/vbt_mega_results.json`, `_data/binance_vision/{BTC,ETH,SOL}USDT_1d_full.parquet`
- Prior: `VBT_MEGA_SWEEP.md` (the sweep), `META_LABEL_SCALP_CPCV_2026_06_04.md` (§D-1 negative)
