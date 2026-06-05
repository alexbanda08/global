# Binary Hedging & Exit Research — 2026-05-30

**Scope:** hedge/exit tactics for high-WR (65-90%) short-duration binary positions on Polymarket
crypto up/down markets (BTC/ETH/SOL, 5m/15m windows). Entry vwap 0.50–0.90, $5 stake,
hold-to-resolve is baseline. Mid-window exit = selling token back on CLOB; hedge = buying
opposite token or taking perp position on Binance/HL.

**Pre-registered finding from internal study:** naive stop-loss / take-profit / late-hedge all
underperform hold-to-resolve on high-WR short binaries. This report investigates whether a
smarter variant exists.

---

## 1. Professional Mechanics: Betfair Green-Up / Cash-Out

### How it works
Betfair exchange (and any CLOB binary): you entered by buying YES at price p₀. If YES drifts to
p₁ > p₀ you can sell at p₁ ("green up") and lock a guaranteed profit regardless of resolution.

**Profit lock formula:**
```
locked_profit = N × (p₁ - p₀) - 2 × half_spread_cost
```
where N = shares held, half_spread_cost = (ask - mid) you pay crossing the book.

**+EV condition:**
```
(p₁ - p₀) > 2 × half_spread_cost + commission_per_share
```
On Betfair: commission 2-5% of net winnings; native Cash-Out adds ~2% haircut vs manual.
On Polymarket crypto: no taker commission on crypto up/down markets (feeRate ≈ 0, per
2026-05-22 canonical verification — "2% on profit only" production behaviour). So:
```
+EV condition collapses to: (p₁ - p₀) > 2 × half_spread  (Polymarket-specific)
```

### Near-expiry micro-structure facts (arXiv 2604.24366, Dubach 2026)
- **Depth decays near resolution**: slope 0.55 on log(seconds-to-close) within category — ~6%
  less depth per 10× reduction in time-to-close. Books get shallower as resolution approaches.
- **Longshot spread premium**: mid-price spread ≈ 400 bps in [0.4, 0.6]; climbs to 1300–1800 bps
  below 0.10. At high-probability side (0.85–0.95) spreads are tighter (roughly 150–300 bps by
  the asymmetric pattern), but absolute cost still 1.5–3 cents per $1 token.
- **Feed vs on-chain**: Lee-Ready direction inference only 59% accurate — backtest exit costs
  derived from WS feed alone are noisy. Use on-chain fills for PnL verification.

**Implication for our setup:** At token price 0.85 (winning position), half-spread ≈ 1.5–2.5¢.
A lock at 0.85 vs resolution at 1.00 sacrifices 15¢ upside but eliminates oracle/resolution
risk. Break-even: p₁ must exceed p₀ by > 3–5¢ before selling is EV-neutral. For entries at
0.55–0.65 that move to 0.85+ during the window, there IS a meaningful locked-profit window.

---

## 2. Partial Cash-Out / Scaling Out When Winning (token at 0.85, minutes left)

### Mechanics
Sell fraction α of position at current price p₁. Residual (1-α) holds to resolution.

**Expected PnL of partial exit:**
```
E[PnL_partial] = α × N × (p₁ - p₀ - spread_cost)            # locked portion
               + (1-α) × N × [WR × (1 - p₀) - (1-WR) × p₀] # residual hold EV
```
where WR = true win probability at decision time.

### When is partial exit +EV vs hold?

Full hold EV = N × [WR × (1 - p₀) - (1-WR) × p₀]

Partial exit EV > full hold EV iff:
```
α × (p₁ - p₀ - spread_cost) > α × [WR × (1 - p₀) - (1-WR) × p₀]
i.e.: p₁ - spread_cost > WR × 1 + (1-WR) × 0 = WR
i.e.: p₁ > WR + spread_cost
```
**Key insight:** partial exit beats hold only when the MARKET's implied probability (p₁) EXCEEDS
your TRUE win probability (WR) by more than the spread cost.

For high-WR sleeves (WR ≈ 0.75–0.90):
- If token is at 0.85 and WR = 0.80 → market overprices, sell is +EV (but rarely occurs on our
  signal, since our entries are at fair or slight discount).
