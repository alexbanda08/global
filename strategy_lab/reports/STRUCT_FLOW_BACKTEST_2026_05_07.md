# Struct+Flow Backtest (TRIGGER dropped — option C)

**Date:** 2026-05-07
**Mode:** all assets
**Thresholds:** struct_min=0.3, flow_min=0.4

## Tier counts

```
{'SKIP': 1500, 'SILVER': 105}
```

## Per-cell SILVER vs baseline momo

| cell    |   n_baseline |   hit_baseline |   mean_baseline |   n_silver |   hit_silver |   mean_silver |   total_silver |   lift_pp |   p_value |
|:--------|-------------:|---------------:|----------------:|-----------:|-------------:|--------------:|---------------:|----------:|----------:|
| BTC_5m  |          337 |       0.910979 |        0.273056 |         40 |     0.825    |      -1.4708  |       -58.8322 |  -8.59792 |      0.58 |
| BTC_15m |          113 |       0.743363 |       -1.39344  |         15 |     0.533333 |      -8.6691  |      -130.037  | -21.0029  |    nan    |
| ETH_5m  |          291 |       0.955326 |        0.97477  |         12 |     0.75     |      -3.96431 |       -47.5717 | -20.5326  |    nan    |
| ETH_15m |          103 |       0.815534 |        0.32115  |         10 |     0.7      |      -3.02882 |       -30.2882 | -11.5534  |    nan    |
| SOL_5m  |          260 |       0.907692 |       -0.253    |          5 |     1        |       2.65409 |        13.2705 |   9.23077 |    nan    |
| SOL_15m |           94 |       0.776596 |       -0.797676 |          3 |     1        |       6.44875 |        19.3462 |  22.3404  |    nan    |

## Notes

- TRIGGER dropped: this isolates the STRUCT+FLOW agreement signal
- SKIP fires when either layer is missing or sign-misaligned with held side
- Sample size still bottleneck (n<80 per cell over Apr-May)