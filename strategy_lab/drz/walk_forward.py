"""Walk-forward + bootstrap validation for top DRZ candidates.

Two evaluation tracks:

  TRACK A — Standalone DRZ rules (no hybrid base sleeves)
    From drz_standalone_results.csv, take the top cells (n>=50) by sum_pnl.
    20d train / 8d test split based on fire_us. Compute train sum_pnl, test
    sum_pnl, test WR. + bootstrap (200 shuffles) of test p-value.

  TRACK B — DRZ overlay on existing hybrid sleeves
    From drz_gate_overlay_improvements.csv with delta_sum > 0 and n>=200.
    Same 20/8 split + bootstrap on the new (stack + DRZ) combo.

Outputs:
  data/v4/canonical/_results/drz_walk_forward.csv
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

LEGACY_FEE = 0.02
N_BOOTSTRAP = 200
RNG = np.random.default_rng(42)
TRAIN_FRAC = 20.0 / 28.0   # 20d / 28d (we have ~32d but use the cleaner middle)


def legacy_pnl(vwap: float, shares: float, usd: float, won: bool) -> float:
    if not np.isfinite(vwap) or shares <= 0 or usd <= 0:
        return np.nan
    if won:
        gross = shares - usd
        return gross - (gross * LEGACY_FEE if gross > 0 else 0.0)
    return -usd


def compute_pnl_for_panel(panel: pd.DataFrame, mask: np.ndarray, direction: str) -> pd.DataFrame:
    """Apply mask + direction; compute legacy pnl per fire."""
    sub = panel.iloc[mask].copy()
    if direction == "UP":
        sub["vwap"] = sub["up_vwap"]; sub["shares"] = sub["up_shares"]
        sub["usd"] = sub["up_usd"]; sub["fill_ok"] = sub["up_fill_ok"]
        sub["won"] = (sub["outcome"] == "Up")
    elif direction == "DOWN":
        sub["vwap"] = sub["dn_vwap"]; sub["shares"] = sub["dn_shares"]
        sub["usd"] = sub["dn_usd"]; sub["fill_ok"] = sub["dn_fill_ok"]
        sub["won"] = (sub["outcome"] == "Down")
    else:
        raise ValueError(f"bad direction {direction}")
    sub = sub[sub["fill_ok"] == True]
    sub["pnl"] = sub.apply(lambda r: legacy_pnl(r["vwap"], r["shares"], r["usd"], r["won"]), axis=1)
    sub = sub.dropna(subset=["pnl"])
    return sub


def time_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """20d train / 8d test by fire_us quantile."""
    if len(df) == 0:
        return df, df
    df_sorted = df.sort_values("fire_us")
    n_train = int(len(df_sorted) * TRAIN_FRAC)
    return df_sorted.iloc[:n_train].copy(), df_sorted.iloc[n_train:].copy()


def bootstrap_p_value(pnl: np.ndarray, n_shuffles: int = N_BOOTSTRAP) -> float:
    """One-sided: P(shuffled sum >= observed sum) under random sign flip null."""
    if len(pnl) < 5:
        return 1.0
    obs = float(pnl.sum())
    shuffled_sums = []
    for _ in range(n_shuffles):
        flips = RNG.choice([-1.0, 1.0], size=len(pnl))
        shuffled_sums.append(float((pnl * flips).sum()))
    arr = np.array(shuffled_sums)
    if obs > 0:
        p = float((arr >= obs).mean())
    else:
        p = float((arr <= obs).mean())
    return p


# ---- Track A: standalone DRZ rules ----

def rule_to_mask(panel: pd.DataFrame, rule: str) -> tuple[np.ndarray, str]:
    in_sup = panel["drz_in_support_zone"].fillna(False).astype(bool).values
    in_res = panel["drz_in_resistance_zone"].fillna(False).astype(bool).values
    rc     = panel["drz_recent_RC"].fillna(False).astype(bool).values
    re_    = panel["drz_recent_RE"].fillna(False).astype(bool).values
    sup_pp = panel["drz_zone_sup_pos_pct"].fillna(-1.0).values
    res_pp = panel["drz_zone_res_pos_pct"].fillna(-1.0).values
    if rule == "A_RC_at_support_UP":
        return rc & in_sup, "UP"
    if rule == "B_RE_at_resistance_DOWN":
        return re_ & in_res, "DOWN"
    if rule == "C_support_buyflow_UP":
        return in_sup & (sup_pp > 60.0), "UP"
    if rule == "D_resistance_sellflow_DOWN":
        return in_res & (res_pp < 40.0) & (res_pp >= 0), "DOWN"
    if rule == "E_at_support_UP":
        return in_sup, "UP"
    if rule == "F_at_resistance_DOWN":
        return in_res, "DOWN"
    raise ValueError(f"unknown rule {rule}")


def track_a():
    rows = []
    standalone = pd.read_csv(RES / "drz_standalone_results.csv")
    candidates = standalone[standalone["n"] >= 50].sort_values("sum_pnl", ascending=False).head(15)

    print("\n--- Track A: standalone DRZ rules walk-forward ---")
    print(f"  {len(candidates)} candidates (n>=50)")

    for _, c in candidates.iterrows():
        tf, asset = c["tf"], c["asset"]
        offset = c["offset_bin"]
        rule = c["rule"]
        panel = pd.read_parquet(RES / f"drz_panel_{tf}.parquet")
        # offset bin filter
        lo, hi = [int(x) for x in offset.split("-")]
        panel = panel[(panel["asset"] == asset) &
                      (panel["fire_offset_s"].between(lo, hi - 1, inclusive="both")) ]
        if len(panel) == 0:
            continue

        mask, direction = rule_to_mask(panel, rule)
        pnl_df = compute_pnl_for_panel(panel, mask, direction)
        if len(pnl_df) < 20:
            continue
        tr, te = time_split(pnl_df)
        tr_sum = float(tr["pnl"].sum()); te_sum = float(te["pnl"].sum())
        tr_wr  = float((tr["won"] > 0).mean()) if len(tr) else np.nan
        te_wr  = float((te["won"] > 0).mean()) if len(te) else np.nan
        p_val = bootstrap_p_value(pnl_df["pnl"].values)
        sign_pass = (tr_sum > 0) and (te_sum > 0)
        rows.append({
            "track": "A_standalone",
            "rule": rule, "asset": asset, "tf": tf, "offset_bin": offset,
            "full_n": len(pnl_df), "full_sum": float(pnl_df["pnl"].sum()),
            "full_WR": float(pnl_df["won"].mean()),
            "full_dpt": float(pnl_df["pnl"].mean()),
            "train_n": len(tr), "train_sum": tr_sum, "train_WR": tr_wr,
            "test_n": len(te), "test_sum": te_sum, "test_WR": te_wr,
            "p_value": p_val,
            "sign_pass": sign_pass,
        })
    return rows


# ---- Track B: hybrid sleeve + DRZ overlay ----

def track_b():
    rows = []
    imp_path = RES / "drz_gate_overlay_improvements.csv"
    if not imp_path.exists():
        return rows
    imp = pd.read_csv(imp_path)
    imp = imp[(imp["delta_sum"] > 0) & (imp["new_n"] >= 200)].head(10)
    print("\n--- Track B: hybrid + DRZ overlay walk-forward ---")
    print(f"  {len(imp)} candidates")

    if len(imp) == 0:
        return rows

    # load joined+drz frames
    frames = {
        "s15_5m":   pd.read_parquet(RES / "s15_joined_drz.parquet"),
        "s6_5m":    pd.read_parquet(RES / "s6_joined_drz.parquet"),
        "v15m_15m": pd.read_parquet(RES / "v15m_joined_drz.parquet"),
    }

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

    # we need to also fetch the baseline stack for each sleeve
    top = pd.read_csv(RES / "hybrid_gate_search_top.csv")
    top_distinct = (top.sort_values("sum_pnl", ascending=False)
                    .drop_duplicates(subset=["asset", "tf", "offset_bin"], keep="first"))

    for _, c in imp.iterrows():
        sid = c["sleeve_id"]
        tf_key, asset, offset = sid.split("/")
        base_row = top_distinct[(top_distinct["asset"] == asset) &
                                (top_distinct["tf"] == tf_key) &
                                (top_distinct["offset_bin"] == offset)]
        if len(base_row) == 0:
            continue
        stack = base_row["gate_stack"].iloc[0].split("&")
        drz_gate = c["drz_gate"]
        new_stack = stack + [drz_gate]

        df = frames[tf_key].copy()
        df["offset_bin"] = df["fire_offset_s"].astype("int64").apply(lambda o: offset_bin(int(o), tf_key))
        cell = df[(df["asset"] == asset) & (df["offset_bin"] == offset)].copy()
        if len(cell) == 0:
            continue

        # apply stack
        mask = np.ones(len(cell), dtype=bool)
        for g in new_stack:
            if g not in cell.columns:
                mask = np.zeros(len(cell), dtype=bool); break
            mask &= cell[g].fillna(False).astype(bool).values
        sub = cell.iloc[mask].copy()
        if len(sub) < 20:
            continue
        sub["pnl"] = sub["pnl_legacy_usd"].astype("float64")
        sub["won"] = (sub["pnl"] > 0)
        tr, te = time_split(sub)
        tr_sum = float(tr["pnl"].sum()); te_sum = float(te["pnl"].sum())
        tr_wr  = float((tr["won"] > 0).mean()) if len(tr) else np.nan
        te_wr  = float((te["won"] > 0).mean()) if len(te) else np.nan
        p_val = bootstrap_p_value(sub["pnl"].values)
        sign_pass = (tr_sum > 0) and (te_sum > 0)
        rows.append({
            "track": "B_overlay",
            "rule": f"{'+'.join(stack)} + {drz_gate}",
            "asset": asset, "tf": tf_key, "offset_bin": offset,
            "full_n": len(sub), "full_sum": float(sub["pnl"].sum()),
            "full_WR": float(sub["won"].mean()),
            "full_dpt": float(sub["pnl"].mean()),
            "train_n": len(tr), "train_sum": tr_sum, "train_WR": tr_wr,
            "test_n": len(te), "test_sum": te_sum, "test_WR": te_wr,
            "p_value": p_val,
            "sign_pass": sign_pass,
        })
    return rows


def main():
    t0 = time.time()
    print("=" * 72); print("DRZ WALK-FORWARD"); print("=" * 72)
    rows = track_a() + track_b()
    out = pd.DataFrame(rows)
    out = out.sort_values(["track", "full_sum"], ascending=[True, False])
    out_path = RES / "drz_walk_forward.csv"
    out.to_csv(out_path, index=False)
    print(f"\nWrote {out_path} ({len(out)} rows)")
    pd.set_option("display.width", 240); pd.set_option("display.max_colwidth", 60)
    print("\n--- ALL CANDIDATES ---")
    show_cols = ["track","rule","asset","tf","offset_bin","full_n","full_sum","full_dpt","train_sum","test_sum","train_WR","test_WR","p_value","sign_pass"]
    print(out[show_cols].to_string(index=False))
    print(f"\nDONE in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
