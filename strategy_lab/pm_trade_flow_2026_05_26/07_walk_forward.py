"""TASK 7 — Walk-forward 20d/8d split on top combos.

Take TOP 10 (asset, tf, off, rule_or_combo) by sum_pnl from:
1. Standalone PM rules (segments where rule was +EV)
2. Gate-overlay on hybrid sleeves (where lift was positive)

Split into IS=first 20d, OOS=last 8d. Confirm OOS persistence.
"""
from __future__ import annotations
import sys
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "strategy_lab" / "pm_trade_flow_2026_05_26"

NOTIONAL = 25.0
LEG_FEE_PCT = 0.02


def legacy_pnl(df: pd.DataFrame, dir_col: str) -> pd.Series:
    n = len(df)
    pnl = np.zeros(n, dtype=np.float64)
    up_vwap = df["up_vwap"].values
    dn_vwap = df["dn_vwap"].values
    outcome = df["outcome"].values
    up_fill = df["up_fill_ok"].values
    dn_fill = df["dn_fill_ok"].values
    dirs = df[dir_col].values
    for i in range(n):
        d = dirs[i]
        if d == "Up":
            if not up_fill[i] or np.isnan(up_vwap[i]) or up_vwap[i] <= 0:
                continue
            shares = NOTIONAL / up_vwap[i]
            if outcome[i] == "Up":
                pnl[i] = (shares - NOTIONAL) * (1 - LEG_FEE_PCT)
            else:
                pnl[i] = -NOTIONAL
        elif d == "Down":
            if not dn_fill[i] or np.isnan(dn_vwap[i]) or dn_vwap[i] <= 0:
                continue
            shares = NOTIONAL / dn_vwap[i]
            if outcome[i] == "Down":
                pnl[i] = (shares - NOTIONAL) * (1 - LEG_FEE_PCT)
            else:
                pnl[i] = -NOTIONAL
    return pd.Series(pnl, index=df.index)


