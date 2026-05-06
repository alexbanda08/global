# Crypto Scalping — iter 2 (4 strategies, extended features)

**Window:** 2024-01-01 → 2024-12-31 (52 weeks, 105k 5-min bars/asset)
**Universe:** BTCUSDT, ETHUSDT, SOLUSDT
**Risk per trade:** 1.0% of equity
**Fees:** Hyperliquid 4.5bp/side taker + 1.5bp slippage

## What changed vs iter 1

**4 strategies running in parallel** (was 2):
- **Bella Fade**       (long-only) — dip-buy after seller exhaustion + OBV/CMF/vol-z gates
- **Offside**          (short-only) — failed-breakout fade with retest + OBV divergence
- **VWAP-Bounce** ★    (long-only) — pullback to VWAP + CMF/MFI/cum-delta confirmation
- **Liquidity-Sweep** ★ (long+short) — session high/low takeout reversal + delta divergence

★ = new in iter 2.

**Extended feature library** (`features.py`, 24 new indicators):
- Money flow: OBV, CMF, MFI, A/D Line, vol_z (volume z-score)
- Order flow: taker_delta (per-bar), taker_delta_z, cum_delta_session, aggression_imbalance
- Volume Profile (rolling 60-bar): POC / VAL / VAH / dist_poc_pct / inside_value_area
- VWAP bands: ±2σ / ±3σ + dist_vwap_sigma
- Liquidity sweeps: session_high_breach / session_low_breach / sweep_reclaim_high / sweep_reclaim_low

## Per-strategy results (full 2024)

| Symbol | Strategy | n | per_wk | WR | PF | avg ret/trade | total $PnL | final eq× |
|---|---|---|---|---|---|---|---|---|
| BTC | bella_fade | 24 | 0.46 | 45.8% | 0.49 | -0.244% | $-577 | 0.942× |
| BTC | offside | 3 | 0.06 | 33.3% | 0.15 | -0.528% | $-158 | 0.984× |
| BTC | vwap_bounce | 365 | 6.98 | 36.2% | 0.54 | -0.175% | $-4,779 | 0.522× |
| BTC | liquidity_sweep | 320 | 6.12 | 38.4% | 0.45 | -0.314% | $-6,398 | 0.360× |
| ETH | bella_fade | 27 | 0.52 | 33.3% | 0.35 | -0.326% | $-849 | 0.915× |
| ETH | vwap_bounce | 353 | 6.75 | 41.4% | 0.71 | -0.102% | $-3,091 | 0.691× |
| ETH | liquidity_sweep | 290 | 5.55 | 40.3% | 0.53 | -0.291% | $-5,773 | 0.423× |
| SOL | bella_fade | 27 | 0.52 | 33.3% | 0.54 | -0.170% | $-456 | 0.954× |
| SOL | vwap_bounce | 221 | 4.23 | **44.3%** | **0.72** | -0.104% | $-2,097 | 0.790× |
| SOL | liquidity_sweep | 286 | 5.47 | **44.1%** | **0.77** | -0.131% | $-3,248 | 0.675× |

## Aggregate (per strategy, cross-asset)

| Strategy | n | per_wk | WR | PF | avg ret | sum PnL |
|---|---|---|---|---|---|---|
| bella_fade | 78 | 0.50 | 37.5% | 0.46 | -0.25% | $-1,882 |
| offside | 3 | 0.06 | 33.3% | 0.15 | -0.53% | $-158 |
| vwap_bounce | 939 | 5.99 | 40.6% | 0.66 | -0.13% | $-9,967 |
| liquidity_sweep | 896 | 5.71 | 40.9% | 0.58 | -0.25% | $-15,420 |
| **TOTAL** | **1,916** | **12.3** | **40.5%** | **0.56** | **-0.20%** | **-$27,427** |

## Honest finding

