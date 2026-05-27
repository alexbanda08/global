"""Summarize V2 hunt for the report — winners per cell, totals, gate compositions."""
from __future__ import annotations
import pandas as pd
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"


def main():
    df = pd.read_csv(RES / "sleeve_hunt_15m_v2_deployable.csv")
    print(f"Total deployable: {len(df)}")

    # Winner per cell (lockbox_n >= 15 for reliability)
    df_clean = df[df["lockbox_n"] >= 15].copy()
    winners = df_clean.sort_values(["asset", "offset_bin", "lockbox_dpt"],
                                     ascending=[True, True, False])
    winners = winners.groupby(["asset", "offset_bin"]).head(1).reset_index(drop=True)
    print(f"\nWinner per (asset, offset_bin) — lockbox_n>=15:")
    cols = ["asset", "offset_bin", "gate_stack", "train_n", "train_WR", "train_dpt",
             "val_n", "val_WR", "val_dpt", "lockbox_n", "lockbox_WR", "lockbox_dpt", "lockbox_p"]
    print(winners[cols].to_string())

    # Total expected PnL
    print(f"\nTotal lockbox_sum across winners: ${(winners['lockbox_n']*winners['lockbox_dpt']).sum():.0f}")
    print(f"Avg dpt across cells: ${winners['lockbox_dpt'].mean():.2f}")

    # R2 confirmation summary
    r2 = pd.read_csv(RES / "sleeve_hunt_15m_v2_r2_confirmation.csv")
    print("\nR2 confirmation status:")
    print(r2["status"].value_counts())

    # Top 10 by lockbox_dpt
    print("\nTop 10 NEW sleeves (by lockbox_dpt, lockbox_n>=20):")
    new_top = df[(df["lockbox_n"] >= 20)].head(10)
    print(new_top[cols].to_string())


if __name__ == "__main__":
    main()
