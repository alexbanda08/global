# Ireland TVRUST implementation audit — what's actually running, and what its data says
**2026-07-01. Full sweep of everything implemented on `vps_ireland` (TVRUST engine, `tradingvenue_rust` DB) + source cross-check against `Desktop/TVRUST`. Complements `IRELAND_LADDER_V2_FIRST_RESULTS_2026_07_01.md` (ladder analysis). Raw: `strategy_lab/directional/_ireland_6day/{_impl_recon,_impl_deep}.txt`, `resolves_all.tsv`.**

## 0. Implementation inventory (vs the specs we sent)
| spec | status on Ireland |
|---|---|
| Moat infra I0–I4 (racer 4-conn, parse fix, ladder, latency tape) | ✅ LIVE (analyzed: v1 13.4d, v2 31h) |
| Ladder v2 (G1 residual + G3 pvs gate, fresh namespace) | ✅ LIVE (fallback path: same DB, sleeve `_v2`; v1 data not yet deleted) |
| **`sumpair_osc` V2 $0 shadow** | 🟡 **CODE COMPLETE (`sumpair_osc.rs`, 30 KB, Jun 29) but NEVER ENABLED — `TV_SUMPAIR_OSC_ENABLED` absent from `/etc/tv/tvrust.env` → zero events. One env flag away.** |
| **`tv-watchdog`** | 🔴 **NOT deployed** (no service on the box). Live-arm prerequisite still missing. |
| Rust sleeve fleet (snipers/scalp twins, Jun 11 bring-up) | ✅ running; tape analyzed below — with a big caveat (§2) |

## 1. Racer / feed (v2 window, 133 slugs)
- **Active-window book freshness is GOOD early/mid window:** avg book_age by time-remaining decile ≈ 54–150 ms through the first 70% of the window. Parse fix + racer working (1.13 M level-updates applied; dedup_first_wins 1.47 M ≈ 1.3× applied — sane 4-conn ratio; recorder_dropped 0).
- ⚠️ **Book goes stale in the endgame:** avg book_age rises to ~0.9 s (decile 3), 1.75 s (decile 2), **2.7 s (final decile)** — exactly when price races to 0/1. Prime suspect: the **>15¢ outlier reject gate** (42,585 rejects, 3.6% of updates) throwing away legitimate end-of-window moves. Matters for any T−60s action (e.g., the v3 residual backstop). Needs a look.
- Ladder-tick dynamics (v3 design input): fills accrue smoothly all window (4.3 sh → 29.1 sh); pair_frac 0.09 → 0.585; paused% 31% → 94% at end. Residual management must run continuously, not just at close.
- Note: v1's `level_updates_applied` (468 M) vs v2 (1.13 M) differ ~50× per-slug — metric definition changed between builds; freshness conclusions rest on book_age, which is measured the same way.

## 2. 🔴 THE BIG FINDING — the Rust resolve tape does NOT measure the scalp edge
`shadow_scalp_exit_btc_5m_d3_v1` (Rust) shows **−$33.85 over 455 resolves (−$0.074/tr, WR 62.2%)** vs the validated +0.91/tr expectation. **This is NOT parity evidence against the edge — the Rust tape isn't measuring the edge at all.** Three source-verified defects:

1. **Resolve PnL = hold-to-resolution for EVERY sleeve.** `resolver.rs` computes `slot_resolution_pnl(entry, qty, won)` generically — losses book **exactly −$5.000** (full stake), wins book the resolution payout (+$2.92 avg at ev 0.63 ✓ arithmetic). The `ScalpExit` sell loop IS spawned (`sniper.rs:1418` "poll/deadline sell loop") but **its result never reaches any event** — there is no `scalp_exit` kind and `resolve` ignores exits. The +60s time-sell (the entire validated edge: execution, not prediction) is invisible in telemetry.
2. **Entry band (0, 0.55) NOT enforced on the poly PAPER path.** Fills median **0.63** (p10 0.56, p90 0.71), both directions equally, only ~5% below 0.55. The band check exists only in the LIVE path (`sniper.rs:1364`) and in `kalshi.rs`; the paper fire path skips it. So the twin trades a systematically different (richer) entry population than the deployed config.
3. **Stale exit knobs in the port:** `sleeves.rs:1401` comment carries "tp 0.65, stop 0.10" — the pre-2026-06-11 config. Operator-final is PURE +60s time sell, TP OFF, STOP OFF (both hosts). Must be synced before the twin means anything.