def main():
    df = pd.read_parquet(OUT_DIR / "fires_with_pm_features.parquet")
    print(f"fires_with_pm: {len(df):,}", flush=True)

    # Determine split: IS=first 20d, OOS=last
    t_min = df["fire_us"].min()
    t_max = df["fire_us"].max()
    span_us = t_max - t_min
    span_d = span_us / 86_400_000_000
    print(f"Window: {pd.to_datetime(t_min, unit='us')} .. {pd.to_datetime(t_max, unit='us')} = {span_d:.2f}d", flush=True)
    split_us = t_min + int(20 * 86_400_000_000)
    df["is_is"] = df["fire_us"] < split_us
    df["is_oos"] = df["fire_us"] >= split_us
    n_is = df["is_is"].sum()
    n_oos = df["is_oos"].sum()
    print(f"IS: {n_is:,}, OOS: {n_oos:,}", flush=True)

    # CANDIDATE COMBOS to walk-forward
    # 1. PM-A_strong per segment
    df["dir_pmA_strong"] = np.where(df["pm_up_imbalance_30s"] > 0.3, "Up", np.where(df["pm_up_imbalance_30s"] < -0.3, "Down", "none"))
    df["pnl_pmA_strong"] = legacy_pnl(df, "dir_pmA_strong")

    # PM-G mint-sell footprint per segment
    df["dir_pmG"] = np.where(
        df["whale_mintsell_active_60s"] == True,
        np.where(df["whale_up_buys_60s"] > df["whale_dn_buys_60s"], "Down", "Up"),
        "none"
    )
    df["pnl_pmG"] = legacy_pnl(df, "dir_pmG")

    # Gate-overlay on V7 BTC 5m off=90 Down with g_flow_with_and_no_whale
    # Need to load standalone per-fire pnl and join
    pf = pd.read_parquet(ROOT / "data" / "v4" / "canonical" / "_results" / "hybrid_standalone_per_fire.parquet")
    pf["direction_str"] = np.where(pf["direction"] == 1, "Up", "Down")
    print(f"per-fire rows: {len(pf):,}", flush=True)

    feat_cols = ["asset", "slug", "tf", "fire_us", "fire_offset_s",
                 "pm_up_imbalance_30s", "pm_volume_spike", "pm_volume_total_30s",
                 "whale_F1_active_60s", "whale_F2_active_60s",
                 "whale_mintsell_active_60s", "whale_unknown_large_active_60s",
                 "whale_direction_majority"]
    feat_keep = df[feat_cols + ["is_is", "is_oos"]].copy()
    join_keys = ["asset", "tf", "fire_offset_s", "slug", "fire_us"]
    pf2 = pf.merge(feat_keep, on=join_keys, how="inner")
    print(f"pf2 after merge: {len(pf2):,}", flush=True)

    # Build candidate list
    results = []

    # === Candidate 1-5: per-segment PM-A_strong on segments where it was +EV
    pmA_segs = pd.read_csv(OUT_DIR / "standalone_rule_by_segment.csv")
    pmA_segs = pmA_segs[(pmA_segs["rule"] == "pmA_strong") & (pmA_segs["n"] >= 200)].sort_values("sum_pnl", ascending=False).head(5)
    for _, seg in pmA_segs.iterrows():
        sub = df[(df["asset"] == seg["asset"]) & (df["tf"] == seg["tf"]) & (df["fire_offset_s"] == seg["fire_offset_s"])].copy()
        for split in ["is_is", "is_oos"]:
            sub_s = sub[sub[split] & sub["dir_pmA_strong"].isin(["Up", "Down"])].copy()
            if len(sub_s) == 0:
                continue
            wr = (sub_s["pnl_pmA_strong"] > 0).mean() * 100
            results.append({
                "combo": f"pmA_strong_{seg['asset']}_{seg['tf']}_{int(seg['fire_offset_s'])}",
                "split": "IS" if split == "is_is" else "OOS",
                "n": len(sub_s),
                "wr": wr,
                "pnl_per": float(sub_s["pnl_pmA_strong"].mean()),
                "sum_pnl": float(sub_s["pnl_pmA_strong"].sum()),
            })

    # === Candidate 6-12: gate-overlay top combos
    g = pd.read_csv(OUT_DIR / "gate_overlay_results.csv")
    g_top = g[(g["n_pass"] >= 50) & (g["lift_per"] > 0.3)].sort_values("lift_per", ascending=False).head(7)
    print(f"gate-overlay top:\n{g_top.to_string(index=False)}", flush=True)

    for _, row in g_top.iterrows():
        asset = row["asset"]; tf = row["tf"]; off = int(row["off"]); rule = row["rule"]; gate = row["gate"]; bet = row["bet_dir"]
        sub = pf2[(pf2["asset"] == asset) & (pf2["tf"] == tf) & (pf2["fire_offset_s"] == off) & (pf2["rule"] == rule)].copy()
        # Build the gate column
        if bet == "Up":
            if "flow_with" in gate:
                sub["pass"] = sub["pm_up_imbalance_30s"] > 0.3 if "strong" in gate else sub["pm_up_imbalance_30s"] > 0
            elif "flow_against" in gate:
                sub["pass"] = sub["pm_up_imbalance_30s"] < -0.3 if "strong" in gate else sub["pm_up_imbalance_30s"] < 0
            elif gate == "g_whale_with":
                sub["pass"] = (sub["whale_direction_majority"] == "Up")
            elif gate == "g_whale_against":
                sub["pass"] = (sub["whale_direction_majority"] == "Down")
            elif gate == "g_pm_volume_spike_flag":
                sub["pass"] = sub["pm_volume_spike"] == 1
            elif gate == "g_pm_no_whale":
                sub["pass"] = (~sub["whale_F1_active_60s"]) & (~sub["whale_F2_active_60s"]) & (~sub["whale_mintsell_active_60s"]) & (~sub["whale_unknown_large_active_60s"])
            elif gate == "g_flow_with_and_no_whale":
                gw = sub["pm_up_imbalance_30s"] > 0
                nw = (~sub["whale_F1_active_60s"]) & (~sub["whale_F2_active_60s"]) & (~sub["whale_mintsell_active_60s"]) & (~sub["whale_unknown_large_active_60s"])
                sub["pass"] = gw & nw
            else:
                sub["pass"] = True
        else:  # Down
            if "flow_with" in gate:
                sub["pass"] = sub["pm_up_imbalance_30s"] < -0.3 if "strong" in gate else sub["pm_up_imbalance_30s"] < 0
            elif "flow_against" in gate:
                sub["pass"] = sub["pm_up_imbalance_30s"] > 0.3 if "strong" in gate else sub["pm_up_imbalance_30s"] > 0
            elif gate == "g_whale_with":
                sub["pass"] = (sub["whale_direction_majority"] == "Down")
            elif gate == "g_whale_against":
                sub["pass"] = (sub["whale_direction_majority"] == "Up")
            elif gate == "g_pm_volume_spike_flag":
                sub["pass"] = sub["pm_volume_spike"] == 1
            elif gate == "g_pm_no_whale":
                sub["pass"] = (~sub["whale_F1_active_60s"]) & (~sub["whale_F2_active_60s"]) & (~sub["whale_mintsell_active_60s"]) & (~sub["whale_unknown_large_active_60s"])
            elif gate == "g_flow_with_and_no_whale":
                gw = sub["pm_up_imbalance_30s"] < 0
                nw = (~sub["whale_F1_active_60s"]) & (~sub["whale_F2_active_60s"]) & (~sub["whale_mintsell_active_60s"]) & (~sub["whale_unknown_large_active_60s"])
                sub["pass"] = gw & nw
            else:
                sub["pass"] = True

        for split in ["is_is", "is_oos"]:
            sub_s = sub[sub[split] & sub["pass"]].copy()
            if len(sub_s) == 0:
                continue
            wr = (sub_s["pnl"] > 0).mean() * 100
            results.append({
                "combo": f"{asset}_{tf}_{off}_{rule}_{bet}_{gate}",
                "split": "IS" if split == "is_is" else "OOS",
                "n": len(sub_s),
                "wr": wr,
                "pnl_per": float(sub_s["pnl"].mean()),
                "sum_pnl": float(sub_s["pnl"].sum()),
            })

    wfr = pd.DataFrame(results)
    # Build IS vs OOS table
    pivot_n = wfr.pivot_table(index="combo", columns="split", values="n", aggfunc="first")
    pivot_pnl = wfr.pivot_table(index="combo", columns="split", values="sum_pnl", aggfunc="first")
    pivot_per = wfr.pivot_table(index="combo", columns="split", values="pnl_per", aggfunc="first")
    pivot_wr = wfr.pivot_table(index="combo", columns="split", values="wr", aggfunc="first")
    out = pd.concat([pivot_n.add_suffix("_n"), pivot_pnl.add_suffix("_pnl"), pivot_per.add_suffix("_per"), pivot_wr.add_suffix("_wr")], axis=1).reset_index()
    out = out.sort_values("IS_pnl", ascending=False)
    print("\n=== WALK-FORWARD TABLE ===", flush=True)
    print(out.to_string(index=False), flush=True)
    out.to_csv(OUT_DIR / "walkforward_results.csv", index=False)

    # Pass count: how many combos have OOS_pnl > 0
    n_combos = len(out)
    n_oos_positive = (out["OOS_pnl"] > 0).sum() if "OOS_pnl" in out.columns else 0
    print(f"\nPASS COUNT: {n_oos_positive}/{n_combos} have positive OOS sum_pnl", flush=True)


if __name__ == "__main__":
    main()
