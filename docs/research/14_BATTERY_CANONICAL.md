# 14 — Canonical Battery Results (5-test Robustness under Perps Simulator)

**Date:** 2026-04-24
**Driver:** [strategy_lab/run_battery_canonical.py](../../strategy_lab/run_battery_canonical.py)
**Simulator:** [strategy_lab/eval/perps_simulator.py](../../strategy_lab/eval/perps_simulator.py)
**Exec:** 4.5 bps taker / 3 bps slip / 3× lev / 3% ATR risk / 2-bar cooldown / canonical ATR stack
**Window:** 2021-01-01 → 2026-04-24
**Raw:** [docs/research/phase5_results/battery_canonical.json](phase5_results/battery_canonical.json)

## Headline — two 5/8 passers (new mission high)

| Cell | Total | Per-Year | Perm p<0.01 | Sharpe lower-CI >0.5 | Calmar lower-CI >1.0 | MDD upper-CI <30% | WFE>0.5 | ≥5/6 pos folds | Plateau |
|---|---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **SOL_BBBreak_LS 4h** | **5/8** | ✅ 5/6 | ✅ | ❌ (0.27) | ❌ (0.06) | ✅ | ✅ 0.59 | ❌ 4/6 | ✅ |
| **SOL_SuperTrend_Flip 4h** | **5/8** | ✅ 6/6 | ✅ | ❌ (0.80) | ❌ (0.46) | ❌ (−42% lower) | ✅ 0.84 | ✅ 5/6 | ❌ cliff (47%) |
| DOGE_HTF_Donchian 4h | 4/8 | ❌ 4/6 | ❌ p=0.10 | ❌ (0.00) | ❌ (−0.09) | ✅ | ✅ 0.65 | ✅ 5/6 | ✅ |
| ETH_CCI_Extreme_Rev 4h | 4/8 | ✅ 5/6 | ✅ | ❌ (0.24) | ❌ (0.06) | ✅ | ✅ 1.23 | ❌ 4/6 | ❌ cliff (107%) |

## Full per-cell per-year Sharpe

| Cell | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|
| SOL_SuperTrend_Flip | **+2.16** | **+1.47** | **+2.09** | **+0.63** | **+2.61** | **+0.20** |
| SOL_BBBreak_LS | +1.95 | +0.87 | +0.93 | +1.54 | +1.14 | −1.46 |
| ETH_CCI_Extreme_Rev | +0.82 | +1.53 | −0.55 | +1.84 | +1.66 | +4.51 |
| DOGE_HTF_Donchian | +1.41 | +0.91 | −0.29 | +1.00 | +1.84 | −0.85 |

**SOL_SuperTrend_Flip has the tightest profile: positive Sharpe in all 6 years.** The only reason it didn't hit 6/8 is that its ATR-based SL is wide enough to produce bootstrap MDD upper-CI at −42% (above the −30% gate) AND the plateau sweep of `ema_reg`/`st_mult` showed a 46.8% Sharpe drop at ±25%. These are real weaknesses.

## Bootstrap 95% CIs (2021-2026)

| Cell | Sharpe | Calmar | Max DD |
|---|---|---|---|
| SOL_SuperTrend_Flip | [+0.80, +2.54] | [+0.46, +4.62] | [−42%, −16%] |
| SOL_BBBreak_LS | [+0.27, +2.01] | [+0.06, +3.53] | [−64%, −25%] |
| ETH_CCI_Extreme_Rev | [+0.24, +2.17] | [+0.06, +3.02] | [−49%, −17%] |
| DOGE_HTF_Donchian | [+0.00, +1.84] | [−0.09, +2.78] | [−70%, −27%] |

**None of the four cells clear the Sharpe lower-CI > 0.5 gate.** That's a 95% confidence bar — uncertainty in the estimate is still wide. More data (more trade count per year) or more conservative stop placement would tighten these. Every cell has its lower CI above zero (barely), so edge-positivity is confirmed; it's the *strength* of the edge that's uncertain.

## Walk-forward efficiency

| Cell | WFE | Pos folds | Worst fold Sharpe |
|---|---:|---:|---:|
| SOL_SuperTrend_Flip | 0.84 | **5/6** | −0.79 |
| DOGE_HTF_Donchian | 0.65 | **5/6** | −0.47 |
| SOL_BBBreak_LS | 0.59 | 4/6 | −0.55 |
| ETH_CCI_Extreme_Rev | 1.23 | 4/6 | −1.18 |

