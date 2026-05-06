# Phase 7 Validation — Critical Findings

**Date:** 2026-05-04
**Status:** Two validation runs — partial 04-22→04-29 data + FULL 12.5d window. **V5 spec FAILS rigorous OOS validation across all 3 assets.**
**Source:** `strategy_lab/v4_signals/phase7_validation.py`.

---

## TL;DR — V5 LATE-ENTRY does NOT have edge

Phase 7's IC findings (IC=0.23-0.43 across assets, **p<0.0001 permutation test**) are statistically REAL — but the IC measures rank correlation, not profit-after-friction. After realistic backtest with **2% taker fees + actual entry prices at t=240s**, the V5 BUY rule loses money on every asset on the FULL data holdout.

### Validation run #1 — partial data (04-22 → 04-29 only)

| Asset | n_holdout | Hit% | PnL ($1 stake) | MaxDD | IC p | Verdict |
|---|---:|---:|---:|---:|---:|---|
| BTC | 146 | 53.4% | -$13.02 | -$22.04 | 0.0000 | ❌ unprofitable |
| ETH | 94 | 55.3% | -$14.04 | -$14.86 | 0.0000 | ❌ unprofitable |
| SOL | 128 | 68.0% | +$10.85 | -$3.22 | 0.0000 | ✓ profitable |

### Validation run #2 — FULL 12.5d data (04-22 → 05-04, 3× more samples)

| Asset | n_holdout | Hit% | PnL | MaxDD | IC p | Verdict |
|---|---:|---:|---:|---:|---:|---|
| BTC | 292 | **45.9%** | **-$43.07** | -$52.41 | 0.0000 | ❌ **worse on full data** |
| ETH | 239 | 55.6% | -$10.94 | -$19.64 | 0.0000 | ❌ unprofitable |
| SOL | 278 | 65.8% | **-$13.00** | -$13.76 | 0.0000 | ❌ **flipped negative on full data** |

**SOL flipped from +$10.85 (partial) to -$13.00 (full).** The earlier "SOL works" result was a 4-day window artifact.

---

## Root cause — late entry has NO real alpha

Phase 7 IC measured "feature → outcome" rank correlation. **It did NOT measure "feature → outcome above what price already implies."** By t=240s into a 5m market, the orderbook has already PRICED IN most of the convergence. The CLOB imbalance feature is correlated with outcome because it's correlated with the current price level, which is already pricing the outcome.

**Math:** at t=240s, average winning-side ask price ≈ $0.75-0.85 (book has converged toward the resolution). Buying that side: gain on win = (1/$0.80) − $1.02 = +$0.23. Loss = −$1.02. To break even at $0.80 entry, need hit rate > 81.6%. Observed hit rates: 46-66%. **Mechanically unprofitable.**

The IC is real, but it's signal we cannot trade because the market already prices it in.

---

## 1. Validation gates applied

Per `phase7_validation.py`:

1. **Chronological 80/20 split** — train on first 80% of markets, OOS on last 20%. Q20/Q80 thresholds fit on TRAIN ONLY, applied to holdout.
2. **Permutation test** (1,000 shuffles): IC p-value across all 3 assets = **0.0000** (signal is statistically significant).
3. **Bootstrap CI** (2,000 resamples) on holdout PnL + hit rate.
4. **Realistic fills**: entry price = top-of-book ask at t=240s (`bucket_24` of orderbook). 2% taker fee on cost.
5. **Equity-curve stats** (using existing `polymarket_stats.equity_curve_stats`): Sharpe, Sortino, Calmar, MaxDD, longest DD run.
6. **Stop-loss simulation**: 50% / 70% / 90% per-trade stops vs no-stop.
7. **Tail risk**: worst 5% of trades — concentration of loss.
8. **Per-hour PnL** breakdown (UTC).

Reused infrastructure: `polymarket_stats.equity_curve_stats`, chronological-split pattern from `polymarket_forward_walk_v2.py`, bootstrap CI pattern.

---

## 2. Train → Holdout degradation

Hit-rate degradation reveals overfit:

