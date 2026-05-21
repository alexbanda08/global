# GA-Based Sleeve Optimization Plan — Adapted from NextTrade (2026-05-19)

## Source review — NextTrade GA architecture

NextTrade ([austin-starks/NextTrade](https://github.com/austin-starks/NextTrade), 1.8k stars) is a TypeScript stock-trading platform with a genetic algorithm optimizer. Core mechanics:

### Algorithm loop (per generation)
1. **Selection**: roulette wheel by fitness — parent probability proportional to fitness.
2. **Crossover**: 50/50 split between `nPointCrossover` (multi-point exchange) and `randomCrossover` (per-gene random parent).
3. **Mutation**: per-element with `mutationProbability`. Floats sampled via Box-Mueller (Gaussian) centered on current value, clamped to `[min, max]`. Integers clamped + rounded.
4. **Replacement**: offspring + spontaneous + elitism → concat with population → sort by fitness → cull to `populationSize`.
5. **Validation**: every `validationFrequency` generations, evaluate top elites on held-out window.

### Hyperparameters (defaults)
- `populationSize`: 3-1000 (typical 50-200)
- `numGenerations`: 1-1000
- `mutationProbability`: per-gene; mutationIntensity = Box-Mueller σ
- `crossoverProbability`: 0.7
- `trainValidationRatio`: 0.8 (80% train, 20% validate)
- `eliteSpontaneousRatio`: fraction reserved for fresh random individuals
- `fitnessFunction`: percent-gain | sortino (default) | sharpe | max-drawdown
- `validationFrequency`: every N gens
- `_BATCH_SIZE`: 10 (parallel evals via worker_threads)

### Key types
```typescript
interface OptimizerVector {
  fieldName: string;     // e.g. "ret_2m_threshold_bp"
  value: number;
  isInteger: boolean;
  max: number; min: number;
  strategyIdx: number;
  values: string[];      // for categorical fields
  type: FieldEnum;       // number | select | date | text
}
```

### Why NOT use NextTrade directly
- TypeScript / MongoDB / Tradier stack — wrong tech for our Python/parquet/L25 lake.
- Stock-equity assumption: no binary-options payoff math, no L25 book-walk fill.
- No microsec-latency-aware kline asof (we identified that bug last session).
- No Polymarket-fee curve, no chainlink-resolved outcomes.

**Port the algorithm, not the code.** Build a thin Python GA on top of our existing harness.

---

## Adaptation to our momo / sleeve system

### What we're optimizing

Each sleeve = signal generator + filters + exit policy. The parameter vectors for our top sleeves:

#### Vector: `momo_5m_v1`
| Gene | Type | Range | Notes |
|---|---|---|---|
| `ret_2m_threshold_bp` | float | 0 - 100 | min ret_2m magnitude to fire |
| `direction_mode` | cat | `same`/`fade`/`auto` | follow ret_2m / invert / GA decides |
| `spread_filter` | float | 0.005 - 0.05 | max ask-bid (in clob price units) |
| `vwap_lo` | float | 0.05 - 0.50 | min entry vwap |
| `vwap_hi` | float | 0.50 - 0.95 | max entry vwap |
| `min_book_depth_usd` | float | 5 - 50 | min $ available top-of-book |
| `hour_mask` | bitmask24 | 0 - 2^24 | which UTC hours enabled |
| `dow_mask` | bitmask7 | 0 - 127 | which days enabled |
| `asset` | cat | BTC/ETH/SOL | per-asset specialization |
| `exit_policy` | cat | HOLD/HEDGE/SELL | exit type |
| `hedge_trigger_bp` | float | 0 - 100 | spot reversal → HEDGE |
| `hedge_arm_offset_s` | int | 30 - 240 | when to arm hedge after entry |
| `sigma_window_min` | int | 10 - 60 | binance sigma normalization |
| `notional_usd` | float | 5 - 100 | trade size |

#### Vector: `momo_15m_v1` (same as above, window=900s instead of 300s)

#### Vector: `mispricing_15m`
| Gene | Type | Range |
|---|---|---|
| `edge_threshold` | float | 0.02 - 0.25 |
| `obs_horizon_s` | int | 60 - 900 |
| `anchor_offset_s` | int | 30 - 600 (slot_end minus) |
| `vwap_lo` / `vwap_hi` | float | 0.10 / 0.90 |
| `fair_p_z_scale` | float | 0.5 - 5.0 (tanh sharpness) |
| `sigma_window_min` | int | 10 - 60 |
| `hour_mask` / `dow_mask` | bitmask | |
| `asset` / `exit_policy` | cat | |

Each vector has 10-15 genes. Bitmasks treated as integer with custom Gaussian-clamp mutation.

### Initial population seeding

Start from KNOWN configs to avoid wasting gens on random:
- **Seed 1**: current production momo (anchor=ws_s+120, no filters)
- **Seed 2**: best KEEP sleeve config (sol_5m_momo_SELL with its actual params)
- **Seed 3**: best FADE config (btc_5m_momo HEDGE DOWN @ 18-22 UTC, inverted)
- **Seeds 4-N**: random vectors within ranges

This makes the GA "polish" known-good rather than search from zero.

### Fitness function (multi-objective composite)

```python
def fitness(vector, train_window):
    trades = backtest(vector, train_window)   # uses lookahead-corrected harness
    n = len(trades)
    if n < 30:  return -1e9   # discard sleeves that don't trade enough

    pnl_total = trades.pnl.sum()
    daily = trades.groupby('date').pnl.sum()
    sharpe = (daily.mean() / daily.std() * sqrt(252)) if daily.std() > 0 else 0
    dd = max_drawdown(daily.cumsum())

    # Composite (tunable weights):
    fitness = (
        0.5 * sharpe                              # risk-adjusted
        + 0.3 * np.sign(pnl_total) * np.log1p(abs(pnl_total))   # log PnL
        - 0.2 * abs(dd) / max(daily.cumsum().max(), 1)          # relative DD penalty
    )

    # Trade-count gate: penalize very low n (overfit risk)
    if n < 100: fitness *= n / 100
    return fitness
```

**Critical**: every backtest call uses `asof_strict(target_us - 100_000)` (100ms latency shift) to prevent the microsec lookahead we found last session.

### Train / Validate / Test split (walk-forward)

```
Apr 24 ─────── May 6 ─── May 12 ─── May 16
 [-----TRAIN--------|--VALIDATE---|--HELD-OUT-TEST--]
       60% (14d)         25% (6d)       15% (3d)
```

- **TRAIN**: GA evolves population, fitness from this window.
- **VALIDATE**: every 5 gens, top-10 elites re-scored on this window. If validation fitness drops while train rises → overfit → halt.
- **HELD-OUT TEST**: never seen until final selection. Only the GA winner is evaluated here. If held-out fitness < 60% of training fitness → reject.

### Multi-armed search

Don't run ONE GA on a flat parameter space. Run one GA **per (asset, sleeve_type)** combo:
- `BTC_momo_5m`, `BTC_momo_15m`, `BTC_mispricing_15m`
- `ETH_momo_5m`, `ETH_momo_15m`, `ETH_mispricing_15m`
- `SOL_momo_5m`, `SOL_momo_15m`, `SOL_mispricing_15m`

9 parallel GA runs. Each finds the best vector for its niche. Combine winners into the final portfolio.

### GA hyperparameters (recommended starting point)

- `population_size`: 80
- `n_generations`: 40
- `mutation_probability`: 0.20 per individual, then 0.30 per gene given individual selected
- `mutation_sigma`: 0.15 × (max - min) per gene (Gaussian width)
- `crossover_probability`: 0.7
- `crossover_type`: uniform (per-gene 50/50 from each parent)
- `tournament_size`: 3 (selection — k-tournament more stable than roulette)
- `elite_fraction`: 0.05 (top 4 individuals survive unchanged)
- `spontaneous_fraction`: 0.10 (8 random newcomers per gen — diversity)
- `validation_frequency`: 5

---

## Architecture

```
strategy_lab/ga_optimizer/
├── __init__.py
├── genome.py              vector definition + bitmask mutation helpers
├── individual.py          single sleeve instance + cache fitness
├── population.py          population of individuals
├── operators.py           selection / crossover / mutation primitives
├── fitness.py             multi-objective fitness wrapping harness
├── backtest_adapter.py    glues genome → harness call w/ 100ms latency
├── ga_loop.py             main evolution loop with logging + checkpoint
├── seeds.py               known-good initial individuals
├── runner.py              CLI entry: orchestrate 9 parallel GA runs
└── tests/
    ├── test_operators.py
    ├── test_genome.py
    └── test_no_lookahead.py   verify every backtest call applies latency shift
```

### Dependencies
- `deap` (battle-tested Python GA framework)
- existing `strategy_lab/discovery_2026_05_16/harness.py`
- `joblib` for parallel fitness eval (8 cores)
- `pandas`, `numpy` (already loaded)

### Persistence (analogous to NextTrade's MongoDB)
- `optimization_runs/{run_id}/state_gen_{n}.parquet` — full population snapshot per generation
- `optimization_runs/{run_id}/best.json` — current best vector + fitness
- `optimization_runs/{run_id}/run_meta.yaml` — hyperparameters + git SHA + start time
- Checkpoint every 5 gens → resumable if killed

---

## Computational cost estimate

Per individual backtest (current harness speed):
- 5m sleeve: ~30s (load + walk all markets in 30-day window)
- 15m sleeve: ~15s
- L25 book load: amortized via per-run cache, ~5s init

Total per generation: 80 individuals × 30s avg = 40 min serial.

With joblib parallelism (8 cores): 5 min per gen.

40 generations × 5 min = **3.3 hours per GA run.**

9 parallel GA runs (one per asset×sleeve_type), serial: 30 hours.
With 2 GA runs in parallel (16 cores): 15 hours.

→ **One-time setup cost: overnight (~12-15 hours).** Then refresh monthly with new data.

---

## Risk controls (anti-overfit)

1. **Held-out window**: last 15% of data NEVER touched during GA. Final winner must pass `held_out_sharpe > 0` AND `held_out_pnl > 0` AND `held_out_n >= 30`.
2. **Multi-objective Pareto front**: report top-10 individuals not just #1. Manual review picks the one with most-diverse parameters (avoid pathological single point).
3. **Permutation test**: shuffle labels on final winner, run 1000 random vectors → winner fitness must exceed 95th percentile of null.
4. **Sleeve stability over time**: refit GA monthly. If winning vector drifts >30% in any gene between months, that gene is unstable → drop or constrain tighter.
5. **Trade-count floor**: any sleeve with <30 trades/month gets fitness=−∞. Avoids "perfect 100% hit rate on n=3" cells.
6. **Sign-flip ablation**: for each gene, ablate by ±50%. If fitness drops <10%, gene was noise → fix at default.

---

## Connection to last-session findings

The manual fade-scan from last session found 27 cuts with combined +$7,922/month edge. Those are GREAT seeds for the GA:
- BTC_momo DOWN @ 18-22 UTC (Bonferroni-strict) → seed individual with `direction_mode=fade`, `hour_mask=0b...11111000` (18-22), strategy initialized to invert.
- ETH_momo DOWN @ 12-17 UTC → seed individual with similar mask, signal=DOWN→inverted.
- SOL_momo SELL (KEEP candidate) → seed at current config, GA polishes thresholds.

The GA should EXCEED the manual fade-scan because:
- Continuous threshold search (not coarse buckets)
- Per-individual hour mask (any 24-bit pattern, not just 4 buckets)
- Joint optimization across all genes simultaneously
- Multi-asset specialization in parallel

**Expected uplift**: manual fade-scan delivered +$10,220/month. GA should reach +$15-25k/month on the same 30-day window, with stronger held-out behavior.

---

## Phased implementation

### Phase 1 — Build infrastructure (2-3 days)
- Implement `genome.py`, `operators.py`, `fitness.py`
- Wrap harness for batch evaluation
- Write `test_no_lookahead.py` to verify 100ms shift applied everywhere
- Validate with toy 5-gene, 20-individual, 5-generation test → produces a winner

### Phase 2 — Single-sleeve validation (1 day)
- Run GA on ONE niche (e.g., BTC momo 5m) for 40 gens
- Confirm convergence (training fitness rises, validation fitness rises ≤30% behind)
- Confirm held-out validation passes
- Sanity: GA winner ≥ best manual fade-scan cut for same niche

### Phase 3 — Full 9-niche sweep (1-2 days compute, parallelized)
- Run all 9 (asset × sleeve_type) GAs
- Build Pareto front per niche
- Cross-validate winners on full universe

### Phase 4 — Deployment (per existing DEPLOYMENT_FINAL.md plan)
- Top vectors per niche become Phase 1 paper-test candidates
- Replace current KEEP + FADE rules with GA-optimized versions
- A/B test old vs new for 2 weeks

---

## Why GA over the alternatives

| Approach | Search efficiency | Handles discrete params | Multi-objective | Our use case |
|---|:---:|:---:|:---:|:---:|
| Grid search | Poor (curse of dim) | Yes | No | Used for fade-scan; coarse only |
| Random search | OK | Yes | No | Used as null baseline |
| Bayesian opt (Optuna) | Best | Limited | Limited | Single-objective only |
| **Genetic algorithm** | Good | Yes | **Yes** | **Picked** |
| RL (PPO/SAC) | Best long-term | Yes | Yes | Overkill, slow to train |

GA is the right balance: handles our mixed continuous+discrete+bitmask gene space, supports multi-objective Pareto reporting, parallelizes cleanly, and is interpretable (you can inspect the winning vector directly).

---

## Open decisions (need user input)

1. **Allow GA to discover new directions or constrain to validated patterns?**
   - Tight: only allow `direction_mode=fade` if seed sleeve is in FADE list. Faster convergence, less risk.
   - Loose: GA picks `direction_mode` freely. More exploration, slower, higher overfit risk.

2. **Compute budget**:
   - Overnight 15h run? OK to schedule.
   - Or shorter 3h single-niche run first to validate end-to-end?

3. **Fitness weights**:
   - Sharpe-heavy (current default 0.5): risk-averse, conservative.
   - PnL-heavy: aggressive growth, accepts higher DD.
   - Custom (e.g., 0.7 sharpe + 0.3 hit-rate-above-65%): you choose.

4. **Re-fit cadence**:
   - Monthly (recommended).
   - Or trigger-based: when held-out fitness degrades >25%.

---

## Files

- `strategy_lab/discovery_2026_05_16/GA_OPTIMIZER_PLAN.md` — this file
- `strategy_lab/discovery_2026_05_16/DEPLOYMENT_FINAL.md` — current keep/fade/kill rules (becomes seed input)
- `strategy_lab/discovery_2026_05_16/LOOKAHEAD_CORRECTION.md` — why all backtests need 100ms latency shift

---

## Next step

Pending your decisions on the 4 open items above, I can:
- Start Phase 1 (build infrastructure) — 2-3 days
- Or run a toy 1-niche test first to prove the harness wiring before committing to overnight runs.

Which?
