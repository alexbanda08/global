"""
anti_edge_analyzer — find systematic biases in losing sleeves to derive inverse strategies.

Hypothesis: if a sleeve has 40% hit rate, the inverse signal has 60% hit rate.
But the inverse only works if the loss is SYSTEMATIC, not random. So we slice by:
  - signal direction (UP vs DOWN)
  - hour of day (UTC)
  - day of week
  - asset
  - tf
And find the cells where hit rate is consistently and statistically below 50%.

Output:
  strategy_lab/results/meta_classifier/anti_edge_breakdown.csv
  strategy_lab/reports/ANTI_EDGE_FINDINGS.md
"""
from __future__ import annotations
import os
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("C:/Users/alexandre bandarra/Desktop/global")
TRADES = Path(os.environ.get("LOSERS_PATH",
    str(ROOT / "data" / "v4" / "shadow_trades_2026_05_05_live" / "losing_sleeves.csv")))
OUT_DIR = ROOT / "strategy_lab" / "results" / "meta_classifier"
OUT_CSV = OUT_DIR / f"anti_edge_breakdown_{TRADES.parent.name}.csv"


def slice_stats(df, slice_cols, min_n=10):
    """Group by slice_cols and compute hit rate, PnL, z-score below 50%."""
    g = df.groupby(slice_cols).agg(
        n=("won", "count"),
        wins=("won", "sum"),
        pnl_total=("pnl_usd", "sum"),
        pnl_per_trade=("pnl_usd", "mean"),
    ).reset_index()
    g["hit_pct"] = 100 * g["wins"] / g["n"]
    g["inverse_hit"] = 100 - g["hit_pct"]
    # Z-score below 50% (assumes binomial std = sqrt(0.25/n))
    g["z_below_50"] = (50 - g["hit_pct"]) / (100 * np.sqrt(0.25 / g["n"]))
    g["anti_edge_score"] = (50 - g["hit_pct"]) * np.sqrt(g["n"])
    g = g[g["n"] >= min_n].sort_values("anti_edge_score", ascending=False)
    return g


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("=== anti-edge analyzer ===\n")

    df = pd.read_csv(TRADES)
    df["won"] = df["won"].map({"t": 1, "f": 0})
    df["at"] = pd.to_datetime(df["at"])
    print(f"loaded {len(df)} trades from {df['sleeve_id'].nunique()} sleeves")
    print(f"date range: {df['at'].min()} → {df['at'].max()}")

    # Overall sleeve summary
    print("\n=== ALL SLEEVES (sample) ===")
    for s in df["sleeve_id"].unique():
        sub = df[df["sleeve_id"] == s]
        print(f"  {s:30s} n={len(sub):4d} hit={sub['won'].mean()*100:.1f}% pnl=${sub['pnl_usd'].sum():+.2f}")

    # SLICE 1: sleeve × signal direction
    print("\n=== SLICE 1: sleeve × signal direction ===")
    s1 = slice_stats(df, ["sleeve_id", "signal"], min_n=20)
    s1.insert(0, "slice_type", "sleeve_x_signal")
    print(s1[["sleeve_id", "signal", "n", "hit_pct", "inverse_hit", "pnl_total", "z_below_50"]].to_string(index=False))

    # SLICE 2: sleeve × hour of day
    print("\n=== SLICE 2: sleeve × hour_utc (top 10 worst by anti-edge score) ===")
    s2 = slice_stats(df, ["sleeve_id", "hour_utc"], min_n=15)
    s2.insert(0, "slice_type", "sleeve_x_hour")
    print(s2.head(10)[["sleeve_id", "hour_utc", "n", "hit_pct", "inverse_hit", "pnl_total", "z_below_50"]].to_string(index=False))

    # SLICE 3: sleeve × signal × hour (granular — find pockets)
    print("\n=== SLICE 3: sleeve × signal × hour_utc (top 15 anti-edge pockets) ===")
    s3 = slice_stats(df, ["sleeve_id", "signal", "hour_utc"], min_n=8)
    s3.insert(0, "slice_type", "sleeve_x_signal_x_hour")
    print(s3.head(15)[["sleeve_id", "signal", "hour_utc", "n", "hit_pct", "inverse_hit", "pnl_total", "z_below_50"]].to_string(index=False))

    # SLICE 4: sleeve × signal × dow_utc
    print("\n=== SLICE 4: sleeve × signal × day_of_week (top 10 anti-edge cells) ===")
    s4 = slice_stats(df, ["sleeve_id", "signal", "dow_utc"], min_n=10)
    s4.insert(0, "slice_type", "sleeve_x_signal_x_dow")
    print(s4.head(10)[["sleeve_id", "signal", "dow_utc", "n", "hit_pct", "inverse_hit", "pnl_total", "z_below_50"]].to_string(index=False))

    # CANDIDATE 1: full inverse of sol_5m_sniper
    print("\n=== CANDIDATE 1: full inverse of sol_5m_sniper ===")
    sol_sniper = df[df["sleeve_id"] == "poly_updown_sol_5m_sniper"]
    n = len(sol_sniper)
    hit = sol_sniper["won"].mean()
    pnl_actual = sol_sniper["pnl_usd"].sum()
    pnl_inverse = -pnl_actual + (n - 2 * sol_sniper["won"].sum()) * 0  # PnL of the OPPOSITE bet
    # When current bet won (+0.49) → inverse would have lost (-0.51)
    # When current bet lost (-0.51) → inverse would have won (+0.49)
    # Per-bet inverse PnL = -current_pnl approximately (with fee adjustment if any)
    inverse_pnl = -sol_sniper["pnl_usd"].sum()  # approximate
    inverse_hit = 100 - hit * 100
    print(f"  current: n={n} hit={hit*100:.1f}% pnl=${pnl_actual:+.2f}")
    print(f"  inverse: n={n} hit={inverse_hit:.1f}% pnl=${inverse_pnl:+.2f} (approx flip)")

    # CANDIDATE 2: eth_5m_sniper DOWN-only inverse
    print("\n=== CANDIDATE 2: eth_5m_sniper DOWN-only inverse ===")
    eth_sniper_down = df[(df["sleeve_id"] == "poly_updown_eth_5m_sniper") & (df["signal"] == "DOWN")]
    n2 = len(eth_sniper_down)
    hit2 = eth_sniper_down["won"].mean()
    pnl_actual2 = eth_sniper_down["pnl_usd"].sum()
    inverse_pnl2 = -pnl_actual2
    print(f"  current: n={n2} hit={hit2*100:.1f}% pnl=${pnl_actual2:+.2f}")
    print(f"  inverse: n={n2} hit={100 - hit2*100:.1f}% pnl=${inverse_pnl2:+.2f}")

    # CANDIDATE 3: btc_5m_volume UP-only inverse
    print("\n=== CANDIDATE 3: btc_5m_volume UP-only inverse ===")
    btc_vol_up = df[(df["sleeve_id"] == "poly_updown_btc_5m_volume") & (df["signal"] == "UP")]
    n3 = len(btc_vol_up)
    hit3 = btc_vol_up["won"].mean()
    pnl_actual3 = btc_vol_up["pnl_usd"].sum()
    inverse_pnl3 = -pnl_actual3
    print(f"  current: n={n3} hit={hit3*100:.1f}% pnl=${pnl_actual3:+.2f}")
    print(f"  inverse: n={n3} hit={100 - hit3*100:.1f}% pnl=${inverse_pnl3:+.2f}")

    # Persist all slices
    all_slices = pd.concat([s1, s2, s3, s4], ignore_index=True)
    all_slices.to_csv(OUT_CSV, index=False)
    print(f"\nWrote {OUT_CSV}")

    # KEY INSIGHT: which CELLS have BOTH high anti-edge score AND big PnL recovery potential
    print("\n=== TOP 10 INVERSE OPPORTUNITIES (sorted by absolute PnL recovery) ===")
    top = all_slices.copy()
    top["pnl_recovery"] = -top["pnl_total"]  # how much PnL we'd flip from negative to positive
    top = top[(top["hit_pct"] < 50) & (top["pnl_recovery"] > 0)].sort_values("pnl_recovery", ascending=False)
    print(top.head(10)[["slice_type", "sleeve_id", "signal", "hour_utc", "dow_utc", "n", "hit_pct", "inverse_hit", "pnl_recovery", "z_below_50"]].fillna("").to_string(index=False))


if __name__ == "__main__":
    main()
