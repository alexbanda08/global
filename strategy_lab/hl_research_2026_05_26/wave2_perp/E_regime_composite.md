# E - Regime composite (perp-native rebuild)

**Output**: `strategy_lab/hl_research_2026_05_26/wave2_perp/E_results.csv`

## Hypothesis
Regime is a **strategy router** and **sizing multiplier**, not a binary gate. 
E1 routes to A2 trend or B1 mean-rev based on Markov+regime_label. 
E2 applies vol-bucket leverage on A3. E3 switches A1/B1 by session. 
E4 uses Cyclops 3-axis count as confidence multiplier on A2 notional.

## Top 5 composite cells (sharpe_ann + calmar rank-sum)
| Strategy | Asset | TF | n | win_rate | total_pnl | sharpe | calmar | max_dd |
|---|---|---|---|---|---|---|---|---|
| E4_cyclops_conf | SOL | 4h | 134 | 0.567 | $+286 | 1.98 | 2.78 | $-103 |
| E2_vol_sized | BTC | 4h | 199 | 0.452 | $+152 | 0.88 | 1.61 | $-94 |
| E1_router | SOL | 4h | 178 | 0.551 | $+170 | 0.85 | 1.39 | $-123 |
| E2_vol_sized | ETH | 4h | 193 | 0.466 | $+58 | 0.43 | 0.52 | $-112 |
| E4_cyclops_conf | ETH | 4h | 137 | 0.423 | $+10 | 0.08 | 0.11 | $-93 |

## Lift summary — composite Sharpe minus best component Sharpe

| Strategy | Asset | TF | composite | best_comp | lift | verdict |
|---|---|---|---|---|---|---|
| E1_router | BTC | 1h | -2.37 | -1.56 | -0.81 | DRAG |
| E1_router | BTC | 4h | -2.36 | -0.78 | -1.58 | DRAG |
| E1_router | ETH | 1h | -0.74 | -0.75 | +0.01 | FLAT |
| E1_router | ETH | 4h | -0.83 | -0.97 | +0.15 | LIFT |
| E1_router | SOL | 1h | -0.73 | +0.54 | -1.26 | DRAG |
| E1_router | SOL | 4h | +0.85 | +1.16 | -0.31 | DRAG |
| E2_vol_sized | BTC | 1h | -0.95 | -0.91 | -0.04 | FLAT |
| E2_vol_sized | BTC | 4h | +0.88 | +0.30 | +0.58 | LIFT |
| E2_vol_sized | ETH | 1h | -3.05 | -3.33 | +0.28 | LIFT |
| E2_vol_sized | ETH | 4h | +0.43 | +0.01 | +0.42 | LIFT |
| E2_vol_sized | SOL | 1h | -1.22 | -1.58 | +0.36 | LIFT |
| E2_vol_sized | SOL | 4h | -0.33 | -0.52 | +0.19 | LIFT |
| E3_session | BTC | 1h | -2.35 | -1.28 | -1.08 | DRAG |
| E3_session | BTC | 4h | -0.39 | +0.13 | -0.52 | DRAG |
| E3_session | ETH | 1h | -1.71 | -1.51 | -0.19 | DRAG |
| E3_session | ETH | 4h | -0.28 | +0.54 | -0.81 | DRAG |
| E3_session | SOL | 1h | -0.22 | -0.97 | +0.75 | LIFT |
| E3_session | SOL | 4h | -0.95 | -0.35 | -0.59 | DRAG |
| E4_cyclops_conf | BTC | 1h | -3.27 | -1.56 | -1.71 | DRAG |
| E4_cyclops_conf | BTC | 4h | -0.65 | -1.28 | +0.63 | LIFT |
| E4_cyclops_conf | ETH | 1h | -1.11 | -0.75 | -0.35 | DRAG |
| E4_cyclops_conf | ETH | 4h | +0.08 | -0.97 | +1.05 | LIFT |
| E4_cyclops_conf | SOL | 1h | -1.58 | +0.54 | -2.12 | DRAG |
| E4_cyclops_conf | SOL | 4h | +1.98 | +1.16 | +0.82 | LIFT |

