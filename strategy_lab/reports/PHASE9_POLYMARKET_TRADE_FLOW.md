# Phase 9 — Polymarket Trade Flow Imbalance

_Generated: 2026-05-05_

## Data

- Source: VPS2 `trades_v2` (18.88M rows, 13.9M BTC)

- Universe: 4673 BTC markets (3505 5m, 1168 15m)

- Markets with >=1 trade in first 2m: 3550 (76.0%)

- Markets with >=1 trade in first 5m: 3564 (76.3%)

- Median trades/market in 2m: 1030

- Median trades/market in 5m: 2981

- Median total USD/market 2m: $10469


## IC vs outcome_up — ALL


### IC table — all timeframes (active) (n=3550)

| Feature | n | IC (Spearman rho) | p-value |
|---|---|---|---|
| poly_tfi_2m | 3550 | +0.3414 *** | 1.27e-97 |
| poly_tfi_5m | 3550 | +0.6377 *** | 0.00e+00 |
| poly_trade_count_2m | 3550 | +0.0055  | 7.45e-01 |
| poly_trade_count_5m | 3550 | +0.0170  | 3.12e-01 |
| poly_avg_trade_size_2m | 3550 | +0.0082  | 6.27e-01 |

## IC by timeframe


### IC table — 5m markets (n=2663)

| Feature | n | IC (Spearman rho) | p-value |
|---|---|---|---|
| poly_tfi_2m | 2663 | +0.4131 *** | 2.86e-110 |
| poly_tfi_5m | 2663 | +0.7138 *** | 0.00e+00 |
| poly_trade_count_2m | 2663 | +0.0125  | 5.20e-01 |
| poly_trade_count_5m | 2663 | +0.0313  | 1.06e-01 |
| poly_avg_trade_size_2m | 2663 | +0.0171  | 3.79e-01 |

### IC table — 15m markets (n=887)

| Feature | n | IC (Spearman rho) | p-value |
|---|---|---|---|
| poly_tfi_2m | 887 | +0.1528 *** | 4.84e-06 |
| poly_tfi_5m | 887 | +0.3601 *** | 1.52e-28 |
| poly_trade_count_2m | 887 | +0.0025  | 9.40e-01 |
| poly_trade_count_5m | 887 | +0.0454  | 1.77e-01 |
| poly_avg_trade_size_2m | 887 | -0.0101  | 7.64e-01 |

## Threshold sweep — poly_tfi_2m


### Threshold sweep — poly_tfi_2m (all, n=3550)

| pct | threshold | n_fired | hit_rate | dir_split |
|---|---|---|---|---|
| top 50% | +0.1831 | 1775 | 72.2% | up=927/dn=848 |
| top 25% | +0.3070 | 888 | 76.5% | up=461/dn=427 |
| top 10% | +0.4207 | 355 | 77.7% | up=200/dn=155 |
| top 5% | +0.5066 | 178 | 77.0% | up=101/dn=77 |

### Threshold sweep — poly_tfi_2m (5m, n=2663)

| pct | threshold | n_fired | hit_rate | dir_split |
|---|---|---|---|---|
| top 50% | +0.1736 | 1332 | 76.8% | up=681/dn=651 |
| top 25% | +0.2927 | 666 | 82.9% | up=343/dn=323 |
| top 10% | +0.4035 | 267 | 85.0% | up=140/dn=127 |
| top 5% | +0.4778 | 134 | 84.3% | up=78/dn=56 |

### Threshold sweep — poly_tfi_2m (15m, n=887)

| pct | threshold | n_fired | hit_rate | dir_split |
|---|---|---|---|---|
| top 50% | +0.2197 | 444 | 60.4% | up=243/dn=201 |
| top 25% | +0.3540 | 222 | 62.6% | up=117/dn=105 |
| top 10% | +0.4825 | 89 | 67.4% | up=49/dn=40 |
| top 5% | +0.5646 | 45 | 73.3% | up=24/dn=21 |

## Threshold sweep — poly_tfi_5m (15m markets only)


### Threshold sweep — poly_tfi_5m (15m, n=889)

