# CHAINLINK FEED RESEARCH — LIVE BTC/ETH/SOL PRICE FEEDS
**Date:** 2026-06-12  
**Purpose:** Evaluate all viable live Chainlink oracle price feeds for BTC/USD, ETH/USD, SOL/USD. Context: Polymarket crypto up/down markets resolve on Chainlink Data Streams; lowest latency vs the actual settlement value wins.

---

## COMPARISON TABLE

| Option | Latency vs Settlement | Update Cadence | Cost | Auth/KYC | Reliability | Integration Effort |
|--------|----------------------|----------------|------|----------|-------------|--------------------|
| **A. Data Streams WS (mainnet)** | ~0ms (IS the settlement source) | Sub-second (~1/s per stream) | Subscription (contact sales) | API key + HMAC; no public self-signup | High (active-active multi-site HA) | Medium (WS + HMAC auth) |
| **B. Data Streams REST latest (mainnet)** | ~0ms (same source) | Poll-on-demand | Same subscription as WS | Same | High | Low (HTTP GET) |
| **C. Data Streams Candlestick streaming (mainnet)** | ~1s (derived from DS reports) | Every second | Same subscription as WS | Same | High | Low (SSE stream, JWT auth) |
| **D. Data Streams testnet WS** | ~0ms (likely real prices — UNVERIFIED) | Sub-second | Free (testnet credentials via contact form) | API key + HMAC; testnet access via contact | Medium | Medium |
| **E. On-chain push feeds (Ethereum mainnet)** | 20–60+ seconds behind settlement | Heartbeat: ~3600s (1h) / 0.5% deviation | Free (public RPC) | None | Medium (chain + RPC latency) | Low (eth_call) |
| **F. On-chain push feeds (Arbitrum)** | 20–60+ seconds behind settlement | Heartbeat: ~3600s / 0.5% deviation | Free (public RPC) | None | Medium | Low (eth_call) |
| **G. data.chain.link website** | Unknown; website scraping | Website-driven, not an API | Free (scraping) | None | Low (ToS risk; JS-rendered) | High (brittle) |
| **H. Pyth Network** | <1s (independent oracle, NOT Chainlink) | Sub-second | Free tier available | API key for some endpoints | High | Medium |

---

## OPTION DETAILS

### A. Chainlink Data Streams — WebSocket (Mainnet)  
**This is the actual settlement source.** Polymarket resolves via `https://data.chain.link/streams/btc-usd` which uses the Data Streams Aggregation Network (the same infrastructure).

- **Latency:** Effectively 0 delta vs settlement — you receive the SAME signed report the resolution uses.
- **Update cadence:** Sub-second (DON produces and signs reports continuously; WS pushes each report as produced).
- **Endpoints:**
  - WS mainnet: `wss://ws.dataengine.chain.link`
  - REST mainnet: `https://api.dataengine.chain.link`
  - Candlestick mainnet: `https://priceapi.dataengine.chain.link`
- **Stream IDs (mainnet, verified from SDK examples):**
  - ETH/USD: `0x000359843a543ee2fe414dc14c7e7920ef10f4372990b79d6361cdc0dd1ba782`
  - BTC/USD: `0x00037da06d56d083fe599397a4769a042d63aa73dc4ef57709d31e9971a5b439`
  - SOL/USD: NOT confirmed in public docs — requires credentials to list available feeds. UNVERIFIED.
- **Cost:** Subscription model (pay-per-verification deprecated). Pricing opaque — must contact Chainlink via https://chain.link/contact?ref_id=datastreams. No public free tier for mainnet.
- **Auth:** API key (UUID) + API secret. HMAC-SHA256 per-request signature. Headers: `Authorization`, `X-Authorization-Timestamp`, `X-Authorization-Signature-SHA256`. Credentials obtained by contacting Chainlink — no self-serve signup documented.
- **HA mode:** Available on mainnet (not testnet). Maintains 2+ simultaneous WS connections with deduplication and auto-failover.
- **Note:** We already run a Chainlink RTDS collector on VPS3 — this IS this feed. If the existing collector is the official Data Streams WS, no change needed. If it's polling on-chain, there is a meaningful lag.

---

### B. Data Streams — REST `/api/v1/reports/latest`  
Same source as A, pull-on-demand. Suitable for polling at ~1–5s intervals as a fallback to WS.

