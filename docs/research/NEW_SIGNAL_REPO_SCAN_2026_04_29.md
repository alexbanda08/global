# Repo scan: signals beyond magnitude-quantile sniper

Date: 2026-04-29
Goal: find a DIFFERENT signal class for Polymarket UP/DOWN crypto markets (5m / 1h / daily) on BTC/ETH/SOL/HYPE/XRP/DOGE.
Already covered: 5m magnitude-quantile sniper on Binance returns.
Scope: funding-rate, on-chain, options-IV, sentiment, event, microstructure. Skipped: vectorbt/backtrader/freqtrade-style generic engines, MM-only, arb-only.

## Shortlist

| # | Repo | Signal class | Free data | Backtest? | Live? | Activity | Idea worth stealing |
|---|------|--------------|-----------|-----------|-------|----------|---------------------|
| 1 | [dev-protocol/Polymarket-Trading-Bot-with-Synth-AI](https://github.com/dev-protocol/Polymarket-Trading-Bot-with-Synth-AI) | Latency sniper: Binance/Bybit move detected -> Polymarket 5m position before odds update | Yes (Binance/Bybit WS) | Paper-mode + real | Yes | 2025+ | "Cycle-end sniper": fire only in last X seconds of the 5m window when realized move > threshold; eliminates timing noise of the magnitude-quantile sniper. |
| 2 | [direkturcrypto/polymarket-terminal](https://github.com/direkturcrypto/polymarket-terminal) | Orderbook sniper on Polymarket itself (not exchange-side) — places 3-tier GTC limits at deep discount to catch panic dumps | Yes (Polymarket CLOB WS) | Live-only | Yes | 2025+ | Tiered GTC ladder at 0.20/0.15/0.10 — passive harvesting of liquidation-driven mispricings on the prediction market itself. Orthogonal to any Binance signal. |
| 3 | [ngixcrash/Polybot](https://github.com/ngixcrash/Polybot) | Hybrid maker + directional sniper for BTC 5m, tuned for Feb-2026 fee changes | Yes | Live-only | Yes | 2026 (current) | Adaptive signal weighting across EMA-cross / OFI / funding tilt; ensemble with vote threshold rather than single hard rule. |
| 4 | [hftbacktest (nkaz001)](https://github.com/nkaz001/hftbacktest) | Order-book imbalance alpha for crypto perps (Binance/Bybit) | Yes (binance vision tick) | Yes (full L2/L3 with queue position) | Backtest -> live | Active | Notebook `Market Making with Alpha - Order Book Imbalance.ipynb`. The OBI alpha (top-N bid vs ask volumes -> short-horizon drift) backtests cleanly on 5m windows — could be lifted whole as a directional signal. |
| 5 | [orderbooktools/crobat](https://github.com/orderbooktools/crobat) | Academic OFI / TFI implementation (Cont/Kukanov/Stoikov, Huang queue-reactive) | Yes (Coinbase WS) | Research-grade only | No | 2023 (paper-grade) | Reference implementation of Order Flow Imbalance — the canonical microstructure alpha. Use the formula, not the live infra. |
| 6 | [hamood1337/CryptoFundingArb](https://github.com/hamood1337/CryptoFundingArb) | Cross-venue funding-rate spread scanner (Binance/Bybit/HL/OKX/Kraken/Kucoin) | Yes (public APIs) | No (scanner) | Yes | 2025 | Build a "funding regime" feature: cross-exchange funding dispersion z-score as a directional filter on 1h Polymarket markets. |
| 7 | [aoki-h-jp/funding-rate-arbitrage](https://github.com/aoki-h-jp/funding-rate-arbitrage) | CEX funding-rate divergence framework | Yes | No | Detection only | Active | Clean Python class structure for normalizing 1h vs 8h funding intervals — solves the Hyperliquid vs Binance apples-to-apples problem. |
| 8 | [minchillo4/btc-liquidation-heatmap](https://github.com/minchillo4/btc-liquidation-heatmap) | OI-anomaly + liquidation-cluster predictor | Yes (CoinAlyze API free tier) | Yes (60h rolling baseline) | Visualizer | 2025 | 3-tier OI-delta severity classification (H1/H2/H3) using rolling MA. Bins reset when price crosses — elegant unresolved-leverage tracker. Feature: "distance to nearest H3 cluster" as a 1h directional filter. |
| 9 | [Polymarket/agents](https://github.com/Polymarket/agents) | Official Polymarket LLM agent framework (LangChain + Chroma) | Mostly free (needs LLM key) | No | Yes | Active (official) | Chroma vector store of historical resolutions — RAG over similar past markets. Useful template for an event/sentiment overlay. |
| 10 | [qrak/LLM_trader](https://github.com/qrak/LLM_trader) | RAG-augmented LLM trader: news + indicators -> BUY/SELL/HOLD/CLOSE with multi-personality agents (conservative/aggressive/contrarian) | Free for code, paid LLM | Yes (with brain-memory replay) | Yes | 2025 | "Brain memory" loop: every trade outcome is fed back into the RAG index. Could batch news per coin every 1h and feed into a single LLM call for a 1h Polymarket directional vote. |
| 11 | [ryanfrigo/kalshi-ai-trading-bot](https://github.com/ryanfrigo/kalshi-ai-trading-bot) | Multi-agent LLM (Grok-4) on Kalshi prediction markets with explicit "AI directional" mode | Free except Grok | Limited | Yes | 2025 | Closest analog to what we want — Kalshi is structurally identical to Polymarket UP/DOWN. Lift the agent-vote architecture wholesale. |
| 12 | [Tickermind (DarmorGamz)](https://github.com/DarmorGamz/Tickermind) | Local-LLM news scanner with directional sentiment + custom TA | Yes (local Llama) | No | Yes | 2025 capstone | Local LLM means $0 inference cost — viable for 5m or 1h news ingestion at scale without API spend. |

## Academic-paper-with-code (bonus)

| Paper | Repo | Relevance |
|-------|------|-----------|
| Westray, "Deep Order Flow Imbalance: Extracting Alpha at Multiple Horizons from the LOB" | Refs in [hftbacktest](https://github.com/nkaz001/hftbacktest) examples | Multi-horizon OFI -> directly maps to 5m / 1h / daily Polymarket horizons. |
| Cont/Kukanov/Stoikov, "The Price Impact of Order Book Events" | [orderbooktools/crobat](https://github.com/orderbooktools/crobat) | Canonical OFI definition. |
| "Bitcoin's Edge: Embedded Sentiment in Blockchain Transactional Data" (arXiv 2504.13598) | linked from paper | NLP on on-chain memo fields as a leading indicator — novel feature class. |
| Amberdata "Bitcoin Options: Finding edge in four years of vol regimes" | Methodology, no code | 1M skew z-score (call IV - put IV, 30d rolling) with |z|>1 trigger. Backtest template for an IV-skew directional overlay. |

## Top 3 to investigate further

1. **dev-protocol/Polymarket-Trading-Bot-with-Synth-AI** — closest in spirit to our existing sniper but adds the "cycle-end" timing twist. Direct A/B against our magnitude-quantile sniper on the same 5m markets is cheap to set up and would tell us whether timing-within-window beats magnitude-of-window.
2. **hftbacktest + crobat (combined)** — order-flow imbalance is the most academically validated microstructure alpha and runs on free Binance tick data we already pull. Genuinely DIFFERENT signal class from our return-magnitude approach. Paste the OBI notebook into our backtest harness, walk-forward against the same Polymarket UP/DOWN slugs.
3. **minchillo4/btc-liquidation-heatmap + hamood1337/CryptoFundingArb** — combine OI-cluster proximity (cascade fragility) with cross-exchange funding dispersion (regime). Best fit for the **1h** Polymarket horizon where 5m microstructure noise washes out but daily macro hasn't taken over. Free data, both repos active.

## Skipped explicitly

- All `polymarket-arbitrage-bot` / `polymarket-copy-trading-bot` clones (Orbital-Alpha, Parallax, RaymondDakus, 0xFives, frogansol, dev-protocol/polymarket-trading-bot, KaustubhPatange/polymarket-trade-engine) — pure copy/arb/dump-hedge, no new signal class.
- CarlosIbCu Polymarket-Kalshi arb — cross-venue arb, not directional.
- Generic crypto-trading-strategy-backtester / btrccts / DorukKorkmaz — generic engines.
- WasamiKirua/uzillion/pmaji whale trackers — alert-only, no model.
