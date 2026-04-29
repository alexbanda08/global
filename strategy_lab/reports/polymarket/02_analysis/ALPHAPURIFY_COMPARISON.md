# AlphaPurify — Repo Analysis & Theft List

**Date:** 2026-04-28
**Source:** https://github.com/eliasswu/AlphaPurify (commit cloned to `_scratch/alphapurify`)
**Author:** Elias Wu — pip package `alphapurify` v0.1.8
**Stack:** Python 3.10+, Polars, DuckDB, Arrow, joblib, scikit-learn, Plotly. ~9k LOC across 5 modules.

---

## 1. Summary

AlphaPurify is a **cross-sectional equities factor research library** — Alphalens with a built-in long/short rebalance backtester, 40+ winsorize/standardize methods, and Plotly reports. It assumes a panel of symbols × dates with a continuous factor and computes IC (rank correlation, by date) + quantile-bin rebalance returns. **It is not a trade-level backtester.** No orderbook, no fills, no maker/taker, no hedging, no transaction-cost model (turnover tracked, never debited). Speed comes from Polars + Arrow IPC mmap + joblib `Parallel` across rebalance periods/horizons. Validation framework is single-period IC stats — no walk-forward, no permutation tests, no out-of-sample split.

**Bottom line:** the repo is the wrong shape for both our engines. Engine A (Polymarket UpDown) is per-trade event-driven on binary CTF outcomes — there is no "panel" to rank. Engine B (Hyperliquid perps) is closer in shape but our V52 champion is single-asset momentum, not cross-sectional ranking. Theftable items are tooling fragments (IC formula, Polars/Arrow speed pattern, stats dict), not architecture.

---

## 2. AlphaPurify — what's actually inside

### 2.1 Module map

| Module | LOC | Purpose |
|---|---:|---|
| `alphapurify/AlphaPurifier.py` | 220 | Builder DSL: `.winsorize().standardize().neutralize().to_result()` |
| `alphapurify/APr_utils.py` | 3726 | 40+ winsorize/standardize functions (mean-std, MAD, IQR, Box-Cox, RANSAC, Huber, RankGauss, Tanh, Yeo-Johnson, EWMA, …) |
| `alphapurify/FactorAnalyzer.py` | 2755 | IC + quantile rebalance backtest + Plotly sheets |
| `alphapurify/Database.py` | 584 | Parquet/DuckDB factor store, `process_code` worker |
| `alphapurify/Exposures.py` | 1426 | `PortfolioExposures`, `PureExposures` — cross-sectional regression for factor return attribution |

### 2.2 Backtest engine (FactorAnalyzer)

- **Inputs:** panel `base_df` with `[trade_date_col, symbol_col, price_col, factor_name]`.
- **Configs:** `ResearchConfig(rebalance_periods=[1,5,10], return_horizons=[1,5,10], bins=5, base_rate=0.02, overnight="on")` + `AnalysisConfig(rank_ic=True, max_workers=-1)`.
- **Core methods:**
  - `calc_stats_for_period(args)` (L406) — quantile rebalance for one period: bin into 5, build long/short legs, compute returns & turnover, output stats dict.
  - `calc_stats_for_horizon(args)` (L849) — IC for one forward-return horizon: `pl.corr(factor, fut_ret, method="spearman")` grouped by trade date.
  - `run_stats_parallel()` (L1025) — writes `base_df` to Arrow IPC file in tempdir, joblib workers `pa.memory_map()` it, fan out across `rebalance_periods × return_horizons`. Avoids pickle overhead.
- **Stats per quantile bucket / long-short:** `Ann. Return, Ann. Std, Ann. Sharpe, Ann. Sortino, Ann. Calmar, Mean Turnover, Max Drawdown, Win Rate, PnL`.
- **No execution model:** turnover is computed (pct of names that changed between rebalances) but never debited. No fees, no slippage, no fill model.
- **No validation:** single-pass IC + quantile stats. No walk-forward, no permutation, no train/test split.

### 2.3 Preprocessing (AlphaPurifier)

