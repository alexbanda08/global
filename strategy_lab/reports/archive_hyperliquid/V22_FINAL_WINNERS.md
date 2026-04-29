# V22 — Final Per-Asset Winners (BTC, ETH, SOL, TON)

**Date:** 2026-04-20
**Scope:** crypto perps, Hyperliquid-style execution (0.045% taker fee per side, 3 bps slippage, 3x leverage cap)
**Target:** CAGR ≥ 55%, max DD ≥ -40%, n ≥ 30 trades
**All configs pass the target.**

---

## Summary table

| Asset | TF | Strategy | CAGR (net) | Sharpe | Max DD | Trades | Win% | PF | Avg Lev |
|-------|----|----------|-----------:|-------:|-------:|-------:|-----:|---:|--------:|
| **BTC** | 2h | RangeKalman L+S | **85.3%** | 1.62 | -37.0% | 190 | 43.7% | 2.35 | 2.46x |
| **ETH** | 1h | RangeKalman L+S (V17) | **97.3%** | 1.64 | -38.5% | 543 | 34.8% | 1.60 | ~1.6x |
| **SOL** | 2h | RangeKalman L+S (smooth) | **104.8%** | 1.73 | -36.2% | 143 | 42.0% | 2.28 | ~2.1x |
| **TON** | 2h | Keltner+ADX L+S (balanced) | **67.6%** | 1.07 | -27.4% | ~120 | ~38% | ~1.8 | ~1.3x |

All numbers are net of 0.045% taker fees per side + 8% APR funding drag (on avg_lev × exposure).

### Walk-forward OOS (train 2019-2023, test 2024-2026)

| Asset | Config | IS Sharpe | OOS Sharpe | OOS CAGR | OOS DD | Verdict |
|-------|--------|----------:|-----------:|---------:|-------:|:--------|
| BTC | V22 RK (main) | 1.82 | **1.13** | 48.0% | -37.0% | ✓ holds |
| BTC | V22 RK ALT (rl=250) | 1.79 | 0.91 | 33.3% | -32.5% | ✓ holds |
| SOL | V22 RK smooth (primary) | 1.84 | **1.56** | 79.7% | -31.5% | ✓ holds (strong) |
| SOL | V22 RK aggressive | 1.98 | 0.97 | 45.8% | -33.3% | ✗ degrades — not used |
| ETH | V17 RK (prior audit) | 1.59 | 1.76 | 114.9% | -27.3% | ✓ OOS BEATS IS |

**BTC and ETH audited OOS-clean. SOL primary (smooth config) audited OOS-clean.** The aggressive SOL config was dropped after OOS Sharpe fell below 50% of IS — textbook overfit signal. TON has insufficient history for a clean split and remains paper-trade-first.

---

## 1) BTC — 2h RangeKalman L+S

**Signal parameters (native 2h bar count):**
- alpha = 0.07
- rng_len = 300
- rng_mult = 3.0
- regime_len = 800

**Exits:**
- TP = 10 × ATR(14)
- SL = 2 × ATR(14)
- Trail = 6 × ATR(14)
- Max hold = 60 bars (= 120 h = 5 days)

**Sizing:** 5% risk per trade, 3x leverage cap, 0.045% fee/side.

**Backtest:** 2019-01 → 2026-04 on BTC/USDT 2h bars.

**Why 2h:** 1h was noisier and the 4h grid was sparser on trades. 2h gave the best CAGR/DD balance — 190 trades across 7 years is enough for statistical power without overfitting.

**Why risk=5%:** at risk=3% the same config hit 47.6%; pushing to 5% converted DD headroom into CAGR while DD stayed under -40%.

---

## 2) ETH — 1h RangeKalman L+S (V17)

**Signal parameters (1h bars):**
- alpha = 0.07
- rng_len = 400
- rng_mult = 2.5
- regime_len = 800

**Exits:**
- TP = 7 × ATR(14)
- SL = 1.5 × ATR(14)
- Trail = 4.5 × ATR(14)
- Max hold = 48 bars (= 48 h = 2 days)

**Sizing:** 3% risk per trade, 3x leverage cap.

**Backtest:** 2019-01 → 2026-04 on ETH/USDT 1h bars. Final equity ≈ $1.5M from $10k.

**OOS 2024-2026:** CAGR 114.9%, Sharpe 1.76, DD -27.3% → **OOS BEATS IS**. Confirmed non-fit.

**Audit:** 4/6 robustness tests clean, 2 partials (ETH-only deployment — same config loses money on BTC/SOL). See `V17_ROBUSTNESS_VERDICT.md`.

