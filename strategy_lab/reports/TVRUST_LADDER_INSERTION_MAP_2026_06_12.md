# TVRUST — b945-Style Continuous GTC Maker Ladder: Insertion-Point Map
_2026-06-12. Read-only audit of `C:\Users\alexandre bandarra\Desktop\TVRUST` (commit state: local `a0ebbe4` + prior, NOT pushed/deployed). Cross-referenced against `B945_ARTICLE_INFRA_GAP_ANALYSIS_2026_06_12.md`._

---

## 1. Strategy Abstraction

### Current shape

| Symbol | Location | Role |
|---|---|---|
| `SniperV5Sleeve` struct | `crates/tv-strat-sniper/src/sleeves.rs` | Static descriptor — `sleeve_id`, `asset`, `tf`, `direction ("BOTH"\|"UP"\|"DOWN")`, `offsets: &'static [i64]`, `gates: Vec<GateRef>`, exit knobs | 
| `GateRef` / `GateFn` | `crates/tv-strat-sniper/src/sleeves.rs:34,27` | Pure fn `(Direction, fire_us, &Panels, &GateArgs) -> bool`; `SniperV5Sleeve::all_gates_pass` evaluates them |
| `eval_sleeve_fire` / `eval_sleeve_fire_dir` | `crates/tv-engine/src/loops/sniper_v5.rs:80,108` | PURE pipeline: rails → gates → `paper_fill_vwap` → `EvalOutcome{fired, entry_vwap}` |
| `SniperController::run` | `crates/tv-engine/src/controllers/sniper.rs:1125` | Outer loop: 5s discovery tick → per-(sleeve×offset) `fire_at_offset` tokio task |
| `fire_at_offset` | `crates/tv-engine/src/controllers/sniper.rs:1188` | Sleeps until `slot_start_us + offset_s*1e6`, then calls `eval_sleeve_fire_dir` once per direction |

**The fire model is strictly single-shot per (sleeve, slot, offset):** one `tokio::time::sleep_until` → one gate eval → one paper fill → one event emitted. There is **no mechanism for a strategy to emit a stream of quote intents** over a window. The controller is unaware of resting orders, cancel/replace cycles, or mid-window state.

### What a ladder needs that does not exist

The ladder is fundamentally a **stateful continuous-quoting controller**, not a single-shot gate evaluator:

- Runs for the full window duration (~900s for 15m) rather than firing at one offset
- Maintains per-token resting order IDs (Up and Down, multiple price levels)
- Reacts to every book update (sub-second cancel/replace loop)
- Accumulates fill inventory and tracks pair fraction
- Logs per-tick telemetry (target quotes, would-be fills, pvs, latency)

**Invasiveness: NEW crate or module.** The ladder cannot be expressed as a `SniperV5Sleeve` (no offsets array, no gates, no single fire_us). It needs its own controller type and its own tokio task pattern.

**Reuse available:**
- `BookState` + `run_dynamic` (feeds the live book, same WS mirror) — direct reuse
- `GammaSlotProvider` / `TokenPublishingSlotProvider` — can discover the market and warm the book
- `EventSink` + `insert_event` — ladder telemetry rows land in the same `trading.events`
- `PolyClobClient::cancel_order` + `post_order` — cancel/replace primitives exist
- `DEFAULT_LIVE_ROSTER` + `TV_LIVE_ONLY_SLEEVE_IDS` env gate — same registration pattern

---

## 2. Poly Book Feed

### Current shape

| Symbol | Location | Role |
|---|---|---|
| `BookState` | `crates/tv-feeds/src/poly_book.rs` (struct at ~line 85) | In-memory `BTreeMap` per token; `apply_at` stamps freshness; `snapshot(token_id, ts_ms) -> Option<L25BookSnapshot>` |
| `run_dynamic` | `crates/tv-feeds/src/poly_book.rs` (fn ~line 345) | Single WS connection; receives `watch::Receiver<Vec<String>>` token list; incremental subscribe on new tokens; prunes at `MAX_SUBSCRIBED_TOKENS = 32`; reconnects on disconnect |
| `TokenPublishingSlotProvider` | `crates/tv-engine/src/controllers/sniper.rs:401` | Decorator over `GammaSlotProvider`; sends discovered Up+Down token IDs into the `watch::Sender<Vec<String>>` that feeds `run_dynamic` |
| `BookFreshnessCfg` / `acquire_book` | `crates/tv-engine/src/controllers/sniper.rs:150,205` | 3-tier: WS mirror (age check) → REST `/book` retry → fail-closed |

