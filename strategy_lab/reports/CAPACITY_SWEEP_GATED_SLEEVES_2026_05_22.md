# Capacity sweep — 11 gated sleeves on L25 sub-second books

**Source data**: gated fires from `backtest_prod_strategies_with_gates.py` (F7-off universe, 28d, Apr 22 → May 21 2026, n = 1 265 fires across 11 sleeves), L25 streaming books from `data/v4/canonical` (latency-shifted strict-asof lookup, `min_book_events=0` matching `LegacyConfig`), fee model = production 2 %-on-profit-only (CLAUDE.md verified rule).
**Runner**: `strategy_lab/markov_filter/capacity_sweep_gated_sleeves.py`
**Outputs**:
- `strategy_lab/markov_filter/_results/capacity_sweep_per_fire.csv` (11 322 rows — every fire × 9 sizes)
- `strategy_lab/markov_filter/_results/capacity_sweep_per_sleeve.csv` (sleeve × notional)
- `strategy_lab/markov_filter/_results/capacity_optimal_three_lenses.csv`

## Method

For every gated-sleeve fire, walk the L25 ASK ladder at the latency-shifted fire timestamp at each of nine candidate notionals: **$25, $50, $100, $250, $500, $1 000, $2 500, $5 000, $10 000**. Then compute hold PnL with production 2 %-on-profit fee. Aggregate per (sleeve, notional).

Three "optimal" picks, because **the right notional depends on the constraint**:

| lens | rule | answers the question |
|---|---|---|
| **max-sum** | Largest size with `fill_rate ≥ 0.95` and max `sum_$` | What size produces the biggest pile of $ over 28d? |
| **practical** | `share_underfilled < 10 %` and `per_trade_$ ≥ 80 %` of peak | How big can I go without choking on book depth and without slippage cutting my edge by more than 20 %? |
| **micro 25 %** | `notional ≤ 25 % of median L25 front-25 depth` | How big stays safe under microstructure rule-of-thumb (avoid taking more than ¼ of visible depth)? |

## Optimal notional per sleeve — three lenses

Sleeves sorted by **max-sum PnL** (highest absolute $ over 28d).

| sleeve | WR % | L25 depth med ($) | max-sum N | max-sum sum_$ | per-tr $ | slip bp | under % | practical N | practical sum_$ | micro N | micro sum_$ |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| momo_v1_btc_15m_HOD     | 75.93 | 13 075 | **$10 000** | **+$118 292** | $2 191 | 2 255 | 14.8 % | $5 000 | +$80 314 | $2 500 | +$47 921 |
| momo_v2_btc_15m_HOD     | 69.12 | 13 771 | **$10 000** | **+$79 662**  | $1 172 | 2 239 | 13.2 % | $5 000 | +$62 189 | $2 500 | +$39 724 |
| momo_v2_eth_15m_HOD     | 68.09 | 11 155 | **$5 000**  | **+$33 064**  | $703   | 1 821 | 0.0 %  | $5 000 | +$33 064 | $2 500 | +$23 134 |
| sniper_btc_15m_HOD      | 62.19 | 5 299  | **$1 000**  | **+$28 270**  | $141   | 1 188 | 0.0 %  | $2 500 | +$23 778 | $1 000 | +$28 270 |
| momo_v2_btc_5m_HOD+MTF2 | 59.54 | 6 736  | **$2 500**  | **+$21 427**  | $164   | 1 270 | 0.8 %  | $2 500 | +$21 427 | $1 000 | +$18 249 |
| sniper_btc_5m_HOD       | 58.23 | 4 016  | **$1 000**  | **+$19 593**  | $83    | 918   | 0.0 %  | $1 000 | +$19 593 | $1 000 | +$19 593 |
| sniper_eth_15m_HOD+M5va | 70.21 | 4 025  | **$2 500**  | **+$17 640**  | $375   | 3 023 | 21.3 % | $1 000 | +$12 570 | $1 000 | +$12 570 |
| sniper_sol_5m_HOD       | 67.94 | 979    | **$500**    | **+$10 251**  | $78    | 1 727 | 7.6 %  | $500   | +$10 251 | $100   | +$3 639  |
| sniper_eth_5m_HOD       | 57.69 | 2 619  | **$500**    | **+$6 726**   | $37    | 1 243 | 0.0 %  | $500   | +$6 726  | $500   | +$6 726  |
| momo_v2_sol_5m_HOD      | 62.90 | 1 898  | **$500**    | **+$6 640**   | $54    | 1 186 | 0.0 %  | $500   | +$6 640  | $250   | +$4 680  |
| momo_v2_sol_15m_HOD     | 55.56 | 3 633  | **$100**    | **+$86**      | $2     | 699   | 0.0 %  | $100   | +$86     | $500   | −$673    |

