# 02 — Regime Detection Layer (Design)

**Status:** Design locked prior to implementation. Research synthesis lives in `02_REGIME_LAYER_RESEARCH.md` (pending).

---

## § 1. Output Contract

The regime classifier returns two per-bar series, aligned to the input OHLCV `DatetimeIndex`:

```python
def classify_regime(df: pd.DataFrame) -> pd.DataFrame:
    """
    Parameters
    ----------
    df : pd.DataFrame
        OHLCV with DatetimeIndex (monotonic, UTC, no gaps).
        Required columns: open, high, low, close, volume.
        Minimum length: 500 bars (warmup).

    Returns
    -------
    pd.DataFrame
        Same index as df. Columns:
          label       : category[6 labels below] — the regime classification
          confidence  : float in [0, 1] — ensemble agreement strength
          trend_score : float in [-3, +3] — signed strength vote from trend methods
          vol_state   : category{"low", "normal", "high"}
          change_pt   : bool — True on bars flagged as regime transitions
    """
```

**The 6 labels:**

| Label               | Criteria (pre-smoothing)                                |
|---------------------|---------------------------------------------------------|
| `strong_uptrend`    | trend_score ≥ +2 AND vol_state in {low, normal}          |
| `weak_uptrend`      | trend_score = +1 (any vol)                              |
| `sideways_low_vol`  | abs(trend_score) ≤ 0.5 AND vol_state == "low"           |
| `sideways_high_vol` | abs(trend_score) ≤ 0.5 AND vol_state == "high"          |
| `weak_downtrend`    | trend_score = −1 (any vol)                              |
| `strong_downtrend`  | trend_score ≤ −2 (any vol; extreme-vol bear counts here) |

Normal-vol sideways is absorbed into `sideways_low_vol` (tighter bucket, fewer false "high-vol" labels in calm markets). This 2-axis decomposition (trend × vol) reduces the labeling problem to two smaller classifiers that vote.

**Confidence scoring:** number of ensemble methods voting for the majority label ÷ total methods. A 4-method ensemble with 3 agreeing → confidence = 0.75.

---

## § 2. No-Lookahead Safeguards (hard rules)

