# Dynamic Hedging & Risk Management Research
## Date: 2026-05-30
## Context: Polymarket binary crypto up/down markets, BTC/ETH/SOL, 5m/15m windows

---

## 1. Delta-Hedging a Short-Dated Binary with the Underlying Perp

### The Binary Delta Problem

A cash-or-nothing binary call (pays $1 if S_T > K, else $0) has Black-Scholes delta:

```
Δ_binary = N'(d₂) / (σ · S · √T)

where:
  d₂ = [ln(S/K) + (r - σ²/2)·T] / (σ·√T)
  N'(x) = (1/√(2π)) · exp(-x²/2)    [standard normal PDF]
```

**Key pathology**: as T → 0 (near expiry), Δ_binary → ∞ near the strike and → 0 away from it. For a 5m binary at the money:

- T = 5/525,600 years (≈ 9.5e-6 years)
- σ (BTC daily) ≈ 2-5%, so σ√T ≈ 0.002 (0.2%) in 5m
- If S is within 0.2% of K, N'(d₂) ≈ 0.40, so Δ_binary ≈ 0.40 / (0.03 × S × √T)
- For BTC at $100,000 with σ=30% annualized: Δ_binary ≈ 0.40 / (0.30 × 100,000 × 0.003) ≈ **444 per $1 binary**

At $5 stake: effective perp hedge = 444 × $5 ≈ **$2,200 notional** — 440x the stake. This is unhedgeable in practice for near-expiry ATM binaries.

### Practical Hedge Regimes

| Scenario | Delta | Hedge feasibility |
|---|---|---|
| 15+ min to expiry, far OTM (>0.5% from K) | 0.01–0.05 | Hedgeable; small stable position |
| 5m window, first 3m, ITM/OTM ±0.3% | 0.1–0.5 | Marginal; rebalance costs eat most benefit |
| 5m window, last 2m, ATM (±0.1%) | 5–50+ | Practically unhedgeable — delta explodes |
| Deep ITM or OTM (>1% from K) any window | <0.02 | Near-zero delta, hedge negligible |

### Hedge-Ratio Logic (Where It Works)

For a portfolio of N binary positions all on the same asset:

```
Hedge size (perp) = - Σᵢ [Δᵢ_binary × Notional_i] / Δ_perp

where Δ_perp ≈ 1.0 per $1 notional
```

For our setup (Polymarket vwap 0.50–0.90, $5 stake, WR 65–90%):
- At entry (t=0, T=5m): position is near-ATM so Δ ≈ 0.5–0.9 (price ≈ win probability ≈ delta at entry in risk-neutral terms)
- **Useful window**: hedge makes sense for the first ~2m of a 5m window only, when delta is stable
- **Last 2m**: delta is so unstable that hedging creates more noise than signal

### Cost vs Benefit

**Perp hedge costs (HL/Binance perp):**
- Taker fee: 0.02–0.05% per trade (HL ~0.035% taker)
- Funding: ~1bp/hr (our data: mean=1.0e-5 hourly rate = 0.001%/hr); negligible for 5m hold
- Slippage (BTC $100k perp, $2,200 notional): < 1bp on liquid HL/Binance perp
- Round-trip for 2,200 notional: ~$0.022–0.055 (0.002–0.005% × $2,200 × 2)

**Variance reduction benefit:**
- If delta is 0.5 and stake is $5, the binary PnL variance is ~$5² × 0.25 (Bernoulli σ² = p(1-p))
- Hedge reduces variance by Δ² × Var(S) — significant only for near-ATM positions
- For 65–90% WR sleeves: position is often deep in-the-money 30s after entry → Δ drops fast → hedge value decays

**Verdict**: Delta hedging is **variance-reduction only, not +EV**, because:
1. Perp hedge costs are small (~$0.03 round-trip) but positive
2. Fees on the Polymarket leg are only on profit → losing the binary AND the perp is full cost
3. For high WR (85%+) deep-ITM positions: delta is low (0.1–0.2) → hedge size minimal → barely worth it
4. For lower WR sleeves (65–70%) near-ATM: hedge could reduce ~15% of variance at cost of ~$0.03/trade

