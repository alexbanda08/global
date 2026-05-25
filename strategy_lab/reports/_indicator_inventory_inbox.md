# Indicator / signal / feature code inventory

Generated 2026-05-23 for the overnight research session. Goal: every callable
that produces a numeric feature ready to combine into a meta-strategy, with a
ready-to-call snippet anchored on a single `(slug, ws_s, fire_us, asset, signal)`
fire.

ALL paths absolute. Conventions per `CLAUDE.md`:
- `ws_s = slug_to_ws_s(slug, tf)` — production anchor for v1 momo / F7 RSI
- `fire_us = (ws_s + 120) * 1_000_000` for v1, `(ws_s + 60) * 1e6` for v2
- ws_s/fire_us in **UTC microseconds** unless suffix says otherwise
- Outcome = chainlink (canonical default), optional `clob_winner` overlay
- L25 books loaded with `slugs=` filter to bound RAM

## 0. Canonical data loaders (already-imported by everything below)

`C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical\load.py`

| Function | Returns | Notes |
| --- | --- | --- |
| `load_resolutions(assets, timeframes, source='rtds', with_clob_winner=False)` | DF with `market_id, slug, ticker, timeframe, slot_start_us, slot_end_us, outcome, strike_price, settlement_price, price_source` | universe — chainlink-only |
| `load_klines(asset, source='binance-spot-ws', period_id='1MIN')` | DF `ts_s, time_period_start_us, price_close, price_open, price_high, price_low, volume_traded` | binance-spot-ws / binance-vision / coinbase / kraken / okx |
| `load_klines_asof(asset, source, period_id) -> (end_us[N], price_close[N])` | numpy arrays for searchsorted asof | end_us = time_period_start_us + period_s × 1e6 |
| `load_klines_1s(asset, source)` | 1Hz binance closes | `klines_1s.parquet` |
| `load_chainlink_rtds(asset)` / `load_chainlink_asof(asset)` | 1Hz oracle prices | `chainlink_rtds.parquet` |
| `load_orderbook_l25_streaming(asset, slugs, subsample_1hz=True, min_ts_us, max_ts_us)` | dict[(slug,outcome)] → (ts_us[N], ap[N,25], asz[N,25], bp[N,25], bsz[N,25]) | pass slugs= or you'll OOM |
| `load_tier1_entries(asset)` | DF per (slug,outcome) at t+120 | already-built L25 snapshot table |
| `load_trades(asset)` | Polymarket trade prints DF (`slug, outcome, timestamp_us, price, size, side`) | STALE — Apr 22 → May 6 only per CLAUDE |
| `load_chainlink_asof(asset) -> (ts[N], price[N])` | asof arrays | settlement price |
| `load_binance_metrics(symbol)` | OI, long/short, taker vol ratio (5-min) | 1y |
| `load_binance_vision_klines(asset, period_id)` | 1m/5m/15m/1h/4h/1d historical | 1y |
| `load_hyperliquid_klines / _trades / _liquidations / _liquidations_full / _funding / _metrics` | HL perp data | |
| `load_cryptocap_dominance(symbol_id, period_id)` | BTC.D, ETH.D, total cap | 12y |
| `load_trading_events(kind, sleeve_id_like)` | VPS3 `trading.events` (30d, ~173k) | `kind='poly_updown_resolution'` for production paper fires |
| `slug_to_ws_s(slug, tf)` / `add_ws_s(df)` | ws_s seconds | window_s = 300 (5m) or 900 (15m) |
| `asof_strict(end_us, price_close, target_us) -> float` | causal close-of-bar lookup | wraps searchsorted |
| `ret_log(end_us, prices, t0_us, t1_us)` / `ret_2m_at_ws(end_us, prices, ws_s)` | log returns | production ret_2m anchor |

```python
import sys; sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
from load import (load_resolutions, load_klines_asof, load_orderbook_l25_streaming,
                  load_trades, load_chainlink_asof, load_klines_1s,
                  asof_strict, slug_to_ws_s, add_ws_s, ret_2m_at_ws,
                  load_trading_events, load_binance_metrics,
                  load_hyperliquid_funding, load_hyperliquid_liquidations)
```

---

## 1. CVD (cumulative volume delta)

### 1.1 CVD on binance 1s — production-grade
`strategy_lab\markov_filter\_cvd_timing_overlay.py::build_cvd_table(b_klines_path) -> dict[asset, DF]`

Inputs: `binance_1s_28d.parquet` (cols `symbol_id, time_period_start_us, price_close, volume_traded, taker_buy_base`).
Computes per asset: `signed = 2*taker_buy_base - volume_traded`, `cvd = cumsum(signed)`, `cvd_slope_30s`, `cvd_slope_60s`, `sigma_60s` (rolling 60s std of 1s log-returns). PRODUCTION-grade — handles dedupe, nan, sort, 5s asof tolerance.

