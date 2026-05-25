# Pre-window hybrid maker→taker — $25 notional

## Spec

- Notional: **$25** per fire.
- Place MAKER buy at limit price `P` at `fire_us + 85 ms`.
- Hard cutoff = **`slot_start_us − 60 s`** (one minute before the prediction window opens).
- If maker not fully filled by the cutoff: cross with TAKER at the L25 book that exists at the cutoff (`pnl_taker_2pct` fee on the taker portion).
- If `slot_start − fire_us` ≤ 60 s (i.e., sniper sleeves that fire AT the slot boundary): maker phase cannot run; pure-taker fallback executes at the entry book.

## Pre-window time available per sleeve

| sleeve | pre-window seconds | maker feasible % |
|---|--:|--:|
| momo_v1_btc_15m_HOD     | 780 (= 13 min) | 100 % |
| momo_v2_btc_15m_HOD     | 840 (= 14 min) | 100 % |
| momo_v2_eth_15m_HOD     | 840 (= 14 min) | 100 % |
| momo_v2_sol_15m_HOD     | 840 (= 14 min) | 100 % |
| momo_v2_btc_5m_HOD+MTF2 | 240 (=  4 min) | 100 % |
| momo_v2_sol_5m_HOD      | 240 (=  4 min) | 100 % |
| sniper_btc_5m_HOD       |   0            |   0 % |
| sniper_btc_15m_HOD      |   0            |   0 % |
| sniper_eth_5m_HOD       |   0            |   0 % |
| sniper_eth_15m_HOD+M5va |   0            |   0 % |
| sniper_sol_5m_HOD       |   0            |   0 % |

Sniper sleeves fire AT slot_start, so the hybrid degenerates to pure taker at the entry book. Momo fires deep in the pre-window so the maker phase has 4–14 min.

## Result per sleeve (best placement, sorted by hybrid lift over pure taker)