## Additive lift: composite vs each component standalone (full)

### E1_router
| Asset | TF | Variant | n | Sharpe | PnL | Calmar |
|---|---|---|---|---|---|---|
| BTC | 1h | composite | 515 | -2.37 | $-376 | -0.97 |
| BTC | 1h | A2_only | 645 | -1.56 | $-292 | -0.93 |
| BTC | 1h | B1_only | 230 | -2.76 | $-220 | -0.96 |
| BTC | 4h | composite | 194 | -2.36 | $-240 | -1.02 |
| BTC | 4h | A2_only | 223 | -1.28 | $-157 | -0.88 |
| BTC | 4h | B1_only | 77 | -0.78 | $-48 | -0.34 |
| ETH | 1h | composite | 516 | -0.74 | $-158 | -0.74 |
| ETH | 1h | A2_only | 643 | -0.75 | $-199 | -0.78 |
| ETH | 1h | B1_only | 222 | -1.94 | $-208 | -0.90 |
| ETH | 4h | composite | 181 | -0.83 | $-141 | -0.64 |
| ETH | 4h | A2_only | 225 | -0.97 | $-196 | -0.59 |
| ETH | 4h | B1_only | 80 | -1.31 | $-101 | -0.47 |
| SOL | 1h | composite | 533 | -0.73 | $-210 | -0.52 |
| SOL | 1h | A2_only | 631 | 0.54 | $+196 | 0.92 |
| SOL | 1h | B1_only | 193 | -2.26 | $-277 | -0.96 |
| SOL | 4h | composite | 178 | 0.85 | $+170 | 1.39 |
| SOL | 4h | A2_only | 218 | 1.16 | $+273 | 2.14 |
| SOL | 4h | B1_only | 71 | -1.22 | $-133 | -0.47 |

### E2_vol_sized
| Asset | TF | Variant | n | Sharpe | PnL | Calmar |
|---|---|---|---|---|---|---|
| BTC | 1h | vol_sized | 569 | -0.95 | $-190 | -0.52 |
| BTC | 1h | flat_1x | 569 | -0.91 | $-155 | -0.51 |
| BTC | 4h | vol_sized | 199 | 0.88 | $+152 | 1.61 |
| BTC | 4h | flat_1x | 199 | 0.30 | $+37 | 0.56 |
| ETH | 1h | vol_sized | 575 | -3.05 | $-702 | -0.90 |
| ETH | 1h | flat_1x | 575 | -3.33 | $-822 | -0.92 |
| ETH | 4h | vol_sized | 193 | 0.43 | $+58 | 0.52 |
| ETH | 4h | flat_1x | 193 | 0.01 | $+1 | 0.01 |
| SOL | 1h | vol_sized | 569 | -1.22 | $-459 | -0.73 |
| SOL | 1h | flat_1x | 569 | -1.58 | $-499 | -0.80 |
| SOL | 4h | vol_sized | 197 | -0.33 | $-90 | -0.33 |
| SOL | 4h | flat_1x | 197 | -0.52 | $-112 | -0.49 |