**Single WS connection confirmed.** The book is exposed as a **mutex-guarded snapshot** (`Arc<Mutex<BookState>>`); callers lock it, call `.snapshot(token, now_ms)`, and get a frozen `L25BookSnapshot{bids, asks, ts_ms}`.

### N-connection racer insertion point

The racer (`tv-feeds-racer` per the B945 infra gap analysis, labeled A1) would replace or wrap `run_dynamic`. The consumer interface is already stable:
- Input: `watch::Receiver<Vec<String>>` (token list)
- Output: `Arc<Mutex<BookState>>` mutations via `state.lock().apply_at(evt, ts_ms)`

A racer could spawn N tasks each calling a variant of `run_dynamic`, all writing to the **same** `BookState` mutex — the `apply_at` + BTreeMap merge is idempotent (last-writer-wins per price level; correct for a dedup-first-wins book mirror). No consumer change needed.

**Effort for racer: M** (new spawning logic in `main.rs` + optional per-connection latency tracking; `BookState` itself unchanged).

### Book stream for continuous quoting

For the ladder's sub-second requote loop, the controller needs a **notification on every book change**, not just a point-in-time snapshot. Two options:
1. **Poll**: task loops `tokio::time::sleep(Duration::from_millis(100))` + lock + snapshot — simple, matches Python's 10Hz `poly_maker_loop`.
2. **Notify channel**: add a `watch::Sender<()>` that `apply_at` pings — zero-copy wake, sub-10ms latency.

Option 1 is sufficient for dry-run and matches the existing Python maker loop cadence. Option 2 is a future optimization.

---

## 3. Order Submission + Lifecycle

### Current shape

| Symbol | Location | Role |
|---|---|---|
| `LiveSubmit` trait | `crates/tv-engine/src/controllers/sniper.rs:952` | Single method: `async fn place_order(&self, req: &LiveOrderRequest) -> Result<LiveOrderResult, String>` |
| `LiveOrderRequest` | `crates/tv-engine/src/controllers/sniper.rs:923` | `token_id`, `side (Buy\|Sell)`, `price`, `size`, `client_order_id` |
| `LiveOrderResult` | `crates/tv-engine/src/controllers/sniper.rs:937` | `status`, `filled_shares`, `avg_price`, `order_id: Option<String>` |
| `ClobLiveSubmit::place_order` | `crates/tv-engine/src/live_submit.rs:219` | Entry = BUY GTC @ 0.99, exit = SELL FAK @ 0.01; decodes `makingAmount`/`takingAmount` |
| `PolyClobClient::cancel_order` | `crates/tv-venues/src/clients/poly_clob.rs:232` | `async fn cancel_order(&self, order_id: &str) -> Result<Value, PolyClobError>` |
| `PolyClobClient::post_order` | `crates/tv-venues/src/clients/poly_clob.rs:164` | Raw order post |
| `PolyClobClient::get_order_book` | `crates/tv-venues/src/clients/poly_clob.rs:205` | REST `/book` per token |

**No resting-order tracking, no cancel-all, no open-order query.** The current `LiveSubmit` trait is single-shot (place one order, get one result). The `ClobLiveSubmit` does not retain any order IDs; there is no `get_open_orders` call exposed in `PolyClobClient` (grep confirms it does not exist in the crate).

### What to add for cancel/replace

The raw `PolyClobClient::cancel_order(order_id)` **already exists**. The gap is at the **controller layer**:

