# Kronos × Polymarket — Final Investigation Report

**Date:** 2026-04-23
**Scope:** End-to-end validation of fine-tuned Kronos BTC 5m predictions for Polymarket Up/Down binary markets.

## TL;DR

| Finding | Verdict |
|---|---|
| Kronos's Jan-Mar accuracy | ✅ 57% baseline, 69% w/ hour+DOW filter |
| Kronos's Apr 22-23 accuracy (real) | ⚠️ **52.9% (5m), 51.4% (15m)** |
| Hour+DOW filter generalization | ❌ Overfit to Jan-Mar regime, HURTS on Apr |
| Simulated 69% backtest PnL | ✅ +$79 / 444 bets, profitable in 100% of Monte-Carlo |
| Real Kronos backtest PnL | ⚠️ **+$6-10 / 444 bets, CI includes zero — no proven edge** |
| Best exit strategy | S3 Target 0.70 + Stop 0.35 (+$7.84, CI [-$11, +$28]) |

**Current state:** Kronos as fine-tuned is **not statistically profitable** on the Apr 22-23 Polymarket universe. Out-of-distribution performance drop (~4-16pp) kills the edge. Not ready for live trading.

---

## 1. Data Assembled

### Kronos Model (fine-tuned)
- Base: Kronos-base 400MB transformer
- Fine-tuned on: BTCUSDT 5m, 3-year window ending 2026-03-31
- Training: 33,441 steps × batch 8 (effective 32), 6h 26m on RTX 3060
- Val loss: 2.5987

### Polymarket Data (VPS Postgres)
- Source: `/opt/storedata` collector on Contabo VPS (IPv6)
- Snapshots collected: **3.84M orderbook snapshots**, 30h window (Apr 22 16:47 → Apr 23 22:04)
- 1,542 distinct markets observed
- Resolved markets for backtest: **444** (333 BTC 5m + 111 BTC 15m)
- Ambiguous (unresolved or data gap): 4 (dropped)

### Binance BTC Data
- Historical: `BTCUSDT_5m_3y.csv` (315,361 bars, 2023-04 → 2026-03)
- Fresh pull: `BTCUSDT_5m_apr.csv` (1,111 bars, Apr 20-23 from Binance public API)
- Combined: 316,472 bars, continuous

---

## 2. Market Mechanics Discovered

By dissecting a single market (`btc-updown-5m-1776951000`):

1. **Markets open ~3 hours BEFORE the resolution window** with bids/asks stuck at 0.505/0.495
2. **The "5m" in "5m market" is the PRICE-TRACKING WINDOW**, not market lifespan
3. **All action is in the final 5 minutes**: 1,000-1,500 snapshots per minute, price swings from 0.42→0.67→0.41→0.98 in seconds
4. **Resolution is visible from snapshots** — no need for Binance kline lookup
5. **Entry point:** `window_start = resolve_unix - 300` (5m) or `- 900` (15m) — when real trading begins at ~50/50 prices
6. **Typical entry ask: 0.51** (very close to fair at window open)
7. **Typical spread: 1¢** (bid/ask tight)

---

## 3. Kronos Accuracy on Apr 22-23 Real Data

| Timeframe | n | Baseline | Hour+DOW filter | Top 25% conf | All filters |
|---|---|---|---|---|---|
| 5m | 333 | **52.9%** | 49.7% ❌ | 48.8% ❌ | 48.8% ❌ |
| 15m | 111 | **51.4%** | 47.1% ❌ | 57.1% (n=28) | 66.7% (n=12) |

**The filters DO NOT GENERALIZE** out of the Jan-Mar training/test regime. The walk-forward warning from earlier analysis proved prescient — the hour-whitelist was curve-fit.

**Kronos's true, un-filtered accuracy on fresh data: ~52-53%.** This is at the breakeven threshold (~53% with fees + spread) — no tradable edge.

---

## 4. Backtest Results

### 4a. Simulated 69%-Accuracy Signal (Monte-Carlo)

Using a hypothetical signal at Kronos's measured Jan-Mar accuracy:
- Mean total PnL: **+$79 / 444 bets** (+17.8% ROI/bet)
- Profitable in **100% of 10,000 simulations**
- CI: [+$60, +$98]

**This validates the strategy mechanics would work IF the signal held.**

### 4b. Real Kronos Signal on Apr 22-23 Data

All 444 markets with real Kronos predictions:

| Strategy | Total PnL | 95% CI | Win% | ROI/bet | Exits (tgt/stp/trl/time/resolve) |
|---|---|---|---|---|---|
| S3 T0.70 + S0.35 | **+$7.84** | [-$11, +$28] | 51.8% | +1.76% | 11/89/0/0/344 |
| S2 Stop 0.35 | +$7.84 | [-$9, +$26] | 52.3% (5m-only) | +2.39% | 0/89/0/0/355 |
| S0 Hold-to-resolution | +$6.20 | [-$14, +$27] | 52.5% | +1.40% | 0/0/0/0/444 |
| S1 Target 0.55 | -$5.28 (5m) / +$5.52 (15m) | | 71% (15m) | — | varies |
| S4 Trail 10% | **-$6.79** | [-$31, +$17] | 47.7% | -1.53% | 0/0/244/0/200 |

**Every positive-PnL strategy has a 95% CI that includes zero.** Sample is too small + accuracy too close to breakeven to prove edge.

### 4c. Strategy Family Verdicts

