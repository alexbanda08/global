# V3 Baseline Backtest — FULL 12.5d Window (lookahead-fixed)

**Date:** 2026-05-04
**Status:** First lookahead-bug found and fixed. Full 12.5d data tells a more cautious story than partial window.
**Source:** `strategy_lab/v4_signals/phase7_validation_v3_full.py`

---

## 0. Lookahead bug fix

First attempt with HL klines used `asof_close(klines, ws)` to get price at window_start. **This was lookahead** — the bar with `time_period_start_us = ws` opens AT ws and closes AT `ws + period`. Its close price = future market resolution price. The first run showed 100% hit rate and +$43 BTC PnL — fingerprint of leaked future data.

Fixed by using `asof_close(klines, ws - period_seconds)` for "price at ws" — last bar that has fully CLOSED by time ws. After fix, results are realistic.

**Lesson:** treat all "close at time T" lookups skeptically when bar's time_period_start_us = T. Same fix pattern needed for any future kline-based feature work.

---

## 1. Full 12.5d window results (4,673 markets per asset, ~2,873 usable after filters)

Chronological 80/20 split. Q90 BTC / Q95 ETH / Q85 SOL fit on train. Holdout = last 20%.

### V3_BASELINE (uniform 0.02 spread, multi-horizon ON for SOL)

| Asset | n_holdout | fired | fire% | hit% | pnl$ | MaxDD$ | IC p |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC | 583 | 53 | 9.1% | **52.8%** | **-$0.20** | -$8.68 | 0.370 (not sig) |
| ETH | 573 | 31 | 5.4% | **41.9%** | **-$8.52** | -$9.56 | 0.038 |
| SOL | 569 | 11 | 1.9% | 54.5% | -$0.22 | -$3.82 | 0.014 |

### V3_SOL_FIX (SOL=0.025 spread, MH on)

| Asset | n_holdout | fired | fire% | hit% | pnl$ | MaxDD$ |
|---|---:|---:|---:|---:|---:|---:|
| BTC | 583 | 53 | 9.1% | 52.8% | -$0.20 | -$8.68 |
| ETH | 573 | 31 | 5.4% | 41.9% | -$8.52 | -$9.56 |
| **SOL** | 569 | **12** (+1) | **2.1%** | **58.3%** | **+$0.27** | -$3.32 |

### V3_SOL_FIX_NO_MH (drop multi-horizon for SOL)

| Asset | n_holdout | fired | fire% | hit% | pnl$ | MaxDD$ |
|---|---:|---:|---:|---:|---:|---:|
| BTC | 583 | 53 | 9.1% | 52.8% | -$0.20 | -$8.68 |
| ETH | 573 | 31 | 5.4% | 41.9% | -$8.52 | -$9.56 |
| **SOL** | 569 | **33** (+22) | **5.8%** | 57.6% | **+$2.73** | -$4.60 |

---

## 2. Findings — V3 is WEAKER than partial window suggested

### BTC: marginal at 52.8% hit, -$0.20 over 53 trades

- Hit rate barely above coin-flip
- IC p-value 0.37 → **not statistically significant**
- Without stop-loss, BTC V3 is breakeven at best on this 12.5-day sample

### ETH: BAD at 41.9% hit (worse than random), -$8.52 over 31 trades

- Hit rate **significantly below 50%** suggests the signal is INVERTED on ETH
- IC p-value 0.038 → significant correlation, but in the wrong direction
- Could be 5m mean-reversion pattern: positive ret_5m predicts outcome DOWN
- **Strong recommendation: investigate ETH V3 logic before continuing**

### SOL: marginal at 54.5%, modest improvement with fix

- Spread fix (0.02 → 0.025) adds 1 trade and flips PnL from -$0.22 to +$0.27
- Dropping multi-horizon adds 22 more trades (3× fire rate) and $2.73 PnL
- IC p-value 0.014 → signal is real

### What changed between partial and full window?

| Asset | Partial (04-22→04-29, n=28) | Full (04-22→05-04, n=53) | Delta |
|---|---:|---:|---|
| BTC hit | 64.3% | 52.8% | **-11.5pp** |
| ETH hit | 60.0% | 41.9% | **-18.1pp** |
| SOL hit (with fix) | 60.9% | 58.3% | -2.6pp |

