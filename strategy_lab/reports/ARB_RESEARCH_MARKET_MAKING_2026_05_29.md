# Market Making Strategy Catalog — Polymarket Binary Up-Down Applicability
**Research date:** 2026-05-29  
**Scope:** Academic theory + crypto practice, ranked by applicability to Polymarket BTC/ETH/SOL 1m/5m/15m binary CLOB  
**Our setup:** Polygon CLOB, AWS eu-west-2 server in Ireland (<2ms RTT), Chainlink oracle lags Binance ~5–20s, maker=$0 fee + 20% rebate share on crypto, taker=`0.07 × p × (1-p)`

---

## Summary Table (ranked by applicability)

| # | Strategy | Applicability | One-line verdict |
|---|---|---|---|
| 1 | **Directional-Tilted / Signal-Skewed One-Sided Maker** | **APPLICABLE** | Post maker bids only on binance-favored side; captures rebate + avoids adverse leg — directly addresses our idea |
| 2 | **Avellaneda-Stoikov Reservation Price + Skew** | **APPLICABLE (partial)** | Formula for shifting quotes by inventory + signal; adapt reservation price to incorporate oracle-lag alpha |
| 3 | **Adverse Selection Detection (VPIN / OFI filter)** | **APPLICABLE** | Detect when informed flow is present; gate/pause quoting on high-toxicity windows |
| 4 | **Fodra-Labadie Directional Bets Extension** | **APPLICABLE** | Formal theory for non-symmetric limit orders when maker has a directional forecast — exact our scenario |
| 5 | **Cartea-Wang Market Making with Alpha Signals** | **APPLICABLE** | Alpha shifts reservation price; when alpha is strong, post only one side; canonical academic reference |
| 6 | **GLFT (Guéant-Lehalle-Fernandez-Tapia)** | PARTIAL | Closed-form optimal spread with inventory constraints; inventory dynamics don't fully apply to binary (0/1 payoff) |
| 7 | **Quote Cancellation / Stale-Quote Protection** | **APPLICABLE** | Cancel both legs the moment binance flips direction; Polymarket CLOB is off-chain, sub-ms cancel feasible |
| 8 | **Maker Rebate Harvesting** | APPLICABLE | 20% of taker fee = `0.014 × p × (1-p)` per contract; real income at scale |
| 9 | **Grid / Ladder Quoting** | PARTIAL | Symmetric grid dies to adverse selection; directional grid (only buy-side laddered) is viable |
| 10 | **Delta-Neutral / Cross-Venue Hedge** | NOT APPLICABLE | No correlated hedge instrument for Polymarket binary outcome contracts |
| 11 | **Ho-Stoll Inventory Model** | PARTIAL | Foundational — same intuition, but continuous payoff assumption invalid for binary |
| 12 | **Glosten-Milgrom Information Spread** | PARTIAL (theory) | Explains WHY symmetric MM loses; used to size the spread to break even against informed traders |
| 13 | **Symmetric Pure Market Making** | **ALREADY KILLED** | Our tests: adverse selection ~20% stuck losers swamp $0.03–0.06 spread; net-negative |
| 14 | **Queue Position Optimization** | NOT APPLICABLE | CLOB is off-chain, Polymarket has no co-location; queue games irrelevant at our latency |

---

## 1. Avellaneda-Stoikov (A-S) Optimal Market Making

### Mechanism
Published in *Quantitative Finance* (2008). Treats market making as a stochastic control problem with CARA utility. Two core outputs:

**Reservation price** (quote center, shifted by inventory):
```
r(s, q, t) = s − q · γ · σ² · (T − t)
```
- `s` = mid-price, `q` = current inventory (signed), `γ` = risk aversion, `σ²` = asset variance, `T−t` = remaining session

**Optimal spread**:
```
δ_bid + δ_ask = γ · σ² · (T − t) + (2/γ) · ln(1 + γ/κ)
```
- `κ` = order book density (fill-rate sensitivity to distance from mid)

When long (`q > 0`), reservation price drops below mid → ask moves closer to mid, bid moves further → the market maker is nudged to sell. Vice versa when short. The spread widens with volatility and remaining time.

**Extensions:** The signal-augmented version uses `r = s + α·signal − q·γ·σ²·(T−t)` where `α·signal` is a directional component (see §5 Cartea-Wang).

### Capital / Infra / Latency
- Vanilla: any capital level; millisecond latency to maintain top-of-book
- Signal-augmented: needs sub-second signal update loop (Binance WS + local computation)

