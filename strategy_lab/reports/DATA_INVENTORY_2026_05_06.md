# Data Inventory — VPS2 vs VPS3 vs Local
**Date:** 2026-05-06 14:15 UTC
**Trigger:** VPS2 deprecation in 10 days; planning FLOW engine + L25 orderbook backtest
**TL;DR:** VPS3 is the future. VPS2 has historical liquidations + slightly more orderbook coverage that needs migration. Local has only L10 — must refresh to L25.

---

## 1. Three-way comparison matrix

| Table | VPS2 | VPS3 | Local | Verdict |
|---|---:|---:|---:|---|
| `orderbook_snapshots_v2` (L25) | 35,455,134 | 33,963,993 | L10 only (~1M rows in `*_book_depth_v3_full.csv`) | ⚠ Local truncated to 10 levels; **VPS has 25** |
| → BTC | 27,870,053 | 26,651,734 | partial | small gap ~4% |
| → ETH | 5,286,988 | 5,086,378 | partial | small gap ~4% |
| → SOL | 2,307,315 | 2,234,950 | partial | small gap ~3% |
| `trades_v2` (Polymarket prints) | 20,060,662 | 17,578,986 | none | ⚠ VPS2 +13% history; **never pulled local** |
| `markets` (Polymarket UpDown markets) | 9,859 | 9,103 | 9,103 (`*_markets_minimal.csv`) | VPS2 has 756 older markets |
| `market_resolutions_v2` | 15,949 | 15,952 | 15,371 (`market_resolutions_full.csv`) | ✓ near-parity; local 4 days behind |
| `binance_klines_v2` (BTC/ETH/SOL all periods) | 2,088,706 | 2,070,144 | 39,772 (`binance_klines_full.csv`) | VPS3 has LIVE through 2026-05-06; VPS2 STOPPED 2026-04-29 (geoblock) |
| → BTC 1MIN binance-spot-ws | 18,897 (stops 04-29) | **28,878 (live to 05-06)** | partial | ✅ **VPS3 is the truth** |
| → BTC 1MIN binance-vision | 510,720 | 510,413 | partial | nearly identical history |
| `binance_liquidations_v2` | **195,745** | **0** | none | 🔴 **MIGRATE BEFORE VPS2 DIES** |
| `hyperliquid_liquidations_v2` | **5,088,771** | 72,337 | none | 🔴 **VPS3 missing 70x history — migrate** |
| `hyperliquid_klines_v2` | 108,723 | 108,435 | 14,836 | ✓ parity |
| `oracle_prices_v2` | 3,079,905 | 1,901,991 | none | 🟡 VPS2 has 60% more — migrate selectively |
| `binance_funding_rate_v2` | 3,735 | 3,735 | none | ✓ identical |
| `binance_metrics_v2` | 315,351 | 315,351 | none | ✓ identical |
| `cryptocap_dominance_v2` | 40,411 | 40,411 | none | ✓ identical |
| `onchain_fills_v2` | 0 | 0 | none | empty both sides |
| `latency_events` | unknown | unknown | none | non-trading metric |

---

## 2. Critical findings

### 2.1 L25 orderbook is on VPS, only L10 locally

Schema confirmed on both VPSs:
```
orderbook_snapshots_v2:
  timestamp_us, local_timestamp_us, exchange, slug, asset_id, outcome_id, source,
  bid_price_0..bid_price_24,  bid_size_0..bid_size_24,    ← 25 levels of bids
  ask_price_0..ask_price_24,  ask_size_0..ask_size_24     ← 25 levels of asks
```

Local file `btc_book_depth_v3_full.csv` header:
```
slug,timeframe,resolve_unix,window_start_unix,bucket_10s,outcome,snap_ts_us,
bid_price_0..bid_price_9,  bid_size_0..bid_size_9,    ← only L10
ask_price_0..ask_price_9,  ask_size_0..ask_size_9
```

**Gap: levels 10–24 (the deeper 60% of the book) never extracted.** For FLOW engine work — OB imbalance at deeper levels, liquidity walls, etc. — we need L25.

### 2.2 VPS2 binance kline collection DEAD after 2026-04-29

