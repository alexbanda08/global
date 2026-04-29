# Side-Asymmetry Test — Standalone Candidate Strategy

**Hypothesis:** Crypto retail bias toward UP causes structural overpricing of YES tokens.
Tested on Polymarket BTC/ETH/SOL UpDown markets (Apr 22-27, 2026).
Strategy core: same as locked baseline (sig_ret5m + hedge-hold rev_bp=5), but stratified by direction.

**Source motivation:** JBecker (2026) Kalshi 72.1M trades — NO outperforms YES at 69/99 price levels; dollar-weighted YES -1.02% vs NO +0.83%. Crypto category 2.69pp gap.


## Test 1 — UP vs DOWN direction asymmetry (q10 universe)

If YES (Up) overpricing exists, DOWN bets should outperform UP bets.

| Slice | n | Hit% | ROI | 95% CI | perm-p (UP vs DOWN) |
|---|---|---|---|---|---|
| ALL×5m UP   | 291 | 79.4% | +25.91% | [+22.48, +29.21]% | — |
| ALL×5m DOWN | 325 | 82.8% | +27.76% | [+24.51, +30.87]% | p=0.402 |
| btc×5m UP   | 97 | 83.5% | +28.01% | [+21.96, +33.81]% | — |
| btc×5m DOWN | 109 | 84.4% | +29.91% | [+24.21, +35.35]% | p=0.640 |
| eth×5m UP   | 100 | 78.0% | +27.16% | [+21.69, +32.35]% | — |
| eth×5m DOWN | 105 | 81.0% | +27.51% | [+21.81, +32.92]% | p=0.927 |
| sol×5m UP   | 94 | 76.6% | +22.42% | [+16.23, +28.31]% | — |
| sol×5m DOWN | 111 | 82.9% | +25.88% | [+20.61, +30.90]% | p=0.394 |
| ALL×15m UP   | 93 | 80.6% | +19.62% | [+15.03, +24.10]% | — |
| ALL×15m DOWN | 114 | 81.6% | +21.09% | [+17.00, +25.19]% | p=0.628 |
| btc×15m UP   | 30 | 83.3% | +22.87% | [+14.84, +30.70]% | — |
| btc×15m DOWN | 39 | 84.6% | +23.23% | [+15.69, +30.58]% | p=0.948 |
| eth×15m UP   | 29 | 82.8% | +18.42% | [+11.27, +25.36]% | — |
| eth×15m DOWN | 40 | 80.0% | +21.34% | [+15.37, +27.48]% | p=0.543 |
| sol×15m UP   | 34 | 76.5% | +17.77% | [+9.42, +25.54]% | — |
| sol×15m DOWN | 35 | 80.0% | +18.41% | [+10.80, +26.03]% | p=0.908 |
| ALL×ALL UP   | 384 | 79.7% | +24.39% | [+21.56, +27.14]% | — |
| ALL×ALL DOWN | 439 | 82.5% | +26.03% | [+23.36, +28.58]% | p=0.406 |
| btc×ALL UP   | 127 | 83.5% | +26.79% | [+21.65, +31.58]% | — |
| btc×ALL DOWN | 148 | 84.5% | +28.15% | [+23.51, +32.59]% | p=0.698 |
| eth×ALL UP   | 129 | 79.1% | +25.20% | [+20.67, +29.49]% | — |
| eth×ALL DOWN | 145 | 80.7% | +25.81% | [+21.43, +30.08]% | p=0.855 |
| sol×ALL UP   | 128 | 76.6% | +21.19% | [+16.24, +26.10]% | — |
| sol×ALL DOWN | 146 | 82.2% | +24.09% | [+19.62, +28.39]% | p=0.393 |

**Overall q10 UP-vs-DOWN permutation p-value: 0.3929**
→ NO significant direction asymmetry detected at this sample size.

## Test 2 — Entry-price overpricing

If markets are perfectly priced, entry_yes_ask + entry_no_bid ≈ 1.00 (no arbitrage). Any premium above 1.00 = both sides overpriced (taker pays spread). Asymmetric premium = one side overpriced more than the other.


Mean (yes_ask + no_ask): 1.0259
Median: 1.0100
P25, P75: 1.0100, 1.0300

Mean entry_yes_ask: 0.5206
Mean entry_no_ask: 0.5054
Mean (1 - entry_no_ask) [implied YES from NO ask]: 0.4946

Delta (yes_ask - (1 - no_ask)) = how overpriced is YES vs implied-from-NO:
  Mean: +0.0259 (+2.59¢)
  Bootstrap 95% CI of delta mean: see below.
  CI: [+0.0239, +0.0281]
→ YES is **systematically overpriced** vs implied-from-NO (CI excludes zero).

## Test 3 — Cross-asset replication of direction asymmetry (q10)

Per asset, compare DOWN ROI minus UP ROI. If 3 unrelated assets agree on sign, signal is robust.

| Asset | UP n | UP ROI | DOWN n | DOWN ROI | DOWN−UP delta |
|---|---|---|---|---|---|
| btc | 127 | +26.79% | 148 | +28.15% | **+1.36pp** |
| eth | 129 | +25.20% | 145 | +25.81% | **+0.61pp** |
| sol | 128 | +21.19% | 146 | +24.09% | **+2.90pp** |

→ 3/3 assets show DOWN > UP ROI.
**Strong cross-asset replication** — all 3 assets confirm DOWN bets win more.

## Test 4 — Day-by-day decomposition of direction asymmetry

Stable lift across days = real signal. Driven by 1 day = artifact.

| Date | UP n | UP ROI | DOWN n | DOWN ROI | DOWN−UP |
|---|---|---|---|---|---|
| 2026-04-22 | 15 | +23.93% | 48 | +21.18% | -2.75pp |
| 2026-04-23 | 89 | +20.87% | 105 | +25.56% | +4.69pp |
| 2026-04-24 | 60 | +28.36% | 62 | +24.36% | -4.01pp |
| 2026-04-25 | 4 | +40.86% | 9 | +36.99% | -3.87pp |
| 2026-04-26 | 52 | +31.39% | 29 | +21.74% | -9.65pp |
| 2026-04-27 | 68 | +24.28% | 79 | +29.92% | +5.64pp |
| 2026-04-28 | 47 | +16.82% | 44 | +26.94% | +10.12pp |
| 2026-04-29 | 49 | +24.70% | 63 | +27.02% | +2.32pp |

→ 4/8 days show DOWN > UP ROI.

## Test 5 — q20 confirmation (larger sample n=1152)

If asymmetry is real, it should also appear on the wider q20 universe (more statistical power).

| Slice | n | Hit% | ROI | 95% CI |
|---|---|---|---|---|
| q20 UP   | 798 | 74.3% | +20.93% | [+18.85, +22.99]% |
| q20 DOWN | 843 | 75.9% | +22.06% | [+19.94, +24.11]% |

**q20 perm p-value (UP vs DOWN): 0.4512**

## Verdict

To deploy as a new strategy candidate, the side-asymmetry needs:
1. q10 perm p-value < 0.05 (statistically significant)
2. ≥ 2/3 cross-asset agreement on sign
3. ≥ 4/5 days showing the predicted direction
4. q20 confirmation (perm p < 0.05 on larger sample)
5. CI of yes-vs-no-implied delta excludes zero

**Criteria met: 3 / 5**

⚠️ **PARTIAL signal.** Worth running on more data before deploy.