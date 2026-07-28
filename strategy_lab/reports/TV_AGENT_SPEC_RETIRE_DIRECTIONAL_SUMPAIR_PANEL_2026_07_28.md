# TV RUST AGENT — retire directional shadow twins + SUM-PAIR dashboard panel + header rewire
**2026-07-28 · TVRUST · vps_ireland. Ladder paper fleet and sumpair_osc are UNTOUCHED — they are the product (ladder paper = session-1 capture benchmark). This retires only the DIRECTIONAL legacy twins and makes sumpair visible.**

## 1. Retire the directional shadow sleeves (ride the NEXT restart — after tonight's same-hours latency capture completes, do NOT pollute it again)
- Retire: `shadow_scalp_exit_btc_5m_d3_v1`, `kalshi_scalp_exit_btc_15m_d3_v1`, `poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_V10`, plus any other scalp/sniper twin still in the roster (the btc-15m sniper pair was killed Jul 21).
- Rationale for the ledger: their purpose was A/B parity vs the Python engine, retired 2026-07-28; V10 cumulative ≈ flat over its life; scalp twins ±$5/week noise at $1 stakes. `retired_parity_purpose_ended`.
- ⚠️ Careful with `TV_LIVE_ONLY_SLEEVE_IDS` semantics — the roster env must end up spawning ONLY ladder fleet + sumpair + the disarmed live sleeve; verify post-restart sleeve list in the boot log and report it (the failure mode to avoid is accidentally spawning the full 120-sleeve shadow roster).
- Their historical events stay in the DB (no deletes); dashboard filters them out as retired.

## 2. SUM-PAIR panel on :8444 (it is invisible today — operator cannot see it at all)
Backend `GET /strat/sumpair` (+ include in `/ws/strat` pushes on new sumpair_osc events):
- Per coin (BTC/ETH): today / 7d / lifetime walk PnL, settles n, $/settle, fires today, both_filled %, partial_frac avg, last fire ts, current window state (armed clips, side, ev_walk of the open fire if any).
- Cumulative walk-PnL daily series per coin (for a small chart).
- Recent tape: last 20 fire/settle events w/ slug, side, ev_walk, outcome, net_pnl_walk.
Frontend: SUM-PAIR section on Overview (two coin cards + cum chart + tape) using the same card/chart components as the ladder pages. Numbers to surface loudly (from operator audit 2026-07-28): BTC lifetime +$1,038 @ +$0.65/settle (real edge, beats its +$0.52 offline benchmark) vs ETH +$114 @ +$0.034/settle (≈noise) — and a 2-day drawdown Jul 27–28 of ≈ −$93 combined coinciding with a fire-rate spike (BTC ~70 fires/day vs 6–12 on the quiet profitable days). A "fires/day vs $/day" mini-view would have shown this instantly; include it.

## 3. Pre-registered ETH-arm verdict (display, don't act)
Add to the panel: ETH arm verdict chip — pre-register NOW: **if ETH lifetime $/settle < $0.10 when n reaches 4,500 settles → retire the ETH arm** (currently n=3,296 @ $0.034). Chip shows n progress + current value vs threshold. No early kill, no tuning; BTC arm has no pending verdict.

## 4. Header strip rewire (follow-up to the "TODAY $5.80" confusion)
Once the twins are retired the current strip would show only stale zeros. Rewire it: primary = LADDER fleet today/week (from ladder_summary net, dedup rules), secondary = SUMPAIR today/week (walk), streak alarm stays but computed over ladder+sumpair. Label each number with its family so a glance can never conflate $1-twins with the fleet again.

## Sequencing
§2–§4 are tv-api + frontend only — ship without any engine restart. §1 rides the next scheduled engine restart together with anything else queued for it (e.g. the in-progress-window cadence you already shipped; nothing else pending engine-side). Same deviation discipline as always.