VPS2 `binance-spot-ws` BTC 1MIN max date = `2026-04-29`.
VPS3 `binance-spot-ws` BTC 1MIN max date = `2026-05-06` (today).

This matches our earlier finding ("VPS2 binance collector geoblocked 04-22"). VPS3 collector kept running. **For all post-04-29 backtests, VPS3 is the only valid source.**

### 2.3 VPS3 missing liquidation history

| Liquidation source | VPS2 | VPS3 |
|---|---:|---:|
| binance_liquidations_v2 | 195,745 | **0** |
| hyperliquid_liquidations_v2 | 5,088,771 | 72,337 |

VPS3 hyperliquid liquidation count starts only ~2 weeks ago. VPS2 has 5M+ rows = months of liquidation data.

**Cyclops uses liquidation magnets as Layer 3 triggers.** If we want to match that capability for our FLOW/TRIGGER work, we need the historical liquidation data on VPS3 BEFORE VPS2 deprecation.

### 2.4 VPS2 has 756 older markets + 2.5M older Polymarket trades

| Table | VPS2 | VPS3 | VPS2 dmin | VPS3 dmin |
|---|---:|---:|---|---|
| markets | 9,859 | 9,103 | 2026-04-08 | **2026-04-28** |
| trades_v2 | 20,060,662 | 17,578,986 | 2026-04-22 | 2026-04-22 (newer dataset starts later) |

VPS3's `markets` table only goes back to 2026-04-28. VPS2 has markets from 2026-04-08 → 2026-04-28. **20 days of older market metadata at risk.**

VPS3 `trades_v2` count is 13% lower despite same dmin — this is because the collector started later or had brief outages early. Need to verify whether the gaps are interleaved or trailing.

### 2.5 VPS3 legacy empty tables

VPS3 has 5 tables with 0 rows: `orderbook_snapshots`, `spot_candles`, `spot_trades`, `trades`, `binance_trades_v2`. These are old/abandoned schemas. Ignore.

---

## 3. Backfill plan — VPS2 → VPS3 (BEFORE DEPRECATION)

Priority by criticality. Run all in parallel `pg_dump → pg_restore` over SSH tunnel.

### 🔴 P0 — Pre-deprecation MUST migrate (10-day deadline)

**Migration A — `binance_liquidations_v2` full**
- 195,745 rows. ~30 MB compressed.
- VPS2 → VPS3 via `pg_dump -t binance_liquidations_v2 | psql`
- Effort: 30 min execution, 0 risk (VPS3 is empty for this table)

**Migration B — `hyperliquid_liquidations_v2` full historical**
- 5,016,434 missing rows (5,088,771 - 72,337). ~1 GB compressed.
- Migrate only rows older than VPS3 min date.
- Effort: 1-2 hr execution

**Migration C — `markets` 756 older rows (2026-04-08 → 2026-04-28)**
- 756 missing rows. ~500 KB.
- Filter on `created_at < (SELECT MIN(created_at) FROM vps3.markets)`
- Effort: 5 min

**Migration D — `oracle_prices_v2` historical gap (~1.18M rows)**
- VPS2 has 3.08M, VPS3 has 1.90M. ~250 MB.
- Migrate rows older than VPS3 min, or full table if simpler.
- Effort: 30 min

### 🟡 P1 — Older Polymarket trades + orderbooks (nice-to-have)

**Migration E — `trades_v2` historical Polymarket prints (older 2.5M)**
- VPS2 has 20.06M, VPS3 has 17.58M. ~500 MB.
- Risk: investigating WHY VPS3 has fewer (collector outage vs starting later) before blanket migration.
- Effort: 1 hr investigation + 2 hr migration

**Migration F — `orderbook_snapshots_v2` historical gap (~1.5M rows)**
- VPS2 has 35.46M, VPS3 has 33.96M. ~3 GB on disk.
- ~4% gap. Probably collector outages.
- Defer unless backtest explicitly needs the missing windows.

### 🟢 P2 — Operations

**Migration G — collector_status, latency_events, asset_market_map**
- Diagnostic tables. Skip unless needed.

---

## 4. Local refresh plan (local ← VPS3)

Local data is stale (newest = 2026-05-02 refresh). Local orderbook is L10 only.