### E3_session
| Asset | TF | Variant | n | Sharpe | PnL | Calmar |
|---|---|---|---|---|---|---|
| BTC | 1h | composite | 612 | -2.35 | $-449 | -0.91 |
| BTC | 1h | A1_only | 667 | -1.28 | $-264 | -0.75 |
| BTC | 1h | B1_only | 230 | -2.76 | $-220 | -0.96 |
| BTC | 4h | composite | 212 | -0.39 | $-56 | -0.47 |
| BTC | 4h | A1_only | 234 | 0.13 | $+20 | 0.18 |
| BTC | 4h | B1_only | 77 | -0.78 | $-48 | -0.34 |
| ETH | 1h | composite | 593 | -1.71 | $-451 | -0.94 |
| ETH | 1h | A1_only | 676 | -1.51 | $-440 | -0.82 |
| ETH | 1h | B1_only | 222 | -1.94 | $-208 | -0.90 |
| ETH | 4h | composite | 218 | -0.28 | $-52 | -0.28 |
| ETH | 4h | A1_only | 245 | 0.54 | $+114 | 0.95 |
| ETH | 4h | B1_only | 80 | -1.31 | $-101 | -0.47 |
| SOL | 1h | composite | 602 | -0.22 | $-79 | -0.26 |
| SOL | 1h | A1_only | 707 | -0.97 | $-401 | -0.74 |
| SOL | 1h | B1_only | 193 | -2.26 | $-277 | -0.96 |
| SOL | 4h | composite | 225 | -0.95 | $-251 | -0.47 |
| SOL | 4h | A1_only | 255 | -0.35 | $-105 | -0.25 |
| SOL | 4h | B1_only | 71 | -1.22 | $-133 | -0.47 |

### E4_cyclops_conf
| Asset | TF | Variant | n | Sharpe | PnL | Calmar |
|---|---|---|---|---|---|---|
| BTC | 1h | composite | 407 | -3.27 | $-390 | -0.90 |
| BTC | 1h | A2_only | 645 | -1.56 | $-292 | -0.93 |
| BTC | 4h | composite | 142 | -0.65 | $-53 | -0.72 |
| BTC | 4h | A2_only | 223 | -1.28 | $-157 | -0.88 |
| ETH | 1h | composite | 421 | -1.11 | $-188 | -0.68 |
| ETH | 1h | A2_only | 643 | -0.75 | $-199 | -0.78 |
| ETH | 4h | composite | 137 | 0.08 | $+10 | 0.11 |
| ETH | 4h | A2_only | 225 | -0.97 | $-196 | -0.59 |
| SOL | 1h | composite | 439 | -1.58 | $-404 | -0.99 |
| SOL | 1h | A2_only | 631 | 0.54 | $+196 | 0.92 |
| SOL | 4h | composite | 134 | 1.98 | $+286 | 2.78 |
| SOL | 4h | A2_only | 218 | 1.16 | $+273 | 2.14 |

## G6 / G7 deep-dive - composite cells with n >= 50

### E1_router - BTC 1h
- n_trades=515  total_pnl=$-376  sharpe=-2.37
- **G6 Sharpe 95% CI**: [-19.74, -3.60]  (FAIL)

**G7 per-regime hold-out**
| Regime | n | Sharpe | PnL | WR |
|---|---|---|---|---|
| trend_up | 277 | -1.99 | $-162 | 0.451 |
| sideways | 0 | nan | $+0 | nan |
| trend_dn | 238 | -2.77 | $-213 | 0.395 |

### E2_vol_sized - BTC 1h
- n_trades=569  total_pnl=$-190  sharpe=-0.95
- **G6 Sharpe 95% CI**: [-12.50, 3.06]  (FAIL)

**G7 per-regime hold-out**
| Regime | n | Sharpe | PnL | WR |
|---|---|---|---|---|
| low_vol | 149 | -1.63 | $-135 | 0.409 |
| mid_vol | 208 | -0.36 | $-22 | 0.452 |
| high_vol | 212 | -0.98 | $-33 | 0.462 |

### E3_session - BTC 1h
- n_trades=612  total_pnl=$-449  sharpe=-2.35
- **G6 Sharpe 95% CI**: [-18.90, -4.12]  (FAIL)

**G7 per-regime hold-out**
| Regime | n | Sharpe | PnL | WR |
|---|---|---|---|---|
| asia | 45 | -3.69 | $-68 | 0.422 |
| london | 125 | -0.86 | $-32 | 0.472 |
| ny | 442 | -2.60 | $-350 | 0.410 |

### E4_cyclops_conf - BTC 1h
- n_trades=407  total_pnl=$-390  sharpe=-3.27
- **G6 Sharpe 95% CI**: [-25.19, -7.12]  (FAIL)

