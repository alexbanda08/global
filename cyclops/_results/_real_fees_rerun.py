"""Recompute every strategy's PnL with the real Polymarket fee curve.

Formula (strategy_lab/fees.py):
    fee_per_share = 0.07 × p × (1 − p)           # crypto markets
    Won PnL  = shares × ((1 − vwap) − fee/share)
             = shares × (1 − vwap) × (1 − 0.07 × vwap)
    Lost PnL = shares × (−vwap − fee/share)
             = −shares × vwap × (1 + 0.07 × (1 − vwap))

We reuse the per-trade CSVs (which carry actual book-walked `shares`,
`vwap_entry`, `won`) — no backtest re-run needed. Validation gates are
re-run on the new PnL.

Differences from legacy:
  - Fee charged on EVERY fill (entry leg of both wins AND losses)
  - Price-dependent: peaks at p=0.50 (1.75%/share), zero at p=0 or p=1
  - Loss path now includes a fee (legacy charged 0% on losses)
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
STAKE_BACKTEST = 25.0
SCALE = 1.0 / STAKE_BACKTEST


def real_pmxt_pnl(shares: np.ndarray, vwap: np.ndarray,
                   won: np.ndarray, fee_rate: float = FEE_RATE) -> np.ndarray:
    """Vector PnL using real Polymarket fee curve."""
    fee = fee_rate * vwap * (1.0 - vwap)        # per-share
    win_pnl = shares * (1.0 - vwap) - shares * fee
    loss_pnl = -shares * vwap - shares * fee
    return np.where(won, win_pnl, loss_pnl)


def load_sleeve_slug_sets():
    ev = pd.read_parquet(Path(CANON) / "trading_events_30d.parquet")
    ev = ev[ev.kind == "poly_updown_resolution"]
    btc5 = ev[ev.sleeve_id.str.contains("btc_5m", na=False)]
    d = btc5["data"].apply(json.loads)
    df = pd.json_normalize(d)
    df["sleeve_id"] = btc5["sleeve_id"].values
    res = pd.read_parquet(Path(CANON) / "resolutions.parquet")
    cid2slug = dict(zip(res.market_id, res.slug))
    df["slug"] = df["condition_id"].map(cid2slug)
    return {
        "all": set(df.slug.dropna().unique()),
        "momo_v2": set(df[df.sleeve_id.str.contains("momo_v2", na=False)].slug.dropna().unique()),
        "vol_inv": set(df[df.sleeve_id == "poly_updown_btc_5m_volume_INV_NIGHT"].slug.dropna().unique()),
    }


def apply_real_fees(df: pd.DataFrame) -> pd.DataFrame:
    """Add `pnl_usd_real` column with real PMXT fee."""
    df = df.copy()
    fired_mask = df["fired"] == True
    if not fired_mask.any():
        df["pnl_usd_real"] = float("nan")
        return df
    sub = df[fired_mask]
    shares = sub["shares"].values.astype("float64")
    vwap = sub["vwap_entry"].values.astype("float64")
    won = sub["won"].values.astype(bool)
    df.loc[fired_mask, "pnl_usd_real"] = real_pmxt_pnl(shares, vwap, won)
    return df


def stats(df_fired: pd.DataFrame, label: str, description: str) -> dict:
    n = len(df_fired)
    if n == 0:
        return None
    wins = int(df_fired["won"].sum())
    losses = n - wins
    wr = float(df_fired["won"].mean())

    legacy_pnl_1 = (df_fired["pnl_usd"] * SCALE).values
    real_pnl_1 = (df_fired["pnl_usd_real"] * SCALE).values

    mean_vwap = float(df_fired["vwap_entry"].mean())
    breakeven_real = mean_vwap + FEE_RATE * mean_vwap * (1 - mean_vwap)

    # Run gates on REAL PnL
    g3_p, g4_lo = float("nan"), float("nan")
    if n >= 10:
        # Build a frame the validators expect
        gv = df_fired[["direction", "outcome_truth", "shares", "stake_usd",
                       "won", "ws_s", "vwap_entry"]].copy()
        gv["pnl_usd"] = df_fired["pnl_usd_real"].values   # IMPORTANT: real PnL
        perm = permutation_test(gv, n_permutations=3000, seed=42)
        g3_p = perm["p_value"]
        boot = bootstrap_mean_ci(gv, n_boot=10000, seed=42)
        g4_lo = boot["ci_lower"] * SCALE

    g1 = "PASS" if float(real_pnl_1.mean()) > 0 else "FAIL"
    g3 = "PASS" if g3_p < 0.05 else ("FAIL" if not np.isnan(g3_p) else "—")
    g4 = "PASS" if g4_lo > 0 else ("FAIL" if not np.isnan(g4_lo) else "—")

    # Drawdown on real PnL
    sorted_idx = np.argsort(df_fired["ws_s"].values)
    real_sorted = real_pnl_1[sorted_idx]
    cum = np.cumsum(real_sorted)
    peak = np.maximum.accumulate(cum)
    max_dd = float((cum - peak).min())

    return {
        "label": label, "description": description,
        "n": n, "wins": wins, "losses": losses, "wr": wr,
        "mean_vwap": mean_vwap, "breakeven_real": breakeven_real,
        "edge_legacy_pp": (wr - mean_vwap) * 100,
        "edge_real_pp": (wr - breakeven_real) * 100,
        "mean_legacy_1": float(legacy_pnl_1.mean()),
        "mean_real_1":   float(real_pnl_1.mean()),
        "sum_legacy_1":  float(legacy_pnl_1.sum()),
        "sum_real_1":    float(real_pnl_1.sum()),
        "real_minus_legacy_1": float(real_pnl_1.sum() - legacy_pnl_1.sum()),
        "max_dd_real_1": max_dd,
        "g1": g1, "g3": g3, "g4": g4,
        "g3_p": g3_p, "g4_lo_real_1": g4_lo,
    }


def main():
    configs = [
        ("S1_P2_raw",                "cyclops/_results/p2_full_21d.csv",
         "raw 3-axis, no filters"),
        ("S2_P3_baseline",           "cyclops/_results/p3_vwap30_momabstain.csv",
         "vwap≥0.30 + mom_abstain"),
        ("S3_P3+blowoff",            "cyclops/_results/p3_plus_blowoff.csv",
         "S2 + blowoff_guard"),
        ("S4_P3+hours",              "cyclops/_results/p3_plus_hours.csv",
         "S2 + hours_guard"),
        ("S5_P3_full_stack",         "cyclops/_results/p3_full_stack.csv",
         "S2 + hours + blowoff + reentry"),
        ("S6_FD_raw",                "cyclops/_results/p5_full_depth_raw.csv",
         "raw + full-depth momentum"),
        ("S7_FD_P3",                 "cyclops/_results/p5_full_depth_p3.csv",
         "S2 + full-depth momentum"),
        ("S8_FD_full_stack",         "cyclops/_results/p5_full_depth_fullstack.csv",
         "S5 + full-depth + ob_guard"),
    ]

    # Apply real fees + collect stats
    rows = []
    s7_with_real = None
    for label, fp, desc in configs:
        p = Path(fp)
        if not p.exists():
            continue
        df = pd.read_csv(p)
        df = apply_real_fees(df)
        fired = df[df.fired == True].copy()
        if fired.empty:
            continue
        s = stats(fired, label, desc)
        if s:
            rows.append(s)
        if label == "S7_FD_P3":
            s7_with_real = df

    # Composite strategies on top of S7
    sleeves = load_sleeve_slug_sets()
    s7_fired = s7_with_real[s7_with_real.fired == True].copy()

    composites = [
        ("X1_S7+sleeve_active",
         s7_fired[s7_fired.slug.isin(sleeves["all"])],
         "S7 + any VPS3 sleeve fired same slug"),
        ("X2_S7+momo_v2",
         s7_fired[s7_fired.slug.isin(sleeves["momo_v2"])],
         "S7 + momo_v2 family fired"),
        ("X3_S7+vol_inv",
         s7_fired[s7_fired.slug.isin(sleeves["vol_inv"])],
         "S7 + volume_INV_NIGHT fired"),
        ("X4_S7+any+vwap_0.4_0.7",
         s7_fired[s7_fired.slug.isin(sleeves["all"])
                   & (s7_fired.vwap_entry >= 0.40)
                   & (s7_fired.vwap_entry <= 0.70)],
         "X1 narrowed to vwap 0.40-0.70"),
    ]
    for label, sub, desc in composites:
        s = stats(sub, label, desc)
        if s:
            rows.append(s)

    # Print updated master table
    print()
    print("=" * 160)
    print("MASTER STRATEGY TABLE — REAL POLYMARKET FEES (fee = 0.07 × p × (1-p) per share, both legs)")
    print("=" * 160)
    print(f"  {'Strategy':>26s}  {'n':>5s}  {'W':>4s}  {'L':>4s}  "
          f"{'WR%':>5s}  {'BrkReal%':>8s}  {'EdgeReal':>9s}  "
          f"{'meanLeg':>9s}  {'meanReal':>9s}  {'Δmean':>8s}  "
          f"{'sumLeg':>9s}  {'sumReal':>9s}  {'ddReal':>9s}  "
          f"{'G1':>5s}  {'G3 p':>6s}  {'G4lo':>9s}  {'G4':>5s}")
    print("-" * 160)
    for r in rows:
        g3_p_str = f"{r['g3_p']:.3f}" if not np.isnan(r['g3_p']) else "—"
        g4_lo_str = f"${r['g4_lo_real_1']:+.4f}" if not np.isnan(r['g4_lo_real_1']) else "—"
        print(f"  {r['label']:>26s}  {r['n']:5d}  {r['wins']:4d}  {r['losses']:4d}  "
              f"{r['wr']*100:5.1f}  {r['breakeven_real']*100:7.2f}%  "
              f"{r['edge_real_pp']:+5.2f}pp  "
              f"${r['mean_legacy_1']:+.4f}  ${r['mean_real_1']:+.4f}  "
              f"${r['mean_real_1']-r['mean_legacy_1']:+.4f}  "
              f"${r['sum_legacy_1']:+.2f}  ${r['sum_real_1']:+.2f}  "
              f"${r['max_dd_real_1']:.2f}  {r['g1']:>5s}  "
              f"{g3_p_str:>6s}  {g4_lo_str:>9s}  {r['g4']:>5s}")
    print()

    # Summary: gates passing
    print("=" * 80)
    print("Strategies passing G1+G3+G4 with REAL PMXT fees")
    print("=" * 80)
    full_pass = [r for r in rows if r["g1"] == "PASS" and r["g3"] == "PASS" and r["g4"] == "PASS"]
    if full_pass:
        for r in full_pass:
            print(f"  {r['label']:>26s}  n={r['n']:4d}  WR={r['wr']*100:5.2f}%  "
                  f"edge_real={r['edge_real_pp']:+5.2f}pp  "
                  f"mean=${r['mean_real_1']:+.4f}  total=${r['sum_real_1']:+.2f}  "
                  f"G3 p={r['g3_p']:.3f}  G4lo=${r['g4_lo_real_1']:+.4f}")
    else:
        print("  (none) — real fees killed every previous G4 pass")

    print()
    print("Strategies passing G1 only (real fees):")
    g1_only = [r for r in rows if r["g1"] == "PASS"]
    for r in g1_only:
        flags = []
        if r["g3"] == "PASS": flags.append("G3")
        if r["g4"] == "PASS": flags.append("G4")
        print(f"  {r['label']:>26s}  total=${r['sum_real_1']:+.2f}  "
              f"mean=${r['mean_real_1']:+.4f}  gates: G1"
              f"{('+' + '+'.join(flags)) if flags else ''}")


if __name__ == "__main__":
    main()
