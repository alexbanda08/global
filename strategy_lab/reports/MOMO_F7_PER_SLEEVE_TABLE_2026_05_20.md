# Per-sleeve comparison — current vs F7 RSI filter — 2026-05-20

**Data sources**:
- `trading_events_30d.parquet` — 74 sleeves with paper/shadow resolutions
- Modes present: only `paper` (momo direction bets) and `shadow` (MAS mint-sell). NO `live` events yet.
- Source canonical binance 1m klines for RSI(14) on log-returns.

## How to read this
- **cur_***: what the production sleeve actually produced (paper/shadow mode)
- **f7_***: counterfactual if F7 gate was applied (UP+RSI>50 / DOWN+RSI<50)
- **f7x_***: stricter F7_extreme (UP+RSI>60 / DOWN+RSI<40)
- `f7_skipped`: how many fires F7 would have filtered out
- `pnl_delta`: F7 sum PnL minus current sum PnL

## Aggregate (sum across all 74 sleeves)

| Config | n_trades | WR % | Sum PnL | $/trade |
|---|---:|---:|---:|---:|
| **Current production** | 58,701 | 45.25% | $-9,508.89 | $-0.1620 |
| **+ F7 filter** | 50,847 | 48.26% | $+78,112.92 | $1.5362 |
| **+ F7_extreme** | 46,561 | 48.16% | $+83,065.53 | $1.7840 |

**Swing**: current $-9,508.89 → F7 $+78,112.92 = **$+87,621.81** improvement over the data window.

## Aggregate by strategy family

| Family | n_sleeves | cur_n | cur_WR% | cur_PnL | f7_n | f7_WR% | f7_PnL | f7x_n | f7x_WR% | f7x_PnL |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| momo (all) | 36 | 8,325 | 48.9% | $-4,307 | 6,069 | 60.1% | $+26,541 | 4,239 | 69.7% | $+38,335 |
| sniper (all) | 8 | 3,543 | 49.9% | $-4,600 | 2,008 | 67.5% | $+9,246 | 1,242 | 76.0% | $+8,615 |
| mint_sell (shadow) | 6 | 38,651 | 42.8% | $+7,047 | 38,651 | 42.8% | $+7,047 | 38,651 | 42.8% | $+7,047 |
| volume_INV_NIGHT | 6 | 6,024 | 50.0% | $-5,910 | 2,346 | 81.3% | $+33,449 | 1,254 | 89.9% | $+23,187 |

## Per-sleeve full table (sorted by current PnL desc)

