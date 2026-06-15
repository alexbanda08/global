# Chainlink Live Feed — PAID Paths + Direct Application — 2026-06-12

Companion to `CHAINLINK_LIVE_FEED_RESEARCH_2026_06_12.md`. Two distinct cost categories:

- **Category A — Paid RPC** (read Chainlink Data FEEDS, on-chain, at high frequency with an SLA). Cheap, self-serve.
- **Category B — Chainlink Data STREAMS direct** (sub-second signed DON reports = settlement-grade, matches RTDS).
  Sales-gated, no public pricing.

⚠️ Reminder: only **Category B / Data Streams** is the sub-second product that settles Polymarket. Category A RPC
gives you the slower on-chain aggregator value, just with reliability + SLA. We **already hold Data Streams (RTDS)
creds on VPS3** — reuse those before paying again.

---

## CATEGORY A — Paid RPC providers, CHEAPEST → MOST EXPENSIVE

Cost math basis: 3 feeds × 1/sec = **7.78M calls/mo**; × 1/5sec = **1.56M calls/mo**. EVM `latestRoundData()` = 1 `eth_call`.

| # | Provider | Entry tier | $/mo | Quota | WS | SLA | Solana | 1s-poll fit (3 feeds) |
|---|---|---|---|---|---|---|---|---|
| 1 | **Ankr PAYG** | pay-as-you-go | **~$1.56/mo** | $0.10/M credits, no min | Y | none | Y | ✅ ~$1.56/mo EVM |
| 2 | **dRPC PAYG** | pay-as-you-go ($50 min deposit) | **~$3.34/mo** | $6/M req, 120+ chains | Y | none | Y | ✅ ~$3.34/mo |
| 3 | **Alchemy PAYG** | pay-as-you-go | **~$4.75/mo @5s**, ~$91/mo @1s | 30M CU free then $0.45/M; 26 CU/call | Y | none (ent only) | ✗ EVM only | ⚠️ pricey at 1s (202M CU) |
| 4 | **Chainstack Growth** | flat | **~$49/mo** | 20M RU/mo, 250 RPS | Y | 24×5 <24h | Y | ✅ fits (7.78M<20M) — best flat |
| 5 | **GetBlock Starter** | flat | $49/mo | 50M CU/mo | Y | std | Y | ⚠️ 1s may exceed → $199 |
| 6 | **Helius Developer** (Solana) | flat | $49/mo | 10M cr/mo, 50 RPS, WS | Y | chat | Solana only | ✅ Solana 1s fits |
| 7 | **QuickNode Build** | flat | $49/mo | 80M cr (÷20=4M calls) | Y | 24h SLA | Y | ✗ 1s exceeds → Accelerate $249 |
| 8 | **Infura Developer** | flat | $50/mo | 450M cr/mo (÷80=5.6M calls) | Y | tickets | ✗ no Solana | ✗ 1s exceeds → Team $225 |
| 9 | **Moralis Pro** | flat | $199/mo | 100M CU (~5M calls) | Y | none | Y | ⚠️ 5s only |
| 10 | **Chainstack Pro** | flat | $199/mo | 80M RU/mo, 400 RPS | Y | std | Y | ✅ easily |
| 11 | **Infura Team** | flat | $225/mo | 2.25B cr/mo | Y | tickets | ✗ | ✅ |
| 12 | **QuickNode Accelerate** | flat | $249/mo | 450M cr (22.5M calls) | Y | 12h SLA | Y | ✅ |
| 13 | **Triton PAYG** (Solana) | PAYG ($125 min) | ~$77.8/mo @1s | $10/M calls | Y gRPC | senior eng | Solana only | ✅ |
| 14 | **Helius Business** (Solana) | flat | $499/mo | 100M cr, gRPC LaserStream | Y+gRPC | priority | Solana only | ✅ sub-ms streaming |
| 15 | **Blockdaemon Starter** | flat | $600/mo | 15M CU, **99.9% uptime SLA** | Y | 99.9% | Y | institutional-grade |

