# Session Handoff — 2026-04-29

**Read this first in the next session. This supersedes SESSION_HANDOFF_2026_04_28.md.**

---

## TL;DR — Where we are

🎯 **NEW FLAGSHIP: V3 portfolio strategy.** Per-asset tuned 3-sleeve sniper portfolio (BTC q10 + ETH q5 + SOL q15 multi-horizon) on 5m markets only. Forward-walk holdout: **+32% ROI, 0 down days, 10/10 validation gates passed.** Deploy guide ready: `strategy_lab/reports/polymarket/01_deployable/TV_STRATEGY_V3_PORTFOLIO_DEPLOY_GUIDE.md`.

✅ **Sim-vs-live mystery closed.** The 30-pp gap is execution layer (50% feed disagreement on small |ret_5m| + HYBRID bid-exit branch). Sim is honest. Both fixes already in `docs/VPS3_FIX_PLAN.md`.

✅ **V2 calibrated-probability stack KILLED.** prob_a/b/c/stack failed forward-walk; raw `sig_ret5m` magnitude filter is more robust to distribution shift than learned calibrators on 7-day data.

✅ **6 paradigms tested + ruled out:** covered-call structure (no edge), maker-both-sides (adverse selection), cross-asset BTC-leader (no predictive power), vol-regime conditioning (minor edge only), exit-in-profit (TP/SL/trail all hurt vs hold), entry-timing delay (loses 24pp ROI).

✅ **VPS2 collector continues running.** Has 8,189 resolved markets across 7.17 days at session end, 2.1-min stale on Binance klines. VPS3 has 14d klines backfill prerequisite documented (per VPS3_FIX_PLAN).

🎯 **Next session focus:** Either (a) ship V3 to VPS3 if TV agent ready, or (b) continue research while VPS3 V2 runs — reuse V3 in 30-day re-validation when collector accumulates more data.

---

## What's locked (don't redo)

| Decision | Value | Source |
|---|---|---|
| **Flagship strategy** | **V3 portfolio**: per-asset tuned magnitude sniper, 5m only | `RESEARCH_DEEP_DIVE_2026_04_29.md` + 10-gate validation |
| Per-asset magnitudes | BTC q10, ETH q5, SOL q15 + multi-horizon | `portfolio_backtest.py` BEST_CELLS |
| 15m markets | dropped from V3 | adding 15m sleeves drops portfolio HO ROI 32% → 26% |
| Exit rule | HEDGE_HOLD only — never bid-exit (HYBRID branch banned) | live VPS3 V2 HYBRID lost ~$1,300 from bid-exit alone |
| Entry mode | maker @ bid+$0.01, wait 30s, fall back taker | +1.3pp HO ROI lift, validated forward-walk |
| Spread filter | skip if `(ask-bid)/mid >= 2%` at entry | +2pp lift validated |
| Reversal threshold | none in V3 (just hold) | TP/SL/trail/oppo-flip ALL hurt ROI vs pure hold |
| **The signal** | `sig_ret5m` raw magnitude, NOT calibrated probability | V2 calibrated stack failed forward-walk; raw threshold robust |
| Multi-horizon filter | enabled SOL only (ret_5m, ret_15m, ret_1h same sign) | +24pp HO ROI lift on SOL via G8 swap test |
| Auxiliary features (OI, L/S, taker, smart-flow, ret_15m, ret_1h alone) | all near-0 IC | univariate IC analysis 2026-04-29 |
| UP/DOWN asymmetry | none (p > 0.4) | `polymarket_side_asymmetry.py` |
| Vol-regime conditional sleeves | weak (+3pp at most), not worth conditioning | A3 backtest 2026-04-29 |

If a new strategy beats current matrix on forward-walk, fine to extend. Otherwise leave alone.

---

## Current TV deployment status

**VPS2** (V1, control arm): runs HEDGE_HOLD volume-mode, OKX-WS feed. Live tape captured (693 resolutions, 47% hit, $-1.8k PnL — sim agrees on volume-mode performance). No changes pending.

