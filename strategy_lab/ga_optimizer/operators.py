"""
GA operators: selection, crossover (uniform / 1-point), elitism, spontaneous gen.
NextTrade-style: roulette-wheel selection + hybrid crossover + Gaussian mutation
with elite + spontaneous diversity.
"""
from __future__ import annotations
import numpy as np
from .genome import Gene, random_individual, mutate_individual, crossover_uniform, crossover_npoint


def tournament_select(fitnesses: list[float], k: int, rng: np.random.Generator) -> int:
    """k-tournament: pick k random, return the best."""
    candidates = rng.integers(0, len(fitnesses), size=k)
    best = candidates[0]
    for c in candidates[1:]:
        if fitnesses[c] > fitnesses[best]:
            best = c
    return int(best)


def roulette_select(fitnesses: list[float], rng: np.random.Generator) -> int:
    """Fitness-proportional. Shifts to positive first."""
    fits = np.array(fitnesses, dtype=float)
    fits = fits - fits.min() + 1e-9   # shift positive
    p = fits / fits.sum()
    return int(rng.choice(len(fits), p=p))


def breed(population: list[dict], fitnesses: list[float], genome: list[Gene],
          rng: np.random.Generator, n_offspring: int,
          per_gene_mut_prob: float = 0.30,
          tournament_k: int = 3) -> list[dict]:
    """Tournament-select parents, crossover (uniform/npoint 50/50), mutate."""
    children = []
    for _ in range(n_offspring):
        a = tournament_select(fitnesses, tournament_k, rng)
        b = tournament_select(fitnesses, tournament_k, rng)
        while b == a and len(population) > 1:
            b = tournament_select(fitnesses, tournament_k, rng)
        if rng.random() < 0.5:
            child = crossover_uniform(population[a], population[b], rng)
        else:
            child = crossover_npoint(population[a], population[b], rng)
        child = mutate_individual(child, genome, rng, per_gene_prob=per_gene_mut_prob)
        children.append(child)
    return children


def elitism(population: list[dict], fitnesses: list[float], n_elite: int) -> list[dict]:
    """Top n_elite individuals (sorted by fitness desc)."""
    idx = sorted(range(len(fitnesses)), key=lambda i: -fitnesses[i])[:n_elite]
    return [dict(population[i]) for i in idx]


def spontaneous(genome: list[Gene], rng: np.random.Generator, n: int) -> list[dict]:
    """Random new individuals for diversity."""
    return [random_individual(genome, rng) for _ in range(n)]