**Consequence:** what the twin actually measured = *favorite-hold on unbanded (ev≈0.63) entries* → WR 62.2% vs ~65–66% breakeven → −0.074/tr, exactly as hold-math predicts. **Do not read this as scalp-edge decay.** But it also means **we currently have NO Rust-side measurement of the exit-scalp** — fix before trusting any Rust scalp number.

## 3. Rust sleeve tape (Jun 11 → Jul 1, resolve events with pnl)
| sleeve | n | sum | $/tr | CI95 | WR | read |
|---|---|---|---|---|---|---|
| poly_sniper_v5_btc_15m_ema50_ema800_off600_down | 581 | **−$153.32** | −0.264 | [−0.64,+0.13] | 68.5% (ev 0.80) | bleeding; below ~80% breakeven; consistent with the killed BTC-15m sniper family |
| kalshi_sniper_…_off600_down_H | 301 | **−$50.22** | −0.167 | [−0.66,+0.34] | 63.1% | same story on Kalshi |
| shadow_scalp_exit_btc_5m_d3_v1 | 455 | −$33.85 | −0.074 | [−0.44,+0.29] | 62.2% | **⚠️ hold-counterfactual, not the edge (§2)** |
| poly_sniper_v5_eth_5m_…hurst_grandparent_V10 | 68 | **+$22.46** | +0.330 | [−1.07,+1.83] | 54.4% (ev 0.49) | matches the ETH cloud/hurst family (+0.33 vs +0.37 shadow OOS) — nice engine-parity signal, n small |
| kalshi_scalp_exit_btc_15m_d3_v1 | 81 | — | — | — | — | **all resolves have `pnl_usd = NULL`** — telemetry gap |

Latency (v2): recv→apply p50 37 µs / p95 80 µs. Warmup fails 4/124 windows.

## 4. Action list (beyond the v3 residual spec already in flight)
1. **Enable `sumpair_osc`** — code is built and gated; set `TV_SUMPAIR_OSC_ENABLED=true` (+its config block from `TV_AGENT_HANDOFF_IRELAND_V2_SHADOW_2026_06_16.md` §2.3) and the V2 fill-model shadow starts accruing. Zero code work.
2. **Deploy `tv-watchdog`** — still the live-arm prerequisite for everything.
3. **Fix the scalp twin so it measures the edge:** enforce `entry_band` on the paper path; emit the sell-loop result (`scalp_exit` event kind or exit-aware resolve PnL: `pnl = (sell_vwap − entry_vwap)·sh`); sync knobs to PURE +60s (tp OFF, stop OFF). Until then, exclude Rust scalp numbers from any edge judgment.
4. **`kalshi_scalp` NULL pnl** + **`pair_gate_bound_sh` never counts** — two small telemetry patches.
5. **Endgame feed staleness:** review the >15¢ reject gate near window end (book_age 2.7 s in the final decile) — it degrades exactly where the v3 taker-backstop must execute.

**Bottom line:** the moat infra is healthy and the ladder v2 experiment is doing its job. But of the two decision-critical shadows, one (`sumpair_osc`) was never switched on, and the other (the Rust scalp twin) is measuring the wrong thing — hold PnL on out-of-band entries — so its −0.074/tr says nothing about our edge. Both are cheap fixes: one env flag, one telemetry patch.
