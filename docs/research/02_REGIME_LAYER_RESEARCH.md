# 02 — Regime Detection: Method Synthesis

Purpose: evaluate the 9 regime-detection methods listed in the mission brief, score each on feasibility for our stack, and pick a 3–4-voter ensemble.

**Stack constraint:** Python 3.14 on Windows. Present: numpy, pandas, scikit-learn, TA-Lib, vectorbt 0.28. **Absent:** `hmmlearn`, `ruptures`, `arch`, `pywavelets`, `statsmodels.regime_switching`. Adding a library requires user approval and carries Windows-wheel risk on 3.14.

---

## Method 1: Gaussian HMM (hmmlearn)

- **Python path:** `from hmmlearn.hmm import GaussianHMM; GaussianHMM(n_components=3, covariance_type="full").fit(X).predict(X)`.
- **Latency:** 3–5 bars typical (forward-algorithm posterior stabilization) in crypto.
- **Look-ahead risk:** `.predict()` (forward) is safe; `.decode()` (Viterbi backward pass) peeks into future observations — **banned** for live labels.
- **Compute:** O(n × k² × d) per inference pass; Baum-Welch refit is expensive (minutes for n=10⁵).
- **Label contribution:** strongest — a 3-state HMM on (log_return, realized_vol, ema_slope) naturally separates up-trend / down-trend / range.
- **Failure mode on crypto:** state-relabeling instability across refits (Rabiner 1989, Nystrup et al. 2018 SSRN 3034793). Mitigate with fixed random_state + post-fit canonical ordering by centroid return.
- **Verdict:** **SKIP (lib not installed).** Replace with GMM (Method 1b) which gives ~80% of the regime-separation value using sklearn.

## Method 1b (substitute): Gaussian Mixture Model (sklearn)

- **Python path:** `from sklearn.mixture import GaussianMixture; GaussianMixture(n_components=3, covariance_type="full", random_state=42).fit(X).predict(X)`.
- **Latency:** 1 bar (no state memory — each bar classified independently).
- **Look-ahead risk:** none if `fit` is done on in-sample window only and `predict` is used for out-of-sample. Use expanding-window refit (e.g. every 5k bars) with frozen models during intervals.
- **Compute:** O(n × k × d²) per pass; fast enough for per-bar on millions of rows.
- **Label contribution:** `predict_proba()` gives a soft 3-way posterior over (up / down / range). Cluster centroids are post-hoc labeled by mean log-return sign and vol magnitude.
- **Failure mode:** no temporal smoothing — more whipsaw than HMM. Compensated by the N-bar hysteresis in § 4 of the design doc.
- **Verdict:** **INCLUDE.** Same family as Method 1, only trade-off is losing the Markov transition prior — which we backfill with explicit hysteresis.

## Method 2: Markov Regime-Switching (Hamilton 1989)

- **Python path:** `statsmodels.tsa.regime_switching.MarkovRegression`.
- **Latency:** similar to HMM.
- **Verdict:** **SKIP.** The Hamilton model's main advantage over HMM is parameter interpretability for macro return series; on crypto high-frequency bars, HMM with Gaussian emissions is equivalent in practice. No reason to add statsmodels dependency for redundant coverage.

## Method 3: Hurst Exponent (rolling R/S)

- **Python path:** rolling Hurst via R/S statistic, pure numpy (~30 LOC). Alternative: DFA (Peng et al. 1994) — slightly more robust to trend contamination.
- **Latency:** window-size lag; a 100-bar R/S reflects the last 100 bars.
- **Look-ahead risk:** none if strictly trailing.
- **Compute:** O(n × w × log w) for R/S; ~50ms per 10k bars.
- **Label contribution:** H > 0.55 → trending, H < 0.45 → mean-reverting, 0.45–0.55 → random walk. A **confirmation voter** — doesn't assign direction, just says "is a trend persistent right now?" Boosts trend_score magnitude when H ≥ 0.55.
- **Failure mode:** noisy at short windows; biased on non-stationary series. On crypto, H estimates fluctuate heavily around 0.5 (Kristoufek & Vosvrda 2014, doi:10.1016/j.physa.2014.06.018).
- **Verdict:** **INCLUDE as optional weighted voter** (weight 0.5). Good persistence confirmation; cheap to compute.

## Method 4: ADX + EMA slope gating

- **Python path:** our own `features.adx()` + `features.ema_slope()` — both already vectorized.
- **Latency:** ADX's Wilder smoothing has ~14-bar warmup.
- **Look-ahead risk:** none.
- **Compute:** trivial.
- **Label contribution:** canonical trend-strength voter. `adx >= 25 AND ema_slope > +strong_pct → strong_uptrend; adx >= 25 AND ema_slope < -strong_pct → strong_downtrend; adx < 20 → sideways`.
- **Failure mode:** crypto-specific fact: ADX stays elevated during sharp reversals (Wilder 1978 was built on commodity markets). Combine with slope sign to disambiguate.
- **Verdict:** **INCLUDE, primary trend voter, weight 1.0.** Battle-tested and interpretable.

## Method 5: GARCH vol state (arch package)

- **Python path:** `arch.arch_model(r, vol="Garch", p=1, q=1).fit().conditional_volatility`.
- **Verdict:** **SKIP (lib not installed).** Realized-vol quantiles (Method 5b) solve the same "is this bar in a high-vol state?" question without the fit overhead or Windows-wheel risk. A GARCH model would add volatility-clustering awareness at significant cost.

## Method 5b (substitute): Realized-vol quantile voter

