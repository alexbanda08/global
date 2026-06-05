"""
edge_val_stage4_l25_2026_06_01.py — STAGE 4: the DECISIVE L25-fill stage.

Two jobs:
(1) Put REAL L25 fills + 0.07 fee on the Stage-3 poly-flow fires (C4 CVD-follow, B1 VPIN).
    Stage 3 showed 67-89% directional WR — but that reads the move that ALREADY happened by
    fire_us=slot_start+offset, so the book has repriced. The mean entry vwap + $/tr will reveal
    whether any of that WR is tradeable edge or just "buy-after-the-move at the moved price".
(2) Test the remaining Tier-1 L25 depth gates as standalone directional signals at fire_us:
    C1  depth-decay ratio    = bid_total/ask_total (UP token) -> bet UP when bids>>asks
    C8  cross-token ask asym = (askN_UP - askN_DN)/(askN_UP + askN_DN) -> bet the THINNER-ask side
    (C2 depth-drain / C3 fleeting-OBI need multi-snapshot trajectories — deferred unless C1/C8 hit.)

Fill: engine_v2.fill_at_book ($25 walk, 85ms latency, spread<=0.05, native-10Hz L25), pnl 0.07 winner-only.
Anchor: fire_us = (slot_start + offset)*1e6, offset = 120s (5m) / 300s (15m) — same as Stage 3.
Window: Apr24 -> Jun1, BTC+ETH (deploy universe). Chunked L25 load (memory-safe).
Usage: C:/Python314/python.exe strategy_lab/directional/edge_val_stage4_l25_2026_06_01.py
"""
from __future__ import annotations
import sys, gc, math, time, traceback
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
from load import load_resolutions, load_orderbook_l25_streaming  # noqa: E402
from engine_v2 import LiveMimicConfig, fill_at_book  # noqa: E402

OUT = ROOT / "strategy_lab" / "directional" / "_results"
S3 = OUT / "edge_val_stage3_polyflow_features_2026_06_01.parquet"
WIN = {"5m": 300, "15m": 900}
OFFSET = {"5m": 120, "15m": 300}
NOTIONAL = 25.0; SPREAD = 0.05; FEE = 0.07
LO = int(pd.Timestamp("2026-04-24", tz="UTC").timestamp())
HI = int(pd.Timestamp("2026-06-01 09:00", tz="UTC").timestamp())
CHUNK_DAYS = 3


def norm_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def stat(x):
    x = np.asarray(x, float); n = len(x)
    if n < 2:
        return (np.nan, np.nan)
    m = x.mean(); se = x.std(ddof=1) / np.sqrt(n)
    return m, (m / se if se else np.nan)


def z_p(k, n, p0):
    if n == 0:
        return (np.nan, np.nan, np.nan)
    ph = k / n; se = math.sqrt(p0 * (1 - p0) / n)
    if se == 0:
        return (ph, np.nan, np.nan)
    z = (ph - p0) / se
    return (ph, z, 2 * (1 - norm_cdf(abs(z))))


def pnl007(v, sh, won):
    return (1 - v) * sh * (1 - FEE * v) if won else -v * sh


def book_depth_at(books, slug, outcome, ts_us, cfg):
    """sum bid/ask sizes over up-to-25 levels for one token at strict-asof ts (latency-shifted)."""
    from engine_v2 import find_book_strict
    bidx = books
    b = find_book_strict(bidx, slug, outcome, int(ts_us) + int(cfg.latency_ms * 1000),
                         max_staleness_us=cfg.max_book_staleness_us)
    if b is None:
        return None
    bs = np.asarray(b.get("bsz", []), float); az = np.asarray(b.get("asz", []), float)
    bp = np.asarray(b.get("bp", []), float); ap = np.asarray(b.get("ap", []), float)
    return dict(bid_sz=bs.sum(), ask_sz=az.sum(),
                bid_notional=float((bp * bs).sum()) if len(bp) == len(bs) else np.nan,
                ask_notional=float((ap * az).sum()) if len(ap) == len(az) else np.nan)