```python
import pandas as pd, numpy as np
from pathlib import Path
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
KL = ROOT / "data/v4/canonical/klines_1s/binance_1s_28d.parquet"
import sys; sys.path.insert(0, str(ROOT/"strategy_lab/markov_filter"))
from _cvd_timing_overlay import build_cvd_table       # heavy: 3-asset load
cvd_tab = build_cvd_table(KL)                          # dict['btc'|'eth'|'sol'] -> DF
# At a single fire (asset='btc', ws_s, fire_us):
sub = cvd_tab['btc']
i = np.searchsorted(sub.ts_kline.values, fire_us, side='right') - 1
cvd_slope_30s = float(sub.cvd_slope_30s.values[i])     # signed: + = net buy pressure
sigma_60s     = float(sub.sigma_60s.values[i])
```

### 1.2 CVD on polymarket trades — over fire window
`strategy_lab\discovery_2026_05_16\strat_A1_cvd_5m.py::compute_cvd_per_market(trades, slug, signal_us, fire_us) -> float`

Sums `signed_notional = price*size, BUY=+ SELL=-` on the UP-side trade prints in `[signal_us, fire_us)`. Production-grade for the 5m strategy. Trades are filtered to `outcome=='Up'` then grouped by slug.

```python
from load import load_trades
trades = load_trades(asset.lower())                # cols slug,outcome,timestamp_us,price,size,side
from discovery_2026_05_16.strat_A1_cvd_5m import compute_cvd_per_market
ws_s = slug_to_ws_s(slug, '5m'); signal_us = ws_s*1_000_000; fire_us=(ws_s+120)*1_000_000
cvd_obs = compute_cvd_per_market(trades, slug, signal_us, fire_us)   # USD signed
signal = "UP" if cvd_obs > 100 else ("DOWN" if cvd_obs < -100 else "SKIP")   # T sweeps in {0,50,100,200,500,1000}
```

### 1.3 CVD on polymarket trades — pre-entry rolling
`strategy_lab\discovery_2026_05_16\refine_H_cvd_filter.py` (inline, lines 36-91)

Per fire, builds per-slug numpy arrays once: `ts, sz, side` indexed by `(slug, outcome)`. Then for each fire computes `cvd_up_5min`, `cvd_dn_5min` over `[entry_us-300s, entry_us)`. Scratch; copy the inner loop into your own driver.

### 1.4 CVD as part of flow_score — production-grade
`strategy_lab\confluence\flow\features.py::compute_trade_features(trades_df, query_ts_us, side) -> dict` returns `cvd_1m, cvd_5m, aggressor_ratio_30s, momentum_30s`.

```python
from confluence.flow.features import compute_trade_features
sub = trades[(trades.slug==slug) & (trades.outcome=='Up')]
feats = compute_trade_features(sub, fire_us, 'Up')
# feats['cvd_1m'], feats['cvd_5m'] in signed share-volume units
```

### 1.5 CVD on polymarket trades for production momo overlay
`strategy_lab\meta_classifier\momo_filter_overlay.py::attach_cvd_features(df, lookback_s=60) -> DF` — production overlay used in F8 filter. Joins by `condition_id`, computes `cvd_60s_up`, `cvd_60s_dn` at `ws_s`. Heavy parquet streaming; OK for batch.

---

## 2. RSI

### 2.1 PRODUCTION RSI(14) Wilder simple-mean — pure
`strategy_lab\markov_filter\_vps3_pull\prod_strategies\rsi.py`
- Class `RSI14()` with `.update(close)`, `.value` (streaming, deque(maxlen=14))
- Function `compute_rsi_14(closes: list[float]) -> float`

This is **the exact production module copied from VPS3** (`/opt/tradingvenue/backend/app/engine/rsi.py`). Log-return-based Wilder simple-mean. Pure / no IO. Edge cases handled (constant prices → 100; constant declines → 0; NaN before 14 bars).

```python
import sys
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\markov_filter\_vps3_pull\prod_strategies")
from rsi import compute_rsi_14
# At a single fire — need 15 binance 1-min closes ending at ws_s (PRODUCTION ANCHOR)
end_us, close = load_klines_asof(asset, "binance-spot-ws", "1MIN")
offsets = list(range(-840, 1, 60))   # -840s .. 0s, 15 bars; matches production
closes = [asof_strict(end_us, close, ws_s*1_000_000 + off*1_000_000) for off in offsets]
rsi14 = compute_rsi_14(closes)        # float in [0,100], NaN if any close <= 0
```

### 2.2 Vectorized RSI(14) — for batch backtests
`strategy_lab\meta_classifier\momo_filter_overlay.py::attach_kline_features(df) -> DF`