| Family | Verdict | Why |
|---|---|---|
| **Hold-to-resolution** | ➖ Marginal, CI crosses 0 | 52.5% × $0.49 − 47.5% × $0.51 ≈ breakeven |
| **Wide stops (0.35-0.40)** | 👍 Slight improvement | Cuts worst losses without missing wins |
| **Tight stops (0.20-0.25)** | ➖ Neutral | Stops out too rarely to help |
| **Far targets (0.80-0.90)** | ➖ Same as hold | Targets rarely reached in 5m window |
| **Tight targets (0.55-0.60)** | ❌ Negative on 5m | Sells tiny wins, keeps tail risk |
| **Tight targets on 15m** | ⚠️ Marginal positive (+$5.52) | 15m has more volatility → 55¢ reachable |
| **Trailing stops** | ❌ Worst | Whipsawed by intra-bucket vol |
| **Time exits** | ❌ Negative | Locks in transitional prices mid-move |
| **Confidence filter + hold** | ⚠️ Mixed | Works on 15m (small n), hurts on 5m |

---

## 5. Root Cause of the Edge Loss

**Out-of-distribution degradation:**
- Fine-tuning cutoff: 2026-03-31
- Real test: 2026-04-22 → 04-23 (3 weeks later)
- Apr BTC regime likely different (volatility, flow, event-driven moves)
- Hour patterns that were predictive in Jan-Mar don't apply in Apr

**Supporting evidence from earlier analyses:**
- Walk-forward (Train Jan → Test Mar): filter acc 65.4% (SAW early degradation signal)
- Monthly Kronos accuracy: Jan 60%, Feb 59%, **Mar 54%** (trending down)
- Naive momentum baseline on Jan-Mar filter window: **52%** — close to Apr Kronos accuracy
- Implication: Kronos's "edge" on Jan-Mar may have been partial regime-fit, not purely generalizable pattern

---

## 6. Files & Artifacts

| File | Description |
|---|---|
| `kronos_ft/config_btc_5m_3y.yaml` | Kronos fine-tune config |
| `D:/kronos-ft/BTCUSDT_5m_3y_polymarket_short/basemodel/best_model/` | Trained model (409MB) |
| `results/kronos/ft_sniff_BTCUSDT_5m_3y_polymarket_short.csv` | 500-window Jan-Mar predictions |
| `results/kronos/kronos_polymarket_predictions.csv` | 444 real Apr 22-23 predictions |
| `data/polymarket/btc_markets.csv` | 455 resolved markets with entry/outcome |
| `data/polymarket/btc_trajectories.csv` | 20,272 10s-bucket trajectory rows |
| `results/polymarket/strategy_grid_all.csv` | Strategy backtest grid (56 strategies) |
| `reports/POLYMARKET_BACKTEST_V1.md` | Simulated 69% accuracy results |
| `reports/POLYMARKET_BACKTEST_REAL.md` | Real 5m Kronos results |
| `reports/POLYMARKET_BACKTEST_REAL_15m.md` | Real 15m Kronos results |
| `reports/POLYMARKET_BACKTEST_REAL_ALL.md` | Combined 5m+15m results |

---

## 7. Path Forward — What to Do Next

### Option A: Collect more data, retry in 1-2 weeks
- VPS collector runs 24/7 → ~340 new 5m markets per day
- 1 week = ~2,400 markets → 5× current sample size
- Re-run this exact backtest pipeline with tighter CIs
- If +$6/444 becomes +$30/2400 with CI [+$5, +$55], edge is proven

### Option B: Retrain Kronos with Apr data included
- Current model's cutoff = Mar 31
- Add Apr 1-22 to training set → retrain (~6h GPU)
- Then re-run inference on Apr 22-23 (1 min GPU)
- If accuracy jumps from 52.9% to 58%+, we have a live-trading signal

### Option C: Simpler models for this specific task
- A 2-layer GRU or even logistic regression on engineered features might capture what Kronos is doing, faster and more robustly
- Features: hour, minute-of-5m-cycle, BTC realized vol, prior N-bar return, session indicator
- Easier to debug, retrain, and productionize

### Option D: Different financial regime signal
- Add ETH + SOL once their Kronos fine-tunes are done
- Ensemble across 3 assets may stabilize out-of-regime performance
- Total potential bet volume: ~1,400 bets/day (vs 340 for BTC alone)

### Option E: Ship with realistic expectations
- Even +$6/444 at 52% accuracy is +1.4% ROI per bet → +$10/day at 1000 bets/day
- Scale via volume not edge: $100 bets × 1000 bets/day = $10K turnover, $140 gross profit expected
- But CI says daily P&L could swing $500+ either way. Risky.

### My recommendation
**Option B + A in parallel:**
1. Kick off Apr-extended retrain tonight (GPU, ~6h)
2. Let collector keep running on VPS
3. In 1 week: ~2,400 markets + updated model → decisive backtest
4. If statistically significant edge emerges → **start Option B path-to-live**
5. If not → pivot to Option C or cut scope

### What NOT to do
- ❌ Don't trade live on current Kronos — evidence is below threshold
- ❌ Don't over-engineer exit strategies — they don't fix a breakeven signal
- ❌ Don't apply the Jan-Mar hour/dow filter — it's overfit
- ❌ Don't trust the simulated 69%-accuracy backtest as a forecast — that accuracy isn't available

---

## Appendix: Kronos's 1-bar predictions vs naive baselines on Apr 22-23

| Predictor | 5m Acc | 15m Acc |
|---|---|---|
| **Kronos (real)** | **52.9%** | **51.4%** |
| Momentum (sign of last bar) | TBD | TBD |
| Always-UP | 50.2% | 44.1% |
| Always-DOWN | 49.8% | 55.9% |

**Note:** 15m's "always-DOWN" baseline hit 55.9% because the 2-day sample happened to have slightly more DOWN resolutions. That's a sample anomaly, not tradable signal.