### Documented Edge
Hummingbot implementation shows systematic spread income in range-bound markets. Sharpe improves 2×+ vs. passive symmetric MM in directional market when inventory control is active (Fodra-Labadie 2012).

### Applicability to Polymarket Binary
**PARTIAL.** Key adaptations needed:
1. **Binary payoff, not continuous.** `q · γ · σ²` is derived for Brownian mid-price; binary up-down resolves to exactly 0 or 1. The "inventory" risk for binary contracts is not a continuous P&L curve — it is a discrete 0 or 1 per contract at resolution. This changes the math but preserves the intuition: holding an inventory of "wrong-side" contracts is catastrophically bad, so the inventory penalty must be harsh (large `γ`).
2. **Oracle lag as signal.** Replace `s` (Binance mid) with the "fair binary probability" derived from binance spot move vs. strike, and incorporate the oracle-lag alpha into the reservation price.
3. **Spread calibration.** The `κ` parameter maps to Polymarket order book fill rate; must be estimated from L25 data.

### Sources
- Avellaneda & Stoikov, *Quantitative Finance* 8(3), 2008
- [Hummingbot guide](https://hummingbot.org/blog/guide-to-the-avellaneda--stoikov-strategy/)
- [QuantLabsNet comprehensive analysis](https://www.quantlabsnet.com/post/ultra-low-latency-high-frequency-market-making-a-comprehensive-analysis-of-the-avellaneda-stoikov-f)
- [Stanford HFT report](https://stanford.edu/class/msande448/2018/Final/Reports/gr5.pdf)

---

## 2. GLFT — Guéant-Lehalle-Fernandez-Tapia (2013)

### Mechanism
Published in *Mathematics and Financial Economics* 7 (2013). Extends A-S: converts the HJB PDEs into a system of linear ODEs, producing a **closed-form solution** for optimal bid/ask quotes with explicit inventory constraints `[q_min, q_max]`.

Key addition: **inventory hard limits.** When `q = q_max` (fully long), stop posting bids entirely. When `q = q_min` (fully short), stop posting asks. This is the natural one-sided quoting boundary arising from pure inventory management.

Asymptotic approximation:
```
δ* ≈ (1/γ) · ln(1 + γ/κ)   [leading term, independent of inventory]
```
plus inventory correction terms. Closed-form Sharpe-optimal quotes reduce to near-A-S in practice.

### Capital / Infra / Latency
Same as A-S; closed-form means computationally trivial to evaluate.

### Documented Edge
GLFT model is the industry standard for OTC and equity market making desks. The hard inventory limits prevent runaway accumulation.

### Applicability to Polymarket Binary
**PARTIAL.** The inventory constraint mechanism is directly applicable: once we hold N units of the "losing-side" binary, we should stop posting. But:
1. The continuous-payoff math doesn't directly port.
2. The binary payoff creates a cliff at resolution — the spread must compensate for a potential loss of the full contract value, not just bid-ask width.
3. Practically: the rule "stop posting on the side where you're already over-exposed" is a direct takeaway, implementable without solving the full GLFT ODEs.

### Sources
- [arXiv:1105.3115](https://arxiv.org/abs/1105.3115) — Guéant, Lehalle, Fernandez-Tapia (2011/2013)
- Springer: *Mathematics and Financial Economics* 7, 477–507 (2013)

---

## 3. Glosten-Milgrom (GM) Information-Based Spread Model (1985)

### Mechanism
*Journal of Financial Economics* 13 (1985). Risk-neutral market maker sets bid/ask conditional on incoming order direction, using Bayesian updating. The spread is purely an **adverse-selection premium**:

```
Spread = E[V | buy order] − E[V | sell order]
```

Each trade is either from an informed trader (who knows true value) or noise trader (random). If fraction `μ` of orders is informed:
```
Ask = E[V] + μ · (E[V | informed buy] − E[V])
Bid = E[V] − μ · (E[V] − E[V | informed sell])
```
The market maker breaks even in expectation by charging a spread that recoups losses to informed traders from noise traders.

In binary markets: `E[V] = p` (probability of Up). A buy order from an informed trader reveals the probability should be higher; the ask is set higher to compensate.

### Capital / Infra / Latency
Theoretical model. Implementation = estimate `μ` empirically from win rate of market orders vs. subsequent resolution.

### Documented Edge
Explains the persistent 2–5¢ spread in prediction markets. Defines the minimum spread that makes symmetric market making break-even. Markets maintain positive spread consistent with GM predictions (startpolymarket guide confirms: "the persistent bid-ask spread of 2–5 cents observed in prediction markets is consistent with Glosten-Milgrom").

### Applicability to Polymarket Binary
**PARTIAL (theoretical tool).** Primary use: **size the minimum spread** to break even against informed flow. In our context:
- Informed traders = latency arbers exploiting oracle lag
- `μ` can be estimated from our data: what fraction of market buys are directionally correct pre-resolution?
- If `μ` is high (many informed arbers at 50¢ markets), the break-even spread is wide — symmetric MM is unprofitable at any reasonable spread, which matches our "already-killed" result.

### Sources
- Glosten & Milgrom, *JFE* 13, 71–100 (1985)
- [Columbia Business School summary](https://business.columbia.edu/faculty/research/bid-ask-and-transaction-prices-specialist-market-heterogeneously-informed-traders)
- [Berkeley narrow spreads paper](https://haas.berkeley.edu/wp-content/uploads/narrow-spreads.pdf)

---

## 4. Ho-Stoll (1981) Inventory Model

### Mechanism
*Journal of Financial Economics* 9 (1981). Single-period mean-variance utility for a dealer. Key result: the dealer adjusts **both** bid and ask prices by the same amount when inventory is off-target — so the **spread stays constant** but the mid shifts. Specifically:

```
bid, ask shift by: Δ = -(q/Q) · γ_portfolio · σ²_asset
```

where `Q` is the dealer's total wealth. The result: optimal quotes are functions of inventory, return variance, and transaction arrival rate (Poisson process).

### Capital / Infra / Latency
Same as A-S (precursor model). Less tractable than A-S in continuous time.

### Documented Edge
Foundational. Directly motivated A-S (2008) and GLFT (2013). Shows that inventory-adjusted quotes are necessary and sufficient for a risk-averse dealer to optimize expected utility.

### Applicability to Polymarket Binary
**PARTIAL.** Same caveats as A-S: continuous payoff assumption. The key takeaway — shift your quote center proportional to inventory × variance — directly applies and is easier to implement than the full A-S machinery.

### Sources
- Ho & Stoll, *JFE* 9, 47–73 (1981)
- [Semantic Scholar](https://www.semanticscholar.org/paper/Optimal-dealer-pricing-under-transactions-and-Ho-Stoll/008cd342a5527411064196d34c7148f54ba72079)

---

## 5. Cartea-Wang: Market Making with Alpha Signals (2020)

### Mechanism
*International Journal of Theoretical and Applied Finance* 23(3), 2020. A market maker observes a **momentum alpha signal** `α_t` about the mid-price direction. The signal arrives from order flow and news. Optimal strategy: when `α_t` is positive (price expected to rise):
- **Do not post sell limit orders** (avoid being picked off on the ask side)
- Post buy limit orders at a favorable price (lean inventory toward the up-move)

When `α_t` is near zero: post both sides (standard symmetric MM).  
When `α_t` is strongly negative: do not post buy limit orders.

The alpha shifts the reservation price:
```
r = s + c₁ · α_t − c₂ · q · γ · σ²
```

Speculative market orders are also used at the end of the horizon. Higher inventory risk tolerance → more alpha-driven speculative trades, higher expected PnL but more inventory variance.

**Critical result:** When alpha is strong, the strategy employs **one-sided limit orders** — this is the academic foundation for our directional-tilted maker idea.

"When the value of α_t is near zero, the strategy posts both sell and buy LOs. When α_t is positive (negative), the strategy tends not to post sell (buy) limit orders to avoid adverse selection costs."

### Capital / Infra / Latency
Needs real-time alpha signal update (e.g., binance momentum every second). Strategy is not latency-critical for the maker leg — orders rest; only the cancel-and-update loop must be fast.

### Documented Edge
Calibrated on Nasdaq nanosecond HFT data. Directional alpha increases PnL by capturing the spread AND trending inventory. Under moderate risk tolerance, Sharpe ratio improves 2× vs. symmetric MM benchmark.

### Applicability to Polymarket Binary
**HIGHLY APPLICABLE.** This is the canonical academic model for our directional-tilted maker idea:
- **Alpha signal** = binance spot momentum vs. strike (our oracle-lag signal), updated at ~1s intervals
- **One-sided quoting rule** = only post Up bids when binance is bullish, only post Down bids when binance is bearish
- **Inventory management** = if stuck holding Up contracts in a down move, stop posting Up bids
- **Adverse selection** = exactly the oracle-lag arbers who take our stale quotes at the wrong price

Implementation plan:
1. Compute `α_t = sign(binance_price_t − strike) × |binance_move|` normalized
2. When `α_t > threshold` → post only buy-Up limit orders at `p_Up_fair − half_spread`
3. When `α_t < -threshold` → post only buy-Down limit orders  
4. Cancel all resting orders the moment `α_t` flips sign

### Sources
- [Cartea & Wang, IJTAF 2020 (Oxford ORA)](https://ora.ox.ac.uk/objects/uuid:c2ba6656-8eab-4b2e-a24a-e9e842d1378f/files/s41687h481)
- [SSRN working paper](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3439440)

---

## 6. Fodra-Labadie: HF Market Making with Inventory Constraints and Directional Bets (2012)

### Mechanism
[arXiv:1206.4810](https://arxiv.org/abs/1206.4810). Extends A-S/GLFT to **non-martingale mid-price processes** — i.e., when the market maker has a directional view. Key innovation: adds an **inventory-risk-aversion parameter** `η` that penalizes non-zero end-of-day inventory.

When the market maker expects prices to **rise**, she places **non-symmetric limit orders** that favor market orders hitting her **bid** (she wants to buy), while keeping ask quotes wider or absent.

When prices expected to **fall**: favor ask quotes, suppress bids.

Numerical results (mean-reverting mid-price benchmark):
- With directional bets: average PnL increases **>15%** vs. martingale benchmark (at cost of higher inventory variance)
- Moderate `η`: give up 5% of PnL to improve Sharpe ratio by **>2×**

### Capital / Infra / Latency
Academic framework. Computationally intensive (HJB solution) but closed-form approximations exist.

### Applicability to Polymarket Binary
**HIGHLY APPLICABLE.** This is the closest academic paper to our exact scenario:
- Non-martingale mid-price: Polymarket binary price is NOT a martingale intra-slug — it's anchored to the binance spot process, creating a predictable drift signal
- Non-symmetric orders: exactly what we want — only post on binance-favored side
- Inventory-risk-aversion `η`: crucial for binary markets where inventory on the wrong side = 100% loss at resolution. Set `η` very high as slug approaches resolution.
- The >15% PnL improvement from directional bets directly motivates the strategy

### Sources
- [arXiv:1206.4810](https://arxiv.org/abs/1206.4810) — Fodra & Labadie (2012)
- Follow-up: [arXiv:1303.7177](https://arxiv.org/pdf/1303.7177) — multi-dimensional Markov extension (2013)
- [HAL archive](https://hal.science/hal-00675925v1)

---

## 7. Adverse Selection Detection: VPIN and Order Flow Toxicity

### Mechanism
**VPIN** (Volume-Synchronized Probability of INformed Trading) — Easley, Lopez de Prado, O'Hara (2012). Measures order flow toxicity in real time by classifying each volume bucket as buyer- or seller-initiated:

```
VPIN = |V_buy − V_sell| / V_total    (over rolling volume buckets)
```

High VPIN → high fraction of informed/directional order flow → market maker is likely being adversely selected → widen spread or stop quoting.

**Order Flow Imbalance (OFI)** — Cont, Kukanov, Stoikov (2010). Measures directional pressure in the LOB:
```
OFI_t = Σ[event_t] (bid_volume_change - ask_volume_change)
```
Strong positive OFI → buyers dominating → price likely to rise. Can be used both as an alpha signal AND as a toxicity detector.

**Toxicity detection loop:**
1. Compute VPIN or OFI from Polymarket order tape in real time
2. When VPIN spikes → oracle arbers are active → pause quoting or widen spread substantially
3. When VPIN is low (noise-trader regime) → resume tight quotes

### Capital / Infra / Latency
Needs real-time order tape. Polymarket CLOB WS provides this (we already have `wss://ws-subscriptions-clob.polymarket.com`). Computation is fast (rolling sum over volume buckets).

### Documented Edge
VPIN predicted the 2010 Flash Crash 1 hour early. Algos that reduce participation when VPIN is high avoid most adverse selection losses. Empirical: AT activity is negatively correlated with VPIN (algos withdraw when toxicity is high).

### Applicability to Polymarket Binary
**HIGHLY APPLICABLE.** In our context:
- **Informed traders** = oracle-lag arbers who know the binance price and are picking off stale Polymarket quotes
- High OFI on the polymarket Up token = informed buyers are hitting the ask = oracle arbers see binance is bullish and they're taking our resting ask
- Signal: if we see a burst of large taker buys on Up token → oracle arbers are active → cancel our Up bids immediately (they've seen we're mispriced)
- Can also gate entries: only post maker orders when OFI is neutral (no informed directional flow visible)

**Practical metric for our setup:** rather than full VPIN, a simpler proxy is "recent taker imbalance on the polymarket token relative to prior 60s". If suddenly 80% of trades are buys, arbers are present — withdraw.

### Sources
- Easley, Lopez de Prado, O'Hara, *Journal of Portfolio Management* (2012)
- [VPIN paper (quantresearch.org)](https://www.quantresearch.org/VPIN.pdf)
- [ScienceDirect introduction to VPIN](https://www.sciencedirect.com/science/article/abs/pii/S2173126812000344)
- [OFI signal (Dean Markwick)](https://dm13450.github.io/2022/02/02/Order-Flow-Imbalance.html)

---

## 8. Directional-Tilted / Signal-Skewed One-Sided Maker (Our Idea — Formalized)

### Mechanism
Synthesizes A-S, Fodra-Labadie, and Cartea-Wang specifically for our Polymarket binary setup:

**Core rule:**
1. Observe `binance_signal = sign(binance_price_t − strike)` → +1 if Up favored, −1 if Down favored
2. Compute signal strength `α = |binance_price_t − strike| / (σ_binance × √(T−t_remaining))`
   - When `α > threshold_enter`: post ONE-SIDED maker limit orders on the binance-favored side only
   - When `α < threshold_enter`: go flat, no maker orders
   - Cancel all resting orders immediately on signal flip
3. Maker order price: `p_maker = p_fair − half_spread` where `p_fair` is derived from binance implied probability (e.g., Black-Scholes digital with 5–20s oracle lag adjustment)
4. Inventory guard: if holding >N contracts on any side, stop adding to that side regardless of signal

**Why this solves the adverse selection problem:**
- Symmetric MM posts on both sides → the wrong side is ALWAYS stale vs. oracle arbers → ~20% of fills are adverse (our empirical finding)
- Directional-tilted MM only posts on the side where WE are the informed party (we know binance, oracle lags by 5–20s) → adverse selection flips: WE are the informed maker, oracle arbers are slower to arb against our maker order than they were to pick off the symmetric MM

**Rebate math:** At `p = 0.6`, taker fee = `0.07 × 0.6 × 0.4 = 0.0168` per contract. Maker rebate = 20% of that = **$0.00336 per contract**. At 1000 contracts/day filled: **$3.36/day** from rebate alone. The spread capture on top is the main alpha.

**Critical risk:** The signal can be wrong near resolution (within 5s of chainlink update, binance may have reversed). Need to widen the exclusion window as slug approaches resolution.

### Capital / Infra / Latency
- Capital: $50–500 capital to start; scale with fill rate
- Infra: Binance WS (already running) + Polymarket CLOB WS (already running)
- Latency: Ireland box (<2ms to London CLOB) is adequate for maker orders (no need for sub-ms; makers rest on book)
- Critical: cancel loop must be <500ms from signal flip to order cancel

### Documented Edge / Expected Returns
- Fodra-Labadie: directional bets add >15% to PnL vs. symmetric benchmark
- Cartea-Wang: one-sided quoting when alpha is strong reduces adverse selection costs
- Our dead symmetric MM: net-negative. Adding direction should flip the P&L sign on the fills that were adverse-selected.
- Rebate income: ~$0.003–0.017 per contract depending on price — floor income while spread varies

### Applicability
**PRIMARY CANDIDATE.** The entire point of this research. Directly supported by 3 academic papers + our empirical data showing symmetric MM fails due to adverse selection.

### Sources
See §5 (Cartea-Wang) and §6 (Fodra-Labadie). Additional:
- [Polymarket maker rebates docs](https://docs.polymarket.com/market-makers/maker-rebates)
- [startpolymarket.com MM guide](https://startpolymarket.com/strategies/market-making/)
- [Finance Magnates: Polymarket dynamic fees](https://www.financemagnates.com/cryptocurrency/polymarket-introduces-dynamic-fees-to-curb-latency-arbitrage-in-short-term-crypto-markets/)

---

## 9. Stale-Quote Risk Management and Quote Cancellation

### Mechanism
Market makers are exposed to being "sniped" when their quotes become stale relative to the true fair value. The latency arbitrageur (sniper) detects the mispricing and fills the market maker's stale order before it can be cancelled. Protection strategies:

1. **Speed-based:** Cancel quotes as fast as possible when external signal moves. The race is: sniper detection speed vs. maker cancel speed.
2. **Speed bump:** Some venues artificially delay taker execution (e.g., IEX 350μs). Polymarket has no speed bump — cancels must be fast.
3. **Option Rights (Last Look):** FX market makers can reject fills for a short window after a quote is hit. Polymarket CLOB has no last look.
4. **Drift guard:** Do not post maker orders when binance is moving fast (high realized volatility in last 5s → suspend quoting until stable).
5. **Price-level guard:** Set maker order further from fair value (widen spread) to require a larger adverse move before being picked off.

In our context, the "sniper" is the latency arber who sees:
- Binance price has moved →  Polymarket binary probability should move → stale maker quote is mispriced → arb

Cancel speed: Polymarket CLOB is off-chain (AWS eu-west-2, same region as our server). WebSocket cancel acknowledgment <2ms. This means we can cancel faster than most takers can react, IF we have a live binance feed triggering the cancel.

### Capital / Infra / Latency
- Needs dedicated cancel-on-signal-flip loop (separate thread from the quoting logic)
- Cancel-on-disconnect: Polymarket CLOB supports `cancel_all_orders` API call; must be wired to any connectivity loss event

### Sources
- [SEC IEX comment letter on stale quotes](https://www.sec.gov/comments/sr-iex-2025-02/sriex202502-615827-1806874.pdf)
- [Foucault, Kozhan, Tham — Toxic Arbitrage (2014)](https://www.inet.econ.cam.ac.uk/events-files/2015/toxic-arbitrage.pdf)
- [BIS Working Paper 1115 — Sharks in the dark](https://www.bis.org/publ/work1115.pdf)

---

## 10. Grid Trading / Layered Ladder Quoting

### Mechanism
Place multiple limit orders at fixed price intervals (e.g., every 1¢) on both sides. As the price oscillates, the bot captures small spreads repeatedly. Profit comes from mean-reversion (price oscillating in a range), not directional prediction.

For a binary prediction market, a "directional grid" variant makes sense:
- Post multiple bids on the Up side at prices 50¢, 49¢, 48¢ (resting, not symmetric)
- No asks on Down side
- When Up fills at 50¢ and price drops to 49¢, sell at 50¢ if it recovers (or hold to resolution)

Pure symmetric grid has the same fatal flaw as symmetric MM: near-resolution, accumulating the wrong side = full loss.

### Capital / Infra / Latency
Low capital (spread across grid levels). No special latency requirements for passive orders.

### Documented Edge
Grid trading works in range-bound markets. Documented by Hummingbot, Binance grid bots, etc. Research: ML models didn't improve; hedging strategies helped.

### Applicability to Polymarket Binary
**PARTIAL.** Symmetric grid = already-killed. Directional grid (only on binance-favored side, e.g., only "Up buy" grid when binance is bullish) is essentially the directional-tilted maker at multiple levels — valid if we have enough depth to ladder. Main risk: getting caught with multiple levels of the wrong-side inventory as resolution approaches.

### Sources
- [Grid Trading Explained (XS)](https://www.xs.com/en/blog/grid-trading/)
- [Bitsgap grid strategy](https://bitsgap.com/blog/grid-trading-strategy-explained-how-to-profit-in-any-market-in-2026)
- [Stevens Institute research on crypto grid trading](https://fsc.stevens.edu/cryptocurrency-market-making-improving-grid-trading-strategies-in-bitcoin/)

---

## 11. Delta-Neutral / Cross-Venue Hedged Market Making

### Mechanism
Market maker provides liquidity on a less liquid venue, then immediately hedges the resulting inventory on a more liquid correlated venue. Net position is delta-neutral; profit is the spread captured on the maker venue.

Classic example: make markets on a small altcoin CEX, hedge inventory on Binance perps for the same asset.

**In binary prediction markets:** after filling a buy-Up maker order at 55¢, can we hedge? Theoretically:
- Short BTC futures to hedge the directional component embedded in the "Up" contract
- Not a perfect hedge: the binary option payoff is not linear in BTC price (it's a digital)

### Capital / Infra / Latency
Needs capital on both venues. Hedge needs to execute within the oracle-lag window (5–20s) to be effective.

### Applicability to Polymarket Binary
**NOT APPLICABLE** in traditional form. Binary contracts don't have a simple linear hedge. Delta of a digital option is `N'(d₂)` — near 50¢, this is the highest (most sensitive), but:
1. No Polymarket "futures" exists to hedge on
2. BTC spot/perp hedge is imperfect (binary payoff ≠ linear BTC exposure)
3. Our actual edge is the binance→chainlink oracle lag: the signal IS the hedge signal, but we can't hedge the binary outcome directly

**Partial application:** If we hold Up contracts and want to reduce delta exposure, short BTC perps for the notional equivalent of the digital delta. This is a gamma/delta approximation hedge — valid in theory but complex to calibrate for 1m/5m resolution windows.

### Sources
- [DWF Labs hedging guide](https://www.dwf-labs.com/news/understanding-market-maker-hedging)
- [Multi-currency inventory risk (arXiv:2207.04100)](https://arxiv.org/pdf/2207.04100)
- [Multi-asset rough Heston MM (arXiv:2212.10164)](https://arxiv.org/pdf/2212.10164)

---

## 12. Maker Rebate Harvesting

### Mechanism
Post resting limit orders specifically to earn the maker rebate from taker flow, even if spread P&L is zero. The rebate is:

```
rebate_per_fill = 20% × taker_fee = 20% × (0.07 × p × (1-p))
                = 0.014 × p × (1-p)
```

| Price (p) | Taker fee/contract | Maker rebate/contract |
|---|---|---|
| 0.50 | $0.0175 | $0.0035 |
| 0.60 | $0.0168 | $0.0034 |
| 0.70 | $0.0147 | $0.0029 |
| 0.80 | $0.0112 | $0.0022 |

Note: this is the `0.07 × p × (1-p)` fee curve from docs. Our CLAUDE.md notes production may still use "2% on winning profit only" for crypto up-down markets. **Must verify which fee curve is active by checking `feesEnabled` and `feeRate` on live market via `getClobMarketInfo(conditionID)`.**

Pure rebate harvesting (post near mid, hope to get filled) without directional filter = symmetric MM = already killed. But **rebate as a component** of directional-tilted maker is meaningful: it provides a floor income on every fill, even on slugs where the spread alone would be marginal.

### Applicability
**APPLICABLE** as a component, not standalone. Directional-tilted maker gets rebate as bonus income on top of the spread alpha from the oracle-lag signal.

### Sources
- [Polymarket maker rebates official docs](https://docs.polymarket.com/market-makers/maker-rebates)
- [Axon.trade fee/rebate math](https://axon.trade/fees-rebates-and-maker-taker-math)

---

## 13. Symmetric Pure Market Making

### Mechanism
Post bid and ask symmetrically around mid-price. Earn the spread on round-trip fills. Standard Hummingbot PMM strategy.

### Applicability to Polymarket Binary
**ALREADY KILLED.** Our empirical finding:
- ~20% of fills are adverse-selected (informed oracle arbers know true price)
- Each adverse fill = near-full contract loss (fills just before resolution at wrong price)
- $0.03–0.06 spread income cannot cover ~20% × ~$0.50 adverse fill rate
- All symmetric/passive sleeves tested: net-negative

This result is consistent with Glosten-Milgrom: if `μ` (informed trader fraction) is high (oracle arbers), the break-even spread exceeds the market spread, making passive MM structurally unprofitable.

### Sources
- Our backtest: `strategy_lab/reports/MAKER_ARB_CENSORING_REVERSAL_2026_05_28.md`
- [startpolymarket.com: "adverse selection can vaporize months of rebate income in a single market"](https://startpolymarket.com/strategies/market-making/)

---

## 14. Queue Position Optimization

### Mechanism
In price-time priority LOBs, orders are filled in FIFO order at each price level. Being first in queue = guaranteed fill; being last = high fill uncertainty. HFT firms invest heavily in co-location and sub-microsecond connectivity to get queue priority.

### Applicability to Polymarket Binary
**NOT APPLICABLE.** Polymarket CLOB is:
1. **Off-chain** (orders matched off-chain, settled on-chain) — no traditional queue model
2. **No co-location** — AWS eu-west-2 is the matching engine; all participants connect over the internet
3. Our Ireland latency (<2ms) is already near-optimal for the London server
4. Queue priority at the same price is not a differentiating factor when all participants are internet-connected

---

## 15. Market Making on Binary Options — Option-Theoretic Framework

### Mechanism
Digital/binary options have delta `Δ = N'(d₂)` and gamma `Γ = −N''(d₂)/σ√τ`. Near expiry (small `τ`) and near the money (`p ≈ 50%`), delta and gamma are highest — the option is most sensitive to the underlying price.

**Theoretical spread for a binary option market maker:**
```
Spread ≥ σ√τ · φ(d₂) · (hedging_cost_per_delta + adverse_fill_cost)
```
where `φ(d₂)` is the standard normal pdf at `d₂`. This spread is widest at-the-money near expiry — exactly when oracle arbers are most active.

**Implication:** Near 50¢ with short time to expiry, the "fair" spread for a market maker to break even on hedging alone is very wide. The Polymarket dynamic fee (reaching 3.15% on a 50¢ contract) is calibrated to make taker arbitrage unprofitable at these parameters — which is equivalent to saying symmetric MM was impossible before the fee.

### Applicability to Polymarket Binary
**PARTIAL (analytical tool).** Use the digital option delta/spread formula to:
1. Calibrate the minimum spread that compensates for unhedgeable resolution risk
2. Understand why spread must widen as `p → 0.5` and `τ → 0`
3. Size maker orders inversely proportional to `Δ` (higher delta near 50¢ = more risk = post less size)

### Sources
- [HangukQuant: Digital Option Market Making on Prediction Markets](https://www.research.hangukquant.com/p/digital-option-market-making-on-prediction)
- [Dynamics of a Binary Option Market (arXiv:2206.07132)](https://arxiv.org/pdf/2206.07132)

---

## Special Focus: The Directional-Tilted Maker Idea — Academic Support Summary

The concept of posting maker orders only on the signal-favored side is formally supported by:

| Paper | Key result for our idea |
|---|---|
| **Cartea-Wang (2020)** | When alpha signal is non-zero, optimal strategy posts ONE-SIDED limit orders; when alpha flips, switch sides |
| **Fodra-Labadie (2012)** | Non-symmetric orders for non-martingale mid-price yield >15% PnL improvement; inventory-risk-aversion parameter scales with resolution risk |
| **Glosten-Milgrom (1985)** | Break-even spread must compensate for informed-trader fraction; if WE are the informed party (via binance signal), we can make markets at lower spread than competitors |
| **VPIN / OFI (Easley et al., 2012)** | Monitor toxicity; pause quoting when other informed agents (oracle arbers) are present |
| **Polymarket dynamic fee design** | Polymarket itself validates the logic: they set taker fees highest at 50¢ (most informed-flow risk), funding rebates for makers who provide liquidity at that risk point |

**Single best insight for our directional-tilted maker:**

> From Cartea-Wang (2020): "When the alpha signal is positive (negative), the strategy tends not to post sell (buy) limit orders to avoid adverse selection costs." — This is the exact rule for our setup. **We are the informed maker (we have the binance signal before oracle update). We should only post on the side where we'd be willing to hold the contract.** We have the signal edge; symmetric posting throws half that edge away by also making on the side where we'd be adversely selected if filled.

---

## Implementation Checklist for Directional-Tilted Maker

Based on the research above, a minimum viable implementation:

1. **Signal:** `α = tanh(binance_move_pct / σ_5s)` — maps Binance move to [-1, +1]
2. **Entry gate:** Only post when `|α| > 0.3` (signal is meaningful) AND `|p_fair - 0.5| < 0.35` (not already too far resolved)
3. **Quote:** Post bid on signal-favored side at `p_fair − half_spread` (half_spread = max(2¢, digital_option_spread))
4. **Cancel trigger:** Cancel within 500ms of `α` sign flip OR Binance 1s bar closes against signal
5. **Inventory cap:** Max N contracts per slug (N = 20 suggested for testing); stop adding when reached
6. **Resolution guard:** Cancel ALL orders when slug has < 60s remaining (oracle update imminent, fills become pure lottery)
7. **VPIN gate:** If recent 60s taker imbalance > 80% one-directional, pause — oracle arbers are active and the book is being swept
8. **Rebate tracking:** Log `0.014 × p × (1-p)` per fill as separate P&L component

---

## Appendix: Polymarket Fee Curve Reference (Verified from Docs)

```
taker_fee = C × 0.07 × p × (1-p)    [C = shares traded, p = price]
maker_fee = 0
maker_rebate_per_fill = 0.20 × taker_fee_equivalent
                      = 0.20 × C × 0.07 × p × (1-p)
                      = C × 0.014 × p × (1-p)
```

**Note from CLAUDE.md:** Live production may use "2% on winning profit only" (LegacyConfig) rather than the `0.07 × p × (1-p)` curve — verify `feesEnabled` per market via `getClobMarketInfo`. The docs above show `feesEnabled=true` for crypto markets as of 2026, feeRate=0.07. Reconcile against live trading events before assuming rebate math.

---

*Sources consolidated: Avellaneda-Stoikov (2008), GLFT (2013), Glosten-Milgrom (1985), Ho-Stoll (1981), Fodra-Labadie arXiv:1206.4810, Cartea-Wang IJTAF 2020, Easley-LdP-O'Hara VPIN (2012), Polymarket docs, startpolymarket.com, HangukQuant digital option MM, FinanceMagnates Polymarket dynamic fee, hftbacktest OFI tutorial, Foucault-Kozhan-Tham toxic arbitrage (2014), BIS WP 1115.*
