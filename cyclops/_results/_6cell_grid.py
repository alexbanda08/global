"""6-cell grid: (BTC, ETH, SOL) × (5m, 15m), S7 + X1, REAL fees, full gates.

Reads each per-asset/per-tf S7 CSV, applies real Polymarket fees, then runs
G1/G3/G4 validation. Builds a comprehensive table.
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

FEE_RATE = 0.07
SCALE = 1.0 / 25.0


def real_pmxt_pnl(shares, vwap, won):
    fee = FEE_RATE * vwap * (1.0 - vwap)
    return np.where(won, shares*(1-vwap) - shares*fee, -shares*vwap - shares*fee)


def sleeve_slugs(asset_tf: str) -> set:
    ev = pd.read_parquet(Path(CANON) / "trading_events_30d.parquet")
    ev = ev[ev.kind == "poly_updown_resolution"]
    sub = ev[ev.sleeve_id.str.contains(asset_tf, na=False)]
    d = sub["data"].apply(json.loads)
    df = pd.json_normalize(d)
    res = pd.read_parquet(Path(CANON) / "resolutions.parquet")
    cid2slug = dict(zip(res.market_id, res.slug))
    return set(df["condition_id"].map(cid2slug).dropna().unique())


def stats(label, sub):
    if sub.empty:
        return {"label": label, "n": 0}
    sub = sub.copy()
    sub["pnl_real"] = real_pmxt_pnl(
        sub.shares.values.astype(float),
        sub.vwap_entry.values.astype(float),
        sub.won.values.astype(bool),
    )
    sub["pnl_1"] = sub.pnl_real * SCALE
    n = len(sub)
    wins = int(sub.won.sum())
    wr = float(sub.won.mean())
    vw = float(sub.vwap_entry.mean())
    bk_real = vw + FEE_RATE * vw * (1 - vw)
    edge = (wr - bk_real) * 100
    mean_1 = float(sub.pnl_1.mean())
    sum_1 = float(sub.pnl_1.sum())

    # Drawdown
    idx = np.argsort(sub.ws_s.values)
    cum = np.cumsum(sub.pnl_1.values[idx])
    peak = np.maximum.accumulate(cum)
    max_dd = float((cum - peak).min())

    # Gates on REAL pnl
    g3_p = float("nan"); g4_lo = float("nan")
    if n >= 10:
        gv = sub[["direction","outcome_truth","shares","stake_usd","won","ws_s","vwap_entry"]].copy()
        gv["pnl_usd"] = sub["pnl_real"].values
        perm = permutation_test(gv, n_permutations=3000, seed=42)
        g3_p = perm["p_value"]
        boot = bootstrap_mean_ci(gv, n_boot=10000, seed=42)
        g4_lo = boot["ci_lower"] * SCALE

    return {
        "label": label, "n": n, "wins": wins, "losses": n - wins, "wr": wr,
        "mean_vwap": vw, "breakeven_real": bk_real, "edge_real_pp": edge,
        "mean_1": mean_1, "sum_1": sum_1,
        "sum_25": float(sub.pnl_real.sum()),
        "max_dd_1": max_dd,
        "g1": "PASS" if mean_1 > 0 else "FAIL",
        "g3": "PASS" if g3_p < 0.05 else ("FAIL" if not np.isnan(g3_p) else "—"),
        "g4": "PASS" if g4_lo > 0 else ("FAIL" if not np.isnan(g4_lo) else "—"),
        "g3_p": g3_p, "g4_lo": g4_lo,
    }


def analyze_cell(asset, tf, csv_path):
    p = Path(csv_path)
    if not p.exists():
        return None
    df = pd.read_csv(p)
    fired = df[df.fired == True]
    if fired.empty:
        return None
    s7 = stats(f"{asset}_{tf}_S7", fired)
    slugs = sleeve_slugs(f"{asset.lower()}_{tf}")
    x1 = stats(f"{asset}_{tf}_X1", fired[fired.slug.isin(slugs)])
    return {"asset": asset, "tf": tf, "s7": s7, "x1": x1,
            "n_sleeve_slugs": len(slugs)}


def main():
    cells = [
        ("BTC", "5m",  "cyclops/_results/p5_full_depth_p3.csv"),
        ("BTC", "15m", "cyclops/_results/p5_btc_15m_p3.csv"),
        ("ETH", "5m",  "cyclops/_results/p5_eth_p3.csv"),
        ("ETH", "15m", "cyclops/_results/p5_eth_15m_p3.csv"),
        ("SOL", "5m",  "cyclops/_results/p5_sol_p3.csv"),
        ("SOL", "15m", "cyclops/_results/p5_sol_15m_p3.csv"),
    ]
    results = []
    for a, t, c in cells:
        r = analyze_cell(a, t, c)
        if r:
            results.append(r)
        else:
            print(f"  MISSING {a} {t}")

    print()
    print("=" * 150)
    print("6-CELL GRID — (BTC, ETH, SOL) × (5m, 15m), REAL Polymarket fees, $1 stake")
    print("=" * 150)
    print(f"  {'Asset':>5s} {'TF':>4s} {'Variant':>5s}  {'n':>5s} {'W':>4s} {'L':>4s}  "
          f"{'WR%':>5s} {'BrkReal%':>8s} {'Edge':>9s}  "
          f"{'mean$1':>9s} {'sum$1':>9s} {'dd$1':>9s}  "
          f"{'G1':>5s} {'G3 p':>6s} {'G4 lo':>9s} {'G4':>5s}")
    print("-" * 150)
    for r in results:
        for variant in ("s7", "x1"):
            s = r[variant]
            if s.get("n", 0) == 0:
                continue
            g3p = f"{s['g3_p']:.3f}" if not np.isnan(s["g3_p"]) else "—"
            g4lo = f"${s['g4_lo']:+.4f}" if not np.isnan(s["g4_lo"]) else "—"
            print(f"  {r['asset']:>5s} {r['tf']:>4s} {variant.upper():>5s}  "
                  f"{s['n']:5d} {s['wins']:4d} {s['losses']:4d}  "
                  f"{s['wr']*100:5.1f} {s['breakeven_real']*100:7.2f}%  "
                  f"{s['edge_real_pp']:+5.2f}pp  "
                  f"${s['mean_1']:+.4f} ${s['sum_1']:+.2f} ${s['max_dd_1']:.2f}  "
                  f"{s['g1']:>5s} {g3p:>6s} {g4lo:>9s} {s['g4']:>5s}")
    print()
    print("=" * 80)
    print("Cells passing G1+G3+G4 (real fees, full validation):")
    print("=" * 80)
    any_pass = False
    for r in results:
        for variant in ("s7", "x1"):
            s = r[variant]
            if s.get("n", 0) == 0:
                continue
            if s["g1"] == "PASS" and s["g3"] == "PASS" and s["g4"] == "PASS":
                any_pass = True
                print(f"  {r['asset']} {r['tf']} {variant.upper()}: "
                      f"n={s['n']} WR={s['wr']*100:.2f}% edge={s['edge_real_pp']:+.2f}pp "
                      f"total=${s['sum_1']:+.2f}  G3 p={s['g3_p']:.3f}  G4 lo=${s['g4_lo']:+.4f}")
    if not any_pass:
        print("  (none)")

    print()
    print("=" * 80)
    print("Cells passing G1 only (positive PnL with real fees):")
    print("=" * 80)
    for r in results:
        for variant in ("s7", "x1"):
            s = r[variant]
            if s.get("n", 0) == 0 or s["g1"] != "PASS":
                continue
            flags = []
            if s["g3"] == "PASS": flags.append("G3")
            if s["g4"] == "PASS": flags.append("G4")
            print(f"  {r['asset']} {r['tf']} {variant.upper()}: "
                  f"n={s['n']:4d}  WR={s['wr']*100:5.2f}%  edge={s['edge_real_pp']:+5.2f}pp  "
                  f"total=${s['sum_1']:+.2f}  ${s['sum_25']:+.2f}@$25  "
                  f"gates: G1{('+' + '+'.join(flags)) if flags else ''}")


if __name__ == "__main__":
    main()
