# Latency / HFT / Oracle-Lag Arbitrage: External Research Catalog
**Date:** 2026-05-29  
**Purpose:** Deep-dive external research catalog — every documented latency/HFT/oracle-lag arbitrage strategy class, evaluated for applicability to our Polymarket BTC/ETH/SOL up-down oracle-lag taker.

---

## Summary Table — Ranked by Applicability to Our Setup

| # | Strategy | Latency Req | Applicability | Key Action |
|---|---|---|---|---|
| 1 | **Oracle-lag taker (Polymarket-specific)** | 1–60s | **ALREADY DOING** | Harden signal; see §10 |
| 2 | **OEV / oracle-backrun informational play** | 5–30s | **APPLICABLE** | Monitor Chainlink update time; buy stale side first |
| 3 | **Cross-exchange lead-lag (futures→spot info)** | 1–30s | **APPLICABLE** | CME/Binance perps as directional pre-signal |
| 4 | **Perpetual funding-rate basis / carry** | Hours–days | **PARTIAL** | Directional bias signal only, not primary edge |
| 5 | **Stale-quote sniping on Polymarket CLOB** | 1–30s | **APPLICABLE** | Same mechanism as #1 but on resting limit orders |
| 6 | **GMX-style oracle front-run on perp DEX** | 1–15s | **PARTIAL** | Confirms our mechanism; direct port blocked by DEX |
| 7 | **MEV sandwich / DEX oracle backrun** | Sub-block (~2s) | **NOT** | Requires on-chain tx ordering; no mempool access |
| 8 | **Classic cross-exchange latency arb (CEX↔CEX)** | Sub-100ms | **NOT** | Speed race; we lose at this timescale |
| 9 | **Stale-quote sniping in equities/FX (last-look)** | Sub-ms | **NOT (context)** | Useful theory; sub-ms out of reach |
| 10 | **Microwave/colocation HFT arms race** | Sub-ms | **NOT** | Infrastructure gap; academic context only |

---

## 1. Oracle-Lag Taker on Polymarket (OUR CURRENT STRATEGY — ALREADY DOING)

**Mechanism:** Polymarket 1m/5m/15m binary crypto markets resolve via Chainlink Data Streams. Chainlink DON aggregates CEX prices and signs a cryptographically verifiable report; Chainlink Automation fetches that report at slot-end and submits the settlement transaction on Polygon. Between a Binance price move and the moment that move propagates into the resting Polymarket CLOB (where market-makers reprice their limit orders), there is a 5–60 second window where the leading side trades below fair value. A fast taker reads Binance WS, computes the implied side, and buys the stale CLOB ask before it is lifted.

**Latency requirement:** Signal latency = seconds (Binance WS → decision → CLOB order). Execution latency to Polymarket CLOB = <2ms (Ireland → AWS eu-west-2 London). Total: 1–30s informational lead is sufficient; sub-100ms execution speed is not required and not the edge.

**Documented edge:**
- Our own OOS backtest: +$1.31/$25 stake, WR 63%, t=2.28 (37-day window, engine_v2, real fees).
- JonathanPetersonn/oracle-lag-sniper (GitHub, open-sourced): 8,876 resolved markets, 5,017 trades, **61.4% WR**, profitable on 20/24 days. Backtest split 60/40 by date — hold-out half also 60.7% WR. Used on 15-min BTC/ETH/XRP/SOL.
- Published claim: order book takes **~55 seconds on average** to reprice after Chainlink update; that gap is the exploitable window.
- Decoded wallet analysis (our data): wallets 0x07480f20 (76.1% WR, ~$224/day on up-down), 0xe3867b68 (69.4%), 0x8ef6a1cc (cl_basis btc-5m) — all running directional oracle-lag takers using `cl_basis_bps` (Binance minus Chainlink) as signal.

**Capital / infra:** $25–$5,000 per trade; no colocation needed; WS connection to Binance + Polymarket CLOB WS; Ireland VPS sufficient.

**Risks:** 
- Edge decays as more bots populate the strategy.
- CLOB book is thin ($5k–$50k per window); large position raises own slippage.
- Polymarket fee = 2% on winning leg only (verified against 25,900 production events).
- Wrong-side entry on a fast mean-reverting move.