Computes `rsi_14` via `np.cumsum` rolling 14-bar window across the entire kline series. ~100× faster for large universes; clipped to 50 when `roll_dn == 0`. Same formula as production.

```python
from meta_classifier.momo_filter_overlay import attach_kline_features
df = attach_kline_features(df)    # in-place adds bin_close_ws, bin_ret_60s, bin_ret_120s, abs_ret_60s, rsi_14, coin_*, kraken_*
```

### 2.3 RSI(14) anchored at fire_us — inline
`strategy_lab\meta_classifier\vwap_continuation_v2_gated.py::rsi_at_anchor(end_us, close, anchor_us) -> float` — production-matching simple-mean Wilder, uses 15 closes at offsets `[-840, -780, ..., 0]` from anchor_us. Drop-in for ANY anchor (ws_s, fire_us, slot_start).

### 2.4 F7 RSI agreement gate — PRODUCTION
`strategy_lab\markov_filter\_vps3_pull\prod_strategies\polymarket\f7_gate.py`
- `f7_basic_passes(signal, rsi_14)` — UP needs RSI>50, DOWN needs RSI<50
- `f7_extreme_passes(signal, rsi_14)` — UP>60, DOWN<40
- `f7_passes(signal, rsi_14, mode='off'|'basic'|'extreme')` — dispatcher
- `decision_label(signal, rsi_14, mode)` — audit label

```python
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\markov_filter\_vps3_pull\prod_strategies\polymarket")
from f7_gate import f7_passes
keep = f7_passes(signal, rsi14, mode='basic')    # True/False
```

---

## 3. MACD

NOT FOUND as a standalone function anywhere in strategy_lab. The momo_variants pipeline computes `ret_2m` as the directional signal but no `12-26-9` style EMA / MACD module exists. Closest substitutes:
- `confluence/flow/features.py::compute_trade_features` → `momentum_30s` (vwap vs prior vwap, last 60s)
- `meta_classifier/momo_filter_overlay.py::attach_kline_features` → `bin_ret_60s`, `bin_ret_120s` log-returns

If MACD is wanted, talib is already installed (`features_15m.py` imports `talib`); use `talib.MACD(closes, fastperiod=12, slowperiod=26, signalperiod=9)`.

---

## 4. Markov regime classifier (production-grade)

`strategy_lab\markov_filter\markov_regime_micro.py`
- States: `BEAR=0, SIDEWAYS=1, BULL=2`
- `label_regimes_vol_adaptive(closes, window_bars, bars_per_day=1440, calib_lookback_days=14) -> int8[]` — q33/q66 per-asset per-bar
- `label_regimes_fixed(closes, window_bars, threshold) -> int8[]`
- `build_transition_matrix(labels) -> 3x3` MLE
- `stationary_distribution(P) -> 3-vec`
- `regime_at_us(end_us, labels, target_us) -> int` — causal asof
- `transition_matrix_asof(end_us, labels, target_us) -> 3x3` — causal MLE up to target
- `markov_signal_at_us(end_us, labels, target_us) -> (regime, p_bull-p_bear)`
- `build_labels_for_asset(asset, window_bars=20, mode='vol_adaptive', fixed_threshold=0.003, bar_minutes=1, source='binance-spot-ws', fresh_klines_csv=None) -> (end_us, closes, labels)`

```python
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\markov_filter")
from markov_regime_micro import build_labels_for_asset, regime_at_us, BEAR, BULL
end_us, _, labels = build_labels_for_asset('BTC', window_bars=20, bar_minutes=1, mode='vol_adaptive')
regime = regime_at_us(end_us, labels, fire_us)        # 0/1/2/-1
markov_pass = (signal == 'UP' and regime == BULL) or (signal == 'DOWN' and regime == BEAR)
```

Active stack used everywhere downstream:
- `M1V` = w20 / 1m / vol_adaptive  (the best per `post_f7_real_compare_v2.py`)
- `M5V` = w20 / 5m / vol_adaptive
- `M1F` = w20 / 1m / fixed (thresholds per asset in `_extract_f7_markov.py`)
- `M5F` = w20 / 5m / fixed

Drivers that already use it: `meta_classifier/momo_variants_markov_overlay.py`, `meta_classifier/shadow_11_sleeves_v2.py`, `markov_filter/post_f7_real_compare_v2.py`, `meta_classifier/vwap_continuation_v2_gated.py`. Outputs: `_results/f7_markov_per_sleeve.csv`, `_results/f7_markov_best_per_sleeve.csv`.

---

## 5. Book microstructure

### 5.1 Top-N imbalance + USD depth + walls — PRODUCTION
`strategy_lab\confluence\flow\features.py::compute_book_features(bid_p, bid_s, ask_p, ask_s) -> dict`

