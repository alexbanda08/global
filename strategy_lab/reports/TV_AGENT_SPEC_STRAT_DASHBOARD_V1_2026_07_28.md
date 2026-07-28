# TV RUST AGENT SPEC — "MISSION CONTROL" strategy dashboard v1 (:8444, PC + phone)
**2026-07-28 · TVRUST only · vps_ireland · ENHANCE the existing :8444 stack (Caddy TLS → tv-api :8090 → Next.js frontend-out). NOT a new stack. Operator wants: every window, every trade, live, complete — desktop and phone.**

## 0. Hard rules
- **tv-engine is NEVER touched by this work.** Only tv-api rebuild/restart + frontend built LOCAL → atomic swap of `/opt/tvrust/frontend-out`. (Established deploy-safety pattern.)
- All new endpoints are **read-only SQL over `tradingvenue_rust`** (except the existing authenticated `/kill`). No writes, no engine coupling. Reuse existing session auth on everything.
- :8443 (Python legacy dashboard) untouched.
- Work in the step order below; each step has an acceptance check — deliver evidence per step, don't batch.

## STEP 1 — Backend: data endpoints (tv-api)
Add under `/strat/*` (auth-gated, JSON):
1. `GET /strat/overview` — per sleeve (live+paper, incl. killed w/ flag): today net, 7d daily nets (sparkline array), $/window lifetime + 48h, windows today, last-window {slug, net, outcome, ts}, status (paper/live-armed/killed), caps. Plus fleet totals and a health block (engine heartbeat age s, NRestarts, watchdog age, feed book_age p50/p95, disk free GB, DB size).
2. `GET /strat/windows?sleeve=&tf=&from=&to=&limit=&cursor=` — paginated window history from `ladder_summary` (+ scalp/sniper `resolve` normalized into the same shape): slug, sleeve, ts, outcome, net, filled_up/dn sh+vwap, pair_frac, pvs, capital_used, maker_pct, rebate, skipped_reason, flags (rcg_flattened, backstop, coc). Server-side aggregates for the filtered set: sum net, avg $/w, WR.
3. `GET /strat/window/{sleeve}/{slug}` — window DETAIL: every event for that sleeve+slug from `trading.events` (fills, quotes/requotes if logged, rcg/backstop/settle) ordered, + the same window across ALL sleeves (twin compare table, incl. live-vs-paper when live).
4. `GET /strat/tape?kinds=&sleeve=&limit=` — flat recent-events tape (order_placed/filled/cancelled/rejected, fire, scalp_exit, resolve, ladder_rcg_flatten, sumpair_osc fire/settle, kill/reconcile/heartbeat-stale incidents).
5. `GET /strat/ab` — paired variant-vs-base stats computed server-side per family (btc5m: c2/rcg/c2rcg vs v3; 15m survivors vs v3): n, meanΔ/w, t-stat, cum-Δ daily series, pre-reg verdict badge (pass/fail/pending + threshold). Use the SAME dedup/paired logic we use in research (join on slug, settled windows only).
6. `GET /strat/live` — session panel: armed bool, caps env, venue-truth open orders + positions (from reconcile cache), daily loss vs breaker, capture ratio so far (live_filled/paper_filled + live_net/paper_net, split sub-cap ≤$24 vs capped), incidents list.
- Perf gate: every endpoint <300ms. Add missing indexes on `trading.events (kind, at)` and `(sleeve_id, at)`; verify with EXPLAIN. The 7.5s dedup query fix from the crashloop incident must not regress.
- ACCEPTANCE: curl each endpoint (authed) with timing + one JSON sample each.

## STEP 2 — Backend: live push
`WS /ws/strat` (reuse ws.rs infra): on connect send snapshot {overview, active windows}; then push deltas: any NEW trading.events row of interest (tail by event_id/at, 1s DB poll loop — no engine hooks), heartbeat age every 5s, and window-close summaries as they settle. Message envelope `{ch: "tape"|"window"|"health"|"live", data}`. Fallback: frontend polls each panel every 5s if WS drops (must be visible: "LIVE ● / polling ○" indicator).
ACCEPTANCE: `websocat` session showing snapshot + a real window settle arriving <2s after the DB row.

## STEP 3 — Frontend: pages (Next.js, same app/auth/brand)
Nav (desktop sidebar / **mobile bottom-tab bar**): Overview · Windows · Tape · A/B Lab · Live · Health.
1. **Overview** — fleet cards (sleeve, today $, 7d sparkline, $/w, last window w/ green/red pulse), fleet equity curve (cum net, per-family toggle), health strip (heartbeat/feed/disk badges — green/amber/red), live-armed banner when armed.
2. **Windows** (the core page) — top: ACTIVE windows board: per market (btc-5m, btc-15m, eth-5m) a live card: countdown to window close, per-sleeve fills so far (up/dn sh + vwaps + paired), provisional exposure; updates via WS. Below: history table (virtualized, filters sleeve/tf/outcome/date, badges for rcg/backstop/skip), row click → **window detail drawer**: fill tape, twin-compare table, mini price/fill timeline chart.
3. **Tape** — live scrolling fill/event tape (WS), color-coded per sleeve/kind, filterable, pause-on-hover.
4. **A/B Lab** — per variant: cum-Δ vs base chart, t-stat gauge vs pre-reg threshold, verdict badge, n counter. This page replaces me hand-running the paired SQL.
5. **Live** — session panel per §STEP1.6 + the EXISTING `/kill` button (red, confirm modal, authed). Arm/disarm stays env+restart (display-only here).
6. **Health** — feeds age per market chart, tick-latency percentiles, reconcile status, uptime/restarts, disk/mem, incident log.
- Charts: lightweight (recharts or uPlot). Dark theme to match existing brand. Timestamps UTC with relative badge.
ACCEPTANCE: screenshots (desktop 1440px + mobile 390px) of all 6 pages with REAL data.

## STEP 4 — Mobile + PWA
Responsive breakpoints (cards stack, tables → card-list on <640px, bottom tabs, touch targets ≥44px). PWA manifest + icons + service-worker shell-cache so it installs to home screen; note: self-signed cert limits SW on some browsers — manifest+responsive is the bar, SW best-effort. Test path: `https://85.137.174.152:8444` on phone (operator accepts the cert once).
ACCEPTANCE: phone screenshots (Overview + Windows + Live), Lighthouse mobile score reported.

## STEP 5 — Deploy + hardening
Build local → swap frontend-out atomically → restart tv-api only. Verify: engine PID unchanged before/after, all 6 pages live on :8444, WS through Caddy works (add explicit `/ws/*` upgrade handling to the :8444 block if needed), auth blocks anonymous on every /strat/* and /ws/strat. Session-1 supervision must be fully doable from the Live+Windows pages alone.
ACCEPTANCE: engine PID proof, authed/unauthed curl matrix, final URL + login flow confirmation.

## STEP 6 — Report
Per-step evidence, endpoint list w/ timings, screenshot set, known gaps, and a 5-line "operator quickstart" (URL, login, what each page answers). Flag any deviation BEFORE implementing. Commit/push as you go.

## Out of scope (do NOT build)
New auth systems, domains/Let's Encrypt (candidate for a later slice), historical backfill beyond `tradingvenue_rust`, python-:8443 integration, any engine-side telemetry changes.