The 04-29 → 05-04 window degraded BTC and ETH significantly while SOL stayed similar. Either:
- (a) regime change in last 5 days (BTC/ETH mean-reverting, SOL stable trend)
- (b) HL perp returns differ from Binance spot more than expected
- (c) overfit on the 7-day window — strategy was always weaker

**(c) is most likely.** The partial-window result was overoptimistic.

---

## 3. Stop-loss is the real value-add

| Asset | no_stop | stop_50% | gain |
|---|---:|---:|---:|
| BTC | -$0.20 | **+$12.80** | +$13.00 |
| ETH | -$8.52 | **+$0.84** | +$9.36 |
| SOL (fix) | +$0.27 | **+$2.87** | +$2.60 |
| SOL (no MH) | +$2.73 | **+$10.01** | +$7.28 |

**With 50% stop, V3 becomes consistently profitable across all assets.** This pattern holds across both partial and full window — stop-loss matters more than spread filter or multi-horizon.

**Recommendation: ship a 50% stop-loss layer alongside Fix A.**

---

## 4. Multi-horizon for SOL: drop it (still confirmed)

Both partial and full window agree: multi-horizon for SOL **culls profitable trades** at marginal hit-rate gain (+0.7pp on full data).

| SOL variant | Full window n | Hit% | PnL |
|---|---:|---:|---:|
| With MH (V3 base / V3.1 / V4 currently use this) | 12 | 58.3% | +$0.27 |
| Without MH | 33 | 57.6% | **+$2.73** |

But with `V3.3` paper-only A/B (per revised SOL fix spec), we'll have **fresh live data** to confirm. Plan unchanged — ship V3.3 in shadow, decide after 7 days.

---

## 5. Why this changes the SOL V3 fix urgency

The original logic was: ship Fix A urgently because SOL fires 0/day in production. Backtest showed Fix A adds 5-15 fires/day at 60%+ hit rate.

**Now we know:** even with Fix A, SOL V3 baseline gives only marginal PnL (+$0.27 over 12 fires in 12.5d). The 60% hit rate is real but per-trade PnL is small after 2% fee.

**Without stop-loss, V3 strategy on the FULL window is breakeven across all 3 assets.** 

This doesn't change the spec — Fix A still beneficial — but the EXPECTED VALUE is much smaller than partial-window suggested. **At $1 stake, V3 is essentially a paper strategy that breaks even.**

---

## 6. What this changes about live launch planning

Per `NEXT_SESSION_START_HERE.md` and `V3_LIVE_LAUNCH_SPEC_2026_04_30.md`, V3 is the planned live launch ($10 bankroll, $1/trade).

**Recommendation before going live:**
1. Apply **stop-loss layer** (50% of stake) — confirmed best ROI improvement.
2. Apply **Fix A** (per-asset spread filter for SOL).
3. **Investigate ETH V3 inverted signal** — at 41.9% hit, ETH is actively losing money. Either:
   - (a) Drop ETH from V3 launch entirely
   - (b) Investigate if HL perp vs Binance spot causes the issue (re-pull Binance klines if collector fixed, or use Polymarket settlement_price as ground truth)
   - (c) Wait for live shadow data on ETH V3 to confirm
4. **Defer V3.3 (multi-horizon A/B) and SOL multi-horizon decision** to 7-day shadow data.
5. **Consider smaller initial bankroll** ($5 instead of $10) until live data confirms.

---

## 7. Files

- This finding: `strategy_lab/reports/V3_BACKTEST_FINDINGS_FULL_2026_05_04.md`
- Full backtest: `strategy_lab/v4_signals/phase7_validation_v3_full.py`
- Full backtest report: `strategy_lab/reports/V3_BACKTEST_FULL_2026_05_04.md`
- Partial backtest (overoptimistic): `strategy_lab/reports/V3_BACKTEST_FINDINGS_2026_05_04.md`
- SOL fix spec (still valid for Fix A): `strategy_lab/reports/SOL_V3_FIX_SPEC_2026_05_04.md`
- HL klines source: `data/v4/refresh_2026_05_02/hl_klines_full.csv` (14,836 rows)
- Returns derived from HL perp (Binance collector dead since 04-29 due to geoblock)