- If token is at 0.85 and WR = 0.88 → market still underprices, hold is +EV.

**Practical conclusion:** For a strategy entering at 0.55–0.70 and with 75-90% true WR, the token
at T+3min is typically 0.75–0.90. The market has repriced, but our TRUE WR is still the anchor.
Partial exit is only EV-positive if the price moves so far that it EXCEEDS our estimated WR.
Threshold: `sell when token > WR + spread_cost` (e.g., WR=0.80 → sell when token > 0.83).

**Volatility / time-to-expiry conditions:**
- HIGH BTC volatility remaining (>0.3% in last 2m kline): resolution is uncertain; holding full
  position retains variance AND tail risk. A partial sell at 0.80+ locks some profit.
- LOW time remaining (<60s): token should be very close to WR. Spread cost (1.5-2.5¢) eats most
  of the profit from a partial sale. Exit is rarely justified.
- MOMENTUM REVERSAL signal (e.g., 30s kline flips direction): if our WR model would drop below
  current token price, a sell/partial-sell is +EV.

---

## 3. Recovering a Losing Position (token at 0.30)

### Options & EV analysis

**3a. Average down (buy more at 0.30)**
Standard Kelly logic: if WR > 0.30, buying more is +EV. But it increases exposure.
For a sleeve with WR=0.75 entering at 0.55 then token at 0.30 → rare scenario (market has moved
strongly against signal). Buying at 0.30 has EV = 0.75 - 0.30 = +0.45/share gross. But signals
are correlated — if token at 0.30 mid-window, the strong BTC move against us ALSO means actual
WR may have declined. Conditional WR needs recomputation. Only valid if:
```
conditional_WR(mid_window, price=0.30) > 0.30 + spread_cost
```
Data available to test: join L25 book (token price at T+2m) to actual resolution outcomes.

**3b. Buy opposite token (lock)**
Buy DOWN at (1 - 0.30) = 0.70. Combined cost: 0.55 (UP entry) + 0.70 (DOWN lock) = $1.25/share
for guaranteed $1.00 payout = guaranteed -$0.25 loss. This is ALWAYS -EV for a normal binary.
Exception: if UP + DOWN > $1.00 due to market dislocation (sum > 1), buying both is EV-positive.
For our 5m crypto markets: UP_ask + DOWN_ask > 1.00 is common in thin-book states. If
UP_ask + DOWN_ask < 1.00 (rare), an arb lock is available.
**Testable:** scan L25 book for windows where sum_asks < 0.99 — these are free-lock opportunities.

**3c. Perp hedge (short BTC perp against DOWN token)**
If holding DOWN at 0.55 entry and token has dropped to 0.30 (BTC moved up strongly), shorting
BTC perp partially replicates the DOWN payoff. BUT:
- Binary resolves on Chainlink price at EXACT window close: resolution is a point-in-time event,
  not a continuous P&L.
- Perp funding on Binance: ~0.01%/8h on average, but during high-volatility can be ±0.1%.
- For a 5-minute window, funding cost is essentially zero (5m = 1/2880 of 8h cycle ≈ 0.003 bps).
- Perp hedge ratio: delta of binary near expiry = N(d₂) in Black-Scholes for a digital. For a
  binary at 0.30 with 2m remaining and BTC vol ≈ 1%/5m, delta ≈ 0.25–0.35. Hedge ratio ≈ 0.30
  of notional.
- Cost: slippage on entry + slippage on exit. Binance BTC/USDT perp mid-to-taker spread ≈ 0.5–1
  bps. On $5 notional: ~$0.0003 round trip. Negligible.
- **Benefit:** Reduces variance on the 20% of trades that lose. BUT for hold-to-resolve, E[PnL]
  is unchanged by a fair-priced hedge — it only reduces variance. EV-neutral if hedge is fair;
  EV-negative if bid-ask and funding drag.