1. **`LadderOrderTracker`** (new struct, ~50 lines): `HashMap<(token_id, price_level) → order_id>` + `place_gtc_level(token, price, size)` + `cancel_level(token, price)` + `cancel_all_token(token)`.
2. **`LadderLiveSubmit`** (new impl of a new trait, or extend `LiveSubmit`): wraps `PolyClobClient`, calls `post_order` with GTC type, stores returned `order_id`, calls `cancel_order` on requote.
3. For paper mode: `LadderPaperSubmit` — same interface, simulates fills by comparing placed price vs live `BookState` ask/bid; logs would-be fills.

`PolyClobClient` is feature-gated (`#[cfg(feature = "clob-sdk")]`) same as `ClobLiveSubmit`. The ladder live submit must carry the same gate.

**Effort: M** (new tracker struct + new submit impl; `cancel_order` primitive exists).

---

## 4. Paper vs Live Plumbing

### Current paper shape

| What | How |
|---|---|
| Paper fill | `paper_fill_vwap(panels, token_id, stake_usd)` in `sniper_v5.rs:42` — walks ask ladder, returns VWAP or `None` |
| Event emitted | `emit_fire(sink, &fire_result)` → `EngineEvent{kind:"fire"\|"fire_skip", sleeve_id, data_json}` |
| DB write | `GrpcDbSink::emit` calls `insert_event(db, kind, sleeve_id, data)` (best-effort; bus write never fails) |
| No-DB mode | Events land on gRPC bus only; `trading.events` write skipped silently |

**No paper fill simulator exists for maker/resting orders.** The existing `paper_fill_vwap` is a taker book-walk (walks asks). For a resting-bid paper sim you need the inverse: compare the ladder's placed bid prices against the live `BookState` asks — a bid at price P gets a would-be fill if the ask side crosses below P.

### Dry-run paper ladder design (minimal)

For zero-capital dry run: NO actual orders placed. Instead:

1. **Snapshot the live book** every ~100ms (poll `BookState`).
2. For each price level in the target ladder, check: does `ask_price <= bid_target`? If yes → would-be fill.
3. Accumulate `would_be_fill_up_shares` + `would_be_fill_dn_shares` per window.
4. Compute `pair_fraction = min(up_shares, dn_shares) / max(up_shares, dn_shares)`.
5. Emit a `ladder_tick` event every N seconds and a `ladder_summary` event at window end.

All of this is purely in-process with no CLOB calls. The live book from `BookState` IS the feed signal.

**Effort: S** (the poll + would-be fill check is ~100 lines; no new infrastructure).

---

## 5. Telemetry / Persistence

### Current schema

`trading.events` table: `(event_id UUID, at TIMESTAMPTZ, sleeve_id TEXT, position_id UUID, order_id UUID, kind TEXT, data JSONB)`.

Write path: `tv_persistence::insert_event(db: &RwDb, kind: &str, sleeve_id: Option<&str>, data: serde_json::Value)` at `crates/tv-persistence/src/events.rs:61`.

Read path: `recent_events(db, limit, kinds)` + gRPC `SubscribeEvents` stream.

### Ladder telemetry plan

No schema changes needed. New `kind` values written to existing table:

| kind | cadence | data payload |
|---|---|---|
| `ladder_tick` | every 10s (or book-change based) | `{slot, up_bid_target, dn_bid_target, up_would_be_shares, dn_would_be_shares, book_age_ms, pvs_estimate}` |
| `ladder_summary` | once at window end | `{slug, pair_fraction, total_up_fills, total_dn_fills, net_pvs, elapsed_s}` |
| `ladder_quote` | per requote (live only) | `{token_id, old_order_id, new_order_id, old_price, new_price, cancel_latency_us}` |

For dry-run: `ladder_tick` + `ladder_summary` only. No `ladder_quote` (no real orders).

Per-tick latency tape: embed `{book_snap_latency_us, tick_processing_us}` in `data`. No separate table needed.

**Effort: S** (reuse `insert_event` as-is; define new JSON shapes in the ladder controller).

---

## 6. Discovery / Early Placement

### Current shape

`GammaSlotProvider::discover` (`crates/tv-engine/src/controllers/sniper.rs:378`) calls `GammaClient::discover_window(asset, tf, now_unix, max_ahead_s)` which:
1. Calls `build_slug(asset, tf, now_unix)` → slug for the window **containing `now_unix`** (i.e., the CURRENT or next window based on floored timestamp)
2. Fetches `GET /events?slug={slug}&limit=1`
3. Rejects `is_far_future` where `slot_start_unix > now_unix + max_ahead_s` (currently 86400s = 1 day)