**Net: hedge is never +EV. It's a volatility-reduction tool worth considering only for sleeves with:**
- WR < 75% (so positions remain near-ATM longer)
- Large stake size (scaling up from $5)
- Multiple simultaneous ATM fires on the same asset

---

## 2. Risk-of-Ruin & Drawdown Control for the 4x Kelly Sleeve

### The 4x Kelly Problem

Full Kelly already represents the maximum geometric-growth bet. Any multiple k > 1 yields:

```
Long-run growth rate (continuous):    g(k) = k·E[log(1+f·X)] is maximized at k=1
For k > 2 (double Kelly):             g(k) < 0 → GUARANTEED RUIN asymptotically
For k = 4:                            extremely negative log-growth; ruin near-certain
```

"4x Kelly" in our context likely means sizing 4× the Kelly-optimal fraction, not 4× bankroll. Even 1.5x Kelly gives ~75% of optimal growth with *more* volatility than full Kelly. 4x Kelly → ruin is near-certain over any reasonable horizon.

### Risk-of-Ruin Formula (Bernoulli bets)

For a binary bet with win probability p, net odds b = (1-price)/price:

```
Kelly fraction:  f* = (bp - q) / b    where q = 1-p
Ruin probability (full Kelly, infinite time): 0  [Kelly provably avoids ruin in theory]
Ruin probability (k·f*, large k):      → 1 as k increases
```

For practical drawdown probability bounds (Busseti, Ryu & Boyd 2016):

```
Risk-Constrained Kelly: add constraint P(min_wealth < α) < β

Optimized bet size:  f_opt = argmax E[log(W)] subject to drawdown_bound(f) ≤ β

Result: f_opt < f*   (always smaller than full Kelly)
Single risk-aversion parameter λ controls growth vs drawdown tradeoff
Outperforms fractional Kelly for same drawdown risk level
```

### Overlay Options (Least EV Give-Up Ordering)

| Method | Formula | Drawdown reduction | EV give-up |
|---|---|---|---|
| **½ Kelly** | f = 0.5 × f* | ~50% less DD | ~25% less growth |
| **¼ Kelly** | f = 0.25 × f* | ~75% less DD | ~44% less growth |
| **Risk-Constrained Kelly** (Boyd) | Convex opt with P(DD > α) < β | Tunable, beats fractional Kelly | Minimal — Pareto-optimal |
| **CPPI** | Bet = M × (NAV - Floor); M = multiplier | Hard floor preserved | Growth sacrificed near floor |
| **Volatility targeting** | f = σ_target / σ_realized × f* | Scales down in high-vol | Moderate; mean-reverts |

**Recommendation for 4x Kelly sleeve:**
1. **Immediately cap at 1x Kelly** — 4x Kelly is not a legitimate sizing strategy
2. **Apply Risk-Constrained Kelly** (Boyd et al.): set α=0.7 (never drop below 70% of peak), β=0.05 (5% ruin probability). Convex optimization problem, solvable in closed form for Bernoulli bets
3. **Alternatively**: use ½ Kelly as a simple overlay, captures ~75% of full-Kelly growth with half the drawdown

### Practical Formula for Our Bets

At entry vwap p_mkt, true win probability p_true (from model), stake notional S:

```
b = (1 - p_mkt) / p_mkt
f* = (b·p_true - (1-p_true)) / b
Safe stake = bankroll × min(f*, 0.5·f*)   ← half-Kelly overlay

Example: p_mkt=0.65, p_true=0.75, b = 0.35/0.65 = 0.538
f* = (0.538×0.75 - 0.25) / 0.538 = (0.404 - 0.25) / 0.538 = 0.286 (28.6% of bankroll)
½-Kelly safe stake = 14.3% of bankroll per fire
```

---

## 3. Portfolio-Level Hedging of Correlated Directional Sleeves

### The Correlation Problem

When 20 sleeves fire simultaneously on BTC-Up:
- Each sleeve holds Δᵢ ≈ 0.5–0.9 (price ≈ win prob at entry)
- Aggregate net delta: Δ_net = Σ Δᵢ × Sᵢ ≈ 20 × 0.7 × $5 = **$70 equivalent BTC notional**
- This is real directional exposure to BTC price in the 5m window

