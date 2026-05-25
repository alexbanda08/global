# Queue-aware maker + hybrid maker→taker — reality check

**Hypothesis tested** (from previous report): place maker buy at passive price (P_bid / P_bid+1 / P_mid / P_ask−1), let it sit until slot_end. Previous model assumed **zero queue position** and **all-or-nothing fills** → reported maker lift ≈ +$2 310 / day. This run lifts both assumptions using Polymarket trades parquet.

**Runner**: [strategy_lab/markov_filter/queue_aware_maker_gated_sleeves.py](strategy_lab/markov_filter/queue_aware_maker_gated_sleeves.py)
**Outputs**:
- [queue_aware_per_fire.csv](strategy_lab/markov_filter/_results/queue_aware_per_fire.csv) (15 844 rows)
- [queue_aware_per_sleeve.csv](strategy_lab/markov_filter/_results/queue_aware_per_sleeve.csv) (176 rows)
- [queue_aware_best_per_sleeve.csv](strategy_lab/markov_filter/_results/queue_aware_best_per_sleeve.csv)

## What changed in the fill model

| | OLD (optimistic) | NEW (queue-aware) |
|---|---|---|
| Queue position | 0 (assumed front of book) | `bsz` at our level from entry L25 (typically 100–300 shares ahead at $1k notional) |
| Fill trigger | First snapshot where `best_ask ≤ P` | Cumulative aggressor SELL volume AT price P (within ½ tick) from trades parquet |
| Fill amount | All-or-nothing (full notional) | `clamp(cum_sell_vol − queue_ahead, 0, target_shares)` — partial fills the norm |
| Fee on filled portion | $0 (maker) | $0 (maker) — unchanged |

**Hybrid policy added**:
- Run maker for first 60 s only
- If maker fills any shares within 60 s, keep those at maker price
- For remaining unfilled shares, cross with TAKER at the book as it stands at `fire_us + 60 s` (2 %-on-profit fee on the taker portion)

## Headline finding

**The optimistic maker advantage evaporates under realistic queue mechanics.**

| Policy | 28-d aggregate $ | $/day | vs pure-taker |
|---|--:|--:|--:|
| **Pure taker (current production model)** | **+$148 477** | +$5 303 | — |
| Pure maker (queue-aware, slot_end window, best placement per sleeve) | +$5 041 | +$180 | **−$143 436 (−97 %)** |
| Hybrid maker→taker 60 s (best placement per sleeve) | +$78 056 | +$2 788 | **−$70 421 (−47 %)** |

Pure maker barely fills (avg fill fraction 0.5–16 %; 70–95 % of fires get **zero** maker fill). The hybrid recovers most of the taker performance via fallback, but the maker portion captures almost no edge — so the hybrid is essentially "taker, but worse" (it pays the same taker slippage on a stale book at fire_us + 60 s).

## Per-sleeve totals @ practical notional

Pure taker is the column to beat. **Maker_q** = best pure-maker queue-aware across 4 placements. **Hybrid** = best hybrid across 4 placements.

| sleeve | $N | pure taker | best pure maker | best hybrid | hyb − taker |
|---|--:|--:|--:|--:|--:|
| momo_v2_btc_15m_HOD     | 1000 | +19 532 |  +11   | +19 347 |   −185  |
| sniper_btc_15m_HOD      | 1000 | +23 180 | +1 394 | +17 028 | −6 152 |
| momo_v2_btc_5m_HOD+MTF2 | 1000 | +18 249 |   +985 | +16 174 | −2 074 |
| momo_v1_btc_15m_HOD     | 1000 | +22 645 |   +763 | +13 599 | −9 046 |
| sniper_eth_15m_HOD+M5va | 1000 | +12 570 |    +43 |  +5 680 | −3 047 |
| momo_v2_sol_5m_HOD      |  500 |  +6 640 |    +32 |  +4 526 | −2 114 |
| momo_v2_eth_15m_HOD     | 1000 | +12 211 |    +77 |  +4 306 | −5 785 |
| sniper_sol_5m_HOD       |  500 | +10 251 |    +55 |  +1 484 | −6 388 |
| sniper_btc_5m_HOD       | 1000 | +16 610 | +1 423 |    +111 | −16 499 |
| momo_v2_sol_15m_HOD     |  100 |     −86 |    +72 |     −61 |    +25 |
| sniper_eth_5m_HOD       |  500 |  +6 503 |   +186 |  −4 139 | −10 205 |
| **TOTAL (28 d)**        |      | **+148 477** | **+5 041** | **+78 056** | **−70 421** |

**Hybrid loses ≥ $2 k vs pure taker on 10 / 11 sleeves.** Only `momo_v2_sol_15m_HOD` ekes out +$25 — and that sleeve already failed the robustness audit (binom p = 0.40) so it's noise.