**Applicability:** ALREADY DOING. See §10 for hardening ideas.

**Sources:**
- JonathanPetersonn, oracle-lag-sniper: https://github.com/JonathanPetersonn/oracle-lag-sniper
- DEV Community writeup: https://dev.to/jonathanpetersonn/building-a-real-time-oracle-latency-bot-for-polymarket-with-python-and-asyncio-3gpg
- Hashnode "55-second" writeup: https://hashnode.com/forums/thread/how-i-used-python-asyncio-to-trade-a-55-second-oracle-lag-on-polymarket
- BlockEden deep-dive on Chainlink Data Streams + Polymarket architecture: https://blockeden.xyz/forum/t/deep-dive-how-chainlink-data-streams-power-polymarkets-5-minute-settlement-oracle-architecture-for-high-frequency-prediction-markets/786

---

## 2. Oracle Extractable Value (OEV) — Informational Oracle-Backrun

**Mechanism:** OEV is the MEV subset arising specifically from oracle price updates. When an oracle (push-based: Chainlink Price Feeds; or pull-based: Chainlink Data Streams) updates the on-chain price, it creates a brief window during which the on-chain price diverges from the true market price. Searchers monitor off-chain prices and the oracle's pending update queue; they submit transactions timed to the oracle update to capture the price correction.

**Two sub-variants relevant to us:**
- **Lending liquidation OEV:** Collateral drops in value → oracle update triggers liquidation eligibility → race to be the liquidator (irrelevant to us but exemplifies the mechanism).
- **Informational OEV (our analogy):** The Chainlink DON has already computed the new price report (off-chain, sub-second) but it has not yet triggered the Polymarket settlement tx. Anyone who can read the signed Chainlink report before the settlement tx lands can determine the winning side with certainty. This is our edge: we read Binance WS as a proxy for the forthcoming Chainlink report.

**Key DeFi precedents:**
- GMX v1 (perpetual DEX): traders systematically opened leveraged positions in the direction of a known upcoming oracle update, then closed post-update. Losses came directly from the GLP LP pool. GMX estimated ~10% of protocol profits lost to oracle front-runners. GMX v2 patched this with two-step execution + Chainlink Data Streams.
- KiloEx: drained $7.5M in a single attack exploiting stale oracle data.
- Aave/Euler: $180M+ in liquidation incentives paid to external liquidators/searchers over time — most is OEV.

**Chainlink's mitigations:**
- Chainlink Smart Value Recapture (SVR): Dual Aggregator + Flashbots MEV-Share; internalizes OEV back to dApp.
- Chainlink Data Streams: "commit-and-reveal" approach makes trade data and oracle report visible atomically on-chain — mitigates front-running by hiding pricing info until settlement.
- API3 OEV Network: L2 ZK-rollup order-flow auction; searchers bid for the right to execute oracle update + trade in one atomic tx.

**Why this matters for us:** Polymarket uses the *pull-based* Data Streams model, not the old push-based oracle. The settlement price is determined at exact slot-end timestamps, not polled. The "exploitable window" is therefore on the CLOB side (market makers are slow to cancel stale orders), not on the oracle submission side — which is our exact observation.

**Latency requirement:** Reading Chainlink Data Streams directly via their WS API gives sub-second access to signed price reports. This is faster than waiting for Binance (which we currently use as proxy). **Upgrading our signal source from Binance WS to the Chainlink Data Streams WS would shorten our signal lag by potentially 1–5 seconds and remove the Binance→Chainlink basis uncertainty.**

**Applicability:** APPLICABLE — specifically the insight that monitoring the oracle's own output stream (not just Binance as a proxy) is the most direct signal.

**Sources:**
- Chainlink OEV explainer: https://chain.link/article/oracle-extractable-value
- Chainlink Smart Value Recapture: https://chain.link/article/smart-value-recapture
- Chainlink Data Streams docs: https://docs.chain.link/data-streams
- Cyfrin oracle attacks: https://medium.com/cyfrin/chainlink-oracle-defi-attacks-93b6cb6541bf
- API3 OEV Network docs: https://docs.api3.org/oev-searchers/

---

## 3. Cross-Exchange Lead-Lag (Futures Lead / Spot Lag)

