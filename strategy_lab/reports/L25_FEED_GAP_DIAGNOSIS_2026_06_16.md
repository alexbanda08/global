# L25 feed-gap investigation — diagnosis + CORRECTION
**2026-06-16.** Triggered by the T1 "feed-loss" finding. Investigated end-to-end (local pipeline → VPS3 storedata source → collector code). **Headline: the canonical L25 is NOT pervasively feed-blind. My earlier "49% invisible / feed blind" was MY measurement bug. Corrected steady-state loss is ~4% (count) / ~8% (volume).**

---

## 0. CORRECTION 2 (2026-06-16, after operator pushback "the collector gets 10 Hz") — THE REAL GAP
Re-read the collector handlers (not just grep). **The operator is right: the WS delivers a high-frequency stream and the collector discards it.**
- `BookSnapshotDeduper` is **lossless** (blake2b of exact top-25 price+size) and its docstring says **"10–20× row-reduction vs naive every-event writes"** → the inbound rate is ~10–20× the ~1–2 Hz we persist (≈ the operator's "10 Hz").
- **`_handle_price_change` = "Phase 15-05: NO DB write"** — the `price_change` **deltas** (collector comment: **"fire hundreds of times/sec"**) are received but **only fire a callback; never persisted.** Only periodic full `book` snapshots are written to `orderbook_snapshots_v2`.
- **Net:** the persisted full-book (~1–2 Hz, lossless-deduped) is ~92% faithful for **coarse fill visibility** (§3 stands), BUT the **order-level book evolution — queue adds/cancels, sub-100 ms transient levels — is NOT in the historical data.** For directional backtests (scalp/sniper) this is fine; **for maker/queue modeling (b945 ladder, sum-pair maker capture) it is the missing data.** The ~8% residual invisible fills in §3 are largely these between-snapshot transients the deltas would carry.
- **This is a deliberate design choice (Phase 15-05, to stop journald flooding / DB bloat), not a broken pipeline.** Fix = re-enable scoped delta persistence (§8).

## 1. TL;DR
- The "feed blind" T1 result was a **join bug**: I matched trades on `trade.local_timestamp_us` (= the data-API **poll/write** time, which lags the real trade by **p90 = 337 s**, hours on backfill) against the real-time book. With a ±300 ms window and a multi-second join error, almost everything looked "invisible" (39–66%).
- **Corrected** (join `trade.timestamp_us` exchange-match-time → `book.timestamp_us` source-time; clocks verified aligned, nearest-snap offset p50 = 0.03 s): **steady-state feed loss = 3.6% count / 7.6% volume (any-side, ±3 s); 7.7% / 12.8% rel-side.** The ±1 s number (23%) shrinks to ~4–8% as the window widens → most apparent loss is **second-granular trade timestamps**, not missing book data.
- The multi-second snapshot "gaps" (p90 8.4 s) are mostly **dedup-on-change** (the top-25 book didn't change), **not** dropped data — the last snapshot stays valid until the next change. Benign.
- **Local pull/convert/merge are faithful** (source 1624 rows vs local 1620 for the test slug). No local pipeline bug.
- The collector is **~92–96% faithful on fills.** No major fix needed.

## 2. How the collector actually works
`storedata-collector.service` → `/opt/storedata/src/storedata/collectors/polymarket.py` (VPS3):
- **Book:** subscribes to CLOB WS `book` (full) + `price_change` (delta); writes `orderbook_snapshots_v2` with **dedup-on-change** (`BookSnapshotDeduper` suppresses identical consecutive top-25 states). A persisted row = a distinct top-25 state. Effective ~1–2 writes/s on an active btc-15m market — that's the **real book-change rate after dedup**, not a throttle and not 10 Hz.
- **Trades:** **NOT from WS.** Polled from the **data-API every 5 s** (`_trade_poll_loop`; WS only emits sparse `last_trade_price`). On trade rows: `timestamp_us` = exchange match time (**second-granular**); `local_timestamp_us` = collector poll/write time (lags 0–5 s live, **minutes–hours on backfill**). → **never join book↔trade on `local_timestamp_us`.**
- Single source (`live`/`polymarket`), single WS connection, healthy receive lag (~25–40 ms).
- **Late-start:** markets discovered via gamma events, `rediscover_interval = 60 s` → first persisted snapshot is variable (median ~116 s into the window; range 6–354 s). **But ~0% of fills occur pre-first-snapshot** (little trading that early), so low impact on fill-modeling.

## 3. Corrected numbers (50 btc-15m slugs, 100,832 covered prints, exchange-time join)
| window | rel-side invisible (ct / vol) | any-side invisible (ct / vol) |
|---|---|---|
| ±1 s | 23.2% / 35.9% | — |
| ±2 s | 15.1% / 22.8% | — |
| ±3 s | 7.7% / 12.8% | **3.6% / 7.6%** |

Window-width dependence (23→15→8% rel-side) ⇒ most "invisibility" is the ±~1 s trade-timestamp rounding. The ±3 s any-side residual (~4% ct / ~8% vol) = top-25 depth truncation (deep walks beyond level 25) + occasional WS drops. **Script: `strategy_lab/directional/_t1_feedloss_v2.py` (supersedes `_t1_feedloss.py`).**

## 4. What is NOT a bug
- Local pull/convert/merge: faithful (no row loss).
- Multi-second snapshot gaps: dedup-on-change (book unchanged) — benign.
- ~1 Hz cadence: fine for our strategies (scalp +60 s exit, sniper µs offsets read closed bars); the book between writes is genuinely unchanged.

## 5. Latent risk to harden (not currently firing)
`migration_2026_06_11/l25_merge_safe.py` dedup keeps a row iff `ts > running_max per (slug,outcome)` — a **monotonic filter**, not an exact `(slug,outcome,ts)` dedup. A single corrupt/far-future timestamp would poison a key and silently drop all later rows for it. **0 mid-window data-stops observed** (so it isn't happening), but recommend switching to an exact-triple `seen`-set dedup for safety on the next refresh.

## 6. Minor recommendations
1. **Relabel "10 Hz" → "~1 Hz dedup-on-change"** wherever it appears (CLAUDE.md L25 convention note is factually wrong). `subsample_1hz=False` stays correct (load all rows).
2. **Late-start** is low fill-impact; only fix (subscribe at market creation, à la the Kalshi pre-subscribe lesson) if you specifically need early-window book state.
3. **Depth:** only top-25 persisted → deep walks (~few % of fills) invisible. Accept, or widen persisted depth (heavier storage).
4. The TVRUST tick-recorder (moat spec I1) recording the live WS BookMirror would give a true high-freq tape going forward — but **lower priority than I claimed**, since the collector is already ~92–96% faithful.

## 7. Impact on prior conclusions (corrections)
- **`SUMPAIR_B945_ERROR_AUDIT_AND_TEST_PLAN_2026_06_16.md` §3b (T1 result) and Finding #2 are CORRECTED** by this doc: the feed is NOT blind to ~half the fills; it's ~92–96% faithful. The "build the racer because our offline data is blind" justification is **withdrawn** — the racer's case reverts to the **original b945 LIVE-execution thesis** (being first at new levels for live maker quoting), which T1 does **not** speak to either way.
- Lesson (ground-truth rule): the trade tape is a **data-API 5 s poll** with a write-time `local_timestamp_us` — any book↔trade microstructure join MUST use `timestamp_us` (exchange) and account for its 1 s granularity.

## 8. FIX SPEC — persist the `price_change` delta stream (storedata / VPS3 collector)
**Goal:** capture the high-frequency order-level book evolution the collector already receives, so maker/queue
modeling (b945 ladder, sum-pair maker capture) has the data it needs. Scope to bound the volume that drove the
Phase 15-05 removal.

**Where:** `/opt/storedata/src/storedata/collectors/polymarket.py` `_handle_price_change` (currently no-op DB-wise);
`storedata-collector.service` on VPS3. **Owner: storedata agent** (collector is their domain, like the resolution engine).

**What to add:**
1. **New table `orderbook_deltas_v2`** (narrow rows): `timestamp_us, local_timestamp_us, market_id, slug, asset_id, outcome, outcome_id, side('bid'|'ask'), price, size, hash, source`. Index on `(slug, timestamp_us)`.
2. In `_handle_price_change`, for **crypto up/down tokens only** (the ~150 we already persist book for — NOT all ~380; this is the volume guard), append each delta `(price, size, side)` to a `_delta_buffer`, flushed via `copy_records_to_table` like `_ob_buffer`. Skip non-crypto tokens (the journald-flood source).
3. Optional volume guard: only persist deltas while a window is active (slot_start−120s … slot_end+60s) — bounds rows to the windows we backtest.
4. Keep the existing full-`book` snapshots as **keyframes** (don't remove them) — offline reconstruction = start from a keyframe, apply subsequent deltas → full book at every delta timestamp (true ~10 Hz+).

**Volume estimate:** ~574 deltas/s aggregate × ~40% crypto ≈ 230/s × narrow rows ≈ ~20 M rows/day uncompressed; with the active-window guard, far less. Comparable to `trades_v2`. (The Phase-15-05 journald flooding was from *logging* every delta at debug, not from the write itself — keep logging off, persist quietly.)

**Pull/canonical:** add an `orderbook_deltas` pull to the L25 refresh (same `\copy ... WHERE timestamp_us >= T_START AND slug LIKE '<asset>-updown-%'` pattern) → new canonical `orderbook_deltas/{asset}.parquet` + a `load_orderbook_deltas()` + a `reconstruct_book_10hz(slug, outcome)` helper (keyframe + apply deltas).

**Acceptance:** for a sample of active btc-15m slugs, reconstructed-from-deltas book has ≥10 Hz effective cadence and the §3 fill-visibility residual drops from ~8% toward ~0 (transients now captured). THEN re-run the maker/queue (b945 ladder) sim on delta-resolution book — the queue-position model finally has its input.

**Interim (no collector change):** the TVRUST tick-recorder (moat spec I1) recording the live WS `price_change` stream gives the same delta tape going forward, independent of storedata. Either path works; fixing storedata makes it canonical + historical-from-now.
