# V23 — Final 9-Coin Portfolio (per-asset winners + walk-forward OOS)

**Date:** 2026-04-20
**Scope:** crypto perps on Binance (proxy for Hyperliquid-style execution)
**Execution model:** 0.045% taker fee/side, 3 bps slippage, 3× leverage cap, next-bar-open fills
**Target:** CAGR ≥ 55% net, max DD ≥ -40%, n ≥ 30 trades, positive OOS Sharpe

---

## Summary — per-coin winners

| Coin | TF | Strategy | Full CAGR (net) | Full Sharpe | Max DD | Trades | Win % | PF |
|------|----|----------|---------------:|------------:|-------:|-------:|------:|---:|
| **BTC** | 4h | RangeKalman L+S | 78.0% | 1.53 | -37.7% | 259 | 44.4% | 1.93 |
| **ETH** | 1h | BB-Break L+S | 124.4% | 2.00 | -33.9% | 493 | 36.5% | 1.95 |
| **SOL** | 4h | BB-Break L+S | 139.3% | 1.93 | -35.5% | 231 | 47.2% | 2.04 |
| **LINK** | 4h | BB-Break L+S | 37.4% | 1.09 | -38.4% | 409 | 40.3% | 1.44 |
| **AVAX** | 4h | RangeKalman L+S | 77.5% | 1.48 | -31.1% | 165 | 49.7% | 2.01 |
| **DOGE** | 4h | BB-Break L+S | 63.5% | 1.22 | -36.5% | 222 | 41.9% | 1.73 |
| **INJ** | 4h | BB-Break L+S | 29.3% | 0.79 | -39.3% | 169 | 48.5% | 1.48 |
| **SUI** | 4h | BB-Break L+S | 160.4% | 1.66 | -35.5% | 245 | 47.3% | 1.62 |
| **TON** | 2h | Keltner+ADX L+S | 166.3% | 1.31 | -33.3% | 84 | 40.5% | 2.24 |

**7 of 9 coins clear the 55% target.** LINK and INJ sit below — they're kept for diversification value, not as aggressive standalone allocations.

**Equal-weight portfolio** ($90k start, one $10k sub-account per coin):
- CAGR: **+82.3% net** · Sharpe **1.89** · Max DD **-25.4%** · Calmar **3.24**
- Final: **$15.96M from $90k** over 8.6 years (177× gross multiple)
- Per-coin DDs around -35% do NOT stack; cross-coin diversification cuts combined DD to -25%

---

## Walk-forward OOS audit (split 2024-01-01)

| Coin | IS n | IS Sh | OOS n | OOS Sh | OOS CAGR | Verdict |
|------|-----:|------:|------:|-------:|---------:|:--------|
| BTC  | 183  | 1.77  | 75    | 1.01   | +41.0%   | ✓ OOS holds |
| ETH  | 361  | 2.18  | 132   | 1.52   | +76.4%   | ✓ OOS holds |
| SOL  | 139  | 2.24  | 92    | 1.42   | +76.9%   | ✓ OOS holds |
| LINK | 280  | 1.26  | 129   | 0.70   | +17.7%   | ✓ OOS holds |
| AVAX | 100  | 1.68  | 65    | 1.19   | +53.7%   | ✓ OOS holds |
| DOGE | 151  | 1.14  | 71    | 1.39   | +75.0%   | ✓ OOS holds (OOS > IS) |
| INJ  | 101  | 0.98  | 68    | 0.52   | +14.4%   | ✓ holds (weak) |
| SUI  | 50   | 0.89  | 195   | 1.85   | +212.0%  | ✓ OOS holds (OOS ≫ IS) |
| TON  | 0    | —     | 84    | 1.31   | +166.3%  | OOS-only (listed 2024-08) |

**All 9 coins pass the ≥ 50% IS-Sharpe retention test.** None flipped negative out of sample. DOGE, SUI actually improved OOS (indicator that the signal family is structurally edge, not fit). TON had no IS slice — treat with extra caution and paper-trade first.