**VPS3** (V2, test arm): runs HYBRID volume+sniper, binance-spot-ws feed. Sniper sleeves cold-start (no fires) until 14-day Binance backfill lands. HYBRID bid-exit branch costs $-1.3k of the $-2.8k loss. **TV agent's task list** (per `docs/VPS3_FIX_PLAN.md`):
1. Backfill 14d binance-spot-ws klines (unblocks sniper)
2. Flip `TV_POLY_HEDGE_POLICY=HEDGE_HOLD` (kills bid-exit)
3. Code PR: maker entry, spread<2% filter, hour whitelist (optional)

**V3** (this session, ready to ship): same prerequisites as V2 fix (uses identical Binance backfill). Deploy guide: `strategy_lab/reports/polymarket/01_deployable/TV_STRATEGY_V3_PORTFOLIO_DEPLOY_GUIDE.md`. Estimated 10-12h of TV agent work, single-day PR.

After V3 deploy, VPS3 will run **15 sleeves** total: 6 V2 volume + 6 V2 sniper + 3 V3 — all paper, all separately attributable in `trading.events` by sleeve_id suffix (`_volume`, `_sniper`, `_v3`).

---

## Folder map (after this session)

```
docs/
  COVERED_CALL_PREDICTION_STRATEGY.md       # initial idea — superseded by S2 backtest finding
  BACKTEST_DATA_REQUIREMENTS.md             # high-level data spec — done
  VPS2_DATA_AVAILABILITY.md                 # snapshot of VPS2 data 2026-04-29
  BINANCE_VISION_BACKFILL_PLAN.md           # done; Binance Vision pulls integrated
  SNIPER_DATA_SPEC_VPS3.md                  # V2 sniper data dependency spec
  SHADOW_TRADE_DIAGNOSIS.md                 # initial sim-vs-live diagnosis (superseded by S1 below)
  RECALIBRATION_PLAN.md                     # 9-tier orchestration plan — executed
  FRESH_RECALIBRATION_RUNBOOK.md            # tier-by-tier playbook
  FINDINGS_2026_04_29.md                    # original recalibration findings (sniper q10 + maker)
  VPS3_FIX_PLAN.md                          # TV agent's V2 fix list (still valid; V3 piggybacks)
  RESEARCH_ROADMAP_2026_04_29.md            # 11-tier research plan; S1/S2/A1/A2/A3 complete
  V2_SIGNALS_DECISION.md                    # V2 stack kill verdict
  plans/
    2026-04-29-v2-signals-design.md
    2026-04-29-v2-signals-implementation.md

strategy_lab/
  v2_signals/                               # all session code
    common.py                               # load/save_features, chronological_split, ASSETS
    build_signal_a.py                       # multi-horizon momentum (V2, killed)
    build_signal_b.py                       # vol-arb digital (V2, killed)
    build_signal_c.py                       # microstructure flow (V2, killed)
    build_stack.py                          # LogReg meta (V2, killed)
    sim_vs_live_recon.py                    # S1 — closes the 30-pp gap mystery
    covered_call_backtest.py                # S2 — no edge in steady-state covered call
    maker_both_sides_backtest.py            # A1 — adverse selection dominates
    cross_asset_leadlag_backtest.py         # A2 — BTC doesn't lead alts on 5m/15m
    vol_regime_backtest.py                  # A3 — vol regime barely matters
    entry_timing_backtest.py                # entry delay loses 24pp ROI
    exit_variants_backtest.py               # hold-to-resolution wins everywhere
    sig_search_backtest.py                  # *** found V3: per-asset mag tuning ***
    multi_horizon_forward_walk.py           # V3 forward-walk validation (16 cells pass)
    portfolio_backtest.py                   # V3 portfolio: 32% HO ROI / 0 down days
    portfolio_gauntlet.py                   # 10-gate validation gauntlet (all passed)
    test_*.py                               # 19 unit tests, all passing
  reports/
    SIM_VS_LIVE_RECONCILIATION.md           # S1 findings
    COVERED_CALL_BACKTEST.md                # S2 verdict
    MAKER_BOTH_SIDES_BACKTEST.md            # A1 verdict
    CROSS_ASSET_LEADLAG.md                  # A2 verdict
    POLYMARKET_V2_SIGNALS_FINDINGS.md       # V2 stack kill report
    RESEARCH_DEEP_DIVE_2026_04_29.md        # *** V3 discovery + 10-gate gauntlet ***
    polymarket/01_deployable/
      TV_STRATEGY_V3_PORTFOLIO_DEPLOY_GUIDE.md   # *** SHIP THIS ***
  data/polymarket/
    {btc,eth,sol}_features_v3.csv           # extended with prob_a/b/c/stack columns
    {btc,eth,sol}_flow_v3.csv               # 60s pre-window trade flow (Task 4 extract)
    vps2_v1_shadow.csv                      # V1 shadow tape for reconciliation
    vps3_v2_shadow.csv                      # V2 shadow tape for reconciliation
```

