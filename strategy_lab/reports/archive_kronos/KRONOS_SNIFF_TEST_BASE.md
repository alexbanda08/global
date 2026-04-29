# Kronos Phase 0 Sniff Test (base) — BTCUSDT 4h

**Window**: 2025-10-01 -> 2026-03-31  **Lookback**: 256 bars  **Pred len**: 20  
**Sample count**: 16  **Model**: NeoQuasar/Kronos-base  **Device**: cuda:0

## Result

| Metric | Value |
|---|---:|
| n | 54 |
| pearson_corr | -0.0665 |
| spearman_corr | 0.0003 |
| direction_acc | 0.5 |
| actual_pos_bias | 0.4444 |
| mean_abs_err_pct | 0.0503 |
| passes_gate | False |

## Verdict

FAIL — raw Kronos-base has no usable edge. Pearson -0.0665, direction_acc 0.5 vs positive-bias 0.4444.

See [results/kronos/sniff_test_BTCUSDT_4h_base.csv](../results/kronos/sniff_test_BTCUSDT_4h_base.csv).