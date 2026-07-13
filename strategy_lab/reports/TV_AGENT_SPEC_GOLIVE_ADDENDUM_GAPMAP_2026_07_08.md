# GO-LIVE SPEC ADDENDUM — what's ALREADY BUILT vs missing (code-VERIFIED 2026-07-08)

**Companion to `TV_AGENT_SPEC_GOLIVE_WATCHDOG_EXECUTOR_2026_07_08.md`.**

> **Provenance / verification status.** The research counterpart's first cut was mapped
> against local HEAD `887669a` (2026-07-02) and flagged as a *lower bound* — their clone
> lags the box. The TV agent has now **re-verified every row against current reality on
> 2026-07-08**. The Ireland box is **scp-deployed (NO git repo)** and carries code beyond
> `887669a`: `loops/feed_watchdog.rs`, ladder v3 (deep quotes + T-tail backstop), and the
> v4_coc shadow. Rows below are tagged `✅VERIFIED` (TV agent confirmed file:line on
> 2026-07-08) or `⬆SHIPPED` (present on box, resolved this pass). **Rule: EXTEND what
> exists, do not rebuild.**

---

## 0. Shipped since `887669a` — do NOT re-plan (resolved this pass)

| Thing | Evidence | Bearing on the plan |
|---|---|---|
| Ladder v3 deep quotes + T-tail backstop | `loops/poly_ladder.rs` (`quote_depth_ticks`, `backstop_tail_s`, `backstop_min_residual_sh`; deep-quote requote ~L790; backstop trigger ~L743) | This IS the go-live strategy. `poly_ladder_btc_5m_v3` = the target. |
| btc-5m mirror | `main.rs spawn_ladder_instance` → `base.variant("5m",…)` | `poly_ladder_btc_5m_v3` runs on box now (paper). |
| v4_coc shadow | env `TV_LADDER_COC_*`; sleeve `poly_ladder_btc_15m_v4_coc` | Parallel experiment; NOT a go-live target. Leave paper. |
| **`feed_watchdog` (the row the counterpart couldn't see)** | `loops/feed_watchdog.rs` — **L1 book-staleness watchdog.** Keys on **book age** (`BookState::age_ms`), NOT conn state; on stale > `TV_POLY_BOOK_STALE_RECONNECT_S`(30) ⇒ force reconnect + REST `/book` reseed + `feed_watchdog` telemetry; `TV_POLY_BOOK_STALE_MAX_RECOVERIES`(5) ⇒ CRITICAL alert. | **Covers part of A3.** Its docstring states the live "flatten-and-halt hook" is a **TODO pending a live path**. → A3 becomes *EXTEND feed_watchdog*, not build-from-zero. |

---

## A1 — watchdog: ~60% built, but the kill end is HYPERLIQUID-only

| item | state | evidence (✅VERIFIED 2026-07-08) |
|---|---|---|
| `tv-watchdog` binary + crate | ✅ BUILT | `crates/tv-watchdog/` (own bin) — `main.rs`, `close.rs`, `live.rs`, `health.rs`, `keepalive.rs`, `kill_consumer.rs`, `webhook.rs`, `config.rs` |
| Layer-1 `kill_switch_requested` consumer | ✅ | `kill_consumer.rs`; wired `main.rs:207-232` |
| Layer-2 direct webhook | ✅ | `webhook.rs`; wired `main.rs:145-174` |
| Layer-3 dead-man keepalive freeze | ✅ (clean freeze, no liquidation) | `keepalive.rs`; wired `main.rs:237-251` |
| own creds, fail-closed | ✅ but **HL creds only** | `main.rs:54-106` (`HL_WATCHDOG_*` + own Fernet); disabled-closer ⇒ logged no-op |
| **close-all = HL reduce_only exits — NO Polymarket CLOB cancel-all** | 🔴 GAP | `close.rs:85 VenueCloser` trait is generic, but the ONLY impl is `live.rs:89 HlWatchdogCloser`/`:126 LiveHlCloser`. `close.rs:127 close_all_via_watchdog` only flattens positions — nothing cancels resting CLOB orders. |
| health probe | 🟡 STUBBED fail-OPEN | `main.rs:182-190` returns `true`; the REAL probe exists but is UNUSED at `live.rs:350 probe_tv_api` |
| engine auto-heartbeat (5s) | 🔴 MISSING | only tv-api `/keepalive` writes liveness; engine emits none. Watchdog reads `live.rs:310 fetch_keepalive` (`MAX(expires_at)`) |
| kill-latch blocking re-arm | 🔴 MISSING | `health.rs:24 HealthState.fired` is IN-MEMORY only; no persisted latch anywhere |
| rails → `kill_switch_requested` bridge | 🔴 MISSING | rails emit `rails.rs:304`+`:545 RailAction::RequestKill`; the ONLY writer of the event is tv-api `handlers/controls.rs:327`. Engine never bridges `RailDecision.request_kill`. Gap documented at `tv-rails/tests.rs:715`. |
| watchdog-side loss / exposure / order-rate checks | 🔴 MISSING | watchdog only reacts to kill-event / health / keepalive |
| engine self-halt rails (separate from watchdog) | ✅ rich | `tv-rails/src/rails.rs` DD ladder + 24h $-loss + concentration + stale-tick close-all |
| systemd unit / deploy | 🔴 MISSING | box has ONLY `tv-rust-api.service` + `tv-rust-engine.service` — no watchdog unit |
| fire-drills | 🔴 pending | run in Phase B with 1 tiny real order |

**A1 rescope (EXTEND):** add a **Polymarket `PolyClobCloser`** impl of `VenueCloser` — cancel-all resting orders THEN FAK-flatten residual — on `PolyClobClient`; wire `probe_tv_api`; add 5s engine heartbeat; persisted kill-latch; rails→event bridge; watchdog loss/exposure/order-rate polls; `tv-rust-watchdog.service`; two drills.

> **⚠️ Creds correctness (do not mis-wire).** Polymarket CLOB cancel is **owner-scoped** —
> you can only cancel orders your own API key placed. So the watchdog's Poly closer needs
> its **own copy of the LADDER wallet's CLOB API creds** (independent cred file / process,
> inv#8-style isolation), but **necessarily the SAME on-chain wallet** the ladder trades on
> — NOT a second wallet (a different wallet cannot cancel the ladder's orders), and NOT the
> Python engine's wallet. This differs from the HL watchdog, which legitimately uses a
> DISTINCT wallet (it places independent reduce_only exits, not owner-scoped cancels).

---

## B — executor: CLOB client done (for the sniper); the ladder has ZERO live branch

| item | state | evidence |
|---|---|---|
| CLOB client: EIP-712 sign, `post_order` GTC/FOK/FAK/GTD, cancel_order, get_order_book, get_balance_allowance, get_trades | ✅ BUILT (✅VERIFIED) | `tv-venues/src/clients/poly_clob.rs:105` (`post_order` :164, `cancel_order` :232, `get_order_book` :205, `get_balance_allowance` :241, `derive_api_key` :150) |
| feature-gated OFF by default | ⚠️ | `clob-sdk` (`tv-venues/Cargo.toml`) — **must be ON in the live build** |
| per-market fail-closed live gate | ✅ | `poly_clob.rs:48 check_live(gate, market_key)` |
| live arming pattern (fail-closed → paper) | ✅ for sniper-v5 + Kalshi | `sniper.rs:924 LiveSubmit` seam + `sniper.rs:1011 LiveSubmitCfg{enabled,allowlist_csv,notional_usd,max_notional}`; real hook `live_submit.rs ClobLiveSubmit` (`clob-sdk`); alerts `live_submit.rs AlertSender` (Pushover+Discord) |
| **ladder live branch** | 🔴 MISSING | `poly_ladder.rs` has NO `LIVE_ENABLED` read / NO `PolyClobClient` / NO `live_submit`. Env `TV_POLY_LADDER_LIVE_ENABLED=false` exists but **nothing reads it**. |
| `cancel_all` / `get_open_orders` on the wrapper | 🔴 MISSING | wrapper exposes single `cancel_order(id)` only (`poly_clob.rs:232`); add both (SDK supports — verify at build). Needed by BOTH A1 cancel-all and B reconcile. |
| user-fill WS (push acks) | 🔴 MISSING | fills via REST `get_trades` poll only |
| open-orders/positions reconcile loop (15s) | 🔴 MISSING | (the sniper 3-tier is *book acquisition*, not order reconcile) |
| `mergePositions` | 🔴 MISSING (redeem exists) | `crates/tv-engine/src/redeemer.rs` = redeem only; on-chain merge for matched pairs is absent |
| 429 / backoff / rate-limit | 🔴 MISSING | no retry/backoff in `poly_clob.rs post_order` |
| Poly min-order-size validation | 🔴 MISSING | tick rounding ✅ (`tv-executors` rounding/`clients/polymarket.rs`); min-size ($1 confirmed) absent |
| secrets registry (Fernet, redacting Debug) | ✅ | fresh dedicated TVRUST wallet via this; approvals scripted `clients/approvals.rs` |
| ladder caps | 🔴 MISSING | need per-window/side + total + daily, engine self-halts FIRST |
| paper twin parallel | ✅ | v3 paper sleeves run now → capture-ratio gate (Phase C) |

**B rescope (BUILD, reusing built pieces):** ladder live branch reusing `PolyClobClient` + the sniper `LiveSubmit`/`LiveGate` arming shape (default OFF, allowlist by sleeve_id); add `cancel_all`+`get_open_orders` to the wrapper; fill-truth (stage-1 tight `get_trades` poll — justify — or user-fill WS); 15s reconcile; `mergePositions`; 429/backoff; min-size; ladder caps; every order-action ⇒ `trading.events` incl. rejection reason. Ship with `clob-sdk` ON. **No synthetic fills on the live path.**

---

## A2 / A3 — pinning + feed hardening

| item | state | evidence / action |
|---|---|---|
| stale-book pause (ladder side-pause at stale>5s) | ✅ BUILT | `poly_ladder.rs` (+ test) |
| **book-staleness watchdog + auto-recovery** | ⬆SHIPPED (box) | `loops/feed_watchdog.rs` — reconnect + REST reseed + escalation. **EXTEND**: fire its live flatten-and-halt hook once B exists. |
| **cancel-resting-orders on stale (live)** | 🔴 MISSING | pause only; live must CANCEL. Depends on B live-order handles. |
| warmup gate | ✅ rich | `poly_ladder.rs` warmup + `data_quality.rs` |
| reject gate 0.15 | 🟡 static + streak-relent(3); **NOT time-aware** | `poly_ladder.rs apply_prints` `(tp-m).abs()>0.15` (~L800); relent in `poly_book.rs` (`reject_relented`, `RELENT_AFTER=3`). `t_frac` available `poly_ladder.rs:844`. **EXTEND** to widen/disable in final 60s (5m) / 2min (15m). |
| poly gap detection / resync | 🔴 MISSING for poly (kalshi HAS it) | port `tv-feeds/src/kalshi.rs:219-250 ApplyResult::SeqGap` (seq≠last+1 ⇒ resubscribe) to the poly racer (`poly_book.rs`) ⇒ REST resync + fail-closed pause |
| CPU pinning (I6) | 🔴 MISSING — planned only | zero `core_affinity`/`CPU_PIN` in `crates/`. Implement `TV_CPU_PIN_ENABLED` + `TV_CPU_PIN_CORES="racer=0,decision=1,submit=2"` (`core_affinity` + systemd `CPUAffinity=`). |
| latency tape | 🟡 book-age only | `poly_ladder.rs:1102 emit_tick_latency` (gated `TV_LATENCY_TAPE_ENABLED`). **EXTEND** with decision→submit→ack once live. Use it for the pinning before/after (p50/p95/p99/max ≥12h each). |

---

## C — operator flip (unchanged)

Not a build. Arm `poly_ladder_btc_5m_v3` ONLY, at caps, when: A+B acceptance signed + fire-drills + kill-latch verified · ≥2wk live · live net CI>0 (n≥300) · capture ≥~50% of paper twin · auto-kill at capture<25% (n≥300) or loss-limit trips twice · **verify real maker rebate vs the assumed `0.0015`** (`poly_ladder.rs from_env TV_POLY_LADDER_REBATE_PER_SH`) and correct the telemetry constant.

---

## Net effect on the 3 phases (verified)

- **Phase A** — watchdog machinery is ~60% there; biggest new piece = **Poly CLOB cancel-all** (`VenueCloser` impl + wrapper `cancel_all`) with owner-scoped creds. Also: wire the (already-written) health probe, 5s heartbeat, persisted latch, rails→event bridge, watchdog risk polls, systemd unit + drills. Pinning = implement planned I6. Feed = **EXTEND `feed_watchdog`** + port kalshi seq-gap + time-aware reject gate + live stale-cancel.
- **Phase B** — CLOB client + arming pattern + secrets DONE; the work is the **ladder live branch** + wrapper `cancel_all`/`get_open_orders` + fill-truth + 15s reconcile + merge + backoff + min-size + caps.
- **Phase C** — unchanged.