- **Endpoint:** `GET https://api.dataengine.chain.link/api/v1/reports/latest?feedID=<id>`
- **Bulk endpoint:** `GET /api/v1/reports/bulk?feedIDs=<id1>,<id2>&timestamp=<ts>` — fetch BTC+ETH+SOL in one call.
- **Latency:** Adds REST round-trip overhead (~10–50ms typical) vs WS push. Still the exact settlement data.
- **Same credentials as A.**

---

### C. Data Streams — Candlestick Streaming API  
A separate API endpoint that wraps Data Streams reports into a streaming price feed. Simpler auth (JWT), SSE-style.

- **Endpoint:** `https://priceapi.dataengine.chain.link/api/v1/streaming?symbol=BTCUSD,ETHUSD`
- **Auth:** POST `/api/v1/authorize` with `login={userID}&password={apiKey}` → JWT token; pass as Bearer.
- **Update cadence:** Every second per symbol (derived from underlying DS reports).
- **Response format:**
  ```json
  {"f": "t", "i": "BTCUSD", "fid": "[FEED_ID]", "p": 2.68e21, "t": 1748525526, "s": 1}
  ```
- **Heartbeat:** Every 5 seconds: `{"heartbeat": 1748525528}`
- **Latency:** ~1s behind WS (candlestick is a 1s aggregation of raw reports).
- **Same credentials/subscription as A.** Requires same mainnet access.
- **Best for:** Simple integration if you want a human-readable price stream without decoding binary reports. One second lag vs WS is acceptable for most signal purposes.

---

### D. Data Streams Testnet  
- **Endpoints:**
  - WS testnet: `wss://ws.testnet-dataengine.chain.link`
  - REST testnet: `https://api.testnet-dataengine.chain.link`
  - Candlestick testnet: `https://priceapi.testnet-dataengine.chain.link`
- **Access:** Contact Chainlink via https://chain.link/contact?ref_id=datastreams requesting testnet access. Likely free or low-friction.
- **Testnet stream IDs (confirmed from SDK docs):**
  - ETH/USD: `0x000359843a543ee2fe414dc14c7e7920ef10f4372990b79d6361cdc0dd1ba782`
  - BTC/USD: `0x00037da06d56d083fe599397a4769a042d63aa73dc4ef57709d31e9971a5b439`
- **Real prices?** UNVERIFIED. Chainlink docs do not explicitly state whether testnet streams use real market data or synthetic/simulated prices. Given that Data Streams is a pull-based off-chain system, testnet likely mirrors real DON consensus prices (as testnet RTDS feeds do), but this is NOT confirmed. Must test empirically after obtaining testnet credentials.
- **HA mode:** NOT available on testnet (mainnet only per docs).
- **Lag vs settlement:** If testnet is real prices, lag is 0 vs the DON consensus. If synthetic, useless for trading.

---

### E & F. On-Chain Push Feeds (Ethereum / Arbitrum)  
Classic AggregatorV3Interface push-based feeds. These are a DIFFERENT product from Data Streams — they are the legacy push oracles, NOT the settlement source for Polymarket resolution.

- **BTC/USD (Ethereum mainnet proxy):** `0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c`
- **ETH/USD (Ethereum mainnet proxy):** `0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419`
- **SOL/USD (Ethereum mainnet proxy):** `0x4ffC43a60e009B551865A93d232E33Fce9f01507`
- **Update parameters (typical for major crypto pairs):**
  - Heartbeat: ~3600 seconds (1 hour max without update)
  - Deviation threshold: 0.5% (triggers update when price moves >0.5%)
  - Actual realized update frequency during active markets: typically every 20–120 seconds when price is moving
- **Latency vs Data Streams settlement:**
  - Push feeds update ON-CHAIN via a transaction (block finality required). On Ethereum: 12-15s finality minimum. On Arbitrum: ~0.25–1s per block but same aggregator lag.
  - The push feed DON reaches consensus, then submits an on-chain transaction. The Data Streams DON reaches consensus and makes the report available instantly off-chain. **Estimated lag: 30–120 seconds behind Data Streams in normal conditions; can be hours during low volatility (heartbeat governs).**
  - **Critical:** Polymarket resolves using Data Streams reports, NOT on-chain push feeds. The resolution price is the Data Streams price at the settlement moment, which will differ from the push feed's last on-chain update.
