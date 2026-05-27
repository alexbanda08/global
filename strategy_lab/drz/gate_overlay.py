"""DRZ as gate overlay on existing hybrid_v1 sleeves.

Steps:
  1. Load drz_panel_{5m,15m}.parquet (DRZ state per fire).
  2. Merge DRZ state onto s15/s6/v15m joined frames by (slug, fire_us, asset).
  3. Compute new gate columns:
       g_drz_at_support_with_up        — in support zone AND direction == UP
       g_drz_at_resistance_with_dn     — in resistance zone AND direction == DOWN
       g_drz_near_zone                 — within 0.5*ATR of any DRZ
       g_drz_no_zone                   — no active zone (trend-follow filter)
       g_drz_recent_RC_with_up         — recent_RC AND direction == UP
       g_drz_recent_RE_with_dn         — recent_RE AND direction == DOWN
       g_drz_buyflow                   — sup_pos_pct > 60 AND direction == UP
       g_drz_sellflow                  — res_pos_pct < 40 AND direction == DOWN
  4. Take top-10 hybrid sleeves from hybrid_gate_search_top.csv, evaluate:
       baseline (existing stack) -> what we already know
       baseline + each DRZ gate added (8 combinations) → compare WR + $/tr + sum
  5. Also test REPLACEMENT — remove one TR gate, swap in DRZ gate.

Outputs:
  data/v4/canonical/_results/drz_gate_overlay_results.csv
  data/v4/canonical/_results/drz_gate_overlay_per_fire.parquet
"""
from __future__ import annotations
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"

JOINED_PATHS = {
    "s15_5m":   RES / "s15_joined_all.parquet",
    "s6_5m":    RES / "s6_joined_all.parquet",
    "v15m_15m": RES / "v15m_joined_all.parquet",
}

DRZ_PANELS = {
    "5m":  RES / "drz_panel_5m.parquet",
    "15m": RES / "drz_panel_15m.parquet",
}


def merge_drz(joined: pd.DataFrame, drz: pd.DataFrame) -> pd.DataFrame:
    """Merge drz state onto joined frame by (asset, slug, fire_us)."""
    drz_cols = ["asset", "slug", "fire_us"] + [c for c in drz.columns if c.startswith("drz_")]
    drz_sub = drz[drz_cols].drop_duplicates(["asset", "slug", "fire_us"], keep="first")
    return joined.merge(drz_sub, on=["asset", "slug", "fire_us"], how="left")


def add_drz_gates(d: pd.DataFrame) -> pd.DataFrame:
    """Add DRZ gate columns to a joined+drz frame."""
    d = d.copy()
    dir_up = (d["direction"] == "UP")
    dir_dn = (d["direction"] == "DOWN")
    in_sup = d["drz_in_support_zone"].fillna(False).astype(bool)
    in_res = d["drz_in_resistance_zone"].fillna(False).astype(bool)
    no_zone = (d["drz_active_zone_count"].fillna(0).astype(int) == 0)
    near_sup = d["drz_dist_to_nearest_support_bps"].abs() < 50.0   # within 50bps (~0.5%)
    near_res = d["drz_dist_to_nearest_resistance_bps"].abs() < 50.0
    near_zone = near_sup.fillna(False) | near_res.fillna(False)
    rc = d["drz_recent_RC"].fillna(False).astype(bool)
    re_ = d["drz_recent_RE"].fillna(False).astype(bool)

    sup_pos = d["drz_zone_sup_pos_pct"].fillna(-1.0)
    res_pos = d["drz_zone_res_pos_pct"].fillna(-1.0)

    def g(x):
        return x.astype("int8").values

    d["g_drz_at_support_with_up"]    = g(in_sup & dir_up)
    d["g_drz_at_resistance_with_dn"] = g(in_res & dir_dn)
    d["g_drz_near_zone"]             = g(near_zone)
    d["g_drz_no_zone"]                = g(no_zone)
    d["g_drz_recent_RC_with_up"]     = g(rc & dir_up)
    d["g_drz_recent_RE_with_dn"]     = g(re_ & dir_dn)
    d["g_drz_buyflow_with_up"]        = g((sup_pos > 60.0) & in_sup & dir_up)
    d["g_drz_sellflow_with_dn"]       = g((res_pos < 40.0) & (res_pos >= 0) & in_res & dir_dn)
    # extra binary: at zone aligned (either bull@sup OR bear@res) — combined direction-aware
    d["g_drz_zone_aligned"]          = g((in_sup & dir_up) | (in_res & dir_dn))
    # extra binary: avoid contra-zone (NOT (at resistance AND UP) AND NOT (at support AND DOWN))
    d["g_drz_not_contra_zone"]       = g(~((in_res & dir_up) | (in_sup & dir_dn)))
    return d


