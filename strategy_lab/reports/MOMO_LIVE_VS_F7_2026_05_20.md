# Momo VPS3 shadow + Ireland live sleeves — F7 RSI comparison — 2026-05-20

**Data pulled fresh today**:
- VPS3 (`storedata-vps3`) momo events last 14d: momo_events_14d.csv
- Ireland VPS (`vps`) maker shadow CSVs (May 19-20): 5 sleeves

## 1. VPS3 momo sleeves — current vs F7 vs F7_extreme

Direct queries on `trading.events`. F7 = RSI(14) on binance 1m agrees with signal direction.

### Aggregate (all momo sleeves)

| Config | n_trades | WR % | Sum PnL | $/trade |
|---|---:|---:|---:|---:|
| **Current production** | 10,166 | 47.97% | $-8,851.30 | $-0.8707 |
| **+ F7 filter** | 6,950 | 57.83% | $+23,522.86 | $3.3846 |
| **+ F7_extreme** | 5,120 | 65.00% | $+35,315.98 | $6.8977 |

**Swing**: $-8,851.30 → $+23,522.86 = **$+32,374.16** improvement over 14d.

=> **~$+2,312.44 / day** if F7 had been live.

### Per-sleeve detail (all momo, sorted by current PnL desc)

| sleeve_id | sym | tf | cur_n | cur_WR% | cur_PnL | f7_n | f7_WR% | f7_PnL | f7_Δ$ | f7x_WR% | f7x_PnL |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| poly_updown_eth_15m_momo_v2_HOLD | ETH | 15m | 121 | 68.6% | $+1,048 | 60 | 88.3% | $+1,090 | $+42 | 88.1% | $+753 |
| poly_updown_eth_15m_momo_v2_SELL | ETH | 15m | 123 | 68.3% | $+959 | 61 | 85.2% | $+923 | $-36 | 87.2% | $+585 |
| poly_updown_eth_15m_momo_v2_HEDGE | ETH | 15m | 125 | 69.6% | $+834 | 63 | 88.9% | $+805 | $-28 | 88.6% | $+540 |
| poly_updown_btc_15m_momo_v2_HOLD | BTC | 15m | 127 | 63.0% | $+779 | 79 | 81.0% | $+1,184 | $+405 | 80.7% | $+831 |
| poly_updown_btc_15m_momo_v2_SELL | BTC | 15m | 127 | 49.6% | $+551 | 67 | 65.7% | $+743 | $+192 | 66.0% | $+494 |
| poly_updown_btc_15m_momo_v2_HEDGE | BTC | 15m | 141 | 63.8% | $+443 | 89 | 83.2% | $+661 | $+218 | 82.8% | $+442 |
| poly_updown_btc_15m_momo_HOLD | BTC | 15m | 96 | 58.3% | $+387 | 54 | 74.1% | $+636 | $+249 | 78.8% | $+465 |
| poly_updown_btc_15m_momo_SELL | BTC | 15m | 100 | 52.0% | $+213 | 52 | 57.7% | $+369 | $+156 | 67.7% | $+390 |
| poly_updown_btc_15m_momo_HEDGE | BTC | 15m | 101 | 60.4% | $+175 | 58 | 75.9% | $+344 | $+168 | 78.1% | $+362 |
| poly_updown_sol_5m_momo_SELL | SOL | 5m | 377 | 50.4% | $+45 | 285 | 57.9% | $+1,065 | $+1,021 | 65.4% | $+1,495 |
| poly_updown_sol_15m_momo_v2_SELL | SOL | 15m | 81 | 49.4% | $+9 | 39 | 74.4% | $+519 | $+510 | 78.6% | $+439 |
| poly_updown_sol_15m_momo_v2_HOLD | SOL | 15m | 81 | 50.6% | $-10 | 38 | 79.0% | $+550 | $+560 | 81.5% | $+440 |
| poly_updown_sol_15m_momo_v2_HEDGE | SOL | 15m | 81 | 50.6% | $-88 | 36 | 77.8% | $+428 | $+516 | 80.8% | $+418 |
| poly_updown_sol_5m_momo_HOLD | SOL | 5m | 378 | 51.1% | $-97 | 279 | 59.5% | $+1,085 | $+1,182 | 66.8% | $+1,559 |
| poly_updown_sol_5m_momo_HEDGE | SOL | 5m | 386 | 50.5% | $-143 | 283 | 59.0% | $+1,135 | $+1,279 | 66.8% | $+1,570 |
| poly_updown_eth_15m_momo_HOLD | ETH | 15m | 79 | 44.3% | $-230 | 34 | 91.2% | $+697 | $+927 | 88.5% | $+504 |
| poly_updown_sol_15m_momo_HOLD | SOL | 15m | 79 | 45.6% | $-247 | 30 | 86.7% | $+511 | $+758 | 77.8% | $+223 |
| poly_updown_sol_15m_momo_SELL | SOL | 15m | 81 | 45.7% | $-256 | 31 | 87.1% | $+492 | $+748 | 75.0% | $+181 |
| poly_updown_eth_15m_momo_HEDGE | ETH | 15m | 83 | 44.6% | $-298 | 35 | 88.6% | $+483 | $+781 | 85.2% | $+290 |
| poly_updown_eth_5m_momo_HOLD | ETH | 5m | 392 | 48.7% | $-341 | 298 | 54.4% | $+577 | $+919 | 60.9% | $+1,161 |
| poly_updown_eth_5m_momo_SELL | ETH | 5m | 402 | 45.5% | $-347 | 302 | 51.0% | $+426 | $+773 | 58.5% | $+1,175 |
| poly_updown_btc_5m_momo_v2_HOLD | BTC | 5m | 588 | 49.7% | $-363 | 434 | 58.8% | $+1,654 | $+2,017 | 66.5% | $+2,544 |
| poly_updown_sol_15m_momo_HEDGE | SOL | 15m | 81 | 46.9% | $-365 | 32 | 84.4% | $+347 | $+712 | 75.0% | $+157 |
| poly_updown_eth_15m_momo_SELL | ETH | 15m | 81 | 38.3% | $-366 | 35 | 74.3% | $+420 | $+786 | 81.8% | $+231 |
| poly_updown_eth_5m_momo_HEDGE | ETH | 5m | 406 | 48.5% | $-400 | 306 | 54.6% | $+371 | $+771 | 59.6% | $+1,162 |
| poly_updown_sol_5m_momo_v2_HOLD | SOL | 5m | 326 | 48.2% | $-540 | 239 | 56.1% | $+558 | $+1,098 | 65.9% | $+1,249 |
| poly_updown_sol_5m_momo_v2_SELL | SOL | 5m | 333 | 44.1% | $-584 | 239 | 51.9% | $+338 | $+922 | 63.2% | $+1,111 |
| poly_updown_sol_5m_momo_v2_HEDGE | SOL | 5m | 338 | 47.6% | $-669 | 242 | 56.6% | $+292 | $+960 | 66.5% | $+1,071 |
| poly_updown_btc_5m_momo_v2_SELL | BTC | 5m | 655 | 38.5% | $-845 | 474 | 47.3% | $+950 | $+1,795 | 58.2% | $+2,104 |
| poly_updown_eth_5m_momo_v2_SELL | ETH | 5m | 403 | 41.4% | $-973 | 277 | 51.3% | $+237 | $+1,211 | 56.9% | $+918 |
| poly_updown_btc_5m_momo_v2_HEDGE | BTC | 5m | 666 | 49.2% | $-976 | 472 | 59.1% | $+907 | $+1,883 | 66.4% | $+1,992 |
| poly_updown_eth_5m_momo_v2_HEDGE | ETH | 5m | 404 | 44.8% | $-999 | 273 | 53.5% | $+97 | $+1,096 | 60.6% | $+909 |
| poly_updown_eth_5m_momo_v2_HOLD | ETH | 5m | 384 | 45.0% | $-1,071 | 269 | 53.2% | $+316 | $+1,387 | 61.0% | $+1,056 |
| poly_updown_btc_5m_momo_HOLD | BTC | 5m | 626 | 46.3% | $-1,282 | 451 | 55.0% | $+1,021 | $+2,303 | 64.4% | $+2,375 |
| poly_updown_btc_5m_momo_SELL | BTC | 5m | 656 | 43.6% | $-1,296 | 466 | 50.2% | $+606 | $+1,902 | 60.9% | $+2,019 |
| poly_updown_btc_5m_momo_HEDGE | BTC | 5m | 658 | 45.9% | $-1,509 | 468 | 55.6% | $+685 | $+2,194 | 64.7% | $+2,100 |

