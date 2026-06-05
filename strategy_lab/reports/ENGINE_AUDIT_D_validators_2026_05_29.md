# ENGINE AUDIT D — Statistical Validator Soundness
**Date:** 2026-05-29  
**Scope:** `cyclops/validate/permutation.py` (G3), `cyclops/validate/bootstrap.py` (G4), `cyclops/validate/walkforward.py` (G2), `cyclops/backtest/runner.py` (G0/G1), `cyclops/backtest/settlement.py`, `cyclops/conventions.py`  
**Focus strategies:** Cyclops X1 (btc-5m sleeve-active composite, n=36), directional `clbasis_rel-btc-5m` (n=64)

---

## 1. Gate Architecture Summary

| Gate | File | Test | Pass Criterion |
|---|---|---|---|
| G0 | runner.py:472-474 | n_fired ≥ 10 | Smoke check |
| G1 | runner.py:477-482 | mean_pnl > 0 | In-sample sign |
| G2 | walkforward.py | Rolling 2d test windows, no refit | ≥75% of windows positive mean PnL |
| G3 | permutation.py | Outcome-shuffle MCPT (N=1000-5000) | p < 0.05 |
| G4 | bootstrap.py | IID resample of per-trade PnL (N=10k-20k) | 95% CI lower > 0 |

**Fee model:** `FEE_RATE = 0.02` in `conventions.py`. Matched to production reality per CLAUDE.md verification (2%-on-profit-only). The "DEPRECATED" banner in `conventions.py` is **misleading** — it warns against this model while CLAUDE.md confirms it is exactly what production uses. Banner should be removed or corrected.

---

## 2. G2 Walk-Forward Audit

### Architecture
`walkforward.py` uses `train_days=5` (burn-in skip) then non-overlapping 2-day test windows. **There is no parameter refit between windows.** The "train" prefix is a misnomer — it is purely an initial burn-in buffer, not a training period. This is correct for a fixed-threshold strategy.

### Verdict logic (line 70)
```python
verdict = (
    "PASS" if n_windows >= 4 and frac_positive >= pass_threshold_frac
    else ("FAIL" if n_windows >= 4 else "insufficient_windows")
)
```
`pass_threshold_frac = 6/8 = 0.75`. The minimum window count to avoid "insufficient_windows" is 4.

### False-positive rate under null
With 50/50 per-window success probability (null), the probability of passing G2:
- With 8 windows (≥6 positive): **P = 14.4%** — not trivially easy to pass
- With minimum 4 windows (≥3 positive): **P = 31.3%** — meaningfully high
- With 7 windows (≥6 positive, ~5/7 threshold): **P = 22.7%**

The 14.4% null pass rate for 8 windows is reasonable but non-negligible. The minimum-4-window fallback is a material weakness: strategies with sparse fires (e.g., n~36 over 21 days) can fall into the 4-window case with a 31% null pass rate.

### Data leakage check
No leakage. The walkforward operates on the output CSV of `runner.py` which records realized PnL at execution time. All signal computations in the runner use strict causal lookups (`asof_strict`, `slug_to_ws_s`). The test windows access different slugs from different dates — no slug overlaps possible given 2d/5m slots.

### Key result (p5_full_depth_p3 = S7, n=238)
- 8 windows, 5/8 positive (62.5%) → **FAIL** (threshold 75%)
- Windows 1-2 (Apr 29 – May 2) are negative, then mostly positive thereafter

### G2 for X1 (n=36)
**G2 was not run for X1.** The master table (`MASTER_TABLE_REAL_FEES.txt`) and `X1_PER_ASSET.txt` only report G1/G3/G4 for X1. With ~1.7 trades/day (Poisson, 2d windows), P(empty window) ≈ 3.4%, so ~7-8 non-empty windows expected — feasible to run but **not done**. This is a gap.

---

## 3. G3 Permutation Test Audit

### Null construction (permutation.py:68-72)
```python
perm = rng.permutation(outcome)
won_null = (direction == perm)
pnl_null = _settle_vector(won_null, shares, stake, fee_rate)
null_means[i] = pnl_null.mean()
```
This shuffles `outcome_truth` across the fired trade set. The direction vector, shares, and stake are preserved. The shuffle correctly destroys the direction↔outcome correlation while keeping the same trade structure (n_trades, stake distribution, shares distribution). The null is well-formed.