**Mechanism:** In equity and crypto markets, one venue systematically leads the price discovery process. Informed traders and hedgers gravitate to the most liquid, lowest-cost venue. In BTC: CME Bitcoin futures have been shown to lead Binance spot by a measurable number of seconds at high-frequency time scales. A bot that monitors the leading venue can predict the direction of the lagging venue's next print.

**Academic evidence:**
- Bitwise/CME analysis (2021, SEC filing exhibit): Time-Shift Lead-Lag analysis at -60s to +60s in 0.2s increments found CME consistently leads, statistically significant (p<0.05).
- Frino et al. (2025, Journal of Futures Markets): 1-second sampling; "futures market generally leads spot markets; daily fluctuations."
- Robertson & Zhang (SSRN 2022): Hayashi-Yoshida estimator; "CME Bitcoin futures have consistently led price formation."
- Counterpoint — Corbet et al. (2018): 1-minute data, found spot leads. Likely a time-resolution artifact (at 1-min, the info has already propagated).

**Practical magnitude:** The lead is measured in seconds (1–30s range at intraday). The same informational lag that makes CME lead Binance in spot also makes Binance lead Polymarket CLOB — a two-step cascade.

**Our current setup:** We use Binance spot WS (`ret_3m`, `ema9_slope_bps`) as the primary signal. Upgrading to also monitor CME Bitcoin futures (via CME WebSocket or a data vendor like Bloomberg/Refinitiv) or Binance perpetual futures (available via Binance WS already) would add a ~1–10s upstream lead signal.

**Latency requirement:** Seconds. No colocation required. Pure informational edge.

**Documented returns:** Multi-venue cross-exchange latency arb (CEX↔CEX) earns on the order of $28,000–$100,000 per venue-pair per year for well-capitalized shops, but requires sub-100ms execution for the direct spread. The INFORMATIONAL component (predicting direction, not capturing the spread itself) is accessible at our timescale.

**Applicability:** APPLICABLE as a signal-enhancement layer. Use Binance perpetuals funding rate direction + perp premium as a second confirmation signal before firing.

**Sources:**
- Bitwise BTC ETP White Paper (CME leads spot): https://static.bitwiseinvestments.com/Bitwise-Bitcoin-ETP-White-Paper-1.pdf
- Frino et al. 2025 (Journal of Futures Markets): https://onlinelibrary.wiley.com/doi/10.1002/fut.22560
- PMC intraday connectedness study: https://pmc.ncbi.nlm.nih.gov/articles/PMC9476405/
- Indie Hackers Polymarket latency arb 2026: https://www.indiehackers.com/post/latency-arbitrage-in-15-minute-crypto-markets-building-a-polymarket-trading-edge-2026-f77cc226c0

---

## 4. Perpetual Funding-Rate Basis / Carry Trade

**Mechanism:** Perpetual futures use a funding rate (every 8 hours on most CEXs) to anchor perp price to spot. When the perp trades at a premium (bullish sentiment), longs pay shorts. A delta-neutral position (long spot + short perp, or long perp + short spot) earns the funding rate as near-riskless carry.

**Edge / returns:**
- BIS Working Paper 1087 ("Crypto Carry"): empirically, deviations of crypto perps from no-arbitrage are "considerably larger" than traditional FX markets; a simple trading strategy generates large Sharpe ratios even for investors paying the highest Binance fees.
- Static strategy (enter when funding >0.01%, exit <0.005%): ~18% annual return, Sharpe 1.4 (2019–2023, documented).
- Dynamic ML-enhanced version: ~31% annual return, Sharpe 2.3 (same period).
- Funding rates are positive the vast majority of the time in crypto, reflecting persistent leveraged long demand.

**Why relevant to our setup:** Binance perp premium (perp price − spot price) divided by time = implied annualized funding. When this premium is large and rising, the market is crowded long → directional signal for our oracle-lag taker (the "Up" side is likely mispriced cheap on Polymarket). We already track `ret_3m`; adding `perp_premium_bps` as a gate could improve precision.

**Latency requirement:** Hours to days for pure carry. Minutes for using it as a directional confirmation signal (seconds of lag is fine).

**Applicability:** PARTIAL — the carry trade itself is not our strategy, but the funding rate direction is a high-quality additional confirmation signal for whether Binance momentum is "real" vs noise.