### Top 15 sleeves by F7 PnL improvement

| sleeve_id | cur_n | cur_WR% | cur_PnL | f7_n | f7_WR% | f7_PnL | improvement |
|---|---:|---:|---:|---:|---:|---:|---:|
| poly_updown_btc_5m_momo_HOLD | 626 | 46.3% | $-1,282 | 451 | 55.0% | $+1,021 | **$+2,303** |
| poly_updown_btc_5m_momo_HEDGE | 658 | 45.9% | $-1,509 | 468 | 55.6% | $+685 | **$+2,194** |
| poly_updown_btc_5m_momo_v2_HOLD | 588 | 49.7% | $-363 | 434 | 58.8% | $+1,654 | **$+2,017** |
| poly_updown_btc_5m_momo_SELL | 656 | 43.6% | $-1,296 | 466 | 50.2% | $+606 | **$+1,902** |
| poly_updown_btc_5m_momo_v2_HEDGE | 666 | 49.2% | $-976 | 472 | 59.1% | $+907 | **$+1,883** |
| poly_updown_btc_5m_momo_v2_SELL | 655 | 38.5% | $-845 | 474 | 47.3% | $+950 | **$+1,795** |
| poly_updown_eth_5m_momo_v2_HOLD | 384 | 45.0% | $-1,071 | 269 | 53.2% | $+316 | **$+1,387** |
| poly_updown_sol_5m_momo_HEDGE | 386 | 50.5% | $-143 | 283 | 59.0% | $+1,135 | **$+1,279** |
| poly_updown_eth_5m_momo_v2_SELL | 403 | 41.4% | $-973 | 277 | 51.3% | $+237 | **$+1,211** |
| poly_updown_sol_5m_momo_HOLD | 378 | 51.1% | $-97 | 279 | 59.5% | $+1,085 | **$+1,182** |
| poly_updown_sol_5m_momo_v2_HOLD | 326 | 48.2% | $-540 | 239 | 56.1% | $+558 | **$+1,098** |
| poly_updown_eth_5m_momo_v2_HEDGE | 404 | 44.8% | $-999 | 273 | 53.5% | $+97 | **$+1,096** |
| poly_updown_sol_5m_momo_SELL | 377 | 50.4% | $+45 | 285 | 57.9% | $+1,065 | **$+1,021** |
| poly_updown_sol_5m_momo_v2_HEDGE | 338 | 47.6% | $-669 | 242 | 56.6% | $+292 | **$+960** |
| poly_updown_eth_15m_momo_HOLD | 79 | 44.3% | $-230 | 34 | 91.2% | $+697 | **$+927** |

