"""Build a 14-sleeve VPS3 consensus vote per (slug, direction) and combine
with Cyclops S7 filters to look for edge.

The single VPS3 sleeves all show negative aggregate PnL in shadow mode.
But IF they are individually informative and uncorrelated, voting consensus
could surface edge that no single sleeve has.

Steps:
  1. Build per-market direction votes from all 14 BTC 5m VPS3 sleeves
     using their RESOLUTION events (won_us per sleeve).
  2. For each market: count Up votes, Down votes; compute majority direction
     and consensus strength.
  3. Recompute PnL at our $1-stake / 2%-fee model using the slug's actual
     outcome and a unified entry vwap (sleeve entry_price average).
  4. Test consensus-based strategies + cross with Cyclops S7 filters.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import sys
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
from load import CANON  # noqa: E402

SCALE = 1.0 / 25.0           # backtest stake → $1


def parse_resolutions():
    ev = pd.read_parquet(Path(CANON) / "trading_events_30d.parquet")
    ev = ev[ev.kind == "poly_updown_resolution"].copy()
    d = ev["data"].apply(json.loads)
    df = pd.json_normalize(d)
    df["sleeve_id"] = ev["sleeve_id"].values
    for c in ("pnl_usd", "entry_qty", "entry_price"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def cid2slug():
    res = pd.read_parquet(Path(CANON) / "resolutions.parquet")
    return dict(zip(res["market_id"].values, res["slug"].values))


def normalize_dir(d):
    if d is None:
        return None
    s = str(d).strip().lower()
    if s in ("up", "u"):
        return "Up"
    if s in ("down", "d"):
        return "Down"
    return None


def pnl_at_legacy_2pct(direction: str, outcome: str, entry_price: float,
                       stake_1: float = 1.0) -> float:
    """Same fee model Cyclops uses: 2% on profit, 0 on loss. Stake = $1."""
    if entry_price <= 0 or entry_price >= 1:
        return 0.0
    won = (direction == outcome)
    qty = stake_1 / entry_price
    if won:
        profit = qty - stake_1     # payoff is qty * $1
        if profit > 0:
            profit *= 0.98
        return float(profit)
    return -float(stake_1)


def main():
    print("Loading VPS3 events ...")
    df = parse_resolutions()
    df["slug"] = df["condition_id"].map(cid2slug())
    df["direction"] = df["signal"].apply(normalize_dir)
    df["outcome_dir"] = df["outcome"].apply(normalize_dir)
    df = df.dropna(subset=["slug", "direction", "outcome_dir"])

    btc5 = df[df.sleeve_id.str.contains("btc_5m", na=False)].copy()
    print(f"  BTC 5m resolutions: {len(btc5)}  unique slugs: {btc5.slug.nunique()}")
    print()

    # --- Build per-(slug, sleeve) direction map; collapse to one fire per sleeve
    sleeve_dir_per_slug = btc5.groupby(["slug", "sleeve_id"]).agg(
        direction=("direction", "first"),
        won=("won", "first"),
        entry_price=("entry_price", "first"),
        outcome_dir=("outcome_dir", "first"),
    ).reset_index()
    print(f"  sleeve-direction rows after collapse: {len(sleeve_dir_per_slug)}")

    # --- Per-slug consensus
    rows = []
    for slug, g in sleeve_dir_per_slug.groupby("slug"):
        n_total = len(g)
        n_up = int((g.direction == "Up").sum())
        n_dn = int((g.direction == "Down").sum())
        majority = "Up" if n_up > n_dn else ("Down" if n_dn > n_up else "Tie")
        strength = max(n_up, n_dn) / n_total if n_total else 0
        outcome = g.outcome_dir.iloc[0]
        mean_entry = float(g.entry_price.mean())
        rows.append({
            "slug": slug, "n_sleeves": n_total, "n_up": n_up, "n_dn": n_dn,
            "majority": majority, "strength": strength,
            "outcome_dir": outcome, "mean_entry": mean_entry,
        })
    cons = pd.DataFrame(rows)
    print(f"  per-slug consensus rows: {len(cons)}")
    print()

    # --- Vote distribution
    print("=" * 72)
    print("A) Vote distribution across 14 BTC 5m sleeves")
    print("=" * 72)
    print(cons["n_sleeves"].value_counts().sort_index().to_dict())
    print()
    print(cons.groupby(["n_sleeves", "majority"]).size().reset_index(name="count"))
    print()

    # --- Consensus strategy: fire majority direction
    print("=" * 72)
    print("B) Consensus-vote strategies ($1 stake, 2% legacy fee)")
    print("=" * 72)
    print(f"{'strategy':>40s}  {'n':>5s}  {'WR':>6s}  {'brk':>6s}  "
          f"{'edge':>7s}  {'mean$1':>8s}  {'sum$1':>8s}")
    print("-" * 88)

    def eval_strat(label, sub, direction_col="majority"):
        sub = sub.copy()
        sub = sub[sub[direction_col].isin(["Up", "Down"])]
        if sub.empty:
            print(f"  {label:>40s}  {0:5d}  no fires")
            return
        sub["won_b"] = (sub[direction_col] == sub.outcome_dir)
        sub["pnl_1"] = sub.apply(
            lambda r: pnl_at_legacy_2pct(r[direction_col], r.outcome_dir,
                                          r.mean_entry, stake_1=1.0),
            axis=1,
        )
        n = len(sub)
        wr = sub.won_b.mean()
        bk = sub.mean_entry.mean()
        mp = sub.pnl_1.mean()
        sp = sub.pnl_1.sum()
        print(f"  {label:>40s}  {n:5d}  {wr*100:5.2f}%  {bk*100:5.2f}%  "
              f"{(wr - bk)*100:+5.2f}pp  ${mp:+.4f}  ${sp:+.2f}")

    # All-markets majority vote
    eval_strat("ALL_markets_majority", cons)

    # Consensus thresholds
    for thr in (0.6, 0.7, 0.8, 0.9, 1.0):
        sub = cons[(cons.strength >= thr) & (cons.n_sleeves >= 5)]
        eval_strat(f"strength>={thr:.1f}_n>=5", sub)

    # 10+ sleeves agree
    for k in (8, 10, 12):
        sub = cons[(cons.n_sleeves >= k) & (cons.strength >= 0.8)]
        eval_strat(f"n_sleeves>={k}_strength>=0.8", sub)
    print()

    # --- Cross with Cyclops S7
    print("=" * 72)
    print("C) Consensus vote + Cyclops S7 cross")
    print("=" * 72)
    cy = pd.read_csv("cyclops/_results/p5_full_depth_p3.csv")
    cy = cy[cy.fired == True].copy()
    cy_slugs = set(cy.slug.values)
    cy_dir = dict(zip(cy.slug.values, cy.direction.values))

    cons["in_cyclops"] = cons.slug.isin(cy_slugs)
    cons["cyclops_dir"] = cons.slug.map(cy_dir)
    cons["agrees_with_cyclops"] = cons["cyclops_dir"] == cons["majority"]

    print(f"  Cyclops S7 fires: {len(cy_slugs)}")
    print(f"  consensus slugs in Cyclops: {cons.in_cyclops.sum()}")
    print(f"  consensus slugs NOT in Cyclops: {(~cons.in_cyclops).sum()}")
    print()

    # Among Cyclops slugs: agreement breakdown
    cy_overlap = cons[cons.in_cyclops].copy()
    print(f"  In Cyclops + consensus agrees with Cyclops: {cy_overlap.agrees_with_cyclops.sum()}")
    print(f"  In Cyclops + consensus disagrees: {(~cy_overlap.agrees_with_cyclops).sum()}")
    print()

    # Cyclops trade outcome stratified by sleeve consensus agreement
    cy = cy.merge(cons[["slug", "majority", "strength", "n_sleeves",
                         "agrees_with_cyclops"]],
                  on="slug", how="left")
    cy["pnl_1"] = cy["pnl_usd"] * SCALE
    print("  Cyclops S7 fires stratified by sleeve-consensus agreement:")
    for agree_value in (True, False, None):
        if agree_value is None:
            sub = cy[cy.agrees_with_cyclops.isna()]
            label = "no_sleeve_data"
        elif agree_value:
            sub = cy[cy.agrees_with_cyclops == True]
            label = "sleeves_AGREE_with_cyclops"
        else:
            sub = cy[cy.agrees_with_cyclops == False]
            label = "sleeves_DISAGREE_with_cyclops"
        if sub.empty:
            print(f"    {label:>34s}  n=0")
            continue
        print(f"    {label:>34s}  n={len(sub):4d}  WR={sub.won.mean():6.3f}  "
              f"mean=${sub.pnl_1.mean():+.4f}  sum=${sub.pnl_1.sum():+.2f}")
    print()

    # Cyclops trades where majority consensus is STRONG and AGREES
    print("  Filtered: Cyclops fires + sleeves agree + strength >= X:")
    for thr in (0.6, 0.7, 0.8):
        sub = cy[(cy.agrees_with_cyclops == True) & (cy.strength >= thr)]
        if sub.empty:
            print(f"    strength>={thr}  n=0")
            continue
        print(f"    strength>={thr}  n={len(sub):4d}  WR={sub.won.mean():6.3f}  "
              f"mean=${sub.pnl_1.mean():+.4f}  sum=${sub.pnl_1.sum():+.2f}")
    print()

    # NEW: Consensus EXPANSION - fire on consensus markets Cyclops missed
    print("=" * 72)
    print("D) Cyclops + consensus expansion")
    print("=" * 72)
    print("  Concept: fire when EITHER Cyclops fires OR sleeves have strong")
    print("  consensus. We need entry vwap for non-Cyclops slugs.")
    print()
    print("  Cyclops universe (S7) total: $+15.88 @ $1 stake")
    print()
    # Markets NOT in Cyclops, but with strong sleeve consensus
    not_cy = cons[~cons.in_cyclops].copy()
    for thr in (0.7, 0.8, 0.9):
        sub = not_cy[(not_cy.strength >= thr) & (not_cy.n_sleeves >= 6)]
        if sub.empty:
            continue
        sub = sub.copy()
        sub["pnl_1"] = sub.apply(
            lambda r: pnl_at_legacy_2pct(r.majority, r.outcome_dir,
                                          r.mean_entry, 1.0),
            axis=1,
        )
        wr = (sub.majority == sub.outcome_dir).mean()
        bk = sub.mean_entry.mean()
        print(f"    consensus-only(strength>={thr},n>=6): n={len(sub):4d}  "
              f"WR={wr*100:5.2f}%  brk={bk*100:5.2f}%  "
              f"edge={(wr - bk)*100:+5.2f}pp  "
              f"mean=${sub.pnl_1.mean():+.4f}  sum=${sub.pnl_1.sum():+.2f}")


if __name__ == "__main__":
    main()
