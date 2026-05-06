# Cyclops Comparison + V4 Edge Plan — 2026-04-30

**Source material:** friend's iteratively-built BTC bot (Cyclops v84-v113+) and a related "second engine" blog post. Both target the same Polymarket BTC UP/DOWN binary market we're trading. Their system is BTC-only (single asset, mostly 15m markets); ours is BTC+ETH+SOL portfolio (5m markets).

## TL;DR

| | Their system (Cyclops v107+) | Our system (V3.1) |
|---|---|---|
| **Architecture** | Multi-signal voting → Brain object → confidence | Single magnitude threshold |
| **Signals** | 10-15 (technical + microstructure + volume + liq) | 1 (\|ret_5m\| > per-asset quantile) |
| **Validation** | Iterative bug-hunting, version log | 10-gate statistical gauntlet (perm/bootstrap/CV) |
| **Markets** | BTC 15m only, single asset | BTC+ETH+SOL 5m portfolio |
| **Sizing** | Modified Kelly with signal quality | Fractional Kelly on bankroll |
| **Exits** | Hold-to-resolution + entry-window filter | Hold-to-resolution + spread filter |
| **Live track record** | 53-74% win rate (volatile, frequent regression) | 65.6% backtest, 78-83% live BTC (n=20) |
| **Edge philosophy** | "No permanent strategy. Edges fragile." | Magnitude continuation in q5-q15 tail |

**Headline:** their architecture is more sophisticated. Our validation is more rigorous. They've shipped more iterations. We've passed more statistical tests. **Our V3 is simpler-but-validated; theirs is feature-rich-but-fragile.**

The right move is **selective adoption**: borrow their validated wins (time-of-day, microstructure signals, Kelly with signal quality), skip their architectural sugar (regime detection, pattern memory, hemispheres) until we have evidence of value.

---

## What they have, we don't

### 1. Live microstructure signals (their "right hemisphere")
- **Polymarket CLOB imbalance** — `imbalance = (up_vol - down_vol) / (up_vol + down_vol)` over last 2 min, filtered by active condition_id, fires when `|imbalance| > 0.20`
- **Order book wall detection** — large resting orders, weighted by reachability (can BTC physically reach the wall in remaining time?)
- **Live trade tape per side** — UP buyers vs DOWN buyers in real time

We have these features in `*_features_v3.csv` (`taker_ratio`, `book_skew`, `smart_minus_retail`) but tested them as standalone signals (A1, V2 prob_c) and got null IC. Their version is **livestream + 2-min window + condition-filtered** — meaningfully different.

### 2. Multi-source liquidation feed
- Pulls liq data from 4 exchanges (Binance, Bybit, OKX, HL) via WebSocket
- Used for: liquidation cluster proximity ("where is the magnet?"), liquidation pressure (cascade detection), volume veto (LIQ as one of 4 vote inputs)

We tried Binance Vision liquidation history → 404 (deprecated). For live, we'd need WS subscriptions. We're missing this entirely.

### 3. Multi-timeframe BTC trend confirmation (BTC_MACRO_BLOCK)
- Aligned 15m + 30m + 1h + (4h?) trend with strength ≥ 0.50 → block counter-trend trades
- Their v113 fix specifically prevented a -$X loss

We have `ret_5m`, `ret_15m`, `ret_1h` in our features. Used only on SOL multi-horizon gate. **Underused — we should test BTC/ETH macro alignment.**

### 4. Time-of-day schedule
Their cited stats (n=300 trades):
- Best: 18:00 UTC = 90% hit, 14:00 UTC = 88%, 17:00 UTC = 69%
- Block: 22:00, 01:00, 02:00, 07:00, 19:00 UTC (<45% hit)
- Weekends fully disabled (BTC trends without pullbacks)

We have window_start_unix on every market. **We've never tested hour-of-day. Would take 30 minutes.**

### 5. Position sizing scaled by signal quality
Their Kelly multiplier ranges 0.5x-1.5x based on:
- confidence level (≥0.80 → +20%, <0.58 → -15%)
- vote_score (strong consensus → +10%)
- synergy_count (each cluster → +3%, capped 15%)
- conflict (slow/fast disagreement → -20%)
- memory_adj (past pattern win rate → ±20%)

We size flat $1/trade, then fractional 12% bankroll Kelly above $50. **No signal-quality differentiation.** A barely-above-threshold magnitude gets the same size as a 3σ outlier.

