"""TASK 3 — Standalone Lee-Mykland rule tests.

Rule LM-A: bet WITH last_jump_dir within last 30s (immediate continuation)
Rule LM-B: bet WITH last_jump_dir within last 60s (delayed continuation)
Rule LM-C: bet WITH last_jump_dir within last 120s
Rule LM-D: bet AGAINST last_jump_dir within last 60s (mean revert)
Rule LM-E: bet at any fire where L_stat_at_fire > 5.97 in direction of sign(log_ret)
Rule LM-F: bet WITH last_jump_dir EXTREME (L>10) within 60s
Rule LM-G: bet WITH last_jump_dir EXTREME within 120s

PnL uses LegacyConfig (2%-on-profit-only). Entry vwap/shares already in fire universe.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
F5 = ROOT / "data" / "v4" / "canonical" / "_results" / "lm_at_fires_5m.parquet"
F15 = ROOT / "data" / "v4" / "canonical" / "_results" / "lm_at_fires_15m.parquet"
OUT_CSV = ROOT / "data" / "v4" / "canonical" / "_results" / "lm_standalone_rules.csv"


def legacy_pnl(direction: str, outcome: str, vwap: float, shares: float, usd_in: float) -> float:
    """LegacyConfig 2%-on-profit-only.

    If direction == outcome -> won; gross = shares - usd_in; fee = 2% × gross if gross>0.
    Else lost; pnl = -usd_in.
    """
    won = (direction == "UP" and outcome == "Up") or (direction == "DOWN" and outcome == "Down")
    if won:
        gross = shares - usd_in
        if gross > 0:
            return gross - 0.02 * gross
        return gross
    return -usd_in


def apply_rule(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Return a copy of df with column 'bet_dir' (UP/DOWN/SKIP) for given rule."""
    df = df.copy()
    bet_dir = np.array(["SKIP"] * len(df), dtype=object)

    if rule == "LM-A":  # WITH last_jump_dir within 30s
        mask = df["lm_has_jump_30s"].values
        sign = df["lm_last_jump_dir_30s"].values
    elif rule == "LM-B":  # WITH last_jump_dir within 60s
        mask = df["lm_has_jump_60s"].values
        sign = df["lm_last_jump_dir_60s"].values
    elif rule == "LM-C":  # WITH last_jump_dir within 120s
        mask = df["lm_has_jump_120s"].values
        sign = df["lm_last_jump_dir_120s"].values
    elif rule == "LM-D":  # AGAINST last_jump_dir within 60s
        mask = df["lm_has_jump_60s"].values
        sign = -df["lm_last_jump_dir_60s"].values
    elif rule == "LM-E":  # L_stat_at_fire > 5.97 in dir of sign(log_ret)
        L = df["lm_L_stat_at_fire"].values
        lr = df["lm_log_ret_at_fire"].values
        mask = (np.isfinite(L)) & (L > 5.97) & (np.isfinite(lr)) & (lr != 0)
        sign = np.where(lr > 0, 1, -1)
    elif rule == "LM-F":  # WITH last_jump_dir extreme within 60s
        mask = df["lm_has_jump_extreme_60s"].values
        sign = df["lm_last_jump_dir_extreme_60s"].values
    elif rule == "LM-G":  # WITH last_jump_dir extreme within 120s
        sign = df["lm_last_jump_dir_extreme_120s"].values
        mask = sign != 0
    else:
        raise ValueError(f"unknown rule {rule}")

    up = mask & (sign > 0)
    dn = mask & (sign < 0)
    bet_dir[up] = "UP"
    bet_dir[dn] = "DOWN"
    df["bet_dir"] = bet_dir
    return df


def compute_pnl_for_rule(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """For each fire with bet_dir != SKIP, compute pnl via LegacyConfig from fields."""
    df = apply_rule(df, rule)
    fires = df[df["bet_dir"] != "SKIP"].copy()
    if len(fires) == 0:
        return fires

    # check fill ok for the bet direction
    fills_ok = np.where(fires["bet_dir"] == "UP", fires["up_fill_ok"], fires["dn_fill_ok"])
    fires = fires[fills_ok].copy()
    if len(fires) == 0:
        return fires

    vwap = np.where(fires["bet_dir"] == "UP", fires["up_vwap"], fires["dn_vwap"])
    shares = np.where(fires["bet_dir"] == "UP", fires["up_shares"], fires["dn_shares"])
    usd = np.where(fires["bet_dir"] == "UP", fires["up_usd"], fires["dn_usd"])
    outcome = fires["outcome"].values

    pnl = np.zeros(len(fires))
    for i in range(len(fires)):
        pnl[i] = legacy_pnl(fires["bet_dir"].iloc[i], outcome[i], vwap[i], shares[i], usd[i])
    fires["pnl_legacy_usd"] = pnl
    fires["won"] = np.where(
        ((fires["bet_dir"] == "UP") & (outcome == "Up")) |
        ((fires["bet_dir"] == "DOWN") & (outcome == "Down")),
        1, 0
    )
    return fires


def summarize(fires: pd.DataFrame, rule: str, tf: str) -> pd.DataFrame:
    """Aggregate per (asset, tf, offset, rule)."""
    if len(fires) == 0:
        return pd.DataFrame()
    rows = []
    for (asset, off), g in fires.groupby(["asset", "fire_offset_s"]):
        if len(g) < 1:
            continue
        rows.append({
            "rule": rule,
            "tf": tf,
            "asset": asset,
            "fire_offset_s": int(off),
            "n": int(len(g)),
            "wr_pct": float(100.0 * g["won"].mean()),
            "per_tr_usd": float(g["pnl_legacy_usd"].mean()),
            "sum_pnl_usd": float(g["pnl_legacy_usd"].sum()),
            "max_dd": float(g["pnl_legacy_usd"].cumsum().min()),
        })
    # also asset-level (all offsets)
    for asset, g in fires.groupby("asset"):
        rows.append({
            "rule": rule,
            "tf": tf,
            "asset": asset,
            "fire_offset_s": -1,  # -1 = all offsets pooled
            "n": int(len(g)),
            "wr_pct": float(100.0 * g["won"].mean()),
            "per_tr_usd": float(g["pnl_legacy_usd"].mean()),
            "sum_pnl_usd": float(g["pnl_legacy_usd"].sum()),
            "max_dd": float(g["pnl_legacy_usd"].cumsum().min()),
        })
    return pd.DataFrame(rows)


def main() -> int:
    all_rows = []
    for tf, path in (("5m", F5), ("15m", F15)):
        print(f"\n=== {tf} ({path.name}) ===")
        df = pd.read_parquet(path)
        for rule in ("LM-A", "LM-B", "LM-C", "LM-D", "LM-E", "LM-F", "LM-G"):
            fires = compute_pnl_for_rule(df, rule)
            summ = summarize(fires, rule, tf)
            if len(summ) == 0:
                print(f"  {rule}: NO FIRES")
                continue
            all_rows.append(summ)
            # Print asset-level pooled
            pooled = summ[summ["fire_offset_s"] == -1].sort_values("asset")
            for _, r in pooled.iterrows():
                print(f"  {rule:6s} {r['asset']} pool n={r['n']:6d}  WR={r['wr_pct']:5.1f}%  "
                      f"$/tr={r['per_tr_usd']:+7.3f}  sum=${r['sum_pnl_usd']:+9.2f}")
    out = pd.concat(all_rows, ignore_index=True)
    out.to_csv(OUT_CSV, index=False)
    print(f"\n[saved] {OUT_CSV} ({len(out)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
