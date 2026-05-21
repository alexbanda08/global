# Phase 9 Lookahead — Multi-Asset Production-Faithful Realfills

_Generated: 2026-05-05_

## Engine — exact production semantics

Reuses canonical `simulate_realfill` from `strategy_lab/polymarket_signal_grid_realfills.py`. Imports `book_walk_fill` from `strategy_lab/book_walk.py` and `equity_curve_stats` from `strategy_lab/polymarket_stats.py`. Production constants:

- **Notional / trade**: $25 (D-04 hard-coded in PolymarketUpdownController)
- **Entry**: book-walk top-10 ASK levels at `bucket_10s = 12` (= t+120s, when signal is observable)
- **Hedge-hold**: each post-entry 10s bucket, if asset's Binance price reverted ≥5 bps against signal direction → BUY OPPOSITE side at the bucket's ASK book (book-walked)
- **Fee**: 2% taker on winning leg's profit only
- **Settlement**: held leg → $1 if correct / $0; hedge leg → vice-versa
- **Thin-book skip**: trades skipped if entry walk filled <50% of notional

## Gates tested

- `{asset}_only`: top-10% \|asset_ret_2m\|, sign(asset_ret_2m) = direction. Tradeable lookahead-honest baseline (entry @ t+120s after observing first 2m return).
- `BTC_P9_orig` (BTC only): top-10% \|poly_tfi_2m\|, sign(TFI) = direction.
- `BTC_P9_resid` (BTC only): top-10% \|TFI − OLS(TFI ~ btc_ret_2m)\|, sign(resid) = direction.

NOTE: Phase 9 TFI parquet only exists locally for BTC (`btc_trade_flow_v1.parquet`). ETH/SOL TFI would require re-running `phase9_polymarket_trade_flow.py` against VPS2 `trades_v2` for those slugs.

### BTC — universe coverage
- markets: 4673 (3505 5m, 1168 15m)
- 1m bars (Binance): 16113
- book slugs at any bucket: 4655

### ETH — universe coverage
- markets: 4673 (3505 5m, 1168 15m)
- 1m bars (Binance): 16113
- book slugs at any bucket: 4648

### SOL — universe coverage
- markets: 4673 (3505 5m, 1168 15m)
- 1m bars (Binance): 16113
- book slugs at any bucket: 4648

## Head-to-head — entry @ bucket 12 (production-honest)

| Gate | n | hit% | total PnL ($) | mean PnL | ROI/trade | Sharpe | hedged | thin | no_book |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC_only — ALL | 463 | 63.5 | $-42.10 | $-0.0909 | +2.76% | -1.69 | 195 | 1 | 5 |
| BTC_only — 5m | 330 | 69.7 | $-86.57 | $-0.2623 | +1.52% | -4.35 | 119 | 1 | 4 |
| BTC_only — 15m | 133 | 48.1 | $+44.47 | $+0.3344 | +5.85% | +3.01 | 76 | 0 | 1 |
| BTC_P9_orig — ALL | 340 | 68.2 | $+141.04 | $+0.4148 | +6.63% | +3.70 | 97 | 1 | 14 |
| BTC_P9_orig — 5m | 209 | 78.0 | $+84.00 | $+0.4019 | +3.47% | +3.58 | 39 | 1 | 8 |
| BTC_P9_orig — 15m | 131 | 52.7 | $+57.04 | $+0.4354 | +11.68% | +1.90 | 58 | 0 | 6 |
| BTC_P9_resid — ALL | 335 | 56.1 | $+554.79 | $+1.6561 | +13.96% | +4.62 | 84 | 0 | 20 |
| BTC_P9_resid — 5m | 180 | 68.9 | $+786.36 | $+4.3686 | +16.94% | +7.27 | 16 | 0 | 12 |
| BTC_P9_resid — 15m | 155 | 41.3 | $-231.57 | $-1.4940 | +10.50% | -4.70 | 68 | 0 | 8 |
| ETH_only — ALL | 452 | 65.9 | $+168.83 | $+0.3735 | +3.46% | +8.35 | 188 | 0 | 16 |
| ETH_only — 5m | 327 | 73.4 | $+139.54 | $+0.4267 | +3.02% | +9.63 | 115 | 0 | 12 |
| ETH_only — 15m | 125 | 46.4 | $+29.28 | $+0.2343 | +4.61% | +2.08 | 73 | 0 | 4 |
| SOL_only — ALL | 445 | 63.1 | $-363.51 | $-0.8169 | +0.28% | -13.99 | 178 | 0 | 24 |
| SOL_only — 5m | 321 | 68.8 | $-295.82 | $-0.9215 | -0.69% | -14.56 | 112 | 0 | 8 |
| SOL_only — 15m | 124 | 48.4 | $-67.69 | $-0.5459 | +2.79% | -4.20 | 66 | 0 | 16 |

