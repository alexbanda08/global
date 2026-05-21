"""
Genome spec for momo / mispricing sleeves. Each gene = (name, kind, min, max, ...).

Kinds:
  - float: Gaussian mutation with clamp
  - int  : float mutation rounded
  - cat  : pick from choices
  - mask : bitmask integer with bit-flip mutation

A genome is an ordered list of Gene definitions. An Individual is a dict of
gene_name -> concrete value.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import numpy as np


@dataclass
class Gene:
    name: str
    kind: str                # "float" | "int" | "cat" | "mask"
    min: float = 0.0
    max: float = 1.0
    sigma: float = 0.1       # gaussian mutation width (relative to range)
    choices: list[Any] = field(default_factory=list)  # for cat
    n_bits: int = 24         # for mask kind (24 for hour, 7 for dow)

    def sample(self, rng: np.random.Generator) -> Any:
        if self.kind == "float":
            return float(rng.uniform(self.min, self.max))
        if self.kind == "int":
            return int(rng.integers(int(self.min), int(self.max) + 1))
        if self.kind == "cat":
            return self.choices[int(rng.integers(0, len(self.choices)))]
        if self.kind == "mask":
            # Sample uniformly across bit positions
            return int(rng.integers(0, 1 << self.n_bits))
        raise ValueError(f"unknown kind {self.kind}")

    def mutate(self, value: Any, rng: np.random.Generator) -> Any:
        if self.kind == "float":
            width = self.sigma * (self.max - self.min)
            new = value + rng.normal(0, width)
            return float(np.clip(new, self.min, self.max))
        if self.kind == "int":
            width = max(1, self.sigma * (self.max - self.min))
            new = int(round(value + rng.normal(0, width)))
            return int(np.clip(new, self.min, self.max))
        if self.kind == "cat":
            # 50/50 keep vs pick new
            if rng.random() < 0.5:
                return value
            return self.choices[int(rng.integers(0, len(self.choices)))]
        if self.kind == "mask":
            # Flip 1-3 random bits
            n_flips = int(rng.integers(1, 4))
            v = value
            for _ in range(n_flips):
                b = int(rng.integers(0, self.n_bits))
                v ^= (1 << b)
            return int(v)
        raise ValueError(f"unknown kind {self.kind}")


def crossover_uniform(a: dict, b: dict, rng: np.random.Generator) -> dict:
    """Per-gene uniform crossover: each gene 50/50 from either parent."""
    return {k: (a[k] if rng.random() < 0.5 else b[k]) for k in a}


def crossover_npoint(a: dict, b: dict, rng: np.random.Generator) -> dict:
    """Single-point crossover."""
    keys = list(a.keys())
    cut = int(rng.integers(1, len(keys)))
    return {k: (a[k] if i < cut else b[k]) for i, k in enumerate(keys)}


def hour_in_mask(mask: int, hour: int) -> bool:
    return bool((mask >> hour) & 1)


def dow_in_mask(mask: int, dow: int) -> bool:
    return bool((mask >> dow) & 1)


# ----- Concrete genome definitions -----

# Inspired by NextTrade OptimizerVector but tuned for our momo sleeves.
# Each sleeve_type has its own genome.

def momo_5m_genome() -> list[Gene]:
    return [
        Gene("ret_2m_threshold_bp", "float", 0.0, 50.0, sigma=0.15),
        Gene("direction_mode", "cat", choices=["same", "fade"]),
        Gene("spread_max", "float", 0.005, 0.05, sigma=0.15),
        Gene("vwap_lo", "float", 0.05, 0.50, sigma=0.10),
        Gene("vwap_hi", "float", 0.50, 0.95, sigma=0.10),
        Gene("hour_mask", "mask", n_bits=24),
        Gene("dow_mask", "mask", n_bits=7),
        Gene("sigma_window_min", "int", 10, 60, sigma=0.20),
        Gene("notional_usd", "float", 5.0, 50.0, sigma=0.10),
    ]


def momo_15m_genome() -> list[Gene]:
    return momo_5m_genome()  # same gene space, window decided by sleeve type


def mispricing_15m_genome() -> list[Gene]:
    return [
        Gene("edge_threshold", "float", 0.02, 0.25, sigma=0.15),
        Gene("anchor_offset_s", "int", 30, 600, sigma=0.15),
        Gene("obs_horizon_s", "int", 60, 900, sigma=0.15),
        Gene("vwap_lo", "float", 0.10, 0.50, sigma=0.10),
        Gene("vwap_hi", "float", 0.50, 0.90, sigma=0.10),
        Gene("hour_mask", "mask", n_bits=24),
        Gene("dow_mask", "mask", n_bits=7),
        Gene("sigma_window_min", "int", 10, 60, sigma=0.20),
        Gene("fair_p_z_scale", "float", 0.5, 5.0, sigma=0.15),
        Gene("notional_usd", "float", 5.0, 50.0, sigma=0.10),
    ]


GENOMES = {
    "momo_5m":        momo_5m_genome(),
    "momo_15m":       momo_15m_genome(),
    "mispricing_15m": mispricing_15m_genome(),
}


def random_individual(genome: list[Gene], rng: np.random.Generator) -> dict:
    return {g.name: g.sample(rng) for g in genome}


def mutate_individual(ind: dict, genome: list[Gene], rng: np.random.Generator,
                       per_gene_prob: float = 0.30) -> dict:
    """Mutate each gene with probability per_gene_prob."""
    new = dict(ind)
    for g in genome:
        if rng.random() < per_gene_prob:
            new[g.name] = g.mutate(ind[g.name], rng)
    # ensure vwap_lo < vwap_hi
    if "vwap_lo" in new and "vwap_hi" in new and new["vwap_lo"] >= new["vwap_hi"]:
        new["vwap_lo"], new["vwap_hi"] = (new["vwap_hi"] - 0.01, new["vwap_lo"] + 0.01)
        new["vwap_lo"] = max(0.05, min(new["vwap_lo"], 0.49))
        new["vwap_hi"] = min(0.95, max(new["vwap_hi"], 0.51))
    return new
