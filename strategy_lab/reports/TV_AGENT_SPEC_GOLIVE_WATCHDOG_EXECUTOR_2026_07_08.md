# TV RUST AGENT SPEC — the path to LIVE: watchdog + live maker executor + core pinning + feed hardening
**2026-07-08 · TVRUST (Rust) ONLY · Ireland · Python frozen · storedata untouched.**

## ENVIRONMENT (read first — no ambiguity)
- **Target box: `vps_ireland` (85.137.174.152), the TVRUST Rust platform only.** All services, units, and code changes land there.
- **DB: Ireland's local `tradingvenue_rust` postgres** — the watchdog consumes/writes `trading.events` there; all telemetry stays there.
- **⚠️ There is NO storedata collector on Ireland.** The storedata collector runs on VPS3 and is research-only — it plays NO role in live execution. All market data for live decisions comes from the engine's OWN WS racer + direct CLOB REST calls (the existing Tier-2 fallback is already REST, not a DB). Do not add any dependency on VPS3 or on any storedata table for the live path. (Ireland's small local `storedata` DB belongs to the frozen Python engine — do not touch it.)
- **Wallet/secrets: the Rust engine's own Fernet secrets registry in `tradingvenue_rust`** — a fresh dedicated wallet, never the Python engine's.
Basis: `IRELAND_V3V4_TRUST_AUDIT_GOLIVE_2026_07_08.md` — **`poly_ladder_btc_5m_v3` passed the paper gate** (+$1.03/win CI[+0.74,+1.38], ex-top2 +$0.87 CI>0, +$212/day, 7/7 days positive, accounting verified per-transaction). Blockers are operational: no kill-path, no live order path, feed edge-cases. This spec is that work, in **3 phases with operator flips between them. NOTHING goes live until Phase C and the operator explicitly funds + flips.**

