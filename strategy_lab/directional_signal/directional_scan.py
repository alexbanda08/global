"""
Directional Up/Down strategy backtest — STAGE 1: feature + fill scan.

Decoded directional wallets reduce to ONE edge: Binance leads the Chainlink
oracle that settles Polymarket up-down markets. Two expressions:
  - cl_basis: (binance - chainlink_rtds)/chainlink  → buy the leading side
  - momentum: ema9_slope / short return sign        → buy the trending side

This script does the EXPENSIVE part once: for every resolved slug in
(asset, tf), at several decision offsets into the window, it records the causal
signals AND the real book fills (native 10Hz L25, engine_v2) for BOTH Up and
Down. The cheap strategy eval + gates + plateau sweeps then operate on this
table (eval_strategies.py) — no re-walking the book per parameter.

Conventions (root CLAUDE.md):
  - L25 native 10Hz: subsample_1hz=False (MANDATORY).
  - Outcome truth = chainlink resolutions `outcome`.
  - Signals strictly causal (asof <= fire_us). Binance 1s for price/return,
    chainlink RTDS for the oracle, 1m closes for ema slope.
  - Fills config-independent (vwap/shares/usd); fee applied later (Legacy vs LiveMimic).
  - Cross-token spread metric (live def) = abs(up_vwap5 - (1 - dn_vwap5)) on $5 walks.

Output: data/v4/canonical/_results/dirscan_<asset>_<tf>.parquet

Usage:
  py -3 strategy_lab/directional_signal/directional_scan.py --asset btc --tf 5m
  py -3 strategy_lab/directional_signal/directional_scan.py --asset btc --tf 5m --day-lo 1779 --day-hi 1781   # day idx range (slot_start_s//86400)
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
from load import (load_resolutions, load_klines_asof, load_klines_1s,  # noqa: E402
                  load_chainlink_rtds, load_orderbook_l25_streaming)
from engine_v2 import LegacyConfig, fill_at_book  # noqa: E402

OUT = ROOT / "data" / "v4" / "canonical" / "_results"
OUT.mkdir(parents=True, exist_ok=True)
CFG = LegacyConfig()  # fills are config-independent; pass spread_filter=None to record raw

WINDOW_S = {"5m": 300, "15m": 900}
OFFSETS = {  # decision offsets (s into window). leave >=60s before settle.
    "5m": [30, 60, 120, 180, 240],
    "15m": [60, 180, 300, 600, 840],
}
NOTIONAL = 25.0
SPREAD_PROBE_USD = 5.0  # for cross-token spread metric (matches live $5 walk)


def _ema_last(x: np.ndarray, span: int) -> float:
    if len(x) == 0:
        return np.nan
    a = 2.0 / (span + 1.0)
    e = x[0]
    for v in x[1:]:
        e = a * v + (1 - a) * e
    return e


def load_binance_1s_arrays(asset: str):
    df = load_klines_1s(asset)
    # pick binance spot source if multiple
    if "source" in df.columns and df["source"].nunique() > 1:
        srcs = df["source"].astype(str)
        pref = srcs[srcs.str.contains("binance", case=False) & srcs.str.contains("spot", case=False)]
        if len(pref):
            df = df[srcs.isin(set(pref.unique()))]
    close_col = "price_close" if "price_close" in df.columns else "close"
    end_col = "time_period_end_us" if "time_period_end_us" in df.columns else "time_close_us"
    df = df[[end_col, close_col]].dropna().sort_values(end_col)
    return df[end_col].to_numpy(np.int64), df[close_col].to_numpy(np.float64)


def load_chainlink_arrays(asset: str):
    df = load_chainlink_rtds(asset)
    tcol = "timestamp_us" if "timestamp_us" in df.columns else [c for c in df.columns if c.endswith("_us")][0]
    pcol = "price" if "price" in df.columns else [c for c in df.columns if "price" in c.lower()][0]
    df = df[[tcol, pcol]].dropna().sort_values(tcol)
    return df[tcol].to_numpy(np.int64), df[pcol].to_numpy(np.float64)


def asof(end_us: np.ndarray, val: np.ndarray, t: int):
    pos = np.searchsorted(end_us, t, side="right") - 1
    return val[pos] if pos >= 0 else np.nan


def signal_at(fire_us: int, b_end, b_close, c_end, c_px, m_end, m_close):
    bin_px = asof(b_end, b_close, fire_us)
    cl_px = asof(c_end, c_px, fire_us)
    bin_60 = asof(b_end, b_close, fire_us - 60_000_000)
    cl_basis_bps = (bin_px - cl_px) / cl_px * 1e4 if cl_px and cl_px == cl_px else np.nan
    ret_60s_bps = (bin_px / bin_60 - 1) * 1e4 if bin_60 and bin_60 == bin_60 else np.nan
    # ema9 slope on 1m closes
    pos = np.searchsorted(m_end, fire_us, side="right") - 1
    ema9_slope_bps = np.nan
    if pos >= 21:
        w = m_close[pos - 29: pos + 1] if pos >= 29 else m_close[: pos + 1]
        e_now = _ema_last(w, 9)
        e_prev = _ema_last(w[:-3], 9) if len(w) > 3 else e_now
        ema9_slope_bps = (e_now - e_prev) / e_prev * 1e4 if e_prev else np.nan
    return bin_px, cl_px, cl_basis_bps, ret_60s_bps, ema9_slope_bps


def fill_side(books, slug, oc, fire_us):
    """Return (vwap25, shares, usd, ask0, bid0, vwap5) — raw, no spread filter."""
    f = fill_at_book(books, slug, oc, fire_us, cfg=CFG, spread_filter=None, notional_usd=NOTIONAL)
    if f is None:
        return None
    f5 = fill_at_book(books, slug, oc, fire_us, cfg=CFG, spread_filter=None, notional_usd=SPREAD_PROBE_USD)
    vwap5 = f5["vwap"] if f5 else f["vwap"]
    return (f["vwap"], f["shares"], f["usd"], f["ask0"], f["bid0"], vwap5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", required=True)
    ap.add_argument("--tf", required=True)
    ap.add_argument("--day-lo", type=int, default=None, help="min day idx (slot_start_s//86400)")
    ap.add_argument("--day-hi", type=int, default=None, help="max day idx inclusive")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    asset, tf = args.asset.lower(), args.tf.lower()
    win = WINDOW_S[tf]
    offsets = OFFSETS[tf]

    res = load_resolutions()
    res = res[res["slug"].astype(str).str.startswith(f"{asset}-updown-{tf}-")].copy()
    res["slot_start_s"] = res["slug"].str.rsplit("-", n=1).str[-1].astype(np.int64)
    res["day_idx"] = res["slot_start_s"] // 86_400
    if args.day_lo is not None:
        res = res[res["day_idx"] >= args.day_lo]
    if args.day_hi is not None:
        res = res[res["day_idx"] <= args.day_hi]
    res = res.sort_values("slot_start_s")
    print(f"{asset}-{tf}: {len(res)} resolved slugs, days {res['day_idx'].min()}..{res['day_idx'].max()}")

    print("  loading binance 1s + chainlink + 1m arrays...")
    b_end, b_close = load_binance_1s_arrays(asset)
    c_end, c_px = load_chainlink_arrays(asset)
    m_end, m_close = load_klines_asof(asset, source="binance-spot-ws", period_id="1MIN")

    rows = []
    for day, grp in res.groupby("day_idx"):
        slugs = set(grp["slug"])
        day_start = int(grp["slot_start_s"].min()) * 1_000_000
        day_end = (int(grp["slot_start_s"].max()) + win + 120) * 1_000_000
        books = load_orderbook_l25_streaming(
            asset, slugs=slugs, subsample_1hz=False,
            min_ts_us=day_start - 5_000_000, max_ts_us=day_end,
        )
        for r in grp.itertuples(index=False):
            ss_us = int(r.slot_start_s) * 1_000_000
            for off in offsets:
                fire_us = ss_us + off * 1_000_000
                bin_px, cl_px, clb, ret60, ema_sl = signal_at(
                    fire_us, b_end, b_close, c_end, c_px, m_end, m_close)
                up = fill_side(books, r.slug, "Up", fire_us)
                dn = fill_side(books, r.slug, "Down", fire_us)
                row = {
                    "slug": r.slug, "asset": asset, "tf": tf,
                    "slot_start_s": int(r.slot_start_s), "offset_s": off,
                    "fire_us": fire_us, "outcome_truth": r.outcome,
                    "strike": float(r.strike_price) if r.strike_price == r.strike_price else np.nan,
                    "bin_px": bin_px, "cl_px": cl_px,
                    "cl_basis_bps": clb, "ret_60s_bps": ret60, "ema9_slope_bps": ema_sl,
                    "px_vs_strike_bps": (bin_px - r.strike_price) / r.strike_price * 1e4
                    if (r.strike_price == r.strike_price and r.strike_price) else np.nan,
                }
                if up:
                    row.update({"u_vwap": up[0], "u_shares": up[1], "u_usd": up[2],
                                "u_ask0": up[3], "u_bid0": up[4], "u_vwap5": up[5], "u_ok": True})
                else:
                    row["u_ok"] = False
                if dn:
                    row.update({"d_vwap": dn[0], "d_shares": dn[1], "d_usd": dn[2],
                                "d_ask0": dn[3], "d_bid0": dn[4], "d_vwap5": dn[5], "d_ok": True})
                else:
                    row["d_ok"] = False
                rows.append(row)
        del books
        print(f"    day {day}: {len(grp)} slugs done (rows so far {len(rows)})", flush=True)

    df = pd.DataFrame(rows)
    out = args.out or (OUT / f"dirscan_{asset}_{tf}.parquet")
    df.to_parquet(out, index=False)
    fill_rate_up = df["u_ok"].mean() if "u_ok" in df else 0
    print(f"\n  {len(df)} rows, Up fill-rate {fill_rate_up*100:.1f}%  -> {out}")


if __name__ == "__main__":
    main()
