# Polymarket lab — full optimization & testing inventory

_All optimization / robustness / validation tools available in `strategy_lab/`. Count: **40+ distinct runners + 1 reusable eval library**. Below is the catalog by category, with API entry points, what they output, and example uses._

## Top-line answer

You can run **8 categories of tests**, with roughly **40+ distinct scripts** across the repo:

| Category | Count | Where |
|---|--:|---|
| Performance metrics (Sharpe, Sortino, Calmar, MDD, Ulcer, tail, deflated/probabilistic Sharpe, regime-conditional) | **14 functions** | `eval/metrics.py` |
| Robustness battery (bootstrap CI, permutation, walk-forward efficiency, per-year stats) | **5 core + 1 orchestrator** | `eval/robustness.py` |
| Walk-forward / time-series CV runners | **9 scripts** | `eval/`, `ga_optimizer/`, `drz/`, per-strategy |
| Genetic-algorithm parameter optimization | **17 modules** | `ga_optimizer/` + `ga_optimizer/path_b/` |
| Permutation tests (strict / outcome / direction) | **3 scripts** | `eval/`, `meta_classifier/`, `ga_optimizer/path_b/` |
| Capacity / slippage / fill-quality | **8 scripts** | `markov_filter/`, `engine_v2.py`, `book_walk.py` |
| Live-vs-shadow comparison | **4 scripts** | `ga_optimizer/path_b/`, `v4_signals/`, `overnight_2026_05_23/` |
| Lookahead audit | **3 scripts** | `meta_classifier/` |

Plus dozens of strategy-specific scorecards in `markov_filter/_*`, `overnight_2026_05_23/`, and the various `*_research_*` dirs.

## 1. Performance metrics — `strategy_lab/eval/metrics.py`

14 pure functions taking `pd.Series` of returns or equity:

| function | what it does |
|---|---|
| `sharpe_ratio(returns, periods_per_year)` | annualized Sharpe |
| `sortino_ratio(returns, periods_per_year)` | downside-only Sharpe |
| `calmar_ratio(cagr, max_dd)` | annual return / max DD |
| `max_drawdown(equity)` | trough-to-peak max DD |
| `dd_duration_bars(equity)` | longest underwater period |
| `dd_recovery_bars(equity)` | bars to recover from drawdown |
| `ulcer_index(equity)` | RMS drawdown depth |
| `ulcer_performance_index(...)` | UPI = (CAGR − rf) / Ulcer |
| `tail_ratio(returns, upper=0.95, lower=0.05)` | 95th / 5th percentile ratio |
| `probabilistic_sharpe(sr, n, sr_benchmark=0)` | López de Prado prob(SR > benchmark) |
| `deflated_sharpe(sr, n, n_trials, var_sr, skew, kurt)` | DSR adjusts for multiple-testing |
| `regime_conditional_sharpe(returns, regime)` | Sharpe per Markov regime |
| `monthly_returns(equity)` | monthly return series |

**Use**:
```python
from strategy_lab.eval.metrics import sharpe_ratio, deflated_sharpe
sr = sharpe_ratio(fills["pnl"] / 25, periods_per_year=3000)
dsr = deflated_sharpe(sr, n=len(fills), n_trials=270, ...)  # 270 gates tested
```

## 2. Robustness battery — `strategy_lab/eval/robustness.py`

| function | what it does |
|---|---|
| `RobustnessReport` (class) | dataclass containing all outputs of one robustness run |
| `per_year_stats(equity, bars_per_year)` | per-year Sharpe, max DD, return, ... |
| `block_bootstrap_ci(returns, n_iter, block_prob, ...)` | stationary block bootstrap (Politis-Romano), returns 95% CI on Sharpe/Calmar/MaxDD |
| `permutation_test(...)` | shuffle returns N times, test alpha vs null |
| `walk_forward_efficiency(...)` | train-test split ratio (sum_test / sum_train) — > 1 = robust |
| `run_robustness(...)` | one-call orchestrator returning a full `RobustnessReport` |

**Use** (single-strategy):
```python
from strategy_lab.eval.robustness import run_robustness
rep = run_robustness(equity=eq_series, returns=pnl/25, bars_per_year=3000,
                     n_bootstrap=2000, n_permutation=2000)
print(rep)   # bootstrap CIs, p-value, wf retention, per-year breakdown
```

## 3. Walk-forward / CV runners

| script | what it does |
|---|---|
| `eval/robustness.py::walk_forward_efficiency` | 70/30 chronological split + test/train ratio |
| `ga_optimizer/walk_forward.py::make_walk_forward_folds` | sliding-window WF folds with configurable window/step |
| `ga_optimizer/walk_forward.py::evaluate_individual_cv` | run a GA candidate across all WF folds |
| `drz/walk_forward.py` | full Track A + Track B WF runner with bootstrap p-values + rule-to-mask DSL |
| `markov_filter/robustness_gated_sleeves.py::walkforward_5050` | 50/50 split — train sum, test sum, wf_ret |
| `avell_hayashi_2026_05_26/t5_walkforward.py` | Avell-Hayashi term-structure WF |
| `cross_exchange_leadlag_2026_05_26/t8_walkforward.py` | lead-lag CV |
| `cross_exchange_leadlag_2026_05_26/t8b_walkforward_basis.py` | basis-spread WF |
| `hl_research_2026_05_26/v52_v24_audit/_b5_walkforward.py` | HL perp WF |
| `overnight_2026_05_23/extra_validation_trimmed.py` | 5-fold rolling time-series CV |

