# Maker-order experiment — 11 gated sleeves

**Hypothesis**: instead of taking the book at `fire_us` (current production), place a *maker* buy limit at a passive price (best_bid, bid+1 tick, mid, ask−1 tick) and let it sit from `fire_us + 85 ms` until `slot_end_us`. Compare maker PnL vs taker PnL (current model).

**Runner**: [strategy_lab/markov_filter/maker_vs_taker_gated_sleeves.py](strategy_lab/markov_filter/maker_vs_taker_gated_sleeves.py)
**Outputs**: [maker_per_fire.csv](strategy_lab/markov_filter/_results/maker_per_fire.csv) (15 844 rows = 1 265 fires × 4 placements × up to 4 notionals), [maker_per_sleeve.csv](strategy_lab/markov_filter/_results/maker_per_sleeve.csv), [maker_best_per_sleeve.csv](strategy_lab/markov_filter/_results/maker_best_per_sleeve.csv).

## Fill model

For each fire, place a buy limit at price `P`:
- Get entry book at `fire_us + 85 ms` (latency-shifted)
- For every subsequent L25 snapshot in `(fire_us + 85 ms, slot_end_us]`:
  - **Fill condition**: `best_ask[t] ≤ P` (an aggressor crossed our level)
  - Fill at price `P`, size = `notional / P` (all-or-nothing)
- If condition never satisfied → no fill, no PnL, no fee.

PnL:
- **Maker filled**: pnl = `shares × (1 − P)` if won, `−shares × P` if lost. **No entry fee** (CLAUDE.md 2026-05-22 verification: maker fee = 0 on BTC/ETH/SOL up-down markets).
- **Taker (baseline)**: book walk at fire_us with 2 %-on-profit-only fee (production rule).

## Best maker placement per sleeve (at practical notional)

| sleeve | $N | best place | mean limit P | taker vwap | save / share | fill rate % | mean fill Δt (s) | WR % | WR fld % | adv sel pp | maker $ | taker $ | maker lift $ |
|---|--:|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| sniper_btc_15m_HOD     | 1000 | P_bid   | 0.48 | 0.55 | 0.07 | 91.7 |  75.2 | 60.98 | 57.45 | 3.53 | **+$37 977** | +$23 180 | **+$14 796** |
| momo_v2_btc_5m_HOD+MTF2 | 1000 | P_bid   | 0.48 | 0.52 | 0.04 | 100.0 | 119.1 | 59.54 | 59.54 | 0.00 | **+$30 077** | +$18 249 | **+$11 828** |
| momo_v1_btc_15m_HOD    | 1000 | P_bid   | 0.49 | 0.53 | 0.04 | 98.1 | 422.9 | 75.93 | 75.47 | 0.46 | **+$28 726** | +$22 645 | **+$6 081**  |
| sniper_btc_5m_HOD      | 1000 | P_bid   | 0.48 | 0.54 | 0.06 | 90.0 |  24.1 | 57.92 | 53.24 | 4.68 | **+$24 556** | +$16 610 | **+$7 946**  |
| momo_v2_btc_15m_HOD    | 1000 | P_bid   | 0.49 | 0.53 | 0.04 | 94.1 | 515.2 | 69.12 | 67.19 | 1.93 | **+$23 137** | +$19 532 | **+$3 605**  |
| sniper_eth_15m_HOD+M5va | 1000 | P_bid   | 0.46 | 0.56 | 0.10 | 89.4 |  50.2 | 70.21 | 66.67 | 3.54 | **+$19 084** | +$12 570 | **+$6 513**  |
| momo_v2_eth_15m_HOD    | 1000 | P_bid   | 0.49 | 0.54 | 0.05 | 95.7 | 556.3 | 68.09 | 66.67 | 1.42 | **+$16 674** | +$12 211 | **+$4 463**  |
| sniper_sol_5m_HOD      | 500  | P_mid   | 0.49 | 0.58 | 0.09 | 83.8 |  29.8 | 70.48 | 64.77 | 5.71 | **+$14 251** | +$10 529 | **+$3 722**  |
| sniper_eth_5m_HOD      | 500  | P_ask-1 | 0.47 | 0.54 | 0.07 | 90.7 |  32.3 | 57.69 | 53.33 | 4.36 | **+$11 557** | +$6 503  | **+$5 054**  |
| momo_v2_sol_5m_HOD     | 500  | P_ask-1 | 0.49 | 0.56 | 0.07 | 87.1 | 215.1 | 62.90 | 57.41 | 5.49 | **+$9 119**  | +$6 640  | **+$2 479**  |
| momo_v2_sol_15m_HOD    | 100  | P_bid   | 0.49 | 0.54 | 0.05 | 94.4 | 661.5 | 55.56 | 52.94 | 2.62 | **+$267**    | +$86     | **+$181**    |
| **TOTAL (11 sleeves)** |       |         |      |      |      |      |       |       |       |      | **+$215 425** | **+$150 755** | **+$64 670** |

