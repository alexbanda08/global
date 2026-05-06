# Phase 9 — Lookahead Validation

_Generated: 2026-05-05_

## Hypothesis

Phase 9's `poly_tfi_2m` (Polymarket trade-flow imbalance over the first 2 minutes
of the market) showed +53.5% ROI / 77.7% hit on top 5%. For 5m markets, that 2m
window is **40% of the market lifetime**. Concern: `poly_tfi_2m` may mostly reflect
BTC's actual return in those same 2 minutes, which the eventual settlement also
reflects.

## Test

Add `btc_ret_2m = log(close@t+120s / close@t)` from Binance 1m bars. Then check
whether `poly_tfi_2m`'s coefficient survives controlling for `btc_ret_2m` in a
joint regression on `outcome_up`.

## Data

- Phase 9 features: 4673 markets (3505 5m, 1168 15m)
- After joining outcome + ≥1 trade in 2m + BTC bars present: **3070** markets
- BTC 1m source: `data\v4\refresh_2026_05_02\binance_spot_1min_full.csv` (16113 bars)

## 1. Direct correlation: poly_tfi_2m vs btc_ret_2m

- Pearson r:  **+0.6157**
- Spearman ρ: +0.6401 (p=0.00e+00)
- n = 3070

→ Strong correlation: `poly_tfi_2m` is **largely** a BTC-momentum proxy. Lookahead concern likely confirmed.


## Regressions — ALL active (n=3070)

### Linear probability model (OLS on 0/1 outcome)

**Univariate poly_tfi_2m:**
```
n=3070, R²=0.1133
  poly_tfi_2m: β=+0.6355  SE=0.0321  t=+19.80  p=0.00e+00
```
**Univariate btc_ret_2m:**
```
n=3070, R²=0.1567
  btc_ret_2m: β=+290.0935  SE=12.1488  t=+23.88  p=0.00e+00
```
**Joint (CONTROLLING FOR BTC RETURN):**
```
n=3070, R²=0.1706
  poly_tfi_2m: β=+0.2824  SE=0.0394  t=+7.17  p=9.58e-13
  btc_ret_2m: β=+222.6222  SE=15.2919  t=+14.56  p=0.00e+00
```
### Logistic regression

**Univariate poly_tfi_2m:**
```
n=3070, logloss=0.6332
  poly_tfi_2m: β=+0.7546  SE=0.0479  z=+15.75  p=0.00e+00
```
**Univariate btc_ret_2m:**
```
n=3070, logloss=0.5937
  btc_ret_2m: β=+1.2394  SE=0.0819  z=+15.13  p=0.00e+00
```
**Joint (CONTROLLING FOR BTC RETURN):**
```
n=3070, logloss=0.5890
  poly_tfi_2m: β=+0.2746  SE=0.0543  z=+5.06  p=4.26e-07
  btc_ret_2m: β=+1.0377  SE=0.0906  z=+11.46  p=0.00e+00
```

**Coefficient survival**: joint/univariate = 0.36× (1.0 = unchanged, 0 = killed by control)
**poly_tfi_2m p-value in joint**: 4.26e-07
→ **Marginal**: poly_tfi_2m loses much of its strength but still has some signal.

## Regressions — 5m markets only (40% lookahead window) (n=2302)

### Linear probability model (OLS on 0/1 outcome)

**Univariate poly_tfi_2m:**
```
n=2302, R²=0.1635
  poly_tfi_2m: β=+0.8008  SE=0.0378  t=+21.20  p=0.00e+00
```
**Univariate btc_ret_2m:**
```
n=2302, R²=0.1835
  btc_ret_2m: β=+317.2538  SE=13.9548  t=+22.73  p=0.00e+00
```
**Joint (CONTROLLING FOR BTC RETURN):**
```
n=2302, R²=0.2099
  poly_tfi_2m: β=+0.4277  SE=0.0488  t=+8.77  p=0.00e+00
  btc_ret_2m: β=+211.9878  SE=18.2361  t=+11.62  p=0.00e+00
```
### Logistic regression

