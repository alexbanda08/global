# Slug-Selection Experiments — Results (2026-06-05)

Tested the deep-research leads (`SLUG_SELECTION_RESEARCH_2026_06_05.md`). Headline: **time-of-day is the one
robust, multiply-confirmed slug/timing selector**; oracle-determinism is real-but-underpowered; everything
else (liquidity, cross-token price-sum, reversal-imbalance) is null/dead causally. All on the confirmed gated
exit-scalp universe (BTC+ETH, entry_vwap<0.55, pnl60), no L25 lookahead.

## ✅ TIME-OF-DAY — the win (walk-forward stable + F2-confirmed)
Scalp edge is strongly hour-dependent. Strong: 22–02 + 9–10 UTC. Dead/weak: 12, 17, 18–21 UTC.
- **Light gate `exclude {12,17}`: 94% coverage, $/tr +2.95→+3.14, SAME total PnL (+2306), walk-forward stable**
  (folds +2.84/+3.41/+3.25). → drop 2 dead hours, keep ~22h/day, free Sharpe with no volume loss.
- Stronger `exclude {2,12,16,17,18}`: 79% coverage, +$3.55/tr (more Sharpe, small volume cost).
- `22–02 only`: +$4.61/tr but 17% coverage — too little volume (don't use as the gate; it's the peak, not the strategy).
- 22–02 × δ≥5: +$7.88/tr (n=19, CI [4.89,10.93]).
- **Recommendation:** gate live scalp sleeves with `exclude {12,17}` (min) or `{2,12,16,17,18}` (more Sharpe).
  Deploy as new gated sleeves alongside the ungated to measure live lift.

## ◐ EXP6 — F2 slug-selector PARTIALLY CRACKED = time-of-day
F2's 102 picked slugs (6.5% of its window's universe) over-select 22–02 (32.4% vs 17% baseline, ~2×) and
**avoid 18–21 UTC entirely** (zero fires). Hour over-selection ratios: h23 2.55×, h0 2.0×, h3 1.75×, h1 1.73×,
h9–10 1.5×. This is the SAME window our independent scalp edge concentrates in → triple confirmation
(our walk-forward + F2 behavior + literature). **A major component of F2's selection is time-of-day.** The
remaining within-hour slug pick is still unexplained (needs Polymarket CLOB WS event tape, not in canonical) —
so TOD is necessary-not-sufficient, but it's the reproducible part.

## ⭐ EXP1 — Oracle-determinism (separate report `ORACLE_SETTLEMENT_SELECTOR_2026_06_05.md`)
Real, survives fills directionally (win 92–100% at vwap~0.85), but underpowered (3–12% fill, 9–42 fills/43d,
CIs include 0). → shadow deploy to accrue power.

## ❌ Dead / null this batch
- **EXP3 Liquidity-inversion:** scalp $/tr flat-to-slightly-higher across liquidity quartiles (no Tetlock
  inversion — our edge is execution, not value-correction). Not a filter.
- **EXP2 Cross-token price-sum (causal):** the eye-popping +$7.57 in Q4_wide was **lookahead** (used opp_ask at
  +30s). At-fire: corr(dev, pnl60) = −0.03; tight books +$4.06 vs wide +$1.48 (DECREASING). Wide cross-token
  deviation HURTS — re-confirms the existing spread filter (trade tight books), not a new edge.
- **EXP4 Reversal-state imbalance:** buyimb quartiles all +$2.5–4.1, no pattern (corr ~0). Null.

## Takeaways
1. **Deploy the time-of-day gate** on the scalp (exclude {12,17}±{2,16,18}). Cheapest, most robust, F2-confirmed.
2. **Deploy the oracle-determinism shadow sleeve** to settle its power question.
3. Microstructure features (imbalance, cross-token, liquidity) do NOT sharpen the scalp causally — consistent
   with §D-1 (delta_bps is the sufficient statistic). Stop testing microstructure selectors.
4. F2's full selector still needs the CLOB WS event tape; TOD explains a major chunk.

## Files
- `slug_liq_tod_2026_06_05.py` (EXP3+5) · `slug_sel_2_4_tgate_2026_06_05.py` (time-gate+EXP2-cache+EXP4) ·
  `exp2_xtoken_causal_2026_06_05.py` (EXP2 causal) · EXP6 inline (F2 hour analysis).
- Research: `SLUG_SELECTION_RESEARCH_2026_06_05.md` · Oracle: `ORACLE_SETTLEMENT_SELECTOR_2026_06_05.md`.
