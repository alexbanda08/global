# Microstructure Filter (E4)

Hypothesis: skip thin-book / wide-spread markets to lift signal-to-fee ratio.
q10 universe (n=509 after dropping markets without book at bucket 0). Hedge-hold rev_bp=5.


## Microstructure feature distribution at bucket 0

- spread_pct: median 2.15% (p25 1.87%, p75 3.92%)
- top_size_usd: median $25 (p25 $7, p75 $86)
- n_levels_ask: median 10 (min 10, max 10)

## Variant grid

| Variant | n | Hit% | ROI | vs baseline | Volume kept |
|---|---|---|---|---|---|
| baseline (baseline) | 509 | 84.3% | +26.15% | +0.00pp | 100% |
| spread_lt_4pct | 383 | 83.8% | +25.94% | -0.21pp | 75% |
| spread_lt_2pct | 180 | 91.1% | +30.69% | +4.53pp | 35% |
| top_size_gt_25usd | 255 | 83.5% | +25.81% | -0.34pp | 50% |
| top_size_gt_100usd | 117 | 85.5% | +27.86% | +1.70pp | 23% |
| n_levels_ge_5 | 509 | 84.3% | +26.15% | +0.00pp | 100% |
| n_levels_ge_8 | 509 | 84.3% | +26.15% | +0.00pp | 100% |
| combined_quality | 220 | 82.7% | +25.52% | -0.63pp | 43% |
| combined_strict ★ | 45 | 88.9% | +32.37% | +6.21pp | 9% |

## Cross-asset breakdown — best `combined_strict` vs baseline

| Asset | TF | best n | best ROI | baseline ROI | Δ |
|---|---|---|---|---|---|
| ALL | ALL | 45 | +32.37% | +26.15% | +6.21pp |
| ALL | 5m | 37 | +36.06% | +26.33% | +9.73pp |
| ALL | 15m | 8 | +15.29% | +25.57% | -10.28pp |
| btc | ALL | 40 | +33.01% | +29.28% | +3.73pp |
| btc | 5m | 34 | +36.39% | +30.55% | +5.84pp |
| btc | 15m | 6 | +13.83% | +25.02% | -11.19pp |
| eth | ALL | 4 | +25.76% | +26.68% | -0.93pp |
| eth | 5m | 2 | +31.83% | +26.47% | +5.36pp |
| eth | 15m | 2 | +19.68% | +27.38% | -7.70pp |
| sol | ALL | 1 | +33.26% | +22.48% | +10.78pp |
| sol | 5m | 1 | +33.26% | +21.97% | +11.29pp |

## Day-by-day — best `combined_strict` vs baseline

| Date | best n | best ROI | baseline ROI | Δ |
|---|---|---|---|---|
| 2026-04-22 | 7 | +36.67% | +24.92% | +11.75pp |
| 2026-04-23 | 21 | +31.95% | +25.34% | +6.61pp |
| 2026-04-24 | 11 | +28.86% | +26.65% | +2.21pp |
| 2026-04-26 | 6 | +35.25% | +27.12% | +8.13pp |

## Verdict

**Criteria: 3/3**
  - In-sample lift > 0: ✅ (+6.21pp)
  - Cross-asset (≥2/3): ✅ (2/3)
  - Day stability (≥4/5): ✅ (4/4)

⚠️ Worth forward-walk validation.