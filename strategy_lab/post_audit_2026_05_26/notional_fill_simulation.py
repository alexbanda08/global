"""TASK 4: L25 sub-second fill simulation at $25, $250, $2500 notionals.

For each top sleeve × notional level, walks the L25 books at fire_us and computes:
  - entry_vwap_walked     (actual walked vwap at notional)
  - slippage_bps          (vs $25 topbook vwap)
  - pnl_at_notional       (legacy fee: shares * (1-vwap) * 0.98 if won, -usd_in if lost)
  - depth_consumed_pct    (entry_qty / total_depth_25_levels * 100)
  - underfilled flag

Output:
  data/v4/canonical/_results/sleeve_notional_fill_simulation.csv

If at $250 notional, slippage > 50 bps OR depth_consumed > 30%, FLAG deploy-risky.
"""
from __future__ import annotations
import os, sys, time, gc
from pathlib import Path
import pandas as pd
import numpy as np

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

ROOT = Path(r"C:/Users/alexandre bandarra/Desktop/global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

from book_walk import book_walk_fill
from load import load_orderbook_l25_streaming
from engine_v2 import LegacyConfig, find_book_strict

RES = ROOT / "data" / "v4" / "canonical" / "_results"
FIRED = RES / "_post_audit_2026_05_26" / "fired_by_sleeve_clean.parquet"

NOTIONALS = [25.0, 250.0, 2500.0]
SPREAD = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}


