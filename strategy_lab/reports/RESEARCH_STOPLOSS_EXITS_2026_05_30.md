# Stop-Loss & Mid-Window Exit Research
## Evidence, Parameterization, and Verdict for High-WR Fixed-Expiry Binary Positions
**Date:** 2026-05-30  
**Scope:** Directional Polymarket BTC/ETH/SOL 5m & 15m CLOB binary markets, ~$5 stake, buy token at vwap 0.50–0.90, hold to resolution (win→$1, lose→$0)

---

## 1. Academic Foundation: When Do Stops Add vs. Destroy Value?

### Kaminski & Lo (2014) — *"When Do Stop-Loss Rules Stop Losses?"*
*Journal of Financial Markets* 18, pp. 234–254. [SSRN link](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=968338)

**Core theorem (proved analytically):**
- Under the Random Walk Hypothesis, a 0/1 stop-loss rule **always reduces expected return** for any positive-drift asset. There is no parameterization that recovers the lost EV.
- Under **momentum / regime-switching** return processes, stops can add value: they exit during persistent drawdown regimes before further loss accumulates. At monthly horizons, volatility-based stops added +50–100 bps/month on U.S. equity data (1950–2004); volatility-based stops added +1.5%/month on daily stock futures (1993–2011).
- **Stop-loss rules add zero value to mean-reversion strategies** — stops crystallize the loss at exactly the moment the strategy expects reversion. Applying them converts recoverable drawdowns into realized losses.
- **Slower-moving stops worked best** in all regimes tested; tight intraday stops performed worst.

**Implication for us:** Our 5m/15m binary payoff is structurally closer to fixed-horizon mean-reversion than to open-ended momentum (the contract resolves regardless). This tilts the prior against stops.

### Stop-Loss + Momentum in Crypto — Butt et al. (2023)
*Behaviour & Experimental Finance* 39. [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S2214635023000473)  
Tested stop-loss on momentum strategies across 147 cryptocurrencies (Jan 2015–Jun 2022). Stop-loss momentum **outperformed hold-momentum** on Sharpe, raw return, and alpha across all market states. However, this is **open-ended position holding with momentum drift** — not fixed-expiry binary payoffs. Not directly transferable.

### Institutional perspective (Breaking Alpha, Jan 2026)
Every stop creates a known exit point that market makers and HFTs exploit via "stop hunting." Stops also generate opportunity costs: positions that recover profitably get stopped out, converting temporary adverse moves into realized losses. The core paradox: stops are simultaneously essential for survival AND detrimental to performance — the balance depends entirely on **strategy type, holding period, and market regime**.

---

## 2. The Fundamental Math: Fixed-Expiry Binary Stops

### Why stops hurt a high-WR fixed-expiry binary

Let:
- `p` = base win rate (e.g., 0.75)
- `q = 1 - p` = base loss rate (0.25)
- `P_sl` = probability a winning trade hits stop before expiry (intra-window adverse excursion)
- Payout on win = `(1 - entry_price)` per token, fee deducted; payout on loss = `0 - entry_price`

Without stop: `EV = p*(1 - v) - q*v` where `v` = vwap entry  
With stop at threshold `s`:
```
EV_stop = p*(1 - P_sl)*(1 - v)          # winners that don't hit stop
        + p*P_sl*(-loss_on_stop)         # winners stopped out early (lose instead of win)
        - q*(1 - P_sl_loss)*v            # losers that don't hit stop (still lose)
        - q*P_sl_loss*stop_loss_amount   # losers stopped (save partial)
```
For a trade with p=0.75 and a stop that wrongly exits 20% of eventual winners:
- **EV_stop ≈ EV_base − 0.75 × 0.20 × (1 - v)** = pure EV destruction
- The only regime where stops recover EV: when `P_sl_loss` (stopping actual losers early) saves more than `P_sl` (stopping eventual winners).

**Key insight:** At vwap entry ~0.65 (our typical range), the token price path has a large upward pull from winner-reversion toward $1. Any stop placed near entry catches winners in intra-window dips. This is why our prior internal study found FIXED STOP-LOSS / TAKE-PROFIT / HEDGE-LATE all underperform HOLD in 8/10 tested sleeves.

### Black-Scholes analog for binary
A binary cash-or-nothing call near expiry has **positive theta** — time passing HELPS the winning position. An early exit discards the remaining option value (gamma). At T-120s of a 300s window, the token has already captured ~40% of its path toward $1; exiting at 0.85 forfeits the remaining expected appreciation if the bet is winning.