**G7 per-regime hold-out**
| Regime | n | Sharpe | PnL | WR |
|---|---|---|---|---|
| 1_axis | 0 | nan | $+0 | nan |
| 2_axes | 407 | -3.27 | $-390 | 0.408 |
| 3_axes | 0 | nan | $+0 | nan |

### E1_router - BTC 4h
- n_trades=194  total_pnl=$-240  sharpe=-2.36
- **G6 Sharpe 95% CI**: [-14.88, -1.53]  (FAIL)

**G7 per-regime hold-out**
| Regime | n | Sharpe | PnL | WR |
|---|---|---|---|---|
| trend_up | 104 | -1.48 | $-85 | 0.462 |
| sideways | 0 | nan | $+0 | nan |
| trend_dn | 90 | -3.52 | $-155 | 0.389 |

### E2_vol_sized - BTC 4h
- n_trades=199  total_pnl=$+152  sharpe=0.88
- **G6 Sharpe 95% CI**: [-3.39, 9.33]  (FAIL)

**G7 per-regime hold-out**
| Regime | n | Sharpe | PnL | WR |
|---|---|---|---|---|
| low_vol | 61 | 2.13 | $+180 | 0.525 |
| mid_vol | 60 | -0.11 | $-4 | 0.383 |
| high_vol | 78 | -1.18 | $-24 | 0.449 |

### E3_session - BTC 4h
- n_trades=212  total_pnl=$-56  sharpe=-0.39
- **G6 Sharpe 95% CI**: [-8.02, 4.78]  (FAIL)

**G7 per-regime hold-out**
| Regime | n | Sharpe | PnL | WR |
|---|---|---|---|---|
| asia | 11 | -4.18 | $-37 | 0.182 |
| london | 35 | -0.61 | $-13 | 0.429 |
| ny | 166 | -0.05 | $-6 | 0.416 |

### E4_cyclops_conf - BTC 4h
- n_trades=142  total_pnl=$-53  sharpe=-0.65
- **G6 Sharpe 95% CI**: [-10.39, 5.58]  (FAIL)

**G7 per-regime hold-out**
| Regime | n | Sharpe | PnL | WR |
|---|---|---|---|---|
| 1_axis | 0 | nan | $+0 | nan |
| 2_axes | 142 | -0.65 | $-53 | 0.486 |
| 3_axes | 0 | nan | $+0 | nan |

### E1_router - ETH 1h
- n_trades=516  total_pnl=$-158  sharpe=-0.74
- **G6 Sharpe 95% CI**: [-11.54, 4.33]  (FAIL)

**G7 per-regime hold-out**
| Regime | n | Sharpe | PnL | WR |
|---|---|---|---|---|
| trend_up | 260 | -0.04 | $-4 | 0.515 |
| sideways | 0 | nan | $+0 | nan |
| trend_dn | 256 | -1.39 | $-154 | 0.438 |

### E2_vol_sized - ETH 1h
- n_trades=575  total_pnl=$-702  sharpe=-3.05
- **G6 Sharpe 95% CI**: [-21.93, -7.63]  (FAIL)

**G7 per-regime hold-out**
| Regime | n | Sharpe | PnL | WR |
|---|---|---|---|---|
| low_vol | 80 | -3.40 | $-198 | 0.412 |
| mid_vol | 187 | -3.59 | $-285 | 0.455 |
| high_vol | 308 | -3.17 | $-219 | 0.396 |

### E3_session - ETH 1h
- n_trades=593  total_pnl=$-451  sharpe=-1.71
- **G6 Sharpe 95% CI**: [-16.64, -0.71]  (FAIL)

**G7 per-regime hold-out**
| Regime | n | Sharpe | PnL | WR |
|---|---|---|---|---|
| asia | 40 | -3.30 | $-48 | 0.500 |
| london | 138 | -0.10 | $-7 | 0.428 |
| ny | 415 | -2.21 | $-396 | 0.407 |

### E4_cyclops_conf - ETH 1h
- n_trades=421  total_pnl=$-188  sharpe=-1.11
- **G6 Sharpe 95% CI**: [-14.14, 3.32]  (FAIL)

