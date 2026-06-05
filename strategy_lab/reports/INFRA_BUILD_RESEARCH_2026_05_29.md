# Infra Build Research — Oracle-Lag Directional Taker
**Date:** 2026-05-29  
**Author:** Research agent (Claude)  
**Purpose:** Concrete infrastructure upgrade plan for Polymarket BTC/ETH/SOL up-down oracle-lag strategy.

---

## 1. Chainlink Data Streams — The Settlement Signal

### What It Is
Pull-based, off-chain oracle delivering **sub-second price reports** verifiable on-chain. This is the exact price used by Polymarket's RTDS to settle BTC/ETH/SOL up-down markets (see Section 5 of Polymarket RTDS docs — topic `crypto_prices_chainlink` delivers a signed report with `symbol`, `timestamp`, `value`; Polymarket's own RTDS re-streams it publicly).

### Access Model
- **No self-serve sign-up.** You must contact Chainlink to request API credentials (API key + secret).
- Contact: https://chain.link/data-streams → "Get Access" form.
- Pricing is **not publicly listed** — enterprise/negotiated basis. No free tier confirmed for mainnet.
- Testnet access available after contacting Chainlink (same form).

### API Methods
Three interfaces available:
1. **WebSocket** — persistent streaming, sub-second push of new reports. SDKs: Go, Rust, TypeScript. HA mode: 2+ concurrent connections to isolated origins.
2. **REST API** — pull single or multiple reports on demand (HMAC auth required).
3. **SDK integration** — wraps WS or REST.

WebSocket endpoint (from docs, auth required):  
`wss://ws-api.testnet.chain.link/api/v1/ws` (testnet)  
Mainnet endpoint only disclosed after credentials issued.

### Auth
HMAC-signed request headers. Credentials (apiKey + userSecret) issued by Chainlink after registration.

### Available Pairs & Stream IDs
All three needed pairs are confirmed available. Canonical list at https://docs.chain.link/data-streams/crypto-streams

| Pair | Confirmed Feed ID (partial/public) | Market Hours |
|------|-------------------------------------|--------------|
| BTC/USD | `0x00036fe43f87884450b4c7e093cd5ed99cac6640d8c2000e6afc02c8838d0265` | 24/7/365 |
| ETH/USD | `0x000359843a543ee2fe414dc14c7e7920ef10f4372990b79d6361cdc0dd1ba782` | 24/7/365 |
| SOL/USD | Not in public search results — listed at above docs URL | 24/7/365 |

Feed type: **CEX-aggregated mid price + LWBA** (Liquidity-Weighted Bid/Ask). Oracles: Chainlayer, Chainlink Labs, Galaxy, Fiews, DexTrac, and others. Report includes: `observationsTimestamp`, `benchmarkPrice`, `bid`, `ask`.

### Update Cadence
Sub-second, **pull-based**: reports are generated continuously by the Aggregation Network; you receive the latest report the moment you pull/subscribe. No fixed Hz documented publicly; in practice reports arrive on every price movement from the oracle network (effectively heartbeat or deviation-triggered, ~1s or faster).

### Latency vs On-Chain Feed
Standard Chainlink Data Feeds (push, on-chain) update every ~60s or on 0.5% deviation. Data Streams delivers the same report **before on-chain commitment**, eliminating the on-chain lag. This is the exact signal Polymarket's settlement engine consumes.

### KEY FINDING — Polymarket Publicly Re-Streams It
`wss://ws-subscriptions-clob.polymarket.com` (or the Gamma RTDS endpoint) streams `crypto_prices_chainlink` topic with no auth required. This means you can **subscribe to the Polymarket RTDS directly and get the same Chainlink price** that will be used for settlement, without obtaining Data Streams credentials. Format:
```json
{"topic":"crypto_prices_chainlink","type":"update","timestamp":1753314088421,
 "payload":{"symbol":"btc/usd","timestamp":1753314088395,"value":67234.50}}
```
However, this is Polymarket's **re-broadcast** — there may be an additional relay delay vs subscribing directly to Chainlink. Magnitude unknown. If the relay adds even 100–200ms of lag vs direct, that's strategically significant.