---

## 3. Volatility-Scaled / ATR-Based Stops

### Evidence
ATR-based stops (1.5×–2× ATR on 5m or 15m bars) outperform fixed-dollar stops in open-ended positions because they scale with realized volatility. For BTC intraday:
- 5m bar ATR is typically 0.08%–0.25% of spot price (roughly $35–$110 per BTC at $44k)
- ATR period 7–14 bars on minute charts is the standard; shorter = more reactive (more false stops)
- Standard parameterization: `stop_distance_pct = k × ATR_14bar_5m / entry_spot`, `k ∈ {1.5, 2.0}`

### For our binary token price path
Token price ATR is NOT the same as BTC spot ATR. At entry vwap=0.65 with 2.5 minutes remaining in a 5m window:
- Token price volatility ≈ `σ_spot × Δ_binary`, where `Δ_binary ≈ normal_pdf(d2)` at near-expiry is HIGH (gamma spike)
- Token ATR 1.5× on a 1m chart at 2.5-min-to-expiry gives a stop that is almost always hit by noise alone

**Verdict:** ATR stops are designed for open-ended positions. Mechanically applying them to fixed-expiry binary tokens at the 5m horizon will produce very high false-exit rates. Not recommended without strong tokenpath-specific recalibration.

**Testable parameterization if you want to try it:**
```python
# Compute token_price ATR over rolling 14 bars at 10s resolution
token_atr_14 = df['token_price'].rolling(14).apply(lambda x: (x.max()-x.min()))
stop_distance = 1.5 * token_atr_14.iloc[-1]
stop_level    = entry_price - stop_distance    # for "Up" token (long)
# trigger: if token_price < stop_level → sell at market
```
Backtest requires L25 native 10Hz data (`subsample_1hz=False`) to see realistic intrabook price paths.

---

## 4. Trailing Stops and "Give-Back" Rules

### Evidence
- Dynamic trailing stops (ATR-based, calibrated to local volatility) on 6h crypto trend-following achieved annualized Sharpe 2.41, max drawdown −12.7% over 36-month 2022–2024 period (QuantPedia adaptive trend study).
- Trailing stops in fixed-stop portfolio study produced **−8.1% cumulative return** in one equity study — i.e., worse than buy-and-hold with fixed stop.
- Trailing stop logic: after price moves `+k×ATR` in your favor, trail stop `k×ATR` below the high-water mark.

### For our setup
A trailing stop on a 5m binary token is almost paradoxical. If the token price rises from 0.65 → 0.85, a trailing stop at 0.85 − 1.5×ATR might be at ~0.75 — which is still above entry. The token resolves at $1 (win) or $0 (lose) in ≤5m. Trailing to 0.75 means you exit at 0.75 instead of collecting $1.00 on a winner.

**Realistic give-back rule:** "If token price exceeds 0.90, sell on any reversal back below 0.85" — but this only adds value if:
1. The token price mean-reverts back to 0.70–0.75 before expiry on enough winners (empirical question requiring path data)
2. The spread cost of the early exit < the give-back captured

**Testable parameterization:**
```python
# Trailing sell trigger: trail from high-water mark
high_water = entry_price
for t, price in enumerate(token_path):
    if price > high_water:
        high_water = price
    trail_stop = high_water - trail_distance   # e.g. trail_distance=0.08
    if price < trail_stop and price > exit_threshold:  # exit_threshold=entry+0.05
        sell_at(price)
        break
```
Grid-search `trail_distance ∈ {0.05, 0.08, 0.12, 0.15}` with L25 10Hz paths.

---

## 5. Take-Profit / Partial Scale-Out

### Evidence
- The 3-tier scale-out model (1/3 at first TP, 1/3 at resistance, 1/3 trail) is well-documented in equity/forex intraday trading.
- Academic finding: partial scale-out *almost always reduces total P&L in expectation* for strategies with positive drift toward TP — you're selling future expected value. Benefit is psychological / drawdown reduction, not EV-positive.
- For near-expiry fixed binary: **positive theta** (time decay helps winners) means selling early forfeits theta. The token price at T-60s on a winning trade is approximately `p_win × $1 − fee`, meaning market price ≈ current win probability. If you entered at 0.65 and your true edge drove win probability to 0.85, the token is now worth ~$0.83. Exiting at 0.83 vs. holding to $1.00 means you collected 0.83−0.65=$0.18 instead of expected $0.35 (= 0.85 × $0.35). You gave up **49% of your expected gain**.

