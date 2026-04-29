# VPS Collector — Data Inventory (2026-04-27, post-backfill)

> **UPDATE 2026-04-27 17:00 CEST.** Metadata pipeline was fixed and `market_resolutions_v2` is now populated with strike/settlement prices from Chainlink. Numbers below reflect the live state. Section "Backtestable universe — POST-BACKFILL" supersedes the original blocker section at the bottom.

## Backtestable universe — POST-BACKFILL

**Total resolved markets: 5,689** (Apr 22 17:45 → Apr 27 16:20 CEST, ~5 days continuous).

| Asset | Timeframe | n | Up | Down | Up rate |
|---|---|---|---|---|---|
| BTC | 5m | **1,423** | 718 | 705 | 50.5% |
| BTC | 15m | **474** | 226 | 248 | 47.7% |
| ETH | 5m | 1,422 | 720 | 702 | 50.6% |
| ETH | 15m | 474 | 234 | 240 | 49.4% |
| SOL | 5m | 1,422 | 722 | 700 | 50.8% |
| SOL | 15m | 474 | 238 | 236 | 50.2% |

**BTC universe: 1,897 markets (1,423× 5m + 474× 15m) — 4.3× the prior 444-market sample.** Up rates are statistically indistinguishable from 50% on every cell — confirming the prior "always-DOWN 55.9% on 15m" was a 2-day noise artifact, not a tradable bias.

**Steady-state ingestion:** ~288× 5m + ~96× 15m BTC markets per full day = ~384 BTC markets/day per asset. Three assets (BTC/ETH/SOL) ⇒ ~1,150 markets/day total going forward.

**Resolution source:** Chainlink Data Streams for 100% of rows (`https://data.chain.link/streams/{btc,eth,sol}-usd`). Canonical, on-chain — no need for Binance lookback for resolution.

### New columns from the migration

`market_resolutions_v2` gained: `strike_price` (BTC USD at slot_start), `settlement_price` (BTC USD at slot_end), `price_source`. Populated on **5,545 of 5,689 (97.5%)** rows; the missing 144 are the oldest Apr 22 rows from before the migration. Sample:

| slug | outcome | strike | settle | source |
|---|---|---|---|---|
| btc-updown-15m-1777298400 | Up | 77,748.91 | 77,851.35 | chainlink |
| btc-updown-15m-1777297500 | Down | 77,856.08 | 77,748.91 | chainlink |
| btc-updown-15m-1777296600 | Up | 77,711.73 | 77,856.08 | chainlink |

This means **we no longer need Binance OHLCV joins for resolution** — strike + settlement come straight from the same oracle Polymarket uses. We still want Binance for *features* (lookback indicators, latency signal), but the ground truth is in-table now.

## Original report (pre-backfill — kept for history)

---

# VPS Collector — Data Inventory (2026-04-27)

VPS: Contabo `vmi3236975`, IPv6 only. Project at `/opt/storedata`. Collector runs as native systemd unit `storedata-collector.service` (active since 2026-04-27 14:20 CEST). Postgres + TimescaleDB on localhost, DB `storedata`, 39 GB.

## How much data we have

### Polymarket orderbook snapshots (`orderbook_snapshots_v2`)

| Metric | Value |
|---|---|
| Total snapshots | **13,581,158** |
| Distinct markets | **5,789** |
| Time range | 2026-04-22 16:47 → 2026-04-27 14:30 (≈5 days continuous) |
| Avg snapshots / market | 2,347 (median 1,034, max 16,355) |
| Markets with ≥500 snapshots | 4,541 (~78%) |
| Markets that "look resolved" (terminal price ≥0.99 or ≤0.01) | 5,546 / 5,789 (~96%) |
| Storage (uncompressed chunks) | ~32 GB across 8 large TimescaleDB chunks |
| Compression policy | enabled, kicks in 6h after insert |

Per-snapshot row carries: `timestamp_us`, `market_id`, `outcome ∈ {"Up","Down"}`, 15 levels of bid/ask (`bid_price_0..14`, `ask_price_0..14`, `bid_size_*`, `ask_size_*`).

