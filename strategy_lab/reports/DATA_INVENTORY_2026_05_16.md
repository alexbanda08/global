# Canonical Data Inventory — 2026-05-16

**Last refresh:** 2026-05-16 07:30 UTC. **Total local size:** ~21 GB across `data/v4/`.
**All sessions / backtests MUST read through:** `from data.v4.canonical.load import *`.

This document supersedes `DATA_INVENTORY_2026_05_15.md`. Now includes data from BOTH VPS2 and VPS3 (independently collected; merged on the local side).

---

## Sources

| host | role |
|---|---|
| **VPS2** (Contabo, IPv6 `root@[2605:a140:2323:6975::1]`) | independent polymarket collector + multi-venue CEX klines + hyperliquid_klines |
| **VPS3** (`root@185.190.143.7`) | tradingvenue engine + binance feed + chainlink RTDS + production `trading.events` + binance 1SEC bars + binance-vision archive |

Both VPS independently collect `orderbook_snapshots_v2`, `trades_v2`, `oracle_prices_v2`, `market_resolutions_v2`. On overlap windows they have **identical row counts** (synced upstream).

**Differences:**
- VPS2 has ~4 days more orderbook history (starts 2026-04-18 vs VPS3's 2026-04-22).
- VPS3 has binance 1SEC klines (10M rows), binance-vision archive (1.97M rows, 1 year), full multi-venue (binance/coinbase/kraken).
- VPS2 has OKX klines (1MIN/5MIN/15MIN) which VPS3 lacks.
- VPS2 has hyperliquid_klines_v2 (181k rows, Jan 30 onwards) which VPS3 lacks.
- VPS3 has 2.5× more hyperliquid_trades_v2 and hyperliquid_liquidations_v2 (more retention).

---

## What's locally available now

### 1) Polymarket orderbook L25 — **VERIFIED 100% coverage** Apr 18 → May 16

Path | rows | size | window
---|---:|---:|---
`refresh_2026_05_16/cache_pre/btc_orderbook_L25_pre_apr22.parquet` | 7,385,574 | 739 MB | 2026-04-18 18:07 → 2026-04-22 (VPS2-only history) |
`refresh_2026_05_16/cache_pre/eth_orderbook_L25_pre_apr22.parquet` | 1,618,697 | 172 MB | same |
`refresh_2026_05_16/cache_pre/sol_orderbook_L25_pre_apr22.parquet` | 681,834 | 75 MB | same |
`refresh_2026_05_06/cache/btc_orderbook_L25.parquet` | 28,108,891 | 2.87 GB | 2026-04-22 15:51 → 2026-05-06 14:34 (baseline) |
`refresh_2026_05_06/cache/eth_orderbook_L25.parquet` | 5,330,469 | 0.62 GB | same |
`refresh_2026_05_06/cache/sol_orderbook_L25.parquet` | 2,323,361 | 0.26 GB | same |
`refresh_2026_05_16/cache/btc_orderbook_L25_delta.parquet` | 19,507,923 | 1.89 GB | 2026-05-06 14:00 → 2026-05-16 06:08 |
`refresh_2026_05_16/cache/eth_orderbook_L25_delta.parquet` | 3,454,668 | 0.41 GB | same |
`refresh_2026_05_16/cache/sol_orderbook_L25_delta.parquet` | 1,659,480 | 0.19 GB | same |

**Total per-asset:**
- BTC: 55,002,388 rows, 5.5 GB → matches VPS2 BTC count exactly
- ETH: 10,403,834 rows, 1.2 GB
- SOL: 4,664,675 rows, 0.5 GB

**Load via:** `load_orderbook_l25_streaming(asset, slugs=...)` — automatically reads all 3 caches and dedups by `(slug, outcome, second)` if `subsample_1hz=True`.

### 2) Polymarket trades — **FULL** Apr 22 → May 16 (replaces stale May 6 cache)

| file | rows | size | window |
|---|---:|---:|---|
| `canonical/trades_polymarket/btc.parquet` | 24,002,995 | 991 MB | 2026-04-26 → 2026-05-16 |
| `canonical/trades_polymarket/eth.parquet` | 6,042,172 | 320 MB | same |
| `canonical/trades_polymarket/sol.parquet` | 2,677,331 | 147 MB | same |

**Load via:** `load_trades(asset)`. Columns: `timestamp_us, exchange, market_id, slug, asset_id, outcome, price, size, side, trade_id, origin_asset_id, ...`

### 3) Klines (multi-venue, multi-timeframe)

| file | description | rows | size | coverage |
|---|---|---:|---:|---|
| `canonical/klines_1m.parquet` | binance/coinbase/kraken 1MIN (multi-venue 1-minute bars) | 487,854 | 22 MB | 2026-04-08 → May 16 (binance), Apr 27 2025 → Apr 28 2026 (vision-1MIN) |
| `canonical/klines_1s.parquet` | **NEW** — binance 1SEC bars (live ws + vision archive) | 9,950,385 | 293 MB | 2026-04-07 → 2026-05-16 |
| `canonical/binance_vision_klines.parquet` | **NEW** — binance-vision archive (all TFs 5MIN/15MIN/1HRS/4HRS/1DAY) | 1,970,724 | 92 MB | 2025-04-27 → 2026-04-28 (~1 year) |
| `canonical/okx_klines.parquet` | **NEW** — OKX 1MIN/5MIN/15MIN klines | 98,975 | 4 MB | 2026-04-28 → present |
| `canonical/hyperliquid_klines.parquet` | **NEW** — HL perp 1MIN/5MIN/15MIN/1HRS/4HRS/1DAY (BTC/ETH/SOL/HYPE) | 181,339 | 6 MB | 2026-01-30 → present |

**Loaders:** `load_klines(asset, source, period_id)`, `load_klines_asof(...)`, `load_klines_1s(...)`, `load_binance_vision_klines(...)`, `load_okx_klines(...)`, `load_hyperliquid_klines(...)`.

### 4) Chainlink oracle (resolution truth)

| file | rows | size | coverage |
|---|---:|---:|---|
| `canonical/chainlink_rtds.parquet` | 5,389,616 | 90 MB | 2026-04-24 01:38 → 2026-05-16 03:47 (1Hz × BTC/ETH/SOL) |

**Load via:** `load_chainlink_rtds(asset)`, `load_chainlink_asof(asset)`.

### 5) Resolutions / universe

| file | rows | size | coverage |
|---|---:|---:|---|
| `canonical/resolutions_from_rtds.parquet` | 24,438 | 2.6 MB | 2026-04-24 → 2026-05-16 (chainlink-derived locally) |
| `canonical/resolutions.parquet` | 25,212 | 2.6 MB | upstream union (VPS2 + VPS3 market_resolutions_v2) |

**Load via:** `load_resolutions(assets=['BTC','ETH','SOL'], timeframes=['5m','15m'])`. Default source `'rtds'` (locally-derived). Set `with_clob_winner=True` to enrich with Polymarket CLOB winner.

### 6) Tier1 entries (production-correct book at ws+120s)

| file | rows | size |
|---|---:|---:|
| `canonical/tier1_entries_at_t120/btc.parquet` | 15,808 | 4.6 MB |
| `canonical/tier1_entries_at_t120/eth.parquet` | 15,406 | 3.2 MB |
| `canonical/tier1_entries_at_t120/sol.parquet` | 14,146 | 2.6 MB |

**Note:** Built against chainlink-only universe. May be stale relative to fresh resolutions — rebuild with `build.py --step tier1` to refresh.

### 7) Hyperliquid feed (NEW)

| file | rows | size | coverage |
|---|---:|---:|---|
| `canonical/hyperliquid_trades_30d.parquet` | 13,613,686 | 561 MB | 2026-04-30 → 2026-05-16 (30d rolling) |
| `canonical/hyperliquid_liquidations_30d.parquet` | 312,208 | 21 MB | 2026-04-16 → 2026-05-16 (30d rolling) |
| `canonical/hyperliquid_liquidations_full.parquet` | **5,228,388** | **338 MB** | **2025-05-25 → 2026-05-16 (~1 year)** |
| `canonical/hyperliquid_funding.parquet` | 10,176 | 0.2 MB | 2026-01-30 → present (hourly per asset) |
| `canonical/hyperliquid_metrics.parquet` | 88,588 | 5 MB | 2026-04-30 → present (mark/oracle/mid/OI/volume) |

**Load via:** `load_hyperliquid_trades(asset)`, `load_hyperliquid_liquidations(asset)` (30d) or `load_hyperliquid_liquidations_full(asset)` (1-year), `load_hyperliquid_funding(asset)`, `load_hyperliquid_metrics(asset)`. Asset is 'BTC' / 'ETH' / 'SOL' / 'HYPE'. Symbol matching: HL trades/funding/metrics use `symbol_id = HYPERLIQUID_PERP_<ASSET>_USD`; HL liquidations use `coin = <ASSET>`.

### 8) Production trading.events (NEW)

| file | rows | size | coverage |
|---|---:|---:|---|
| `canonical/trading_events_30d.parquet` | 173,643 | 14 MB | last 30 days |

**Load via:** `load_trading_events(kind='poly_updown_signal', sleeve_id_like='%v3_1%')`. The `data` column is JSON-as-string — use `json.loads` or `pd.json_normalize` to extract `reason`, `signal`, etc.

### 9) Market-context datasets (NEW)

| file | rows | size | coverage |
|---|---:|---:|---|
| `canonical/cryptocap_dominance.parquet` | 40,411 | 2.6 MB | **2014-04-01 → 2026-05-01** (12+ years of BTC/ETH dominance + total cap) |
| `canonical/binance_metrics.parquet` | 315,351 | 19 MB | 2025-04-27 → 2026-04-27 (perp open_interest, long/short ratios, taker volume ratio) |

**Load via:** `load_cryptocap_dominance(symbol_id, period_id)`, `load_binance_metrics(symbol)`. Useful for regime overlays, longer-horizon backtests.

---

## Critical conventions (DO NOT VIOLATE)

- **Timestamps are UTC microseconds.** Never localize. `timestamp_us`, `slot_start_us`, `time_period_start_us`, `time_exchange_us`.
- **`ws_s ≠ slot_start`.** Production controller anchors `ret_2m` and `fire_us` on `ws_s = slot_start - window_s` (the PREVIOUS slot's start). Use `slug_to_ws_s(slug, tf)` from load.py. Anchoring on slot_start instead inflates hit rate 25-40pp due to lookahead.
- **Outcome = Chainlink Data Streams**, never binance. `resolutions_from_rtds` filters this.
- **Binance is the SIGNAL source** (production controller's feed). Coinbase/Kraken/OKX for ablation.
- **`asof_strict(end_us, prices, target_us)`** — close of bar that ENDED at-or-before target. Strict causal lookup.
- **L25 entry walk** is the production fill model. `book_walk_fill(prices, sizes, $25)` from `strategy_lab/book_walk.py`.
- **Production fee model**: 2% on profit only (winning leg), no fee on losses.

---

## Quick start (any session)

```python
import sys; sys.path.insert(0, "data/v4/canonical")
from load import (
    load_resolutions,                        # 24,438 markets, chainlink-only
    load_klines, load_klines_asof,           # 1MIN multi-venue (binance/coinbase/kraken/okx)
    load_klines_1s,                          # NEW: 1SEC binance bars (10M rows)
    load_binance_vision_klines,              # NEW: 1-year archive, all timeframes
    load_okx_klines,                         # NEW: OKX 1MIN/5MIN/15MIN
    load_hyperliquid_klines,                 # NEW: HL perp klines (BTC/ETH/SOL/HYPE)
    load_hyperliquid_trades,                 # NEW: 13.6M trades 30d
    load_hyperliquid_liquidations,           # NEW: 312k liqs 30d
    load_hyperliquid_liquidations_full,      # NEW: 5.2M liqs 1-year
    load_hyperliquid_funding,                # NEW: 10k funding rows
    load_hyperliquid_metrics,                # NEW: 88k metrics (OI, mark/oracle/mid)
    load_cryptocap_dominance,                # NEW: 40k rows, 2014 -> 2026
    load_binance_metrics,                    # NEW: 315k perp metrics (OI, ratios)
    load_trading_events,                     # NEW: production audit log 30d
    load_chainlink_rtds, load_chainlink_asof,
    load_orderbook_l25_streaming,            # streaming, filter by slugs
    load_tier1_entries,
    load_trades,                             # NOW FRESH Apr 22 -> May 16 (was stale May 6)
    asof_strict,
    slug_to_ws_s, add_ws_s, ret_2m_at_ws,    # production anchor helpers
)
import pandas as pd

# Universe (chainlink-only, May 16 fresh)
res = load_resolutions(assets=["BTC"], timeframes=["5m"])   # 5,887 markets

# Production signal feed
end_us, prices = load_klines_asof("BTC", "binance-spot-ws", "1MIN")

# Higher-resolution signal at 1Hz (new!)
end_us_1s, prices_1s = ... # build from load_klines_1s("BTC", source="binance-spot-ws")

# Orderbook (3-cache merged, dedup by 1Hz)
gated_slugs = set(res.slug.head(100))
books = load_orderbook_l25_streaming("btc", slugs=gated_slugs)

# Liquidation triggers (new!)
liqs = load_hyperliquid_liquidations("BTC")

# Production telemetry (new!)
fires = load_trading_events(kind="poly_updown_signal", sleeve_id_like="%v3_1%")
```

---

## Audit history & verification

- L25 verified 100% vs VPS3 row count (47.6M BTC) on 2026-05-16. Apr 18 → May 16 fully covered.
- 05_06 baseline = source of truth for Apr 18 → May 6 14:05 (the 4-day Apr 18-22 prefix is from VPS2 only; the rest is identical to VPS3).
- 05_16 delta = full 100% coverage of May 6 14:00 → May 16 06:08, no missing chunks.
- 05_09 and 05_12 deltas SUPERSEDED by 05_16. Kept on disk for ~1.4 GB; can be deleted to reclaim space (no longer referenced by `load.py`).

---

## Known issues / open work

1. **trades_polymarket may grow stale** — next session should re-pull if timestamp > 24h old. No automatic delta pull yet.
2. **HL trades/liqs/trading.events are 30d rolling** — VPS3 retains 30d on these tables. Pull more frequently for continuous history.
3. **binance 1SEC live coverage starts May 7 21:16** — earlier 1SEC data is in `binance-vision` archive (Apr 7 → May 6 23:59:59) which has slightly different schema/source label.
4. **VPS2 collector still active** — could be queried for delta if VPS3 retention drops. Use as failover.
5. **No daily cron yet** — manual `pull_l25_full_window_2026_05_16.sh` + `pull_tier_all_vps{2,3}.sh` runs needed to keep fresh.

---

## Files / scripts referenced

| path | purpose |
|---|---|
| `migration_2026_05_12/pull_l25_complete_2026_05_16.sh` | L25 May 10-17 delta pull (VPS3) |
| `migration_2026_05_12/pull_l25_gap_may6_may10.sh` | L25 gap-fill May 6-10 (VPS3) |
| `migration_2026_05_12/pull_l25_full_window_2026_05_16.sh` | L25 May 14-17 generic pull (VPS3) |
| `migration_2026_05_12/pull_tier_all_vps2.sh` | VPS2 tier 1+2 backfill (orderbook pre-Apr22, OKX, HL klines) |
| `migration_2026_05_12/pull_tier_all_vps3.sh` | VPS3 tier 1+2+3 backfill (1SEC, vision, trades, HL feed, events) |
| `migration_2026_05_12/convert_tier_all_2026_05_16.py` | Convert all CSV.gz → parquet, place in canonical |
| `migration_2026_05_12/convert_l25_combined_2026_05_16.py` | L25 stream-converter (memory-bound BTC) |
| `data/v4/canonical/load.py` | All canonical loader functions |
| `data/v4/canonical/build.py` | Canonical rebuild from refresh CSVs |

---

*End of inventory. Generated 2026-05-16 ~07:30 UTC.*