**Aggregate (11 sleeves, 28 d)**:

| lens | aggregate sum_$ | vs $25 baseline |
|---|--:|--:|
| max-sum (capital unconstrained) | **+$341 651** | ×49.1 |
| practical (10 % underfill cap) | **+$276 639** | ×39.7 |
| micro 25 % depth rule | **+$203 833** | ×29.3 |
| baseline $25 stake | +$6 962 | × 1.0 |

## Full capacity curves

### Sum $ PnL by notional (rows = sleeve, cols = $ stake)

| sleeve | $25 | $50 | $100 | $250 | $500 | $1k | $2.5k | $5k | $10k |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| momo_v1_btc_15m_HOD     | 667 | 1 328 | 2 626 | 6 391 | 12 251 | 22 645 | 47 921 | 80 314 | **118 292** |
| momo_v2_btc_15m_HOD     | 596 | 1 181 | 2 318 | 5 576 | 10 624 | 19 532 | 39 724 | 62 189 | **79 662**  |
| momo_v2_btc_5m_HOD+MTF2 | 624 | 1 243 | 2 452 | 5 885 | 10 936 | 18 249 | **21 427** | −3 833 | −44 990 |
| momo_v2_eth_15m_HOD     | 408 |   801 | 1 554 | 3 681 |  6 885 | 12 211 | 23 134 | **33 064** | 28 706 |
| momo_v2_sol_15m_HOD     |  55 |    78 |   **86** |   −58 |   −673 | −2 647 | −11 293 | −29 303 | −59 187 |
| momo_v2_sol_5m_HOD      | 679 | 1 267 | 2 314 | 4 680 | **6 640** |  4 958 | −8 233 | −22 696 | −31 184 |
| sniper_btc_15m_HOD      |1 275| 2 505 | 4 840 |11 066 | 19 089 | **28 270** | 23 778 | 1 476 | −20 505 |
| sniper_btc_5m_HOD       |1 060| 2 065 | 3 932 | 8 770 | 14 928 | **19 593** | −7 485 | −54 334 | −82 434 |
| sniper_eth_15m_HOD+M5va | 554 | 1 081 | 2 070 | 4 610 |  7 987 | 12 570 | **17 640** | 19 000 | 10 574 |
| sniper_eth_5m_HOD       | 838 | 1 566 | 2 841 | 5 520 |  **6 726** |    507 | −26 658 | −44 703 | −52 206 |
| sniper_sol_5m_HOD       |1 052| 1 973 | 3 639 | 7 489 | **10 251**|  7 734 |  4 086 |  3 117 |  3 419 |

**Bold = sleeve max.** Three structural shapes:

1. **BTC 15m sleeves** (momo_v1, momo_v2, sniper) — books are deep (median depth $5k–$14k), curves keep growing through $10k (max-sum picks $10k). But slippage hits 22 % by then and 13–15 % of fires partially underfill.
2. **5m and ETH/SOL 15m sleeves** — clear interior maximum. Optimum lands at $500–$2 500 depending on sleeve. Beyond it, slippage swamps the directional edge and PnL flips negative.
3. **SOL 15m momo_v2** — already failing the robustness test (binom p = 0.40); capacity curve confirms it: optimal is $100 with $86 over 28d. Drop.

### Per-trade $ PnL — where slippage starts winning

