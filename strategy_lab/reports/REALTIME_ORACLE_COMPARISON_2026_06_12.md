# Real-Time Oracle Comparison — Pyth Lazer vs RedStone vs Chainlink Data Streams — 2026-06-12

**Goal:** most reliable, no-lag, real-time BTC/ETH/SOL feed. User referenced "200ms vs 50ms, prefer 50ms."
**Resolved:** that framing = **Pyth Lazer / Pyth Pro** channel names (`fixed_rate@50ms` vs `fixed_rate@200ms`).
Chainlink has NO public 50/200ms tiers. RedStone's fast product is on-chain-only, not a 50ms WS tier.

Companion to `CHAINLINK_LIVE_FEED_RESEARCH_2026_06_12.md` + `CHAINLINK_PAID_PATHS_2026_06_12.md`.

---

## ⚠️ SETTLEMENT vs SIGNAL — read before choosing

Polymarket up/down markets **settle on Chainlink** (our `chainlink_rtds` = Chainlink Data Streams). Pyth and
RedStone are DIFFERENT oracles with DIFFERENT values. So:

- Want a **faster SIGNAL** to drive entries/exits → **Pyth Lazer 50ms is the best answer** (self-serve, free trial,
  literally a 50ms channel). It will NOT equal the Chainlink settlement value, but for *timing a trade* that's fine.
- Want to **predict/replicate settlement** → you MUST use **Chainlink Data Streams** (the RTDS creds we already
  hold on VPS3). A 50ms Pyth feed that disagrees with Chainlink at the settlement instant would mis-call outcomes.

**The 50ms feed you want = Pyth Lazer, as a SIGNAL source. Keep Chainlink RTDS as the settlement truth.**

---

## THE 50ms / 200ms PRODUCT = PYTH LAZER (Pyth Pro) ✅

Official channels (docs.pyth.network/price-feeds/pro/payload-reference):
| Channel | Cadence |
|---|---|
| `real_time` | pushed on each new price, bounded **1ms–50ms** |
| `fixed_rate@1ms` | every 1 ms |
| **`fixed_rate@50ms`** | **every 50 ms** ← the one you want |
| `fixed_rate@200ms` | every 200 ms |
| `fixed_rate@1000ms` | every 1 s |

BTC/ETH/SOL all have `min_channel: real_time` → 50ms is available for all three.

**Access (self-serve, FREE trial):**
1. Sign up at **https://pythdata.app** (Pyth Terminal) → instant free API key, no sales call.
2. Free tier = slower crypto channels (≥200ms). Faster channels (`real_time`/`1ms`/`50ms`) = paid service agreement.
3. Key = Bearer token, permissioned per asset-class + min-channel.

**Pricing (NOT official; community/Messari datapoints):** Free trial via Terminal · Crypto+ ~$5k/mo · Pro ~$10k/mo ·
Enterprise negotiated. No hard rate limits — connections/feeds/channels set by agreement. Treat $ as approximate.

**Feed IDs (Lazer u32, NOT hex):** BTC=`1`, ETH=`2`, SOL=`6`. Price = mantissa × 10^-8.

**Endpoints (connect to ALL 3 for HA):**
`wss://pyth-lazer-0.dourolabs.app/v1/stream` · `-1` · `-2`

```js
import { PythLazerClient } from "@pythnetwork/pyth-lazer-sdk";
const client = await PythLazerClient.create({ urls:[
  "wss://pyth-lazer-0.dourolabs.app/v1/stream",
  "wss://pyth-lazer-1.dourolabs.app/v1/stream",
  "wss://pyth-lazer-2.dourolabs.app/v1/stream"], token: process.env.ACCESS_TOKEN });
client.subscribe({ type:"subscribe", subscriptionId:1, priceFeedIds:[1,2,6],
  properties:["price","bestBidPrice","bestAskPrice","feedUpdateTimestamp"],
  formats:["leUnsigned"], channel:"fixed_rate@50ms", deliveryFormat:"json" });
client.addMessageListener(m => console.log(m));
```
Off-chain only? Yes — `leUnsigned` format, parse JSON, no chain needed. `bestBid/Ask` + EMA included.
HA: publishers→relayers→MQ→routers; connect all 3 WS, one drops during deploys. min_publishers=3.

