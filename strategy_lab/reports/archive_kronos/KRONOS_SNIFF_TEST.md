# Kronos Phase 0 Sniff Test — BTCUSDT 4h

**Window**: 2025-10-01 -> 2026-03-31  
**Lookback**: 256 bars  **Pred len**: 20  
**Sample count**: 8  **Model**: `NeoQuasar/Kronos-small`

## Result

| Metric | Value |
|---|---:|
| n | 54 |
| pearson_corr | -0.1122 |
| spearman_corr | -0.0784 |
| direction_acc | 0.4815 |
| actual_pos_bias | 0.4444 |
| mean_abs_err_pct | 0.05 |
| passes_gate | False |

## Verdict

❌ **FAIL** — raw model has no usable edge on this universe. Either fine-tune Kronos-small on Binance 4h (Phase 3), try a different timeframe, or drop the idea.

## Per-window forecasts

See [`results/kronos/sniff_test_BTCUSDT_4h.csv`](../results/kronos/sniff_test_BTCUSDT_4h.csv).