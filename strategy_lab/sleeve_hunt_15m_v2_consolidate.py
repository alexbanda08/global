"""Consolidate greedy + exhaustive deployable lists, dedupe, save final V2 list."""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"


def main():
    g = pd.read_csv(RES / "sleeve_hunt_15m_v2_deployable.csv")
    print(f"Greedy deployable: {len(g)}")
    e = pd.read_csv(RES / "sleeve_hunt_15m_v2_exhaustive.csv")
    print(f"Exhaustive rows: {len(e)}")
    ed = e[e["deployable"] == True].copy()
    print(f"Exhaustive deployable: {len(ed)}")

    # Common columns
    common = sorted(set(g.columns) & set(ed.columns))
    g = g[common]
    ed = ed[common]
    g["source"] = "greedy"
    ed["source"] = "exhaustive"
    combined = pd.concat([g, ed], ignore_index=True)

    # Dedupe by (asset, offset_bin, pool, gate_stack)
    combined["gate_stack_sorted"] = combined["gate_stack"].str.split("&").apply(
        lambda x: "&".join(sorted(x)))
    combined = combined.drop_duplicates(["asset", "offset_bin", "pool", "gate_stack_sorted"],
                                          keep="first").copy()
    combined = combined.sort_values("lockbox_dpt", ascending=False).reset_index(drop=True)
    print(f"Dedup: {len(combined)}")

    out_path = RES / "sleeve_hunt_15m_v2_deployable.csv"
    combined.to_csv(out_path, index=False)
    print(f"\nSaved {out_path}: {combined.shape}")

    # Show top 30
    cols = ["asset", "offset_bin", "pool", "gate_stack",
             "train_n", "train_WR", "train_dpt",
             "val_n", "val_WR", "val_dpt",
             "lockbox_n", "lockbox_WR", "lockbox_dpt", "lockbox_p", "source"]
    print("\nTop 30:")
    print(combined.head(30)[cols].to_string())

    # Stats by asset & offset
    print("\n\nDeployable counts by asset:")
    print(combined.groupby("asset").size())
    print("\nDeployable counts by offset_bin:")
    print(combined.groupby("offset_bin").size())
    print("\nGate-stack composition:")
    gate_counts = {}
    for s in combined["gate_stack"]:
        for gg in s.split("&"):
            gate_counts[gg] = gate_counts.get(gg, 0) + 1
    for gg, c in sorted(gate_counts.items(), key=lambda x: -x[1]):
        print(f"  {gg}: {c}")


if __name__ == "__main__":
    main()