Maker total = **+$215 425 / 28 d ≈ +$7 694 / day**.
Maker lift vs taker = **+$64 670 / 28 d ≈ +$2 310 / day** of pure savings on the same trade signals.

## Maker sum PnL ($) by placement at $1 000 notional

| sleeve | P_bid | P_bid+1 | P_mid | P_ask−1 | taker baseline |
|---|--:|--:|--:|--:|--:|
| momo_v1_btc_15m_HOD     | **28 726** | 10 211 | 17 642 | 27 309 | 22 645 |
| momo_v2_btc_15m_HOD     | **23 137** |  2 984 | 15 309 | 21 891 | 19 532 |
| momo_v2_btc_5m_HOD+MTF2 | **30 077** |  4 656 | 21 180 | 27 917 | 18 249 |
| momo_v2_eth_15m_HOD     | **16 674** | 12 932 | 13 032 | 16 318 | 12 211 |
| momo_v2_sol_15m_HOD     |  **2 672** | −1 066 |   −726 |  2 478 | −2 647 |
| momo_v2_sol_5m_HOD      | 17 870 |  6 148 | 11 615 | **18 238** |  4 958 |
| sniper_btc_15m_HOD      | **37 977** | 25 261 | 30 307 | 37 233 | 23 180 |
| sniper_btc_5m_HOD       | **24 556** | −8 715 | 11 243 | 23 167 | 16 610 |
| sniper_eth_15m_HOD+M5va | **19 084** |  2 678 | 14 107 | 18 894 | 12 570 |
| sniper_eth_5m_HOD       | 21 598 | 10 053 | 17 279 | **23 114** |    124 |
| sniper_sol_5m_HOD       | 25 902 | 23 060 | **28 502** | 28 210 |  7 734 |

**P_bid (post at best_bid) is the winning placement in 8 / 11 sleeves.** P_bid+1 (one tick *above* best_bid) is consistently the WORST — it gives up the price advantage without improving fill rate enough.

## Aggregate maker vs taker across all 11 sleeves at each notional

| notional | placement | maker $ | taker $ | maker lift $ |
|--:|---|--:|--:|--:|
|   $25 | P_bid     |   6 207 |   7 678 | **−1 471** |
|   $25 | P_ask−1   |   6 119 |   7 678 | **−1 559** |
|   $25 | P_mid     |   4 487 |   5 563 | **−1 076** |
|   $25 | P_bid+1   |   2 205 |   2 570 |   −365     |
|  $100 | P_bid     |  24 827 |  28 103 | **−3 276** |
|  $100 | P_ask−1   |  24 477 |  28 103 |   −3 626   |
|  $100 | P_mid     |  17 949 |  20 260 |   −2 311   |
|  $500 | P_bid     | 124 136 | 101 961 | **+22 174** |
|  $500 | P_ask−1   | 122 384 | 101 961 |   +20 423 |
|  $500 | P_mid     |  89 745 |  72 005 |   +17 740 |
| $1000 | P_bid     | 248 272 | 135 166 | **+113 106** |
| $1000 | P_ask−1   | 244 769 | 135 166 |   +109 603 |
| $1000 | P_mid     | 179 490 |  91 976 |    +87 514 |

**Two regimes, separated by ≈ $200 stake:**
- **Under ~$200**: taker wins. The taker fills 100 % of fires at the ask (a tight 0.02 spread), while maker forgoes ~10 % of fires that never get filled. Forgone wins outweigh the saved spread.
- **Above ~$500**: maker wins decisively. Taker slippage explodes as it walks deep into L25 (median 1 200 bp by $1 000), while maker price stays anchored at best_bid. The saved per-share price advantage scales linearly with notional.