| sleeve | $25 | $100 | $500 | $1k | $2.5k | $5k | $10k |
|---|--:|--:|--:|--:|--:|--:|--:|
| momo_v1_btc_15m_HOD     | 12.4 | 48.6 | 226.9 | 419.4 |  887.4 |1 487.3 |2 190.6 |
| momo_v2_btc_15m_HOD     |  8.8 | 34.1 | 156.2 | 287.2 |  584.2 |  914.5 |1 171.5 |
| momo_v2_btc_5m_HOD+MTF2 |  4.8 | 18.7 |  83.5 | 139.3 |  163.6 |  −29.3 | −343.4 |
| momo_v2_eth_15m_HOD     |  8.7 | 33.1 | 146.5 | 259.8 |  492.2 |  703.5 |  610.8 |
| momo_v2_sol_15m_HOD     |  1.5 |  2.4 | −18.7 | −73.5 | −313.7 | −814.0 |−1 644 |
| momo_v2_sol_5m_HOD      |  5.5 | 18.7 |  53.5 |  40.0 |  −66.4 | −183.0 | −251.5 |
| sniper_btc_15m_HOD      |  6.3 | 24.1 |  95.0 | 140.7 |  118.3 |    7.3 | −102.0 |
| sniper_btc_5m_HOD       |  4.5 | 16.6 |  63.0 |  82.7 |  −31.6 | −229.3 | −347.8 |
| sniper_eth_15m_HOD+M5va | 11.8 | 44.0 | 169.9 | 267.5 |  375.3 |  404.3 |  225.0 |
| sniper_eth_5m_HOD       |  4.6 | 15.6 |  37.0 |   2.8 | −146.5 | −245.6 | −286.9 |
| sniper_sol_5m_HOD       |  8.0 | 27.8 |  78.3 |  59.0 |   31.2 |   23.8 |   26.1 |

### ROI on capital deployed (%) — capital-efficiency ranking

| sleeve | $25 | $250 | $500 | $1k | $2.5k | $5k | $10k |
|---|--:|--:|--:|--:|--:|--:|--:|
| momo_v1_btc_15m_HOD     | **49.4** | 47.3 | 45.4 | 41.9 | 35.5 | 29.8 | 22.2 |
| sniper_eth_15m_HOD+M5va | **47.2** | 39.2 | 34.0 | 26.8 | 15.7 | 10.9 |  5.2 |
| momo_v2_btc_15m_HOD     | **35.1** | 32.8 | 31.3 | 28.7 | 23.4 | 18.3 | 11.9 |
| momo_v2_eth_15m_HOD     | **34.7** | 31.3 | 29.3 | 26.0 | 19.7 | 14.1 |  6.4 |
| sniper_sol_5m_HOD       | **32.1** | 22.9 | 15.8 |  7.0 |  2.6 |  1.8 |  2.0 |
| sniper_btc_15m_HOD      | **25.4** | 22.0 | 19.0 | 14.1 |  4.8 |  0.2 | −1.7 |
| momo_v2_sol_5m_HOD      | **21.9** | 15.1 | 10.7 |  4.1 | −3.6 | −8.0 |−10.1 |
| momo_v2_btc_5m_HOD+MTF2 | **19.1** | 18.0 | 16.7 | 13.9 |  6.5 | −0.6 | −4.9 |
| sniper_eth_5m_HOD       | **18.4** | 12.1 |  7.4 |  0.3 | −6.8 | −8.7 | −9.7 |
| sniper_btc_5m_HOD       | **17.9** | 14.8 | 12.6 |  8.3 | −1.3 | −6.0 | −7.9 |
| momo_v2_sol_15m_HOD     |  **6.1** | −0.6 | −3.7 | −7.5 |−13.3 |−22.0 |−29.2 |

ROI **monotonically decays** with size on every sleeve. Total $ has an interior maximum because $size × ROI peaks somewhere.

### Underfill rate (%) — when L25 starts running out

| sleeve | $500 | $1k | $2.5k | $5k | $10k |
|---|--:|--:|--:|--:|--:|
| momo_v1_btc_15m_HOD     | 0.0 |  0.0 |  0.0 |  0.0 | 14.8 |
| momo_v2_btc_15m_HOD     | 0.0 |  0.0 |  0.0 |  0.0 | 13.2 |
| momo_v2_btc_5m_HOD+MTF2 | 0.0 |  0.0 |  0.8 | 23.7 | 74.8 |
| momo_v2_eth_15m_HOD     | 0.0 |  0.0 |  0.0 |  0.0 | 34.0 |
| momo_v2_sol_15m_HOD     | 0.0 |  2.8 | 19.4 | 55.6 | 66.7 |
| momo_v2_sol_5m_HOD      | 0.0 | 10.5 | 65.3 | 90.3 | 97.6 |
| sniper_btc_15m_HOD      | 0.0 |  0.0 |  7.0 | 43.3 | 86.1 |
| sniper_btc_5m_HOD       | 0.0 |  0.0 | 12.2 | 71.3 | 97.1 |
| sniper_eth_15m_HOD+M5va | 0.0 |  2.1 | 21.3 | 61.7 | 97.9 |
| sniper_eth_5m_HOD       | 0.0 |  3.9 | 47.3 | 90.7 | 98.9 |
| sniper_sol_5m_HOD       | 7.6 | 50.4 | 92.4 | 99.2 | 99.2 |

