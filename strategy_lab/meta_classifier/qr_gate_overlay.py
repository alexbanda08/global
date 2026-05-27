"""TASK 4 — QR gates as filters on existing top hybrid_v1 sleeves.

Strategy: take the top-10 hybrid_v1 sleeves (from hybrid_gate_search_top.csv).
For each sleeve, replay it against the per-fire joined data (s15/s6/v15m
_joined_all), then test adding each NEW QR gate (g_qr_*). Report lift in
WR, $/tr, sum_pnl, n.

QR binary gates (all evaluated WRT bet direction):
  g_qr_state_with       — qr_state matches direction (>=+1 UP, <=-1 DOWN)
  g_qr_state_strong_with — |qr_state|==2 matches direction
  g_qr_trending         — market_regime == 1 (trending; direction-agnostic)
  g_qr_high_health      — market_health > 70 (direction-agnostic)
  g_qr_high_conf        — signal_confidence > 4 (direction-agnostic)
  g_qr_top_conf         — signal_confidence > 6 (direction-agnostic)
  g_qr_volume_strong    — volume_ratio > 1.3 (direction-agnostic)

Outputs:
  data/v4/canonical/_results/qr_gate_overlay.csv
  data/v4/canonical/_results/qr_gate_overlay_top.csv
"""
from __future__ import annotations
import sys, time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"
QR5 = RES / "qr_panel_5m.parquet"
QR15 = RES / "qr_panel_15m.parquet"
TOP = RES / "hybrid_gate_search_top.csv"

S15 = RES / "s15_joined_all.parquet"
S6 = RES / "s6_joined_all.parquet"
V15M = RES / "v15m_joined_all.parquet"

OUT_FULL = RES / "qr_gate_overlay.csv"
OUT_TOP = RES / "qr_gate_overlay_top.csv"

QR_GATES = [
    "g_qr_state_with",
    "g_qr_state_strong_with",
    "g_qr_trending",
    "g_qr_high_health",
    "g_qr_high_conf",
    "g_qr_top_conf",
    "g_qr_volume_strong",
]


