# Strategy Discovery — Fresh Context (2026-05-16)

**Use this document to bootstrap a NEW session focused on finding strategies.** No prior assumptions, no momo/v3 baggage. You have a complete local data lake; this doc tells you what's in it and how to read it.

---

## 0. The 30-second mental model

You're trading **Polymarket "Up/Down" binary options** on **BTC/ETH/SOL** with 5-minute and 15-minute settlement windows. Each market resolves to "Up" if the underlying spot price went up over the window, "Down" otherwise. The resolution truth comes from **Chainlink Data Streams** (1Hz oracle).

Your competitive surface is:
- **The CLOB itself** (Polymarket's order book) — bid/ask on YES/NO shares of "Up"
- **Cross-venue spot prices** — Binance, Coinbase, Kraken, OKX (you can compare to the CLOB-implied probability)
- **Trades flow** on the CLOB — informed-trader detection
- **Hyperliquid perp signals** — funding, liquidations, OI changes (correlated risk-on/risk-off)
- **Oracle feed** — chainlink RTDS price (the resolution truth)

Each Polymarket market opens, accumulates a book, then settles at slot_end (= slot_start + 5min or 15min). You can **enter** at any time before slot_end, **hold** to settlement, or **exit** early (sell back to CLOB / hedge with the opposite side).

---

## 1. Quick start — copy this into your script

```python
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

from load import (
    # universe
    load_resolutions,                    # 24,438 chainlink-resolved BTC/ETH/SOL × 5m/15m markets
    # underlying spot prices
    load_klines, load_klines_asof,       # 1MIN multi-venue (binance/coinbase/kraken/okx)
    load_klines_1s,                      # 1SEC binance (9.95M rows, Apr 7 → May 16)
    load_binance_vision_klines,          # 1-year history (1MIN/5MIN/15MIN/1HRS/4HRS/1DAY)
    load_okx_klines,                     # OKX 1MIN/5MIN/15MIN
    load_chainlink_rtds, load_chainlink_asof,   # 1Hz oracle truth
    # Polymarket order book + trades
    load_orderbook_l25_streaming,        # 25-level book snapshots, Apr 18 → May 16
    load_tier1_entries,                  # pre-joined L25 book at slot_start+120s
    load_trades,                         # all CLOB trades, 32M rows
    # Hyperliquid perp signals (cross-asset correlation)
    load_hyperliquid_klines,             # HL perp OHLCV
    load_hyperliquid_trades,             # 13.6M HL trades 30d
    load_hyperliquid_liquidations,       # 30d HL liqs (BTC/ETH/SOL/HYPE)
    load_hyperliquid_liquidations_full,  # 5.2M HL liqs back to May 2025
    load_hyperliquid_funding,            # HL funding 1H
    load_hyperliquid_metrics,            # OI / mark / oracle / mid
    # Macro / regime
    load_cryptocap_dominance,            # BTC dom + total cap, back to 2014
    load_binance_metrics,                # Perp OI / long-short ratios / taker volume
    # Production engine telemetry (independent reference)
    load_trading_events,                 # 30d audit log from VPS3 production controllers
    # utilities
    asof_strict,                         # causal-correct end-time-indexed asof lookup
    slug_to_ws_s, add_ws_s, ret_2m_at_ws,  # production anchor helpers (see §6)
)
import pandas as pd
import numpy as np

# Example: universe of BTC 5m markets in the last 7d
res = load_resolutions(assets=["BTC"], timeframes=["5m"])
recent = res[res.slot_start_us > (res.slot_start_us.max() - 7*86400_000_000)]
print(f"{len(recent)} BTC 5m markets in last 7 days")
```

---

## 2. Datasets — everything you have locally

### 2.1 Market universe (the playing field)

| dataset | file | rows | coverage | loader | purpose |
|---|---|---:|---|---|---|
| Chainlink-resolved markets | `canonical/resolutions_from_rtds.parquet` | 24,438 | 2026-04-24 → 2026-05-16 | `load_resolutions(source='rtds')` | Backtest universe. Outcome = chainlink truth, zero binance contamination. |
| Upstream resolutions | `canonical/resolutions.parquet` | 25,212 | 2026-04-22 → 2026-05-16 | `load_resolutions(source='upstream')` | Wider window, trusts VPS-side derivation. |
| Markets catalog | (in resolutions) | 21k | open + active | — | Slug, condition_id, clob_token_ids, platform, timeframe. |

**Columns of `load_resolutions()`:**
- `market_id` (= polymarket condition_id), `slug` (e.g. `btc-updown-5m-1778025900`)
- `ticker` (BTC/ETH/SOL), `timeframe` (5m/15m)
- `slot_start_us`, `slot_end_us` (UTC microseconds)
- `outcome` ('Up' / 'Down') — derived from chainlink RTDS at slot boundaries
- `strike_price`, `settlement_price`, `delta_price`
- `strike_ts_us`, `settle_ts_us`

**Slug format:** `<asset>-updown-<tf>-<slot_start_seconds>`. The trailing integer is the unix timestamp (seconds) of `slot_start_us / 1e6`.

```python
# Markets active in a specific 1-hour window
import pandas as pd
res = load_resolutions()
window_start = pd.Timestamp("2026-05-10 12:00", tz="UTC").timestamp() * 1e6
window_end   = window_start + 3600 * 1e6
hour = res[(res.slot_start_us >= window_start) & (res.slot_start_us < window_end)]
```

### 2.2 Orderbook L25 — the Polymarket CLOB (5.5 GB, 70M rows)

| file | rows | coverage | notes |
|---|---:|---|---|
| `refresh_2026_05_16/cache_pre/btc_orderbook_L25_pre_apr22.parquet` | 7.4M | Apr 18 → Apr 22 | VPS2-only history, no longer on VPS |
| `refresh_2026_05_06/cache/btc_orderbook_L25.parquet` | 28.1M | Apr 22 → May 6 14:05 | baseline |
| `refresh_2026_05_16/cache/btc_orderbook_L25_delta.parquet` | 19.5M | May 6 14:00 → May 16 06:08 | verified 100% vs VPS3 |
| (ETH and SOL: same structure, smaller) | | | |

**Each row = one orderbook snapshot.** Columns:
- `timestamp_us` (UTC us)
- `slug`, `market_id`, `outcome` (Up/Down — the side of the book)
- `ask_price_0..24`, `ask_size_0..24` — 25 ask levels (price 0-1, size in shares)
- `bid_price_0..24`, `bid_size_0..24` — 25 bid levels

```python
# Load all books for a specific BTC market
slugs = {"btc-updown-5m-1778025900"}
books = load_orderbook_l25_streaming("btc", slugs=slugs, subsample_1hz=True)
# books is dict[(slug, outcome) -> (ts_us[N], ap[N,25], asz[N,25], bp[N,25], bsz[N,25])]
for (slug, outcome), (ts, ap, asz, bp, bsz) in books.items():
    print(slug, outcome, len(ts), "snapshots")
```

**Production fill model — L25 book walk:**
```python
from strategy_lab.book_walk import book_walk_fill
# walks asks for $25 notional, returns (vwap, shares, usd_spent, hit_levels, under_filled)
vwap, shares, usd, _, under = book_walk_fill(list(ap_at_t), list(asz_at_t), 25.0)
```

**Production fee model:** 2% on **profit only** (winning leg), no fee on losses or losing leg. Implement as `profit - max(profit, 0) * 0.02`.

### 2.3 Polymarket CLOB trades (1.4 GB, 32M rows)

| file | rows | coverage |
|---|---:|---|
| `canonical/trades_polymarket/btc.parquet` | 24M | Apr 22 → May 16 |
| `canonical/trades_polymarket/eth.parquet` | 6M | same |
| `canonical/trades_polymarket/sol.parquet` | 2.7M | same |

**Columns:** `timestamp_us, exchange, market_id, slug, asset_id, outcome, price, size, side, trade_id, origin_asset_id`

`side` = `BUY` / `SELL` from the taker perspective. **Direction-aware trade flow** is the most underused signal in the dataset — every fill tells you which side was the aggressor.

```python
trades = load_trades("btc")
trades = trades[trades.slug == "btc-updown-5m-1778025900"]
# CVD (cumulative volume delta) for Up-side
up = trades[trades.outcome == "Up"].copy()
up["signed_size"] = np.where(up.side == "BUY", up.size, -up.size)
up["cvd"] = up.signed_size.cumsum()
```

### 2.4 Underlying spot klines

| dataset | file | rows | coverage | venues |
|---|---|---:|---|---|
| Klines 1MIN multi-venue | `canonical/klines_1m.parquet` | 502k | Apr 8 → May 16 | binance-spot-ws, coinbase-spot-ws, kraken-spot-ws |
| Klines 1SEC binance | `canonical/klines_1s.parquet` | 9.95M | Apr 7 → May 16 | binance-spot-ws (live) + binance-vision (archive) |
| Binance-vision archive | `canonical/binance_vision_klines.parquet` | 1.97M | **Apr 27 2025 → Apr 28 2026** (~1 year) | binance-vision (1MIN/5MIN/15MIN/1HRS/4HRS/1DAY) |
| OKX klines | `canonical/okx_klines.parquet` | 99k | Apr 28 → May 16 | okx-ws (1MIN/5MIN/15MIN) |

**Columns:** `symbol_id, period_id, source, time_period_start_us, time_period_end_us, price_open/high/low/close, volume_traded, trades_count, quote_volume`

**Symbol naming:** `BINANCE_SPOT_BTC_USDT`, `COINBASE_SPOT_BTC_USD`, `KRAKEN_SPOT_BTC_USD`, `OKX_SPOT_BTC_USDT`.

```python
# Compare CLOB-implied probability to binance spot at a specific time
end_us, prices = load_klines_asof("BTC", "binance-spot-ws", "1MIN")
target = pd.Timestamp("2026-05-10 12:34:00", tz="UTC").timestamp() * 1e6
close = asof_strict(end_us, prices, int(target))
```

### 2.5 Chainlink RTDS (the oracle that settles markets)

| file | rows | coverage |
|---|---:|---|
| `canonical/chainlink_rtds.parquet` | 5.39M | Apr 24 01:38 → May 16 03:47 (1Hz × BTC/ETH/SOL) |

**This is the resolution truth.** A market resolves "Up" if `chainlink_price(slot_end) > chainlink_price(slot_start)`. Markets where chainlink data is missing within ±60s of either boundary get dropped (no fake resolution).

```python
ts_us, cl = load_chainlink_asof("BTC")
strike     = asof_strict(ts_us, cl, slot_start_us)
settlement = asof_strict(ts_us, cl, slot_end_us)
outcome    = "Up" if settlement > strike else "Down"
```

### 2.6 Hyperliquid perp data (cross-venue derivative pressure)

| dataset | file | rows | coverage |
|---|---|---:|---|
| HL klines | `canonical/hyperliquid_klines.parquet` | 181k | Jan 30 → May 16 (BTC/ETH/SOL/HYPE × 6 TF) |
| HL trades 30d | `canonical/hyperliquid_trades_30d.parquet` | 13.6M | Apr 30 → May 16 |
| HL liquidations 30d | `canonical/hyperliquid_liquidations_30d.parquet` | 312k | rolling |
| **HL liquidations FULL** | `canonical/hyperliquid_liquidations_full.parquet` | **5.23M** | **May 2025 → May 2026 (1 year)** |
| HL funding | `canonical/hyperliquid_funding.parquet` | 10k | Jan 30 → May 16, hourly |
| HL metrics | `canonical/hyperliquid_metrics.parquet` | 89k | Apr 30 → May 16 (mark/oracle/mid/OI/volume) |

**HL liquidations columns:** `time_exchange_us, block_time_us, coin (BTC/ETH/SOL/etc), side (B/A), dir, price, size, liquidated_user, counterparty_user, ...`. A cascade of liquidations on HL often precedes a spot price move on Binance — useful as an "imminent volatility" signal.

```python
liqs = load_hyperliquid_liquidations_full("BTC")
# 5-min rolling liquidation notional
liqs["notional"] = liqs.price.astype(float) * liqs["size"].astype(float)
liqs["ts"] = pd.to_datetime(liqs.time_exchange_us, unit="us", utc=True)
liqs = liqs.set_index("ts")
rolling_5m_notional = liqs.notional.rolling("5min").sum()
```

### 2.7 Macro context

| dataset | file | rows | coverage |
|---|---|---:|---|
| **CryptoCap dominance** | `canonical/cryptocap_dominance.parquet` | 40k | **2014-04-01 → 2026-05-01 (12 years)** |
| **Binance perp metrics** | `canonical/binance_metrics.parquet` | 315k | Apr 27 2025 → Apr 27 2026 (1 year) |

CryptoCap is BTC dominance, total crypto market cap, stablecoin caps — daily granularity. Useful for regime overlays (bull/bear, risk-on/risk-off).

Binance metrics: open_interest, top-trader long/short ratio, taker volume ratio — per-symbol, perp futures. The OI changes and ratio shifts often lead spot.

### 2.8 Tier 1 entries (production-fired book at ws+120s)

| file | rows |
|---|---:|
| `canonical/tier1_entries_at_t120/{btc,eth,sol}.parquet` | ~15k each |

Pre-joined snapshot of the L25 book at `slot_start + 120s` for every resolved market in the universe. Use this when you want a quick "what would I have seen if I fired at t+2min?" without loading the full L25 stream. **Note:** built against the resolutions universe of May 6, may need a rebuild for fresher markets.

### 2.9 Production engine telemetry (independent oracle of "what really happened")

| file | rows | coverage |
|---|---:|---|
| `canonical/trading_events_30d.parquet` | 174k | last 30 days |

The audit log from VPS3's production tradingvenue engine. Every signal evaluation, every fire, every skip, every resolution — with timestamps, sleeve IDs, JSON data blob.

```python
# Look at every audit reason emitted in the last 30d
events = load_trading_events()
print(events.groupby([events.sleeve_id, events.data.str.extract(r'"reason":"([^"]+)"', expand=False)[0]]).size().head(50))
```

This is your **ground-truth comparator**: when you backtest a new strategy, you can compare your simulated fires/skips to what production actually did. Different = bug or different gate logic.

---

## 3. The production engines (what's running on VPS3 right now)

These are the deployed sleeves you're competing against — and the audit data in `trading_events_30d.parquet` lets you see their decisions live. **You don't need to build anything compatible with these** — this is just for context.

### 3.1 momo family (5 sleeves)
- `momo` (v1), `momo_v2`, `sniper`, `volume`, plus an inverse variant `volume_INV_NIGHT`.
- Hedge policies: `HOLD` (no exit), `HEDGE` (fire opposite leg on price reversal), `SELL` (sell back to CLOB).
- Anchor: production observes `ret_2m` over the **PREVIOUS** 5m/15m slot's first 2 minutes (`ws_s = slot_start - window_s`).

### 3.2 v3 family (5 sleeves: v3, v3_1, v3_2, v3_3, v4)
- Different gate stacks on top of momo:
  - `v3` = per-asset quantile, no extras
  - `v3_1` = directional quantile + regime overlay + live-direction filter
  - `v3_2` = base quantile + hour blocklist + macro_2of3 + liq_quiet
  - `v3_3` = v3_2 + SOL-only MH-AND filter
  - `v4` = v3_1 + v3_2 (full stack)
- All 5 fire on BTC/ETH/SOL × 5m only currently.

### 3.3 What it tells you
The production telemetry shows what humans have already tried. **You don't have to** beat these specific configurations. Look for orthogonal signals: trades flow, HL liquidations, cross-venue spread, dominance regime shifts.

---

## 4. Convention crib sheet (DO NOT VIOLATE)

These have burned previous sessions:

### 4.1 Timestamps
- **All timestamps are UTC microseconds.** Never localize. Suffixes: `_us` (microseconds), `_s` (seconds), occasionally `_ms`.
- Column names tell you the unit. `timestamp_us`, `slot_start_us`, `time_period_start_us`, `time_exchange_us`, `funding_time_us`, `create_time_us`.

### 4.2 `ws_s ≠ slot_start` (THE big footgun)
```python
slug = "btc-updown-5m-1778025900"
slug_suffix     = 1778025900                       # SECONDS, = slot_start_us / 1e6
slot_start_us   = 1778025900 * 1_000_000
slot_end_us     = slot_start_us + 300 * 1_000_000  # 5m market → +300s
window_s        = 300                              # or 900 for 15m
ws_s            = slug_suffix - window_s           # = the PREVIOUS slot's slot_start
```
- Production's `ret_2m_at_signal` and `fire_us` anchor on **`ws_s`** (the start of the previous slot), not on `slot_start`. The 2-minute observation is over `[ws_s, ws_s + 120]`.
- If you anchor on `slot_start` you read the **first 2 minutes of the prediction window itself** → lookahead → backtest inflates hit rate 25-40 pp (~85% sim vs ~50% live).
- Use `slug_to_ws_s(slug, "5m")` from load.py. Sanity-check: `py -3 data/v4/canonical/_test_ws_s.py` should print `=== ALL CHECKS PASSED ===`.

### 4.3 `asof_strict` (causal-correct lookup)
```python
from load import asof_strict
end_us, prices = load_klines_asof("BTC", "binance-spot-ws", "1MIN")
# Returns close of the 1MIN bar that ENDED at-or-before target_us. Never future.
close_at_t = asof_strict(end_us, prices, target_us=some_us)
```
The bar must have **ENDED** at-or-before target, not started. For 1MIN bars: `end_us = time_period_start_us + 60_000_000`. Encoded in `load_klines_asof`.

### 4.4 Outcome = chainlink, never binance
The canonical resolutions are **chainlink-derived**. Some older datasets had binance fallback contamination (markets resolved by `binance.close > strike` when chainlink data was missing). Those add 5-10pp of false hit rate. Always use `load_resolutions(source='rtds')` (default) and trust its `outcome` column.

### 4.5 Spread filter + L25 walk
- Spread filter is applied at entry: `(ask_price_0 - bid_price_0) > threshold` → skip. Production threshold: BTC 0.02, ETH 0.02, SOL 0.025.
- Fill model: walk **asks** for $25 notional (default), VWAP across levels. If you can't fill at least 50% of $25, skip the trade.

### 4.6 Production fee
2% **on profit only** (winning leg of a hedge, or the won side if HOLD). No fee on losses or losing legs.
```python
def pnl_with_fee(profit_raw):
    return profit_raw - (max(profit_raw, 0) * 0.02)
```

---

## 5. Strategy idea space (NEW directions, no momo overlap)

This is your inspiration menu. Each is independent of any current sleeve. Pick one that excites you, build it.

### A. Trades-flow alpha (most underused dataset)
You have **32M CLOB trades** with side + size + timestamp per (slug, outcome). Aggressor-direction CVD per market should predict short-term price movement. Try:
- 30-second rolling CVD on the Up side of a market → enter if CVD > q90 (informed traders piling in).
- Net taker-buy aggression across the 2-minute pre-window vs 2-minute prediction window.
- "Big trade" detection: filter to size > $X, see if those moves anticipate settlement.

### B. Cross-venue arb / lead-lag
Coinbase + Kraken + OKX + Binance all stream 1MIN bars. Binance leads. But:
- When binance moves 1σ while coinbase/kraken stay flat → mean revert?
- OKX is futures-heavier — does OKX's print lead binance by N seconds?
- Build the "venue with the freshest move" as a directional signal.

### C. Hyperliquid liquidation cascades as triggers
You have 5.23M HL liquidations going back to May 2025. Liq cascades create temporary directional pressure on binance spot:
- 5-min rolling HL liq notional > $X → expect 5m bias for next 10-15 min.
- Side-specific: long liqs → expect downside continuation; short liqs → upside.
- Test against the 5m market that opens within Y minutes of the cascade.

### D. Funding/OI regime overlay
Binance perp open_interest and HL funding tell you positioning. Combine:
- High OI + tightening long-short ratio → expect compression then breakout direction.
- Funding flipping sign → directional bias change.
- Use this as a binary gate on any other signal: "only fire when regime says X".

### E. Book microstructure
You have 25-level books at 1Hz throughout each market's life. So far everyone uses just level-0:
- Book imbalance at top 5 levels: `sum(bid_size_0..4) / (sum(bid_size_0..4) + sum(ask_size_0..4))`.
- Slope of the book (price impact for $100, $1000, $10000): predictive of which way trade flow will push.
- "Iceberg" detection: large bids replenishing at the same price.

### F. Cross-asset (multi-symbol)
You have BTC, ETH, SOL markets running in parallel. If BTC moves first:
- Does the BTC market settle faster than ETH/SOL? Then ETH/SOL markets are MORE predictable conditional on BTC outcome being decided.
- Pairs: BTC outcome agreed by spot move → bet on ETH/SOL inheriting the move.

### G. Dominance / macro regime
12 years of BTC dominance + total cap. Build:
- Daily regime: BTC dominance rising = BTC outperforms alts. → bias 5m markets toward BTC Up, SOL Down.
- Dominance flips often precede 1-3 day bias. Layer this as a multiplier on per-asset edge.

### H. Mispricing detection (the most direct edge)
CLOB-implied probability vs your computed "fair probability":
- p_clob = `1 - mid_price_of_up_side`. If market YES price is $0.42, then CLOB says P(Up) = 42% (if buying YES) or 58% (if selling YES).
- Compute fair P(Up) from binance momentum + book imbalance + HL signal.
- Bet on the gap. Most direct, hardest to engineer the fair-value model.

### I. Long-horizon backtest (1 year)
You have binance-vision 1-year history. Build a strategy that uses **only** binance OHLCV + cryptocap dominance + binance perp metrics — no L25 needed. Test on 1 year. If it works, you have something robust.

---

## 6. Common patterns / code skeletons

### 6.1 Build a "fire event" backtest harness
```python
from data.v4.canonical.load import (
    load_resolutions, load_klines_asof, asof_strict, slug_to_ws_s
)

res = load_resolutions(assets=["BTC"], timeframes=["5m"])
end_us, prices = load_klines_asof("BTC", "binance-spot-ws", "1MIN")

def predict(row):
    ws_s = slug_to_ws_s(row.slug, row.timeframe)
    p_now = asof_strict(end_us, prices, int(ws_s + 120) * 1_000_000)
    p_2m_ago = asof_strict(end_us, prices, int(ws_s) * 1_000_000)
    return "UP" if p_now > p_2m_ago else "DOWN"

res["my_signal"] = res.apply(predict, axis=1)
hit = (res.my_signal == res.outcome.str.upper()).mean()
print(f"Naive momentum hit rate: {hit:.3f}")
```

### 6.2 Walk the L25 book at fire time
```python
from strategy_lab.book_walk import book_walk_fill

books = load_orderbook_l25_streaming("btc", slugs={"btc-updown-5m-1778025900"})
ts, ap, asz, bp, bsz = books[("btc-updown-5m-1778025900", "Up")]
# At fire_us, find the snapshot
fire_us = (slug_to_ws_s("btc-updown-5m-1778025900", "5m") + 120) * 1_000_000
i = np.searchsorted(ts, fire_us, side="right") - 1
ap_now = ap[i].tolist(); asz_now = asz[i].tolist()
vwap, shares, usd, _, under = book_walk_fill(ap_now, asz_now, 25.0)
print(f"Fill at {vwap:.4f}, got {shares:.2f} shares for ${usd:.2f}")
```

### 6.3 Compute trade CVD per market
```python
trades = load_trades("btc")
trades_m = trades[trades.slug == "btc-updown-5m-1778025900"].copy()
trades_m = trades_m[trades_m.outcome == "Up"].sort_values("timestamp_us")
trades_m["signed"] = np.where(trades_m.side == "BUY", trades_m["size"].astype(float),
                                                       -trades_m["size"].astype(float))
trades_m["cvd"] = trades_m.signed.cumsum()
```

### 6.4 Get all HL liqs in a 10-minute window before a market opens
```python
res = load_resolutions(assets=["BTC"], timeframes=["5m"]).head(100)
liqs = load_hyperliquid_liquidations_full("BTC")
liqs["ts_us"] = liqs.time_exchange_us
# For each market, sum liq notional in [slot_start - 10min, slot_start]
def liqs_pre(slot_start_us):
    lo, hi = slot_start_us - 600 * 1_000_000, slot_start_us
    sub = liqs[(liqs.ts_us >= lo) & (liqs.ts_us < hi)]
    return float((sub.price.astype(float) * sub["size"].astype(float)).sum())
res["liq_notional_pre"] = res.slot_start_us.apply(liqs_pre)
```

---

## 7. Validation patterns (do these before celebrating)

1. **Anchor sanity test**: `py -3 -X utf8 data/v4/canonical/_test_ws_s.py` — confirms slug_to_ws_s helpers are consistent.

2. **No-lookahead test**: Pick 100 random markets. For each, your signal at `fire_us` must use ONLY price/book data with timestamp `< fire_us`. Print 10 random samples and eyeball.

3. **Production cross-check**: For 50 markets that production actually fired on, compare your simulated decision (`UP`/`DOWN`/`SKIP`) to production's `data.signal` field. Production-correct backtest matches >95%. If you're at 75%, you have a bug.

4. **Permutation test (1000 draws)**: Sign-flip signals randomly per trade. Your observed PnL should be in the top decile (p<0.1) of the null distribution. If p > 0.5 the "edge" is noise.

5. **Walkforward (rolling 7d train / 1d test)**: Refit any thresholds per train window. OOS sharpe < 0 → strategy doesn't generalize.

---

## 8. File map (where every file lives)

```
data/v4/
├── canonical/                                      <-- read everything from here
│   ├── resolutions.parquet                          (25,212 / upstream)
│   ├── resolutions_from_rtds.parquet                (24,438 / chainlink-only) ← DEFAULT
│   ├── chainlink_rtds.parquet                       (5.4M  / Apr 24 → May 16, 1Hz)
│   ├── klines_1m.parquet                            (502k  / multi-venue 1MIN)
│   ├── klines_1s.parquet                            (10M   / binance 1SEC)
│   ├── binance_vision_klines.parquet                (1.97M / 1-year archive)
│   ├── okx_klines.parquet                           (99k   / OKX 1MIN/5MIN/15MIN)
│   ├── hyperliquid_klines.parquet                   (181k  / HL perp OHLCV)
│   ├── hyperliquid_trades_30d.parquet               (13.6M / HL trades 30d)
│   ├── hyperliquid_liquidations_30d.parquet         (312k  / HL liqs 30d)
│   ├── hyperliquid_liquidations_full.parquet        (5.23M / HL liqs 1yr) ←
│   ├── hyperliquid_funding.parquet                  (10k   / HL funding hourly)
│   ├── hyperliquid_metrics.parquet                  (89k   / HL OI/mark/oracle)
│   ├── cryptocap_dominance.parquet                  (40k   / 12-year macro)
│   ├── binance_metrics.parquet                      (315k  / binance perp metrics 1yr)
│   ├── trading_events_30d.parquet                   (174k  / production telemetry)
│   ├── trades_polymarket/
│   │   ├── btc.parquet                              (24M)
│   │   ├── eth.parquet                              (6M)
│   │   └── sol.parquet                              (2.7M)
│   ├── tier1_entries_at_t120/
│   │   └── {btc,eth,sol}.parquet                    (book at ws_s+120 per market)
│   ├── load.py                                       <-- ALL loaders defined here
│   ├── build.py                                      <-- rebuild from refresh dirs
│   ├── README.md
│   └── clob_resolutions_cache.parquet
│
├── refresh_2026_05_06/cache/                       <-- L25 baseline Apr 22 → May 6
│   ├── btc_orderbook_L25.parquet                    (28.1M)
│   ├── eth_orderbook_L25.parquet                    (5.3M)
│   ├── sol_orderbook_L25.parquet                    (2.3M)
│   └── *_flow_features.parquet                      (feature engineering outputs)
│
└── refresh_2026_05_16/
    ├── cache_pre/                                   <-- L25 Apr 18-22 (VPS2-only, irreplaceable!)
    │   └── {btc,eth,sol}_orderbook_L25_pre_apr22.parquet
    └── cache/                                       <-- L25 delta May 6 → May 16
        └── {btc,eth,sol}_orderbook_L25_delta.parquet (verified 100% vs VPS)
```

**Rule:** Always read through `canonical/load.py`. Never hardcode parquet paths. The loader is the abstraction.

---

## 9. How to refresh data (when you start a new session in N days)

The collectors keep running on VPS2 + VPS3. To pull the latest delta:

1. Top up canonical resolutions + klines + chainlink:
   ```bash
   py -3 -X utf8 data/v4/canonical/build.py --step resolutions
   py -3 -X utf8 data/v4/canonical/build.py --step chainlink
   py -3 -X utf8 data/v4/canonical/build.py --step klines
   py -3 -X utf8 data/v4/canonical/build.py --step resolutions-from-rtds
   ```

2. Top up L25 delta:
   ```bash
   bash migration_2026_05_12/pull_l25_full_window_2026_05_16.sh   # edit W_LO/W_HI dates
   py -3 -X utf8 migration_2026_05_12/convert_l25_combined_2026_05_16.py
   ```

3. Top up everything else (trades, HL, events):
   ```bash
   bash migration_2026_05_12/pull_tier_all_vps3.sh
   bash migration_2026_05_12/pull_remaining_all.sh
   py -3 -X utf8 migration_2026_05_12/convert_tier_all_2026_05_16.py
   ```

Pull scripts on VPS3 take ~5-20 min depending on table. **Don't rely on this being instant on a new session day.**

**Critical reminder:** VPS3 retains orderbook data ~24 days. Anything older than that is GONE from production and must be in your local cache. If you skip a week, you can re-pull the recent week but you can't go further back.

---

## 10. What this document is NOT

- **Not a strategy.** No claims about what edges exist. Just data + tools.
- **Not a production system.** Your backtests are NOT what production does. The trading.events log is the only ground truth for production behavior.
- **Not coupled to momo/v3.** Forget the production sleeves exist. Start from data.

---

## 11. The first hour of your fresh session

1. Read this document.
2. Run the quick-start prelude (§1). Confirm `len(load_resolutions())` prints ~24,438.
3. Pick ONE idea from §5. Write 50 lines of code that:
   - Loads the relevant data via canonical loaders
   - Computes a signal per (slug, fire_us)
   - Compares the signal direction to `outcome`
4. Print hit rate + total PnL assuming flat $25 entries with the L25 walk fill model.
5. Sanity-check no lookahead.
6. If hit rate > 55% AND signal volume > 50 trades — write it up, run permutation test, decide if it's worth more work.

Most ideas die at step 4 (random hit rate). That's expected. **Cycle fast.**

---

*Generated 2026-05-16. Local data: 19 GB. Coverage: BTC/ETH/SOL Apr 18 → May 16 2026 for L25; 1-year for klines and HL liquidations; 12 years for macro dominance.*
