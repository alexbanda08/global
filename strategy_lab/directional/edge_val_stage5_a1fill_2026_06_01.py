"""
edge_val_stage5_a1fill_2026_06_01.py — fill test for the ONE survivor: A1 HL short-liq cascade (60s).

A1 predicts UP at ws_s when forced-BUY liq notional (Close Short + Open Long, method=market) over
[ws_s-60, ws_s] > T. The cascade ends at ws_s = slot_start - window (5/15 min BEFORE the slug opens),
so entering at slot_start+5s the Up token should still be ~0.50 (signal not yet priced) — unlike the
Stage-3/4 within-window flow trap (vwap 0.68-0.87). This tests whether A1's +8pp WR is tradeable.

Fill: engine_v2.fill_at_book Up @ fire=slot_start+5s ($25 walk, 85ms, spread<=0.05), pnl 0.07 winner-only.
Window: Apr24->May27 (HL liq coverage). BTC+ETH.
Usage: C:/Python314/python.exe strategy_lab/directional/edge_val_stage5_a1fill_2026_06_01.py
"""
from __future__ import annotations
import sys, gc, math, time, traceback
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
from load import load_resolutions, load_hyperliquid_liquidations_full, load_orderbook_l25_streaming  # noqa: E402
from engine_v2 import LiveMimicConfig, fill_at_book  # noqa: E402

OUT = ROOT / "strategy_lab" / "directional" / "_results"
WIN = {"5m": 300, "15m": 900}
NOTIONAL = 25.0; SPREAD = 0.05; FEE = 0.07; OFFSET = 5
LO = int(pd.Timestamp("2026-04-24", tz="UTC").timestamp())
HI = int(pd.Timestamp("2026-05-27 13:30", tz="UTC").timestamp())


def stat(x):
    x = np.asarray(x, float); n = len(x)
    if n < 2:
        return (np.nan, np.nan)
    m = x.mean(); se = x.std(ddof=1) / np.sqrt(n)
    return m, (m / se if se else np.nan)


def pnl007(v, sh, won):
    return (1 - v) * sh * (1 - FEE * v) if won else -v * sh


def hl_buy_stream(coin):
    hl = load_hyperliquid_liquidations_full(coin)
    hl = hl[(hl["dir"].isin(["Close Short", "Open Long"])) & (hl["method"] == "market")]
    ts = (hl.time_exchange_us.values / 1e6).astype(float)
    val = (hl.price.astype(float) * hl["size"].astype(float)).values
    o = np.argsort(ts)
    return ts[o], val[o]


def run():
    t0 = time.time()
    res = load_resolutions()
    res = res[res.ticker.isin(["BTC", "ETH"]) & res.timeframe.isin(["5m", "15m"])].copy()
    res["slot_start"] = (res.slot_start_us // 1_000_000).astype(np.int64)
    res["ws_s"] = res.slot_start - res.timeframe.map(WIN).astype(np.int64)
    res["won_up"] = (res.outcome.astype(str).str.lower() == "up")
    res = res[(res.ws_s >= LO) & (res.ws_s < HI)]

    # compute A1 60s cascade sum at ws_s per row
    streams = {c: hl_buy_stream(c) for c in ["BTC", "ETH"]}
    res["casc60"] = 0.0
    for c in ["BTC", "ETH"]:
        ts, val = streams[c]
        cs = np.concatenate([[0.0], np.cumsum(val)])
        m = res.ticker == c
        a = res.loc[m, "ws_s"].values.astype(float)
        hi = np.searchsorted(ts, a, side="right"); lo = np.searchsorted(ts, a - 60, side="right")
        res.loc[m, "casc60"] = cs[hi] - cs[lo]

    base_up = float(res.won_up.mean())
    recs = []
    # only need L25 for qualifying slugs (casc60 > 1k) -> small set
    qual = res[res.casc60 > 1000].copy()
    print(f"A1 qualifying fires (casc60>1k): {len(qual)} ; base P(Up)={base_up:.4f}", flush=True)
    for asset in ["BTC", "ETH"]:
        for tf in ["5m", "15m"]:
            books = None
            try:
                sub = qual[(qual.ticker == asset) & (qual.timeframe == tf)]
                if sub.empty:
                    continue
                slugs = set(sub.slug.values)
                books = load_orderbook_l25_streaming(asset.lower(), slugs=slugs, subsample_1hz=False)
                cfg = LiveMimicConfig()
                for _, row in sub.iterrows():
                    ss = int(row.slot_start); won_up = bool(row.won_up)
                    fire_us = (ss + OFFSET) * 1_000_000
                    fill = fill_at_book(books, row.slug, "Up", fire_us, cfg=cfg, side="buy",
                                        spread_filter=SPREAD, notional_usd=NOTIONAL)
                    if fill is None:
                        continue
                    v = float(fill["vwap"]); sh = float(fill["shares"])
                    recs.append(dict(slug=row.slug, asset=asset, tf=tf, casc60=float(row.casc60),
                                     vwap=v, shares=sh, won=won_up, pnl=pnl007(v, sh, won_up)))
            except Exception:
                print(f" !! FAIL {asset} {tf}"); traceback.print_exc()
            finally:
                del books; gc.collect()
    F = pd.DataFrame(recs)
    F.to_parquet(OUT / "edge_val_stage5_a1fill_2026_06_01.parquet", index=False)

    def cell(g):
        p = g.pnl.to_numpy(); m, t = stat(p)
        return dict(n=len(g), wr=round(100 * g.won.mean(), 1), vwap=round(g.vwap.mean(), 3),
                    per_tr=round(m, 3), total=round(p.sum(), 1), t=round(t, 2))

    print("\n" + "=" * 84)
    print("STAGE 5 — A1 HL short-cascade 60s, REAL Up fill @ slot_start+5s, 0.07 fee")
    print("=" * 84)
    rows = []
    for T in [1000, 10000, 50000]:
        g = F[F.casc60 > T]
        if len(g) >= 10:
            d = cell(g); d.update(param=f"casc60>{T}"); rows.append(d)
    P = pd.DataFrame(rows)
    print(P[["param", "n", "wr", "vwap", "per_tr", "total", "t"]].to_string(index=False))
    print(f"\nfills={len(F)} ; total {time.time()-t0:.0f}s")


if __name__ == "__main__":
    run()
