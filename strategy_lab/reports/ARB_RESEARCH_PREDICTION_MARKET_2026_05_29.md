# Prediction-Market & CTF/Merge Arbitrage: Strategy Catalog
**Compiled 2026-05-29 | Research-only document — no local codebase reads**

---

## Summary Table — Ranked by Applicability to Our Polymarket BTC/ETH/SOL Up-Down Setup

| # | Strategy | Applicability | Latency Req | Capital | Notes |
|---|----------|---------------|-------------|---------|-------|
| 1 | **CEX→Oracle Lag Directional Taker** | **APPLICABLE** | <500ms | $5–$50/trade | Our current working strategy |
| 2 | **Sum<$1 Complement Arb (single-market)** | **ALREADY KILLED** | <100ms | Small | 0.004-0.13% book-time, ~$125/day gross |
| 3 | **Neg-Risk NO-Basket Conversion Arb** | **NOT** (wrong market type) | Minutes | $100s | Binary Up/Down not neg-risk structure |
| 4 | **Cross-Platform Arbitrage (Polymarket vs Kalshi/options)** | **PARTIAL** | Seconds–minutes | $100–$10k | Different markets, legal friction |
| 5 | **Mint-Sell-Hedge at Sum>$1 (passive LP)** | **PARTIAL** | Seconds | $100+ | When Up+Down ask sum >$1.00; our wallet decode |
| 6 | **Longshot Mispricing / Calibration Edge** | **PARTIAL** | Minutes | $100+ | Applies to near-expiry or near-certain slugs |
| 7 | **Combinatorial Cross-Market Arb** | **PARTIAL** | <1s | Small | Requires correlated markets (we have 3 assets) |
| 8 | **LLM/Superforecaster Directional Bet** | **PARTIAL** | Hours | $50+ | Not arb; directional conviction — limited edge |
| 9 | **Augur Invalid-Outcome Exploit** | **NOT** (Augur-specific) | Hours | $100+ | Augur V2 only, oracle dispute mechanism |
| 10 | **AMM vs CLOB Arb (LMSR/constant-product)** | **NOT** (Poly is CLOB only) | Seconds | $1k+ | Omen/Augur AMMs only, not Polymarket |
| 11 | **Passive Symmetric Maker-Arb (paired bids)** | **ALREADY KILLED** | None | $1k+ | Killed — maker adverse selection |
| 12 | **Dutch Book / Sure-Bet across bookmakers** | **NOT** (jurisdiction) | Minutes | $500+ | Sportsbooks geo-blocked; Kalshi US-only |

---

## 1. CEX→Oracle Lag Directional Taker (Oracle Latency Arbitrage)

### Mechanism
Polymarket Up/Down crypto markets resolve via Chainlink Data Streams oracle, which lags Binance spot price by ~5–20s. An informed trader who observes a decisive Binance price move before the oracle settles can place a directional taker order on Polymarket while the book still reflects the pre-move probability. The edge window = oracle lag − execution latency.

### Requirements
- **Latency**: <500ms order placement from signal to fill; our Ireland VPS is <2ms RTT to Polymarket CLOB (London AWS eu-west-2)
- **Capital**: $1–$50 per trade (bounded by book depth at L25)
- **Infrastructure**: Live Binance WS price feed + Polymarket CLOB WS order book feed + sub-second order placement

### Documented Edge / Returns
- **Our own data (2026-05-28)**: Cyclops S7 composite achieves WR 80.6%, +$0.244/trade after real fees, n=36, p=0.002, G4 CI lower = +$0.022/trade. F2 wallet cluster: 86% WR on 449 trades.
- **PolySwarm paper (arXiv:2604.03888, 2026)**: explicitly models this as "latency arbitrage module — exploiting stale Polymarket prices by deriving CEX-implied probabilities from a log-normal pricing model and executing within the human reaction-time window."
- **Chainlink Data Streams docs**: acknowledges "High-frequency updates let participants act on real-time data"; the lag is a structural design feature (pull-oracle architecture).

### Applicability to Us
**APPLICABLE — this is our primary current edge.** The oracle lag is structural (Chainlink pull model vs Binance push WS). Our Ireland exec box is near-optimal for Polymarket London CLOB. Kills: need directional signal filter (F7 RSI / Cyclops) to avoid adverse selection in flat-market periods. Key risk: Polymarket patches oracle with faster Chainlink push, or competing HFTs crowd the signal.

### Sources
- arXiv:2604.03888 (PolySwarm — latency arb module)
- Our internal: `strategy_lab/reports/MOMO_REST_LAG_VS_MICROSTRUCTURE.md`
- Chainlink Data Streams docs: https://docs.chain.link/data-streams
- `strategy_lab/reports/CYCLOPS_CLONE_SPEC_2026_05_16.md`

---

## 2. Single-Market Complement Arbitrage (Sum < $1 Take-Both)

