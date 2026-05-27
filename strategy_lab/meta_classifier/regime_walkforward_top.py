"""Walk-forward on top 3 regime-conditional sleeves to confirm OOS edge.

Split: 19d train (Apr 30 - May 19), 3d test (May 20 - May 22).
For each sleeve:
  - learn best regime from train
  - test: fire only when current regime == learned best regime
Bootstrap CIs on test sum_pnl and dpt.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES  = ROOT / "data" / "v4" / "canonical" / "_results"

WIN_START_US = int(dt.datetime(2026, 4, 30, tzinfo=dt.timezone.utc).timestamp() * 1e6)
WIN_END_US   = int(dt.datetime(2026, 5, 23, tzinfo=dt.timezone.utc).timestamp() * 1e6)


def boot(arr: np.ndarray, n_boot: int = 2000, seed: int = 42) -> dict:
    if arr.size == 0:
        return dict(n=0, sum_pnl=0.0, dpt=np.nan, dpt_ci=(np.nan, np.nan), sum_ci=(np.nan, np.nan))
    rng = np.random.default_rng(seed)
    dpts = np.empty(n_boot)
    sums = np.empty(n_boot)
    for i in range(n_boot):
        ids = rng.integers(0, arr.size, arr.size)
        dpts[i] = arr[ids].mean()
        sums[i] = arr[ids].sum()
    dpts.sort(); sums.sort()
    return dict(
        n=arr.size,
        sum_pnl=float(arr.sum()),
        dpt=float(arr.mean()),
        dpt_ci=(float(dpts[int(0.025*n_boot)]), float(dpts[int(0.975*n_boot)])),
        sum_ci=(float(sums[int(0.025*n_boot)]), float(sums[int(0.975*n_boot)])),
        WR=float((arr > 0).mean()),
    )


def run_sleeve(panel_name: str, asset: str, direction: str) -> dict:
    panel = pd.read_parquet(RES / panel_name)
    panel = panel[panel["regime_label"].notna()].copy()
    sub = panel[(panel["asset"] == asset) & (panel["direction"] == direction)]
    if sub.empty:
        return None
    train_end_us = int(dt.datetime(2026, 5, 20, tzinfo=dt.timezone.utc).timestamp() * 1e6)
    train = sub[sub["fire_us"] < train_end_us]
    test  = sub[sub["fire_us"] >= train_end_us]
    if train.empty or test.empty:
        return None
    # Best regime on train
    g = train.groupby("regime_label")["pnl_legacy_usd"].mean()
    best_regime = g.idxmax() if len(g) else None
    worst_regime = g.idxmin() if len(g) else None
    baseline_train = train["pnl_legacy_usd"].mean()
    baseline_test  = test["pnl_legacy_usd"].mean()
    # Test fires gated to best regime
    test_gated = test[test["regime_label"] == best_regime]
    test_vetoed = test[test["regime_label"] != worst_regime]
    return {
        "panel": panel_name,
        "asset": asset,
        "direction": direction,
        "train_n": len(train),
        "test_n": len(test),
        "train_baseline_dpt": float(baseline_train),
        "test_baseline_dpt":  float(baseline_test),
        "train_best_regime":  best_regime,
        "train_worst_regime": worst_regime,
        "test_baseline_full": boot(test["pnl_legacy_usd"].values),
        "test_gated_best":    boot(test_gated["pnl_legacy_usd"].values),
        "test_vetoed_worst":  boot(test_vetoed["pnl_legacy_usd"].values),
    }


if __name__ == "__main__":
    targets = [
        ("s6_with_ta_regime.parquet",              "ETH", "DOWN"),
        ("v15m_with_ta_and_markov_regime.parquet", "ETH", "DOWN"),
        ("v15m_with_ta_and_markov_regime.parquet", "SOL", "DOWN"),
        ("s6_with_ta_regime.parquet",              "SOL", "DOWN"),
        ("s6_with_ta_regime.parquet",              "BTC", "DOWN"),
        ("s6_with_ta_regime.parquet",              "BTC", "UP"),
        ("s15_with_ta_and_markov_regime.parquet",  "SOL", "DOWN"),
    ]
    rows = []
    for panel_name, asset, direction in targets:
        r = run_sleeve(panel_name, asset, direction)
        if r is None: continue
        rows.append({
            "panel": panel_name, "asset": asset, "direction": direction,
            "train_n": r["train_n"], "test_n": r["test_n"],
            "train_baseline_dpt": r["train_baseline_dpt"],
            "test_baseline_dpt":  r["test_baseline_dpt"],
            "train_best_regime":  r["train_best_regime"],
            "train_worst_regime": r["train_worst_regime"],
            "test_full_n":   r["test_baseline_full"]["n"],
            "test_full_sum": r["test_baseline_full"]["sum_pnl"],
            "test_full_dpt": r["test_baseline_full"]["dpt"],
            "test_full_dpt_ci_low":  r["test_baseline_full"]["dpt_ci"][0],
            "test_full_dpt_ci_high": r["test_baseline_full"]["dpt_ci"][1],
            "test_gated_n":   r["test_gated_best"]["n"],
            "test_gated_sum": r["test_gated_best"]["sum_pnl"],
            "test_gated_dpt": r["test_gated_best"]["dpt"],
            "test_gated_dpt_ci_low":  r["test_gated_best"]["dpt_ci"][0],
            "test_gated_dpt_ci_high": r["test_gated_best"]["dpt_ci"][1],
            "test_veto_n":   r["test_vetoed_worst"]["n"],
            "test_veto_sum": r["test_vetoed_worst"]["sum_pnl"],
            "test_veto_dpt": r["test_vetoed_worst"]["dpt"],
            "test_veto_dpt_ci_low":  r["test_vetoed_worst"]["dpt_ci"][0],
            "test_veto_dpt_ci_high": r["test_vetoed_worst"]["dpt_ci"][1],
        })
    out = pd.DataFrame(rows)
    out_path = RES / "regime_walkforward_top.csv"
    out.to_csv(out_path, index=False)
    print(f"wrote: {out_path}")
    cols_to_show = ["panel", "asset", "direction", "train_best_regime",
                    "train_baseline_dpt", "test_baseline_dpt",
                    "test_full_dpt", "test_gated_dpt", "test_gated_n",
                    "test_gated_dpt_ci_low", "test_gated_dpt_ci_high",
                    "test_veto_dpt", "test_veto_n"]
    print(out[cols_to_show].to_string(index=False))
