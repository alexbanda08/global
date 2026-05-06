# Phase 9 Lookahead — Engine-Faithful Test

_Generated: 2026-05-05_

## What this is

Re-runs Phase 9 entries through the **same engine semantics that `combined_gate_v2.py` uses for the published +143.60 / 77.7% number**, but with five competing gates so we can isolate how much of P9's edge is just same-window BTC momentum.

## Engine semantics

- **Gate firing**: top-10% percentile threshold on each gate's score (matches `combined_gate_v2`)
- **Direction**: sign of the gate's score (procyclic for TFI/resid/BTC)
- **Engine A (mid-fill)**: entry @ $0.50, $0.01 fixed fee → win=+$0.49 / loss=−$0.51 (combined_gate_v2 default)
- **Engine B (book-walk)**: entry @ `ask_price_0` at `bucket_10s=0`, 2% taker per side; resolves at $1/$0

## Data

- Active universe: 3070 markets (2302 5m, 768 15m), all with ≥1 trade in 2m + BTC return + P9 features
- BTC 1m bars: 16113
- Median ask_price_0 (Up token):   $0.500
- Median ask_price_0 (Down token): $0.510
- Markets missing book@bucket_0:   505 (16.4%)

## OLS used to build residual

- `poly_tfi_2m = +0.0084 + (+238.94) · btc_ret_2m + ε`
- Residual (`poly_tfi_2m_resid`) is the part of TFI not explained by same-window BTC return.

## Head-to-head — ENGINE A (mid-fill)

| Gate | n | hit | ROI | total PnL | avg ask |
|---|---:|---:|---:|---:|---:|
| G1 P9_orig (top-10% |TFI|) | 307 | 79.2% | +56.3% | $+86.43 | $0.568 |
| G2 BTC_only (top-10% |btc_ret_2m|) | 307 | 86.0% | +70.0% | $+107.43 | $0.547 |
| G3 P9_resid (TFI − OLS(BTC)) | 307 | 54.7% | +7.4% | $+11.43 | $0.528 |
| G4 P9 ∩ AGREE | 282 | 83.0% | +64.0% | $+90.18 | $0.571 |
| G5 P9 ∩ DISAGREE | 25 | 36.0% | -30.0% | $-3.75 | $0.516 |
| G1 P9_orig — 5m | 231 | 85.3% | +68.6% | $+79.19 | $0.591 |
| G2 BTC_only — 5m | 231 | 90.5% | +79.0% | $+91.19 | $0.550 |
| G3 P9_resid — 5m | 231 | 64.5% | +27.0% | $+31.19 | $0.556 |
| G1 P9_orig — 15m | 77 | 67.5% | +33.1% | $+12.73 | $0.523 |
| G2 BTC_only — 15m | 77 | 74.0% | +46.1% | $+17.73 | $0.539 |
| G3 P9_resid — 15m | 77 | 50.6% | -0.7% | $-0.27 | $0.494 |

## Head-to-head — ENGINE B (book-walked, realistic fills)

| Gate | n | hit | mean PnL | total PnL |
|---|---:|---:|---:|---:|
| G1 P9_orig (top-10% |TFI|) | 230 | 79.2% | $+0.2338 | $+53.78 |
| G2 BTC_only (top-10% |btc_ret_2m|) | 263 | 86.0% | $+0.2935 | $+77.20 |
| G3 P9_resid (TFI − OLS(BTC)) | 233 | 54.7% | $+0.0106 | $+2.47 |
| G4 P9 ∩ AGREE | 216 | 83.0% | $+0.2692 | $+58.14 |
| G5 P9 ∩ DISAGREE | 14 | 36.0% | $-0.3117 | $-4.36 |
| G1 P9_orig — 5m | 190 | 85.3% | $+0.2809 | $+53.37 |
| G2 BTC_only — 5m | 207 | 90.5% | $+0.3423 | $+70.85 |
| G3 P9_resid — 5m | 194 | 64.5% | $+0.0819 | $+15.89 |
| G1 P9_orig — 15m | 48 | 67.5% | $+0.1539 | $+7.39 |
| G2 BTC_only — 15m | 58 | 74.0% | $+0.1223 | $+7.09 |
| G3 P9_resid — 15m | 48 | 50.6% | $-0.0242 | $-1.16 |

---

## VERDICT

- **G1 P9_orig**  → hit 79.2%, ROI_A +56.3%, total_A $+86.43
- **G2 BTC_only** → hit 86.0%, ROI_A +70.0%, total_A $+107.43
- **G3 P9_resid** → hit 54.7%, ROI_A +7.4%, total_A $+11.43
- **G4 AGREE**    → hit 83.0%, ROI_A +64.0%, total_A $+90.18
- **G5 DISAGREE** → hit 36.0%, ROI_A -30.0%, total_A $-3.75

→ **G2 (BTC alone) ≥ G1 (P9)**: the published Phase 9 edge can be reproduced by simply firing on the same-window BTC return — Polymarket trade flow is redundant.
→ **G3 (residual TFI) is near coin-flip**: the BTC-purged component of Phase 9 has no meaningful predictive power. Phase 9's edge is almost entirely BTC momentum.
→ **G5 DISAGREE worse than coin-flip**: when TFI contradicts BTC, P9 is actively bad — confirming P9 alone is unreliable.