### p-value formula (line 74)
```python
p_value = float((null_means >= observed_mean).sum() + 1) / float(n_permutations + 1)
```
This is the Phipson & Smyth (2010) correction ensuring p ≠ 0. Minimum p = 1/(N+1). For N=5000: minimum p = 0.0002. **Correct.**

### Null distribution asymmetry — expected, not a bug
Under the null, shuffled outcomes give ~50% WR. With fee=2%-on-profit, 50% WR at typical entries yields **negative** expected PnL. S7 null_mean = −$1.59 vs observed = +$1.67. This large gap is by design: the shuffle destroys real skill and exposes the natural house edge. The null is harder to beat, not easier.

### Constant-direction risk
If all fired trades have `direction == "Up"` and the historical Up-win rate ≈ observed WR, shuffling outcomes would produce null WR ≈ base rate, collapsing the test power. **In practice this is not an issue:** S7 has 148 Up / 90 Down (mixed); clbasis_rel btc-5m fires both directions based on cl_basis_bps sign (few Down fires due to the ~+13bps systematic offset, but not zero).

### Vectorized _settle_vector vs settle_legacy — correctness
`_settle_vector` (permutation.py:33-40) replicates `settle_legacy` (settlement.py:18-32) vectorized. Both apply `fee_rate` on positive profit only (winning leg), zero fee on losses. **Identical semantics.** No discrepancy.

### Results
- Cyclops X1: G3 p = 0.002 — **PASS**
- S7 full depth: G3 p = 0.011 — **PASS**
- clbasis_rel btc-5m (directional): G3 p = 0.0005 — **PASS**

G3 is **sound** as implemented.

---

## 4. G4 Bootstrap Audit

### Implementation (bootstrap.py:34-38)
```python
idx = rng.integers(0, n, size=(n_boot, n))
samples = pnl[idx]
boot_means = samples.mean(axis=1)
lo = float(np.quantile(boot_means, alpha / 2))
```
Standard IID resample-with-replacement. Fixed denominator n. No block structure.

### IID assumption validity
Lag-1 autocorrelation of per-trade PnL:
- S7 (n=238): lag-1 = **−0.038** (essentially zero)
- clbasis_rel btc-5m (n=64): lag-1 = **−0.148** (slightly negative)

Autocorrelation is negligible-to-slightly-negative. There is **no positive serial correlation** in the fired PnL series that would cause IID bootstrap to understate CI width. The concern about regime clustering is not confirmed in this data.

### Block bootstrap comparison — clbasis_rel btc-5m (n=64, 12 trading days)

Block bootstrap (resample full trading days, 20,000 draws):

| Method | ci_lower | ci_upper | CI width | PASS G4? |
|---|---|---|---|---|
| IID (as implemented) | **+$2.89** | +$9.42 | $6.53 | **YES** |
| Block by day | **+$4.26** | +$10.03 | $5.77 | **YES** |

**The block bootstrap gives a TIGHTER (narrower) CI and a HIGHER ci_lower (+$4.26 vs +$2.89).** This is counterintuitive but explained by the day structure: day-20587 (16 trades) and day-20599 (17 trades) are the two largest days; when those large days are undersampled in block draws, the mean is pulled toward the smaller-sample days which also have high per-trade PnL (+$8-20). Block resampling by day effectively upweights the consistent-positive smaller days. The IID result is **valid and if anything conservative** for clbasis_rel btc-5m.

**Conclusion: clbasis_rel btc-5m G4 result ($2.93 IID ci_lower) is robust to block bootstrap.**

### G4 for Cyclops X1 (n=36, IID ci_lower = +$0.0042)

X1's IID ci_lower is borderline — barely positive. With n=36 over ~21 days (1.7 trades/day), analytical estimate for block bootstrap:

- Theoretical SE ratio (block/IID) = √(n_trades/n_days) = √(36/21) = **1.31×** wider
- Estimated block half-width: $0.24 × 1.31 = $0.31
- Estimated block ci_lower: $0.244 − $0.31 = **−$0.07** → **FAIL**

X1's G4 pass is marginal and likely would **fail** under block bootstrap. The IID ci_lower of +$0.0042 is extremely close to zero (within numerical noise of the boundary). **X1's G4 pass should be treated as fragile.**

