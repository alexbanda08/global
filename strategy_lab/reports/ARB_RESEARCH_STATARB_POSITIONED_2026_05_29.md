# Statistical & Positioned / Relative-Value Arbitrage: Catalog and Applicability to Polymarket Binary Up-Down Markets

**Date:** 2026-05-29  
**Scope:** External research synthesis — statistical arb, positioned/sequential arb, convergence trades, relative-value strategies. Mapped to our BTC/ETH/SOL Polymarket up-down binary setup.

---

## Summary Table (ranked by applicability)

| # | Strategy | Applicability | Key Reason |
|---|----------|--------------|------------|
| 1 | Oracle-Lag / CEX→Chainlink Lead-Lag Taker | **APPLICABLE (working candidate)** | Chainlink lags Binance 5-20s; directional taker capitalizes the known stale oracle |
| 2 | Model Fair Value vs Poly Price (Implied Prob Arb) | **APPLICABLE (new)** | BSM N(d2) or log-normal gives P(up) from Binance vol; trade when Poly price deviates |
| 3 | ETF Creation/Redemption ↔ Mint/Merge Arb | **APPLICABLE (structural analog, execution barrier)** | MINT $1→(Up+Down), MERGE (Up+Down)→$1 is identical to ETF in-kind creation/redemption; exploit Up+Down≠$1 |
| 4 | Funding-Rate / Perp-Spot Delta-Neutral | **PARTIAL** | Binance BTC perp funding readable; no direct Poly leg but signals sentiment skew useful |
| 5 | Cross-Slug / Term-Structure (Calendar) Arb | **PARTIAL** | Same strike, adjacent windows (1m/5m/15m) should imply consistent P; divergences tradeable |
| 6 | Pairs / Cointegration (Cross-Asset Poly) | **PARTIAL** | BTC-Up and ETH-Up are correlated; cointegration-based spread between them possible but thin books |
| 7 | Volatility Arb (Realized vs Implied Poly Vol) | **PARTIAL** | Poly price ≈ risk-neutral P; calibrate implied vol back from price, trade vs GARCH/HV forecast |
| 8 | Convergence / On-the-Run Off-the-Run | **NOT** | Requires liquidity premium dynamics; Poly slugs are independent markets, no on-run/off-run structure |
| 9 | Cross-Sectional StatArb (Factor Model) | **NOT** | Requires large portfolio of correlated securities; 3 assets × 3 timeframes = 9 markets, too small |
| 10 | Index Arbitrage | **NOT** | No index product over Poly markets exists |
| 11 | Basis Trade / Cash-and-Carry | **NOT** | Poly binary is not a deliverable forward; no futures leg available |
| 12 | Merger / Risk Arbitrage | **NOT** | Event-driven; crypto up-down slug is not a corporate event |
| 13 | Symmetric Market-Neutral Maker Arb | **ALREADY KILLED** | Tested: net-negative after adverse selection; see MAKER_ARB_CENSORING_REVERSAL report |
| 14 | Positioned/Sequential Maker Arb (leg-in) | **ALREADY KILLED** | Tested: −$0.03/share; adverse selection mechanism documented below |

---

## 1. Pairs Trading & Cointegration

### Mechanism
Pioneered at Morgan Stanley mid-1980s by Nunzio Tartaglia's quant group. Identify two securities sharing a long-run equilibrium (cointegrated I(1) series). Spread = log(A) − β·log(B) is stationary (ADF test confirms I(0)). When spread z-score exceeds ±1.5–2σ: go short outperformer, long underperformer. Exit at mean-reversion (z→0). Hedge ratio β from Engle-Granger or Johansen cointegration.

**Key math:** If X,Y ~ I(1) and ∃β s.t. X − βY ~ I(0), they are cointegrated (Engle & Granger 1987). The stationary residual drifts back to zero with half-life = −ln(2)/λ where λ = mean-reversion speed from AR(1) fit.

### Capital / Infra / Latency
- Capital: proportional to two-sided position size; market-neutral so no directional capital at risk
- Infra: real-time price feeds, cointegration monitoring, z-score computation
- Latency: seconds to minutes; not an HFT strategy

### Documented Edge/Returns
- Morgan Stanley group earned ~$50M/year 1987–1989 before strategy crowded
- Academic studies (Gatev, Goetzmann, Rouwenhorst 2006, *Review of Financial Studies*): ~11% excess annual return on 20-day trading rule, pre-costs; declined post-2002 as strategies proliferated
- Crypto pairs: some evidence of cointegration between BTC/ETH at hourly timescales

### Applicability to Our Setup
**PARTIAL.** The analog: BTC_Up Poly price and ETH_Up Poly price on same timeframe should correlate (both driven by correlated underlying moves). A divergence — e.g. BTC_Up=0.60 but ETH_Up=0.45 on same 5m window, when BTC/ETH correlation is high — implies one is mispriced. Structural problems:
1. **No short-sell of Poly shares** without holding inventory; can only buy (long). To short, must hold the other side or use MERGE.
2. **Convergence is not guaranteed within slug lifetime** — slugs expire in minutes; if cointegration reverts slowly, trade can expire before convergence.
3. **Thin books** — L25 shows BTC books at ~$25 depth; simultaneous execution of two legs is costly.
Best use: signal filter. If BTC_Up diverges sharply from ETH_Up (given corr), flag as potential mispricing worth trading directionally.