### Mechanism
On a binary Up/Down CTF market, 1 Up share + 1 Down share = exactly $1 at resolution. If `ask(Up) + ask(Down) < $1.00`, buying both is risk-free profit = $1 − ask(Up) − ask(Down). This is a "lock" or "sure-thing" arb requiring simultaneous execution of both legs.

### Requirements
- **Latency**: <100ms from signal to both fills; opportunities close within 3.6 seconds median (Cheng et al. 2026, NBA markets)
- **Capital**: As small as feasible given book depth (median 14.8 shares per episode in NBA study)
- **Infrastructure**: Simultaneous dual-leg order placement; must account for CLOB matching delay

### Documented Edge / Returns
- **Cheng et al. arXiv:2605.00864 (UCLA, Apr 2026)**: Across 173 NBA games, 75M LOB snapshots, only **7 valid single-market episodes** found, median duration 3.6 seconds. Retail-scale only due to shallow depth.
- **Our own audit**: Sum<$1 exists 0.004–0.13% of book-time on our BTC/ETH/SOL slugs, ~$125/day gross, requires sub-100ms colo, killed.
- **Dubach arXiv:2604.24366 (2026)**: confirms "a sub-50ms median archive-ingestion delay with multi-second tail" — latency matters heavily.

### Applicability to Us
**ALREADY KILLED.** Our own test found it exists rarely and requires faster infrastructure than we have (or want to build). The NBA paper confirms this is the empirical reality on Polymarket broadly. At ~$125/day gross (our measurement), not worth the colo investment.

### Sources
- arXiv:2605.00864 (Cheng, Yang, Zou — UCLA, 2026)
- arXiv:2604.24366 (Dubach — Polymarket microstructure, 2026)
- Our own data: `strategy_lab/reports/MAKER_ARB_CENSORING_REVERSAL_2026_05_28.md`

---

## 3. Neg-Risk NO-Basket Conversion Arbitrage

### Mechanism
Polymarket's Negative Risk (NegRisk) adapter enables capital-efficient trading in **mutually-exclusive multi-outcome** events (e.g., presidential elections with N candidates). The mechanism: holding 1 NO token in each of (N-1) outcomes is equivalent to holding 1 YES + $1 in the remaining outcome. The NegRiskAdapter contract allows converting a basket of NO tokens into the equivalent YES tokens + USDC.

**Arb opportunity**: If the sum of all YES prices < $1.00 (which must be true since exactly one wins), or conversely if the implied NO basket is mispriced vs. a YES equivalent, a conversion arbitrage is possible. The NegRisk vault collects fees from conversions when `feeRate > 0`.

### Requirements
- **Latency**: Minutes (on-chain conversion, no HFT required)
- **Capital**: $100+ across all outcome legs
- **Infrastructure**: Polygon wallet, NegRiskAdapter contract calls, understanding of multi-leg pricing

### Documented Edge / Returns
- **Polymarket neg-risk-ctf-adapter README / docs**: The conversion mechanism is explicitly designed to allow capital-efficient "no" positions. Fee leakage from conversion is the cost.
- **Polymarket docs**: `negRisk: true` flag required on orders; separate contract addresses for the NegRisk exchange.
- No empirical papers specifically quantifying neg-risk conversion arb returns found.

### Applicability to Us
**NOT APPLICABLE.** Our BTC/ETH/SOL Up/Down markets are **standard binary CTF markets** (not neg-risk). The neg-risk structure only applies to mutually-exclusive multi-outcome events (elections, sports winners). Our Up/Down slugs are independent binary markets with no NegRiskAdapter. The mechanism is inapplicable to our market type.

### Sources
- https://docs.polymarket.com/advanced/neg-risk.md
- https://github.com/Polymarket/neg-risk-ctf-adapter (README)
- Polymarket CLOB client SDK docs: `negRisk` parameter

---

## 4. Cross-Platform Arbitrage (Polymarket vs. Kalshi / Options Markets)

### Mechanism
When Polymarket and Kalshi (or CME event contracts, or options-implied probabilities) trade the same event at different prices, a trader can simultaneously buy the "cheap" side on one venue and sell (or hedge) on the other, locking in risk-free profit net of fees and settlement risk.

**Variants**:
- **Polymarket vs. Kalshi**: Same political/economic event traded on both; prices occasionally diverge by 2–5%.
- **Polymarket vs. CEX binary options**: Crypto price prediction on Polymarket vs. Deribit/OKX binary/digital options for the same strike/expiry.
- **Polymarket vs. CEX perpetuals/options implied probability**: Convert option IV to risk-neutral probability and compare to Polymarket price.
- **PolySwarm's approach (arXiv:2604.03888)**: KL-divergence and JS-divergence between LLM-estimated probabilities and Polymarket prices to find "negation pair mispricings."

### Requirements
- **Latency**: Seconds to minutes (not HFT) for political/macro events; faster for crypto price events
- **Capital**: $100–$10k (must leg into both sides, capital locked until resolution)
- **Infrastructure**: Accounts on multiple platforms; Kalshi requires US citizenship/KYC
- **Legal**: Kalshi is CFTC-regulated (US only). Polymarket geo-blocks US users. Cross-arb between them is legally complex for US traders; non-US traders cannot access Kalshi.

