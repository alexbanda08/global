# STOREDATA SPEC — persist Polymarket `price_change` deltas (collector bug fix)
**2026-06-16 · for the storedata agent · system: storedata only (VPS3). Self-contained; touches nothing outside storedata.**

## 1. The bug
The Polymarket collector receives the venue's **high-frequency order-book delta stream and discards it.** Only periodic full-`book` snapshots are persisted.

Evidence (read in `/opt/storedata/src/storedata/collectors/polymarket.py`):
- `_handle_price_change(...)` (~line 671) docstring: **"Phase 15-05: NO DB write … Delta events update in-memory state via the latency correlator callback only — no row is appended."** Its own comment: the branch **"fires hundreds of times/sec on a normal feed."**
- `_handle_book(...)` (~line 591) is the *only* writer → `orderbook_snapshots_v2`, gated by `BookSnapshotDeduper.should_emit` (lossless blake2b of exact top-25). Deduper docstring: **"10–20× row-reduction vs naive every-event writes"** → inbound rate is ~10–20× the persisted ~1–2 Hz.
- Measured: `orderbook_snapshots_v2` ≈ **1–2 rows/s** per active btc-15m token (verified vs a research re-pull: source 1624 vs canonical 1620 for one slug — the pull is faithful; the sparsity is the collector).

Consequence: the persisted full-book is ~92% faithful for **coarse fill visibility**, but **order-level book evolution — every order add/cancel, sub-100 ms transient levels, FIFO queue dynamics — is not in the data.** That stream is required for maker/queue modeling (passive-maker ladder, sum-pair maker capture). The deletion was deliberate (Phase 15-05) to stop journald flooding — but the flood was from **logging** every delta at debug, not from writing.

## 2. Fix — persist deltas to a new table, scoped to bound volume

### 2.1 New table (migration `scripts/009_orderbook_deltas_v2.sql`, mirror the 008 style)
```sql
CREATE TABLE IF NOT EXISTS orderbook_deltas_v2 (
  timestamp_us        bigint   NOT NULL,   -- exchange ts (ms→µs, from msg 'timestamp')
  local_timestamp_us  bigint   NOT NULL,   -- collector receipt (now_us)
  exchange            text     NOT NULL DEFAULT 'polymarket',
  market_id           text     NOT NULL,
  slug                text     NOT NULL,
  asset_id            text     NOT NULL,
  outcome             text     NOT NULL,
  outcome_id          smallint NOT NULL,
  side                text     NOT NULL,   -- 'bid' | 'ask' (from the change)
  price               numeric  NOT NULL,
  size                numeric  NOT NULL,   -- new resting size at that price (0 = level removed)
  hash                text,                -- msg 'hash' if present (dedup on reconnect)
  source              text     NOT NULL DEFAULT 'live'
);
CREATE INDEX IF NOT EXISTS ix_obd_v2_slug_ts ON orderbook_deltas_v2 (slug, timestamp_us);
CREATE INDEX IF NOT EXISTS ix_obd_v2_ts      ON orderbook_deltas_v2 (timestamp_us);
```

### 2.2 Collector change (`polymarket.py`)
- `__init__`: add `self._delta_buffer: list[tuple] = []` (twin of `_ob_buffer`); reuse `self._seen_trade_hashes`-style guard if you want delta-hash dedup on reconnect (optional).
- `_handle_price_change`: after the existing C-01 gate (`_snapshot_received`), for **crypto up/down tokens only** (the same `_asset_info` subset already used for book writes — i.e. `info = self._asset_info.get(asset_id)`; skip if `None` → that's the ~380→~150 narrowing that was the flood source), parse the message's `changes` array and append **one row per change** to `_delta_buffer` via `emit`-style tuple matching the table column order. Map: `timestamp` (ms)→`timestamp_us`, `now_us`→`local_timestamp_us`, `info['market_id'/'slug'/'outcome'/'outcome_id']`, each change's `price`/`size`/`side`, `msg['hash']`. **Keep the latency-correlator callback as-is.** **Do NOT log per delta** (the Phase-15-05 flood cause) — counts only, at INFO, in the flush.
- Flush: extend `_flush_buffer` to also call a new `_flush_delta_buffer` (copy of `_flush_ob_buffer` → `copy_records_to_table('orderbook_deltas_v2', _delta_buffer, columns=...)`); clear on success; on error log `delta_flush_error` with `lost_rows` (best-effort, never raise — same posture as the existing flushers).
- **Keep `_handle_book` / `orderbook_snapshots_v2` exactly as-is** — full-book rows are the **keyframes** for offline reconstruction (keyframe + apply deltas → full book at every delta ts).

### 2.3 Volume guard (so this doesn't recreate the Phase-15-05 problem)
- **Crypto-only scope** (the `_asset_info` filter) already cuts ~380→~150 tokens.
- **Optional active-window gate:** only buffer deltas when the token's window is live (`slot_start−120s ≤ now ≤ slot_end+60s`) — the windows research actually backtests. Bounds rows hard.
- Estimate: ~574 deltas/s aggregate × ~40% crypto ≈ ~230/s × narrow rows ≈ ~20 M rows/day uncompressed (far less with the window gate) — comparable to `trades_v2`. Writing is cheap; **just never log per-row.**

## 3. Acceptance
- `orderbook_deltas_v2` accrues rows during active btc/eth/sol-updown windows at ≫ the `orderbook_snapshots_v2` rate (target ≥10× for active tokens).
- For a sample active slug, **keyframe (full book) + replay deltas reconstructs a book at ≥10 Hz effective cadence.**
- journald/CPU unchanged (no per-delta logging).

## 4. Out of scope (explicit)
- **Nothing in Tradingvenue / TVRUST.** This is storedata only.
- The research/canonical side (pull `orderbook_deltas_v2` → `data/v4/canonical/orderbook_deltas/{asset}.parquet`, add `load_orderbook_deltas()` + `reconstruct_book_10hz()`) is a **separate downstream step in the research repo** — not this agent's job. This spec's deliverable ends at: deltas land in the storedata DB, reconstructable to ≥10 Hz.
