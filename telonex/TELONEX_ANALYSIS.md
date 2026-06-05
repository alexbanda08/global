# Telonex API — analysis (2026-06-04)

Historical prediction-market data (Polymarket + Binance) as **daily Parquet** via REST.
API key tested + working: `tlx_14ecdbcbfd155a0defaf857fa0950e45`.

## Endpoint shape

```
GET https://api.telonex.io/v1/downloads/{exchange}/{channel}/{YYYY-MM-DD}?slug={slug}&outcome={Yes|No}
Authorization: Bearer <key>
```
- `exchange` ∈ `polymarket` | `binance`
- Selector: `slug`+`outcome`, OR `market_id`+`outcome`, OR `asset_id` (one required)
- 200 → **302 redirect to a presigned S3 URL** → Parquet (`PAR1`). Filename `{asset_id}_{date}_{channel}.parquet`.
- **Auth gotcha:** the S3 leg must NOT carry the `Authorization: Bearer` header (S3 rejects dual-auth → 400). `curl -L` and browser `fetch` strip it automatically; `urllib`/`requests` do not — must drop it manually on redirect. See `client.py`.

## Channels (Polymarket) — schemas verified

| Channel | Schema (key cols) | Sample/day | vs our canonical |
|---|---|---|---|
| `quotes` | `timestamp_us, bid_price, bid_size, ask_price, ask_size` (top-of-book) | 8.2k rows | top-of-book only |
| `trades` | `timestamp_us, price, size, side, trade_id, origin_asset_id` | 259 rows | ≈ our `trades_polymarket` **+ side + trade_id** |
| `book_snapshot_5` | L5 depth (`bid/ask_price_0..4`) | — | subset of our L25 |
| `book_snapshot_25` | **`bid_price_0..24, bid_size_0..24, ask_price_0..24, ask_size_0..24`** | 60k rows | **EXACT match to our `orderbook_l25` schema** |
| `book_snapshot_full` | nested `bids[], asks[]` arrays (full depth) | 65k rows | **deeper than our L25** |
| `onchain_fills` | on-chain settlement fills (per-wallet) | — | **NEW — we don't collect this** |
| `crypto_prices` | underlying crypto px ref, keyed by slug+outcome | — | ≈ chainlink ref per market |

All timestamps are `timestamp_us` (UTC microseconds) — **same convention as our canonical**. Prices/sizes are strings (object dtype) — cast on load.

## Discovery — the markets catalog

```
GET /v1/datasets/polymarket/markets   (also .../tags)
```
→ **1,544,179 markets, 801 MB Parquet** (all Polymarket markets ever). Columns include per-market, per-channel **date-coverage ranges**:
`trades_from/to, quotes_from/to, book_snapshot_{5,25,full}_from/to, onchain_fills_from/to`,
plus `slug, event_slug, question, category, outcome_0/1, asset_id_0/1, status, start_date_us, end_date_us, settled_at_us, tags, resolution_source`.

⚠️ The catalog file is large + the S3 transfer is **SSL-flaky from this environment** (took 6 retries). Saved locally at `telonex/samples/markets_catalog.parquet`.

## Coverage for OUR use case (BTC/ETH/SOL up-or-down)

- **52,062 up-or-down markets** total. Crypto subset **32,440** (bitcoin 9,410 / ethereum 9,069 / solana 8,868 / xrp 8,675 / bnb 2,212 + epoch-style btc 2,547 / eth 2,544).
- Slug formats: human `bitcoin-up-or-down-may-26-2026-6pm-et` AND **epoch `btc-up-or-down-15m-1759273200`** (≈ our `btc-updown-15m-<epoch>`, just hyphenation differs).
- **`-up-or-down-15m-<epoch>`: 5,091 markets.  `-5m-<epoch>`: 0** (Telonex doesn't carry our 5m epoch slugs by that pattern — 5m may be human-named hourly or absent; needs deeper check before relying on it).

### Per-channel date coverage (crypto up/down)

| Channel | Markets w/ data | Date range |
|---|---:|---|
| book_snapshot_25 / full / quotes | 17,768 | **2025-10-11 → 2026-06-04** |
| trades | 17,337 | 2025-10-11 → 2026-06-04 |
| **onchain_fills** | **31,980** | **2025-03-12 → 2026-06-01** |

**14,264 crypto up/down markets have data BEFORE 2026-04-22** (our canonical start).

## Why this matters for us

1. **L25 backfill ~6 months.** `book_snapshot_25` = our exact `orderbook_l25` schema, back to **2025-10-11** (vs our Apr 22). Drop-in extend of history.
2. **`onchain_fills` = the missing wallet tape.** On-chain settlement fills back to **2025-03-12** (a full year). This is plausibly the per-wallet attribution data the F2/wallet-decode work flagged as a gap (CLAUDE.md F2 verdict: "requires Polymarket CLOB WS event tape"). Worth a focused eval.
3. **`book_snapshot_full`** gives full depth beyond our 25 levels.
4. **trades + side + trade_id** richer than our `trades_polymarket`.

## Caveats / open questions

- **Slug mapping required.** Ours `btc-updown-{5m,15m}-<epoch>` vs theirs `*-up-or-down-15m-<epoch>` / human. Need a join table (epoch + asset → Telonex slug) before backfilling.
- **5m coverage unconfirmed** — epoch `-5m-` = 0 in catalog. Our core 5m sleeves may not be backfillable here; 15m looks covered.
- **Per-market-per-day-per-channel granularity** = 1 HTTP request each. Backfilling 14k markets × N days × channels = many requests; **rate-limit/quota on the key is unknown** (no `/account` or `/usage` endpoint found — all returned 404).
- **Prices are strings** — cast to float on ingest.
- Large-file S3 transfers SSL-flaky from this box (retry loop needed).

## Files

- `telonex/client.py` — reusable downloader (auth + S3-redirect strip + retry).
- `telonex/samples/*.parquet` — one sample per channel (quotes, trades, book_snapshot_25, book_snapshot_full) + `markets_catalog.parquet`.
- `telonex/analyze_catalog.py` — catalog coverage analysis (reproduces the tables above).
