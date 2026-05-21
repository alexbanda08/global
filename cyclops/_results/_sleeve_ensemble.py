"""Mix VPS3 shadow-mode sleeves with the Cyclops S7 (FD P3) result.

Goal: find combinations that improve WR / mean PnL over the best single
strategy. All PnL reported at $1 stake equivalent (rescale ÷25).

Workflow:
  A) Build per-sleeve resolution stats from trading_events_30d.parquet
  B) Map condition_id ↔ slug ↔ ws_s using canonical resolutions.parquet
  C) Cross-ref VPS3 fires with Cyclops S7 fires at (slug, direction)
  D) Test ensemble strategies:
       - INTERSECT same direction (both fire and agree)
       - UNION (either fires)
       - Cyclops fires guarded by sleeve agreement
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import sys
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
from load import CANON  # noqa: E402

STAKE_BACKTEST = 25.0
SCALE = 1.0 / STAKE_BACKTEST


# ---------------------------------------------------------------------------
# A) Build per-sleeve stats from resolutions
# ---------------------------------------------------------------------------

def parse_resolutions() -> pd.DataFrame:
    """Return one row per resolved trade: sleeve_id, condition_id, signal,
    outcome, won, pnl_usd, entry_price."""
    ev = pd.read_parquet(Path(CANON) / "trading_events_30d.parquet")
    ev = ev[ev.kind == "poly_updown_resolution"].copy()

    parsed = ev["data"].apply(json.loads)
    df = pd.json_normalize(parsed)
    df["sleeve_id"] = ev["sleeve_id"].values
    df["event_at"] = ev["at"].values
    # Numeric coercions (these are dicts of numeric strings)
    for c in ("pnl_usd", "entry_qty", "entry_price", "strike_price",
             "settlement_price"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def per_sleeve_stats(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sl, g in df.groupby("sleeve_id"):
        n = len(g)
        if n == 0:
            continue
        wins = int(g["won"].sum())
        losses = n - wins
        wr = wins / n
        # Production trades are size ~$25; rescale to $1
        sum_pnl_1 = float(g["pnl_usd"].sum()) * SCALE
        mean_pnl_1 = float(g["pnl_usd"].mean()) * SCALE
        mean_entry = float(g["entry_price"].mean())
        rows.append({
            "sleeve_id": sl,
            "n": n,
            "wins": wins,
            "losses": losses,
            "wr": wr,
            "mean_entry": mean_entry,
            "edge_pp": (wr - mean_entry) * 100,
            "mean_pnl_1": mean_pnl_1,
            "sum_pnl_1": sum_pnl_1,
        })
    return pd.DataFrame(rows).sort_values("sum_pnl_1", ascending=False)


# ---------------------------------------------------------------------------
# B) condition_id ↔ slug map
# ---------------------------------------------------------------------------

def cid_to_slug_map() -> dict:
    res = pd.read_parquet(Path(CANON) / "resolutions.parquet")
    # res.market_id is the condition_id (verified earlier — same hex form)
    return dict(zip(res["market_id"].values, res["slug"].values))


# ---------------------------------------------------------------------------
# C) Cyclops S7 (FD P3) fired-trade set
# ---------------------------------------------------------------------------

def cyclops_s7() -> pd.DataFrame:
    df = pd.read_csv("cyclops/_results/p5_full_depth_p3.csv")
    f = df[df.fired == True].copy()
    f["pnl_1"] = f["pnl_usd"] * SCALE
    return f[["slug", "ws_s", "direction", "vwap_entry",
              "shares", "won", "pnl_usd", "pnl_1"]].copy()


# ---------------------------------------------------------------------------
# D) Ensemble experiments
# ---------------------------------------------------------------------------

def normalize_dir(d):
    if d is None or (isinstance(d, float) and np.isnan(d)):
        return None
    s = str(d).strip().lower()
    if s in ("up", "u"):
        return "Up"
    if s in ("down", "d"):
        return "Down"
    return None


def main():
    print("Loading resolutions ...")
    df = parse_resolutions()
    cid_map = cid_to_slug_map()
    df["slug"] = df["condition_id"].map(cid_map)
    df["direction"] = df["signal"].apply(normalize_dir)
    df = df.dropna(subset=["slug", "direction"])
    print(f"  resolved rows: {len(df)}")
    # BTC 5m only
    btc5 = df[df.sleeve_id.str.contains("btc_5m", na=False)].copy()
    print(f"  BTC 5m resolved: {len(btc5)}")

    # ---- Per-sleeve baseline stats ----
    print()
    print("=" * 72)
    print("A) Per-sleeve baseline stats (BTC 5m, $1 stake)")
    print("=" * 72)
    stats = per_sleeve_stats(btc5)
    cols = ["sleeve_id", "n", "wins", "losses", "wr", "mean_entry",
            "edge_pp", "mean_pnl_1", "sum_pnl_1"]
    pd.options.display.float_format = "{:.4f}".format
    print(stats[cols].to_string(index=False))
    print()

    # ---- Cyclops baseline ----
    cy = cyclops_s7()
    print("=" * 72)
    print("B) Cyclops S7 (FD P3) baseline")
    print("=" * 72)
    print(f"  n={len(cy)}  wr={cy.won.mean():.4f}  "
          f"mean_pnl_1=${cy.pnl_1.mean():+.4f}  sum_pnl_1=${cy.pnl_1.sum():+.2f}")
    print()

    # ---- Intersection / Union with each VPS3 sleeve ----
    print("=" * 72)
    print("C) Ensemble experiments (Cyclops S7 × each VPS3 sleeve)")
    print("=" * 72)
    print(f"{'Sleeve':>40s}  {'mode':>10s}  {'n':>5s}  {'WR':>6s}  "
          f"{'mean$1':>8s}  {'sum$1':>8s}")
    print("-" * 90)

    rows_ensemble = []
    for sl in sorted(btc5.sleeve_id.unique()):
        sv = btc5[btc5.sleeve_id == sl][["slug", "direction", "won", "pnl_usd"]].copy()
        sv["pnl_1"] = sv["pnl_usd"] * SCALE
        sv_idx = {(r.slug, r.direction): r for r in sv.itertuples()}
        cy_idx = {(r.slug, r.direction): r for r in cy.itertuples()}

        # Intersection — same (slug, direction) in both; use Cyclops PnL.
        inter_keys = set(sv_idx.keys()) & set(cy_idx.keys())
        if inter_keys:
            inter_pnl = np.array([cy_idx[k].pnl_1 for k in inter_keys])
            inter_won = np.array([cy_idx[k].won for k in inter_keys])
            n = len(inter_keys)
            wr = float(inter_won.mean())
            mp = float(inter_pnl.mean())
            sp = float(inter_pnl.sum())
            print(f"  {sl:>40s}  {'INTER':>10s}  {n:5d}  {wr:6.3f}  "
                  f"${mp:+.4f}  ${sp:+.2f}")
            rows_ensemble.append({"sleeve_id": sl, "mode": "INTERSECT",
                                   "n": n, "wr": wr, "mean_1": mp, "sum_1": sp})

        # Disagreement — Cyclops fires Direction-X, sleeve fired Direction-Y.
        # Use Cyclops side.
        cy_only_dis = []
        for k_slug in {k[0] for k in cy_idx}:
            sv_dirs = [k[1] for k in sv_idx if k[0] == k_slug]
            cy_dirs = [k[1] for k in cy_idx if k[0] == k_slug]
            for cd in cy_dirs:
                if any(sd != cd for sd in sv_dirs):
                    cy_only_dis.append(cy_idx[(k_slug, cd)])
        if cy_only_dis:
            arr_pnl = np.array([r.pnl_1 for r in cy_only_dis])
            arr_won = np.array([r.won for r in cy_only_dis])
            n = len(cy_only_dis)
            wr = float(arr_won.mean())
            mp = float(arr_pnl.mean())
            sp = float(arr_pnl.sum())
            print(f"  {sl:>40s}  {'DISAGR':>10s}  {n:5d}  {wr:6.3f}  "
                  f"${mp:+.4f}  ${sp:+.2f}")
            rows_ensemble.append({"sleeve_id": sl, "mode": "DISAGREE",
                                   "n": n, "wr": wr, "mean_1": mp, "sum_1": sp})

    print()
    print("=" * 72)
    print("D) Top ensemble combos by total $1 PnL")
    print("=" * 72)
    if rows_ensemble:
        ens = pd.DataFrame(rows_ensemble).sort_values("sum_1", ascending=False)
        print(ens.to_string(index=False))
    print()


if __name__ == "__main__":
    main()