### Sleeves where F7 HURTS (counter-examples)

| sleeve_id | cur_n | cur_WR% | cur_PnL | f7_n | f7_WR% | f7_PnL | loss |
|---|---:|---:|---:|---:|---:|---:|---:|
| poly_updown_eth_15m_momo_v2_SELL | 123 | 68.3% | $+959 | 61 | 85.2% | $+923 | **$-36** |
| poly_updown_eth_15m_momo_v2_HEDGE | 125 | 69.6% | $+834 | 63 | 88.9% | $+805 | **$-28** |

## 2. Ireland VPS maker sleeves (May 19-20 data)

These are PAT/ACC-M/MAS strategies — NOT directional. F7 RSI filter does not apply directly. Reporting current per-slug PnL aggregates.

| sleeve | n_slugs | n_winners | WR % | Sum PnL | $/slug | n_POST | n_FILL | n_MERGE | n_TAKE | n_log | F7 note |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| mas | 57 | 0 | 0.0% | $-239.63 | $-4.2040 | 62 | 0 | 0 | 0 | 175 | F7 N/A — pair-arb / mint-sell not directional |
| acc-pc | 8 | 0 | 0.0% | $-263.57 | $-32.9459 | 1,056 | 0 | 0 | 30 | 2,086 | F7 N/A — pair-arb / mint-sell not directional |
| acc-m | 29 | 0 | 0.0% | $-525.39 | $-18.1169 | 2,536 | 0 | 0 | 160 | 5,176 | F7 N/A — pair-arb / mint-sell not directional |
| acc-h | 41 | 0 | 0.0% | $-3,474.33 | $-84.7398 | 3,925 | 0 | 0 | 3,622 | 11,169 | F7 N/A — pair-arb / mint-sell not directional |
| pat-shadow | 22 | 0 | 0.0% | $-5,218.84 | $-237.2201 | 0 | 0 | 0 | 1,528 | 1,528 | F7 N/A — pair-arb / mint-sell not directional |

