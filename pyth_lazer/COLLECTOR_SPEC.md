# Pyth Lazer Collector — Simple Spec

Verified working 2026-06-12 with a live key (real_time reachable, ~50ms cadence, 0 stale).
Reference probe: `pyth_lazer/probe_lazer.py`. SETTLEMENT CAVEAT: Pyth ≠ Chainlink — this is a SIGNAL feed;
keep Chainlink RTDS as the resolution truth.

---

## 1. Connection

3 HA WebSocket endpoints — connect to ALL THREE, dedup by `timestampUs` (one drops during deploys):
```
wss://pyth-lazer-0.dourolabs.app/v1/stream
wss://pyth-lazer-1.dourolabs.app/v1/stream
wss://pyth-lazer-2.dourolabs.app/v1/stream
```

## 2. Auth

Server-side = HTTP header on the WS upgrade:
```
Authorization: Bearer <YOUR_KEY>
```
(Browser-only alternative: `?ACCESS_TOKEN=<KEY>` query param. Use the header on a server.)
401 at upgrade = bad token · 403 = no permission.

## 3. Subscribe (send once after connect)

```json
{
  "type": "subscribe",
  "subscriptionId": 1,
  "priceFeedIds": [1, 2, 6],
  "properties": ["price", "bestBidPrice", "bestAskPrice", "exponent", "feedUpdateTimestamp"],
  "formats": [],
  "channel": "real_time",
  "deliveryFormat": "json",
  "parsed": true,
  "ignoreInvalidFeedIds": true
}
```
- Feed IDs (u32, NOT hex): **BTC=1, ETH=2, SOL=6**.
- `channel: "real_time"` = the fastest available (~50ms; bounded 1–50ms). **Do NOT use `fixed_rate@1ms`** — the live
  server rejects it (`"unknown channel"`). Valid channels: `real_time`, `fixed_rate@50ms|200ms|1000ms`.
- `formats: []` = no signed binary blob, just parsed JSON (lightest). Use `["evm"]`/`["solana"]` only if you need
  on-chain-verifiable proofs.

## 4. Incoming message shape

Ignore everything except `type == "streamUpdated"`:
```json
{
  "type": "streamUpdated",
  "subscriptionId": 1,
  "parsed": {
    "timestampUs": "1758690761750000",
    "priceFeeds": [
      { "priceFeedId": 1, "price": "6374136000000",
        "bestBidPrice": "6374120000000", "bestAskPrice": "6374150000000",
        "exponent": -8, "feedUpdateTimestamp": 1758690761750000 }
    ]
  }
}
```
Other `type` values (`subscribed`, errors): a `{"type":"error", ...}` means the subscribe was rejected — log + stop.

## 5. Parse → row

For each `pf` in `parsed.priceFeeds`:
```
real_price = int(pf["price"]) * 10 ** pf["exponent"]        # exponent = -8
bid        = int(pf["bestBidPrice"]) * 10 ** exponent
ask        = int(pf["bestAskPrice"]) * 10 ** exponent
server_us  = int(parsed["timestampUs"])                      # UTC microseconds
fresh      = pf["feedUpdateTimestamp"] >= server_us          # else carried-forward (no new data this tick)
```
Suggested row (match `chainlink_rtds` style — all UTC µs):
```
recv_us, server_us, feed_update_us, symbol(BTC/ETH/SOL), price, bid, ask, exponent, source='pyth_lazer'
```

## 6. Reconnect / liveness

- Reconnect on close with exponential backoff (cap ~10s); re-send the subscribe on every reconnect.
- Respond to WS ping with pong (most libs auto). Treat >2s of silence as dead → drop + reconnect.
- Dedup across the 3 connections on `(symbol, server_us)`.

## 7. Gotchas (found in testing)

- **Cadence is ~50ms, not 1ms.** `real_time` floors at the feed's ~50ms aggregation. 1ms is documented but not
  served. Don't promise sub-50ms.
- **Clock skew:** `recv_us - server_us` looked like ~2.9s but that was the local Windows clock being behind.
  Run `w32tm /resync` (or NTP) on the collector host before trusting absolute latency; inter-arrival deltas are fine.
- **Key is a secret** — env var only (`PYTH_LAZER_TOKEN`), never commit.

## 8. Minimal Python (single endpoint, prove-out)

```python
import asyncio, json, time, os, websockets
URL="wss://pyth-lazer-0.dourolabs.app/v1/stream"; SYM={1:"BTC",2:"ETH",6:"SOL"}
SUB={"type":"subscribe","subscriptionId":1,"priceFeedIds":[1,2,6],
     "properties":["price","bestBidPrice","bestAskPrice","exponent","feedUpdateTimestamp"],
     "formats":[],"channel":"real_time","deliveryFormat":"json","parsed":True,"ignoreInvalidFeedIds":True}
async def run():
    hdr=[("Authorization",f"Bearer {os.environ['PYTH_LAZER_TOKEN']}")]
    async with websockets.connect(URL, additional_headers=hdr) as ws:
        await ws.send(json.dumps(SUB))
        async for raw in ws:
            m=json.loads(raw)
            if m.get("type")!="streamUpdated": continue
            p=m["parsed"]; sus=int(p["timestampUs"])
            for pf in p["priceFeeds"]:
                e=pf["exponent"]; price=int(pf["price"])*10**e
                print(int(time.time()*1e6), sus, SYM[pf["priceFeedId"]], price)
asyncio.run(run())
```
(For production: wrap all 3 URLs, add reconnect+dedup, write parquet instead of print.)
