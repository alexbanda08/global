# Maker Hedge Strategy — extending maker-entry with maker-side hedge orders

q10 universe (n=579). hedge-hold rev_bp=5. Entry-side wait = 30s (best from prior sweep).
Hedge wait windows tested: 20s / 40s / 60s. Tick improvement: 1¢. Fallback to taker on no-fill.

## Variant grid

| Variant | n | Hit% | ROI | vs T/T baseline | Entry fill | Hedge trigger | Hedge fill | Mean cost |
|---|---|---|---|---|---|---|---|---|
| Tentry / Thedge 0s (baseline) | 509 | 84.3% | +26.15% | +0.00pp | 0% | 56% | 0% | $0.6733 |
| Tentry / Mhedge 20s | 509 | 83.3% | +25.59% | -0.57pp | 0% | 56% | 3% | $0.6790 |
| Tentry / Mhedge 40s | 509 | 82.9% | +25.25% | -0.91pp | 0% | 56% | 3% | $0.6825 |
| Tentry / Mhedge 60s | 509 | 83.1% | +25.13% | -1.02pp | 0% | 56% | 4% | $0.6836 |
| Mentry / Thedge 0s ★ | 509 | 84.7% | +26.81% | +0.66pp | 25% | 56% | 0% | $0.6666 |
| Mentry / Mhedge 20s | 509 | 83.5% | +26.24% | +0.09pp | 25% | 56% | 3% | $0.6724 |
| Mentry / Mhedge 40s | 509 | 83.1% | +25.91% | -0.25pp | 25% | 56% | 3% | $0.6758 |
| Mentry / Mhedge 60s | 509 | 83.3% | +25.79% | -0.36pp | 25% | 56% | 4% | $0.6770 |

## Cross-asset × timeframe — best variant `Mentry / Thedge 0s` vs T/T baseline

| Asset | TF | n | Hit% | best ROI | T/T ROI | Δ |
|---|---|---|---|---|---|---|
| ALL | ALL | 509 | 84.7% | +26.81% | +26.15% | +0.66pp |
| ALL | 5m | 392 | 83.2% | +27.09% | +26.33% | +0.76pp |
| ALL | 15m | 117 | 89.7% | +25.87% | +25.57% | +0.30pp |
| btc | ALL | 170 | 86.5% | +29.52% | +29.28% | +0.24pp |
| btc | 5m | 131 | 86.3% | +30.81% | +30.55% | +0.26pp |
| btc | 15m | 39 | 87.2% | +25.20% | +25.02% | +0.18pp |
| eth | ALL | 170 | 83.5% | +27.26% | +26.68% | +0.58pp |
| eth | 5m | 130 | 80.8% | +27.11% | +26.47% | +0.64pp |
| eth | 15m | 40 | 92.5% | +27.75% | +27.38% | +0.37pp |
| sol | ALL | 169 | 84.0% | +23.64% | +22.48% | +1.16pp |
| sol | 5m | 131 | 82.4% | +23.36% | +21.97% | +1.39pp |
| sol | 15m | 38 | 89.5% | +24.59% | +24.23% | +0.36pp |

## Day-by-day — best variant `Mentry / Thedge 0s` vs T/T baseline

| Date | n | best ROI | T/T ROI | Δ |
|---|---|---|---|---|
| 2026-04-22 | 55 | +25.59% | +24.92% | +0.67pp |
| 2026-04-23 | 210 | +26.12% | +25.34% | +0.77pp |
| 2026-04-24 | 140 | +27.22% | +26.65% | +0.57pp |
| 2026-04-25 | 17 | +31.15% | +31.15% | +0.00pp |
| 2026-04-26 | 87 | +27.76% | +27.12% | +0.64pp |

## Verdict

**Criteria:**
  1. In-sample lift > 0 vs T/T baseline: ✅ (+0.66pp)
  2. Cross-asset agreement (≥2/3): ✅ (3/3)
  3. Day-by-day stability (≥4/5): ✅ (4/5)

**Score: 3/3** — forward-walk validation needed before deploy.

## Decomposition: entry-only vs hedge-only contribution

| Source | ROI | Lift vs T/T |
|---|---|---|
| T/T baseline | +26.15% | — |
| M-entry / T-hedge | +26.81% | +0.66pp |
| T-entry / M-hedge 20s | +25.59% | -0.57pp |
| **Mentry / Thedge 0s (best combo)** | +26.81% | +0.66pp |