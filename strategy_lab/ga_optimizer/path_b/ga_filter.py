"""
GA over per-cell action map. Genome = list of cells; gene[i] ∈ {KEEP, INVERT, SKIP}.

Fitness: vector applied to TRAIN-window events → real PnL + Sharpe.
Held-out validation: same vector applied to TEST-window events.
"""
from __future__ import annotations
import json, time
from pathlib import Path
from dataclasses import dataclass, asdict
import numpy as np
import pandas as pd


ACTIONS = ["KEEP", "INVERT", "SKIP"]
ACTION_TO_IDX = {a: i for i, a in enumerate(ACTIONS)}


@dataclass
class PathBConfig:
    population_size: int = 100
    n_generations: int = 80
    elite_fraction: float = 0.10
    spontaneous_fraction: float = 0.10
    per_gene_mut_prob: float = 0.08
    tournament_k: int = 3
    train_fraction: float = 0.65
    val_fraction: float = 0.15
    held_out_fraction: float = 0.20
    seed: int = 42
    min_n_cell: int = 40                 # MIN trades per cell (raised)
    sharpe_weight: float = 0.20
    n_keep_max: int | None = 15          # max active cells (sparsity constraint)
    require_train_and_val_positive: bool = True   # cell must be +PnL on BOTH


def encode_individual_random(n_cells: int, rng: np.random.Generator) -> np.ndarray:
    return rng.integers(0, 3, size=n_cells).astype(np.int8)


def encode_individual_baseline(per_cell_choice: dict, cell_ids: list[str]) -> np.ndarray:
    return np.array([ACTION_TO_IDX[per_cell_choice.get(c, "SKIP")] for c in cell_ids], dtype=np.int8)


def encode_individual_seed_keep(cell_ids: list[str]) -> np.ndarray:
    return np.zeros(len(cell_ids), dtype=np.int8)  # all KEEP (= production default)


def encode_individual_seed_skip(cell_ids: list[str]) -> np.ndarray:
    return np.full(len(cell_ids), 2, dtype=np.int8)  # all SKIP (= no trades baseline)


def apply_actions_to_events(action_vec: np.ndarray, events: pd.DataFrame,
                            cell_ids: list[str]) -> pd.DataFrame:
    """
    Given an action vector indexed by cells_list, project to per-event PnL.
    Adds 'realized_pnl' column to events copy.
    """
    cell_id_to_action_idx = {cid: int(action_vec[i]) for i, cid in enumerate(cell_ids)}
    out = events.copy()
    out["action_idx"] = out["cell_id"].map(cell_id_to_action_idx).fillna(2).astype(int)  # default SKIP
    # vectorized realized_pnl
    pnl_cols = np.stack([out.pnl_same.values, out.pnl_invert.values, out.pnl_skip.values], axis=1)
    out["realized_pnl"] = pnl_cols[np.arange(len(out)), out.action_idx]
    return out


