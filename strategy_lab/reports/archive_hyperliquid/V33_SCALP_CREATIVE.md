# V33 — Creative + Scalping Round (audit baked in)

**Date:** 2026-04-22
**Scope:** Six new families orthogonal to V23-V30, including scalping on 15m.
**Configurations tested:** 2,232 across 5 coins × 2 timeframes × 6 families × 2 exit configs × 2 risk settings.
**Audit rule:** V31 Option B — any winner must pass the 5-test suite (IS/OOS + plateau + null + DSR + per-year) before earning shelf space.

---

## The six families

1. **VWAP_Scalp** (15m, 1h) — Rolling-window VWAP z-fade with RSI oversold/overbought confirm. Classic scalp mean-reversion inside Bollinger-like z-bands.
2. **Keltner_Pullback** (15m, 1h) — Buy pullbacks to the Keltner mid-EMA in established trend (EMA-regime filter + RSI dip confirm).
3. **RSI_Div** (1h, 4h) — Regular bullish/bearish price-vs-RSI divergence at trailing swing lows/highs.
4. **ATR_Burst** (15m, 1h) — Trade in the direction of sudden true-range expansion > k×rolling-mean when ADX confirms trend.
5. **ORB_Break** (15m) — 00 UTC opening range (first N bars) breakout with regime filter.
6. **ETHBTC_Ratio** (1h, 4h) — ETH mean-reversion based on z-score of the ETH/BTC ratio relative to its rolling mean. Genuinely cross-asset.

Coins: BTCUSDT, ETHUSDT, SOLUSDT, DOGEUSDT, SUIUSDT.

---

## Sweep result — 32 best-per-(coin,family,TF) winners

Out of 2,232 configs, **32 produced n ≥ 25 trades, DD ≥ -50%**. Top 7 by score:

| Rank | Strategy                     | CAGR   | Sh    | DD    | n   |
|------|------------------------------|--------|-------|-------|-----|
| 1    | SUI RSI_Div 1h               | +26.1% | +0.74 | -40.2%| 111 |
| 2    | DOGE RSI_Div 4h              | +17.4% | +0.79 | -23.3%| 80  |
| 3    | SUI Keltner_Pullback 1h      | +16.8% | +0.89 | -24.0%| 27  |
| 4    | ETH ETHBTC_Ratio 4h          | +11.9% | +0.69 | -34.5%| 144 |
| 5    | SOL ATR_Burst 1h             | +10.1% | +0.66 | -22.1%| 25  |
| 6    | DOGE Keltner_Pullback 1h     |  +9.8% | +0.55 | -36.9%| 44  |
| 7    | SOL Keltner_Pullback 15m     |  +8.9% | +0.51 | -38.5%| 156 |

These are all modest absolute numbers — none approach V30's headline sleeves (ETH CCI +122% OOS, SOL SuperTrend +51% full-period). That's the first honest read: these creative families have real edge but not large edge.

---

## Audit verdict — 0 of 7 clear the full bar

| Strategy                     | IS Sh  | OOS Sh | Plateau | Null% | DSR  | Verdict  |
|------------------------------|--------|--------|---------|-------|------|----------|
| SUI RSI_Div 1h               | +1.74  | +0.44  | 57%     | 90%   | 0.00 | OVERFIT  |
| SUI Keltner_Pullback 1h      | +3.66  | +0.04  | 62%     | 67%   | 0.00 | OVERFIT  |
| DOGE RSI_Div 4h              | +0.88  | +0.67  | 50%     | 90%   | 0.00 | OVERFIT  |
| ETH ETHBTC_Ratio 4h          | +0.38  | +1.22  | **20%** | 100%  | 0.00 | OVERFIT  |
| SOL ATR_Burst 1h             | +0.27  | +1.16  | 50%     | 100%  | 0.00 | OVERFIT  |
| DOGE Keltner_Pullback 1h     | +0.14  | +1.04  | **100%**| 100%  | 0.00 | OVERFIT  |
| SOL Keltner_Pullback 15m     | +1.24  | -0.87  | 62%     | 23%   | 0.00 | OVERFIT  |

### What specifically killed each one

**Deflated Sharpe (DSR) = 0.00 across the board.** With 2,232 configs tested, the expected max Sharpe under the null is ~1.8. None of V33's winners reach that; DSR deflates them all to zero.

**Plateau < 60% for 5 of 7.** ETH ETHBTC_Ratio hit only 20% — the edge sits on a single parameter sweet spot (z_thr=2.5, z_lookback=100). Perturbing even one grid step flips most neighbors to negative. Classic fragile spike.

**IS→OOS degradation for 3 of 7.** SUI RSI_Div 1h dropped from IS Sharpe 1.74 to OOS 0.44. SUI Keltner_Pullback 1h collapsed from 3.66 IS to 0.04 OOS. SOL Keltner_Pullback 15m went from IS 1.24 to OOS -0.87.