**Key finding:** `build_slug` computes `slot_start = (now_unix / tf_sec) * tf_sec` — it always generates the slug for the window that CONTAINS `now_unix`, not a future window. To discover the **next** window (which opens in the future), you must compute `slot_start = ((now_unix / tf_sec) + 1) * tf_sec`.

**The early-placement requirement (from b945 forensics):** btc-15m markets accept orders up to ~24h before `slot_start`. The far-future guard rejects these today (`is_far_future` with `max_ahead_s=86400` would ALLOW a 24h-ahead window, but `build_slug` never generates such a slug).

### Insertion point for early placement

`GammaSlotProvider::discover` or a new `EarlySlotProvider` that:
1. Calls `build_slug` for the NEXT N windows (N=2 covers current + next 15m; for 24h coverage call with `now_unix + k*900` for k=1..96)
2. Passes `max_ahead_s = 86_400` (already the default) so the far-future guard allows it
3. Returns `SlotInfo` with `slot_start_us` in the future — the ladder controller then places orders immediately (not sleeping to `slot_start_us`)

The `TokenPublishingSlotProvider` then publishes the UP/DOWN tokens for book-warming, which already works for future windows.

**Note:** `GammaSlotProvider` currently has `max_ahead_s: 86_400` by default — the guard would PASS for a 24h-ahead window. The only change needed is to generate the future-window slug. **Effort: S** (change `build_slug` call to `now_unix + 900` for next window; add a loop for k windows).

---

## 7. Config / Roster

### Current shape

| Symbol | Location | Role |
|---|---|---|
| `DEFAULT_LIVE_ROSTER` | `crates/tv-engine/src/main.rs:841` | `[&str; 5]` — the 5 live sleeve IDs |
| `resolve_live_only()` | `crates/tv-engine/src/main.rs:850` | Reads `TV_LIVE_ONLY_SLEEVE_IDS`; `*`/`all` → full shadow roster; CSV → custom set; empty → `DEFAULT_LIVE_ROSTER` |
| `filter_roster()` | `crates/tv-engine/src/main.rs` | Filters `Vec<SniperV5Sleeve>` to the live set |
| Loop gates | `main.rs` | `if settings.tv_poly_sniper_v5_enabled { ... }` — each loop gated by an env flag |
| Live arm gate | `main.rs:~line 550` | `TV_POLY_SNIPER_V5_LIVE_ENABLED=true` + `TV_POLY_SNIPER_V5_LIVE_ALLOWLIST` CSV gates real order placement |

The ladder is NOT a `SniperV5Sleeve` — it does not belong in `sniper_v5_sleeves()` and cannot be filtered via `resolve_live_only`. It needs its own loop task and its own env gates.

### Minimal config for `poly_ladder_btc_15m` in PAPER

Add to `tv_config::Settings` (mirrors the Python `TV_*` env-name convention):

```
TV_POLY_LADDER_ENABLED=true          # spawns the ladder loop task
TV_POLY_LADDER_LIVE_ENABLED=false    # false = dry-run (no real orders)
TV_POLY_LADDER_ASSET=BTC
TV_POLY_LADDER_TF=15m
TV_POLY_LADDER_NOTIONAL_PER_LEVEL=1  # $ per price level (paper: ignored, real: $1)
TV_POLY_LADDER_LEVELS=10             # price levels per side
```

In `main.rs`, add after the existing sniper-v5 spawn block:

```rust
if env_flag("TV_POLY_LADDER_ENABLED") {
    let ladder_stop = stop_rx.clone();
    let ladder_book = book_state.clone();    // same Arc<Mutex<BookState>>
    let ladder_sink = sink.clone();
    let ladder_gamma = gamma_client.clone(); // same GammaClient
    tasks.spawn(async move {
        tv_engine::loops::poly_ladder::run(
            "BTC", "15m",
            ladder_book, ladder_gamma, ladder_sink,
            false, // live_enabled = false → paper
            ladder_stop,
        ).await;
    });
}
```

