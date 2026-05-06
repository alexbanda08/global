# Deep Shadow Investigation — 2026-05-01

**Window:** 2026-04-30 06:10 → 2026-05-01 14:10 (1.33 days)
**Total resolutions:** 2,978
**Hosts:** VPS2 (V1 / OKX-WS) + VPS3 (V2 sniper + V3 / binance-spot-ws)

This document analyzes 4 open mysteries from the live shadow data.
**No actions, no recommendations to disable** — pure investigation.

---

## 🔍 Investigation 1: V1 (VPS2/OKX) vs V2 (VPS3/binance-WS) — same strategy, different feeds

Both VPS run identical volume-mode logic. The only difference is the price feed used to decide signal direction:
- **VPS2 = OKX WebSocket** (V1 control arm)
- **VPS3 = binance-spot-ws** (V2 test arm)

| Asset/TF | V1 (OKX) hit | V1 PnL | V2 (binance) hit | V2 PnL | Feed delta |
|---|---|---|---|---|---|
| BTC 5m | 49.3% | -$293 | 51.2% | +$51 | **+1.9pp / +$344 (V2)** |
| BTC 15m | 47.1% | -$273 | 49.6% | -$129 | **+2.5pp / +$144 (V2)** |
| ETH 5m | 44.6% | -$1,252 | 46.0% | -$1,048 | **+1.4pp / +$204 (V2)** |
| ETH 15m | 51.7% | -$31 | 53.6% | +$70 | **+1.9pp / +$101 (V2)** |
| SOL 5m | 45.4% | -$1,320 | 46.2% | -$1,205 | **+0.8pp / +$115 (V2)** |
| SOL 15m | 58.6% | +$279 | 57.8% | +$256 | -0.8pp / -$23 (V1) |

**Verdict:** binance-spot-ws feed beats OKX-WS by **1-3pp hit rate** on 5 of 6 sleeves. The 1.33-day cumulative feed-only edge is **+$885 across all 6 sleeves**.

**Why:** Polymarket UP/DOWN markets settle via Chainlink price oracle. Chainlink aggregates from multiple sources but binance is the largest BTC/ETH/SOL spot venue — so binance prices are systematically closer to Chainlink settlement than OKX.

**Implication:** the V1/V2 design intent (V1 as control arm) is now empirically validated. V2 is meaningfully better at the feed level alone, before any sniper logic. The ~30pp sim-to-live gap from earlier diagnostics is partly **feed accuracy** — confirms what S1 reconciliation guessed.

---

## 🔍 Investigation 2: Why did sniper hit rate crash from 55.7% (04-30) to 28% (05-01)?

### Day-by-day breakdown

**04-30 (n=61, hit=55.7%, PnL=+$120):**
- UP signals: 35 fires, 48.6% hit, -$51
- DOWN signals: 26 fires, 65.4% hit, **+$171**

**05-01 (n=25, hit=28.0%, PnL=-$292):**
- UP signals: **11 fires, 0.0% hit, -$278.75** ⚠
- DOWN signals: 14 fires, 50.0% hit, -$13

### Smoking gun: 05-01 UP signals went 0-for-11

Not a single UP signal hit on 05-01. Every magnitude-positive blip mean-reverted. The market spent 05-01 in a **sustained downtrend** that swallowed every counter-trend UP signal.

### Hour distribution on 05-01

| Hour | n | hit | PnL |
|---|---|---|---|
| 0 | 3 | 0% | -$75 |
| 1 | 1 | 0% | -$26 |
| 3 | 8 | 25% | -$107 |
| 4 | 3 | 0% | -$76 |
| 5 | 5 | 60% | +$18 |
| 6 | 2 | 100% | +$50 |
| 7 | 1 | 0% | -$26 |
| 10 | 1 | 0% | -$25 |
| 11 | 1 | 0% | -$25 |

