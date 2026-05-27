"""Exhaustive top-K gate search for 15m sleeve hunt v2 — find sleeves greedy missed.

For each cell (asset, offset_bin) and pooled, enumerate all 2- and 3-gate stacks
on Train, then validate top-20 by `train_dpt * train_WR * sqrt(n)` on Val + Lockbox.
"""
from __future__ import annotations

import sys
import time
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"
sys.path.insert(0, str(ROOT / "strategy_lab"))

from sleeve_hunt_15m_v2_hunt import (  # noqa: E402
    cell_summary, apply_gate_stack, bootstrap_p_value,
    split_train_val_lockbox, offset_bin_label, OFFSET_BINS,
    COMMON_CANDIDATES,
    TRAIN_END_US, VAL_END_US, LOCKBOX_END_US,
    MIN_N_TRAIN, MIN_N_CELL,
)


def enumerate_top_k(df_train: pd.DataFrame, df_val: pd.DataFrame, df_lockbox: pd.DataFrame,
                     candidates: list, label: dict, k: int = 2,
                     top_n: int = 10, pnl_col: str = "pnl_legacy_usd"):
    """Try all k-combinations and return top_n by train score."""
    avail = [c for c in candidates if c in df_train.columns and df_train[c].sum() > 0]
    if len(avail) < k:
        return []
    rows = []
    pnl_arr = df_train[pnl_col].astype("float64").values
    base_mask = np.ones(len(df_train), dtype=bool)
    for combo in combinations(avail, k):
        mask = base_mask.copy()
        for g in combo:
            mask &= df_train[g].fillna(False).astype(bool).values
        n_train = int(mask.sum())
        if n_train < MIN_N_TRAIN:
            continue
        p = pnl_arr[mask]
        train_wr = float((p > 0).mean())
        train_sum = float(p.sum())
        train_dpt = train_sum / n_train
        score = train_dpt * train_wr * (n_train ** 0.5)
        rows.append({"combo": combo, "score": score, "train_n": n_train,
                      "train_wr": train_wr, "train_sum": train_sum, "train_dpt": train_dpt})
    rows.sort(key=lambda r: -r["score"])
    out = []
    for r in rows[:top_n]:
        gates = list(r["combo"])
        tr_sub = apply_gate_stack(df_train, gates)
        val_sub = apply_gate_stack(df_val, gates)
        lb_sub = apply_gate_stack(df_lockbox, gates)
        s_train = cell_summary(tr_sub, pnl_col)
        s_val = cell_summary(val_sub, pnl_col)
        s_lb = cell_summary(lb_sub, pnl_col)
        p_lockbox = bootstrap_p_value(lb_sub[pnl_col].values) if s_lb["n"] >= 15 else float("nan")
        row = {**label, "gate_stack": "&".join(gates), "k": k}
        for prefix, st in (("train", s_train), ("val", s_val), ("lockbox", s_lb)):
            for kk, v in st.items():
                row[f"{prefix}_{kk}"] = v
        row["lockbox_p"] = p_lockbox
        row["val_pass"] = (s_val["n"] >= 15 and s_val["sum_pnl"] > 0 and s_val["WR"] >= 0.65)
        row["lockbox_pass"] = (s_lb["n"] >= 10 and s_lb["sum_pnl"] > 0 and
                                 s_lb["WR"] >= 0.60 and (np.isnan(p_lockbox) or p_lockbox < 0.10))
        row["deployable"] = row["val_pass"] and row["lockbox_pass"]
        out.append(row)
    return out


def main():
    t0 = time.time()
    print("="*80)
    print("SLEEVE HUNT 15M V2 — EXHAUSTIVE TOP-K (k=2 + k=3) GATE SEARCH")
    print("="*80)

    df = pd.read_parquet(RES / "sleeve_hunt_15m_full_features.parquet")
    df["offset_bin"] = df["fire_offset_s"].astype("int64").apply(offset_bin_label)
    df = df[df["offset_bin"].notna()].copy()
    candidates = [c for c in COMMON_CANDIDATES if c in df.columns]
    print(f"Candidates: {len(candidates)}")

    out = []
    # Per-asset
    print("\n--- Per-asset exhaustive ---")
    for asset in ("BTC", "ETH", "SOL"):
        for ob, _, _ in OFFSET_BINS:
            sub = df[(df.asset == asset) & (df.offset_bin == ob)]
            if len(sub) < MIN_N_CELL:
                continue
            tr, vl, lb = split_train_val_lockbox(sub)
            if len(tr) < MIN_N_CELL:
                continue
            label = {"asset": asset, "offset_bin": ob, "pool": "per_asset"}
            for k in (2, 3):
                rows = enumerate_top_k(tr, vl, lb, candidates, label, k=k, top_n=5)
                out.extend(rows)
        print(f"  {asset} done, {len(out)} rows so far")
    # Pooled
    print("\n--- Pooled exhaustive ---")
    for ob, _, _ in OFFSET_BINS:
        sub = df[df.offset_bin == ob]
        if len(sub) < MIN_N_CELL:
            continue
        tr, vl, lb = split_train_val_lockbox(sub)
        if len(tr) < MIN_N_CELL:
            continue
        label = {"asset": "POOL", "offset_bin": ob, "pool": "pooled_all"}
        for k in (2, 3):
            rows = enumerate_top_k(tr, vl, lb, candidates, label, k=k, top_n=5)
            out.extend(rows)
    print(f"\nTotal: {len(out)} rows")

    df_out = pd.DataFrame(out)
    out_path = RES / "sleeve_hunt_15m_v2_exhaustive.csv"
    df_out.to_csv(out_path, index=False)
    print(f"Saved {out_path}")

    if "deployable" in df_out.columns:
        deploy = df_out[df_out["deployable"] == True].sort_values("lockbox_dpt", ascending=False).reset_index(drop=True)
        print(f"\nDeployable: {len(deploy)}")
        if len(deploy):
            print(deploy[["asset","offset_bin","pool","gate_stack","train_n","train_WR","train_dpt",
                          "val_n","val_WR","val_dpt","lockbox_n","lockbox_WR","lockbox_dpt","lockbox_p"]].head(30).to_string())

    print(f"\n=== DONE in {time.time()-t0:.1f}s ===")


if __name__ == "__main__":
    main()