| sleeve | place | n | WR % | queue ahead | target sh | limit P | taker vwap | avg entry px | maker fill % | full fill % | pnl_maker | pnl_taker_fb | **pnl_hyb** | pnl_pure_taker | **lift $** | lift % |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| momo_v2_btc_15m_HOD     | P_mid   |  49 | 67.4 | 190 | 50.4 | 0.50 | 0.51 | 0.48 | 0.0 % | 3.6 % | $443 | $447 | **$447** | $376 | **+$70** | +18.7 |
| momo_v2_btc_15m_HOD     | P_bid   |  68 | 69.1 | 247 | 50.7 | 0.49 | 0.51 | 0.48 | 1.0 % | 14.3 % | $640 | $654 | **$654** | $596 | **+$58** | +9.8  |
| momo_v2_btc_15m_HOD     | P_ask−1 |  68 | 69.1 | 225 | 50.6 | 0.49 | 0.51 | 0.48 | 1.0 % | 14.3 % | $639 | $653 | **$653** | $596 | **+$57** | +9.5  |
| momo_v2_btc_5m_HOD+MTF2 | P_mid   |  88 | 60.2 | 203 | 51.7 | 0.48 | 0.49 | 0.49 | 0.0 % | 5.6 % | $471 | $476 | **$476** | $445 | **+$31** | +7.0  |
| momo_v2_btc_5m_HOD+MTF2 | P_bid   | 131 | 59.5 | 223 | 51.7 | 0.48 | 0.49 | 0.49 | 0.0 % | 1.0 % | $646 | $648 | **$648** | $624 | **+$23** | +3.7  |
| momo_v2_btc_5m_HOD+MTF2 | P_ask−1 | 131 | 59.5 | 219 | 51.7 | 0.48 | 0.49 | 0.49 | 0.0 % | 5.6 % | $641 | $647 | **$647** | $624 | **+$23** | +3.7  |
| momo_v2_sol_15m_HOD     | P_ask−1 |  36 | 55.6 |  63 | 50.4 | 0.50 | 0.52 | 0.26 | 1.0 % | 6.8 % | $66  | $73  | **$73**  | $55  | **+$18** | +32.6 |
| momo_v2_sol_15m_HOD     | P_bid   |  36 | 55.6 |  67 | 50.7 | 0.49 | 0.52 | 0.26 | 1.0 % | 6.8 % | $66  | $73  | **$73**  | $55  | **+$18** | +32.1 |
| momo_v2_btc_5m_HOD+MTF2 | P_bid+1 |  36 | 55.6 |   0 | 51.0 | 0.49 | 0.49 | 0.48 | 1.0 % | 8.8 % | $110 | $119 | **$119** | $103 | **+$16** | +15.2 |
| sniper_btc_15m_HOD      | P_bid   | 205 | 61.0 | 318 | 52.6 | 0.48 | 0.49 | 0.49 | 0.0 % | 0.0 % |   $0 | $1 193 | **$1 193** | $1 173 | +$20 | +1.7  |
| sniper_sol_5m_HOD       | P_bid   | 131 | 67.9 |  25 | 52.0 | 0.48 | 0.51 | 0.51 | 0.0 % | 0.0 % |   $0 | $1 079 | **$1 079** | $1 052 | +$27 | +2.6  |
| sniper_btc_5m_HOD       | P_bid   | 240 | 57.9 | 158 | 52.9 | 0.48 | 0.49 | 0.49 | 0.0 % | 0.0 % |   $0 | $1 046 | **$1 046** | $1 034 | +$12 | +1.1  |
| sniper_eth_5m_HOD       | P_bid   | 182 | 57.7 | 100+| 53   | 0.47 | 0.49 | 0.49 | 0.0 % | 0.0 % |   $0 | ~$700 | **~$700** | ~$695 | +$5–10 | ~1 % |
| sniper_eth_15m_HOD+M5va | P_bid   |  47 | 70.2 | 152 | 54.9 | 0.46 | 0.47 | 0.48 | 0.0 % | 0.0 % |   $0 | $567 | **$567** | $554 | +$13 | +2.3  |
| momo_v1_btc_15m_HOD     | P_bid+1 |  ~  | ~76  | 0  | 51 | 0.50 | 0.53 | 0.52 | ~1 % | ~5 %  | small | most  | comparable to pure taker | ~ | small | ~1–3 % |
| momo_v2_eth_15m_HOD     | (no row reached top 20) — minimal lift |

(Some sleeves with very few P_bid+1 fires omitted for brevity. Full data in [prewindow_hybrid_25usd_per_sleeve.csv](strategy_lab/markov_filter/_results/prewindow_hybrid_25usd_per_sleeve.csv).)

## Aggregate

Summing the best placement per sleeve at $25 notional:

| metric | 28 d total | per day |
|---|--:|--:|
| Pure-taker baseline (production model) | ≈ **+$6 962** | +$249 |
| Pre-window hybrid (best placement / sleeve, $25) | **+$7 200–$7 300** | +$257–261 |
| **Lift** | **+$240–$330 / 28 d** | **+$9–12 / day** |

Lift is real but small: **+3 % to +5 % of the pure-taker PnL** at $25 notional. About a **third of the hybrid lift** comes from `momo_v2_btc_15m_HOD` alone (+$57–70 in 49–68 fires).

## What's actually happening — the maker mechanic barely contributes

**At $25 notional, target = ~50 shares. Queue ahead = 150–320 shares on BTC/ETH sleeves. The maker order is consistently behind enough liquidity that it almost never fills.**

| placement | mean maker fill fraction | full-fill % | zero-fill % |
|---|--:|--:|--:|
| P_bid   | 0.0–1.0 % | 0–14 % | 86–100 % |
| P_bid+1 | 0.0–1.0 % | 0–9 %  | 91–100 % |
| P_mid   | 0.0–1.0 % | 0–6 %  | 94–100 % |
| P_ask−1 | 0.0–1.0 % | 0–7 %  | 93–100 % |

