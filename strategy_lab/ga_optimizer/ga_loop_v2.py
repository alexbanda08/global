"""
GA loop v2 with:
  - Walk-forward cross-validation (3 folds) for robust fitness
  - Diversity tracking (population gene variance per gen)
  - Adaptive mutation rate (increases if diversity drops)
  - Held-out test on final winners
  - Joblib parallel fitness eval (8 workers default)
  - Checkpointing every N gens (resumable)
"""
from __future__ import annotations
import json, time
from pathlib import Path
from dataclasses import dataclass, field, asdict
import numpy as np
import pandas as pd

from .genome import Gene, random_individual, mutate_individual
from .operators import breed, elitism, spontaneous, tournament_select
from .fitness import evaluate_momo, fitness as compute_fitness
from .walk_forward import make_walk_forward_folds, evaluate_individual_cv

try:
    from joblib import Parallel, delayed
    _HAVE_JOBLIB = True
except ImportError:
    _HAVE_JOBLIB = False


@dataclass
class GAConfigV2:
    sleeve_type: str
    asset: str
    population_size: int = 60
    n_generations: int = 30
    elite_fraction: float = 0.10
    spontaneous_fraction: float = 0.10
    per_gene_mut_prob: float = 0.30
    per_gene_mut_prob_max: float = 0.50  # bumped if diversity drops
    tournament_k: int = 3
    n_folds: int = 3
    train_fraction_per_fold: float = 0.70
    held_out_split: float = 0.15
    checkpoint_frequency: int = 5
    seed: int = 42
    n_parallel_workers: int = 8
    diversity_threshold: float = 0.15  # below this, bump mutation rate


def population_diversity(population: list[dict], genome: list[Gene]) -> float:
    """Mean per-gene normalized standard deviation across population."""
    diversities = []
    for g in genome:
        if g.kind == "float":
            vals = np.array([ind[g.name] for ind in population], dtype=float)
            denom = g.max - g.min
            d = float(np.std(vals) / max(denom, 1e-9))
            diversities.append(d)
        elif g.kind == "int":
            vals = np.array([ind[g.name] for ind in population], dtype=float)
            denom = g.max - g.min
            d = float(np.std(vals) / max(denom, 1e-9))
            diversities.append(d)
        elif g.kind == "cat":
            vals = [ind[g.name] for ind in population]
            unique = len(set(vals))
            diversities.append(unique / max(len(g.choices), 1))
        elif g.kind == "mask":
            vals = np.array([ind[g.name] for ind in population], dtype=int)
            # bit-wise entropy proxy
            bit_means = []
            for b in range(g.n_bits):
                bit_means.append(((vals >> b) & 1).mean())
            # entropy maximized at 0.5
            bit_means = np.array(bit_means)
            ent = float((4 * bit_means * (1 - bit_means)).mean())  # normalized 0-1
            diversities.append(ent)
    return float(np.mean(diversities)) if diversities else 0.0


def _eval_one(ind, sleeve_type, asset, res_df, books, klines_end_us, klines_prices, folds):
    return evaluate_individual_cv(ind, sleeve_type, asset, res_df, books,
                                    klines_end_us, klines_prices, folds)


