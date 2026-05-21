"""X1 strategy stats per asset (BTC / ETH / SOL).

X1 = Cyclops S7 (full-depth + P3 filters) AND any VPS3 same-asset 5m sleeve
also fired on that slug. Applies REAL Polymarket fees.

Reads per-asset S7 CSVs + VPS3 trading_events. Reports validation gates
(G1 / G3 / G4) for each asset.
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


def real_pmxt_pnl(shares, vwap, won, fee_rate=FEE_RATE):
    fee = fee_rate * vwap * (1.0 - vwap)
    win_pnl = shares * (1.0 - vwap) - shares * fee
    loss_pnl = -shares * vwap - shares * fee
    return np.where(won, win_pnl, loss_pnl)


def sleeve_slugs_for_asset(asset: str) -> set:
    """Slugs where any same-asset 5m VPS3 sleeve resolved a trade."""
    ev = pd.read_parquet(Path(CANON) / "trading_events_30d.parquet")
    ev = ev[ev.kind == "poly_updown_resolution"]
    needle = f"{asset.lower()}_5m"
    sub = ev[ev.sleeve_id.str.contains(needle, na=False)]
    d = sub["data"].apply(json.loads)
    df = pd.json_normalize(d)
    res = pd.read_parquet(Path(CANON) / "resolutions.parquet")
    cid2slug = dict(zip(res.market_id, res.slug))
    return set(df["condition_id"].map(cid2slug).dropna().unique())


def analyze(asset: str, csv_path: str) -> dict:
    p = Path(csv_path)
    if not p.exists():
        return {"asset": asset, "error": f"missing CSV {csv_path}"}

    df = pd.read_csv(p)
    fired = df[df.fired == True].copy()
    if fired.empty:
        return {"asset": asset, "error": "no fires"}

    # Apply REAL fees
    fired["pnl_real"] = real_pmxt_pnl(
        fired.shares.values.astype("float64"),
        fired.vwap_entry.values.astype("float64"),
        fired.won.values.astype(bool),
    )
    fired["pnl_real_1"] = fired["pnl_real"] * SCALE

    # X1 = sleeve-active filter
    sleeve_set = sleeve_slugs_for_asset(asset)
    x1 = fired[fired.slug.isin(sleeve_set)].copy()

    out = {"asset": asset}
    for label, sub in (("S7_baseline", fired), ("X1_sleeve_active", x1)):
        if sub.empty:
            out[label] = {"n": 0}
            continue
        n = len(sub)
        wins = int(sub.won.sum())
        losses = n - wins
        wr = float(sub.won.mean())
        mean_vwap = float(sub.vwap_entry.mean())
        breakeven_real = mean_vwap + FEE_RATE * mean_vwap * (1 - mean_vwap)
        mean_real_1 = float(sub.pnl_real_1.mean())
        sum_real_1 = float(sub.pnl_real_1.sum())
        sum_real_25 = float(sub.pnl_real.sum())

        # Drawdown on real PnL
        idx_sorted = np.argsort(sub.ws_s.values)
        cum = np.cumsum(sub.pnl_real_1.values[idx_sorted])
        peak = np.maximum.accumulate(cum)
        max_dd_1 = float((cum - peak).min())

        # Gates (use REAL PnL)
        g3_p, g4_lo_1 = float("nan"), float("nan")
        if n >= 10:
            gv = sub[["direction", "outcome_truth", "shares", "stake_usd",
                       "won", "ws_s", "vwap_entry"]].copy()
            gv["pnl_usd"] = sub["pnl_real"].values
            perm = permutation_test(gv, n_permutations=3000, seed=42)
            g3_p = perm["p_value"]
            boot = bootstrap_mean_ci(gv, n_boot=10000, seed=42)
            g4_lo_1 = boot["ci_lower"] * SCALE

        # Per direction
        by_dir = {}
        for d in ("Up", "Down"):
            sd = sub[sub.direction == d]
            if not sd.empty:
                by_dir[d] = {
                    "n": int(len(sd)),
                    "wr": float(sd.won.mean()),
                    "mean_real_1": float(sd.pnl_real_1.mean()),
                    "sum_real_1": float(sd.pnl_real_1.sum()),
                }

        out[label] = {
            "n": n, "wins": wins, "losses": losses, "wr": wr,
            "mean_vwap": mean_vwap, "breakeven_real": breakeven_real,
            "edge_real_pp": (wr - breakeven_real) * 100,
            "mean_real_1": mean_real_1,
            "sum_real_1": sum_real_1,
            "sum_real_25_actual": sum_real_25,
            "max_dd_real_1": max_dd_1,
            "g1": "PASS" if mean_real_1 > 0 else "FAIL",
            "g3": "PASS" if g3_p < 0.05 else ("FAIL" if not np.isnan(g3_p) else "—"),
            "g4": "PASS" if g4_lo_1 > 0 else ("FAIL" if not np.isnan(g4_lo_1) else "—"),
            "g3_p": g3_p,
            "g4_lo_1": g4_lo_1,
            "by_dir": by_dir,
        }
    return out


def fmt_pct(x):
    return f"{x*100:5.2f}%" if not np.isnan(x) else "  —  "


def main():
    runs = [
        ("BTC", "cyclops/_results/p5_full_depth_p3.csv"),
        ("ETH", "cyclops/_results/p5_eth_p3.csv"),
        ("SOL", "cyclops/_results/p5_sol_p3.csv"),
    ]

    results = []
    for asset, csv_path in runs:
        r = analyze(asset, csv_path)
        results.append(r)

    # Top-line table
    print()
    print("=" * 130)
    print("X1 strategy per-asset — REAL Polymarket fees, $1 stake")
    print("=" * 130)
    print(f"{'Asset':>6s}  {'Variant':>20s}  {'n':>5s}  {'W':>5s}  {'L':>5s}  "
          f"{'WR%':>5s}  {'Brk%real':>8s}  {'EdgeReal':>9s}  "
          f"{'mean$1':>9s}  {'sum$1':>9s}  {'dd$1':>9s}  "
          f"{'G1':>5s}  {'G3p':>6s}  {'G4 lo':>9s}  {'G4':>5s}")
    print("-" * 130)
    for r in results:
        if "error" in r:
            print(f"  {r['asset']:>4s}  {r['error']}")
            continue
        for var in ("S7_baseline", "X1_sleeve_active"):
            s = r.get(var, {})
            if s.get("n", 0) == 0:
                continue
            g3p = f"{s['g3_p']:.3f}" if not np.isnan(s.get("g3_p", float("nan"))) else "—"
            g4lo = f"${s['g4_lo_1']:+.4f}" if not np.isnan(s.get("g4_lo_1", float("nan"))) else "—"
            print(f"  {r['asset']:>4s}  {var:>20s}  {s['n']:5d}  {s['wins']:5d}  {s['losses']:5d}  "
                  f"{s['wr']*100:5.1f}  {s['breakeven_real']*100:7.2f}%  "
                  f"{s['edge_real_pp']:+5.2f}pp  "
                  f"${s['mean_real_1']:+.4f}  ${s['sum_real_1']:+.2f}  "
                  f"${s['max_dd_real_1']:.2f}  {s['g1']:>5s}  {g3p:>6s}  "
                  f"{g4lo:>9s}  {s['g4']:>5s}")
    print()

    # Per-direction detail
    print("=" * 80)
    print("Per-direction breakdown (X1, real fees)")
    print("=" * 80)
    for r in results:
        if "error" in r:
            continue
        x1 = r.get("X1_sleeve_active", {})
        if x1.get("n", 0) == 0:
            continue
        print(f"\n  {r['asset']}:")
        for d, ds in x1.get("by_dir", {}).items():
            print(f"    {d:5s}  n={ds['n']:3d}  WR={ds['wr']*100:5.2f}%  "
                  f"mean=${ds['mean_real_1']:+.4f}  sum=${ds['sum_real_1']:+.2f}")

    # Combined cross-asset X1
    print()
    print("=" * 80)
    print("Cross-asset X1 (BTC + ETH + SOL combined)")
    print("=" * 80)
    combined_n = 0
    combined_w = 0
    combined_sum_1 = 0.0
    for r in results:
        x1 = r.get("X1_sleeve_active", {})
        if x1.get("n", 0) > 0:
            combined_n += x1["n"]
            combined_w += x1["wins"]
            combined_sum_1 += x1["sum_real_1"]
    if combined_n > 0:
        print(f"  Total trades: {combined_n}  Wins: {combined_w}  Losses: {combined_n - combined_w}")
        print(f"  Combined WR: {combined_w/combined_n*100:.2f}%")
        print(f"  Combined PnL: ${combined_sum_1:+.2f} @ $1 stake "
              f"(${combined_sum_1*25:+.2f} @ $25 stake)")


if __name__ == "__main__":
    main()