---

## 5. Multiple-Comparisons Analysis

### Cyclops X1 within the Cyclops sweep

The master table shows 12 strategies tested on BTC-5m data, all evaluated on the same in-sample period. With alpha=0.05 and N=12 independent tests, expected false G3 passes = 0.60 (low). Bonferroni threshold = 0.05/12 = **0.0042**.

X1 G3 p = 0.002 < 0.0042 → **passes Bonferroni correction** over 12 explicit tests.

However, the Cyclops strategy development followed a sequential search path (S1→S2→S3→S4→S5→S6→S7→X1) with implicit hypothesis exploration. If the effective test count is ≥25, Bonferroni threshold drops to 0.002 and X1 begins to fail. The boundary is: X1 fails Bonferroni when **≥26 implicit tests** were explored.

Given the visible search tree (8 explicit Sn stages + 4 Xn variants), the true count likely lies between 12–30 implicit tests. **X1 G3 p=0.002 is borderline under a conservative multiple-comparisons framing.**

### clbasis_rel btc-5m within the directional sweep

The directional eval tested 66 market×strategy combinations from `dir_eval_plateau.json`, with an underlying parameter sweep of **2,958 cells** total. For the G3 test specifically, it runs at the primary (offset=60) parameter cell, giving one G3 test per strategy×market.

With 66 strategy×market combinations at alpha=0.05: expected false G3 passes = 3.3. clbasis_rel btc-5m G3 p = 0.0005.

Bonferroni threshold over 66 tests = 0.05/66 = **0.00076**. clbasis_rel btc-5m p = 0.0005 < 0.00076 → **passes Bonferroni** over all 66 explicit market×strategy cells.

Even conservatively counting the full 2,958-cell plateau sweep: Bonferroni = 0.05/2958 = 0.000017. G3 runs once per strategy×market (not once per cell), so the relevant count is 66 or perhaps 11 strategies × 6 markets = 66. **clbasis_rel G3 p=0.0005 withstands Bonferroni over the relevant hypothesis space.**

---

## 6. Settlement Function Audit

`settle_legacy` (settlement.py:18-32):
```python
if not won:
    return -float(usd)        # no fee on losses
payout = float(shares) * 1.0
profit = payout - float(usd)
if profit > 0:
    profit -= fee_rate * profit   # 2% on positive profit only
return profit
```
**Correct.** Matches production verified behavior (CLAUDE.md: "LOST trades: pnl_usd = -entry_qty × entry_price exactly; WON trades: pnl_usd = entry_qty × (1 - entry_price) × 0.98 exactly").

Edge case: if `profit ≤ 0` on a win (overbought entry > $1), no fee is applied. This is correct — you don't pay a fee on a loss even if you technically "won" the binary outcome.

---

## 7. Conventions File Warning

`conventions.py` has a DEPRECATED banner (lines 1-15) warning that `FEE_RATE = 0.02` is wrong and the "real" fee is `0.07 × p × (1-p)`. Per CLAUDE.md 2026-05-22 verification, **this banner is incorrect for the BTC/ETH/SOL up-down markets**. Production actually uses 2%-on-profit-only. The banner creates confusion: it marks correct logic as deprecated. It should be removed or replaced with a note explaining that the poly-curve formula applies to other markets but NOT to crypto up-down markets where feeRate is effectively 0.

---

## 8. Verdict: Is the clbasis_rel-btc-5m Result Real?

### Evidence for real signal
1. **G3 p = 0.0005** — survives Bonferroni over 66 strategy×market cells with margin (threshold 0.00076). The direction→outcome link is genuine.
2. **Plateau 97.8%** — 44/45 parameter cells (offset × entry price) are positive EV. Not a single-point fit. Robust to parameter variation.
3. **WR = 85.9%** — far above the break-even rate for 0.688 mean entry (≈68.8% break-even at 2%-on-profit).
4. **G4 IID ci_lower = +$2.93** — strong margin, and block bootstrap improves this to +$4.26.
5. **Block bootstrap PASSES with wider margin than IID.**
6. **Causal construction confirmed** — trailing baseline uses `.shift(1)`, signal derived at offset=60s, outcome from chainlink (not future leak).
7. **Mechanism is real** — fires when Binance diverges from Chainlink RTDS oracle by >3bps above its trailing median; the oracle is the settlement authority, so large divergence predicts direction.

