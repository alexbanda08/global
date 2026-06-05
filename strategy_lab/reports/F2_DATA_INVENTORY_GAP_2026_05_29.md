# F2 Data Inventory Gap Analysis — 2026-05-29

**Purpose**: Map current canonical dataset (as of 2026-05-29 refresh) against the 4 missing inputs
identified in `F2_FINAL_VERDICT_2026_05_18.md` that block decoding F2's ~4% slug-selector.

**Canonical last refreshed**: 2026-05-29 13:17 UTC (`migration_2026_05_29/`)

---

## (a) Full Data Source Inventory

| Source | File(s) | Resolution | Coverage | Freshness (as of 2026-05-29) |
|--------|---------|-----------|----------|------------------------------|
| **Polymarket trades** (`trades_v2`) | `trades_polymarket/{btc,eth,sol}.parquet` | Per-executed-trade (~14 cols: `timestamp_us, price, size, side, trade_id, slug, outcome, …`) | Apr 26 → May 29 13:17 UTC | Current — 39.7M/10.5M/4.6M rows |
| **Polymarket orderbook L25 snapshots** | `orderbook_l25/{btc,eth,sol}.parquet` | Event-driven; median ~55ms, 61% <100ms — NOT fixed-rate | Apr 22 → May 29 13:13 UTC | Current — 70.7M/13.2M/5.9M rows |
| **Tier-1 L25 books at t+120** | `tier1_entries_at_t120/{btc,eth,sol}.parquet` | One snapshot per (slug, outcome) at ws+120s | Apr 22 → ~May 15 | STALE — not rebuilt since ~May 15 (README gotcha #6) |
| **Chainlink RTDS** (`oracle_prices_v2`) | `chainlink_rtds.parquet` | ~1 Hz (~8.62M rows) | Apr 28 18:40 → May 29 13:17 UTC | Current — rolling 30d |
| **Market resolutions** | `resolutions.parquet` / `resolutions_from_rtds.parquet` | Per-market (one row per settled slug) | ~Apr 28 → May 29 13:10 UTC | Current — 42,494 / 39,304 rows |
| **Binance spot klines — 1MIN/5MIN/15MIN** | `klines_1m.parquet` (source: `binance-spot-ws`) | 1-min bars (OHLCV + taker_buy_base/quote) | Apr 22 → May 29 13:15 UTC | Current — 575,483 rows |
| **Binance spot klines — 1SEC** | `klines_1s.parquet` | 1-second bars | Apr 7 → May 29 13:16 UTC (live ws: May 7+; vision archive: Apr 7–May 6) | Current — 13.38M rows; **sub-minute backtest window effectively May 7–29 only** |
| **Binance vision historical klines** | `binance_vision_klines.parquet` | 1MIN/5MIN/15MIN/1HRS/4HRS/1DAY | Apr 27 2025 → Apr 28 2026 | Static — ~1 year archive, no updates |
| **Coinbase spot klines** | `klines_1m.parquet` (source: `coinbase-spot-ws`) | 1-min bars only | Apr 28 → ~May 16 | STALE — VPS2 dormant since ~May 16 |
| **Kraken spot klines** | `klines_1m.parquet` (source: `kraken-spot-ws`) | 1-min bars only | Apr 28 → ~May 16 | STALE — VPS2 dormant since ~May 16 |
| **OKX spot klines** | `klines_1m.parquet` + `okx_klines.parquet` (source: `okx-ws`) | 1-min bars only | Apr 28 → ~May 16 | STALE — VPS2 dormant since ~May 16 |
| **Hyperliquid perp klines** | `hyperliquid_klines.parquet` | 1MIN/5MIN/15MIN/1HRS/4HRS/1DAY | Jan 30 → May 27 | Refreshed May 27 — ~4 months |
| **Hyperliquid perp trades (30d rolling)** | `hyperliquid_trades_30d.parquet` | Per-trade | ~Apr 16 → May 16 | STALE — last pulled May 16 (~13.6M rows) |
| **Hyperliquid liquidations (full history)** | `hyperliquid_liquidations_full.parquet` | Per-fill liquidation event | May 25 2025 → May 27 2026 | Refreshed May 27 — 5.27M rows |
| **Hyperliquid funding rates** | `hyperliquid_funding.parquet` | 1-hourly per asset | Jan 30 → May 15 | STALE — last pulled May 16 (~2,544 rows/asset) |
| **Hyperliquid perp metrics** | `hyperliquid_metrics.parquet` | ~1-min WS snapshots (OI, mark, oracle price) | Apr 30 → May 16 | STALE — last pulled May 16 |
| **Trading events (live controller)** | `trading_events_30d.parquet` | Per-event (order_filled, position_settled, etc.) | Rolling 30d → May 29 13:18 | Current — 1.13M rows |
| **Crypto market cap dominance** | `cryptocap_dominance.parquet` | Various periods | Apr 1 2014 → ~May 1 2026 | Mildly stale — ~Apr 30 last |
| **Binance perp metrics (OI/LS ratio)** | ~~`binance_metrics.parquet`~~ DELETED | — | Dead since Apr 26 2026 | **DEAD** — VPS3 Ireland geoblocked from Binance futures API |

**No Bybit data of any kind exists in the dataset.**

---

## (b) Per-Item Verdict on the 4 F2 Missing Inputs

### Missing Input 1: Cross-exchange basis at ~100ms resolution (Bybit/OKX/Coinbase TRADE tape)

**Verdict: DONT HAVE**

What we have: 1-min OHLCV bars for Coinbase/Kraken/OKX spot (stale to ~May 16, VPS2 dormant).
No Bybit data at any resolution — no collector, no table, no mention in any script.
No per-trade tick data for any of Bybit/OKX/Coinbase — only kline bars.
No 100ms basis computation exists anywhere in the codebase.

The F2 verdict required: per-trade WS tapes from Bybit perp + OKX perp + Coinbase spot to compute
cross-venue basis at 100ms cadence. We collect only 1-min bars from spot OKX/Coinbase/Kraken.
Gap: **missing Bybit entirely; missing per-trade tick data for all non-Binance venues; missing the
100ms basis computation layer.**

---

### Missing Input 2: Polymarket CLOB WS ORDER-EVENT tape (per-order ADD/REPLACE/CANCEL/MATCH)

**Verdict: DONT HAVE**

What we have:
- `trades_polymarket` = executed **match** events only (14 cols: `timestamp_us, price, size, side,
  trade_id, slug, outcome, market_id, asset_id, …`). This is `trades_v2` from storedata — filled/matched
  trades only.
- `orderbook_l25` = L25 price/size **book snapshots** at event-driven ~55ms cadence. These show the
  state of the book but do NOT record individual order ADD/REPLACE/CANCEL events.

There is no `order_events` table in storedata, no collector subscribing to
`wss://ws-subscriptions-clob.polymarket.com/ws/market` topic `market/{condition_id}/orders`, and no
ADD/CANCEL/REPLACE records anywhere in canonical data. The F2 verdict's hypothesis — "F2 fires within
milliseconds of a specific maker quote appearing" — cannot be tested.

Gap: **complete absence of per-order lifecycle events (ADD/REPLACE/CANCEL/MATCH at order granularity).**

---

### Missing Input 3: Funding-rate spikes; maker-counterparty profiling; mempool

**Verdict: PARTIAL — funding partial, counterparty/mempool absent**

**Funding rates**: We have HL hourly funding (`hyperliquid_funding.parquet`, Jan 30 → May 15, STALE 2
weeks). We do NOT have Binance/Bybit 8-hour funding (binance_metrics dead, no Bybit). HL funding is
~3% of total perp OI; Binance/Bybit funding is the meaningful signal. The FUNDING_OI_2026_05_26
report confirms the HL-only funding-fade hypothesis "essentially failed" standalone.

**Liquidation cascades**: We DO have HL liquidations (full 1-year history, refreshed May 27). This is
the strongest signal found in deriv analysis (+$8–$17/trade on short-squeeze events). BUT HL is ~3%
of total perp OI — Binance/Bybit dominant liq events are not captured.

**Maker-counterparty profiling**: No per-order maker address tracking. `trades_v2` has `trade_id` and
`side` but no maker wallet address per trade. Maker address tracking (`0xeebde7a0`, `0x04b6d7e9`)
identified in F2 verdict is not actionable from current data.

**Mempool (Polygon)**: Not collected. No collector, no table, no code.

Gap: partial on HL funding/liqs (stale + wrong venue); complete absence of Binance/Bybit
funding spikes, maker-address per-trade, and mempool data.

---

### Missing Input 4: Chainlink Data Streams as direct settlement-price signal

**Verdict: HAVE IT (effectively)**

We have `chainlink_rtds.parquet`: `oracle_prices_v2` on VPS3, source label
`polymarket-rtds-chainlink`, symbols `CHAINLINK_{BTC,ETH,SOL}_USD`, cadence ~1Hz,
coverage Apr 28 → May 29 13:17 UTC (rolling 30d, 8.62M rows, freshness current).

This IS the settlement-price feed. The `resolutions_from_rtds.parquet` table re-derives all market
outcomes directly from this feed with zero Binance contamination. Chainlink RTDS is the signal used
by Polymarket's own settlement contract and is confirmed to agree with Ireland VPS resolution
99.64% of the time.

Caveat: rolling 30d only — historical window before Apr 28 requires `resolutions.parquet` (upstream
pull). No "Data Streams" SDK subscription; data arrives via VPS3 storedata's oracle collector, which
is functionally equivalent for backtest purposes.

---

## (c) Single Most Important Missing Piece

**The Polymarket CLOB WS order-event tape (ADD/REPLACE/CANCEL per-order) is the #1 gap.**

Reasoning:
1. It is the only signal that can distinguish "fresh maker quote from a specific address just appeared"
   from the general noisy flow we already have. F2's ~55ms reaction time (inferred from L25 snapshot
   density) suggests they react to a specific book event, not a price level.
2. Cross-exchange basis (#1) is also critical but requires more infrastructure (Bybit collector +
   basis computation). The order-event tape requires only one new WS subscription to a Polymarket
   endpoint that is already publicly documented.
3. Funding/liq (#3) produced real but small standalone signals (+$1–$8/trade) from HL alone — the
   incremental gain from adding Bybit funding is incremental improvement. The order-event tape could
   be the binary unlock that makes the slug-selector decodable.
4. Chainlink RTDS (#4) is already solved.

**To collect**: subscribe `wss://ws-subscriptions-clob.polymarket.com/ws/market` topics
`book/{asset_id}` and `market/{condition_id}/orders`; persist raw ADD/REPLACE/CANCEL/MATCH events
with microsecond receipt timestamps to a new storedata table `order_events_v1`. Estimated ~100 GB/month.
