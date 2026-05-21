"""Final master strategy table v2 — adds VPS3-sleeve composite strategies.

Reports all strategies tested in this project at $1 stake.
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path
import sys

sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global")
from load import CANON
from cyclops.validate.permutation import permutation_test
from cyclops.validate.bootstrap import bootstrap_mean_ci
from cyclops.validate.walkforward import walkforward_test

SCALE = 1.0 / 25.0


def load_sleeve_slug_set():
    ev = pd.read_parquet(Path(CANON) / "trading_events_30d.parquet")
    ev = ev[ev.kind == "poly_updown_resolution"]
    btc5 = ev[ev.sleeve_id.str.contains("btc_5m", na=False)]
    d = btc5["data"].apply(json.loads)
    df = pd.json_normalize(d)
    df["sleeve_id"] = btc5["sleeve_id"].values
    res = pd.read_parquet(Path(CANON) / "resolutions.parquet")
    cid2slug = dict(zip(res.market_id, res.slug))
    df["slug"] = df["condition_id"].map(cid2slug)
    out = {
        "all": set(df.slug.dropna().unique()),
        "momo_v2": set(df[df.sleeve_id.str.contains("momo_v2", na=False)].slug.dropna().unique()),
        "vol_inv": set(df[df.sleeve_id == "poly_updown_btc_5m_volume_INV_NIGHT"].slug.dropna().unique()),
        "sniper":  set(df[df.sleeve_id == "poly_updown_btc_5m_sniper"].slug.dropna().unique()),
    }
    return out


def stats_for_df(df, label, description):
    if df.empty:
        return None
    n = len(df)
    wins = int(df["won"].sum())
    losses = n - wins
    wr = float(df["won"].mean())
    if "pnl_usd" in df.columns:
        pnl_1 = df["pnl_usd"] * SCALE
    elif "pnl_1" in df.columns:
        pnl_1 = df["pnl_1"]
    else:
        return None
    mean_pnl_1 = float(pnl_1.mean())
    sum_pnl_1 = float(pnl_1.sum())
    mean_vwap = float(df["vwap_entry"].mean()) if "vwap_entry" in df.columns else float("nan")
    edge_pp = (wr - mean_vwap) * 100 if not np.isnan(mean_vwap) else float("nan")

    ws_min = int(df["ws_s"].min())
    ws_max = int(df["ws_s"].max())
    days = (ws_max - ws_min) / 86400

    # Drawdown
    pnl_sorted = pnl_1.values[np.argsort(df["ws_s"].values)]
    cum = np.cumsum(pnl_sorted)
    peak = np.maximum.accumulate(cum)
    max_dd = float((cum - peak).min())

    # Gates
    g3_p = float("nan")
    g4_lo = float("nan")
    g2_n = 0
    g2_pos = 0
    if n >= 10 and "pnl_usd" in df.columns:
        gates_df = df[["direction", "outcome_truth", "shares", "stake_usd",
                       "pnl_usd", "won", "ws_s", "vwap_entry"]].copy() \
            if "outcome_truth" in df.columns else df.copy()
        perm = permutation_test(gates_df, n_permutations=3000, seed=42)
        g3_p = perm["p_value"]
        boot = bootstrap_mean_ci(gates_df, n_boot=10000, seed=42)
        g4_lo = boot["ci_lower"] * SCALE
        wf = walkforward_test(gates_df, train_days=5, test_days=2)
        g2_n = wf["n_windows"]
        g2_pos = wf["n_positive"]
    g1 = "PASS" if mean_pnl_1 > 0 else "FAIL"
    g3 = "PASS" if g3_p < 0.05 else ("FAIL" if not np.isnan(g3_p) else "—")
    g4 = "PASS" if g4_lo > 0 else ("FAIL" if not np.isnan(g4_lo) else "—")
    g2 = (
        "PASS" if g2_n >= 4 and g2_pos / g2_n >= 6/8
        else "FAIL" if g2_n >= 4 else "—"
    )

    return {
        "label": label, "description": description,
        "n": n, "wins": wins, "losses": losses,
        "wr": wr, "mean_vwap": mean_vwap, "edge_pp": edge_pp,
        "mean_pnl_1": mean_pnl_1, "sum_pnl_1": sum_pnl_1,
        "max_dd_1": max_dd, "days": days,
        "g1": g1, "g2": g2, "g3": g3, "g4": g4,
        "g3_p": g3_p, "g4_lo_1": g4_lo,
        "g2_n": g2_n, "g2_pos": g2_pos,
    }


def main():
    # Load all existing per-trade CSVs
    configs = [
        ("S1_P2_raw",
         "cyclops/_results/p2_full_21d.csv",
         "raw 3-axis, degraded momentum (tier1 snapshot)"),
        ("S2_P3_baseline",
         "cyclops/_results/p3_vwap30_momabstain.csv",
         "+ vwap>=0.30 + require_momentum_abstain"),
        ("S3_P3+blowoff",
         "cyclops/_results/p3_plus_blowoff.csv",
         "S2 + blowoff_guard"),
        ("S4_P3+hours",
         "cyclops/_results/p3_plus_hours.csv",
         "S2 + hours_guard 13-21 UTC + weekend off"),
        ("S5_P3_full_stack",
         "cyclops/_results/p3_full_stack.csv",
         "S2 + hours + blowoff + reentry"),
        ("S6_FD_raw",
         "cyclops/_results/p5_full_depth_raw.csv",
         "raw 3-axis with full-depth streaming OB + 24M trades"),
        ("S7_FD_P3",
         "cyclops/_results/p5_full_depth_p3.csv",
         "S2 with full-depth momentum"),
        ("S8_FD_full_stack",
         "cyclops/_results/p5_full_depth_fullstack.csv",
         "S5 with full-depth momentum + ob_guard"),
    ]
    rows = []
    for label, fp, desc in configs:
        p = Path(fp)
        if not p.exists():
            continue
        df = pd.read_csv(p)
        fired = df[df.fired == True].copy()
        if fired.empty:
            continue
        # Hot-fix: pnl_usd needed; outcome_truth needed for perm test
        s = stats_for_df(fired, label, desc)
        if s:
            rows.append(s)

    # Now add composite strategies on top of S7 (FD P3)
    s7_csv = pd.read_csv("cyclops/_results/p5_full_depth_p3.csv")
    s7_f = s7_csv[s7_csv.fired == True].copy()
    sleeve_sets = load_sleeve_slug_set()

    composites = [
        ("X1_S7+sleeve_active",
         s7_f[s7_f.slug.isin(sleeve_sets["all"])],
         "S7 + any VPS3 BTC 5m sleeve also fired on slug"),
        ("X2_S7+momo_v2",
         s7_f[s7_f.slug.isin(sleeve_sets["momo_v2"])],
         "S7 + any momo_v2 family sleeve fired"),
        ("X3_S7+vol_inv",
         s7_f[s7_f.slug.isin(sleeve_sets["vol_inv"])],
         "S7 + volume_INV_NIGHT sleeve fired"),
        ("X4_S7+any+vwap_0.4_0.7",
         s7_f[s7_f.slug.isin(sleeve_sets["all"])
              & (s7_f.vwap_entry >= 0.40) & (s7_f.vwap_entry <= 0.70)],
         "X1 restricted to vwap 0.40-0.70 (the sweet bucket)"),
    ]
    for label, sub, desc in composites:
        s = stats_for_df(sub, label, desc)
        if s:
            rows.append(s)

    # Print final master table
    print()
    print("=" * 130)
    print("MASTER STRATEGY TABLE v2 — All strategies tested at $1 stake")
    print("=" * 130)
    print(f"{'#':>3s}  {'Strategy':>26s}  {'n':>5s}  {'W':>4s}  {'L':>4s}  "
          f"{'WR%':>5s}  {'Brk%':>5s}  {'Edge':>7s}  {'mean$1':>9s}  "
          f"{'sum$1':>9s}  {'dd$1':>9s}  {'G1':>5s}  {'G2':>5s}  "
          f"{'G3 p':>6s}  {'G4 lo':>9s}  {'G4':>5s}")
    print("-" * 130)
    for r in rows:
        g3_p_str = f"{r['g3_p']:.3f}" if not np.isnan(r["g3_p"]) else "—"
        g4_lo_str = f"${r['g4_lo_1']:+.4f}" if not np.isnan(r["g4_lo_1"]) else "—"
        print(f"  {r['label']:>26s}  {r['n']:5d}  {r['wins']:4d}  {r['losses']:4d}  "
              f"{r['wr']*100:5.1f}  {r['mean_vwap']*100:5.1f}  {r['edge_pp']:+5.2f}pp  "
              f"${r['mean_pnl_1']:+.4f}  ${r['sum_pnl_1']:+.2f}  "
              f"${r['max_dd_1']:.2f}  {r['g1']:>5s}  {r['g2']:>5s}  "
              f"{g3_p_str:>6s}  {g4_lo_str:>9s}  {r['g4']:>5s}")
    print()

    # Highlight passing strategies
    print("=" * 80)
    print("Strategies passing G1 (mean PnL > 0):")
    print("=" * 80)
    for r in rows:
        if r["g1"] == "PASS":
            badges = []
            if r["g3"] == "PASS": badges.append("G3")
            if r["g4"] == "PASS": badges.append("G4")
            if r["g2"] == "PASS": badges.append("G2")
            print(f"  {r['label']:>26s}  n={r['n']:4d}  "
                  f"WR={r['wr']*100:5.2f}%  edge={r['edge_pp']:+5.2f}pp  "
                  f"$+{r['sum_pnl_1']:.2f} @ $1 stake  "
                  f"gates: {'+'.join(badges) if badges else 'G1 only'}")

    print()
    print("=" * 80)
    print("Strategies passing G1 AND G3 AND G4 (full validation):")
    print("=" * 80)
    full_pass = [r for r in rows if r["g1"] == "PASS" and r["g3"] == "PASS" and r["g4"] == "PASS"]
    if full_pass:
        for r in full_pass:
            print(f"  {r['label']:>26s}  n={r['n']:4d}  "
                  f"WR={r['wr']*100:5.2f}%  edge={r['edge_pp']:+5.2f}pp  "
                  f"$+{r['sum_pnl_1']:.2f} @ $1  "
                  f"G3 p={r['g3_p']:.3f}  G4_lo=${r['g4_lo_1']:+.4f}")
    else:
        print("  (none)")


if __name__ == "__main__":
    main()
