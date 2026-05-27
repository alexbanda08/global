# Wave 2 + 3 Master Table — HL Strategy Research

**Total cells tested**: 790

**Family summary**:

| source   | n_cells   | max_sharpe   | median_sharpe   | n_passing_3plus_gates   |
|----------|-----------|--------------|-----------------|-------------------------|

## Top-30 ranked (rank_score = sharpe + 0.5 × gate_ratio − size_penalty)

| # | Source | Strategy | Asset | TF | n | WR | $/tr | Sharpe | p | perm-p | Gates | Notes |
|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|---|---|
| 1 | nan | SOL_4h_bos_AND_liq_hold5 | SOL | 4h | 2.0 | 1.000 | 7.22 | 53.05 | 0.5000 | — | G2 |  |
| 2 | nan | SOL_1m_liq_long_1000k_60m_reversion | SOL | 1m | 5.0 | 1.000 | 5.64 | 43.23 | 0.0625 | — | G2 | liq_long_>=$1000k_60m_reversio |
| 3 | nan | SOL_1m_liq_long_1000k_30m_reversion | SOL | 1m | 5.0 | 1.000 | 7.73 | 30.85 | 0.0625 | — | G2 | liq_long_>=$1000k_30m_reversio |
| 4 | nan | SOL_1m_liq_long_500k_30m_reversion | SOL | 1m | 6.0 | 1.000 | 9.40 | 28.64 | 0.0312 | 0.4400 | G1,G2 | liq_long_>=$500k_30m_reversion |
| 5 | nan | SOL_1m_liq_long_500k_60m_reversion | SOL | 1m | 6.0 | 1.000 | 7.37 | 27.23 | 0.0312 | 0.4000 | G1,G2 | liq_long_>=$500k_60m_reversion |
| 6 | nan | ETH_4h_bos_AND_liq_hold5 | ETH | 4h | 2.0 | 1.000 | 1.96 | 23.56 | 0.5000 | — | G2 |  |
| 7 | nan | N5.2_sweep_nan_to_SOL | SOL | nan | 3.0 | 1.000 | 6.84 | 22.08 | 0.1376 | — | G_pos_sharpe,G_pos_pnl | UP/1.0 |
| 8 | nan | BTC_1m_liq_long_100k_60m_reversion | BTC | 1m | 8.0 | 0.875 | 4.20 | 21.70 | 0.0703 | — | G2 | liq_long_>=$100k_60m_reversion |
| 9 | nan | N5.2_sweep_nan_to_ETH | ETH | nan | 7.0 | 0.857 | 4.79 | 20.38 | 0.0146 | — | G_pos_sharpe,G_pos_pnl,G1 | UP/0.5 |
| 10 | nan | SOL_1m_liq_long_100k_60m_reversion | SOL | 1m | 8.0 | 1.000 | 5.29 | 18.02 | 0.0078 | 0.5700 | G1,G2 | liq_long_>=$100k_60m_reversion |
| 11 | nan | SOL_1m_liq_long_250k_60m_reversion | SOL | 1m | 7.0 | 1.000 | 5.51 | 17.68 | 0.0156 | 0.6200 | G1,G2 | liq_long_>=$250k_60m_reversion |
| 12 | nan | BTC_1m_liq_long_500k_60m_reversion | BTC | 1m | 5.0 | 0.800 | 3.63 | 17.04 | 0.3750 | — | G2 | liq_long_>=$500k_60m_reversion |
| 13 | nan | BTC_1m_liq_long_250k_60m_reversion | BTC | 1m | 6.0 | 0.833 | 3.33 | 16.73 | 0.2188 | — | G2 | liq_long_>=$250k_60m_reversion |
| 14 | nan | N5.2_sweep_nan_to_SOL | SOL | nan | 3.0 | 0.667 | 2.36 | 16.41 | 0.2153 | — | G_pos_sharpe,G_pos_pnl | DOWN/1.0 |
| 15 | nan | SOL_1m_liq_long_250k_30m_reversion | SOL | 1m | 7.0 | 0.857 | 6.86 | 16.37 | 0.1250 | — | G2 | liq_long_>=$250k_30m_reversion |
| 16 | nan | SOL_1m_liq_long_100k_30m_reversion | SOL | 1m | 8.0 | 0.875 | 6.48 | 16.33 | 0.0703 | — | G2 | liq_long_>=$100k_30m_reversion |
| 17 | nan | ETH_1m_cascade_60m_reversion_filt_ranging | ETH | 1m | 13.0 | 0.846 | 10.21 | 15.29 | 0.0225 | 0.0300 | G1,G2,G4 | base=ETH_1m_cascade_60m_revers |
| 18 | nan | ETH_1m_cascade_60m_reversion_filt_markov_contra | ETH | 1m | 13.0 | 0.846 | 10.21 | 15.29 | 0.0225 | 0.0300 | G1,G2,G4 | base=ETH_1m_cascade_60m_revers |
| 19 | nan | N5.2_sweep_nan_to_SOL | SOL | nan | 7.0 | 0.714 | 1.86 | 14.11 | 0.0569 | — | G_pos_sharpe,G_pos_pnl | DOWN/0.5 |
| 20 | nan | ETH_1m_cascade_60m_reversion_filt_ldn_ny | ETH | 1m | 13.0 | 0.769 | 9.63 | 13.88 | 0.0923 | — | G2 | base=ETH_1m_cascade_60m_revers |
| 21 | nan | N5.2_sweep_nan_to_ETH | ETH | nan | 7.0 | 0.857 | 6.50 | 13.75 | 0.0618 | — | G_pos_sharpe,G_pos_pnl | UP/0.5 |
| 22 | nan | BTC_1m_liq_long_100k_30m_reversion | BTC | 1m | 8.0 | 0.750 | 3.47 | 13.82 | 0.2891 | — | G2 | liq_long_>=$100k_30m_reversion |
| 23 | nan | ETH_1m_cascade_60m_reversion | ETH | 1m | 15.0 | 0.800 | 8.77 | 13.21 | 0.0352 | 0.0500 | G1,G2 | cascade_5+_60s_60m_reversion |
| 24 | nan | N5.2_sweep_nan_to_ETH | ETH | nan | 7.0 | 0.714 | 3.31 | 11.52 | 0.1034 | — | G_pos_sharpe,G_pos_pnl | UP/0.5 |
| 25 | nan | SOL_4h_sms_markov_sized_hold3 | SOL | 4h | 31.0 | 0.806 | 5.51 | 10.14 | 0.0009 | — | G1,G2,G6 |  |
| 26 | nan | SOL_1h_sms_regime_trending_hold3 | SOL | 1h | 4.0 | 0.750 | 1.72 | 11.26 | 0.6250 | — | G2 |  |
| 27 | nan | N5.2_sweep_nan_to_SOL | SOL | nan | 3.0 | 0.667 | 9.28 | 10.91 | 0.3561 | — | G_pos_sharpe,G_pos_pnl | UP/1.0 |
| 28 | nan | ETH_1m_liq_long_250k_60m_reversion | ETH | 1m | 9.0 | 0.778 | 6.50 | 10.95 | 0.1797 | — | G2 | liq_long_>=$250k_60m_reversion |
| 29 | nan | ETH_1m_liq_long_100k_60m_reversion | ETH | 1m | 9.0 | 0.778 | 6.50 | 10.95 | 0.1797 | — | G2 | liq_long_>=$100k_60m_reversion |
| 30 | nan | N5.2_sweep_nan_to_SOL | SOL | nan | 10.0 | 0.800 | 5.99 | 10.44 | 0.0673 | — | G_pos_sharpe,G_pos_pnl | UP/0.5 |

