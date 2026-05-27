# QuantMuse mining — honest verdict + 3 indicators worth testing

_2026-05-23. Surveyed `0xemmkty/QuantMuse` (2.6k stars, factor-based quant
framework). **Verdict: mostly NOT applicable** — it's a stock-screening
framework for daily/monthly equity portfolios, not microstructure trading.
But 3 standard TA indicators we haven't tested are worth porting._

---

## What QuantMuse is (and why most of it doesn't fit)

| What it does | Why it doesn't apply to us |
|---|---|
| **Stock screeners** (Momentum, Value, Quality, MultiFactor, MeanReversion) | We trade BINARY OPTIONS, not equities — no portfolio to rebalance |
| **Factor models** (P/E, P/B, ROE, dividend yield) | None of these factors exist for `BTC-updown-5m-1779504600` |
| **Monthly/quarterly rebalancing** | Our markets settle in 5 minutes |
| **Daily momentum (20-60 day)** | Our momentum lives in 1-300 seconds |
| **LLM sentiment analysis** | Already covered by polymarket-bot mining (and not worth porting) |
| **ML model wrappers** (sklearn/XGBoost/LightGBM) | Wrong scale; our M1V Markov already does the equivalent |

The 5 built-in strategies (Momentum, Value, Quality, MultiFactor, MeanReversion)
are all stock pickers with monthly cadence. **Cannot port directly.**

---

## What IS worth porting — 3 indicators

These are standard TA primitives buried in `data_service/ml/feature_engineering.py`
that **we haven't tested yet** and CAN be computed from our 1s OHLCV+CVD data.

### Indicator A — **Bollinger Band position** (`bb_position`)

```
bb_middle = SMA(close, N)
bb_std    = STDEV(close, N)
bb_upper  = bb_middle + 2·bb_std
bb_lower  = bb_middle - 2·bb_std

bb_position = (close - bb_lower) / (bb_upper - bb_lower)      # 0 = at lower band, 1 = at upper
bb_width    = (bb_upper - bb_lower) / bb_middle                # vol-of-vol
```

**Why interesting**: VWAP measures average price; BB measures price RELATIVE
TO VOLATILITY. When `bb_position > 0.95` and dev_bps > 5bps, we have BOTH
"price is at the top of its vol envelope" AND "binance is above VWAP" —
likely a different signal than either alone.

**Test on our data**: compute at multiple windows (30s, 60s, 120s, 300s of
1s bars) and bucket VWAP-continuation fires by bb_position tier.

### Indicator B — **Money Flow Index (MFI)**

```
typical_price = (high + low + close) / 3
money_flow    = typical_price · volume
positive_mf   = sum(money_flow where TP_t > TP_{t-1}) over N bars
negative_mf   = sum(money_flow where TP_t < TP_{t-1}) over N bars
mfi           = 100 - 100 / (1 + positive_mf / negative_mf)         # 0-100 oscillator
```

**Why interesting**: combines price action AND volume into a single
oscillator. Different from CVD (which only counts buy-vs-sell volume) and
different from RSI (which only counts price). MFI catches divergences
where price moves but volume disagrees.

**Test on our data**: compute MFI at 30s/60s window on 1s bars. Overlay
on top of spike-driven fires (S6) — fade fires where MFI > 80 (overbought
+ price spike up = exhaustion).

### Indicator C — **Stochastic Oscillator** (sub-minute)

```
%K = 100 · (close - lowest_low_N) / (highest_high_N - lowest_low_N)
%D = SMA(%K, 3)
```

**Why interesting**: %K measures where the current close sits within the
recent N-bar high-low range. At 60s window on 1s bars: %K > 80 means the
close is in the top 20% of the last minute's range. Combined with our
spike detector, this catches "spike into new local high" vs "spike from
the middle of the range".

**Test on our data**: overlay on spike-driven fires; bucket by %K tier.
Hypothesis: spike + %K > 80 (breakout into new range) has higher WR than
spike + %K mid-range.

---

## What we already have that QuantMuse doesn't add

- **RSI(14) at ws_s** — F7 gate, production-verified at 94.67% match
- **Markov regime (M1V, M5V)** — vol-adaptive tertile classifier (more
  principled than RSI bands for regime detection)
- **CVD slope** — buy/sell flow imbalance from `taker_buy_base`
- **15m-anchored and slot-anchored VWAP** with dev_bps
- **Spike detection** at 5s/15s/30s with CVD confirmation
- **Cross-asset confluence** (BTC/ETH/SOL synchronization)
- **L25 book walk fills** via `engine_v2`

The QuantMuse indicators that would have been useful (RSI, MACD, basic
momentum) we already have via F7 + ret_2m + Markov.

---

## Verdict + recommendation

**Don't write a comprehensive QuantMuse backtest.** The ROI is much lower
than yesterday's mlmodelpoly mining (which produced S1 and gave us the
Black-Scholes fair value model).

**DO write a single combined experiment** that adds bb_position, MFI, and
%K as overlays on the existing winning fires (S1.5 slot-anchored + S6
spike-driven) and tests if any new gate combination pushes WR meaningfully.

Estimated upside: +2-5pp WR on a subset of cells if the indicators capture
something orthogonal to what we already have. Could add 1-3 new sleeves at
85%+ WR.

If none of the 3 indicators improves on existing gates, we close the
"QuantMuse mining" line and move on.

---

## Suggested implementation

Build `strategy_lab/meta_classifier/quantmuse_indicators_overlay.py` that:

1. Loads `vwap_slot_anchored_5m_per_fire.parquet` + `spike_entry_5m_per_fire.parquet`.
2. Loads 1s binance.
3. Computes bb_position(60s), bb_position(120s), mfi(60s), stoch_k(60s) at
   each fire's timestamp.
4. Buckets fires by:
   - bb_position tier (`<0.1`, `0.1-0.5`, `0.5-0.9`, `>0.9`)
   - MFI tier (`<20`, `20-50`, `50-80`, `>80`)
   - %K tier (`<20`, `20-50`, `50-80`, `>80`)
5. Reports WR / $/tr per (existing config × new indicator tier) cell.

Runtime estimate: ~10 minutes on existing data. No new data pulls needed.

---

## What we WON'T port from QuantMuse

| Item | Why skip |
|---|---|
| Stock screening framework | Wrong asset class |
| Factor optimizer (sharpe maximization) | Our 2^9 brute force already does this |
| LLM market analysis | Already saw in polymarket-bot |
| Backtest engine | We have engine_v2 (better for our microstructure use case) |
| Position sizing | Already covered by Kelly idea (S4 from polymarket-bot) |
| Multi-source data | We already have binance + chainlink + L25 |
| Realtime WebSocket framework | tv-engine already runs ws_mirror in production |

---

## Files

- Repo URL: https://github.com/0xemmkty/QuantMuse
- Source mined: `data_service/strategies/builtin_strategies.py`, `examples/quantitative_strategies.py`, `data_service/ml/feature_engineering.py`, `examples/factor_analysis_demo.py`
- Verdict authored: 2026-05-23

## End
