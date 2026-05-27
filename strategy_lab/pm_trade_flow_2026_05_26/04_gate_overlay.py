"""TASK 4 — Gate-overlay test on top 7 hybrid sleeves.

Use hybrid_standalone_per_fire.parquet which has the actual fired rules and the
direction taken. For each (asset, tf, fire_offset_s, rule) sleeve in deployable list,
join with our PM features and compute lift from each gate.
"""
from __future__ import annotations
import sys
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "strategy_lab" / "pm_trade_flow_2026_05_26"


def main():
    print("Loading per-fire sleeve data...", flush=True)
    pf = pd.read_parquet(ROOT / "data" / "v4" / "canonical" / "_results" / "hybrid_standalone_per_fire.parquet")
    pf["direction_str"] = np.where(pf["direction"] == 1, "Up", "Down")
    print(f"per-fire rows: {len(pf):,}", flush=True)

    dp = pd.read_csv(ROOT / "data" / "v4" / "canonical" / "_results" / "hybrid_standalone_deployable.csv")
    print(f"Deployable sleeves: {len(dp)}", flush=True)
    print(dp.to_string(index=False), flush=True)

    # Load our features
    feats = pd.read_parquet(OUT_DIR / "fires_with_pm_features.parquet")
    # Restrict to columns we need
    feat_cols = ["asset", "slug", "tf", "fire_us", "fire_offset_s",
                 "pm_up_imbalance_30s", "pm_volume_spike",
                 "whale_F1_active_60s", "whale_F2_active_60s",
                 "whale_mintsell_active_60s", "whale_unknown_large_active_60s",
                 "whale_direction_majority", "book_favors_up"]
    feats = feats[feat_cols]

    join_keys = ["asset", "tf", "fire_offset_s", "slug", "fire_us"]
    merged = pf.merge(feats, on=join_keys, how="inner")
    print(f"After merge: {len(merged):,}", flush=True)

    gate_results = []
    for _, sleeve in dp.iterrows():
        asset = sleeve["asset"]
        tf = sleeve["tf"]
        off = int(sleeve["offset_s"])
        rule = sleeve["rule"]
        sub = merged[(merged["asset"] == asset) & (merged["tf"] == tf) & (merged["fire_offset_s"] == off) & (merged["rule"] == rule)].copy()
        if len(sub) == 0:
            print(f"  {asset} {tf} off={off} {rule}: NO MATCH", flush=True)
            continue

        bet_dir = sub["direction_str"].mode().iloc[0] if len(sub) else "Up"
        # baseline = the actual PnL of this sleeve
        base_n = len(sub)
        base_per = sub["pnl"].mean()
        base_wr = (sub["pnl"] > 0).mean() * 100
        base_sum = sub["pnl"].sum()
        print(f"\n{asset} {tf} off={off} {rule} (bet={bet_dir}): n={base_n}, per=${base_per:.3f}, WR={base_wr:.1f}%, sum=${base_sum:.0f}", flush=True)

        # Compute gates aware of direction
        # gate is conditional on the bet's direction
        if bet_dir == "Up":
            sub["g_flow_with"] = (sub["pm_up_imbalance_30s"] > 0).astype(int)
            sub["g_flow_against"] = (sub["pm_up_imbalance_30s"] < 0).astype(int)
            sub["g_whale_with"] = (sub["whale_direction_majority"] == "Up").astype(int)
            sub["g_whale_against"] = (sub["whale_direction_majority"] == "Down").astype(int)
        else:
            sub["g_flow_with"] = (sub["pm_up_imbalance_30s"] < 0).astype(int)
            sub["g_flow_against"] = (sub["pm_up_imbalance_30s"] > 0).astype(int)
            sub["g_whale_with"] = (sub["whale_direction_majority"] == "Down").astype(int)
            sub["g_whale_against"] = (sub["whale_direction_majority"] == "Up").astype(int)
        sub["g_pm_volume_spike_flag"] = sub["pm_volume_spike"]
        sub["g_pm_no_whale"] = ((~sub["whale_F1_active_60s"]) & (~sub["whale_F2_active_60s"]) & (~sub["whale_mintsell_active_60s"]) & (~sub["whale_unknown_large_active_60s"])).astype(int)
        # Combined: flow_with AND no_whale
        sub["g_flow_with_and_no_whale"] = (sub["g_flow_with"] & sub["g_pm_no_whale"]).astype(int)
        # flow strong (>0.3)
        if bet_dir == "Up":
            sub["g_flow_strong_with"] = (sub["pm_up_imbalance_30s"] > 0.3).astype(int)
            sub["g_flow_strong_against"] = (sub["pm_up_imbalance_30s"] < -0.3).astype(int)
        else:
            sub["g_flow_strong_with"] = (sub["pm_up_imbalance_30s"] < -0.3).astype(int)
            sub["g_flow_strong_against"] = (sub["pm_up_imbalance_30s"] > 0.3).astype(int)

        for gate in ["g_flow_with", "g_flow_against", "g_flow_strong_with", "g_flow_strong_against",
                     "g_pm_volume_spike_flag", "g_pm_no_whale", "g_whale_with", "g_whale_against",
                     "g_flow_with_and_no_whale"]:
            mask = sub[gate].astype(int) == 1
            n = int(mask.sum())
            if n == 0:
                continue
            pnl_g = sub.loc[mask, "pnl"]
            gate_results.append({
                "asset": asset, "tf": tf, "off": off, "rule": rule, "bet_dir": bet_dir,
                "gate": gate, "n_base": base_n, "n_pass": n,
                "pass_rate": n / base_n,
                "wr_pass": float((pnl_g > 0).mean() * 100),
                "pnl_per_pass": float(pnl_g.mean()),
                "sum_pnl_pass": float(pnl_g.sum()),
                "pnl_per_base": base_per,
                "lift_per": float(pnl_g.mean() - base_per),
                "wr_base": base_wr,
            })

    g = pd.DataFrame(gate_results)
    g.to_csv(OUT_DIR / "gate_overlay_results.csv", index=False)
    print("\n=== TOP GATE-SLEEVE COMBOS BY LIFT (n_pass>=50) ===", flush=True)
    print(g[g["n_pass"] >= 50].sort_values("lift_per", ascending=False).head(30).to_string(index=False), flush=True)

    # Aggregate lift per gate across sleeves
    agg = g[g["n_pass"] >= 30].groupby("gate").agg(
        n_sleeve_combos=("lift_per", "size"),
        mean_lift_per=("lift_per", "mean"),
        median_lift_per=("lift_per", "median"),
        mean_pass_rate=("pass_rate", "mean"),
        sum_pnl_total=("sum_pnl_pass", "sum"),
    ).reset_index().sort_values("mean_lift_per", ascending=False)
    print("\n=== AGGREGATE LIFT PER GATE ===", flush=True)
    print(agg.to_string(index=False), flush=True)
    agg.to_csv(OUT_DIR / "gate_overlay_aggregate.csv", index=False)


if __name__ == "__main__":
    main()
