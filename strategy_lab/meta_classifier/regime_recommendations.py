"""Top regime-conditional sleeve recommendations.

For each S6 + S1.5 base sleeve (highest variance in dpt across regimes),
identify the best regime to fire and worst regime to skip.

Output: data/v4/canonical/_results/regime_recommendations.csv
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


def analyse(panel: pd.DataFrame, family_name: str) -> list:
    panel = panel[panel["regime_label"].notna()].copy()
    rows = []
    for (asset, direction), sub in panel.groupby(["asset", "direction"]):
        per_regime = sub.groupby("regime_label").agg(
            n=("pnl_legacy_usd", "size"),
            sum_pnl=("pnl_legacy_usd", "sum"),
            WR=("won", "mean"),
            dpt=("pnl_legacy_usd", "mean"),
        ).reset_index()
        if per_regime.empty:
            continue
        baseline_dpt = sub["pnl_legacy_usd"].mean()
        baseline_sum = sub["pnl_legacy_usd"].sum()
        # best (highest dpt) and worst (lowest dpt) regime
        best  = per_regime.sort_values("dpt", ascending=False).iloc[0]
        worst = per_regime.sort_values("dpt").iloc[0]
        # Regime-conditional sleeve: fire ONLY in best regime
        cond_n   = int(best["n"])
        cond_sum = float(best["sum_pnl"])
        cond_dpt = float(best["dpt"])
        # Veto: skip worst regime
        veto = sub[sub["regime_label"] != worst["regime_label"]]
        veto_sum = float(veto["pnl_legacy_usd"].sum())
        veto_dpt = float(veto["pnl_legacy_usd"].mean()) if len(veto) else np.nan
        rows.append({
            "family": family_name,
            "asset": asset,
            "direction": direction,
            "baseline_n": len(sub),
            "baseline_sum": baseline_sum,
            "baseline_dpt": baseline_dpt,
            "best_regime": best["regime_label"],
            "best_n": cond_n,
            "best_sum": cond_sum,
            "best_dpt": cond_dpt,
            "best_WR": float(best["WR"]),
            "worst_regime": worst["regime_label"],
            "worst_dpt": float(worst["dpt"]),
            "veto_n": len(veto),
            "veto_sum": veto_sum,
            "veto_dpt": veto_dpt,
            "dpt_uplift_best": cond_dpt - baseline_dpt,
            "dpt_uplift_veto": veto_dpt - baseline_dpt,
        })
    return rows


def main():
    s6  = pd.read_parquet(RES / "s6_with_ta_regime.parquet")
    s15 = pd.read_parquet(RES / "s15_with_ta_and_markov_regime.parquet")
    v15 = pd.read_parquet(RES / "v15m_with_ta_and_markov_regime.parquet")

    rows = []
    rows += analyse(s6,  "S6_5m")
    rows += analyse(s15, "S1.5_5m")
    rows += analyse(v15, "S7_15m")
    out = pd.DataFrame(rows)
    out_path = RES / "regime_recommendations.csv"
    out.to_csv(out_path, index=False)
    print(f"wrote: {out_path}")

    # Print top recommendations by dpt uplift in best regime
    out_sorted = out.sort_values("dpt_uplift_best", ascending=False)
    print()
    print("=== Top 15 (best regime dpt uplift vs baseline) ===")
    cols = ["family", "asset", "direction", "best_regime", "best_n", "best_dpt",
            "baseline_dpt", "dpt_uplift_best", "best_sum", "baseline_sum"]
    print(out_sorted[cols].head(15).to_string(index=False))
    print()
    print("=== Top 10 (veto-improvement) ===")
    cols2 = ["family", "asset", "direction", "worst_regime", "veto_dpt", "baseline_dpt",
            "dpt_uplift_veto", "veto_sum", "baseline_sum"]
    print(out_sorted.sort_values("dpt_uplift_veto", ascending=False)[cols2].head(10).to_string(index=False))


if __name__ == "__main__":
    main()
