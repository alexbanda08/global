"""Overlay SMS gates onto the top-10 hybrid_v1 sleeves.

Uses the FULL fire universe from `*_joined_all.parquet` (where all base gates
are pre-computed), joins SMS panel, applies each sleeve's gate stack to
re-derive its passing-fires set, then measures SMS-gate lift.

Inputs:
  data/v4/canonical/_results/{s15,s6,v15m}_joined_all.parquet  — fires + base gates
  data/v4/canonical/_results/sms_panel_{5m,15m}.parquet        — SMS panel
  data/v4/canonical/_results/hybrid_gate_search_top.csv        — top sleeves to overlay

Outputs:
  data/v4/canonical/_results/sms_gate_overlay.csv
  data/v4/canonical/_results/sms_top_new_sleeves.csv
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"

GATE_TOP = RES / "hybrid_gate_search_top.csv"
S15_JOIN = RES / "s15_joined_all.parquet"
S6_JOIN = RES / "s6_joined_all.parquet"
V15M_JOIN = RES / "v15m_joined_all.parquet"

SMS_5M = RES / "sms_panel_5m.parquet"
SMS_15M = RES / "sms_panel_15m.parquet"

OUT = RES / "sms_gate_overlay.csv"
OUT_TOP_SLEEVES = RES / "sms_top_new_sleeves.csv"


SMS_COL_LIST = [
    "bos_buy", "bos_sell", "choch_buy", "choch_sell",
    "bars_since_bos_buy", "bars_since_bos_sell",
    "bars_since_choch_buy", "bars_since_choch_sell",
    "rsi_bullish_div", "rsi_bearish_div",
    "cvd_sign", "cvd_level",
    "liquidity_up", "liquidity_dn",
    "trend_strength_raw", "system_confidence",
]


def merge_sms(joined: pd.DataFrame, sms_panel_path: Path, tf_min: int) -> pd.DataFrame:
    panel = pd.read_parquet(sms_panel_path)[["asset", "ts_us"] + SMS_COL_LIST].copy()
    bar_us = tf_min * 60 * 1_000_000
    out_parts = []
    for asset in ("BTC", "ETH", "SOL"):
        f_a = joined[joined.asset == asset].copy()
        p_a = panel[panel.asset == asset][["ts_us"] + SMS_COL_LIST].copy()
        if len(f_a) == 0:
            continue
        f_a["lookup_us"] = f_a["fire_us"].astype("int64") - bar_us
        f_a = f_a.sort_values("lookup_us")
        p_a = p_a.sort_values("ts_us")
        m = pd.merge_asof(
            f_a, p_a.rename(columns={"ts_us": "panel_ts_us"}),
            left_on="lookup_us", right_on="panel_ts_us",
            direction="backward", tolerance=2 * bar_us,
        )
        out_parts.append(m)
    return pd.concat(out_parts, ignore_index=True)


def add_sms_gates(df: pd.DataFrame) -> pd.DataFrame:
    is_up = (df["direction"] == "UP").astype(np.int8)
    is_dn = (df["direction"] == "DOWN").astype(np.int8)
    df = df.copy()

    df["g_sms_recent_bos_with"] = (
        (is_up & ((df["bars_since_bos_buy"] >= 0) & (df["bars_since_bos_buy"] <= 5))) |
        (is_dn & ((df["bars_since_bos_sell"] >= 0) & (df["bars_since_bos_sell"] <= 5)))
    ).fillna(0).astype(np.int8)
    df["g_sms_recent_choch_with"] = (
        (is_up & ((df["bars_since_choch_buy"] >= 0) & (df["bars_since_choch_buy"] <= 3))) |
        (is_dn & ((df["bars_since_choch_sell"] >= 0) & (df["bars_since_choch_sell"] <= 3)))
    ).fillna(0).astype(np.int8)
    df["g_sms_trend_strength_with"] = (
        (is_up & (df["trend_strength_raw"].fillna(0) >= 3)) |
        (is_dn & (df["trend_strength_raw"].fillna(0) <= -3))
    ).fillna(0).astype(np.int8)
    df["g_sms_conf_high"] = (df["system_confidence"].fillna(0) >= 75).astype(np.int8)
    df["g_sms_cvd_with"] = (
        (is_up & (df["cvd_sign"].fillna(0) > 0)) |
        (is_dn & (df["cvd_sign"].fillna(0) < 0))
    ).fillna(0).astype(np.int8)
    df["g_sms_rsi_div_with"] = (
        (is_up & (df["rsi_bullish_div"].fillna(0) == 1)) |
        (is_dn & (df["rsi_bearish_div"].fillna(0) == 1))
    ).fillna(0).astype(np.int8)
    df["g_sms_no_liquidity_above"] = (
        (is_up & (df["liquidity_up"].fillna(0) == 0)) |
        (is_dn & (df["liquidity_dn"].fillna(0) == 0))
    ).fillna(0).astype(np.int8)
    df["g_sms_liq_reclaim_with"] = (
        (is_up & (df["liquidity_dn"].fillna(0) == 1)) |
        (is_dn & (df["liquidity_up"].fillna(0) == 1))
    ).fillna(0).astype(np.int8)
    return df


SMS_GATES = [
    "g_sms_recent_bos_with", "g_sms_recent_choch_with",
    "g_sms_trend_strength_with", "g_sms_conf_high",
    "g_sms_cvd_with", "g_sms_rsi_div_with",
    "g_sms_no_liquidity_above", "g_sms_liq_reclaim_with",
]


def offset_in_bin(off: int, lo_hi_label: str) -> bool:
    """lo_hi_label like '60-150' / '150-240' / '240-300' / '60-240' / '240-480' / '480-840'."""
    parts = lo_hi_label.split("-")
    lo, hi = int(parts[0]), int(parts[1])
    return lo <= int(off) < hi or (off == hi)  # 300 inclusive at top of 240-300


def apply_stack(df: pd.DataFrame, gate_stack: str) -> np.ndarray:
    gates = gate_stack.split("&")
    mask = np.ones(len(df), dtype=bool)
    for g in gates:
        mask &= (df[g] == 1).values
    return mask


def stat_block(df, label):
    n = len(df)
    if n == 0:
        return {"label": label, "n": 0, "WR": np.nan, "sum_pnl": 0.0, "dpt": np.nan, "wins": 0}
    wins = int(df["won"].sum())
    sum_pnl = float(df["pnl_legacy_usd"].sum())
    return {"label": label, "n": n, "wins": wins, "WR": wins / n,
            "sum_pnl": sum_pnl, "dpt": sum_pnl / n}


def main():
    # 1. Load joined-all per tf and merge SMS
    print("[load + merge SMS]")
    s15 = pd.read_parquet(S15_JOIN)
    s6 = pd.read_parquet(S6_JOIN)
    v15m = pd.read_parquet(V15M_JOIN)
    s15 = merge_sms(s15, SMS_5M, tf_min=5)
    s6 = merge_sms(s6, SMS_5M, tf_min=5)
    v15m = merge_sms(v15m, SMS_15M, tf_min=15)
    s15 = add_sms_gates(s15)
    s6 = add_sms_gates(s6)
    v15m = add_sms_gates(v15m)
    print(f"  s15: {len(s15):,}, s6: {len(s6):,}, v15m: {len(v15m):,}")

    # 2. Load + dedup top sleeves
    tops = pd.read_csv(GATE_TOP)
    tops = tops.drop_duplicates(subset=["asset", "tf", "offset_bin", "gate_stack"]).reset_index(drop=True)
    print(f"  {len(tops)} unique sleeves")
    top10 = tops.sort_values("dpt", ascending=False).head(10).reset_index(drop=True)

    rows = []
    for sleeve_idx, sl in top10.iterrows():
        if sl["tf"] == "s15_5m":
            src = s15; tf_name = "s15_5m"
        elif sl["tf"] == "s6_5m":
            src = s6; tf_name = "s6_5m"
        elif sl["tf"] == "v15m_15m":
            src = v15m; tf_name = "v15m_15m"
        else:
            continue
        # asset + offset_bin + stack
        sub = src[src["asset"] == sl["asset"]].copy()
        # filter to offset_bin
        bin_mask = sub["fire_offset_s"].astype(int).apply(lambda o: offset_in_bin(o, sl["offset_bin"]))
        sub = sub[bin_mask].copy()
        if len(sub) == 0:
            print(f"  [{sleeve_idx}] {sl['asset']}/{tf_name}/{sl['offset_bin']}/{sl['gate_stack'][:60]}: 0 fires in offset_bin")
            continue
        stack_mask = apply_stack(sub, sl["gate_stack"])
        passing = sub[stack_mask].copy()
        print(f"  [{sleeve_idx}] {sl['asset']}/{tf_name}/{sl['offset_bin']}: {len(passing):,} passing fires (expected ~{sl['n']:.0f})")

        base = stat_block(passing, "baseline")
        base.update({"sleeve_id": sleeve_idx, "asset": sl["asset"], "tf": tf_name,
                     "offset_bin": sl["offset_bin"], "sleeve": sl["gate_stack"],
                     "sms_gate": "NONE", "lift_dpt": 0.0, "lift_WR": 0.0})
        rows.append(base)

        for gate in SMS_GATES:
            passing2 = passing[passing[gate] == 1]
            st = stat_block(passing2, gate)
            st.update({"sleeve_id": sleeve_idx, "asset": sl["asset"], "tf": tf_name,
                       "offset_bin": sl["offset_bin"], "sleeve": sl["gate_stack"],
                       "sms_gate": gate,
                       "lift_dpt": st["dpt"] - base["dpt"] if st["n"] > 0 else np.nan,
                       "lift_WR": st["WR"] - base["WR"] if st["n"] > 0 else np.nan})
            rows.append(st)

    res = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(OUT, index=False)
    print(f"\nwrote {OUT} ({len(res)} rows)")

    pd.set_option("display.max_colwidth", 50)
    print("\n=== TOP 10 sleeves baseline + each SMS gate ===")
    print(res[["sleeve_id", "asset", "tf", "offset_bin", "sms_gate", "n", "WR", "dpt", "lift_dpt", "lift_WR"]].to_string(index=False))

    # Build best-new-sleeve per base
    print("\n=== BEST SMS gate per base sleeve (n>=50, n>=20% of base) ===")
    best_new = []
    for sleeve_id, grp in res.groupby("sleeve_id"):
        base = grp[grp["sms_gate"] == "NONE"].iloc[0]
        cands = grp[(grp["sms_gate"] != "NONE") & (grp["n"] >= 50) &
                    (grp["n"] >= 0.2 * base["n"])]
        if len(cands) == 0:
            continue
        # rank by lift_dpt
        best = cands.sort_values("lift_dpt", ascending=False).iloc[0]
        best_new.append({
            "asset": base["asset"], "tf": base["tf"], "offset_bin": base["offset_bin"],
            "base_sleeve": base["sleeve"][:80],
            "added_sms_gate": best["sms_gate"],
            "base_n": int(base["n"]), "base_WR": float(base["WR"]),
            "base_dpt": float(base["dpt"]), "base_sum_pnl": float(base["sum_pnl"]),
            "new_n": int(best["n"]), "new_WR": float(best["WR"]),
            "new_dpt": float(best["dpt"]), "new_sum_pnl": float(best["sum_pnl"]),
            "lift_dpt": float(best["lift_dpt"]), "lift_WR": float(best["lift_WR"]),
            "keep_rate": int(best["n"]) / max(int(base["n"]), 1),
        })
    best_df = pd.DataFrame(best_new).sort_values("new_dpt", ascending=False)
    print(best_df.to_string(index=False))
    best_df.to_csv(OUT_TOP_SLEEVES, index=False)
    print(f"\nwrote {OUT_TOP_SLEEVES}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