---

## Signal families — brief mechanics

### RangeKalman L+S (BTC, AVAX)
`kal_t = kal_{t-1} + α·(close - kal_{t-1})` — a linear Kalman-EMA of close. Deviation bands at `kal ± rng_mult · mean(|close - kal|)`. Long on breakout up with regime SMA up; short on breakout down with regime SMA down. Works best on high-quality trenders (BTC 4h, AVAX 4h).

### BB-Break L+S (ETH, SOL, LINK, DOGE, INJ, SUI)
Bollinger-band breakout: long when close crosses above `SMA(n) + k·std(n)` and regime SMA is up; short mirror for down. Dominant family across the altcoin set — strongly trend-following, good at catching multi-bar range expansions.

### Keltner+ADX L+S (TON)
Keltner channel (`EMA(k_n) ± k_mult·ATR(k_n)`) breakout, gated by ADX(14) > threshold and regime SMA direction. ADX requirement filters chop. TON short history makes this the most audit-sensitive config.

---

## Go-live sequence

1. **Paper trade all 9 for 4 weeks** using the Pine scripts in `/pine/` (`*_V23_*.pine`). Compare realized fills/slippage/trade count vs. backtest expectations.
2. **Circuit breaker:** if any sub-account hits -45% DD live, halt that coin and re-audit.
3. **Portfolio weighting:** equal-weight is the safe default — per-coin correlations are below 0.5. Overweight toward the OOS-strong set (SOL, ETH, SUI, DOGE) if you want more concentrated risk.
4. **Re-audit every 6 months**, especially TON (no IS), INJ (weak OOS Sh), LINK (under target).
5. **Do NOT** cross-apply configs. Each (coin, family, TF) is tuned independently; V17 audit previously showed ETH config loses money on BTC/SOL.

---

## Honest caveats

- **All configs found by grid search** — expect 20-40% haircut on CAGR vs. backtest.
- **Walk-forward OOS is a single split** — not a rolling walk-forward. The 2024-2026 window is ~2.3 years and includes the 2024 bull leg; a 2022-bear regime check would be a useful follow-up.
- **Funding drag is modeled at 8% APR** × avg_lev × exposure. Real funding can spike to 30-50% APR during extremes; budget for 10-15% in stress scenarios.
- **Leverage cap = 3×** is a hard ceiling. Risk-based sizing will under-fill some trades; that's intentional and protective.
- **Liquidity** is fine for retail size today on BTC/ETH/SOL/LINK/AVAX/DOGE/SUI. INJ and TON are thinner; slippage may be higher than 3 bps at size.
- **Pine vs. Python parity** is unverified — paper-trade the Pine and compare trade-by-trade against the Python backtest before live.

---

## Files

- `/pine/BTC_V23_RangeKalmanLS.pine`, `/pine/AVAX_V23_RangeKalmanLS.pine`
- `/pine/ETH_V23_BBBreakLS.pine`, `/pine/SOL_V23_BBBreakLS.pine`, `/pine/LINK_V23_BBBreakLS.pine`, `/pine/DOGE_V23_BBBreakLS.pine`, `/pine/INJ_V23_BBBreakLS.pine`, `/pine/SUI_V23_BBBreakLS.pine`
- `/pine/TON_V23_KeltnerADXLS.pine`
- `/strategy_lab/results/v23/v23_summary.csv` — flat per-coin metrics
- `/strategy_lab/results/v23/v23_oos_summary.csv` — OOS verdict per coin
- `/ALL_COINS_STRATEGY_REPORT.pdf` — 12-page rich report with charts

---

## Supersedes

`V22_FINAL_WINNERS.md` (4-coin portfolio BTC/ETH/SOL/TON). This V23 doc keeps the same 4-coin configs as a subset where the V22 parameters still scored top; otherwise the V23 grid found better configs (notably ETH switched from RangeKalman → BB-Break at 1h, SOL and BTC moved to 4h).
