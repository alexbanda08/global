# Alt-Signal Grid — Cross-Asset × Hedge-Hold rev_bp=5

Universe: BTC + ETH + SOL Up/Down markets (5,742 total). Exit: hedge-hold rev_bp=5. Bootstrap n=2000. ROI = mean PnL per (1 share entry + 1 share hedge) × 100.

**Locked baseline:** `sig_ret5m_q20` (★) at q20×15m×ALL → n=289, hit 75.8%, ROI +20.39%.


## Best signal per (asset, tf) cell

| Asset | TF | Best signal | n | Hit | ROI | vs baseline |
|---|---|---|---|---|---|---|
| ALL | ALL | `sig_ret5m_q5` | 292 | 83.2% | +25.34% | +5.11pp vs baseline |
| ALL | 15m | `sig_ret5m_q5` | 74 | 86.5% | +23.03% | +2.64pp vs baseline |
| ALL | 5m | `sig_ret5m_q5` | 218 | 82.1% | +26.13% | +5.95pp vs baseline |
| btc | ALL | `sig_ret5m_q10` | 191 | 84.8% | +27.90% | +5.37pp vs baseline |
| btc | 15m | `sig_combo_q20` | 48 | 81.2% | +26.32% | +4.08pp vs baseline |
| btc | 5m | `sig_ret5m_q10` | 143 | 85.3% | +29.61% | +6.98pp vs baseline |
| eth | ALL | `sig_ret5m_q10` | 194 | 80.4% | +24.89% | +5.47pp vs baseline |
| eth | 15m | `sig_ret5m_q10` | 49 | 83.7% | +24.34% | +3.14pp vs baseline |
| eth | 5m | `sig_ret5m_q5` | 73 | 79.5% | +25.34% | +6.52pp vs baseline |
| sol | ALL | `sig_ret5m_q5` | 98 | 83.7% | +23.64% | +4.86pp vs baseline |
| sol | 15m | `sig_ret5m_q5` | 25 | 84.0% | +21.45% | +3.71pp vs baseline |
| sol | 5m | `sig_ret5m_q5` | 73 | 83.6% | +24.39% | +5.26pp vs baseline |


## Full grid (all asset × tf × signal)

