# TV RUST AGENT — PRE-LIVE MASTER PLAN: python shutdown → CPU pin → honest drills → session-ready
**2026-07-28 · vps_ireland · Execute phases IN ORDER, evidence per phase. This consolidates the original build plan (B945_ARTICLE_INFRA_GAP_ANALYSIS §8 build order A1–C3) with everything since. Goal: box 100% dedicated to TVRUST, all pre-live gaps closed, session-1 unblocked.**

## Context (why, one paragraph — do not relitigate)
TVRUST exists because the b945 maker edge is offline-unprovable (queue rank unobservable; 5 engines hit the flow-capture ceiling) — only live resting orders measure OUR capture. Article-derived fixes already landed: taker-completion REMOVED (06-16), GLT Q=4 deployed, early-placement dropped by evidence. Paper fleet has 24 green days (v3 +$0.6–0.9/w; c2 t=4.06 capacity proof). Remaining pre-live holes: A3 pinning never done, kill-drill never honest (07-28 07:40 `drill_open_orders {order_ids:[], open_orders:0}` = empty book AGAIN — not acceptance), dry-arm never run, wallet unfunded (operator's job).

## PHASE 0 — Python stack retirement (frees the box)
1. Stop+disable `tv-engine.service` (python), `tv-api.service` (python/uvicorn :8000), `tv-ai-bot.service`. Postgres/redis/caddy STAY. `:8443` Caddy block: leave config, dead upstream is fine (or serve a static "retired" page).
2. Pre-stop snapshot: `systemctl status` of the three + last 20 journal lines + confirm ZERO open venue orders/positions owned by the python stack (wallets unfunded ⇒ expect trivially zero — but LOOK).
3. Archive: `tar` /opt/tradingvenue logs/state ledger note `python_stack_retired_2026_07_28`; do NOT delete /opt/tradingvenue.
4. ACCEPTANCE: three units disabled, `free -h` before/after (~500MB back), rust engine journal clean through the change (no missed windows: `ladder_summary` cadence uninterrupted across the stop timestamp).

## PHASE 1 — A3 CPU pinning (original design, now on a clean box)
1. Coarse (systemd, do first): `tv-rust-engine.service` `CPUAffinity=0 1` · `tv-rust-api.service` `CPUAffinity=2` · `tv-rust-watchdog.service` `CPUAffinity=2`. daemon-reload + restart api/watchdog freely; engine restart in the SAME restart as any Phase-2 code deploy (don't burn two).
2. Fine (in-proc, only if straightforward): `core_affinity` pin of the ladder decision/submit threads to core 1, feeds/racer threads to core 0 via `TV_CPU_PIN_ENABLED/TV_CPU_PIN_CORES`. If thread-model refactor needed — STOP, coarse is enough for session-1, note it.
3. ACCEPTANCE: `taskset -pc` per pid showing masks; `tick_latency` p50/p95/p99/max for 12h BEFORE (baseline = last 12h pre-change) vs 12h AFTER, same-hours comparison. Target: p99/max tail improvement, no p50 regression. Report the table.

## PHASE 2 — Honest drills (BLOCKING for session-1; the 07-09/07-12/07-28 empty-book drills are all REJECTED)
1. **Fire-drill A:** place 1 REAL GTC bid ($1–2 at 0.01–0.05) on a live btc-updown-5m via ladder wallet creds → `drill_open_orders` must log the venue order-id and count ≥1 → watchdog kill → count 0 within 5s, owner-scoped. **Fire-drill B:** fresh resting order → `kill -9` engine → watchdog ALONE cancels + logs. NOTE: placing the resting bid needs ~$2 of USDC on the proxy — if balance is $0, STOP after staging and report "blocked: fund wallet" (operator deposits; do not touch other wallets).
2. **$2 dry-arm:** arm `poly_ladder_btc_5m_v3_live` ONE window, cap $2 → venue-ack lifecycle events (order_placed/cancelled/filled if touched, venue ids, no synthetic) → disarm → reconcile zero.
3. ACCEPTANCE: event-tape excerpts w/ venue order-ids + before/after counts. An empty-book `ok:true` fails review automatically.

## PHASE 3 — System debug sweep (fast, read-only; fix only what blocks live)
Verify + report each: engine heartbeat 5s cadence & watchdog stale-kill armed-mode wiring · reconcile loop 30s + `mergePositions` path compiles into live branch · daily-loss breaker logic unit-tested · SIGTERM cancel-on-shutdown test green · secrets loaded (2/2) & never logged · Caddy :8444 WS upgrade for `/ws/*` (dashboard dependency) · disk (22G free) + Ireland logrotate sanity (python logs stop growing after Phase 0) · `trading.events` indexes for the dashboard queries · leftover kill-candidates confirmed stopped (v32_cheap must be GONE per Jul-25 prereg fail).

## PHASE 4 — Session-1 readiness gate (operator + agent checklist)
All must be TRUE: Phase 0–3 evidence delivered · wallet funded (operator, ~$50–100 USDC on ladder proxy) · dashboard v1 Live+Windows pages usable (parallel spec `TV_AGENT_SPEC_STRAT_DASHBOARD_V1_2026_07_28.md`) · runbook `TV_AGENT_SPEC_GOLIVE_SESSION1_RUNBOOK_C2RCG_2026_07_27.md` §3–§4 staged (caps 12/40/15, disarmed, paper twin untouched). Then operator arms; capture-ratio methodology (sub-cap ≤$24 split) is the session's product.

## Sequencing note
Phase 0 and the dashboard spec can run the same day; Phase 1 coarse pins ride the Phase-2 deploy restart; c2rcg combo paper sleeve (already specced) rides the same deploy. ONE engine restart total for phases 0–3.

## Reporting
Per-phase evidence blocks; deviations flagged BEFORE implementing; commits pushed. Final deliverable: "READY FOR SESSION-1: YES/NO + blockers" one-pager.