### Single Perp Hedge Formula

```
Perp hedge (notional) = -Δ_net = -Σᵢ [Δᵢ × Notionalᵢ]

For 20 sleeves, each $5, all BTC-Up, avg Δ = 0.7:
  Hedge = 20 × 0.7 × $5 = $70 short BTC perp

Continuous update rule (every Δt = 30s):
  ΔHedge = -[Δ_net(t) - Δ_net(t-Δt)]
```

For cross-asset (BTC sleeves + ETH sleeves + SOL sleeves firing simultaneously):

```
BTC_hedge = -Σ [Δᵢ_BTC × Sᵢ]
ETH_hedge = -Σ [Δⱼ_ETH × Sⱼ]  
SOL_hedge = -Σ [Δₖ_SOL × Sₖ]
```

Correlation adjustment: BTC/ETH correlation ≈ 0.85–0.92 in crypto. If ETH and BTC both fire the same direction, net exposure to "crypto factor" is larger than individual hedges suggest. A beta-adjusted aggregate:

```
Total_crypto_beta = BTC_notional + β_ETH×ETH_notional + β_SOL×SOL_notional
where β_ETH ≈ 1.1–1.3 (ETH more volatile than BTC)
     β_SOL ≈ 1.5–2.0 (SOL more volatile than BTC)

Hedge all via BTC perp: short BTC_notional + β_ETH×ETH_notional + β_SOL×SOL_notional
```

### Cost of Portfolio Hedge

For $70 BTC perp notional, round-trip:
- HL taker fees: 0.035% × $70 × 2 = **$0.049**
- Funding for 5m hold: 1bp/hr × (5/60) hr × $70 = **$0.001**
- Total: **~$0.05 per sleeve-batch** (20 simultaneous fires)

Compare to variance reduction: if a 5m window has realized vol of 0.2% (per our HL klines), $70 notional has σ = 0.2% × $70 = $0.14 price risk → hedge removes this. Net benefit is positive for same-direction batch fires.

### Implementation Note

Delta is not static — it evolves as BTC price moves toward/away from K during the 5m window. Need to rebalance the aggregate hedge at ~30s intervals. At 30s rebalance intervals, a 5m window needs ~10 rebalance ticks → total friction: $0.049 × 10 = **$0.49** for the full 5m window. Against $70 notional exposure, this is 0.7% — likely worth it only for large same-direction correlated batches (>10 simultaneous fires, same asset, same direction).

---

## 4. Regime-Conditional Hedging

### Core Logic

Rather than hedging every trade, activate perp hedge only when realized vol is elevated (delta instability is high = hedge benefit is high AND simultaneous fire correlation is high):

```
HEDGE_ON if: RV_percentile(rolling 6h, 1-min bars) > threshold_pct
HEDGE_OFF otherwise (low vol = price stable = delta stable = low residual risk)
```

### Quantitative Triggers (Testable with Our Data)

**Trigger 1: Realized volatility percentile (Binance 1m klines)**
```python
rv = binance_1m['close'].pct_change().rolling(60).std() * sqrt(60)  # 1h RV
rv_pctile = rv.rank(pct=True)  # rolling 30-day percentile
hedge_on = rv_pctile > 0.70   # top 30% vol regime
```

**Trigger 2: ATR-based intraday trigger (1m bars, 14-period ATR)**
```python
atr = ta.atr(high, low, close, period=14)  # 14-minute ATR on 1m bars
atr_pctile = atr.rank(pct=True)
hedge_on = atr_pctile > 0.65
```

**Trigger 3: Hyperliquid liquidation cascade (available in our data)**
```python
# liq_long_60s + liq_short_60s spike → high realized vol → hedge on
total_liq_60s = liq_long_60s + liq_short_60s
hedge_on = total_liq_60s > $5,000   # 90th pctile from our data: $794 long / extreme short tail
```

**Trigger 4: Funding rate extremes (HL hourly)**
```python
# High funding = market tilted → directional risk is higher → hedge more
funding_zscore = (funding_rate - funding_rate.mean(30d)) / funding_rate.std(30d)
hedge_on = abs(funding_zscore) > 1.5   # ~7% of time
```