| sleeve_id | symbol | tf | mode | cur_n | cur_WR% | cur_PnL | f7_n | f7_WR% | f7_PnL | f7_Δ$ | f7_Δwr |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| poly_mint_sell_btc_5m | BTC | 5m | shadow | 7,899 | 59.2% | $+1,924 | 7,899 | 59.2% | $+1,924 | $+0 | +0.0pp |
| poly_mint_sell_eth_5m | ETH | 5m | shadow | 7,353 | 51.5% | $+1,615 | 7,353 | 51.5% | $+1,615 | $+0 | +0.0pp |
| poly_mint_sell_btc_15m | BTC | 15m | shadow | 7,938 | 42.4% | $+1,366 | 7,938 | 42.4% | $+1,366 | $+0 | +0.0pp |
| poly_mint_sell_eth_15m | ETH | 15m | shadow | 7,052 | 31.2% | $+946 | 7,052 | 31.2% | $+946 | $+0 | +0.0pp |
| poly_mint_sell_sol_5m | SOL | 5m | shadow | 4,079 | 40.5% | $+772 | 4,079 | 40.5% | $+772 | $+0 | +0.0pp |
| poly_updown_eth_15m_momo_v2_HOLD | ETH | 15m | paper | 88 | 67.0% | $+691 | 44 | 90.9% | $+853 | $+162 | +23.9pp |
| poly_updown_eth_15m_momo_v2_SELL | ETH | 15m | paper | 92 | 65.2% | $+652 | 45 | 86.7% | $+786 | $+135 | +21.4pp |
| poly_updown_btc_15m_momo_v2_HOLD | BTC | 15m | paper | 95 | 64.2% | $+639 | 59 | 93.2% | $+1,246 | $+607 | +29.0pp |
| poly_updown_btc_15m_momo_HOLD | BTC | 15m | paper | 68 | 66.2% | $+539 | 44 | 84.1% | $+740 | $+201 | +17.9pp |
| poly_updown_eth_15m_momo_v2_HEDGE | ETH | 15m | paper | 92 | 68.5% | $+535 | 47 | 91.5% | $+675 | $+140 | +23.0pp |
| poly_updown_btc_15m_momo_v2_SELL | BTC | 15m | paper | 98 | 50.0% | $+507 | 50 | 80.0% | $+902 | $+394 | +30.0pp |
| poly_updown_btc_15m_sniper | BTC | 15m | paper | 401 | 49.9% | $+491 | 196 | 89.3% | $+2,835 | $+2,344 | +39.4pp |
| poly_updown_sol_5m_momo_SELL | SOL | 5m | paper | 326 | 52.8% | $+429 | 262 | 59.9% | $+1,265 | $+836 | +7.2pp |
| poly_mint_sell_sol_15m | SOL | 15m | shadow | 4,330 | 20.2% | $+425 | 4,330 | 20.2% | $+425 | $+0 | +0.0pp |
| poly_updown_btc_15m_momo_v2_HEDGE | BTC | 15m | paper | 107 | 64.5% | $+417 | 67 | 94.0% | $+836 | $+420 | +29.5pp |
| poly_updown_btc_15m_momo_SELL | BTC | 15m | paper | 70 | 61.4% | $+416 | 40 | 72.5% | $+524 | $+108 | +11.1pp |
| poly_updown_btc_15m_momo_HEDGE | BTC | 15m | paper | 72 | 68.1% | $+379 | 47 | 85.1% | $+500 | $+121 | +17.1pp |
| poly_updown_sol_5m_momo_HEDGE | SOL | 5m | paper | 332 | 52.7% | $+265 | 260 | 61.1% | $+1,335 | $+1,069 | +8.4pp |
| poly_updown_eth_5m_v3_2 | ETH | 5m | paper | 24 | 66.7% | $+240 | 23 | 69.6% | $+242 | $+2 | +2.9pp |
| poly_updown_eth_5m_v3_3 | ETH | 5m | paper | 24 | 66.7% | $+240 | 23 | 69.6% | $+242 | $+2 | +2.9pp |
| poly_updown_sol_5m_momo_HOLD | SOL | 5m | paper | 326 | 53.1% | $+239 | 256 | 61.7% | $+1,286 | $+1,047 | +8.7pp |
| poly_updown_eth_5m_v4 | ETH | 5m | paper | 17 | 64.7% | $+173 | 16 | 68.8% | $+175 | $+2 | +4.0pp |
| poly_updown_eth_5m_v3_1 | ETH | 5m | paper | 20 | 60.0% | $+146 | 19 | 63.2% | $+148 | $+2 | +3.2pp |
| poly_updown_eth_5m_v3 | ETH | 5m | paper | 41 | 46.3% | $+125 | 39 | 48.7% | $+128 | $+3 | +2.4pp |
| poly_updown_sol_5m_v3_1 | SOL | 5m | paper | 207 | 53.1% | $+60 | 166 | 59.6% | $+521 | $+461 | +6.5pp |
| poly_updown_sol_5m_momo_v2_HOLD | SOL | 5m | paper | 271 | 51.7% | $+34 | 214 | 58.9% | $+809 | $+774 | +7.2pp |
| poly_updown_btc_5m_volume | BTC | 5m | paper | 1 | 0.0% | $-25 | 0 | 0.0% | $+0 | $+25 | +0.0pp |
| poly_updown_eth_5m_volume | ETH | 5m | paper | 1 | 0.0% | $-25 | 0 | 0.0% | $+0 | $+25 | +0.0pp |
| poly_updown_sol_5m_volume | SOL | 5m | paper | 1 | 0.0% | $-26 | 0 | 0.0% | $+0 | $+26 | +0.0pp |
| poly_updown_sol_5m_momo_v2_SELL | SOL | 5m | paper | 276 | 47.1% | $-107 | 214 | 54.2% | $+576 | $+683 | +7.1pp |
| poly_updown_sol_15m_momo_v2_SELL | SOL | 15m | paper | 61 | 45.9% | $-115 | 27 | 81.5% | $+440 | $+554 | +35.6pp |
| poly_updown_sol_5m_v4 | SOL | 5m | paper | 179 | 52.5% | $-116 | 146 | 58.2% | $+211 | $+328 | +5.7pp |
| poly_updown_sol_15m_momo_v2_HOLD | SOL | 15m | paper | 61 | 47.5% | $-133 | 26 | 88.5% | $+471 | $+604 | +40.9pp |
| poly_updown_sol_15m_momo_SELL | SOL | 15m | paper | 65 | 47.7% | $-144 | 24 | 100.0% | $+523 | $+667 | +52.3pp |
| poly_updown_btc_5m_momo_v2_HOLD | BTC | 5m | paper | 471 | 50.3% | $-158 | 378 | 60.3% | $+1,736 | $+1,894 | +10.0pp |
| poly_updown_sol_15m_momo_HOLD | SOL | 15m | paper | 62 | 46.8% | $-158 | 22 | 100.0% | $+519 | $+677 | +53.2pp |
| poly_updown_eth_5m_sniper | ETH | 5m | paper | 460 | 47.6% | $-202 | 368 | 54.6% | $+420 | $+622 | +7.0pp |
| poly_updown_eth_5m_sniper_DOWN_INV | ETH | 5m | paper | 213 | 51.2% | $-204 | 46 | 84.8% | $+691 | $+895 | +33.6pp |
| poly_updown_sol_15m_momo_v2_HEDGE | SOL | 15m | paper | 61 | 47.5% | $-211 | 24 | 87.5% | $+349 | $+560 | +40.0pp |
| poly_updown_sol_5m_momo_v2_HEDGE | SOL | 5m | paper | 277 | 52.0% | $-229 | 217 | 59.5% | $+524 | $+753 | +7.5pp |
| poly_updown_sol_15m_momo_HEDGE | SOL | 15m | paper | 64 | 48.4% | $-252 | 24 | 95.8% | $+380 | $+632 | +47.4pp |
| poly_updown_btc_5m_v3_1 | BTC | 5m | paper | 209 | 57.4% | $-281 | 168 | 68.5% | $-20 | $+260 | +11.0pp |
| poly_updown_sol_5m_v3_2 | SOL | 5m | paper | 260 | 51.1% | $-281 | 206 | 55.8% | $+173 | $+454 | +4.7pp |
| poly_updown_btc_5m_v4 | BTC | 5m | paper | 155 | 56.1% | $-300 | 133 | 63.2% | $-109 | $+190 | +7.0pp |
| poly_updown_sol_5m_v3 | SOL | 5m | paper | 249 | 50.6% | $-303 | 202 | 56.9% | $+312 | $+615 | +6.3pp |
| poly_updown_btc_5m_v3_2 | BTC | 5m | paper | 158 | 55.7% | $-311 | 134 | 62.7% | $-118 | $+194 | +7.0pp |
| poly_updown_btc_5m_v3_3 | BTC | 5m | paper | 158 | 55.7% | $-314 | 134 | 62.7% | $-120 | $+194 | +7.0pp |
| poly_updown_eth_15m_momo_HOLD | ETH | 15m | paper | 62 | 40.3% | $-316 | 24 | 100.0% | $+585 | $+901 | +59.7pp |
| poly_updown_btc_5m_v3 | BTC | 5m | paper | 239 | 56.1% | $-319 | 187 | 66.3% | $+12 | $+331 | +10.2pp |
| poly_updown_eth_15m_momo_SELL | ETH | 15m | paper | 64 | 32.8% | $-348 | 25 | 76.0% | $+412 | $+760 | +43.2pp |
| poly_updown_eth_5m_momo_HOLD | ETH | 5m | paper | 341 | 48.1% | $-398 | 274 | 55.1% | $+646 | $+1,043 | +7.0pp |
| poly_updown_eth_15m_momo_HEDGE | ETH | 15m | paper | 66 | 40.9% | $-407 | 25 | 96.0% | $+348 | $+755 | +55.1pp |
| poly_updown_sol_5m_v3_3 | SOL | 5m | paper | 215 | 49.8% | $-424 | 177 | 55.4% | $+32 | $+456 | +5.6pp |
| poly_updown_btc_5m_momo_v2_SELL | BTC | 5m | paper | 541 | 39.6% | $-444 | 414 | 49.0% | $+1,063 | $+1,506 | +9.5pp |
| poly_updown_eth_15m_volume_INV_NIGHT | ETH | 15m | paper | 554 | 50.2% | $-445 | 274 | 90.2% | $+5,122 | $+5,567 | +40.0pp |
| poly_updown_eth_5m_momo_SELL | ETH | 5m | paper | 346 | 45.1% | $-475 | 272 | 52.6% | $+448 | $+923 | +7.5pp |
| poly_updown_btc_5m_momo_v2_HEDGE | BTC | 5m | paper | 519 | 49.9% | $-509 | 400 | 61.5% | $+1,076 | $+1,585 | +11.6pp |
| poly_updown_eth_5m_momo_HEDGE | ETH | 5m | paper | 353 | 48.2% | $-515 | 280 | 55.7% | $+393 | $+908 | +7.6pp |
| poly_updown_eth_5m_momo_v2_SELL | ETH | 5m | paper | 333 | 42.9% | $-537 | 244 | 53.3% | $+413 | $+950 | +10.3pp |
| poly_updown_sol_15m_sniper | SOL | 15m | paper | 390 | 49.5% | $-628 | 186 | 84.4% | $+2,494 | $+3,122 | +34.9pp |
| poly_updown_sol_5m_sniper | SOL | 5m | paper | 548 | 50.5% | $-681 | 428 | 57.5% | $+330 | $+1,010 | +6.9pp |
| poly_updown_eth_5m_momo_v2_HEDGE | ETH | 5m | paper | 330 | 46.1% | $-691 | 241 | 55.6% | $+273 | $+965 | +9.5pp |
| poly_updown_btc_15m_volume_INV_NIGHT | BTC | 15m | paper | 553 | 48.8% | $-696 | 266 | 92.5% | $+5,343 | $+6,040 | +43.7pp |
| poly_updown_eth_5m_momo_v2_HOLD | ETH | 5m | paper | 316 | 46.2% | $-709 | 237 | 55.3% | $+531 | $+1,239 | +9.1pp |
| poly_updown_sol_5m_sniper_INV | SOL | 5m | paper | 518 | 50.0% | $-722 | 103 | 80.6% | $+1,374 | $+2,097 | +30.6pp |
| poly_updown_btc_5m_momo_HOLD | BTC | 5m | paper | 524 | 47.0% | $-905 | 406 | 56.9% | $+1,299 | $+2,204 | +9.9pp |
| poly_updown_sol_5m_volume_INV_NIGHT | SOL | 5m | paper | 1,293 | 51.2% | $-964 | 454 | 75.1% | $+4,890 | $+5,853 | +23.9pp |
| poly_updown_btc_5m_momo_SELL | BTC | 5m | paper | 551 | 43.9% | $-1,100 | 417 | 52.0% | $+853 | $+1,953 | +8.1pp |
| poly_updown_eth_15m_sniper | ETH | 15m | paper | 366 | 46.7% | $-1,180 | 193 | 80.8% | $+1,717 | $+2,897 | +34.1pp |
| poly_updown_btc_5m_momo_HEDGE | BTC | 5m | paper | 544 | 47.4% | $-1,189 | 419 | 58.0% | $+927 | $+2,116 | +10.6pp |
| poly_updown_btc_5m_volume_INV_NIGHT | BTC | 5m | paper | 1,646 | 49.8% | $-1,221 | 573 | 79.8% | $+7,963 | $+9,184 | +30.0pp |
| poly_updown_eth_5m_volume_INV_NIGHT | ETH | 5m | paper | 1,440 | 50.5% | $-1,277 | 511 | 75.7% | $+5,803 | $+7,079 | +25.2pp |
| poly_updown_sol_15m_volume_INV_NIGHT | SOL | 15m | paper | 538 | 47.4% | $-1,307 | 268 | 85.8% | $+4,329 | $+5,636 | +38.4pp |
| poly_updown_btc_5m_sniper | BTC | 5m | paper | 647 | 52.5% | $-1,474 | 488 | 61.3% | $-615 | $+859 | +8.7pp |

