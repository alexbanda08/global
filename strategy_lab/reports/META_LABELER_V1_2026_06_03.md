# P1 Meta-Labeler v1 — relative-value filter on lag-taker — 2026-06-03

Base = lag-taker enriched fires (n=3653). Target=won. Features=signal-only (entry_vwap EXCLUDED).
Calibrated P(win) (isotonic); decision = take iff P(win)-entry_vwap > margin. Metric = win07 $/tr.
Model = XGBoost. Purged walk-forward + time-held-out lockbox (last 25%).

## Lockbox result
| set | n | WR | $/tr (win07) | bootstrap 95% CI |
|---|--:|--:|--:|--:|
| ALL fires | 914 | 59.1% | -0.146 | [-1.515, +1.219] |
| META-GATED | 134 | 61.2% | +2.023 | [-1.787, +5.750] |

margin=0.28, dev OOF AUC=0.506, lockbox AUC=0.548.

**VERDICT: 🟡 lifts but CI includes 0 / low-n**

## Notes
- entry_vwap deliberately excluded from features (else model relearns market price -> no edge).
- win07 label/PnL uses the enriched file's entry_vwap (lag-taker study fill). Re-fill the deployed
  cell at 10Hz before sizing (Phase-A lesson). This run proves the PIPELINE + first signal of lift.
- This is the pipeline template for P1: swap the base universe (momo-F7, sniper) and re-run.
