"""
Main GA evolution loop. Generation-based with elitism + spontaneous diversity.
Checkpoints every N gens. Validates every M gens.
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


@dataclass
class GAConfig:
    sleeve_type: str               # momo_5m | momo_15m | mispricing_15m
    asset: str                     # BTC | ETH | SOL
    population_size: int = 50
    n_generations: int = 30
    elite_fraction: float = 0.10   # top 10% preserved unchanged
    spontaneous_fraction: float = 0.10  # 10% random newcomers per gen
    per_gene_mut_prob: float = 0.30
    tournament_k: int = 3
    validation_frequency: int = 5
    checkpoint_frequency: int = 5
    train_validation_split: float = 0.70   # 70% train, 20% validate, 10% held-out
    held_out_split: float = 0.10
    seed: int = 42


@dataclass
class GenerationResult:
    generation: int
    best_train_fitness: float
    best_train_pnl: float
    best_train_n: int
    best_train_win: float
    best_individual: dict
    mean_train_fitness: float
    validation_pnl: float | None = None
    validation_n: int | None = None
    validation_win: float | None = None
    elapsed_s: float = 0.0


def run_ga(config: GAConfig, genome: list[Gene], seeds: list[dict],
           res_df: pd.DataFrame, books: dict,
           klines_end_us: np.ndarray, klines_prices: np.ndarray,
           run_dir: Path) -> list[GenerationResult]:
    rng = np.random.default_rng(config.seed)
    run_dir.mkdir(parents=True, exist_ok=True)

    # Time windows: train / validate / held-out
    ts_min = int(res_df.slot_start_us.min())
    ts_max = int(res_df.slot_start_us.max())
    span = ts_max - ts_min
    train_end = ts_min + int(span * config.train_validation_split)
    val_end = ts_min + int(span * (1 - config.held_out_split))
    train_window = (ts_min, train_end)
    val_window = (train_end, val_end)
    held_window = (val_end, ts_max)

    def time_str(us):
        return pd.to_datetime(us, unit="us", utc=True).strftime("%Y-%m-%d %H:%M")
    print(f"[GA] train: {time_str(train_window[0])} → {time_str(train_window[1])}")
    print(f"[GA] valid: {time_str(val_window[0])}  → {time_str(val_window[1])}")
    print(f"[GA] held : {time_str(held_window[0])} → {time_str(held_window[1])}")

    def eval_individual(ind: dict, window: tuple[int, int]) -> dict:
        trades = evaluate_momo(ind, config.sleeve_type, config.asset, res_df, books,
                                klines_end_us, klines_prices, window_us=window)
        return compute_fitness(trades, ind)

    # ---- Seed population ----
    population = list(seeds)
    while len(population) < config.population_size:
        population.append(random_individual(genome, rng))
    population = population[: config.population_size]
    print(f"[GA] seeded {len(seeds)} known + {config.population_size - len(seeds)} random = {len(population)} individuals")

    n_elite = max(1, int(config.population_size * config.elite_fraction))
    n_spontaneous = max(1, int(config.population_size * config.spontaneous_fraction))
    n_offspring = config.population_size - n_elite - n_spontaneous

    results: list[GenerationResult] = []

    for gen in range(config.n_generations):
        t0 = time.time()
        # Evaluate
        fitnesses_train = []
        details = []
        for ind in population:
            r = eval_individual(ind, train_window)
            fitnesses_train.append(r["fitness"])
            details.append(r)

        # Best
        best_idx = int(np.argmax(fitnesses_train))
        best_d = details[best_idx]
        elapsed = time.time() - t0
        gr = GenerationResult(
            generation=gen,
            best_train_fitness=best_d["fitness"],
            best_train_pnl=best_d["pnl"],
            best_train_n=best_d["n"],
            best_train_win=best_d["win_rate"],
            best_individual=population[best_idx],
            mean_train_fitness=float(np.mean(fitnesses_train)),
            elapsed_s=elapsed,
        )

        # Validation (periodic)
        if gen % config.validation_frequency == 0:
            val_r = eval_individual(population[best_idx], val_window)
            gr.validation_pnl = val_r["pnl"]
            gr.validation_n = val_r["n"]
            gr.validation_win = val_r["win_rate"]
            print(f"  gen {gen:3d}  [VAL] n={val_r['n']:4d} win={val_r['win_rate']:.3f} pnl=${val_r['pnl']:+.0f}")

        print(f"[GA] gen {gen:3d}  best_train_fit={best_d['fitness']:.4f}  "
              f"pnl=${best_d['pnl']:+.0f}  n={best_d['n']:4d}  win={best_d['win_rate']:.3f}  "
              f"mean_fit={gr.mean_train_fitness:.4f}  ({elapsed:.0f}s)")

        # Checkpoint
        if gen % config.checkpoint_frequency == 0 or gen == config.n_generations - 1:
            ckpt = run_dir / f"gen_{gen:03d}.json"
            with open(ckpt, "w") as f:
                json.dump({
                    "config": asdict(config),
                    "generation": gen,
                    "population": population,
                    "fitnesses": fitnesses_train,
                    "best": asdict(gr),
                }, f, indent=2, default=str)

        results.append(gr)

        # Breed next generation
        elite = elitism(population, fitnesses_train, n_elite)
        kids = breed(population, fitnesses_train, genome, rng, n_offspring,
                     per_gene_mut_prob=config.per_gene_mut_prob,
                     tournament_k=config.tournament_k)
        new_random = spontaneous(genome, rng, n_spontaneous)
        population = elite + kids + new_random

    # ---- Final held-out evaluation on best ----
    print(f"\n[GA] final held-out eval on top-3 by training fitness...")
    final_results = []
    last_train_idx_sorted = sorted(range(len(population)), key=lambda i: -results[-1].best_train_fitness)
    # Use the best individual from the LAST generation's evaluation
    top_3 = [results[-1].best_individual]
    # Add 2 more diverse top individuals from population
    sorted_pop = sorted(zip(population, [eval_individual(p, train_window)["fitness"] for p in population]),
                        key=lambda x: -x[1])
    for p, _ in sorted_pop[:2]:
        if p != top_3[0]:
            top_3.append(p)
    top_3 = top_3[:3]

    for i, ind in enumerate(top_3):
        held_r = eval_individual(ind, held_window)
        train_r = eval_individual(ind, train_window)
        val_r = eval_individual(ind, val_window)
        full_r = eval_individual(ind, (ts_min, ts_max))
        print(f"  top {i+1}: held_n={held_r['n']:3d} held_pnl=${held_r['pnl']:+.0f} "
              f"held_win={held_r['win_rate']:.3f}  |  train_pnl=${train_r['pnl']:+.0f}  "
              f"valid_pnl=${val_r['pnl']:+.0f}  full_pnl=${full_r['pnl']:+.0f}")
        final_results.append({"individual": ind, "held": held_r, "train": train_r,
                              "valid": val_r, "full": full_r})

    with open(run_dir / "final.json", "w") as f:
        json.dump({"config": asdict(config), "top_3_held_out": final_results,
                   "history": [asdict(r) for r in results]},
                  f, indent=2, default=str)
    print(f"\n[GA] DONE. results saved to {run_dir}")
    return results