def main():
    print("Loading fired_by_sleeve_clean.parquet…")
    fired = pd.read_parquet(FIRED)
    # Strip UNIV — those are crosss-asset, fires already match BTC/ETH/SOL panels
    fired["asset_lc"] = fired["asset_norm"].str.lower()
    print(f"  {len(fired):,} fires across {fired.sleeve_id.nunique()} sleeves")

    # Per-asset L25 load (1Hz subsample = ~10 events/sec at most after subsample)
    results = []
    for asset_lc in ("btc", "eth", "sol"):
        asset = asset_lc.upper()
        sub = fired[fired["asset_lc"] == asset_lc].copy()
        if sub.empty:
            print(f"\n[{asset}] no fires, skip")
            continue
        slugs = set(sub["slug"].tolist())
        print(f"\n[{asset}] {len(sub):,} fires, {len(slugs):,} unique slugs — streaming L25…")
        t0 = time.time()
        # Use FULL L25 (no 1hz subsample) — we want sub-second resolution per CLAUDE.md.
        # Sliding window bounded by fire_us min/max.
        min_us = int(sub["fire_us"].min()) - 60_000_000
        max_us = int(sub["fire_us"].max()) + 60_000_000
        books = load_orderbook_l25_streaming(
            asset_lc, slugs=slugs, subsample_1hz=False,
            min_ts_us=min_us, max_ts_us=max_us,
        )
        print(f"  L25 streamed in {time.time()-t0:.1f}s, {len(books)} pairs")

        # Walk per fire × notional
        cfg = LegacyConfig()
        spread = SPREAD[asset]
        rows_asset = []
        t1 = time.time()
        for r in sub.itertuples(index=False):
            slug = r.slug
            fire_us = int(r.fire_us)
            direction = r.direction
            outcome_key = "Up" if direction == "UP" else "Down"
            book = find_book_strict(books, slug, outcome_key, fire_us)
            if book is None:
                continue
            ap = book["ap"]
            asz = book["asz"]
            bp = book["bp"]
            ask0 = float(ap[0]) if len(ap) and np.isfinite(ap[0]) else float("nan")
            bid0 = float(bp[0]) if len(bp) and np.isfinite(bp[0]) else float("nan")
            if not (np.isfinite(ask0) and np.isfinite(bid0)) or (ask0 - bid0) > spread:
                continue

            ap_list = [float(x) for x in ap]
            asz_list = [float(x) for x in asz]
            # Total available depth in $ across 25 levels
            total_depth_usd = float(sum(
                p * s for p, s in zip(ap_list, asz_list)
                if np.isfinite(p) and np.isfinite(s) and s > 0 and 0 < p < 1
            ))

            # Reference vwap @ $25
            v25, sh25, usd25, lev25, _ = book_walk_fill(ap_list, asz_list, 25.0)
            if sh25 <= 0:
                continue

            row_base = {
                "sleeve_id": r.sleeve_id,
                "asset": asset,
                "slug": slug,
                "fire_us": fire_us,
                "direction": direction,
                "won": int(r.won),
                "ask0": ask0,
                "bid0": bid0,
                "total_depth_usd_25_levels": total_depth_usd,
            }

            for n in NOTIONALS:
                vwap, shares, usd, levels, under = book_walk_fill(ap_list, asz_list, n)
                if shares <= 0:
                    pnl = float("nan")
                    slip = float("nan")
                    depth_pct = float("nan")
                else:
                    pnl = float(shares * (1.0 - vwap) * 0.98 if r.won else -usd)
                    slip = (vwap - v25) / v25 * 1e4 if v25 > 0 else float("nan")
                    depth_pct = (usd / total_depth_usd * 100.0) if total_depth_usd > 0 else float("nan")
                row_base.update({
                    f"vwap_at_{int(n)}": vwap,
                    f"shares_at_{int(n)}": shares,
                    f"usd_filled_at_{int(n)}": usd,
                    f"levels_at_{int(n)}": int(levels),
                    f"under_at_{int(n)}": int(under),
                    f"pnl_at_{int(n)}": pnl,
                    f"slippage_bps_at_{int(n)}": slip,
                    f"depth_pct_at_{int(n)}": depth_pct,
                })
            rows_asset.append(row_base)
        del books
        gc.collect()
        print(f"  walked {len(rows_asset):,} fires in {time.time()-t1:.1f}s")
        results.extend(rows_asset)

    df = pd.DataFrame(results)
    out = RES / "sleeve_notional_fill_simulation.csv"
    df.to_csv(out, index=False)
    print(f"\nwrote {out} ({len(df):,} rows)")

    # Per-sleeve summary
    rows = []
    for sid, grp in df.groupby("sleeve_id"):
        row = {"sleeve_id": sid, "asset": grp["asset"].iloc[0],
                "n_fires": len(grp)}
        for n in NOTIONALS:
            ni = int(n)
            row[f"avg_slip_bps_{ni}"] = grp[f"slippage_bps_at_{ni}"].mean()
            row[f"p90_slip_bps_{ni}"] = grp[f"slippage_bps_at_{ni}"].quantile(0.9)
            row[f"avg_depth_pct_{ni}"] = grp[f"depth_pct_at_{ni}"].mean()
            row[f"p90_depth_pct_{ni}"] = grp[f"depth_pct_at_{ni}"].quantile(0.9)
            row[f"under_pct_{ni}"] = grp[f"under_at_{ni}"].mean() * 100
            row[f"sum_pnl_{ni}"] = grp[f"pnl_at_{ni}"].sum()
            row[f"avg_pnl_{ni}"] = grp[f"pnl_at_{ni}"].mean()
            row[f"wr_{ni}"] = ((grp[f"pnl_at_{ni}"] > 0).mean())
        row["deploy_risk_250"] = (
            (row.get("p90_slip_bps_250", 0) > 50) or
            (row.get("p90_depth_pct_250", 0) > 30) or
            (row.get("under_pct_250", 0) > 5)
        )
        row["deploy_risk_2500"] = (
            (row.get("p90_slip_bps_2500", 0) > 50) or
            (row.get("p90_depth_pct_2500", 0) > 30) or
            (row.get("under_pct_2500", 0) > 5)
        )
        rows.append(row)
    summary = pd.DataFrame(rows)
    summary_out = RES / "sleeve_notional_fill_summary.csv"
    summary.to_csv(summary_out, index=False)
    print(f"wrote {summary_out}")
    print()
    print(summary[["sleeve_id", "asset", "n_fires",
                    "avg_slip_bps_25", "avg_slip_bps_250", "avg_slip_bps_2500",
                    "avg_depth_pct_25", "avg_depth_pct_250", "avg_depth_pct_2500",
                    "deploy_risk_250", "deploy_risk_2500"]].to_string(index=False))


if __name__ == "__main__":
    main()
