# Range Filter [DW] 1s panel — 2026-05-25

Defaults: Type 1 / Close / qty=2.618 / Average Change / n=14 / smooth=true / sn=27

## Per-asset summary

| asset | bars | dir+1 % | dir-1 % | dir0 % | mean dwell (s) | median dwell (s) |
|---|---:|---:|---:|---:|---:|---:|
| BTC | 1,832,514 | 49.82 | 50.18 | 0.00 | 42.0 | 27.0 |
| ETH | 1,832,512 | 51.22 | 48.78 | 0.00 | 32.1 | 22.0 |
| SOL | 1,832,505 | 51.62 | 48.38 | 0.00 | 20.5 | 12.0 |

## rf_band_pos distribution (per asset)

| asset | p5 | p25 | p50 | p75 | p95 | <0 % | >1 % |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC | 0.00 | 0.00 | 0.50 | 1.00 | 1.00 | 0.00 | 0.00 |
| ETH | 0.00 | 0.02 | 0.55 | 0.99 | 1.00 | 0.00 | 0.00 |
| SOL | 0.00 | 0.05 | 0.57 | 0.98 | 1.00 | 0.00 | 0.00 |

## Verification — first 100 BTC bars (recompute)

- max |rf_close ref vs prod| on 100 BTC bars = 0.000000e+00
- max |rf_r     ref vs prod| on 100 BTC bars = 0.000000e+00
- sample (last bar, idx 99): close=76418.99  rf=76419.1013  r=2.4846

## Fire-time rf_dir agreement (vs bet direction)

| file | rows | rf cov % | dir col | n w/dir | agree % |
|---|---:|---:|---|---:|---:|
| s15_with_rf.parquet | 33323 | 99.91 | direction | 33294 | 79.23 |
| s15_with_ta_markov_rf.parquet | 33323 | 99.91 | direction | 33294 | 79.23 |
| s6_with_rf.parquet | 11336 | 100.00 | direction | 11336 | 92.65 |
| v15m_with_ta_markov_rf.parquet | 12492 | 86.68 | direction | 10828 | 66.79 |
