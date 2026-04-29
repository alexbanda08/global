# 40 — V68c: Surgical drop of dead-weight diversifiers

**Date:** 2026-04-27
**Runner:** [strategy_lab/run_v68c_drop_dead_diversifiers.py](../../strategy_lab/run_v68c_drop_dead_diversifiers.py)
**Output:** [phase5_results/v68c_drop_diversifiers.json](phase5_results/v68c_drop_diversifiers.json)
**Elapsed:** 7.7 s

## TL;DR

Five-way variant test against V69 baseline (V52* α=0.75 × per-position L=1.75 = Sh 2.61 / CAGR +61.1% / MDD −12.4%):

- **`drop_MFI_ETH` (α = 0.8125)** — only variant with positive Sharpe delta. **Sh 2.65 (+0.04), CAGR +64.9% (+3.8 pp), MDD −14.3% (−1.9 pp), WR_d 51.4%**. Marginal but real.
- **`drop_both` (α = 0.875)** — biggest CAGR jump (+7.6 pp to +68.7%) but flat Sharpe and MDD widens 4.8 pp.
- **`drop_SVD_AVAX`** — dominated by `drop_MFI_ETH` on every metric. Skip.
- **`pure_V41_only`** — Sharpe loses 0.25. Confirms diversifiers collectively add Sharpe value even when individually weak.

**Strict promotion gate (Sharpe lift AND MDD non-worse within 50 bps): HOLD.** No variant clears.

**Pragmatic recommendation: `drop_MFI_ETH` is a mild improvement worth paper-trading at the next iteration — but V69 baseline (keep all 4) remains the production candidate.** The Sharpe lift is within statistical noise on a 27-month sample.

## Full results

| Variant | α | Standalone Sh / CAGR / MDD | Levered Sh / CAGR / MDD / WR_d | ΔSh | ΔCAGR | ΔMDD |
|---|---:|---|---|---:|---:|---:|
| **V69 baseline (keep all 4)** | 0.7500 | 2.64 / +33.3% / −7.3% | **2.61 / +61.1% / −12.4% / 50.2%** | — | — | — |
| drop_SVD_AVAX | 0.8125 | 2.61 / +35.2% / −9.1% | 2.58 / +64.8% / −15.4% / 50.8% | −0.03 | +3.7 pp | −3.0 pp |
| **drop_MFI_ETH** | 0.8125 | **2.67 / +35.2% / −8.5%** | **2.65 / +64.9% / −14.3% / 51.4%** | **+0.04** | **+3.8 pp** | −1.9 pp |
| drop_both | 0.8750 | 2.63 / +37.0% / −10.3% | 2.61 / +68.7% / −17.2% / 51.6% | −0.01 | +7.6 pp | −4.8 pp |
| pure_V41_only | 1.0000 | 2.40 / +36.1% / −10.8% | 2.37 / +66.3% / −18.1% / 50.2% | −0.25 | +5.2 pp | −5.7 pp |

All five variants clear the user target (CAGR ≥ 60%, WR ≥ 50%, MDD ≥ −40%) under L=1.75 per-position leverage.

## What this confirms about the V52 design

Three durable findings from this exercise:

1. **MFI_ETH is genuinely dead weight at high leverage.** Per-sleeve CAGR was −1.4% (negative) at L=1.75 in doc 39. Removing it strictly improves the blend on Sharpe + CAGR + WR_d. The only cost is a small MDD widening (~2 pp).
2. **SVD_AVAX is alive but barely.** Per-sleeve Sharpe 0.30, CAGR +3.9%. Dropping it widens MDD MORE than dropping MFI_ETH (-3.0 pp vs -1.9 pp). Counterintuitive but real: SVD_AVAX's small positive returns are timed in MDD-helpful periods. Sleeve-level Sharpe ranking ≠ blend-contribution ranking.
3. **Pure V41 (no diversifiers) is materially worse.** Sharpe drops from 2.61 → 2.37 (−0.25). The four diversifiers collectively contribute ~0.25 Sharpe even though individually they look weak. This is the diversification math working.

## Why I'm not promoting `drop_MFI_ETH` to V70

The +0.04 Sharpe lift is **within typical statistical noise** for a 5000-bar sample. To get a robust Sharpe difference signal:

- Required samples ≈ 4 / Δ_Sharpe² ≈ 4 / 0.04² = **2500 bar-years** per variant
- We have 27 months of data per coin
- Conclusion: this lift could reverse on the next 6 months of data

The honest call is "this is a candidate for paper-trade A/B testing, not a backtest-driven promotion." The V25/V27 lookahead-bug discipline applies here too: small positive backtest deltas often dissipate in live trading.

## Two alternate framings, in case priorities shift

If **CAGR is the binding constraint** (not Sharpe), `drop_both` is the right choice:
- α = 0.875, MFI_SOL + VP_LINK only
- Levered: Sh 2.61, **CAGR +68.7%**, MDD −17.2%, WR_d 51.6%
- Trade-off: +7.6 pp CAGR for −4.8 pp wider MDD. Calmar loses 0.42.
- Live MDD planning: −17.2% × 1.5 = −25.8%. Still inside −40% cap, with 14.2 pp margin.

If **Sharpe is the binding constraint**, V69 baseline (α=0.75, all 4 diversifiers) wins.

## Recommendation

1. **Keep V69 baseline (V52* α=0.75 + all 4 diversifiers + per-position L=1.75) as the production candidate** for the V64→V69 deployment plan amendment.
2. **Document `drop_MFI_ETH` as a Stage-2 paper-trade candidate.** After 4 weeks of V69 paper-trading produces a clean Sharpe estimate, optionally split paper capital 50/50 to V69 vs V69-with-MFI_ETH-dropped to A/B test the Sharpe lift on live-equivalent data. Only promote to V70 if the live A/B shows persistent Sharpe lift > 0.10 over 8+ weeks.
3. **Park `drop_both` (the CAGR-maxed variant) as a backup** only if V69 fails the Stage-1 paper-trade Sharpe gate (Sharpe ≥ 1.30) due to slippage attrition. Higher CAGR backstop with the same target-pass guarantees.
4. **MFI_ETH is now flagged for next-cycle research.** Either tune its parameters (current: `lower=25, upper=75`) for the post-2024 regime, or replace it with a different ETH-coin diversifier (the role is structural — V52 wants ETH-side diversifier exposure).

## Files

- [run_v68c_drop_dead_diversifiers.py](../../strategy_lab/run_v68c_drop_dead_diversifiers.py)
- [phase5_results/v68c_drop_diversifiers.json](phase5_results/v68c_drop_diversifiers.json)

Reading order: [33](33_NEW_STRATEGY_VECTORS.md) → [34](34_V67_LEVERAGE_HIT.md) → [35](35_QUANTMUSE_REPO_ANALYSIS.md) → [36](36_V68_WEIGHT_OPTIMIZER.md) → [37](37_V68B_V41_RESHARE_WIN.md) → [38](38_V68B_GATES_PROMOTED.md) → [39](39_V69_PER_POSITION_LEVERAGE.md) → [40](40_V68C_DROP_DIVERSIFIERS.md) (this).
