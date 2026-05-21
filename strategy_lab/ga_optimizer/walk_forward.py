"""
Walk-forward cross-validation for GA fitness.
Splits the time window into K folds. Each fold trains on first N% + validates on last (100-N)%.
Aggregates fitness across folds → more robust against overfit to a single train/val split.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from .fitness import evaluate_momo, fitness as compute_fitness


def make_walk_forward_folds(ts_min: int, ts_max: int,
                             n_folds: int = 3,
                             train_fraction: float = 0.70) -> list[dict]:
    """
    Build K walk-forward folds. Each fold = (train_window, val_window).
    Folds are time-ordered, expanding train, rolling val.
    """
    span = ts_max - ts_min
    fold_span = span // (n_folds + 1)
    folds = []
    for k in range(n_folds):
        # Each fold uses: ts_min .. (k+1)*fold_span as train, then 1*fold_span as val
        train_end = ts_min + int(fold_span * (k + 1))
        val_end = ts_min + int(fold_span * (k + 2))
        folds.append({
            "k": k,
            "train": (ts_min, train_end),
            "val": (train_end, val_end),
        })
    return folds


def evaluate_individual_cv(individual: dict, sleeve_type: str, asset: str,
                            res_df: pd.DataFrame, books: dict,
                            klines_end_us: np.ndarray, klines_prices: np.ndarray,
                            folds: list[dict]) -> dict:
    """
    Evaluate an individual across all walk-forward folds.
    Returns aggregated fitness = mean(val fitness across folds) with penalty for variance.
    """
    fold_results = []
    for fold in folds:
        # Train fitness (used only for info; we don't fit on this window inside a single eval)
        trades_train = evaluate_momo(individual, sleeve_type, asset, res_df, books,
                                      klines_end_us, klines_prices,
                                      window_us=fold["train"])
        fit_train = compute_fitness(trades_train, individual)
        # Validation fitness on out-of-sample fold
        trades_val = evaluate_momo(individual, sleeve_type, asset, res_df, books,
                                    klines_end_us, klines_prices,
                                    window_us=fold["val"])
        fit_val = compute_fitness(trades_val, individual)
        fold_results.append(dict(k=fold["k"], train=fit_train, val=fit_val))

    val_fitnesses = [r["val"]["fitness"] for r in fold_results]
    val_pnls = [r["val"]["pnl"] for r in fold_results]
    val_ns = [r["val"]["n"] for r in fold_results]
    val_wrs = [r["val"]["win_rate"] for r in fold_results]

    # Aggregate
    mean_val_fit = float(np.mean(val_fitnesses))
    std_val_fit = float(np.std(val_fitnesses))
    # Penalize high variance (unstable across time) — Sharpe-like
    cv_fitness = mean_val_fit - 0.3 * std_val_fit

    # Hard gate: every fold must have n >= 20 (no zero-trade folds)
    if any(n < 20 for n in val_ns):
        cv_fitness -= 0.5

    return dict(
        cv_fitness=cv_fitness,
        mean_val_fitness=mean_val_fit,
        std_val_fitness=std_val_fit,
        val_pnls=val_pnls,
        val_ns=val_ns,
        val_wrs=val_wrs,
        fold_results=fold_results,
    )