- **Practical +EV case:** If perp is mispriced relative to Chainlink at window close (e.g.,
  perp price > Chainlink oracle by >0.1%), then a short perp + hold DOWN = carry trade.
  We have both HL klines and chainlink_rtds to test this.

---

## 4. The Math of Hedging a Binary Near Expiry

### Delta of a binary (cash-or-nothing digital option)
```
Δ_binary = ∂P/∂S = φ(d₂) / (S × σ × √T)
```
where φ = standard normal PDF, d₂ = [ln(S/K) + (r - σ²/2)T] / (σ√T).

**Near expiry (T → 0):** Δ spikes. At S ≈ K (at-the-money), Δ → ∞. Binary delta is
HIGHEST near expiry when near-the-money — making delta hedging extremely expensive near T=0.

**Practical consequence:** Attempting to delta-hedge a near-ATM 5m binary with a perp in
the last 60–120 seconds requires very large and rapidly-changing positions. This is the
"terminal risk concentration" problem identified by Dubach (2026) and confirmed in deep-hedging
literature. For deep-ITM positions (token at 0.85), Δ is smaller and more stable → hedging is
more practical.

### Free-middle / lock-and-win condition
Hold UP (cost p_up) + buy DOWN (cost p_dn). Total cost = p_up + p_dn.
If p_up + p_dn < 1.00: buy both → guaranteed $1.00 payout → profit = 1.00 - (p_up + p_dn) > 0.
If p_up + p_dn = 1.00: break-even lock.
If p_up + p_dn > 1.00: normal state on Polymarket; locking is -EV.

Our canonical L25 data has ask prices for both sides at every snapshot. We can compute
`sum_ask = UP_ask + DOWN_ask` at each timestamp and identify when sum_ask < 1.00.
Expected frequency: very rare for liquid crypto markets. Most likely during rapid oracle
updates or thin-book states.

---

## 5. Cross-Instrument Hedge: Perp Delta Hedge

### Does anyone do this profitably?
Academic evidence: "only a minority of market makers hedge consistently; most rely on rapid
inventory rebalancing" (Hu et al. 2025). Deep-hedging literature: continuous rebalancing costs
are prohibitive for short-dated instruments.

### Our specific case (5m binary, $5 stake)
- Binary delta at entry (token ≈ 0.65, T=5m): ~0.30–0.40 of notional
- Hedge notional: 0.35 × $5 = $1.75 equivalent BTC exposure
- Binance perp fees: 0.02-0.05 bps maker/taker on ~$1.75 → $0.0001 — negligible
- Rebalance frequency: if we rebalance at T+2m (once): trivial cost
- Variance reduction: meaningful IF the binary PnL has high covariance with BTC spot.
  For a 5m UP/DOWN market, the binary payoff IS determined by BTC spot → correlation ≈ 1.0 in
  expectation. A correctly-sized short perp would nearly perfectly offset a losing trade.

### Net EV impact of perp hedge
- Cost ≈ $0.0002/trade (negligible)
- Variance reduction: significant (cuts losing leg's $3.25 loss to near zero)
- BUT: on winning trades, the perp hedge LOSES money (short perp in an up-move)
- Net expected PnL change = -(hedge ratio × perp_expected_return) ≈ 0 (if perp is fairly priced)

**Key finding:** Perp hedge is EV-neutral at fair prices but reduces variance. For a high-WR
sleeve (80% WR) it's actually DILUTIVE to CAGR growth because the wins (80%) get reduced by the
losing perp leg while losses (20%) get partially recovered. Kelly criterion says: fractional
Kelly + no hedge maximizes long-run growth when WR > 0.75 and entry price is fair. Hedge only
adds value if: (a) we believe the position's true WR has dropped since entry (conditional WR
updating), or (b) the perp is mispriced relative to oracle.

---

## 6. Conditional WR Re-Estimation Mid-Window

**The real signal:** at T+2m into a 5m window, we have 2 more 1m klines. Can we recompute our
F7 RSI / momo signal and get a REVISED WR estimate for the remaining 3 minutes?

