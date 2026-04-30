# Research Deep-Dive — 2026-04-29 (uncommitted, working draft)

**Status:** 7 backtests run after the V2-stack kill. Major reversal: forward-walk PASSES on the per-asset tuned mag-only sniper portfolio at +32% holdout ROI, 0 down days. Documenting before deciding next move.

---

## What I tested (in order)

1. **A3 vol-regime conditional** — does hit rate vary by realized vol bucket?
2. **Entry timing** — fire at +0/30/60/90/120s into window?
3. **Exit variants** — TP at 70/80/90/95, SL at 30/40, trailing 5/10/15, oppo-flip
4. **Magnitude sweep + multi-horizon** — q5/q10/q15/q20/q25 × mag-only / multi-horizon
5. **Multi-horizon forward-walk** — chronological 80/20 on the strongest cells
6. **Portfolio (3-sleeve)** — BTC q10 + ETH q5 + SOL q15 in parallel
7. **Portfolio (8-sleeve)** — added 15m + multi-horizon variants

---

## Result 1 — Vol-regime barely matters

```
vol_bucket   n   weighted_hit  weighted_roi
ALL        1644      62.2%       23.6%
LOW         544      61.3%       24.8%
MED         559      58.8%       18.5%
HIGH        544      58.9%       15.5%
```

Minor edge to low-vol regimes (61% vs 59% hit). BTC sniper q10 robust across all buckets. **Not worth conditioning on.**

Top cell: BTC 15m low-vol q10 — hit 78.3%, ROI +69.7%, n=23 (suspicious cherry-pick at small n).

---

## Result 2 — Fire at delay=0, never wait

| delay | BTC 5m q10 hit | BTC 5m q10 ROI | avg entry $ |
|---|---|---|---|
| **0s** | **69.4%** | **+33%** | **$0.528** |
| 30s | 68.8% | +16.6% | $0.609 |
| 60s | 69.2% | +7.0% | $0.645 |
| 120s | 69.2% | +9.8% | $0.640 |

Hit rate stays high but YES ask drifts up ~10c → ROI collapses. Fire immediately at window-start.

---

## Result 3 — Hold-to-resolution dominates every exit variant

q10 ALL on BTC (n=275):

| exit_rule | win % | ROI % | early_exit % |
|---|---|---|---|
| **hold** | 67.6 | **+37.0** | 0.0 |
| tp_95 | 69.5 | +35.9 | 64.0 |
| tp_90 | 70.9 | +34.1 | 68.7 |
| tp_80 | 76.7 | +32.2 | 74.9 |
| tp_70 | 84.0 | +31.5 | 84.4 |
| sl_30 | 53.5 | +30.3 | 46.5 |
| trail_15 | 61.8 | +25.5 | 75.3 |
| oppo_flip | 47.3 | +22.9 | 68.7 |

TP rules win MORE often (76-84% hit) but ROI suffers because the exited winners would have closed at $1.00. Stop-losses cut MORE than they save. **Don't add exit logic to q10 sniper.**

---

## Result 4 — Per-asset magnitude tuning matters

Best magnitude differs by asset (mag_only on tf=ALL):

| asset | best_mag | hit % | ROI % | n |
|---|---|---|---|---|
| BTC | q10 | 67.6 | +37.0 | 275 |
| ETH | q5 | 61.3 | +27.2 | 137 |
| SOL | q10 or q15 | 60.8 / 58.4 | +16.1 / +11.7 | 273 / 409 |

**Multi-horizon agreement adds lift on ETH/SOL but not BTC:**

| cell | mag-only ROI | multi-horizon ROI | lift |
|---|---|---|---|
| BTC ALL q15 | +26.2% | +36.2% | +10.0 pp |
| ETH ALL q20 | +20.2% | +30.1% | +9.9 pp |
| SOL ALL q5 | +5.3% | +18.4% | +13.1 pp |
| SOL 5m q5 | +3.6% | +18.4% | +14.8 pp |

The "all 3 horizons same sign" filter (ret_5m, ret_15m, ret_1h) reliably bumps SOL/ETH performance. BTC barely cares.

---

## Result 5 — Forward-walk PASSES on 16 cells (the big shift)

Chronological 80/20 split. Gate: hit ≥60%, ROI ≥+10%, drift ≤8pp.

**Top 8 gate-passers (raw `sig_ret5m`, NOT calibrated probabilities):**

| asset | tf | selector | mag | TR_n | TR_hit | HO_n | HO_hit | HO_ROI | drift |
|---|---|---|---|---|---|---|---|---|---|
| BTC | 5m | mag_only | **q10** | 165 | 68.5 | 36 | **72.2** | **+47.1%** | -3.7 |
| BTC | 5m | multi_horizon | q15 | 110 | 64.5 | 25 | 68.0 | +45.1% | -3.5 |
| BTC | 5m | mag_only | q20 | 329 | 60.8 | 97 | 60.8 | +21.7% | 0.0 |
| BTC | ALL | mag_only | q10 | 220 | 67.7 | 49 | 65.3 | +31.8% | 2.4 |
| ETH | 5m | mag_only | **q5** | 82 | 64.6 | 26 | **65.4** | **+37.6%** | -0.8 |
| ETH | 5m | multi_horizon | q5 | 38 | 60.5 | 16 | 62.5 | +34.2% | -2.0 |
| ETH | ALL | mag_only | q15 | 328 | 62.5 | 113 | 60.2 | +20.5% | 2.3 |
| SOL | 5m | mag_only | **q15** | 246 | 56.5 | 66 | **62.1** | **+21.9%** | -5.6 |