40+ functions in three categories:
- **Winsorize:** `mean_std, mad, iqr, quantile, rolling_quantile, boxcox_compress, zscore, rankgauss, tanh, huber, ransac, volatility, …` (k-sigma & quantile clipping variants)
- **Standardize:** `zscore, rolling_zscore, rolling_robust, rolling_minmax, EWMA, normal_scores, quantile_binning, log_zscore, yeo_johnson, boxcox, rank_gaussianize, volatility_scaling, …`
- **Neutralize:** ridge / lasso / elastic-net / Huber / RANSAC / Theil-Sen / Bayesian-Ridge / PCA / FastICA / KernelRidge regression of factor on industry+style dummies (residual = neutralized factor).

Most variants are sklearn one-liners with Polars wrappers.

### 2.4 Factor return attribution (PureExposures)

Cross-sectional regression of next-period asset returns on a panel of factor exposures (target factor + nuisance factors like `momentum_12_1, vol_60, beta_252`). Returns "pure" target-factor return controlling for the others. Standard Barra-style decomposition.

---

## 3. Comparison table — AlphaPurify vs. our two engines

Engine A = `strategy_lab/` Polymarket UpDown. Engine B = VPS Hyperliquid perps (V52 champion).

| Feature | AlphaPurify | Engine A (Polymarket) | Engine B (Hyperliquid) | Worth stealing? |
|---|---|---|---|---|
| **Domain** | Cross-sectional equities (panel: stocks × dates) | Single-asset binary CTF (5m/15m up-down) | Single-asset perp futures (BTC/ETH/SOL) | — |
| **Backtest unit** | Rebalance period × quantile bucket | Per-market simulation `simulate_market(...)` | Per-bar mark-price replay | — |
| **Signal type** | Continuous factor, ranked cross-sectionally | Continuous (`sig_ret5m`, `smart_minus_retail`); quantile-thresholded by absolute value | Time-series momentum / regime | — |
| **Fill model** | None — assumes execution at price_col | `book_walk.py` orderbook walking; maker hybrid (limit at bid+1¢, 30s wait, fallback taker) | Mark price + funding accrual | A&B: keep ours. AP has nothing |
| **Hedge logic** | None | Hedge-hold rev_bp=5 (always taker on hedge) | N/A (perps directional) | A: keep ours |
| **Cost model** | None (turnover tracked, not debited) | Per-trade fees baked into book-walk fills | Funding accrued each interval, exchange fees per fill | A&B: ours stronger |
| **IC analysis** | Spearman rank corr per date, multi-horizon parallel | Pearson r `sig_ret5m vs fwd_outcome` (one number) | Not formalized as IC | **Engine A YES** — formalize current Pearson into Rank-IC time series |
| **Quantile backtest** | Native: 5 bins, long/short top-bottom | We use absolute quantile thresholds (q10, q20) on the signal itself, no rebalance | Not applicable | **No** — our quantile use case is different |
| **Validation** | Single-pass IC stats. No walk-forward, no permutation | Chronological 80/20 forward-walk (`polymarket_forward_walk_v2.py`); bootstrap CI 2000×n | Holdout split | **A&B keep ours**; AP weaker here |
| **Cross-asset / multi-symbol** | Native (panel structure) | E6: BTC ret as confirmation filter on ETH/SOL 5m | V52 single-asset; no cross-coin | Engine B: rebalance pattern would apply IF we built cross-coin alpha. Not on roadmap. |
| **Speed pattern** | Polars + Arrow IPC mmap + joblib `Parallel` across periods | pandas `iterrows()` per row, no parallelism | Vectorized numpy, single-threaded | **YES (Engine A)** — Arrow-mmap + joblib Parallel for `polymarket_signal_grid_v2.py`. Per-market sims are embarrassingly parallel, current loop is the bottleneck |
| **Reporting** | Plotly interactive sheets (long, short, long-short, IC) | Markdown tables + HTML dashboards (`*_dashboard.py`) | PDF + html | Equivalent. Don't switch |
| **Stats reported** | Ann Return/Sharpe/Sortino/Calmar/MaxDD/Turnover/WinRate | Per-trade PnL, ROI, win rate, bootstrap CI | Sharpe, MaxDD, funding-adj returns | **Engine A YES** — add Sharpe/MaxDD on equity curve; we report per-trade only |
| **Winsorize/standardize** | 40+ methods | None applied to signals | None applied | **Pass** — our signals are bounded & the domain doesn't have outlier crises that demand fancy clipping |
| **Factor return attribution** | PureExposures (cross-sectional regression) | N/A | N/A | **Pass** — single-asset, nothing to attribute |
| **Storage** | Parquet + DuckDB | Postgres + extracted CSV | Postgres + per-run pickles | **Pass** — Storedata is fine |
| **Position sizing** | Equal-weight quantile bucket | $1/slot fixed | Fixed contract size | None to steal |