## 4. Genetic-algorithm parameter optimization — `ga_optimizer/`

Two paths:

### Path A — main GA loop
| module | function |
|---|---|
| `ga_loop_v2.py` | evolutionary loop (selection, crossover, mutation, elitism) |
| `fitness.py` | fitness function (default = Sharpe-on-walkforward) |
| `genome.py` | hyperparameter encoding |
| `operators.py` | crossover + mutation operators |
| `seeds.py` | seed individuals from a prior best-config CSV |
| `runner.py` / `runner_v2.py` | top-level CLI |
| `multi_niche_runner.py` | niching for multi-modal landscape |
| `walk_forward.py` | WF folds used in fitness evaluation |

### Path B — sleeve-level GA + permutation gate
| module | function |
|---|---|
| `path_b/runner.py` | main path-B runner |
| `path_b/cells.py` | (asset, tf) cell definitions |
| `path_b/full_window_analysis.py` | full-window scoring |
| `path_b/ga_filter.py` | GA-discovered gate filters |
| `path_b/momo_ga_runner.py` | momo-specific GA |
| `path_b/permutation_gate.py` | permutation test as a fitness gate |
| `path_b/robust_cells.py` / `robust_cells_clean.py` | robustness-filtered cells |
| `path_b/sleeve_level_analysis.py` | per-sleeve breakdown |
| `path_b/strict_oos_test.py` | strict OOS validation |
| `path_b/validate_tier_a_realfill.py` | real-fill validation of top candidates |
| `path_b/live_vs_shadow.py` | compare GA-best to live shadow PnL |
| `path_b/diagnose_mintsell.py` | mint-and-sell strategy diagnosis |

**Use**: `py strategy_lab/ga_optimizer/path_b/runner.py` (config in the source).

## 5. Permutation tests

| script | what it does |
|---|---|
| `eval/robustness.py::permutation_test` | shuffle returns, P(sum ≥ observed) |
| `meta_classifier/permutation_strict.py` | strict shuffle-by-direction permutation |
| `ga_optimizer/path_b/permutation_gate.py` | permutation as a GA fitness filter |
| `markov_filter/robustness_gated_sleeves.py::permutation_outcome` | 2 nulls in one: binomial-vs-vwap + Monte Carlo with random outcomes |

## 6. Capacity / slippage / fill-quality

| script | what it does |
|---|---|
| `markov_filter/capacity_sweep_gated_sleeves.py` | sweep notional from $25 → $10 000 at fixed sleeves, report sum/slippage/underfill % |
| `markov_filter/maker_vs_taker_gated_sleeves.py` | maker placement (best_bid, +1 tick, mid, -1 tick) vs taker on each fire |
| `markov_filter/queue_aware_maker_gated_sleeves.py` | queue-aware fill model + hybrid maker→taker fallback (joins trades parquet) |
| `markov_filter/prewindow_hybrid_25usd.py` | $25 prewindow hybrid: maker → taker fallback at slot_start-60s |
| `book_walk.py::book_walk_fill` | L25 ask ladder walk for $-budget fills |
| `engine_v2.py::LegacyConfig / LiveMimicConfig` | 2%-on-profit (prod) vs 0.07·p·(1-p) (hypothetical) fee + 85ms latency |
| `markov_filter/_aggregate_capacity.py` | aggregate capacity report builder |
| `markov_filter/_optimal_three_lenses.py` | three picks per sleeve: max-sum / practical / micro-25% depth |

## 7. Live-vs-shadow comparison

| script | what it does |
|---|---|
| `overnight_2026_05_23/vps3_verify_shadow_sleeves/04_local_live_vs_backtest.py` | matches `trading_events_30d.parquet` shadow fires to backtest expectations + computes FADE direction sanity |
| `ga_optimizer/path_b/live_vs_shadow.py` | GA-best vs live shadow log comparison |
| `v4_signals/backtest_vs_shadow_audit.py` | shadow-audit join of v4 signals |
| `markov_filter/post_f7_real_compare_v2.py` | post-F7 momo real-vs-backtest |

## 8. Lookahead audit

| script | what it does |
|---|---|
| `meta_classifier/phase9_lookahead_test.py` | basic lookahead detector |
| `meta_classifier/phase9_lookahead_realfills.py` | lookahead test on real-fill panel |
| `meta_classifier/phase9_lookahead_realfills_multi.py` | multi-asset variant |
| `discovery_2026_05_16/lookahead_audit.py` | audit of fire-time data leakage |

## 9. Per-strategy reusable scorecards (already-built)

