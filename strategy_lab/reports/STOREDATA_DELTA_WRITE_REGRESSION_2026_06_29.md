# STOREDATA — `orderbook_deltas_v2` write regression (EMPTY despite events)
**2026-06-29. For the storedata agent. The delta capture worked ~2026-06-16 (~1 M rows pulled, 145/s) and has since regressed to writing NOTHING.**

## Symptom (verified live 2026-06-29 21:36 UTC+2)
- `orderbook_deltas_v2` = **0 rows** (`pg_total_relation_size` 32 kB, `reltuples = -1` → recreated, never analyzed). `max(timestamp_us)` NULL.
- Collector **alive** (`systemctl is-active` = active); `ws_event_distribution` shows **`price_change` ≈ 434k**/cycle, `book` ≈ 9.5k → the WS stream + parse are fine.
- `orderbook_snapshots_v2` **fresh** (0.15 s stale) → the snapshot write path works.
- **15m crypto markets ARE active + tracked:** last-5-min snapshots — btc-15m 640 / eth-15m 208 / sol-15m 242 (plus 5m). So the 15m TF-scope is NOT finding nothing.
- **Active-window gate is sane:** current `btc-updown-15m-1782761400`, `now_s − slot_start = 392 s` → inside `[slot_start−LEAD, slot_end+LAG]`. Gate passes.

So every gate that should pass does pass, yet 0 rows are written.

## Localization — the per-change `asset_id` path
`_handle_price_change` (the 2026-06-16 delta impl) appends to `_delta_buffer` only if, per change:
`info = _asset_info.get(change["asset_id"])` is not None AND `_snapshot_received.get(change["asset_id"])` AND `info["timeframe"] in _DELTA_TIMEFRAMES` AND `_delta_window_active(info, now_s)`.
TF-scope + active-window verified OK above. So the failure is the first gate or the flush:

### Suspect 1 — asset_id mismatch (everything skipped, `_delta_count == 0`)
`change.get("asset_id")` from `price_changes[]` is not a key in `_asset_info` / `_snapshot_received`. Those are populated by `_handle_book` using the **book channel's** asset_id. If the `price_change` per-change asset_id differs in format/source from the `book` asset_id, **every change hits `info is None` (or `not _snapshot_received`) → skipped → empty table.** This is the most likely regression (the per-change asset_id was the 2026-06-16 change).

### Suspect 2 — flush not wired (buffered, never written, `_delta_count` large)
`_delta_buffer` appends, but `_flush_delta_buffer` isn't called from the flush loop (`_flush_buffer`) → the buffer grows in memory and never `copy_records_to_table`s.

## Decisive test (1 line)
Log once: `log.info("delta_dbg", count=self._delta_count, buf=len(self._delta_buffer))`.
- `count == 0` → **Suspect 1** (asset_id gate). Then dump one raw `price_change` frame's `asset_id` and compare to (a) `_asset_info` keys and (b) `orderbook_snapshots_v2.asset_id` values for the same market. Align the lookup to whatever id the book/discovery uses.
- `count` large but table empty → **Suspect 2** (flush). Wire `_flush_delta_buffer` into the flush loop (twin of `_flush_ob_buffer`); confirm `copy_records_to_table('orderbook_deltas_v2', ...)` runs + clears the buffer; check for a swallowed flush exception.

## Impact
- **~13 days of delta data lost** (Jun 16 → Jun 29). Accrual restarts from zero once fixed.
- Blocks the whole Phase-2 maker/queue analysis (no delta data to consume). The research pipeline (`load_orderbook_deltas`, `reconstruct_book_10hz`, `phase2_maker_queue_sim`) is built and waiting.

## After the fix
Confirm `orderbook_deltas_v2` accrues at ≫ the snapshot rate for active btc/eth/sol-15m (target ≥10× snapshots, ~145/s/token on btc-15m). Then the research side pulls → canonical → Phase-2.