Returns: `imb_l1, imb_l5, imb_l10, imb_l25` (positive = bid pressure), `bid_max_size_l10_usd` (wall detection), `depth_l5_usd, depth_l10_usd, depth_l25_usd`. Handles non-finite via sanitization. Pure, side-effect-free.

```python
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab")
from confluence.flow.features import compute_book_features, _book_arrays_from_row
# given a DF row from L25 parquet with columns ask_price_0..24, ask_size_0..24, bid_*:
bp, bs, ap, az = _book_arrays_from_row(row)
feats = compute_book_features(bp, bs, ap, az)        # {imb_l1, imb_l5, imb_l10, imb_l25, bid_max_size_l10_usd, depth_l5_usd, depth_l10_usd, depth_l25_usd}
```

### 5.2 Top-5 imbalance + mid drift + slope — composite at fire
`strategy_lab\discovery_2026_05_16\strat_E_book_micro.py::compute_features_for_market(books, slug, entry_us, side='Up') -> dict`

Returns `imb_up, mid_now, mid_30s_ago, drift_30s, slope_100_1000, spread, ap0, bp0, book_ts_us`. Slope = `walk_asks($1000) - walk_asks($100)` impact. Production-grade for backtests; uses load_orderbook_l25_streaming.

```python
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\discovery_2026_05_16")
from strat_E_book_micro import compute_features_for_market
books = load_orderbook_l25_streaming(asset.lower(), slugs={slug})
feats = compute_features_for_market(books, slug, fire_us, side='Up')
```

### 5.3 Spread / VWAP-slip / book-depth — scratch overlay
`strategy_lab\markov_filter\_microstructure_inline.py` — operates on a pre-computed `fills.csv` (with `best_ask, bid0, vwap, shares` columns). Computes `spread_pct = (best_ask - bid0)/mid`, `vwap_slip = vwap - best_ask`, `log_shares`, per-cell quartile WR overlays. Scratch (output goes to `BOOK_MICROSTRUCTURE_GATES.md`), but the formulas are correct.

### 5.4 Sparse-book filter — PRODUCTION
`strategy_lab\book_filters.py`
- `count_book_events(books_idx, slug, outcome, window_start_us, window_end_us) -> int`
- `filter_by_min_book_events(df, books, min_events=25, ...) -> DF` — PMXT default; drops markets with too few L25 snapshots.

### 5.5 L25 walk fills — PRODUCTION
`strategy_lab\book_walk.py::book_walk_fill(prices, sizes, notional_usd, side='buy') -> (vwap, shares, usd, levels, underfilled)`. Defends against `p>=1 or p<=0`. Used by `engine_v2.fill_at_book`.

### 5.6 Microstructure quality filter (legacy)
`strategy_lab\polymarket_microstructure_filter.py::compute_micro_features(row, book_by_asset) -> dict` returns `spread_pct, top_size_usd, n_levels_ask, n_levels_bid, depth_5lvl_usd`. Operates on the older 10-level book_depth_v3 CSV; use 5.1 above for L25 data.

---

## 6. VWAP

### 6.1 15m-anchored VWAP from binance 1s — production-grade
`strategy_lab\meta_classifier\anchored_vwap_fade_5m.py::build_per_asset_arrays(df_1s) -> dict`
`strategy_lab\meta_classifier\vwap_continuation_5m.py::build_per_asset(df_1s) -> dict`

Both compute per-asset arrays: `ts_us, close, vwap_15m, sigma_per_sqrt_sec`. VWAP anchored to UTC 15m buckets: `bucket = floor(ts_us / (15*60*1e6)) * (15*60*1e6)`, then `vwap = cumsum(px*vol) / cumsum(vol)` within bucket. Sigma = rolling 900-bar std of 1s log-returns.

```python
import sys; sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\meta_classifier")
from vwap_continuation_5m import build_per_asset
KL1S = r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical\klines_1s\binance_1s_28d.parquet"
import pandas as pd; df_1s = pd.read_parquet(KL1S)
arrs = build_per_asset(df_1s)        # arrs['BTC'] = {'ts_us', 'close', 'vwap_15m', 'sigma_per_sqrt_sec'}
import numpy as np
sub = arrs['BTC']
i = np.searchsorted(sub['ts_us'], fire_us, side='right') - 1
dev_bps = 10_000 * np.log(sub['close'][i] / sub['vwap_15m'][i])   # >0 = price extended above VWAP
```

### 6.2 Rolling trade VWAP (last 30s) — used by flow_score
`compute_trade_features` (see §1.4) returns `momentum_30s = (vwap_last_30s - vwap_prior_30s) / vwap_prior_30s`. Pure.

