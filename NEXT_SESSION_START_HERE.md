# NEXT SESSION — Start Here

**Date created:** 2026-04-29
**Purpose:** single entry-point pointing to everything you need to resume work without re-reading the entire history.

---

## In one sentence

**V3 portfolio strategy is ready to deploy on VPS3 in shadow mode** — per-asset tuned 3-sleeve sniper (BTC q10 + ETH q5 + SOL q15 multi-horizon), 5m only, maker entry, spread filter, HEDGE_HOLD. Forward-walk holdout +32% ROI. All 10 validation gates passed.

---

## Read in this order

1. **`strategy_lab/reports/session/SESSION_HANDOFF_2026_04_29.md`** — full state of the world, what's locked, what's live, decision tree for next steps.

2. **`strategy_lab/reports/polymarket/01_deployable/TV_STRATEGY_V3_PORTFOLIO_DEPLOY_GUIDE.md`** — TV agent's deploy playbook. ~10-12 hours of work to ship.

3. **`strategy_lab/reports/RESEARCH_DEEP_DIVE_2026_04_29.md`** — full backtest evidence + 10-gate validation results.

4. **`docs/VPS3_FIX_PLAN.md`** — V2 baseline prerequisites. V3 piggybacks on the same Binance backfill.

That's enough to resume.

---

## What's the question this session needs to answer?

Pick one:

**Path A — Ship V3.** Hand `TV_STRATEGY_V3_PORTFOLIO_DEPLOY_GUIDE.md` to the TV agent. Verify VPS3 has the 14-day Binance backfill. Watch for the first sleeve fire after deploy. 7-day observation window.

**Path B — Continue research.** The 7-day data is exhausted. Wait for collector to accumulate 30 days (~2026-05-23) and re-run V3 + V2 stack on the bigger window. Until then, the only meaningful research targets are:
- Maker-then-taker hybrid (the A1 maker-both-sides could work as an active maker overlay; not tested)
- Funding-rate / event-driven signals
- Other venues (Kalshi, Manifold) — multi-day cost each
- LLM-driven event-conditional trading (speculative)

**Path C — Verify shadow trades.** If V1/V2 are still running on VPS2/VPS3, re-pull `trading.events` and recompute hit rates. Compare to backtest predictions. Confirm sim-vs-live reconciliation is still holding.

---

## Critical "don't lose this" facts

1. **The simulator is honest.** Sim-vs-live gap is execution-layer (feed disagreement at small magnitudes, HYBRID bid-exit). Backtest numbers within their stated bounds are trustworthy.

2. **V3's per-asset gates are tuned on 7 days of data.** Bulletproof on this sample but the sample is small. Don't scale beyond paper without 30-day re-validation.

3. **Direction IS the alpha** — G10 stratified permutation showed magnitude alone with random direction LOSES money. The signal works only with correct direction inference.

4. **Hold-to-resolution dominates every exit variant.** TP, SL, trailing, opposite-flip — all hurt. Don't add exit logic to the q-tail sniper.

5. **15m markets dilute the portfolio.** 5m only.

6. **Calibrated probabilities (V2 stack) overfit 7-day data.** Raw magnitude thresholds are more robust to distribution shift. Don't reach for calibration when a quantile gate works.

---

## Repo / VPS state

- **GitHub:** https://github.com/alexbanda08/global
- **Last committed:** `c82e9cb` (A2 cross-asset lead-lag findings)
- **Uncommitted in working tree:** V3 discovery work (per "stop committing" instruction). Run `git status && git add -A && git commit -m "..." && git push` when ready.

VPS access cheatsheet inside `SESSION_HANDOFF_2026_04_29.md` §"VPS access cheat sheet".

---

## If something feels off

Re-check these in order:
1. Is VPS2 collector still running? (`SELECT MAX(timestamp_us) FROM orderbook_snapshots_v2`)
2. Is VPS3 binance-spot-ws collector running? (`SELECT source, MAX(time_period_start_us) FROM binance_klines_v2 GROUP BY source`)
3. Is the TV agent's V2 fix actually deployed on VPS3? (`grep TV_POLY_HEDGE_POLICY /etc/tv/tradingvenue.env`)
4. Does VPS3 have the 14-day Binance backfill landed? Check sleeve fire counts in `trading.events`.

If any of these fail, it'll show up before you start any new research. Address first.

End of pointer doc.