1. Every rolling computation uses `.rolling(window)` and NEVER `.rolling(window, center=True)`.
2. HMM / Markov-switching / BOCPD: **Only `.predict(...)` or equivalent forward-pass output is used.** Smoothing via Viterbi backward pass is forbidden for *live* labels (backward pass uses future observations to refine past labels — that's look-ahead). A separate "research-only" smoothed output MAY be exposed under a `smoothed=True` flag for post-hoc analysis, never for backtest signals.
3. Indicator warmup: first `max_warmup` bars produce `label = "sideways_low_vol"` (safest neutral) and `confidence = 0.0`.
4. Hysteresis smoothing (see § 4) uses only trailing labels — never forward.
5. **Unit test:** `test_no_lookahead_shift_invariance` — running `classify_regime(df.iloc[:-k])` must produce labels identical to `classify_regime(df).iloc[:-k]` for every `k ∈ {1, 5, 10, 100}`. Any divergence = bug.

---

## § 3. Ensemble Composition

Selected **3 primary voters + 1 optional**. Full rationale in `02_REGIME_LAYER_RESEARCH.md` — key substitutions driven by stack constraints (no `hmmlearn` / `ruptures` / `arch`):

| Voter              | Axis         | Weight  | Role                                         |
|--------------------|--------------|---------|----------------------------------------------|
| `trend_adx_ema`    | trend_score  | 1.0     | ADX magnitude + EMA-slope sign → vote in {−2,−1,0,+1,+2} |
| `vol_quantile`     | vol_state    | 1.0     | Expanding-window realized-vol quantile (no-lookahead) |
| `gmm_trendvol`     | both (soft)  | 1.0 / 0.5 | GaussianMixture on (log_return, realized_vol, ema_slope); `predict_proba` feeds both axes |
| `hurst` (optional) | trend_score  | 0.5     | Trend-persistence confirmation (boosts magnitude when H ≥ 0.55) |

### § 3.1 Substitutions vs mission brief

- **HMM → GaussianMixture.** `hmmlearn` isn't installed on the py-3.14 venv and Windows-wheel availability is fragile. GMM captures the same Gaussian emission structure; the Markov transition prior HMM adds is backfilled by our explicit N-bar hysteresis (§ 4). One-line config swap restores HMM if/when a Phase-3 candidate needs it.
- **GARCH → realized-vol quantile.** Same rationale — `arch` isn't installed. Expanding-window vol quantiles answer the "low vs normal vs high" question we care about without GARCH's volatility-clustering overhead.
- **BOCPD / PELT / Markov-switching / Ehlers / DC / wavelet — skipped.** Either redundant with the 3 primary voters, or marginal lift vs implementation cost on OHLCV. See research doc for per-method verdicts.

### § 3.2 Vote aggregation

```
trend_score = 1.0 · trend_adx_ema_vote         # ∈ {-2,-1,0,+1,+2}
            + 1.0 · gmm_trend_vote             # ∈ {-1,0,+1} from argmax component
            + 0.5 · hurst_boost                # sign from ADX-EMA, magnitude 1 iff H ≥ 0.55
                                                # raw range: [-3.5, +3.5]; clipped to [-3, +3]

P(vol=s) ∝ 1.0 · I[vol_quantile == s] + 0.5 · gmm_vol_posterior(s)
vol_state = argmax_s P(vol=s)
```

`confidence = min(1.0, |trend_score| / 3.0)`. Low-trend-score bars inherit a small vol-voter-agreement bonus so sideways labels aren't always 0-confidence.

---

## § 4. Hysteresis / Whipsaw Suppression

Raw per-bar labels are noisy. Applied AFTER classification:

1. **N-bar confirmation (hard):** A new label becomes active only after `N_confirm` consecutive bars with that label. Default `N_confirm = 3` on 4h (≈ 12h), scaled proportionally on other TFs. Until confirmed, the previous label persists.
2. **Hold-floor (soft):** Once a label is confirmed, the classifier cannot switch for `N_hold_floor` bars (default 5). Prevents 1-bar flip-flops.
3. **Confidence-gated switching:** A label change that crosses a *category* boundary (e.g. uptrend ↔ sideways) requires `confidence ≥ 0.6`. Intra-category drift (weak_uptrend ↔ strong_uptrend) is unrestricted.

All three are trailing-only (no look-ahead).

---

## § 5. Module Layout

```
strategy_lab/regime/
├── __init__.py          # exports classify_regime, RegimeConfig, load_regime_labels
├── regime_classifier.py # orchestrator — runs voters, aggregates, applies hysteresis
├── voters/
│   ├── trend_adx_ema.py # ADX + EMA-slope trend voter
│   ├── hmm_gaussian.py  # Gaussian HMM voter (lazy-imports hmmlearn if available)
│   ├── vol_quantile.py  # realized-vol quantile voter
│   ├── hurst.py         # rolling Hurst exponent (R/S or DFA)
│   └── bocpd.py         # Bayesian online change-point (optional, feature-flagged)
├── features.py          # shared feature engineering (log returns, ATR, realized vol, etc.)
└── config.py            # RegimeConfig dataclass + default presets
```

`classify_regime()` instantiates a `RegimeConfig` (sets which voters run, their weights, hysteresis params), calls each voter, runs aggregation, applies hysteresis, returns the DataFrame.

---

## § 6. RegimeConfig

```python
@dataclass(frozen=True)
class RegimeConfig:
    voters: tuple[str, ...] = ("trend_adx_ema", "hmm_gaussian", "vol_quantile")
    trend_weights: dict[str, float] = field(default_factory=lambda: {
        "trend_adx_ema": 1.0, "hmm_gaussian": 1.0, "hurst": 0.5,
    })
    vol_weights: dict[str, float] = field(default_factory=lambda: {
        "vol_quantile": 1.0, "hmm_gaussian": 0.5,
    })
    # Hysteresis
    n_confirm_bars: int = 3
    n_hold_floor_bars: int = 5
    category_switch_min_confidence: float = 0.6
    # HMM specifics
    hmm_n_states: int = 3
    hmm_n_iter: int = 50
    hmm_random_state: int = 42
    # Trend method specifics
    adx_period: int = 14
    adx_strong_threshold: float = 25.0
    ema_slope_fast: int = 20
    ema_slope_slow: int = 50
    # Vol quantile bins (computed on expanding window, lag-1 to avoid lookahead)
    vol_low_quantile: float = 0.33
    vol_high_quantile: float = 0.66
    # Warmup
    warmup_bars: int = 500
```

Presets for different timeframes live in `config.py`:
- `REGIME_4H_PRESET`
- `REGIME_1H_PRESET` (faster ADX, smaller windows, higher n_confirm)
- `REGIME_15M_PRESET` (very fast, n_hold_floor increases to offset noise)

---

## § 7. Test Plan

### § 7.1 Unit tests (synthetic data — deterministic)

- `test_label_mapping_covers_all_combinations` — every (trend_score, vol_state) combo routes to exactly one of the 6 labels.
- `test_warmup_returns_neutral` — first 500 bars all map to sideways_low_vol with confidence=0.
- `test_hysteresis_blocks_whipsaw` — inject a synthetic 1-bar flip; classifier must suppress it.
- `test_confidence_bounds` — confidence in [0, 1] on every bar post-warmup.
- `test_no_lookahead_shift_invariance` — per § 2 rule 5.
- `test_voter_independence` — disable each voter one at a time; result changes but stays valid.

### § 7.2 Historical regression (real BTC 4h)

Dated windows where the "right" answer is common-knowledge obvious:

| Window                          | Expected dominant label     | Tolerance        |
|---------------------------------|-----------------------------|------------------|
| 2020-03-01 → 2020-04-15 (COVID) | `strong_downtrend` + `sideways_high_vol` mix | ≥ 70% of bars in either |
| 2021-01-01 → 2021-04-15         | `strong_uptrend`            | ≥ 60% of bars    |
| 2022-05-01 → 2022-11-30 (LUNA/FTX) | `strong_downtrend` + `weak_downtrend` | ≥ 65% combined |
| 2023-05-01 → 2023-10-01 (range) | sideways_*                  | ≥ 70% sideways_*  |
| 2024-01-01 → 2024-04-15         | `strong_uptrend`            | ≥ 60% of bars    |

Test asserts these counts. A failing window flags a voter that needs tuning, not a hard reject — retune and re-run.

### § 7.3 Whipsaw metric

Count regime flips per 1000 bars on BTC 4h across 2020-2024. Target: **≤ 25 flips / 1000 bars** on the post-hysteresis output. Higher = hysteresis under-damped.

---

## § 8. Integration with Strategies

A consuming strategy receives the per-bar regime labels and decides how to react:

```python
# inside strategy_lab/strategies/adaptive/foo.py
from strategy_lab.regime import classify_regime, REGIME_4H_PRESET

def generate_signals(df):
    regime = classify_regime(df, config=REGIME_4H_PRESET)
    labels = regime["label"]

    # Example: trend-follow only in strong uptrend/downtrend; skip chop
    active = labels.isin(["strong_uptrend", "strong_downtrend"])
    entries = raw_trend_entries & active
    exits   = raw_trend_exits | (labels != labels.shift(1))  # regime-flip exit
    return {"entries": entries, "exits": exits}
```

The regime DataFrame is cached on disk at `strategy_lab/regime/cache/{symbol}_{tf}_{config_hash}.parquet` so Phase-5 grid runs don't recompute for every strategy.

---

## § 9. Open Questions (for user review)

1. **HMM state count.** Literature suggests 3–5 states is typical. Default is 3 (up/down/range) but 4 (up/down/low-vol-range/high-vol-range) maps more cleanly onto the 6 labels. Research agent will settle this in § 3.
2. **Hysteresis defaults per TF.** 4h N_confirm=3 feels right; 15m N_confirm=12 (≈ 3h). Review after § 3 research.
3. **Cache invalidation.** Config hash drives cache filenames. If we tweak a voter, every cached regime label becomes stale. Acceptable friction?
4. **Confidence threshold for strategies.** Should strategies receive filtered labels (confidence ≥ 0.6) or raw labels plus confidence score and decide per-strategy? Default: expose both; strategy picks.