### 6.3 Rolling regression slope (1h / 4h)
`strategy_lab\confluence\structure\btc_trend.py`
- `rolling_slope_norm(closes) -> float` — OLS slope / mean(closes), unit 1/step
- `compute_trend_slopes(btc_kline, ws_unix_arr, minutes_1h=60, minutes_4h=240) -> (slope_1h_arr, slope_4h_arr)`
- `realized_vol_1h(btc_kline, ws_unix, minutes=60) -> float` — std of 1m log-returns

Production-grade, end-time-indexed, vectorizable.

---

## 7. OBV / volume profile

NOT FOUND. Closest substitutes:
- `volume_traded` per-bar in `load_klines` and `load_klines_1s`
- CVD ≈ OBV-like cumulative net flow (§1 above)
- VWAP anchored on volume (§6 above)
- `compute_book_features` USD-depth aggregates (§5.1)

talib provides `talib.OBV(close, volume)` if needed.

---

## 8. HMM / advanced regime classifiers

### 8.1 HMM — searched, not present
No `hmm_adaptive.py` or `regime_classifier/` folder found. Closest available:
- `strategy_lab\markov_filter\markov_regime_micro.py` — 3-state MLE Markov (§4)
- `strategy_lab\confluence\structure\regime_classifier.py` — rule-based hysteresis (§8.2)

### 8.2 Rule-based regime classifier (TREND/SIDEWAYS/VOLATILE) — PRODUCTION
`strategy_lab\confluence\structure\regime_classifier.py`
- `classify_regime_series(slope_1h_arr, vol_1h_arr, vol_thresh=0.0040, slope_thresh=4.0e-5, hysteresis_bars=5, initial='sideways') -> ndarray[str]`
- `regime_factor(regime) -> 0.3 / 0.0 / -0.3`

Causes:
- vol_high → 'volatile'
- |slope| high → 'trend'
- else → 'sideways'
Hysteresis: 5 consecutive raw labels required before flipping.

```python
from confluence.structure.btc_trend import compute_trend_slopes, realized_vol_1h
from confluence.structure.regime_classifier import classify_regime_series, REGIME_TREND, REGIME_VOLATILE
btc = load_klines('BTC')  # cols ts_s, price_close
slopes_1h, slopes_4h = compute_trend_slopes(btc, [ws_s])
vol_1h = realized_vol_1h(btc, ws_s)
regimes = classify_regime_series([slopes_1h[0]], [vol_1h])
regime = regimes[0]    # 'trend' / 'sideways' / 'volatile'
```

---

## 9. Cross-asset / cross-venue signals

### 9.1 BTC-leads-altcoin
`strategy_lab\discovery_2026_05_16\strat_F_cross_asset.py::fetch_btc_and_self(asset, fire_us[]) -> (btc_ret, self_ret)`. Computes `(close_now / close_prev) - 1` over 120s for BTC and the row's asset. PRODUCTION-style; uses `asof_strict` + cached `get_klines`.

### 9.2 Coinbase/Kraken premium + agreement
`strategy_lab\meta_classifier\momo_filter_overlay.py::attach_kline_features(df)` returns `coin_ret_60s, premium_ws (= log(coinbase/binance)), kraken_ret_60s, kraken_premium_ws`. F9 in the overlay = 3-venue agreement gate. PRODUCTION-grade.

### 9.3 CryptoCap dominance — loader only
`load_cryptocap_dominance(symbol_id, period_id)` — BTC.D, ETH.D, total cap. No feature builders yet; raw data.

---

## 10. HL liquidation / funding / OI overlays

### 10.1 HL liquidation cascade signal
`strategy_lab\discovery_2026_05_16\strat_C_hl_liqs.py::build_liq_arrays(asset, prefer='auto', window_lo_us, window_hi_us) -> dict`

Returns sorted `ts_us`, `notional`, `long_n`, `short_n`. For each fire: `lookback=[fire-L, fire]`, `net = sum(short_n) - sum(long_n)`. Signal = UP if net > T, DOWN if < -T. Production-style universe driver included.

### 10.2 Funding / OI regime
`strategy_lab\discovery_2026_05_16\strat_D_funding_oi.py::build_features(df_universe, anchor, offset_s)`. Causal asof of: `oi_delta_1h` (binance metrics), `ls_ratio` (top trader), `hl_funding`, `hl_funding_min_4h`, `hl_funding_max_4h`, `hl_funding_cross_4h`.

### 10.3 Liquidation magnet (cluster detection) — PRODUCTION
`strategy_lab\confluence\trigger\liq_magnet.py::compute_liq_magnet(liq_prices_in_window, current_price, asset) -> (active, distance_bps)`. 1-D sliding-window cluster detection; min cluster size 3; per-asset radius (BTC $200 / ETH $40 / SOL $2). `filter_liq_window(liq_df, query_ts_us, lookback_s=3600)` → np.array of prices.

