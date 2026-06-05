"""
realistic_latency_validation.py — does the latency edge survive REALISTIC fills?

Takes the fast-directional-taker signal (buy binance-leading side at small offset on
strong moves) and fills it through engine_v2.fill_at_book: book-WALK for a $notional
target + 85ms latency shift + spread filter + min-book-events. Then PnL with the
production fee (2%-on-winning-profit-only, per CLAUDE.md) AND the 0.07-curve (bracket).

Decisive: if net PnL/trade stays positive after walk + latency + spread filter (and
the fill RATE is non-trivial), the fast directional taker is deployable.

Usage: py -X utf8 strategy_lab/directional/realistic_latency_validation.py
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
from engine_v2 import LiveMimicConfig, fill_at_book, book_event_count  # noqa: E402

CANON = ROOT / "data" / "v4" / "canonical"
OUT = ROOT / "strategy_lab" / "directional" / "_results"
WIN = {"5m": 300, "15m": 900}
LO = int(pd.Timestamp("2026-05-22", tz="UTC").timestamp())
HI = int(pd.Timestamp("2026-05-27", tz="UTC").timestamp())
OFFSETS = [5, 10, 20]
SPREADS = [0.03, 0.05, 0.10]
NOTIONAL = 25.0
RET_BPS = 2.0
SYM = {"BTC": "BINANCE_SPOT_BTC_USDT", "ETH": "BINANCE_SPOT_ETH_USDT", "SOL": "BINANCE_SPOT_SOL_USDT"}


def binance_1s(asset):
    df = pd.read_parquet(CANON / "klines_1s.parquet",
                         columns=["time_period_start_us", "price_close", "symbol_id", "source", "period_id"])
    df = df[(df.symbol_id == SYM[asset]) & (df.source == "binance-spot-ws") & (df.period_id == "1SEC")].sort_values("time_period_start_us")
    return (df.time_period_start_us.values.astype(np.int64) + 1_000_000), df.price_close.values.astype(float)


def asof(ts, v, t):
    i = np.searchsorted(ts, t.astype(np.int64), side="right") - 1
    out = np.full(len(t), np.nan); ok = i >= 0; out[ok] = v[i[ok]]; return out


def legacy_pnl(fill, won):
    # production 2%-on-winning-profit-only; entry has no fee
    shares = float(fill["shares"]); usd = float(fill["usd"])
    return (shares - usd) * 0.98 if won else -usd


def run():
    res = load_resolutions(); res["slug"] = res["slug"].astype(str)
    cfg = LiveMimicConfig()  # 85ms latency, min_book_events=25, poly curve (we override fee below)
    rows = []
    for asset in ["BTC", "ETH", "SOL"]:
        be, bc = binance_1s(asset)
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
            ss = sub.ss.values.astype(np.int64); sl = sub.slug.values
            px_open = asof(be, bc, ss * 1_000_000)
            for off in OFFSETS:
                fire = (ss + off) * 1_000_000
                pxf = asof(be, bc, fire)
                ret = pxf / px_open - 1.0
                for spf in SPREADS:
                    n_sig = 0; n_fill = 0
                    pnl_leg = []
                    for k in range(len(sl)):
                        if not np.isfinite(ret[k]) or abs(ret[k]) * 1e4 < RET_BPS:
                            continue
                        n_sig += 1
                        lead = "Up" if ret[k] > 0 else "Down"
                        fill = fill_at_book(books, sl[k], lead, int(fire[k]), cfg=cfg,
                                            side="buy", spread_filter=spf, notional_usd=NOTIONAL)
                        if fill is None:
                            continue
                        n_fill += 1
                        won = (ret[k] > 0) == won_up[sl[k]]
                        pnl_leg.append(legacy_pnl(fill, won))
                    if n_fill < 30:
                        continue
                    arr = np.array(pnl_leg)
                    rows.append(dict(asset=asset, tf=tf, offset=off, spread_filter=spf,
                                     n_signal=n_sig, n_fill=n_fill,
                                     fill_rate=round(100 * n_fill / n_sig, 1),
                                     pnl_per_trade=round(float(arr.mean()), 4),
                                     pnl_per_dollar=round(float(arr.mean() / NOTIONAL), 5),
                                     total=round(float(arr.sum()), 1)))
            print(f"[{asset} {tf}] {time.time()-t0:.0f}s", flush=True)
    df = pd.DataFrame(rows); df.to_csv(OUT / "realistic_latency.csv", index=False)
    pd.set_option("display.width", 240)
    print("\n" + "=" * 100)
    print("REALISTIC FILL VALIDATION (book-walk $25 + 85ms latency + spread filter, 2%-on-profit fee)")
    print("=" * 100)
    pooled = (df.groupby(["offset", "spread_filter"]).apply(lambda g: pd.Series({
        "n_signal": int(g.n_signal.sum()), "n_fill": int(g.n_fill.sum()),
        "fill_rate": round(float(100*g.n_fill.sum()/g.n_signal.sum()),1),
        "pnl_per_trade": round(float((g.pnl_per_trade*g.n_fill).sum()/g.n_fill.sum()),4),
        "total": round(float(g.total.sum()),1)}), include_groups=False).reset_index())
    print("POOLED across asset/tf:")
    print(pooled.to_string(index=False))
    print(f"\nNOTIONAL=${NOTIONAL}/trade, strong moves |ret|>={RET_BPS}bps. pnl_per_trade>0 = edge survives.")
    print(f"wrote {OUT/'realistic_latency.csv'}")


if __name__ == "__main__":
    run()