def fitness_on_window(action_vec: np.ndarray, events: pd.DataFrame, cell_ids: list[str],
                      sharpe_weight: float = 0.2, n_keep_max: int | None = None) -> dict:
    """Apply actions, compute fitness on this slice of events."""
    proj = apply_actions_to_events(action_vec, events, cell_ids)
    fired = proj[proj.action_idx != 2]  # excl SKIP
    n = len(fired)
    if n < 30:
        return dict(fitness=-1e9, pnl=0.0, n=n, win_rate=0.0, sharpe=0.0, n_active_cells=0)
    n_active_cells = int(((action_vec == 0) | (action_vec == 1)).sum())
    # Sparsity penalty: if n_keep_max set and exceeded, severe penalty
    sparsity_penalty = 0.0
    if n_keep_max is not None and n_active_cells > n_keep_max:
        sparsity_penalty = (n_active_cells - n_keep_max) * 200.0   # hefty
    pnl = float(fired.realized_pnl.sum())
    won = ((fired.action_idx == 0) & (fired.won == True)) | ((fired.action_idx == 1) & (fired.won == False))
    wr = float(won.mean())
    daily = fired.groupby("date").realized_pnl.sum()
    sharpe = float(daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 0 else 0.0
    fitness = pnl + sharpe_weight * sharpe * 100 - sparsity_penalty
    return dict(fitness=fitness, pnl=pnl, n=n, win_rate=wr, sharpe=sharpe,
                n_active_cells=n_active_cells, sparsity_penalty=sparsity_penalty)


def tournament(fitnesses: np.ndarray, k: int, rng: np.random.Generator) -> int:
    cands = rng.integers(0, len(fitnesses), size=k)
    return int(cands[np.argmax(fitnesses[cands])])


def mutate(vec: np.ndarray, per_gene_prob: float, rng: np.random.Generator) -> np.ndarray:
    mask = rng.random(len(vec)) < per_gene_prob
    new_vals = rng.integers(0, 3, size=mask.sum()).astype(np.int8)
    out = vec.copy()
    out[mask] = new_vals
    return out


def crossover_uniform(a: np.ndarray, b: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    mask = rng.random(len(a)) < 0.5
    return np.where(mask, a, b).astype(np.int8)


def crossover_2point(a: np.ndarray, b: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    n = len(a)
    p1, p2 = sorted(rng.integers(0, n, size=2))
    out = a.copy()
    out[p1:p2] = b[p1:p2]
    return out


def run_path_b_ga(cells: list, events_train: pd.DataFrame, events_val: pd.DataFrame,
                  events_held: pd.DataFrame, config: PathBConfig, run_dir: Path) -> dict:
    rng = np.random.default_rng(config.seed)
    run_dir.mkdir(parents=True, exist_ok=True)

    cell_ids = [c.cell_id for c in cells]
    n_cells = len(cell_ids)
    print(f"[Path B GA] n_cells = {n_cells}")

    # Seed population
    population = [
        encode_individual_seed_keep(cell_ids),     # all KEEP (production)
        encode_individual_seed_skip(cell_ids),     # all SKIP
    ]
    # Conservative baseline: only ACTIVE if train AND val both positive for SAME action
    train_cells_stats = {}
    co_positive_count = 0
    for c in cells:
        tr = events_train[events_train.cell_id == c.cell_id]
        vl = events_val[events_val.cell_id == c.cell_id]
        if len(tr) < 10 or len(vl) < 3:
            train_cells_stats[c.cell_id] = "SKIP"
            continue
        tr_same, tr_inv = float(tr.pnl_same.sum()), float(tr.pnl_invert.sum())
        vl_same, vl_inv = float(vl.pnl_same.sum()), float(vl.pnl_invert.sum())
        if config.require_train_and_val_positive:
            keep_ok = tr_same > 0 and vl_same > 0
            inv_ok = tr_inv > 0 and vl_inv > 0
        else:
            keep_ok = tr_same > 0
            inv_ok = tr_inv > 0
        opts = {"SKIP": 0.0}
        if keep_ok:
            opts["KEEP"] = tr_same + vl_same
        if inv_ok:
            opts["INVERT"] = tr_inv + vl_inv
        chosen = max(opts, key=opts.get)
        train_cells_stats[c.cell_id] = chosen
        if chosen != "SKIP":
            co_positive_count += 1
    print(f"  conservative baseline: {co_positive_count} cells passed train+val co-positive filter")
    baseline_vec = encode_individual_baseline(train_cells_stats, cell_ids)
    population.append(baseline_vec)

    # Evaluate baseline immediately so user sees the starting point
    baseline_train = fitness_on_window(baseline_vec, events_train, cell_ids, config.sharpe_weight, config.n_keep_max)
    baseline_val = fitness_on_window(baseline_vec, events_val, cell_ids, config.sharpe_weight, config.n_keep_max)
    baseline_held = fitness_on_window(baseline_vec, events_held, cell_ids, config.sharpe_weight, config.n_keep_max)
    print(f"  CONSERVATIVE baseline: train ${baseline_train['pnl']:+.0f} (n={baseline_train['n']})  "
          f"val ${baseline_val['pnl']:+.0f} (n={baseline_val['n']})  "
          f"HELD ${baseline_held['pnl']:+.0f} (n={baseline_held['n']} wr={baseline_held['win_rate']:.3f})  "
          f"[active cells: {baseline_train['n_active_cells']}]")

    # Fill rest with random
    while len(population) < config.population_size:
        population.append(encode_individual_random(n_cells, rng))
    population = [np.asarray(v, dtype=np.int8) for v in population[: config.population_size]]

    n_elite = max(1, int(config.population_size * config.elite_fraction))
    n_spont = max(1, int(config.population_size * config.spontaneous_fraction))
    n_offspring = config.population_size - n_elite - n_spont

    history = []
    best_overall = {"score": -1e18, "vector": None, "gen": -1,
                     "train": {"fitness": -1e9, "pnl": 0.0, "n": 0, "win_rate": 0.0, "sharpe": 0.0},
                     "val":   {"fitness": -1e9, "pnl": 0.0, "n": 0, "win_rate": 0.0, "sharpe": 0.0}}

    for gen in range(config.n_generations):
        t0 = time.time()
        fitnesses = np.array([fitness_on_window(p, events_train, cell_ids, config.sharpe_weight, config.n_keep_max)["fitness"]
                               for p in population])
        best_idx = int(np.argmax(fitnesses))
        best_p = population[best_idx]
        best_train = fitness_on_window(best_p, events_train, cell_ids, config.sharpe_weight, config.n_keep_max)
        best_val   = fitness_on_window(best_p, events_val,   cell_ids, config.sharpe_weight, config.n_keep_max)
        elapsed = time.time() - t0

        # Prefer vectors that work on BOTH train + val: composite score = train_fit + 2*val_fit
        composite_score = best_train["fitness"] + 2.0 * best_val["fitness"]
        if composite_score > best_overall["score"]:
            best_overall = {"score": composite_score, "gen": gen, "vector": best_p.tolist(),
                             "train": best_train, "val": best_val}

        n_keep = int((best_p == 0).sum())
        n_inv = int((best_p == 1).sum())
        n_skip = int((best_p == 2).sum())
        history.append(dict(
            gen=gen, best_train_fit=best_train["fitness"], best_train_pnl=best_train["pnl"],
            best_train_n=best_train["n"], best_train_wr=best_train["win_rate"],
            best_val_pnl=best_val["pnl"], best_val_n=best_val["n"], best_val_wr=best_val["win_rate"],
            n_keep=n_keep, n_invert=n_inv, n_skip=n_skip, elapsed_s=elapsed,
        ))
        print(f"[Path B] gen {gen:3d}  train_pnl=${best_train['pnl']:+8.0f} (n={best_train['n']:4d} wr={best_train['win_rate']:.3f})  "
              f"val_pnl=${best_val['pnl']:+8.0f} (n={best_val['n']:4d} wr={best_val['win_rate']:.3f})  "
              f"[K={n_keep} I={n_inv} S={n_skip}]  ({elapsed:.1f}s)")

        # Breed
        # Elite
        elite_idx = np.argsort(-fitnesses)[:n_elite]
        elite = [population[i].copy() for i in elite_idx]
        # Offspring (tournament + crossover + mutation)
        kids = []
        for _ in range(n_offspring):
            a = tournament(fitnesses, config.tournament_k, rng)
            b = tournament(fitnesses, config.tournament_k, rng)
            parent_a, parent_b = population[a], population[b]
            child = crossover_uniform(parent_a, parent_b, rng) if rng.random() < 0.5 \
                    else crossover_2point(parent_a, parent_b, rng)
            child = mutate(child, config.per_gene_mut_prob, rng)
            kids.append(child)
        # Spontaneous
        spont = [encode_individual_random(n_cells, rng) for _ in range(n_spont)]
        population = elite + kids + spont

    # Final: held-out on best overall
    best_vec = np.array(best_overall["vector"], dtype=np.int8)
    held = fitness_on_window(best_vec, events_held, cell_ids, config.sharpe_weight, config.n_keep_max)
    print(f"\n[Path B] HELD-OUT on best gene: n={held['n']} wr={held['win_rate']:.3f} "
          f"pnl=${held['pnl']:+.0f} sharpe={held['sharpe']:.2f}  active_cells={held['n_active_cells']}")

    # Export deployment config (per-cell action)
    deploy = []
    for c, action_idx in zip(cells, best_vec):
        action = ACTIONS[int(action_idx)]
        deploy.append({
            "sleeve_id": c.sleeve_id, "signal": c.signal,
            "hour_bucket": c.hour_bucket, "dow_group": c.dow_group,
            "asset": c.asset, "family": c.family,
            "n_train": c.n, "action": action,
            "live_pnl_keep": c.pnl_same, "live_pnl_invert": c.pnl_invert,
        })
    result = {
        "config": asdict(config),
        "best_overall": best_overall,
        "held_out": held,
        "history": history,
        "deployment": deploy,
    }
    with open(run_dir / "result.json", "w") as f:
        json.dump(result, f, indent=2, default=str)
    return result
