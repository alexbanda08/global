# Research Roadmap — What's Next

**Date:** 2026-04-29 (updated end of session — see "Progress" below)
**Context:** sig_ret5m sniper q10 is the deployable winner. V2 stack killed. Live A/B on VPS2/VPS3 ongoing.

---

## Progress (end of session 2026-04-29)

| Tier | Item | Status | Result | Evidence |
|---|---|---|---|---|
| S | S1 sim-vs-live debug | ✅ DONE | Sim is honest. 30pp gap = 50% feed disagreement (vanishes at q10) + HYBRID bid-exit ($1.3k cost). Both in VPS3 fix plan. | `strategy_lab/reports/SIM_VS_LIVE_RECONCILIATION.md` |
| S | S2 covered-call backtest | ❌ no edge | ROI 0.7-1%, leverage adds nothing, structure is delta-neutral | `strategy_lab/reports/COVERED_CALL_BACKTEST.md` |
| A | A1 maker-both-sides | ❌ adverse selection | ROI -5% to -21%, hit 32-40% (below random) on fired markets | `strategy_lab/reports/MAKER_BOTH_SIDES_BACKTEST.md` |
| A | A2 cross-asset lead-lag | ❌ no predictive power | BTC-leader: 50% hit (random) on alts at 5m/15m | `strategy_lab/reports/CROSS_ASSET_LEADLAG.md` |
| A | A3 vol-regime conditional | ⚠️ minor edge | +3pp at most, not worth conditioning | inside `RESEARCH_DEEP_DIVE_2026_04_29.md` |
| ★ | Entry timing variants | ✅ confirmed | Fire at delay=0; waiting kills 24pp ROI | inside `RESEARCH_DEEP_DIVE_2026_04_29.md` |
| ★ | Exit variants (TP/SL/trail) | ❌ all hurt | Hold-to-resolution dominates every alternative | inside `RESEARCH_DEEP_DIVE_2026_04_29.md` |
| ★ | Sig search (mag sweep + multi-horizon) | ✅ **V3 FOUND** | Per-asset tuned mag (BTC q10, ETH q5, SOL q15+MH) | inside `RESEARCH_DEEP_DIVE_2026_04_29.md` |
| ★ | Multi-horizon forward-walk | ✅ 16 cells pass gate | BTC 5m q10 HO 72.2% / +47%, ETH 5m q5 HO 65.4% / +38%, SOL 5m q15 HO 78.3% / +55% | `strategy_lab/v2_signals/multi_horizon_forward_walk.py` |
| ★ | Portfolio combination | ✅ **+32% HO ROI** | 3-sleeve, 0 down days | `strategy_lab/v2_signals/portfolio_backtest.py` |
| ★ | 10-gate validation gauntlet | ✅ ALL PASSED | Permutation p<0.005, bootstrap CI [+602, +1456], realistic-fill 27% ROI | `strategy_lab/v2_signals/portfolio_gauntlet.py` |
| ★ | V3 deploy guide | ✅ READY | TV agent's playbook | `strategy_lab/reports/polymarket/01_deployable/TV_STRATEGY_V3_PORTFOLIO_DEPLOY_GUIDE.md` |

**12 paradigms tested. 1 winner (V3 portfolio). 11 ruled out cleanly.** The 7-day data has been thoroughly exhausted.

---

## Tier S — Do these first (highest leverage)

### S1. Debug the simulator-vs-live gap
**Why:** Backtest says q10 = 78% hit / +28% ROI. Live VPS2 V1 (HEDGE_HOLD only) = 47% hit, NEGATIVE PnL. **Until this is closed, every backtest number is suspect.**

**What:** Replay every VPS3 V2 resolution through the local Tier 2 simulator with identical inputs. For each market the sim predicted UP/DOWN/SKIP — compare to what live actually did. Find the per-market delta.

Likely causes (ranked):
- **Entry fill price drift**: sim assumes mid (~0.50), live hits ask (~0.53) → ~6% spread cost the sim doesn't model.
- **Hedge attempt success rate**: sim's HYBRID buy-opposite simulator may succeed more often than live's `no_asks` rate (272/648 = 42% on VPS3).
- **Resolution price source**: sim uses chainlink-fast (offline), live uses live oracle. Edge cases at boundary may differ.
- **Feed lead-lag**: sim uses one snapshot per 10s bucket; live ticks at every WS update.

**Output:** `strategy_lab/reports/SIM_VS_LIVE_RECONCILIATION.md` with per-cause breakdown of the 30-pp gap. Decision: which gap component is biggest, fix that first.

**Cost:** 1-2 days. We already have shadow tapes locally.

**Risk:** finding it's a bug in our simulator → all prior numbers wrong. Worth knowing.

---

### S2. Synthetic covered-call backtest (the original idea, never executed)
**Why:** The user's first request was: "long BTC perp + short Polymarket YES = covered call". We sidelined to recalibrate sig_ret5m. Now with 7 days of data we can actually compute it.

**What:** For each of the 8,189 resolved markets, simulate:
- Open: long BTC perp at window_start, sized at 2× / 5× / 60× notional (parameter sweep)
- Open: sell YES on Polymarket at top-of-ask (or maker, sweep both)
- Close: at slot_end_us (= when the binary resolves)
- PnL = perp PnL (linear in BTC move) + binary PnL ($1 if NO wins, 0 if YES wins, minus the premium received)

