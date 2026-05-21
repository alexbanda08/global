# Momo v1 + v2 — canonical (chainlink-only) backtest
_Generated: 2026-05-10_

## What this is
Production-faithful backtest of the two shadow-mode strategies, against the **canonical chainlink-only** dataset (no `binance-klines-1m` contamination).

## Strategy spec

| | momo v1 (`t_plus_120`) | momo v2 (`t_plus_60`) |
|---|---|---|
| ret anchor | `log(close@(ws+120) / close@ws)` | `log(close@(ws+60) / close@(ws-60))` |
| Fire offset | ws + 120s | ws + 60s |
| L25 entry book | snapshot at ws+120 | snapshot at ws+60 |

Common: q90 |ret_2m| over rolling 14d, signal = sign(ret_2m), $25 L25 ASK walk, spread filter per asset, 2% fee on profit only, HOLD policy.

## Headline (across BTC/ETH/SOL × 5m/15m, HOLD)

| variant   |    n |   hit_pct |   pnl_total |   pnl_mean |   avg_vwap |   avg_dt_book_us |
|:----------|-----:|----------:|------------:|-----------:|-----------:|-----------------:|
| v1        | 1736 |     85.48 |     -894.36 |    -0.5152 |   0.868019 |           703245 |
| v2        | 1610 |     67.52 |    -2655.74 |    -1.6495 |   0.70887  |           668220 |

## Per-cell

| variant   | asset   | tf   |   n |   hit_pct |   pnl_total |   pnl_mean |   avg_vwap |
|:----------|:--------|:-----|----:|----------:|------------:|-----------:|-----------:|
| v1        | BTC     | 15m  | 163 |     74.85 |     -139.52 |    -0.8559 |   0.763764 |
| v1        | BTC     | 5m   | 485 |     86.39 |     -301.17 |    -0.621  |   0.881768 |
| v1        | ETH     | 15m  | 133 |     75.94 |     -127.65 |    -0.9598 |   0.789868 |
| v1        | ETH     | 5m   | 426 |     90.14 |      -60.35 |    -0.1417 |   0.903511 |
| v1        | SOL     | 15m  | 149 |     73.83 |     -250.36 |    -1.6803 |   0.785853 |
| v1        | SOL     | 5m   | 380 |     91.58 |      -15.31 |    -0.0403 |   0.914976 |
| v2        | BTC     | 15m  | 140 |     64.29 |      -94.26 |    -0.6733 |   0.653658 |
| v2        | BTC     | 5m   | 440 |     68.18 |     -411.08 |    -0.9343 |   0.696916 |
| v2        | ETH     | 15m  | 139 |     61.15 |     -379.8  |    -2.7323 |   0.653384 |
| v2        | ETH     | 5m   | 433 |     69.75 |     -795.56 |    -1.8373 |   0.734948 |
| v2        | SOL     | 15m  | 102 |     57.84 |     -400.2  |    -3.9235 |   0.685026 |
| v2        | SOL     | 5m   | 356 |     70.51 |     -574.85 |    -1.6147 |   0.742137 |

## Comparison vs production strategy_lab spec
Production momo_v2 spec table (from `backend/app/strategies/polymarket/momo_v2.py` docstring, pre-canonical-fix):

| Anchor | n | mean | hit% | vwap |
|---|---:|---:|---:|---:|
| ws+120 (v1) | 966 | +$9.98 | 87.2 | 0.676 |
| ws+60 (v2)  | 935 | +$13.67 | 87.5 | 0.612 |

Differences from prior numbers indicate the chainlink-only filter dropped the tautological-correlation contamination. If both v1 and v2 are below break-even on canonical, the previous backtest spec was inflated by the `binance-klines-1m` bug (now confirmed responsible for ~$14k of the prior baseline PnL).

## Files
- `data/v4/canonical/_results/momo_v1v2_per_trade_all.csv` — full per-trade
- `data/v4/canonical/_results/momo_v1v2_per_trade_{btc,eth,sol}.csv` — per asset
- `data/v4/canonical/_results/momo_v1v2_summary.csv` — headline
- `data/v4/canonical/_results/momo_v1v2_per_cell.csv` — per-cell