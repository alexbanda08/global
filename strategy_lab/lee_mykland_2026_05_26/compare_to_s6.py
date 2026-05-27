"""TASK 4 — Compare Lee-Mykland to S6 heuristic spike detector.

S6 fires from `s6_joined_all.parquet` (existing spike detector at OFFSETS 15-120s).
LM "fires" = bars where is_jump_01 OR is_jump_extreme.

For each (asset, fire_offset_s) cell, compare:
  - n_s6 (S6 fires)
  - n_lm (fires with LM jump in 60s)
  - overlap_s6_lm = # S6 fires that ALSO have LM jump in 60s
  - overlap_lm_s6 = # LM-flagged fires that ALSO are S6 fires
  - wr_s6_only, wr_lm_only, wr_both
  - $/tr deltas
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
S6 = ROOT / "data" / "v4" / "canonical" / "_results" / "s6_joined_all.parquet"
LM_5M = ROOT / "data" / "v4" / "canonical" / "_results" / "lm_at_fires_5m.parquet"
LM_PANEL = ROOT / "data" / "v4" / "canonical" / "_results" / "lee_mykland_panel.parquet"
OUT = ROOT / "data" / "v4" / "canonical" / "_results" / "lm_vs_s6_comparison.csv"


def legacy_pnl(direction: str, outcome: str, vwap: float, shares: float, usd_in: float) -> float:
    won = (direction == "UP" and outcome == "Up") or (direction == "DOWN" and outcome == "Down")
    if won:
        gross = shares - usd_in
        if gross > 0:
            return gross - 0.02 * gross
        return gross
    return -usd_in


def main() -> int:
    s6 = pd.read_parquet(S6)
    print(f"[1] s6_joined_all: {len(s6):,} rows; "
          f"per asset/off:\n{s6.groupby(['asset','fire_offset_s']).size().head(8)}")

    # Build set of (asset, slug, fire_offset_s, definition, tier) → S6 fires
    # And dedupe to one fire per (asset, slug, fire_offset_s) — many definitions can fire same fire_us
    s6_unique = s6.drop_duplicates(["asset", "slug", "fire_offset_s"], keep="first").copy()
    s6_unique["s6_fire"] = True
    print(f"    unique s6 fires (slug, offset): {len(s6_unique):,}")
    s6_keys = set(zip(s6_unique["asset"], s6_unique["slug"], s6_unique["fire_offset_s"].astype(int)))

    # LM at fires: full hybrid 5m universe, with LM features
    lm = pd.read_parquet(LM_5M)
    # Add LM jump flag (within 60s of fire OR extreme jump in 60s)
    lm["lm_signal_60s"] = lm["lm_has_jump_60s"].astype(bool)
    lm["lm_signal_extreme_60s"] = lm["lm_has_jump_extreme_60s"].astype(bool)
    print(f"[2] hybrid 5m universe: {len(lm):,} rows; "
          f"lm jump in 60s: {int(lm['lm_signal_60s'].sum()):,}")

    # Mark S6 membership in lm universe
    lm_keys = list(zip(lm["asset"], lm["slug"], lm["fire_offset_s"].astype(int)))
    lm["s6_match"] = [k in s6_keys for k in lm_keys]
    print(f"    matched s6 in lm: {int(lm['s6_match'].sum()):,}")

    # S6 produces a direction. To compute "would S6 bet on this fire", import from s6_unique.
    s6_direction_map = {
        (a, sl, int(off)): d for a, sl, off, d in zip(
            s6_unique["asset"], s6_unique["slug"], s6_unique["fire_offset_s"], s6_unique["direction"]
        )
    }

    # For each fire in lm universe, also compute:
    #   - LM direction = jump_dir_60s sign
    #   - S6 direction (if matched)
    s6_dirs = []
    for a, sl, off in lm_keys:
        s6_dirs.append(s6_direction_map.get((a, sl, off), None))
    lm["s6_direction"] = s6_dirs

    # Now categorize each fire:
    #   - "lm_only": LM jump in 60s, NOT in s6
    #   - "s6_only": in s6, no LM jump in 60s
    #   - "both":    in s6 AND has LM jump in 60s
    #   - "neither": neither
    cat = np.full(len(lm), "neither", dtype=object)
    cat[(lm["lm_signal_60s"]) & (~lm["s6_match"])] = "lm_only"
    cat[(~lm["lm_signal_60s"]) & (lm["s6_match"])] = "s6_only"
    cat[(lm["lm_signal_60s"]) & (lm["s6_match"])] = "both"
    lm["category"] = cat

    # Compute LM-style direction: sign of last_jump_dir_60s
    lm["lm_direction"] = np.where(lm["lm_last_jump_dir_60s"] > 0, "UP",
                                  np.where(lm["lm_last_jump_dir_60s"] < 0, "DOWN", "SKIP"))

    # Compute PnL each fire IF traded — try with LM dir for lm-flagged, S6 dir for s6-only
    bet_dir = np.array(["SKIP"] * len(lm), dtype=object)
    bet_dir[lm["category"] == "lm_only"] = lm.loc[lm["category"] == "lm_only", "lm_direction"].values
    # For "s6_only" and "both", use s6's direction (its decision rule is the spike detector)
    for c in ("s6_only", "both"):
        m = (lm["category"] == c).values
        if m.any():
            bet_dir[m] = np.where(
                lm.loc[m, "s6_direction"].notna(),
                lm.loc[m, "s6_direction"].astype(str).values, "SKIP"
            )
    lm["bet_dir"] = bet_dir

    # Filter to fills
    fills_ok = np.where(lm["bet_dir"] == "UP", lm["up_fill_ok"],
                        np.where(lm["bet_dir"] == "DOWN", lm["dn_fill_ok"], False))
    lm["fill_ok"] = fills_ok
    sub = lm[(lm["bet_dir"] != "SKIP") & (lm["fill_ok"])].copy()
    print(f"[3] tradeable fires (bet_dir!=SKIP, fill_ok): {len(sub):,}")

    # Compute pnl
    pnl = np.zeros(len(sub))
    for i in range(len(sub)):
        r = sub.iloc[i]
        v = r["up_vwap"] if r["bet_dir"] == "UP" else r["dn_vwap"]
        s = r["up_shares"] if r["bet_dir"] == "UP" else r["dn_shares"]
        u = r["up_usd"] if r["bet_dir"] == "UP" else r["dn_usd"]
        pnl[i] = legacy_pnl(r["bet_dir"], r["outcome"], v, s, u)
    sub["pnl_legacy_usd"] = pnl
    sub["won"] = (((sub["bet_dir"] == "UP") & (sub["outcome"] == "Up")) |
                  ((sub["bet_dir"] == "DOWN") & (sub["outcome"] == "Down"))).astype(int)

    # Aggregate by category × asset
    print("\n=== LM vs S6 — per asset (all 5m offsets pooled) ===")
    rows = []
    for asset in ("BTC", "ETH", "SOL"):
        for cat_name in ("lm_only", "s6_only", "both"):
            g = sub[(sub["asset"] == asset) & (sub["category"] == cat_name)]
            if len(g) == 0:
                continue
            rows.append({
                "asset": asset,
                "category": cat_name,
                "n": int(len(g)),
                "wr_pct": float(100.0 * g["won"].mean()),
                "per_tr_usd": float(g["pnl_legacy_usd"].mean()),
                "sum_pnl_usd": float(g["pnl_legacy_usd"].sum()),
            })
            print(f"  {asset} {cat_name:8s} n={len(g):5d}  WR={100.0*g['won'].mean():5.1f}%  "
                  f"$/tr={g['pnl_legacy_usd'].mean():+7.3f}  sum=${g['pnl_legacy_usd'].sum():+9.2f}")

    # Print overlap stats
    print("\n=== OVERLAP ===")
    n_s6_total = int((lm["category"].isin(("s6_only", "both"))).sum())
    n_lm_total = int((lm["category"].isin(("lm_only", "both"))).sum())
    n_both = int((lm["category"] == "both").sum())
    print(f"  Total fires with S6 trigger:       {n_s6_total:,}")
    print(f"  Total fires with LM jump (60s):     {n_lm_total:,}")
    print(f"  Both:                                 {n_both:,}")
    if n_s6_total > 0:
        print(f"  % of S6 fires that are also LM:     {100.0*n_both/n_s6_total:5.1f}%")
    if n_lm_total > 0:
        print(f"  % of LM fires that are also S6:     {100.0*n_both/n_lm_total:5.1f}%")

    out = pd.DataFrame(rows)
    out.to_csv(OUT, index=False)
    print(f"\n[saved] {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
