# Chainlink Live Feed Research — BTC / ETH / SOL — 2026-06-12

**Goal:** find a reliable, preferably free, live Chainlink oracle feed for BTC/USD, ETH/USD, SOL/USD.
**Method:** 3 parallel sonnet web-research agents (EVM Data Feeds, Solana native, hosted/3rd-party APIs).

---

## ⚠️ Critical framing (project-specific)

Production resolution truth = **Chainlink Data Streams (RTDS)** — sub-second, signed DON reports
(`chainlink_rtds.parquet`, already collected on VPS3 with credentials). The **free** paths below deliver
**Chainlink Data FEEDS** (on-chain aggregators, push-on-heartbeat/deviation) which are a **DIFFERENT, SLOWER,
LOWER-PRECISION product** — NOT byte-identical to the RTDS values that settle Polymarket up/down markets.

- **Free + reliable = Data Feeds** (on-chain `latestRoundData()` via public RPC). Latency = block time + heartbeat;
  major-crypto heartbeats are SLOW (BTC ETH mainnet 1–24h, only deviation-triggered between).
- **Sub-second, production-matching = Data Streams** — NO free self-serve tier; requires application to Chainlink
  (we already have RTDS creds on VPS3). For a *new* live feed that must match settlement, reuse VPS3 RTDS, do not
  substitute Data Feeds.

**Bottom line:** if you want a *free* live read → Data Feeds on a cheap L2 via public RPC. If you want *settlement-
grade* sub-second → it's the Data Streams creds we already hold, not a free API.

---

## OPTION 1 — Chainlink Data Feeds via free public RPC (FREE, no key) ✅ recommended free path

Read `latestRoundData()` (selector `0xfeaf968c`) on the proxy aggregator. Answer ÷ 1e8 (8 decimals).

### Contract addresses

**Ethereum mainnet (chainId 1)** — heartbeats are slow:
| Feed | Proxy | Heartbeat | Deviation |
|---|---|---|---|
| BTC/USD | `0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c` | 86400s (24h) | 0.5% |
| ETH/USD | `0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419` | 3600s (1h) | 0.5% |
| SOL/USD | `0x4ffC43a60e009B551865A93d232E33Fce9f01507` | verify | 0.5% |

**Arbitrum One (chainId 42161)** — tighter deviation, ~250ms blocks → BEST free L2:
| Feed | Proxy | Deviation |
|---|---|---|
| BTC/USD | `0x6ce185026b56E6C96cca62b2C48BbF4E86bdDb2D` | 0.05% |
| ETH/USD | `0x639Fe6ab55C921f74e7fac1ee960C0B6293ba612` | 0.05% |
| SOL/USD | `0x24ceA4b8ce57cdA33F7de89F898A89B8b3C0e7b2` | 0.1% |

> ⚠️ Always re-verify at https://docs.chain.link/data-feeds/price-feeds/addresses (JS-rendered; addresses can change).
> On L2s also read the **Sequencer Uptime Feed** to detect stale-during-downtime.

### Free public RPCs (no API key)
| Provider | Ethereum | Arbitrum |
|---|---|---|
| LlamaRPC | `https://eth.llamarpc.com` | `https://arbitrum.llamarpc.com` |
| dRPC | `https://eth.drpc.org` | `https://arbitrum.drpc.org` |
| Ankr | `https://rpc.ankr.com/eth` | `https://rpc.ankr.com/arbitrum` |
| PublicNode | `https://ethereum-rpc.publicnode.com` | `https://arbitrum-one-rpc.publicnode.com` |
| Cloudflare | `https://cloudflare-eth.com` | — |

Rate limits IP-based/undisclosed; fine for polling every 1–30s; use 2+ as fallbacks. For streaming, `eth_subscribe("newHeads")` (WS on Alchemy free / Ankr) + poll on each block gets you the value within one block of any update.

```python
import requests
FEEDS = {  # Ethereum mainnet
  "BTC/USD":"0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c",
  "ETH/USD":"0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419",
  "SOL/USD":"0x4ffC43a60e009B551865A93d232E33Fce9f01507"}
def price(addr, rpc="https://rpc.ankr.com/eth"):
    h = requests.post(rpc, json={"jsonrpc":"2.0","method":"eth_call",
        "params":[{"to":addr,"data":"0xfeaf968c"},"latest"],"id":1}, timeout=5).json()["result"][2:]
    return int(h[64:128],16)/1e8   # word[1] = answer; also word[3]=updatedAt for staleness
for n,a in FEEDS.items(): print(n, price(a))
```
**Staleness guard:** decode `updatedAt` (word[3]); alert if `now - updatedAt > heartbeat + grace`.