- **Cost:** Free. Any public RPC endpoint works (Infura, Alchemy, Ankr, public nodes).
- **Integration:**
  ```python
  from web3 import Web3
  w3 = Web3(Web3.HTTPProvider("https://eth-mainnet.g.alchemy.com/v2/YOUR_KEY"))
  ABI = [{"inputs":[],"name":"latestRoundData","outputs":[{"name":"roundId","type":"uint80"},{"name":"answer","type":"int256"},{"name":"startedAt","type":"uint256"},{"name":"updatedAt","type":"uint256"},{"name":"answeredInRound","type":"uint80"}],"stateMutability":"view","type":"function"}]
  feed = w3.eth.contract(address="0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c", abi=ABI)
  roundId, answer, startedAt, updatedAt, answeredInRound = feed.functions.latestRoundData().call()
  btc_usd = answer / 1e8  # BTC/USD uses 8 decimals
  # ALWAYS check: if (block.timestamp - updatedAt) > 3700: STALE
  ```
- **Verdict:** 30–120s lag vs settlement in normal conditions, potentially hours in low-vol. Useful only as a coarse sanity check or fallback. NOT viable for trading signal.

---

### G. data.chain.link Website  
The data.chain.link website displays push feed data (NOT Data Streams) and is JavaScript-rendered. There is no documented public API backing it. Any "scraping" approach would be fragile, ToS-risky, and deliver push-feed data with additional scraping latency. **Discard.**

---

### H. Pyth Network  
Pyth is a competing oracle network with sub-second latency. It is NOT Chainlink and does NOT produce the values Polymarket uses for resolution. However, it aggregates from similar CEX sources and could serve as a low-latency proxy to approximate what Data Streams will produce.

- **Latency:** <400ms (publishes every ~400ms on Pythnet; Hermes API pushes in real-time).
- **Update cadence:** ~2.5 updates/second.
- **Price IDs:**
  - BTC/USD: `0xe62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43`
  - ETH/USD: `0xff61491a931112ddf1bd8147cd1b641375f79f5825126d665480874634fd0ace`
  - SOL/USD: `0xef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d`
- **Hermes API (free):** `https://hermes.pyth.network/v2/updates/price/latest?ids[]=<price_id>`
- **WS stream (free):** `wss://hermes.pyth.network/ws` — subscribe to streaming price updates.
- **Cost:** Free for reading prices. No auth required for Hermes REST/WS.
- **Correlation with Chainlink Data Streams:** Both aggregate from major CEX venues. Pyth typically leads on-chain push feeds but may diverge from RTDS by 0–5 ticks depending on DON composition and aggregation methodology.
- **Verdict:** Useful as a FREE, zero-auth, sub-second proxy price signal. NOT the settlement source. Good for checking if a resolution is about to move before Data Streams confirms.

---

### I. Community/GitHub Projects  
- **smartcontractkit/data-streams-sdk** (Go, Rust, TypeScript): Official SDKs; still require credentials. No open free endpoint.
- **Public node providers (Alchemy, Infura, dRPC):** Offer enhanced APIs for on-chain push feeds (eth_call to AggregatorV3) but not Data Streams. Push feeds only — same 30–120s lag.
- **No confirmed community project** exposes Data Streams data for free as of research date. The protocol requires credentials from Chainlink.

---

## LATENCY QUANTIFICATION: DATA STREAMS vs ON-CHAIN PUSH FEEDS

```
Data Streams settlement moment (t=0):
  → DON reaches consensus off-chain
  → Signed report immediately available in Aggregation Network
  → WS subscribers receive report: t + ~0ms (push)
  → REST poll: t + 10–50ms (round-trip)

On-chain push feed update (same consensus event):
  → DON submits on-chain transaction
  → Ethereum block: t + 12–15s (block time)
  → RPC sees finalized: t + 15–30s
  → During low-vol (heartbeat governs): up to t + 3600s (1 HOUR)

Verdict: Data Streams = 0–50ms lag. Push feeds = 15–3600s lag.
The gap is orders of magnitude. Push feeds are UNSUITABLE for
Polymarket resolution prediction.
```

---

## RECOMMENDATIONS

### #1 RECOMMENDATION: Chainlink Data Streams WebSocket (Mainnet)  
**Already what we should be running.** Verify that the existing VPS3 RTDS collector uses `wss://ws.dataengine.chain.link` (mainnet WS), not a polling or on-chain approach.