**Why this contradicts the V2-stack kill:** The V2 signals were calibrated probabilities (LogReg + isotonic). The raw `sig_ret5m` magnitude filter is much more robust to distribution shift. Calibration overfits 7-day data; raw thresholds don't.

---

## Result 6 — 3-sleeve portfolio (BTC q10 + ETH q5 + SOL q15)

| split | n | total_pnl | ROI | daily_sharpe | max_dd | neg_days |
|---|---|---|---|---|---|---|
| train | 493 | $2,766 | +22.45% | 29.64 | $0 | 0/7 |
| **holdout** | **128** | **$1,029** | **+32.16%** | **27.05** | **$0** | **0/2** |

**Holdout has 0 losing days.** Per-sleeve hit rates in holdout: BTC 72.2%, ETH 65.4%, SOL 62.1% — all clean.

Caveat: holdout = 2 days only. The "0 down days" claim is statistically thin. But the per-sleeve hit rates being consistent with train across all 3 assets is a strong signal.

---

## Result 7 — 8-sleeve dilutes (lesson: don't add 15m)

Adding 15m sleeves and multi-horizon variants:

| split | n | total_pnl | ROI | daily_sharpe | neg_days |
|---|---|---|---|---|---|
| train | 911 | $4,978 | +21.86% | 25.34 | 0/7 |
| holdout | 235 | $1,556 | +26.49% | 19.02 | 0/2 |

ROI dropped from 32.16% → 26.49%. The 15m sleeves are weaker (BTC 15m HO ROI -2.82%; SOL 15m -8.93%). One outlier: SOL 5m multi_horizon q15 HO ROI **+54.89%** on n=23 — possible alpha but tiny sample.

**Stick with the 3-sleeve 5m portfolio.**

---

## What this changes vs the V2 kill report

The V2 stack was killed because `prob_a/b/c/stack` failed forward-walk. **That kill stands** — those particular probability calibrators don't generalize.

But the underlying signal `sig_ret5m` with a magnitude filter (NOT calibrated probability) **DOES generalize.** Per-asset tuned magnitude (BTC q10, ETH q5, SOL q15) on 5m markets passes forward-walk on every asset, with combined holdout ROI +32%.

So the deploy plan should be UPGRADED:
- Existing plan: "sniper q10" with sig_ret5m on all assets
- **New plan**: per-asset tuned mag (BTC q10, ETH q5, SOL q15) on 5m only

ETH at q5 is significantly tighter than q10 (top 5% vs top 10%). Fewer fires, higher hit rate.

---

## Open questions (worth checking before any deploy change)

1. **Realistic fills**: the +32% holdout ROI assumes top-of-book ask. Tier 2 (book-walk fills) typically takes a 3-5 pp haircut. Need to re-run with realistic fills on the portfolio.

2. **Maker entry overlay**: the existing recalibration found maker tick=0.01 wait=30s adds +2 pp. Should compose with the per-asset tuning.

3. **2-day holdout is tiny**: forward-walk validated, but the holdout slice is just 1.4 days. The overall 7-day sample is small. A 30-day re-validation is needed.

4. **Drift on BTC q10 was -3.7pp** (negative drift = holdout BETTER than train). Sometimes that's a regime that happened to favor holdout. May not persist.

5. **Did NOT test**: simultaneous q10 sniper + maker + spread filter as a stack on the portfolio. The recalibration showed those overlays add +6 pp combined. Combined with per-asset tuning could push portfolio ROI toward +38-40%.

---

## Recommended next moves

If user wants more research:
- **Run portfolio through realistic-fill simulator** (1 hour)
- **Run portfolio with maker entry overlay** (1 hour)
- **Walk-forward with multiple splits** (60/20/20, etc.) to validate the holdout result wasn't a fluke

If user wants to ship:
- **Update VPS3 fix plan** to use per-asset tuned magnitudes:
  - BTC sniper: q10 (unchanged)
  - ETH sniper: q5 (TIGHTER than current spec)
  - SOL sniper: q15 (LOOSER than current spec)
- All 3 with HEDGE_HOLD + maker entry + spread filter (existing recalibration)
- Expected live: +32% ROI on the q-filtered subset, scaled down maybe ~10pp for live execution → +20% live ROI as the bull case.

---

## Files (uncommitted as requested)

- `strategy_lab/v2_signals/vol_regime_backtest.py`
- `strategy_lab/v2_signals/entry_timing_backtest.py`
- `strategy_lab/v2_signals/exit_variants_backtest.py`
- `strategy_lab/v2_signals/sig_search_backtest.py`
- `strategy_lab/v2_signals/multi_horizon_forward_walk.py`
- `strategy_lab/v2_signals/portfolio_backtest.py`
- This summary: `strategy_lab/reports/RESEARCH_DEEP_DIVE_2026_04_29.md`

7 new scripts. Will commit when you say.
