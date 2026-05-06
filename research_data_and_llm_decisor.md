# Research: Free Crypto Data + LLM-as-Event-Decisor

Scope: Polymarket UP/DOWN bot, BTC/ETH/SOL/HYPE/XRP/DOGE on 5m/1h/daily.
Date: 2026-04-29.

---

## TOPIC 1 — Free Crypto Data Sources

| # | Source | What | Free Limits | Auth | HYPE/XRP/DOGE |
|---|---|---|---|---|---|
| 1 | **Binance Futures Funding** `/fapi/v1/fundingRate` | Funding rate history all USDT-perps | 500 req / 5min / IP, shared with fundingInfo | None for public | XRP/DOGE yes; HYPE no |
| 2 | **Bybit Funding** `/v5/market/funding/history` | Funding history per symbol | 600 req / 5s / IP global | None | XRP/DOGE yes; HYPE listed as ETHPERP-style |
| 3 | **OKX Public** `/api/v5/public/funding-rate(-history)` | Funding + OI | ~20 req/2s/IP per endpoint, WS preferred | None | XRP/DOGE yes; HYPE no |
| 4 | **Hyperliquid Info API** `api.hyperliquid.xyz/info` | Funding history, OI, L2 book, liquidations on-chain | No documented hard cap, free | None | HYPE native + all majors as perps |
| 5 | **CoinGlass Free API** | Aggregated OI, liquidations, long/short, funding heatmap | 10k calls/month, daily granularity (1m needs Standard $299), 2019+ history daily | API key (free signup) | XRP/DOGE yes; HYPE yes |
| 6 | **Binance liquidation WS** `!forceOrder@arr` | Real-time forced liquidations all symbols | WS, no daily cap | None | XRP/DOGE yes; HYPE no |
| 7 | **Whale Alert API** | Large transfers across BTC/ETH/SOL/DOGE/XRP/TRX | 10 req/min free, BTC+USDT only on free dashboard | API key | DOGE/XRP yes; HYPE no |
| 8 | **Glassnode Studio Free** | Tier-1 metrics, daily resolution, web only | No API on free; API requires Pro + add-on | n/a free | Treasury metrics for HYPE/DOGE/XRP added 2025 (paid) |
| 9 | **Alternative.me Fear&Greed** `api.alternative.me/fng` | Daily 0–100 index, 2018+ history | Unlimited, no key | None | Aggregate (BTC-weighted) |
| 10 | **LunarCrush v4** | Galaxy Score, social vol, sentiment per coin | Individual tier 10 req/min; full API needs Builder paid | Bearer key | All 6 covered |
| 11 | **Santiment SanAPI** | 500+ on-chain/social/dev metrics, GraphQL | 14-day trial; free tier has 30-day lag on restricted metrics | Key | HYPE limited; XRP/DOGE yes |
| 12 | **CryptoPanic API** | Aggregated news + votes (bullish/bearish flags) | Free dev plan ~hundreds calls/day, 1 req/sec typical | Key | All 6 |
| 13 | **CoinDesk Data API** (developers.coindesk.com) | News + price; RSS coindesk.com/arc/outboundfeeds/rss/ | Free tier with key, RSS unlimited | Key (RSS none) | All 6 in news |
| 14 | **NewsAPI.org** | Generic news search | 100 req/day, 24h delay, dev only | Key | All by keyword |
| 15 | **Reddit API** (OAuth) | r/CryptoCurrency, r/Bitcoin, r/HypeUnit etc | 100 QPM per OAuth client, 10-min rolling | OAuth required | All 6 by sub |
| 16 | **Deribit Public** `public/get_book_summary_by_currency` | Options chain w/ mark/bid/ask IV, Greeks, DVOL | Stricter than auth but ample for polling | None | BTC/ETH/SOL only — no HYPE/XRP/DOGE options |
| 17 | **DeFiLlama Open API** `api.llama.fi` | TVL, fees, stablecoins, prices | No key, ~10–30 req/min unofficial throttle | None | HYPE chain TVL covered, others irrelevant |
| 18 | **Electric Capital Open Dev Data** (github.com/electric-capital/crypto-ecosystems) | Repo taxonomy + monthly MAD counts | Public repo + dashboard, no rate limit | None | All 6 ecosystems |

