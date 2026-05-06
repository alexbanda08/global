# Crypto Derivatives Z-Score — Phase R0 Findings

**Date:** 2026-04-30
**Window:** 2023-05-01 → 2026-04-30 (3 years)
**Symbols:** BTCUSDT, ETHUSDT, SOLUSDT

## Data assembled

| Dataset | Source | Rows | Coverage |
|---|---|---|---|
| Metrics (OI, LSR, top-LSR, taker-ratio) | Binance Vision daily zips | 315k × 3 symbols | 3y, 5min cadence |
| Funding rate | Binance Vision monthly + REST gap-fill | 3,288 × 3 symbols | 3y, 8h cadence |
| Coinbase BTC 1h spot | Coinbase Advanced Trade API | 26,295 | 3y |
| Binance BTC/ETH/SOL 1h spot | Binance REST | 26,300 each | 3y |
| Stablecoin mcaps (8 coins) | DefiLlama | 12,344 | full history |
| **Liquidations** | ❌ Vision removed; Coinglass paid | — | — |

Score caps at 85/100 (lost 15 pts for `brigaliqui`). Rescaled to 0..100 for regime classifier comparability.

## Naive backtest of Pine spec entry rules

| Symbol | Trades | WR | Expectancy | PF | Final eq | Buy-hold |
|---|---|---|---|---|---|---|
| BTC | 63 (63L/0S) | 44.4% | +0.14% | 1.57 | 1.09× | 2.60× |
| ETH | 0 | — | — | — | 1.00× | 1.21× |
| SOL | 0 | — | — | — | 1.00× | 3.67× |

**Issues:**
1. **Zero shorts in 3 years × 3 assets.** Short filter `(score≥70 AND cross_leverage_heat>1.5 AND z_dom_stables>1.0 AND below_ema21)` never co-fires.
2. **ETH/SOL have no `z_cb_premium`** (Coinbase BTC-only) — caps their unscaled score at 75 vs BTC's 85. Score never reaches 60 → no entries.
3. **Long PF 1.57 on BTC** is real edge but barely. Loses 2.5× to buy-hold on a bull-trending asset.

## Diagnostic — where the edge actually lives (4h fwd return, baseline +0.02%)

### Long-side components (BTC)

| Signal | n | mean 4h fwd | edge × baseline |
|---|---|---|---|
| `z_lsr < -1.5` (contrarian short positioning) | 5012 | **+0.048%** | 2.4× ✅ |
| `brigalS < -1.0` (longs expanding) | 11208 | **+0.040%** | 2.0× ✅ |
| `z_cb_premium > +1.0` (US institutional buy) | 11906 | +0.033% | 1.7× ✅ |
| `z_oi_silent > +1.5` (smart accumulation) | 3111 | +0.032% | 1.6× ✅ |
| `cross_inst_lead > 0` | 12158 | +0.027% | 1.4× marginal |
| `z_oi > +1.0` | 8030 | +0.008% | ❌ no edge alone |

### Score >= 70 (BTC, n=80) — full composite signal
- 1h fwd: +0.22% (11× baseline), 52.5% hit rate
- 4h fwd: +0.18%, 51.2% hit rate
- 24h fwd: +0.30%, 53.8% hit rate

### Short-side components — broadly weak

| Signal | n | mean 4h fwd | direction |
|---|---|---|---|
| `z_lsr > +1.5` | 4842 | +0.012% | **wrong direction** (longs were right) |
| `cross_leverage_heat > 1.5` | 12638 | -0.021% | -1bp better than baseline |
| `z_oi < -1.0` | 7487 | -0.018% | marginal |

The 3-year window is bull-biased; short signals should re-test on a 2022-style bear regime to be fair.

## Decisions for v1 indicator

1. **Drop the Pine spec's 4-AND long entry; use score threshold + top components.** v2 backtest below.
2. **Drop short-side trading entirely** for now. Only act on `score_bear` as a *risk-off filter to size DOWN longs*, not as a short trigger.
3. **Fetch Coinbase ETH/SOL spot** to enable cb_premium for those assets (separate task).
4. **Liquidations component:** sourcing from Coinglass paid is justifiable IF the rest of the indicator validates. Defer until v1 validates.

## Files

```
strategy_lab/v4_signals/derivatives_zscore/
  fetch_data.py          — Vision metrics + funding (3y, parallel)
  fetch_aux.py           — Coinbase + Binance spot + DefiLlama stables
  fill_funding_gap.py    — REST gap-fill for current month
  compute_zscores.py     — 10-metric z-score panel (5min)
  backtest.py            — Pine-spec entry/exit
  diagnose.py            — component edge ablation
  FINDINGS.md            — this file

data/v4/derivatives_zscore/
  metrics/{BTC,ETH,SOL}USDT.parquet    18MB each
  funding/{BTC,ETH,SOL}USDT.parquet    50KB each
  spot/{BINANCE,COINBASE}-{BTC,ETH,SOL}-1h.parquet
  stables/market_caps.parquet          8 coins × 3y
  panels/{BTC,ETH,SOL}USDT_zscore.parquet  39 cols × 315k rows

strategy_lab/reports/derivatives_zscore/
  {SYM}_equity.parquet, {SYM}_trades.parquet, summary.parquet
```