### Recommendation (Category A)
- **Cheapest that works at 1s, all 3 coins, one venue:** **Ankr PAYG (~$1.56/mo)** or **dRPC PAYG (~$3.34/mo)** — no SLA.
- **Cheapest with real support + flat bill at 1s:** **Chainstack Growth ~$49/mo** (only flat-$49 plan whose quota actually covers 7.78M calls; QuickNode/Infura $49 tiers do NOT).
- **Want a signed uptime SLA:** Blockdaemon ($600) or any provider's Enterprise tier.
- For 5s polling, the math collapses — almost any free or $0–5/mo PAYG tier covers it.

---

## CATEGORY B — Chainlink Data Streams (DIRECT) — settlement-grade, sub-second

### How to apply (100% sales-gated — NO self-serve, NO open testnet)
1. **Form:** https://chain.link/contact ("Talk to an expert"). Asks business email, project website, free-text
   "what to discuss" → explicitly write **"Data Streams API credentials (testnet + mainnet)"**. No Data-Streams-
   specific intake form exists; this generic enterprise form is the only entry.
2. Chainlink BD/platform coordinator provisions: `STREAMS_API_KEY` + `STREAMS_API_SECRET` (HMAC-SHA256 signing);
   sometimes `CHAINLINK_CLIENT_ID/SECRET`. Same route for testnet and mainnet.
3. **Endpoints once credentialed:** REST `https://api.dataengine.chain.link`, WS `wss://ws.dataengine.chain.link`
   (testnet `*.testnet-dataengine.chain.link`).
4. **Turnaround:** not publicly disclosed; anecdotally days–weeks for known DeFi projects, unknown for small/research.

### Pricing — NOT publicly disclosed
- Billing page (`docs.chain.link/data-streams/billing`) states only: subscription model (pay-per-verification
  **deprecated**); **zero tiers/dollar/LINK numbers published anywhere**.
- Each signed report carries a `nativeFee` (gas token) + `linkFee` (LINK) — values Chainlink-set/negotiated.
- **Only real datapoint:** GMX-Solana pays Chainlink **1.2% of total protocol fees** (revenue-share, not flat sub).
  No public $/mo or $/request figure exists.

### Cheaper / faster routes to Data Streams
- **No RPC reseller** offers it (Alchemy/Infura/QuickNode do NOT resell Data Streams as of mid-2026).
- **Chainlink BUILD program** (https://chain.link/build) — for Web3 startups *with a token*; you allocate % of
  native token in exchange for early product access + support. Likely faster/cheaper than cold sales IF you have a token.
- **Chainlink SCALE** = for blockchain ecosystems, not apps — N/A.
- **AWS Marketplace** lists Chainlink *Data Standard* (different product), no Data Streams pricing there.

### Contact channels
- Form: https://chain.link/contact · Docs CTA "Contact us" on data-streams pages
- Discord: https://discord.com/invite/chainlink (#data-streams / #developer-support — questions, not credentials)
- Email: `press@chain.link` (BD-ish, from docs metadata), `security@chain.link` (security only)
- BUILD: https://chain.link/build

### Fastest practical route for a small/research project
Fire all three in parallel: (1) chain.link/contact form mentioning Data Streams + your use case, (2) direct email
to press@chain.link, (3) ask in Discord #data-streams. Set expectations: small non-DeFi applicants may get slow/no
response — which is why **reusing the existing VPS3 RTDS credentials is by far the path of least resistance.**

---

## VERDICT

| You want | Path | Cost |
|---|---|---|
| Cheapest reliable HF read, all 3 coins | **Ankr/dRPC PAYG** (Data Feeds) | **~$1.5–3.5/mo** |
| Flat bill + support at 1s | **Chainstack Growth** | **~$49/mo** |
| Signed uptime SLA | Blockdaemon / Enterprise | **$600+/mo** |
| Sub-second settlement-grade (matches resolution) | **Data Streams direct** — apply via chain.link/contact | **opaque (sales/rev-share); we already hold VPS3 RTDS creds** |

**Practical call:** for live oracle reads, paid Data Feeds RPC (Ankr/dRPC PAYG, or Chainstack Growth for SLA) is
the cheap reliable answer. For resolution-grade sub-second, do NOT pay Chainlink again — reuse VPS3 RTDS.