Notable gaps: HYPE has no Deribit options, no Whale Alert, no Binance/OKX perp (Bybit only via HYPEPERP). Hyperliquid native API fills HYPE perp + on-chain.

---

## TOPIC 2 — LLM as Event Decisor

### Latency + Pricing (single short prompt, 5m bar requires <3s end-to-end)

| Model | Input $/1M | Output $/1M | TTFT | Output speed | Notes |
|---|---|---|---|---|---|
| **Claude Haiku 4.5** | $1.00 | $5.00 | sub-second w/ caching | very fast (Anthropic claims 4–5x Sonnet 4.5) | Cache hit $0.10/1M, 200k ctx |
| **Kimi K2 0905 (Exacto)** Moonshot direct | $0.40 | $2.00 | Fireworks 0.57s TTFT | up to 397 t/s | 262k ctx, 75% cache discount → $0.15/1M |
| **Kimi K2.5 reasoning** | $0.60 | $2.50 | Fireworks 8s on reasoning trace | 397 t/s peak | Reasoning mode adds latency — avoid for 5m |
| **Kimi K2.6** | $0.55 / $2.65 (Moonshot) | — | Fireworks 0.70s TTFT | 70 t/s Fireworks, 163 Clarifai | 256k ctx |
| **GLM-4.6** Z.AI | ~$0.60 | ~$2.20 | China DC adds 100–300ms vs US | n/a published | 128k ctx; Flash variant free |
| **GLM-4.7** OpenRouter | $0.60 | $2.20 | route-dependent | route-dependent | 128k+ |

Latency takeaway: Kimi K2 0905 / K2.6 on **Fireworks** route ≈ 0.6–0.7s TTFT + ~100 output tokens at 70–397 t/s = **~0.9–1.5s end-to-end**, fits the <3s 5m bar. GLM via Z.AI direct adds geographic latency (Asia DC) — risky for North-America-hosted bots; route via Fireworks/Novita instead. K2.5 reasoning mode breaches budget at 8s TTFT; use non-reasoning K2 0905 for 5m and reserve reasoning for 1h/daily.

### Practical Work (2024–2026)

1. **TradeTrap** (arXiv 2512.02261, Dec 2025) — Adversarial data poisoning on price/news retrieval tools causes "epistemic hallucination": agent believes it holds positions it liquidated. Strongest empirical case for an action-selector pattern in trading agents. https://arxiv.org/html/2512.02261v1
2. **FS-ReasoningAgent** (arXiv 2410.12464 v3, Mar 2025) — Splitting news into factual vs subjective streams improves profit by **+7% BTC, +2% ETH, +10% SOL** vs single-stream prompt. Direct template for our event decisor. https://arxiv.org/html/2410.12464v3
3. **Multi-agent zero-shot BTC** (Sci. ScienceDirect 2025, S0306457325004078) — Reddit sentiment +23.30% total return; **news sentiment degrades performance** vs LSTM/PatchTST baselines. Implication: weight Reddit/Twitter higher than headline RSS in our prompt context.
4. **LLMs for Crypto Nowcasting** (MDPI Sept 2025) — Bench of 5 frontier models across 12 assets; Gemini-2.5-Pro most consistent for short-horizon directional. Off-the-shelf LLMs do capture short-term direction with proper prompting. https://www.mdpi.com/2674-1032/4/4/53
5. **Adaptive Multi-Agent BTC** (arXiv 2510.08068, Oct 2025) — Verbal-feedback Reflect agent injects daily/weekly natural-language critiques into next prompt → adapts without finetuning. Useful pattern for our event decisor's persistent memory.
6. **CryptoTrade** (EMNLP 2024) — On + off-chain combined prompt, reflective mechanism. Beats time-series baselines but **loses to traditional TA signals**. Don't replace TA — augment it. https://aclanthology.org/2024.emnlp-main.63/
7. **TauricResearch/TradingAgents** + **auronsun/TradingAgents-crypto** — Open-source LangGraph multi-agent frame; supports OpenAI/Anthropic/GLM/DeepSeek/Qwen. Crypto fork is closest to our need. https://github.com/auronsun/TradingAgents-crypto
8. **OWASP LLM01:2025** — Prompt injection ranks #1 in 73% of audited GenAI deployments. Indirect injection via news feed body text is the realistic threat for a crypto-news-reading bot. Mitigation: action-selector + plan-then-execute (Beurer-Kellner 2025). https://genai.owasp.org/llmrisk/llm01-prompt-injection/

