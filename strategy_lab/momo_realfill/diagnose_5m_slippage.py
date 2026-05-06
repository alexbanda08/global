"""diagnose_5m_slippage — figure out exactly where the 5m HOLD entry-side
slippage comes from.

For each shadow fire matched to L25:
    1. Production entry_price (from shadow CSV)
    2. Realfill vwap_e (from L25 walked at ws+120s exactly)
    3. Diff = production paid more than realfill expected → slippage
    4. Time-shift the realfill lookup by ±N seconds to find when production
       SAW the book it actually traded against.
    5. Compute spread + book depth at production fill time vs at strict ws+120s

Output: per-(asset, tf) slippage breakdown with conditional gates.
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "meta_classifier"))

from book_walk import book_walk_fill                    # noqa: E402
from extended_backtest_with_robustness import NOTIONAL_USD  # noqa: E402
from loaders.raw_orderbook_l25 import (                 # noqa: E402
    load_orderbook_l25_raw, OrderbookIndex,
)
from strategy_lab.momo_realfill import match_shadow as ms

_OID = {"Up": 0, "Down": 1}


def diagnose():
    print("[1] loading shadow…")
    shadow = ms.load_shadow()

    print("[2] loading L25 indices…")
    indices = {}
    for asset in ("btc", "eth", "sol"):
        slugs = set(shadow[shadow.asset == asset.upper()]["slug"].unique())
        if not slugs:
            continue
        ob_df = load_orderbook_l25_raw(asset, slugs=slugs)
        indices[asset] = OrderbookIndex(ob_df)
        print(f"    [{asset}] indexed {len(ob_df):,} rows for {len(slugs)} slugs")

    print("[3] per-trade slippage decomposition…")
    rows = []
    for _, r in shadow.iterrows():
        if r.asset.lower() not in indices:
            continue
        idx = indices[r.asset.lower()]
        ws_s = int(r.ws_unix)
        held = "Up" if r.signal == "UP" else "Down"
        held_id = _OID[held]
        entry_ts_us = (ws_s + 120) * 1_000_000

        asks_p, asks_s = idx.book_at(r.slug, held_id, entry_ts_us, side="ask")
        if asks_p is None:
            continue
        bids_p, bids_s = idx.book_at(r.slug, held_id, entry_ts_us, side="bid")

        # Spread + book quality at strict ws+120
        spread = (
            float(asks_p[0]) - float(bids_p[0])
            if asks_p[0] is not None and bids_p[0] is not None
            and np.isfinite(asks_p[0]) and np.isfinite(bids_p[0])
            else None
        )
        l1_ask_size = float(asks_s[0]) if asks_s[0] is not None and np.isfinite(asks_s[0]) else 0
        # Walk own asks for $25 to get realfill vwap
        vwap_e, shares_e, usd_e, hit_levels, under_e = book_walk_fill(
            asks_p, asks_s, NOTIONAL_USD
        )

        # Production paid:
        prod_entry = float(r.entry_price) if pd.notna(r.entry_price) else None
        prod_qty = float(r.entry_qty) if pd.notna(r.entry_qty) else None

        rows.append({
            "asset": r.asset,
            "tf": r.timeframe,
            "exit": r["exit"],
            "slug": r.slug,
            "ws_unix": ws_s,
            "signal": r.signal,
            "won": r.won,
            "spread_at_t120": spread,
            "rf_vwap_e": vwap_e,
            "rf_shares_e": shares_e,
            "rf_usd_filled": usd_e,
            "rf_hit_levels": hit_levels,
            "rf_underfilled": under_e,
            "rf_l1_ask_size": l1_ask_size,
            "prod_entry_price": prod_entry,
            "prod_entry_qty": prod_qty,
            # Slippage in bps: (prod - rf) / rf × 10000
            "slip_bps": ((prod_entry - vwap_e) / vwap_e * 10000)
                        if (prod_entry and vwap_e and vwap_e > 0) else None,
            "slip_dollar_per_25": (prod_entry - vwap_e) * (NOTIONAL_USD / vwap_e)
                                  if (prod_entry and vwap_e and vwap_e > 0) else None,
        })
    df = pd.DataFrame(rows)
    out = ROOT / "strategy_lab" / "results" / "meta_classifier" / "momo_5m_slippage_diag.csv"
    df.to_csv(out, index=False)
    print(f"    [csv] → {out}  ({len(df)} rows)")

    print("\n[4] aggregate per (asset, tf) — focus on 5m HOLD:\n")
    only5m = df[(df["tf"] == "5m") & (df["exit"] == "HOLD")].copy()
    print(f"5m HOLD total: {len(only5m)} matched")
    print()
    print("Per-asset 5m HOLD diagnostics:")
    grp = only5m.groupby("asset")
    for asset, g in grp:
        n = len(g)
        med_slip = g["slip_bps"].median()
        p95_slip = g["slip_bps"].quantile(0.95)
        med_dollar = g["slip_dollar_per_25"].median()
        med_spread = g["spread_at_t120"].median()
        med_l1_size = g["rf_l1_ask_size"].median()
        n_under = (g["rf_underfilled"] == True).sum()  # noqa
        n_hit_gt_5 = (g["rf_hit_levels"] > 5).sum()
        win = g["won"].sum()
        loss = n - win
        print(f"  {asset}: n={n:3d}  win/loss={win}/{loss}  "
              f"med_slip={med_slip:+.0f}bps  p95_slip={p95_slip:+.0f}bps  "
              f"med_$slip=${med_dollar:+.3f}  med_spread={med_spread:.4f}  "
              f"med_L1_size={med_l1_size:.1f}  underfilled={n_under}/{n}  "
              f"hit>5levels={n_hit_gt_5}/{n}")

    print("\n[5] WIDE-SPREAD vs TIGHT-SPREAD breakdown (was production firing on bad markets?):\n")
    only5m_hold = df[(df["tf"] == "5m") & (df["exit"] == "HOLD")].copy()
    only5m_hold["wide_spread"] = only5m_hold["spread_at_t120"] > 0.025
    g = only5m_hold.groupby(["asset", "wide_spread"])["won"].agg(["count", "sum"]).reset_index()
    g["loss"] = g["count"] - g["sum"]
    g["hit"] = g["sum"] / g["count"]
    print(g.to_string(index=False))

    print("\n[6] hit rate by L1 ask size bucket:\n")
    only5m_hold["l1_bucket"] = pd.cut(
        only5m_hold["rf_l1_ask_size"],
        bins=[0, 5, 25, 100, 1000, 100000],
        labels=["0-5", "5-25", "25-100", "100-1k", ">1k"],
    )
    g = only5m_hold.groupby(["asset", "l1_bucket"], observed=True)["won"].agg(["count", "sum"]).reset_index()
    g["hit"] = g["sum"] / g["count"]
    print(g.to_string(index=False))

    print("\n[7] hit rate by SLIPPAGE bucket (prod minus realfill, bps):\n")
    only5m_hold["slip_bucket"] = pd.cut(
        only5m_hold["slip_bps"],
        bins=[-1000, -50, 0, 50, 200, 1000, 100000],
        labels=["≤-50", "-50..0", "0..50", "50..200", "200..1k", ">1k"],
    )
    g = only5m_hold.groupby(["asset", "slip_bucket"], observed=True)["won"].agg(["count", "sum"]).reset_index()
    g["hit"] = g["sum"] / g["count"]
    print(g.to_string(index=False))


if __name__ == "__main__":
    diagnose()