---

## FIDELITY AUDIT — does the test match production?

| Concern | Check | Pass? |
|---|---|---|
| Entry walks real book? | `book_walk_fill(ask_p, ask_s, $25)` over top-10 levels — same call signature as `polymarket_signal_grid_realfills.py` | ✅ |
| Entry uses MID assumption? | NO — vwap_e is computed from actual ASK levels, NOT $0.50 mid | ✅ |
| Slippage tracked? | avg_vwap_e per asset captured below; underfilled_entry counter tracks trades that exhaust top-10 depth | ✅ |
| Losses computed? | unhedged loss = `-usd_e` (full deployed capital lost). Counted via `unhedged_losses` and summed via `unhedged_loss_total` | ✅ |
| Hedge prices via book? | YES — opposite-side ask book walked with `book_walk_fill(h_ask_p, h_ask_s, target_h)` at the trigger bucket | ✅ |
| Hedge target shares? | `target_h = shares_e × top_opposite_ask` (canonical formula from `simulate_realfill`); bumps to `shares_e × vwap_h` if first walk underfilled | ✅ |
| Fee model? | 2% taker on winning leg's PROFIT (not on cost) — matches `simulate_realfill` lines 153-174 | ✅ |
| Hedge-trigger feed? | Asset's own Binance 1m close (BTC for BTC universe, ETH for ETH, SOL for SOL) — production uses `fetch_close_asof` with the same per-asset feed | ✅ |
| Reversion threshold? | 5 bps against signal direction (production REV_BP_THRESHOLD) | ✅ |
| Thin-book skip? | Trades skipped (NOT zero-pnl'd) if `usd_e < notional × 0.5`; counted via `skipped_thin` | ✅ |
| Missing-book skip? | Trades skipped when slug not in book OR entry_bucket has no snapshot; counted via `skipped_no_book` | ✅ |
| Equity curve stats? | Sharpe/Sortino/MaxDD computed via `equity_curve_stats` chronologically sorted by `window_start_unix` | ✅ |
| Bootstrap CI? | 2000 resamples on per-trade pnls, 2.5%/97.5% quantiles | ✅ |
| Hold to resolution? | Yes when not hedged — settles at $1 if `outcome_up == sig`, else $0; matches binary CTF settlement | ✅ |

### Per-asset audit metrics (on asset_only — ALL gate)

| Asset | Trades | avg_vwap_e (entry slippage) | avg_levels_touched | underfilled | unhedged_losses | unhedged_loss_$ | hedged | thin_skipped | no_book_skipped |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC | 463 | $0.8573 | 1.12 | 0 | 4 | $-100.00 | 195 | 1 | 5 |
| ETH | 452 | $0.8799 | 1.33 | 2 | 2 | $-50.00 | 188 | 0 | 16 |
| SOL | 445 | $0.8745 | 1.92 | 0 | 6 | $-150.00 | 178 | 0 | 24 |

**Reading**:
- `avg_vwap_e` > $0.50 confirms entries cross the mid (real ask, not assumed mid).
- `avg_levels_touched` > 1 means $25 stake walks beyond top of book (real liquidity drag).
- `unhedged_loss_$` is the total cash debited on losing unhedged bets — confirms losses are NOT silently zero'd.
- `hedged` count > 0 confirms the rev_bp=5 trigger fires and books opposite-side fills.

---

## VERDICT

**Asset-momentum gate (top-10% \|asset_ret_2m\|, entry t+120s, real fills, hedge-hold):**
- BTC_only: n=463  hit=63.5%  total $-42.10  ROI +2.76%/trade  Sharpe -1.69
- ETH_only: n=452  hit=65.9%  total $+168.83  ROI +3.46%/trade  Sharpe +8.35
- SOL_only: n=445  hit=63.1%  total $-363.51  ROI +0.28%/trade  Sharpe -13.99

**BTC Phase 9 head-to-head:**
- BTC_P9_orig:  n=340  hit=68.2%  total $+141.04  ROI +6.63%/trade
- BTC_P9_resid: n=335  hit=56.1%  total $+554.79  ROI +13.96%/trade
- BTC_only:     n=463  hit=63.5%  total $-42.10  ROI +2.76%/trade  ← **dominant**