**Sources:** Engle & Granger (1987) *Econometrica*; Gatev et al. (2006) *Rev. Financial Studies*; Wikipedia Pairs Trade; QuantInsti Pairs Trading Basics.

---

## 2. Mean-Reversion / Ornstein-Uhlenbeck Process

### Mechanism
The OU (Ornstein-Uhlenbeck) process is the continuous-time AR(1): dX_t = θ(μ − X_t)dt + σdW_t, where θ = mean-reversion speed, μ = long-run mean, σ = vol. The process reverts to μ with half-life = ln(2)/θ. Trading signal: when X_t >> μ, sell; when X_t << μ, buy. Optimal entry/exit thresholds derived by Avellaneda & Lee (2010) to maximize Sharpe. Applied to spread between correlated instruments (spread is the OU process).

**Key insight:** the Sharpe of an OU-based strategy scales as √(2θ/π) × (μ_spread/σ_spread) — faster reversion and higher signal-to-noise ratio improve performance.

### Capital / Infra / Latency
- Capital: long-short, market-neutral; capital ~ 2× notional per pair
- Infra: rolling regression, half-life estimation, real-time z-score
- Latency: generally seconds-to-minutes; HFT OU strategies need sub-ms

### Documented Edge/Returns
- Avellaneda & Lee (2010): ETF-based OU stat-arb on US equities, Sharpe ~1.5–2 before 2008, degraded after
- Crypto: BTC spot–perp spread shows OU behavior with θ ≈ 0.1–0.5/hour

### Applicability to Our Setup
**PARTIAL.** The Poly price of a given series (e.g. BTC_5m) across consecutive slugs does not form a stationary OU process — each slug is a new market resolving independently. However:
1. **Intra-slug reversion**: within a single slug lifetime (5m), if a price spike to 0.80 is driven by a large order, it may mean-revert as the book refills. This is a microstructure mean-reversion play, not OU in the classical sense.
2. **Cross-slug relative value**: if BTC_5m slug at t=T prices Up at 0.72 but BTC vol and price are unchanged from t=T-5m where Up priced at 0.55, the new slug is likely stale/mispriced.
**Not a standalone strategy** given slug independence. Better used as a filter within the directional oracle-lag strategy.

**Sources:** Ornstein & Uhlenbeck (1930); Wikipedia OU process; Avellaneda & Lee (2010) *Quantitative Finance*.

---

## 3. Statistical Arbitrage (Cross-Sectional, Factor-Based)

### Mechanism
Bottom-up, beta-neutral strategy using statistical signals across a large cross-section of securities (hundreds+). Each security's return is decomposed into factor exposures (market, sector, style) + idiosyncratic residual. StatArb trades the idiosyncratic residuals, going long stocks with negative residuals (expected to revert up) and short stocks with positive residuals. Signals include momentum, reversal, earnings surprise, short-term mean reversion.

Pioneered at Morgan Stanley (Bamberger/Tartaglia 1985), later Renaissance Technologies, D.E. Shaw. Modern cross-sectional stat arb uses thousands of stocks, sub-second execution.

### Capital / Infra / Latency
- Capital: large portfolios ($100M+) to diversify idiosyncratic risk
- Infra: factor model, PCA, real-time feeds for hundreds of securities
- Latency: varies; intraday stat arb needs sub-second; daily rebalance needs less

### Documented Edge/Returns
- Khandani & Lo (2007): "Quant meltdown" of Aug 2007 revealed widespread stat-arb crowding — $1T in stat-arb positions in US equities; typical Sharpe 1.5–3 before crowding
- Persistence of returns has declined as strategy became mainstream; edge concentrated in harder-to-access signals