If revised_WR drops significantly (e.g., from 0.80 at entry to 0.55 mid-window due to reversal):
- Token market price may still be at 0.70 (slow to update).
- Selling at 0.70 when revised_WR = 0.55 → EV = 0.70 > 0.55 = +EV exit.
- This is "signal reversal exit" — the most theoretically sound reason to exit early.

**Formula for conditional sell decision:**
```
Exit if: token_price_now > revised_WR(T+k) + spread_cost
```

This is testable with our L25 data: compute F7 signal at T+2m and T+3m, compare to token
mid-price at same timestamps, and to final resolution outcome.

---

## 7. Ranked Shortlist: 5 Most Promising Testable Ideas

### Rank 1: Signal-Reversal Exit (Conditional WR Re-estimation)
**Tactic:** Recompute entry signal (F7 RSI / momo) at T+2m and T+3m into the window. If signal
would flip direction, sell token at current market price.
**+EV condition:** Sell when token_mid > revised_WR + spread_cost (~2-3¢).
**Testable:** Join L25 book snapshots at T+2m/T+3m to resolution outcomes. Compare P(win |
signal_flipped_mid) vs token_price_at_flip. If P(win) < token_price, exit is +EV.
**Data:** L25 books (native 10Hz, subsample_1hz=False) + klines_1m for re-derivation of signal.
**Parametrize:**
- `flip_threshold`: signal changes direction with confidence > X%
- `min_profit_locked`: only exit if token_price > entry_price + min_profit_locked
- `exit_fraction`: 0.5 or 1.0 (partial vs full)

### Rank 2: Free-Lock Scan (sum_asks < 1.00 arb)
**Tactic:** At any point mid-window, check if UP_ask + DOWN_ask < 1.00. If so, buy the
cheaper side → guaranteed profit of (1.00 - sum_asks) at resolution, regardless of direction.
**+EV condition:** Always +EV when sum < 1.00 by definition (subject to fill risk).
**Testable:** Scan entire L25 book history for timestamps where sum_ask < 0.99 (1¢ buffer for
slippage). Measure frequency, average edge, and whether a second order can fill.
**Data:** L25 books only. No klines needed.
**Expected frequency:** Low (<1% of snapshots) but risk-free when it occurs.

### Rank 3: Price-Exceeds-Entry-WR Partial Sell
**Tactic:** Sell X% of position whenever token_mid > WR_estimate + spread_cost, where WR is
the sleeve's historical win rate for this signal configuration.
**+EV condition:** Mathematical (derived in §2 above): p₁ > WR + spread_cost.
**Testable:** Using L25 intra-window price trajectories: for each fire, track token price at
T+1m, T+2m, T+3m, T+4m. Count how often price crossed above WR+3¢ threshold. Compute
PnL differential vs hold-to-resolve.
**Data:** L25 books (T+1m through T+4m snapshots) + resolution outcomes.
**Parametrize:**
- `sell_fraction`: 0.25, 0.50, 0.75, 1.0
- `WR_threshold_cushion`: 0.02–0.05 above historical WR
- `max_time_before_expiry`: don't exit within last 60s (spread widens, depth decays)