## Top 10 by F7 PnL improvement

| sleeve_id | cur_PnL | f7_PnL | improvement | cur_WR | f7_WR | n_skipped |
|---|---:|---:|---:|---:|---:|---:|
| poly_updown_btc_5m_volume_INV_NIGHT | $-1,221 | $+7,963 | **$+9,184** | 49.8% | 79.8% | 1073 |
| poly_updown_eth_5m_volume_INV_NIGHT | $-1,277 | $+5,803 | **$+7,079** | 50.5% | 75.7% | 929 |
| poly_updown_btc_15m_volume_INV_NIGHT | $-696 | $+5,343 | **$+6,040** | 48.8% | 92.5% | 287 |
| poly_updown_sol_5m_volume_INV_NIGHT | $-964 | $+4,890 | **$+5,853** | 51.2% | 75.1% | 839 |
| poly_updown_sol_15m_volume_INV_NIGHT | $-1,307 | $+4,329 | **$+5,636** | 47.4% | 85.8% | 270 |
| poly_updown_eth_15m_volume_INV_NIGHT | $-445 | $+5,122 | **$+5,567** | 50.2% | 90.2% | 280 |
| poly_updown_sol_15m_sniper | $-628 | $+2,494 | **$+3,122** | 49.5% | 84.4% | 204 |
| poly_updown_eth_15m_sniper | $-1,180 | $+1,717 | **$+2,897** | 46.7% | 80.8% | 173 |
| poly_updown_btc_15m_sniper | $+491 | $+2,835 | **$+2,344** | 49.9% | 89.3% | 205 |
| poly_updown_btc_5m_momo_HOLD | $-905 | $+1,299 | **$+2,204** | 47.0% | 56.9% | 118 |

## Sleeves where F7 HURTS (counter-examples / risks)

None — F7 helps every sleeve or stays neutral.


## Caveats

- Mode breakdown: only `paper` (momo) and `shadow` (mint_sell) — **no `live` events in this 30d window**.
- mint_sell sleeves: F7 applied based on signal direction inferred from outcome; not meaningful for pair-buy strategies.
- RSI on binance 1m closes — at the resolution timestamp (close to fire+resolve time).
- This is COUNTERFACTUAL — assumes filter had been live; reality would also depend on fill price drift.