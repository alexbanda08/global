"""TASK 5 — Apply Lee-Mykland as gate overlay on top sleeves.

Top sleeves from MASTER_DEPLOY_SPEC_2026_05_26.md (A.1.1 - A.1.7 hybrid v1):
  All built on top of s6_joined_all (BTC/ETH/SOL 5m + 15m).

LM Gates:
  g_lm_recent_jump_with = last LM jump_01 within 60s aligns with bet dir
  g_lm_no_recent_jump   = no LM jump_01 in last 120s
  g_lm_high_stat        = current L_stat at fire > 5.97 (1% sig)
  g_lm_jump_count_high  = >2 LM jumps_01 in last 300s
  g_lm_extreme_with     = last extreme jump (L>10) within 120s aligns with bet dir

For each (asset × tf × offset_s_range) base sleeve + each LM gate, report:
  n_base, WR_base, $/tr_base; n_gated, WR_gated, $/tr_gated
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
S6 = ROOT / "data" / "v4" / "canonical" / "_results" / "s6_joined_all.parquet"
LM_5M = ROOT / "data" / "v4" / "canonical" / "_results" / "lm_at_fires_5m.parquet"
LM_15M = ROOT / "data" / "v4" / "canonical" / "_results" / "lm_at_fires_15m.parquet"
OUT = ROOT / "data" / "v4" / "canonical" / "_results" / "lm_gate_overlay.csv"


def legacy_pnl(direction: str, outcome: str, vwap: float, shares: float, usd_in: float) -> float:
    won = (direction == "UP" and outcome == "Up") or (direction == "DOWN" and outcome == "Down")
    if won:
        gross = shares - usd_in
        if gross > 0:
            return gross - 0.02 * gross
        return gross
    return -usd_in


def add_lm_gates(df: pd.DataFrame, direction_col: str) -> pd.DataFrame:
    """Add gate columns based on LM features and the bet direction column.

    direction_col: 'UP' or 'DOWN' per row (the sleeve's bet direction).
    """
    df = df.copy()
    dir_sign = np.where(df[direction_col] == "UP", 1,
                         np.where(df[direction_col] == "DOWN", -1, 0))

    df["g_lm_recent_jump_with"] = (
        df["lm_has_jump_60s"] & (df["lm_last_jump_dir_60s"] == dir_sign) & (dir_sign != 0)
    )
    df["g_lm_no_recent_jump"] = (~df["lm_has_jump_120s"])
    df["g_lm_high_stat"] = (df["lm_L_stat_at_fire"] > 5.97)
    df["g_lm_jump_count_high"] = (df["lm_n_jumps_in_last_300s"] > 2)
    df["g_lm_extreme_with"] = (
        (df["lm_last_jump_dir_extreme_120s"] == dir_sign) & (dir_sign != 0)
    )
    df["g_lm_extreme_against"] = (
        (df["lm_last_jump_dir_extreme_120s"] == -dir_sign) & (dir_sign != 0)
    )
    return df


def build_s6_base_with_lm() -> pd.DataFrame:
    """Join s6_joined_all (5m S6 spike fires) to lm_at_fires_5m by (slug, asset, fire_offset_s)."""
    s6 = pd.read_parquet(S6)
    # Keep S6 selectable fires (their 'direction' picks the bet)
    s6_keep = s6[["asset", "slug", "fire_offset_s", "fire_us", "direction", "outcome",
                  "ret_5s_bps", "ret_15s_bps", "cvd_5s", "cvd_15s"]].copy()
    s6_keep = s6_keep.drop_duplicates(["asset", "slug", "fire_offset_s"], keep="first")

    # Hybrid 5m universe has the up/dn fill fields
    lm = pd.read_parquet(LM_5M)
    # Pull the LM feature cols + fill cols
    lm_keep = lm[["asset", "slug", "fire_offset_s",
                  "up_fill_ok", "dn_fill_ok",
                  "up_vwap", "up_shares", "up_usd",
                  "dn_vwap", "dn_shares", "dn_usd",
                  "lm_L_stat_at_fire", "lm_log_ret_at_fire",
                  "lm_has_jump_30s", "lm_has_jump_60s", "lm_has_jump_120s",
                  "lm_has_jump_extreme_60s",
                  "lm_last_jump_dir_30s", "lm_last_jump_dir_60s", "lm_last_jump_dir_120s",
                  "lm_last_jump_dir_extreme_60s", "lm_last_jump_dir_extreme_120s",
                  "lm_n_jumps_in_last_300s", "lm_n_jumps_extreme_300s"]].copy()

    base = s6_keep.merge(lm_keep, on=["asset", "slug", "fire_offset_s"], how="inner")
    print(f"  S6×LM joined: {len(base):,} rows (s6={len(s6_keep):,}, lm={len(lm):,})")

    # Compute base pnl using S6's picked direction
    fills_ok = np.where(base["direction"] == "UP", base["up_fill_ok"], base["dn_fill_ok"])
    base = base[fills_ok].copy()
    vwap = np.where(base["direction"] == "UP", base["up_vwap"], base["dn_vwap"])
    shares = np.where(base["direction"] == "UP", base["up_shares"], base["dn_shares"])
    usd = np.where(base["direction"] == "UP", base["up_usd"], base["dn_usd"])
    pnl = np.zeros(len(base))
    for i in range(len(base)):
        pnl[i] = legacy_pnl(base["direction"].iloc[i], base["outcome"].iloc[i],
                            vwap[i], shares[i], usd[i])
    base["pnl_legacy_usd"] = pnl
    base["won"] = (((base["direction"] == "UP") & (base["outcome"] == "Up")) |
                   ((base["direction"] == "DOWN") & (base["outcome"] == "Down"))).astype(int)
    return base


def report_sleeve(name: str, df: pd.DataFrame, mask: np.ndarray) -> dict:
    g = df[mask]
    n = int(len(g))
    if n == 0:
        return {"sleeve": name, "n": 0, "wr_pct": np.nan, "per_tr_usd": np.nan, "sum_pnl_usd": 0.0}
    return {
        "sleeve": name,
        "n": n,
        "wr_pct": float(100.0 * g["won"].mean()),
        "per_tr_usd": float(g["pnl_legacy_usd"].mean()),
        "sum_pnl_usd": float(g["pnl_legacy_usd"].sum()),
    }


def main() -> int:
    print("[1] building S6 + LM joined base...")
    base = build_s6_base_with_lm()
    base = add_lm_gates(base, "direction")
    print(f"    base after fills: {len(base):,}")

    # Define top sleeves as (asset, offset_range) from MASTER_DEPLOY_SPEC A.1
    # A.1.1 BTC s6_hybrid_v1: 60-150s
    # A.1.2 ETH s6_hybrid_v1: 60-150s
    # A.1.3 SOL s6_hybrid_v1: 60-150s
    # We'll also do 15-60s, 30-90s for variations
    sleeves = [
        ("btc_s6_60_150", "BTC", (60, 150)),
        ("eth_s6_60_150", "ETH", (60, 150)),
        ("sol_s6_60_150", "SOL", (60, 150)),
        ("btc_s6_15_60",  "BTC", (15, 60)),
        ("eth_s6_15_60",  "ETH", (15, 60)),
        ("sol_s6_15_60",  "SOL", (15, 60)),
        ("btc_s6_all",    "BTC", (15, 300)),
        ("eth_s6_all",    "ETH", (15, 300)),
        ("sol_s6_all",    "SOL", (15, 300)),
    ]

    gates = [
        ("none", lambda d: np.ones(len(d), dtype=bool)),
        ("g_lm_recent_jump_with", lambda d: d["g_lm_recent_jump_with"].values),
        ("g_lm_no_recent_jump",   lambda d: d["g_lm_no_recent_jump"].values),
        ("g_lm_high_stat",        lambda d: d["g_lm_high_stat"].values),
        ("g_lm_jump_count_high",  lambda d: d["g_lm_jump_count_high"].values),
        ("g_lm_extreme_with",     lambda d: d["g_lm_extreme_with"].values),
        ("g_lm_extreme_against",  lambda d: d["g_lm_extreme_against"].values),
        # composites
        ("g_lm_high_and_with",
            lambda d: (d["g_lm_high_stat"].values & d["g_lm_recent_jump_with"].values)),
        ("g_lm_extreme_with_or_high",
            lambda d: (d["g_lm_extreme_with"].values | d["g_lm_high_stat"].values)),
    ]

    rows = []
    print("\n=== GATE OVERLAY ON TOP SLEEVES ===")
    for sleeve_name, asset, (off_lo, off_hi) in sleeves:
        sub = base[(base["asset"] == asset) &
                   (base["fire_offset_s"] >= off_lo) &
                   (base["fire_offset_s"] <= off_hi)].copy()
        if len(sub) == 0:
            continue
        base_stats = report_sleeve(f"{sleeve_name}_BASE", sub, np.ones(len(sub), dtype=bool))
        print(f"\n  {sleeve_name}: n={base_stats['n']}  WR={base_stats['wr_pct']:.1f}%  "
              f"$/tr={base_stats['per_tr_usd']:+.3f}  sum={base_stats['sum_pnl_usd']:+.2f}")
        rows.append(base_stats)
        for gate_name, gate_fn in gates:
            if gate_name == "none":
                continue
            m = gate_fn(sub)
            stat = report_sleeve(f"{sleeve_name}_{gate_name}", sub, m)
            if stat["n"] >= 20:
                lift_wr = stat["wr_pct"] - base_stats["wr_pct"]
                lift_tr = stat["per_tr_usd"] - base_stats["per_tr_usd"]
                print(f"    {gate_name:30s} n={stat['n']:4d}  WR={stat['wr_pct']:5.1f}% "
                      f"({lift_wr:+5.1f})  $/tr={stat['per_tr_usd']:+.3f} ({lift_tr:+.3f})  "
                      f"sum=${stat['sum_pnl_usd']:+8.2f}")
            rows.append(stat)

    out = pd.DataFrame(rows)
    out.to_csv(OUT, index=False)
    print(f"\n[saved] {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
