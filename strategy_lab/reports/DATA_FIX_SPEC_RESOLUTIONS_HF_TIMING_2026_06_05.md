# DATA-FIX SPEC — `resolutions_hf` slot timing vs actual trading window (2026-06-05)

**For:** storedata / canonical operator.
**Why:** blocks the scalp different-window OOS (§D-2) on the new Feb–Mar backfill. The 1s signal + L25 books
+ trades are all present; the only blocker is that `resolutions_hf` slot_start/slot_end do NOT line up with the
actual market trading window. Fixing this unlocks a clean disjoint-window OOS on BTC/ETH (98M L25 rows).

## Symptom (reproducible)
Take BTC slug `btc-updown-5m-1772323200`:
- `resolutions_hf`: `slot_start_us` = 2026-03-01 **00:00:00**, `slot_end_us` = **00:05:00**, timeframe 5m,
  outcome present, `price_source` = bmoney1321-real. Slug suffix `1772323200` = 00:00:00 (matches slot_start).
- `orderbook_l25_backfill/btc.parquet` for this slug: timestamps **00:02:17.072 → 00:06:34.973** (~4.3 min).
- `trades_polymarket_hf/btc.parquet` for this slug: timestamps **00:02:17.366 → 00:06:23.621**.

→ The **trades and the book agree with each other** (both start 00:02:17, end ~00:06:3x) but are **shifted
~+137s from `resolutions_hf` slot_start (00:00:00)** and **extend ~+95s past slot_end (00:05:00)**.

The offset is **not constant** — across the first six 5m slugs it ranged **+74s to +149s** (book_start −
slot_start), and book_end − slot_end ranged **+95s to +226s**. Books are **contiguous slug-to-slug** (each
slug's activity starts ~where the previous slug's ended).

## What this breaks
The lag-taker scalp needs, per slug:
1. the **strike time** (window open) to anchor the 5s Binance-return lag and the Up/Down outcome, and
2. the book/trades present at **strike+5s** to fire + fill.
With the current `resolutions_hf` timing, firing at slot_start+5s (00:00:05) lands ~137s before any book/trade
exists → 0% fill. Re-anchoring to the activity window gives fills but the **lag↔outcome alignment is wrong**
(the outcome is defined by the [slot_start, slot_end] underlying move, but trading sits in a shifted window),
so the OOS result is confounded and unusable.

## Diagnosis — please determine which it is
Run, per slug, the gap `min(trade_ts) − slot_start_us` and `max(trade_ts) − slot_end_us`. Likely one of:
- **(A) Label/clock offset in `resolutions_hf`:** slot_start/slot_end (or the slug suffix→epoch mapping) are
  computed with a wrong reference (e.g. off by one sub-interval, or a TZ/epoch bug), while the real strike/settle
  match the trades/book. → Recompute slot_start/slot_end from the true source.
- **(B) Markets genuinely strike at slot_start but trade in a delayed window** (late MM quoting, ~2 min). → Then
  slot_start IS the strike (use it for the lag anchor + outcome) and trading just starts late; we'd fire at the
  first available book. In this case the timing is "correct" but we need the **true strike timestamp** confirmed
  so the lag anchor is right, and we accept early-window fills are impossible for these markets.
- **(C) The backfill ingest mis-joined slugs↔activity** (the contiguous slug-to-slug pattern hints the activity
  rows may be assigned to the wrong adjacent slug). → Re-join activity to slugs by the on-chain market/condition
  id + true window, not by row order/proximity.

Cross-check against the on-chain market: the Polymarket `condition_id` / market metadata for each slug has the
canonical accepting/closing times — compare those to both `resolutions_hf` slot_* AND the trades/book span to see
which is authoritative.

## Required fixed output (acceptance)
For each hf slug, provide timestamps that satisfy ALL of:
1. `strike_ts_us` = the underlying-price reference time the outcome is settled against (window open).
2. `settle_ts_us` = the settle reference time (window close); `outcome` consistent with the underlying move
   `sign(price@settle − price@strike)` using the same feed the market settles on.
3. **The L25 book and trades for the slug fall within `[strike_ts_us − ε, settle_ts_us + ε]`** (ε ≤ ~5s), i.e.
   activity is inside the declared window — specifically a book snapshot must exist at **`strike_ts_us + 5s`**
   (so the +5s scalp can fire), and through `strike_ts_us + ~180s` (so a +60s book-sell after an early fire works).
4. Window length matches the timeframe (5m → settle−strike ≈ 300s; 15m → 900s).

Acceptance test (what I'll run to confirm): for a 200-slug sample, `fill_at_book(slug, side, strike_ts+5s)` must
return non-None for ≥80% of slugs (currently 0%), and book/trade spans must lie within the declared window.

## Scope
- Priority: **BTC + ETH** (Feb 21 → Mar 24, 98M L25 rows each) — the big clean OOS window.
- Then SOL + XRP (Mar 1 → Mar 13). SOL/XRP currently 0% fill even re-anchored — verify their backfill too.
- The main-window data (Apr 22 → Jun 4, `resolutions.parquet` chainlink) is FINE — do not touch; it's the
  reference where the scalp fires correctly at +5s. Use it to validate the fix (the fixed hf timing should make
  Feb–Mar behave like the main window).

## Files / evidence
- Repro script: `strategy_lab/directional/scalp_oos_backfill_2026_06_05.py` (shows 0% fill at +5s; 96% fill when
  re-anchored to activity but confounded).
- Inventory + anomaly write-up: `strategy_lab/reports/NEW_DATA_INVENTORY_2026_06_05.md`.
- Affected: `data/v4/canonical/resolutions_hf.parquet` (timing), cross-checked against
  `orderbook_l25_backfill/{btc,eth,sol,xrp}.parquet` + `trades_polymarket_hf/{btc,eth}.parquet`.
