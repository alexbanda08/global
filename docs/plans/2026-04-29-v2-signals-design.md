# V2 Signals — A new UpDown strategy from zero (Approach 2: signal-stack)

**Date:** 2026-04-29
**Status:** Design approved, ready for implementation plan
**Predecessor:** sig_ret5m (existing). Backtest hit 78%, live hit 22-49%. Suggests live-execution issues + monoculture risk on a single magnitude signal.

---

## 1. The premise

Move from a single signal (`|ret_5m|` magnitude → bet WITH direction) to a **stack of three calibrated probability signals** that exploit different inefficiencies:

- **A — Multi-horizon momentum agreement** (a different directional signal)
- **B — Vol-arb / digital fair-value pricing** (no direction; pure mispricing)
- **C — Polymarket microstructure / flow** (no Binance; pure prediction-market signal)

Each emits `P(UP) ∈ [0,1]` per market. A logistic-regression **stack** combines them. We test all 4 (A, B, C, stack) individually against the same forward-walk gate as sig_ret5m. The best survivor ships.

**Building philosophy:** YAGNI ruthlessly. Reuse existing infrastructure. Three new signal columns + one stack column added to `features_v3.csv`. The 36 existing engines (signal_grid_v2, forward_walk_v2, maker_entry, microstructure_filter, …) consume them automatically.

---

## 2. Architecture

```
data/binance/{asset}_klines_window.csv   ────┐
data/binance/{asset}_metrics_window.csv  ────┤
data/polymarket/{asset}_markets_v3.csv   ────┼──► polymarket_build_features.py
data/polymarket/{asset}_book_depth_v3.csv ───┤    (existing)  → features_v3.csv [base columns]
                                              │
                                              ├──► v2_signals/build_signal_a.py  → adds prob_a column
                                              ├──► v2_signals/build_signal_b.py  → adds prob_b column
                                              ├──► v2_signals/build_signal_c.py  → adds prob_c column
                                              └──► v2_signals/build_stack.py     → adds prob_stack column

features_v3.csv  ──►  signal_grid_v2.py / forward_walk_v2.py / etc. (existing, unchanged except signal list)
                                              │
                                              ▼
                  results/polymarket/v2_signals_*.csv
                  reports/POLYMARKET_V2_SIGNALS_FINDINGS.md
```

Single edit point on existing code: add `prob_a, prob_b, prob_c, prob_stack` to the signal-name list inside `signal_grid_v2.py` and `forward_walk_v2.py`. Threshold rule for prob signals:

```python
if prob > 0.55:  bet UP
elif prob < 0.45: bet DOWN
else:             SKIP
```

(The 0.55/0.45 band is grid-searched per signal in {0.52, 0.55, 0.58, 0.60, 0.65} during build.)

---

## 3. Signal A — Multi-horizon momentum agreement

**Definition:**
```python
votes_up = int(ret_5m  > 0) + int(ret_15m > 0) + int(ret_1h  > 0)
raw_a    = votes_up / 3.0   # ∈ {0.000, 0.333, 0.667, 1.000}
```

**Calibration to probability:** raw_a is one of 4 buckets — too coarse. On the train slice, compute empirical `P(outcome_up=1)` per `(votes_up, asset, tf)` triple. Use that as `prob_a`. Bucket with <20 train samples falls back to 0.5.

**Differs from sig_ret5m:** no magnitude filter. Captures regime (drifting trend) instead of impulse (single big bar).

**Hypothesis:** ret_15m and ret_1h had near-0 univariate IC, but their AGREEMENT with ret_5m should distinguish trend from spike. If true, prob_a will outperform sig_ret5m in chop regimes.

**Computation cost:** trivial. All 3 returns already in features_v3.

---

## 4. Signal B — Vol-arb / digital fair value

**Definition:** treat each binary as a digital option, price it analytically.

```python
T = (slot_end_us - now_us) / 1_000_000             # seconds remaining
σ = realized_vol(binance_1m_close, last_1440_min)  # daily realized vol
σ_T = σ * sqrt(T / 86400)                          # scaled to remaining tenor
S  = current_binance_close
S0 = strike_price                                  # already in features_v3 (window-start spot)
d  = (ln(S / S0) + 0.5 * σ_T**2) / σ_T
fair_yes = norm.cdf(d)
prob_b   = fair_yes
```

**Calibration:** raw `prob_b` may be miscalibrated due to model assumptions (lognormal returns, no jumps). Apply isotonic regression on train slice mapping `raw → empirical hit rate`.

**Differs from A:** no historical returns. Uses *current* spot, *strike*, *time-remaining* — captures mid-window drift toward strike.

**Hypothesis:** retail traders price binaries directionally without doing vol math. Sub-15-minute digitals systematically mispriced vs realized vol. Model edge ∝ |fair_yes - market_yes|.

**Computation cost:** moderate. Need rolling realized vol; readily computable from existing klines_window.

---

## 5. Signal C — Polymarket microstructure / flow

**Definition:** zero Binance. Pure Polymarket-side signal from `trades_v2` and `book_depth_v3.csv`.

