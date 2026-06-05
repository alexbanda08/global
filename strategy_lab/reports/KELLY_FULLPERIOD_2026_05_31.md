# Kelly Full-Period Backtest — ALL_5m_phase1_kelly
**Date:** 2026-06-01  
**Panel:** `data/v4/canonical/_results/master_5m_panel.parquet` (40,210 rows, May 1–21, 20.8 days)  
**Script:** `strategy_lab/_opt_2026_05_30/18_kelly_fullperiod_backtest.py`

---

## ⚠ CRITICAL PERIOD LIMITATION

Panel covers **May 1–21 only** (not Apr 24). Week 21 (May 18–21) dominates: +$13,840 of $18,879 total. The 4× Kelly tier (n=152, fe>3000, vwap_median=0.48) drives nearly all returns. These are near-resolved high-conviction slots. **All conclusions are contingent on this 21-day window.**

---

## 1. Summary Table

| Config | n | WR% | $/tr | Total $ | MDD $ | Calmar | Period |
|---|---|---|---|---|---|---|---|
| BASE full-Kelly | 3,508 | 84.4 | +5.38 | +$18,879 | −$844 | 391.6 | May 1–21 |
| BASE half-Kelly | 3,508 | 84.4 | +2.69 | +$9,440 | −$422 | 391.6 | May 1–21 |
| EU gate full-Kelly | 1,104 | 84.2 | +3.52 | +$3,883 | −$626 | 108.6 | May 1–21 |
| EU gate half-Kelly | 1,104 | 84.2 | +1.76 | +$1,941 | −$313 | 108.6 | May 1–21 |
| Flat-$5 (legacy 2%) counterfactual | 3,508 | — | +0.33 | +$1,167 | — | — | May 1–21 |

**Kelly_mult mean:** 1.37 (mostly 1× fires, but 4× tail dominates PnL).

---

## 2. Weekly Breakdown

| Week | Period | n | WR% | $/tr | Total $ | EU n | EU WR% | EU $/tr | EU Total $ |
|---|---|---|---|---|---|---|---|---|---|
| 18 | May 1–3 | 347 | 82.4 | +0.23 | +$80 | 92 | 85.9 | +3.33 | +$306 |
| 19 | May 4–10 | 1,120 | 83.1 | +1.70 | +$1,902 | 342 | 82.2 | −0.88 | −$301 |
| 20 | May 11–17 | 1,158 | 84.7 | +2.64 | +$3,058 | 376 | 83.8 | +1.42 | +$534 |
| 21 | May 18–21 | 883 | 86.2 | +15.67 | +$13,840 | 294 | 86.7 | +11.37 | +$3,344 |

**Week 21 dominates.** The 4× Kelly tail fires heavily in this period (extreme fair_edge_bp cluster). The EU gate was −$301 in week 19, undermining the keep_EU thesis on the full period.

---

## 3. Kelly Tier Breakdown

| Mult | n | WR% | $/tr | Total $ | MDD $ | Stake | fe_mean | vwap_med |
|---|---|---|---|---|---|---|---|---|
| 1× | 2,690 | 87.9 | +0.18 | +$472 | −$779 | $25 | −356 bp | 0.93 |
| 2× | 497 | 76.3 | +1.81 | +$898 | −$801 | $50 | 1,414 bp | 0.78 |
| 3× | 169 | 69.2 | +14.55 | +$2,460 | −$450 | $75 | 2,444 bp | 0.66 |
| 4× | 152 | 64.5 | +99.01 | +$15,050 | −$412 | $100 | 4,266 bp | 0.48 |

**Key insight:** 1× tier (77% of fires) nets only +$472 flat. The 4× tail (4.3% of fires) generates +$15,050 = **80% of total PnL**. Very low vwap_median (0.48) at 4×: these are deep-conviction pre-resolution slots. At flat-$5, total collapses to +$1,167 (+$0.33/tr), confirming the edge is purely in Kelly sizing of the high-fe tail.

---

## 4. ½-Kelly Analysis

| Config | Total $ | MDD $ | Calmar | vs Full-Kelly |
|---|---|---|---|---|
| Full-Kelly | +$18,879 | −$844 | 391.6 | — |
| Half-Kelly | +$9,440 | −$422 | 391.6 | 50% return, 50% MDD, same Calmar |