| Asset | Train hit% (n) | Holdout hit% (n) | Degradation |
|---|---:|---:|---:|
| BTC | ~70% (n=600 fired) | 53.4% (146) | **-17pp** ❌ |
| ETH | ~67% (n=580 fired) | 55.3% (94) | **-13pp** ❌ |
| SOL | ~79% (n=593 fired) | 68.0% (128) | **-11pp** ⚠ marginal |

The Q20/Q80 thresholds fit on the first 80% of markets don't generalize cleanly to the last 20%. SOL is most robust (smallest degradation).

---

## 3. Stop-loss simulation — **critical for BTC**

50%-of-stake stop-loss applied to each trade (rough proxy — true stop requires intra-window price path).

| Asset | no_stop | stop_50% | stop_70% | stop_90% |
|---|---:|---:|---:|---:|
| **BTC** | -$13.02 | **+$5.70** ⭐ | -$1.50 | -$8.70 |
| ETH | -$14.04 | -$1.04 | -$6.04 | -$11.04 |
| **SOL** | +$10.85 | **+$16.57** ⭐ | +$14.37 | +$12.17 |

**Conclusion:**
- **BTC has heavy negative tail** — 50% stop turns -$13 → +$6 net positive. **Stop-loss is essential for BTC V5**.
- **ETH still unprofitable** with stops — 50% stop reduces loss but doesn't break-even. **Drop ETH from V5 or rework feature.**
- **SOL benefits from stop too** — already profitable, stop adds ~$6 alpha. **Recommend ship SOL V5 with 50% stop.**

---

## 4. Tail-risk concentration

Worst 5% of trades drive 30-55% of total absolute PnL — extreme concentration.

| Asset | Worst trades | $ contribution | % of total | Hours (UTC) | Direction split |
|---|---:|---:|---:|---|---|
| BTC | 7 / 146 | -$7.14 (avg -$1.02) | +54.9% (of NET LOSS) | 7, 9, 10, 13 | 5 DOWN / 2 UP |
| ETH | 4 / 94 | -$4.08 (avg -$1.02) | +29.1% (of net loss) | 6, 7, 8 | 2 DOWN / 2 UP |
| SOL | 6 / 128 | -$6.12 (avg -$1.02) | -56.4% (drag on profit) | 5, 7, 9, 13, 21 | 3 DOWN / 3 UP |

Pattern across assets: **morning hours (6-13 UTC) and DOWN trades are over-represented in worst tail.** Suggests: (a) regime gating around US market open hours, (b) DOWN-side signal noisier than UP-side.

---

## 5. Per-hour highlights (holdout)

**SOL** has best hours at 8 UTC (+$1.53), 13 (+$3.18), 17 (+$7.67) — concentrated in mid-day UTC.
**BTC** has worst hours at 7 (-$2.43), 13 (-$2.43), 22 (-$1.36) — same windows that drove tail risk.
**ETH** scattered, no clear time-of-day edge.

This suggests adding an **HOUR-OF-DAY FILTER** to V5 entry: e.g., skip BTC trades in hours {7, 13} regardless of feature value. Need 30-day OOS to confirm.

---

## 6. Revised V5 spec verdict — KILL the original V5 spec

After full-window validation:

- **BTC V5: REJECTED.** -$43 over 292 trades. Not even stop-loss saves it (best stop result +$3.73, marginal). Hit rate 45.9% < 50%.
- **ETH V5: REJECTED.** -$10.94 base, +$15.58 with 50% stop — but stop-driven profit isn't real alpha, it's just clamping a structurally negative-EV strategy. The "+$15.58 with stop" result is fragile and expected to disappear in OOS.
- **SOL V5: REJECTED.** Flipped from +$10.85 (partial) to -$13.00 (full window). The original positive result was a sampling artifact of the 4-day window.

**Do NOT ship V5 LATE-ENTRY as designed.** The original V5_LATE_ENTRY_SPEC_2026_05_04.md should be marked superseded with reference to this findings doc.

### Stop-loss results (FULL data — confirms BTC & ETH structural negative skew)

| Asset | no_stop | stop_50% | stop_70% | stop_90% |
|---|---:|---:|---:|---:|
| BTC | -$43.07 | +$3.73 | -$14.27 | -$32.27 |
| ETH | -$10.94 | +$15.58 | +$5.38 | -$4.82 |
| SOL | -$13.00 | +$0.52 | -$4.68 | -$9.88 |

