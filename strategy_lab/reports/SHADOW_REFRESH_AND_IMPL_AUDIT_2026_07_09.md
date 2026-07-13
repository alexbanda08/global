# Shadow refresh (v2/v3/v4, Jul 8→9 delta) + TV-agent implementation audit
**2026-07-09. Two-period split: the Jul-8 audit window (Jul 2–8) vs the ~1 new day since. Raws: `_ireland_6day/ladder_all_refresh.tsv`, compiled tables in `_ireland_6day/_wf/`. Companion to `IRELAND_V3V4_TRUST_AUDIT_GOLIVE_2026_07_08.md`.**

## 1. Shadow delta — did anything change?
| sleeve | Jul 2–8 (baseline) | Jul 8→now (new) | read |
|---|---|---|---|
| **btc-5m v3** | +1.026 CI[+0.73,+1.38] ex2 +0.87, $212/d | **+0.795 CI[+0.26,+1.43] ex2 +0.55, $171/d (n=211)** | ✅ **HOLDS out-of-window** — the go-live case got stronger (now ~7d, positive every single day) |
| btc-15m v4_coc | +0.609 ns | **+1.426 CI[+0.02,+3.29]** (n=30) | 🟢 strengthening — new window clears 0; retract my "kill in a week" lean, extend the trial |
| btc-15m v3 | +0.013 ns | +0.627 ns (n=38) | still flat/marginal — unchanged |
| **eth-5m v3** | +0.425 CI[+0.16,+0.69] | **−0.170 [−0.59,+0.25]** (n=102) | 🔴 flipped negative — residual −0.285 is the driver; not significant yet, but consistent with ETH being the weak market everywhere (ce25, sumpair). **Demote from go-live consideration; watch 1 more week.** |
| sumpair btc-5m | +0.512 CI>0 | **+1.887 CI[+0.46,+3.78]** (n=91) | strengthening; level0 ≈ walk still (models agree) |
| sumpair eth-5m | −0.058 ns | +0.146 ns | recovered to flat |
| scalp twin | — | 13 exits total, +0.89/tr, band 100% | ⚠️ no fires in ~21h (regime-plausible, watch) |

**Trust re-check on the fresh data: perfect** — reconciliation maxdiff 0.0000 on every sleeve incl. coc terms; 0 stuck windows; outcome-mismatch rate stable ~1–3.5% (the known sub-tick near-ties). The engine's numbers remain fully trustworthy.

**Analysis differences vs Jul-8 conclusions:** (1) btc-5m verdict UNCHANGED-stronger (a true out-of-window hold); (2) v4_coc upgraded from "ns, likely selection" to "trending validated — extend"; (3) **eth-5m downgraded from second-candidate to watch-list** (its residual bleeds where BTC's doesn't — ETH flow toxicity, consistent with every prior ETH datapoint); (4) everything else unchanged.

## 2. TV-agent implementation audit (go-live spec progress)
| item | status |
|---|---|
| `tv-rust-watchdog.service` deployed | ✅ **DONE** — active since Jul 8 17:31, WATCH-ONLY fail-closed, health probe wired |
| Poly CLOB cancel-all | 🔴 **wired but BROKEN**: `400 "Could not derive api key!"` at startup — **root cause is almost certainly the empty secrets registry** (`trading.secrets` = 0 rows): no ladder wallet exists yet, so L1 key-derivation has nothing to sign with. Expected until the wallet step; must be validated with a real drill after creds land. |
| engine heartbeat / kill-latch / rails→kill bridge / pinning / feed-hardening | ⏳ NOT LANDED — engine binary untouched since Jul 5 (these need an engine rebuild+restart); WIP visible in the local tree (`poly_close.rs`, `poly_live.rs`, `risk.rs`, `deploy/` — uncommitted) |
| Phase B (ladder live branch, caps, wallet, reconcile) | not started — correct per phase discipline |
| watchdog DB role | TEMP reuses TV_DB_URL (self-flagged: needs dedicated role before kill capability) |
| ⚠️ **process risk** | **the Jul-8 work exists ONLY as uncommitted local changes** (repo 1 behind origin + big uncommitted diff matching the deployed binaries) — a lost checkout loses the WIP. Tell the agent to commit/push. |

## 3. Actions
1. **TV agent:** (a) commit/push the WIP immediately (loss risk); (b) sequence fix — create the fresh ladder wallet + load Fernet secrets FIRST, then re-validate `derive-api-key` and run a cancel-all drill (the 400 should disappear); (c) proceed with the engine-side Phase-A items (heartbeat/latch/bridge/pinning/feed-hardening) in the next engine deploy.
2. **Research:** keep eth-5m paper on watch (kill/keep at ~2wk total); extend v4_coc; the btc-5m go-live case is now 7 days CI>0 — the statistical side is done, waiting purely on Phase A/B.
3. Minor: check why the scalp twin has fired 0 times in 21h (probably gate/regime; confirm signal cadence is healthy).