The ladder loop reuses the same `book_state` and `gamma_client` already alive. No new connections needed for paper mode.

---

## Surface Summary Table

| # | Surface | File : key lines | Current shape | For ladder: reuse / extend / new | Effort |
|---|---|---|---|---|---|
| 1 | Strategy abstraction | `tv-strat-sniper/src/sleeves.rs` `SniperV5Sleeve`; `tv-engine/src/controllers/sniper.rs:1125,1188` `SniperController::run` + `fire_at_offset` | Single-shot gate→fill per offset; NO continuous quoting | **NEW** `LadderController` with its own tokio loop (poll book → compare targets → requote or log would-be fills) | L |
| 2 | Poly book feed | `tv-feeds/src/poly_book.rs` `BookState` + `run_dynamic`; `main.rs` `tok_tx/tok_rx` watch channel | Single WS, `Arc<Mutex<BookState>>` snapshot consumer | **REUSE** same `BookState` + `run_dynamic` + `tok_tx`; add 100ms poll in ladder loop | S |
| 3 | Order submit + lifecycle | `tv-engine/src/live_submit.rs` `ClobLiveSubmit`; `tv-venues/src/clients/poly_clob.rs:232` `cancel_order` | Single-shot `place_order`; `cancel_order` exists; NO open-order tracking | **EXTEND** — new `LadderLiveSubmit` + `LadderOrderTracker` using existing `PolyClobClient::cancel_order` + `post_order` | M |
| 4 | Paper / dry-run | `tv-engine/src/loops/sniper_v5.rs:42` `paper_fill_vwap`; `tv-engine/src/sink.rs` `EventSink` | Taker book-walk; no maker fill sim | **NEW** maker-side would-be fill check (bid vs live ask); emit `ladder_tick`/`ladder_summary` via existing `EventSink` | S |
| 5 | Telemetry / persistence | `tv-persistence/src/events.rs:61` `insert_event`; `trading.events` schema | `(kind, sleeve_id, data JSONB)` — extensible | **REUSE** `insert_event` with new kind strings (`ladder_tick`, `ladder_summary`, `ladder_quote`) | S |
| 6 | Discovery / early placement | `tv-venues/src/clients/gamma.rs:47,232` `build_slug` + `discover_window`; `sniper.rs:337` `GammaSlotProvider` | Discovers window CONTAINING `now_unix`; far-future guard allows 24h ahead | **EXTEND** `GammaSlotProvider` (or new `EarlySlotProvider`) to also generate slug for `now_unix + 900` (next window); rest of machinery unchanged | S |
| 7 | Config / roster | `tv-engine/src/main.rs:841` `DEFAULT_LIVE_ROSTER` + `resolve_live_only`; `tv-config` Settings | `SniperV5Sleeve` filter + loop env gate per loop | **EXTEND** — add `TV_POLY_LADDER_ENABLED` + `TV_POLY_LADDER_LIVE_ENABLED` env flags; ladder is NOT a `SniperV5Sleeve` entry | S |

---

## Minimal Zero-Capital Dry-Run Path

Goal: paper ladder fires against real feed, observable in `trading.events` + logs, no real orders placed.

### Change list (smallest set, ordered)

**Step 1 — New `crates/tv-engine/src/loops/poly_ladder.rs` (L, ~300 lines, NEW file)**

Core loop. Does everything in-process, no CLOB calls:

```
loop every 100ms:
  1. discover_window("BTC", "15m", now, max_ahead_s=86400)
     → GammaSlot { up_token_id, down_token_id, slot_start_unix }
  2. if slot_start > now + 86400: skip (too far ahead)
  3. book = book_state.lock().snapshot(up_token_id, now_ms)
           + book_state.lock().snapshot(dn_token_id, now_ms)
  4. compute target_ladder: N levels both sides
     - bid_price_k = mid - k * tick (weighted by price, cap > 0.85)
  5. for each level k: would_be_fill_up += check_crossing(bid_price_k, book_up.asks)
     same for dn
  6. accumulate window totals
  7. if (now - last_tick_emit) >= 10s: emit ladder_tick event
  8. if now >= slot_end + 5s: emit ladder_summary, reset accumulators
```

