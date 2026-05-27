"""TASK 5 — confidence-bucket WR analysis.

For each top hybrid sleeve, segment its fires into confidence buckets and
compute WR + $/tr per bucket. Tests whether higher QR confidence == higher
WR (monotonic).

Buckets: [0,2), [2,4), [4,6), [6,8]

Outputs:
  data/v4/canonical/_results/qr_confidence_buckets.csv
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

OUT = RES / "qr_confidence_buckets.csv"


def overlay_qr(joined: pd.DataFrame, qr_panel: pd.DataFrame) -> pd.DataFrame:
    joined = joined.copy()
    joined["_lookup_us"] = joined["fire_us"].astype("int64") - 1
    qr_cols = ["ribbon_state", "market_regime", "market_health",
               "signal_confidence", "volume_ratio"]
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
    return out.drop(columns=["_lookup_us"])


def offset_bin(off: int, tf: str) -> str:
    if tf in ("s15", "s6", "5m"):
        if off <= 90: return "30-90"
        if off <= 150: return "60-150"
        if off <= 210: return "120-210"
        return "180-270"
    else:
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


def normalize_offset_bin_filter(df: pd.DataFrame, tf_label: str, offset_bin_str: str) -> pd.DataFrame:
    if "fire_offset_s" not in df.columns:
        return df
    fam = "5m" if tf_label in ("s15", "s6") else "15m"
    df = df.copy()
    df["_ofb"] = df["fire_offset_s"].astype(int).apply(lambda o: offset_bin(o, fam))
    return df[df["_ofb"] == offset_bin_str].drop(columns=["_ofb"])


def main():
    t0 = time.time()
    print("[1] loading panels + joined...")
    qr5 = pd.read_parquet(QR5)
    qr15 = pd.read_parquet(QR15)
    top = pd.read_csv(TOP)
    top = top.sort_values("sum_pnl", ascending=False).drop_duplicates(
        subset=["asset", "tf", "offset_bin", "gate_stack"]
    ).head(15).reset_index(drop=True)

    s15 = pd.read_parquet(S15)
    s6 = pd.read_parquet(S6)
    v15m = pd.read_parquet(V15M)
    s15q = overlay_qr(s15, qr5)
    s6q = overlay_qr(s6, qr5)
    v15mq = overlay_qr(v15m, qr15)
    sources = {"s15_5m": s15q, "s6_5m": s6q, "v15m": v15mq}

    bins = [(0, 2), (2, 4), (4, 6), (6, 8.01)]
    rows = []
    for idx, sleeve in top.iterrows():
        tf = str(sleeve["tf"]); asset = str(sleeve["asset"])
        offset_bin_str = str(sleeve["offset_bin"]); stack = str(sleeve["gate_stack"])
        if tf not in sources:
            continue
        sub = sources[tf]
        sub = sub[sub.asset == asset]
        sub = normalize_offset_bin_filter(sub, tf.split("_")[0], offset_bin_str)
        base = apply_gate_stack(sub, stack)
        if len(base) == 0:
            continue
        for lo, hi in bins:
            bk = base[(base["qr_signal_confidence"] >= lo) & (base["qr_signal_confidence"] < hi)]
            n = len(bk)
            if n == 0:
                wr, dpt, smp = np.nan, np.nan, 0.0
            else:
                wr = bk["won"].mean()
                dpt = bk["pnl_legacy_usd"].mean()
                smp = bk["pnl_legacy_usd"].sum()
            rows.append({
                "rank": idx + 1, "asset": asset, "tf": tf, "offset_bin": offset_bin_str,
                "stack": stack[:60] + ("..." if len(stack) > 60 else ""),
                "conf_bin": f"[{lo},{hi if hi<8 else 8}]",
                "n": n, "WR": wr, "dpt": dpt, "sum_pnl": smp,
            })

    out = pd.DataFrame(rows)
    out.to_csv(OUT, index=False)
    print(f"\n[2] wrote {OUT.name} ({len(out)} rows)")

    print("\nConfidence-bucket WR table (top 10 sleeves):")
    # Pivot for readability: WR by conf bin per sleeve
    piv = out.pivot_table(
        index=["rank", "asset", "tf", "offset_bin"], columns="conf_bin",
        values=["n", "WR", "dpt"], aggfunc="first",
    )
    print(piv.head(15).to_string())

    # Monotonicity test: does WR rise across [0,2)→[6,8]?
    print("\nMonotonicity test (top 12 sleeves):")
    for rank in sorted(out["rank"].unique())[:12]:
        sb = out[out["rank"] == rank].sort_values("conf_bin")
        wrs = sb["WR"].dropna().tolist()
        ns = sb["n"].tolist()
        mono = all(wrs[i] <= wrs[i+1] + 0.01 for i in range(len(wrs)-1)) if len(wrs) >= 3 else False
        asset = sb.iloc[0]["asset"]; tf = sb.iloc[0]["tf"]; ofb = sb.iloc[0]["offset_bin"]
        print(f"  rank{rank} {asset} {tf} {ofb}: WR by bin = {[round(x,3) if x==x else None for x in wrs]}  n={ns}  monotonic={mono}")

    print(f"\nDONE in {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
