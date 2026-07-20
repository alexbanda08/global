# TV RUST AGENT SPEC — FINISH THE GO-LIVE PUNCH LIST (items 2–7)
**2026-07-14 · TVRUST (Rust) ONLY · vps_ireland · no storedata dependency · paper fleet stays untouched.**

## 0. Context / ground rules
- Parent specs still govern: `TV_AGENT_SPEC_GOLIVE_WATCHDOG_EXECUTOR_2026_07_08.md` + `TV_AGENT_SPEC_GOLIVE_ADDENDUM_GAPMAP_2026_07_08.md`. This spec is the **remaining-items order sheet** — nothing here supersedes those, it sequences them.
- Already DONE (verified, do not redo): item 1 WS feed stale-recovery; watchdog service deployed + heartbeat beating; wallet creds loaded (`poly_signer_private_key` + `poly_proxy_address` in `trading.secrets`, Jul 9); v3.1 paper variants deployed Jul 14 13:47 (verified clean).
- **All paper sleeves (v3/v4/v31/sumpair) stay BYTE-FROZEN.** Engine restarts to ship these items are fine; config churn is not.
- Goal state: a **$40 supervised live session** on `poly_ladder_btc_5m_v3` config, operator watching, cap $12/window/side, paper twin running in parallel for capture-ratio measurement.
- Work the items IN THIS ORDER — each is a gate for the next. Report per-item, don't batch-report at the end.

## ITEM 2 — CLOB parse fix + HONEST fire-drill (gate for everything below)
- Fix the CLOB open-orders parse error (`invalid type: map, expected a sequence`) in the watchdog's order-query path. Root-cause it (API shape changed vs struct?), don't just swallow the error.
- Then rerun the kill-drill **honestly**:
  1. Place **1 real resting GTC bid** far from touch (e.g. $1.10 total at price 0.01–0.05 on a btc-updown-5m market) using the loaded creds.
  2. Query open orders → must show **count ≥ 1** (proves the parse fix).
  3. Trigger the watchdog kill path.
  4. Query open orders again → **count = 0**, and the cancel must be **owner-scoped** (watchdog uses the SAME wallet creds as the ladder will).
- ACCEPTANCE: journal + `trading.events` rows showing before-count ≥1, kill fired, after-count =0, with timestamps. The Jul 9 drill (`ok:true` on an empty book with parse errors in the log) is explicitly NOT accepted.

## ITEM 3 — Ladder LIVE branch wiring (the executor)
`ladder_live.rs` exists (mtime Jul 9) but is not wired into the engine. Wire it as a **separate sleeve** `poly_ladder_btc_5m_v3_live`, spawned ONLY when `TV_LADDER_LIVE_ENABLED=true` AND creds present AND watchdog heartbeat fresh (<10s) — fail-closed on all three.
- **Same quoting logic as the frozen paper v3** (depth 2, same rungs/pvs gate/T−45s backstop/rcg OFF). No new strategy code — this is execution plumbing only.
- Emit full order lifecycle to `trading.events`: `order_placed / order_filled (partial-aware) / order_cancelled / order_rejected`, each with venue order-id, price, size, side, token, and the venue ack payload. **PnL/state builds from venue acks ONLY — no synthetic fills, ever.**
- Hard caps (env, all enforced in code before any place call):
  - `TV_LADDER_LIVE_MAX_PER_WINDOW_USD=12` (per side)
  - `TV_LADDER_LIVE_MAX_OPEN_NOTIONAL_USD=40`
  - `TV_LADDER_LIVE_MAX_DAILY_LOSS_USD=15` → hit = flatten + disarm + CRITICAL event
- Reconcile loop every 30s: venue open orders + positions vs local state; any mismatch → log `live_reconcile_mismatch` + prefer venue truth. Include `mergePositions` handling for paired Up+Down inventory.
- Venue hygiene: 429/backoff with jitter, respect min order size, cancel-on-shutdown (SIGTERM handler), idempotent re-place after reconnect.
- clob-sdk feature gate ON in the release build.
- ACCEPTANCE: with `TV_LADDER_LIVE_ENABLED=false` (default) the engine behaves exactly as today (diff of journal startup lines = only the new "live branch present, disarmed" line). Dry-arm test: enable on ONE window with cap $2, verify full lifecycle events land, then disarm. Do NOT leave it armed — the operator flips it during the supervised session.

## ITEM 4 — Engine 5s auto-heartbeat
Engine publishes a heartbeat row/key every 5s (uptime, loop lags, feed ages, armed-state). Watchdog treats heartbeat stale >15s as kill-trigger when armed. ACCEPTANCE: stop the engine → watchdog logs the stale detection within 20s.

## ITEM 5 — LADDER OPS dashboard section (:8444)
Per the plan you already drafted (keep your structure). Minimum panels: (1) armed/disarmed + caps + watchdog heartbeat age, (2) live open orders + positions (venue truth), (3) per-window live vs paper-twin PnL + capture ratio, (4) fill tape (lifecycle events), (5) reconcile status + last mismatch, (6) kill button → watchdog kill path (owner-scoped cancel-all + disarm). Read path must not touch the engine loops (query DB/API only). ACCEPTANCE: screenshot + the kill button drill (can reuse the ITEM 2 drill order).

## ITEM 6 — CPU pinning
Pin per parent spec: racer/feed threads and ladder loops on separate cores from the API/dashboard; document the map in the report. ACCEPTANCE: `taskset`/affinity output in the report + no feed-age regression over 1h (compare `book_age` telemetry before/after).

## ITEM 7 — Scalp-twin silence diagnosis
The rust scalp twin has emitted nothing — diagnose why (feed? gate thresholds? spawn missing?) and report. Diagnosis only unless the fix is one line; do NOT restructure anything while items 2–5 are in flight.

## Reporting
Per item: what changed (files/commits), evidence (journal lines, event rows, counts), and any deviation from this spec flagged BEFORE implementing it. If something is already built that I've marked missing, say so with proof instead of rebuilding.
