# TV RUST AGENT — 🔴 P0 INCIDENT: engine crash-loop since ≤ Jul 15 10:00 UTC (fix NOW, before any punch-list work)
**2026-07-16 · TVRUST only · vps_ireland · tv-rust-engine · drop everything else until this is green.**

## What is happening (verified by operator-side audit, Jul 16 ~05:15 UTC)
- `tv-rust-engine` is crash-looping every ~15s, ~236 restarts/hour, continuously since at least **Jul 15 10:00 UTC** (journal window cut there — find the true start).
- Panic, every cycle:
  ```
  thread 'tokio-rt-worker' panicked at crates/tv-persistence/src/queries.rs:366:12:
  called `Result::unwrap()` on an `Err` value: ColumnDecode { index: "\"total\"",
  source: "value not representable as rust_decimal::Decimal" }
  → systemd: Main process exited, code=dumped, status=6/ABRT (core-dump)
  ```
- Root cause, **reproduced directly in psql**: the dedup sleeve-PnL query (`WITH deduped AS (... row_number ...) SELECT COALESCE(SUM((data->>'pnl_usd')::numeric),0) ...`) now returns
  `-8.2361891385767786897769753748435` — **31 decimal places**. `rust_decimal::Decimal` holds max 28 significant digits → decode fails → your `.unwrap()` aborts the whole runtime. `trading.events` has `resolve` rows with `pnl_usd` up to **31 fractional digits** (unrounded float math serialized at full precision). The query is permanently poisonous — every boot re-runs it (~7.5s, also >1s slow-threshold) and dies.
- Impact: the ENTIRE ladder paper fleet is dead since Jul 15 (~98% of windows `skipped_reason=no_book`, 0 fills, $0 on all 9 sleeves — books never warm in a 15s lifetime); sumpair_osc silent since Jul 15 01:46; snipers/scalp only firing in the seconds each boot survives. The v3.1 A/B ledger has a 20h+ hole.

## Fix (in this order)

### 1. Stop the bleeding — make the decode infallible (the actual bug)
- `queries.rs:366`: **remove the `.unwrap()`**. Change the query to bound the scale server-side: `SELECT COALESCE(ROUND(SUM((data->>'pnl_usd')::numeric), 8), 0)::numeric AS total` (8 dp is far beyond any real PnL precision). Decode via `try_get`; on decode error log `WARN pnl_sum_decode_failed` + return 0 rather than panicking.
- **Sweep the whole crate for the same pattern**: every `(data->>'…')::numeric` decoded into `rust_decimal::Decimal` gets the same `ROUND(...,8)` + try_get treatment. One poison row must never again take the engine down. NO panics reachable from DB row content — that's a hard invariant from the parent go-live spec (fail-closed, not fail-dead).

### 2. Fix the writer so poison rows stop being produced
- Find which emitter writes `pnl_usd` (and any other USD/share float) at full f64 precision into event payloads; round to 6 dp at serialization time (helper, applied to all money/share fields in event `data`). Do NOT rewrite/UPDATE historical rows — the reader-side ROUND in (1) already neutralizes them; the events table is append-only audit.

### 3. While you're in there (same restart, cheap)
- That dedup PnL query at 7.5s is the slow query already flagged in the item-5 dashboard work — add the index/materialization you planned so it's <1s. It runs at every boot on the hot path.

### 4. Verify recovery — acceptance evidence required
- Engine stays up **≥ 60 min** with zero restarts (`journalctl -u tv-rust-engine` shows one Started line; `systemctl show -p NRestarts` stops incrementing).
- Ladder fleet alive again: fresh `ladder_summary` rows with `skipped_reason` NOT `no_book` and non-zero `filled_up_sh/filled_dn_sh` on btc_5m_v3 within a few windows; sumpair_osc emitting again.
- The previously-crashing SUM endpoint/query returns a finite rounded value (show it).
- Find and report the **true crash-loop start time** (first ABRT in journal) and the first poison `resolve` row (ts + sleeve) so we can stamp the exact A/B outage window.

## Reporting
- Journal the outage in the ladder A/B ledger: outage window [start → recovery], all ladder/sumpair paper results inside it are VOID (not zero) — the v3.1 variant comparison clock effectively restarts at recovery.
- Report: root-cause confirmation, files/commits changed, the acceptance evidence above, and anything ELSE you find that was masked by the loop (e.g. whether the Jul 14 15:31 deploy introduced the poison writer — `git log` the pnl_usd emission path).
- Paper sleeve configs stay byte-frozen — this is a persistence/reader fix only, no strategy logic changes. Punch-list items (real-order fire-drill, dry-arm, CPU pinning) resume AFTER the 60-min-uptime acceptance.