### Sources
- https://docs.chain.link/data-streams
- https://docs.chain.link/data-streams/reference/data-streams-api/interface-ws
- https://docs.chain.link/data-streams/crypto-streams
- https://data.chain.link/streams/btc-usd-cexprice-streams
- https://docs.polymarket.com/market-data/websocket/rtds

---

## 2. Polymarket CLOB WebSocket — What It Exposes

### Endpoint
```
wss://ws-subscriptions-clob.polymarket.com/ws/market   (public market data)
wss://ws-subscriptions-clob.polymarket.com/ws/user     (private order/trade events, auth required)
```

### Channels & Event Types

#### Market Channel (no auth)
Subscribe by sending `assets_ids` (token IDs, not condition IDs).

| Event Type | Description |
|------------|-------------|
| `book` | Full L2 orderbook snapshot (bids/asks arrays) |
| `price_change` | Price-level delta: `{price, side, size}` where size = total resting at that level |
| `last_trade_price` | Most recent trade: `{side, size, price}` |
| `tick_size_change` | Tick size changed (fires at price >0.96 or <0.04) |
| `best_bid_ask` | Top-of-book L1 update (requires `custom_feature_enabled: true`) |
| `market_resolved` | Market settled (requires `custom_feature_enabled: true`) |

#### User Channel (auth required)
Subscribe by sending `markets` (condition IDs) + `auth` block.

| Event Type | Sub-type | Description |
|------------|----------|-------------|
| `order` | `PLACEMENT` | New order placed |
| `order` | `UPDATE` | Partial fill |
| `order` | `CANCELLATION` | Order cancelled |
| `trade` | `TRADE` | Match executed |

### CRITICAL — No Per-Order L3 Feed
`price_change` events are **aggregated price-level** (L2), not per-order ADD/REPLACE/CANCEL. There is NO FIX-style individual order event stream (L3). You cannot reconstruct who placed or cancelled a specific order. This means:
- You CAN maintain a local L2 depth-of-book (snapshot + deltas).
- You CANNOT detect individual large orders being pulled or placed in real time (only the net size change at each level).
- For the oracle-lag strategy, this is sufficient — you only need to walk the book to find entry price.
- For decoding competitor triggers (e.g., F2 slug-selector), L3 data is NOT available via CLOB WS. Would require Polygon on-chain event indexing or a custom Polymarket insider feed.

### Auth Requirements
- Market channel: **no auth** for subscriptions.
- User channel: **L2 API key + HMAC-SHA256** signature required. Keys obtained by EIP-712-signing an L1 credentials request with your wallet private key.

### Rate Limits
WebSocket connections do NOT count against REST rate limits. No documented per-connection message rate limit found for WS specifically; the connection closes if PONG not sent within 10s of server PING.

### Heartbeat
Server PINGs every 5s. Client must PONG within 10s. Client should send "PING" every 10s. Optional: heartbeat mode (if connection drops, all open orders cancelled).

### Sources
- https://docs.polymarket.com/developers/CLOB/websocket/wss-overview
- https://docs.polymarket.com/developers/CLOB/websocket/market-channel
- https://docs.polymarket.com/developers/CLOB/websocket/user-channel
- https://docs.polymarket.com/developers/CLOB/websocket/market-channel-migration-guide

---

## 3. Order Placement Latency & AWS Co-location

### Infrastructure Confirmation
Polymarket CLOB is definitively hosted on **AWS eu-west-2 (London)**. Confirmed by multiple independent sources (newyorkcityservers.com, quantvps.com). Order matching is off-chain (fast), settlement on Polygon (async, not on the critical path for PnL).

### Measured Latency Figures (from public sources)
| Location | Round-Trip to CLOB |
|----------|--------------------|
| US East Coast | ~130ms |
| Dublin/Ireland VPS | <5ms |
| Amsterdam | ~10ms |
| AWS eu-west-2 (same-region) | Sub-1ms (intra-region) |

Ireland VPS already achieves <5ms, which is competitive. Moving INTO AWS eu-west-2 would reduce this to **sub-millisecond** (same-region, inter-AZ latency measured at 0.25–2.4ms across AWS regions globally). For a strategy where the edge window is ~55s, sub-5ms is likely already fine. Co-location in eu-west-2 would matter if competing with bots running IN London.