**Sources:**
- BIS Working Paper 1087 (Crypto Carry): https://www.bis.org/publ/work1087.pdf
- arXiv Fundamentals of Perpetual Futures: https://arxiv.org/pdf/2212.06888
- ScienceDirect funding rate arbitrage risk-return: https://www.sciencedirect.com/science/article/pii/S2096720925000818

---

## 5. Stale-Quote Sniping on Prediction Market CLOBs

**Mechanism:** Classic latency arbitrage: a market maker posts a limit order at a price reflecting the current market state. When the underlying asset price moves, the market maker's order becomes stale (priced below fair value for the informed taker). A fast taker picks off the stale order before the market maker can cancel.

This is precisely what our oracle-lag taker does — it is the Polymarket-specific instantiation of the general stale-quote sniping phenomenon.

**Academic documentation (Budish-Cramton-Shim framework):**
Aquilina, Budish, O'Neill (2021, BIS Working Paper 955) quantified this in equity markets:
- Latency arbitrage races: ~1 per minute per symbol for FTSE 100 stocks.
- Modal race duration: **5–10 microseconds** (sub-ms; out of reach for us in equities).
- 20% of all trading volume occurs during races.
- **Latency arbitrage tax: 0.42 basis points** of trading volume; ~£60M/year in UK; extrapolated $5B/year globally in equities.
- Top 6 firms win >80% of all races.
- Latency arb accounts for **33% of effective spread** and **31% of all price impact**.

**Key insight for Polymarket:** In equity CLOBs, the race lasts microseconds — we cannot win. In Polymarket, the "race" lasts 5–60 seconds because:
1. Polymarket CLOB market makers are not co-located HFT firms.
2. The oracle (Chainlink) only updates on 0.5% deviation or heartbeat.
3. Human and slower-bot market makers take 10–60s to cancel and reprice.
The structural advantage for us is that Polymarket has **not yet attracted microsecond-scale HFT infrastructure** — the race is still in seconds.

**Latency requirement for Polymarket sniping:** 1–30 seconds of informational lead. Ireland VPS → London CLOB: ~2ms execution. This is sufficient.

**Applicability:** APPLICABLE — this is our exact strategy. The BCS framework confirms it is a structural feature of any CLOB with stale quotes; the only question is whether the window is sub-ms (equities, we lose) or multi-second (Polymarket, we win).

**Sources:**
- Aquilina, Budish, O'Neill, BIS WP 955: https://www.bis.org/publ/work955.htm (full PDF: https://www.bis.org/publ/work955.pdf)
- Budish, Cramton, Shim (QJE 2015) Semantic Scholar: https://www.semanticscholar.org/paper/The-High-Frequency-Trading-Arms-Race:-Frequent-as-a-Budish-Cramton/ab490960df8dc315cc5b4a089c7ce206ea5f7746
- CFA Institute blog on BCS batch auctions: https://blogs.cfainstitute.org/marketintegrity/2014/11/10/are-frequent-batch-auctions-a-solution-to-hft-latency-arbitrage/

---

## 6. GMX-Style Oracle Front-Run on Perpetual DEX

**Mechanism:** GMX v1 (and similar oracle-priced perpetual DEXs) used a Chainlink push-feed as the execution price. The oracle updates every N seconds or on threshold deviation. Traders observed the lag between Binance and the GMX oracle price feed, then:
1. Opened a leveraged long (or short) position at the stale GMX oracle price, knowing the next oracle update would move in their direction.
2. Closed the position immediately after the oracle updated.
3. Profits came from the GLP liquidity pool (protocol LPs are the counterparty).

**Documented losses:** GMX estimated approximately **10% of protocol profits** were captured by oracle front-runners before Chainlink Data Streams integration. KiloEx lost $7.5M in a single oracle-stale-price attack.

**Mitigation (GMX v2):** Two-step order execution (submit order in block N, execute in block N+1 with the next oracle price) + Chainlink Data Streams (sub-second, commit-and-reveal). This closed the window on GMX.

**Why relevant:** Confirms our mechanism is not theoretical — it was deployed at scale against real protocols. The structural analogy to Polymarket is direct: Polymarket uses Chainlink Data Streams (commit-and-reveal for settlement), but the CLOB order book is NOT on-chain and NOT protected by commit-and-reveal. The residual window is on the CLOB resting orders, not the settlement oracle — which is exactly what we exploit.

