# Crypto Scalping — pivot iteration 1 (Bella Fade + Offside)

**Window:** 2024-01-01 → 2024-12-31 (52 weeks, 105k 5-min bars/asset)
**Universe:** BTCUSDT, ETHUSDT, SOLUSDT
**Risk per trade:** 1.0% of equity
**Fees:** Hyperliquid 4.5bp/side taker + 1.5bp slippage
**Data:** Binance 5m OHLCV with `taker_buy_quote / quote_volume` for buyer/seller-aggression

## TL;DR

Both tutorial-faithful patterns ported to crypto are **slightly negative** in iter 1:

| Symbol | Strategy | n | per_wk | WR | PF | avg ret/trade | total $PnL | final eq× |
|---|---|---|---|---|---|---|---|---|
| BTC | bella_fade_2T   | 65 | 1.24 | 58.5% | 0.81 | -0.087% | $-575   | 0.942× |
| BTC | bella_fade_1T2R | 65 | 1.24 | 52.3% | 0.84 | -0.087% | $-585   | 0.942× |
| BTC | offside         | 42 | 0.80 | 31.0% | 0.22 | -0.275% | $-1,097 | 0.890× |
| ETH | bella_fade_2T   | 69 | 1.32 | 47.8% | 0.70 | -0.163% | $-1,095 | 0.890× |
| ETH | bella_fade_1T2R | 69 | 1.32 | 44.9% | 0.89 | -0.064% | $-477   | 0.952× |
| ETH | offside         | 12 | 0.23 | 50.0% | 0.69 | -0.056% | $-67    | 0.993× |
| SOL | bella_fade_2T   | 67 | 1.28 | 52.2% | 0.83 | -0.081% | $-553   | 0.945× |
| SOL | bella_fade_1T2R | 67 | 1.28 | 44.8% | 0.85 | -0.082% | $-577   | 0.942× |
| SOL | offside         | 1  | 0.02 | 0.0%  | 0.00 | -0.104% | $-10    | 0.999× |

**The good news:** signals fire at the right times — TP1 hits @ +0.85% with 100%
WR, but stops blow out 35-45% of trades at -1.21%. The pattern logic is
directionally right; the **stop placement is too tight for 5m crypto noise**.

## Per-strategy diagnostic (where the money goes)

### Bella Fade — exit reason breakdown (single-2R variant)

| Asset | total | STOP n / WR / avg | TP n / WR / avg | TIME n / WR / avg |
|---|---|---|---|---|
| BTC | 65 | 26 / 0% / **-1.24%** | 7 / 100% / +1.79% | 32 / 84% / +0.44% |
| ETH | 69 | 31 / 0% / **-1.21%** | 9 / 100% / +1.84% | 29 / 76% / +0.57% |
| SOL | 67 | 29 / 0% / **-1.14%** | 11 / 100% / +1.89% | 27 / 70% / +0.26% |

**TIME exits are positive on average (76-84% WR)** — strategy gets follow-through,
just rarely the full 2R. Suggests: lower TP target, tighten time stop.

### Bella Fade — exit breakdown (two-target variant: TP1=1R / TP2=1.5R / BE-stop)

| Asset | TP1 hits | STOP first | TIME first |
|---|---|---|---|
| BTC | 25 (+0.80% avg) | 23 (-1.23%) | 17 (+0.15%) |
| ETH | 27 (+0.92% avg) | 30 (-1.21%) | 12 (+0.00%) |
| SOL | 28 (+0.86% avg) | 25 (-1.14%) | 14 (-0.07%) |

**TP1 hits 38-39% of the time at +0.86% avg, but 35-45% stop out at -1.21%.**
Even with WR 55%, the asymmetric size kills expectancy:
   `0.55 × 0.50R - 0.45 × 1.00R = -0.18R per trade`

Two-target needs WR > 67% to break even. Single-target at 2R needs 33% TP-hit rate;
we're at 11-16%.

### Offside — losing structurally

ETH closest to breakeven (PF 0.69, only -0.7% over 12 trades). BTC's failed-
breakouts often turn into **real** breakouts that just retested first; entering
short on the opposite-side break gets us short into a continuation.