def cell_stats(sub: pd.DataFrame, pnl_col: str = "pnl_legacy_usd") -> dict:
    n = len(sub)
    if n == 0:
        return {"n": 0, "wins": 0, "WR": np.nan, "sum_pnl": 0.0, "dpt": np.nan}
    pnl = sub[pnl_col].astype("float64").values
    wins = int((pnl > 0).sum())
    return {"n": n, "wins": wins, "WR": wins / n,
            "sum_pnl": float(pnl.sum()), "dpt": float(pnl.mean())}


def apply_stack(df: pd.DataFrame, gates: list[str]) -> pd.DataFrame:
    mask = np.ones(len(df), dtype=bool)
    for g in gates:
        if g not in df.columns:
            return df.iloc[:0]
        mask &= df[g].fillna(False).astype(bool).values
    return df.iloc[mask]


def main():
    t0 = time.time()
    print("=" * 72); print("DRZ GATE OVERLAY"); print("=" * 72)

    # Load DRZ panels and joined frames
    drz_5m  = pd.read_parquet(DRZ_PANELS["5m"])
    drz_15m = pd.read_parquet(DRZ_PANELS["15m"])
    print(f"drz_panels: 5m={len(drz_5m):,}, 15m={len(drz_15m):,}")

    joined = {}
    for key, p in JOINED_PATHS.items():
        df = pd.read_parquet(p)
        drz_panel = drz_5m if key.endswith("_5m") else drz_15m
        df = merge_drz(df, drz_panel)
        df = add_drz_gates(df)
        joined[key] = df
        n_with_drz = df["drz_in_support_zone"].notna().sum()
        print(f"  {key}: {df.shape}, n_with_drz={n_with_drz:,}")

    # Save joined+drz frames for downstream use
    for key, df in joined.items():
        outp = RES / f"{key.replace('_5m','').replace('_15m','')}_joined_drz.parquet"
        df.to_parquet(outp, index=False, compression="zstd")
        print(f"  wrote {outp}")

    # Top hybrid sleeves — pick the BEST stack PER (asset, tf, offset_bin) for diversity
    top = pd.read_csv(RES / "hybrid_gate_search_top.csv")
    top10 = (top.sort_values("sum_pnl", ascending=False)
             .drop_duplicates(subset=["asset", "tf", "offset_bin"], keep="first")
             .head(10).copy())
    print(f"\nTop-10 DISTINCT hybrid sleeves (one best stack per cell):")
    print(top10[["asset", "tf", "offset_bin", "gate_stack", "n", "WR", "sum_pnl"]].to_string(index=False))

    DRZ_GATES = [
        "g_drz_at_support_with_up",
        "g_drz_at_resistance_with_dn",
        "g_drz_near_zone",
        "g_drz_no_zone",
        "g_drz_recent_RC_with_up",
        "g_drz_recent_RE_with_dn",
        "g_drz_buyflow_with_up",
        "g_drz_sellflow_with_dn",
        "g_drz_zone_aligned",
        "g_drz_not_contra_zone",
    ]

    # offset bin parser
    OFFSET_BINS_5M = [(60, 150), (150, 240), (240, 300)]
    OFFSET_BINS_15M = [(60, 240), (240, 480), (480, 840)]
    def offset_bin(off: int, tf: str) -> str | None:
        bins = OFFSET_BINS_5M if not tf.endswith("15m") else OFFSET_BINS_15M
        for lo, hi in bins:
            if lo <= off < hi:
                return f"{lo}-{hi}"
        if not tf.endswith("15m") and off == 300:
            return "240-300"
        if tf.endswith("15m") and off == 840:
            return "480-840"
        return None

    results = []
    for _, sleeve in top10.iterrows():
        tf_key = sleeve["tf"]
        asset = sleeve["asset"]
        offset = sleeve["offset_bin"]
        stack = sleeve["gate_stack"].split("&")

        df = joined.get(tf_key)
        if df is None:
            continue
        df = df.copy()
        df["offset_bin"] = df["fire_offset_s"].astype("int64").apply(lambda o: offset_bin(int(o), tf_key))
        cell = df[(df["asset"] == asset) & (df["offset_bin"] == offset)]
        if len(cell) == 0:
            continue

        # Baseline (verify we reproduce the table)
        base = apply_stack(cell, stack)
        base_stats = cell_stats(base)
        results.append({
            "sleeve_id": f"{tf_key}/{asset}/{offset}",
            "asset": asset, "tf": tf_key, "offset_bin": offset,
            "stack": "&".join(stack),
            "drz_gate": "",
            "type": "baseline",
            **base_stats,
        })

        # ADD DRZ gate
        for g_drz in DRZ_GATES:
            new_stack = stack + [g_drz]
            sub = apply_stack(cell, new_stack)
            s = cell_stats(sub)
            results.append({
                "sleeve_id": f"{tf_key}/{asset}/{offset}",
                "asset": asset, "tf": tf_key, "offset_bin": offset,
                "stack": "&".join(new_stack),
                "drz_gate": g_drz,
                "type": "ADD",
                **s,
            })

        # REPLACE one TR gate at a time with each DRZ gate
        tr_gates = [g for g in stack if g.startswith("g_tr_")]
        for tr in tr_gates:
            for g_drz in DRZ_GATES:
                new_stack = [g for g in stack if g != tr] + [g_drz]
                sub = apply_stack(cell, new_stack)
                s = cell_stats(sub)
                results.append({
                    "sleeve_id": f"{tf_key}/{asset}/{offset}",
                    "asset": asset, "tf": tf_key, "offset_bin": offset,
                    "stack": "&".join(new_stack),
                    "drz_gate": g_drz,
                    "type": f"REPLACE_{tr}",
                    **s,
                })

    out = pd.DataFrame(results)
    out_path = RES / "drz_gate_overlay_results.csv"
    out.to_csv(out_path, index=False)
    print(f"\nWrote {out_path} ({len(out)} rows)")

    # Highlight: ADD overlays that improved sum_pnl with n>=30
    print("\n--- TOP OVERLAYS THAT IMPROVED ON BASELINE (ADD, n>=30) ---")
    impr = []
    for sid, grp in out.groupby("sleeve_id"):
        base = grp[grp["type"] == "baseline"]
        if len(base) == 0: continue
        b_sum = float(base["sum_pnl"].iloc[0])
        b_n   = int(base["n"].iloc[0])
        b_wr  = float(base["WR"].iloc[0])
        adds = grp[grp["type"] == "ADD"]
        for _, r in adds.iterrows():
            if int(r["n"]) >= 30:
                impr.append({
                    "sleeve_id": sid,
                    "drz_gate": r["drz_gate"],
                    "base_n": b_n, "base_WR": b_wr, "base_sum": b_sum,
                    "new_n": int(r["n"]), "new_WR": float(r["WR"]), "new_sum": float(r["sum_pnl"]),
                    "delta_sum": float(r["sum_pnl"]) - b_sum,
                    "delta_WR": float(r["WR"]) - b_wr,
                    "new_dpt": float(r["dpt"]),
                })
    if impr:
        impr_df = pd.DataFrame(impr).sort_values("delta_sum", ascending=False)
        pd.set_option("display.width", 240); pd.set_option("display.max_colwidth", 60)
        print(impr_df.head(20).to_string(index=False))
        impr_df.to_csv(RES / "drz_gate_overlay_improvements.csv", index=False)
    else:
        print(" no improvements found at n>=30")

    print(f"\nDONE in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