**Latency requirement:** Seconds (oracle heartbeat lag). No colocation.

**Applicability:** PARTIAL — the exact mechanism (DEX oracle front-run) is not directly portable (we'd need to be a perp DEX trader, not a prediction market trader). But the analogy is 1:1 and validates our edge.

**Sources:**
- Castle Capital GMX v2 analysis: https://chronicle.castlecapital.vc/p/deciphering-gmx-v2-next-wave-decentralized-perps
- Chainlink low-latency oracle for DeFi derivatives: https://blog.chain.link/low-latency-oracle-solution/

---

## 7. MEV: Sandwich Attacks and Oracle Backrunning (On-Chain)

**Mechanism:** On-chain MEV involves searchers monitoring the mempool (pending transaction queue) and inserting their own transactions before (front-run) or after (back-run) a target transaction. Sandwich attack = front-run + back-run around a victim swap on a DEX.

**Oracle backrunning:** When a Chainlink push-oracle submits a price update transaction, searchers see it in the mempool and submit a liquidation or trade transaction to execute immediately after the oracle update lands, capturing the price correction.

**Documented scale:** Over $540M extracted via sandwich attacks, liquidations, and DEX arb over 32 months (Qin et al., arXiv 2101.05511). Cross-chain sandwich attacks (new 2025 variant): $5.27M in two months from Symbiosis protocol.

**Why NOT applicable:** Our edge is off-chain (Polymarket CLOB is an off-chain matching engine; settlement is on Polygon but orders are not mempool-visible). We do not control transaction ordering on Polygon. There is no mempool to monitor for Chainlink Data Streams reports (pull-based = reports are delivered to the requesting contract, not broadcast publicly in the mempool before settlement). This category is **not reachable** with our setup.

**Latency requirement:** Sub-block (~2 seconds on Ethereum, ~1 block on Polygon ~2s). Requires specialized Flashbots/MEV-relay infrastructure.

**Applicability:** NOT applicable. Our edge is off-chain CLOB repricing lag, not on-chain tx ordering.

**Sources:**
- Ethereum MEV docs: https://ethereum.org/en/developers/docs/mev/
- Flash Boys 2.0 (Daian et al.): https://arxiv.org/abs/1904.05234
- Quantifying BEV (Qin et al.): https://arxiv.org/abs/2101.05511
- Cross-chain sandwich attacks (2025): https://arxiv.org/html/2511.15245v1

---

## 8. Classic Cross-Exchange Latency Arbitrage (CEX↔CEX Pure Spread)

**Mechanism:** BTC/USDT trades at $28,000 on Binance. KuCoin lags by 100ms due to infrastructure differences. A co-located bot buys on KuCoin at $28,000 and sells on Binance at $28,100, capturing $100/BTC in ~100ms.

**Infrastructure required:** Co-location at both exchanges (or nearby data centers), sub-ms order routing, direct market access, dedicated hardware. Firms spend ~$8M per microwave link between Chicago and New York; Chicago–NY fiber is ~6.65ms, microwave ~4.2–5.2ms (BCS/Aquilina research). London–Frankfurt: fiber 17ms, microwave 4.2ms.

**Documented edge (equities):** Latency arbitrage tax 0.42 basis points in FTSE 100; $5B/year globally. On crypto, spreads are wider but competition is intensifying rapidly.

**Why NOT applicable:** We are not co-located. Our Ireland VPS has ~2ms to Polymarket (London), which is fine for our purpose, but we cannot reliably beat co-located bots in a microsecond race. Any direct spread CEX↔CEX arb would require sub-100ms execution, which we cannot guarantee.

**Applicability:** NOT applicable as a direct strategy. Contextually useful: confirms that the CEX↔CEX pure-speed game is a capital-intensive infrastructure arms race we do not enter.

**Sources:**
- Aquilina, Budish, O'Neill BIS WP 955: https://www.bis.org/publ/work955.htm
- Microwave vs fiber analysis: https://wealthandfinance.digital/microwave-vs-fiber-the-network-showdown-reshaping-financial-markets/
- QuantVPS latency arbitrage explainer: https://www.quantvps.com/blog/what-is-latency-arbitrage
- arXiv Chicago-NY information transmission: https://arxiv.org/pdf/1302.5966

---

## 9. Last-Look and Stale Quote Sniping in FX / Equities

**Mechanism:** Foreign exchange liquidity providers stream quotes to clients. A fast client ("latency arbitrageur") can observe the LP's quote updating slowly while the true market has already moved — and trade on the stale quote for risk-free profit. "Last Look" is the LP's defense: the LP retains the option to reject an order received during the evaluation period (typically milliseconds), preventing exploitation of stale quotes.

**Academic framework (Cartea, Jaimungal, Walton 2018):** "Foreign Exchange Markets with Last Look" (Mathematics and Financial Economics). Formalizes the equilibrium: spreads widen when Last Look is active because the LP can sift toxic (LA) flow from slow-trader flow; brokers break even by recovering LA losses from slow-trader gains. When price revisions are positively correlated (momentum), Last Look is more effective at filtering toxic flow and spreads are tighter.

**Kyle (1985) / Glosten-Milgrom (1985) connection:** Seminal models of informed vs noise trading; LPs cannot observe trade type ex ante, so they widen the spread to break even against informed flow. Our Polymarket oracle-lag taker IS the "informed trader" in this framework — we have information (Binance price direction) that Polymarket makers do not yet have. The 2% taker fee we pay is the "spread" the protocol charges.

**Latency requirement:** Sub-ms in FX/equities (out of reach). On Polymarket, seconds — achievable.

**Applicability:** NOT applicable as a direct strategy (FX/equities sub-ms race). HIGHLY RELEVANT as theoretical framework — we are the snipers; the 2% fee is our "spread cost." Understanding this from the maker's perspective informs how quickly the edge will decay (when makers start using faster cancellation logic or tighter deviation thresholds).

**Sources:**
- Cartea, Jaimungal, Walton (2018): https://arxiv.org/pdf/1806.04460
- Norges Bank (NBIM) Last Look paper: https://www.nbim.no/contentassets/bab2624ad58c4aa4aca65d19bfff2152/nbim_asset-managerperspective_3-15.pdf

---

## 10. Microwave / Colocation HFT Arms Race

**Mechanism:** HFT firms invest $8M+ per microwave network link to shave 2–5ms off Chicago–NY latency. Modal race duration on FTSE 100: 5–10 microseconds. Top 6 firms win >80% of races. CME microwave now handles 47% of index futures trades during volatile periods (vs 28% of normal volume).

**Why documented:** The BCS/Aquilina literature (NBER, BIS) models this as a socially wasteful prisoner's dilemma — every firm must match competitors' speed investments or be sniped. Total welfare cost: ~$5B/year in equities globally.

**Proposed solution (BCS):** Frequent Batch Auctions — replace continuous-time CLOB with discrete-time (e.g., 100ms) uniform-price auctions. Eliminates latency arbitrage by making all orders within a batch interval "simultaneous." Not yet widely adopted.

**Applicability:** NOT applicable. We cannot win microsecond races. Contextually important: confirms that the "arms race" interpretation of our edge is relevant — we are in a **seconds-timescale** arms race on Polymarket, and this will compress over time as the market matures and faster bots arrive.

**Sources:**
- Aquilina, Budish, O'Neill BIS WP 955: https://www.bis.org/publ/work955.htm
- BCS paper (Semantic Scholar): https://www.semanticscholar.org/paper/The-High-Frequency-Trading-Arms-Race:-Frequent-as-a-Budish-Cramton/ab490960df8dc315cc5b4a089c7ce206ea5f7746
- NY Fed batch auctions: https://www.newyorkfed.org/medialibrary/media/newsevents/events/markets/2015/A-Market-Design-Perspective-HFT-Debate.pdf
- Microwave networks study (ScienceDirect): https://www.sciencedirect.com/science/article/pii/S1386418123000514

---

## 11. AI-Augmented Signal Confirmation on Short-Duration Prediction Markets

**Mechanism:** Rather than purely reactive oracle-lag detection, layer a predictive model that forecasts the probability a current Binance move will *persist* through the end of the slot — filtering out fast mean-reversions that would still end up on the wrong side at resolution.

**Published approaches:**
- Jung-Hua Liu (Medium, 2026): "AI-Augmented Arbitrage in Short-Duration Prediction Markets" — LSTM on Polymarket 5-minute BTC binary options with live trading analysis. Combines oracle-lag signal with momentum classification.
- QuantVPS lead-lag framework: "Instead of merely reacting to price differences, top-performing algorithms forecast microstructure changes before the rest of the market adjusts." Uses RL to optimize timing and volume.
- Optimal stopping framework (arXiv 2309.16008, Purdue): Sequential optimal stopping problem for entry/exit timing in statistical arbitrage, incorporating transaction costs. Maximizes gain-per-entry by choosing *when* within the window to enter.

**Applicability:** APPLICABLE as a research direction. Our current signal is directional-only (slope of ema9, `ret_3m`). Adding a persistence/volatility gate (e.g., "is the move large enough relative to recent sigma to suggest it won't reverse?") directly maps to the optimal stopping literature.

**Sources:**
- Jung-Hua Liu AI-augmented Polymarket: https://medium.com/@gwrx2005/ai-augmented-arbitrage-in-short-duration-prediction-markets-live-trading-analysis-of-polymarkets-8ce1b8c5f362
- Optimal entry/exit with signature (arXiv): https://arxiv.org/pdf/2309.16008
- Robust lead-lag detection (arXiv): https://arxiv.org/pdf/2305.06704

---

## 12. Special Topic: Chainlink Data Streams Architecture vs. Our Strategy

**What Chainlink Data Streams actually does:**
- Pull-based (not push): reports are generated continuously at sub-second frequency by the DON (Decentralized Oracle Network) and stored off-chain.
- Polymarket's settlement contract fetches the report for `slot_start_us` and `slot_end_us` via Chainlink Automation, verifies the cryptographic signature on-chain, and settles.
- The signed price report exists off-chain (Chainlink's aggregation network) potentially seconds before it is fetched by the Automation contract.
- Reports include: mid price, Liquidity-Weighted Bid and Ask (LWBA), timestamp, DON signature.

**Implication for our strategy:**
- We currently use Binance spot price as a PROXY for what Chainlink will report.
- The Chainlink Data Streams WS API (subscribe to reports in real time) would give us the **exact** price that will be used for settlement, not a proxy.
- Subscribing directly to the `BTC/USD` Data Streams feed via WS would:
  1. Eliminate basis risk (Binance vs Chainlink divergence when they use different sources).
  2. Confirm the exact direction with certainty rather than inference.
  3. Potentially shorten signal latency by 1–5s (no need to wait for the Chainlink price to visibly lag Binance — we'd see the Chainlink price directly).
- **Access:** Chainlink Data Streams requires a developer plan/API key. Available via REST API or WebSocket (active-active multi-site for 99.9%+ uptime). Crypto streams include LWBA prices showing current order book depth.

**Risk:** Using the Chainlink report directly may constitute front-running the settlement — Polymarket's T&Cs should be reviewed. The commit-and-reveal architecture is designed to prevent using the report to front-run on-chain settlement transactions; using it to trade on the CLOB (off-chain) is a different question.

**Sources:**
- Chainlink Data Streams docs: https://docs.chain.link/data-streams
- Chainlink Data Streams architecture: https://docs.chain.link/data-streams/architecture
- Chainlink LWBA prices: https://docs.chain.link/data-streams/concepts/liquidity-weighted-prices

---

## 13. Hardening / Extending the Oracle-Lag Taker: Best Ideas Synthesized

### 13.1 Direct Chainlink Data Streams Signal (HIGH PRIORITY)
**Action:** Subscribe to Chainlink Data Streams WS for BTC/USD, ETH/USD, SOL/USD. Replace Binance proxy with exact Chainlink report.  
**Expected gain:** Eliminates 1–5s of basis uncertainty; WR should improve by removing "Binance moved but Chainlink agrees" false positives.  
**Effort:** Medium (API key required; WS client addition).

### 13.2 Multi-Venue Lead Confirmation (HIGH PRIORITY)
**Action:** Add Binance perpetuals (already on WS) `perp_premium_bps` and `funding_rate_direction` as pre-signal gates. Require both spot move AND perp premium moving in same direction before firing.  
**Rationale:** CME/perp futures lead spot price discovery by 1–10s. A spot move that is *not* confirmed by perps is more likely to reverse before slot end.  
**Expected gain:** Filters ~15–20% of borderline trades that are mean-reverting.

### 13.3 Optimal Entry Timing Within the Window (MEDIUM PRIORITY)
**Action:** Instead of firing at the first signal, wait for signal confirmation via a second Binance bar. Entry at `ws_s + 60s` vs `ws_s + 30s` — our data shows WR rises with offset but EV stays ~0 at coin-flip signals. For *strong* signals (cl_basis_bps > threshold), early entry captures more of the stale-ask window.  
**Research basis:** Our own lag_sweep: WR 50%→59%→66% as offset increases but EV flat due to price move; JonathanPetersonn: signal fires at minimum 5 minutes remaining, price moved ≥0.07%. Optimal stopping theory (arXiv 2309.16008).

### 13.4 Persistence / Volatility Gate (MEDIUM PRIORITY)
**Action:** Add a realized-volatility gate: if 30s realized vol > σ_threshold, skip (mean-reversion risk too high). If move size > k×σ, it is more likely to persist.  
**Rationale:** Flash Boys 2.0 / toxic flow literature: informed trades tend to be larger and more persistent than noise trades. Our taker is "informed" — but we want to filter out the cases where the Binance move is itself noise.

### 13.5 CLOB Order-Book Depth Filter (ALREADY PARTIALLY DONE)
**Status:** engine_v2 already uses `min_book_events=25` and the cross-token spread filter.  
**Enhancement:** Additionally monitor the bid-ask depth on both Up and Down tokens. If the ask on the leading side has already been lifted significantly (indicating a faster bot got there first), skip — the edge is gone.

### 13.6 Multi-Asset Correlation Signal (LOW PRIORITY)
**Action:** For BTC slot fires, check if ETH is also moving in the same direction. Correlated cross-asset moves are more persistent than uncorrelated single-asset moves.  
**Basis:** Wallet 0xe3867b68 uses `ema9_slope_cross_asset` (BTC + ETH combined). If both are moving, oracle update will move in the confirmed direction.

### 13.7 Time-of-Day Gating (MEDIUM PRIORITY)
**Observation from wallet decodes:** Decoded wallet 0xe3867b68 fires heavily in non-US hours; F2 wallet (decoded) fires 22:00–02:00 UTC + 09:00–10:00 UTC, avoids 12:00–21:00 UTC. During US hours, market makers are faster (more active) and the CLOB reprices faster, shrinking the exploitable window.  
**Action:** Add a ToD gate that requires a larger `cl_basis_bps` threshold during US hours (12:00–21:00 UTC) and accepts a lower threshold during quiet hours.

---

## Appendix: Key Papers / Sources Reference

| Source | Relevance |
|---|---|
| Aquilina, Budish, O'Neill (BIS WP 955, 2021) | Quantifies LA tax (0.42 bps, $5B/yr, 20% of volume in races) |
| Budish, Cramton, Shim (QJE 2015) | Root diagnosis: continuous CLOB creates structural sniping; batch auctions as fix |
| Cartea, Jaimungal, Walton (2018) | Last-look / stale-quote sniping formalized in FX |
| Daian et al. Flash Boys 2.0 (2019) | First formal treatment of MEV / PGA in DEXs |
| Qin, Zhou, Gervais (2021) | Quantifies $540M BEV extracted over 32 months on Ethereum |
| Zhou et al. HFT on DEX (2020) | Sandwich attacks on Uniswap; $1000s/day per adversary documented |
| Chainlink OEV explainer (2026) | OEV mechanism, Chainlink SVR, API3 OEV Network |
| Chainlink Data Streams docs | Sub-second pull-based oracle; WS API; LWBA prices |
| JonathanPetersonn oracle-lag-sniper (GitHub) | Open-source Polymarket oracle-lag bot; 61.4% WR on 8,876 markets |
| BlockEden deep-dive (2026) | Chainlink Data Streams + Polymarket settlement architecture |
| BIS WP 1087 (Crypto Carry) | Funding rate arb; large Sharpe documented |
| CME lead-lag studies (Bitwise, Frino 2025) | CME futures lead spot by seconds at high frequency |
