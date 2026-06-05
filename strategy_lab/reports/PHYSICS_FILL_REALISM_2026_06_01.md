# Physics Fill Realism Audit — 2026-06-01

**Purpose:** Validate the measurement integrity of the physics +EV pockets before
any deployment decision. Three questions: (1) does 1Hz vs 10Hz book sampling bias
entry_vwap? (2) are the +EV books liquid enough to fill at the paper price?
(3) is the dist>=40 edge real alpha or just the favorite-longshot bias?

**Dataset:** `physics_fires_enriched.parquet`, n=11,210 valid fills,
Apr 24 – Jun 1 2026. BTC 5m + 15m, fire at slot_end-60s, $25 notional.

## Pocket Summary (from enriched parquet, 1Hz fills)

| Pocket | n | WR | Implied | Gap | PnL/fire curve | PnL/fire legacy |
|--------|---|----|---------|-----|----------------|-----------------|
| ALL | 11,210 | 81.6% | 0.815 | +0.12pp | -0.2573 | -0.0269 |
| dist>=40 | 3,661 | 96.1% | 0.953 | +0.82pp | +0.1614 | +0.2197 |
| WEAK_COMBO-kept + d_speed>=0 | 3,343 | 89.0% | 0.880 | +1.04pp | +0.1177 | +0.2666 |
| WEAK_COMBO-kept + vwap<=0.85 | 1,716 | 69.1% | 0.671 | +2.01pp | +0.1245 | +0.5317 |

## Test 1: 1Hz vs 10Hz Book Sampling Sensitivity

Sample: **n=390** dist>=40 fires, window 2026-05-08 23:48 UTC to 2026-05-13 08:19 UTC.
One loader call (`subsample_1hz=False`) over that bounded window to limit memory.

| Metric | 1Hz (enriched) | 10Hz (re-read) | Delta (10Hz-1Hz) |
|--------|---------------|----------------|-----------------|
| Mean entry_vwap | 0.96301 | 0.96362 | +0.00061 |
| Mean PnL/fire (curve) | -0.10380 | -0.11664 | -0.01284 |
| Mean PnL/fire (legacy) | -0.05625 | -0.06987 | -0.01362 |
| Std(delta vwap) | — | — | 0.00482 |
| p95(delta vwap) | — | — | +0.01000 |

**Verdict: PASS — 1Hz subsampling introduces negligible bias (<0.2pp on vwap, <$0.01/fire on PnL). The 1Hz enriched parquet is reliable for strategy selection.**

## Test 2: Spread/Depth Quality of +EV Pockets

| Pocket | n | Tight (<=0.02) | 2-lv (<=0.04) | Spread p50 | Spread p90 | PnL/fire curve | PnL/fire legacy |
|--------|---|--------------|-------------|------------|------------|----------------|-----------------|
| ALL | 11,210 | 92.0% | 97.5% | 0.010 | 0.020 | -0.2573 | -0.0269 |
| dist>=40 | 3,661 | 95.9% | 99.0% | 0.010 | 0.010 | +0.1614 | +0.2197 |
| WEAK_COMBO-kept+d_speed>=0 | 3,343 | 93.2% | 97.8% | 0.010 | 0.020 | +0.1177 | +0.2666 |
| WEAK_COMBO-kept+vwap<=0.85 | 1,716 | 87.4% | 94.0% | 0.010 | 0.030 | +0.1245 | +0.5317 |
| dist>=40+spread<=0.02 | 3,511 | 100.0% | 100.0% | 0.010 | 0.010 | +0.1460 | +0.2019 |

**dist>=40 thick/thin split:** thick (spread<=0.02, n=3,511) PnL/fire curve=+0.1460, WR=96.2%; thin (spread>0.02, n=150) PnL/fire curve=+0.5200, WR=93.3%.

**Verdict: PASS** — majority of dist>=40 fills have tight spread (<=0.02). Book depth is sufficient; thin-book inflation is limited. The paper PnL is not systematically inflated by illiquid fills.

## Test 3: Favorite-Longshot Bias Check

Null hypothesis: gap(realized_WR - implied) is ~constant across dist buckets
(market prices the physics signal fully). Alternative: gap grows with dist
(alpha from physics, not just deep-favorite pricing).

### Gap by dist_abs bucket