### Applicability to Our Setup
**NOT directly applicable.** We have 9 markets (BTC/ETH/SOL × 1m/5m/15m). Cross-sectional stat arb requires large N to diversify; 9 is not enough. Factor model has no natural structure across Poly prediction markets that differ from traditional equity factors.
Conceptual value: the **residual decomposition** idea is useful — model each Poly price as (macro factor) + (asset-specific factor) + (slug-specific noise). Trade slug-specific noise mean-reversion. But this is absorbed into the model-fair-value strategy (#12 below).

**Sources:** Wikipedia Statistical Arbitrage; Khandani & Lo (2007) *J. Investment Management*; Morgan Stanley history.

---

## 4. Basis Trade / Cash-and-Carry (Spot-Futures)

### Mechanism
Exploits the basis: difference between spot price and futures price. In cost-of-carry framework: F = S × e^(r−q)T where r = risk-free rate, q = convenience yield/dividend yield. If F > fair value: sell futures, buy spot (cash and carry). If F < fair value: buy futures, sell spot (reverse cash and carry). Profit = (F − S×e^(r−q)T) converging to zero at expiry.

**Crypto basis trade**: Buy BTC spot, sell BTC quarterly futures at premium → collect the "basis" (annualized premium that historically ran 5-30% in bull markets). Carry risk: forced unwinding during spot rallies where basis widens before converging.

### Capital / Infra / Latency
- Capital: held for futures lifetime (days–months); requires margin on futures leg
- Infra: cross-exchange connectivity (spot + derivatives exchange)
- Latency: not time-critical; entry/exit at identified mispricings

### Documented Edge/Returns
- Crypto basis trade: Deribit/CME Bitcoin futures basis 5–30% annualized in 2020–2021; narrowed to 5–10% post-FTX collapse
- Treasury basis trade: well-known hedge fund strategy; LTCM collapse 1998 a famous failure due to leverage and liquidity crunch

### Applicability to Our Setup
**NOT directly applicable.** Poly binary slugs have no deliverable spot; there is no futures contract referencing Poly binary prices. The math doesn't transfer. However, conceptually the **Chainlink oracle as "synthetic settlement future"** is analogous — the oracle price at expiry is the known settlement, and Poly price should converge to 0 or 1 at expiry. This is trivially true and not tradeable.

**Sources:** Wikipedia Basis Trading; Wikipedia Convergence Trade; CME Group fair value formula.

---

## 5. Funding-Rate Arbitrage (Perpetual-Spot)

### Mechanism
Crypto perpetual futures (perps) have no expiry. To peg perp price to spot, exchanges use a **funding rate** mechanism: every 8 hours, longs pay shorts (positive funding, perp > spot) or shorts pay longs (negative funding, perp < spot). The funding rate ≈ premium_index × clamp(0.1%, ..., -0.1%).

**Strategy:** When funding rate is persistently positive (market bullish), take delta-neutral position: long spot BTC + short BTC perp. Collect funding payments (income) while being price-hedged. Risk: funding rate regime change; liquidation risk on leveraged perp.

**Published returns:** Binance BTC perp funding averaged +0.01% to +0.05% per 8h in bull markets (≈ 4–22% annualized). Glassnode/Coinglass data shows funding spiked to 0.1%/8h ($365/year per $1000 notional) in Jan 2021.

### Capital / Infra / Latency
- Capital: 2× notional (spot + margin for short perp)
- Infra: Binance spot + perp API; funding rate monitor
- Latency: entry within hours of rate appearing; not HFT

### Documented Edge/Returns
- ~5–30% annualized in bull markets; compresses in bear/neutral markets
- Risk: negative funding in bear market (longs receive funding, shorts pay — reverse carry)

### Applicability to Our Setup
**PARTIAL as signal, not direct strategy.** We cannot take a perp-spot arb position in Poly markets. However:
1. **Funding rate as sentiment signal**: Persistent high positive funding = market is net long BTC = bulls paying bears. This structurally implies Binance price has an upward drift component from leveraged longs. A systematic rule: high-positive-funding → slightly favor Up on BTC slugs? This is weak but documentable.
2. **Basis between Binance spot and Binance perp mark price**: if perp > spot (positive basis), market expects continuation — an additional input to the directional model.
3. **Not a Poly-native strategy** — funding payments occur on Binance perp, not on Poly.

**Sources:** Wikipedia Perpetual Futures; Binance funding rate documentation; Coinglass funding rate data.

---

## 6. Index Arbitrage & ETF Creation/Redemption ↔ Mint/Merge

### Mechanism

**ETF creation/redemption:** Authorized Participants (APs) deliver a basket of underlying stocks in exchange for ETF shares (creation) or redeem ETF shares for the basket (redemption). If ETF trades at a premium to NAV, APs buy the basket + deliver → create ETF shares → sell at premium → pocket spread. If at discount, redeem ETF → get basket → sell. This arbitrage keeps ETF ≈ NAV continuously. APs work in creation unit blocks (~50,000 shares). (Wikipedia ETF Arbitrage Mechanism)

**Polymarket analog (structural isomorphism):**
- ETF basket ↔ (Up share + Down share) complete set
- ETF creation ↔ MINT: pay $1 USDC → receive 1 Up + 1 Down (gasless, 1:1)
- ETF redemption ↔ MERGE: return 1 Up + 1 Down → receive $1 USDC (gasless, 1:1)
- ETF NAV ↔ $1 (always; Up + Down always sum to exactly $1 at redemption)
- Premium/discount ↔ (Up_price + Down_price − $1): if sum > $1 → MERGE to earn premium; if sum < $1 → MINT then sell at premium

**The sum-≠-$1 arb in practice:**
- If Up=0.55, Down=0.48 → sum=1.03 → buy set cheaply ($1 via MINT), sell both for $1.03, profit $0.03 before gas
- If Up=0.55, Down=0.43 → sum=0.98 → buy Up at 0.55 + Down at 0.43, MERGE for $1, profit $0.02
- This is "true" arbitrage (risk-free at expiry or instantaneous via merge) in theory

**Why it was killed for us:** After taker fees (2% on winning leg) and execution risk (must fill both legs simultaneously at quoted prices), the net PnL turns negative unless the sum deviation > ~2% and you can fill both legs at posted prices. With thin L25 books (Up and Down depth both ~$25), the larger order moves the book and the arb disappears before full fill.

### Capital / Infra / Latency
- Capital: $1 per round trip (MINT→MERGE); costs: gas=0 (Polymarket gasless), taker fee 2% on profit
- Infra: real-time monitoring of Up+Down sum across all active slugs; simultaneous CLOB fills
- **Latency: critical.** Must buy Up + Down atomically or near-atomically. If Up is filled first and Down price moves, leg-2 is at risk → adverse selection. Near-colo needed (<10ms round trip) to minimize exposure window.

### Documented Edge/Returns
- ETF arb: APs earn 1–5 bps per round trip on large block sizes; competitive among APs
- Poly sum-arb: our own backtest found sum deviation >$0.02 occurs rarely; after fees net-negative at our scale
- **Already killed for symmetric version.** Asymmetric sum-arb (one-sided) still theoretically possible if the sum deviates significantly enough.

### Applicability to Our Setup
**APPLICABLE (structural analog) but execution-barrier.** The isomorphism with ETF creation/redemption is exact. The practical barrier is:
1. **Fee drag**: 2% on winning leg eats ~$0.01–0.02 on a $0.50 trade = 2–4% of notional
2. **Execution risk**: books are thin; can't buy both legs simultaneously without moving price
3. **Latency**: Ireland VPS at ~2ms to Poly CLOB; far from US East origin traders at ~130ms — we have an edge in UK/EU but not vs colo

The structural analog is powerful for understanding: **any persistent sum ≠ $1 beyond fees + latency represents a real arb**. If books get deeper or fees decrease, this becomes live.

**Sources:** Wikipedia ETF creation/redemption mechanism; CLAUDE.md (canonical fee model verification); MAKER_ARB_CENSORING_REVERSAL_2026_05_28.md.

---

## 7. Lead-Lag / Cross-Venue Price Discovery

### Mechanism
When the same information is incorporated into multiple markets at different speeds, the faster market "leads" and the slower "lags." Trading the lag: monitor the fast market, project the lagged market's fair value, trade the laggard before it incorporates the information.

**Academic basis:**
- Hasbrouck (1995): "Information Shares" framework — the market with the highest share of the common efficient price innovation is the leader
- de Jong & Schotman (2010): intraday lead-lag between large-cap and small-cap stocks; large-cap leads
- Budish, Cramton & Shim (2015, *QJE*): HFT "arms race" for lead-lag — latency arbitrage tax = 0.42bps of trading volume; $5B/year globally in equity markets

**CEX → Oracle lag (our specific case):**
- Binance spot BTC price is the fastest, highest-liquidity venue
- Chainlink Data Streams (RTDS) ingests Binance price with ~5–20s processing + publish delay
- Poly slug resolution uses Chainlink settlement price at slug_end
- **Edge:** Binance price at T+0 predicts Chainlink price at T+[5-20s]; if Poly slug expires in that window, directional taker on Poly at T+0 captures the lag

**PolySwarm (arXiv 2604.03888, 2026):** independently confirms the same structure: "A latency arbitrage module exploits stale Polymarket prices by deriving CEX-implied probabilities from a log-normal pricing model and executing trades within the human reaction-time window."

### Capital / Infra / Latency
- Capital: per-trade sizing; limited by Poly book depth (~$25 L25)
- Infra: Binance 1s/WS feed + Chainlink RTDS stream + Poly CLOB WS
- **Latency: competitive advantage is critical.** Ireland VPS ~2ms to Poly CLOB vs US East ~130ms. Sub-second execution required to capture Chainlink lag before other arbitrageurs

### Documented Edge/Returns
- Our backtest (F7/Cyclops validated at G1+G3+G4): n=36, WR 80.6%, +$0.244/trade, p=0.002
- PolySwarm: claims latency arb module exploits stale prices systematically on Polymarket
- BIS (Budish 2015): latency arb worth $5B/year in equities, 33% of effective spread

### Applicability to Our Setup
**APPLICABLE (working candidate / already deployed).** This is our primary validated edge. The theoretical literature fully supports the mechanism. **Key open questions:**
1. What is the exact oracle lag distribution? (empirical from our RTDS data)
2. At what Binance price move threshold does the lag create a tradeable signal?
3. How many other traders exploit the same lag? (crowding risk)

**Sources:** Hasbrouck (1995) *J. Finance*; Budish, Cramton & Shim (2015) *QJE*; Wikipedia Lead-Lag Effect; arXiv:2604.03888 (PolySwarm); CLAUDE.md F7 verification.

---

## 8. Calendar / Term-Structure Arbitrage

### Mechanism
**Traditional:** Buy near-dated contract, sell far-dated contract (or vice versa) when the spread deviates from fair value dictated by cost-of-carry + roll yield. Applied to commodity futures (oil contango/backwardation), interest rate swaps (swap curve), options (implied vol term structure).

**Calendar spread in options:** Buy near-month option, sell far-month option at same strike when near-month IV is cheap relative to far-month. Profit if near-month IV rises toward fair value.

**Poly analog:** Same asset (BTC), same directional question (will price be Up vs strike?), different windows: 1m vs 5m vs 15m slugs. Each window fires roughly simultaneously. A 1m Up is a shorter "option" than a 15m Up on the same strike (holding everything else constant, 15m should have more entropy / closer to 0.50). Cross-window consistency: if 1m Up = 0.80 but 15m Up = 0.55 with the same strike, one may be wrong.

**Formal framework (barrier option analogy):** A 1m Up slug is a cash-or-nothing digital: pays $1 if BTC_t+1m > BTC_t0. A 15m Up slug on the same window start is a wider barrier. Under BSM, the wider window should have price closer to 0.50. Implied vol surface consistency across the term structure gives a no-arb constraint.

### Capital / Infra / Latency
- Capital: two positions (1m + 15m) of equal notional; partial hedge
- Infra: simultaneous book monitoring across 3 timeframes
- Latency: seconds to enter both legs; not latency-critical

### Documented Edge/Returns
- No published result specifically for Poly cross-window arb
- Calendar spreads in equity options: documented IV term-structure arbitrage, typical Sharpe ~0.5–1.5

### Applicability to Our Setup
**PARTIAL.** The theoretical no-arb constraint between 1m and 15m prices on the same asset is real. Challenges:
1. **Strike/window misalignment**: 1m and 15m slugs fire from different `slot_start` times; comparing them requires careful alignment to same underlying window start
2. **Liquidity**: thin books in 1m slugs
3. **Not a pure arb**: the two slugs have different underlying time windows, so they measure different things (1m is a sub-event of 15m, but not identical)
4. **Signal application**: strong 15m directional signal that contradicts 1m market price → trade 1m

**Sources:** Wikipedia Calendar Spread; Wikipedia Basis Trading; BSM formula for binary options.

---

## 9. Volatility Arbitrage & Vol Risk Premium

### Mechanism
**Vol arb:** Exploit difference between implied volatility (from option pricing) and realized/forecasted future volatility. Buy delta-hedged options when IV < expected RV (long vol); sell when IV > expected RV (short vol). Delta-hedged → pure vol exposure, no directional risk.

**Vol risk premium (VRP):** Empirically, implied vol > realized vol on average (VIX > subsequent realized S&P vol). Sellers of options harvest this premium. Documented in equities (Coval & Shumway 2001), crypto (Siu & Elliott 2021), and prediction markets.

**Binary options vol arb:** The BSM formula for a cash-or-nothing digital paying $1 if S_T > K:
- Price = N(d2) = N[(ln(S/K) + (r − σ²/2)T) / (σ√T)]
- Given Binance spot S, strike K (known from slug), time T (slug duration), risk-free r≈0: the **only free parameter is σ**
- Market price of Up = implied_N(d2) → back out implied σ
- Compare to GARCH/EWMA realized vol from Binance 1s klines
- If implied_σ >> realized_σ → sell Up (market prices too much uncertainty)
- If implied_σ << realized_σ → buy Up or Down depending on moneyness

### Capital / Infra / Latency
- Capital: per-trade directional (buy Up or Down)
- Infra: real-time vol model (GARCH or EWMA on 1s klines), BSM inversion
- Latency: computed once per slug open; seconds acceptable

### Documented Edge/Returns
- Vol risk premium in equities: ~2–4% annualized return from systematic short-vol (Coval & Shumway 2001)
- Crypto options: Deribit BTC implied vol consistently 5–15pp above realized vol (documented by Glassnode research)
- Prediction market equiv: not directly documented; our data could characterize it

### Applicability to Our Setup
**PARTIAL (novel angle).** The BSM N(d2) framework gives a model-fair-value for each slug using only Binance spot + vol + time to expiry. This is the **model-fair-value vs. Poly-price** relative value strategy:

```
fair_p_up = N((ln(S/K) + (r − σ²/2)·T) / (σ√T))
edge = fair_p_up − poly_ask_up          # if positive → buy Up
edge = poly_bid_up − fair_p_up          # if positive → sell Up (need inventory)
```

Combined with the oracle-lag signal (know direction of Chainlink move before market does), this becomes a layered signal. The vol model quantifies "how surprising is the move" not just direction.

**Key challenge:** BSM assumes GBM for S_t; crypto returns are fat-tailed/have jumps. Use a jump-diffusion or realized vol model rather than constant σ.

**Sources:** Wikipedia Volatility Arbitrage; BSM binary option formula (Wikipedia Black-Scholes Extensions); Coval & Shumway (2001); arXiv:2604.03888 (log-normal model for Poly implied prob).

---

## 10. Risk / Merger Arbitrage

### Mechanism
Buy target company stock after acquisition announcement at discount to deal price; sell if deal collapses. Profit = deal premium × P(success) − loss × P(failure). Kelly sizing based on deal probability estimate. Requires: M&A information access, legal analysis, regulatory assessment.

### Capital / Infra / Latency
- Capital: 1–3% per deal; diversified across 20–50 active deals
- Infra: M&A news feeds, legal/regulatory monitor
- Latency: hours-to-days; not latency-sensitive

### Documented Edge/Returns
- Risk arb hedge funds: historically 8–12% annualized; Sharpe ~1–2
- Mitchell & Pulvino (2001): risk arb earns positive returns with option-like exposure to market crashes

### Applicability to Our Setup
**NOT applicable.** Poly up-down crypto markets have no corporate event structure. The closest analog would be "event arb" — trading Poly political/macro event markets when new information arrives — but our universe is strictly BTC/ETH/SOL price direction.

**Sources:** Wikipedia Risk Arbitrage; Mitchell & Pulvino (2001) *J. Finance*.

---

## 11. Convergence Trades

### Mechanism
Long one asset, short a near-identical asset at a premium, expecting convergence. Classic examples:
- On-the-run vs off-the-run Treasuries (liquidity premium converges when new bond issues)
- Junk bond vs Treasury spread compression
- Cash-and-carry (futures vs spot)
- LTCM: long off-the-run + short on-the-run → convergence trade that failed in 1998 liquidity crisis

**Key risk:** convergence may not happen before capital is exhausted; liquidity crisis can widen spreads indefinitely.

### Applicability to Our Setup
**NOT applicable in classic form.** No near-identical Poly instrument trades at a persistent premium. The closest is the ETF/MERGE arb (section 6) which IS a convergence trade — but we've killed the symmetric version due to fees.

**Sources:** Wikipedia Convergence Trade; LTCM case study.

---

## 12. Model Fair Value vs. Poly Price (Relative-Value / Implied Probability Arb)

### Mechanism
This is the most novel and directly applicable strategy for our setup. The core idea:

**Step 1: Derive fair probability from CEX data.**
Given:
- S = Binance spot price at time of fire (ws_s)
- K = slug strike = Chainlink price at slug_start (known from canonical data)
- T = time to slug expiry in years (e.g. 300s / 31,536,000 = 9.5×10⁻⁶ years)
- σ = realized vol from Binance 1s klines (EWMA or GARCH)

BSM cash-or-nothing digital: **P(Up) = N(d2)** where d2 = (ln(S/K) + (r − σ²/2)·T) / (σ√T)

At ultra-short T, d2 simplifies: ln(S/K) dominates vs vol·√T term. P(Up) ≈ Φ(ln(S/K) / (σ√T)) — essentially a probit of the current-price-vs-strike distance normalized by expected vol over the window.

**Step 2: Compare to Poly market price.**
If P_model(Up) >> P_poly(Up_ask) → buy Up (underpriced given model)
If P_model(Up) << P_poly(Up_bid) → buy Down (Up is overpriced, Down is cheap)

**Step 3: Signal conditioning.**
The model signal is weakest near expiry (P converges to 0 or 1 regardless of model) and strongest at mid-slug. Combined with oracle-lag signal (confirmed direction of Chainlink settlement), the model serves as an **entry-timing filter**: only fire when model edge AND directional signal agree.

**Additional signals available:**
- Binance 1s volume imbalance → short-term drift in S
- Binance perp funding rate → sentiment skew
- Cross-asset (ETH signal cross-validates BTC signal)

### Capital / Infra / Latency
- Capital: single directional leg ~$25 (L25 depth)
- Infra: real-time Binance 1s klines → rolling σ model; slug strike from canonical
- Latency: model computation in <1ms; dominant latency is Poly CLOB execution (~2ms Ireland)

### Documented Edge
- PolySwarm (arXiv:2604.03888, 2026): "deriving CEX-implied probabilities from a log-normal pricing model" achieves positive returns vs Poly market prices in backtest
- Theoretical: any persistent mispricing of P(Up) vs BSM fair value is exploitable if execution cost < model edge
- Our oracle-lag strategy is a special case: at ws_s, Binance price S has already moved and Poly hasn't updated → P_model(Up) has shifted sharply while P_poly hasn't

### Applicability to Our Setup
**APPLICABLE (new, high-priority).** This is a generalization of our existing oracle-lag strategy. The oracle-lag fires when we _know_ (from Chainlink vs Binance divergence) that the settlement price will differ from current Poly price. The model-fair-value strategy fires more broadly whenever the Poly price deviates from what Binance vol+price implies. This includes:
- Oracle-lag trades (confirmed signal)
- Post-large-Binance-move trades before Poly updates
- Moments when Poly book is stale due to thin participation

**Sources:** BSM binary option formula (Wikipedia Black-Scholes, section "Binary options"); arXiv:2604.03888; PolySwarm log-normal model description.

---

## 13. Positioned / Sequential Leg-In Arbitrage — Theory and Why It Fails

### Mechanism
A "positioned" or "sequential" arb abandons market-neutrality: instead of entering both legs of an arb simultaneously, the trader enters Leg 1 first, waits for an opportunity to enter Leg 2 at a better price, then holds the completed arbitrage position to convergence.

**Example in Poly context (already tested):**
- See a slug where Up = 0.55, Down = 0.44 (sum = 0.99 → slight MINT arb)
- MINT $1 → get 1 Up + 1 Down at $1 cost
- Sell Up immediately at 0.55 → hold Down at basis 0.45, hoping Down rises to 0.50+
- Or conversely: buy Up at 0.55, wait for Down price to fall to where sum < $1

The idea is that by being "positioned" in one leg, the trader can leg into the arb more cheaply than buying both legs simultaneously.

### Why Positioned Arb Suffers Adverse Selection

**The Glosten-Milgrom (1985) framework** is definitive here (Lawrence Glosten & Paul Milgrom, *Journal of Financial Economics* 1985):

> In a market where some traders hold private information, the equilibrium bid-ask spread compensates the market maker for the adverse selection risk of trading against informed counterparties.

In the Glosten-Milgrom model:
- The market maker posts a spread
- Uninformed traders (noise traders) arrive randomly
- Informed traders (who know the true value) arrive with probability α
- Market maker loses on every trade with an informed trader, profits on every uninformed trade
- At equilibrium, spread = E[loss to informed traders] / E[volume from uninformed] — the "adverse-selection component" of the spread

**Applied to positioned Poly arb:**
When you enter Leg 1 (say buy Up at 0.55), you are taking liquidity. The market maker who sold to you has posted at 0.55 because they estimate the distribution of order flow. If YOU are seeking to leg into an arb (an informed strategy), you are precisely the "informed trader" the Glosten-Milgrom model predicts will systematically take from market makers. The market maker will widen the quote after seeing your Leg 1 trade.

**Empirically, in our data:**
- Positioned maker arb in Poly: tested across all maker-arb slugs with `inv = 0` at resolution
- Result: −$0.03/share net after correctly accounting for unsettled (censored) slugs
- The "edge" was entirely survivorship bias: slugs that resolved with inventory=0 were the winners; losers were the right-censored un-REDEEMed positions
- FULL reversal documented in `MAKER_ARB_CENSORING_REVERSAL_2026_05_28.md`

**More formally, why adverse selection dominates:**

1. **Information asymmetry**: when the Poly book shows Up+Down < $1 (a MINT arb), informed players already know whether price is going Up or Down. When you MINT and sell Up at 0.55, you're selling to someone who has bought it at 0.55 because they think Up will win. You've effectively taken the side of the uninformed — holding Down at 0.45 while the informed counterparty holds Up.

2. **Price impact**: your Leg 1 trade (selling Up at 0.55) signals your activity to the market. Down sellers observe Up being sold → infer MINT arb → raise Down ask price. The "free lunch" of sum < $1 evaporates before Leg 2 can be filled.

3. **Execution timing exposure**: in the period between Leg 1 and Leg 2, the underlying BTC/ETH price can move. If it moves strongly toward Up, Up rises to 0.70 and Down falls to 0.25 — your Down position is now worth $0.25 not $0.45. You've made a directional bet disguised as an arb.

4. **Maker position = free option to informed traders**: any maker limit order placed as part of a positioned arb is a free option to informed traders. If the price moves strongly and your Down limit order is filled at 0.44, it means someone who knows Down will lose $1 is happy to sell Down to you at 0.44. You are the counterparty to better-informed flow. This is Kyle (1985) model logic: informed traders pick off stale limit orders.

**Net: positioned arb is not market-neutral; it is directional with adverse selection skew. The edge requires being better-informed than the counterparty. Since we are taking liquidity on both legs (not market-making), we are paying the adverse selection premium, not collecting it.**

### Conditions Under Which Positioned Arb Could Work
Despite the above, positioned arb can work if:
1. **Execution risk is minimal** — near-instantaneous Leg 1 + Leg 2 (requires colo + deep books + atomic CLOB fills)
2. **The arb is large enough** to cover adverse selection costs (typically 2–5× taker fees minimum)
3. **The market is sufficiently slow-moving** — if Poly price updates at human speed and you can leg in within milliseconds, the window before informed players react is exploitable

None of these conditions hold for us currently: books are thin ($25 depth), we're not colocated, and the sum-arb margin (typically $0.01–0.03) is smaller than adverse selection costs.

**Sources:** Glosten & Milgrom (1985) *J. Financial Economics*; Kyle (1985) *Econometrica*; Wikipedia Market Maker (adverse selection component); Wikipedia Adverse Selection; MAKER_ARB_CENSORING_REVERSAL_2026_05_28.md; our own tested result: −$0.03/share.

---

## 14. Cross-Asset Implied Probability Relative Value

### Mechanism
If BTC and ETH are correlated (ρ ≈ 0.85 at 5m scale), then:
- P(BTC_Up) and P(ETH_Up) on same-duration slugs should be correlated
- If BTC just made a strong +0.3% move on Binance and P(BTC_Up)=0.75, while ETH price is flat and P(ETH_Up)=0.50 despite high BTC-ETH correlation → ETH_Up is likely underpriced

This is a cross-asset implied-probability relative-value trade: use the well-priced asset (BTC) to project fair probability of the correlated asset (ETH) and trade the gap.

**Formal approach:**
1. Estimate ρ(BTC_return, ETH_return) on 5m scale using recent 1s kline data
2. Compute driftBTC = (BTC_spot − BTC_strike) / BTC_spot
3. Project driftETH_implied ≈ β × driftBTC where β = ETH/BTC 5m beta
4. Compute P_implied(ETH_Up) = N(driftETH_implied / (σ_ETH × √T))
5. Compare to P_poly(ETH_Up); trade if gap > threshold

### Applicability to Our Setup
**PARTIAL.** The cross-asset signal is already partially embedded in our multi-asset data. Key challenges:
1. **Beta instability**: BTC-ETH beta varies significantly over short intervals
2. **Simultaneous oracle-lag**: if Chainlink lags Binance for both, the lag-based signal already captures the dominant mispricing without needing cross-asset comparison
3. **Additive signal**: useful as a secondary confirming signal, not primary strategy

The strongest application: when BTC fire is borderline (near 50/50 per model), but ETH cross-validation pushes confidence to >60%, take the BTC trade.

---

## 15. Ornstein-Uhlenbeck / Intra-Slug Microstructure Reversion

### Mechanism
Within a single active slug (up to 15m window), the Poly price of Up may exhibit short-term mean-reverting behavior driven by:
1. **Order flow impact**: large taker order pushes Up from 0.55 to 0.65; book then replenishes as makers add supply near 0.60
2. **Information arrival**: Binance spike at T causes Up to jump; if spike reverses, Up should revert
3. **Market-maker rebalancing**: Poly MMs hedge inventory by quoting tighter post-large-order

**Trading rule:** measure intra-slug price impact of large orders; buy if price was pushed down by selling pressure and book is replenishing; sell if price was pushed up and is now above model fair value.

### Applicability to Our Setup
**NOT a standalone strategy** given thin Poly books and our ~$25 max order size. The intra-slug reversion window is 1–60s; we'd need to detect large orders, wait for impact to decay, and fill — all within a slug that may expire in <5 minutes. Useful as a signal modifier for entry timing: prefer to enter on temporary adverse price movements when the model edge is confirmed.

---

## 16. Sources Reference List

| # | Source | Used For |
|---|--------|----------|
| 1 | Wikipedia: Statistical Arbitrage | StatArb overview, factor models |
| 2 | Wikipedia: Pairs Trade | Pairs trading mechanism, Morgan Stanley history |
| 3 | Wikipedia: Cointegration | ADF test, Engle-Granger (1987) |
| 4 | Wikipedia: Ornstein-Uhlenbeck Process | OU math, mean-reversion half-life |
| 5 | Wikipedia: Exchange-Traded Fund (Arbitrage section) | ETF creation/redemption mechanism |
| 6 | Wikipedia: Basis Trading | Spot-futures basis arb |
| 7 | Wikipedia: Convergence Trade | LTCM, on-the-run/off-the-run |
| 8 | Wikipedia: Volatility Arbitrage | Vol arb, implied vs realized vol |
| 9 | Wikipedia: Risk Arbitrage | Merger arb overview |
| 10 | Wikipedia: Perpetual Futures | Funding rate mechanism |
| 11 | Wikipedia: Market Maker | Glosten-Milgrom 1985, adverse selection spread decomposition |
| 12 | Wikipedia: Adverse Selection | Akerlof lemons, informed/uninformed traders |
| 13 | Wikipedia: Market Microstructure | Transaction cost decomposition (order processing + adverse selection + inventory) |
| 14 | Wikipedia: Price Discovery | Hasbrouck information share framework |
| 15 | Wikipedia: Black-Scholes Model | Binary/digital option pricing, N(d2) cash-or-nothing formula |
| 16 | Wikipedia: Prediction Market | Binary option structure, Polymarket context |
| 17 | Wikipedia: Calendar Spread | Term-structure vol arb |
| 18 | Wikipedia: Binary Option (Digital Option) | BSM pricing of cash-or-nothing, digital options |
| 19 | Wikipedia: Index Arbitrage | Index fair value, ETF creation/redemption |
| 20 | QuantInsti: Pairs Trading Basics | Z-score methodology, ADF, entry/exit rules |
| 21 | arXiv:2604.03888 (PolySwarm, Barot & Borkhatariya, 2026) | CEX-implied prob model, Poly latency arb confirmation, KL-divergence cross-market inefficiency detection |
| 22 | Budish, Cramton & Shim (2015) *QJE* — via BIS search result | Latency arb tax = 0.42bps, $5B/year global equity; 33% of effective spread |
| 23 | Glosten & Milgrom (1985) *J. Financial Economics* (via Wikipedia citation) | Adverse selection component of bid-ask spread, informed/uninformed model |
| 24 | Gatev, Goetzmann & Rouwenhorst (2006) *Rev. Financial Studies* | Pairs trading returns ~11% annual, decline post-2002 |
| 25 | CLAUDE.md / local research | Fee model verification (2%-on-profit), oracle-lag confirmation, L25 convention, maker-arb reversal |

---

## Appendix: Structured Checklist for Each New Strategy Idea

Before implementing any arb variant, verify:
- [ ] Is the arb **simultaneous** (both legs atomic) or **sequential** (positioned)?
  - Sequential → quantify adverse selection cost; assume −$0.03/share baseline unless model edge > 2% net
- [ ] What is the **sum deviation threshold** required to cover: (a) taker fees, (b) adverse selection cost, (c) execution slippage?
- [ ] Is the convergence **time-bounded** within slug lifetime?
- [ ] Is there a **model-fair-value** signal to confirm direction before entering?
- [ ] Does the strategy require **colo** to be competitive? (sum-arb: yes; oracle-lag: Ireland VPS sufficient)