**All 4 patterns are net-negative on 2024 majors.** The frequency target is hit
(combined ~12 trades/wk per asset, close to tutorial's 16-20/wk), but the
**win-rate ceiling is ~45%** across every strategy and asset — that's 7-8
percentage points below the ~52% needed to break even on 1:1 R:R + fees.

The pattern is consistent enough to be informative:

| | BTC | ETH | SOL |
|---|---|---|---|
| Avg WR across strategies | 39% | 38% | **42%** |
| Avg PF across strategies | 0.41 | 0.46 | **0.66** |

**SOL shows the most signal** — best PF on every strategy. Two explanations:
1. SOL has more intraday chop (more reversal patterns work)
2. SOL has wider relative ranges (stops further from entry → fewer noise-stops)

**The single closest-to-profitable variant**: SOL Liquidity-Sweep **longs** —
130 trades, **WR 48.5%, PF 0.96, avg -0.018%, only -$455** over the year.
Essentially break-even. With 1 percentage point of WR improvement OR
asymmetric R:R (1.2R targets), this would flip positive.

## Why iter 2 didn't deliver

The patterns we built are all **counter-trend / mean-reversion** plays:
- Bella Fade: fade aggressive sellers after exhaustion
- Offside: fade failed breakouts
- VWAP-Bounce: fade pullbacks at VWAP
- Liquidity-Sweep: fade stop-hunts

In **strongly trending** markets (BTC/ETH 2024 was up ~150% / ~46% with
multi-week runs), counter-trend patterns get steamrolled. Every "exhaustion"
is followed by another wave; every "failed breakout" turns out to be a real
breakout that just retested first; every VWAP touch is the start of a deeper
selloff.

The metrics confirm: **40-45% WR is a flat-coin scenario** with a slight
negative drift from fees. The patterns aren't broken — they're untimely.

## Iteration 3 plan

The iter-2 stack is good infrastructure. Iter 3 should add **regime gating
+ asymmetric R:R**, not more patterns.

### A. Regime gate (highest priority — single-most-likely fix)

Compute a daily regime label from the existing 5m features:
```python
regime[t] := "TRENDING_UP"  if close[t] > ma_24h[t] AND
                              (close[t]/close[t-288d] - 1) > 0.02 AND
                              realized_vol_30d_4h[t] > 0.4
             "TRENDING_DOWN" if mirror
             "CHOP"          if |close - ma_24h| / ma_24h < 0.5%  AND
                                realized_vol_30d_4h < median
             "VOLATILE"      otherwise (high vol + no clear direction)
```

Strategy gates:
- **VWAP-Bounce, Bella Fade**: only fire in CHOP or end-of-TRENDING_DOWN regimes
- **Offside**: only fire in CHOP regimes
- **Liquidity-Sweep shorts**: enable in TRENDING_UP (catch terminal blow-offs)
- **Liquidity-Sweep longs**: enable in TRENDING_DOWN (catch capitulation lows)
- **Liquidity-Sweep longs+shorts**: in CHOP (already best — 48% WR on SOL)

Expected impact: if 60% of 2024 was trending and we filtered those out, we'd
keep ~40% of trades in the regime where the patterns work, lifting WR from
40% to ~50-55%.

### B. Asymmetric R:R (second priority)

Current: 1:1 to 1.2:1 R:R. With 40-45% WR, expectancy = 0.40 × 1.2R - 0.60 × 1R = -0.12R.

Instead, target **1.5R-2R** with the same stop:
- WR will drop a bit (more time-stops without hitting target)
- But each winner is bigger
- 35% WR × 2R - 65% × 1R = +0.05R per trade (just barely positive)

Best candidate: VWAP-Bounce on SOL (PF 0.72 already, just needs target stretch).

### C. Trend-follow variant (deferred)

The mirror of every counter-trend strategy is a trend-follow variant:
- **Bella Continuation**: don't fade aggressive sellers — short the next pullback
- **Offside Breakout-Continuation**: don't fade failed breakouts — long the
  TRUE breakouts (the ones that don't fail)
- **VWAP Reject**: don't long pullbacks to VWAP — short the bounces that fail
  to break VWAP from below

These are conjugate strategies — when counter-trend loses, trend-follow wins.
Build only after regime-gate is verified.

### D. Combined-quality score (deferred)

Replace AND-chain filtering with a weighted score:
```
score = w1 × cmf_pos + w2 × obv_rising + w3 × volume_spike +
        w4 × delta_aligned + w5 × inside_value_area + w6 × cum_delta_pos
```
Tune weights to maximize WR × frequency. Only enter when score > threshold.

## What's working well already

- **Infrastructure**: 4 detectors + 24-indicator feature library + sim
  + reporting all run end-to-end in ~75s for 1 year × 3 assets.
- **Signal density**: 12 trades/wk combined per asset is real — close to
  tutorial's 16-20/wk target. Patterns ARE firing.
- **SOL chemistry**: clear that SOL is the most amenable asset to this style.
  Iter 3 should focus there first, BTC last.
- **Liquidity-Sweep longs on SOL** (130 trades, PF 0.96): one tiny tweak
  away from positive expectancy. The signal logic is sound.

## Files (iter 2)

```
strategy_lab/scalping/
  README.md
  data_loader.py             — basic features
  features.py                — 24 extended features (OBV/CMF/MFI/VP/VWAP-bands/sweep/delta)
  detect_bella_fade.py       — iter 2: ATR stop, 1.2R target, OBV/CMF gates, whipsaw pre-check
  detect_offside.py          — iter 2: retest, vol-spike, OBV divergence, short-only
  detect_vwap_bounce.py      — NEW: pullback to VWAP + CMF/MFI/cum-delta confirmation
  detect_liquidity_sweep.py  — NEW: session high/low sweep + delta divergence
  scalp_simulator.py         — TP1/TP2 partial + single-target engines
  run_scalping.py            — driver: detect → sim → score → SUMMARY for all 4

strategy_lab/reports/scalping/
  ITER2_SUMMARY.md (this file)
  scalping_results_iter2.csv
  bella_fade/{sym}_signals.parquet, {sym}_trades.csv
  offside/{sym}_signals.parquet, {sym}_trades.csv
  vwap_bounce/{sym}_signals.parquet, {sym}_trades.csv
  liquidity_sweep/{sym}_signals.parquet, {sym}_trades.csv
  equity/{sym}_{strategy}.parquet  (4 per asset)
```
