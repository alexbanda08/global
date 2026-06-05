# New Canonical Data — Inventory & What It Unlocks (2026-06-05)

Operator uploaded a large historical backfill + new coins. Mapped the full stack. **Headline: it's the
poly-SIDE history (L25 books, trades, outcomes) for Feb–Mar + 4 new coins — but the matching binance-1s
SIGNAL and chainlink ORACLE were NOT backfilled to that window, and DOGE/BNB/HYPE are outcome-only.** So the
scalp OOS (the prize) is still blocked on one missing feed; book/trade strategies CAN be OOS'd now.

## What's new
- **`resolutions_hf`** (64,728): up/down outcomes for **6 coins** — BTC/ETH/SOL + **XRP, DOGE, BNB, HYPE**.
  Window **Jan 2 → Apr 21** (pre-search). New coins settle on `aliplayer-markets` / `bmoney-real` /
  `hf-trentmkelly-settle` (NOT chainlink). Per-coin span: BTC Jan2–, ETH Feb21–, SOL/XRP Mar1–, DOGE/BNB/HYPE Apr6–21.
- **`orderbook_l25_backfill/`** — L25 books: **BTC/ETH Feb 21→Mar 24 (98M rows each!)**, SOL/XRP Mar 1→Mar 13 (~850k).
- **`trades_polymarket_hf/`** — poly trade tape **BTC/ETH only**, Feb 21→Mar 24 (34M/8M).
- **`cryptocap_dominance`** (40k) — macro regime feature (dominance).
- **`binance_vision_klines`** — BTC/ETH/SOL only, 1MIN+ (no new coins, no 1s).
- HL klines (Jan30→May27, BTC/ETH/SOL/HYPE, **hourly** — too coarse for the scalp).

## The blocker (timing/feed mismatch)
| need | have for Feb–Mar backfill? |
|---|---|
| poly L25 books | ✅ BTC/ETH (98M), SOL/XRP (Mar1–13) |
| poly trade tape | ✅ BTC/ETH only |
| outcomes | ✅ resolutions_hf (6 coins) |
| **binance 1s signal (scalp lag)** | ❌ **klines_1s = Apr 7→ only** |
| **chainlink oracle (settle selector)** | ❌ **Apr 24→ only; new coins don't use chainlink** |
| price/book for DOGE/BNB/HYPE | ❌ outcome-only |

→ The L25-backfill window (Feb–Mar) and the 1s-signal window (Apr 7+) are **disjoint**. The lag-taker scalp
needs a sub-minute price; none exists for Feb–Mar (HL is hourly). So the **scalp different-window OOS (§D-2)
remains blocked** — by a missing feed, not missing markets.

## What IS runnable now (book/trade-only — no external signal needed)
1. **Cross-window OOS of the book/trade findings on BTC/ETH Feb–Mar** (L25 98M + trades 34M + outcomes):
   favorite-longshot, cross-token price-sum, time-of-day. First TRUE different-window OOS we can run for
   *anything* — tests whether the Apr–Jun results (mostly negatives) replicate on a disjoint month.
2. **XRP up/down (Mar 1–13)**: L25 + outcomes → favorite/book strategies on a NEW coin (no chainlink → no
   oracle-determinism; no trade tape → book-mid only).
3. **DOGE/BNB/HYPE**: outcome-only → no backtest possible (no price/book). Universe-stats only.

## The ask (unlocks the prize)
To run the **scalp / oracle-determinism OOS** on the Feb–Mar backfill, we need the operator to also backfill:
- **binance 1s klines for Feb 21 → Apr 7** (to match the L25 backfill) → unlocks the lag-taker scalp OOS = the
  deflation-proof §D-2 gate we've been blocked on.
- (optional) chainlink RTDS Feb–Mar → unlocks the oracle-determinism OOS for BTC/ETH/SOL.
- For new coins to be tradeable: their underlying price feed + poly trade tape + L25 (only XRP has L25 so far).