- If the existing collector is a proper Data Streams WS subscriber: **nothing to change**.
- If it's polling the REST API: switch to WS for push delivery (eliminates poll interval lag).
- To add BTC/SOL streams alongside ETH: add their feedIDs to the WS subscription.

**Action to get credentials if not already held:** Contact Chainlink at https://chain.link/contact?ref_id=datastreams. State you are building a prediction market settlement monitoring system. Subscription pricing is undisclosed publicly.

### #2 FALLBACK: Pyth Network Hermes API (Free, Zero-Auth)  
If Data Streams access is lost, Pyth gives sub-second BTC/ETH/SOL prices for free with no credentials:

```python
import requests, time

PYTH_IDS = {
    "BTC": "0xe62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43",
    "ETH": "0xff61491a931112ddf1bd8147cd1b641375f79f5825126d665480874634fd0ace",
    "SOL": "0xef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d",
}

def get_pyth_prices():
    ids = "&".join(f"ids[]={v}" for v in PYTH_IDS.values())
    r = requests.get(f"https://hermes.pyth.network/v2/updates/price/latest?{ids}", timeout=5)
    parsed = r.json()["parsed"]
    return {p["id"][:8]: int(p["price"]["price"]) * 10**int(p["price"]["expo"]) for p in parsed}
```

Or WS stream:
```python
import websocket, json

def on_message(ws, msg):
    data = json.loads(msg)
    # data["parsed"][0]["price"]["price"] → raw price
    # data["parsed"][0]["price"]["expo"]  → exponent

ws = websocket.WebSocketApp("wss://hermes.pyth.network/ws")
ws.on_message = on_message
# Subscribe after connect:
# ws.send(json.dumps({"type": "subscribe", "ids": list(PYTH_IDS.values())}))
```

**Expected Pyth-vs-RTDS divergence:** Typically 0–$20 for BTC, 0–$2 for ETH under normal conditions. Will diverge more during fast moves. Track empirically by comparing Pyth price to RTDS resolution outcome over 2–4 weeks.

---

## TESTNET STRATEGY (Recommended for Backup Credential)

1. Submit testnet request at https://chainlinkcommunity.typeform.com/datastreams
2. On receipt of testnet API key + secret, connect to `wss://ws.testnet-dataengine.chain.link/api/v1/ws?feedIDs=0x00037da06d56d083fe599397a4769a042d63aa73dc4ef57709d31e9971a5b439`
3. Cross-check reported prices against Pyth/Binance prices at same timestamp
4. If |testnet_price - binance_spot| < 0.5%: testnet IS real prices → viable free redundant feed
5. If testnet prices are clearly synthetic: testnet is useless for trading signal

Testnet cannot be used for HA mode (mainnet-only limitation). Treat as credential-free experiment only.

---

## INTEGRATION SKETCH: DATA STREAMS WS PYTHON

```python
import asyncio, hashlib, hmac, time, uuid, websockets, json, os

API_KEY    = os.environ["STREAMS_API_KEY"]    # UUID format
API_SECRET = os.environ["STREAMS_API_SECRET"]

FEED_IDS = {
    "BTC": "0x00037da06d56d083fe599397a4769a042d63aa73dc4ef57709d31e9971a5b439",
    "ETH": "0x000359843a543ee2fe414dc14c7e7920ef10f4372990b79d6361cdc0dd1ba782",
    # SOL: obtain ID from /api/v1/feeds after connecting
}

WS_HOST = "ws.dataengine.chain.link"  # mainnet
PATH = "/api/v1/ws"

def make_auth_headers(method: str, path: str, body: str = "") -> dict:
    ts = str(int(time.time() * 1000))
    msg = "\n".join([method.upper(), path, body, API_KEY, ts])
    sig = hmac.new(API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return {
        "Authorization": API_KEY,
        "X-Authorization-Timestamp": ts,
        "X-Authorization-Signature-SHA256": sig,
    }

async def stream():
    feed_param = ",".join(FEED_IDS.values())
    full_path = f"{PATH}?feedIDs={feed_param}"
    headers = make_auth_headers("GET", full_path)
    uri = f"wss://{WS_HOST}{full_path}"
    
    async with websockets.connect(uri, additional_headers=headers) as ws:
        async for msg in ws:
            report = json.loads(msg)["report"]
            feed_id = report["feedID"]
            # Decode fullReport bytes → ReportV3 struct for price
            # Fields: feedId, observationsTimestamp, price (int192, 18 decimals for crypto)
            print(f"feedID={feed_id[:10]}… ts={report.get('observationsTimestamp')}")

asyncio.run(stream())
```