**Low-trade-count artefacts.** SOL ATR_Burst 1h OOS has only 9 trades, SUI Keltner_Pullback 1h IS has only 6. Sharpe numbers off that few trades are essentially noise.

---

## The scalping-specific finding

**Scalping on 15m with 0.045% taker fees doesn't work in our tests.** SOL Keltner_Pullback 15m had the only sub-hour entry that cleared n ≥ 25. IS Sharpe 1.24 looked exciting; OOS Sharpe -0.87 is a cliff.

Why: every 15m scalp pays ~12 bps round-trip in fees + slippage. If the signal's average winner is 30-50 bps, fees eat 25-40% of gross alpha. The breakeven bar is brutal, and when the market regime shifts (2025-2026), the edge flips negative instantly.

**Scalping needs maker fees (+/- 0.015% rebate) or much bigger per-trade expectancy** to be viable at our cost structure. Both are outside what our current sim models.

---

## The cross-asset finding — tantalizing but fragile

**ETH ETHBTC_Ratio 4h** is the most interesting negative result. OOS Sharpe 1.22 with 58 trades, null-beat 100%, per-year profile showing genuine cross-regime edge (2023 +47%, 2024 +57%). This looks real.

But the plateau test — 20% — reveals it's a single-point spike. z_thr=2.5, z_lookback=100 is the winner; z_thr=2.0 or 3.0 (one step either side) drops the sleeve to negative territory. We got lucky picking the right grid point, not discovering a robust regime.

**If we want to pursue this family**, the right next step is a denser plateau sweep (z_thr ∈ {1.75, 2.0, 2.25, 2.5, 2.75, 3.0}, lookback ∈ {50, 75, 100, 150, 200}) and require plateau ≥ 60% before deployment. That's a V34 candidate.

---

## What we learned (net value of V33)

**Negative results are information.** V33 didn't add to the deploy-live shortlist, but it sharpened what we know:

1. **The audit bar works.** Without V31/V32's overfit suite, ETH ETHBTC_Ratio 4h's headline Sharpe 1.22 and 100% null-beat would have looked deployable. The plateau test caught the fragility in one pass.

2. **15m scalping is not viable at our taker-fee cost structure.** Dead branch unless we get maker rebates. That's a structural finding, not a parameter-search failure.

3. **The V28/V30 shortlist is complete for now.** 11 audit-clean sleeves across 4 coins remains the deploy set. No V33 sleeve joins the shelf.

4. **Cross-asset ratio signals are the right next frontier.** The ETH/BTC attempt had the cleanest OOS behavior of any V33 family; it just needs a denser parameter grid to find a robust region. Promising, not dead.

---

## Deploy-live shortlist (unchanged from V32)

**Core (V23 BBBreak + V27 Donchian, V32-audited):**
1. SOL BBBreak_LS 4h
2. SUI BBBreak_LS 4h
3. DOGE BBBreak_LS 4h
4. ETH HTF_Donchian 4h
5. BTC HTF_Donchian 4h
6. SOL HTF_Donchian 4h
7. DOGE HTF_Donchian 4h

**New (V30, V31-audited):**
8. SOL SuperTrend_Flip 4h
9. DOGE TTM_Squeeze_Pop 4h
10. ETH CCI_Extreme_Rev 4h
11. ETH VWAP_Zfade 4h

**11 sleeves, 4 coins, all audit-clean.**

---

## Audit ledger (V31 + V32 + V33)

| Round | Tested | Pass | Fail/Overfit | Notes                          |
|-------|--------|------|--------------|--------------------------------|
| V31   | 10     | 4    | 5 (1 mixed)  | First overfit pass             |
| V32   | 7      | 7    | 0            | V28 P2 cores all clean         |
| V33   | 7      | 0    | 7            | No new families survive bar    |
| **Total** | **24** | **11** | **12 (1 mixed)** | **~46% survival rate** |

The 46% survival rate across three rounds of auditing is actually reasonable. It tells us the audit is selective but not impossibly strict.

---

## What's next (candidate V34 directions)

Ideas that remain orthogonal and haven't been tested with proper audit discipline:

1. **Dense ETHBTC_Ratio sweep** — fine-grained plateau grid to find robust region (1-2 hrs of compute).
2. **Funding-rate reversion** — requires Hyperliquid funding series ingestion (1 day of infra work).
3. **Pair spreads beyond ETH/BTC** — SOL/ETH beta, DOGE/SOL cross, or basket-vs-BTC.
4. **Event windows** — CPI/FOMC/Fed speeches as binary labels; narrow-window plays.
5. **Regime-routed portfolios** — use the regime classifier we already built to rotate between trend and range sleeves.

None of these would be "more new families to fling at the wall." They'd be focused probes with the overfit audit baked in from the start.