### Companion datasets (`/opt/storedata/imports/data/`)
- `BTCUSDT/` — Binance OHLCV CSVs at 1m/5m/15m/1h/4h/1d/1w.
- `coinapi/liquidations/{BTC,ETH,SOL}USDT/` — parquet liquidation feeds (price, qty, accumulated qty).
- `coinapi/micro_features/BTCUSDT_15m_micro.parquet` — pre-computed 15m micro features.
- `coinapi/trades/` — tick-level trades.
- `fetch_binance.py`, `process_ohlcv.py` — local importers.

### Other tables in the DB
`binance_klines_v2` (107 chunks, compressed), `liquidations_v2`, `oracle_prices_v2`, `binance_liquidations_v2`, `trades_v2`, plus `engine.hl_trades` (Hyperliquid project — separate concern).

## Backtestable universe for BTC Up/Down

- Slug convention confirmed: `btc-updown-5m-<resolve_unix>` and `btc-updown-15m-<resolve_unix>`.
- Apr 22–23 extract produced **444 resolved BTC markets (333× 5m + 111× 15m)** ≈ **222 markets/day**.
- Pro-rated: **~1,100 BTC up/down markets resolved across the current 5-day window**, with ~96% having clean terminal prices for resolution inference.
- Plus 4,541 markets with ≥500 snapshots → trajectory density is fine for any exit-rule grid (we ran 56 strategies on 444; 1,100 will tighten 95% CIs by ~√(1100/444) ≈ 1.6×).

## ⚠️ One real problem: `markets` metadata table is stale

| Column population | Count |
|---|---|
| Rows in `markets` (Polymarket) | 138 (99× 5m + 39× 15m) |
| Of which have title/slug | 138 (all old, latest sample is **April 9** entries) |
| Of which have `resolve_at`, `resolved_at`, `outcome`, `result` populated | **0** |
| Snapshot market_ids with NO matching `markets` row | **5,782 of 5,789 (99.9%)** |

So the collector is writing orderbook snapshots but **not upserting market metadata**. To run a backtest we have to:

1. Either pull metadata from Polymarket Gamma API (`GET /markets`) keyed by `condition_id` / `market_id` and backfill `markets`, **or**
2. Identify BTC up/down markets *without* the metadata — by joining snapshots to a Gamma-API-fetched slug list, **or**
3. Replay the existing `polymarket_extract_*.sql` extractors after the metadata backfill.

This is the single blocker before we can backtest on the new ~5-day window. The Apr 22–23 extract worked because someone backfilled the `markets` table at that time; nothing has refreshed it since.

## Suggested next steps (in order)

1. **Fix the metadata pipeline.** Write a one-shot script that calls Gamma API `GET /markets?closed=true` (paginated) and upserts into `markets` for any `market_id` present in `orderbook_snapshots_v2`. Schedule it as a sibling systemd timer to the collector.
2. **Re-extract the BTC universe** with the existing `polymarket_extract_markets_v2.sql` + `polymarket_extract_trajectories.sql` over the now-5-day window. Expect ~1,100 markets vs 444.
3. **Re-run Kronos inference** + the `polymarket_backtest_real.py` exit-grid on the bigger sample. The ~2.5× sample-size jump alone may push best strategies (S3 T0.70+S0.35) out of "CI crosses zero" territory if the signal still has *any* edge.
4. **Add the latency-edge probe.** The companion datasets already have Binance 1m + liquidations, so we can compute the 30–90s lag the CYCLOPS doc claims and test trading only on lag-aligned moves.
5. **Let the collector keep running.** Every week buys us another ~1,500 BTC markets; that's the cheapest thing in this whole stack.

## VPS access reference

```
ssh -i "$HOME/.ssh/vps2_ed25519" -6 root@2605:a140:2323:6975::1
# DB env: /etc/storedata/collector.env (root only)
# psql via:  set -a; . /etc/storedata/collector.env; set +a; psql -h 127.0.0.1 -U $PGUSER -d $PGDATABASE
```
