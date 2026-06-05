"""
path_overlay.py — add STOP-LOSS or HEDGE to the fast directional taker.

Base: fire 5s into window when |binance ret since slot_start|>=3bps, BUY leading side
($25 book-walk), HOLD to resolution. ~37% lose the full entry. We test two overlays
on the native-10Hz book PATH between fire and slot_end:

  STOP-LOSS(s): monitor the leading side's best BID; if it drops to <= entry_vwap - s,
    SELL the shares at that bid (cut the loss). Else hold to resolution.
  HEDGE(r):     monitor binance; if it REVERSES by >= r bps against the entry move,
    BUY the OTHER side at its (lag-stale) ask to complete a pair, hold to resolution
    -> redeem $1/pair. realized = shares*1 - usd_in - usd_hedge (loss capped at sum-1).

Fees: production 2%-on-winning-profit-only at resolution; mid-window sell/hedge taker
legs modeled fee-free (conservative-ish; crypto per-fill fee ~0 per CLAUDE.md).
Entry uses engine_v2 $25 book-walk; path exit/hedge fills use top-of-book (level 0).

Usage: py -X utf8 strategy_lab/directional/path_overlay.py
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
from load import load_resolutions, load_orderbook_l25_streaming  # noqa: E402
from engine_v2 import LiveMimicConfig, fill_at_book  # noqa: E402

CANON = ROOT / "data" / "v4" / "canonical"
OUT = ROOT / "strategy_lab" / "directional" / "_results"
WIN = {"5m": 300, "15m": 900}
OFFSET = 5; SPREAD = 0.05; NOTIONAL = 25.0; MIN_RET = 3.0
IS_CUTOFF = int(pd.Timestamp("2026-05-15", tz="UTC").timestamp())
STOPS = [0.10, 0.15, 0.20]
HEDGES = [3.0, 5.0]
SYM = {"BTC": "BINANCE_SPOT_BTC_USDT", "ETH": "BINANCE_SPOT_ETH_USDT", "SOL": "BINANCE_SPOT_SOL_USDT"}
CHUNK = 5 * 86400


def binance_1s(asset):
    df = pd.read_parquet(CANON / "klines_1s.parquet",
                         columns=["time_period_start_us", "price_close", "symbol_id", "source", "period_id"])
    df = df[(df.symbol_id == SYM[asset]) & (df.source == "binance-spot-ws") & (df.period_id == "1SEC")].sort_values("time_period_start_us")
    return (df.time_period_start_us.values.astype(np.int64) + 1_000_000), df.price_close.values.astype(float)


def asof1(ts, v, t):
    i = int(np.searchsorted(ts, int(t), side="right")) - 1
    return float(v[i]) if i >= 0 else np.nan


def asof_vec(ts, v, T):
    i = np.searchsorted(ts, T.astype(np.int64), side="right") - 1
    out = np.full(len(T), np.nan); ok = i >= 0; out[ok] = v[i[ok]]; return out


def run():
    res = load_resolutions(); res["slug"] = res["slug"].astype(str)
    cfg = LiveMimicConfig()
    bz = {a: binance_1s(a) for a in ["BTC", "ETH", "SOL"]}
    lo = int(pd.Timestamp("2026-04-22", tz="UTC").timestamp())
    hi = int(pd.Timestamp("2026-05-30", tz="UTC").timestamp())
    bounds = list(range(lo, hi, CHUNK)) + [hi]
    rows = []
    for i in range(len(bounds) - 1):
        clo, chi = bounds[i], bounds[i + 1]
        for asset in ["BTC", "ETH", "SOL"]:
            be, bc = bz[asset]
            for tf in ["5m", "15m"]:
                pref = f"{asset.lower()}-updown-{tf}-"
                sub = res[(res.ticker == asset) & (res.timeframe == tf)]
                sub = sub[sub.slug.str.startswith(pref)].copy()
                sub["ss"] = sub.slug.str.rsplit("-", n=1).str[-1].astype(np.int64)
                sub = sub[(sub.ss >= clo) & (sub.ss < chi)]
                if sub.empty: continue
                slugs = set(sub.slug); won_up = dict(zip(sub.slug, sub.outcome.str.lower() == "up"))
                books = load_orderbook_l25_streaming(asset.lower(), slugs=slugs, subsample_1hz=False)
                for ss, slug in zip(sub.ss.values.astype(np.int64), sub.slug.values):
                    fire = (ss + OFFSET) * 1_000_000
                    slot_end = (ss + WIN[tf]) * 1_000_000
                    px0 = asof1(be, bc, ss * 1_000_000); pxf = asof1(be, bc, fire)
                    if not (np.isfinite(px0) and np.isfinite(pxf)): continue
                    ret = pxf / px0 - 1.0
                    if abs(ret) * 1e4 < MIN_RET: continue
                    lead = "Up" if ret > 0 else "Down"
                    other = "Down" if lead == "Up" else "Up"
                    fill = fill_at_book(books, slug, lead, int(fire), cfg=cfg, side="buy",
                                        spread_filter=SPREAD, notional_usd=NOTIONAL)
                    if fill is None: continue
                    shares = float(fill["shares"]); usd_in = float(fill["usd"]); vwap = usd_in / shares
                    won = (ret > 0) == won_up[slug]
                    base = (shares - usd_in) * 0.98 if won else -usd_in

                    lb = books.get((slug, lead)); ob = books.get((slug, other))
                    # leading-side bid path after fire
                    rec = {"slot_start": int(ss), "base": base}
                    if lb is not None:
                        lts = lb[0].astype(np.int64); lbid = lb[3][:, 0].astype(float)
                        m = (lts > fire) & (lts <= slot_end) & np.isfinite(lbid) & (lbid > 0)
                        lts2, lbid2 = lts[m], lbid[m]
                        for s in STOPS:
                            hit = np.where(lbid2 <= (vwap - s))[0]
                            if len(hit):
                                sell_bid = lbid2[hit[0]]
                                rec[f"stop{int(s*100)}"] = shares * sell_bid - usd_in
                            else:
                                rec[f"stop{int(s*100)}"] = base
                    # hedge: binance reversal -> buy other side at ask, hold pair
                    if ob is not None:
                        ots = ob[0].astype(np.int64); oask = ob[1][:, 0].astype(float)
                        m = (ots > fire) & (ots <= slot_end) & np.isfinite(oask) & (oask > 0) & (oask < 1)
                        ots2, oask2 = ots[m], oask[m]
                        bret = asof_vec(be, bc, ots2) / px0 - 1.0  # ret since open at each monitor tick
                        for r in HEDGES:
                            # reversal against entry: if entered Up (ret>0), trigger when ret drops <= ret_entry - r/1e4... use ret since OPEN dropping below 0 by r? use move-against = entry_ret - cur_ret >= r
                            against = (ret - bret) * 1e4 if ret > 0 else (bret - ret) * 1e4
                            hit = np.where(against >= r)[0]
                            if len(hit):
                                a = oask2[hit[0]]
                                usd_h = shares * a  # complete equal shares
                                # pair of `shares` redeems $1 each at resolution (one side wins)
                                rec[f"hedge{int(r)}"] = shares * 1.0 - usd_in - usd_h
                            else:
                                rec[f"hedge{int(r)}"] = base
                    rows.append(rec)
        print(f"[chunk {pd.to_datetime(clo,unit='s',utc=True):%m-%d}] cum={len(rows)}", flush=True)
    df = pd.DataFrame(rows)
    df["period"] = np.where(df.slot_start < IS_CUTOFF, "IS", "OOS")
    df.to_csv(OUT / "path_overlay.csv", index=False)
    cols = ["base"] + [f"stop{int(s*100)}" for s in STOPS] + [f"hedge{int(r)}" for r in HEDGES]
    print("\n" + "=" * 92)
    print(f"PATH OVERLAYS on fast-taker (|ret|>=3bps, offset {OFFSET}s, $25) — mean pnl/trade & t-stat")
    print("=" * 92)
    for per in ["IS", "OOS"]:
        g = df[df.period == per]
        print(f"\n--- {per}  (n={len(g)}) ---")
        for c in cols:
            x = g[c].dropna().to_numpy()
            if len(x) < 10: continue
            m = x.mean(); t = m / (x.std(ddof=1)/np.sqrt(len(x))) if x.std() else np.nan
            wr = 100*(x > 0).mean(); worst = x.min()
            print(f"  {c:<9} mean={m:+.4f}  t={t:5.2f}  win%={wr:4.1f}  worst={worst:+.1f}  total={x.sum():+.0f}")
    print(f"\nwrote {OUT/'path_overlay.csv'}")


if __name__ == "__main__":
    run()