### 10.4 Trade-flow OFI (held-side, 30s) — PRODUCTION
`strategy_lab\confluence\trigger\ofi.py::compute_ofi_30s(trades_df, query_ts_us, window_s=30) -> float in [-1,1]`. Normalized signed volume.

---

## 11. Other tracked production indicators

### 11.1 FVG (Fair Value Gap) — PRODUCTION
`strategy_lab\confluence\trigger\fvg.py::compute_fvg(klines_1m, query_ts_s, lookback_min=30) -> (active, side)` where side is `'up'|'down'|None`. Detects unfilled 3-candle gaps within lookback; end-time-indexed.

### 11.2 S/R swing levels — PRODUCTION
`strategy_lab\confluence\structure\sr_levels.py`
- `extract_swings(kline, window_bars=30) -> DF(ts_s_pivot, ts_s_confirm, level, kind)` — local extremum confirmed by 30 bars each side
- `nearest_distance_bps(swings, kline, ws_unix, lookback_days=5) -> (dist_to_resistance_bps, dist_to_support_bps)`
- `compute_distances_for_universe(swings, kline, ws_unix_arr, lookback_days=5)` — vectorized

### 11.3 Guard filters — PRODUCTION
`strategy_lab\confluence\guard\filters.py`
- `compute_extreme_price(prices)` — block when entry_price < 0.35 or > 0.65
- `compute_dead_market(btc_at_open, btc_at_t90)` — block if |Δ BTC| < $5
- `compute_counter_trend(btc_at_open, btc_at_t120, btc_at_t90, signal)` — block continuation (move>=10 AND vel agrees)
- `compute_choppiness(closes_window)` — Bill Williams CI > 0.70
- `compute_all_guards(...) -> dict[str, ndarray]` — composite

### 11.4 ATR + ADX (Wilder) — PRODUCTION
`strategy_lab\build_features_v3plus.py::wilder_smooth(s, n)` (EMA alpha=1/n), `add_atr_adx(df, n=14) -> DF` (adds `atr_14, atr_pct, adx_14, plus_di_14, minus_di_14`), `add_price_regime_features(df) -> DF` (adds `ma200, price_vs_ma200_pct`). Operates on 5m OHLCV.

### 11.5 talib-driven 15m feature pipeline (BTC perp)
`strategy_lab\features_15m.py` — uses `talib.ATR`, plus oi/funding/premium/liq z-scores. The full feature roster:
- `close_ret_1bar, _4bar, _8bar`, `atr_14`, `realized_vol_24_pct`, `taker_ratio_z_7d`, `oi_pct_chg_4bar, _24bar`, `top_trader_ls_z_7d`, `funding_rate_z_30d`, `premium_z_30d`, `liq_count_15m`, `liq_notional_15m`, `liq_notional_z_7d`, `bar_wick_up_frac`, `bar_wick_dn_frac`, `regime_bull` (close>EMA200d), `regime_slope_pos` (EMA200d slope > 0).

### 11.6 Polymarket features pipeline (legacy, sufficient for cross-checks)
`strategy_lab\polymarket_build_features.py::build_features(markets, klines, metrics) -> DF` — for each window_start computes `ret_5m / ret_15m / ret_1h`, `oi_delta_5m/15m/1h`, `oiv_delta_5m`, L/S retail + top-trader z-scores, taker buy/sell ratio + delta, book skew. All asof at ws_s, no lookahead.

---

## 12. Backtest engine primitives (USE THESE)

### 12.1 engine_v2 — single live-mimic primitive
`strategy_lab\engine_v2.py`
- `LegacyConfig()` — 2%-on-profit, 0ms latency, no sparse-book filter
- `LiveMimicConfig()` — poly_taker_curve fee (`feeRate × p × (1-p)`), 85ms latency, min_book_events=25
- `find_book_strict(books_idx, slug, outcome, target_us, max_staleness_us=60e6) -> dict|None`
- `book_event_count(books_idx, slug, outcome, start_us, end_us)`
- `fill_at_book(books_idx, slug_or_mid, outcome, fire_us, cfg, side='buy', spread_filter=0.02, notional_usd=None) -> dict|None`
- `hold_pnl(fill, won, cfg) -> float`
- `sell_at_bid_partial(bid_p, bid_s, shares) -> (vwap, shares, usd)`
- `sell_pnl(fill, sell_vwap, sell_shares, sell_usd, cfg)`

PER CLAUDE.md: production currently uses **2%-on-profit-only** (verified 2026-05-22). Use **LegacyConfig** for production-parity shadow PnL; use LiveMimicConfig only for hypothetical "what if poly turns on real fees" analysis.

