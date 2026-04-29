# V8 + V9 Strategy Exploration — Verdict

Research date: 2026-04-20.
Scripts: `strategies_v8.py`, `strategies_v9.py`, `advanced_simulator.py`, `v8_hunt.py`.
Full raw data: `results/v8_hunt.csv`.

## What was tested

Built a brand-new **advanced simulator** that supports:
- Partial exits at TP1 / TP2 / TP3 (% scale-outs with per-level configurable fractions)
- **Ratcheting SL**: moves to breakeven at TP1, to TP1 level at TP2
- **Post-TP2 trailing stop** (ATR-scaled, Chandelier-style)
- Hyperliquid maker fees (0.015 %) + zero slippage (limit-order model)

Two new strategy families on top:
- **V8 (novel entries)** — Triple SuperTrend stack, HMA + ADX regime filter, Volatility-percentile Donchian
- **V9 (hybrid)** — take the proven V3B / V4C / V2B / HWR1 entries and wrap them with the multi-TP ladder

Tested: 8 strategies × 6 coins = 48 combos across 2022-2025.

## Honest verdict

The research ideas (SuperTrend, HMA+ADX, multi-TP, ratcheting SL) are conceptually sound and well-documented in the 2025-2026 literature — **but at 4h crypto on our signal universe, they do not outperform the simple V3B / V4C trailing-stop strategies we already have.**

### The core tradeoff — multi-TP costs CAGR

| Pair | Strategy | Trades/yr | WR | PF | CAGR | Why |
|---|---|---:|---:|---:|---:|---|
| ETH | V3B_adx_gate (baseline, TSL) | ~14 | 42 % | 1.44 | +45 % FULL | Full runner captures trends |
| ETH | V9E_v3b_aggressive (ladder) | ~1 | 75 % | 2.27 | +2.2 %/yr | TP1/TP2 caps the big wins |

Every V9-ladder variant shows the same pattern: **higher WR, higher PF, but much smaller CAGR**. Partial exits at TP1 mathematically prevent the strategy from reaping the big trending runs that V3B/V4C exist to capture.

### Top 4 high-WR + profitable passers

| Coin | Strategy | n | WR | PF | CAGR | DD | Final on $10k |
|---|---|---:|---:|---:|---:|---:|---:|
| XRP | V8B_hma_adx_regime | 6 | 67 % | 1.85 | +4.3 % | −10.8 % | $12,252 |
| XRP | V9D_hwr1_ladder | 8 | 75 % | 1.31 | +0.9 % | −7.8 % | $10,455 |
| ETH | V8C_vol_donchian | 9 | 56 % | 1.26 | +4.0 % | −15.8 % | $12,055 |
| ADA | V9E_v3b_aggressive | 7 | 71 % | 1.87 | +2.4 % | −7.4 % | $11,190 |

All positive-return, all ≥ 55 % WR, but **CAGR is tiny** (0.9 % – 4.3 %/yr) compared with baseline V3B/V4C (20-45 %/yr).

### V8 novel entries mostly failed

- **V8A (Triple SuperTrend)** — 0 trades in 4 years on every coin. The three-filter confluence is too strict.
- **V8B (HMA + ADX)** — 3-13 trades in 4 years. ADX > 22 on 4h is rare for our universe. Profitable on XRP only.
- **V8C (Vol-regime Donchian)** — promising on ETH (55 % WR / PF 1.26) and SOL (50 % WR / PF 1.67) but low trade counts.

## Why multi-TP ladder + SuperTrend under-performs here

The 2026 research describes these techniques for **lower timeframes (1-15 min) and more liquid instruments**. On 4h crypto:

1. **Crypto 4h trends run long** — closing 40 % at TP1 = 1 ATR gives up huge profit when the move runs 5-10 ATR. Baseline V3B/V4C with a single trailing stop captures the whole move.
2. **Signal frequency is low** — 10-30 trades/year on 4h, so small samples make year-level WR very noisy. "50 % WR in every year" becomes statistically fragile.
3. **ATR gating hurts** — ADX > 22 and vol-percentile > 0.25 filters eliminate ~70 % of otherwise valid signals.
4. **Fee impact is nil** at Hyperliquid maker rates, so there's no structural benefit to "take a quick TP1 win".

## The fundamental truth

**You cannot simultaneously maximise CAGR AND win rate with the same entry signals.** Every crypto strategy sits on that frontier:

```
high WR, low CAGR   ← V9-ladder family, HWR family
↕ (tradeoff)
low WR, high CAGR   ← V3B, V4C (our current production)
```

To break this frontier you need **genuinely new information**, not new exit logic:
- **Orderflow signals** (we already have Binance futures metrics: OI, LS ratio, funding)
- **Liquidation cascade signals** (we already have CoinAPI liquidations 2023-2026)
- **Cross-asset factor signals** (BTC-dominance, inter-crypto correlation breaks)
- **ML-based pattern recognition on these alternate datasets**

## Recommendation

1. **Keep the current portfolio as-is for capital growth** (6 coins, V3B/V4C, +54 % OOS CAGR / 1.44 Sharpe).
2. **If psychological comfort of 60 %+ WR matters more than growth**, switch the XRP sleeve to HWR1 (already done) and accept a 40 % haircut on total return.
3. **For the next real breakthrough**, pivot research to orderflow + liquidations. The data is already downloaded in `data/binance/futures/` and `data/coinapi/liquidations/` but hasn't been systematically mined yet.