### EIP-712 Signing Overhead
Every order requires:
1. L2 auth headers (HMAC-SHA256 on request params — CPU-trivial, <0.1ms).
2. EIP-712 structured signing of the order payload with your EOA private key. This is a secp256k1 ECDSA signature — typically **<1ms** with hardware/software wallet in local process; NOT an on-chain transaction.
3. Timestamp drift >60s causes rejection — requires NTP sync.

Signing adds negligible latency if done in-process with a local private key (no hardware wallet round-trip).

### Order Types
- **GTC** (Good Till Cancel) — standard resting limit order.
- **FOK** (Fill or Kill) — documented in the order schema (`order_type` field values include `GTC`, `FOK`). FOK behaves as marketable: fills fully at or better than limit price, or rejects entirely. This is the relevant type for aggressive oracle-lag entry.
- No confirmed IOC (Immediate-or-Cancel) documented; FOK is the closest aggressive type.

### Rate Limits (REST)
| Endpoint | Burst Limit | Sustained |
|----------|-------------|-----------|
| `POST /order` | 3,500/10s | 36,000/10min (~60/s avg) |
| `DELETE /order` | 3,000/10s | 30,000/10min |
| `POST /orders` (batch, up to 15) | 1,000/10s | 15,000/10min |
| CLOB general | 9,000/10s | — |

Throttling via Cloudflare: requests queue before 429 is returned.

### Should You Move to AWS eu-west-2?
- Current Ireland VPS: **<5ms** to CLOB. Already well within the 55s edge window.
- AWS eu-west-2 same-region: **<1ms**. Improvement ~4ms.
- This matters ONLY if other bots are co-located in London and race you by 3–4ms per fire.
- Given that the Chainlink oracle lag is ~55s, a 4ms improvement is likely **not the binding constraint**. The binding constraint is how fast you detect the oracle move (see Section 1).
- **Conclusion**: moving to eu-west-2 is a minor optimization, not urgent. Ireland is adequate unless you observe systematic losses to faster competitors within the first few seconds post-oracle-move.

### Sources
- https://newyorkcityservers.com/blog/polymarket-server-location-latency-guide
- https://www.quantvps.com/blog/polymarket-servers-location
- https://docs.polymarket.com/developers/CLOB/introduction
- https://agentbets.ai/guides/polymarket-rate-limits-guide/
- https://www.bitsand.cloud/posts/cross-az-latencies

---

## 4. Cross-Exchange Trade Tapes — Sub-Second Basis Computation

All four major exchanges provide **free, public, no-auth WebSocket trade streams** for BTC/ETH/SOL.

### Endpoints

| Exchange | WS Base URL | Trade Topic/Channel | Auth? |
|----------|-------------|---------------------|-------|
| Binance | `wss://stream.binance.com:9443` | `btcusdt@trade`, `ethusdt@trade`, `solusdt@trade` | No |
| Bybit | `wss://stream.bybit.com/v5/public/linear` | `publicTrade.BTCUSDT`, `publicTrade.ETHUSDT`, `publicTrade.SOLUSDT` | No |
| OKX | `wss://ws.okx.com:8443/ws/v5/public` | `{"channel":"trades","instId":"BTC-USDT"}` | No |
| Coinbase Adv. | `wss://ws-feed.exchange.coinbase.com` | `matches` channel, products: `BTC-USD`, `ETH-USD`, `SOL-USD` | No |

### Message Rate / Volume Estimates
- BTC/USDT on Binance: ~5–50 trades/sec during active markets. Each message ~200–400 bytes JSON.
- For 4 exchanges × 3 assets × ~20 msg/sec average: ~240 msg/sec, ~50–100 KB/sec (~4–9 GB/day uncompressed). Gzip/DEFLATE reduces to ~1–2 GB/day.
- Binance WS limit: 1,024 streams per connection, 5 messages/sec INCOMING (subscription commands), 300 connections per IP per 5 min. No limit on received push messages.
- Bybit: WS requests not counted against REST rate limits.