> **Companion gap map is CODE-VERIFIED (2026-07-08).** Every "already built" claim below is confirmed against current box reality (not the counterpart's `887669a` snapshot) in `TV_AGENT_SPEC_GOLIVE_ADDENDUM_GAPMAP_2026_07_08.md`, with file:line. The box is scp-deployed (no git) and already carries `loops/feed_watchdog.rs` (L1 staleness watchdog), ladder v3, and v4_coc — **EXTEND those, don't rebuild.** Reuse targets confirmed present: `tv-venues poly_clob.rs:105 PolyClobClient`, the sniper arming shape (`sniper.rs:1011 LiveSubmitCfg` + `live_submit.rs ClobLiveSubmit`), `poly_clob.rs:48 LiveGate`.

---

## PHASE A — safety + infra (no live capability yet)

### A1. `tv-watchdog` — the independent kill-path (hard prerequisite, house rule)
A **separate binary + systemd service** (`tv-watchdog.service`), NOT a task inside the engine — it must survive an engine hang/crash:
- **Own credentials (owner-scoped — wire carefully)**: its **own copy** of the ladder wallet's CLOB API creds (independent cred file/process, inv#8-style isolation) so it can **cancel-all directly at the venue even if the engine process is dead**; own read-only DB pool + write access for its own events. ⚠️ Polymarket CLOB cancel is **owner-scoped** — only the key that placed an order can cancel it — so this is **necessarily the SAME on-chain wallet the ladder trades on**, NOT a second wallet and NOT the Python engine's wallet. (This differs from the existing HL watchdog closer, which legitimately uses a DISTINCT wallet because it places independent reduce_only exits, not owner-scoped cancels.) Extend the existing generic `close.rs:85 VenueCloser` seam with a `PolyClobCloser` (cancel-all → FAK-flatten residual) on `PolyClobClient`; add `cancel_all`/`get_open_orders` to the wrapper (only single `cancel_order(id)` exists today).
- Triggers (any ⇒ cancel ALL open orders at the venue + set a kill-latch the engine must respect on restart + `kill_executed` event + log alert):
  1. `trading.events(kind='kill_switch_requested')` row (manual kill: one SQL insert from anywhere).
  2. **Engine heartbeat stale** — engine writes a heartbeat every 5s (event or file); stale >30s WHILE open live orders exist ⇒ kill.
  3. **Daily realized loss ≤ −`WD_DAILY_LOSS_LIMIT_USD`** (default 50) from live fill events.
  4. **Exposure cap**: open live inventory > `WD_MAX_EXPOSURE_USD` (default 200).
  5. **Runaway guard**: >`WD_MAX_ORDERS_PER_MIN` (default 60) order placements.
- Poll cadence ≤2s. The kill-latch (a DB row/flag) blocks any live loop from arming until an operator clears it.
- **Acceptance = two fire-drills** (Phase B, with 1 tiny real order): (i) manual kill row ⇒ all orders cancelled <5s; (ii) `kill -9` the engine with a resting order ⇒ watchdog cancels it alone.

### A2. Per-core pinning (the moat-infra item)
- Inventory the box's vCPUs first; then pin: WS racer ingest threads → dedicated core; book-apply + quote-decision hot loop → dedicated core; DB/telemetry/tokio-blocking → remaining cores; leave core 0 to the OS. Use thread affinity in-process (e.g. `core_affinity`) + systemd `CPUAffinity=` on the unit so nothing else schedules onto the hot cores.
- Goal is the TAIL, not the median (p50 is already 37–62µs): kill the 145–228ms max outliers. **Deliver a before/after from the existing `tick_latency` tape (p50/p95/p99/max over ≥12h each).**

### A3. Feed hardening — no missed/stale data feeding live decisions
The live maker's #1 risk is quoting on a stale book. **Note — `loops/feed_watchdog.rs` already exists on the box** (L1: detects book-age staleness → force reconnect + REST `/book` reseed + escalation alert; keys on `BookState::age_ms`, never conn state). Its live "flatten-and-halt hook" is an explicit TODO pending a live path. **EXTEND it**, don't rebuild. Known issues to close:
1. **Endgame reject gate**: the >15¢ delta outlier gate rejects legit end-of-window moves (book_age rises 0.9→2.7s in the final deciles; 42.6k rejects). Make it **time-aware**: widen or disable in the final 2 minutes (5m: final 60s). If already done in a prior turn, show evidence.
2. **Gap detection + resync**: per market, detect delta discontinuity (sequence/hash mismatch or apply failure) ⇒ immediate REST snapshot resync; **fail-closed: pause quoting on that market until the book is verified fresh again.**
3. **Stale-book guard (live-critical):** if `book_age > TV_LIVE_STALE_PAUSE_MS` (default 2000) on a live market ⇒ pause new quotes; `> TV_LIVE_STALE_CANCEL_MS` (default 5000) ⇒ **cancel resting live orders on that market** (a stale maker gets picked off). Re-arm automatically when fresh. Log `stale_pause`/`stale_cancel` events.
4. **Startup warmup gate**: no live quote before the racer warmup passes + one clean REST snapshot cross-check per market.

---

## PHASE B — live maker executor (built + dry-run, still not armed)

### B1. Order lifecycle for the ladder (btc-5m v3 semantics, live)
- **Place**: GTC bids at the deep-quote levels (best_bid − 2 ticks, both sides), exactly the paper sleeve's decisions. Respect venue minimums (~5 shares / ~$1 — VERIFY live and encode), tick 0.01 (0.001 near extremes), collateral = shares×price.
- **Requote**: when the paper logic moves a rung ⇒ cancel+replace. **Rate-limit** (`TV_LADDER_LIVE_MAX_REQUOTES_PER_MIN`, default 30/market) and handle 429/425 with backoff+jitter.
- **Fill truth — fail-closed like the Python sniper**: book fills ONLY from venue acks / user-fill WS. Pre-subscribe the user channel per market before placing. NO synthetic booking, ever. Plus a **REST reconciliation loop** (every 15s: open orders + positions vs internal state; any unknown fill/order ⇒ reconcile + `reconcile_mismatch` event + pause that market).
- **Backstop**: T−45s residual flatten = real marketable-limit SELL (partial-tolerant); log actual proceeds.
- **Settlement**: winners/pairs redeemed post-resolution (mergePositions for pairs if cheaper, else redeem both legs — b945 pattern); a redeemer loop with retries; `redeemed` events with tx refs.
- **Caps enforced in-engine** (watchdog is the backstop, not the first line): `TV_LADDER_LIVE_MAX_PER_WINDOW_USD=50`/side, `TV_LADDER_LIVE_MAX_TOTAL_USD=200`, `TV_LADDER_LIVE_DAILY_LOSS_LIMIT_USD=50` (engine self-halts before the watchdog would).
- **Scope lock**: live-armed market list = `TV_LADDER_LIVE_MARKETS=btc-5m` ONLY. 15m/eth/v4_coc/sumpair/scalp all stay paper.

### B2. Wallet
- **Fresh dedicated wallet for TVRUST** — do NOT reuse the Python engine's drained wallet. Creds via the existing secrets mechanism (never plaintext in env/logs/events). One-time USDC allowance approvals scripted. Operator funds ~$400 when flipping Phase C.

### B3. Telemetry (the Python lesson: rejections were invisible)
Every order action = a `trading.events` row: `order_placed/order_filled/order_cancelled/order_rejected/order_reconciled` with venue ids, prices, sizes, and **rejection reasons** (esp. balance/allowance). Live `ladder_summary` same schema as paper + `mode:'live'` + `live_fill_capture` fields. **The paper twin keeps running in parallel on the same market** — per-window comparison (paper fills vs live fills) is the capture-ratio gate.

### B4. Dry-run acceptance (operator funds ~$20 for this)
On ONE btc-5m window with per-window cap $5: place → requote → (fill or not) → backstop flatten → settle/redeem → all events present, PnL identity exact vs venue statement, reconciliation clean. Then the two watchdog fire-drills (A1). Show the tape.

---

## PHASE C — armed (operator flip only)
Set live on btc-5m at caps ($50/window/side, $200 total, $50/day loss). **Pre-registered gates (already agreed):** run ≥2wk; judge ONLY on (a) live wallet net CI>0, (b) capture ratio = live fills / paper-twin fills ≥ ~50%; kill if capture <25% at n≥300 windows or the loss limit trips twice. Also verify the real maker rebate rate vs the assumed 0.0015 and correct the telemetry constant.

## Do NOT
❌ Arm anything before A+B acceptance + operator flip. ❌ Synthetic fills on the live path. ❌ Reuse the Python wallet. ❌ Live-arm 15m/eth/v4_coc/sumpair/scalp. ❌ Touch Python Tradingvenue or storedata. ❌ Print secrets in logs/events.

## Provenance
Gate results: `IRELAND_V3V4_TRUST_AUDIT_GOLIVE_2026_07_08.md`. Deep-quote/backstop semantics: `TV_AGENT_SPEC_LADDER_V3_DEEPQUOTES_5M_2026_07_02.md`. Fail-closed fill pattern: Python `_place_live_order` (audit `SCALP_LIVE_READINESS_AUDIT_2026_07_02.md` — and its wallet-invisibility failure is why B3 exists). Fee/redeem rules: winner-only 0.07 curve, $0 maker/redeem; maker rebate = income (verify rate live).