def run():
    t0 = time.time()
    feats = pd.read_parquet(S3)
    feats = feats[feats.asset.isin(["BTC", "ETH"])].copy()
    feats["vpin"] = np.where(feats.gross > 0, np.abs(feats.cvd) / feats.gross, 0.0)
    fmap = feats.set_index("slug")
    res = load_resolutions()
    res = res[res.ticker.isin(["BTC", "ETH"]) & res.timeframe.isin(["5m", "15m"])].copy()
    res["slot_start"] = (res.slot_start_us // 1_000_000).astype(np.int64)
    res["won_up"] = (res.outcome.astype(str).str.lower() == "up")
    res = res[(res.slot_start >= LO) & (res.slot_start < HI)]

    recs = []
    bounds = list(range(LO, HI, CHUNK_DAYS * 86400)) + [HI]
    for ci in range(len(bounds) - 1):
        clo, chi = bounds[ci], bounds[ci + 1]
        for asset in ["BTC", "ETH"]:
            for tf in ["5m", "15m"]:
                books = None
                try:
                    off = OFFSET[tf]
                    sub = res[(res.ticker == asset) & (res.timeframe == tf)
                              & (res.slot_start >= clo) & (res.slot_start < chi)]
                    sub = sub[sub.slug.isin(fmap.index)]
                    if sub.empty:
                        continue
                    slugs = set(sub.slug.values)
                    books = load_orderbook_l25_streaming(asset.lower(), slugs=slugs, subsample_1hz=False)
                    cfg = LiveMimicConfig()
                    for _, row in sub.iterrows():
                        slug = row.slug
                        ss = int(row.slot_start); won_up = bool(row.won_up)
                        fire_us = (ss + off) * 1_000_000
                        fr = fmap.loc[slug]
                        cvd = float(fr.cvd); vpin = float(fr.vpin); gross = float(fr.gross)
                        pred_up = cvd > 0
                        side = "Up" if pred_up else "Down"
                        # flow-fire fill (predicted side)
                        fill = fill_at_book(books, slug, side, fire_us, cfg=cfg, side="buy",
                                            spread_filter=SPREAD, notional_usd=NOTIONAL)
                        rec = dict(slug=slug, asset=asset, tf=tf, ss=ss, won_up=won_up,
                                   cvd=cvd, vpin=vpin, gross=gross, pred_up=pred_up,
                                   filled=fill is not None)
                        if fill is not None:
                            v = float(fill["vwap"]); sh = float(fill["shares"])
                            won = (pred_up == won_up)
                            rec.update(vwap=v, shares=sh, won=won, pnl=pnl007(v, sh, won))
                        # C1/C8 depth at fire (both tokens)
                        du = book_depth_at(books, slug, "Up", fire_us, cfg)
                        dd = book_depth_at(books, slug, "Down", fire_us, cfg)
                        if du and dd:
                            rec["c1_ratio_up"] = du["bid_sz"] / du["ask_sz"] if du["ask_sz"] > 0 else np.nan
                            au, ad = du["ask_notional"], dd["ask_notional"]
                            rec["c8_askasym"] = (au - ad) / (au + ad) if (au + ad) > 0 else np.nan
                        recs.append(rec)
                except Exception:
                    print(f"  !! FAIL {asset} {tf} {pd.to_datetime(clo,unit='s',utc=True):%m-%d}", flush=True)
                    traceback.print_exc()
                finally:
                    del books; gc.collect()
        print(f"[chunk {pd.to_datetime(clo,unit='s',utc=True):%m-%d}] recs={len(recs)} t={time.time()-t0:.0f}s", flush=True)

    F = pd.DataFrame(recs)
    F.to_parquet(OUT / "edge_val_stage4_l25_2026_06_01.parquet", index=False)
    filled = F[F.filled].copy()
    print(f"\nfills: {len(filled)}/{len(F)} ({100*len(filled)/max(len(F),1):.0f}%)")

    def cell(g):
        p = g.pnl.to_numpy(); m, t = stat(p)
        return dict(n=len(g), wr=round(100 * g.won.mean(), 1), vwap=round(g.vwap.mean(), 3),
                    per_tr=round(m, 3), total=round(p.sum(), 1), t=round(t, 2))

    pd.set_option("display.width", 200)
    print("\n" + "=" * 92)
    print("STAGE 4 — REAL L25 FILLS on poly-flow fires (the trap test). $/tr after 0.07 fee.")
    print("If WR high but vwap high and per_tr ~0 -> the Stage-3 WR was 'move already happened', NOT edge.")
    print("=" * 92)
    rows = []
    for T in [50, 200, 500, 1000]:
        g = filled[np.abs(filled.cvd) > T]
        if len(g) >= 20:
            d = cell(g); d.update(gate="C4_cvd_follow", param=f"|cvd|>{T}"); rows.append(d)
    for vq in [0.5, 0.7, 0.9]:
        thr = filled.vpin.quantile(vq)
        g = filled[(filled.vpin >= thr) & (np.abs(filled.cvd) > 200)]
        if len(g) >= 20:
            d = cell(g); d.update(gate="B1_vpin_follow", param=f"vpin>=q{int(vq*100)}"); rows.append(d)
    P = pd.DataFrame(rows)
    print(P[["gate", "param", "n", "wr", "vwap", "per_tr", "total", "t"]].to_string(index=False))

    # ---- C1 / C8 depth gates: standalone directional WR (no fill needed) ----
    print("\n" + "=" * 92)
    print("STAGE 4 — L25 DEPTH GATES (standalone directional WR vs 0.5)")
    print("=" * 92)
    drows = []
    base = float(F.won_up.mean())
    dd = F[np.isfinite(F.get("c1_ratio_up", np.nan))]
    for thr in [1.2, 1.5, 2.0, 3.0]:
        # C1: bid>>ask on UP token -> bet UP ; ask>>bid -> bet DOWN
        up_q = dd.c1_ratio_up > thr; dn_q = dd.c1_ratio_up < (1 / thr)
        q = up_q | dn_q; pred_up = up_q
        n = int(q.sum())
        if n >= 20:
            k = int((pred_up[q] == dd.won_up[q]).sum()); wr, z, p = z_p(k, n, 0.5)
            drows.append(dict(gate="C1_depth_ratio", param=f"thr{thr}", n=n, wr=round(wr, 4),
                              lift_pp=round((wr - .5) * 100, 2), p=round(p, 4)))
    d8 = F[np.isfinite(F.get("c8_askasym", np.nan))]
    for thr in [0.2, 0.3, 0.5]:
        # thinner UP ask (asym<-thr) -> bet UP ; thinner DN ask (asym>thr) -> bet DOWN
        up_q = d8.c8_askasym < -thr; dn_q = d8.c8_askasym > thr
        q = up_q | dn_q; pred_up = up_q
        n = int(q.sum())
        if n >= 20:
            k = int((pred_up[q] == d8.won_up[q]).sum()); wr, z, p = z_p(k, n, 0.5)
            drows.append(dict(gate="C8_ask_asym", param=f"thr{thr}", n=n, wr=round(wr, 4),
                              lift_pp=round((wr - .5) * 100, 2), p=round(p, 4)))
    print(pd.DataFrame(drows).to_string(index=False))
    print(f"\nbase P(Up)={base:.4f} ; total {time.time()-t0:.0f}s")


if __name__ == "__main__":
    run()