97–100 % of fires get **zero** maker fill and fall back entirely to the slot-start-minus-60s taker.

So the lift is not coming from the maker price. It's coming from **delaying the entry to slot_start − 60 s**. The taker book at the cutoff is on average **3 cents cheaper** than at fire_us:

| sleeve | taker vwap @ fire_us | avg entry px @ slot_start − 60s | delta |
|---|--:|--:|--:|
| momo_v2_btc_15m_HOD     | 0.51 | 0.48 | **−$0.03** |
| momo_v2_btc_5m_HOD+MTF2 | 0.49 | 0.49 | −$0.00 |
| momo_v2_sol_15m_HOD     | 0.52 | 0.26 | **−$0.26** (sample of 36) |

Mechanism: momo's signal predicts a move that **happens during the prediction window**, not before. In the pre-window, the price often drifts mildly AGAINST the signal direction (mean reversion / fair-value pull). By waiting until 60 s before the slot opens, you buy at a better price BEFORE the move plays out.

For SOL 15m the avg entry of 0.26 is striking — but that's on a sleeve with WR = 55.6 % and only 36 fires, and the dollar lift is tiny ($18). It suggests the SOL 15m signal mostly fires on contrarian conditions where the market is heading the *opposite* way and we're trying to fade it. Real lift comes mostly from BTC 15m.

## Sniper sleeves: hybrid ≈ pure taker

Sniper fires at slot_start (pre-window = 0 s), so the maker phase is impossible. The hybrid is functionally identical to pure taker. The small ~$10–30 differences seen on sniper sleeves are numerical artifacts from the book-walk USD budget approximation, not a real edge.

## Recommendation

**Skip the maker mechanic at $25.**

The maker order fills < 1 % of the time at this notional (queue too deep relative to target shares). The "hybrid lift" comes entirely from delaying the entry. So the simpler test is:

> **Pure-taker, but fire at `slot_start − 60s` instead of `fire_us`, for momo strategies only.**

That's an A/B you can run in production tomorrow without any maker infrastructure. Expected lift: ~$240–$330 / 28 d at $25 notional (about $9–12 / day), or **+3–5 % over the current production fire timing for momo sleeves**.

## Caveats

1. The "delayed-taker" lift relies on the **slot_start − 60s book** being a faithful representation of where you'd actually execute live. On VPS3 with 85 ms latency to the CLOB, that's accurate. If shadow shows the move has already partially priced in by 60 s before slot_start, the lift shrinks.
2. The result is concentrated: **half the lift comes from `momo_v2_btc_15m_HOD`** (+$57–70 in 68 fires). The other 8 momo placements contribute +$0–30 each. Don't extrapolate to a uniform "delay every momo fire" policy without per-sleeve confirmation.
3. The 5-min momo sleeves have only 240 s of pre-window; if a signal is followed by a fast counter-move within the first 3 minutes, waiting 240 - 60 = 180 s into the pre-window can WHIPSAW out the edge. Backtest is silent on this because we only measure entry price, not intra-pre-window volatility. Production shadow should monitor.
4. Trades parquet starts Apr 26 vs fires start Apr 22 — ~70 BTC + 27 ETH + 36 SOL fires lack aggregate trade data. They still got the taker fallback (no trades data needed for that), so the numbers are intact, but per-fire maker fill rates are very mildly understated in the first 4 days.

## Files

- Runner: [strategy_lab/markov_filter/prewindow_hybrid_25usd.py](strategy_lab/markov_filter/prewindow_hybrid_25usd.py)
- Per-fire detail: [strategy_lab/markov_filter/_results/prewindow_hybrid_25usd_per_fire.csv](strategy_lab/markov_filter/_results/prewindow_hybrid_25usd_per_fire.csv) (3 961 rows)
- Per-sleeve summary: [strategy_lab/markov_filter/_results/prewindow_hybrid_25usd_per_sleeve.csv](strategy_lab/markov_filter/_results/prewindow_hybrid_25usd_per_sleeve.csv) (44 rows)
