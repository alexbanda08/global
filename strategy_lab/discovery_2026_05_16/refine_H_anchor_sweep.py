"""
Refine Strategy H — sweep entry anchors + edge thresholds with REAL L25 fills.

Goal: find the anchor where (a) book hasn't fully repriced, (b) signal still has time
to play out, (c) per-trade PnL is positive after 2% fee.

Anchors tested (us before slot_end):
    5m markets : 30, 60, 90, 120, 150 (= ws_s+120 == slot_start = slot_start = slot_end-300)
    15m markets: 30, 60, 90, 120, 180, 300, 600, 900 (= slot_start)

Edge thresholds: 0.07, 0.08, 0.09, 0.10, 0.12, 0.15, 0.20
Fair-p horizon (binance window): 120s, 300s, 600s
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "discovery_2026_05_16"))

from load import (
    load_resolutions, load_klines_asof, load_orderbook_l25_streaming, asof_strict,
)
from harness import (
    SPREAD_FILTER, NOTIONAL, FEE_RATE, get_klines, walk_asks, get_book_at,
)

OUT_CSV = Path(__file__).parent / "refine_H_results.csv"

ASSETS = ["BTC", "ETH", "SOL"]

# ----- Fair-p model -----
def fair_p_up(ret: float, sigma_norm: float) -> float:
    if not np.isfinite(ret) or sigma_norm <= 0:
        return 0.5
    z = ret / sigma_norm
    p = 0.5 + 0.5 * np.tanh(2.0 * z)
    return float(np.clip(p, 0.10, 0.90))


def compute_sigma_30min(asset: str, fire_us: int) -> float:
    """Realized std of 1MIN returns over preceding 30min. Used to z-score the obs return."""
    end_us, prices = get_klines(asset, "binance-spot-ws", "1MIN")
    idx_end = int(np.searchsorted(end_us, fire_us, side="right") - 1)
    if idx_end < 30:
        return 0.0
    sl = prices[idx_end - 30 + 1 : idx_end + 1]
    if len(sl) < 5:
        return 0.0
    rets = np.diff(np.log(sl))
    rets = rets[np.isfinite(rets)]
    if len(rets) < 5:
        return 0.0
    return float(np.std(rets))


# ----- Run sweep -----
def run_anchor(tf: str, anchor_offset_s: int, edge_thrs: list[float],
               horizons_s: list[int], n_per_asset: int = 1500) -> pd.DataFrame:
    """
    For a given timeframe + anchor offset (seconds before slot_end), sweep
    edge thresholds and binance-momentum horizons. Returns long-format DF.
    """
    res = load_resolutions(timeframes=[tf])
    # Sample uniformly across time per asset (deterministic)
    sampled = []
    for a in ASSETS:
        sub = res[res.ticker == a].sort_values("slot_start_us").copy()
        if len(sub) > n_per_asset:
            idx = np.linspace(0, len(sub) - 1, n_per_asset).astype(int)
            sub = sub.iloc[idx]
        sampled.append(sub)
    res = pd.concat(sampled, ignore_index=True)
    res["entry_us"] = res["slot_end_us"] - anchor_offset_s * 1_000_000

    # Per-asset: load L25 in batches, then evaluate all trades.
    rows = []
    for asset in ASSETS:
        asset_res = res[res.ticker == asset].copy()
        slugs = set(asset_res.slug.unique())
        # batch L25 load
        BATCH = 500
        slugs_list = list(slugs)
        books: dict = {}
        for i in range(0, len(slugs_list), BATCH):
            chunk = set(slugs_list[i : i + BATCH])
            bks = load_orderbook_l25_streaming(asset.lower(), slugs=chunk, subsample_1hz=True)
            books.update(bks)
        # binance klines
        end_us, prices = get_klines(asset, "binance-spot-ws", "1MIN")
        SPREAD = SPREAD_FILTER[asset]

        for _, r in asset_res.iterrows():
            entry_us = int(r["entry_us"])
            slot_start_us = int(r["slot_start_us"])
            # Compute fair-p for each horizon
            sigma = compute_sigma_30min(asset, entry_us)
            for horizon_s in horizons_s:
                obs_lo_us = max(slot_start_us, entry_us - horizon_s * 1_000_000)
                p_now = asof_strict(end_us, prices, entry_us)
                p_then = asof_strict(end_us, prices, obs_lo_us)
                if not (np.isfinite(p_now) and np.isfinite(p_then) and p_then > 0):
                    continue
                ret_obs = p_now / p_then - 1.0
                fair_p = fair_p_up(ret_obs, sigma)

                # Book lookup at entry_us — both sides
                snap_up = get_book_at(books, r["slug"], "Up", entry_us)
                if snap_up is None:
                    continue
                ap_up, asz_up, bp_up, bsz_up = snap_up
                ap0_up = float(ap_up[0]) if np.isfinite(ap_up[0]) else np.nan
                bp0_up = float(bp_up[0]) if np.isfinite(bp_up[0]) else np.nan
                if not (np.isfinite(ap0_up) and np.isfinite(bp0_up)):
                    continue
                if (ap0_up - bp0_up) > SPREAD:
                    continue   # spread filter
                mid_up = (ap0_up + bp0_up) / 2
                p_clob_up = mid_up

                # For each edge threshold, generate signal + fill
                for thr in edge_thrs:
                    edge = fair_p - p_clob_up
                    if abs(edge) < thr:
                        continue
                    if edge > 0:
                        side = "Up"; signal = "UP"
                        ap, asz = list(ap_up), list(asz_up)
                    else:
                        side = "Down"; signal = "DOWN"
                        snap_dn = get_book_at(books, r["slug"], "Down", entry_us)
                        if snap_dn is None:
                            continue
                        ap_dn, asz_dn, _, _ = snap_dn
                        ap, asz = list(ap_dn), list(asz_dn)
                    vwap, shares, spent, under = walk_asks(ap, asz, NOTIONAL)
                    if under or not np.isfinite(vwap) or shares <= 0:
                        continue
                    won = int(signal == r["outcome"].upper())
                    profit_raw = shares * (won - vwap)
                    fee = max(profit_raw, 0.0) * FEE_RATE
                    pnl = profit_raw - fee
                    rows.append(dict(
                        tf=tf, anchor_off_s=anchor_offset_s, horizon_s=horizon_s,
                        thr=thr, asset=asset, slug=r["slug"], outcome=r["outcome"],
                        signal=signal, edge=edge, fair_p=fair_p, p_clob_up=p_clob_up,
                        vwap=vwap, shares=shares, won=won, pnl=pnl,
                    ))
    return pd.DataFrame(rows)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", choices=["5m","15m","all"], default="all")
    ap.add_argument("--n-per-asset", type=int, default=1500)
    args = ap.parse_args()

    t0 = time.time()
    all_rows: list[pd.DataFrame] = []

    EDGE_THRS = [0.07, 0.08, 0.09, 0.10, 0.12, 0.15, 0.20]
    HORIZONS = [120, 300, 600]

    sweeps_5m = [("5m", 30), ("5m", 60), ("5m", 90), ("5m", 120), ("5m", 150)]
    sweeps_15m = [("15m", 30), ("15m", 60), ("15m", 90), ("15m", 120),
                  ("15m", 180), ("15m", 240), ("15m", 270), ("15m", 300),
                  ("15m", 330), ("15m", 360), ("15m", 420), ("15m", 480),
                  ("15m", 600), ("15m", 900)]
    if args.tf == "5m":
        sweeps = sweeps_5m
    elif args.tf == "15m":
        sweeps = sweeps_15m
    else:
        sweeps = sweeps_5m + sweeps_15m

    for tf, anchor in sweeps:
        t1 = time.time()
        out_file = OUT_CSV.parent / f"refine_H_{tf}_anchor{anchor}.parquet"
        if out_file.exists():
            print(f"[{tf} slot_end-{anchor:>3}s] EXISTS, skip")
            continue
        print(f"[{tf} slot_end-{anchor:>3}s] running...", flush=True)
        df = run_anchor(tf, anchor, EDGE_THRS, HORIZONS, n_per_asset=args.n_per_asset)
        df_n = 0 if df is None else len(df)
        print(f"   -> {df_n} fires in {time.time()-t1:.1f}s")
        if df is not None and len(df):
            df.to_parquet(out_file, index=False)
            all_rows.append(df)
    out = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()
    print(f"\nTOTAL fires: {len(out)}  in {time.time()-t0:.1f}s")
    if len(out):
        out.to_parquet(OUT_CSV.with_suffix(".parquet"), index=False)
        agg = (
            out.groupby(["tf","anchor_off_s","horizon_s","thr"])
               .agg(n=("won","size"), hit=("won","mean"), pnl=("pnl","sum"),
                    pnl_per_trade=("pnl","mean"), median_vwap=("vwap","median"))
               .round(4).reset_index()
               .sort_values("pnl", ascending=False)
        )
        agg.to_csv(OUT_CSV, index=False)
        print(f"\nTop 25 configs by total PnL (n>=200):")
        top = agg[agg["n"] >= 200].head(25)
        print(top.to_string(index=False))
        print()
        print(f"Top 25 by pnl_per_trade (n>=200):")
        print(agg[agg["n"] >= 200].nlargest(25, "pnl_per_trade").to_string(index=False))


if __name__ == "__main__":
    main()