def run_ga_v2(config: GAConfigV2, genome: list[Gene], seeds: list[dict],
              res_df: pd.DataFrame, books: dict,
              klines_end_us: np.ndarray, klines_prices: np.ndarray,
              run_dir: Path):
    rng = np.random.default_rng(config.seed)
    run_dir.mkdir(parents=True, exist_ok=True)

    # Time windows: hold out last X% as truly unseen test
    ts_min = int(res_df.slot_start_us.min())
    ts_max = int(res_df.slot_start_us.max())
    held_start = ts_min + int((ts_max - ts_min) * (1 - config.held_out_split))
    cv_window = (ts_min, held_start)
    held_window = (held_start, ts_max)

    folds = make_walk_forward_folds(cv_window[0], cv_window[1],
                                     n_folds=config.n_folds,
                                     train_fraction=config.train_fraction_per_fold)
    def time_str(us):
        return pd.to_datetime(us, unit="us", utc=True).strftime("%Y-%m-%d %H:%M")
    print(f"[GAv2] CV window: {time_str(cv_window[0])} → {time_str(cv_window[1])}")
    print(f"[GAv2] held out: {time_str(held_window[0])} → {time_str(held_window[1])}  (held last {config.held_out_split*100:.0f}%)")
    for f in folds:
        print(f"  fold {f['k']}: train {time_str(f['train'][0])} → {time_str(f['train'][1])}  | val {time_str(f['val'][0])} → {time_str(f['val'][1])}")

    # Seed population
    population = list(seeds)
    while len(population) < config.population_size:
        population.append(random_individual(genome, rng))
    population = population[: config.population_size]

    n_elite = max(1, int(config.population_size * config.elite_fraction))
    n_spont = max(1, int(config.population_size * config.spontaneous_fraction))
    n_offspring = config.population_size - n_elite - n_spont
    current_mut_prob = config.per_gene_mut_prob

    history = []
    best_overall = {"cv_fitness": -1e9}

    for gen in range(config.n_generations):
        t0 = time.time()

        # Parallel CV fitness eval
        if _HAVE_JOBLIB and config.n_parallel_workers > 1:
            cv_results = Parallel(n_jobs=config.n_parallel_workers, prefer="threads")(
                delayed(_eval_one)(ind, config.sleeve_type, config.asset, res_df, books,
                                     klines_end_us, klines_prices, folds)
                for ind in population
            )
        else:
            cv_results = [_eval_one(ind, config.sleeve_type, config.asset, res_df, books,
                                     klines_end_us, klines_prices, folds)
                          for ind in population]

        cv_fits = [r["cv_fitness"] for r in cv_results]
        # Population diversity
        diversity = population_diversity(population, genome)
        # Adaptive mutation
        if diversity < config.diversity_threshold:
            current_mut_prob = min(config.per_gene_mut_prob_max, current_mut_prob + 0.05)
        else:
            current_mut_prob = max(config.per_gene_mut_prob,
                                    current_mut_prob - 0.02)

        # Best
        best_idx = int(np.argmax(cv_fits))
        best_r = cv_results[best_idx]
        # Track overall best
        if best_r["cv_fitness"] > best_overall["cv_fitness"]:
            best_overall = {"individual": dict(population[best_idx]),
                              "cv_fitness": best_r["cv_fitness"],
                              "gen": gen,
                              "details": best_r}
        elapsed = time.time() - t0
        gen_summary = {
            "gen": gen, "best_cv_fit": best_r["cv_fitness"],
            "mean_val_pnl": float(np.mean(best_r["val_pnls"])),
            "mean_val_n": float(np.mean(best_r["val_ns"])),
            "mean_val_wr": float(np.mean(best_r["val_wrs"])),
            "fold_val_pnls": best_r["val_pnls"],
            "diversity": diversity, "mut_prob": current_mut_prob,
            "elapsed_s": elapsed,
        }
        history.append(gen_summary)

        print(f"[GAv2] gen {gen:3d}  cv_fit={best_r['cv_fitness']:+.4f}  "
              f"val_pnls={[f'{p:+.0f}' for p in best_r['val_pnls']]}  "
              f"val_ns={best_r['val_ns']}  "
              f"div={diversity:.3f}  mut={current_mut_prob:.2f}  ({elapsed:.0f}s)")

        # Checkpoint
        if gen % config.checkpoint_frequency == 0 or gen == config.n_generations - 1:
            with open(run_dir / f"gen_{gen:03d}.json", "w") as f:
                json.dump({
                    "gen": gen, "diversity": diversity,
                    "mut_prob": current_mut_prob,
                    "population": population,
                    "cv_fitnesses": cv_fits,
                    "best": best_overall,
                }, f, indent=2, default=str)

        # Breed
        elite = elitism(population, cv_fits, n_elite)
        kids = breed(population, cv_fits, genome, rng, n_offspring,
                     per_gene_mut_prob=current_mut_prob,
                     tournament_k=config.tournament_k)
        new_random = spontaneous(genome, rng, n_spont)
        population = elite + kids + new_random

    # ---- Final: re-eval top-5 on held-out + report ----
    print(f"\n[GAv2] FINAL: re-evaluating top-5 on held-out window...")
    # Re-eval current population to find top-5
    final_cv = [_eval_one(ind, config.sleeve_type, config.asset, res_df, books,
                            klines_end_us, klines_prices, folds)
                 for ind in population]
    top5_idx = sorted(range(len(final_cv)), key=lambda i: -final_cv[i]["cv_fitness"])[:5]

    final_report = []
    for rank, i in enumerate(top5_idx):
        ind = population[i]
        cv = final_cv[i]
        # Held-out eval
        held_trades = evaluate_momo(ind, config.sleeve_type, config.asset, res_df, books,
                                      klines_end_us, klines_prices, window_us=held_window)
        held = compute_fitness(held_trades, ind)
        print(f"  rank{rank+1}: cv_fit={cv['cv_fitness']:+.4f}  "
              f"held: n={held['n']:3d} win={held['win_rate']:.3f} pnl=${held['pnl']:+.0f}  "
              f"sharpe={held['sharpe']:.2f}  individual={ind}")
        final_report.append({"rank": rank+1, "individual": ind, "cv": cv, "held_out": held})

    with open(run_dir / "final_v2.json", "w") as f:
        json.dump({
            "config": asdict(config),
            "best_overall": best_overall,
            "top5_held_out": final_report,
            "history": history,
        }, f, indent=2, default=str)

    print(f"\n[GAv2] DONE. results saved to {run_dir}")
    return final_report