Test 3 sizing modes:
- **Naked covered call**: short YES with no perp hedge
- **Delta-1 cover**: long perp at notional matching the binary payout
- **Leveraged cover**: long perp at 60× sized to cover the binary on a 1.5% move

Stratify by sniper q10 trigger — does the magnitude filter make the covered call profitable too?

**Output:** `strategy_lab/reports/COVERED_CALL_BACKTEST.md` with PnL × leverage × sizing. Decision: ship if any cell ≥+15% holdout ROI with DD ≤ -10%.

**Cost:** ~1 day. We have markets, books, klines.

**Risk:** likely fails for the same reason V2 signals failed (small sample → fragile). But it's a different paradigm so worth testing — and we never even ran the basic version.

---

## Tier A — Worth doing once Tier S clears

### A1. Maker-on-both-sides spread provision
**Why:** Currently we pay the spread; what if we collect it instead? Quote both YES bid (slightly above mid) and NO bid (same), let retail hit us, hold to resolution.

**What:** Simulate maker quotes at mid ± 1¢ on both sides. Track:
- Fill probability per side (from book depth)
- PnL per fill (now we're long the asset whose price diverges from mid)
- Adverse selection (do we get hit on the wrong side disproportionately?)

**Cost:** 2-3 days (more involved simulator).
**Risk:** Polymarket fee schedule may make this negative-EV. Verify maker fees first.

### A2. Cross-asset lead-lag exploitation
**Why:** `polymarket_cross_asset_leader.py` showed +3 pp ROI lift when BTC AGREES with the local signal. Lead-lag itself never tested as a primary signal.

**What:** "BTC moved up 0.4% in last 30s, ETH market hasn't priced it yet → buy ETH UP" — does it forward-walk?

**Cost:** 2-3 days.
**Risk:** Lead-lag windows on prediction markets are seconds-to-minutes; our 10-bucket data may be too coarse. Need raw book snapshots.

### A3. Vol-regime-conditional sleeves
**Why:** time_of_day showed +4 pp lift; vol regimes likely show similar. Different signals work in different regimes.

**What:** Compute realized vol per hour. Bucket into low/med/high. Per bucket, find best-performing signal+exit combination on train, validate on holdout.

**Cost:** 1-2 days.
**Risk:** ~7 days × 24 hours / 3 vol buckets = 56 hours per bucket — small samples per bucket per signal.

---

## Tier B — Defer until ≥30 days of data

### B1. Re-run V2 signals stack on bigger window
**Why:** 7 days too thin for distribution-shift testing. With 30 days we can fit on 24, holdout on 6 — and the holdout spans ≥1 vol regime cycle.

**Cost:** Trivial (already coded). Schedule for 2026-05-23.

### B2. Extend collector to 1h / 4h binaries
**Why:** Currently VPS2 only collects 5m + 15m. The original "covered call" idea wanted 4h and 24h tenors. Different microstructure, different retail bias.

**Cost:** 1 day collector edit + 14 days of forward scrape.

### B3. ML end-to-end (LightGBM)
**Why:** With 30 days × 8,200 = ~35k samples, gradient boosting on raw features becomes viable. Avoided in V2 stack because of overfit risk on 7 days.

**Cost:** 2-3 days.
**Risk:** Most likely outcome: GBM finds 30-day-window-specific patterns that don't generalize. Test rigor (purged k-fold + embargo) is critical.

---

## Tier C — Speculative / paradigm shifts

### C1. Other prediction market venues (Kalshi, PredictIt, Manifold)
**Why:** Polymarket's particular inefficiencies may be unique to its USDC/Polygon setup. Different venues = different microstructure.

**Cost:** 3-5 days per venue (collector + data pipeline). Each has its own quirks.

### C2. Funding-rate arbitrage on prediction markets
**Why:** Implicit funding cost on Polymarket binaries (cost of holding YES vs decay of NO) creates a one-sided pressure during bull/bear regimes. Untapped.

**Cost:** Research-heavy, ~1 week to even formalize.

### C3. LLM-driven event-conditional trading
**Why:** Some markets resolve on macro events (CPI, FOMC). LLM reads the news flash → predicts the binary. Polymarket retail is slow on event prints.

**Cost:** Significant. Latency-sensitive. Probably needs co-location with the resolution oracle.

---

## Recommended path

1. **Today–tomorrow:** S1 (sim-vs-live debug). The biggest unknown.
2. **End of week:** S2 (covered-call backtest). Original idea, low cost, never tested.
3. **Next week, depending on S1/S2:**
   - If S1 finds simulator bug → re-run all backtest reports, recompute deployment thresholds.
   - If S2 shows covered-call edge → engineer for VPS3 deploy alongside sniper q10.
   - If both null → A1 (maker spread provision) as the next paradigm.
4. **Continuous:** monitor VPS2/VPS3 collectors, accumulate data toward 30+ day window. B-tier items unlock automatically when calendar passes 2026-05-23.

The current VPS3 fix plan (HEDGE_HOLD + sniper q10 + maker entry + spread filter) is unblocked and ships independent of any of the above. TV agent can proceed without waiting on this research.
