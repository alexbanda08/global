# V3 ∪ BTC_only Union — Production-Faithful Realfills

_Generated: 2026-05-05_

## Setup

Same canonical engine as `phase9_lookahead_realfills_multi.py`. $25 stake, hedge-hold rev_bp=5, 2% fee, top-10 book walk, entry @ bucket 12 (= t+120s).

## Gates

- **V3**:       prob_stack confidence ≥ 0.65, sign(prob_stack-0.5) — covers Apr 22 → Apr 29 only
- **P7**:       top-5% \|imb_slope_2m\|, **CONTRARIAN** — full Apr 22 → May 4
- **BTC_only**: top-10% \|asset_ret_2m\|, sign(asset_ret_2m) — full Apr 22 → May 4

## Universe coverage

- Total markets: 4673
- With V3 features:    2734 (V3 only computed Apr 22 → Apr 29)
- With P7 features:    4631
- With BTC ret_2m:     4673

## Pairwise gate overlap

| Pair | only A | only B | both | Jaccard |
|---|---:|---:|---:|---:|
| V3 vs BTC | 281 | 420 | 49 | 0.065 |
| V3 vs P7 | 302 | 204 | 28 | 0.052 |
| BTC vs P7 | 426 | 189 | 43 | 0.065 |

On V3 ∩ BTC_only fires (n=49), V3 and BTC_only directions **agree** on 69.4% of markets.

## Engine results — entry @ t+120s, real fills, hedge-hold

| Gate | n | hit% | total PnL | mean PnL | ROI/trade | Sharpe | hedged | thin | no_book |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| V3_alone — ALL | 322 | 57.1 | $+417.15 | $+1.2955 | +10.82% | +7.14 | 62 | 0 | 8 |
| V3_alone — 5m | 238 | 59.7 | $+222.28 | $+0.9340 | +8.16% | +4.34 | 34 | 0 | 6 |
| V3_alone — 15m | 84 | 50.0 | $+194.87 | $+2.3199 | +18.37% | +6.96 | 28 | 0 | 2 |
| BTC_only — ALL | 463 | 63.5 | $-42.10 | $-0.0909 | +2.76% | -1.69 | 195 | 1 | 5 |
| BTC_only — 5m | 330 | 69.7 | $-86.57 | $-0.2623 | +1.52% | -4.35 | 119 | 1 | 4 |
| BTC_only — 15m | 133 | 48.1 | $+44.47 | $+0.3344 | +5.85% | +3.01 | 76 | 0 | 1 |
| P7_alone — ALL | 228 | 56.1 | $-278.69 | $-1.2223 | -0.20% | -4.30 | 32 | 0 | 4 |
| P7_alone — 5m | 212 | 56.6 | $-384.20 | $-1.8123 | -3.20% | -6.23 | 26 | 0 | 3 |
| P7_alone — 15m | 16 | 50.0 | $+105.51 | $+6.5942 | +39.52% | +5.73 | 6 | 0 | 1 |
| V3_BTC — ALL | 736 | 60.6 | $+345.78 | $+0.4698 | +6.14% | +4.32 | 235 | 1 | 13 |
| V3_BTC — 5m | 533 | 65.1 | $+129.48 | $+0.2429 | +4.38% | +1.86 | 138 | 1 | 10 |
| V3_BTC — 15m | 203 | 48.8 | $+216.30 | $+1.0655 | +10.76% | +5.51 | 97 | 0 | 3 |
| V3_BTC_P7 — ALL | 900 | 59.6 | $+193.27 | $+0.2147 | +5.31% | +1.95 | 254 | 1 | 16 |
| V3_BTC_P7 — 5m | 685 | 62.9 | $-53.58 | $-0.0782 | +3.31% | -0.59 | 152 | 1 | 12 |
| V3_BTC_P7 — 15m | 215 | 48.8 | $+246.85 | $+1.1481 | +11.71% | +5.99 | 102 | 0 | 4 |

---

## VERDICT

- **V3 alone**:  n= 322  hit=57.1%  total $+417.15  ROI +10.82%/trade
- **BTC_only**:  n= 463  hit=63.5%  total $-42.10  ROI +2.76%/trade
- **P7 alone**:  n= 228  hit=56.1%  total $-278.69  ROI -0.20%/trade
- **V3 ∪ BTC**:        n= 736  hit=60.6%  total $+345.78  ROI +6.14%/trade
- **V3 ∪ BTC ∪ P7**:   n= 900  hit=59.6%  total $+193.27  ROI +5.31%/trade

**Incremental PnL of adding BTC_only to V3**: $-71.37
**Incremental PnL of adding P7 to (V3 ∪ BTC)**: $-152.51

→ **BTC_only is fully captured by V3** (incremental = $-71). V3 already harvests this signal.