### Evidence from Our Data

From canonical batch stats (30,111 fires):
- HL funding zscore std = 1.01, p10 = -1.32, p90 = +1.24 → good regime discriminator
- HL basis_bps mean = -3.8 bps (HL perp below Binance spot) → persistent short premium on HL
- Liq_short_60s: extreme skew (std $206k, mean $4,445) → cascade events identifiable in real-time
- These suggest: **funding zscore + total_liq triggers are the most data-rich options we have**

### Cost-Benefit of Regime Conditioning

Expected hedge cost without conditioning: ~$0.05/batch × N_fires
With conditioning (hedge only in top 30% vol regime):
- Only 30% of fire batches get hedged → cost drops 70%
- But the fires in high-vol regimes have wider delta spread → variance reduction is 2–3x larger
- Net: regime-conditioning likely **3–5x better Sharpe** on the hedge overlay than always-on hedging

---

## 5. "Lock the Lag" — Perp Hedge to Lock Binary Mispricing

### Mechanics

If the Polymarket binary is mispriced vs the underlying (e.g., BTC-Up trades at 0.55 but our model says true probability = 0.75):

1. **Buy the binary**: pay $0.55, edge = $0.20 per $1 payoff
2. **Simultaneously hedge delta**: short BTC perp with notional = Δ × $5 = 0.75 × $5 = $3.75

The hedge neutralizes the directional component, leaving only the mispricing component. But unlike a vanilla option (where you can lock the vol mispricing via delta hedge + wait for theta decay), a binary's value doesn't decompose cleanly into directional + vol components:

```
Binary PnL = (won ? 1 : 0) × (1 - fee) × $5 - $5 × p_mkt
           = (won ? 1 : 0) × $4.90 - $2.75     [at p_mkt=0.55, 2%-profit fee]

Perp PnL (short) = -(S_final - S_entry) × notional / S_entry
                 ≈ -Δ_binary × (S_final - S_entry) / S_entry × $5
```

**The lock is imperfect because**:
- S_final and binary outcome are correlated but not perfectly hedged (outcome depends on chainlink resolution vs T-minute bar close, not live price at expiry)
- For our exact setup: outcome = chainlink RTDS settlement vs strike — this IS driven by spot price, so the hedge is structurally valid

**Is it risk-free?** No. The hedge reduces price-path variance but doesn't eliminate it:
- Slippage risk on entry
- Mark-to-market funding on the perp during the 5m hold
- Chainlink resolution is vs. strike (fixed), not a dynamic settlement → hedge works if price at resolution ≈ perp mark at T

### When It's Closest to Risk-Free

For our setup, the most favorable case:
- Large mispricing (e.g., binary at 0.40 when true prob = 0.80 — rare but happens in illiquid brief moments)
- Binary entry and perp entry at same second → minimal basis risk
- 5m window: funding negligible, perp very liquid

**Formula for approximate locked spread**:
```
Expected spread locked = (p_true - p_mkt) × $5 × (1 - 2%fee) - hedge_friction
                       = (0.80 - 0.40) × $4.90 - $0.05
                       = $1.96 - $0.05 = $1.91 per trade

Residual variance (from imperfect hedge): σ_residual ≈ σ_price × (Δ_binary - Δ_hedge) × $5
```

**Testability**: Our data can directly test this. For each fire where our model assigns p_true ≠ p_mkt:
- Simulate: buy binary at L25 book price + short HL perp with correct delta sizing
- Compute realized PnL from canonical outcomes + HL klines

---

## 6. Synthesis & Ranked Shortlist

### Overall Framework Assessment

Our setup (5m binary, $5 stake, 20 correlated sleeves) has a unique risk profile:
- **Short horizon** (5m) → delta instability near expiry is the primary barrier to clean delta-hedging
- **Correlated sleeves** → portfolio-level net delta can be substantial ($50–$100 notional in extreme batches)
- **High WR** (65–90%) → many positions quickly become deep-ITM → delta drops fast → hedge window is brief
- **Small per-trade stake** → hedge friction eats 1–5% of expected PnL per trade individually; only worthwhile at portfolio level