**Pyth Lazer (Pro, push) vs Pyth Hermes (Core, pull):** Hermes = FREE, permissionless, pull, ~400ms, hex IDs.
Lazer = paid, push WS, 1ms–1s configurable, u32 IDs, bid/ask. For 50ms real-time you need Lazer, not Hermes.

---

## RedStone — fast product is on-chain only, NOT a 50ms WS tier ⚠️

- **RedStone Bolt** = "fastest oracle", **2.4ms** updates / 400+/s — BUT it's an **on-chain push to MegaETH testnet
  only**, NOT a consumer WebSocket you can subscribe to off-chain. No 50/200ms tiers. Not usable as a BTC/ETH/SOL
  data feed for us today.
- **RedStone Live Feeds** = the actual off-chain WS push product. "Low-latency" but **no documented ms number**.
  API-key gated (`x-api-key`, max 30 conns, 8h forced reconnect), WS URL not public → contact sales.
  feedIds: `"BTC"`/`"ETH"`/`"SOL"`, dataServiceId `redstone-primary-prod`. `passthrough` channel = lowest latency
  (per-signer payloads, you aggregate). Free public REST exists (`api.redstone.finance/prices`) but polling-only.
- Pricing: contact sales (no public $). Reliability: 15+ nodes, claims 0 downtime / $4.9B TVS.
- **Verdict:** not the 50ms product. Skip unless you specifically want RedStone's value or MegaETH.

---

## Chainlink Data Streams — settlement-grade, but NO public 50/200ms tier ⚠️

- Official cadence = **"sub-second" / ≥1/sec**; third-party measured **~300ms**. All BTC/ETH/SOL = single
  **`DS-Premium`** tier. No named 50/200ms tiers (the "200ms" in docs = an SDK reconnect backoff, unrelated).
  Sub-ms exists only via a one-off MegaETH precompile, not buyable.
- **This is the ONLY oracle that matches Polymarket settlement** (it IS the RTDS we collect).
- Access: sales-gated (chain.link/contact), HMAC creds, opaque pricing (GMX pays 1.2% of fees). We already hold
  creds on VPS3 — reuse, don't re-apply.
- Mainnet stream IDs: ETH `0x000359843a543ee2fe414dc14c7e7920ef10f4372990b79d6361cdc0dd1ba782`,
  BTC `0x00037da06d56d083fe599397a4769a042d63aa73dc4ef57709d31e9971a5b439`, SOL `0x0003...c24f` (full ID via browser).

---

## HEAD-TO-HEAD

| | **Pyth Lazer (Pro)** | RedStone Live | Chainlink Data Streams |
|---|---|---|---|
| 50ms tier? | ✅ `fixed_rate@50ms` (+1ms, real_time) | ❌ "low-latency", unspecified | ❌ sub-second/~300ms only |
| Self-serve free trial? | ✅ pythdata.app instant key | ❌ contact sales | ❌ sales-gated |
| Real-time WS push? | ✅ 3-endpoint HA | ✅ (URL gated) | ✅ (HA active-active) |
| Pricing | free trial; ~$5–10k/mo paid (unofficial) | contact sales | opaque (rev-share) |
| Matches Polymarket settlement? | ❌ (Pyth value) | ❌ (RedStone value) | ✅ THE settlement truth |
| BTC/ETH/SOL all available? | ✅ (1,2,6) | ✅ | ✅ |
| Bid/ask + EMA | ✅ | ✅ (passthrough) | ✅ (LWBA) |

---

## RECOMMENDATION

1. **For the fastest real-time SIGNAL (the 50ms you asked for): Pyth Lazer `fixed_rate@50ms`.** Self-serve free
   key today at pythdata.app; flip to a paid agreement for the 50ms channel. Connect all 3 WS endpoints. Feed IDs 1/2/6.
2. **Keep Chainlink RTDS (VPS3) as the settlement truth** — never substitute Pyth for outcome resolution.
3. **Skip RedStone** for now (fast product is on-chain MegaETH-only; Live Feeds has no stated ms + is sales-gated).

**Next decision:** is the 50ms feed a trade-timing signal (→ Pyth Lazer, proceed) or must it equal settlement
(→ stay Chainlink, 50ms not available publicly)? If signal: I can stand up a Pyth Lazer collector module next.