## UPDATE — 1s backfilled ✓, but L25 backfill has a TIMING ANOMALY (blocks scalp OOS)
Operator readied 1s klines: `klines_1s` now **Jan 1 → Jun 4 for BTC/ETH/SOL**, **Jan 1 → Apr 6 for
BNB/DOGE/XRP**. The scalp signal is unblocked. BUT running the scalp OOS on the Feb–Mar L25 backfill
(`scalp_oos_backfill_2026_06_05.py`) exposed a **data anomaly in `orderbook_l25_backfill`**:
- For every hf slug, the L25 book **starts ~75–150s AFTER slot_start and ends ~100–220s PAST slot_end**
  (e.g. slot 00:00–00:05 → book 00:02:17–00:06:34). Books are contiguous slug-to-slug (each starts where the
  prior ended). **CONFIRMED via trades:** `trades_polymarket_hf` for the same slug ALSO start at 00:02:17
  (identical to the book), so it is NOT a book-timestamp lag — the ENTIRE market activity (trades+book) is
  shifted ~+137s (varies 74–150s) from `resolutions_hf` slot_start and runs ~4.3min. The mismatch is
  **`resolutions_hf` slot timing vs the actual trading window**. Book prices at start ~0.50/0.51 → consistent with **lagged book
  timestamps**, not late trading.
- Effect: firing at the deployed **+5s gives 0% fill** (book doesn't exist yet). SOL/XRP backfill = 0% fill
  even re-anchored.
- An EXPLORATORY re-anchor (fire +30s into the available book ≈ slot_start+130s) fills 96% but is the WRONG
  regime — the scalp edge lives early and decays late (per `SCALP_DYNAMIC_EXIT`), so the negative result there
  (BTC gated +0.35 ns, ETH gated −2.58) is confounded, NOT a refutation of the +5s deployed scalp.
→ **Clean scalp OOS still blocked — now by the L25 backfill timing, not the signal.**

### Exploratory OOS result (re-anchored to real trading window) — YELLOW FLAG, confounded
Firing 30s into each slug's real (shifted) trading window, fresh 5s lag, book-sell +60s:
- BTC Feb–Mar: gated vwap<0.55 +$0.35/tr (CI [−1.99,+2.93], ns); all-filled −$0.21 (ns).
- ETH Feb–Mar: gated −$2.58/tr (CI [−4.09,−1.08], sig NEGATIVE); all-filled −$1.80 (t=−4.78).
- SOL/XRP: 0% fill (worse coverage).
This is a cautionary signal the scalp may NOT generalize to Feb–Mar — BUT it's confounded: (a) the trading window
is shifted ~137s vs the strike/outcome window → the lag↔outcome alignment is off; (b) window compressed to ~4.3min;
(c) firing offset differs from the deployed +5s. **Not a clean refutation; the scalp OOS is still effectively
blocked** until the timing is reconciled.

### Operator ask (to unlock the §D-2 scalp OOS — the prize)
**Reconcile `resolutions_hf` slot_start/slot_end with the actual trading window.** The trades+book agree with each
other but are shifted ~+137s (74–150s, per-market) from the hf slot_start, and run past slot_end. Either the
slug→slot mapping / strike timestamp in `resolutions_hf` is offset, or the markets strike at slot_start but trade
in a later window. We need, per slug: the true strike time (for the binance lag anchor) AND the true settle time,
matching the trades/book activity. Once aligned, the deployed +5s scalp can be OOS'd on Feb–Mar (BTC/ETH 98M rows
= big clean disjoint window). Also: chainlink RTDS Feb–Mar (oracle selector); underlying price + L25 for DOGE/BNB/HYPE.

## Recommended next
- **Highest value:** get the binance-1s Feb–Mar backfill → then run the scalp OOS (the real deflation gate).
- **Runnable now (medium value):** favorite-longshot/cross-token **cross-window OOS on BTC/ETH Feb–Mar** — a
  genuine disjoint-window robustness check of our book findings. Likely confirms the death, but it's the first
  real OOS we can do.
- XRP new-coin book test (Mar 1–13) — exploratory.