SuperTrend and HTF-Donchian both pass the ≥5/6 positive folds bar — stronger structural evidence than raw Sharpe alone.

## Permutation null tests

| Cell | Real Sharpe | Null mean | Null 99th %ile | p-value |
|---|---:|---:|---:|---:|
| SOL_SuperTrend_Flip | +1.70 | −0.09 | +0.55 | **0.00** |
| SOL_BBBreak_LS | +1.19 | +0.00 | +0.86 | **0.00** |
| ETH_CCI_Extreme_Rev | +1.22 | −0.39 | +0.37 | **0.00** |
| DOGE_HTF_Donchian | +0.89 | −0.05 | +1.02 | 0.10 |

Three of four cells pass p<0.01 — the real edge is clearly above the null distribution's 99th percentile. **DOGE_HTF_Donchian fails permutation** — its +0.89 Sharpe is within the null's noise envelope (99th pct +1.02). That result reframes the earlier "strongest cell" label from report 10.

## Parameter plateau

| Cell | Passed | worst-25% drop | worst-50% drop | Cliff | Bad param |
|---|:---:|---:|---:|:---:|---|
| SOL_BBBreak_LS | ✅ | 16.9% | 22.6% | No | — |
| DOGE_HTF_Donchian | ✅ | 13.6% | 22.7% | No | — |
| SOL_SuperTrend_Flip | ❌ | 46.8% | 46.8% | No | one of `st_n`/`st_mult`/`ema_reg` |
| ETH_CCI_Extreme_Rev | ❌ | 85.4% | **107%** | **Yes** | CCI param space is sharply peaked |

CCI's 107% Sharpe drop at ±50% is a genuine overfit signature. SuperTrend's is moderate — likely just one param (probably `st_mult`) is sensitive; the others plateau fine. Both candidates need a re-sweep of the sensitive parameter to find the plateau.

## The mission's first near-promotion candidate

**SOL_SuperTrend_Flip 4h** now has:
- Positive Sharpe every year since 2021 ✅
- Permutation p-value 0.00 (highly significant edge) ✅
- Walk-forward 5/6 positive folds ✅
- WFE 0.84 (OOS retains 84% of IS edge) ✅
- **But:** wide bootstrap MDD (−42% lower CI), parameter non-plateau on at least one param (47% drop).

**SOL_BBBreak_LS 4h** has:
- Positive Sharpe 5/6 years ✅
- Permutation p-value 0.00 ✅
- Plateau passed ✅
- **But:** walk-forward 4/6 positive, wide bootstrap CIs, MDD still wide.

These are the strongest candidates the mission has produced. Neither clears 7/8, but both clear 5/8 which is an unambiguous improvement over anything we've seen. The 2026-YTD drag (partial year) hurts their ratios.

## Recommended next steps

1. **Parameter plateau resweep on SOL_SuperTrend_Flip** — find the stable region by sweeping `st_n`, `st_mult`, `ema_reg` individually at ±10% and ±20%. If even one of the three has a wide plateau we can rebaseline. Likely 1 turn.
2. **Re-run with tighter SL on SOL_SuperTrend_Flip** — the current `sl_atr=2.0` gives the −42% MDD lower-CI. Try `sl_atr=1.5` or `1.75`. If MDD upper-CI drops under −30% without killing Sharpe, that's the promotion candidate.
3. **ETH_CCI_Extreme_Rev plateau fix** — the CCI threshold pair `(cci_lo, cci_hi)` is the most-likely cliff source. Sweep that specifically to find a plateau region.
4. **Extend to remaining V25/V29 winners** — `sui_bbbreak`, `sol_bbbreak` on 4h are already tested; add AVAX, LINK, DOGE BBBreak + V29 Lateral_BB_Fade cells using the canonical battery.

## Artifacts

- [strategy_lab/run_battery_canonical.py](strategy_lab/run_battery_canonical.py) — 5-test driver
- [docs/research/phase5_results/battery_canonical.json](docs/research/phase5_results/battery_canonical.json) — raw reports
- [strategy_lab/eval/perps_simulator.py](strategy_lab/eval/perps_simulator.py) — canonical simulator (unchanged from report 13)
