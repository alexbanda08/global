# Cyclops (Gustafssonkotte) Bot — Full Architecture Deep-Dive

**Source:** [@Gustafssonkotte on X](https://x.com/Gustafssonkotte) (Researcher & Contributor @Polymarket per his X bio; TG: `lebenshnell`; 1,652 followers)

**⚠ READ §16 FIRST. The author DELETED half this architecture on May 11.**

**Articles extracted (chronological):**
- **Tweet F** — *MRO strategy for 5-minute Bitcoin markets* (Mar 2 2026, id `2028471093640470580`, full short tweet)
- **Article E** — *Prediction Markets + AI = Unlimited Money Printer* (Mar 18 2026, id `2034179153902125253` → article `2033438760520568832`) — preview only; sponsored-style content, lower architectural value
- **Article A** — *How I Built a Polymarket BTC Trading Bot in 3 Months: Architecture, Brain, and Risk Management* (Apr 21 2026, id `2046677998477225984`) — FULL extract
- **Article B** — *How I Built an Algo Trading Bot for Polymarket* (Apr 27 2026, id `2048689549593747456`) — FULL extract
- **Article C** — *Bot Update: How I Raised WR to 68%* (May 7 2026, id `2052278497406582788`) — analyzed earlier in `CYCLOPS_UPDATE_COMPARISON_2026_05_07.md` (4 infra fixes lifted WR 55% → 68% on same signals)
- **Article D** — *Deleted half my bot's code and it started winning* (May 11 2026, id `2053745943770525696`) — TL;DR + headlines only; see §16

Telegram channel: `t.me/cyclops_signals`

Extraction path: X.com blocked unauth fetch → `r.jina.ai/<url>` reader renders JS and returns markdown. Articles D and E were blocked by an x-thread.org cookie banner on the second pass; only their previews are available. Confirmed via DDG snippets the same author owns the earlier "Cyclops" pieces (same `{2: 0.50, 3: 0.54, 4: 0.60, 5: 0.66}` calibration fingerprint).

---

## 1. Module layout (Article A)

The bot is a **modular monolith** — single Python process, isolated modules with clear responsibilities. The structure he ships:

```
bot.py              <- entry point, CLI
bot_loop.py         <- main loop
engine.py           <- brain: decision making
risk.py             <- risk management
kelly.py            <- position sizing
signals/
  context.py        <- market context
  memory.py         <- signal memory
  optimizer.py      <- entry optimizer
brain/
  state.py          <- brain state
  calibrator.py     <- confidence calibration
heatmap.py          <- visualization (+ data aggregation)
sentiment.py        <- sentiment analysis
```

His own note: *"The first 100 versions were a monolith. One file, all logic inside, from data parsing to trade execution. It worked fine until the first serious bug. Finding a problem in 4,000 lines of unstructured code is a nightmare. … After one too many hours of debugging I made a decision: rewrite everything into a modular architecture. That turned out to be the best decision in the entire project."*

Benefits he lists:
- A bug in `risk.py` does not touch `engine.py`
- Changing signal logic does not break position management
- Each module has one job and one job only
- Testing, debugging, iterating is dramatically faster

---

## 2. The "Brain" — UnifiedBrainEngine

Core idea: **signals do NOT vote**. They accumulate into a **multi-dimensional market state** vector. The vector is the bot's market view. A single number — confidence — is derived from it.

### 2.1 Four market dimensions + weights

```
pressure   40%   Order flow, CLOB pressure, CVD
momentum   25%   MACD, acceleration, impulse
structure  20%   Trend, EMA, market structure
flow       15%   Confirmed deal flow
```

Each incoming signal pushes ONE of these dimensions toward bullish or bearish:

```python
def absorb_signal(self, state, key, agree, strength=1.0):
    # Signal shifts the relevant dimension of the state vector
    # scaled by adaptive and contextual weight multipliers
    w = base_weight * adaptive_mult * context_mult * strength
    current = getattr(state, dimension)
    setattr(state, dimension, clip(current + w, -1.0, 1.0))
```

### 2.2 Confidence formula

```python
signal_strength = (
    state.pressure  * 0.40 +
    state.momentum  * 0.25 +
    state.structure * 0.20 +
    state.flow      * 0.15
)

signal_prob = 0.5 + signal_strength * 0.65 + consensus_boost
```

- `consensus_boost` activates when the majority of signals agree with each other → amplifies confidence
- An `uncertainty` term discounts the result when market conditions are unclear (Article B)

`signal_prob` is THE single number that drives the entry decision. There is no ensemble, no voting tally, no average. One brain, one number.

### 2.3 Adaptive weights (calibration loop)

After each closed trade the bot checks which signals were right and **slowly shifts their weights using a moving average**. Slow on purpose — guard against overfitting to short streaks of luck.

He explicitly mentions a **calibrator** module (`brain/calibrator.py`) — confidence calibration. The earlier-article `{2: 0.50, 3: 0.54, 4: 0.60, 5: 0.66}` was the win-probability lookup table; this is now derived from actual performance, not hardcoded.

---

## 3. Heatmap — volumetric view (Article B)

One major data source is an **aggregated price-level map**. Each price level stores:
- Buy and sell volumes
- Liquidations
- Order book imbalance **across multiple exchanges**

The bot reads three things from the map:
1. **Volume concentration** — heavy volume below current price ⇒ buyers defending that level
2. **Liquidation clusters** — price tends to move toward liq clusters because triggering them creates cascading momentum
3. **Large orders in the book** — wall = support/resistance

### Wall reachability — important detail

If price cannot physically reach the wall within remaining time, the weight of that order is **reduced** (not zero, but discounted):

```python
max_move = btc_speed * mins_left
reachable = distance_to_wall <= max_move
```

This filters out the noise of "there's a $500k wall at $100k BTC" — irrelevant if the market closes in 30 seconds.

---

## 4. Position sizing — Kelly with tier caps

The Kelly Criterion is the math-optimal formula for bet sizing given a known edge. He uses it BUT protects against ruin with tier-based caps:

```python
def kelly_size(edge, entry_px, balance, kelly_mult=1.0):
    cap = tier_cap(edge)           # cap grows with edge strength
    odds = 1.0 / entry_px - 1.0
    fraction = min(edge / odds * kelly_mult, cap)
    return clip(balance * fraction, MIN_COST, MAX_COST)
```

Notes:
- `tier_cap(edge)` — cap is FUNCTION of edge strength; bigger edge → bigger cap allowed
- `kelly_mult` is a global Kelly fraction multiplier (operator can run quarter-Kelly etc.)
- `MIN_COST` / `MAX_COST` are absolute USD bounds

His principle: *"Position size is mathematically grounded but protected from ruin by tiered caps."*

---

## 5. Risk management — DrawdownManager

```python
class DrawdownManager:
    def is_halted(self, total, day_start):
        return (
            self.drawdown_pct(total) >= MAX_DRAWDOWN or
            self.daily_loss_pct(total, day_start) >= DAILY_LIMIT
        )
```

Two hard halts:
- **Max drawdown** — % drop from peak balance
- **Daily loss limit** — trading stops until next day if breached

His description: *"Drawdown control. If the balance drops significantly from its peak, the bot pauses and only resumes after partial recovery."* — implies the halt is NOT a timed pause (like the earlier article's `RISK_PAUSE_MIN`); it's gated on **balance recovery**.

He also separately: *"Daily loss limit. If the daily loss limit is breached, trading stops until the next day."* → fixed time gate.

---

## 6. Entry filter

The bot REFUSES to enter when:
- Edge is insufficient (below MIN_EDGE)
- Contract price is outside the working range (range capped between **0.60 and 1.40** — interesting, NOT the Cyclops public 0.35-0.65 — this is the rounded-for-tick-size range; may be his specific naming)
- Too little or too much time remains until market close

His optimal window: **the middle of the market's lifetime**:
- Early ⇒ too much uncertainty
- Late ⇒ spread widens (CLOB book thins out as market closes)

---

## 7. Sentiment module — mathematical, not narrative

His exact words: *"Sentiment has direct mathematical meaning. When market sentiment shifts, it literally changes the probability estimate. This is why there is a dedicated sentiment.py module."*

Sentiment is treated as a SIGNAL that updates the state vector (probably injected into a specific dimension — likely `flow` or as its own contextual multiplier). Not narrative analysis; structured input with weight.

---

## 8. Operational summary

| Layer | Component | Key concept |
|---|---|---|
| Entry | `bot.py` | CLI parse, demo mode (no real trades) |
| Loop | `bot_loop.py` | Find active markets, evaluate signals, execute |
| Brain | `engine.py` + `brain/state.py` | 4-dim state vector, signal_strength, signal_prob |
| Calibration | `brain/calibrator.py` | Slow adaptive weights from closed trades |
| Signals | `signals/{context,memory,optimizer}.py` | Context-aware, memory of past states, entry optimizer |
| Data | `heatmap.py` | Multi-exchange price-level map (vol + liq + walls) |
| Sentiment | `sentiment.py` | Numeric input to probability estimate |
| Sizing | `kelly.py` | Kelly with tier caps + MIN/MAX absolute bounds |
| Risk | `risk.py` (DrawdownManager) | MAX_DRAWDOWN + DAILY_LIMIT hard halts |
| Config | env vars only | No code changes for tuning |

---

## 9. Key principles he calls out

- *"Risk management matters more than signals. You can survive with mediocre signals and strict risk management. The reverse is not true."*
- *"Signals do not vote directly — they push a multi-dimensional state vector."*
- *"Position size is mathematically grounded but protected from ruin by tiered caps."*
- *"All settings are overridable via environment variables, no code changes needed."*
- *"Sentiment has direct mathematical meaning."*
- *"The first 100 versions were a monolith — rewriting to modular architecture was the best decision in the entire project."*

---

## 10. Comparison vs OUR system (state as of 2026-05-16)

| Dimension | Cyclops (Gustafsson) | Us (Tradingvenue/canonical) | Gap |
|---|---|---|---|
| **Architecture** | Modular monolith (12 files, env-var config) | Production = monolith controller `polymarket_updown.py` 3133 LOC + ad-hoc rails | We have 11 rails + supervisor but no clean module boundaries inside the controller |
| **Signal model** | 4-dim state vector (pressure/momentum/structure/flow with 40/25/20/15 weights) | Single-feature `ret_2m` momentum + binary fire on q90 | **We are 1-dim; he is 4-dim.** Huge structural gap |
| **Confidence** | `signal_prob = 0.5 + strength*0.65 + consensus_boost - uncertainty` | binary fire (yes/no), no continuous confidence | **Major gap** — we have no confidence number |
| **Adaptive weights** | Post-trade moving-average shift on each signal's weight | None — quantile threshold refit weekly | **We are static; he is online-learning** |
| **Heatmap** | Multi-exchange aggregated price-level map (vol + liq + walls + reachability) | We have raw L25 OB but no aggregated cross-venue heatmap | **He aggregates across exchanges, we don't** |
| **Wall reachability** | `max_move = btc_speed * mins_left` discounts unreachable walls | Not implemented | Quick win |
| **Sentiment** | Numeric mathematical input (`sentiment.py`) | Not implemented | We tested `news_sentiment` once (rejected), but he uses it AS a probability shifter not a binary signal |
| **Sizing** | Kelly with edge-scaled tier cap + `MIN_COST`/`MAX_COST` absolute bounds | Fixed $25 notional | **We size flat; he sizes by edge** |
| **Risk halt** | DrawdownManager: peak-DD + daily-loss with **balance-recovery** resume | 11 rails (rail_03/04/05 portfolio DD, rail_11 abs day loss) — timed/fixed pauses | Ours is more comprehensive but lacks the **resume-on-recovery** mechanic |
| **Entry filter** | MIN_EDGE + price-range 0.60-1.40 + middle-of-life time gate | SPREAD_FILTER per asset + entry_price gate | **No middle-of-life gate** — we fire at fixed t+120 regardless of market lifetime position |
| **Calibration** | Brain calibrator slowly updates win-prob mapping `{n_signals: prob}` | None | **No calibration loop** — backtest threshold is offline-refit only |
| **Multi-venue** | Aggregates Binance + Coinbase + Bybit etc. into heatmap | Binance primary, others as ablation tests only | He fuses; we substitute |
| **What we have he doesn't** | 11-rail safety framework, independent watchdog, Claude supervisor, multi-venue (HL+Polymarket+Kalshi), production-faithful backtest infra, anti-edge audits | Cyclops is single-venue, single-asset (BTC binary) | **OUR EDGE in safety + breadth** |

---

## 11. Adaptation proposal — port his architecture onto our infra

The goal: **keep our infra (rails, watchdog, supervisor, backtest engine, canonical data layer) and ADD his signal model + sizing + calibration on top.**

### Phase 1 — Build the 4-dim state vector (greenfield)

New module `strategy_lab/brain/`:

```
strategy_lab/brain/
├── state.py            # BrainState dataclass with pressure/momentum/structure/flow
├── absorb.py           # absorb_signal(state, key, agree, strength) — pushes dims
├── confidence.py       # signal_strength + signal_prob with consensus_boost + uncertainty
├── calibrator.py       # online adaptive weight updates per signal class
└── tests/
    └── test_brain.py
```

Map our existing features (already built) to his dimensions:

| His dim | Weight | Our existing features that fit |
|---|---:|---|
| pressure | 40% | FLOW layer features (CVD, aggressor ratio, L25 imbalance — already built per `confluence/flow/features.py`) |
| momentum | 25% | `ret_2m`, MACD on 1m kline, derivatives Z-scores (`v4_signals/derivatives_zscore`) |
| structure | 20% | STRUCTURE layer features (BTC trend slope, S/R levels, regime — already built per `confluence/structure/`) |
| flow | 15% | Confirmed deal flow — needs new module that listens to trade prints on the held side |

We have most of the inputs. The missing piece is the AGGREGATION logic (his `absorb_signal` + state vector).

### Phase 2 — Heatmap data layer

New module `strategy_lab/heatmap/`:

```
strategy_lab/heatmap/
├── build.py            # aggregate L25 OB + trades + HL liquidations into price-level map
├── wall_reach.py       # max_move = btc_speed * mins_left; reachable = ...
└── score.py            # contribute to signals via absorb_signal(state, "heatmap_wall", ...)
```

Inputs already in canonical:
- Multi-venue klines (binance + coinbase + kraken + okx 1MIN) → we can derive btc_speed
- L25 OB at any time → wall locations + sizes
- HL liquidations (post-Feb 2026 dir-label drift handled) → liq clusters

### Phase 3 — Kelly sizing with tier caps

Replace fixed $25 notional with edge-scaled sizing:

```python
def kelly_size(edge, entry_px, balance, kelly_mult=0.25):  # quarter-Kelly for safety
    cap = tier_cap(edge)              # 0.005 / 0.010 / 0.015 / 0.020 for MICRO/BRONZE/SILVER/GOLD
    odds = 1.0 / entry_px - 1.0       # binary CLOB odds
    fraction = min(edge / odds * kelly_mult, cap)
    return clip(balance * fraction, MIN_COST=5.0, MAX_COST=50.0)
```

We already have the tier classifier (`strategy_lab/confluence/tier_classifier.py`) — needs an `edge` input. Edge = `signal_prob - entry_px`.

### Phase 4 — DrawdownManager (balance-recovery variant)

Add to existing rail framework. Use his variant (resume on partial balance recovery) as **complementary** to our existing timed pauses (rail_03/04/05). Hybrid:

```python
class DrawdownManagerV2:
    def is_halted(self, total, day_start, peak):
        if (peak - total) / peak >= MAX_DRAWDOWN:
            # Pause until balance recovers to peak - 0.5 * MAX_DRAWDOWN
            self.halted_until_recovery_to = peak * (1 - 0.5 * MAX_DRAWDOWN)
            return True
        if total < self.halted_until_recovery_to:
            return True
        if self.daily_loss_pct(total, day_start) >= DAILY_LIMIT:
            return True
        return False
```

### Phase 5 — Entry filter (middle-of-life time gate)

For 5m markets, fire only between t+90 and t+210 (skip the first 90s and last 90s). For 15m, t+180 to t+720. Test via canonical universe replay before deploying.

### Phase 6 — Calibrator (online weight adaptation)

Per signal class (FLOW, STRUCTURE, momo, etc.), track post-resolution per-trade win/loss. Slow EMA on signal weight (e.g., α=0.02):

```python
def update_weight(self, signal_key, was_correct):
    current_w = self.weights[signal_key]
    target = 1.0 if was_correct else 0.5
    self.weights[signal_key] = (1 - alpha) * current_w + alpha * target
```

Run this from production trade-resolution events.

---

## 12. Strategy ideas this UNLOCKS for our codebase

### A. Confidence-driven sizing (the highest-EV upgrade)
Replace our binary fire (yes/no) with confidence-graded stake. Run the 4-dim brain on canonical universe; output `signal_prob` per market. Stake = Kelly(edge=signal_prob - entry_px). Backtest vs flat-$25 baseline on the 21d full universe.

### B. Cross-venue heatmap as a NEW signal
The canonical klines table has 4 venues (binance/coinbase/kraken/okx). Build the aggregated price-level map he describes — currently NO ONE in our codebase uses it. This is a green-field signal that doesn't exist in the lab.

### C. Adaptive weight calibrator on existing signals
Apply his EMA-based adaptive weights to our existing 14 sleeves' signal scores. Expected: bad sleeves automatically downweight themselves; good sleeves get more allocation. Cleaner than our current "manually disable bad sleeves" approach.

### D. Middle-of-life entry filter
Run our 21d canonical backtest with the t+90..t+210 (5m) / t+180..t+720 (15m) entry window. Compare to current `t+120 fixed`. If lifts edge → cheap win.

### E. Liquidation cluster magnet (validated direction)
Cyclops uses it explicitly. Our `confluence/trigger/liq_magnet.py` was built but underweighted due to data lag. With his explicit wall-reachability discount we can finally validate it properly.

### F. Sentiment as a probability shifter (not binary signal)
We dropped `fetch_news_sentiment.py` because it didn't pass our binary backtests. Per his use, sentiment is a CONTINUOUS shifter of `signal_prob` — try it as a probability nudge (±0.02) instead of a yes/no gate.

---

## 13. What to do next session

Priority order:

1. **Read this document + earlier `CYCLOPS_UPDATE_COMPARISON_2026_05_07.md`** — together they specify the full Cyclops architecture.
2. **Build `strategy_lab/brain/state.py` + `absorb.py` + `confidence.py`** — Phase 1 of the adaptation. Greenfield, no canonical changes.
3. **Wire existing FLOW + STRUCTURE features as inputs** to `absorb_signal`. We already compute these; just route them.
4. **Backtest on canonical 21d universe** — produce `signal_prob` per market, compare to baseline `q90 |ret_2m|` gating.
5. **If `signal_prob` is calibrated to actual win rate**, build Phase 3 (Kelly + tier caps) on top.

Each phase is independently testable. Don't ship the whole thing at once — port his pattern incrementally, validate each piece against our existing baseline.

---

## 14. Hard NOT-to-do

- DO NOT lift his exact `{2: 0.50, 3: 0.54}` constants — those are calibrated to HIS bot's signal count. Build our own calibrator.
- DO NOT abandon our 11-rail safety framework for his single `DrawdownManager`. Add his as a 12th rail, don't replace.
- DO NOT throw away `extended_backtest_with_robustness.py` and rewrite from scratch. The brain is an ADDITIONAL signal layer feeding into the existing engine.
- DO NOT trust his numbers as if they apply to our universe. Re-validate every threshold on canonical.

---

## 15. Source receipts

- Article A full markdown indexed at `ctx_search source: "jina reader btc thread"`
- Article B full markdown indexed at `ctx_search source: "jina reader algo thread"`
- Twitter syndication JSON confirms author + timestamps + article rest_ids
- Earlier Cyclops update analysis: `strategy_lab/reports/CYCLOPS_UPDATE_COMPARISON_2026_05_07.md`

To re-fetch fresh content next session:
```python
mcp__plugin_context-mode_context-mode__ctx_fetch_and_index(
    url="https://r.jina.ai/https://x-thread.org/t/2046690018236735644",
    source="jina reader btc thread",
)
mcp__plugin_context-mode_context-mode__ctx_fetch_and_index(
    url="https://r.jina.ai/https://x-thread.org/t/2048755838358061116",
    source="jina reader algo thread",
)
```

To find newer articles by Gustafssonkotte:
```python
# 1. List his recent tweet IDs via syndication
mcp__plugin_context-mode_context-mode__ctx_fetch_and_index(
    url="https://syndication.twitter.com/srv/timeline-profile/screen-name/Gustafssonkotte",
    source="gustafsson timeline",
)
# 2. For each tweet ID:
mcp__plugin_context-mode_context-mode__ctx_fetch_and_index(
    url=f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&token=a",
    source=f"tweet {tweet_id}",
)
# 3. If tweet has article.rest_id → fetch via r.jina.ai/https://x-thread.org/t/{tweet_id}
```

---

*Generated 2026-05-16. Content quoted from his public articles is fair-use research summary; principles can be re-implemented but DO NOT copy code verbatim — re-derive from our universe.*

---

## 16. 🚨 May 11 pivot — he gutted the architecture above

**Article D — "Deleted half my bot's code and it started winning" (May 11 2026)** — only TL;DR + headline available (x-thread.org cookie-walled on follow-up fetches; unrollnow.com and threadkeeper.io returned no body). What we have, verbatim from DDG/Twitter syndication previews:

> *"TL;DR — The bot traded BTC on Polymarket. WR was 41% on 17 trades, balance was creeping down. I deleted half the codebase: **the voter, the tier table, "fair probability", "edge"**. Rewrote the brain from scratch. **Day 1 after release: 33 trades, 60% WR, balance in the green**. The main fix wasn't new indicators. The main fix was a **conflict detector** …"*

### What he DELETED (from the architecture in §§1-9 above)

| Deleted component | Where it lived in §§1-9 |
|---|---|
| **The voter** | The signal voting/consensus aggregator inside `engine.py` |
| **The tier table** | `tier_cap(edge)` and the GOLD/SILVER/BRONZE/MICRO mapping that drove sizing |
| **"fair probability"** | The hardcoded-then-calibrated `{n_sigs: prob}` lookup table (`{2: 0.50, 3: 0.54, 4: 0.60, 5: 0.66}` from his earlier C-piece) |
| **"edge"** | `edge = signal_prob - entry_px` used inside Kelly sizing |

He KEPT (presumably): module structure, risk manager, infrastructure, the multi-dim state vector itself.

### What he ADDED: a **conflict detector**

We don't have the full content, but the framing ("main fix was a conflict detector") strongly suggests:
- The OLD signal pipeline was firing trades when DIFFERENT signals disagreed
- The 4-dim state could be net-bullish overall even if pressure says BUY and momentum says SELL — averaging hides the conflict
- A conflict detector says: *if your signals disagree, do NOT trade* — wait for coherent state
- This is structurally different from a `consensus_boost` (which amplifies confidence when signals agree); a detector that SKIPS entirely when they don't is the inverse

### Why this matters for us

The deep-dive in §§1-15 was based on his Apr 21 + Apr 27 architecture. **He just told us the second half of that architecture (voter/tier/fair_prob/edge) was actively losing him money** — 41% WR on 17 trades. Deleting it took him from 41% → 60% WR overnight (n=33).

That changes which parts of his pattern are worth porting:

| §11 Phase | Original recommendation | After May 11 pivot |
|---|---|---|
| Phase 1 — 4-dim BrainState | PORT | **STILL PORT** — state vector is the foundation, he kept it |
| Phase 3 — Kelly with tier caps | PORT | **DO NOT PORT** — he deleted this |
| Phase 6 — adaptive calibrator | PORT | **MODIFY** — he deleted the `{n: prob}` mapping but kept the principle of "calibrate to live data". Calibrate WEIGHTS, not the prob mapping |
| (new) **Conflict detector** | (didn't exist) | **NEW HIGHEST-PRIORITY PORT** — skip-on-disagreement is what unlocked his +19pp WR |
| Confidence formula `signal_prob = 0.5 + strength*0.65 + consensus_boost` | PORT | **REVISE** — drop the `+ consensus_boost` half; replace with a coherence/conflict gate that pre-filters BEFORE confidence is computed |
| `edge = signal_prob - entry_px` for sizing | PORT | **DO NOT PORT** — directly admitted bad mapping |

### Conflict detector — proposed implementation for us

We don't have his code. Build from first principles, consistent with how he describes it:

```python
def has_conflict(state, threshold=0.15):
    """Return True iff the four signal dimensions disagree by more than threshold.

    A coherent state has all dims pointing the same way (all positive or all negative).
    A conflicted state has at least one dim opposing the majority direction.
    """
    dims = [state.pressure, state.momentum, state.structure, state.flow]
    # All weakly aligned (< threshold magnitude in any dim) → not enough info, conflict
    if all(abs(d) < threshold for d in dims):
        return True
    # Sign majority direction
    pos = sum(1 for d in dims if d > threshold)
    neg = sum(1 for d in dims if d < -threshold)
    # If both poles have at least one strong vote → conflict
    return pos > 0 and neg > 0


def should_fire(state):
    return not has_conflict(state)
```

Note this is NOT the same as requiring unanimity — only that no dimension OPPOSES strongly. Weak/neutral dims are fine; explicit disagreement isn't.

### What this also implies about §§1-15 (revised reading)

His Apr 27 article said *"Signals do not vote directly — they push a multi-dimensional state vector."* In May 11 he ALSO admits there was STILL a "voter" component he had to delete. So even his own description of his architecture was inconsistent with his code. We should:

1. Take the 4-dim state vector as the ground-truth load-bearing concept.
2. Treat the confidence formula, tier caps, fair-probability table, edge calc as **suspect** — they survived past Apr 27 articles but he himself rejected them by May 11.
3. Treat the conflict detector as the PRIMARY new mechanism, not a refinement.

### Sample-size caveat

His "60% WR Day 1" claim is **n=33**. By our own session's analysis (`MOMO_FULL_UNIVERSE_2026_05_16.md`), n=33 over 1 day is meaningless — our 14d shadow positives at n=20-58 collapsed to negative on the 21d full universe. Apply the same skepticism here: a 60% / 33-trade window is a noise band, not a result. He has been publishing breathless "Day 1 results" since the start.

### Article E (Mar 18) — "Prediction Markets + AI = Unlimited Money Printer"

Title is hyperbolic; bio caveat says *"all content here is sponsored or commissioned"* — likely a paid promo piece, not an architectural disclosure. Preview reads:

> *"Artificial intelligence can analyze sports markets and deliver consistently profitable predictions through a structured pipeline, from data collection to risk management and market adaptation."*

Generic AI-pipeline content. Skip unless full content surfaces.

### Tweet F (Mar 2) — MRO strategy

Tweet text (caught via syndication, not behind any wall):

> *"MRO strategy for 5-minute Bitcoin markets on Polymarket. Custom oscillator catches price reversals. MRO tracks when price moves too far with volume confirmation. **Below -70 signals Up bet. Above +70 signals Down bet.** Calculation compares current price and volume to values from 5 candles ago [video clip attached]"*

MRO is a custom oscillator he built. Pattern: classic mean-reversion (oversold below -70 = buy, overbought above +70 = sell). Uses volume + price 5 candles back. Not a full strategy, more like a single signal. Likely one of the inputs to his `pressure` or `momentum` state-vector dimension. We have similar mean-reversion signals already in `strategy_lab/v4_signals/` (`v52_priceaction.py` etc.) — no strict need to port unless we want a direct comparison.

---

## 17. Final priority order — what to actually build

After incorporating §16:

| # | Component | Why | Effort |
|---|---|---|---|
| 1 | **Conflict detector** (skip-on-disagreement gate) | He says this is THE thing that fixed his WR. Trivial to add as a pre-filter to ANY of our existing signals. | ~half day |
| 2 | **4-dim BrainState** (`strategy_lab/brain/state.py` + `absorb.py`) | Foundation he kept across all 4 articles | 1-2 days |
| 3 | **Wall reachability discount** in `confluence/trigger/liq_magnet.py` | Drop-in tweak; already have liq data + multi-venue prices | half day |
| 4 | **Multi-venue heatmap** (`strategy_lab/heatmap/`) | Aggregate L25 OB + trades + liqs across binance/coinbase/kraken/okx; new capability for us | 3-4 days |
| 5 | **Adaptive weight calibrator** (slow EMA on closed-trade outcomes per signal class) | Survives the May 11 cut | 1 day |
| 6 | **Middle-of-life entry filter** | Cheap; backtest on canonical | half day |
| 7 | **Sentiment as continuous shifter** (not binary gate) | Wholly missing from our codebase | 2 days |
| ❌ | ~~Kelly with tier caps~~ | He deleted this | — |
| ❌ | ~~`fair_probability` lookup~~ | He deleted this | — |
| ❌ | ~~`edge`-based sizing~~ | He deleted this | — |
| ❌ | ~~`consensus_boost`~~ | Subsumed by inverse mechanism (conflict detector skips when no consensus) | — |

The single most valuable thing to port is #1 — **the conflict detector** — because it can be added as a layer ON TOP of our existing momo / FLOW / STRUCTURE signals without rewriting anything. It also lines up with our own `validate_silver_alpha.py` finding that small-sample signals are too noisy: don't fire when uncertain.

---

## 18. Updated source receipts (post May 16 pivot research)

| Source label | URL | Status |
|---|---|---|
| `tweet 2028471 MRO` | syndication tweet-result id 2028471093640470580 | ✅ full short tweet |
| `tweet 2034179 meta` | syndication tweet-result id 2034179153902125253 | ✅ article meta only (preview) |
| `tweet 2046690018236735644 meta` (already had) | syndication tweet-result | ✅ |
| `tweet 2048755838358061116 meta` (already had) | syndication tweet-result | ✅ |
| `tweet 2052286 meta` | syndication tweet-result id 2052286284937220240 | ✅ article meta only (preview) |
| `tweet 2053758 meta` | syndication tweet-result id 2053758338974838857 | ✅ article meta + preview (TL;DR) |
| `jina reader btc thread` | r.jina.ai/x-thread.org/t/2046690018236735644 | ✅ FULL article A markdown |
| `jina reader algo thread` | r.jina.ai/x-thread.org/t/2048755838358061116 | ✅ FULL article B markdown |
| `jina 2053 force` | r.jina.ai/x-thread.org/t/2053758338974838857 | ⚠ cookie-walled, only banner |
| `jina 2034 cachebust` | r.jina.ai/x-thread.org/t/2034179153902125253 | ⚠ cookie-walled |
| `jina 2052 v2` | r.jina.ai/x-thread.org/t/2052286284937220240 | ⚠ cookie-walled |
| `unrollnow 2053` | unrollnow.com/status/2053758338974838857 | ❌ "no text available" |
| `wayback cdx` | web.archive.org/cdx for x.com/Gustafssonkotte/status/* | ❌ empty |
| `ddg deleted half title` | DDG search snippet | ✅ TL;DR text recovered |
| `ddg deleted half content` | DDG search snippet | ✅ same TL;DR confirmed |

To get articles D + E full text in a future session, try (in order):
1. Different jina cache-bust parameter combinations (sometimes works after time passes)
2. Wait 24-48h and re-try x-thread.org via jina (cookie wall may rotate)
3. Use Chrome MCP if connection works
4. Ask user to paste the article body directly *(this is what happened — see §19)*

---

## 19. Operator-pasted content — Day 1 / 2 / 3 cheat-code updates + conflict filter manifesto

User pasted three sequential "UPDATING THE CHEAT CODE FOR POLYMARKET" daily updates plus the conflict-filter manifesto from Article D. This unlocks the actual implementation details. Source: operator-pasted from his X timeline, treated as trusted input.

### 19.1 The real signal decomposition — Q1 / Q2 / Q3 / Q4

Cyclops does NOT use the 4-dim pressure/momentum/structure/flow split from §2. The actual decomposition is:

| Bucket | What it measures | Detection |
|---|---|---|
| **Q1** | **Trend** | Multi-timeframe alignment metric (`MTF`); `s_trend` magnitude; works on 1h candles |
| **Q2** | **Levels** | Support/resistance pivots; works on 15m candles (`Q2_RESAMPLE_FACTOR=30`); outputs `p_up` probability |
| **Q3** | **Momentum / mean-reversion** | OB-driven score `S` on shorter TF; muted ×10 when 3+ timeframes agree |
| ~~Q4~~ | ~~Heatmap voice~~ | **DROPPED** Day 3 — heatmap is noise on 5min, sometimes contrarian |

Multi-TF buffer is 7200 candles = 60h history. Loaded via 20-thread parallel prefill (`DS_PREFILL_WORKERS=20`, `DS_PREFILL_BARS=3000`, ~45s startup vs 96s sequential).

His own description of his Apr 27 "4-dim state vector" turned out to be either misleading or already deprecated by May. The actual taxonomy in production code is Q1/Q2/Q3.

### 19.2 The CONFLICT FILTER — verbatim manifesto

> *"vote_smart wasn't bad — it was architecturally broken in one specific place. When three signals disagreed, the system had no way to detect it. It summed the weights, got a number, and interpreted that number as confidence. That is not confidence. That is the average of contradictions."*

> *"Conflict filter does not add new logic. It removes false entries the system should never have taken. This is not an improvement, this is a fix."*

> *"The old system asked one weighted question. The new one asks three independent questions and measures how much they agree. Trend, Levels, Momentum. If they disagree too much, the trade is skipped. That is the entire fix."*

> *"If conflict filter cuts even half of the bad entries — 70% is achievable without changing any other logic. Just less noise going in."*

Day-1-after-fix result: **33 trades, 60% WR.** Target: 70% via calibration (not rewrites).

### 19.3 Day 1 changes ("UPDATING THE CHEAT CODE")

- **Parallel prefill** — 3000 candles via 20 threads in ~45s. Vars: `DS_PREFILL_BARS=3000`, `DS_PREFILL_WORKERS=20`.
- **Multi-TF architecture** — buffer 500→7200 candles (60h history). New `get_candles(tf)` API. Q2 → 15m. `Q2_RESAMPLE_FACTOR=30`. When 3+ TFs agree → Q3 mean-reversion muted ×10.
- **Pre-emptive re-entry cooldown** — lock on `condition_id` is set RIGHT AFTER ENTRY log, BEFORE Kelly. Old behavior: Kelly blocked first, cooldown never armed → 5 entries in 6s into same market. `REENTRY_COOLDOWN_SEC=30`.
- **Q1 trend strength gate (soft)** — if `|MTF| < Q1_MIN_MTF` then `s_trend *= 0.5`. Most weak setups go to SKIP downstream. `Q1_MIN_MTF=3`.
- **Trading schedule (fractional hours)** — `TRADING_START_UTC` accepts float (`5.83 = 05:50 UTC`). Pause windows: `PAUSE_WINDOWS_UTC=8.0-8.75,17.0-17.5`. Stop: 21:00 UTC.

### 19.4 Day 2 changes

- **Heatmap unwrap fix** — one-line bug killed entire heatmap layer for 2 days. Q3 OB was null in **218/218 cycles** — bot was flying blind. After fix: confidence "jumped significantly, single biggest unlock of the week".
- **OB manipulation guard** — tracks OB volatility over 5s window; if score swings too hard, signal suppressed. `OB_VOLATILITY_THRESHOLD=0.5`.
- **Pause windows** — multiple comma-separated, no more 7am loop-never-stopped.
- **Pre-emptive re-entry cooldown** — same bug class as Day 1; reinforced.
- **Q1 hard trend gate** — promoted from soft (s_trend ×0.5) to HARD SKIP when `|MTF| < Q1_MIN_MTF`. Symmetric UP/DOWN. Cuts trade count ~67%, keeps high-conviction setups. ENV kill switch: `Q1_HARD_GATE=0` reverts.

### 19.5 Day 3 changes (with key reversals)

- **VWAP rolling window** — old cumulative VWAP over 720 5-min candles (60h history) got "stuck" — showed same -0.54% deviation for hours, current price could never catch up to anchor. New: VWAP only over last 24 candles (2h). Standard intraday practice. `VWAP_WINDOW_BARS=24` (0 = old behavior).
- **Blowoff guard (REGIME-SPECIFIC, NOT SYMMETRIC)** — pattern: UP entries with `BB=touch_upper` + `RSI14>=60` + `|MTF|>=3`. Same setup on DOWN side worked fine. *"Logic stays symmetric, market physics doesn't."* Hard SKIP on UP-blowoff entries (reason=`blowoff_up`). DOWN-blowoff stays open. Vars: `BLOWOFF_GUARD_ENABLED`, `BLOWOFF_GUARD_UP`, `BLOWOFF_GUARD_DOWN`, `BLOWOFF_RSI_THRESHOLD=60`, `BLOWOFF_MIN_MTF=3`.
- **Q1 hard trend gate ROLLED BACK** — tried Day 2's hard SKIP on `|MTF|<3`; turned out the problem wasn't weak MTF, it was STRONG-MTF entries on overbought peaks. Reverted to soft gate (`s_trend × 0.5`). ENV switch kept: `Q1_HARD_GATE=0` (default).
- **Q4 heatmap-voice module DROPPED** — diagnostic finding: 4 WIN trades had heatmap screaming DOWN while price went UP. `OB_PRESSURE` and `LIQ_MAGNET` on 5-min are NOISE, sometimes contrarian. "Real diagnostic value, not predictive."

### 19.6 Three silent bugs that were running for weeks (operator's audit)

1. **Wrong sizing applied** — trade tier was getting lost mid-pipeline. Same `UNKNOWN`-tier problem from the May 7 article (also operator-pasted earlier).
2. **Risk pause logged but never enforced** — drawdown limits did nothing. Same `_check_risk()` returning True regardless from the May 7 article.
3. **Bot reporting wins it didn't have** — fake P&L in logs while actual balance trended down. "All silent. All corrupting outcomes for weeks."

### 19.7 Trading hours discipline

> *"Bitcoin moves when institutions move. Trading at 3 AM on a flat tape is just paying spreads. Weekday hours only. Weekends fully off. The bot stays running, only entries are blocked."*

Concrete schedule: `TRADING_START_UTC=5.83` (05:50 UTC), pause windows `8.0-8.75,17.0-17.5`, stop `21:00 UTC`. Bot stays alive but entry-blocked outside hours.

---

## 20. Re-revised priority list (replacing §17)

After §19 the picture is concrete. The conflict filter is THE thing. Build it on top of OUR existing 14-sleeve momo + confluence stack. Order:

| # | Component | Why | Effort |
|---|---|---|---|
| 1 | **Conflict filter** — 3-axis (Trend, Levels, Momentum) coherence gate. Skip when axes disagree. | His Day-1 result (41% → 60% WR) is attributable to THIS alone. Trivial to add. | half day |
| 2 | **Multi-TF prefill** in our backtest engine — load 60h of klines per asset across 1h/15m/5m so MTF metrics are computable. We already have 30d of klines via canonical; just wire the API. | Foundation for any MTF-aware signal | half day |
| 3 | **MTF alignment metric** — count how many timeframes agree on direction (`alignment ∈ [-N, +N]`). Use as `Q1` analog. Replace baseline momo's single-feature `ret_2m` with this. | Direct port of his `s_trend × 0.5` gate (soft version) | 1 day |
| 4 | **15m pivots / S+R levels** — `Q2` analog. We have `confluence/structure/sr_levels.py` already; just wire it into the conflict-filter inputs. | Reuse existing module | half day |
| 5 | **Re-entry cooldown** — lock on `condition_id` IMMEDIATELY after entry log, BEFORE the rest of the order pipeline. Production TV-agent fix; we should mirror. | Same bug pattern they had; we should preemptively guard | (TV agent) |
| 6 | **Trading hours guard** — backtest a "weekday business-hours only" filter on the canonical 21d universe. Drop weekend + off-peak slots; compare WR. | Cheap; canonical has timestamps | half day |
| 7 | **Blowoff guard (regime-asymmetric)** — for our SOL/BTC, find the UP and DOWN equivalents of his `BB+RSI+MTF` blowoff and SKIP asymmetrically. | His own admission that physics isn't symmetric is worth porting | 1 day |
| 8 | **Rolling-window VWAP** in features — replace any cumulative VWAP in our `confluence/flow/features.py` with a rolling 24-bar version. | We may already have this; verify and tighten | half hour |
| 9 | **OB manipulation guard** — track OB score volatility over 5s and suppress if too jumpy. | Trivial; reuses existing L25 stream | half day |
| ❌ | Cross-exchange **heatmap** | Cyclops himself just dropped this — heatmap on 5m is noise. **Do NOT build.** Saves ~3-4 days from prior §17 plan. |
| ❌ | Kelly with tier caps | Already retired in §16 | |
| ❌ | fair_probability lookup | Already retired in §16 | |
| ❌ | edge-based sizing | Already retired in §16 | |

The big shift vs §17: **DROP heatmap**, KEEP conflict-filter at #1. Heatmap was the largest item by effort in the prior plan; cutting it saves ~3-4 days for stuff Cyclops himself has live evidence works.

---

## 21. Implementation skeleton — conflict filter on canonical

This is what to actually build first. Greenfield, no canonical changes required.

`strategy_lab/conflict_filter/`

```python
# strategy_lab/conflict_filter/axes.py
import numpy as np
from typing import Literal

Axis = Literal["trend", "levels", "momentum"]

def compute_trend_axis(klines_1m, klines_15m, klines_1h, ws_s):
    """Q1 analog: MTF alignment.
    Returns: signed alignment in [-3, +3] (one vote per TF).
    """
    votes = []
    for k in (klines_1m, klines_15m, klines_1h):
        slope = rolling_slope(k, ws_s)
        votes.append(int(np.sign(slope)))
    return sum(votes)   # -3..+3

def compute_levels_axis(klines_15m, ws_s, current_px):
    """Q2 analog: levels pivot direction.
    Output: p_up in [0, 1]; 0.5 = no signal.
    """
    pivots = extract_pivots(klines_15m, ws_s, lookback=100)   # last 25h on 15m
    nearest_below = max((p for p in pivots if p < current_px), default=None)
    nearest_above = min((p for p in pivots if p > current_px), default=None)
    if nearest_below is None or nearest_above is None:
        return 0.5
    dist_below = (current_px - nearest_below) / current_px
    dist_above = (nearest_above - current_px) / current_px
    # Asymmetric distance ⇒ pull toward farther level
    return 0.5 + 0.4 * (dist_above - dist_below) / (dist_above + dist_below)

def compute_momentum_axis(trades, ob_snapshots, ws_s):
    """Q3 analog: short-TF momentum / OB pressure.
    Returns: directional score in [-1, +1].
    """
    # Reuse strategy_lab/confluence/flow/features.compute_flow_score
    from strategy_lab.confluence.flow.features import (
        compute_book_features, compute_trade_features, compute_flow_score
    )
    book = compute_book_features(ob_snapshots[-1])
    flow = compute_trade_features(trades, ws_s)
    return compute_flow_score(book, flow)
```

```python
# strategy_lab/conflict_filter/gate.py
def conflict_filter(trend_axis, levels_p_up, momentum_score,
                    levels_min_certainty=0.15,
                    momentum_min_strength=0.15):
    """Cyclops manifesto: 'If they disagree too much, the trade is skipped.'

    Returns: (should_fire: bool, signal_dir: 'Up'/'Down'/None, reason: str)
    """
    # Convert each axis to a SIGNED vote with explicit "no signal" state
    trend_sign = np.sign(trend_axis) if abs(trend_axis) >= 1 else 0
    levels_sign = (
        +1 if levels_p_up > 0.5 + levels_min_certainty else
        -1 if levels_p_up < 0.5 - levels_min_certainty else 0
    )
    momentum_sign = (
        +1 if momentum_score >  momentum_min_strength else
        -1 if momentum_score < -momentum_min_strength else 0
    )

    votes = [trend_sign, levels_sign, momentum_sign]
    pos = sum(1 for v in votes if v > 0)
    neg = sum(1 for v in votes if v < 0)
    abst = sum(1 for v in votes if v == 0)

    # Disagreement: any direct opposition
    if pos > 0 and neg > 0:
        return False, None, f"conflict_pos{pos}_neg{neg}"

    # Too much abstention: not enough info
    if abst >= 2:
        return False, None, f"abstention_{abst}"

    direction = "Up" if pos >= 1 else "Down"
    return True, direction, "coherent"
```

```python
# strategy_lab/conflict_filter/backtest.py
"""Wire conflict_filter into the existing canonical 21d backtest.

Run pattern (mirrors momo_full_universe_canonical):
  for each (slug, ws_s) in resolutions:
      trend_axis    = compute_trend_axis(...)
      levels_p_up   = compute_levels_axis(...)
      momentum      = compute_momentum_axis(...)
      should_fire, direction, reason = conflict_filter(trend_axis, levels_p_up, momentum)
      if should_fire:
          run book-walk fill → record per-trade PnL
      else:
          log skip with reason
"""
```

Backtest on canonical 21d universe (n≈2,909 baseline momo fires). Expect: conflict filter cuts fire rate by 40-60% (matches his ~67% cut). Look for: per-cell `pnl_mean` flip from negative to positive on cells that were losing.

Validation gates same as our existing battery: permutation, walkforward, bootstrap CI. Same bar as `MOMO_FULL_UNIVERSE_2026_05_16.md` — beat -$1.21/tr baseline.

---

## 22. Verbatim quotes worth pinning

These are the lines from his Day-3 essay worth re-reading whenever we're tempted to add complexity:

> *"The system didn't get smarter. It just stopped lying to itself."*

> *"This is not an upgrade. This is surgery."*

> *"I wasn't losing because of a bad strategy. I was losing because I trusted a conclusion with no foundation."*

> *"Q2 p_up=0.50 is not a signal. It's the system saying it doesn't know. I was trading uncertainty."*

> *"Winrate doesn't grow from new features. It grows when you remove what was in the way."*

> *"The hard part wasn't building new indicators. The hard part was deleting the old ones that pretended to work."*

> *"70% WR is a calibration question, not a rewrite question."*

> *"The bot wasn't losing because it was bad. The bot was losing because I was listening to its broken brain. Every loss was a signal. I was averaging them into an entry."*

The headline lesson for us: **WE are also averaging contradictions.** Our `extended_backtest_with_robustness.py` simulator fires when `|ret_2m| >= q90` — a single weighted dimension. No detection of when STRUCTURE disagrees with FLOW. That's exactly what he just diagnosed and fixed.

---

## 23. Updated source receipts (post Day-1/2/3 operator paste)

| Source label | Date | Status |
|---|---|---|
| Operator-pasted Day 1 update | (operator timeline) | ✅ full text |
| Operator-pasted Day 2 update | (operator timeline) | ✅ full text |
| Operator-pasted Day 3 update | (operator timeline) | ✅ full text |
| Operator-pasted Article D manifesto | (operator timeline) | ✅ full conflict-filter section |

These supersede the §18 entries that were "preview only" — we now have the substantive content for Article D.
