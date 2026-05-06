# Crypto Scalping — pivot from derivatives z-score to price-action scalps

**Source tutorial:** SMB-style 2-strategy scalping framework (Bella Fade + Offside).
**Goal:** find profitable scalps in 5-minute crypto data on the universe we already
have (BTC/ETH/SOL).

## The 3 pillars (verbatim)

1. **Pick 2 setups** to be great at. Target frequency 16-20 occurrences/week.
   Risk 5-10% of daily-stop per trade.
2. **Get timing right.** Most ideas should be passed; deploy capital only when
   multiple edges stack.
3. **Have a specific edge** with three predefined elements:
   - Risk Point (where stop sits — usually structural high/low)
   - Reasonable Expected Move (target via measured wave)
   - Shot Clock (max time the trade has to play out)

## Data we already have (5-min cadence)

| Symbol | Bars | Range | Years |
|---|---|---|---|
| BTCUSDT | 905,161 | 2017-08 → 2026-03 | 8.6y |
| ETHUSDT | 905,161 | 2017-08 → 2026-03 | 8.6y |
| SOLUSDT | 592,637 | 2020-08 → 2026-03 | 5.6y |

Columns per bar: `open / high / low / close / volume / quote_volume / trades /
taker_buy_base / taker_buy_quote`. **`taker_buy_quote / quote_volume` < 0.50 ⇒
sellers dominant** — perfect for "aggressive seller" detection.

## Stock → crypto adaptation map

| Stock-market concept | Crypto translation |
|---|---|
| "The open" | UTC daily open (00:00). Also test session opens: London (07:00 UTC), NY (13:30 UTC). 24/7 markets have no single open — these 3 anchors carry the most liquidity / repricing |
| "In-play stock" | High RVOL (24h volume > 1.5× 30d median) AND in a recent trend (price > MA20 for longs, < MA20 for shorts) |
| "Aggressive seller hunting liquidity" | `taker_buy_ratio = taker_buy_quote / quote_volume < 0.45` for ≥3 of last 5 bars, with cumulative return < -threshold |
| "Sloppy / forced selling" | high-range bars (range > 1.5× 20-bar median) + 3+ consecutive red closes |
| "Low of the day (LOD)" | Low since session anchor (per-anchor session) or rolling 24h low |
| "Descending trend line" | We approximate as: linear regression slope < 0 on the sell-off window. Break = price closes above the highest high of the last 3 bars |
| "Wave" / "measured move" | range height of the consolidation; or first momentum-stall in the rebound |
| "VWAP" | Daily-reset `cumsum(close * volume) / cumsum(volume)` |
| "2 cents below LOD" | 0.05-0.15% below LOD (per-asset; tighter for BTC, looser for SOL) |
| "Trapped traders rushing to exit" | volume spike + adverse close on the breakout-failure bar |
| "Shot clock" | bars (5-min units): typical scalp = 6-24 bars (30 min - 2 hours) |

## Strategy 1 — Bella Fade (long-only)

**Thesis:** strong asset gets dumped at session open by an aggressive seller.
Once they finish, the underlying strength reverts price up.

**Detection rules (5-min bars):**

```
session_anchor_bars = bars where minute resets at 00:00 / 07:00 / 13:30 UTC
in_play_long(t)   := vol_24h(t) > 1.5 × vol_30d_median(t) AND close(t) > ma_20_4h(t)
selloff_window(t) := look 4-8 bars back; check
                        cumulative_return < -SELLOFF_PCT  (e.g., -0.4% BTC, -1.0% SOL)
                        AND avg(taker_buy_ratio) < 0.45 over the window
                        AND ≥3 consecutive red closes
                        AND high-low range > 1.5× 20-bar median range (sloppiness)
trendline_break(t) := close(t) > max(high[t-3:t-1]) AND close(t) > close(t-1)

ENTRY long when: in_play_long(t) AND selloff_window detected ending at t-1
                 AND trendline_break(t)
                 AND we are within 60 minutes of an anchor
```