Two effects compounded:
1. **Regime mismatch** — markets trending down, UP signals reverted (V3.1's hypothesis confirmed at scale)
2. **Bad hours dominated** — 14 of 25 fires were in hours 0-4 UTC (which Phase 1 backtest already flagged as weak)

### Per-asset on 05-01

| Asset | n | hit | PnL |
|---|---|---|---|
| BTC | 7 | 42.9% | -$28 |
| ETH | 7 | 28.6% | -$77 |
| SOL | 11 | **18.2%** | **-$187** |

SOL took the biggest hit (consistent with previous SOL UP findings — UP went 0% on n=many, DOWN held up).

**Verdict:** 05-01 wasn't a "broken model" — it was the simultaneous trigger of two known weakpoints (UP-regime mismatch + bad hours). Both are addressable in V3.1/V3.2 patches. Without those patches, the model bleeds in this regime.

---

## 🔍 Investigation 3: Why is SOL 15m volume UP outperforming so much?

n=106 fires, 64.2% hit, +$541.51 cumulative PnL, avg fill 0.5286.

### By date (the edge is GROWING)

| Date | n | hit | PnL |
|---|---|---|---|
| 04-30 | 62 | 61.3% | +$231 |
| 05-01 | 44 | **68.2%** | +$311 |

Edge is improving day-over-day, not a single-session anomaly.

### Cross-asset comparison (same TF, same mode, same period)

| Sleeve | n | hit | PnL |
|---|---|---|---|
| BTC 15m volume UP | 109 | 52.3% | +$33 (breakeven) |
| ETH 15m volume UP | 118 | 51.7% | -$38 (breakeven) |
| **SOL 15m volume UP** | **106** | **64.2%** | **+$541** |

This is **SOL-specific.** Same logic, same TF, same window — only SOL delivers edge.

### By hour (UP only, n≥3)

| Hour | n | hit | PnL |
|---|---|---|---|
| 0 | 6 | 100% | +$129 |
| 7 | 4 | 100% | +$88 |
| 23 | 8 | 75% | +$82 |
| 1 | 6 | 67% | +$39 |
| 9 | 6 | 67% | +$39 |
| 11 | 9 | 67% | +$59 |
| 12 | 6 | 67% | +$38 |
| 15 | 6 | 67% | +$36 |
| 21 | 6 | 67% | +$38 |
| 10 | 9 | **22%** | **-$133** ⚠ |
| 17 | 3 | 33% | -$29 |

Distributed positive across most hours. One bad hour (10 UTC) is the only -$ outlier and it's an n=9 sample.

### Hypothesis space

1. **SOL price/sentiment regime favors UP reversals at 15m horizon.** Volume mode fires after sustained directional flow. If SOL has been chopping, mean-reversion UP signals catch the bounce.
2. **Polymarket SOL 15m pricing is biased.** UP shares might be systematically cheap because retail biases DOWN on alts. Average fill 0.5286 is HIGHER than BTC/ETH, suggesting market expects UP less.
3. **Mechanical edge from settlement source.** Polymarket settles via Chainlink. SOL's Chainlink feed may have specific aggregation quirks that align with binance-WS volume-mode logic.
4. **Pure sample variance.** n=106 over 1.33 days; could be reverting to mean.

### What contradicts hypothesis 4

The cross-asset null result on BTC and ETH using **the exact same logic** suggests it's not pure variance — there's something SOL-specific. If it were variance, we'd expect at least one of BTC/ETH to coincidentally win too. Instead BTC/ETH are precisely at coin-flip.

### What contradicts hypothesis 1 (regime)

If it were regime-only, we'd expect a similar SOL edge in 5m volume too. But:
- SOL 5m volume UP: 44.5% hit on n=355, **-$1,530** — losing badly

So 15m is special, not just SOL. Specific to the 15m timeframe.

**Verdict:** open mystery. Most likely a **15m-specific structural edge in SOL UP signals** that disappears at 5m. Could be a real regime-fit edge or a sample artifact — needs 30+ days to disambiguate.

---

## 🔍 Investigation 4: 15m vs 5m sniper — backtest said 15m dilutes, live disagrees

### Aggregate sniper+V3 by timeframe

| TF | n | hit | PnL |
|---|---|---|---|
| 5m | 63 | 44.4% | **-$212** |
| 15m | 29 | **62.1%** | **+$132** |

Live: 15m hits 18pp BETTER than 5m. Backtest said the opposite (15m dilutes the portfolio).

### Per-asset 5m vs 15m sniper

| Asset | 5m n / hit / PnL | 15m n / hit / PnL |
|---|---|---|
| BTC | 20 / 65.0% / +$149 | 10 / 50.0% / -$6 |
| **ETH** | 13 / 30.8% / -$129 | **7 / 71.4% / +$63** |
| **SOL** | 24 / 25.0% / -$324 | **12 / 66.7% / +$75** |

**For BTC, 5m is better. For ETH and SOL, 15m is dramatically better.**

This is the OPPOSITE of the V3 portfolio decision (5m only, drop 15m). The backtest said 15m dilutes the COMBINED portfolio because the marginal 15m fires were mostly noise. But live data shows that the surviving 15m fires (after the bot's quantile gate) on alts are higher quality than 5m fires.

### Direction split on 15m sniper

| Sleeve | UP n / hit | DOWN n / hit |
|---|---|---|
| BTC 15m sniper | 3 / 66.7% | 7 / 42.9% |
| ETH 15m sniper | 4 / 50.0% | **3 / 100%** |
| SOL 15m sniper | 6 / 50.0% | **6 / 83.3%** |

Same UP/DOWN asymmetry as 5m: DOWN >> UP on alts. Even at 15m, alt UP signals are weaker than DOWN.

### Why the live/backtest divergence?

Three possibilities:

1. **Backtest sample window was during an UP-trending market** where 5m sniper benefited and 15m didn't show its edge. Live window is DOWN-trending, where 15m DOWN signals shine.
2. **15m fires have lower frequency** (29 vs 63 for sniper+V3), so they're more selective. The 12 SOL 15m sniper fires are top-of-quantile within a wider window — higher quality per fire.
3. **The backtest's "15m dilutes" claim was based on COMBINED ROI in a portfolio sense.** It assumed equal capital across TFs. But if 15m fires less often, naturally lower contribution to portfolio ROI even with equal per-trade quality.

### What this changes about the analysis

**Doesn't reverse the V3 decision** (5m-only) automatically — the backtest dilution finding may still be regime-specific. But **suggests 15m is worth re-considering** for ETH and SOL specifically, especially DOWN signals.

---

## 🧩 Cross-investigation patterns

Three findings tie together:

### 1. DOWN signals dominate on alts (BOTH timeframes)

| Sleeve | UP hit | DOWN hit |
|---|---|---|
| BTC 5m sniper | 58.3% | 75.0% |
| BTC 15m sniper | 66.7% | 42.9% |
| ETH 5m sniper | 25% | 40% |
| ETH 15m sniper | 50% | 100% |
| SOL 5m sniper | 7.7% | 45.5% |
| SOL 15m sniper | 50% | 83.3% |
| SOL 15m volume | 64.2% (UP wins on volume!) | 52.9% |

The UP/DOWN asymmetry is consistent across sniper sleeves on alts, both timeframes. The exception: SOL 15m **volume** mode where UP wins (different signal class).

### 2. Bad hours pile on bad regimes

The 05-01 crash wasn't independent of the hour issue — 56% of 05-01 fires (14/25) were in hours 0-4 UTC, which we already knew were weak from Phase 1 backtest. The "regime crash" is partly a "bad-hour concentration" event.

### 3. Feed quality matters at the margin

V2 (binance-WS) outperforms V1 (OKX-WS) by 1-3pp on hit rate. This is a structural edge from feed selection alone. Same strategy logic, different price source = +$885 over 1.33 days.

---

## Open questions for next iteration

1. **Does the SOL 15m volume UP edge persist?** Need 7+ more days to confirm it's not variance.
2. **Why is SOL 15m volume UP fill cost (0.5286) higher than DOWN (0.5251)?** If UP is winning at higher cost, it suggests genuine information edge, not just tape-following.
3. **Is the 15m sniper alt-edge regime-specific?** If we re-test the 15m portfolio backtest on this 1.33-day live window, does it now look profitable?
4. **What was the BTC trend on 05-01?** If it was strongly down, that explains UP-signal kill rate. Need to plot ret_5m / ret_1h against fire times.
5. **Are V1 and V2 firing on the SAME markets at the same times?** Investigation 5 showed similar fire counts (361 vs 373 BTC 5m) but didn't confirm same-market overlap. Could the 12-fire diff explain the V2 edge?

---

## Files

- `data/v4/shadow_trades_2026_05_01/{vps2,vps3}.csv` — raw dumps from both hosts
- `strategy_lab/v4_signals/shadow_deep_investigation.py` — investigation harness
- `strategy_lab/v4_signals/shadow_trades_analysis.py` — earlier surface-level analysis
- This report: `strategy_lab/reports/SHADOW_DEEP_INVESTIGATION_2026_05_01.md`