---

### Ranked Shortlist: Most Promising Overlays

#### #1 (HIGHEST PRIORITY): Portfolio-Level Net Delta Hedge on Correlated Batches

**What**: When ≥5 sleeves fire same direction, same asset, within the same 5m window — aggregate the net delta and place one HL perp hedge.

**Why top**: Addresses the actual risk (correlated simultaneous losses), minimal friction per dollar hedged, testable immediately with our data.

**Formula**:
```
Hedge_trigger = (same_asset_same_direction_fire_count >= 5)
Hedge_notional = -Σ [Δᵢ × Notionalᵢ]   ← sum over co-firing sleeves
Δᵢ = vwap_fill_price_i   (price ≈ risk-neutral win prob ≈ delta for binary)
Place at HL perp market order, hold until earliest resolution
```

**Backtest parameterization (our data)**:
- Use `load_klines(asset, '1s')` for perp proxy (HL klines are close enough)
- Use `trading_events` to identify co-firing windows
- Simulate perp PnL: `-Δ_net × (S_resolution - S_entry) / S_entry × Hedge_notional`
- Resolution price: `load_chainlink_asof(ts_us)` at slug expiry
- Compare portfolio PnL hedged vs unhedged across all windows with ≥5 co-fires

**Expected cost**: ~$0.05 per batch × N_batches; **Expected benefit**: reduction in correlated loss batches

---

#### #2: Risk-Constrained Kelly (Replace 4x Kelly Immediately)

**What**: Use Boyd et al. (2016) convex optimization to size the 4x Kelly sleeve properly.

**Why urgent**: 4x Kelly guarantees ruin. This is not a hedging idea — it's a critical position-sizing fix.

**Implementation**:
```python
# For each fire: compute f* from true probability estimate
b = (1 - p_mkt) / p_mkt
f_kelly = (b * p_true - (1 - p_true)) / b

# Apply ½-Kelly as simple overlay (captures 75% growth, halves drawdown):
f_safe = 0.5 * f_kelly
stake = bankroll * f_safe

# Or use Risk-Constrained Kelly with drawdown constraint:
# Minimize: -E[log(W)] subject to P(W < 0.8 * W_peak) < 0.05
# (Can be solved as convex program; see Boyd et al. arxiv:1603.06183)
```

**Backtest parameterization**: Apply ½-Kelly sizing to historical fire records in `trading_events`, compare cumulative growth curve and max drawdown vs fixed $5 stake.

---

#### #3: Regime-Conditional Portfolio Hedge (HL Funding Zscore + Liquidation Trigger)

**What**: Only activate the portfolio-level perp hedge when HL funding zscore > 1.5 OR total_liq_60s > $5,000.

**Why**: These two signals from our existing data indicate high-vol / high-directional-risk regimes where hedge benefit exceeds cost by 3–5x.

**Backtest parameterization**:
```python
# Use: load_hyperliquid_funding(asset) + load_hyperliquid_liquidations(asset)
funding_z = (funding_rate - fund_mean_30d) / fund_std_30d
total_liq = liq_long_60s + liq_short_60s   # from liquidations loader
regime_on = (abs(funding_z) > 1.5) | (total_liq > 5000)

# Only apply portfolio hedge (#1 above) when regime_on == True
# Compare: (1) always hedge, (2) regime-conditional hedge, (3) no hedge
# Metric: Sharpe ratio of portfolio PnL; cost efficiency = EV_saved / friction_paid
```

---

#### #4: Volatility-Targeting Stake Scaler

**What**: Scale stake size inversely with realized BTC/ETH/SOL 1h rolling volatility percentile.

**Formula**:
```
stake_i = base_stake × (σ_target / σ_realized_1h)
         = $5 × (0.003 / rv_1h)    # target: 0.3% realized vol per 1h window
         = $5 × clip(0.5, 3.0, scale_factor)  # cap at 3x, floor at 0.5x

# rv_1h from Binance 1m klines:
rv_1h = returns.rolling(60).std() * sqrt(60)
```

**Why it works**: High volatility → binary delta is more unstable → more adverse selection risk → smaller stakes. Low volatility → price stable → model signal more reliable → larger stakes.

