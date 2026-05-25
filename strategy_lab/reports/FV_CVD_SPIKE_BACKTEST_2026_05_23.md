# Fair-value + CVD + spike backtest — 2026-05-23 02:58 UTC

Adds three features per momo fire from 1s binance klines (pulled from VPS3 `binance_klines_v2.period_id='1SEC'`, 28d window):

- **fair_up** = Φ(z) Black-Scholes UP-probability (mlmodelpoly port)
- **cvd_30s_slope** = (CVD@fire − CVD@fire−30s) / 30; CVD = cumsum(2·taker_buy − total_vol)
- **spike_5s_bps** = 10000·log(close@fire / close@fire−5s)

**Edge** = `fair_up − entry_vwap` for UP fires, `(1−fair_up) − entry_vwap` for DOWN.

Universe: 3,360 Baseline_v1+v2 fires with valid features.

## A. WR by edge bucket

| edge_tier   |    n |    wr |   avg_pnl |   sum_pnl | bucket_type   |
|:------------|-----:|------:|----------:|----------:|:--------------|
| <-5pp       | 1341 | 0.469 |    -2.06  | -2761.8   | A_edge        |
| -5..-2pp    |  142 | 0.437 |    -3.972 |  -563.968 | A_edge        |
| -2..0pp     |   84 | 0.536 |     1.158 |    97.306 | A_edge        |
| 0..2pp      |  121 | 0.43  |    -3.886 |  -470.234 | A_edge        |
| 2..5pp      |  123 | 0.455 |    -2.703 |  -332.513 | A_edge        |
| 5..10pp     |  222 | 0.495 |    -0.758 |  -168.217 | A_edge        |
| >10pp       | 1327 | 0.516 |     0.343 |   454.774 | A_edge        |

## B. WR by edge × CVD agreement

|                     |   n |    wr |   avg_pnl |
|:--------------------|----:|------:|----------:|
| ('<-5pp', False)    | 368 | 0.467 |    -2.116 |
| ('<-5pp', True)     | 973 | 0.47  |    -2.038 |
| ('-5..-2pp', False) |  41 | 0.488 |    -1.772 |
| ('-5..-2pp', True)  | 101 | 0.416 |    -4.865 |
| ('-2..0pp', False)  |  22 | 0.591 |     4.016 |
| ('-2..0pp', True)   |  62 | 0.516 |     0.144 |
| ('0..2pp', False)   |  34 | 0.412 |    -4.665 |
| ('0..2pp', True)    |  87 | 0.437 |    -3.582 |
| ('2..5pp', False)   |  35 | 0.4   |    -5.17  |
| ('2..5pp', True)    |  88 | 0.477 |    -1.722 |
| ('5..10pp', False)  |  59 | 0.475 |    -1.769 |
| ('5..10pp', True)   | 163 | 0.503 |    -0.392 |
| ('>10pp', False)    | 406 | 0.517 |     0.438 |
| ('>10pp', True)     | 921 | 0.516 |     0.301 |

## C. WR by edge × spike agreement

|                     |    n |    wr |   avg_pnl |
|:--------------------|-----:|------:|----------:|
| ('<-5pp', False)    | 1287 | 0.471 |    -1.969 |
| ('<-5pp', True)     |   54 | 0.426 |    -4.225 |
| ('-5..-2pp', False) |  139 | 0.446 |    -3.518 |
| ('-5..-2pp', True)  |    3 | 0     |   -25     |
| ('-2..0pp', False)  |   78 | 0.551 |     1.876 |
| ('-2..0pp', True)   |    6 | 0.333 |    -8.166 |
| ('0..2pp', False)   |  114 | 0.43  |    -3.907 |
| ('0..2pp', True)    |    7 | 0.429 |    -3.548 |
| ('2..5pp', False)   |  121 | 0.446 |    -3.124 |
| ('2..5pp', True)    |    2 | 1     |    22.762 |
| ('5..10pp', False)  |  213 | 0.479 |    -1.584 |
| ('5..10pp', True)   |    9 | 0.889 |    18.787 |
| ('>10pp', False)    | 1251 | 0.52  |     0.529 |
| ('>10pp', True)     |   76 | 0.447 |    -2.73  |

## D. Per-cell WR at edge >= 2pp

|                |   n |    wr |   avg_pnl |   sum_pnl |
|:---------------|----:|------:|----------:|----------:|
| ('BTC', '15m') | 142 | 0.606 |     4.863 |   690.597 |
| ('BTC', '5m')  | 650 | 0.494 |    -0.672 |  -436.622 |
| ('ETH', '15m') |  78 | 0.513 |     0.336 |    26.241 |
| ('ETH', '5m')  | 401 | 0.484 |    -1.254 |  -502.826 |
| ('SOL', '15m') |  59 | 0.525 |     0.523 |    30.849 |
| ('SOL', '5m')  | 342 | 0.523 |     0.426 |   145.804 |

## E. Triple stack: edge >= 2pp & cvd_agree & no-anti-spike

Overall:

|    n |    wr |   avg_pnl |   sum_pnl |
|-----:|------:|----------:|----------:|
| 1162 | 0.513 |     0.147 |   171.269 |

Per cell:

|                |   n |    wr |   avg_pnl |   sum_pnl |
|:---------------|----:|------:|----------:|----------:|
| ('BTC', '15m') |  98 | 0.643 |     6.728 |   659.345 |
| ('BTC', '5m')  | 447 | 0.494 |    -0.666 |  -297.903 |
| ('ETH', '15m') |  54 | 0.519 |     0.459 |    24.786 |
| ('ETH', '5m')  | 272 | 0.485 |    -1.189 |  -323.392 |
| ('SOL', '15m') |  43 | 0.581 |     3.052 |   131.224 |
| ('SOL', '5m')  | 248 | 0.512 |    -0.092 |   -22.791 |

_per-fire parquet: `data\v4\canonical\_results\fv_cvd_spike_overlay.parquet`_
_script: `strategy_lab/meta_classifier/fv_cvd_spike_backtest.py`_