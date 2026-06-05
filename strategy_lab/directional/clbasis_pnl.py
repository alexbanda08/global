"""
clbasis_pnl.py — Pass 2: does buying the binance-leading side actually PROFIT?

WR alone is not edge: buying a token at entry_px that wins with prob WR has
EV/share = WR*(1-ep)*0.98 - (1-WR)*ep. You only profit if WR > ~entry_px (the
market must UNDERPRICE the move's persistence — which is the binance->chainlink
lag thesis). This measures realized PnL on the broad universe.

Fire @ slot_start+offset. Leading side from a binance signal (px_vs_strike or
ret_3m). entry_px = last polymarket trade on the leading-side token at-or-before
fire_us (canonical trades_polymarket, fresh to May 28). Outcome = chainlink.
Fee = LegacyConfig (2% on winning profit only).

Usage: py -X utf8 strategy_lab/directional/clbasis_pnl.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_resolutions, load_klines_asof, load_trades  # noqa: E402

OUT = ROOT / "strategy_lab" / "directional" / "_results"
OUT.mkdir(parents=True, exist_ok=True)
WIN = {"5m": 300, "15m": 900}
EP_LO, EP_HI = 0.55, 0.92
OFFSETS = [60, 120]
SIGNALS = ["px_vs_strike", "ret_3m"]


def asof_idx(a, t): return np.searchsorted(a, t.astype(np.int64), side="right") - 1


def kline_signals(asset):
    e, c = load_klines_asof(asset, "binance-spot-ws", "1MIN")
    e = e.astype(np.int64); c = c.astype(float)
    ret3 = np.full_like(c, np.nan); ret3[3:] = (c[3:] / c[:-3] - 1) * 1e4
    return e, c, ret3


def trade_price_lookup(asset, slugset):
    """dict (slug,outcome_lower)->(ts_us sorted, price) from canonical trades."""
    tr = load_trades(asset)
    cols = {c.lower(): c for c in tr.columns}
    sc = cols.get("slug"); oc = cols.get("outcome"); tc = cols.get("timestamp_us"); pc = cols.get("price")
    tr = tr[[sc, oc, tc, pc]].copy()
    tr.columns = ["slug", "outcome", "ts", "price"]
    tr["slug"] = tr["slug"].astype(str)
    tr = tr[tr["slug"].isin(slugset)]
    tr["outcome"] = tr["outcome"].astype(str).str.lower()
    tr["ts"] = pd.to_numeric(tr["ts"], errors="coerce")
    tr["price"] = pd.to_numeric(tr["price"], errors="coerce")
    tr = tr.dropna(subset=["ts", "price"]).sort_values(["slug", "outcome", "ts"])
    d = {}
    for (slug, oc2), g in tr.groupby(["slug", "outcome"]):
        d[(slug, oc2)] = (g["ts"].to_numpy().astype(np.int64), g["price"].to_numpy())
    return d


def entry_px(d, slug, side_lower, fire_us):
    arr = d.get((slug, side_lower))
    if arr is None:
        return np.nan
    ts, pr = arr
    i = int(np.searchsorted(ts, int(fire_us), side="right")) - 1
    return float(pr[i]) if i >= 0 else np.nan


def run():
    res = load_resolutions(); res["slug"] = res["slug"].astype(str)
    rows = []; buckets = []
    for asset in ["BTC", "ETH", "SOL"]:
        e, c, ret3 = kline_signals(asset)
        ra = res[res.ticker == asset]
        slugset = set(ra.slug)
        d = trade_price_lookup(asset, slugset)
        for tf in ["5m", "15m"]:
            sub = ra[ra.timeframe == tf]
            if sub.empty:
                continue
            ss = sub.slot_start_us.to_numpy().astype(np.int64)
            up = (sub.outcome.str.lower() == "up").to_numpy()
            strike = pd.to_numeric(sub.strike_price, errors="coerce").to_numpy()
            slugs = sub.slug.to_numpy()
            for off in OFFSETS:
                if off >= WIN[tf]:
                    continue
                tgt = ss + off * 1_000_000
                ki = asof_idx(e, tgt)
                px = np.where(ki >= 0, c[ki], np.nan)
                r3 = np.where(ki >= 3, ret3[ki], np.nan)
                pvs = (px - strike) / strike * 1e4
                for sig_name, sig in [("px_vs_strike", pvs), ("ret_3m", r3)]:
                    recs = []
                    for i in range(len(slugs)):
                        s = sig[i]
                        if not np.isfinite(s) or abs(s) < 1e-9:
                            continue
                        lead = "up" if s > 0 else "down"
                        ep = entry_px(d, slugs[i], lead, tgt[i])
                        if not np.isfinite(ep) or ep < EP_LO or ep > EP_HI:
                            continue
                        won = (s > 0) == up[i]
                        pnl = (1 - ep) * 0.98 if won else -ep   # per share, LegacyConfig
                        recs.append((won, ep, pnl))
                        bk = "[.55,.65)" if ep < .65 else "[.65,.75)" if ep < .75 else "[.75,.85)" if ep < .85 else "[.85,.92]"
                        buckets.append(dict(asset=asset, tf=tf, off=off, sig=sig_name,
                                            bucket=bk, won=won, pnl=pnl))
                    if len(recs) < 20:
                        continue
                    arr = np.array(recs, dtype=float)
                    wonv, epv, pnlv = arr[:, 0], arr[:, 1], arr[:, 2]
                    rows.append(dict(asset=asset, tf=tf, offset=off, signal=sig_name,
                                     n=len(recs), wr=round(100 * wonv.mean(), 1),
                                     mean_ep=round(epv.mean(), 3),
                                     edge_wr_minus_ep=round(wonv.mean() - epv.mean(), 3),
                                     pnl_per_share=round(pnlv.mean(), 4),
                                     total=round(pnlv.sum(), 1)))
    df = pd.DataFrame(rows); df.to_csv(OUT / "clbasis_pnl.csv", index=False)
    bdf = pd.DataFrame(buckets)
    pd.set_option("display.width", 220)
    print("=" * 100)
    print("DIRECTIONAL TAKER PnL — buy binance-leading side, entry_px in [0.55,0.92], LegacyConfig fee")
    print("=" * 100)
    print("per-share PnL: won=(1-ep)*0.98, lost=-ep.  edge = WR - mean_entry_px (must be >0 to profit)")
    print(df.sort_values("pnl_per_share", ascending=False).to_string(index=False))
    if not bdf.empty:
        print("\nPnL by entry_px bucket (pooled, offset 60+120, both signals):")
        g = bdf.groupby("bucket").agg(n=("pnl", "size"), wr=("won", lambda x: round(100*x.mean(),1)),
                                      pnl_per_share=("pnl", lambda x: round(x.mean(),4)),
                                      total=("pnl", lambda x: round(x.sum(),1)))
        print(g.to_string())
    tot = df.total.sum() if not df.empty else 0
    print(f"\nGRAND TOTAL per-share PnL across cells: {tot:+.1f}")
    print(f"wrote {OUT/'clbasis_pnl.csv'}")


if __name__ == "__main__":
    run()
