# Microstructure Filter (E4)

Hypothesis: skip thin-book / wide-spread markets to lift signal-to-fee ratio.
q10 universe (n=727 after dropping markets without book at bucket 0). Hedge-hold rev_bp=5.


## Microstructure feature distribution at bucket 0

- spread_pct: median 2.20% (p25 1.90%, p75 4.26%)
- top_size_usd: median $22 (p25 $6, p75 $76)
- n_levels_ask: median 10 (min 10, max 10)

## Variant grid

| Variant | n | Hit% | ROI | vs baseline | Volume kept |
|---|---|---|---|---|---|
| baseline (baseline) | 727 | 83.8% | +27.06% | +0.00pp | 100% |
| spread_lt_4pct | 525 | 83.8% | +27.08% | +0.02pp | 72% |
| spread_lt_2pct ★ | 233 | 89.7% | +30.87% | +3.80pp | 32% |
| top_size_gt_25usd | 336 | 83.3% | +26.80% | -0.26pp | 46% |
| top_size_gt_100usd | 152 | 80.3% | +25.74% | -1.32pp | 21% |
| n_levels_ge_5 | 727 | 83.8% | +27.06% | +0.00pp | 100% |
| n_levels_ge_8 | 727 | 83.8% | +27.06% | +0.00pp | 100% |
| combined_quality | 278 | 83.8% | +27.05% | -0.01pp | 38% |
| combined_strict | 51 | 84.3% | +30.60% | +3.54pp | 7% |

## Cross-asset breakdown — best `spread_lt_2pct` vs baseline

| Asset | TF | best n | best ROI | baseline ROI | Δ |
|---|---|---|---|---|---|
| ALL | ALL | 233 | +30.87% | +27.06% | +3.80pp |
| ALL | 5m | 174 | +32.77% | +28.02% | +4.75pp |
| ALL | 15m | 59 | +25.24% | +23.76% | +1.48pp |
| btc | ALL | 106 | +34.17% | +28.96% | +5.21pp |
| btc | 5m | 81 | +36.76% | +29.94% | +6.82pp |
| btc | 15m | 25 | +25.77% | +25.53% | +0.24pp |
| eth | ALL | 75 | +30.81% | +27.41% | +3.40pp |
| eth | 5m | 58 | +32.21% | +28.68% | +3.53pp |
| eth | 15m | 17 | +26.04% | +23.13% | +2.92pp |
| sol | ALL | 52 | +24.22% | +24.76% | -0.54pp |
| sol | 5m | 35 | +24.48% | +25.37% | -0.89pp |
| sol | 15m | 17 | +23.67% | +22.66% | +1.00pp |

## Day-by-day — best `spread_lt_2pct` vs baseline

| Date | best n | best ROI | baseline ROI | Δ |
|---|---|---|---|---|
| 2026-04-22 | 18 | +27.64% | +26.55% | +1.09pp |
| 2026-04-23 | 50 | +31.05% | +26.55% | +4.50pp |
| 2026-04-24 | 48 | +32.15% | +26.57% | +5.58pp |
| 2026-04-26 | 25 | +31.90% | +28.18% | +3.72pp |
| 2026-04-27 | 39 | +29.84% | +28.23% | +1.61pp |
| 2026-04-28 | 32 | +26.32% | +22.13% | +4.19pp |
| 2026-04-29 | 21 | +37.86% | +29.30% | +8.56pp |

## Verdict

**Criteria: 3/3**
  - In-sample lift > 0: ✅ (+3.80pp)
  - Cross-asset (≥2/3): ✅ (2/3)
  - Day stability (≥4/5): ✅ (7/7)

⚠️ Worth forward-walk validation.