### Risks
1. **Small n = 64 over 33 days** (~2 fires/day). All statistical tests pass but the sample is thin. One month of adverse regime could reverse the result.
2. **Rare fires skew toward specific regime** — 12 of 33 days had fires, heavily clustered (days 20587-20599 = May 13-19 contributed 59/64 trades). If that was a favorable regime, out-of-sample may differ.
3. **Multiple-comparisons risk is low but not zero** — 66 strategy×market combinations tested. At alpha=0.05, 3 false positives expected; clbasis_rel btc-5m is the lone full-battery survivor, and its p-value of 0.0005 is well below the Bonferroni threshold. Risk is real but mitigated.
4. **G2 (directional): 7/7 test windows positive** — strong but the test windows are within-sample.

**Overall: clbasis_rel btc-5m is NOT a multiple-comparisons false positive.** The combination of p=0.0005 G3, block-bootstrap-robust G4 (+$4.26 lower), 97.8% plateau coverage, and mechanistic interpretability makes this the strongest statistical case in the repo. Forward-test is still required to confirm it's not a 33-day regime artifact.

### Cyclops X1 comparison
X1 (n=36) passes Bonferroni on G3 (p=0.002 vs threshold 0.0042) and G4 IID (+$0.0042), but:
- G4 is borderline and likely fails block bootstrap (estimated ci_lower = −$0.07)
- G2 was not run for X1
- n=36 is very small

X1 is not as robustly validated as clbasis_rel btc-5m. Both need forward testing.

---

## 9. Summary of Bugs / Issues Found

| ID | Severity | Location | Issue |
|---|---|---|---|
| D1 | MEDIUM | conventions.py:1-15 | DEPRECATED banner is wrong — FEE_RATE=0.02 IS the correct production fee. Banner should be removed. |
| D2 | MEDIUM | bootstrap.py | IID assumption untested. No block-bootstrap option. For clbasis_rel it is fine (negative autocorr); for other strategies it should be checked. |
| D3 | LOW | walkforward.py | 4-window minimum gives 31% null pass rate. Could tighten to min_windows=6 for better protection. |
| D4 | LOW | cyclops/master_table | G2 not reported for X1/X2/X3/X4 sleeve strategies. Missing gate. |
| D5 | INFO | permutation.py | N=1000 (default CLI) may give noisy p-values near boundary. Results use N=5000, which is adequate. |

---

## 10. Recommendations

1. **Remove/correct the DEPRECATED banner** in `conventions.py` — it marks correct code as wrong.
2. **Run G2 for X1** — ~36 trades is enough for 8 test windows; should be reported before deployment decision.
3. **Add block-bootstrap to bootstrap.py** as a second metric alongside IID, especially for strategies with n<100.
4. **Forward-test clbasis_rel btc-5m** with weekly G3/G4 monitoring. Kill if G3 p ≥ 0.05 or G4 ci_lower ≤ 0 at n≥30 accumulated live fires.
5. **Document the sequential search path** for Cyclops (S1→…→X1) to enable proper multiple-comparisons accounting in future audits.

---

## Appendix: Block Bootstrap Results

### clbasis_rel btc-5m (n=64, 12 trading days, May 7-19 cluster)

```
Day structure: 1,4,16,13,1,4,1,1,1,1,4,17 trades per day
Lag-1 autocorrelation: -0.148

IID bootstrap (N=20,000):
  ci_lower = +$2.89  ci_upper = +$9.42  std = $1.67  PASS

Block bootstrap day-level (N=20,000):
  ci_lower = +$4.26  ci_upper = +$10.03  std = $1.49  PASS

Block CI is TIGHTER and HIGHER than IID. IID is valid and conservative.
```

### Cyclops S7 / p5_full_depth_p3 (n=238, 21 days)

```
Day structure: 1-36 trades per day (median ~12)
Lag-1 autocorrelation: -0.038

IID bootstrap:
  ci_lower = -$1.33  ci_upper = +$4.68  FAIL

Block bootstrap day-level:
  ci_lower = -$0.63  ci_upper = +$3.58  FAIL (still fails, but narrower)

Both agree: S7 alone fails G4.
```