def add_qr_gates(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    dir_up = d["direction"] == "UP"
    dir_dn = d["direction"] == "DOWN"

    def g(cond):
        return cond.fillna(False).astype("int8").values

    d["g_qr_state_with"] = g(
        ((d["qr_ribbon_state"] >= 1) & dir_up) | ((d["qr_ribbon_state"] <= -1) & dir_dn)
    )
    d["g_qr_state_strong_with"] = g(
        ((d["qr_ribbon_state"] == 2) & dir_up) | ((d["qr_ribbon_state"] == -2) & dir_dn)
    )
    d["g_qr_trending"] = g(d["qr_market_regime"] == 1)
    d["g_qr_high_health"] = g(d["qr_market_health"] > 70)
    d["g_qr_high_conf"] = g(d["qr_signal_confidence"] > 4)
    d["g_qr_top_conf"] = g(d["qr_signal_confidence"] > 6)
    d["g_qr_volume_strong"] = g(d["qr_volume_ratio"] > 1.3)
    return d


def overlay_qr_to_joined(joined: pd.DataFrame, qr_panel: pd.DataFrame, tf_label: str) -> pd.DataFrame:
    joined = joined.copy()
    joined["_lookup_us"] = joined["fire_us"].astype("int64") - 1
    qr_cols = ["ribbon_state", "market_regime", "market_health",
               "signal_confidence", "volume_ratio", "momentum_consistency"]
    parts = []
    for asset in ("BTC", "ETH", "SOL"):
        j_a = joined[joined.asset == asset].sort_values("_lookup_us").reset_index(drop=True)
        q_a = qr_panel[qr_panel.asset == asset].sort_values("bar_close_us").reset_index(drop=True)
        q_ren = q_a.rename(columns={c: f"qr_{c}" for c in qr_cols})
        q_ren = q_ren[["bar_close_us"] + [f"qr_{c}" for c in qr_cols]]
        merged = pd.merge_asof(
            j_a, q_ren,
            left_on="_lookup_us", right_on="bar_close_us",
            direction="backward",
            tolerance=20 * 60 * 1_000_000,
        )
        parts.append(merged)
    out = pd.concat(parts, ignore_index=True)
    out = out.drop(columns=["_lookup_us"])
    out = add_qr_gates(out)
    return out


def offset_bin(off: int, tf: str) -> str:
    if tf in ("s15", "s6", "5m"):
        if off <= 90: return "30-90"
        if off <= 150: return "60-150"
        if off <= 210: return "120-210"
        return "180-270"
    else:  # 15m
        if off <= 240: return "60-240"
        if off <= 480: return "240-480"
        if off <= 720: return "480-720"
        return "720-840"


def apply_gate_stack(df: pd.DataFrame, stack_str: str) -> pd.DataFrame:
    gates = stack_str.split("&")
    mask = pd.Series([True] * len(df), index=df.index)
    for g in gates:
        if g not in df.columns:
            return df.iloc[0:0]
        mask &= (df[g] == 1)
    return df[mask].copy()


def base_label(tf):
    return tf  # keep s15/s6/v15m as-is for offset_bin lookups


def normalize_offset_bin_filter(df: pd.DataFrame, tf_label: str, offset_bin_str: str) -> pd.DataFrame:
    """offset_bin string like '60-150' — return rows whose fire_offset_s
    matches this bin label (using offset_bin())."""
    if "fire_offset_s" not in df.columns:
        return df
    fam = "5m" if tf_label in ("s15", "s6") else "15m"
    df = df.copy()
    df["_ofb"] = df["fire_offset_s"].astype(int).apply(lambda o: offset_bin(o, fam))
    return df[df["_ofb"] == offset_bin_str].drop(columns=["_ofb"])


def main():
    t0 = time.time()
    print("[1] loading panels + top sleeves...")
    qr5 = pd.read_parquet(QR5)
    qr15 = pd.read_parquet(QR15)
    top = pd.read_csv(TOP)
    # Top sleeves often have duplicates — keep top 12 by sum_pnl across tfs.
    top = top.sort_values("sum_pnl", ascending=False).drop_duplicates(
        subset=["asset", "tf", "offset_bin", "gate_stack"]
    )
    top = top.head(30).reset_index(drop=True)
    print(f"  top sleeves picked (top 30): {len(top)}")
    print(top[["asset", "tf", "offset_bin", "gate_stack", "n", "WR", "sum_pnl", "dpt"]].head(15).to_string(index=False))

    print("\n[2] loading joined + overlaying QR...")
    s15 = pd.read_parquet(S15)
    s6 = pd.read_parquet(S6)
    v15m = pd.read_parquet(V15M)
    print(f"  s15: {s15.shape}  s6: {s6.shape}  v15m: {v15m.shape}")
    s15q = overlay_qr_to_joined(s15, qr5, "s15")
    s6q = overlay_qr_to_joined(s6, qr5, "s6")
    v15mq = overlay_qr_to_joined(v15m, qr15, "v15m")
    print(f"  s15q: {s15q.shape}  s6q: {s6q.shape}  v15mq: {v15mq.shape}")
    sources = {"s15_5m": s15q, "s6_5m": s6q, "v15m": v15mq}

    print("\n[3] sleeve+QR overlay sweep...")
    rows = []
    for idx, sleeve in top.iterrows():
        tf = str(sleeve["tf"])
        asset = str(sleeve["asset"])
        offset_bin_str = str(sleeve["offset_bin"])
        stack = str(sleeve["gate_stack"])
        if tf not in sources:
            continue
        df_all = sources[tf]
        sub = df_all[df_all.asset == asset]
        sub = normalize_offset_bin_filter(sub, tf.split("_")[0], offset_bin_str)
        # apply baseline gate stack
        base = apply_gate_stack(sub, stack)
        n_base = len(base)
        if n_base == 0:
            continue
        wr_base = base["won"].mean()
        sum_base = base["pnl_legacy_usd"].sum()
        dpt_base = base["pnl_legacy_usd"].mean()
        # baseline row
        rows.append({
            "rank": idx + 1, "asset": asset, "tf": tf, "offset_bin": offset_bin_str,
            "base_stack": stack, "added_gate": "(none/baseline)",
            "n": n_base, "WR": wr_base, "dpt": dpt_base, "sum_pnl": sum_base,
            "delta_n": 0, "delta_WR": 0.0, "delta_dpt": 0.0, "delta_sum_pnl": 0.0,
        })
        for g in QR_GATES:
            base_g = base[base[g] == 1]
            n_g = len(base_g)
            if n_g == 0:
                continue
            wr_g = base_g["won"].mean()
            sum_g = base_g["pnl_legacy_usd"].sum()
            dpt_g = base_g["pnl_legacy_usd"].mean()
            rows.append({
                "rank": idx + 1, "asset": asset, "tf": tf, "offset_bin": offset_bin_str,
                "base_stack": stack, "added_gate": g,
                "n": n_g, "WR": wr_g, "dpt": dpt_g, "sum_pnl": sum_g,
                "delta_n": n_g - n_base, "delta_WR": wr_g - wr_base,
                "delta_dpt": dpt_g - dpt_base, "delta_sum_pnl": sum_g - sum_base,
            })

    out = pd.DataFrame(rows)
    out.to_csv(OUT_FULL, index=False)
    # Top lift per sleeve
    overlays = out[out.added_gate != "(none/baseline)"].copy()
    overlays["lift_dpt_pct"] = overlays["delta_dpt"] / overlays["dpt"].replace(0, np.nan)
    top_lift = overlays.sort_values("delta_dpt", ascending=False).head(40)
    top_lift.to_csv(OUT_TOP, index=False)

    print(f"\n[4] wrote {OUT_FULL.name} ({len(out)} rows)")
    print(f"      wrote {OUT_TOP.name}  ({len(top_lift)} top-lift rows)")
    print("\nTop 25 gate overlays by delta_dpt:")
    cols = ["rank","asset","tf","offset_bin","added_gate","n","WR","dpt","delta_n","delta_WR","delta_dpt","delta_sum_pnl"]
    print(top_lift[cols].head(25).to_string(index=False))
    print(f"\nDONE in {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