### Documented Edge / Returns
- **LessWrong case study (aphyer, 2020)**: PredictIt showed persistent 5–10% mispricings vs. other platforms due to withdrawal fees (5% on profits), position limits ($850/contract), and slow capital movement. These structural frictions prevented arbitrage despite visible price gaps.
- **Vitalik post (2021)**: Augur vs. Polymarket vs. Betfair showed divergences >$0.10 post-election due to liquidity fragmentation and withdrawal delays.
- **PolySwarm (2026)**: "negation pair mispricings" found via KL-divergence engine; no quantified dollar edge reported.

### Applicability to Us
**PARTIAL.** For our specific BTC/ETH/SOL crypto price markets:
- Kalshi lists crypto-price event contracts (monthly/weekly, not intra-hour). Not the same resolution window as our 1m/5m/15m slugs. No direct cross-platform arb.
- CEX options: Deribit BTC options could provide implied probability for daily/weekly price moves, but not for the exact 1m/5m window. Implied vol to binary prob mapping is imprecise.
- Most actionable if Polymarket launches longer-window (daily) crypto price markets matching Deribit strikes.
- **Legal note**: Our exec is Ireland-based; we cannot access Kalshi.

### Sources
- arXiv:2604.03888 (PolySwarm — cross-market KL/JS divergence)
- https://www.lesswrong.com/posts/c3iQryHA4tnAvPZEv/ (PredictIt limits analysis)
- Vitalik: https://vitalik.eth.limo/general/2021/02/18/election.html

---

## 5. Mint-at-Sum>$1 / Sell-One-Leg Strategy (CTF Overpriced Complete Set)

### Mechanism
When `ask(Up) + ask(Down) > $1.00` (book is pricing the complete set above $1 — common due to market-maker spreads), a trader can:
1. **Mint**: Pay $1 USDC → receive 1 Up + 1 Down (gasless, 1:1, no fee)
2. **Sell one leg** at the ask price via CLOB (e.g., sell Up at ask)
3. **Hold the other leg** (Down) as a directional position at an effective entry < $1 − ask(Up)

Or alternatively: sell **both legs** simultaneously into the bids (not asks), netting > $1 if `bid(Up) + bid(Down) > $1` — a rarer version of the sum>$1 arb.

The more aggressive form is **mint-and-sell**: mint a complete set, immediately sell one leg at market, and delta-hedge or hold the other. This is what our decoded wallet wallets (0x9dae874a, 0xa0a50783) appear to do.

### Requirements
- **Latency**: <2s for mint + sell (Polymarket relayer is gasless; execution time is the bottleneck)
- **Capital**: $1–$100 per slug (small denomination per fire)
- **Infrastructure**: Polygon wallet + CTF splitPosition call + CLOB limit/market sell

### Documented Edge / Returns
- **Our internal analysis**: `sum_asks_mean = 1.0128–1.0165` for decoded wallets; consistent book entry above $1. At $2.5 notional, +$0.04 to +$0.41/slug in BOTH_SIDES_PARTIALS regime (n=9-113 slugs/cell). Lifetime PnL on decoded wallets: $568k–$344k (wallets 0xb27bc932, 0xcfb103c3).
- **Maker-arb censoring reversal**: The pure passive "maker-arb" variant (resting paired bids) was killed by adverse selection. The mint+sell variant with directional leg holding is the live candidate.
- **Note**: MINT/MERGE are gasless and exactly 1:1 on Polymarket (Polygon relayer subsidizes gas; confirmed in our fee model verification).

### Applicability to Us
**PARTIAL.** The mint-and-sell variant is our second active candidate (`strategy_lab/reports/MINT_AND_SELL_V2_FULL_REPLICATION_2026_05_16.md`). Edge is real when: (1) directional edge on held leg, (2) sum_asks > $1.005 to cover spread. Pure passive mint+sell without directional filter has near-zero edge (both sides eat into premium). The V2 spec is ready; validate maker rebate status before live deploy.

### Sources
- Our internal: `strategy_lab/reports/MINT_AND_SELL_V2_FULL_REPLICATION_2026_05_16.md`
- Our internal: `strategy_lab/reports/MAKER_ARB_CENSORING_REVERSAL_2026_05_28.md`
- Polymarket CTF splitPosition interface (gasless): https://docs.polymarket.com
- Gnosis Conditional Tokens: https://github.com/gnosis/conditional-tokens-contracts

---

## 6. Longshot Bias / Calibration Mispricing

### Mechanism
Classical prediction-market literature documents "longshot bias" — low-probability outcomes are systematically overpriced (bettors overestimate their probability) and high-probability outcomes are underpriced. Trading the anti-longshot direction (sell overpriced longshots, buy overpriced favorites) has historically yielded positive EV on parimutuel markets (Snowberg & Wolfers 2010) and IEM/TradeSports.

