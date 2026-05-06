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
| V3 vs BTC | 288 | 426 | 42 | 0.056 |
| V3 vs P7 | 302 | 204 | 28 | 0.052 |
| BTC vs P7 | 432 | 196 | 36 | 0.054 |

On V3 ∩ BTC_only fires (n=42), V3 and BTC_only directions **agree** on 42.9% of markets.

## Engine results — entry @ t+120s, real fills, hedge-hold

| Gate | n | hit% | total PnL | mean PnL | ROI/trade | Sharpe | hedged | thin | no_book |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| V3_alone — ALL | 322 | 61.5 | $+641.97 | $+1.9937 | +11.51% | +11.22 | 60 | 0 | 8 |
| V3_alone — 5m | 238 | 64.3 | $+449.12 | $+1.8870 | +9.73% | +8.86 | 27 | 0 | 6 |
| V3_alone — 15m | 84 | 53.6 | $+192.86 | $+2.2959 | +16.53% | +7.33 | 33 | 0 | 2 |
| BTC_only — ALL | 454 | 85.5 | $+4931.64 | $+10.8626 | +42.65% | +21.31 | 158 | 1 | 13 |
| BTC_only — 5m | 328 | 87.5 | $+3947.13 | $+12.0339 | +47.83% | +17.17 | 89 | 1 | 7 |
| BTC_only — 15m | 126 | 80.2 | $+984.51 | $+7.8136 | +29.16% | +38.75 | 69 | 0 | 6 |
| P7_alone — ALL | 228 | 60.5 | $+2.46 | $+0.0108 | +3.26% | +0.04 | 37 | 0 | 4 |
| P7_alone — 5m | 212 | 60.4 | $-125.72 | $-0.5930 | +0.52% | -2.08 | 30 | 0 | 3 |
| P7_alone — 15m | 16 | 62.5 | $+128.19 | $+8.0116 | +39.59% | +7.38 | 7 | 0 | 1 |
| V3_BTC — ALL | 736 | 74.9 | $+5186.18 | $+7.0464 | +29.14% | +21.33 | 209 | 1 | 19 |
| V3_BTC — 5m | 540 | 77.0 | $+4174.04 | $+7.7297 | +31.63% | +17.43 | 113 | 1 | 12 |
| V3_BTC — 15m | 196 | 68.9 | $+1012.15 | $+5.1640 | +22.27% | +24.72 | 96 | 0 | 7 |
| V3_BTC_P7 — ALL | 909 | 72.3 | $+5243.97 | $+5.7689 | +24.44% | +21.00 | 234 | 1 | 22 |
| V3_BTC_P7 — 5m | 703 | 73.5 | $+4220.83 | $+6.0040 | +25.24% | +17.16 | 134 | 1 | 14 |
| V3_BTC_P7 — 15m | 206 | 68.0 | $+1023.14 | $+4.9667 | +21.69% | +24.14 | 100 | 0 | 8 |

---

## VERDICT

- **V3 alone**:  n= 322  hit=61.5%  total $+641.97  ROI +11.51%/trade
- **BTC_only**:  n= 454  hit=85.5%  total $+4931.64  ROI +42.65%/trade
- **P7 alone**:  n= 228  hit=60.5%  total $+2.46  ROI +3.26%/trade
- **V3 ∪ BTC**:        n= 736  hit=74.9%  total $+5186.18  ROI +29.14%/trade
- **V3 ∪ BTC ∪ P7**:   n= 909  hit=72.3%  total $+5243.97  ROI +24.44%/trade

**Incremental PnL of adding BTC_only to V3**: $+4544.21
**Incremental PnL of adding P7 to (V3 ∪ BTC)**: $+57.78

→ **BTC_only adds significant alpha to V3** (+$4544). Worth deploying.