Note: The `fullReport` blob must be decoded. Use the Go/Rust/TypeScript official SDKs which handle decoding automatically. The `price` field in the decoded ReportV3 is int192 with 18 decimal places.

---

## KNOWN UNKNOWNS (UNVERIFIED)

- **SOL/USD mainnet stream ID:** Not found in public docs. Must query `/api/v1/feeds` after obtaining credentials.
- **Testnet prices = real?** Assumed yes based on DON architecture but not explicitly stated in docs.
- **Mainnet subscription cost:** Chainlink does not publish pricing. Likely enterprise-tier ($hundreds–thousands/month depending on call volume). UNVERIFIED.
- **RTDS vs Data Streams equivalence:** `data.chain.link/streams/btc-usd` — the "streams" URL implies the Polymarket resolution IS the new Data Streams product, not the legacy RTDS (Real-Time Data Streams, the older off-chain signed data product). The existing VPS3 "RTDS collector" may be the right product under a different name — confirm by checking if its credential type is API-key+HMAC (Data Streams) or a different auth scheme.
- **data.chain.link website API:** JS-rendered, no documented public API found. Network call inspection would be required (UNVERIFIED). Even if found, would likely be rate-limited and not intended for programmatic use.

---

# MEASURED BENCHMARK 2026-06-12 (12-min live shoot-out, Windows desktop)

_Runner: `strategy_lab/directional/_feed_latency_bench.py`. Baseline = Polymarket RTDS
(`wss://ws-live-data.polymarket.com`, topic `crypto_prices_chainlink` — the SETTLEMENT feed itself,
1Hz, all 7 coins, free, no auth). Compared: Pyth Hermes SSE stream (free) + Chainlink Arbitrum
AggregatorProxy `latestRoundData()` polled 250ms via 4 working free RPCs (arb1.arbitrum.io/rpc,
publicnode, 1rpc.io/arb, drpc; llamarpc dead / ankr now key-walled / meowrpc walled). Feed
addresses verified on-chain via `description()`: BTC 0x6ce18586…, ETH 0x639Fe6ab…, SOL 0x24ceA4b8…
all "X / USD". All feeds timestamped on the same local clock → relative lags valid (absolute
transport numbers carry local clock skew ~3-4s, ignore them)._

| Feed | Updates (12 min, per coin) | Price lead/lag vs RTDS | Verdict |
|---|---|---|---|
| **Polymarket RTDS** | 708-710 (1Hz) | baseline (= settlement value) | **KEEP — already optimal among free options** |
| Pyth Hermes (free) | 1,522 (~2.1Hz) | **LAGS RTDS by ~3.0-3.2s** (best-shift alignment, err 0.7-1.1bp); move-events first-detected +2.6..+6.8s AFTER rtds (small n) | redundancy/failover only, NOT a leading signal |
| Arbitrum on-chain feeds | **5-8 rounds total** (deviation-gated ~0.05%) | n/a — too sparse to align | **DISQUALIFIED** for 1s-resolution use |

## Conclusions
1. **No free provider beats the RTDS we already consume.** RTDS IS the resolution feed — by
   definition nothing mirroring Chainlink can lead it; the only upstream is Chainlink Data Streams
   direct (paid) which serves the same numbers marginally earlier.
2. **The only thing that LEADS the settlement value is the raw exchange tape (Binance)** — which is
   exactly the lag edge our deployed scalp already trades. Mirror-feeds can at best tie.
3. Pyth tracks the Chainlink number within ~1bp but delivered ~3s late via public Hermes from our
   location → fine as a watchdog/failover for RTDS outages, useless for signal.
4. Arbitrum push feeds: 0.05% deviation gating → ~7 updates/12min in calm tape. Not usable.
5. Caveats: 12-min calm-market sample (move-event n=1-10); measured from desktop, not Ireland/VPS3
   (EU colo would shave transport but not the ~3s Pyth structural lag); Solana-native feeds
   (BTC+SOL only, no ETH) not tested — needs OCR2 account-layout parse, only worth it if someone
   demonstrates it leads RTDS.
Artifact: `_results/feed_bench_1781278131.parquet` (6,713 rows).

---

# BENCHMARK ROUND 2 — PYTH LAZER (2026-06-12, 15-min head-to-head, free key)