**G7 per-regime hold-out**
| Regime | n | Sharpe | PnL | WR |
|---|---|---|---|---|
| 1_axis | 0 | nan | $+0 | nan |
| 2_axes | 421 | -1.11 | $-188 | 0.456 |
| 3_axes | 0 | nan | $+0 | nan |

### E1_router - ETH 4h
- n_trades=181  total_pnl=$-141  sharpe=-0.83
- **G6 Sharpe 95% CI**: [-9.86, 4.09]  (FAIL)

**G7 per-regime hold-out**
| Regime | n | Sharpe | PnL | WR |
|---|---|---|---|---|
| trend_up | 84 | 0.64 | $+54 | 0.429 |
| sideways | 0 | nan | $+0 | nan |
| trend_dn | 97 | -2.28 | $-195 | 0.402 |

### E2_vol_sized - ETH 4h
- n_trades=193  total_pnl=$+58  sharpe=0.43
- **G6 Sharpe 95% CI**: [-5.48, 7.92]  (FAIL)

**G7 per-regime hold-out**
| Regime | n | Sharpe | PnL | WR |
|---|---|---|---|---|
| low_vol | 21 | 4.98 | $+137 | 0.524 |
| mid_vol | 73 | -1.74 | $-90 | 0.452 |
| high_vol | 99 | 0.26 | $+11 | 0.465 |

### E3_session - ETH 4h
- n_trades=218  total_pnl=$-52  sharpe=-0.28
- **G6 Sharpe 95% CI**: [-7.34, 5.47]  (FAIL)

**G7 per-regime hold-out**
| Regime | n | Sharpe | PnL | WR |
|---|---|---|---|---|
| asia | 10 | -1.84 | $-11 | 0.200 |
| london | 39 | 1.86 | $+57 | 0.487 |
| ny | 169 | -0.65 | $-98 | 0.444 |

### E4_cyclops_conf - ETH 4h
- n_trades=137  total_pnl=$+10  sharpe=0.08
- **G6 Sharpe 95% CI**: [-7.73, 7.99]  (FAIL)

**G7 per-regime hold-out**
| Regime | n | Sharpe | PnL | WR |
|---|---|---|---|---|
| 1_axis | 0 | nan | $+0 | nan |
| 2_axes | 137 | 0.08 | $+10 | 0.423 |
| 3_axes | 0 | nan | $+0 | nan |

### E1_router - SOL 1h
- n_trades=533  total_pnl=$-210  sharpe=-0.73
- **G6 Sharpe 95% CI**: [-11.55, 4.79]  (FAIL)

**G7 per-regime hold-out**
| Regime | n | Sharpe | PnL | WR |
|---|---|---|---|---|
| trend_up | 275 | -0.51 | $-72 | 0.455 |
| sideways | 0 | nan | $+0 | nan |
| trend_dn | 258 | -0.94 | $-138 | 0.496 |

### E2_vol_sized - SOL 1h
- n_trades=569  total_pnl=$-459  sharpe=-1.22
- **G6 Sharpe 95% CI**: [-13.68, 1.59]  (FAIL)

**G7 per-regime hold-out**
| Regime | n | Sharpe | PnL | WR |
|---|---|---|---|---|
| low_vol | 174 | -0.66 | $-113 | 0.448 |
| mid_vol | 227 | -2.06 | $-249 | 0.454 |
| high_vol | 168 | -1.79 | $-96 | 0.446 |

### E3_session - SOL 1h
- n_trades=602  total_pnl=$-79  sharpe=-0.22
- **G6 Sharpe 95% CI**: [-8.63, 6.29]  (FAIL)

**G7 per-regime hold-out**
| Regime | n | Sharpe | PnL | WR |
|---|---|---|---|---|
| asia | 28 | 4.32 | $+87 | 0.429 |
| london | 160 | 0.52 | $+50 | 0.487 |
| ny | 414 | -0.92 | $-216 | 0.481 |