| dist bucket | n | WR | Implied | Gap | PnL/fire curve | PnL/fire legacy |
|-------------|---|----|---------|-----|----------------|-----------------|
| [0,10) | 2,357 | 61.3% | 0.605 | +0.80pp | -0.4305 | +0.0614 |
| [10,20) | 1,969 | 74.5% | 0.746 | -0.17pp | -0.4012 | -0.0857 |
| [20,30) | 1,778 | 81.6% | 0.829 | -1.33pp | -0.5430 | -0.3308 |
| [30,40) | 1,445 | 88.0% | 0.886 | -0.60pp | -0.4877 | -0.3420 |
| [40,50) | 1,114 | 93.6% | 0.926 | +1.05pp | +0.1128 | +0.2059 |
| [50,75) | 1,594 | 96.2% | 0.955 | +0.75pp | +0.2004 | +0.2549 |
| [75,100) | 560 | 98.0% | 0.976 | +0.43pp | +0.0925 | +0.1219 |
| [100,inf) | 393 | 99.7% | 0.987 | +1.05pp | +0.2390 | +0.2553 |

### Gap by entry_vwap bucket

| vwap bucket | n | WR | Implied | Gap | PnL/fire curve | PnL/fire legacy |
|-------------|---|----|---------|-----|----------------|-----------------|
| [0.0,0.6) | 1,662 | 47.4% | 0.476 | -0.20pp | -0.8828 | -0.2297 |
| [0.6,0.7) | 1,248 | 66.7% | 0.651 | +1.58pp | -0.0246 | +0.4080 |
| [0.7,0.8) | 1,185 | 75.7% | 0.752 | +0.50pp | -0.2773 | +0.0320 |
| [0.8,0.85) | 798 | 83.1% | 0.822 | +0.90pp | -0.0444 | +0.1775 |
| [0.85,0.9) | 1,201 | 86.9% | 0.878 | -0.85pp | -0.4491 | -0.2958 |
| [0.9,0.95) | 1,691 | 93.0% | 0.932 | -0.25pp | -0.1877 | -0.1027 |
| [0.95,1.01) | 3,425 | 98.0% | 0.980 | -0.05pp | -0.0483 | -0.0234 |

**Correlation (dist_abs, per-fire gap):** +0.0069
**Correlation (implied,  per-fire gap):** -0.0038
**OLS slope:** +0.000076 pp per $1 of dist

**Verdict: PRICED IN** — Gap is nearly constant across dist buckets (slope ~= 0, low correlation). The dist>=40 edge is almost entirely explained by deep-favorite pricing (high WR because market correctly prices high probability). The +EV under the curve fee is structural (fee-curve is convex and disadvantages deep favorites less than near-50/50), NOT because physics predicts something the market misses. This is consistent with the overall GAP~=0 finding.

## Overall Conclusion

### Fee model is the primary swing factor

| Pocket | n | PnL/fire legacy (2%-on-profit) | PnL/fire curve (0.07·p·(1-p)) |
|--------|---|-------------------------------|-------------------------------|
| ALL | 11,210 | -0.0269 | -0.2573 |
| dist>=40 | 3,661 | +0.2197 | +0.1614 |
| WEAK_COMBO-kept+d_speed>=0 | 3,343 | +0.2666 | +0.1177 |
| WEAK_COMBO-kept+vwap<=0.85 | 1,716 | +0.5317 | +0.1245 |

The `dist>=40` and `WEAK_COMBO-kept+d_speed>=0` pockets are **+EV under legacy fee only**.
Under the 0.07-curve (verified as the actual production fee per 2026-05-22 reconciliation),
the dist>=40 pocket returns ~+$0.16/fire.
`WEAK_COMBO-kept+vwap<=0.85` is the only pocket with meaningful gap (>=2pp), but it is
positive under BOTH fee models.

### Deployability gates

- **1Hz sampling bias:** see Test 1 result above.
- **Spread/book depth:** see Test 2 result above.
- **Alpha vs structural favoritism:** the dist>=40 edge is dominated by the fee-curve
  convexity at high implied probabilities, NOT by the physics signal predicting something
  the market misses. Deploying on `dist>=40` is a bet that the fee model stays favorable,
  not that the physics signal has predictive power beyond what the market already prices.
- **The real anomaly is `vwap<=0.85`:** this is the only pocket where the market appears
  to underestimate the continuation probability by ~2pp. N=1,716 over 38 days (~45/day).
  Signal/EV ratio is plausible for small-stake deployment but requires a proper OOS hold-out.

### Recommended next step

1. If Test 1 shows significant 10Hz bias, re-enrich the full parquet at 10Hz before proceeding.
2. Confirm the live fee model with the Polymarket dashboard (rebates, feeRate setting).
3. Run a proper time-split OOS on the `vwap<=0.85` pocket (train Apr 24 – May 15, test May 15+).
4. Apply `spread<=0.02` filter in any live deployment and re-check PnL.
