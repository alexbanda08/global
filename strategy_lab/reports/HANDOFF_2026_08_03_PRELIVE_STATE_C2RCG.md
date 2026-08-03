# HANDOFF 2026-08-03 — pre-live state: c2rcg SUPER-ADDITIVE (t=7.87), twin parity locked, session-1 waiting only on funding
**Read with: TV_AGENT_SPEC_MASTER_PLAN_V2_ARMCTL_2026_07_29.md (control plane), TV_AGENT_SPEC_SLEEVE_BY_SLEEVE_READY_2026_07_29.md (ready state), READY_STATE_2026_07_30.md (TVRUST docs, agent side).**

## A. Performance — last 5 days (Jul 30 → Aug 3 partial, paper $)

| Sleeve | Windows | Net 5d | $/window |
|---|---|---|---|
| **btc_5m_v31_c2rcg** | 1,272 | **+$1,745.5** | **1.372** |
| btc_5m_v31_c2 | 1,273 | +$1,327.0 | 1.042 |
| btc_5m_v31_rcg | 1,269 | +$1,159.9 | 0.914 |
| btc_5m_v31_d1 | 1,270 | +$1,021.0 | 0.804 |
| btc_5m_v3 (base, GO-LIVE) | 1,271 | +$871.3 | 0.685 |
| btc_5m_v3_live (twin, paper) | 1,269 | +$846.3 | 0.667 |
| eth_5m_v3 | 1,322 | +$159.7 | 0.121 |
| btc_15m_v3 | 439 | +$123.3 | 0.281 |
| sumpair BTC / ETH (walk) | 164 / 403 settles | +$72.7 / +$41.1 | 0.44 / 0.10 per settle |

Zero negative days for any BTC-5m arm across the whole week (8/8 days green, all arms).

## B. Paired verdicts (full life since 2026-07-16, vs frozen v3 base, same-slug join)

| Arm | n | Δ/w | t | Verdict |
|---|---|---|---|---|
| **c2rcg** | **1,842** | **+0.649** | **7.87** | 🔥 SUPER-ADDITIVE (c2 0.327 + rcg 0.154 = 0.481 expected; combo delivers 0.649). Pre-reg n=2,000 reached ~Aug 4 — barring collapse, PASSES with the strongest t in program history. |
| c2 | 5,137 | +0.327 | 5.35 | ✅ confirmed (2× clip capacity proof) |
| rcg | 5,138 | +0.154 | 4.15 | ✅ confirmed (residual flatten) |
| d1 | 5,133 | +0.148 | 2.83 | recovered; watch-only |
| **v3_live twin** | 1,693 | −0.012 | −0.23 | ⭐ PARITY: live code path ≡ base. Pre-live validation complete. |
| d4 | 1,100 | −0.242 | −2.36 | dead (killed Jul 21) |

Sumpair lifetime: BTC +$1,090.9/1,875 settles (+$0.58/settle, CONFIRMED edge, drawdown of Jul 27-28 recovered) · ETH +$201/3,907 (+$0.05, verdict chip pending n=4,500 → currently projects RETIRE).

## C. Live path — state as of Aug 3 ~14:00Z
- **DONE:** arm control-plane (per-sleeve, fail-closed boot_reset, watchdog force-disarm-only) · per-sleeve Live cards + wallet panel (pUSD contract displayed: 0xc011a7e1…82dfb) · KILL button (was wired to NOTHING before — now real) · CPU pins (latency tails −31..−48%) · twins retired (roster = 8 ladder arms + sumpair + live sleeve) · :8443 zombie retired (410) · python stack retired · DB timeouts + boot_db_guard (post-outage hardening) · events partitioned (19s→6ms) · operator password rotated + login working · dashboard: OPS/WINDOWS/CHART/A-B/SUM-PAIR live w/ ws push, window chart w/ our orders+fills.
- **OPERATOR (in progress):** fund `0xDBe708dd048c63588051b5bB22316eD34ae545e4` — ~3 POL native first (plumbing test on wallet panel), then **$40 pUSD (token contract 0xc011a7e1…82dfb — NEVER send to the contract address; it's the token selector)**; then 5 approvals in Settings; agent verifies allowances on-chain, STOPS.
- **THEN:** operator-triggered drills (tv-drill place → watchdog kill count≥1→0; kill -9 variant) → $2 one-window dry-arm via the button → session-1: v3_live, $4/side warm-up → $12, $40/day, $15 breaker, 5h supervised. Product = capture ratio (sub-cap ≤$24 windows separately; capture_today AND capture_merged until redemption-fee question measured).
- **Promotion ladder (pre-registered):** session-1 clean + capture ≥50% → longer/higher-cap session-2 → c2 sizing → c2rcg config (verdict imminent) → sumpair BTC live (own executor, later). 15m stays paper pending delta-stream queue-sim research.

## D. In flight (agents)
- **TV agent:** chart selector redesign (one entry per sleeve + period SEARCH + human window labels "11:45 – 11:50 · 03/06", no raw epochs) + oracle-pane fix (relay PROVEN healthy from Ireland — /oracle/prices 200 fresh 3.6s; bug is tv-api hitting bare /oracle → 200+SPA-HTML silent poison, zero error logs; add reason-badge unreachable/parse/stale). Also owed: Tape/Health pages, PWA, phone screenshot, Ireland target/ cleanup (11G again).
- **Storedata agent:** 🔴 VPS3 disk 95% (9.9G free) — orderbook_deltas_v2 retention NEVER applied (flagged Jul 23): add drop_after 30d + one-off chunk drop to ≥30G free + growers audit + <20G disk alarm. Ruling recorded: 30d rolling deltas sufficient for queue-sim research, no export needed.
- **Known-good:** Ireland disk 9.7G free w/ July partition compaction due (runway ~11d, his script exists, needs trigger — agent CANNOT self-trigger on wall clock; anything scheduled needs operator ping or cron).

## E. Standing rules (unchanged)
Judge by paired same-slug stats, never summed arms (arms replay the SAME windows — summing = 4× fiction). Twin never pauses while live armed (capture ratio). No post-hoc tuning of failed pre-registrations (v32 lesson). Oracle pane never shows a CEX proxy (Polymarket's own public WS is a CEX republish — memory: project-polymarket-price-ws-not-oracle). Engine restarts are no longer free once the wallet is funded.