---

## OPTION 2 — Chainlink NATIVE on Solana (FREE, no key) ✅ for BTC & SOL only

Read the OCR2-v2 feed account directly via `getAccountInfo` (no SDK needed). Verified live 2026-06-12.

| Feed | Mainnet-beta pubkey | Status |
|---|---|---|
| BTC/USD | `Cv4T27XbjVoKUYwP72NQQanvZeA7W4YF9L4EnYT9kx5o` | ✓ live ($63,349) |
| SOL/USD | `CH31Xns5z3M1cTAbKW34jcxPPciazARpijcHj9rxtemt` | ✓ live ($66.90) |
| **ETH/USD** | **NOT AVAILABLE on Solana mainnet** | ✗ use EVM (Opt 1) or Pyth |

OCR2-v2 program: `HEvSKofvBgfaexv23kMabbYqxasxU3mQ4ibBMEmJWHny`. granularity=1 (1s ringbuffer); updates ~every few seconds in active trading. ETH/USD has NO native Solana Chainlink feed — must source ETH from EVM (Option 1) or Pyth.

```python
import requests, struct, base64
RPC="https://api.mainnet-beta.solana.com"   # getAccountInfo allowed on public; getProgramAccounts is NOT
def read_feed(pk):
    d = base64.b64decode(requests.post(RPC, json={"jsonrpc":"2.0","id":1,
        "method":"getAccountInfo","params":[pk,{"encoding":"base64"}]}).json()["result"]["value"]["data"][0])
    dec=d[138]; ln=struct.unpack_from("<I",d,148)[0]; cur=struct.unpack_from("<I",d,152)[0]
    off=200+((cur-1+ln)%ln)*48
    return struct.unpack_from("<q",d,off+16)[0]/10**dec
print("BTC", read_feed("Cv4T27XbjVoKUYwP72NQQanvZeA7W4YF9L4EnYT9kx5o"))
print("SOL", read_feed("CH31Xns5z3M1cTAbKW34jcxPPciazARpijcHj9rxtemt"))
```

**Live push (sub-second on change):** WS `accountSubscribe` to the feed pubkey → fires on every OCR round.
Free Solana RPC/WS: Helius (10 RPS, 1M cr/mo, WS), PublicNode (`wss://solana-mainnet.publicnode.com`), Alchemy.
Public `api.mainnet-beta.solana.com` **blocks getProgramAccounts** (use Helius/Alchemy for feed discovery).

---

## OPTION 3 — Chainlink Data Streams (sub-second, settlement-grade) — NOT free self-serve

REST `https://api.dataengine.chain.link` + WS `wss://ws.dataengine.chain.link`. HMAC-SHA256 auth
(UUID key + secret). **No free tier — apply at https://chain.link/contact?ref_id=datastreams.** This is the
product behind our existing `chainlink_rtds` collector. benchmarkPrice = 18 decimals. For a settlement-matching
live feed, **reuse the VPS3 RTDS creds** rather than re-applying.

---

## Hosted / 3rd-party — mostly NOT true Chainlink
- **Etherscan API** `module=proxy&action=eth_call` — free 5 req/s, 100k/day w/ key; TRUE Chainlink; REST only.
- **Alchemy free** — 30M CU/mo (~1.15M eth_calls), WS included; best free *production* RPC; TRUE Chainlink.
- **DeFiLlama `coins.llama.fi`** — keyless but **CoinGecko-sourced, NOT Chainlink** (can differ 0.5–2%). Reject.
- **data.chain.link** dashboard — no stable public JSON API behind it. Do not rely on.

---

## RECOMMENDATION

| Need | Use | Cost |
|---|---|---|
| Free live read, all 3 coins, one venue | **Option 1, Arbitrum** via `arbitrum.llamarpc.com` (BTC+ETH+SOL all present, 0.05–0.1% dev) | $0 |
| Free, Solana-native, push streaming | **Option 2** (BTC+SOL only; ETH from Opt 1/Pyth) + WS accountSubscribe | $0 |
| Settlement-grade sub-second (matches Polymarket resolution) | **Data Streams** = existing VPS3 RTDS creds, NOT a free API | (already held) |

**Pick:** Arbitrum Data Feeds (Option 1) is the single cleanest FREE source covering all three coins. But it is
NOT the RTDS value that settles markets — for anything resolution-critical, stay on the VPS3 Data Streams collector.

Full agent reports retained in session context. Verify all addresses at docs.chain.link before wiring.