### E4_cyclops_conf - SOL 1h
- n_trades=439  total_pnl=$-404  sharpe=-1.58
- **G6 Sharpe 95% CI**: [-16.24, 0.86]  (FAIL)

**G7 per-regime hold-out**
| Regime | n | Sharpe | PnL | WR |
|---|---|---|---|---|
| 1_axis | 0 | nan | $+0 | nan |
| 2_axes | 439 | -1.58 | $-404 | 0.456 |
| 3_axes | 0 | nan | $+0 | nan |

### E1_router - SOL 4h
- n_trades=178  total_pnl=$+170  sharpe=0.85
- **G6 Sharpe 95% CI**: [-3.83, 9.71]  (FAIL)

**G7 per-regime hold-out**
| Regime | n | Sharpe | PnL | WR |
|---|---|---|---|---|
| trend_up | 97 | 1.58 | $+171 | 0.567 |
| sideways | 0 | nan | $+0 | nan |
| trend_dn | 81 | -0.02 | $-1 | 0.531 |

### E2_vol_sized - SOL 4h
- n_trades=197  total_pnl=$-90  sharpe=-0.33
- **G6 Sharpe 95% CI**: [-7.69, 5.66]  (FAIL)

**G7 per-regime hold-out**
| Regime | n | Sharpe | PnL | WR |
|---|---|---|---|---|
| low_vol | 65 | 0.63 | $+81 | 0.554 |
| mid_vol | 80 | -2.23 | $-189 | 0.463 |
| high_vol | 52 | 0.56 | $+18 | 0.519 |

### E3_session - SOL 4h
- n_trades=225  total_pnl=$-251  sharpe=-0.95
- **G6 Sharpe 95% CI**: [-9.52, 2.87]  (FAIL)

**G7 per-regime hold-out**
| Regime | n | Sharpe | PnL | WR |
|---|---|---|---|---|
| asia | 8 | -24.61 | $-97 | 0.125 |
| london | 35 | -0.86 | $-44 | 0.457 |
| ny | 182 | -0.54 | $-110 | 0.456 |

### E4_cyclops_conf - SOL 4h
- n_trades=134  total_pnl=$+286  sharpe=1.98
- **G6 Sharpe 95% CI**: [-0.91, 15.11]  (FAIL)

**G7 per-regime hold-out**
| Regime | n | Sharpe | PnL | WR |
|---|---|---|---|---|
| 1_axis | 0 | nan | $+0 | nan |
| 2_axes | 133 | 1.94 | $+279 | 0.564 |
| 3_axes | 1 | nan | $+7 | 1.000 |

## Buy-and-hold benchmark (single LONG over full window, $250 notional)
| Asset | TF | total_pnl | sharpe | calmar | max_dd | bars |
|---|---|---|---|---|---|---|
| BTC | 1h | $+272 | 0.69 | 0.47 | $-584 | 25319 |
| BTC | 4h | $+283 | 0.72 | 0.48 | $-588 | 6329 |
| ETH | 1h | $-69 | 0.09 | -0.16 | $-434 | 25319 |
| ETH | 4h | $-63 | 0.10 | -0.15 | $-426 | 6329 |
| SOL | 1h | $+686 | 0.55 | 0.26 | $-2603 | 25319 |
| SOL | 4h | $+700 | 0.57 | 0.27 | $-2622 | 6329 |

## Notes
- All trades use HL taker 4.5 bps each side + 3 bps slippage + hourly funding accrual.
- E2 leverage range: low_vol=2.0x / mid_vol=1.0x / high_vol=0.5x. E4 notional: 2_of_3 -> $250, 3_of_3 -> $500.
- Overlap-aware: a new fire is skipped while still in a position.
- Sharpe annualization uses bar-period scaling (bars_per_year / avg_bars_held).
- Composite vs component comparison enables additive-lift verification (G_lift).
- Window: ~2023-05 to ~2026-03 (~34 months) where HL funding overlaps with Binance klines.
