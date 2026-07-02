# TV AGENT SPEC — TVRUST delta tick-recorder (Rust client only)
**2026-06-16 · for the TVRUST engine agent · system: TVRUST (Rust) ONLY.**

> **⚠️ RETRACTED 2026-06-16 (operator scope correction).** TVRUST does NOT need to *persist/collect* a delta
> tape — that's **storedata's** job (the `orderbook_deltas_v2` collection feeds research/backtest). TV only
> needs the **live in-memory book** to fire/execute, which `BookState` already maintains by applying
> `price_change` deltas (`apply_inner` → `BookEvent::PriceChange`). **Do NOT implement this recorder.**
> **The REAL execution-critical TV item is a PARSE FIX, not recording:** `poly_book.rs` parses the WS
> `price_change` event with the key `changes` and a **message-level** `asset_id` (`:109,:117,:143`), but the
> live frame (verified by the storedata agent) is **`price_changes[]` with a PER-CHANGE `asset_id`** — so
> TVRUST is very likely producing **0 price_change events → the live book only updates on ~1 Hz full
> snapshots → stale for quoting**, silently degrading EVERY poly strategy (sniper/scalp/ladder/V2). Apply the
> SAME fix storedata did: accept both `price_changes`/`changes` keys + route/enrich each change by its own
> `asset_id`; verify against the live frame. (The latency tape — moat I3 — stays a valid TV item.) The
> recording rationale below is superseded; kept only for history.

> **Scope rules (read first):**
> - Implement in the **Rust client (TVRUST)** only. **Do NOT modify Python Tradingvenue** — it stays as-is; we port to Python later for parity once Rust is proven.
> - This is **independent of storedata.** TVRUST records its **own** live WS feed; it does not read/pull anything from the storedata collector. (A separate storedata spec handles that system.)
> - This realizes moat-spec I1 (tick recording) from `TV_AGENT_SPEC_TVRUST_MOAT_INFRA_2026_06_16.md`, made concrete and delta-focused.

## 1. Why
TVRUST's book mirror (`tv-feeds/src/poly_book.rs::run_dynamic`) receives the Polymarket CLOB WS stream — full `book` snapshots **and** high-frequency `price_change` deltas (order adds/cancels, hundreds/sec) — and applies them to the in-memory `BookState`, but **records nothing durably.** The delta stream is exactly what maker/queue modeling (the b945 ladder, sum-pair maker capture) needs and what a ~1 Hz full-book snapshot cannot give. Record it from TVRUST's own feed so we get a true ≥10 Hz, queue-resolution tape going forward — owned by TVRUST, no external dependency.

## 2. What to build
A **best-effort, off-hot-path** recorder that captures every parsed WS message (book keyframes + price_change deltas) for the subscribed window tokens and writes a rotated tape to disk. **The live book mirror must never block on it.**

### 2.1 Crate / module
- Add module `crates/tv-feeds/src/tick_recorder.rs` (or a small `tv-tick-recorder` crate). Deps: `arrow` + `arrow-ipc` (stream append is simplest; `parquet` if you prefer columnar-at-rest). Add to `tv-feeds/Cargo.toml`.
- `TickRecorder { tx: tokio::sync::mpsc::Sender<TickFrame> }` + a spawned writer task owning the file handles. Channel **bounded** (e.g. 65_536); the WS path uses `tx.try_send` and **drops + counts on full** (never `.await`, never block).

### 2.2 Frame schema (two record kinds → two Arrow files, rotated together)
- **keyframe tape** `book-<UTC-hour>.arrow`: `{recv_us:i64, exch_ts_us:i64, asset_id, slug, outcome, bid_price_0..24:f32, bid_size_0..24:f32, ask_price_0..24:f32, ask_size_0..24:f32}` — written on each full `book` message (the reconstruction anchor).
- **delta tape** `delta-<UTC-hour>.arrow`: `{recv_us:i64, exch_ts_us:i64, asset_id, slug, outcome, side:'bid'|'ask', price:f32, size:f32, hash}` — **one row per change** in each `price_change` message.
- `recv_us` = `Instant`/wall µs at parse; `exch_ts_us` = message `timestamp` (ms→µs).

### 2.3 Insertion point (`poly_book.rs::run_dynamic`)
- Where messages are parsed and applied to `BookState` (`state.lock().apply_at(...)`), add, behind `Option<&TickRecorder>`:
  - on full `book`: build the keyframe row from the parsed ladder → `rec.try_record_book(...)`.
  - on `price_change`: for each change → `rec.try_record_delta(...)`. **Ensure `run_dynamic` parses `price_change` deltas** (a correct mirror already must, to stay live; if it currently only takes full books, add delta apply + record).
- **Scope:** only the tokens already subscribed via the `watch::Receiver<Vec<String>>` (the active window tokens) — no extra subscriptions, no extra connections.
- **Hot-path safety:** the recorder call is `try_send` only. If the channel is full, drop and increment a `dropped` counter (emit in `feed_quality`/log every 10 s). The book apply proceeds regardless.

### 2.4 Writer task
- Owns rotating Arrow IPC stream writers (`book-*.arrow`, `delta-*.arrow`), rotate every `TV_POLY_TICK_RECORD_ROTATE_S` (default 3600) or on UTC-hour boundary; `fsync`/close on rotate. Batches rows (e.g. flush every 200 ms or 4096 rows). Best-effort: on write error, log + drop the batch, never crash the engine.

## 3. Config (`tv-config`, `TV_*` env names)
```
TV_POLY_TICK_RECORD_ENABLED=false        # default OFF → zero behavior change, recorder never spawned
TV_POLY_TICK_RECORD_DIR=/var/lib/tv/rust_ticks
TV_POLY_TICK_RECORD_ROTATE_S=3600
TV_POLY_TICK_RECORD_CHAN_CAP=65536
```
Spawn the writer task + wire the `TickRecorder` into `run_dynamic` in `main.rs` only when `TV_POLY_TICK_RECORD_ENABLED`. Default off ⇒ the 5 live sleeves + book mirror are byte-identical.

## 4. Acceptance
- Flag on, on Ireland `:8444` (or local): `delta-*.arrow` accrues at ≫ the `book-*.arrow` rate for active btc/eth/sol-updown tokens (target deltas ≥10× keyframes; ≥10 Hz effective).
- **Live book-mirror latency unaffected:** `dropped` counter ≈ 0 under normal load; no added await in the WS loop (verify the recorder call is `try_send`).
- An offline reader (Rust test or a Python helper) reconstructs a book at ≥10 Hz: load nearest keyframe, apply subsequent deltas, compare top-of-book to the next keyframe → matches.
- Flag off ⇒ no files, no task, no overhead.

## 5. Out of scope (explicit)
- **No Python Tradingvenue changes.** Rust client only. (Port to Python later for parity.)
- **No storedata interaction.** This records TVRUST's own WS; it does not read storedata's `orderbook_*` tables.
- Not the racer/pre-signed-grid/ladder-live items (separate moat-spec sections); this is solely the I1 delta tape.

## 6. Files / provenance
Insertion: `crates/tv-feeds/src/poly_book.rs` (`run_dynamic`, `BookState`), new `crates/tv-feeds/src/tick_recorder.rs`, `crates/tv-config` (env), `crates/tv-engine/src/main.rs` (spawn + wire). Context: `TV_AGENT_SPEC_TVRUST_MOAT_INFRA_2026_06_16.md` §I1, `L25_FEED_GAP_DIAGNOSIS_2026_06_16.md` (why the delta stream matters).