```python
from engine_v2 import LegacyConfig, fill_at_book, hold_pnl
cfg = LegacyConfig()
books = load_orderbook_l25_streaming(asset.lower(), slugs={slug})
side = "Up" if signal == "UP" else "Down"
fill = fill_at_book(books, slug, side, fire_us, cfg=cfg, spread_filter=0.02)
if fill is not None:
    won = (signal == "UP" and outcome == "Up") or (signal == "DOWN" and outcome == "Down")
    pnl = hold_pnl(fill, won=won, cfg=cfg)
```

### 12.2 Fees module
`strategy_lab\fees.py`
- `poly_fee_per_share(price, fee_rate=0.07)` — `rate × p × (1-p)`
- `poly_fee_usd(price, shares, fee_rate)` — total fee on a fill
- `poly_taker_fee_per_share/_usd` — aliases
- `poly_maker_rebate_per_share/_usd(price, shares, fee_rate=0.07, rebate_share=0.20)`
- `long_payoff_after_fees(entry_price, won, fee_rate)`
- `breakeven_hit_rate(entry_price, fee_rate)` — `p + fee(p)`
- `bps_to_rate(bps)`, `feerate_for_market_bps(bps)`
- Constants: `DEFAULT_CRYPTO_FEE_BPS=700`, `LEGACY_CRYPTO_FEE_BPS=70`, `CRYPTO_MAKER_REBATE_SHARE=0.20`

### 12.3 Legacy harness (discovery_2026_05_16)
`strategy_lab\discovery_2026_05_16\harness.py` — **DEPRECATED for fee math** but the helpers are useful:
- `NOTIONAL=25, FEE_RATE=0.02, SPREAD_FILTER={'BTC':0.02,'ETH':0.02,'SOL':0.025}, WINDOW_S={'5m':300,'15m':900}`
- `get_klines(asset, venue, period)` — cached `(end_us, prices)`
- `compute_entry_us(row, anchor, offset_s) -> int` — anchor ∈ {ws_s, slot_start, slot_end_minus}
- `hold_pnl_no_book(signal, outcome, entry_price, notional=25) -> float` — quick flat-entry PnL
- `walk_asks(prices, sizes, dollars) -> (vwap, shares, usd, under)` — wraps book_walk
- `book_fill_pnl(slug, signal, outcome, books_*, ts_us, asset, notional) -> (pnl, vwap, under)`
- `evaluate_no_book(df, entry_anchor, entry_offset_s, fixed_entry_price=0.5) -> dict`
- `load_book_subset(asset, slugs) -> dict`

---

## 13. Mispricing / cross-book signals

### 13.1 CLOB mid vs binance-fair gap
`strategy_lab\discovery_2026_05_16\strat_H_mispricing.py::compute_binance_features(res)` then per-row `p_clob_up = mid_up`, `z = ret_window/sigma_recent`, `fair_p_up = clamp(0.5+0.5*tanh(2*z), 0.10, 0.90)`, `edge = fair_p_up - p_clob_up`. Signal = UP if edge > T, DOWN if < -T. Sigma = std of trailing 30m of 1m returns.

### 13.2 Binance-only baseline + ret_2m
`strategy_lab\discovery_2026_05_16\strat_I_binance_only.py` and `strat_B_cross_venue.py` — the "pure ret_2m" baselines.

---

## 14. Production scorecard helpers (point you at the deployed gates)

| File | Computes |
| --- | --- |
| `strategy_lab\markov_filter\backtest_prod_strategies_with_gates.py` | runs F7 / Markov / time-of-day / book gates across 11 production sleeves |
| `strategy_lab\markov_filter\_final_scorecard.py` + `_results\post_f7_all_sleeves_overlay\per_sleeve_all_gates.csv` | Already-computed per-sleeve table: BASELINE_ALL, F7_only, MARKOV:wXX, F7+MARKOV:wXX |
| `strategy_lab\markov_filter\_extract_f7_markov.py` | reads above; picks best F7+MARKOV per sleeve |
| `strategy_lab\markov_filter\monthly_hod_refresh.py` | rebuilds per-sleeve hour-of-day top-8 |
| `strategy_lab\markov_filter\post_f7_real_compare_v2.py` | classify_strategy(sleeve_id) splits into family (momo/sniper/v3/v4/volume), per family Markov+F7 comparison |
| `strategy_lab\meta_classifier\shadow_11_sleeves_v2.py` | 11-sleeve verification harness using prod paper resolutions + Markov |
| `strategy_lab\meta_classifier\momo_variants_2abc.py` | 2A/2B/2C late-fire variants + F7 toggle on the 12 momo cells |

---

## 15. Quick recipe — combine 5 signals on one fire