---

## 4. Ranked theft list

### Tier 1 — High value, low effort (do these)

**1. [HIGH | ½ day] Formalize sig_ret5m as Rank-IC time series — Engine A.**
Today we report a single Pearson r ≈ +0.123 for `sig_ret5m` vs forward outcome. AlphaPurify's pattern: group by trade date, compute Spearman within each cross-section, output a daily IC series → mean IC, IC IR (mean/std), IC autocorr.
For Polymarket: "cross-section" = the set of markets with overlapping resolution windows. Daily IC series gives us:
  - **IC drift detection** — first concrete trigger to retire a signal
  - **IC IR** as a single number to compare alt-signals (we currently rank by ROI lift, which is execution-conflated)
  - **IC autocorr** — how persistent is the signal? Informs rebalance/refit cadence
Implementation: ~80 LOC wrapper around existing `*_features_v3.csv`. One-liner: `pl.corr(factor, outcome, method="spearman")` per `resolution_date_bucket`.

**2. [HIGH | 1 day] Arrow-mmap + joblib `Parallel` for per-market sims — Engine A.**
`polymarket_signal_grid_v2.py` iterates per-market in a single thread. With ~5,742 markets × multiple parameter cells the grid sweeps take 10+ minutes. AlphaPurify's pattern (FactorAnalyzer.py L1038-1080):
```python
with tempfile.TemporaryDirectory() as tmp_dir:
    base_df_path = os.path.join(tmp_dir, "base.arrow")
    with pa.OSFile(base_df_path, "wb") as sink:
        writer = pa.RecordBatchFileWriter(sink, arrow_table.schema)
        writer.write_table(arrow_table)
    # workers mmap the file — zero-copy shared memory
    Parallel(n_jobs=mp.cpu_count()-1)(delayed(_worker)(...) for ... in tasks)
```
Workers `pa.memory_map()` instead of inheriting via fork or pickling. **Expected: 8-10x speedup** on grid sweeps, alt-signal hunts, robustness checks. Modest port — `book_walk.py` already pure-numpy so it's pickle-safe. Read-only data, embarrassingly parallel — clean fit.

**3. [MEDIUM | 2 hours] Add Sharpe/MaxDD on equity curve to Engine A reports.**
Today we report per-trade PnL, ROI, win rate, bootstrap CI. We don't compute the equity curve and its drawdown. `polymarket_signal_grid_v2.py` outputs per-trade pnls — sort by entry timestamp, cumsum, then AlphaPurify's stats block (FactorAnalyzer.py L621-650) is ~20 lines:
```python
running_max = np.maximum.accumulate(cum_nv)
drawdown = cum_nv / running_max - 1
max_dd = float(np.nanmin(drawdown))
sharpe = excess_ret / vol  # already annualized
sortino = excess_ret / downside_vol
```
Useful for **drawdown-aware sizing** in the TV pilot — we can answer "what's the worst rolling 7-day drawdown on the holdout backtest?" instead of just bootstrap CI on mean ROI. Adds nothing to alpha but adds a real risk number for sizing decisions.

### Tier 2 — Medium value, medium effort (consider)

**4. [MEDIUM | 1 day] Cross-coin Rank-IC scaffolding — Engine B (deferred).**
If we ever build a cross-coin alpha (rank top-N HL perps by some factor, long-short the legs), AlphaPurify's quantile rebalance loop is the right starting skeleton. Today V52 is single-asset; this is a **bookmark, not a port**. Cost: irrelevant until we decide cross-coin perps is on the roadmap.