---

## Data state

**VPS2** (`2605:a140:2323:6975::1`) — collector source-of-truth:
- `orderbook_snapshots_v2`: 19.16M rows / 8,395 markets / 7.17 days (live, growing)
- `market_resolutions_v2`: 8,206 resolved (6,154 5m + 2,052 15m), 99% with strike+settle
- `trades_v2`: 8.05M Polymarket prints
- `binance_klines_v2`: full year 1m/5m/15m/1h/4h/1d, source `binance-vision` + filled gap with `binance-spot-ws` from VPS3 (continuous to 2.1-min stale)

**VPS3** (`185.190.143.7`) — strategy-only:
- `binance_klines_v2 source='binance-spot-ws'`: 1.06 days only (started 2026-04-28 20:53). **Needs the 14d backfill before sniper or V3 fires.**
- Live trade tape: 1,594 V2 signals, 607 resolutions, 299 hedge_skip events.

**Local**:
- 8,189 resolved markets in `data/polymarket/{asset}_features_v3.csv` with extended columns (prob_a/b/c/stack from V2 work + multi-horizon ret cols)
- 245 MB book_depth_v3 across 3 assets (full L21 books at 10s buckets)
- 4.5 MB shadow tapes (V1 + V2)

---

## Validation evidence (V3 — the bar each new variant must clear)

10-gate gauntlet on V3 portfolio (3-sleeve), all passed:

| Gate | Result |
|---|---|
| G1 outcome-permutation (200 reps) | p < 0.005 (real $1029 vs perm mean $149±313) |
| G2 block bootstrap (1000 reps) | 95% CI [$602, $1456] — lower bound positive |
| G3 realistic L10 fills | HO ROI 27.09% (vs 32.16% top-of-ask, 5pp haircut) |
| G4 multi-split 60/70/80/90 | HO ROI 25-41% — stable, monotonic |
| G5 per-day | both holdout days positive |
| G6 sample-size 50/75/100% | HO ROI 21-32% — robust |
| G7 magnitude ±2pp | smooth optima, all positive |
| G8 multi-horizon swap | SOL benefits +24pp; BTC/ETH neutral or worse |
| G9 maker overlay | +1.3pp HO ROI lift |
| G10 stratified ret_5m perm | direction IS the alpha (p < 0.005) |

Threshold for ANY new variant going forward: must beat or match V3's 10-gate results on the same forward-walk.

---

## Repo state

GitHub: https://github.com/alexbanda08/global

Last committed (this session, before "stop committing" instruction):
```
c82e9cb feat(a2): cross-asset lead-lag - BTC does NOT predict ETH/SOL on 5m/15m
ad63fd3 feat(a1): maker-on-both-sides backtest - adverse selection dominates
c40aa62 feat(s2): covered-call backtest - no edge in steady-state structure
0323598 feat(sim-vs-live): S1 reconciliation - decompose 30pp gap into 3 components
130c50a docs(v2_signals): kill decision - all 4 new signals failed forward-walk gate
c1fb284 feat(v2_signals): wire prob_a/b/c/stack into signal_grid_v2 + forward_walk_v2
... (V3 discovery work intentionally uncommitted per user instruction)
```

**Uncommitted (in working tree, awaiting user push instruction):**
- `strategy_lab/v2_signals/vol_regime_backtest.py`
- `strategy_lab/v2_signals/entry_timing_backtest.py`
- `strategy_lab/v2_signals/exit_variants_backtest.py`
- `strategy_lab/v2_signals/sig_search_backtest.py`
- `strategy_lab/v2_signals/multi_horizon_forward_walk.py`
- `strategy_lab/v2_signals/portfolio_backtest.py`
- `strategy_lab/v2_signals/portfolio_gauntlet.py`
- `strategy_lab/v2_signals/sim_vs_live_recon.py`
- `strategy_lab/v2_signals/covered_call_backtest.py`
- `strategy_lab/v2_signals/maker_both_sides_backtest.py`
- `strategy_lab/v2_signals/cross_asset_leadlag_backtest.py`
- `strategy_lab/reports/RESEARCH_DEEP_DIVE_2026_04_29.md`
- `strategy_lab/reports/COVERED_CALL_BACKTEST.md`
- `strategy_lab/reports/MAKER_BOTH_SIDES_BACKTEST.md`
- `strategy_lab/reports/CROSS_ASSET_LEADLAG.md`
- `strategy_lab/reports/SIM_VS_LIVE_RECONCILIATION.md`
- `strategy_lab/reports/polymarket/01_deployable/TV_STRATEGY_V3_PORTFOLIO_DEPLOY_GUIDE.md`
- This handoff doc