**On Polymarket**: Dubach (2026) confirms the longshot spread premium: median spread ~400 bps in the 0.40–0.60 mid range, climbing to **1,300–1,800 bps** for markets below 0.10. However, the paper argues this is primarily a **liquidity provision constraint** (maker inventory risk on asymmetric binary payoffs), not a behavioural bias — so pure fade-the-longshot trades may not extract alpha.

**Variant for our markets**: Near-expiry BTC/ETH/SOL slugs with extreme prices (e.g., Up at 0.02 when price is 0.5% below strike with 30s left) may be mispriced if the oracle lag means the market hasn't updated to already-settled prices.

### Requirements
- **Latency**: Minutes (passive directional), or seconds (near-expiry oracle lag)
- **Capital**: $10–$500
- **Infrastructure**: Market scanner for probability-range filters; no special infrastructure beyond standard CLOB access

### Documented Edge / Returns
- **Dubach arXiv:2604.24366**: longshot spread premium documented empirically. Not quantified as tradeable alpha.
- **Snowberg & Wolfers (2010)**: "Explaining the Favorite-Longshot Bias" — racetrack/sportsbook evidence. A few percent of stake.
- **Wikipedia / academic consensus**: Longshot bias is real in parimutuel and fixed-odds markets; weaker in CLOB-based prediction markets where arbitrageurs can correct.
- **Our context**: At slug level, near-expiry extreme pricing + oracle lag creates a variant that overlaps with strategy #1.

### Applicability to Us
**PARTIAL.** The classical longshot bias is weak or absent in Polymarket's liquid crypto markets (professional arb corrects it quickly). The near-expiry / oracle-lag variant is already captured under strategy #1. Independent longshot fade without oracle signal is unproven in our setup.

### Sources
- arXiv:2604.24366 (Dubach — longshot spread premium SF1)
- Snowberg & Wolfers (2010): "Explaining the Favorite-Longshot Bias: Is it Risk-Love or Misperceptions?" J. Political Economy
- Wolfers & Zitzewitz (2004): "Prediction Markets" Journal of Economic Perspectives
- Wikipedia: Favourite-longshot bias

---

## 7. Combinatorial / Cross-Market Arbitrage Within Polymarket

### Mechanism
When two related-but-not-identical markets trade on Polymarket simultaneously (e.g., "BTC Up 1m" and "BTC Up 5m" in overlapping time windows, or "BTC Up" and "ETH Up" with high correlation), mispricings in relative prices may emerge. The "middle" strategy: buy in one market at a price that guarantees profit if the other market settles at a different, correlated value.

**Concrete variants**:
- **NBA Moneyline vs. Point Spread combinatorial arb** (Cheng et al.): buy moneyline winner + point spread underdog when combined ask < $1.00 guaranteed payout.
- **Same-asset different-window arb**: BTC Up 1m vs. BTC Up 5m (partially overlapping) — if 1m window result is already observable before 5m resolves, the 5m market is mispriced.
- **Cross-asset correlation fade**: If BTC and ETH Up-Down markets trade at very different implied probs for the same 1-minute window (unusual given high BTC-ETH correlation), fade the divergence.

### Requirements
- **Latency**: <1s for same-asset different-window; minutes for cross-asset
- **Capital**: Varies; up to $500+ for meaningful size
- **Infrastructure**: Multi-market monitoring + simultaneous order execution

### Documented Edge / Returns
- **Cheng et al. arXiv:2605.00864**: 290 combinatorial episodes across 173 NBA games; median return 101 bps per execution; but 76.9% of episodes capped at ~14.8 shares of depth. Total profit small at retail scale.
- **PolySwarm (2026)**: KL/JS divergence scanner for cross-market inefficiencies (not quantified in dollar terms for crypto markets).

### Applicability to Us
**PARTIAL.** For our crypto slugs specifically:
- BTC 5m vs. 1m window: potentially exploitable if 1m result is visible before 5m oracle settles — but this requires the same oracle-lag logic as strategy #1.
- BTC vs. ETH correlation: correlation is high (~0.85 daily) but instantaneous 1-minute returns diverge frequently. Fade trades would require a correlation model and carry execution risk.
- Most promising: same-asset different-window near resolution (already a sub-case of oracle-lag arb). Cross-asset pure correlation trades are speculative.

### Sources
- arXiv:2605.00864 (Cheng et al. — NBA combinatorial arb, 2026)
- arXiv:2604.03888 (PolySwarm — cross-market KL/JS)

---

## 8. LLM / Superforecaster Directional Betting

### Mechanism
Not arbitrage per se, but documented as a systematic edge: aggregating LLM probability estimates (or trained human superforecasters) to identify markets where Polymarket prices deviate significantly from well-calibrated external forecasts, then trading the direction.

