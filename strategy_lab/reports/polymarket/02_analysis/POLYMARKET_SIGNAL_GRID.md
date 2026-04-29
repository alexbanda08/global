# Polymarket Real-Signal × Exit Grid — BTC Up/Down (Apr 22-27)

Signals derived from Binance microstructure (ret_5m, smart_minus_retail) via VPS `binance_klines_v2` + `binance_metrics_v2`. Fee 2% on winnings. Bootstrap n=2000.


## 5m — top 12 cells by PnL

| Signal | Strategy | n | PnL | 95% CI | Win% |
|---|---|---|---|---|---|
| sig_ret5m | S0_hold | 1422 | $+54.59 | [$+19, $+92] | 54.8% |
| sig_ret5m | S2_stop35 | 1422 | $+49.49 | [$+29, $+71] | 30.2% |
| sig_ret5m | S2_stop30 | 1422 | $+46.59 | [$+24, $+71] | 34.6% |
| sig_ret5m | S2_stop40 | 1422 | $+39.43 | [$+21, $+58] | 25.2% |
| sig_ret5m_q20 | S2_stop35 | 285 | $+32.46 | [$+22, $+42] | 41.4% |
| sig_ret5m_q20 | S0_hold | 285 | $+31.07 | [$+15, $+47] | 61.4% |
| sig_ret5m_q20 | S2_stop30 | 285 | $+30.95 | [$+19, $+43] | 44.6% |
| sig_ret5m | S3_t70s35 | 1422 | $+28.38 | [$+16, $+41] | 49.2% |
| sig_ret5m_q10 | S0_hold | 143 | $+26.25 | [$+16, $+37] | 68.5% |
| sig_ret5m_q20 | S2_stop40 | 285 | $+24.34 | [$+16, $+33] | 33.3% |
| sig_ret5m_q10 | S2_stop35 | 143 | $+21.53 | [$+14, $+29] | 46.9% |
| sig_ret5m_q10 | S2_stop30 | 143 | $+21.13 | [$+13, $+29] | 49.7% |

## 15m — top 12 cells by PnL

| Signal | Strategy | n | PnL | 95% CI | Win% |
|---|---|---|---|---|---|
| sig_ret5m | S0_hold | 474 | $+33.33 | [$+13, $+53] | 57.8% |
| sig_ret5m | S2_stop30 | 474 | $+19.49 | [$+6, $+34] | 35.2% |
| sig_ret5m | S2_stop35 | 474 | $+18.21 | [$+6, $+31] | 30.2% |
| sig_ret5m_q20 | S2_stop30 | 95 | $+13.24 | [$+7, $+20] | 48.4% |
| sig_ret5m | S2_stop40 | 474 | $+12.44 | [$+2, $+23] | 23.2% |
| sig_ret5m_q20 | S2_stop35 | 95 | $+11.85 | [$+6, $+18] | 43.2% |
| sig_ret5m_q20 | S0_hold | 95 | $+11.40 | [$+2, $+20] | 62.1% |
| sig_ret5m_q20 | S2_stop40 | 95 | $+9.30 | [$+4, $+15] | 34.7% |
| sig_combo_q20 | S2_stop30 | 48 | $+8.26 | [$+4, $+13] | 54.2% |
| sig_combo_q20 | S2_stop35 | 48 | $+8.08 | [$+4, $+12] | 50.0% |
| sig_ret5m_q20 | S3_t70s35 | 95 | $+7.95 | [$+4, $+11] | 66.3% |
| sig_combo_q20 | S0_hold | 48 | $+7.61 | [$+1, $+14] | 66.7% |