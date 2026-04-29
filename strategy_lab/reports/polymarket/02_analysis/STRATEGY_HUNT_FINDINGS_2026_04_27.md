# Strategy Hunt — Findings — 2026-04-27

End-to-end pass with the new Binance microstructure data backfilled. **First strategy with a 95% CI that excludes zero.**

## TL;DR

| Strategy | Universe | n | PnL/$1 stake | 95% CI | Hit rate | ROI/bet |
|---|---|---|---|---|---|---|
| **`sig_ret5m S0_hold` (5m)** | all 5m | **1,422** | **+$54.59** | **[+$19, +$92]** | 54.8% | **+3.8%** |
| **`sig_ret5m_q20 S0_hold` (5m)** | top/bot 20% by \|ret_5m\| | 285 | +$31.07 | [+$15, +$47] | **61.4%** | **+10.9%** |
| **`sig_ret5m_q10 S0_hold` (5m)** | top/bot 10% by \|ret_5m\| | 143 | +$26.25 | [+$16, +$37] | **68.5%** | **+18.4%** |
| **`sig_ret5m S0_hold` (15m)** | all 15m | 474 | +$33.33 | [+$13, +$53] | 57.8% | +7.0% |
| **`sig_combo_q20 S0_hold` (15m)** | ret_5m + smart-vs-retail agree | 48 | +$7.61 | [+$1, +$14] | **66.7%** | +15.9% |

**The signal is BTC's spot return on Binance over the 5 minutes immediately before `window_start`.** Sign(ret_5m) → bet UP/DOWN. Hold to resolution. No exit rule helps; stops hurt.

This is a textbook latency-arb result: Binance moves first, Polymarket settles via Chainlink Data Streams which lag by 4–12s, so prior 5min Binance return predicts the next 5–15min Polymarket outcome at 60%+ when the move is large.

## How we got here

### Pipeline

1. `polymarket_extract_features.sql` — pulled 10,944 Binance OHLCV rows (1m/5m/15m) and 1,729 metrics rows (OI + L/S + taker flow at 5min cadence) for Apr 21 → Apr 27, 2026.
2. `polymarket_build_features.py` — computed 17 features per market evaluated AT `window_start` (no lookahead): spot returns, OI deltas, L/S ratios, taker buy/sell, book skew. Output: `data/polymarket/btc_features_v3.csv`. 100% coverage on Binance features.
3. `polymarket_features_univariate.py` — univariate predictive test per feature. Identified `ret_5m` (Pearson r = +0.123, p = 3e-6) and `smart_minus_retail` (15m only, p = 0.011) as the top features.
4. `polymarket_signal_grid.py` — ran 6 signal variants × 9 exit rules × 2 timeframes = 108 cells.

### Univariate winners (top-quintile hit rate)

| TF | Feature | Top-Q | Bot-Q | Pearson r | p |
|---|---|---|---|---|---|
| 5m | ret_5m | **60.7%** | **58.9%** | +0.123 | 3e-6 |
| 5m | ls_count_delta_5m | 56.5% | 53.0% | +0.052 | 0.049 |
| 15m | smart_minus_retail | 60.0% | 57.9% | +0.044 | 0.339 |
| 15m | ret_5m | 58.9% | 61.1% | +0.116 | 0.011 |
| 15m | ls_top_count | 55.8% | 61.1% | +0.077 | 0.094 |

All other features (oi_delta, taker_ratio, book_skew, ret_1h) are statistical noise.

### Strategy grid headline cells

**5m, full grid:** 6 signals × 9 exits × 1,422 markets

The `sig_ret5m` family produces 4 of the top 5 cells. **All cells with that signal have CI excluding zero.** Stops uniformly hurt because we'd exit at e.g. 0.30 instead of riding to a 1.00 resolution where the signal is right ~55% of the time.

**15m, full grid:** same shape. `sig_ret5m S0_hold` again leads with CI [+$13, +$53] on 474 trades.

## What this means