### When partial exits ARE +EV for us (narrow conditions)
Only if both:
1. **Token vwap has rallied to ≥0.92** (very deep in the money, near-certain win) AND
2. **Spread cost of selling < remaining expected appreciation** (i.e., win probability already >95%)

At vwap=0.92 with 30s to expiry and p_win=0.97:
- Remaining EV if held: 0.97 × 0.08 = $0.078/token (net of fee)
- Sell now at 0.92 − spread(~0.01) = $0.91 realized gain vs. holding at $0.92 expected → hold still marginally better
- **Exception:** if there is a meaningful tail-risk event (news spike, oracle delay) that could crash the token — then lock at 0.92 is rational risk management

**Testable parameterization:**
```python
# Sell entire position if token crosses 0.92 with T < 60s remaining
if token_price >= 0.92 and seconds_to_expiry < 60:
    sell_at_bid()
```
Only test on very-high-WR sleeves (WR > 85%) where this condition fires frequently enough for statistical significance.

---

## 6. Time-Based Exits and Signal-Reversal Exits

### Evidence
- Time-based exits (close position at T-X seconds regardless of P&L) have documented support in algorithmic trading: if thesis hasn't proven correct by T% of the window, the thesis likely failed.
- **The "4-minute rule" for Polymarket 5m** (Medium, Apr 2026): watch first 4 minutes for directional persistence; enter in minute 4 for the 5th-minute close. Momentum in short binary windows persists because liquidity is insufficient to correct mispricings before expiry.
- Signal-reversal exits (exit when RSI/momentum flip direction): RSI on 5m chart, period 9-10 with 75/25 levels. RSI reversal alone: 50–60% WR. Our strategy fires at 65–90% WR — reversal signal would mostly fire against us. **Signal-reversal exits for high-WR entries are net-negative** (confirmed internally: "1s RSI/MACD/CCI gates — no-ops (~98% agree with the move; the move IS the signal)").
- **Order flow imbalance (OFI)** = `(Q_bid − Q_ask) / (Q_bid + Q_ask)` predicts near-term mid-price changes with R²=0.65 (Cont et al. 2014). IR > 0.65 predicts price increase within 15–30 min (58% accuracy). For 5m binary tokens this translates to: a flip in OFI toward the losing side mid-window is a weak but measurable reversal signal.

### Testable time-based exit parameterization
```python
# T-X exit: if entry at T=0 of 300s window, exit at T=240 (60s before close)
# Only profitable if: expected drift in final 60s is negative for our position
# (test empirically on token price paths conditioned on WR of the sleeve)
if elapsed_seconds >= 240:
    sell_at_bid()
```
Grid search `X ∈ {30, 60, 90, 120}` seconds-before-expiry. Hypothesis: early exit at T-30s may capture token price close to $0.90–0.95 without spread risk from final-second volatility spikes.

**Testable signal-reversal exit (weak signal):**
```python
# OFI reversal: if OFI flips from > 0.3 to < -0.2 mid-window
# Combined with token price > entry + 0.10 (only protect a gain)
ofi = (q_bid - q_ask) / (q_bid + q_ask)
if ofi < -0.20 and token_price > entry_price + 0.10:
    sell_at_bid()
```

---

## 7. The Crucial Question: Can ANY Exit Rule Beat Hold-to-Expiry After Spread+Fees?

### Mathematical answer
For a position with:
- Known binary payoff ($0 or $1) at fixed time T
- True win probability p > 0.5
- Entry price v ∈ (0, 1)
- Edge = p − v > 0

The expected value of holding = `p × (1 − v) − (1 − p) × v = p − v` (ignoring fees)

**An early exit at price `m` (mid-window token price) has EV = `m − v`**

This beats hold IFF: **`m − v > p − v`**, i.e., **`m > p`**

Interpretation: the market's implied probability (token price `m`) must be **strictly greater than your true win probability `p`**. This can only happen if:
1. The market has temporarily over-priced the token beyond your edge estimate (mean-reversion opportunity — but with 1.8% fee round-trip + spread ≈ 1.2%, this requires m > p + ~0.025), OR
2. A negative signal arrived after entry that lowered your estimate of p below m (exit is defensive, not alpha-seeking)

**Conditions where early exit is mathematically +EV:**