All branches behind `if !live_enabled { ... simulate ... } else { ... cancel/replace ... }`.

**Step 2 — Extend `GammaSlotProvider` to discover NEXT window (S, ~10 lines added to `sniper.rs`)**

Add `discover_next_window` method to `GammaSlotProvider` or add a `next_window_offset_s: i64` field (default 0, set to `tf_sec` for early placement):

```rust
// In discover(): also generate slot for now + tf_sec_i64
let next_slug_start = (now / tf_sec + 1) * tf_sec;
```

Or simpler: in the ladder loop, call `GammaClient::discover_window(asset, tf, now + tf_sec_i64, max_ahead_s)` directly. The method already exists and would accept the next-window `now`.

**Step 3 — Register UP/DOWN tokens with the existing book mirror (S, ~5 lines in `main.rs`)**

Pass the same `tok_tx` sender into the ladder loop so it can publish next-window tokens. The ladder calls `tok_tx.send(vec![up_token_id, dn_token_id])` — `run_dynamic` subscribes them incrementally (already handles this).

**Step 4 — Add env flag + spawn in `main.rs` (S, ~20 lines)**

```rust
if env_flag("TV_POLY_LADDER_ENABLED") {
    tasks.spawn(async move {
        tv_engine::loops::poly_ladder::run(
            book_state, gamma_client, tok_tx_clone, sink, stop_rx,
            /*live_enabled=*/ false,
        ).await;
    });
}
```

No `Settings` struct change needed for the minimal paper path — read env vars directly in the loop with `std::env::var`.

**Step 5 — Verify observability**

With `TV_POLY_LADDER_ENABLED=true` (no creds, no live flag):
- `journalctl -u tv-rust-engine | grep ladder_tick` → per-window ticks visible
- `psql tradingvenue_rust -c "SELECT kind, data FROM trading.events WHERE kind LIKE 'ladder_%' ORDER BY at DESC LIMIT 20"` → summary rows
- `pair_fraction` in `ladder_summary.data_json` is the key metric (target: approach b945's ~44%)

### NOT needed for dry run (defer to live phase)

- `LadderLiveSubmit` / `LadderOrderTracker` (no real orders)
- `tv-feeds-racer` N-connection WS (single connection is fine for observability)
- New `tv-config` Settings fields (env vars read directly)
- Schema migration (new `kind` values need no DB schema change)
- EIP-712 signing for ladder orders (only needed for live arm)

### Total dry-run scope

| Item | Effort | New/Extend |
|---|---|---|
| `crates/tv-engine/src/loops/poly_ladder.rs` | L (~300 lines) | NEW |
| `loops/mod.rs` — add `pub mod poly_ladder` | S (1 line) | EXTEND |
| `main.rs` — spawn block + env flag | S (~20 lines) | EXTEND |
| `GammaClient` next-window call | S (~5 lines in loop) | REUSE |
| `tok_tx` share into ladder loop | S (~5 lines in main.rs) | REUSE |

No new crates, no new dependencies (reuses `tokio`, `tracing`, `serde_json`, `tv-feeds`, `tv-venues`, `tv-persistence` already in the workspace). Compiles without `--features clob-sdk`. Fail-closed: if `GammaClient` returns `None` the loop logs and retries next tick.

---

## Key Invariants to Preserve

- **inv #13:** token IDs come ONLY from `GammaClient::discover_window` (gamma), never from Storedata. The ladder must use the same `GammaClient` call.
- **inv #7:** no Kill RPC in the proto. A kill is triggered only by a `trading.events(kind='kill_switch_requested')` row. The ladder loop must check the `stop` watch channel (already the pattern for all loops).
- **Live arm fail-closed:** `TV_POLY_LADDER_LIVE_ENABLED=false` (default) must guarantee zero CLOB calls. The ladder loop structure must check this flag before any `PolyClobClient` call.
- **Slot discovery dedup:** the sniper loop already dedupes by `(slug, asset, tf, slot_start_us)`. The ladder loop should maintain its own `current_slug` state and reset accumulators only when the slug changes.