- **PolySwarm (2026)**: 50 LLM personas; confidence-weighted Bayesian combination; quarter-Kelly sizing. Outperforms single-model baselines on Brier score.
- **Metaculus / Good Judgment Project**: Human superforecasters historically beat prediction markets on certain slow-moving events (elections 6-12 months out, due to "time preference" bias at Polymarket).

### Requirements
- **Latency**: Hours to days (not real-time arb)
- **Capital**: $50–$5k per trade
- **Infrastructure**: LLM API access or superforecaster subscription; bet sizing model

### Documented Edge / Returns
- **PolySwarm paper**: better calibration than single models; no live PnL reported.
- **Vitalik's election bet**: $308k position earning $56k+ profit betting against Augur market that priced Trump winning at non-trivial probability after the election was called.
- **ACX (Scott Alexander 2022)**: Prediction markets are accurate but not perfectly so; "smart money" edge exists on slow-moving events.
- **Gwern.net**: Historical personal betting records; positive EV on IEM and Intrade when markets showed clear miscalibration.

### Applicability to Us
**PARTIAL** for crypto price slugs (weak). LLM/superforecaster edge applies to slow events (politics, macro) — not to 1m/5m BTC price resolution where crypto volatility dominates. However, for longer-term Polymarket crypto markets (e.g., "BTC above $100k by year-end"), this approach is valid. Our current 1m/5m/15m up-down slugs resolve too fast for external forecasting to add value beyond CEX signal.

### Sources
- arXiv:2604.03888 (PolySwarm — LLM forecasting framework)
- Vitalik: https://vitalik.eth.limo/general/2021/02/18/election.html
- ACX: https://www.astralcodexten.com/p/prediction-market-faq
- Gwern: https://gwern.net/prediction-market

---

## 9. Augur "Invalid" Outcome Exploit / Oracle Dispute Arbitrage

### Mechanism
Augur V2 has a dispute mechanism where holders of REP token can challenge market resolutions. The "Invalid" outcome is a pre-defined resolution for ambiguous markets. A trader who knows (or suspects) a market will resolve "Invalid" can buy ITRUMP/INVALID tokens cheaply before the dispute.

A separate exploit: buying a minority position in the intended "wrong" outcome before a dispute, then buying enough REP to influence the dispute resolution toward that outcome (a 51%-style attack on the oracle). High capital requirement; documented theoretically.

### Requirements
- **Latency**: Hours to days
- **Capital**: Large (REP holdings for oracle influence); retail: just buy INVALID tokens cheaply
- **Infrastructure**: REP staking, Augur dispute system knowledge

### Documented Edge / Returns
- **Vitalik (2021)**: ITRUMP stayed <$0.02 throughout the post-election period despite theoretical attack possibility. Rational actors chose not to attack because expected attack cost > expected gain.
- **Augur documentation**: Dispute mechanism is designed to prevent oracle manipulation; requires >50% of REP staked to successfully challenge.

### Applicability to Us
**NOT APPLICABLE.** Augur-specific. Our markets use Polymarket's UMA CTF adapter with Chainlink Data Streams — no on-chain dispute mechanism. Oracle is the Chainlink pull feed, not a REP-voting system.

### Sources
- Vitalik: https://vitalik.eth.limo/general/2021/02/18/election.html (ITRUMP section)
- Wikipedia: https://en.wikipedia.org/wiki/Augur_(software)

---

## 10. AMM-vs-CLOB Arbitrage (LMSR / Constant-Product Prediction Markets)

### Mechanism
Early prediction markets (Augur V1, Gnosis Omen) used Automated Market Makers — specifically LMSR (Logarithmic Market Scoring Rule) or constant-product formulas — where any trade moves the price along a deterministic curve. An AMM price can diverge from the efficient CLOB price, enabling an arbitrageur to buy cheap on the AMM and sell on a CLOB (or vice versa).

The LMSR has a bounded loss guarantee for the operator (subsidized market making), making it common for thin markets. An informed trader can systematically extract value from the LMSR by trading against it when its prices lag external information.

### Requirements
- **Latency**: Seconds to minutes (blockchain confirmation time)
- **Capital**: Varies; LMSR pool size determines available depth
- **Infrastructure**: Ethereum/Polygon wallet + AMM contract interaction

### Documented Edge / Returns
- **Paradigm AMM writeup (2021)**: Quantifies price impact and frontrunning on Uniswap-style AMMs. Applies conceptually to prediction market AMMs.
- **Academic literature**: LMSR arbitrage is well-studied (Othman et al. 2013 "A Practical Liquidity-Sensitive Automated Market Maker") — liquidity parameter b controls loss bound and price sensitivity.
- **Omen**: Used constant-product AMM for prediction markets; active arb community exploited oracle-lagged prices.

### Applicability to Us
**NOT APPLICABLE.** Polymarket is a pure CLOB. No AMM component. This strategy requires an AMM venue. If Polymarket ever integrates an AMM liquidity pool, this becomes relevant.