| pct | threshold | n_fired | hit_rate | dir_split |
|---|---|---|---|---|
| top 50% | +0.1984 | 445 | 75.7% | up=244/dn=201 |
| top 25% | +0.3324 | 223 | 83.4% | up=125/dn=98 |
| top 10% | +0.4698 | 89 | 88.8% | up=49/dn=40 |
| top 5% | +0.5384 | 45 | 88.9% | up=24/dn=21 |

### Per-direction (top 5% |poly_tfi_2m|, n=178)

| direction | n | hit_rate |
|---|---|---|
| predict UP | 101 | 78.2% |
| predict DOWN | 77 | 75.3% |

## Orthogonality vs Phase 7


### Cross-orthogonality vs Phase 7 (n=3535)

| Phase 9 feature | Phase 7 feature | Pearson r | Spearman rho |
|---|---|---|---|
| poly_tfi_2m | imb_t | -0.1270 | -0.1188 |
| poly_tfi_2m | imb_slope_2m | -0.1524 | -0.1502 |
| poly_tfi_5m | imb_t | -0.0936 | -0.0805 |
| poly_tfi_5m | imb_slope_2m | -0.1349 | -0.1258 |

### Top-5% gate overlap (n=3535, thr=p95)
- only Phase 9 fires: 160
- only Phase 7 fires: 160
- BOTH fire:           17
- Jaccard:             0.050 (1.0 = perfect overlap, 0 = orthogonal)


## Verdict

- **IC poly_tfi_2m**: +0.3414 (p=1.27e-97, n=3550)  — large, highly significant
- **IC poly_tfi_5m**: +0.6377 (p≈0)                  — but this CONSUMES the entire 5m window for 5m markets (lookahead-ish — only safe to use for 15m markets where 5m is strictly intra-window)
- **Top 5% |poly_tfi_2m| hit rate**: 77.0% on 178 markets (5m: 84.3%, 15m: 73.3%)
- **Top 10% |poly_tfi_2m| hit rate**: 77.7% on 355 markets — sweet spot for n
- **Orthogonality vs Phase 7**: |corr| < 0.16, Jaccard 0.05 — STRONGLY ORTHOGONAL
- **Orthogonality vs V3**: Jaccard 0.036 (V3∩P9, top-10% gate) — STRONGLY ORTHOGONAL

### Tri-signal union (V3 ∪ P7 ∪ P9)

From `combined_gate_v2.py`:

| Strategy             | n_bets | hit  | ROI    | pnl_total |
|----------------------|--------|------|--------|-----------|
| V3 alone             | 330    | 63.6% | +25.3% | $+41.70   |
| P7 alone             | 232    | 59.9% | +17.8% | $+20.68   |
| P9 alone             | 355    | 77.7% | +53.5% | $+94.95   |
| UNION V3 ∪ P7        | 534    | 62.2% | +22.3% | $+59.66   |
| UNION V3 ∪ P9        | 661    | 70.8% | +39.6% | $+130.89  |
| **UNION V3 ∪ P7 ∪ P9** | **840** | **68.1%** | **+34.2%** | **$+143.60** |

### Caveats / risks

1. **Self-prediction bias**. Polymarket trade flow in the first 2 minutes of a 5m market reflects whatever BTC has *already done*. The 84.3% hit rate may be partly a redundant readout of intra-window BTC return, not novel alpha. Validate by including BTC ret in a regression and seeing if poly_tfi_2m retains a coefficient.
2. **Execution timing**. Signal is computed at signal_time = window_start + 2min. Need a live ingestion path (WS subscription on `trades` channel) to match this in production.
3. **Slippage**. Top-decile TFI markets concentrate volume — entering at signal_time means you've ALREADY moved with the flow. Realized fills will be worse than the 0.50 mid assumption.

### Verdict: DEPLOY-WORTHY but VALIDATE LOOKAHEAD

Phase 9 is highly orthogonal to V3 and Phase 7. The tri-signal union improves bet count by +57% over V3 alone (330 → 840) and total PnL by +244% ($+41.70 → $+143.60) at 68.1% hit. **Action**: (1) regression-test for redundancy with BTC return, (2) build live `trades_v2` ingestion mirror on WS, (3) start shadow logging Phase 9 signals from now.