The pattern of "stop ALWAYS helps" indicates **negative skew** in trade outcomes — losses cluster at -$1.02 (full stake) which is structural to the BUY-AND-HOLD-TO-RESOLUTION mechanic. **Stops aren't alpha — they're risk management on a strategy without edge.**

### Tail risk (FULL data)

Worst 5% of holdout trades:
- BTC: 14/292 trades, sum = +33.2% of total (negative) PnL
- ETH: 11/239, sum = +102.5% of total — WORST 5% IS THE ENTIRE LOSS
- SOL: 13/278, sum = +102.0% of total — same pattern

**Translation:** if you removed the worst 5% of trades, ETH and SOL would break even. But you can't predict in advance which trades will be the worst. Stop-loss is a coarse proxy.

### What this means

The Phase 7 finding "IC=+0.43 SOL t=240s" was **real but not tradable**. CLOB imbalance momentum at t=240s is correlated with outcome BECAUSE it's correlated with current price, which has already priced in the outcome. To find tradable alpha, we need a feature that:
- Is observable at t (e.g., 240s)
- Predicts outcome better than entry price alone (residual IC after controlling for price)
- Has effect size large enough to overcome 2% taker fee + entry price markup

---

## 7. What this changes about original V5 spec

The original V5_LATE_ENTRY_SPEC_2026_05_04.md needs amendments:

1. **Section 2 BTC** — add mandatory 50% stop + hour blocklist {7, 13}
2. **Section 2 ETH** — replace with "DEFER until full-window backtest passes". Currently fails OOS.
3. **Section 2 SOL** — confirm + add 50% stop (marginal additional gain but reduces variance)
4. **Section 5 (implementation)** — add stop-loss execution path: cancel + market-sell at -50%
5. **Section 6 (backtest validation)** — add: "OOS chronological 80/20 split shows realistic-fee PnL is marginal for BTC, negative for ETH, positive only for SOL"

---

## 8. Path forward — search for residual-IC signals

To find tradable alpha at late-entry, signals must be **independent of entry price**:

1. **Residual IC analysis** — regress feature on entry_yes_ask, then test whether RESIDUAL is correlated with outcome. Only the residual is alpha.
2. **Trade flow imbalance from `trades_v2`** — actual fills (not just orderbook posting) reveal informed flow. We have 16.8M Polymarket trades on VPS2; **Phase 9** is the next swing.
3. **Cross-token or cross-horizon features** — e.g., compare last-30s slope to last-180s slope. Acceleration may add value beyond slope itself.
4. **Liquidity-conditioned signals** — when book is THIN (low depth), CLOB imbalance is more informative because each order moves price more.
5. **Maker entry instead of taker** — Polymarket charges 0% maker fee. Entering as a passive bid might capture better entry price + cleaner edge.
6. **EARLIER entry (t=60s, t=120s)** — IC is weaker but entry price is closer to fair $0.50. After-fee math may improve.

### Recommended next experiment: Phase 8 — residual IC + Phase 9 trade flow

```python
# Pseudocode for residual-IC test
# For each asset, regress feature on entry_price, get residual:
residual = feature - linear_fit(entry_price)
# Test if residual still predicts outcome:
ic_residual = spearman_correlation(residual, outcome)
# If ic_residual << ic_raw → no tradable alpha
# If ic_residual ≈ ic_raw → real alpha independent of price

# Phase 9: pull trades_v2, compute 60s-rolling buy/sell volume imbalance
# Test if it has nonzero residual IC after controlling for entry price
```

---

## 9. Files

- This findings doc: `strategy_lab/reports/PHASE7_VALIDATION_FINDINGS_2026_05_04.md`
- Validation harness: `strategy_lab/v4_signals/phase7_validation.py`
- Full validation report: `strategy_lab/reports/PHASE7_VALIDATION_2026_05_04.md`
- Original V5 spec (to be revised): `strategy_lab/reports/V5_LATE_ENTRY_SPEC_2026_05_04.md`
- Phase 7 IC findings: `strategy_lab/reports/PHASE7_CLOB_MOMENTUM_2026_05_04.md`
- Stats helpers: `strategy_lab/polymarket_stats.py`, `strategy_lab/book_walk.py`