**5. [LOW | 2 hours] Spearman vs Pearson for our continuous signals.**
We use Pearson r for `sig_ret5m vs forward outcome`. The signal is heavy-tailed (5-min crypto returns); rank correlation is more robust. Cheap swap, single line. May change reported r from +0.123 to something tighter or looser — informative either way.

### Tier 3 — Pass (covered or irrelevant)

**6. [SKIP] 40+ winsorize/standardize variants.** Our continuous signals (`sig_ret5m`, `smart_minus_retail`) are domain-bounded (5-min crypto returns, market-microstructure-derived). We've already validated `q10`/`q20` quantile thresholds; further preprocessing variants risk overfit on small samples (5,742 markets total). Skip the menu, don't browse.

**7. [SKIP] PureExposures factor return attribution.** Single-asset directional bets — there are no nuisance factors to regress out. Conceptually backwards for our domain.

**8. [SKIP] Plotly sheets.** We have working HTML dashboards (`*_dashboard.py`). Switching costs > marginal interactivity gain.

**9. [SKIP] DuckDB + Parquet storage.** Storedata Postgres is the source of truth; CSVs are extraction artifacts. Adding a DuckDB layer adds ops surface for no win.

**10. [SKIP] Long-short rebalance backtester architecture.** Designed for monthly/weekly equity portfolios. Our trades are one-shot binary CTF resolutions over 5/15 minutes. Architecture mismatch.

---

## 5. What NOT to steal — explicit rejection list

Avoiding revisits in future sessions:

- **AlphaPurifier neutralization (ridge/lasso/PCA on factor)** — No industry/style factors in our universe; factor neutralization is a no-op for single-asset crypto.
- **Multi-frequency rebalance config** — We don't rebalance; we open one trade per market and exit on hedge-hold rev_bp.
- **Industry-grouped IC** — Crypto has no Barra-style industry buckets. BTC/ETH/SOL is already the "groups".
- **`return_horizons` array sweep** — Our outcome horizon is fixed by the market resolution time. Not a free parameter.
- **`pl.corr` industry-grouped attribution** — Same: no groups.
- **Database module** — Reinventing what we have.

---

## 6. Domain-fit score

| Engine | AlphaPurify domain-fit | Why |
|---|---:|---|
| **Engine A (Polymarket UpDown)** | **3/10** | Architecture mismatch (panel-rebalance vs per-trade event). 2-3 tooling fragments transfer (IC, Sharpe, parallel pattern). Zero alpha transfer — different asset class entirely. |
| **Engine B (Hyperliquid perps)** | **2/10** | Even worse fit — V52 is single-asset momentum, not cross-sectional. Would only matter if we expand to cross-coin alpha (not on roadmap). Tooling fragments same as Engine A but harder to retrofit into existing V52 pipeline. |

**Net verdict:** worth ½ day to port Tier 1 items #1 and #3 to Engine A. Item #2 (Arrow-mmap parallel) is higher impact and worth the full day. Engine B: nothing to port now.

---

## 7. Time spent

- Clone + map structure: 30 min
- Read FactorAnalyzer + Exposures + AlphaPurifier: 45 min
- Write this doc: 30 min
- **Total: ~1¾ hours.** Under the ½-day budget.

---

## 8. Concrete follow-up tickets (if user wants to act)

1. **Phase 19 / Plan A:** "Add Rank-IC time-series report to Polymarket signal grid" — formalize signal validation against drift.
2. **Phase 19 / Plan B:** "Parallelize `polymarket_signal_grid_v2.py` with Arrow-mmap + joblib" — 8-10x speedup on sweeps.
3. **Phase 19 / Plan C:** "Add equity-curve Sharpe + MaxDD to backtest stats dict" — drawdown-aware sizing for TV pilot.

These are independent, low-risk tooling adds. None touches the locked strategy matrix.

---

**End of analysis.** Source dump retained at `_scratch/alphapurify/` — delete when done.
