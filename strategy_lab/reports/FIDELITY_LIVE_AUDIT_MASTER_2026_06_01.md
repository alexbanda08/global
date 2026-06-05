# Live-vs-Spec-vs-Backtest Fidelity Audit — MASTER tracker (2026-06-01)

**Goal:** for every sleeve firing in shadow on VPS3, compare the LIVE engine logic against
(a) the global-folder engine/strategy code that created it, (b) the written spec, (c) the
backtest that validated it. Flag **MATCH / DRIFT / BUG** per family, with evidence.

**Inputs (all local):**
- LIVE engine snapshot: `vps3_engine_snapshot_2026_06_01/` (pulled from VPS3 `/opt/tradingvenue/backend/app/`).
- Firing list (7d): `vps3_engine_snapshot_2026_06_01/firing_sleeves_7d.csv` (154 sleeves).
- Family classification: `vps3_engine_snapshot_2026_06_01/families.json` (16 families).
- Global engines: `strategy_lab/engine_v2.py`, `strategy_lab/book_walk.py`, `strategy_lab/_opt_2026_05_30/*`, `cyclops/`, universe panels.
- Specs: `strategy_lab/reports/TV_AGENT_SPEC_*.md`, `SHADOW_DEPLOY_SPEC_*`, `CYCLOPS_CLONE_SPEC_*`.
- Prior audits (update, don't redo): `FIDELITY_AUDIT_*_2026_05_29.md`, `ENGINE_AUDIT_{A,B,C,D}_2026_05_29.md`, `ENGINE_CORRECTNESS_AUDIT_2026_05_28.md`.
- Conventions that MUST hold (CLAUDE.md): `ws_s = slot_start − window_s` anchor; F7 RSI simple-mean Wilder at ws_s; fee = 0.07·p·(1−p) winner-only; L25 native 10Hz; cross-token vs same-token spread.

## Engine→family map (audit units)
| Auditor | Engine / files (live) | Families covered | Firing sleeves (n) | Report |
|---|---|---|---|---|
| **A1** | `sniper_v5_gates.py`, `sniper_v5_sleeves.py`, `sniper_v5_thresholds.py`, `poly_sniper_v5_loop.py`, `poly_maker_fill_sim.py`, `sleeve_registry.py` | sniper_v5 FRAMEWORK (fill/fee/gate plumbing) | framework | FIDELITY_LIVE_A1_sniperv5_framework_2026_06_01.md |
| **A2** | sniper_v5 sleeve defs + `microstructure.py`, `features_1s.py`, `vwap_store.py` | snv5_eth_5m, snv5_btc_5m, snv5_btc_15m(ema_down), snv5_eth_15m, snv5_sol_15m, kalshi(ema_down port) | ~55 | FIDELITY_LIVE_A2_sniperv5_sleeves_2026_06_01.md |
| **B** | `momo.py`, `momo_v2.py`, `f7_gate.py`, `poly_updown_loop.py` | updown_momo_v1, updown_momo_v2 | ~38 | FIDELITY_LIVE_B_momo_f7_2026_06_01.md |
| **C** | `engine/oracle_lag.py`, fast_taker sleeves in sniper_v5 | fast_taker (lagv2 + b2_nomerge) | 5 | FIDELITY_LIVE_C_fasttaker_oraclelag_2026_06_01.md |
| **D** | `updown_5m.py`, `updown_15m.py`, `inverse.py`, `vwap_continuation.py`, `gates.py` | updown_inverse, updown_v3v4, updown_sniper_hod, updown_vwap_off, snv5_sol_5m | ~40 | FIDELITY_LIVE_D_legacy_updown_2026_06_01.md |
| **E** | shadow sleeve defs (`shadow9.py`, kelly/prewindow/fade) | shadow_updown | 14 | FIDELITY_LIVE_E_shadow_updown_2026_06_01.md |

## Per-auditor verdict (COMPLETE 2026-06-01)
| Auditor | MATCH | DRIFT | BUG | Headline |
|---|---|---|---|---|
| A1 framework | 4 | 2 | 0 | **Fee-model setting ambiguity** on VPS3 (`tv_poly_maker_fee_model` default `"curve"`=0.07 on every take incl losers, vs CLAUDE.md "2%-on-profit"). + fill-realism off by default (no 85ms/sparse-book guard → live fills thin books backtest rejects, esp SOL). |
| A2 sleeves | 21 | — | 2 | `btc_5m_l_1hrf_imb5_{rf,ribbon}_v8` gate-1 = `g_grandparent_trend_with` live but spec = `g_1h_rf_with` (unfixed since 05-29, −$996 live). V10 ema_down band gate [0.15,0.93] **doesn't exist** (only narrow [0.15,0.55]). ETH-5m-hurst family **fully faithful**. |
| B momo/f7 | 21 | 0 | 0 | Losses are **faithful decay**: live `momo_HOLD_f7` runs **bare F7 without the M1V/M5V Markov overlay** that gave +59% WR → ~51%/breakeven. ws_s + simple-Wilder RSI confirmed. 15m cells +EV. |
| C fast_taker | — | — | 8 | **CONFIRMED:** all 8 fire 100% UP — gates read `oracle_lag.price_delta_bps`=(binance−chainlink_strike)/oracle (structurally +) instead of intra-window binance return. Fix = swap the shim in `_build_gate_kwargs`; history reset. b2_nomerge design faithful. |
| D legacy | 0 | 5 | 0 | 0 code bugs. 17 **faithful-but-bad** (INV_NIGHT ×6 −$3.4k premise wrong → KILL; v3/v4 edge gone → KILL). 5 stale-HoD drift. **11 sol_5m sniper UNVALIDATED** (no SOL universe; 55% ask-NaN inflates BT). |
| E shadow | 14 | — | 3(minor) | `phase1_kelly` −$1780 = **kelly SIZING flaw on ~50% signal** (4× fe tail didn't recur), not a bug. `S4_prewindow` +$238 real+causal but n=25 + edge in live pre-window top-of-book (uncanonical). fade ×6 = anti-edge −$1.2k. |

## SYNTHESIS — the engines are faithful; the losses are mostly real
Across ~120 firing sleeves, **only 2 real code bugs** exist: (1) the fast_taker 100%-UP signal (8 sleeves, C), (2) `l_1hrf_imb5` gate-1 (2 sleeves, A2). Everything else is **correctly implemented** — the negative live PnL is faithful (dead/decayed signal) or unvalidated, NOT engine drift. This is the key reassurance: live ≈ what the code says; where live ≪ backtest it's overfit-decay, not a fidelity break.

### Cross-cutting issue #1 — FEE MODEL split-brain (resolve FIRST, it distorts every PnL)
A1 and E independently found live code charges the **0.07·p·(1−p) curve** (`poly_maker_fill_sim.py:843` default `"curve"`; `poly_updown_resolver.slot_resolution_pnl`), while CLAUDE.md's 2026-05-22 verification said production actually charges **2%-on-profit-only**, and the Jun-01 handoff says 0.07-curve-winner-only is "operator-confirmed correct." These disagree. **Action: read `settings.tv_poly_maker_fee_model` on live VPS3 + confirm against an actual `poly_updown_resolution` event's `pnl_usd`. Until resolved, every shadow $ figure is ±$0.34–0.43/winning-trade uncertain.**

### Real code bugs to fix
1. 🔴 **fast_taker signal** (C) — swap `price_delta_bps` shim → intra-window binance return in `_build_gate_kwargs`; fixes all 8; reset history. This unblocks the one real edge.
2. 🔴 **l_1hrf_imb5_{rf,ribbon}_v8** (A2) — gate-1 wrong (`g_grandparent_trend_with`→`g_1h_rf_with`), −$996 live.
3. 🟡 **V10 ema_down band gate** (A2) — `g_entry_vwap_band(0.15,0.93)` not implemented; needed before the specced deploy.

### KILL list (faithful-but-bad, bleeding shadow PnL on dead premises)
- INV_NIGHT ×6 (−$3.4k, premise wrong) · fade ×6 (−$1.2k, anti-edge) · v3/v4 SOL+btc (edge gone) · phase1_kelly (kelly on coin-flip; or drop to fe1000-gated V10) · the 2 look-ahead KILLs (q_parent15mslope, ts_mpskew_any_off30).

### Faithful + real edges (keep / promote)
- **ETH-5m hurst sniper family** (fully faithful, +PnL, low-DD) — the fleet's best.
- **btc_15m ema_down DOWN family** (faithful) — add the band gate.
- **momo 15m cells** (+EV) — add Markov overlay to the 5m HOLD sleeves to recover the +59% WR.
- **fast_taker** — real edge, blocked ONLY by the signal bug above.

### Validation gaps to close
- Build the **SOL 5m universe panel** → 11 sol_5m sniper sleeves currently run on faith (+ SOL L25 55% ask-NaN inflates any BT).
- Refresh stale **HoD tables** (sniper_hod anti-selecting) — build the never-built `_recompute_hod_top8.py` monthly job.

### Reports
FIDELITY_LIVE_{A1,A2,B,C,D,E}_*_2026_06_01.md (per-engine detail).

## Known-going-in (from handoffs)
- 🔴 `fast_taker_lagv2`: 8 sleeves fire 100% UP — wrong signal (feed-vs-oracle instead of binance intra-window return). `TV_AGENT_FIX_LAGV2_SIGNAL_2026_06_01.md`.
- 🔴 `btc_5m_parent15m_notrang`: missing `parent_15m_not_ranging` gate → 28× over-fire (reconstruction broken; verify in live too).
- 2 KILLs (`btc_5m_q_parent15mslope_ts_imb5_v8`, `btc_5m_ts_mpskew_any_off30`): look-ahead originals, confirmed dead full-period.
- ema_down: fidelity ✅ already (EMA_DOWN_DEEPDIVE); band [0.15,0.93] is the edge.