**C1 — Trade-tape pressure (last 60s of resolved-market trades):**
```python
yes_buy = sum(t.size for t in trades_60s if t.side=='buy' and t.token=='YES')
yes_sell = sum(t.size for t in trades_60s if t.side=='sell' and t.token=='YES')
no_buy  = sum(t.size for t in trades_60s if t.side=='buy' and t.token=='NO')
no_sell = sum(t.size for t in trades_60s if t.side=='sell' and t.token=='NO')
flow = ((yes_buy - yes_sell) - (no_buy - no_sell)) / (total_volume + 1e-6)
```
Range [-1, +1]. Positive = aggressive YES buying (pressure for UP).

**C2 — Book imbalance (current top-5 ask-size both sides):**
```python
yes_ask5 = sum(ask_size_0..4) on YES side
no_ask5  = sum(ask_size_0..4) on NO side
imbalance = (no_ask5 - yes_ask5) / (no_ask5 + yes_ask5 + 1e-6)
```
Positive = NO has more sellers → MMs cheaply offer NO → they expect UP.

**Combine:**
```python
raw_c  = 0.6 * flow + 0.4 * imbalance  # ∈ [-1, +1]
prob_c = 0.5 + 0.4 * raw_c              # squash to [0.1, 0.9]
```
Re-calibrate via isotonic on train.

**Hypothesis:** Polymarket has real microstructure. Smart MMs vs retail leaks resolution direction.

**Computation cost:** highest. Need to bucket the 8M trades_v2 prints by market_id and the 60-second pre-resolution window. Indexed query, doable.

---

## 6. Stack meta-model

```python
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV

X_train = features[['prob_a', 'prob_b', 'prob_c']].values
y_train = features['outcome_up'].values

base = LogisticRegression(C=1.0, fit_intercept=True)
clf  = CalibratedClassifierCV(base, cv=3, method='isotonic')
clf.fit(X_train, y_train)

prob_stack = clf.predict_proba(X_full)[:, 1]
```

3-fold isotonic on top of logistic regression. Coefficients are inspectable. We log:
- LogReg weights `[w_a, w_b, w_c]` and intercept
- Per-feature contribution analysis
- Calibration plot (binned predicted vs actual hit rate)

**Threshold grid-search:** `{0.52, 0.55, 0.58, 0.60, 0.65}` × signal — pick the threshold that maximizes train ROI; lock for holdout.

---

## 7. Validation gates

Per signal, must clear ALL:

| Gate | Threshold |
|---|---|
| Forward-walk holdout hit rate | ≥ 60% |
| Holdout ROI | ≥ +10% on $25 stake |
| Train → holdout hit drift | ≤ 8 pp degradation |
| Day-by-day robustness | no single day < 45% hit |
| Live-tape reconciliation | within 10 pp of backtest hit (when ≥30 live samples exist) |

Decision tree:
- Stack passes, components fail → ship stack.
- Components pass, stack adds < 2pp lift → ship best component.
- Multiple components pass independently → ship as parallel sleeves with stack as 4th.
- Nothing passes → abandon, stick with sig_ret5m sniper q10.

---

## 8. Build artifacts

New files (under `strategy_lab/v2_signals/`):
- `build_signal_a.py` — adds `prob_a` to features_v3.csv (asset-templated via env var)
- `build_signal_b.py` — adds `prob_b` (needs rolling realized vol)
- `build_signal_c.py` — adds `prob_c` (needs trades_v2 indexed by market_id)
- `build_stack.py` — fits LogReg + isotonic, adds `prob_stack`
- `run_v2_signals_pipeline.sh` — orchestrator: builds all 4 columns then triggers existing engines

Edited files (existing):
- `polymarket_signal_grid_v2.py` — add 4 entries to signal list
- `polymarket_forward_walk_v2.py` — same

Deliverables:
- `results/polymarket/v2_signals_grid.csv`
- `results/polymarket/v2_signals_forward_walk.csv`
- `reports/POLYMARKET_V2_SIGNALS_FINDINGS.md` — synthesis + ship/kill decision

---

## 9. Out of scope (explicit)

- No new ML beyond logistic regression (8,200 samples × 3 features = no gradient-boosting)
- No new features beyond what's needed for A, B, C (auxiliary features had IC ~0)
- No new exit logic — reuse existing rev15 + HEDGE_HOLD + maker entry
- No live deploy — backtest-only this round
- No new trades_v2 ETL beyond the 60s pre-resolution window per market
- No 5m-vs-15m optimization — run both, pick winner per signal

---

## 10. Risk register

| Risk | Mitigation |
|---|---|
| 7 days too thin for 3-feature LogReg fit | Per-feature univariate IC inspection BEFORE training the stack. If any IC <0.02, drop it from the stack. |
| Look-ahead bias in B (uses "current" spot mid-window) | All B inputs are evaluated AT window-start, never mid-window. Strict snapshot timestamp ≤ slot_start_us. |
| C requires expensive trades_v2 join | Pre-aggregate at SQL extraction time: emit `{asset}_flow_v3.csv` with per-market 60s pre-window flow. |
| Stack overfits 7d sample | 3-fold cross-validated isotonic + LogReg. Compare in-sample vs holdout R² to detect. |
| All 4 signals correlate tightly with ret_5m | Compute pairwise corr(prob_x, ret_5m) and corr matrix on prob_a/b/c. If any pair > 0.85, drop the redundant one. |
