# Combined Gate v2 — V3 ∪ Phase 7 ∪ Phase 9

_Generated: 2026-05-05_

## Gate definitions

- **V3** : prob_stack confidence ≥ 0.65  (procyclic)
- **P7** : |imb_slope_2m| ≥ p95, threshold=0.008307  (CONTRARIAN)
- **P9** : |poly_tfi_2m|  ≥ p90, threshold=0.4207  (procyclic, ≥1 trade)

## Individual gate performance

| Gate | n_bets | hit | ROI | pnl_total |
|---|---|---|---|---|
| V3 alone | 330 | 63.6% | +25.3% | $+41.70 |
| P7 alone | 232 | 59.9% | +17.8% | $+20.68 |
| P9 alone | 355 | 77.7% | +53.5% | $+94.95 |

## Pairwise overlap (Jaccard)

- V3∩P7: only_V3=302  only_P7=204  both=28  Jaccard=0.052
- V3∩P9: only_V3=306  only_P9=331  both=24  Jaccard=0.036
- P7∩P9: only_P7=204  only_P9=327  both=28  Jaccard=0.050

## UNION strategies

| Strategy | n_bets | hit | ROI | pnl_total |
|---|---|---|---|---|
| UNION (V3∪P7) [baseline] | 534 | 62.2% | +22.3% | $+59.66 |
| UNION (V3∪P9) | 661 | 70.8% | +39.6% | $+130.89 |
| UNION (V3∪P7∪P9) | 840 | 68.1% | +34.2% | $+143.60 |