### Rank 4: Mid-Window Momentum Reversal Hedge via Opposite Token
**Tactic:** If holding UP and 1m kline at T+2m shows strong DOWN move (>0.5% BTC), buy DOWN
token to lock. Calculate locked PnL: (UP entry price + DOWN current price) vs 1.00.
**+EV condition:** Only if UP_price_paid + DOWN_current_ask < 1.00 AFTER the move (rare but
possible in a fast market where DOWN hasn't repriced yet).
**Testable:** Join L25 book to 1m klines. For each window where BTC moved >0.5% against signal
at T+2m, compute UP_entry_price + DOWN_ask_at_T+2m. Distribution of this sum vs 1.00.
**Data:** L25 books + klines_1m.
**Parametrize:**
- `reversal_threshold_pct`: BTC move needed (0.3%, 0.5%, 0.8%)
- `min_lock_profit`: only execute if sum_ask < 0.98

### Rank 5: Perp Variance-Reduction Hedge (Conditional on Mid-Window Reversal)
**Tactic:** Do NOT hedge at entry. Only hedge if at T+2m: (a) signal has reversed AND (b)
revised P(win) < 0.50. Short BTC perp (Binance) = hedge ratio × notional. Unwind at resolution.
**+EV condition:** EV-neutral on expectation, but reduces drawdown on losing trades. Best
deployed when: revised_WR < 0.50 but exit is too costly (token hasn't repriced yet).
**Cost structure:**
- Binance BTCUSDT perp: ~0.02 bps maker / 0.05 bps taker. On $5 notional = $0.0001–0.0003.
- Funding for 3m window: 3/480 × daily_rate × notional ≈ $0.00005 at normal rates.
- Perp slippage: negligible ($5 notional, deep BTC book).
**Testable:** For trades where T+2m signal reversal occurred AND final outcome = LOSE, compute
how much the perp hedge would have recovered vs how much it would have cost on winning trades.
**Data:** klines_1m (for hedge sizing) + HL/Binance perp prices + resolution outcomes.

---

## 8. Implementation Notes

### Backtest framework
All of the above are testable with existing canonical pipeline:
```python
from data.v4.canonical.load import (
    load_orderbook_l25_streaming,  # subsample_1hz=False mandatory
    load_klines, load_klines_asof,
    load_resolutions,
)
from strategy_lab.engine_v2 import LegacyConfig, fill_at_book, hold_pnl
```

For mid-window exit, need `sell_pnl_partial` from engine_v2.py (exists as `sell_pnl_partial`).

### Critical gotchas
1. **Do NOT use subsample_1hz=True** for L25 in backtest — production book is 10Hz.
2. **spread_filter must use cross-token definition** (`abs(up_vwap - (1-dn_vwap))`), not
   same-token bid-ask, to match live controller behavior.
3. **Fee model is 2%-on-profit-only** for production comparison (LegacyConfig). LiveMimicConfig
   uses 0.07×p×(1-p) which is conservative stress-test.
4. **Depth decay near expiry** (Dubach 2026): do not assume same book depth at T+4m55s as at
   T+0. Spread will be wider; adjust spread_cost estimate upward near expiry.
5. **Perp funding** during 5m window is negligible; basis risk (perp vs Chainlink oracle)
   is the main risk — verify using chainlink_rtds vs HL klines at resolution timestamp.

---

## Sources

- arXiv:2604.24366 — Dubach (2026), "The Anatomy of a Decentralized Prediction Market:
  Microstructure Evidence from the Polymarket Order Book"
  https://arxiv.org/abs/2604.24366
- arXiv:2412.14144 — "Application of the Kelly Criterion to Prediction Markets" (2024)
  https://arxiv.org/html/2412.14144v1
- Navnoor Bawa, "The Mathematical Execution Behind Prediction Market Alpha" (Dec 2025)
  https://navnoorbawa.substack.com/p/the-mathematical-execution-behind
- Betfair Trading: Greening Up mechanics
  https://apps.betfair.com/learning/greening-up-applying-maths-to-hedge-your-profit/
- Polymarket Docs: Prices & Orderbook
  https://docs.polymarket.com/concepts/prices-orderbook
- Jung-Hua Liu, "AI-Augmented Arbitrage in Short-Duration Prediction Markets" (Medium, 2026)
  https://medium.com/@gwrx2005/ai-augmented-arbitrage-in-short-duration-prediction-markets-live-trading-analysis-of-polymarkets-8ce1b8c5f362
- Benjamin-Cup, "Unlocking Edges in Polymarket's 5-Minute Crypto Markets" (Medium)
  https://medium.com/@benjamin.bigdev/unlocking-edges-in-polymarkets-5-minute-crypto-markets-last-second-dynamics-bot-strategies-and-db8efcb5c196
- Hu et al. (2025) on selective delta hedging by market makers
  https://www.aeaweb.org/conference/2026/program/paper/27z3hKsB
- arXiv:2509.07718 — "Hedging Options on Asset Portfolios against Just One Underlying Asset
  in the Presence of Transaction Costs" (2025)
  https://arxiv.org/pdf/2509.07718