**Exit rules:**
- Stop: LOD - 0.10% (BTC) / -0.15% (ETH) / -0.20% (SOL)
- TP1: +1R, exit 50%
- TP2: +2R, exit 50%
- Shot clock: 12 bars (1 hour) — exit at market if no TP1 yet
- After TP1: trail stop to entry (move stop to break-even on remainder)

## Strategy 2 — Offside (long + short variants)

**Thesis:** trapped traders panic-cover after a failed breakout, fast move to the
opposite extreme of the consolidation range.

**Detection rules:**

```
trending_move(t)  := abs(close[t] - close[t-20]) > 1.5 × ATR(20)
                     (clear directional 100min move before consolidation)
range_window(t)   := find a 8-20 bar window ending at t-1 where:
                       (range_high - range_low) / mid_price < 0.4% (tight)
                       AND ≥2 high-bars within 0.05% of range_high (top tests)
                       AND ≥2 low-bars within 0.05% of range_low (bottom tests)
                       AND price near VWAP throughout (|close - vwap| / close < 0.2%)
failed_up(t)      := close(t-K..t-1) > range_high for ≥1 bar (breakout) AND
                     close(t) < range_high (back inside within K=2 bars)
                     AND volume on the failed bar > 1.5× window-avg volume
failed_down(t)    := mirror image: bar(s) below range_low, then close back inside

ENTRY short on failed_up + close < range_low (or close < midpoint with momentum)
ENTRY long  on failed_down + close > range_high (or close > midpoint with momentum)
```

**Exit rules:**
- Stop: outside the extreme of the failed breakout (e.g., short: range_high + 0.10%)
- TP: one measured-move from breakdown point (= range_height)
- Shot clock: range_window_bars / 2 (panic should be fast)
- No partial — full TP

## Quality filters (the "edge stacking" pillar #2)

A signal becomes a TRADE only when **multiple edges stack**:

- Bella Fade requires: `in_play_long` ✓ + `selloff_window` ✓ + `trendline_break` ✓
  + within session-anchor proximity ✓
- Offside requires: `trending_move` ✓ + `range_window` (with both top+bottom tests) ✓
  + `failed_breakout` with volume confirmation ✓ + near VWAP ✓

If we hit 16-20 trades/week per strategy across 3 symbols, we're in the right
zone. Far more = filters too loose. Far less = too tight.

## Risk model

- Account: 10,000 USDC starting equity
- Risk per trade: 1% of account (R = 1% × equity)
- Position sizing: `qty = (account × 0.01) / (entry - stop)` — fixed-R sizing
- Daily-stop: 3% of account; 3 consecutive losses → stop trading for 24h
  (per the tutorial's "scaling" suggestion, but conservative for backtest)
- Fees: 12bp round-trip (Hyperliquid taker × 2 + slippage)

## Engine

We **reuse** `strategy_lab/eval/perps_simulator_tp12.py` (TP1/TP2 partial-fill
two-tier engine — written for exactly this kind of partial-out scalp setup) as
the underlying simulator. Detectors emit entry timestamps + per-trade params
(stop, tp1, tp2, max_hold) which are fed into the simulator.

## Files

- `README.md`         — this analysis
- `data_loader.py`    — load 5m OHLCV across years; compute features
- `detect_bella_fade.py` — Bella Fade detector
- `detect_offside.py` — Offside detector
- `scalp_simulator.py`— per-trade engine (TP1/TP2/stop/shot-clock)
- `run_scalping.py`   — driver: detect → simulate → score → report

## Outputs

`strategy_lab/reports/scalping/`:
- `bella_fade/{sym}_signals.parquet` — every detected setup with metadata
- `bella_fade/{sym}_trades.csv` — trades after simulation
- `offside/{sym}_signals.parquet`
- `offside/{sym}_trades.csv`
- `SUMMARY.md` — frequency, win-rate, expectancy, per-asset edge

## Next iterations after MVP

1. Adaptive thresholds (calibrate SELLOFF_PCT and range tightness per-asset)
2. Volume-profile filter (avoid setups in dead-zone hours like 06:00-09:00 UTC)
3. Multi-symbol relative-strength gate (only fade when alts beat BTC; only short
   when alts lag BTC)
4. Add 3rd setup once 2 are profitable (per pillar #1, master 2 first then expand)