These don't need to be re-implemented — just point them at a new panel + run.

| script | input | output |
|---|---|---|
| `markov_filter/robustness_gated_sleeves.py` | gated `fills.csv` | per-sleeve scorecard (n, WR, $/tr, sortino_pt, max_dd, bootstrap CI, walk-forward 50/50, binom p, MC p) |
| `markov_filter/capacity_sweep_gated_sleeves.py` | gated fills + L25 books | notional sweep $25→$10k per sleeve |
| `markov_filter/maker_vs_taker_gated_sleeves.py` | gated fills + L25 books | maker vs taker per placement |
| `markov_filter/queue_aware_maker_gated_sleeves.py` | + trades parquet | queue-aware fills |
| `markov_filter/prewindow_hybrid_25usd.py` | + slot timing | prewindow hybrid maker→taker |
| `overnight_2026_05_23/dedup_backtest_top_configs.py` | master panel | top-config robustness scorecard with dedup |
| `overnight_2026_05_23/per_sleeve_per_asset_tf.py` | 5m + 15m panels | 18-cell (asset × tf × rule) scorecard |
| `overnight_2026_05_23/kelly_tier_sweep.py` | gated fills | 13 Kelly sizing schedules, per-tier behaviour |
| `overnight_2026_05_23/markov_conditional_strategies.py` | master panel | 16 Markov-conditional variants |
| `overnight_2026_05_23/down_only_and_late_zoom.py` | master panel | direction-asymmetric + late-offset sweeps |
| `overnight_2026_05_23/extra_validation_trimmed.py` | master panel | 5-fold time-CV + stress tests (drop top 5% PnL) |
| `markov_filter/_final_scorecard.py` | gated fills | the canonical per-sleeve final scorecard |
| `markov_filter/_optimal_three_lenses.py` | capacity sweep CSV | max-sum / practical / micro-25% optima |

## 10. Backtest engines

| engine | use |
|---|---|
| `engine.py` | legacy, kept for reference |
| `engine_v2.py` | **canonical** — LiveMimicConfig + LegacyConfig + book_walk_fill + min_book_events + 85ms latency |

## 11. Plateau / parameter stability — `eval/plateau.py`

| function | what it does |
|---|---|
| `parameter_plateau(fitness_fn, params, search_grid)` | tests if a chosen param is on a flat/stable region (anti-overfit) |

Plateau ≥ 0.7 = robust to nearby parameter values; < 0.5 = curve-fit.

## How many can we run in one go?

If you give me a fresh fire-panel parquet, I can run **every test in this catalog** as a single chained pipeline:

```text
panel → robustness_gated_sleeves      → per-sleeve metrics
      → capacity_sweep_gated_sleeves  → notional knee per sleeve
      → maker_vs_taker_gated_sleeves  → fill-model comparison
      → kelly_tier_sweep              → sizing curves
      → per_sleeve_per_asset_tf       → 5m + 15m + per-cell
      → markov_conditional_strategies → 16 regime variants
      → down_only_and_late_zoom       → direction/offset asymmetry
      → extra_validation_trimmed      → 5-fold CV + stress tests
      → run_robustness                → bootstrap + permutation + WF + per-year
      → parameter_plateau             → robustness around best params
```

That's a complete **robustness battery for a new strategy in one command-chain** (≈ 5-15 min compute on a 21-d panel).

For new gate / parameter discovery use the **GA optimizer** (`ga_optimizer/path_b/runner.py`). Adds 30-60 min for a ~500-individual × 30-generation evolution.

## Recommended pipeline for a NEW strategy candidate

1. **Backtest panel** (use `engine_v2.LegacyConfig`)
2. **`robustness_gated_sleeves.py`** — Sharpe, Sortino, max DD, walk-forward, bootstrap CI, binom + MC p-value
3. **`extra_validation_trimmed.py`** — 5-fold rolling CV + drop-top-5% stress test
4. **`capacity_sweep_gated_sleeves.py`** — find the notional knee
5. **`maker_vs_taker_gated_sleeves.py`** if a maker variant exists
6. **`kelly_tier_sweep.py`** if `fair_edge_bp` (or equivalent conviction signal) is available
7. **`deflated_sharpe`** with `n_trials = #gates tested` to correct for multi-comparison
8. **`parameter_plateau`** on the chosen gate parameters
9. **`permutation_strict.py`** as a final null-hypothesis sanity check
10. **`live_vs_shadow.py`** after 7+ days of shadow deploy

A strategy that passes 1-9 with `wf_ret ≥ 0.7`, `bootstrap CI lo > 0`, `binom_p < 0.01`, and `deflated_sharpe > 0` is deploy-ready in my opinion.

## Files

- This inventory: `strategy_lab/reports/OPTIMIZATION_TEST_INVENTORY_2026_05_26.md`
- Eval library: `strategy_lab/eval/`
- GA optimizer: `strategy_lab/ga_optimizer/`
- Per-strategy scorecards: `strategy_lab/markov_filter/`, `strategy_lab/overnight_2026_05_23/`
