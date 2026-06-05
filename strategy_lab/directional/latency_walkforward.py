"""
latency_walkforward.py — does the latency edge survive OUT-OF-SAMPLE on the full
Apr 22 -> May 29 window? (The project's capstone lesson: signals die OOS.)

Same fast-directional-taker as realistic_latency_validation (buy binance-leading side
at L25 best-ask via engine_v2 book-walk + 85ms latency + spread filter, |ret|>=2bps,
offset 5/10s, production 2%-on-profit fee), but:
  - runs the FULL canonical window, chunked weekly to bound L25 memory
  - splits trades into IN-SAMPLE (slot_start < 2026-05-15) vs OUT-OF-SAMPLE (>=)
  - reports per period: n, fill%, WR, mean pnl/trade, 95% CI, t-stat
  - per-week stability table

Usage: py -X utf8 strategy_lab/directional/latency_walkforward.py
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
OFFSETS = [5, 10]
SPREAD = 0.05
NOTIONAL = 25.0
RET_BPS = 2.0
IS_CUTOFF = int(pd.Timestamp("2026-05-15", tz="UTC").timestamp())
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
    shares = float(fill["shares"]); usd = float(fill["usd"])
    return (shares - usd) * 0.98 if won else -usd


def ci(x):
    n = len(x)
    if n < 2: return (float(np.mean(x)) if n else np.nan, np.nan, np.nan)
    m = float(np.mean(x)); se = float(np.std(x, ddof=1)) / np.sqrt(n)
    return m, m - 1.96 * se, m + 1.96 * se, m / se if se else np.nan


def run():
    res = load_resolutions(); res["slug"] = res["slug"].astype(str)
    cfg = LiveMimicConfig()
    bz = {a: binance_1s(a) for a in ["BTC", "ETH", "SOL"]}
    lo_all = int(pd.Timestamp("2026-04-22", tz="UTC").timestamp())
    hi_all = int(pd.Timestamp("2026-05-30", tz="UTC").timestamp())
    bounds = list(range(lo_all, hi_all, CHUNK_DAYS * 86400)) + [hi_all]
    trades = []  # (slot_start, offset, won, pnl)
    for ci_idx in range(len(bounds) - 1):
        clo, chi = bounds[ci_idx], bounds[ci_idx + 1]
        wk = pd.to_datetime(clo, unit="s", utc=True).strftime("%m-%d")
        for asset in ["BTC", "ETH", "SOL"]:
            be, bc = bz[asset]
            for tf in ["5m", "15m"]:
                pref = f"{asset.lower()}-updown-{tf}-"
                sub = res[(res.ticker == asset) & (res.timeframe == tf)]
                sub = sub[sub.slug.str.startswith(pref)].copy()
                sub["ss"] = sub.slug.str.rsplit("-", n=1).str[-1].astype(np.int64)
                sub = sub[(sub.ss >= clo) & (sub.ss < chi)]
                if sub.empty: continue
                slugs = set(sub.slug)
                won_up = dict(zip(sub.slug, sub.outcome.str.lower() == "up"))
                books = load_orderbook_l25_streaming(asset.lower(), slugs=slugs, subsample_1hz=False)
                ss = sub.ss.values.astype(np.int64); sl = sub.slug.values
                px_open = asof(be, bc, ss * 1_000_000)
                for off in OFFSETS:
                    fire = (ss + off) * 1_000_000
                    ret = asof(be, bc, fire) / px_open - 1.0
                    for k in range(len(sl)):
                        if not np.isfinite(ret[k]) or abs(ret[k]) * 1e4 < RET_BPS: continue
                        lead = "Up" if ret[k] > 0 else "Down"
                        fill = fill_at_book(books, sl[k], lead, int(fire[k]), cfg=cfg,
                                            side="buy", spread_filter=SPREAD, notional_usd=NOTIONAL)
                        if fill is None: continue
                        won = (ret[k] > 0) == won_up[sl[k]]
                        trades.append((int(ss[k]), off, won, legacy_pnl(fill, won)))
        print(f"[chunk {wk}] cum trades={len(trades)}", flush=True)
    df = pd.DataFrame(trades, columns=["slot_start", "offset", "won", "pnl"])
    df["period"] = np.where(df.slot_start < IS_CUTOFF, "IN-SAMPLE", "OUT-OF-SAMPLE")
    df.to_csv(OUT / "latency_walkforward_trades.csv", index=False)

    print("\n" + "=" * 100)
    print("LATENCY EDGE WALK-FORWARD — full Apr22->May29, IS(<May15) vs OOS(>=May15)")
    print("=" * 100)
    rows = []
    for off in OFFSETS:
        for per in ["IN-SAMPLE", "OUT-OF-SAMPLE"]:
            g = df[(df.offset == off) & (df.period == per)]
            if len(g) < 10: continue
            m, lo, hi, t = ci(g.pnl.to_numpy())
            rows.append(dict(offset=off, period=per, n=len(g),
                             wr=round(100*g.won.mean(),1), pnl_per_trade=round(m,4),
                             ci_lo=round(lo,4), ci_hi=round(hi,4), t_stat=round(t,2),
                             total=round(g.pnl.sum(),1)))
    print(pd.DataFrame(rows).to_string(index=False))
    print("\nPer-week stability (mean pnl/trade, offset=5):")
    g5 = df[df.offset == 5].copy()
    g5["wk"] = pd.to_datetime(g5.slot_start, unit="s", utc=True).dt.strftime("%Y-%m-%d").str[:10]
    g5["wkbin"] = (g5.slot_start // (7*86400))
    wk = g5.groupby("wkbin").agg(n=("pnl","size"), wr=("won", lambda x: round(100*x.mean(),1)),
                                 pnl=("pnl", lambda x: round(x.mean(),4)),
                                 start=("slot_start", lambda x: pd.to_datetime(x.min(),unit="s",utc=True).strftime("%m-%d")))
    print(wk[["start","n","wr","pnl"]].to_string(index=False))
    print(f"\nwrote {OUT/'latency_walkforward_trades.csv'}")


if __name__ == "__main__":
    run()