### Why F7 doesn't apply to Ireland sleeves

F7 filter requires a directional signal (UP/DOWN) to filter by RSI agreement:
- `acc-m`: posts BIDs on BOTH sides when `sum_bids < $1` — NOT directional
- `acc-h`: composite taker with 4 sub-rules (discount-capture, sharp-drop, early-slot, buy-pressure) — only ACC-H's `buy_pressure` sub-rule has direction inherent
- `acc-pc`: pair-completion taker, reacts to OWN inventory imbalance — semi-directional but signal is from book, not market direction
- `mas`: mint-and-sell, posts ASKs both sides after minting — NOT directional
- `pat-shadow`: pure pair-arb taker, fires when sum_asks < $1 — NOT directional

To apply F7 to ANY of these, we'd need to:
1. Pick a synthetic 'signal direction' (e.g. side with higher RSI)
2. Skip fires where RSI disagrees with that synthetic signal

This is a research experiment, NOT the F7 the user asked about. The F7 alpha demonstrated on momo paper data (74% WR) is specific to **directional bets**. Ireland's maker bots don't make directional bets.

## 3. Summary recommendation

**Momo on VPS3 (directional)**: Apply F7 filter immediately. Expected lift: see Section 1 aggregate.
- Add `rsi_14_at_ws` to the momo signal payload (computed at fire time)
- Filter: skip fire if `(signal==UP and rsi<50) or (signal==DOWN and rsi>50)`
- Test variants:
  - F7: `rsi >= 50` agreement → biggest universe
  - F7_extreme: `rsi >= 60 / <= 40` → smaller universe, higher WR

**Ireland maker bots (non-directional)**: F7 not applicable. Use the existing shadow data to validate the recent maker bot deployment instead. Separate analysis stream.

## 4. Files

- `C:\Users\alexandre bandarra\Desktop\global\strategy_lab\results\meta_classifier\momo_live_vs_f7.csv` — VPS3 per-sleeve table
- `C:\Users\alexandre bandarra\Desktop\global\strategy_lab\results\meta_classifier\ireland_live_sleeves.csv` — Ireland per-sleeve table
- `C:\Users\alexandre bandarra\Desktop\global\strategy_lab\monitoring\_logs\vps3\momo_events_14d.csv` — raw 159k VPS3 momo events (signal + resolution + hedge_skip)
- `C:\Users\alexandre bandarra\Desktop\global\strategy_lab\monitoring\_logs\ireland/*.csv` — raw Ireland maker shadow CSVs
