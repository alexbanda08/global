"""
l25_ask_latency_test.py — DECISIVE test: does a fast taker get STALE L25 asks?

Hypothesis (the wallets' edge + the colo question): right after Binance moves, the
resting Polymarket asks haven't repriced (they lag the chainlink oracle), so a FAST
taker buys the leading side BELOW fair value. If true, edge = WR - entry_px > 0 at
SMALL offsets and decays to ~0 as offset grows (price catches up). If entry_px ~ WR
at every offset, the book is efficient and speed/colo buys nothing.

Per resolved slug, offsets {5,10,20,30,45,60}s into the window:
  ret = binance_1s(fire)/binance_1s(slot_start) - 1   (which way binance is leading)
  leading = Up if ret>0 else Down
  entry_px = L25 best-ASK of leading side asof fire  (what a fast taker PAYS now)
  won = leading == chainlink outcome
  pnl/share = won? (1-entry_px)*0.98 : -entry_px   (LegacyConfig 2%-on-profit)

Usage: py -X utf8 strategy_lab/directional/l25_ask_latency_test.py
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_resolutions, load_orderbook_l25_streaming  # noqa: E402

CANON = ROOT / "data" / "v4" / "canonical"
OUT = ROOT / "strategy_lab" / "directional" / "_results"
OUT.mkdir(parents=True, exist_ok=True)
WIN = {"5m": 300, "15m": 900}
LO = int(pd.Timestamp("2026-05-22", tz="UTC").timestamp())
HI = int(pd.Timestamp("2026-05-27", tz="UTC").timestamp())
OFFSETS = [5, 10, 20, 30, 45, 60]
SYM = {"BTC": "BINANCE_SPOT_BTC_USDT", "ETH": "BINANCE_SPOT_ETH_USDT", "SOL": "BINANCE_SPOT_SOL_USDT"}


def binance_1s_asof(asset):
    df = pd.read_parquet(CANON / "klines_1s.parquet",
                         columns=["time_period_start_us", "price_close", "symbol_id", "source", "period_id"])
    df = df[(df.symbol_id == SYM[asset]) & (df.source == "binance-spot-ws") & (df.period_id == "1SEC")]
    df = df.sort_values("time_period_start_us")
    end = (df.time_period_start_us.values.astype(np.int64) + 1_000_000)
    return end, df.price_close.values.astype(float)


def asof(arr_ts, arr_v, t):
    i = np.searchsorted(arr_ts, t.astype(np.int64), side="right") - 1
    out = np.full(len(t), np.nan)
    ok = i >= 0
    out[ok] = arr_v[i[ok]]
    return out


def ask_asof(arr, t):
    ts, ap, asz, bp, bsz = arr
    a = ap[:, 0].astype(float)
    i = int(np.searchsorted(ts.astype(np.int64), int(t), side="right")) - 1
    if i < 0:
        return np.nan
    v = a[i]
    return v if (np.isfinite(v) and 0 < v < 1) else np.nan


def run():
    res = load_resolutions(); res["slug"] = res["slug"].astype(str)
    rows = []
    for asset in ["BTC", "ETH", "SOL"]:
        be, bc = binance_1s_asof(asset)
        for tf in ["5m", "15m"]:
            pref = f"{asset.lower()}-updown-{tf}-"
            sub = res[(res.ticker == asset) & (res.timeframe == tf)]
            sub = sub[sub.slug.str.startswith(pref)].copy()
            sub["ss"] = sub.slug.str.rsplit("-", n=1).str[-1].astype(np.int64)
            sub = sub[(sub.ss >= LO) & (sub.ss <= HI)]
            if sub.empty:
                continue
            slugs = set(sub.slug)
            won_up = dict(zip(sub.slug, sub.outcome.str.lower() == "up"))
            t0 = time.time()
            books = load_orderbook_l25_streaming(asset.lower(), slugs=slugs, subsample_1hz=False)
            ss_arr = sub.ss.values.astype(np.int64)
            slug_arr = sub.slug.values
            px_open = asof(be, bc, ss_arr * 1_000_000)
            for off in OFFSETS:
                fire = (ss_arr + off) * 1_000_000
                px_fire = asof(be, bc, fire)
                ret = px_fire / px_open - 1.0
                recs = []
                for k in range(len(slug_arr)):
                    if not np.isfinite(ret[k]) or abs(ret[k]) < 1e-9:
                        continue
                    slug = slug_arr[k]
                    lead = "Up" if ret[k] > 0 else "Down"
                    arr = books.get((slug, lead))
                    if arr is None:
                        continue
                    ep = ask_asof(arr, fire[k])
                    if not np.isfinite(ep):
                        continue
                    won = (ret[k] > 0) == won_up[slug]
                    recs.append((won, ep, abs(ret[k]) * 1e4))
                if len(recs) < 30:
                    continue
                a = np.array(recs)
                wv, ev, rv = a[:, 0], a[:, 1], a[:, 2]
                pnl = np.where(wv > 0, (1 - ev) * 0.98, -ev)
                # strong-move subset
                strong = rv >= 2.0
                rows.append(dict(asset=asset, tf=tf, offset=off, n=len(recs),
                                 wr=round(100 * wv.mean(), 1), mean_ep=round(ev.mean(), 3),
                                 edge=round(wv.mean() - ev.mean(), 3),
                                 pnl_per_share=round(pnl.mean(), 4),
                                 n_strong=int(strong.sum()),
                                 wr_strong=round(100 * wv[strong].mean(), 1) if strong.sum() > 10 else np.nan,
                                 edge_strong=round(wv[strong].mean() - ev[strong].mean(), 3) if strong.sum() > 10 else np.nan,
                                 pnl_strong=round(pnl[strong].mean(), 4) if strong.sum() > 10 else np.nan))
            print(f"[{asset} {tf}] {time.time()-t0:.0f}s", flush=True)
    df = pd.DataFrame(rows); df.to_csv(OUT / "l25_ask_latency.csv", index=False)
    pd.set_option("display.width", 240)
    print("\n" + "=" * 100)
    print("L25-ASK LATENCY PICK-OFF — buy binance-leading side at best-ask, by offset (s into window)")
    print("=" * 100)
    pooled = (df.groupby("offset").apply(lambda g: pd.Series({
        "n": int(g.n.sum()),
        "wr": round(float((g.wr*g.n).sum()/g.n.sum()),1),
        "mean_ep": round(float((g.mean_ep*g.n).sum()/g.n.sum()),3),
        "edge": round(float((g.edge*g.n).sum()/g.n.sum()),4),
        "pnl_per_share": round(float((g.pnl_per_share*g.n).sum()/g.n.sum()),4)}),
        include_groups=False).reset_index())
    print("POOLED by offset (edge = WR - mean_entry_ask; >0 = stale-ask edge):")
    print(pooled.to_string(index=False))
    print("\nStrong-move (|ret|>=2bps) pooled by offset:")
    ps = (df.dropna(subset=["pnl_strong"]).groupby("offset").apply(lambda g: pd.Series({
        "n_strong": int(g.n_strong.sum()),
        "wr_strong": round(float((g.wr_strong*g.n_strong).sum()/g.n_strong.sum()),1),
        "edge_strong": round(float((g.edge_strong*g.n_strong).sum()/g.n_strong.sum()),4),
        "pnl_strong": round(float((g.pnl_strong*g.n_strong).sum()/g.n_strong.sum()),4)}),
        include_groups=False).reset_index())
    print(ps.to_string(index=False))
    print(f"\nwrote {OUT/'l25_ask_latency.csv'}")


if __name__ == "__main__":
    run()