_Lazer real_time channel via `wss://pyth-lazer-0.dourolabs.app/v1/stream` (Bearer token, free key
WORKS on real_time despite docs implying paid tier). 50ms cadence, ~18k updates/coin/15min vs
RTDS 1Hz. Probe: `pyth_lazer/probe_lazer.py` ✓. Same-clock comparison, runner `_feed_latency_bench.py`._

| Feed | Cadence | Price alignment vs RTDS | Move-event (≥5bp) first-detection |
|---|---|---|---|
| **Pyth Lazer (free)** | **50ms** | **LEADS RTDS +2.6..+2.8s** (err 0.4-1.0bp, all 3 coins) | **sees moves 1.4-1.8s BEFORE RTDS** (median; n=1/8/12 btc/eth/sol) |
| Pyth Hermes | ~500ms | ~sync/lags −0.2s | mixed +1.4s |
| Arbitrum on-chain | 13-19 rounds/15min | n/a | disqualified |

## Reading
1. **Lazer is the first FREE feed that LEADS the settlement feed** — consistent across BTC/ETH/SOL,
   tight tracking (≤1bp alignment error). The ~1.5-1.8s event lead is the tradable number (the
   +2.6s shift includes RTDS's 1Hz staircase quantization).
2. Mechanism: Lazer is a multi-exchange aggregate published at 50ms; Chainlink Data Streams
   aggregates similar sources but Polymarket's RTDS republishes at 1Hz — Lazer ≈ a fast preview of
   what RTDS will print. NOT the settlement value itself (Pyth ≠ Chainlink) — use as SIGNAL, never
   as truth.
3. Use cases for us: (a) sharper δ (delta-vs-strike) estimate near window events for the scalp
   sleeves; (b) potentially cleaner than single-venue Binance for the lag signal (multi-exchange);
   (c) RTDS watchdog. Next: benchmark Lazer vs our BINANCE WS signal (does it add anything beyond
   Binance, which also leads RTDS?).
4. Caveats: 15-min calm sample (few ≥5bp events); free-key rate/tier stability unverified for 24/7
   collection; desktop measurement (Ireland/VPS3 colo would only improve it).
ACTION: port `pyth_lazer/probe_lazer.py` connect/subscribe/parse into the storedata collector
(per the probe's header) + side-by-side log Lazer vs Binance WS vs RTDS for a full day before
wiring into any sleeve.
Artifact: `_results/feed_bench_1781279584.parquet` (62,022 rows).

---

# BENCHMARK ROUND 3 — LAZER vs BINANCE WS vs RTDS (20 min, 106,063 rows, 2026-06-12)

_Added Binance spot bookTicker mid (our production signal venue) to the same-clock shoot-out.
Artifact: `_results/feed_bench_1781281434.parquet`. (Binance "transport delay ~1ms" cell is an
artifact — bookTicker has no event timestamp, stamped locally; ignore it.)_

| Metric | Binance WS | Pyth Lazer | RTDS |
|---|---|---|---|
| Move first-detection vs RTDS (median) | **BTC −7.5s · ETH −2.9s · SOL −1.1s** | BTC −1.3s · ETH −1.6s · **SOL −1.8s** | baseline |
| Settlement-value tracking error | **5.6–6.3bp** (venue basis) | **0.4–1.3bp** | 0 (is the value) |
| Cadence | ~event-driven (throttled 100ms here) | 50ms | 1Hz |

## Verdict — they are COMPLEMENTARY, not substitutes
- **Binance stays the EARLIEST direction signal** (sees moves first, esp. BTC) — the deployed scalp's
  edge is intact and unbeaten.
- **Lazer is the best free SETTLEMENT-VALUE PREVIEW**: ≤1.3bp from the Chainlink number, ~1.3–1.8s
  before RTDS prints it. Binance can't do this (5–6bp venue basis vs the oracle).
- Concrete use: sharper δ (delta-vs-strike) measurement ~1.5s earlier than RTDS — strike-cross
  calls near window open/close, and a higher-precision scalp entry gate. Also RTDS watchdog.
- Pipeline: collector spec written (`pyth_lazer/COLLECTOR_SPEC.md`) — hand to storedata agent;
  after ≥1 day of side-by-side logs, consider an A/B scalp sleeve with Lazer-δ vs RTDS-δ.
- Caveats: 20-min calm sample (n=4–13 move events/coin), desktop clock, free-key 24/7 stability
  unverified.