## Why frequency is far below the 16-20/week target

Tutorial was written for stock-market day-traders trading 6.5h × 5d ≈ 32h/week.
Crypto is 24/7 (168h/week, 5×) but:
- **No single "open"** — Bella Fade is fundamentally a session-open pattern.
  Spreading across Asia/London/NY anchors → < 1.5/week per asset.
- **Tight consolidation rare** — Offside needs range/mid < 0.5% for 8-20 bars.
  Only 0.2-2.5/week.

Realistic crypto target: **3-8 setups/week per strategy per asset** = 10-25/week
combined across 3 assets. Will require loosening criteria.

## Iteration 2 plan (priority-ordered)

### A. Bella Fade fixes (highest priority — directional edge already real)
1. **Drop the partial out** — single TP at **1.0-1.2R** (winners come fast,
   2nd wave rarely fills in crypto)
2. **Tighten shot clock** to 12 bars (1h) — TIME exits at 24 bars dilute the win
3. **Wider stop** — LOD - 0.20% (was 0.10%) AND/OR LOD - 0.5×ATR(20)
4. **Stop-survival pre-check** — if any of last 3 bars closed below LOD-buffer,
   skip the entry (high whipsaw risk)
5. **Restore pre-selloff strength filter** but use slow MA (close[t-w] >
   ma_24h[t-w]) — iter 1 dropped this for frequency; restore for selectivity

Target: 30 higher-quality BTC trades, WR 60-65%, PF > 1.2.

### B. Offside fixes
1. **Wait for retest** — after opposite-side break, wait for ONE retest before
   entering. Reduces continuation-trap losses on BTC.
2. **Volume gate at entry** — require `quote_volume[t] > 1.2× window_avg_qv`.
3. **Side asymmetry** — disable LONG side; short-side Offside on ETH already
   shows PF 0.86 / WR 60%.
4. **Sweep range_pct** in [0.4%, 0.6%, 0.8%] for SOL (current 0.5% too tight).

### C. New 3rd strategy candidate — VWAP-bounce (deferred until A+B work)
- Setup: strong asset, deep pullback to VWAP from above, holds, bounces
- Entry: close > VWAP after touching from below + taker_buy spike
- Stop: VWAP - 0.15%
- Target: session high
- Expected: 8-12/week, less directional bias-prone

### D. Combined-signal layer (preserves derivatives work)
The 5m panel (`data/v4/derivatives_zscore/panels/`) at 5min cadence has
`sum_taker_long_short_vol_ratio`, `z_oi`, `z_lsr`, `cross_institutional_lead`
etc. Iteration 3 idea: only take Bella Fade longs when `z_lsr < -1` AND
`cross_institutional_lead > 0` — derivatives confluence on top of price action.

## Files

```
strategy_lab/scalping/
  README.md              — pattern analysis + crypto adaptation
  data_loader.py         — 5m OHLCV loader + VWAP/RVOL/ATR/sessions
  detect_bella_fade.py   — Bella Fade pattern detector
  detect_offside.py      — Offside pattern detector (vectorized)
  scalp_simulator.py     — TP1+TP2 partial + single-target engines
  run_scalping.py        — driver: detect → sim → score → SUMMARY

strategy_lab/reports/scalping/
  SUMMARY.md (this file)
  scalping_results.csv
  bella_fade/{sym}_signals.parquet, {sym}_trades.csv, {sym}_trades_single2R.csv
  offside/{sym}_signals.parquet, {sym}_trades.csv
  equity/{sym}_bella.parquet, {sym}_bella_single2R.parquet, {sym}_offside.parquet
```

## Status

- ✅ MVP scaffolding built end-to-end (loader → detector → sim → report)
- ✅ Both tutorial patterns implemented faithfully
- ⚠️ Both patterns net-negative in iter 1 (signals OK, stop placement too tight)
- 🔁 Iteration 2 plan ready (changes A1-A5 should flip Bella Fade BTC/ETH to PF > 1)
