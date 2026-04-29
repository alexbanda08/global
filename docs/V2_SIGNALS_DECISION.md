# V2 Signals — Decision

**Date:** 2026-04-29

**Decision: KILL.** All 4 new signals (prob_a, prob_b, prob_c, prob_stack) failed forward-walk holdout (chronological 80/20 split). Best holdout hit rate among new signals = 57.3% (prob_a 5m BTC), below the 60% gate. Best holdout PnL = +$28 (prob_a 5m ALL), below the +10% ROI gate.

The existing `sig_ret5m` sniper q20 (62.7% holdout hit, +$36 PnL) remains the only validated cell; q10 is stronger still per `docs/FINDINGS_2026_04_29.md`.

Per the design's decision tree:
> Nothing passes → abandon the V2 stack project; revert to sig_ret5m sniper q10.

## Action

1. **No deploy of prob_a/b/c/stack to VPS3.** TV agent's existing `docs/VPS3_FIX_PLAN.md` (sig_ret5m sniper q10 + HEDGE_HOLD + maker entry + spread<2% filter) continues unchanged.

2. **Code stays in repo.** The 4 builder scripts and engine wirings are clean and re-runnable. When 30+ days of data accumulates, re-run forward-walk; if survives gate then, revisit deploy.

3. **No clean-up needed.** No live infrastructure was provisioned for these signals. Backtest-only experiment.

Full reasoning: `strategy_lab/reports/POLYMARKET_V2_SIGNALS_FINDINGS.md`.