### Sources
- Paradigm: https://www.paradigm.xyz/2021/08/understanding-automated-market-makers-part-1-price-impact
- Othman et al. (2013): "A Practical Liquidity-Sensitive Automated Market Maker" — ACM EC 2013
- Wikipedia market maker entry (LMSR reference)

---

## 11. Passive Symmetric Maker-Arb (Resting Paired Bids Summing <$1)

### Mechanism
Rest passive limit orders: `bid(Up) + bid(Down) < $1`. If both fill, lock in risk-free profit = $1 − bid(Up) − bid(Down). In theory, this is a passive version of the sum<$1 arb requiring no speed advantage.

### Requirements
- **Latency**: None (passive resting orders)
- **Capital**: Small ($1–$100 per pair)
- **Infrastructure**: Order placement API, monitoring for fill events

### Documented Edge / Returns / Risks
- **Our internal testing**: Net-negative across all sleeves. Root cause = adverse selection: when markets move enough that both bids fill (the condition for profit), the market has usually moved strongly in one direction — meaning the "losing" leg is worth near-zero on resolution, not $0.50. Censoring: right-censored (losers never get REDEEM) masked this; uncensored truth is −$0.41 to −$3.63/slug.
- **Cheng et al. (2026)**: Passive symmetric strategy not tested, but their finding that single-market arb lasts 3.6s before closure implies passive resting orders would only fill when one side is toxic.

### Applicability to Us
**ALREADY KILLED.** Internal audit confirms net-negative. Adverse selection dominates. CLOB informed traders pick off the favorable leg before the other fills, leaving a one-sided adverse position.

### Sources
- Our internal: `strategy_lab/reports/MAKER_ARB_CENSORING_REVERSAL_2026_05_28.md`
- Our internal: `strategy_lab/reports/CLEAN_SETTLED_AUDIT_2026_05_28.md`

---

## 12. Dutch Book / Sure-Bet Across Bookmakers

### Mechanism
A Dutch book (or "sure bet" / "arb bet") exists when the sum of reciprocal odds across all outcomes on different platforms sums to < 1.0 — i.e., betting on all outcomes on different platforms guarantees profit regardless of result.

For binary markets: if Polymarket offers Up at 0.55 and a sportsbook offers Down (equivalent) at 0.48, combined cost = $1.03 → slight loss. If Polymarket offers Up at 0.52 and sportsbook offers Down at 0.51, combined cost = $1.03. Rare condition where both sides are below fair (sums < 1.00) across different venues.

### Requirements
- **Latency**: Minutes (must place bets before odds change)
- **Capital**: $500–$10k
- **Infrastructure**: Multiple platform accounts; currency conversion; geo-restrictions

### Documented Edge / Returns
- **Wikipedia Dutch book**: Classically documented in horse racing and football betting. Margin sportsbooks maintain ensures sum > 1; rare cross-book discrepancies exist 0.1–0.5% of events.
- **Prediction market specific**: PredictIt vs. Polymarket mispricings historically 2–5% but eaten by PredictIt's 5% withdrawal fee and $850 position limits (LessWrong analysis).

### Applicability to Us
**NOT APPLICABLE.** Sportsbooks covering BTC/ETH/SOL price events are rare and geo-blocked in Ireland. Kalshi is US-only. Betfair does not list intra-hour crypto price markets. There is no practical counterpart venue for our 1m/5m/15m resolution slugs.

### Sources
- https://en.wikipedia.org/wiki/Dutch_book
- LessWrong: https://www.lesswrong.com/posts/c3iQryHA4tnAvPZEv/ (PredictIt friction analysis)

---

## 13. CTF Collateral / Redemption Arbitrage (Post-Resolution)

### Mechanism
After a market resolves, winning tokens trade at exactly $1.00 and losing tokens at $0.00. If there is any delay in the oracle settling the result vs. the CLOB price updating, winning tokens may still trade below $1.00 — buyable for $0.95 and redeemable at $1.00 after the oracle confirms.

Variant: "Resolution frontrunning" — buying winning tokens just before the oracle settles when outcome is knowable (e.g., from Chainlink price feed) but Polymarket has not yet settled.

### Requirements
- **Latency**: Seconds to minutes (before oracle settlement propagates to CLOB)
- **Capital**: $1–$1k per market
- **Infrastructure**: Oracle monitoring + CLOB order placement

### Documented Edge / Returns
- **Our oracle lag data**: Chainlink settles 5–20s after Binance price. During this window, CLOB is still trading. If the outcome is clear (price far from strike), buying the winning token during the lag window is essentially free money.
- This is a special case of strategy #1 (oracle lag directional taker) — specifically the "sure outcome" sub-case (not directional, but risk-free when outcome is locked).