Half-Kelly gives exactly proportional risk/return (same Calmar = 391.6). Recommended for live sizing given the leverage concentration in the 4× tail.

---

## 5. New Gate Scan (both-half holdout, base_per_tr = +$5.38)

Only gates where **both H1 and H2 per_tr > +$5.38** count as PASS.

| Gate | n | Retain% | WR% | $/tr | Total $ | MDD $ | Calmar | H1 $/tr | H2 $/tr | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| **fair_edge_bp > 2000** | 321 | 9.2 | 67.0 | +54.55 | +$17,510 | −$650 | 471.9 | +$28.39 | +$80.54 | **PASS** |
| **fair_edge_bp > 1500** | 496 | 14.1 | 68.6 | +35.91 | +$17,812 | −$669 | 466.6 | +$19.74 | +$52.09 | **PASS** |
| **fair_edge_bp > 1000** | 818 | 23.3 | 72.6 | +22.50 | +$18,408 | −$611 | 527.7 | +$10.83 | +$34.17 | **PASS** |
| EU gate (keep 6–13h) | 1,104 | 31.5 | 84.2 | +3.52 | +$3,883 | −$626 | 108.6 | −$0.08 | +$6.94 | **FAIL** |
| m5v_pass | 1,206 | 34.4 | 84.0 | +9.39 | +$11,320 | −$616 | 321.7 | +1.69 | +$17.08 | FAIL |
| imb5_dir_agree | 1,771 | 50.5 | 84.0 | +8.69 | +$15,384 | −$592 | 455.3 | +1.72 | +$15.64 | FAIL |
| rvol_30_300 > 2.0 | 1,160 | 33.1 | 88.4 | +7.45 | +$8,637 | −$497 | 304.6 | +0.26 | +$14.64 | FAIL |
| rsi_14 mid-band (30–70) | 2,430 | 69.3 | 85.1 | +6.63 | +$16,102 | −$552 | 511.2 | +2.17 | +$11.08 | FAIL |
| m1v AND m5v pass | 506 | 14.4 | 86.6 | +6.17 | +$3,123 | −$261 | 209.3 | +4.78 | +$7.56 | FAIL |
| macd_agree | 3,044 | 86.8 | 85.4 | +5.89 | +$17,931 | −$833 | 377.1 | +1.77 | +$10.02 | FAIL |
| cvd_agree_60s | 2,846 | 81.1 | 86.7 | +5.21 | +$14,841 | −$637 | 408.1 | +2.56 | +$7.87 | FAIL |
| EU + fe > 1000 | 266 | 7.6 | 74.1 | +15.66 | +$4,165 | −$451 | 161.7 | +5.25 | +$26.07 | FAIL (H1 barely) |
| f7_pass | 2,723 | 77.6 | 84.9 | +2.41 | +$6,568 | −$853 | 134.9 | +1.30 | +$3.52 | FAIL |
| cross_full_agree | 2,982 | 85.0 | 85.5 | +2.77 | +$8,266 | −$873 | 165.9 | +2.02 | +$3.52 | FAIL |

**Only `fair_edge_bp` threshold gates PASS both halves.** Higher fe threshold = better $/tr AND better Calmar (527.7 at fe>1000 vs 391.6 base). The best single gate is **fe > 1000** (n=818, +$22.50/tr, Calmar=527.7, H1 +$10.83, H2 +$34.17).

---

## 6. EU Gate Re-examination

The `keep_EU` gate (fire hour 6–13 UTC) was the top gate in the live May 26–30 window (+$2,272 vs +$249 base on 256/858 live fires). On the full May 1–21 panel:

| Split | EU n | EU $/tr | EU Total |
|---|---|---|---|
| H1 (May 1–12 roughly) | 538 | **−$0.08** | −$43 |
| H2 (May 13–21 roughly) | 566 | **+$6.94** | +$3,928 |
| Full period | 1,104 | +$3.52 | +$3,883 |

**EU gate fails both-half holdout on the full period.** The H1 result is essentially flat (−$0.08/tr). The +$2,272 live result and H2 full-period result are both driven by week 21 concentration. **EU is not a robust gate on the full dataset — it is correlated with the May 18–21 spike, not an independent time-of-day signal.** CI-lo in the live window (−$0.37) already warned of this.

