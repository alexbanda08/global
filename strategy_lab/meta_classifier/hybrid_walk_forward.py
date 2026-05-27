"""Walk-forward + bootstrap p-value validation of the top gate stacks.

Picks the top-10 stacks by sum_pnl_28d from hybrid_gate_search.csv, then for each:
  - 20d train / 8d test split (by fire_us UTC day)
  - Reports train_WR, test_WR, train_$/tr, test_$/tr
  - Bootstrap p-value: shuffle outcomes 200x; what fraction of bootstraps
    reach the stack's actual sum_pnl?

Outputs:
  data/v4/canonical/_results/hybrid_walk_forward.csv
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"
sys.path.insert(0, str(ROOT / "strategy_lab" / "meta_classifier"))
from hybrid_backtest import walk_forward_split  # type: ignore

N_BOOT = 200
SEED = 42
TOP_N = 20


def apply_stack(df: pd.DataFrame, gate_stack: str) -> pd.DataFrame:
    if gate_stack == "(baseline)":
        return df.copy()
    mask = np.ones(len(df), dtype=bool)
    for g in gate_stack.split("&"):
        if g in df.columns:
            mask &= df[g].fillna(False).astype(bool).values
        else:
            return df.iloc[[]].copy()
    return df.iloc[mask].copy()


def stats(sub: pd.DataFrame, pnl_col="pnl_legacy_usd") -> dict:
    n = len(sub)
    if n == 0:
        return {"n": 0, "wins": 0, "WR": float("nan"), "sum_pnl": 0.0, "dpt": float("nan")}
    pnl = sub[pnl_col].astype("float64").values
    wins = int((pnl > 0).sum())
    return {"n": n, "wins": wins, "WR": wins / n, "sum_pnl": float(pnl.sum()),
            "dpt": float(pnl.mean())}


def bootstrap_pvalue(full_df: pd.DataFrame, sub_df: pd.DataFrame,
                     pnl_col="pnl_legacy_usd", n_boot=N_BOOT, seed=SEED) -> float:
    """How often does a random subsample of size |sub| beat sub's sum_pnl?"""
    target = float(sub_df[pnl_col].sum())
    pool = full_df[pnl_col].astype("float64").values
    k = len(sub_df)
    if k == 0 or len(pool) <= k:
        return float("nan")
    rng = np.random.default_rng(seed)
    hits = 0
    for _ in range(n_boot):
        idx = rng.choice(len(pool), size=k, replace=False)
        if pool[idx].sum() >= target:
            hits += 1
    return hits / n_boot


def main():
    print("Loading hybrid_gate_search.csv...")
    df_search = pd.read_csv(RES / "hybrid_gate_search.csv")
    # exclude baselines, keep best result per (tf, asset, offset_bin)
    non_base = df_search[df_search["gate_stack"] != "(baseline)"].copy()
    # only consider rows with n >= 30 already (gate_search enforced) and sum_pnl > 0
    non_base = non_base[non_base["sum_pnl"] > 0]
    # Take top-N by sum_pnl globally
    top = non_base.sort_values("sum_pnl", ascending=False).head(TOP_N).reset_index(drop=True)
    print(f"Top {TOP_N} stacks by sum_pnl (all cells):")
    print(top[["tf", "asset", "offset_bin", "gate_stack", "n", "WR", "sum_pnl", "dpt"]].to_string(index=False))

    # Load joined frames
    frames = {
        "s15_5m":  pd.read_parquet(RES / "s15_joined_all.parquet"),
        "v15m_15m": pd.read_parquet(RES / "v15m_joined_all.parquet"),
        "s6_5m":   pd.read_parquet(RES / "s6_joined_all.parquet"),
    }
    # add offset_bin
    for k, df in frames.items():
        df["offset_bin"] = df["fire_offset_s"].astype("int64").apply(
            lambda x: next((f"{lo}-{hi}" for lo, hi in [(60, 150), (150, 240), (240, 300)] if lo <= x < hi),
                          ("240-300" if x == 300 else None)) if k != "v15m_15m" else
            next((f"{lo}-{hi}" for lo, hi in [(60, 240), (240, 480), (480, 840)] if lo <= x < hi),
                 ("480-840" if x == 840 else None))
        )
        frames[k] = df

    rows = []
    for _, r in top.iterrows():
        tf = r["tf"]; asset = r["asset"]; ob = r["offset_bin"]; stack = r["gate_stack"]
        cell_df = frames[tf][(frames[tf].asset == asset) & (frames[tf].offset_bin == ob)].copy()
        sub_full = apply_stack(cell_df, stack)
        full_s = stats(sub_full)

        # train/test split
        train, test = walk_forward_split(cell_df, train_days=20, test_days=8, by="fire_us")
        sub_train = apply_stack(train, stack)
        sub_test = apply_stack(test, stack)
        s_train = stats(sub_train); s_test = stats(sub_test)

        # bootstrap p-value against the FULL cell (random subsample size = sub_full)
        pval = bootstrap_pvalue(cell_df, sub_full)

        rows.append({
            "tf": tf, "asset": asset, "offset_bin": ob, "gate_stack": stack,
            "n_full": full_s["n"], "WR_full": full_s["WR"],
            "sum_pnl_full": full_s["sum_pnl"], "dpt_full": full_s["dpt"],
            "n_train": s_train["n"], "WR_train": s_train["WR"],
            "sum_pnl_train": s_train["sum_pnl"], "dpt_train": s_train["dpt"],
            "n_test": s_test["n"], "WR_test": s_test["WR"],
            "sum_pnl_test": s_test["sum_pnl"], "dpt_test": s_test["dpt"],
            "bootstrap_p": pval,
        })
        oos_status = "PASS" if (s_test["n"] >= 10 and s_test["sum_pnl"] > 0) else "FAIL"
        print(f"  {tf} {asset} {ob} k={len(stack.split('&'))}: "
              f"train n={s_train['n']} WR={s_train['WR']:.3f} ${s_train['sum_pnl']:+.1f}  |  "
              f"test n={s_test['n']} WR={s_test['WR']:.3f} ${s_test['sum_pnl']:+.1f}  |  "
              f"p={pval:.3f}  {oos_status}")

    out = pd.DataFrame(rows)
    out_path = RES / "hybrid_walk_forward.csv"
    out.to_csv(out_path, index=False)
    print(f"\nWrote {out_path}")
    # summary OOS pass/fail counts
    out_with = out.copy()
    out_with["oos_pass"] = (out_with["n_test"] >= 10) & (out_with["sum_pnl_test"] > 0)
    n_pass = int(out_with["oos_pass"].sum())
    n_total = len(out_with)
    print(f"\nOOS test pass rate: {n_pass}/{n_total} ({n_pass/n_total*100:.0f}%)")
    n_sig = int((out["bootstrap_p"] <= 0.05).sum())
    print(f"Bootstrap p<=0.05: {n_sig}/{n_total} ({n_sig/n_total*100:.0f}%)")


if __name__ == "__main__":
    main()