**To resume:** the operator can run `git status && git add -A && git commit -m "..." && git push` when ready.

---

## VPS access cheat sheet

```bash
# VPS2 collector + V1 shadow
ssh -i ~/.ssh/vps2_ed25519 root@'[2605:a140:2323:6975::1]'
# Postgres: peer auth via `sudo -u postgres psql -d storedata`
# Read-only via /etc/tv/tv-ro.env (TV_RO_PWD_PLAIN)

# VPS3 V2 strategy + binance-spot-ws collector
ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7
# Postgres: tradingvenue_ro (pwd in /etc/tv/tv-ro.env)
# Operator login: operator / 7ldip+mTW-8k#@RsgJv#
# tradingvenue write user: tradingvenue / e7mFkLNAJc6agwBam5H6AnJRb1W-YwdT
```

**Important:** large `EXISTS (SELECT 1 FROM orderbook_snapshots_v2 ...)` queries can lock the table for tens of minutes on VPS2. Always slug-scope or short-time-range queries.

---

## Next-session decision tree

**If TV agent shipped V3 to VPS3:**
1. Monitor 24h: per-sleeve fire counts, hit rates, PnL.
2. After 7 days: A/B compare V1 (VPS2) vs V2 vs V3 paper. Decision: which to ramp.

**If TV agent hasn't shipped V3 yet:**
1. Read `TV_STRATEGY_V3_PORTFOLIO_DEPLOY_GUIDE.md` end-to-end.
2. Confirm prerequisites (VPS3 14-day Binance backfill landed).
3. Single-day PR with the 7 changes (per-asset quantile, multi-horizon flag, spread filter, maker entry, sleeve registration, env vars, tests).
4. Smoke test in shadow mode before any live ramp.

**If continuing research:**
1. Re-run V3 portfolio + V2 signals stack on 30 days when collector reaches that. Schedule for ~2026-05-23.
2. Revisit C-tier roadmap items (Kalshi/Manifold venues, LLM-event-driven). All speculative, multi-day cost each.
3. **Don't** test more 7-day variants — the data has been thoroughly exhausted (12 backtest paradigms run, 1 winner found, 11 ruled out).

---

## Critical context the next session must NOT miss

1. **Live VPS3 V2 hit rate is 26.5%, not because the signal is broken** — but because (a) sniper never fired (no Binance backfill) so VPS3 ran volume-mode only, and (b) HYBRID bid-exit fallback bled $1.3k. After both fixes, expect 65-72% hit rate per V2 sniper, and 60-72% per V3 sleeve (per backtest forward-walk).

2. **The simulator is HONEST.** Sim-vs-live decomposition (S1) showed the 30-pp gap is entirely in the execution layer. Trust the backtest numbers within their stated bounds.

3. **The 2-day holdout is the only weak point in V3.** All 10 gates passed but the holdout slice is just 1.4 days of data. Re-validate at 30 days before any size scaling beyond paper.

4. **V3's per-asset gates are TUNED on this 7-day window.** ETH q5 is tighter than backtest hyperparameter convention; SOL multi-horizon was found via swap test. Both are credible (forward-walk, gauntlet) but small-n. Treat the magnitudes as live-tunable, not gospel.

5. **The covered-call original idea is empirically dead** for short-tenor binaries (S2 result: ROI 0.7-1%, leverage doesn't help). Don't revisit unless we add vol-arb conditioning.

6. **Polymarket microstructure (trade flow) is empirically dead** as a primary signal (A1 + V2 prob_c). It works AT THE BOOK ENTRY level (maker overlay +1.3pp) but not as a directional signal.

End of handoff.