### 6. Confidence calibration (Platt scaling)
- Bucket predictions, periodically re-fit `real_WR ~ a × predicted + b` via weighted linear regression
- Auto-adjust if bot is systematically over/underconfident
- Bounded coefficients: a ∈ [0.5, 2.0], b ∈ [-0.15, 0.15]

We don't output a confidence number — we output binary fire/skip. To get this we'd need to map `|ret_5m| / threshold` ratio to a calibrated probability.

### 7. Period observation window
v96 PeriodTracker: first 5 minutes of a 15m market = OBSERVE only (no entries). Accumulate direction, CVD, OFI, speed/accel. By minute 5-10 produce a verdict 0.0-1.0. If ≥0.60 confidence, drop entry magnitude threshold by 20%.

We fire whenever the magnitude gate triggers. **No "wait and watch" period.**

### 8. Pre-warm indicator history at startup
v89: 37 REST requests to build 35 candles before first iteration. Solves cold-start blind period.

We assume features are pre-loaded; not relevant for our infrastructure but a discipline marker.

### 9. Visual diagnostic dashboard
Their Image 2 shows EVERY signal's verdict even when no trade is fired. Operators can see: MACD bearish, ST bearish, OFI bearish, but CLOB imbalance UP → no trade because edge=-0.069. **We have query templates but no real-time dashboard.**

---

## What we have, they don't

### 1. Statistical validation pipeline
- Outcome permutation test (200 reps, p<0.005)
- Block bootstrap CI (95%: $602-$1456 holdout PnL)
- Multi-split chronological CV (60/70/80/90)
- Per-day decomposition
- Stratified-by-magnitude permutation (validates direction is the alpha, not magnitude alone)

Their evidence is "we lost money so we patched it" — anecdotal. **We can claim our edge is statistically distinguishable from random.**

### 2. Multi-asset portfolio
BTC + ETH + SOL in one stack. Diversification benefit (when BTC sniper is paused for low vol, ETH/SOL still fire). Their bot is BTC-only.

### 3. Per-asset directional asymmetry (V3.1 patch)
We just diagnosed and patched: SOL UP=11% live hit vs SOL DOWN=67%. Their public commentary doesn't show explicit per-direction quantile splits — they have generic "UP vs DOWN" balance.

### 4. Sim-vs-live reconciliation (S1)
We measured the execution-layer gap between sim and live. They acknowledge "edges fragile" but don't appear to have a quantified sim→live transfer ratio.

### 5. Hold-to-resolution discipline (validated)
We tested TP/SL/trail/oppo-flip variants. **All hurt ROI.** They don't appear to have run this experiment — their "exits matter more than entries" claim is speculative.

### 6. Rigorous orthogonality tests for feature classes
We tested funding+OI (V4-A, null), news+sentiment (V4-C, null on lexicon). They added more signals iteratively without ever showing a feature has zero IC and removing it.

---

## Top 5 features worth borrowing (ranked by evidence strength × implementation cost)

### Tier S: ship this week (cheap + strong evidence)

#### 1. **Time-of-day schedule filter** (their best-evidenced finding)
- **Evidence:** their n=300 trades show 90% / 88% / 69% best hours, <45% worst hours. Plausible mechanism: London/NYSE liquidity windows
- **Cost:** 30 min — group existing backtest data by hour-of-day, compute hit rate
- **Risk:** if our 7-day window doesn't replicate their hour pattern, may not generalize. But we can test it for free
- **Action:** build `hour_of_day_analysis.py` on our existing data, decide whether to gate

#### 2. **Polymarket CLOB live imbalance signal** (their "right hemisphere")
- **Evidence:** they cite this as a primary signal, used in many versions, claimed to detect direction before BTC moves enough
- **Cost:** 1-2 hrs — we already have `taker_ratio` and `book_skew` features. Re-test with their formulation: 2-min window, condition-filtered, threshold 0.20
- **Risk:** we tested similar features in A1/V2 prob_c, found null IC. But our test was simplistic. Their version might work
- **Action:** re-engineer the feature properly, IC-test on our 7-day window

#### 3. **Macro trend block (BTC_MACRO_BLOCK)** (related to our V3.1 regime patch)
- **Evidence:** their v113 specifically cites this preventing a real loss. Aligned with the structural finding that DOWN > UP in alts during downtrends
- **Cost:** already built in V3.1 patch (soft regime filter ±0.5%). They use stricter (3 of 4 timeframes aligned + strength ≥0.50)
- **Action:** test their stricter formulation against our soft version on backtest

