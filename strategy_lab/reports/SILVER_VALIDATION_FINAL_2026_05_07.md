# SILVER Validation — Final Synthesis (3 scopes)

**Date:** 2026-05-07
**Strategy:** confluence SILVER tier, struct+flow sign-aligned (struct≥0.30, flow≥0.40)

Three scopes were validated against the same 5-gate battery (G1 permutation 10k, G2 walk-forward 5d/2d, G3 bootstrap 10k, G4 logistic regression, G5 L25 realfill).

---

## Headline comparison

| Scope | n_uni | n_exec | Hit% | Mean $ | Total $ | G2 OOS pos windows | G3 bootstrap 95% CI | G4 reg p (struct, flow) |
|---|---:|---:|---:|---:|---:|---:|---|---:|
| **SOL only** | 13 | 8 | **100.0%** | **+$4.08** | **+$32.62** | **3/3** | **[+$2.18, +$5.90]** | n<10 |
| SOL + ETH_15m | 25 | 18 | 83.3% | +$0.13 | +$2.33 | 2/5 | [-$5.54, +$4.94] | 0.20, 0.19 |
| Full universe | 105 | 85 | 76.5% | **-$2.75** | **-$234.11** | 1/5 | **[-$5.50, -$0.20]** | 0.87, 0.69 |

**Interpretation:**
- Adding ETH_15m: alpha collapses to neutral (CI straddles zero).
- Adding BTC + ETH_5m: alpha goes **decisively negative** (CI excludes zero on the negative side, p(loss)=98.3%).
- The "SILVER tier" labels are systematically WRONG on BTC and ETH — they anti-select good momo trades on those assets.
- **Only SOL holds up under signed alignment.**

---

## Per-asset breakdown (full-universe run, n=85)

| Asset | n | Hit% | Mean $/trade | Total $ |
|---|---:|---:|---:|---:|
| BTC | 55 | 74.5% | **-$3.43** | -$188.87 |
| ETH | 22 | 72.7% | **-$3.54** | -$77.86 |
| **SOL** | **8** | **100.0%** | **+$4.08** | **+$32.62** |

---

## Gate verdicts (SOL-only — the only viable scope)

| Gate | Test | Pass? | Detail |
|---|---|---|---|
| G1 | Permutation p<0.05 | FAIL (mech) | p=NaN — all 8 trades won, null distribution collapses |
| G2 | Walk-forward 5d/2d, ≥half windows positive | **PASS** | 3/3 OOS windows positive, OOS mean +$1.84 |
| G3 | Bootstrap 95% CI excludes zero | **PASS** | [+$2.18, +$5.90] |
| G4 | Regression p<0.10 on struct or flow | FAIL (mech) | n=8 too small + zero variance in y (all wins) |
| G5 | Realfill execution viable | INFO | n=8 SOL, hit 100%, +$4.08, 4 spread skips (33% live drop) |

**Overall SOL-only:** UNCONFIRMED — sample underpowered, but no evidence against the signal.

---

## Why SILVER works on SOL but not BTC/ETH

Hypothesis (unverified, worth testing):

1. **BTC/ETH have established momo edge.** The full SOL momo baseline LOSES (-$0.40/trade, hit 87.3%) → momo alpha is negative on SOL. Filtering with struct+flow agreement on a NEGATIVE-edge cell catches the few trades that go right.
2. **BTC/ETH momo is positive-edge** (~+$0.30 to +$0.97/trade). Filtering with struct+flow alignment ANTI-SELECTS the good trades — possibly because struct+flow agreement correlates with continuation conditions, where momo's contrarian/mean-revert bias is exactly wrong.

This is the SAME pattern the original anti-edge finding flagged: SOL behaves opposite to BTC/ETH on momo signals. SILVER tier is exploiting that.

---

## Period and density (SOL only)

- Universe: 2026-04-22 → 2026-05-06 (13.9 calendar days)
- First SILVER trade: 2026-04-23 15:15 UTC
- Last SILVER trade: 2026-05-05 00:30 UTC
- 5 of 14 days had any trades (concentrated; Apr 23 had 4 of 8)
- 0.57 trades/calendar day → ~17 picks/30d → ~11 fills/30d (after 38.5% live-drop)

## Monthly expectancy (SOL-only, bootstrap)

| Metric | Value |
|---|---:|
| Bootstrap mean monthly $ (10k draws) | +$69.16 |
| 95% CI total $ | [+$46.87, +$90.74] |
| 95% CI mean $/trade | [+$2.76, +$5.34] |
| P(monthly < 0) | 0.00% |

These numbers are **mechanically positive** because all 8 observations were wins. They will regress on more data.

**Breakeven hit rate: 86.0%** (mean win $4.08 × H = (1-H) × $25 → H = 25/29.08).

Baseline momo SOL hits 87.3% — only 1.3pp above breakeven. SILVER's 100% in the observed window is a 14pp cushion that may or may not survive.

---

## Final recommendation

1. **Restrict TV agent spec to SOL_5m + SOL_15m only.** Drop ETH_15m from production scope (validation data shows it dilutes alpha).

2. **Paper-deploy as the only responsible next step.** Live capital risks too much given:
   - Bootstrap CI is mechanically clean but driven entirely by n=8
   - G1 + G4 mechanically can't fail-stop until we observe a loss
   - 86% breakeven leaves ~1pp cushion under regression to baseline

3. **Validation gates for paper → live promotion:**
   - n ≥ 80 paper trades (~7-10 weeks at observed density)
   - At least 5 observed losses (so G1 perm test is informative)
   - Walk-forward ≥ 6 of last 8 windows positive
   - Bootstrap 95% CI lower bound > $+1/trade
   - Live hit rate ≥ 88% (1pp above breakeven for safety margin)

4. **Capital ramp on live:**
   - Week 1-2 live: 0.5% × bankroll per trade
   - Week 3-4: 1.0% if hit ≥ 90% so far
   - Week 5+: 1.5% if all metrics hold

5. **DO NOT live-deploy `confluence_silver_v1` for any asset other than SOL** until separate validation passes for that asset.

---

## Files

- Per-trade CSV (SOL only): `strategy_lab/results/meta_classifier/silver_per_trade.csv`
- Validation JSON (last run = full universe): `strategy_lab/results/meta_classifier/silver_validation.json`
- Latest validation report (overwritten 3x): `strategy_lab/reports/SILVER_VALIDATION_2026_05_07.md`
- This synthesis: `strategy_lab/reports/SILVER_VALIDATION_FINAL_2026_05_07.md`
- Comprehensive overview: `strategy_lab/reports/SILVER_OVERVIEW_2026_05_07.md`
- TV agent spec (needs SOL-only update): `strategy_lab/reports/TV_AGENT_SPEC_CONFLUENCE_SILVER_V1.md`

## Reproduce

```bash
cd "/c/Users/alexandre bandarra/Desktop/global"
py -X utf8 -m strategy_lab.confluence.validate_silver_alpha               # SOL only
py -X utf8 -m strategy_lab.confluence.validate_silver_alpha --include-eth-15m
py -X utf8 -m strategy_lab.confluence.validate_silver_alpha --include-all
py -X utf8 -m strategy_lab.confluence.silver_overview
```