### Library Support
- `cryptofeed` (Python): normalizes Binance, Bybit, Coinbase, OKX + 40 others. Single callback interface for trades, book updates.
- `ccxt` (JS/Python/Go/etc.): 100+ exchanges, WS support.

### Use for Oracle-Lag Strategy
Cross-exchange trade tapes enable:
1. Sub-second cross-venue basis: detect if BTC moves on Binance first, then Bybit/Coinbase confirm → stronger signal before oracle update.
2. F2 wallet decoder: F2 fires contrarian to 5s flow imbalance; replicating requires per-trade tape, not klines.
3. Flash crash / spoofing detection (optional).

### Sources
- https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams
- https://bybit-exchange.github.io/docs/v5/websocket/public/trade
- https://www.okx.com/docs-v5/en/
- https://pypi.org/project/cryptofeed/

---

## 5. Upgrade Ranking — Value / Effort

### #1 — Chainlink Data Streams Direct Subscription
**Key fact:** Polymarket ALREADY re-streams Chainlink prices on `wss://ws-subscriptions-clob.polymarket.com` at topic `crypto_prices_chainlink` — **no credentials needed**. This is your fast-path. Subscribe to this topic immediately; it gives you the exact settlement price with no auth overhead.

Direct Chainlink subscription (bypassing Polymarket's relay) requires contacting Chainlink, negotiated pricing, enterprise onboarding. Potential benefit: remove Polymarket's relay latency (unknown but possibly 50–200ms). **INVESTIGATE** this delta by comparing timestamp offsets in RTDS feed vs Chainlink directly.

**Recommendation:** BUILD (free path via Polymarket RTDS now); INVESTIGATE direct Chainlink subscription after measuring relay lag.

### #2 — Cross-Exchange Trade Tapes (Binance + 1–2 others)
**Key fact:** All endpoints free, public, no-auth. 4 exchanges × 3 assets = ~240 msg/sec, manageable. Enables sub-second multi-venue confirmation of oracle move direction.

**Recommendation:** BUILD (low effort, high signal value for earlier oracle-move detection).

### #3 — Polymarket CLOB WS Full Depth (already partially built)
**Key fact:** L2 book events (`price_change`, `book` snapshot) via no-auth WS. No per-order (L3) events exist — cannot detect individual order placement/cancellation. For oracle-lag entry, L2 is sufficient to walk the book and price the fill.

**Recommendation:** BUILD (likely already running given your production WS mirror; ensure `best_bid_ask` with `custom_feature_enabled:true` for top-of-book speed).

### #4 — AWS eu-west-2 Co-location
**Key fact:** Ireland VPS already achieves <5ms to CLOB. Moving in-region gives <1ms. Delta: ~4ms. This is irrelevant against a 55s edge window unless you're racing bots in the first 100ms post-oracle-move.

**Recommendation:** SKIP for now. Revisit if live data shows consistent losses in the <10s post-oracle window against faster competitors.

### #5 — Direct Chainlink Data Streams (full enterprise subscription)
**Key fact:** No self-serve, no public pricing, must contact Chainlink. Even if cost is $0 (e.g., they offer free API tier for non-protocol use), onboarding lag is weeks. The Polymarket RTDS relay may be functionally equivalent latency for this strategy.

**Recommendation:** INVESTIGATE relay lag vs direct first. If delta is >100ms, pursue enterprise access. Otherwise, skip.

---

## YES/NO Answers

**Q: Does Chainlink Data Streams offer a low-latency streaming feed we can subscribe to from Ireland?**  
**YES** — WebSocket API exists, sub-second delivery, SDKs in Go/Rust/TypeScript. BUT requires contacting Chainlink for credentials; no self-serve. More importantly: Polymarket RTDS already re-broadcasts this feed publicly (`crypto_prices_chainlink` topic) — use that immediately while evaluating direct subscription.

**Q: Is moving the VPS into AWS eu-west-2 London worth it?**  
**NO** — Ireland VPS is already <5ms to the CLOB. The oracle-lag edge window is ~55s. A 4ms improvement is not the binding constraint. The binding constraint is how quickly you detect the Chainlink price move, not the order submission RTT. Spend the effort on the oracle feed before the compute location.