| Asset | TF | Signal | n | Hit | PnL/trade | ROI |
|---|---|---|---|---|---|---|
| ALL | ALL | `sig_ret5m_q5` | 292 | 83.2% | $+0.2534 | +25.34% |
| ALL | ALL | `sig_ret5m_q10` | 579 | 81.5% | $+0.2458 | +24.58% |
| ALL | ALL | `sig_ret5m_thr25bps` | 181 | 81.8% | $+0.2354 | +23.54% |
| ALL | ALL | `sig_ret5m_q20` ★ | 1152 | 73.8% | $+0.2023 | +20.23% |
| ALL | ALL | `sig_combo_q20` | 606 | 72.4% | $+0.2002 | +20.02% |
| ALL | ALL | `sig_ret5m_q20_srfilter` | 1030 | 72.6% | $+0.1989 | +19.89% |
| ALL | ALL | `sig_ret15m_q20` | 1152 | 70.1% | $+0.1772 | +17.72% |
| ALL | ALL | `sig_ret1h_q20` | 1152 | 60.6% | $+0.1241 | +12.41% |
| ALL | ALL | `sig_smartretail_q20` | 1262 | 57.9% | $+0.0793 | +7.93% |
| ALL | 15m | `sig_ret5m_q5` | 74 | 86.5% | $+0.2303 | +23.03% |
| ALL | 15m | `sig_ret5m_q10` | 146 | 82.2% | $+0.2203 | +22.03% |
| ALL | 15m | `sig_ret5m_thr25bps` | 40 | 85.0% | $+0.2170 | +21.70% |
| ALL | 15m | `sig_combo_q20` | 153 | 74.5% | $+0.2052 | +20.52% |
| ALL | 15m | `sig_ret5m_q20` ★ | 289 | 75.8% | $+0.2039 | +20.39% |
| ALL | 15m | `sig_ret5m_q20_srfilter` | 260 | 75.0% | $+0.2029 | +20.29% |
| ALL | 15m | `sig_ret15m_q20` | 289 | 70.6% | $+0.1785 | +17.85% |
| ALL | 15m | `sig_ret1h_q20` | 289 | 61.2% | $+0.1271 | +12.71% |
| ALL | 15m | `sig_smartretail_q20` | 317 | 53.3% | $+0.0657 | +6.57% |
| ALL | 5m | `sig_ret5m_q5` | 218 | 82.1% | $+0.2613 | +26.13% |
| ALL | 5m | `sig_ret5m_q10` | 433 | 81.3% | $+0.2543 | +25.43% |
| ALL | 5m | `sig_ret5m_thr25bps` | 141 | 80.9% | $+0.2406 | +24.06% |
| ALL | 5m | `sig_ret5m_q20` ★ | 863 | 73.1% | $+0.2018 | +20.18% |
| ALL | 5m | `sig_combo_q20` | 453 | 71.7% | $+0.1985 | +19.85% |
| ALL | 5m | `sig_ret5m_q20_srfilter` | 770 | 71.8% | $+0.1975 | +19.75% |
| ALL | 5m | `sig_ret15m_q20` | 863 | 70.0% | $+0.1767 | +17.67% |
| ALL | 5m | `sig_ret1h_q20` | 863 | 60.4% | $+0.1231 | +12.31% |
| ALL | 5m | `sig_smartretail_q20` | 945 | 59.5% | $+0.0839 | +8.39% |
| btc | ALL | `sig_ret5m_q10` | 191 | 84.8% | $+0.2790 | +27.90% |
| btc | ALL | `sig_ret5m_q5` | 96 | 83.3% | $+0.2755 | +27.55% |
| btc | ALL | `sig_ret5m_thr25bps` | 42 | 83.3% | $+0.2536 | +25.36% |
| btc | ALL | `sig_combo_q20` | 184 | 78.8% | $+0.2398 | +23.98% |
| btc | ALL | `sig_ret5m_q20` ★ | 380 | 77.1% | $+0.2253 | +22.53% |
| btc | ALL | `sig_ret5m_q20_srfilter` | 342 | 76.3% | $+0.2209 | +22.09% |
| btc | ALL | `sig_ret15m_q20` | 380 | 70.5% | $+0.1791 | +17.91% |
| btc | ALL | `sig_ret1h_q20` | 380 | 57.4% | $+0.1030 | +10.30% |
| btc | ALL | `sig_smartretail_q20` | 486 | 55.3% | $+0.0444 | +4.44% |
| btc | 15m | `sig_combo_q20` | 48 | 81.2% | $+0.2632 | +26.32% |
| btc | 15m | `sig_ret5m_q5` | 24 | 83.3% | $+0.2413 | +24.13% |
| btc | 15m | `sig_ret5m_q10` | 48 | 83.3% | $+0.2283 | +22.83% |
| btc | 15m | `sig_ret5m_q20` ★ | 95 | 77.9% | $+0.2225 | +22.25% |
| btc | 15m | `sig_ret5m_thr25bps` | 8 | 87.5% | $+0.2218 | +22.18% |
| btc | 15m | `sig_ret5m_q20_srfilter` | 85 | 77.6% | $+0.2205 | +22.05% |
| btc | 15m | `sig_ret15m_q20` | 95 | 71.6% | $+0.1842 | +18.42% |
| btc | 15m | `sig_ret1h_q20` | 95 | 56.8% | $+0.1153 | +11.53% |
| btc | 15m | `sig_smartretail_q20` | 121 | 52.1% | $+0.0229 | +2.29% |
| btc | 5m | `sig_ret5m_q10` | 143 | 85.3% | $+0.2961 | +29.61% |
| btc | 5m | `sig_ret5m_q5` | 72 | 83.3% | $+0.2869 | +28.69% |
| btc | 5m | `sig_ret5m_thr25bps` | 34 | 82.4% | $+0.2611 | +26.11% |
| btc | 5m | `sig_combo_q20` | 136 | 77.9% | $+0.2316 | +23.16% |
| btc | 5m | `sig_ret5m_q20` ★ | 285 | 76.8% | $+0.2262 | +22.62% |
| btc | 5m | `sig_ret5m_q20_srfilter` | 257 | 75.9% | $+0.2211 | +22.11% |
| btc | 5m | `sig_ret15m_q20` | 285 | 70.2% | $+0.1774 | +17.74% |
| btc | 5m | `sig_ret1h_q20` | 285 | 57.5% | $+0.0989 | +9.89% |
| btc | 5m | `sig_smartretail_q20` | 365 | 56.4% | $+0.0516 | +5.16% |
| eth | ALL | `sig_ret5m_q10` | 194 | 80.4% | $+0.2489 | +24.89% |
| eth | ALL | `sig_ret5m_q5` | 98 | 82.7% | $+0.2489 | +24.89% |
| eth | ALL | `sig_ret5m_thr25bps` | 64 | 82.8% | $+0.2453 | +24.53% |
| eth | ALL | `sig_ret5m_q20` ★ | 386 | 71.8% | $+0.1942 | +19.42% |
| eth | ALL | `sig_ret5m_q20_srfilter` | 342 | 70.2% | $+0.1896 | +18.96% |
| eth | ALL | `sig_ret15m_q20` | 386 | 69.9% | $+0.1846 | +18.46% |
| eth | ALL | `sig_combo_q20` | 191 | 67.5% | $+0.1692 | +16.92% |
| eth | ALL | `sig_ret1h_q20` | 386 | 60.6% | $+0.1208 | +12.08% |
| eth | ALL | `sig_smartretail_q20` | 388 | 59.8% | $+0.0952 | +9.52% |
| eth | 15m | `sig_ret5m_q10` | 49 | 83.7% | $+0.2434 | +24.34% |
| eth | 15m | `sig_ret5m_thr25bps` | 15 | 93.3% | $+0.2391 | +23.91% |
| eth | 15m | `sig_ret5m_q5` | 25 | 92.0% | $+0.2355 | +23.55% |
| eth | 15m | `sig_ret5m_q20` ★ | 97 | 76.3% | $+0.2120 | +21.20% |
| eth | 15m | `sig_ret5m_q20_srfilter` | 87 | 75.9% | $+0.2079 | +20.79% |
| eth | 15m | `sig_ret15m_q20` | 97 | 73.2% | $+0.1943 | +19.43% |
| eth | 15m | `sig_combo_q20` | 46 | 73.9% | $+0.1882 | +18.82% |
| eth | 15m | `sig_ret1h_q20` | 97 | 64.9% | $+0.1315 | +13.15% |
| eth | 15m | `sig_smartretail_q20` | 98 | 59.2% | $+0.1240 | +12.40% |
| eth | 5m | `sig_ret5m_q5` | 73 | 79.5% | $+0.2534 | +25.34% |
| eth | 5m | `sig_ret5m_q10` | 145 | 79.3% | $+0.2507 | +25.07% |
| eth | 5m | `sig_ret5m_thr25bps` | 49 | 79.6% | $+0.2471 | +24.71% |
| eth | 5m | `sig_ret5m_q20` ★ | 289 | 70.2% | $+0.1883 | +18.83% |
| eth | 5m | `sig_ret5m_q20_srfilter` | 255 | 68.2% | $+0.1834 | +18.34% |
| eth | 5m | `sig_ret15m_q20` | 289 | 68.9% | $+0.1813 | +18.13% |
| eth | 5m | `sig_combo_q20` | 145 | 65.5% | $+0.1632 | +16.32% |
| eth | 5m | `sig_ret1h_q20` | 289 | 59.2% | $+0.1172 | +11.72% |
| eth | 5m | `sig_smartretail_q20` | 290 | 60.0% | $+0.0855 | +8.55% |
| sol | ALL | `sig_ret5m_q5` | 98 | 83.7% | $+0.2364 | +23.64% |
| sol | ALL | `sig_ret5m_thr25bps` | 75 | 80.0% | $+0.2167 | +21.67% |
| sol | ALL | `sig_ret5m_q10` | 194 | 79.4% | $+0.2098 | +20.98% |
| sol | ALL | `sig_combo_q20` | 231 | 71.4% | $+0.1942 | +19.42% |
| sol | ALL | `sig_ret5m_q20` ★ | 386 | 72.5% | $+0.1878 | +18.78% |
| sol | ALL | `sig_ret5m_q20_srfilter` | 346 | 71.4% | $+0.1862 | +18.62% |
| sol | ALL | `sig_ret15m_q20` | 386 | 69.9% | $+0.1679 | +16.79% |
| sol | ALL | `sig_ret1h_q20` | 386 | 63.7% | $+0.1482 | +14.82% |
| sol | ALL | `sig_smartretail_q20` | 388 | 59.3% | $+0.1072 | +10.72% |
| sol | 15m | `sig_ret5m_q5` | 25 | 84.0% | $+0.2145 | +21.45% |
| sol | 15m | `sig_ret5m_thr25bps` | 17 | 76.5% | $+0.1952 | +19.52% |
| sol | 15m | `sig_ret5m_q10` | 49 | 79.6% | $+0.1894 | +18.94% |
| sol | 15m | `sig_ret5m_q20_srfilter` | 88 | 71.6% | $+0.1809 | +18.09% |
| sol | 15m | `sig_ret5m_q20` ★ | 97 | 73.2% | $+0.1775 | +17.75% |
| sol | 15m | `sig_combo_q20` | 59 | 69.5% | $+0.1711 | +17.11% |
| sol | 15m | `sig_ret15m_q20` | 97 | 67.0% | $+0.1570 | +15.70% |
| sol | 15m | `sig_ret1h_q20` | 97 | 61.9% | $+0.1342 | +13.42% |
| sol | 15m | `sig_smartretail_q20` | 98 | 49.0% | $+0.0602 | +6.02% |
| sol | 5m | `sig_ret5m_q5` | 73 | 83.6% | $+0.2439 | +24.39% |
| sol | 5m | `sig_ret5m_thr25bps` | 58 | 81.0% | $+0.2231 | +22.31% |
| sol | 5m | `sig_ret5m_q10` | 145 | 79.3% | $+0.2168 | +21.68% |
| sol | 5m | `sig_combo_q20` | 172 | 72.1% | $+0.2021 | +20.21% |
| sol | 5m | `sig_ret5m_q20` ★ | 289 | 72.3% | $+0.1913 | +19.13% |
| sol | 5m | `sig_ret5m_q20_srfilter` | 258 | 71.3% | $+0.1881 | +18.81% |
| sol | 5m | `sig_ret15m_q20` | 289 | 70.9% | $+0.1715 | +17.15% |
| sol | 5m | `sig_ret1h_q20` | 289 | 64.4% | $+0.1529 | +15.29% |
| sol | 5m | `sig_smartretail_q20` | 290 | 62.8% | $+0.1231 | +12.31% |