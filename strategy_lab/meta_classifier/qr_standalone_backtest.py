"""TASK 3 — QR standalone signal test on the existing fire universes.

We build "synthetic" fires from QR rules at every (slug, offset) combination
inside hybrid_fire_universe_{5m,15m}.parquet, fill via baked up_vwap/dn_vwap
(LegacyConfig fee model — 2% on profit only on the winning leg), then
report per (asset, tf, offset_bin, rule): n, WR, $/tr, sum_pnl.

Rules:
  A — high-conviction trend: bet UP when (state >= +1 AND regime=='trending'
      AND health > 70 AND confidence > 4); mirror DOWN.
  B — strong stack only: bet WITH qr_state when |state|==2.
  C — bull/volume: bet UP when (state == +1 AND volume_ratio > 1.3); mirror.

Outputs:
  data/v4/canonical/_results/qr_standalone_results.csv
  data/v4/canonical/_results/qr_standalone_per_fire.parquet
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
FU5 = RES / "hybrid_fire_universe_5m.parquet"
FU15 = RES / "hybrid_fire_universe_15m.parquet"
OUT_CSV = RES / "qr_standalone_results.csv"
OUT_PT = RES / "qr_standalone_per_fire.parquet"

LEGACY_FEE = 0.02  # 2% on profit (winning leg only)


def legacy_pnl(entry_price: pd.Series, won: pd.Series, notional_usd: float = 25.0) -> pd.Series:
    """Legacy 2%-on-profit-only fee model.
    win:  pnl = qty * (1 - p) * (1 - 0.02)   where qty = notional / p
    lose: pnl = -qty * p = -notional
    """
    qty = notional_usd / entry_price.replace(0, np.nan)
    pnl_win = qty * (1.0 - entry_price) * (1.0 - LEGACY_FEE)
    pnl_lose = -qty * entry_price  # = -notional
    return np.where(won, pnl_win, pnl_lose)


def offset_bin(off: int, tf: str) -> str:
    if tf == "5m":
        if off <= 90:
            return "30-90"
        if off <= 150:
            return "60-150"
        if off <= 210:
            return "120-210"
        return "180-270"
    else:  # 15m
        if off <= 240:
            return "60-240"
        if off <= 480:
            return "240-480"
        if off <= 720:
            return "480-720"
        return "720-840"


def apply_qr_rules(df: pd.DataFrame) -> pd.DataFrame:
    """For every row in the augmented universe, emit rule-fires.

    Each row contributes 0..N rule entries.  Each entry is one bet candidate
    with direction + rule_id. We collect all candidates into a flat per-fire
    DataFrame, score pnl using up_vwap/dn_vwap from the row.
    """
    out_rows = []
    df = df.copy()
    df["won_up"] = (df["outcome"] == "Up").astype(np.int8)
    df["won_dn"] = (df["outcome"] == "Down").astype(np.int8)
    # rule A
    a_up = (df["qr_ribbon_state"] >= 1) & (df["qr_market_regime"] == 1) & \
           (df["qr_market_health"] > 70) & (df["qr_signal_confidence"] > 4)
    a_dn = (df["qr_ribbon_state"] <= -1) & (df["qr_market_regime"] == 1) & \
           (df["qr_market_health"] > 70) & (df["qr_signal_confidence"] > 4)
    df["rule_A_up"] = a_up.fillna(False)
    df["rule_A_dn"] = a_dn.fillna(False)
    # rule B
    b_up = df["qr_ribbon_state"] == 2
    b_dn = df["qr_ribbon_state"] == -2
    df["rule_B_up"] = b_up.fillna(False)
    df["rule_B_dn"] = b_dn.fillna(False)
    # rule C
    c_up = (df["qr_ribbon_state"] == 1) & (df["qr_volume_ratio"] > 1.3)
    c_dn = (df["qr_ribbon_state"] == -1) & (df["qr_volume_ratio"] > 1.3)
    df["rule_C_up"] = c_up.fillna(False)
    df["rule_C_dn"] = c_dn.fillna(False)

    rules_dirs = [
        ("A", "up"), ("A", "dn"),
        ("B", "up"), ("B", "dn"),
        ("C", "up"), ("C", "dn"),
    ]
    for rule, dr in rules_dirs:
        mask = df[f"rule_{rule}_{dr}"]
        if dr == "up":
            sub = df[mask & df["up_fill_ok"]].copy()
            sub["direction"] = "UP"
            sub["entry_vwap"] = sub["up_vwap"]
            sub["won"] = sub["won_up"].astype(bool)
        else:
            sub = df[mask & df["dn_fill_ok"]].copy()
            sub["direction"] = "DOWN"
            sub["entry_vwap"] = sub["dn_vwap"]
            sub["won"] = sub["won_dn"].astype(bool)
        if len(sub) == 0:
            continue
        sub["rule"] = rule
        sub["pnl_legacy_usd"] = legacy_pnl(sub["entry_vwap"], sub["won"])
        out_rows.append(sub)
    if not out_rows:
        return pd.DataFrame()
    out = pd.concat(out_rows, ignore_index=True)
    return out


def overlay_qr_panel(uni: pd.DataFrame, qr_panel: pd.DataFrame, tf_s: int) -> pd.DataFrame:
    """Causal asof merge of qr_panel onto fire universe rows."""
    uni = uni.copy()
    uni["_lookup_us"] = uni["fire_us"].astype("int64") - 1
    parts = []
    qr_cols = [
        "bull_align", "ribbon_state", "ribbon_aligned", "market_regime",
        "market_health", "signal_confidence", "volume_ratio",
        "momentum_consistency",
    ]
    for asset in ("BTC", "ETH", "SOL"):
        u_a = uni[uni.asset == asset].sort_values("_lookup_us").reset_index(drop=True)
        q_a = qr_panel[qr_panel.asset == asset].sort_values("bar_close_us").reset_index(drop=True)
        q_a = q_a.rename(columns={c: f"qr_{c}" for c in qr_cols})
        q_a = q_a[["bar_close_us"] + [f"qr_{c}" for c in qr_cols]]
        merged = pd.merge_asof(
            u_a, q_a,
            left_on="_lookup_us", right_on="bar_close_us",
            direction="backward",
            tolerance=20 * 60 * 1_000_000,
        )
        parts.append(merged)
    out = pd.concat(parts, ignore_index=True)
    out = out.drop(columns=["_lookup_us"])
    return out


def run_one(uni_path: Path, qr_path: Path, tf_label: str, tf_s: int) -> pd.DataFrame:
    print(f"\n[{tf_label}] loading universe + qr panel...")
    uni = pd.read_parquet(uni_path)
    qr = pd.read_parquet(qr_path)
    print(f"  universe rows: {len(uni):,}  qr rows: {len(qr):,}")
    print(f"  overlaying qr...")
    aug = overlay_qr_panel(uni, qr, tf_s)
    print(f"  rule-fire generation...")
    fires = apply_qr_rules(aug)
    if len(fires) == 0:
        return pd.DataFrame()
    fires["tf"] = tf_label
    fires["offset_bin"] = fires["fire_offset_s"].apply(lambda o: offset_bin(int(o), tf_label))
    print(f"  total rule-fires: {len(fires):,}")
    print(f"  per-rule:")
    for r in ("A", "B", "C"):
        sub = fires[fires.rule == r]
        if len(sub) == 0:
            continue
        wr = sub.won.mean()
        dpt = sub.pnl_legacy_usd.mean()
        n = len(sub)
        print(f"    {r}: n={n:6d}  WR={wr:.3f}  $/tr={dpt:+.3f}  sum_pnl={sub.pnl_legacy_usd.sum():+.0f}")
    return fires


def summarize(fires: pd.DataFrame) -> pd.DataFrame:
    rows = []
    grp = fires.groupby(["asset", "tf", "offset_bin", "rule"])
    for (asset, tf, offb, rule), sub in grp:
        n = len(sub)
        wr = sub.won.mean()
        dpt = sub.pnl_legacy_usd.mean()
        sum_pnl = sub.pnl_legacy_usd.sum()
        rows.append({
            "asset": asset, "tf": tf, "offset_bin": offb, "rule": rule,
            "n": n, "WR": wr, "dpt": dpt, "sum_pnl": sum_pnl,
        })
    return pd.DataFrame(rows).sort_values("sum_pnl", ascending=False).reset_index(drop=True)


def main():
    t0 = time.time()
    parts = []
    p5 = run_one(FU5, QR5, "5m", 300)
    if len(p5):
        parts.append(p5)
    p15 = run_one(FU15, QR15, "15m", 900)
    if len(p15):
        parts.append(p15)
    fires = pd.concat(parts, ignore_index=True)
    print(f"\n[total fires across both tfs and 3 rules]: {len(fires):,}")
    summary = summarize(fires)
    print("\nTop 30 cells by sum_pnl:")
    print(summary.head(30).to_string(index=False))

    summary.to_csv(OUT_CSV, index=False)
    fires.to_parquet(OUT_PT, index=False, compression="zstd")
    print(f"\nwrote {OUT_CSV.name} ({len(summary)} cells)")
    print(f"wrote {OUT_PT.name} ({len(fires):,} rows)")
    print(f"\nDONE in {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
