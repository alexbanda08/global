# TV RUST AGENT — PRE-LIVE ORDER SHEET: drills NOW + $40 session-1 staging + c2rcg combo
**2026-07-27 · TVRUST · vps_ireland. ⏰ OPERATOR STARTS THE $40 SUPERVISED LIVE SESSION IN ~1 HOUR (5h, trade-by-trade supervision). Items §1–§2 must be DONE with evidence before then. Do NOT arm anything yourself — operator flips the switch.**

## §1 — Overdue kill (5 min)
`poly_ladder_btc_15m_v32_cheap` failed its pre-registered Jul-25 verdict (full-life n=721, Δ−0.321/w vs base, t=−1.76; last 48h −$131). Stop the sleeve, ledger note `prereg_fail_no_tune`. (Negative result already accepted; bands stay frozen forever.)

## §2 — The two drills (BLOCKING; run now, deliver evidence)
1. **Real-order fire-drill:** place 1 GTC bid ~$1–2 total at price 0.01–0.05 on a live btc-updown-5m market with the ladder wallet → query open orders (count ≥1 in the log) → trigger watchdog kill → open orders count = 0, owner-scoped, <5s. Then repeat variant (b): with a fresh resting order, `kill -9` the engine → watchdog alone cancels it. Event tape (before/after counts + venue order-ids) into `trading.events`.
2. **$2 dry-arm:** arm `poly_ladder_btc_5m_v3_live` for ONE window with `TV_LADDER_LIVE_MAX_PER_WINDOW_USD=2` → verify full lifecycle events land from VENUE ACKS (order_placed/filled/cancelled with venue ids; no synthetic fills) → disarm → reconcile clean (venue open orders 0, positions match).
- ACCEPTANCE: journal + event-tape excerpts. `ok:true` on an empty book is NOT acceptance (Jul-9 rule).

## §3 — Session-1 parameters (stage env, LEAVE DISARMED)
- Sleeve: `poly_ladder_btc_5m_v3_live` (frozen v3 config — no entry changes).
- Caps: `MAX_PER_WINDOW_USD=12`/side · `MAX_OPEN_NOTIONAL_USD=40` · `MAX_DAILY_LOSS_USD=15` (hit ⇒ auto flatten+disarm+CRITICAL).
- Paper twin `poly_ladder_btc_5m_v3` keeps running untouched (capture-ratio benchmark).
- Watchdog live-mode: heartbeat stale >15s ⇒ owner-scoped cancel-all. Verify armed-state gating (flag+creds+fresh heartbeat, fail-closed).
- Dashboard: LADDER OPS panels live-ready (armed strip, venue-truth orders/positions, live-vs-paper per window, fill tape, kill button). Fix anything broken NOW.

## §4 — Session-1 runbook (operator + Claude supervise 5h)
1. **T−10min:** operator checks §2 evidence → arms via env flag + restart. First 2 windows at `MAX_PER_WINDOW_USD=4` (warm-up), then 12 if clean.
2. **Per-window supervision loop (every 5min):** venue-ack fills vs dashboard vs paper twin same window — price/size/side must reconcile exactly; any `live_reconcile_mismatch` event ⇒ pause quotes, investigate before next window.
3. **Abort criteria (any ⇒ kill button, session over):** reconcile mismatch unresolved in 1 window · daily-loss breaker · watchdog/heartbeat incident · >2 consecutive windows with fills but paper twin shows none (toxic-fill signature) · operator judgment.
4. **Capture-ratio measurement (the session's actual product):** per window log `live_filled_usd / paper_filled_usd` and `live_net / paper_net` — **computed separately for windows where paper filled ≤$24 (sub-cap, honest comparison) vs >$24 (cap-clipped by design)**. 5h ≈ 60 windows ≈ ~45 sub-cap comparisons.
5. **T+5h:** disarm, cancel-all, reconcile, then report: fills tape, PnL (venue truth), capture ratios (sub-cap/all), rebate line if visible, incidents. Success gate for session 2 (longer, higher caps): zero safety incidents AND sub-cap fill-capture ≥50%.

## §5 — New paper sleeve `poly_ladder_btc_5m_v31_c2rcg` (pre-registered combo)
c2 (2× clip, +0.321/w t=4.06) + rcg (residual flatten 0.30–0.45, +0.133/w t=2.84) in ONE sleeve, shared base feed, everything else byte-v3. Hypothesis (frozen): additive, Δ≥+0.35/w vs base, judged paired t≥2 at n≥2,000 (~7d). Telemetry: both variants' fields. If sub-additive (Δ<c2 alone) that's the finding — no tuning.

## §6 — Reporting
§1+§2 evidence immediately (operator reads it pre-arm). §4 report at session end. §5 first-24h snapshot. Never print secrets; venue acks only; paper fleet stays frozen.
