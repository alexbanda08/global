"""
latency_threshold_sweep.py — does a SHARPER move filter make the latency edge
statistically significant? (Decisive: turn marginal -> real, or kill it.)

Same fast-directional-taker as the walk-forward ($25 book-walk + 85ms latency +
spread<=0.05, offset 5s, production 2%-on-profit), but records ret_bps per fire so
we can bucket by move size {>=2,>=3,>=5,>=8 bps} in one L25 pass, split IS/OOS, and
report n, fill-conditional WR, pnl/trade, 95% CI, t-stat per bucket.

Hypothesis: bigger binance moves -> bigger stale-ask gap -> bigger per-trade edge ->
t-stat clears 2. If even the big-move buckets stay t<2, it's the efficient-market wall.

Usage: py -X utf8 strategy_lab/directional/latency_threshold_sweep.py
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
OFFSET = 5
SPREAD = 0.05
NOTIONAL = 25.0
MIN_RET = 2.0
IS_CUTOFF = int(pd.Timestamp("2026-05-15", tz="UTC").timestamp())
THRESHOLDS = [2.0, 3.0, 5.0, 8.0]
SYM = {"BTC": "BINANCE_SPOT_BTC_USDT", "ETH": "BINANCE_SPOT_ETH_USDT", "SOL": "BINANCE_SPOT_SOL_USDT"}
CHUNK_DAYS = 5


def binance_1s(asset):
    df = pd.read_parquet(CANON / "klines_1s.parquet",
                         columns=["time_period_start_us", "price_close", "symbol_id", "source", "period_id"])
    df = df[(df.symbol_id == SYM[asset]) & (df.source == "binance-spot-ws") & (df.period_id == "1SEC")].sort_values("time_period_start_us")
    return (df.time_period_start_us.values.astype(np.int64) + 1_000_000), df.price_close.values.astype(float)


def asof(ts, v, t):
    i = np.searchsorted(ts, t.astype(np.int64), side="right") - 1
    out = np.full(len(t), np.nan); ok = i >= 0; out[ok] = v[i[ok]]; return out


def legacy_pnl(fill, won):
    return (float(fill["shares"]) - float(fill["usd"])) * 0.98 if won else -float(fill["usd"])


def stat(x):
    n = len(x)
    if n < 2: return (np.nan, np.nan)
    m = float(np.mean(x)); se = float(np.std(x, ddof=1)) / np.sqrt(n)
    return m, (m / se if se else np.nan)


def run():
    res = load_resolutions(); res["slug"] = res["slug"].astype(str)
    cfg = LiveMimicConfig()
    bz = {a: binance_1s(a) for a in ["BTC", "ETH", "SOL"]}
    lo_all = int(pd.Timestamp("2026-04-22", tz="UTC").timestamp())
    hi_all = int(pd.Timestamp("2026-05-30", tz="UTC").timestamp())
    bounds = list(range(lo_all, hi_all, CHUNK_DAYS * 86400)) + [hi_all]
    rec = []  # (slot_start, ret_bps, won, pnl)
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
                ss = sub.ss.values.astype(np.int64); sl = sub.slug.values
                fire = (ss + OFFSET) * 1_000_000
                ret = asof(be, bc, fire) / asof(be, bc, ss * 1_000_000) - 1.0
                for k in range(len(sl)):
                    rb = abs(ret[k]) * 1e4
                    if not np.isfinite(rb) or rb < MIN_RET: continue
                    lead = "Up" if ret[k] > 0 else "Down"
                    fill = fill_at_book(books, sl[k], lead, int(fire[k]), cfg=cfg,
                                        side="buy", spread_filter=SPREAD, notional_usd=NOTIONAL)
                    if fill is None: continue
                    won = (ret[k] > 0) == won_up[sl[k]]
                    rec.append((int(ss[k]), rb, won, legacy_pnl(fill, won)))
        print(f"[chunk {pd.to_datetime(clo,unit='s',utc=True):%m-%d}] cum={len(rec)}", flush=True)
    df = pd.DataFrame(rec, columns=["slot_start", "ret_bps", "won", "pnl"])
    df["period"] = np.where(df.slot_start < IS_CUTOFF, "IS", "OOS")
    df.to_csv(OUT / "latency_threshold_sweep.csv", index=False)
    print("\n" + "=" * 90)
    print(f"MOVE-THRESHOLD SWEEP (offset {OFFSET}s, $25 book-walk, 2%-on-profit) — IS vs OOS")
    print("=" * 90)
    rows = []
    for thr in THRESHOLDS:
        for per in ["IS", "OOS"]:
            g = df[(df.ret_bps >= thr) & (df.period == per)]
            if len(g) < 10: continue
            m, t = stat(g.pnl.to_numpy())
            rows.append(dict(min_ret_bps=thr, period=per, n=len(g),
                             wr=round(100*g.won.mean(),1), pnl_per_trade=round(m,4),
                             t_stat=round(t,2), total=round(g.pnl.sum(),1),
                             trades_per_day=round(len(g)/22,1)))
    print(pd.DataFrame(rows).to_string(index=False))
    print("\n(t_stat>2 = significant. trades_per_day approx over ~22-day 1s window.)")
    print(f"wrote {OUT/'latency_threshold_sweep.csv'}")


if __name__ == "__main__":
    run()