## Recommended deploy notionals (practical lens)

What I'd actually start with — the **practical** column above, then ratchet up only if shadow PnL replicates these numbers.

| sleeve | recommended N | shadow target sum_$ (28d) | $/day projection |
|---|--:|--:|--:|
| momo_v1_btc_15m_HOD     | **$5 000** | +$80 314 | +$2 868 |
| momo_v2_btc_15m_HOD     | **$5 000** | +$62 189 | +$2 221 |
| momo_v2_eth_15m_HOD     | **$5 000** | +$33 064 | +$1 181 |
| sniper_btc_15m_HOD      | **$2 500** | +$23 778 | +$849 |
| momo_v2_btc_5m_HOD+MTF2 | **$2 500** | +$21 427 | +$765 |
| sniper_btc_5m_HOD       | **$1 000** | +$19 593 | +$700 |
| sniper_eth_15m_HOD+M5va | **$1 000** | +$12 570 | +$449 |
| sniper_sol_5m_HOD       |   **$500** | +$10 251 | +$366 |
| sniper_eth_5m_HOD       |   **$500** | +$6 726  | +$240 |
| momo_v2_sol_5m_HOD      |   **$500** | +$6 640  | +$237 |
| momo_v2_sol_15m_HOD     | **DROP**   | —        | — |
| **TOTAL (10 sleeves)**  |            | **+$276 552** | **+$9 877 / day** |

That is ≈ **$10k / day projected** vs the current production +$3.6k / day F7 lift (from `NEXT_SESSION_PICKUP_2026_05_21.md`). A ~3 × scale-up if the backtest holds in production.

## Caveats — what would shrink these numbers in live trading

These backtest numbers are **a ceiling**, not an expectation. Real live PnL at these sizes is likely to be lower, because:

1. **Snapshot-vs-tradeable adversity**. L25 records the book *before* anyone reacts to our intent. Real takers at $10 k notional can move the inside, and HFT bots watching the order flow may pull resting orders. The slippage we modelled (2 200 bp on $10 k BTC 15m) is a lower bound — the realised slippage will be that **plus** adverse selection.
2. **L25 ceiling is hard**. Beyond level 25 we can't simulate at all. For sniper_btc_5m_HOD the L25 sum exhausts at $2 500 — we can't actually fit $5 000 even in the model, hence the 71 % underfill rate at $5 000.
3. **Production controllers fire all sleeves on the same slug**. Multiple gated sleeves on the same (BTC, 15m) cell hit the same book within microseconds; their fills compete. We modelled each in isolation. **Joint capacity will be lower than the sum** of per-sleeve capacities — re-run the sweep with *combined* fires per slug to estimate the true joint ceiling.
4. **Latency variance**. The cfg used `latency_ms=0` (LegacyConfig). Production runs with 85 ms (LiveMimicConfig). At larger sizes a 100 ms book is "older" — depth may already be drained by competitors before our order lands.
5. **Polymarket has matchmaking limits**. Even at maker-side, individual orders > $1 000 get filled in smaller chunks by the CLOB, which charges the taker fee on each fill. Our `book_walk_fill` assumes one immediate taker hit at vwap — fine for $1 000 and below, optimistic above.
6. **Backtest fee model assumes 2 %-on-profit-only**. Verified true on production today (CLAUDE.md fee verification 2026-05-22). If Polymarket ever flips on the `poly_taker_curve` fee for the up/down markets, **every $/trade above falls by ≈ $0.07 × p × (1−p) × shares**, which at $5 000 BTC 15m fills ≈ $1.20 per trade — modest but compounding.

## Next steps

1. **Joint-fires capacity** — re-run with all gated sleeves' fires pooled per (slug, asset, fire_us), simulating shared L25 depth consumption. Should land in the $200–250 k aggregate range.
2. **Live shadow at small size** — deploy the 10 sleeves at recommended sizes but cap initial deploy at **$250 per fire**. Measure actual vwap vs backtest vwap per fire to estimate the adverse-selection penalty.
3. **Iterate up** — only ratchet to recommended size after 7 d of shadow data confirms slippage within 25 % of backtest slippage at the recommended size.
4. **Re-pull L25 with deeper book**. The L25 ceiling is the binding constraint at $5k+ for several sleeves. If Polymarket data API exposes L100, pull and re-run for the BTC 15m sleeves to lift the ceiling on the $10 k recommendations.
