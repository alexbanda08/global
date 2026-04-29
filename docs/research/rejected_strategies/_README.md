# Rejected Strategies — what didn't work and why

Strategies, signal families, or blend variants that **failed promotion gates**,
**regressed vs the prior champion**, or were structurally invalidated. Each is
kept for institutional memory: knowing what doesn't work is as valuable as
knowing what does, and these failures shaped the V41 → V69 lineage that did.

## Why these are still useful

Three reasons not to delete:
1. **Audit trail.** Every "spectacular result" we don't ship now has a
   recorded reason — protects against re-running the same idea blind.
2. **Negative findings in the literature.** V60 trail-tighten and V61 pairs
   produced clean negative results that map onto the user's published-research
   context (Vector 5 / Vector 7 in [33_NEW_STRATEGY_VECTORS.md](../33_NEW_STRATEGY_VECTORS.md)).
3. **Scaffolding for future iterations.** V68 and V68c didn't promote but
   *informed* the V52* α-sweep that did promote (see V68b in promoted/).

## The graveyard, ordered by category

### Failed strategy designs

- **20_V40_ADAPTIVE_STUDY.md** — V40 regime-adaptive: regime classifier used
  as an entry filter cut trade count too aggressively. Referenced in doc 24
  (in promoted/) as "the V40 mistake" — the lesson became "use regime as
  exit/sizing modifier, NOT as entry filter".

- **25_PRICE_ACTION_SCAN.md** — broad price-action signal scan. 3 promo-grade
  candidates found, but **MDDs too wide** to pass MDD gate.

- **26_PRICE_ACTION_ADAPTIVE.md** — price-action sleeves × adaptive exits.
  Sharpe lifts but **MDD gate FAIL** for all 20 (sleeve, config) combos.

- **31_V61_PAIRS.md** — V61: pairs / spread z-score mean-reversion (BTC/ETH,
  ETH/SOL, SOL/AVAX). **All 3 pairs FAIL the standalone Sharpe gate.** The
  *structural* hypothesis (residuals mean-revert) confirmed; the *alpha*
  hypothesis (revert fast enough to beat 9 bps round-trip + slip) failed.
  Pivot recommendation: Vector 4 = funding-rate signals (executed in V66 in
  this session, also closed without single-sleeve target hit).

### Failed blend / promotion candidates

- **27_V56_BLEND.md** — V56: V52 + Inside-Bar blend test. Blend **FAILS**
  strict promotion gate. Sharpe lifts +0.13 but binding gate (Calmar) regresses.

- **28_V58_TIGHT_BLEND.md** — V58: tightened-exit IBB blend. 2/12 variants
  PASS, "tightTrail_92_08invvol" became a candidate — but failed final battery
  in V59 (next file).

- **29_V59_GATES.md** — V59: 10-gate battery on V58 candidate. **V58 passes
  8/9 gates BUT the binding gate (Calmar lower-CI) regressed vs V52.**
  Recommendation: KEEP V52 deployed. Do NOT promote V58. (Lesson reused
  in V68b — see promoted/38_V68B_GATES_PROMOTED.md, where Calmar lower-CI
  improved by +0.142.)

- **30_V60_TRAIL_SWEEP.md** — V60: trail-tighten sweep on V52's own sleeves.
  Hypothesis: same lever as V58 IBB compresses V52 MDD enough to clear
  Calmar lower-CI. **Result: uniform monotone degradation across all
  sleeves.** The V58 lesson didn't transfer. Closed as a saturation finding.

### Exploration that informed promotions (no_lift / hold)

- **36_V68_WEIGHT_OPTIMIZER.md** — V68: walk-forward sleeve-weight optimizer
  via scipy (QuantMuse Pattern 2). Standalone NO_LIFT vs V52 (ΔSh −0.07).
  But surfaced a directional finding: optimizer wants ~80–85 % V41 core
  weight vs V52's 60 %. That finding fed V68b (in promoted/) where the
  smooth α-curve peaked at 0.75 and gave Sh +0.12 lift.

- **40_V68C_DROP_DIVERSIFIERS.md** — V68c: drop "dead-weight" diversifiers
  (SVD_AVAX, MFI_ETH). All four variants FAIL the strict promotion gate
  (MDD non-worse within 50 bps). Best variant `drop_MFI_ETH` lifts Sharpe
  by +0.04 — within statistical noise on 27 months. **Recommendation: HOLD
  V69 baseline, document drop_MFI_ETH as Stage-2 paper-trade A/B candidate.**

## Recurring failure modes (cross-referencing)

- **Calmar lower-CI gate** is the most-frequently-binding gate in the
  lineage. V52 baseline narrowly fails it (0.987 < 1.0). V58, V59, V60 all
  fail or regress on it. V63 (leveraged) and V69 (V52* α=0.75) fix it.
  Lesson: bootstrap-CI metrics are the binding constraint, not point
  estimates.

- **MDD gate** binds on price-action and pure-sleeve experiments
  (25, 26). Resolved only by multi-sleeve diversification.

- **Statistical noise on small samples**: 27 months is enough to *find*
  a pattern but not enough to confirm Sharpe deltas < 0.10 with confidence
  (V68c finding). Promotion gates that depend on small backtest deltas
  should run live A/B before promotion.