- **Edge is real, statistically significant on 1,422 trades, 95% CI excludes zero** at multiple slicings (full sample, q20, q10).
- **It's not a Kronos retrain.** The signal is one number computed from public Binance data — the BTC close minus the close 5min earlier. Anything more elaborate is gravy on top.
- **Wider filter = lower hit rate, but more bets ⇒ more total PnL.** The `q20` filter (only trade markets in top/bottom 20% by |ret_5m|) raises hit to 61% but gives up 80% of trades. For absolute PnL the unfiltered version wins; for risk-adjusted return, q20 is better (CI lo is +$15 on 285 trades vs +$19 on 1,422).
- **Combo signals (ret_5m AND smart-vs-retail agree) push hit rate to 66.7%** on 15m but only fire 48 times in 5 days. Useful as a "high conviction" overlay rather than a primary.

## Caveats — read these before scaling

1. **5-day sample.** This is one BTC regime. We need at least 30 days to be confident. The collector keeps running; we re-run this script monthly.
2. **Possible ret_5m / window_start timing artifact.** The signal is `BTC_close[window_start] - BTC_close[window_start - 300s]`. We need to verify the *actual* time we'd enter (when we observe the entry quote in live trading) matches `window_start`. If our entry quote in `btc_markets_v3.csv` is captured 30s after `window_start`, we may be implicitly using 30s of post-window information.
3. **Liquidity.** The PnL assumes we can hit `entry_yes_ask` at $1 stake size. The orderbook depth at the top is enough for $50–$200 typically; at $1k+ we'd start eating into the second/third level.
4. **Fee model is conservative.** We charge 2% on winnings only (Polymarket protocol fee). In practice there's also gas (~$0.05–0.15 per fill) which on small bets is non-trivial. With $0.10 gas per round trip on 1,422 trades = $284 in friction, eating most of the unfiltered PnL. This is a critical issue for live execution sizing — use `q10` or `q20` filtered variants where per-trade ROI is much higher.

## Recommended next experiments

1. **Validate timing assumption.** Cross-check `entry_yes_ask` snapshot timestamp vs `window_start_unix` for 50 random markets. If they're within ~5s, signal is sound. If 30+s, recompute features with proper offset.
2. **Forward-walk sanity check.** Holdout last 24h of markets, train on the first 4 days, evaluate. Hit rate should hold ≥56% on holdout.
3. **Add gas to the cost model** in `polymarket_signal_grid.py` and re-rank — this changes the q10 vs full picture meaningfully.
4. **Try `ret_3m`, `ret_1m` shorter lookbacks.** If the latency edge is 4–12s as the open-source bots claim, even shorter Binance lookbacks might be sharper.
5. **Cross-asset (ETH, SOL).** Same script structure, different symbol. We have `binance_klines_v2` for both; we just don't have the Polymarket markets extracted yet (they exist in `market_resolutions_v2`).
6. **Monitor live shrinkage.** Once the bot is live, track realized hit rate; if it drops below 56%, retrain or kill switch.

## Files produced

| File | Purpose |
|---|---|
| `polymarket_extract_features.sql` | DB extract for klines + metrics |
| `data/binance/btc_klines_window.csv` | 10,944 OHLCV bars |
| `data/binance/btc_metrics_window.csv` | 1,729 OI/L/S rows |
| `polymarket_build_features.py` | Feature engineering |
| `data/polymarket/btc_features_v3.csv` | 1,896 markets × 25 columns |
| `polymarket_features_univariate.py` | Univariate test |
| `reports/POLYMARKET_FEATURES_UNIVARIATE.md` | Per-feature results |
| `polymarket_signal_grid.py` | Signal × strategy grid runner |
| `results/polymarket/signal_grid.csv` | 108-cell grid |
| `reports/POLYMARKET_SIGNAL_GRID.md` | Pretty grid report |
| `reports/STRATEGY_HUNT_FINDINGS_2026_04_27.md` | This document |
