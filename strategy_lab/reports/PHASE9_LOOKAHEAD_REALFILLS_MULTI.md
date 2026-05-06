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
| BTC_only — ALL | 454 | 85.5 | $+4931.64 | $+10.8626 | +42.65% | +21.31 | 158 | 1 | 13 |
| BTC_only — 5m | 328 | 87.5 | $+3947.13 | $+12.0339 | +47.83% | +17.17 | 89 | 1 | 7 |
| BTC_only — 15m | 126 | 80.2 | $+984.51 | $+7.8136 | +29.16% | +38.75 | 69 | 0 | 6 |
| BTC_P9_orig — ALL | 340 | 76.2 | $+514.90 | $+1.5144 | +8.12% | +13.49 | 87 | 1 | 14 |
| BTC_P9_orig — 5m | 209 | 83.7 | $+110.21 | $+0.5273 | +2.84% | +4.48 | 30 | 1 | 8 |
| BTC_P9_orig — 15m | 131 | 64.1 | $+404.69 | $+3.0893 | +16.54% | +14.03 | 57 | 0 | 6 |
| BTC_P9_resid — ALL | 339 | 69.6 | $+177.13 | $+0.5225 | +5.04% | +3.92 | 85 | 1 | 15 |
| BTC_P9_resid — 5m | 206 | 75.2 | $-256.86 | $-1.2469 | -3.27% | -8.53 | 29 | 1 | 9 |
| BTC_P9_resid — 15m | 133 | 60.9 | $+433.99 | $+3.2631 | +17.91% | +13.21 | 56 | 0 | 6 |
| ETH_only — ALL | 453 | 89.0 | $+3569.98 | $+7.8807 | +30.78% | +43.52 | 169 | 0 | 15 |
| ETH_only — 5m | 328 | 89.6 | $+2742.09 | $+8.3600 | +33.04% | +34.42 | 98 | 0 | 9 |
| ETH_only — 15m | 125 | 87.2 | $+827.89 | $+6.6231 | +24.85% | +42.94 | 71 | 0 | 6 |
| SOL_only — ALL | 436 | 84.9 | $+3972.93 | $+9.1122 | +36.72% | +44.13 | 154 | 0 | 32 |
| SOL_only — 5m | 325 | 87.7 | $+3232.05 | $+9.9448 | +40.52% | +37.33 | 94 | 0 | 10 |
| SOL_only — 15m | 111 | 76.6 | $+740.87 | $+6.6745 | +25.61% | +30.88 | 60 | 0 | 22 |

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
| BTC | 454 | $0.7093 | 1.23 | 0 | 16 | $-400.00 | 158 | 1 | 13 |
| ETH | 453 | $0.7509 | 1.59 | 2 | 8 | $-200.00 | 169 | 0 | 15 |
| SOL | 436 | $0.7428 | 2.74 | 3 | 10 | $-250.00 | 154 | 0 | 32 |

**Reading**:
- `avg_vwap_e` > $0.50 confirms entries cross the mid (real ask, not assumed mid).
- `avg_levels_touched` > 1 means $25 stake walks beyond top of book (real liquidity drag).
- `unhedged_loss_$` is the total cash debited on losing unhedged bets — confirms losses are NOT silently zero'd.
- `hedged` count > 0 confirms the rev_bp=5 trigger fires and books opposite-side fills.

---

## VERDICT

**Asset-momentum gate (top-10% \|asset_ret_2m\|, entry t+120s, real fills, hedge-hold):**
- BTC_only: n=454  hit=85.5%  total $+4931.64  ROI +42.65%/trade  Sharpe +21.31
- ETH_only: n=453  hit=89.0%  total $+3569.98  ROI +30.78%/trade  Sharpe +43.52
- SOL_only: n=436  hit=84.9%  total $+3972.93  ROI +36.72%/trade  Sharpe +44.13

**BTC Phase 9 head-to-head:**
- BTC_P9_orig:  n=340  hit=76.2%  total $+514.90  ROI +8.12%/trade
- BTC_P9_resid: n=339  hit=69.6%  total $+177.13  ROI +5.04%/trade
- BTC_only:     n=454  hit=85.5%  total $+4931.64  ROI +42.65%/trade  ← **dominant**