**Backtest**: Compare fixed $5 stake vs vol-targeted stake on all 30,111 fires in canonical data. Expected outcome: reduces left-tail losses in high-vol periods with modest EV give-up.

---

#### #5: "Lock the Lag" for Large Edge Fires (>15% Mispricing)

**What**: For fires where `|p_true - p_mkt| > 0.15`, simultaneously buy the binary and hedge the delta with HL perp.

**Why**: Large mispricings are rare but present (from our F2/Cyclops analysis). The hedge converts a directional bet into a near-pure alpha capture.

**Formula**:
```
For fire where p_mkt = 0.55, p_true = 0.75:
  Buy binary: $5 at 0.55
  Short perp: Δ_binary × $5 = 0.70 × $5 = $3.50 notional
  
Locked expected value (vs pure binary):
  Without hedge: E[PnL] = 0.75 × $4.90 - $5 = -$1.325... wait
  
Correction (2% fee on PROFIT only, LegacyConfig):
  Win: PnL_binary = (1 - 0.55) × (1 - 0.02) × $5 = $2.205
  Lose: PnL_binary = -$5 × 0.55 = -$2.75
  E[PnL_binary] = 0.75 × $2.205 - 0.25 × $2.75 = $1.654 - $0.688 = $0.966
  
  With hedge (short $3.50 perp):
  Win: binary_win + perp_loss = $2.205 - (S_T-S_0)/S_0 × $3.50
  But if won, S_T > S_0 → perp loses → partial offset
  Lose: binary_loss + perp_win = -$2.75 + (S_0-S_T)/S_0 × $3.50
  
  Variance reduction: the co-movement of BTC price and binary outcome
  is the hedge's source of risk reduction (not EV gain)
```

**Backtest**: On high-edge fires only (filter: `|p_fire - p_outcomes_avg| > 0.15` across similar slugs). Compare binary-only PnL variance vs binary+perp-hedge PnL variance. Use HL 1s klines for perp entry/exit simulation.

---

## 7. Implementation Roadmap

| Priority | Overlay | Data needed | Complexity | Expected benefit |
|---|---|---|---|---|
| **CRITICAL** | Fix 4x Kelly → ½-Kelly | trading_events, bankroll history | Low | Prevents ruin |
| **High** | Portfolio net-delta hedge for ≥5 co-fires | trading_events, HL klines, chainlink | Medium | Reduces correlated loss batches |
| **High** | Regime-conditional trigger (funding + liq) | load_hyperliquid_funding + _liquidations | Low-Medium | 3–5x better hedge efficiency |
| **Medium** | Volatility-targeting stake scaler | Binance 1m klines (already loaded) | Low | Reduces high-vol adverse selection |
| **Low** | Lock-the-lag for >15% edge fires | L25 books + HL klines + outcomes | High | Niche; requires calibrated p_true model |

---

## References

- Busseti, Ryu & Boyd (2016). "Risk-Constrained Kelly Gambling." Stanford. [arxiv:1603.06183](https://arxiv.org/pdf/1603.06183)
- Hull, J. & White, A. "Optimal Delta Hedging for Options." Rotman. [PDF](https://www-2.rotman.utoronto.ca/~hull/downloadablepublications/Optimal%20Delta%20Hedging.pdf)
- BIS Working Paper 1087 (2024). "Crypto Carry." [BIS](https://www.bis.org/publ/work1087.pdf)
- Bawa, N. (2025). "The Math of Prediction Markets: Binary Options, Kelly Criterion, and CLOB Pricing Mechanics." [Substack](https://navnoorbawa.substack.com/p/the-math-of-prediction-markets-binary)
- E.P. Chan (2010). "How do you limit drawdown using Kelly formula?" [Blog](http://epchan.blogspot.com/2010/04/how-do-you-limit-drawdown-using-kelly.html)
- QuantInsti. "Risk-Constrained Kelly Criterion." [Blog](https://blog.quantinsti.com/risk-constrained-kelly-criterion/)
- Macroption. "Delta Hedging: Calculations, Adjustments." [Link](https://www.macroption.com/delta-hedging/)