| Condition | Mechanism | Testable Signal |
|-----------|-----------|-----------------|
| Token price > 0.92 with T < 60s | Residual EV < spread cost of holding | Price level + time threshold |
| Negative OFI shock mid-window reverses underlying price | p drops below current m | L25 OFI flip + BTC 1s kline reversal |
| Volatility spike (ATR expansion) after entry | Fat-tail risk materializes; p conditional drops | ATR on 1s Binance klines mid-window |
| Underlying spot reversal > 2× entry return (2m ret flip) | Entry momentum signal invalidated | BTC `ret_2m` polarity flip post-entry |

### Polymarket's actual spread cost context
- Taker fee on crypto markets as of March 2026: **1.80%**
- Bid-ask spread on liquid 5m markets: ~1.2–2.0% (narrowed from 4.5% in 2023)
- Round-trip cost of an early exit (sell mid-window + the original buy): **~3–4% total**

For a position entered at vwap=0.65 with true p=0.75:
- EV of hold = 0.75 − 0.65 = $0.10/token
- Early exit at 0.73 (mid-window, market pricing you at ~73%) = 0.73 − 0.65 − 0.018 (fee) − 0.01 (half-spread) = **$0.052** vs $0.10 hold → **hold wins by $0.048**
- For early exit to win: must exit at ≥ 0.75 + 0.028 = **0.778**, meaning the market must have priced the token beyond your true edge

**Conclusion: Hold dominates unless you have a mid-window signal that your true p has dropped below the current token price by more than the round-trip cost.**

---

## 8. QuantPedia Polymarket Mean-Reversion Evidence (April 2026)

QuantPedia study (April 2026) on Polymarket binary contracts using 10-min sampled data, 12 strategy variants:

- Mean-reversion signals generate **positive alpha under passive limit-order execution (zero-spread)**
- Under **10 bps friction**, performance degrades severely: the best zero-spread strategy (Sharpe +2.97) becomes the worst performer (Sharpe −2.60) — a 5.57-point degradation
- Shorter lookback + lower holding periods consistently underperform longer-horizon strategies when friction is included
- **Direct application to our setup:** The 5m window is too short for mean-reversion exits to overcome 1.8% taker fees unless using passive limit orders exclusively

---

## 9. Ranked Shortlist of Testable Exit Rules

**Rank by expected incremental value for our specific setup (high-WR, 5m/15m, fixed binary, L25 book data available):**

### Tier 1 — Most Likely to Add Value (test first)

**Rule A: Deep-ITM time exit (T-30s, token ≥ 0.92)**
- Condition: token price ≥ 0.92 AND seconds_to_expiry ≤ 30
- Rationale: residual EV of ~$0.08 × win_prob vs. risk of last-second volatility spike; fee cost < residual risk for very-high-WR sleeves
- Parameterize: threshold ∈ {0.88, 0.90, 0.92, 0.95} × time_cutoff ∈ {15s, 30s, 60s}
- Data needed: L25 10Hz token price paths in final 60s, by sleeve and entry vwap bucket

**Rule B: Underlying spot reversal stop (BTC 1s ret_2m flip)**
- Condition: if BTC `ret_2m` flips polarity (was positive at fire, now negative) AND magnitude > 1× entry_ATR
- Rationale: the primary entry signal (Cyclops/F7 RSI momentum on BTC) is falsified; p conditional has dropped
- Parameterize: reversal_threshold_bps ∈ {5, 8, 12, 20}; apply only when T > 60s remaining (gives time to exit)
- Data needed: Binance 1s klines intra-window, token price at time of reversal detection

### Tier 2 — Moderate Expected Value (test second)

**Rule C: Trailing stop from high-water mark (protect realized gain)**
- Condition: token_price > entry + 0.15 → trail at high_water − 0.10
- Rationale: protects a large profit; only meaningful if token price exceeds 0.80 mid-window
- Parameterize: trail_distance ∈ {0.05, 0.08, 0.12}; min_gain_before_arm ∈ {0.10, 0.15, 0.20}
- Expected drag: negative EV on average (stops winners), offset by occasional saves

**Rule D: OFI reversal gate (L25 order flow)**
- Condition: order_flow_imbalance flips from > +0.30 to < −0.20 AND token_price > entry + 0.05
- Rationale: directional order flow reversal reduces conditional p; protect partial gain
- Parameterize: OFI_threshold_exit ∈ {−0.15, −0.20, −0.30}; rolling window ∈ {10s, 20s, 30s}
- Data needed: L25 book snapshots at 10Hz (bid/ask depth available in L25)

### Tier 3 — Low Expected Value / Speculative (test last)