## Adverse-selection signal (real, but manageable)

| placement | mean WR % | mean WR-when-filled % | mean fill rate % | adverse-sel (pp) |
|---|--:|--:|--:|--:|
| P_ask−1 | 64.17 | 60.87 | 91.75 | **3.30** |
| P_bid   | 64.17 | 60.85 | 91.84 | **3.32** |
| P_mid   | 63.23 | 60.47 | 93.09 | **2.76** |
| P_bid+1 | 62.72 | 60.89 | 95.53 | 1.83 |

Across every placement, **WR-when-filled is 1.8 – 3.3 pp below the overall WR** — confirming that maker fills cluster on the trades that go on to LOSE (price came down to our bid because the directional signal was wrong). But the spread savings (~6–10 ¢ per share = 12–20 % of notional) more than compensate.

## Fill-rate observations

| placement | mean fill rate | mean fill Δt (s) |
|---|--:|--:|
| P_ask−1 | 91.7 % |  72 s |
| P_bid   | 91.8 % | 215 s |
| P_mid   | 93.1 % |  90 s |
| P_bid+1 | 95.5 % | 180 s |

Even at the most passive placement (`P_bid`), 92 % of orders fill within the slot window. Polymarket up/down markets are volatile enough that prices oscillate through every level multiple times per slot. Mean wait to fill ranges from ~25 s (sniper_btc_5m, fast 5 m slots, near-spread) to ~660 s (momo_v2_sol_15m, 15 m slot, deep placement).

## ⚠ Critical caveats — model is OPTIMISTIC

These backtest numbers are an **upper bound**, not an expectation. Three model simplifications inflate the result:

1. **Zero queue position assumed.** Real maker orders sit in a FIFO queue at their price level. If 800 shares are already resting at $0.48 and only 200 shares aggressively sell into us, we get 0 fill — those 800 shares ahead of us soak the flow. Realistic queue position factor for an "unprivileged" maker on Polymarket is on the order of 10–30 % effective fill share. **Apply 0.10–0.30 multiplier to maker lift estimates**.
2. **All-or-nothing fill assumed.** The model treats one snapshot crossing our limit as a full notional fill. In reality only the aggressor's size fills, and many fills will be partial (5–25 shares at a time). Subsequent fills require more aggressors.
3. **No fee verification at large size.** The CLAUDE.md "maker fee = 0" check was on small orders. Polymarket may apply different fee schedules above certain notional thresholds — needs verification before deploying at $500 +.

**More realistic deployment expectation**: take the modelled maker lift, multiply by ~0.20 for queue effect, and you get **+$13 000 / 28 d ≈ +$465 / day** of pure maker savings on top of the existing gated taker. Still meaningful but not the headline +$2 310 / day.

## Recommended next steps

1. **Build a queue-aware fill model.** For each fire, record the resting bid size at our chosen placement at `fire_us`. Use trade-flow data (need to pull from Polymarket trades parquet) to count aggressor sell volume at that level over the slot window. Fill = `min(notional / P, max(0, aggressor_volume − resting_queue_ahead))`.
2. **Hybrid maker → taker fallback.** Place maker for the first `T` seconds of the slot (e.g. 60 s); if not filled by then, cross with a taker. This caps the "miss" downside while keeping most of the maker upside.
3. **Live shadow.** Pick the top 3 sleeves by maker lift (`sniper_btc_15m_HOD`, `momo_v2_btc_5m_HOD+MTF2`, `momo_v1_btc_15m_HOD`) and deploy a maker SHADOW companion to each. Wire the existing TV-agent SHADOW infra to log every maker order's fill state and realised price. After 7 days, compare realised maker share-fill rate vs the 92 % modelled here. If realised fill rate ≥ 30 % the strategy is profitable; if < 15 % the queue dominance kills it.
4. **Maker rebate verification.** Re-check whether the Polymarket maker rebate is currently 0 % via the API (`feeRate`, `feesEnabled`) for these specific BTC/ETH/SOL up/down markets. If it's actually paying (per docs it's `0.20 × feeRate × p × (1−p) × shares`), add it to the maker PnL — at $1 000 fills on 50-cent markets that's ~+$1 per fill = +$1 200 / 28 d additional.
