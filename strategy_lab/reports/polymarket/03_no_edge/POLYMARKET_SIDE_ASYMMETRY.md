# Side-Asymmetry Test — Standalone Candidate Strategy

**Hypothesis:** Crypto retail bias toward UP causes structural overpricing of YES tokens.
Tested on Polymarket BTC/ETH/SOL UpDown markets (Apr 22-27, 2026).
Strategy core: same as locked baseline (sig_ret5m + hedge-hold rev_bp=5), but stratified by direction.

**Source motivation:** JBecker (2026) Kalshi 72.1M trades — NO outperforms YES at 69/99 price levels; dollar-weighted YES -1.02% vs NO +0.83%. Crypto category 2.69pp gap.


## Test 1 — UP vs DOWN direction asymmetry (q10 universe)

If YES (Up) overpricing exists, DOWN bets should outperform UP bets.

| Slice | n | Hit% | ROI | 95% CI | perm-p (UP vs DOWN) |
|---|---|---|---|---|---|
| ALL×5m UP   | 207 | 81.6% | +26.00% | [+21.94, +29.90]% | — |
| ALL×5m DOWN | 226 | 81.0% | +24.92% | [+21.01, +28.82]% | p=0.677 |
| btc×5m UP   | 67 | 86.6% | +31.17% | [+24.41, +37.46]% | — |
| btc×5m DOWN | 76 | 84.2% | +28.23% | [+21.46, +34.58]% | p=0.528 |
| eth×5m UP   | 70 | 80.0% | +26.92% | [+20.30, +33.06]% | — |
| eth×5m DOWN | 75 | 78.7% | +23.35% | [+15.98, +30.31]% | p=0.479 |
| sol×5m UP   | 70 | 78.6% | +20.12% | [+12.67, +27.00]% | — |
| sol×5m DOWN | 75 | 80.0% | +23.13% | [+16.27, +29.39]% | p=0.535 |
| ALL×15m UP   | 69 | 84.1% | +23.12% | [+17.40, +28.54]% | — |
| ALL×15m DOWN | 77 | 80.5% | +21.05% | [+15.89, +26.12]% | p=0.595 |
| btc×15m UP   | 22 | 81.8% | +24.27% | [+13.95, +34.07]% | — |
| btc×15m DOWN | 26 | 84.6% | +21.61% | [+11.81, +30.65]% | p=0.719 |
| eth×15m UP   | 22 | 90.9% | +27.23% | [+19.55, +34.85]% | — |
| eth×15m DOWN | 27 | 77.8% | +21.99% | [+13.50, +30.78]% | p=0.391 |
| sol×15m UP   | 25 | 80.0% | +18.50% | [+7.78, +28.24]% | — |
| sol×15m DOWN | 24 | 79.2% | +19.39% | [+10.56, +28.17]% | p=0.896 |
| ALL×ALL UP   | 276 | 82.2% | +25.28% | [+21.94, +28.41]% | — |
| ALL×ALL DOWN | 303 | 80.9% | +23.93% | [+20.74, +27.07]% | p=0.574 |
| btc×ALL UP   | 89 | 85.4% | +29.46% | [+23.74, +34.96]% | — |
| btc×ALL DOWN | 102 | 84.3% | +26.54% | [+20.87, +31.94]% | p=0.447 |
| eth×ALL UP   | 92 | 82.6% | +27.00% | [+21.60, +32.16]% | — |
| eth×ALL DOWN | 102 | 78.4% | +22.99% | [+17.12, +28.60]% | p=0.324 |
| sol×ALL UP   | 95 | 78.9% | +19.69% | [+13.59, +25.46]% | — |
| sol×ALL DOWN | 99 | 79.8% | +22.22% | [+16.57, +27.38]% | p=0.510 |

**Overall q10 UP-vs-DOWN permutation p-value: 0.5666**
→ NO significant direction asymmetry detected at this sample size.

## Test 2 — Entry-price overpricing

If markets are perfectly priced, entry_yes_ask + entry_no_bid ≈ 1.00 (no arbitrage). Any premium above 1.00 = both sides overpriced (taker pays spread). Asymmetric premium = one side overpriced more than the other.


Mean (yes_ask + no_ask): 1.0263
Median: 1.0100
P25, P75: 1.0100, 1.0300

Mean entry_yes_ask: 0.5171
Mean entry_no_ask: 0.5092
Mean (1 - entry_no_ask) [implied YES from NO ask]: 0.4908

Delta (yes_ask - (1 - no_ask)) = how overpriced is YES vs implied-from-NO:
  Mean: +0.0263 (+2.63¢)
  Bootstrap 95% CI of delta mean: see below.
  CI: [+0.0239, +0.0290]
→ YES is **systematically overpriced** vs implied-from-NO (CI excludes zero).

## Test 3 — Cross-asset replication of direction asymmetry (q10)

Per asset, compare DOWN ROI minus UP ROI. If 3 unrelated assets agree on sign, signal is robust.

| Asset | UP n | UP ROI | DOWN n | DOWN ROI | DOWN−UP delta |
|---|---|---|---|---|---|
| btc | 89 | +29.46% | 102 | +26.54% | **-2.93pp** |
| eth | 92 | +27.00% | 102 | +22.99% | **-4.00pp** |
| sol | 95 | +19.69% | 99 | +22.22% | **+2.53pp** |

→ 1/3 assets show DOWN > UP ROI.
**Weak / no cross-asset replication.**

## Test 4 — Day-by-day decomposition of direction asymmetry

Stable lift across days = real signal. Driven by 1 day = artifact.

| Date | UP n | UP ROI | DOWN n | DOWN ROI | DOWN−UP |
|---|---|---|---|---|---|
| 2026-04-22 | 22 | +21.75% | 53 | +21.22% | -0.53pp |
| 2026-04-23 | 112 | +21.74% | 128 | +23.91% | +2.16pp |
| 2026-04-24 | 73 | +28.12% | 75 | +25.13% | -2.99pp |
| 2026-04-25 | 6 | +26.58% | 11 | +33.63% | +7.05pp |
| 2026-04-26 | 63 | +29.39% | 36 | +22.59% | -6.80pp |

→ 2/5 days show DOWN > UP ROI.

## Test 5 — q20 confirmation (larger sample n=1152)

If asymmetry is real, it should also appear on the wider q20 universe (more statistical power).

| Slice | n | Hit% | ROI | 95% CI |
|---|---|---|---|---|
| q20 UP   | 561 | 75.4% | +21.15% | [+18.67, +23.64]% |
| q20 DOWN | 591 | 72.3% | +19.36% | [+16.72, +22.05]% |

**q20 perm p-value (UP vs DOWN): 0.3318**

## Verdict

To deploy as a new strategy candidate, the side-asymmetry needs:
1. q10 perm p-value < 0.05 (statistically significant)
2. ≥ 2/3 cross-asset agreement on sign
3. ≥ 4/5 days showing the predicted direction
4. q20 confirmation (perm p < 0.05 on larger sample)
5. CI of yes-vs-no-implied delta excludes zero

**Criteria met: 1 / 5**

❌ **NO clear edge** in side asymmetry on Polymarket BTC/ETH/SOL — paper findings (Kalshi-based, longshot-heavy) don't replicate on our mid-priced UpDown markets.