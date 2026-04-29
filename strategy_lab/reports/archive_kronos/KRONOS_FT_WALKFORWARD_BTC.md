# Kronos FT — Walk-Forward Validation of Hour/DOW Filter

**The question:** Does the hour-whitelist we chose in V3 generalize out-of-sample, or was it curve-fit to the full 3-month test slice?

**Protocol:** Pick hours/days using ONLY the training months. Evaluate on the held-out test months. Compare filtered accuracy to un-filtered baseline in the SAME test period.

Hour keep threshold: acc ≥ 58% in train, n ≥ 5
DOW keep threshold: acc ≥ 50% in train

## TRAIN on 2026-01 → TEST on 2026-02

- Train samples: 147, Test samples: 179
- Hours kept (from train): [0, 4, 5, 8, 10, 11, 12, 14, 19, 20, 21]
- Days kept (from train): ['Friday', 'Monday', 'Sunday', 'Thursday', 'Tuesday', 'Wednesday']

**Filtered accuracy on TEST: 57.1% (95% CI [45.5%, 67.5%])**
Baseline accuracy on TEST (no filter): 58.7% (95% CI [51.4%, 65.9%])
**Lift from filter: -1.5pp**
Coverage: 43.0% of test samples passed filter (77/179)

## TRAIN on 2026-01 → TEST on 2026-03

- Train samples: 147, Test samples: 172
- Hours kept (from train): [0, 4, 5, 8, 10, 11, 12, 14, 19, 20, 21]
- Days kept (from train): ['Friday', 'Monday', 'Sunday', 'Thursday', 'Tuesday', 'Wednesday']

**Filtered accuracy on TEST: 65.4% (95% CI [55.1%, 75.6%])**
Baseline accuracy on TEST (no filter): 53.5% (95% CI [45.9%, 61.1%])
**Lift from filter: +11.9pp**
Coverage: 45.3% of test samples passed filter (78/172)

## TRAIN on 2026-01 → TEST on 2026-02+2026-03

- Train samples: 147, Test samples: 351
- Hours kept (from train): [0, 4, 5, 8, 10, 11, 12, 14, 19, 20, 21]
- Days kept (from train): ['Friday', 'Monday', 'Sunday', 'Thursday', 'Tuesday', 'Wednesday']

**Filtered accuracy on TEST: 61.3% (95% CI [54.2%, 69.0%])**
Baseline accuracy on TEST (no filter): 56.1% (95% CI [51.0%, 61.3%])
**Lift from filter: +5.2pp**
Coverage: 44.2% of test samples passed filter (155/351)

## TRAIN on 2026-01+2026-02 → TEST on 2026-03

- Train samples: 326, Test samples: 172
- Hours kept (from train): [7, 8, 9, 10, 12, 13, 14, 18, 19, 20, 21, 22]
- Days kept (from train): ['Friday', 'Monday', 'Sunday', 'Thursday', 'Tuesday', 'Wednesday']

**Filtered accuracy on TEST: 62.5% (95% CI [51.4%, 73.6%])**
Baseline accuracy on TEST (no filter): 53.5% (95% CI [46.5%, 61.1%])
**Lift from filter: +9.0pp**
Coverage: 41.9% of test samples passed filter (72/172)

## Verdict logic

- Filter is REAL if OOS lift > 0pp AND OOS CI lower bound > 50%
- Filter is NOISE if OOS lift ≈ 0pp or negative
- Filter is REGIME-DEPENDENT if lift is positive on one test but negative on another