## Deploy candidates (n ≥ 30, sharpe ≥ 1.5, ≥ 3 gates passed)

**13 candidate(s)** meet all 3 criteria.

| Source | Strategy | Asset | TF | n | WR | $/tr | Sharpe | Gates |
|---|---|---|---|---:|---:|---:|---:|---|
| nan | SOL_4h_sms_markov_sized_hold3 | SOL | 4h | 31.0 | 0.806 | 5.51 | 10.14 | G1,G2,G6 |
| nan | N3|ETH|h24h|z1.5 | ETH | 24h_hold | 216.0 | 0.593 | 2.15 | 3.79 | G1,G2,G3,G4,G6 |
| nan | SOL_4h_pure_sms_signal_flip | SOL | 4h | 105.0 | 0.695 | 4.24 | 3.75 | G1,G2,G6 |
| nan | N3|SOL|h72h|z2.0 | SOL | 72h_hold | 132.0 | 0.530 | 2.39 | 3.50 | G2,G3,G4,G6 |
| nan | N3|SOL|h24h|z2.0 | SOL | 24h_hold | 126.0 | 0.516 | 1.70 | 3.45 | G2,G3,G4,G6 |
| nan | N3|BTC|h24h|z2.0 | BTC | 24h_hold | 100.0 | 0.610 | 1.53 | 3.23 | G1,G2,G3,G4,G6 |
| nan | N2-cross_to_neg|HYPE|h72h|z2.0 | HYPE | 72h_hold | 151.0 | 0.576 | 3.10 | 2.87 | G2,G3,G4,G6 |
| nan | N3|SOL|h72h|z1.5 | SOL | 72h_hold | 286.0 | 0.528 | 1.98 | 2.72 | G2,G3,G4,G6 |
| nan | N2-B|HYPE|h72h|z1.5 | HYPE | 72h_hold | 116.0 | 0.543 | 2.92 | 2.63 | G2,G3,G4 |
| nan | N3|ETH|h24h|z1.0 | ETH | 24h_hold | 507.0 | 0.550 | 1.35 | 2.39 | G1,G2,G3,G4,G6 |
| nan | N3|BTC|h24h|z1.0 | BTC | 24h_hold | 532.0 | 0.523 | 0.89 | 1.91 | G2,G3,G4,G6 |
| nan | N3|SOL|h24h|z1.5 | SOL | 24h_hold | 263.0 | 0.490 | 1.11 | 1.98 | G2,G4,G6 |
| nan | N3|SOL|h24h|z1.0 | SOL | 24h_hold | 621.0 | 0.512 | 1.08 | 1.82 | G2,G4,G6 |