### 4.1 Critical — pull L25 orderbook for the strategy lab

**Action:** rewrite `polymarket_extract_book_depth_full.sql` to project all 25 levels, and re-run the extract over the full date range.

```sql
-- target SQL
SELECT slug, timeframe, resolve_unix, window_start_unix, bucket_10s,
       outcome, snap_ts_us,
       bid_price_0..bid_price_24,  bid_size_0..bid_size_24,
       ask_price_0..ask_price_24,  ask_size_0..ask_size_24
FROM <existing aggregation CTE>
ORDER BY slug, snap_ts_us;
```

**Expected output:** ~3x the current file size (150MB → ~450MB per asset). Total ~1.4 GB for BTC+ETH+SOL.

**Effort:** rewrite SQL (15 min) + run extract on VPS3 (~10 min) + scp (~30 min on slow connection) = ~1 hr.

### 4.2 Refresh resolution + market data through 2026-05-06

The `refresh_2026_05_06/` dir already has:
- `klines_full.csv` (3.9M)
- `market_resolutions_full.csv` (1.3M)

Missing:
- L25 orderbook for the 2026-05-02 → 2026-05-06 window
- Updated `*_markets_minimal.csv`
- Updated `binance_spot_1min_full.csv` through 2026-05-06
- Updated `mr_full.csv`

**Effort:** ~1.5 hr including L25 refresh.

### 4.3 NEW — pull `trades_v2` for FLOW engine

We've never extracted `trades_v2` locally. For FLOW engine (CVD, aggressor ratio):
- 17.58M Polymarket trade prints on VPS3
- ~3-5 GB raw
- Need aggregation: 1m / 10s buckets per asset+market
- Effort: 2-3 hr (write extract SQL, aggregate, scp)

---

## 5. Recommended sequence (this week)

**Day 1 (today):**
1. Rewrite `polymarket_extract_book_depth_full.sql` for L25
2. Run on VPS3, scp to local
3. Pull updated klines + resolutions through 2026-05-06

**Day 2:**
4. Migrate `binance_liquidations_v2` VPS2→VPS3 (30 min)
5. Migrate `markets` older rows VPS2→VPS3 (5 min)
6. Migrate `oracle_prices_v2` historical gap (30 min)

**Day 3:**
7. Migrate `hyperliquid_liquidations_v2` historical (1-2 hr)
8. Investigate `trades_v2` gap VPS2 vs VPS3
9. Optionally migrate older Polymarket trades

**Day 4:**
10. Pull `trades_v2` aggregations to local (1m + 10s buckets)
11. Build FLOW feature pipeline (CVD, aggressor ratio, OB imbalance using L25)
12. Add `aux["flow_*"]` features alongside `aux["ret_5m"]`

**Day 5:**
13. Backtest V3 + FLOW UNION strategy
14. Backtest extreme-price filter (0.35-0.65)
15. Backtest smart counter-trend (mean reversion vs continuation)

---

## 6. Open questions for operator

1. Confirm VPS2 deprecation date so we can size the migration window precisely.
2. Should we keep VPS2 binance-vision historical kline data (510k rows × 3 assets × 6 periods) or accept VPS3's near-identical copy?
3. Is there a `liq_db` service the controller talks to that we should also point at VPS3 post-migration? (We saw `v3_2_liq_quiet_passes` reads from `liq_db`.)
4. Is `chat_messages` (VPS2-only table) actively used by trading-venue, or just collector dashboard? If trading uses it → migrate. Otherwise drop.

---

## 7. Files referenced

- This report: `strategy_lab/reports/DATA_INVENTORY_2026_05_06.md`
- L10 orderbook (current): `data/v4/refresh_2026_05_02/{btc,eth,sol}_book_depth_v3_full.csv`
- Target L25 orderbook (to create): `data/v4/refresh_2026_05_06/{btc,eth,sol}_book_depth_v3_L25.csv`
- Existing extract SQL: `strategy_lab/sql/polymarket_extract_book_depth_full.sql` (need L25 rewrite)
- Companion comparison report: `strategy_lab/reports/TRADINGVENUE_VS_CYCLOPS_2026_05_06.md`
