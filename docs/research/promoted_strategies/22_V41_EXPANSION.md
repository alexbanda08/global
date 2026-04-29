# 22 — V41 Expansion Scan: Champion Holds

**Date:** 2026-04-24
**Scope:** broad search for more V41 regime-adaptive-exit winners and new exit variant (V47 breakeven-SL)
**Scan:** 6 coins × 5 signal families × 3 exit styles = **90 runs**
**Honest verdict:** champion `NEW_60_40_V41` is near-optimal for current 4h sleeve universe; gains are marginal.

## TL;DR

- Tested V41 regime-adaptive exits on: CCI, STF, VWZ, BBBRK, LATBB across ETH, BTC, SOL, AVAX, DOGE, LINK.
- Added **V47 breakeven-SL** (move SL to entry once trade 1×ATR in profit).
- **9 sleeves improved over baseline per-sleeve** — but only 2 improve the blend.
- **SOL_VWZ_V47** is the only marginal Sharpe improver when added to champion (2.416 → 2.442 at best config).
- **DOGE_LATBB_V47** improves Calmar but costs Sharpe+CAGR.
- **Champion holds.** Best 4-sleeve alternative trades 6.6pp CAGR for 0.018 Sharpe — bad trade.

## Per-sleeve winners (improvement over baseline, min 20 trades, pos_yrs ≥ 3)

| Rank | Coin | Signal | Exit | Baseline Sh | New Sh | ΔSh | New CAGR | New MDD | Pos Yrs |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|
| 1 | ETH | CCI | V41 | 1.22 | **1.58** | +0.36 | +53.9% | −27.9% | 5/6 |
| 2 | ETH | BBBRK | V41 | 0.50 | 0.79 | +0.29 | +28.0% | −60.0% | 4/6 |
| 3 | DOGE | LATBB | V47 | −0.27 | −0.01 | +0.26 | −0.9% | −20.0% | 3/6 |
| 4 | SOL | VWZ | V47 | 0.20 | 0.42 | +0.23 | +2.7% | −23.3% | 2/6 |
| 5 | LINK | STF | V41 | 0.22 | 0.41 | +0.18 | +8.3% | −45.0% | 4/6 |
| 6 | DOGE | CCI | V41 | 0.11 | 0.25 | +0.14 | +3.1% | −42.1% | 3/6 |
| 7 | AVAX | CCI | V47 | 0.25 | 0.33 | +0.07 | +4.1% | −27.9% | 4/6 |
| 8 | BTC | VWZ | V41 | −0.67 | −0.63 | +0.04 | −6.6% | −34.0% | 2/6 |
| 9 | LINK | VWZ | V41 | 0.28 | 0.32 | +0.04 | +3.3% | −18.0% | 2/6 |

**ETH_CCI_V41** remains the crown jewel (+29% Sharpe), already baked into the champion. Everything else has either too-high MDD, too-few pos_yrs, or too-weak standalone Sharpe.

## Blend-level tests

Only sleeves that survive standalone audit AND improve the blend are worth deploying. Tested each promising sleeve layered onto the champion:

### Layering single sleeves onto champion

| Layer | Weight | Sharpe | CAGR | MDD | Calmar | vs Champ |
|---|---:|---:|---:|---:|---:|---|
| (baseline) Champion | — | **2.416** | +44.9% | −11.8% | **3.80** | — |
| + SOL_VWZ_V47 | 15% | 2.436 | +37.9% | −10.5% | 3.60 | +Sh, −CAGR |
| + SOL_VWZ_V47 | 25% | 2.442 | +33.3% | −9.7% | 3.45 | +Sh, −11pp CAGR |
| + DOGE_LATBB_V47 | 15% | 2.395 | +37.2% | −9.6% | **3.87** | +Calmar, −Sh |
| + ETH_BBBRK_V41 | 15% | 2.239 | +43.7% | −14.3% | 3.05 | all worse |
| + LINK_STF_V41 | 15% | 2.213 | +39.6% | −11.4% | 3.48 | all worse |

