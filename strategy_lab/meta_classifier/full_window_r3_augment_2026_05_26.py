"""For each top R2 winning stack, try adding ONE R3 gate. See if combined
stack beats the R2-only stack on the test split (last 8 days).

This is the practical "is R3 a real lift" test.

Output: data/v4/canonical/_results/full_window_r3_augmented_stacks.csv
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab" / "meta_classifier"))
RES = ROOT / "data" / "v4" / "canonical" / "_results"
FULL = RES / "_full_window_2026_05_26"
from hybrid_backtest import walk_forward_split  # type: ignore
from full_window_gate_search_2026_05_26 import (
    load_r3_panels, build_full_window_for_universe, offset_bin_label,
    R3_VOL_GATES, R3_MICRO_GATES, MIN_N, BOOTSTRAP_N, bootstrap_pvalue
)

R3_ALL = R3_VOL_GATES + R3_MICRO_GATES


def evaluate_stack(df, gates, pnl_col="pnl_legacy_usd", train_days=14, test_days=8):
    mask = np.ones(len(df), dtype=bool)
    for g in gates:
        if g not in df.columns:
            return None
        mask &= df[g].fillna(False).astype(bool).values
    sub = df.iloc[mask].copy().sort_values("fire_us")
    if len(sub) < MIN_N:
        return None
    tr, te = walk_forward_split(sub, train_days=train_days, test_days=test_days)
    out = {"n": len(sub)}
    out["WR"] = (sub[pnl_col] > 0).mean()
    out["dpt"] = float(sub[pnl_col].mean())
    out["sum"] = float(sub[pnl_col].sum())
    for nm, x in [("train", tr), ("test", te)]:
        if len(x) == 0:
            out[f"{nm}_n"] = 0; out[f"{nm}_WR"] = float("nan")
            out[f"{nm}_dpt"] = float("nan"); out[f"{nm}_sum"] = 0.0
            continue
        p = x[pnl_col].astype("float64").values
        out[f"{nm}_n"] = len(p)
        out[f"{nm}_WR"] = (p > 0).mean()
        out[f"{nm}_dpt"] = float(p.mean())
        out[f"{nm}_sum"] = float(p.sum())
        if nm == "test":
            out["test_pboot"] = bootstrap_pvalue(p)
    return out


def main():
    print("Loading panels...")
    r3 = load_r3_panels()
    panels = {
        "s15_5m": build_full_window_for_universe("s15_5m", r3),
        "s6_5m": build_full_window_for_universe("s6_5m", r3),
        "v15m_15m": build_full_window_for_universe("v15m_15m", r3),
    }

    # Get top R2-only stacks
    top = pd.read_csv(RES / "full_window_gate_search_top.csv")
    # Take unique (asset, tf, offset_bin, gate_stack) — focus on top 25
    top_unique = top.drop_duplicates(["asset","tf","offset_bin","gate_stack"]).head(25)

    print(f"Augmenting top {len(top_unique)} R2 stacks with each R3 gate...")
    rows = []
    for _, r in top_unique.iterrows():
        ftf = r["tf"]; tf = "5m" if "5m" in ftf else "15m"
        df = panels[ftf].copy()
        df["offset_bin"] = df["fire_offset_s"].astype("int64").apply(lambda o: offset_bin_label(o, tf))
        sub = df[(df.asset == r["asset"]) & (df.offset_bin == r["offset_bin"])].copy()

        base_gates = r["gate_stack"].split("&")
        base_eval = evaluate_stack(sub, base_gates)
        if base_eval is None:
            continue
        for r3_gate in R3_ALL:
            if r3_gate not in sub.columns: continue
            new_gates = base_gates + [r3_gate]
            new_eval = evaluate_stack(sub, new_gates)
            if new_eval is None or new_eval["n"] < MIN_N:
                continue
            row = {
                "asset": r["asset"], "tf": ftf, "offset_bin": r["offset_bin"],
                "r2_stack": "&".join(base_gates), "r3_gate": r3_gate,
                "new_stack": "&".join(new_gates),
                "base_n": base_eval["n"], "base_WR": base_eval["WR"], "base_dpt": base_eval["dpt"], "base_sum": base_eval["sum"],
                "base_test_n": base_eval.get("test_n", 0), "base_test_WR": base_eval.get("test_WR"),
                "base_test_dpt": base_eval.get("test_dpt"), "base_test_sum": base_eval.get("test_sum"),
                "new_n": new_eval["n"], "new_WR": new_eval["WR"], "new_dpt": new_eval["dpt"], "new_sum": new_eval["sum"],
                "new_test_n": new_eval.get("test_n", 0), "new_test_WR": new_eval.get("test_WR"),
                "new_test_dpt": new_eval.get("test_dpt"), "new_test_sum": new_eval.get("test_sum"),
                "new_test_pboot": new_eval.get("test_pboot"),
                "retention_pct": new_eval["n"] / base_eval["n"] * 100 if base_eval["n"] else float("nan"),
                "dpt_lift_full": new_eval["dpt"] - base_eval["dpt"],
                "dpt_lift_test": (new_eval.get("test_dpt", 0) or 0) - (base_eval.get("test_dpt", 0) or 0),
                "WR_lift_test": ((new_eval.get("test_WR", 0) or 0) - (base_eval.get("test_WR", 0) or 0)) * 100,
            }
            rows.append(row)

    df_out = pd.DataFrame(rows)
    # Sort by dpt_lift_test
    df_out = df_out.sort_values("dpt_lift_test", ascending=False).reset_index(drop=True)
    out_path = RES / "full_window_r3_augmented_stacks.csv"
    df_out.to_csv(out_path, index=False)
    print(f"\nwrote {out_path} ({len(df_out)} R2-stack × R3-gate combinations)")

    # Top 20
    print("\nTOP 20 R3-augmented stacks by test_dpt_lift:")
    cols = ["asset","tf","offset_bin","r2_stack","r3_gate","retention_pct","base_test_dpt","new_test_dpt","dpt_lift_test","new_test_WR","new_test_pboot","new_test_n"]
    print(df_out[cols].head(20).to_string())


if __name__ == "__main__":
    main()