```python
import sys, numpy as np
ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
sys.path.insert(0, fr"{ROOT}\data\v4\canonical")
sys.path.insert(0, fr"{ROOT}\strategy_lab")
sys.path.insert(0, fr"{ROOT}\strategy_lab\markov_filter")
sys.path.insert(0, fr"{ROOT}\strategy_lab\markov_filter\_vps3_pull\prod_strategies")
sys.path.insert(0, fr"{ROOT}\strategy_lab\markov_filter\_vps3_pull\prod_strategies\polymarket")

from load import (load_resolutions, load_klines_asof, load_orderbook_l25_streaming,
                  load_trades, asof_strict, slug_to_ws_s)
from markov_regime_micro import build_labels_for_asset, regime_at_us, BEAR, BULL
from rsi import compute_rsi_14
from f7_gate import f7_passes
from confluence.flow.features import compute_book_features, _book_arrays_from_row, compute_trade_features
from engine_v2 import LegacyConfig, fill_at_book, hold_pnl

asset, slug, tf = "BTC", "btcusdt-up-or-down-may-21-1300-utc-5m-1740099000", "5m"
ws_s = slug_to_ws_s(slug, tf); fire_us = (ws_s + 120) * 1_000_000

# (a) binance ret_2m + RSI(14) at ws_s
end_us, close = load_klines_asof(asset, "binance-spot-ws", "1MIN")
closes = [asof_strict(end_us, close, ws_s*1_000_000 + off*1_000_000) for off in range(-840, 1, 60)]
rsi14 = compute_rsi_14(closes)
ret_2m = np.log(asof_strict(end_us, close, fire_us) / asof_strict(end_us, close, ws_s*1_000_000))
signal = "UP" if ret_2m > 0 else "DOWN"

# (b) F7 gate
keep_f7 = f7_passes(signal, rsi14, mode='basic')

# (c) Markov M1V regime
m_end_us, _, m_lab = build_labels_for_asset(asset, window_bars=20, bar_minutes=1, mode='vol_adaptive')
regime = regime_at_us(m_end_us, m_lab, fire_us)
keep_markov = (signal == "UP" and regime == BULL) or (signal == "DOWN" and regime == BEAR)

# (d) Polymarket flow_score (CVD + imbalance + aggressor + momentum)
trades = load_trades(asset.lower())
side = "Up" if signal == "UP" else "Down"
trd_side = trades[(trades.slug == slug) & (trades.outcome == side)]
trade_feats = compute_trade_features(trd_side, fire_us, side)

# (e) L25 book microstructure at fire
books = load_orderbook_l25_streaming(asset.lower(), slugs={slug})
ts, ap, asz, bp, bsz = books[(slug, side)]
i = np.searchsorted(ts, fire_us, side='right') - 1
book_feats = compute_book_features(bp[i], bsz[i], ap[i], asz[i])

# (f) Final fill (LegacyConfig = production-parity)
cfg = LegacyConfig()
fill = fill_at_book(books, slug, side, fire_us, cfg=cfg, spread_filter=0.02)
# pnl = hold_pnl(fill, won=..., cfg=cfg)  # need outcome from load_resolutions
```

---

## 16. Files that you might think contain indicators but DON'T

| File | Reality |
| --- | --- |
| `strategy_lab\polymarket_alt_signal_grid.py` | grid over baselines, no new indicator |
| `strategy_lab\polymarket_features_univariate.py` | univariate IC sweep, uses §11.6 features |
| `strategy_lab\polymarket_revbp_sweep.py` | reverse-bps grid, no indicator |
| `strategy_lab\strategies_v*.py` | crypto trading strategies (Bollinger / EMA / etc) for an unrelated futures venue, not polymarket |
| `strategy_lab\v[0-9]+_*.py` and `run_v[0-9]+_*.py` | futures-strategy backtest runners; ignore for polymarket |
| `strategy_lab\hyperliquid\` | HL venue ingestion, no signals |
| `strategy_lab\kronos_ft\` | a separate ML pipeline, kept for reference |
| `strategy_lab\f2_replica\` | F2 wallet decode, not generalized indicators |

---

## 17. Sample-data sanity (so you know what's loadable)

- Resolutions: ~30,750 chainlink-resolved markets, Apr 24 → May 21 20:10 UTC (~28d)
- L25: BTC ~2.7GB, ETH ~1.5GB, SOL ~1GB. Full sub-second; pass `slugs=` and `subsample_1hz=True` to make it manageable.
- Trades polymarket: STALE Apr 22 → May 6 (no fresh delta puller). Limit any trade-based feature to that window.
- Binance 1s: `data/v4/canonical/klines_1s/binance_1s_28d.parquet` — current 28d window
- Production paper resolutions: `trading_events_30d.parquet`, ~25,900 `poly_updown_resolution` rows.

---

End of inventory.