---

## 7. Walk-Forward 50/50

| Config | Train Total | Test Total | Test $/tr | Test WR% |
|---|---|---|---|---|
| BASE full-Kelly | +$3,046 | +$15,833 | +$9.03 | 85.6 |
| BASE half-Kelly | +$1,523 | +$7,917 | +$4.51 | 85.6 |
| EU gate full-Kelly | +$41 | +$3,841 | +$6.96 | 85.7 |
| EU gate half-Kelly | +$21 | +$1,921 | +$3.48 | 85.7 |

Test half dominates (train = +$3k, test = +$15.8k) because the 4× tail fires concentrate in May 18–21 (the test half). This is **timing concentration, not generalization evidence**. The walk-forward confirms the edge but does not validate it as persistent: the train half is near-breakeven.

---

## 8. Verdicts

### Does the kelly edge persist May 1–21?

**Partially yes, but heavily concentrated.** 80% of returns come from the 4× tier (fe>3000, n=152, vwap~0.48). These are near-resolved pre-window slots where the model has extreme conviction. This is genuine alpha — near-resolution arbitrage where fair_edge_bp captures market mispricing. However, the returns are **not uniformly distributed** across time: weeks 18–20 average +$1.94/tr while week 21 alone delivers +$15.67/tr. The edge exists but has lumpy timing driven by when extreme-fe slots appear.

### Does keep_EU persist?

**No.** EU gate fails both-half holdout (H1 = −$0.08/tr). The live May 26–30 result was a lucky sample from the high-spike period. EU is not an independent time-of-day signal on the May 1–21 panel.

### Best new gate?

**`fair_edge_bp > 1000`** — best overall PASS gate: n=818, +$22.50/tr, Calmar=527.7 vs 391.6 base, both-half PASS (H1 +$10.83, H2 +$34.17). Captures the 2×+3×+4× tiers. Retains 23% of fires but 97% of total PnL (+$18,408 vs +$18,879). Combines naturally with the existing tier structure.

**`fair_edge_bp > 1500`** and **`fair_edge_bp > 2000`** also PASS with even higher $/tr but fewer fires.

### ½-Kelly recommendation

Confirmed. Half-Kelly: +$9,440 total, MDD −$422, Calmar 391.6 — identical Calmar to full-Kelly. The 4× tier fires at $50 stake instead of $100. Reduces single-trade loss exposure by 50% at zero cost to risk-adjusted return.

---

## 9. Risk Flags

1. **Week 21 dominance**: 73% of total in 4 days. Results not stable across the full 21-day window.
2. **1× tier is a loser**: flat $25 at 1× fe earns +$0.18/tr. At flat-$5: +$0.33/tr aggregate. The Kelly signal is the sizing, not the base signal direction.
3. **Train half nearly zero**: walk-forward train +$3k vs test +$15.8k. Suggests forward returns depend on the spike recurring.
4. **vwap_median = 0.48 at 4×**: these fires are at ~48-50 cents, deep in-the-money. Extreme Kelly leverage on near-resolved slots. If the fair_edge_bp model mis-calibrates even slightly, drawdown spikes.
5. **Panel is May 1–21 only**: missing Apr 22–30 (9 days). Full 40-day window would dilute the week-21 concentration but is not available in this panel.

---

## 10. Recommended Config

| Config | Stake | Gate | Expected $/tr | Expected n/day | Risk |
|---|---|---|---|---|---|
| **fe>1000, half-Kelly** | $12.5–$50 scaled | fe>1000 | +$11.25 | ~40 | Medium |
| **fe>1500, half-Kelly** | $12.5–$50 scaled | fe>1500 | +$17.96 | ~24 | Medium-low |
| **BASE half-Kelly** | $12.5–$50 scaled | none | +$2.69 | ~170 | Medium-high |

**Deploy recommendation: fe>1000 + half-Kelly.** Calmar 527.7, 23% fire retention, both-half PASS. Stake $12.5×kelly_mult ($12.5/$25/$37.5/$50 by tier). Do not deploy `keep_EU` as a gate — it does not generalize.

---

*Generated: 2026-06-01. Script: `strategy_lab/_opt_2026_05_30/18_kelly_fullperiod_backtest.py`.*
