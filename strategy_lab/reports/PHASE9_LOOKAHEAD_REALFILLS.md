# Phase 9 Lookahead — Production-Faithful Realfills Test

_Generated: 2026-05-05_

## Engine

Reuses `simulate_realfill` from `strategy_lab/polymarket_signal_grid_realfills.py` (canonical Polymarket UpDown engine that produced the published v2 numbers). Imports `book_walk_fill` from `strategy_lab/book_walk.py` and `equity_curve_stats` from `strategy_lab/polymarket_stats.py`.

## Engine constants (production-locked)

- Notional per trade: **$25** (matches `PolymarketUpdownController` D-04)
- Entry: book-walked across top-10 ASK levels at `bucket_10s = entry_bucket`
- Hedge-hold: every 10s bucket after entry, if Binance has reverted ≥5 bps against signal direction → BUY OPPOSITE side at the bucket's ASK (book-walked)
- Fee: 2% taker, applied to winning leg's profit only
- Settlement: held leg pays $1 if correct / $0; hedge leg vice-versa

## Gates compared

- **G1 P9_orig**:  top 10% |poly_tfi_2m|,       direction = sign(TFI)        (original Phase 9)
- **G2 BTC_only**: top 10% |btc_ret_2m|,        direction = sign(btc_ret_2m) (apples-to-apples lookahead baseline)
- **G3 P9_resid**: top 10% |poly_tfi_2m_resid|, direction = sign(resid)      (TFI − OLS(BTC); BTC-purged Phase 9)

OLS used to construct residual: `poly_tfi_2m = +0.0097 + (+79.83)·btc_ret_2m + ε`

## Active universe

- 3550 markets (2663 5m, 887 15m), each with ≥1 trade in 2m + valid BTC return

---

## Results — entry @ bucket 12 (t+120s, production-honest)

Signal becomes observable at t+120s; this is when production would actually fire.

| Gate | n | hit | sig_won% | total PnL | mean PnL | ROI%/trade | Sharpe | hedged | thin | no_book |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| G1 P9_orig — ALL | 340 | 76.2% | 78.8% | $+514.90 | $+1.5144 | +8.12% | +13.49 | 87 | 1 | 14 |
| G1 P9_orig — 5m | 209 | 83.7% | 86.6% | $+110.21 | $+0.5273 | +2.84% | +4.48 | 30 | 1 | 8 |
| G1 P9_orig — 15m | 131 | 64.1% | 66.4% | $+404.69 | $+3.0893 | +16.54% | +14.03 | 57 | 0 | 6 |
| G2 BTC_only — ALL | 344 | 87.5% | 86.0% | $+4357.80 | $+12.6680 | +49.12% | +19.01 | 118 | 1 | 10 |
| G2 BTC_only — 5m | 248 | 89.9% | 89.1% | $+3554.73 | $+14.3336 | +56.17% | +15.60 | 67 | 1 | 5 |
| G2 BTC_only — 15m | 96 | 81.2% | 78.1% | $+803.07 | $+8.3653 | +30.90% | +35.05 | 51 | 0 | 5 |
| G3 P9_resid — ALL | 339 | 69.6% | 72.6% | $+177.13 | $+0.5225 | +5.04% | +3.92 | 85 | 1 | 15 |
| G3 P9_resid — 5m | 206 | 75.2% | 78.6% | $-256.86 | $-1.2469 | -3.27% | -8.53 | 29 | 1 | 9 |
| G3 P9_resid — 15m | 133 | 60.9% | 63.2% | $+433.99 | $+3.2631 | +17.91% | +13.21 | 56 | 0 | 6 |

## Reference — entry @ bucket 0 (matches combined_gate_v2's lookahead-y mid-fill)

| Gate | n | hit | total PnL | ROI%/trade |
|---|---:|---:|---:|---:|
| G1 P9_orig — ALL — bucket0 | 267 | 83.9% | $+3188.09 | +47.80% |
| G2 BTC_only — ALL — bucket0 | 271 | 88.9% | $+5023.94 | +74.80% |
| G3 P9_resid — ALL — bucket0 | 268 | 81.3% | $+2765.41 | +40.83% |

---

## VERDICT (entry @ bucket 12, ALL active)

- **G1 P9_orig**  → n= 340  hit=76.2%  total $+514.90  ROI +8.12%/trade
- **G2 BTC_only** → n= 344  hit=87.5%  total $+4357.80  ROI +49.12%/trade
- **G3 P9_resid** → n= 339  hit=69.6%  total $+177.13  ROI +5.04%/trade

→ **BTC alone (G2) ≥ Phase 9 (G1)** in production engine. The Polymarket trade-flow signal is redundant against same-window BTC return.
→ **G3 (BTC-purged residual) holds** at ROI +5.04%/trade. Phase 9 has independent predictive power beyond BTC.