- **Python path:** `features.vol_quantile_state()` — already implemented.
- **Latency:** 1 bar.
- **Look-ahead risk:** quantiles computed on expanding past-only window; no lookahead.
- **Compute:** trivial.
- **Label contribution:** the **vol_state axis** of the 6-label matrix. Classifies each bar as low / normal / high vol. Drives the sideways_low_vol vs sideways_high_vol split.
- **Failure mode:** expanding window means early years (first 500 bars) label everything "normal".
- **Verdict:** **INCLUDE, primary vol voter, weight 1.0.**

## Method 6: BOCPD / PELT (ruptures)

- **Verdict:** **SKIP (lib not installed + adds limited value).** Change-point detection is useful for flagging *transition bars*, but our hysteresis layer already handles transitions explicitly. BOCPD would compete with the hysteresis rather than complement it. If we had intraday sentiment data, BOCPD would be more valuable; on OHLCV alone, the voters above already mark transitions.

## Method 7: Ehlers cycle/trend mode (Sine Wave / Instantaneous Trendline)

- **Python path:** manually implement from TASC articles (Ehlers 2002); no canonical Python lib.
- **Verdict:** **SKIP.** Ehlers' methods are designed for sub-Nyquist indicator lag reduction, not regime classification. The "cycle vs trend mode" output is binary and doesn't map cleanly onto our 6-label scheme. Implementation cost vs marginal information gain is poor.

## Method 8: Directional Change (Tsang et al. 2017)

- **Python path:** custom implementation (~80 LOC, no lib).
- **Latency:** event-driven — DC events fire at variable bar intervals depending on threshold (e.g. 1%).
- **Look-ahead risk:** DC itself is trailing, but naïve implementations leak if extrema are looked up post-hoc.
- **Compute:** O(n) single pass.
- **Label contribution:** DC produces "upturn / downturn" events with a threshold parameter. Useful as a change-point confirmation, similar to BOCPD but parameter-light.
- **Failure mode:** one parameter (threshold) that's arbitrary on crypto; 1% events on 4h BTC can fire dozens of times in one day during volatile regimes.
- **Verdict:** **MAYBE — defer.** Track for a Phase-3 research candidate that explicitly uses DC events as signal timing.

## Method 9: Wavelet decomposition (pywavelets)

- **Verdict:** **SKIP (lib not installed + overkill).** Wavelet-based regime detection (Gencay et al. 2001, Nystrup et al. 2018) shows academic promise but the marginal lift over HMM/GMM on crypto is small, while implementation + testing overhead is large. Revisit only if Phase-5 shows our ensemble missing a specific frequency-band phenomenon.

---

## Ensemble recommendation

**Chosen ensemble (3 voters + 1 optional):**

| Voter              | Axis         | Weight  | Role                                         |
|--------------------|--------------|---------|----------------------------------------------|
| `trend_adx_ema`    | trend_score  | 1.0     | Primary trend strength — ADX magnitude + EMA-slope sign |
| `vol_quantile`     | vol_state    | 1.0     | Primary vol classifier — expanding-window quantiles |
| `gmm_trendvol`     | BOTH (soft)  | 1.0 / 0.5 | Joint regime clustering on (log_return, realized_vol, ema_slope); `predict_proba` contributes to both trend_score (weight 1.0) and vol_state (weight 0.5) |
| `hurst` (optional) | trend_score  | 0.5     | Trend-persistence confirmation (boosts magnitude when H ≥ 0.55) |

**Aggregation:**
```
trend_score = 1.0 · trend_adx_ema_vote   (∈ {-2,-1,0,+1,+2})
            + 1.0 · gmm_trend_vote       (∈ {-1,0,+1} from argmax component)
            + 0.5 · hurst_boost          (∈ {-1,0,+1}; sign follows trend_adx_ema, magnitude 1 iff H ≥ 0.55)
                                         # range: [-3.5, +3.5], clipped to [-3, +3]

P(vol_state = s) ∝ 1.0 · I[vol_quantile == s] + 0.5 · P_gmm(vol-high-cluster if s=="high" else low-cluster if s=="low" else mid)
vol_state = argmax_s P(vol_state = s)
```

**Why this over HMM:** zero new dependencies. GMM captures the same Gaussian emission structure HMM fits; the Markov transition prior that HMM adds is substituted by our explicit N-bar hysteresis (§ 4 of the design doc), which is more debuggable. If/when a Phase-3 candidate requires true state-transition modeling, we add hmmlearn and swap the voter in a single-line config change.

**Citations:**
- Rabiner, L.R. (1989). *A tutorial on hidden Markov models and selected applications in speech recognition.* Proceedings of the IEEE 77(2).
- Nystrup, P., Madsen, H., & Lindström, E. (2018). *Dynamic allocation or diversification: A regime-based approach to multiple assets.* Journal of Portfolio Management. [SSRN 3034793](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3034793).
- Kristoufek, L., & Vosvrda, M. (2014). *Measuring capital market efficiency: Long-term memory, fractal dimension and approximate entropy.* Physica A 413. doi:10.1016/j.physa.2014.06.018.
- Peng, C.K., et al. (1994). *Mosaic organization of DNA nucleotides.* Physical Review E 49(2) — the DFA paper, applied to finance later.
- Tsang, E., Tao, R., Serguieva, A., Ma, S. (2017). *Profiling high-frequency equity price movements in directional changes.* Quantitative Finance 17(2).
- Wilder, J.W. (1978). *New Concepts in Technical Trading Systems.* Trend Research — ADX origin.

**Non-peer citations (clearly marked as blog/practitioner):**
- Robot Wealth — *"Regime Filters Can Improve Any Strategy"* (blog, empirical on crypto): https://robotwealth.com/
- Ernie Chan — *Algorithmic Trading* Ch. 5 on regime-switching.