### Failure modes documented
- Phantom-position hallucination after liquidation (TradeTrap).
- Concept drift in keyword-sentiment ("NFT" 2021 vs 2025) — CryptoPanda Medium.
- Latency spikes on reasoning models (Kimi K2.5 8s TTFT).
- Indirect injection via RAG poisoning — 5 crafted docs flip 90% of responses.
- News degrades vs Reddit signal in BTC zero-shot trading.

---

## Hot Picks for 5m / 1h Crypto UP/DOWN Bot

- **Hyperliquid Info API + Bybit funding history** — only free combo that covers all six assets including HYPE on perp + funding + OI in <100ms.
- **Binance liquidation WS + CoinGlass aggregated free** — real-time forced-flow signal; the single highest-frequency edge for 5m UP/DOWN.
- **Reddit OAuth at 100 QPM + Alternative.me F&G** — cheap, fast, and 2025 papers show Reddit > News for BTC short-horizon. Skip news-only sentiment as primary.
- **Kimi K2 0905 via Fireworks** as production decisor — 0.6s TTFT, $0.40/$2.00 per 1M, 75% cache discount. Fits 5m budget; Claude Haiku 4.5 ($1/$5) is the dev fallback.
- **FS-ReasoningAgent fact/subjective split + action-selector pattern** — only architecture with both (a) measured profit lift on BTC/ETH/SOL and (b) defense against the TradeTrap phantom-position class of injection.

---

### Sources
Binance funding: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History
Bybit: https://bybit-exchange.github.io/docs/v5/rate-limit
OKX: https://www.okx.com/docs-v5/en/
Hyperliquid: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
CoinGlass: https://docs.coinglass.com/ + https://www.coinglass.com/pricing
Whale Alert: https://docs.whale-alert.io/
Glassnode: https://docs.glassnode.com/basic-api/api
Alternative.me F&G: https://alternative.me/crypto/api/
LunarCrush: https://lunarcrush.com/developers/api/overview
Santiment: https://academy.santiment.net/products-and-plans/sanapi-plans/
CryptoPanic, CoinDesk dev: https://developers.coindesk.com/
DeFiLlama: https://api-docs.defillama.com/
Reddit: https://support.reddithelp.com/hc/en-us/articles/16160319875092-Reddit-Data-API-Wiki
Deribit: https://docs.deribit.com/
Electric Capital: https://github.com/electric-capital/crypto-ecosystems
Kimi K2: https://artificialanalysis.ai/models/kimi-k2-5/providers
GLM 4.6: https://docs.z.ai/guides/overview/pricing
Claude Haiku 4.5: https://www.anthropic.com/news/claude-haiku-4-5
TradeTrap: https://arxiv.org/html/2512.02261v1
FS-ReasoningAgent: https://arxiv.org/html/2410.12464v3
Multi-agent BTC: https://arxiv.org/html/2510.08068v1
LLM Nowcasting: https://www.mdpi.com/2674-1032/4/4/53
CryptoTrade: https://aclanthology.org/2024.emnlp-main.63/
TradingAgents-crypto: https://github.com/auronsun/TradingAgents-crypto
OWASP LLM01: https://genai.owasp.org/llmrisk/llm01-prompt-injection/
