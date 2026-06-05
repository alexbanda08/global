# ml4t Step 1 — Deflated-Sharpe re-judgment of overnight winners — 2026-06-04

DSR with `effective_trials` = real #searched. A candidate is REAL only if `is_significant=True` AFTER deflation.

## (A) CPU scalp/slug finalists — effective_trials=387,200, variance_trials(est)=0.0054

| rank | model/filter/exit | n | mean $/tr | Sharpe | DSR prob | sig(estV) | sig(4×V cons) |
|--:|---|--:|--:|--:|--:|:--:|:--:|
| 1 | rf/vwap055/e75 | <12 | — | — | — | n/a | n/a |
| 2 | rf/vwap055/e75 | 38 | 5.404 | 0.534 | 0.996 | ✅ | — |
| 3 | rf/broad/e60 | <12 | — | — | — | n/a | n/a |
| 4 | rf/vwap055/e75 | <12 | — | — | — | n/a | n/a |
| 5 | rf/vwap055/e75 | 18 | 3.738 | 0.384 | 0.645 | — | — |
| 6 | et/d3v055/e75 | <12 | — | — | — | n/a | n/a |
| 7 | rf/broad/e60 | <12 | — | — | — | n/a | n/a |
| 8 | et/vwap055/e45 | <12 | — | — | — | n/a | n/a |
| 9 | et/vwap055/e75 | <12 | — | — | — | n/a | n/a |
| 10 | rf/vwap055/e75 | <12 | — | — | — | n/a | n/a |
| 11 | et/vwap055/e75 | 14 | 5.947 | 0.676 | 0.997 | ✅ | — |
| 12 | rf/vwap055/e75 | 27 | 4.604 | 0.516 | 0.978 | ✅ | — |
| 13 | rf/vwap055/e75 | 25 | 4.728 | 0.549 | 0.99 | ✅ | — |
| 14 | rf/vwap055/e75 | <12 | — | — | — | n/a | n/a |
| 15 | et/d3v055/e75 | <12 | — | — | — | n/a | n/a |
| 16 | rf/vwap055/e75 | 27 | 5.832 | 0.738 | 1.0 | ✅ | — |
| 17 | rf/vwap055/e75 | <12 | — | — | — | n/a | n/a |
| 18 | rf/vwap055/e75 | 14 | 7.707 | 0.769 | 1.0 | ✅ | — |
| 19 | rf/vwap055/e75 | <12 | — | — | — | n/a | n/a |
| 20 | rf/vwap055/e75 | <12 | — | — | — | n/a | n/a |

**Survivors: 6/20 at estimated variance_trials; 0/20 at 4× (conservative).**

## (B) Pre-committed EXIT-SCALP (deployed cell, NOT searched → effective_trials=1)

- TIME+45 hold (n=118): mean $5.564/tr, per-trade Sharpe 0.635, DSR prob 1.0, significant=✅
- TIME+60 hold (n=118): mean $5.56/tr, per-trade Sharpe 0.599, DSR prob 1.0, significant=✅

## Read
- (A) If 0/20 finalists survive DSR at 387k trials → the scalp/slug SELECTION was multiple-testing noise (expected — confirms the overnight caution). The selector edge is not real.
- (B) The exit-scalp is pre-registered (not searched) so DSR at trials=1 is the honest test of the LIVE edge. If significant → the edge survives formal DSR (strong). This is the thing to push to the different-window OOS.
- per-trade Sharpe here is on $25 single-fire returns (high variance); DSR `probability` is the deflated PSR.
---

## VERDICT (ml4t DSR, 2026-06-04)

1. **Scalp/slug SELECTORS (387k search) = multiple-testing noise.** 6/20 "survive" DSR only at the *lenient*
   variance_trials=0.0054 (estimated from the kept top-tail, which understates the true cross-trial Sharpe
   spread). At a realistic **4× variance → 0/20 survive.** Since the full 387k-trial population (incl. all the
   discarded candidates) has a far larger Sharpe spread than the top tail, the honest deflation is the
   conservative one: **none of the scalp selectors are real.** This formally confirms the overnight caution.
   → **Do not pursue model-based scalp-fire selection.**
2. **The pre-committed EXIT-SCALP is REAL.** Pre-registered (not searched) → DSR needs no trial deflation;
   it passes cleanly: TIME+45 Sharpe 0.635, **DSR prob 1.0, is_significant=True** (same for +60). This is the
   one edge that survives formal Deflated Sharpe.
3. **Net:** the edge is the **exit-scalp execution**, not selection. Next: (a) CPCV-validate the exit-scalp with
   `engineer` meta-labeling to sharpen its entry filter; (b) push it to the **different-window OOS** (the only
   deflation-proof test); (c) keep accruing live shadow fires toward the ≥200 gate.

Caveat: per-trade Sharpe is on $25 single-fire returns (high variance); DSR `probability` is the deflated PSR.
variance_trials was estimated from the top_checkpoint tail — the 4×-conservative column is the trustworthy read.