**Univariate poly_tfi_2m:**
```
n=2302, logloss=0.6039
  poly_tfi_2m: β=+0.9646  SE=0.0585  z=+16.50  p=0.00e+00
```
**Univariate btc_ret_2m:**
```
n=2302, logloss=0.5713
  btc_ret_2m: β=+1.4647  SE=0.1025  z=+14.29  p=0.00e+00
```
**Joint (CONTROLLING FOR BTC RETURN):**
```
n=2302, logloss=0.5620
  poly_tfi_2m: β=+0.4242  SE=0.0703  z=+6.03  p=1.62e-09
  btc_ret_2m: β=+1.1297  SE=0.1154  z=+9.79  p=0.00e+00
```

**Coefficient survival**: joint/univariate = 0.44× (1.0 = unchanged, 0 = killed by control)
**poly_tfi_2m p-value in joint**: 1.62e-09
→ **Marginal**: poly_tfi_2m loses much of its strength but still has some signal.

## Regressions — 15m markets only (13% lookahead window) (n=768)

### Linear probability model (OLS on 0/1 outcome)

**Univariate poly_tfi_2m:**
```
n=768, R²=0.0284
  poly_tfi_2m: β=+0.2825  SE=0.0597  t=+4.74  p=2.60e-06
```
**Univariate btc_ret_2m:**
```
n=768, R²=0.0917
  btc_ret_2m: β=+215.1457  SE=24.4725  t=+8.79  p=0.00e+00
```
**Joint (CONTROLLING FOR BTC RETURN):**
```
n=768, R²=0.0919
  poly_tfi_2m: β=+0.0282  SE=0.0674  t=+0.42  p=6.76e-01
  btc_ret_2m: β=+208.9656  SE=28.5913  t=+7.31  p=6.80e-13
```
### Logistic regression

**Univariate poly_tfi_2m:**
```
n=768, logloss=0.6787
  poly_tfi_2m: β=+0.3453  SE=0.0749  z=+4.61  p=4.09e-06
```
**Univariate btc_ret_2m:**
```
n=768, logloss=0.6405
  btc_ret_2m: β=+0.7849  SE=0.1240  z=+6.33  p=2.47e-10
```
**Joint (CONTROLLING FOR BTC RETURN):**
```
n=768, logloss=0.6404
  poly_tfi_2m: β=+0.0086  SE=0.0868  z=+0.10  p=9.22e-01
  btc_ret_2m: β=+0.7795  SE=0.1355  z=+5.75  p=8.70e-09
```

**Coefficient survival**: joint/univariate = 0.02× (1.0 = unchanged, 0 = killed by control)
**poly_tfi_2m p-value in joint**: 9.22e-01
→ **Killed**: poly_tfi_2m is largely a BTC-momentum readout.

## 3. Top-5% gate (the actual deploy threshold)


### Top-5% |poly_tfi_2m| — ALL active

- n_fired = 154
- hit (poly_tfi_2m sign): 80.5%
- hit (btc_ret_2m sign):  81.8%
- when both signs agree:  83.8% (n=142)
- when signs disagree:    41.7% (n=12)
  → in the disagreement subset, poly_tfi_2m loses to BTC: poly_tfi_2m alone is near coin-flip when BTC contradicts it

### Top-5% |poly_tfi_2m| — 5m markets

- n_fired = 116
- hit (poly_tfi_2m sign): 85.3%
- hit (btc_ret_2m sign):  90.5%
- when both signs agree:  90.7% (n=108)
- when signs disagree:    12.5% (n=8)
  → in the disagreement subset, poly_tfi_2m loses to BTC: poly_tfi_2m alone is near coin-flip when BTC contradicts it

### Top-5% |poly_tfi_2m| — 15m markets

- n_fired = 39
- hit (poly_tfi_2m sign): 76.9%
- hit (btc_ret_2m sign):  76.9%
- when both signs agree:  80.0% (n=35)
- when signs disagree:    50.0% (n=4)
  → in the disagreement subset, poly_tfi_2m loses to BTC: poly_tfi_2m alone is near coin-flip when BTC contradicts it

---

## VERDICT

| Slice | n | poly_tfi_2m β (joint) | btc_ret_2m β (joint) | p (poly_tfi_2m) |
|---|---|---|---|---|
| ALL  | 3070 | +0.275 | +1.038 | **4.26e-07** |
| 5m   | 2302 | +0.424 | +1.130 | **1.62e-09** |
| 15m  | 768 | +0.009 | +0.780 | **9.22e-01** |
