"""Deep dive on DISAGREEMENT alpha (mp_skew, imb5_diff opposite signs).

Tests:
  - (mp_skew > T_mp) AND (imb5_diff < T_imb)  -> bet UP
  - (mp_skew < -T_mp) AND (imb5_diff > T_imb) -> bet DN
With Hawkes confirmation variant.

Threshold sweep on T_mp in {0, 0.1, 0.3, 0.5} and T_imb in {0, 0.1, 0.2, 0.5}.
Per (asset, tf, fire_offset_s).
"""
import pandas as pd
import numpy as np
import sys

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
OUT_DIR = f"{ROOT}/strategy_lab/cross_feature_2026_05_26"
sys.path.insert(0, OUT_DIR)
from importlib.util import spec_from_file_location, module_from_spec
_spec = spec_from_file_location("score_rules", f"{OUT_DIR}/02_score_rules.py")
_score_mod = module_from_spec(_spec)
_spec.loader.exec_module(_score_mod)
compute_pnl = _score_mod.compute_pnl


def main():
    df = pd.read_parquet(f"{OUT_DIR}/master.parquet")
    df = df[df["outcome"].isin(["Up", "Down"])].copy()
    print(f"rows: {len(df):,}")

    rows = []
    t_mp_grid = [0, 0.1, 0.3, 0.5]
    t_imb_grid = [0, 0.1, 0.2, 0.5]
    hawkes_confirm_grid = [False, True]

    for t_mp in t_mp_grid:
        for t_imb in t_imb_grid:
            for hc in hawkes_confirm_grid:
                # Define rule masks
                if hc:
                    base_up = (
                        (df["mp_skew"] > t_mp) &
                        (df["imb5_diff"] < -t_imb) &
                        (df["hawkes_lambda_imbalance"] > 0.2)
                    )
                    base_dn = (
                        (df["mp_skew"] < -t_mp) &
                        (df["imb5_diff"] > t_imb) &
                        (df["hawkes_lambda_imbalance"] < -0.2)
                    )
                else:
                    base_up = (df["mp_skew"] > t_mp) & (df["imb5_diff"] < -t_imb)
                    base_dn = (df["mp_skew"] < -t_mp) & (df["imb5_diff"] > t_imb)
                base_up = base_up.fillna(False)
                base_dn = base_dn.fillna(False)
                rule_str = f"DISAGR_mp={t_mp}_imb={t_imb}_hk={'Y' if hc else 'N'}"

                for (asset, tf, off), sub in df.groupby(["asset", "tf", "fire_offset_s"]):
                    sub_up = base_up.loc[sub.index]
                    sub_dn = base_dn.loc[sub.index]
                    # UP
                    up_pnl = compute_pnl(sub, "UP")
                    m_up = sub_up & up_pnl.notna()
                    n_up = int(m_up.sum())
                    if n_up >= 30:
                        won_up = (sub.loc[m_up, "outcome"] == "Up").astype(int)
                        pnl_up_vals = up_pnl[m_up].to_numpy(float)
                        rows.append({
                            "rule": rule_str, "side": "UP",
                            "asset": asset, "tf": tf, "fire_offset_s": int(off),
                            "n": n_up, "WR": float(won_up.mean()),
                            "per_trade": float(pnl_up_vals.mean()),
                            "sum_pnl": float(pnl_up_vals.sum()),
                        })
                    # DN
                    dn_pnl = compute_pnl(sub, "DN")
                    m_dn = sub_dn & dn_pnl.notna()
                    n_dn = int(m_dn.sum())
                    if n_dn >= 30:
                        won_dn = (sub.loc[m_dn, "outcome"] == "Down").astype(int)
                        pnl_dn_vals = dn_pnl[m_dn].to_numpy(float)
                        rows.append({
                            "rule": rule_str, "side": "DN",
                            "asset": asset, "tf": tf, "fire_offset_s": int(off),
                            "n": n_dn, "WR": float(won_dn.mean()),
                            "per_trade": float(pnl_dn_vals.mean()),
                            "sum_pnl": float(pnl_dn_vals.sum()),
                        })
    out = pd.DataFrame(rows)
    out.to_csv(f"{OUT_DIR}/disagreement_deep_dive.csv", index=False)
    print(f"Saved disagreement_deep_dive.csv ({len(out)} rows)")
    print()
    print("=== TOP 25 BY PER_TRADE (n>=50, WR>=0.6) ===")
    top = out[(out["n"] >= 50) & (out["WR"] >= 0.6)].sort_values("per_trade", ascending=False).head(25)
    print(top.to_string())

    # By asset/tf summary: best per cell
    print("\n=== BEST DISAGR PER (asset, tf, side, fire_offset) ===")
    grouped = out.groupby(["asset", "tf", "side", "fire_offset_s"])
    best = grouped.apply(lambda g: g.loc[g["per_trade"].idxmax()] if len(g) > 0 else None, include_groups=False).reset_index()
    best = best.sort_values("per_trade", ascending=False).head(30)
    print(best.to_string())

    # Aggregate: for each threshold combo, total fires & avg WR & avg per_trade across all cells
    print("\n=== THRESHOLD AGGREGATE (avg metrics across cells, n>=50) ===")
    out_n50 = out[out["n"] >= 50].copy()
    by_rule = out_n50.groupby("rule").agg(
        n_cells=("n", "size"),
        total_fires=("n", "sum"),
        avg_WR=("WR", "mean"),
        avg_per_trade=("per_trade", "mean"),
        sum_pnl=("sum_pnl", "sum"),
    ).reset_index()
    by_rule = by_rule.sort_values("avg_per_trade", ascending=False)
    print(by_rule.to_string())


if __name__ == "__main__":
    main()