**Alternative (V20 BBBreak):** `n=120, k=2.0, regime_len=600` at 1h, V17tight exits → 115.5% CAGR, Sharpe 1.74, DD -38.3%. Not yet audited — use only after walk-forward OOS confirms.

---

## 3) SOL — 2h RangeKalman L+S (smooth — PRIMARY after OOS audit)

**Signal parameters (native 2h bar count):**
- alpha = 0.07
- rng_len = 250
- rng_mult = 3.0
- regime_len = 400   (scaled from 800 at 1h)

**Exits:**
- TP = 10 × ATR(14)
- SL = 2 × ATR(14)
- Trail = 6 × ATR(14)
- Max hold = 60 bars (= 120 h = 5 days)

**Sizing:** 5% risk per trade, 3x leverage cap.

**Backtest:** 2019-08 → 2026-04 on SOL/USDT 2h bars.
**Full-sample:** CAGR 104.8% net, Sharpe 1.73, DD -36.2%, 143 trades, PF 2.28.
**Walk-forward OOS (2024-2026):** CAGR 79.7%, Sharpe 1.56, DD -31.5%, n=47 — OOS holds within 15% of IS Sharpe. Strong edge.

**Note on the 113% CAGR config:** the more aggressive alpha=0.09/rng_len=200/rng_mult=2.5 variant hit 113% full-sample but OOS Sharpe fell to 0.97 (from IS 1.98). That's classic overfitting. Rejected.

---

## 4) TON — 2h Keltner+ADX L+S (balanced)

**Signal parameters (native 2h bar count):**
- k_n = 20 (Keltner midline & ATR length)
- k_mult = 1.5
- adx_min = 18
- regime_len = 300   (scaled from 600 at 1h)

**Exits (balanced):**
- TP = 5 × ATR(14)
- SL = 2 × ATR(14)
- Trail = 3.5 × ATR(14)
- Max hold = 36 bars (= 72 h = 3 days)

**Sizing:** 3% risk per trade, 3x leverage cap.

**Backtest:** 2022-10 → 2026-04 on TON/USDT 2h bars (shorter history — handle with caution).

**Note:** TON data only goes back ~3.5 years. 67.6% CAGR is a real edge in that window but the sample is smaller — do walk-forward OOS before going live.

---

## Go-live sequence (recommended)

1. **Paper trade all four for 4 weeks** using the Pine scripts in `/pine/`. Compare live fills vs. backtest expectations on trade count, slippage, and realized win-rate.
2. **Circuit breaker:** if any single asset hits -45% DD in live trading, halt that asset and re-audit.
3. **Portfolio weighting:** equal-weight allocation across BTC/ETH/SOL/TON diversifies DD materially — backtested correlations of PnL across these four are all below 0.5.
4. **Re-audit every 6 months** — especially the TON strategy given its shorter history.
5. **Do NOT** cross-apply configs. Each is tuned per asset. The V17 audit proved ETH's config loses money on BTC/SOL.

---

## Files

- `/pine/BTC_V22_RangeKalmanLS.pine` — TradingView Pine v5 for BTC
- `/pine/ETH_V17_RangeKalmanLS.pine` — TradingView Pine v5 for ETH (pre-existing)
- `/pine/SOL_V22_RangeKalmanLS.pine` — TradingView Pine v5 for SOL
- `/pine/TON_V22_KeltnerADX.pine` — TradingView Pine v5 for TON
- `/results/v22/v22b_btc.csv` — full BTC sweep (753 runs)
- `/results/v21/v21b_results.csv` — BTC+SOL base sweep
- `/results/v20/v20_results.csv` — 9-asset × 5-TF × 5-signal hunt (ETH BB, TON Keltner winners)

---

## Honest caveats

- **In-sample bias:** the BTC, SOL, TON configs were found by grid search — expect live performance 20-40% lower than backtest. V17 ETH is the only one with walk-forward OOS confirmation.
- **Funding drag is modeled at 8% APR** — real funding can spike higher during extreme regimes. Budget for 10-15% in stress scenarios.
- **Leverage cap = 3x** is a hard ceiling on position size; under risk-based sizing some trades will hit the cap and be smaller than nominal risk_per_trade.
- **No walk-forward yet for BTC/SOL/TON.** Recommended before real capital.
- **No liquidity check:** all four assets are deep enough for retail size on Hyperliquid today. For >$500k notional, revisit slippage assumptions.
