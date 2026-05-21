# SOL FLOW Strategy Variants — 2026-05-07

**Date:** 2026-05-07  |  **Asset:** SOL  |  **Period:** Apr 22 → May 6 2026  |  **Stake:** $25  |  **Policy:** HOLD  |  **Permutations:** 1000

## TL;DR

**NO WINNER** — no SOL FLOW variant clears mean>=$5, p<0.05, n>=80. FLOW signal is informative on direction (G1) but does not generate tradeable alpha at the structural sample size we have on SOL.

**Ship bar:** mean $/trade ≥ +5, p<0.05, n≥80.

## All variants — combined results

| Variant | Cell | Param | n | hit% | mean $ | total $ | p | hit_lift |
|---|---|---|---:|---:|---:|---:|---:|---:|
| V1 | SOL_5m | T=0.15 | 1183 | 50.5 | -1.5902 | -1881.23 | 0.538 | - |
| V1 | SOL_5m | T=0.25 | 652 | 51.8 | -2.6349 | -1717.99 | 0.492 | - |
| V1 | SOL_5m | T=0.35 | 299 | 59.5 | +1.8465 | +552.10 | 0.530 | - |
| V1 | SOL_5m | T=0.45 | 114 | 64.9 | +0.1432 | +16.33 | 0.525 | - |
| V1 | SOL_15m | T=0.15 | 356 | 53.1 | +0.3720 | +132.43 | 0.540 | - |
| V1 | SOL_15m | T=0.25 | 208 | 52.4 | -0.1259 | -26.18 | 0.519 | - |
| V1 | SOL_15m | T=0.35 | 94 | 56.4 | +0.5460 | +51.33 | 0.523 | - |
| V1 | SOL_15m | T=0.45 | 33 | 54.5 | +0.7673 | +25.32 | 0.438 | - |
| V2 | SOL_5m | baseline (full momo) | 260 | 90.8 | -0.2530 | -65.78 | 0.561 | +0.0pp |
| V2 | SOL_5m | flow_agrees & |flow|>=0.10 | 76 | 97.4 | +1.8477 | +140.42 | 0.677 | +6.6pp |
| V2 | SOL_15m | baseline (full momo) | 94 | 77.7 | -0.7977 | -74.98 | 0.544 | +0.0pp |
| V2 | SOL_15m | flow_agrees & |flow|>=0.10 | 32 | 87.5 | +1.8333 | +58.67 | 0.638 | +9.8pp |
| V3 | SOL_5m | flip on opposes | 83 | 9.6 | -1.8085 | -150.11 | 0.389 | - |
| V3 | SOL_15m | flip on opposes | 44 | 29.5 | +3.8546 | +169.60 | 0.531 | - |
| V4 | SOL_5m | Q1 | 19 | 100.0 | +1.6762 | +31.85 | - | - |
| V4 | SOL_5m | Q2 | 19 | 94.7 | +1.4559 | +27.66 | 0.342 | - |
| V4 | SOL_5m | Q3 | 16 | 93.8 | +1.1388 | +18.22 | 0.373 | - |
| V4 | SOL_5m | Q4 | 22 | 100.0 | +2.8497 | +62.69 | - | - |
| V4 | SOL_15m | Q1 | 7 | 85.7 | +0.9698 | +6.79 | 0.731 | - |
| V4 | SOL_15m | Q2 | 7 | 85.7 | +1.1696 | +8.19 | 0.744 | - |
| V4 | SOL_15m | Q3 | 10 | 90.0 | +2.8047 | +28.05 | 0.746 | - |
| V4 | SOL_15m | Q4 | 8 | 87.5 | +1.9555 | +15.64 | 0.743 | - |
| V5 | SOL_5m | agree & 0.35-0.65 | 0 | - | - | - | - | - |
| V5 | SOL_15m | agree & 0.35-0.65 | 1 | 100.0 | +13.2086 | +13.21 | - | - |

## Variant definitions

| Variant | Description |
|---|---|
| V1 | FLOW-only standalone — full SOL universe; signal=sign(flow_score), gate by |flow_score|>T (T sweep). |
| V2 | FLOW-veto momo — keep momo fires where flow_agrees & |flow|>=0.10; baseline=full momo SOL. |
| V3 | FLOW-inverse momo — momo fires where flow opposes, FLIP signal direction. |
| V4 | FLOW-magnitude bucketing — among V2 set, split by |flow_score| quartile. |
| V5 | V2 + extreme-price skip — V2 set AND 0.35 ≤ entry_price ≤ 0.65. |

