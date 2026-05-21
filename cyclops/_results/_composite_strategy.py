"""Build the composite 'Cyclops S7 + sleeve-presence' strategy and validate.

Tests several variants:
  X0: Cyclops S7 only (baseline reference)
  X1: Cyclops S7 + ANY VPS3 BTC 5m sleeve also fired
  X2: Cyclops S7 + momo_v2 family fired (strongest correlate)
  X3: Cyclops S7 + volume_INV_NIGHT also fired
  X4: Cyclops S7 + sleeve-presence + restrict to vwap 0.40–0.70 (the sweet bucket)

Then runs the validation battery (G3 permutation, G4 bootstrap) on each.
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path
import sys
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
from load import CANON

# Reuse validation modules
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global")
from cyclops.validate.permutation import permutation_test
from cyclops.validate.bootstrap import bootstrap_mean_ci

SCALE = 1.0 / 25.0


def load_sleeve_slug_map():
    ev = pd.read_parquet(Path(CANON) / "trading_events_30d.parquet")
    ev = ev[ev.kind == "poly_updown_resolution"]
    btc5 = ev[ev.sleeve_id.str.contains("btc_5m", na=False)]
    d = btc5["data"].apply(json.loads)
    df = pd.json_normalize(d)
    df["sleeve_id"] = btc5["sleeve_id"].values
    res = pd.read_parquet(Path(CANON) / "resolutions.parquet")
    cid2slug = dict(zip(res.market_id, res.slug))
    df["slug"] = df["condition_id"].map(cid2slug)
    return df.dropna(subset=["slug"])


def main():
    sleeve_df = load_sleeve_slug_map()
    cy = pd.read_csv("cyclops/_results/p5_full_depth_p3.csv")
    cy_f = cy[cy.fired == True].copy()
    cy_f["pnl_1"] = cy_f["pnl_usd"] * SCALE

    all_sleeve_slugs = set(sleeve_df.slug.unique())
    momo_v2_slugs = set(sleeve_df[sleeve_df.sleeve_id.str.contains("momo_v2")].slug.unique())
    vol_inv_slugs = set(sleeve_df[sleeve_df.sleeve_id == "poly_updown_btc_5m_volume_INV_NIGHT"].slug.unique())
    sniper_slugs = set(sleeve_df[sleeve_df.sleeve_id == "poly_updown_btc_5m_sniper"].slug.unique())

    variants = {
        "X0_S7_baseline": cy_f,
        "X1_S7+any_sleeve": cy_f[cy_f.slug.isin(all_sleeve_slugs)],
        "X2_S7+momo_v2":   cy_f[cy_f.slug.isin(momo_v2_slugs)],
        "X3_S7+vol_inv":   cy_f[cy_f.slug.isin(vol_inv_slugs)],
        "X4_S7+sniper":    cy_f[cy_f.slug.isin(sniper_slugs)],
        "X5_S7+any+vwap_0.4_0.7":
            cy_f[cy_f.slug.isin(all_sleeve_slugs)
                  & (cy_f.vwap_entry >= 0.40) & (cy_f.vwap_entry <= 0.70)],
        "X6_S7+momo_v2+vol_inv_both":
            cy_f[cy_f.slug.isin(momo_v2_slugs & vol_inv_slugs)],
    }

    print(f"{'Variant':>35s}  {'n':>5s}  {'wins':>5s}  {'WR':>6s}  "
          f"{'brk':>6s}  {'edge':>7s}  {'mean$1':>9s}  {'sum$1':>9s}  "
          f"{'G3_p':>6s}  {'G4_CI_lo':>9s}")
    print("-" * 116)

    for label, sub in variants.items():
        if sub.empty:
            print(f"  {label:>33s}  empty")
            continue
        n = len(sub)
        wins = int(sub.won.sum())
        wr = sub.won.mean()
        bk = sub.vwap_entry.mean()
        edge = (wr - bk) * 100
        mp = float(sub.pnl_1.mean())
        sp = float(sub.pnl_1.sum())

        # Build a dataframe shape the validators want
        sub_v = sub.rename(columns={"vwap_entry": "vwap_entry"}).copy()
        # Run gates
        if n >= 10:
            perm = permutation_test(sub_v, n_permutations=3000, seed=42)
            p_val = perm["p_value"]
            boot = bootstrap_mean_ci(sub_v, n_boot=10000, seed=42)
            ci_lo_1 = boot["ci_lower"] * SCALE
        else:
            p_val = float("nan")
            ci_lo_1 = float("nan")

        print(f"  {label:>33s}  {n:5d}  {wins:5d}  {wr*100:5.2f}%  "
              f"{bk*100:5.2f}%  {edge:+5.2f}pp  ${mp:+.4f}  ${sp:+.2f}  "
              f"{p_val:5.3f}  ${ci_lo_1:+.4f}")
    print()

    # Also: per-vwap-bucket on the best variant (sleeve_active)
    print("=" * 80)
    print("Vwap-bucket analysis on X1 (Cyclops + ANY sleeve fire)")
    print("=" * 80)
    x1 = variants["X1_S7+any_sleeve"].copy()
    bins = [0.30, 0.40, 0.50, 0.60, 0.70, 1.01]
    x1["vwap_bin"] = pd.cut(x1.vwap_entry, bins=bins)
    bb = x1.groupby("vwap_bin", observed=True).agg(
        n=("pnl_1", "size"),
        wr=("won", "mean"),
        mean_vwap=("vwap_entry", "mean"),
        mean_pnl_1=("pnl_1", "mean"),
        total_1=("pnl_1", "sum"),
    )
    bb["edge_pp"] = (bb["wr"] - bb["mean_vwap"]) * 100
    print(bb.to_string())


if __name__ == "__main__":
    main()