### Tier A: ship this month (medium cost, plausible value)

#### 4. **Signal-quality-scaled Kelly sizing**
- **Evidence:** standard quant practice. We're currently flat $1/trade; their multiplier 0.5x-1.5x is principled
- **Cost:** 2-3 hrs to wire `|ret_5m|/threshold` ratio → confidence → Kelly multiplier
- **Risk:** at $1-5/market we're below platform minimum to vary size meaningfully. Useful only at $25+/market
- **Action:** design + implement, but defer activation until bankroll ≥$100

#### 5. **Live order book WebSocket feed (Polymarket CLOB)**
- **Evidence:** their feature 2 above depends on this. We currently use historical book_depth_v3.csv; live we'd need WS
- **Cost:** 1-2 days — Polymarket CLOB WS subscription + streaming feature computation + wiring into entry decision
- **Risk:** infrastructure debt (reconnection handling, deduplication, latency monitoring)
- **Action:** scope as V4 phase 2 if Tier S features pay off

### Tier B: maybe later (high cost, speculative value)

#### 6. **Live liquidation feed (Binance/Bybit/OKX/HL WS)**
- **Evidence:** Cyclops uses this heavily but never published a clean ablation. Plausible: liquidation cascades create predictable short-term moves
- **Cost:** 4-5 days — 4 WS subscriptions, deduplication, heatmap aggregation, signal generation
- **Risk:** historical backtest impossible (Vision discontinued). All evidence will be live-paper
- **Action:** defer to V4 phase 3, only if Tier A confirms multi-signal architecture works

#### 7. **Confidence calibration (Platt scaling)**
- **Evidence:** standard practice in ML; their version sounds well-engineered
- **Cost:** 1 day — bucket predictions, weighted regression, online recalibration
- **Risk:** needs continuous in-sample data to calibrate (>200 trades)
- **Action:** defer until 30-day OOS data lands; pointless on 7-day window

#### 8. **Period observation window**
- **Evidence:** their PeriodTracker on 15m markets observes 5 mins → trades 5-10 min window. We're on 5m markets → can't observe 1.7 mins (no time)
- **Cost:** N/A — incompatible with our 5m horizon
- **Action:** skip unless we add 15m sleeves

### Tier C: skip (overhead without evidence)

- **Regime detection (TREND/VOLATILE/CHOPPY)** — sounds nice, no rigorous backtest evidence. High overfit risk on our 7-day window.
- **Signal memory (Jaccard pattern matching)** — overfitting machine. Would need 1000+ trades to be safe.
- **Two-hemisphere architecture** — labeling signals as "left" vs "right" hemisphere is org sugar. Same outcomes from clean feature unioning.
- **Synergy bonuses (non-linear cluster amplification)** — only meaningful with many uncorrelated signals. We have 1.
- **VETO system** — we have spread filter, V3.1 has direction gate. Adding more vetoes risks over-blocking. Their volume veto requires 4-of-4 alignment which is rare.

---

## What their failure modes teach us (CRITICAL)

Reading between the lines of their version log:
- v107: "Removed entire committee system... fewer places where the system lies to itself" → **complexity created bugs**
- v90: "StochRSI K=80 with downCross blocked entry at CLOB conf=1.00, BTC went up $130, bot missed it" → **vetoes can fail catastrophically**
- v89: "First 17 minutes... all indicators returned None" → **cold-start bugs hidden**
- v88: "Platt calibration was bypassing StochRSI veto" → **calibration interactions hide bugs**
- "Win rate dropped from 74% to 53% after patches, rolling back" → **patching creates regression**

**Lesson:** their architecture is the ARTIFACT of many losses, not a pre-validated design. Each new feature was duct-taped after a loss. Our V3 has 1 signal that passed 10 gates. **More features = more places to lie to ourselves.**

The blog post says: "There is no permanent strategy. What worked three days ago may fail today."

This is dangerous advice if interpreted as "keep adding features." The real implication: **rigorous validation matters more than feature count.**

---

## V4 implementation plan — prioritized

### Phase 1: ship time-of-day filter (this week, 1-2 hrs)

```python
# strategy_lab/v4_signals/hour_of_day_analysis.py
# Group existing 7-day backtest by hour-of-day, compute hit rate.
# If pattern matches Cyclops claims (peaks 14:00/17:00/18:00 UTC, troughs 22:00-02:00),
# add hour gate to V3.1.
```

