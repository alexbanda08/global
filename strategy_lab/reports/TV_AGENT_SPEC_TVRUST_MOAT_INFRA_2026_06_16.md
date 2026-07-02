# TV AGENT SPEC — TVRUST data-freshness instrument (the "moat" infra layers)
**2026-06-16 · for the TVRUST engine agent · target: build the instrument that can finally test the infra-moat thesis, on Ireland `:8444`, paper-first.**

This spec builds the **5 infrastructure layers** the 0xSurferX article calls the real moat ("the strategy logic is the easy 1%; the infra is the 99% that 99% can't repeat"). It is the **Part-B companion** to `SUMPAIR_B945_ERROR_AUDIT_AND_TEST_PLAN_2026_06_16.md` (read its §2 Findings + §3 test plan first) and **extends** `TV_AGENT_SPEC_RUST_LADDER_B945_2026_06_13.md` + `TVRUST_LADDER_INSERTION_MAP_2026_06_12.md`.

---

## 0. READ FIRST — reconciling the "speed is flat" directive

The 06-13 ladder spec §0 says *"SPEED IS NOT THE LEVER … do not build a sub-millisecond arms race."* **That is still correct AND does not conflict with this spec.** Two different axes:

- **Reaction latency** (how fast the ladder loop re-quotes against the book it already has): the 06-13 sweep showed this is **flat** → a **100 ms poll loop stays correct**. Do NOT build a sub-ms requote race. ✅ unchanged.
- **Feed completeness** (whether the book mirror even *sees* a price level appear before it's consumed): this was **never tested** — our offline conclusion came from a single-connection 10 Hz tape that structurally cannot see sub-100 ms churn (`ERROR_AUDIT §2 Finding #1`). The racer is a **feed-completeness instrument**, not a speed race.

So: **keep the 100 ms ladder poll; build the racer to widen what the book mirror sees, not to loop faster.** They are orthogonal.

### Go/no-go gate on the racer (I2)
The racer (I2) is **conditional** on test **T1 (feed-loss audit)** from the test plan:
> Build I2 only if T1 shows **≥~20% of real fills execute at price levels our 10 Hz snapshots never showed.** If T1 says <5%, the feed is fine, skip I2, and the offline numbers stand.

**Unconditional regardless of T1** (good hygiene + needed for the live tests L2/L3 either way): **I0 (commit+deploy+watchdog), I1 (tick recording), I3 (latency tape), I4 (warmup gate).**

---

## 1. Build order

| # | Layer | Conditional? | Effort | Why |
|---|---|---|---|---|
| **I0** | Commit + deploy the existing Stage-0 ladder; **deploy `tv-watchdog`** | NO — do first | S | The ladder (`poly_ladder.rs` ~640 lines) is **uncommitted/undeployed**; the **kill-path watchdog is NOT on the box** (live-arm safety hole). |
| **I1** | Durable raw **tick recording** (book + trade frames) | NO | M | The article's "record your own data" layer + the flow-capture denominator. Needed for T1/T2 *with our own feed* and for L1. |
| **I2** | **N-connection WS racer** + `feed_quality` | YES (T1) | M | The feed-completeness instrument. The disputed moat. |
| **I3** | **Per-hop latency tape** (recv→decision→submit→ack→fill) | NO | S–M | Replaces the assumed 85 ms (`Finding #3`); answers L2. |
| **I4** | Shared **data-quality / warmup gate** | NO | S | Already PARTIAL in the ladder; promote to a reusable layer; "bad-data window traded > missed window." |
| **I5** | **Pre-signed grid** + `LadderOrderTracker`/`LadderLiveSubmit` + **dense multi-level ladder** | live only (Stage-1+) | M–L | Real cancel/replace + EV-layering (lever a). Needed for L3. |
| **I6** | **CPU pinning** (`core_affinity`) | YES (I3 shows contention) | S | RE-OPENED (`Finding #5`): the old "speed flat" deferral was measured without racer load beside live Python TV. |

---

## 2. Each layer — insertion point, change, config, acceptance

### I0 — Commit + deploy Stage-0 ladder + deploy the watchdog (do first)
- **Files (already written, local-only):** `crates/tv-engine/src/loops/poly_ladder.rs`, `crates/tv-feeds/src/poly_trade.rs` (`TradeState` + `run_dynamic`), `loops/mod.rs`, `main.rs` spawn block. Commit them.
- **Deploy:** scp changed crates → on-box `cargo build --release --features clob-sdk` → restart `tv-rust-engine`. Set `TV_POLY_LADDER_ENABLED=true`, `TV_POLY_LADDER_LIVE_ENABLED=false` (paper).
- **🔴 SAFETY — deploy `tv-watchdog`:** the kill-path binary (R7) is built but **not running on Ireland.** No live arm of anything (ladder or sniper) may flip to live until the watchdog is up (independent creds, read-only pool, consumes `trading.events(kind='kill_switch_requested')`). This is a hard gate, not optional.
- **Acceptance:** `ladder_tick`/`ladder_summary`/`feed_quality` rows in `tradingvenue_rust.trading.events`; watchdog heartbeat visible; 5 live sleeves byte-identical (ladder isolated — its own book+trade WS mirrors, never touches the sniper `tok_tx`).

### I1 — Durable raw tick recording (`tv-feeds` + `tv-persistence`)
- **Insertion:** `poly_book::run_dynamic` (and `poly_trade::run_dynamic`) already apply deltas to in-memory `BookState`/`TradeState`. Add a **durable sink**: write each **deduped** book delta + trade print as a compact frame.
- **Storage:** append-only — either a partitioned file tape (NDJSON/parquet per window, like the VPS2 L25 collector) or a `trading.tick_tape` table. File tape preferred (1 TB/day raw is the article's number at full scale; we start at btc-15m only). Record `{ts_recv_us, asset_id, kind(book|trade), price, size, side, seq/hash, conn_id}`.
- **Config:** `TV_TICK_RECORD_ENABLED=true`, `TV_TICK_RECORD_DIR=/var/lib/tv/rust_ticks`, `TV_TICK_RECORD_ROTATE_S=900`.
- **Acceptance:** one btc-15m window's raw book+trade tape on disk; row count ≈ live book-update rate; **this tape becomes the input to re-run T1/T2 on OUR OWN feed** (not just canonical VPS2) — the apples-to-apples check.

### I2 — N-connection WS racer (`tv-feeds`) — **conditional on T1**
- **Insertion (from insertion map §2):** wrap/extend `poly_book::run_dynamic`. Spawn **N** tasks, each a `run_dynamic` variant on its own WS connection, **all writing the same `Arc<Mutex<BookState>>`** — `apply_at` + BTreeMap merge is idempotent (last-writer-wins per level, correct for first-wins dedup). Consumer interface unchanged.
- **Dedup:** first-wins by `(asset_id, seq)` or `(asset_id, book_hash)`; a frame already seen is dropped (and NOT re-recorded by I1).
- **Health/cull:** per-connection **jitter EMA** (inter-tick gap); every `cull_interval_s`, kill the slowest `cull_frac` and respawn; **stagger** connects across `stagger_ms`; **drop-first-tick** from each new connection (it carries a cached pre-connect snapshot).
- **Quality:** reject any tick with **>`reject_delta`** price jump from last-known-good (log + skip).
- **Config:** `TV_POLY_RACER_ENABLED`, `TV_POLY_RACER_N_CONNS=6` (**start 4–8, ramp empirically — do NOT jump to 100–300 before measuring the per-IP rate limit**), `TV_POLY_RACER_CULL_INTERVAL_S=4`, `TV_POLY_RACER_CULL_FRAC=0.1`, `TV_POLY_RACER_STAGGER_MS=1000`, `TV_POLY_RACER_REJECT_DELTA=0.15`, `TV_POLY_RACER_DROP_FIRST=true`.
- **Telemetry (`feed_quality`, 10 s):** `{n_conns, culled, dropped_first, rejected_delta, jitter_ema_ms_per_conn, dedup_first_wins_count, unique_levels_seen}`.
- **Acceptance (the L1 instrument):** `unique_levels_seen` and **flow-capture** measurably exceed the single-connection baseline on the same windows. If they don't move at N=6, the racer thesis is dead — log it and stop ramping.

### I3 — Per-hop latency tape (`tv-engine`)
- **Insertion:** stamp `Instant::now()`/µs at every hop on the ladder (and, when live, sniper) path: `t_recv` (WS frame in) → `t_dedup_win` (first-wins accepted) → `t_decision` (quote computed) → `t_submit` (POST sent) → `t_ack` (CLOB response) → `t_fill` (fill event). Carry the chain on the order/quote object.
- **Storage:** new `insert_event` kind `tick_latency` (reuse `tv-persistence::insert_event`, no schema change), payload = the per-hop µs deltas; aggregate p50/p95 emitted in `ladder_quote`.
- **Config:** `TV_LATENCY_TAPE_ENABLED=true`.
- **Acceptance (answers L2):** a latency distribution from Ireland. **If p50 submit-latency ≫ 85 ms, every latency-sensitive offline verdict must be re-baselined** (flag to operator).

### I4 — Shared data-quality / warmup gate (`tv-feeds`/`tv-engine`)
- **Status:** PARTIAL — already in `poly_ladder.rs` (stale-book pause, >15¢ outlier reject, 15 s warmup, `skipped_reason="warmup_fail"`). Promote to a **reusable function** so the sniper/scalp hot path can adopt it too (Finding: the momo fake-fill + stale-data sagas were exactly this bug class, and the sniper path has only NaN guards).
- **Rule:** 15 s pre-window warmup; require **≥3 clean ticks/token** with **no >5¢ jump** in the final 5 s; on failure **SKIP the window** entirely.
- **Config:** `TV_LADDER_WARMUP_S=15`, `TV_LADDER_WARMUP_MIN_TICKS=3`, `TV_LADDER_WARMUP_MAX_JUMP=0.05`.
- **Acceptance:** `feed_quality.warmup_pass` rate logged; skipped windows carry `skipped_reason`.

### I5 — Live order lifecycle + dense ladder (`tv-venues` + `tv-engine`) — Stage-1+
- **`LadderOrderTracker`** (new, ~50 lines): `HashMap<(token_id, price_level) → order_id>` + `place_gtc_level`/`cancel_level`/`cancel_all_token`. Primitives exist: `PolyClobClient::post_order` (`poly_clob.rs:164`, GTC) + `cancel_order` (`:232`).
- **`LadderLiveSubmit`** (new impl): wraps `PolyClobClient`, stores `order_id`s, fail-closed like `ClobLiveSubmit`, feature-gated `clob-sdk`.
- **Pre-signed grid:** at window open, pre-build + EIP-712-sign the grid (2 tokens × `n_levels` × `clip(price)`) on a 1¢ grid; hot path = lookup + POST. (Hygiene — don't sign in the loop — NOT a speed race, per §0.)
- **Dense multi-level ladder (lever a):** upgrade the Stage-0 single-clip-per-side to **`n_levels` across the near-mid band, clip ∝ price**, **skip levels > 0.85** (his measured −EV zone). Keep **MAKER-ONLY** (no taker-completion — fires 0/27,039 below sum 1.0). Keep **GLT cap Q≈4** + **AS skew γ=0.05** (the profit lever).
- **Config:** `TV_LADDER_N_LEVELS=12`, `TV_LADDER_CLIP_USD=5`, `TV_LADDER_MAX_PRICE=0.85`, `TV_LADDER_Q_CAP=4`, `TV_LADDER_AS_GAMMA=0.05`.
- **Acceptance (answers L3):** real GTC place/cancel against CLOB; `ladder_quote` rows with real latencies + rejection codes (NSF/timeout/ghost); **measured maker fill-rate at fresh levels** vs our FIFO ceiling.

### I6 — CPU pinning (`tv-engine`) — conditional on I3
- **Trigger:** only if the I3 latency tape shows **contention spikes** (the racer beside live Python TV on the same box). `core_affinity`: WS-racer core / ladder-decision core / submit core.
- **Config:** `TV_CPU_PIN_ENABLED`, `TV_CPU_PIN_CORES="racer=0,decision=1,submit=2"`.
- **Acceptance:** latency-tape p95 drops after pinning; else leave off.

---

## 3. Staged rollout — mapped to the test-plan gates

| Stage | Creds | Capital | Builds | Clears |
|---|---|---|---|---|
| **0** | none | $0 | I0 | Ladder + watchdog live on box; telemetry flowing; **run T1/T2/T3 offline in parallel** |
| **0.5** | none | $0 | I1 + I3 + I4 (+ I2 if T1 ≥20%) | **L1** flow-capture + pair-fraction with racer vs baseline; **L2** real latency distribution |
| **1** | wallet+API | $0 | I5 (real GTC, NSF-reject) | live plumbing: signing, place/cancel/replace, rejection taxonomy. **Watchdog MUST be up (I0).** |
| **2** | wallet+API | $50–100 inv cap | dense ladder live | **L3** first real maker fill-rate at fresh levels — the decision data |

**Pre-registered promotion gate (Stage-2 → scale capital):**
> ≥~**11.5%** live flow-capture (b945's level; vs ~7% offline floor) **AND** pair-fraction materially > **29%** (toward 44%) **AND** positive net across a thin-flow week **AND** I3 latency healthy. Else file the ladder dead and keep only the V2 oscillation-harvest sleeve.

---

## 4. Guardrails (chain-verified — do NOT re-litigate)
- **MAKER-ONLY** ladder; no taker-completion (0/27,039 below sum 1.0).
- **No split/mint** (zero `splitPosition` on-chain); **post-resolution merge only** (relayer + the ported redeemer; no mid-window merge).
- **Fee = winner-only `0.07·p·(1−p)`**; $0 on maker + redeem; rebates = income. **Never** fee maker/redeem legs.
- **No stops** on the ladder (two-sided self-hedged); **Q≈4 GLT cap + AS γ=0.05** are the profit lever, not speed.
- **Fail-closed:** `TV_*_LIVE_ENABLED=false` ⇒ zero CLOB calls. Token IDs come only from `GammaClient::discover_window` (inv #13). Kill only via the `trading.events` row (inv #7).
- **🔴 Watchdog up before any live flag** (I0). **Skip bad-data windows** (I4).
- **100 ms ladder poll stays** — racer widens the feed, it does not loop faster.

## 5. Open questions for the operator (flag, don't block)
1. Ireland box capacity: racer (N=6) + tick recording + ladder beside live Python TV — pin cores (I6) or budget a second/NVMe box? (Operator already raised NVMe-vs-SSD — the latency tape I3 is what decides if disk I/O on the tick tape is a bottleneck.)
2. Poly WS per-IP connection ceiling (racer N — start 4–8, ramp from the `feed_quality` data).
3. Probe wallet for Stage-1/2 (reuse planned `poly_ab_signer`, or a separate funded wallet for Stage-2).
4. Tick-tape format: file (parquet, like VPS2) vs `trading.tick_tape` table — file preferred for volume.

## 6. Provenance
Insertion points: `TVRUST_LADDER_INSERTION_MAP_2026_06_12.md` + the 2026-06-16 TVRUST survey. Strategy facts: `TV_AGENT_SPEC_RUST_LADDER_B945_2026_06_13.md` + `B945_SESSION_REAUDIT_2026_06_13.md`. Rationale for re-opening the feed race: `SUMPAIR_B945_ERROR_AUDIT_AND_TEST_PLAN_2026_06_16.md` §2.