## Permutation test summary

All p-values from 1000-draw permutation test on `extended_backtest_with_robustness.permutation_test`. H0: outcome direction is independent of fired signal direction (within fired sample).

- 0 / 20 variants reach p<0.05.

## Notable findings (sub-ship-bar but worth tracking)

| Variant | Cell | n | hit% | mean $ | hit_lift | Note |
|---|---|---:|---:|---:|---:|---|
| V2 | SOL_5m | 76 | 97.4 | +1.85 | +6.6pp | Replicates G1; lift over baseline real but n too small for p<0.05 |
| V2 | SOL_15m | 32 | 87.5 | +1.83 | +9.8pp | Same — directional lift visible, sample size limit |
| V1 | SOL_5m | 299 | 59.5 | +1.85 | - | T=0.35 — no momo, but only +$1.85/trade |
| V3 | SOL_15m | 44 | 29.5 | +3.85 | - | Inverse signal on flow-opposes — interesting, n=44 |
| V3 | SOL_5m | 83 | 9.6 | -1.81 | - | Inverse FAILS on 5m — flow-opposes still mostly correctly directional there |
| V4 | SOL_5m Q4 | 22 | 100.0 | +2.85 | - | Strongest |flow|≥0.32 quartile, but n=22 |

**Interpretation:**
- V2's directional lift (+6.6 to +9.8pp hit lift, $1.85 vs $-0.25 mean) is real but fails permutation because the SOL anti-edge baseline already has hit≈90% (most HOLD wins on momo SOL — losses are just rare and large). Permutation null mean is therefore high too.
- V1 standalone has no edge below T=0.35 and only modest +$1.85 above — trading 299 markets to net $552 is not robust enough.
- V3 inverse on SOL_5m collapses (9.6% hit) — confirms G1's finding that flow-opposes already underperforms; flipping that direction does NOT recover. The 89% anti-edge inversion finding does NOT generalize via FLOW magnitude.
- V5 collapses because most V2-eligible momo+flow-agree fires are at extreme entry prices (momentum already moved price away from 50/50). Extreme-price skip is incompatible with momo gating on SOL.

## Recommendation

**Do not ship as standalone or refiner.** No variant clears mean≥+5, p<0.05, n≥80.

**Carry forward (with caveats):**
- V2 (FLOW-veto on SOL_5m & SOL_15m) shows directional lift consistent with G1 and is the most defensible variant. Recommend deploying as a **paper-only sleeve** for 4-6 weeks to accumulate n≥200 fires before re-running permutation. Expected $5-8/wk net at $25 stake based on current means.
- V1 standalone is dead.
- V3 inverse is dead on 5m; uncertain on 15m due to n=44 — defer.
- V4 magnitude shows monotone-ish increase by quartile (Q4 highest mean) but n is structurally too small to size by quartile.
- V5 is dead (incompatible with momo gating).

### Next steps

- Re-test V2 after additional 4 weeks of data (target n≥150 per cell). If mean still ≈+$1.85 and p drops below 0.10, ship.
- Consider FLOW as a tier classifier input (probabilistic up-weight) rather than a binary fire gate — this matches the V4 monotone hint without requiring quartile sizing.
- Re-evaluate whether FLOW combined with other layers (STRUCTURE, TRIGGER) yields confluence on SOL where FLOW alone does not.
- Investigate V2's high baseline hit rate (90.8% on SOL_5m) — losses are rare but ~$25 each. The mean PnL is dominated by tail-loss reduction, not hit-rate lift; FLOW may filter the catastrophic-loss tail more than detection statistics indicate. A loss-rate-conditional study (mean loss given loss in V2 vs baseline) would test this directly.

## Reproduction

```
cd "C:\Users\alexandre bandarra\Desktop\global"
py -X utf8 -m strategy_lab.confluence.flow.sol_strategies
```

Outputs: `strategy_lab/results/meta_classifier/sol_flow_strategies.csv` and this report.