### Applicability to Us
**APPLICABLE** (sub-case of strategy #1). When BTC/ETH/SOL price at window-end is decisively above/below strike and Chainlink hasn't settled yet, the winning token is buyable below $1. Our current directional strategy already captures this sub-case. The pure "near-certain" filter (price > 3σ from strike with 5s left) could be separated as a standalone sub-strategy with near-zero directional risk.

### Sources
- Our internal: `CLAUDE.md` ("Outcome resolution = Chainlink Data Streams. Chainlink lags Binance spot by ~5-20s")
- arXiv:2604.03888 (PolySwarm — latency arb module)

---

## 14. Negation Pair (Up + Down) Mispricing via Information Asymmetry

### Mechanism
On any binary market, `price(Up) + price(Down) = 1` in a frictionless market (no-arbitrage). When `price(Up) + price(Down) ≠ 1` at mid prices, one side is "expensive" and the other is "cheap" relative to the no-arb constraint. A trader with an informational edge (e.g., knowing the oracle's current input) can:
1. Buy the underpriced token (cheap side)
2. Simultaneously short the overpriced token (synthetic short via mint+sell)

The PolySwarm paper uses Jensen-Shannon divergence between the two sides as a signal for "negation pair mispricings."

### Requirements
- **Latency**: <500ms
- **Capital**: $1–$50 per trade
- **Infrastructure**: Dual-leg simultaneous execution, oracle price feed

### Documented Edge / Returns
- **Dubach (2026)**: median `price(Up) + price(Down)` at mid is approximately 1.00 for liquid markets (median effective half-spread ~0 once direction inference is corrected). Deviations exist but are small and brief.
- **PolySwarm (2026)**: JS divergence scanner identifies these — no dollar PnL disclosed.

### Applicability to Us
**PARTIAL.** When the oracle is lagging and the real-world outcome is directionally clear, `price(Up) + price(Down)` diverges from 1.00 because informed traders are buying one side. This is exactly the oracle-lag signal — already captured in strategy #1. As an independent strategy (without oracle signal), the negation pair mispricing is too small and brief to trade profitably given our fees.

### Sources
- arXiv:2604.03888 (PolySwarm — negation pair mispricings)
- arXiv:2604.24366 (Dubach — spread decomposition showing near-zero adverse selection)

---

## 15. Settlement / Resolution Dispute Arbitrage (UMA / Kleros Oracles)

### Mechanism
Some prediction markets use dispute-resolution oracles (UMA, Kleros, Augur REP) where a contested outcome goes to a decentralized arbitration process. If the "correct" outcome differs from the current market price during the dispute window, a sophisticated trader can buy the mispriced side cheaply and profit when the dispute resolves correctly.

This requires: (a) understanding the legal/factual merits of the dispute, (b) ability to hold through resolution timeline (days to weeks), (c) possibly staking to influence the outcome.

### Requirements
- **Latency**: Days to weeks
- **Capital**: $100–$10k per dispute
- **Infrastructure**: Oracle dispute system knowledge; UMA/REP staking

### Documented Edge / Returns
- **Vitalik (2021)**: ITRUMP at $0.02 during post-election Augur dispute window = potential 50x if dispute resolved "Invalid." Nobody took it at scale due to capital lock-up + attack uncertainty.
- **No systematic quantified returns found** for this strategy.

### Applicability to Us
**NOT APPLICABLE (currently).** Polymarket's BTC/ETH/SOL price markets use Chainlink Data Streams oracle (pull-based, deterministic, no human dispute). There is no dispute mechanism for the crypto price resolution. However, if Chainlink feed malfunctions or a market resolves ambiguously, UMA adapter could trigger a dispute — rare edge case only.

### Sources
- Vitalik: https://vitalik.eth.limo/general/2021/02/18/election.html
- Polymarket UMA CTF Adapter: https://github.com/Polymarket/uma-ctf-adapter

---

## 16. Temporal Arbitrage: Pre-Market vs. In-Market Price Gaps

### Mechanism
Before a market opens for trading (or in the first few seconds of a slug when liquidity is thin), mispricing is possible if: (a) informed traders have not yet moved the price, (b) automated market makers haven't arrived. Buying at stale opening prices before the market efficiently reflects new information.

**Specific to our setup**: Each new BTC/ETH/SOL slug opens at some default price (likely carried from prior slug's settlement or neutral 0.50). If there is already directional information (Binance price trending strongly), the opening price may lag reality.

### Requirements
- **Latency**: <1s from slug creation to first trade
- **Capital**: $1–$20 per slug
- **Infrastructure**: Slug creation monitoring + immediate order placement

### Documented Edge / Returns
- No papers specifically quantify slug-opening mispricing on Polymarket's crypto price markets.
- **Our internal observation**: `ws_s` convention — production fires at `ws_s + 120s` (v1) or `ws_s + 60s` (v2) after slug start. The slug has been trading for 60-120s before we fire. Opening price mispricing window may be earlier than our current fire timing.

### Applicability to Us
**PARTIAL.** Worthy of empirical investigation: scan for systematic price drift in the first 30s of each slug vs. Binance signal. If slugs open at 0.50 regardless of Binance trend, this is exploitable. Requires modifying fire logic to target slug-open rather than ws_s anchor.

### Sources
- Our internal: `CLAUDE.md` (ws_s convention, slug start timing)
- arXiv:2604.24366 (Dubach — no time-to-close effect found on depth, but does not analyze opening-price drift)

---

## Additional Academic Background: Prediction Market Efficiency

### General Findings (Academic Consensus)
- **Wolfers & Zitzewitz (2004, JEP)**: Prediction markets are well-calibrated for events with many independent traders; thin/short-window markets show more mispricing.
- **Snowberg & Wolfers (2010)**: Longshot bias in parimutuel markets = ~2-3% of stake. Smaller in CLOB markets.
- **Cheng et al. (2026, arXiv:2605.00864)**: Polymarket NBA markets "demonstrate profound microstructural efficiency" — single-market arb rare (7 episodes / 173 games), combinatorial arb limited to retail scale by liquidity.
- **Dubach (2026, arXiv:2604.24366)**: 8 stylized facts of Polymarket microstructure; near-zero adverse selection in liquid markets; longshot spread premium = liquidity constraint, not behavioural bias.
- **LessWrong case study (2020)**: PredictIt's structural frictions (5% withdrawal fee, $850 position limits) explain persistent mispricings that cannot be arbitraged. Frictionless markets (Polymarket) are more efficient.
- **Vitalik (2021)**: Augur post-election = case study in limits-to-arb: rational arb existed ($0.52 → $1.00 NTRUMP) but barriers (capital lock-up, technical complexity, smart contract risk) prevented full correction for weeks.

---

## Key Surprising Findings

1. **Polymarket microstructure is highly efficient for liquid markets** (Dubach 2026): median effective half-spread ≈ 0; adverse selection ≈ 0 once direction inference is corrected. The book looks efficient. **This means pure passive arb is nearly impossible — only information asymmetry (oracle lag) works.**

2. **Combinatorial arb is empirically bounded at retail scale** (Cheng et al. 2026): Even when 290 combinatorial arb episodes exist across 173 NBA games, 76.9% are capped at ~14.8 shares due to book shallowness. Our BTC/ETH/SOL markets are less liquid than NBA markets = even harder.

3. **Neg-risk conversion does NOT apply to our market type**: Our Up/Down binary CTF markets are standard binary (not neg-risk multi-outcome). The sophisticated neg-risk converter arbitrage that some Polymarket docs describe is irrelevant to us.

4. **The oracle latency arb (strategy #1) has an academic parallel** confirmed in PolySwarm (2026): CEX-implied probability vs. Polymarket price divergence during the human reaction-time window is a documented, named strategy — our approach is academically grounded.

5. **Trade direction inference from Polymarket's public WS feed is only ~59% accurate** (Dubach 2026): on-chain OrderFilled events are the only reliable ground truth. This explains why naive orderbook-based backtests of market-making strategies can be systematically wrong.

---

## Sources Index

| Source | URL / Reference |
|--------|----------------|
| Polymarket Negative Risk docs | https://docs.polymarket.com/advanced/neg-risk.md |
| Neg-Risk CTF Adapter GitHub | https://github.com/Polymarket/neg-risk-ctf-adapter |
| Polymarket documentation index | https://docs.polymarket.com/llms.txt |
| arXiv:2605.00864 (Cheng et al.) | https://arxiv.org/abs/2605.00864 — NBA combinatorial arb |
| arXiv:2604.24366 (Dubach) | https://arxiv.org/abs/2604.24366 — Polymarket microstructure |
| arXiv:2604.03888 (PolySwarm) | https://arxiv.org/abs/2604.03888 — LLM + latency arb |
| Vitalik election post (2021) | https://vitalik.eth.limo/general/2021/02/18/election.html |
| Vitalik info finance (2024) | https://vitalik.eth.limo/general/2024/11/09/infofinance.html |
| ACX Prediction Market FAQ | https://www.astralcodexten.com/p/prediction-market-faq |
| LessWrong PredictIt limits | https://www.lesswrong.com/posts/c3iQryHA4tnAvPZEv/ |
| Zvi: When Do Markets Work? | https://thezvi.wordpress.com/2018/07/26/prediction-markets-when-do-they-work/ |
| Gwern prediction markets | https://gwern.net/prediction-market |
| Wikipedia: Prediction market | https://en.wikipedia.org/wiki/Prediction_market |
| Wikipedia: Dutch book | https://en.wikipedia.org/wiki/Dutch_book |
| Wikipedia: Augur | https://en.wikipedia.org/wiki/Augur_(software) |
| Paradigm AMM writeup | https://www.paradigm.xyz/2021/08/understanding-automated-market-makers-part-1-price-impact |
| Snowberg & Wolfers (2010) | "Explaining the Favorite-Longshot Bias" J. Political Economy |
| Wolfers & Zitzewitz (2004) | "Prediction Markets" J. Economic Perspectives |
| Chainlink Data Streams | https://docs.chain.link/data-streams |