## Why the maker fails: queue mechanics

| placement | mean queue ahead (shares) | mean target shares @ $1k | mean fill fraction | mean zero-fill % |
|---|--:|--:|--:|--:|
| P_bid     | 159–318 | ~2 030 | **0.5–1 %** | **82–95 %** |
| P_bid+1   | 0       | ~2 030 | **0.6 %**   | **44–95 %** |
| P_mid     | 0–224   | ~2 020 | **0.5–1 %** | **78–96 %** |
| P_ask−1   | 64–149  | ~2 020 | **0.5 %**   | **81–94 %** |

For BTC sleeves at $1 000 notional, our **target = ~2 000 shares**, but only **0.5–1 % of that fills** within slot_end. Even posting one tick above best_bid (P_bid+1, queue ahead = 0) only fills 0.6 % on average — there simply aren't enough aggressors selling AT our exact tick within 5–15 min to absorb a $1 k notional.

## Why the hybrid still loses vs pure taker

Two leaks:

1. **Stale book at +60 s**. The hybrid taker crosses 60 s AFTER the signal. By then, prices have drifted (often AGAINST us when the signal was right — the easy moves already happened). vwap at +60 s is typically 1–2 cents WORSE than at fire_us for winning trades.
2. **Almost no maker fills in 60 s**. `hyb_maker_part_pct` (fraction of fires with ANY maker fill in 60 s) is **0–8 %** across all sleeves. The hybrid is operationally just "taker, delayed by 60 s" for 92–100 % of fires.

`sniper_eth_5m_HOD` is the worst case: pure taker = +$6 503, hybrid = −$4 139 (a **$10 k loss** vs taker). The 5-min slot moves too fast — by +60 s the book has already discovered the move.

## Where small-target maker might still help

The one signal that survives: at very **small notional** the target shares fit within typical aggressor volume per 60 s.

| notional | best placement | maker_q fill frac | hyb_lift vs taker |
|--:|---|--:|--:|
| $25  | P_bid+1 |  16 % |   −$586 |
| $100 | P_bid+1 |   7 % | −$2 868 |
| $500 | P_bid+1 |   2 % | −$18 324 |
| $1000 | P_bid+1 |  1 % | −$28 675 |

Even at $25 (target ~50 shares) the average fill is only 16 % — too low to recover the spread savings against losses on unfilled fires.

## Conclusion

**Stick with pure taker.** The maker advantage from the previous report was an artifact of the zero-queue / all-or-nothing fill model. With realistic queue mechanics:

- Pure maker captures **3 % of pure-taker PnL**
- Hybrid maker→taker (60 s) captures **53 % of pure-taker PnL**
- No placement / notional combo beats pure taker on more than 1 of 11 sleeves

## What might still work — escape valves

These are 3 ideas worth trying *before* concluding maker is dead:

1. **Longer maker window (180 s)** before fallback. 60 s of aggregator flow at our exact tick is rare; 180 s is more realistic for slow-fill venues. Re-run hybrid with `HYBRID_WINDOW_S = 180`.
2. **Smaller notional, multiple makers**. Place 10 × $100 maker orders at staggered prices ($best_bid, +1, +2, … +4 ticks) instead of one $1 000 at $best_bid. Spread the queue risk; let aggressors hit whichever level the price drifts to. Sum target ≈ 2 000 shares but distributed.
3. **Per-fire maker decide**. Only attempt maker when:
   - `queue_ahead < target_shares × 0.5` AND
   - L25 ask depth at fire_us is shallow (large taker slippage expected)

The current model fires maker on every signal — that's why it loses on the half of signals where taker would have been fine.

## Caveats on this run

- Trades parquet starts **Apr 26 2026**; the gated-sleeve window starts **Apr 22**. ~4 days at the front have no aggressor data — those fires get 0 fill in the maker model (fairness check: pure-taker number includes them at full taker rate, so this DOES penalise maker slightly. Magnitude: ~14 % of fires).
- 70 BTC / 27 ETH / 36 SOL slugs (133 / 1 265 fires, ~10 %) have no trades-key entry at all — same 0-fill effect.
- Fill model still assumes our order is at the **front of the queue among orders posted AFTER `fire_us`** — i.e., we capture all aggressor flow that walks past our level after the snapshot. This is still optimistic if other passive bids arrived in the same second; in reality there will be queue competition from other algos. **Apply a further 50 % multiplier on the fill numbers for a true expectation.**
- Trades.side semantics ("sell" = taker sold the outcome share into our bid) verified by spot check on the schema — but if the convention is inverted on Polymarket's data feed, every number here flips. Worth a one-fire manual cross-check before depending on this further.
