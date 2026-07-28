# TV RUST AGENT — MASTER PLAN v2: arm control-plane (per-strategy START/STOP button) + full pre-live consolidation
**2026-07-29 · TVRUST · vps_ireland. Supersedes/absorbs: PRELIVE_MASTER_PLAN (phases 2–4 open), STRAT_DASHBOARD_V1 (in flight), SESSION1_RUNBOOK (standing). Phase 0 ✅ (python retired, 380MB back) and Phase 1 coarse ✅/⏳ (engine pin lands next restart) are DONE — evidence accepted, incl. the MAX_OPEN_ORDERS=4 ruling (your reasoning accepted; my depth-2→4 objection was wrong).**

## Workstream A — ONE engine restart bundle (do first; everything below rides it)
The next tv-rust-engine restart applies, together:
1. `CPUAffinity=0 1` drop-in (already staged) + `MAX_OPEN_ORDERS=4` (already staged).
2. **NEW: runtime arm control-plane** (the green-button backend — §A2 below).
3. Dead-config cleanup flagged in your ruling-3 answer: delete or comment `n_levels` (parsed-never-read) so the next reader doesn't repeat my mistake.
After restart: start the 12h post-pin `tick_latency` clock (after-table vs your baseline: p50 21.4µs / p95o95 153µs / worst 166.5ms — the tail is the target).

### A2 — Arm control-plane design (fail-closed, DB-driven)
- New table `trading.arm_state (sleeve_id pk, armed bool, caps jsonb, updated_at, updated_by, reason)`. Every flip ALSO writes an audit event `arm_flip {sleeve, armed, by, preconditions_snapshot}`.
- **tv-api:** `POST /strat/arm/{sleeve}` and `POST /strat/disarm/{sleeve}` (session-auth + explicit `confirm: true` body). Arm validates server-side and REFUSES with named reasons unless ALL hold: creds loaded · watchdog heartbeat <10s · wallet balance > $5 pUSD (cached ≤60s on-chain read) · reconcile clean · daily-loss breaker not tripped · caps present. Disarm never refuses.
- **Engine:** live branch polls `arm_state` every ≤5s. disarmed→armed: begin quoting at the NEXT window open (never mid-window). armed→disarmed: immediate owner-scoped cancel-all + T-flatten policy + `arm_flip` ack event.
- **Boot rule (non-negotiable):** on ANY engine start, in-memory state = DISARMED and the engine WRITES `armed=false, reason=boot_reset` to the table regardless of prior value. The button starts sessions; it never survives restarts, crashes, or DB outages (DB unreachable ⇒ treat as disarm).
- **Watchdog:** reads `arm_state`; any sleeve armed + engine heartbeat stale >15s ⇒ existing kill path + write disarm.
- Env-flag arming (`TV_LADDER_LIVE_ENABLED`) becomes a MASTER ENABLE (must be true for the API path to work at all) — belt and suspenders, so the button can never arm a build that wasn't deployed for live.
- ACCEPTANCE: unit tests (boot_reset, precondition refusals, disarm-cancel) + a paper-mode arm/disarm cycle showing the full event trail, before any funded use.

## Workstream B — Dashboard (STRAT_DASHBOARD_V1 spec continues) + the buttons
- Finish the 6-page Mission Control per the existing spec (Overview/Windows/Tape/A/B/Live/Health, WS push, mobile+PWA). Status from your side, please: what's built beyond the LADDER OPS panel + auth fix.
- **Per-strategy START/STOP button** on Overview cards + Live page, wired to §A2: green START → modal (caps, balance, precondition checklist live-evaluated — button disabled with reason chips if any fail) → arm. Red STOP → one confirm → disarm (instant cancel-all). Global KILL stays. Mobile: buttons ≥44px, modal thumb-reachable.
- ACCEPTANCE: phone screenshot of an arm-refusal (unfunded wallet reasons shown) — that exact screen is the operator's pre-funding view, prove it renders.

## Workstream C — funding-gated live path (unchanged, sequence locked)
Operator funds `0xDBe708…45e4` (~$40 pUSD + ~3 POL) → approvals via Settings → you verify allowances on-chain, report, STOP → operator triggers `tv-drill place` → fire-drills A+B evidence (venue ids, count ≥1 → 0) → $2 dry-arm one window → READY one-pager. With §A2 live, the dry-arm and session-1 arming happen via the BUTTON (its first real use, supervised).

## Workstream D — Phase-3 debug sweep (from the pre-live plan, still owed)
Heartbeat/watchdog timing · reconcile+mergePositions in live branch · breaker unit test · SIGTERM cancel test · secrets never logged · Caddy /ws/* upgrade on :8444 · events indexes · disk/log sanity post-python · confirm v32_cheap gone. Plus NEW: `arm_state` table indexes + the A2 test suite. Single report.

## Workstream E — session-1 and after
Session-1 per runbook (warm-up $4 → $12, capture-ratio sub-cap split = the product). Post-session promotion path (pre-registered, not to be improvised): capture ≥50% & 0 incidents ⇒ session-2 longer/higher caps ⇒ c2 sizing promotion (t=4.06) ⇒ rcg/c2rcg per paper verdicts. Parallel research (not yours): delta-stream queue-rank simulator.

## Sequencing
A (restart bundle) immediately; B in parallel (frontend swap needs no engine restart; tv-api restarts freely); D right after A's restart; C whenever funding lands (independent); E gated on C. Report per workstream, deviations flagged before implementing — the c2rcg band catch and the MAX_OPEN_ORDERS pushback are the standard to keep.