### Multi-way stacks (champion + SOL + DOGE at various weights)

Best Sharpe: champion@70% + SOL_VWZ_V47@25% + DOGE_LATBB_V47@5% → Sharpe **2.439**, CAGR +30.9% (−14pp vs champion).

Best Calmar: similar territory; SOL weighted 10-15% with DOGE 5-10%. CAGR always crashes 10-14pp.

### Adding SOL_VWZ_V47 as a proper 4th sleeve in P3 side

- `P3_4sleeve_eqw` + P5 standard: Sharpe 2.434, CAGR +38.3%, MDD −11.7%, Calmar 3.27
- `P3_4sleeve_invvol` + P5 standard: Sharpe 2.442, CAGR +33.8%, MDD −13.5%, Calmar 2.51 (Calmar crashes)

The invvol version aggressively weights the low-vol SOL_VWZ sleeve, wrecking CAGR. The EQW version is the only one worth considering.

### Adding BOTH SOL_VWZ and DOGE_LATBB (5-sleeve P3 + 4-sleeve P5)

All three variants tested LOSE to champion on Sharpe. Over-diversification erodes alpha concentration.

## Key insights

1. **Diminishing returns at this scale.** The champion already pulls from 4 sleeves with good negative correlation. Adding more sleeves dilutes alpha faster than it adds diversification.

2. **Per-sleeve Sharpe improvement ≠ blend improvement.** 7 of 9 "winners" from the per-sleeve scan HURT the blend. This is the opposite lesson from study 19 — there, better sleeves made better blends. Here, the marginal sleeves are too correlated with existing ones to diversify meaningfully.

3. **V47 breakeven-SL is a legitimate technique.** It works especially well on weaker signals (SOL_VWZ: 0.20 → 0.42) and preserves Sharpe on others. Worth keeping in the exit-stack toolbox.

4. **SOL_VWZ_V47 is the only meaningful discovery.** Anti-correlated with champion, small but real Sharpe improvement. Bad standalone but structurally useful.

## Recommendation

### Primary deployment: keep `NEW_60_40_V41`

No expansion variant both raises Sharpe AND preserves CAGR. Operational complexity of adding more sleeves isn't justified.

### Optional lower-vol complement: `P3_4sleeve_eqw + P5 standard`

If running a second sub-account with a lower-vol mandate:
- Sharpe 2.434, CAGR +38.3%, MDD −11.7%, Calmar 3.27, min-yr +13.1%
- Adds SOL_VWZ_V47 as a 4th sleeve in P3 side (equal-weight, not inv-vol)
- Trades ~7pp CAGR for slightly smoother equity and 1pp MDD improvement

Not required; champion stands.

## Where meaningful gains would come from

Based on what we've seen across studies 18-22:

1. **Net-new signal families** — not exit tweaks. Options/order-flow signals, cross-coin cointegration pairs, funding-rate mean-reversion.
2. **Non-BTC-beta returns** — equity momentum, FX carry, commodity trend — real diversifier.
3. **Pre-2021 history** for SUI/AVAX/SOL — tightens Calmar CI further.
4. **Intra-bar execution modeling** — TWAP fills, limit-order queue models, real slippage per-bar.
5. **Live forward data** — 3+ months of paper-trade fills to tighten out-of-sample Calmar.

## Artifacts

- [strategy_lab/run_v41_expansion.py](../../strategy_lab/run_v41_expansion.py) — 90-run scan
- [strategy_lab/run_v41_expansion_multistack.py](../../strategy_lab/run_v41_expansion_multistack.py) — stacking tests
- [docs/research/phase5_results/v41_expansion_grid.csv](phase5_results/v41_expansion_grid.csv)
- [docs/research/phase5_results/v41_expansion_top5.json](phase5_results/v41_expansion_top5.json)
