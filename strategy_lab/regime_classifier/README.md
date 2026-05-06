# Regime Classifier — daily up/down prediction for crypto majors

**Goal:** binary classifier predicting whether **next UTC day** closes higher
or lower than current close, for BTC/ETH/SOL. Output is a calibrated
probability that doubles as:

  1. **Polymarket scoring** — directly bet "Will BTC close UP today?" markets.
     Polymarket spreads are ~2-3%; we need calibrated p such that
     p_up × payout > 1 + spread.

  2. **Regime overlay** for the existing strategies — gate Bella Fade /
     VWAP-Bounce / derivatives strategies on classifier output.

  3. **Standalone signal** — long when p_up > 0.55, short when p_up < 0.45,
     hold otherwise.

## Why a classifier (not a regressor)?

- Polymarket markets are binary
- Direction is more predictable than magnitude in 5-min crypto data
  (per the regime_detector_v2 GB results — test acc 60-72%)
- Calibration is the real edge, not raw accuracy

## Data sources (all already on disk)

| Source | Resolution | Coverage |
|---|---|---|
| Binance 5m OHLCV | 5min | 2017-2026, BTC/ETH/SOL |
| Derivatives panel | 5min | 2023-2026, BTC/ETH/SOL (LSR, OI, funding, taker ratios, cross-asset) |
| Funding rates | 8h | 2023-2026 |
| Stablecoin mcaps | daily | 2023-2026 |

We aggregate everything to **daily** resolution (last value of UTC day) and
build a feature matrix where row `t` = day, columns = current-state +
historical-window summaries.

## Feature design (target ~60-100 features)

### Price-action (5m → daily aggregates)
- Returns over [1, 3, 7, 30] days
- Realized vol over [7, 14, 30] days (annualized)
- High-low range / mid for [1, 7] days (compression vs expansion)
- Distance to MA_20 / MA_50 / MA_200 (% above/below)
- Position in Bollinger band (z-score of close vs BB(20, 2))
- ADX(14) — trend strength
- RSI(14)

### Volume / money flow (from features.py module)
- OBV slope (5d, 20d)
- CMF (20-bar daily)
- MFI (14-bar daily)
- Volume z-score (today vs 30-day median)
- Cumulative delta-of-day (last UTC day)
- Aggression imbalance (fraction of intraday bars buyer-dominant)

### Volume profile
- Distance from POC (rolling 60-bar daily window)
- Inside/outside value-area flag

### Derivatives (from existing 5m panel)
- z_lsr (current value, 5d slope)
- z_top_lsr_count
- brigalS
- cross_institutional_lead, cross_retail_lead, cross_leverage_heat
- z_oi, z_oi_silent
- z_taker_ratio
- funding_rate (current 8h, 7d avg)

### Cross-asset
- BTC 1d return - ETH 1d return (relative strength)
- BTC 1d return - SOL 1d return
- ETH 1d return - SOL 1d return

### Calendar
- Day-of-week (one-hot)
- Days to weekend
- Hour of US market close (most volatility tends to cluster around 21:00 UTC)

## Target

For each (asset, day_t):
- target = 1 if close[day_t+1] > close[day_t] else 0
- evaluation: what would betting on the predicted side make us
  vs naive "always UP" baseline (BTC has ~55% up-days historically)

## Model

**HistGradientBoostingClassifier** (sklearn) — same model class that hit
60-72% test accuracy in `regime_detector_v2.py`. Hyperparams:
  - max_iter=300, learning_rate=0.05, max_depth=5
  - early_stopping=True, validation_fraction=0.15
  - class_weight="balanced"

## Validation

Walk-forward, anchored:
  - Train on 2 years (730 days)
  - Predict next 90 days
  - Roll forward 90 days, retrain, predict next 90, etc.
  - 8-12 folds expected over 2023-2026

For each fold, record:
  - Accuracy, log-loss, Brier score
  - Calibration plot (predicted prob vs realized frequency)
  - Polymarket EV at various confidence thresholds

## Calibration

Raw GB output is overconfident. We apply **Platt scaling** (or isotonic
regression) on each fold's training set, fit on train, apply to test.

## Polymarket scoring

For a binary market with $1 payout if UP, market price p_market, our
estimate p_us:
  - Bet UP if p_us > p_market + spread/2 (~ p_market + 0.015)
  - Bet DOWN if p_us < p_market - spread/2

Polymarket "Bitcoin Up or Down" market historically shows the prediction
hovering ~50-55%. If our calibrated p_us routinely lands at 60%+ with a
real 60% hit rate, that's deployable edge.

## Pipeline

```
strategy_lab/regime_classifier/
  README.md             (this file)
  feature_engineering.py — assemble daily feature matrix per asset
  train.py              — walk-forward GB classifier + calibration
  polymarket_backtest.py — Polymarket-style EV score on OOS predictions
  inspect.py            — feature importance + calibration plots

strategy_lab/reports/regime_classifier/
  features_{sym}.parquet     (full feature matrix per asset)
  predictions_{sym}.parquet  (OOS predictions: timestamp, p_up, realized)
  feature_importance.csv     (cross-asset, cross-fold permutation importance)
  calibration_{sym}.csv      (binned predicted-vs-realized)
  polymarket_results.csv     (per-asset EV at thresholds 0.55, 0.60, 0.65)
  SUMMARY.md
```

## Success criteria

- **Test accuracy ≥ 56%** across all 3 assets (vs ~52% naive baseline of
  always-up). Each percentage point matters: 56% × 2 - 1 = +12% per-bet edge.
- **Calibration Brier score ≤ 0.245** (perfect calibration = 0.21).
- **Polymarket EV per bet ≥ +1.5%** at threshold p > 0.58 (after 2% spread).
- **Walk-forward stability**: no fold should be worse than 50% accuracy.

If we hit those, the classifier is deployable on Polymarket AND useful as a
regime overlay on every other strategy in the lab.