**Rule E: Fixed stop-loss at entry − 0.12**
- Condition: token_price < entry_price − 0.12 → sell
- Evidence from internal study: stops underperform hold in 8/10 sleeves; this stops losers too late and stops winners early
- Only test on sleeves with WR < 65% or very wide entry vwap (> 0.80)

**Rule F: Time-based exit at T-60s unconditionally**
- Condition: at 240s elapsed in a 300s window, always sell
- Rationale: captures ~80% of window path value while avoiding final-second oracle/resolution risk
- Expected drag: forfeits final 60s of positive theta on winners; may help on 15m sleeves only
- Parameterize: exit_at_elapsed ∈ {200s, 240s, 270s} for 300s windows; {800s, 840s, 870s} for 900s windows

---

## 10. Implementation Notes

### Data requirements
All rules above require **L25 native 10Hz** (`subsample_1hz=False`) token price paths. Do NOT use 1Hz subsampled — this is the same mistake that made V5 backtest place thousands of fires while live placed zero (confirmed 2026-05-27).

### Fee model
Use `engine_v2.LegacyConfig` (2%-on-profit-only) for comparison to production. For early-exit PnL calculation, the fee is on the buying leg only (you sold at a gain = fee applies to the profit portion). The sell-out leg is a new taker order at 1.8% of the sell amount under new fee rules — verify which fee regime applies on the live account.

### Cross-token spread check
Production controller uses cross-token spread = `abs(up_vwap − (1 − dn_vwap))`. Early exits bypass this check — verify that the exit order can be placed (book must have reasonable depth on the buy side of the opposite token or sell side of the same token).

### Statistical power
5m BTC sleeve has ~36 fires/21d in Cyclops validation set. Testing 2×2 = 4 variants of Rule A needs ~150+ fires for 80% power at expected effect size ±$0.05/trade. Run across all 3 assets and both timeframes pooled where rule logic applies identically.

---

## Summary

The academic and empirical consensus is clear for our setup:

1. **Stops destroy EV in mean-reverting and high-WR fixed-horizon contexts** (Kaminski & Lo, internal study, QuantPedia Polymarket study). Our prior internal finding that HOLD wins 8/10 sleeves is consistent with theory.

2. **The only mathematically valid early-exit regime** is when the market has priced the token *above* your true edge estimate (exit at a premium), OR when your entry signal has been falsified mid-window (BTC momentum reversal).

3. **For 15m sleeves specifically**, HEDGE_LATE showed marginal benefit (+$0.395/tr for BTC_15M sleeves) in prior internal tests — the longer window allows real adverse drift to develop, making conditional late-exits worth exploring.

4. **Rule A (deep ITM + T-30s)** and **Rule B (BTC momentum reversal)** are the highest-priority tests. Both are testable on existing canonical data with L25 10Hz paths + Binance 1s klines.

---

## References

- Kaminski, K.M. & Lo, A.W. (2014). *When Do Stop-Loss Rules Stop Losses?* Journal of Financial Markets 18, 234–254. [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=968338)
- Butt, H.A. et al. (2023). *Stop-loss rules and momentum payoffs in cryptocurrencies.* Behavioural and Experimental Finance 39. [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S2214635023000473)
- QuantPedia (April 2026). *Exploiting Mean-Reversion in Decentralized Prediction Markets.* [QuantPedia](https://quantpedia.com/exploiting-mean-reversion-in-decentralized-prediction-markets-evidence-from-polymarket-binary-contracts/)
- Medium/Benjamin Cup (2026). *Unlocking Edges in Polymarket's 5-Minute Crypto Markets.* [Medium](https://medium.com/@benjamin.bigdev/unlocking-edges-in-polymarkets-5-minute-crypto-markets-last-second-dynamics-bot-strategies-and-db8efcb5c196)
- Breaking Alpha (2026). *Stop-Loss Mechanisms in Institutional Trading Systems.* [breakingalpha.io](https://breakingalpha.io/insights/stop-loss-mechanisms-institutional-trading-systems)
- Optimal Stopping Theory in Trading. [MDPI Finance](https://www.mdpi.com/2227-7072/10/4/96)
- Cont, R. et al. (2014). Order flow imbalance effects. [ScienceDirect intraday crypto momentum](https://www.sciencedirect.com/science/article/abs/pii/S1062940822000833)
- Polymarket Fees Documentation (2026). [docs.polymarket.com/fees](https://docs.polymarket.com/polymarket-learn/trading/fees)
- Internal: `strategy_lab/engine_v2.py`, exit policy audit (HOLD wins 8/10 sleeves), BTC_15M HEDGE_LATE finding (+$0.395/tr)