Decision rule: enable hour gate only if at least 3 hour-bands show >5pp deviation from baseline AND pattern is monotonic (no zigzag).

### Phase 2: re-test Polymarket CLOB imbalance with their formulation (1-2 hrs)

```python
# strategy_lab/v4_signals/clob_imbalance_v2.py
# Recompute taker_ratio with: 2-min window, condition_id filter, threshold 0.20.
# Test as: standalone signal, gate on V3, modifier on V3 fire decision.
```

Decision rule: enable as V3 gate if it adds ≥3pp hit rate with no fire-rate collapse.

### Phase 3: macro alignment block stricter formulation (1 hr)

```python
# strategy_lab/v4_signals/macro_block_v2.py
# Test: 3 of 4 timeframes (5m, 15m, 1h, 4h?) aligned + strength threshold.
# Compare against existing V3.1 soft regime filter (±0.5%).
```

### Phase 4: signal-quality Kelly (defer until $100 bankroll, ~3 hrs)

```python
# strategy_lab/v4_signals/kelly_signal_quality.py
# multiplier = 0.5 + 1.0 * normalize(|ret_5m| / threshold, [1.0, 3.0])
# Below threshold → no fire. At threshold → 0.5x. At 3σ → 1.5x.
```

### Phase 5 (V4): live order book + liq WebSocket (defer to month 2, ~1 week)

Only build this if Phases 1-4 deliver compounding edge. Otherwise it's speculative infrastructure debt.

### Phase 6 (V5): confidence calibration (defer to 30-day OOS data, ~1 day)

Pointless until we have ≥200 live trades to calibrate against.

---

## What to NOT build (ever, on current evidence)

- Pattern memory / Jaccard similarity / signal memory — overfitting machine
- Regime detector with named regimes — pseudo-precision
- Two-hemisphere split — architecture aesthetics
- Synergy bonuses (non-linear) — needs many uncorrelated signals we don't have
- Multi-veto stacking — V3.1 already has spread + direction; more vetoes will starve fire rate

---

## Honest comparison: where they're stronger, where we are

**They're stronger at:**
1. Iteration speed — ~30 versions documented, regular hot-patches
2. Live ops dashboard — visual signal verdicts in real time
3. Microstructure depth — Polymarket CLOB live + multi-exchange liq feeds
4. Single-asset BTC focus depth — every quirk understood

**We're stronger at:**
1. Statistical validation discipline — 10-gate gauntlet, permutation tests, bootstrap
2. Multi-asset portfolio — diversification across BTC/ETH/SOL
3. Honest negative results — V4-A and V4-C documented as null
4. Sim-to-live transfer measurement — quantified the gap (S1 reconciliation)
5. Per-direction analysis — V3.1 caught the SOL UP asymmetry

**Verdict on edge:**
Their backtest claims (90% win rate at peak hours) are NOT independently validated. Their live track record swings 53-74%. Our V3 backtest holdout is 65.6% with statistical bounds. **Our claimed edge is more conservative but more credible.**

The right move is to adopt their best-evidenced features (time-of-day, microstructure, macro block) without adopting their architecture (hemispheres, regime, memory). Build incrementally, validate each addition.

---

## Action items (ranked)

| # | Task | Time | Priority | When |
|---|---|---|---|---|
| 1 | Hour-of-day analysis on existing backtest | 1-2 hrs | HIGH | This week |
| 2 | Polymarket CLOB imbalance v2 (their formulation) | 1-2 hrs | HIGH | This week |
| 3 | Macro alignment block (stricter than V3.1) | 1 hr | MEDIUM | Next week |
| 4 | V3 ship to live (separate task — already specced) | TV agent's task | HIGH | When ready |
| 5 | Signal-quality Kelly (bankroll-gated) | 3 hrs | MEDIUM | After $100 bankroll |
| 6 | Live Polymarket CLOB WS feed | 1-2 days | MEDIUM | After Phase 1+2 confirm |
| 7 | Multi-exchange liq feed | 4-5 days | LOW | After live edge confirmed at scale |
| 8 | Confidence calibration | 1 day | LOW | After 30-day live data |
| 9 | Real-time dashboard | 1-2 days | LOW | Quality-of-life improvement |

**Next action:** I can start with #1 (hour-of-day) right now. ~30 min to write the analysis, ~30 min to test.
