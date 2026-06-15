"""
OPEN-SCALP KNOB RE-OPTIMIZATION  —  2026-06-09  (THREAD B)
Two pre-registered knobs on the deployed open exit-scalp, plateau-tested on the disjoint BBO window:
  (1) ENTRY OFFSET: fire at {1,2,3,5,8,10,15}s after slot_start (signal=binance return [slot_start, slot_start+off]).
      Is +5s optimal? Earlier = book fresher but signal tiny/noisy; later = cleaner signal but book caught up.
  (2) DELTA BAND: post-hoc sweep gate [lo,hi] on delta_bps (current = >=3, with a 12 cap "load-bearing").
Fire iff |delta|>=3, cheap entry<0.55; entry $25 @ lead best_ask (off+85ms, size-capped, spread<=.05); exit
SELL best_bid +60s. Pooled BTC+ETH+SOL, 15m+5m. PLATEAU = a knob is robust only if neighbors agree (not a spike).
"""
import sys, os, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
from load import load_orderbook_bbo
CANON = ROOT / "data/v4/canonical"; RES = ROOT / "strategy_lab/directional/_results"
SPREAD = 0.05; STAKE = 25.0; LAT_US = 85_000
COINS = os.environ.get("EO_COINS", "BTC,ETH,SOL").split(",")
TFS = os.environ.get("EO_TFS", "15m,5m").split(",")
OFFS = [1, 2, 3, 5, 8, 10, 15]
WIN = ("2026-03-30", "2026-04-21"); TAG = os.environ.get("EO_TAG", "")

def klines(coin):
    sym = f"BINANCE_SPOT_{coin.upper()}_USDT"
    df = pd.read_parquet(CANON / "klines_1s.parquet", columns=["symbol_id", "time_period_start_us", "price_close"],
                         filters=[("symbol_id", "==", sym)]).sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    return df.time_period_start_us.values.astype("int64"), df.price_close.values.astype(float)
def asof(ts, v, t):
    i = np.searchsorted(ts, t, "right") - 1
    return np.where(i >= 0, v[np.clip(i, 0, len(v) - 1)], np.nan)
def bpnl(sell, ev, sh): return (sell - ev) * sh - 0.015 * sh * (ev * (1 - ev) + sell * (1 - sell))
def boot(v, nb=5000):
    v = np.asarray(v); v = v[np.isfinite(v)]
    if len(v) < 5: return (np.nan, np.nan)
    i = np.random.randint(0, len(v), (nb, len(v))); return tuple(np.percentile(v[i].mean(1), [2.5, 97.5]))
def stat(v):
    v = np.asarray(v); v = v[np.isfinite(v)]
    if len(v) < 5: return f"n={len(v):4d}(few)"
    t = v.mean() / v.std(ddof=1) * np.sqrt(len(v)) if v.std() > 0 else np.nan; lo, hi = boot(v)
    return f"n={len(v):4d} $/tr={v.mean():+.3f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}] won={(v>0).mean():.2f}"

res = pd.read_parquet(CANON / "resolutions_hf.parquet")
res = res[res.outcome.isin(["Up", "Down"])].drop_duplicates("slug")
BCOLS = ["timestamp_us", "slug", "outcome", "best_bid", "best_ask", "best_bid_size", "best_ask_size"]
lo_ts = pd.Timestamp(WIN[0], tz="UTC").value // 1000; hi_ts = pd.Timestamp(WIN[1], tz="UTC").value // 1000
ROWS = []
for coin in COINS:
    be, bc = klines(coin)
    for tf in TFS:
        d = res[(res.ticker == coin) & (res.timeframe == tf) &
                (res.slot_start_us >= lo_ts) & (res.slot_start_us <= hi_ts)].copy()
        if not len(d): print(f"{coin} {tf}: none", flush=True); continue
        print(f"\n=== {coin} {tf}: {len(d)} windows ===", flush=True)
        slugs = d.slug.tolist(); B = 120
        for i in range(0, len(slugs), B):
            chunk = d.iloc[i:i + B]
            cmin = int(chunk.slot_start_us.min()) - 2_000_000; cmax = int(chunk.slot_end_us.max()) + 2_000_000
            bbo = load_orderbook_bbo(coin, slugs=set(chunk.slug), min_ts_us=cmin, max_ts_us=cmax, columns=BCOLS)
            bk = {}
            for (sl, oc), g in bbo.groupby(["slug", "outcome"]):
                g = g.sort_values("timestamp_us")
                bk[(sl, oc)] = (g.timestamp_us.values.astype("int64"), g.best_ask.values.astype(float),
                                g.best_bid.values.astype(float), g.best_ask_size.values.astype(float))
            for _, r in chunk.iterrows():
                ss = int(r.slot_start_us); send = int(r.slot_end_us)
                p0 = asof(be, bc, ss)
                if not np.isfinite(p0) or p0 <= 0: continue
                for off in OFFS:
                    t = ss + off * 1_000_000
                    pr = asof(be, bc, t)
                    if not np.isfinite(pr): continue
                    delta = (pr / p0 - 1.0) * 1e4
                    if abs(delta) < 3.0: continue
                    lead = "Up" if delta > 0 else "Down"
                    key = (r.slug, lead)
                    if key not in bk: continue
                    ts, ask, bid, asz = bk[key]
                    je = np.searchsorted(ts, t + LAT_US, "right") - 1
                    if je < 0 or je >= len(ts): continue
                    a0, b0, s0 = ask[je], bid[je], asz[je]
                    if not (np.isfinite(a0) and np.isfinite(b0)) or (a0 - b0) > SPREAD: continue
                    sh = min(STAKE / a0, s0)
                    if sh * a0 < STAKE * 0.5: continue
                    ext = min(t + 60_000_000, send)
                    jx = np.searchsorted(ts, ext, "right") - 1
                    won = (delta > 0) == (r.outcome == "Up")
                    sell = bid[jx] if (0 <= jx < len(ts) and np.isfinite(bid[jx])) else (1.0 if won else 0.0)
                    ROWS.append(dict(coin=coin, tf=tf, slug=r.slug, off=off, delta=abs(delta), ev=a0,
                                     won=won, pnl60=bpnl(sell, a0, sh)))
            del bbo, bk
        F = pd.DataFrame(ROWS); F.to_parquet(RES / f"scalp_entryopt_2026_06_09{TAG}.parquet")
        print(f"  [ckpt] {coin} {tf}: rows={len(F[(F.coin==coin)&(F.tf==tf)])}", flush=True)

F = pd.DataFrame(ROWS); F.to_parquet(RES / f"scalp_entryopt_2026_06_09{TAG}.parquet")
print(f"\nsaved {len(F)} rows")
G = F[F.ev < 0.55]
print("\n===== (1) ENTRY-OFFSET PLATEAU (cheap, |delta|>=3, exit +60), pooled =====")
for off in OFFS:
    print(f"  +{off:3d}s  {stat(G[G.off==off].pnl60.values)}")
print("\n===== (1b) per coin-tf, +3 vs +5 vs +8 =====")
for (coin, tf), g in G.groupby(["coin", "tf"]):
    print(f"  {coin} {tf}: +3 {stat(g[g.off==3].pnl60.values)} | +5 {stat(g[g.off==5].pnl60.values)} | +8 {stat(g[g.off==8].pnl60.values)}")
print("\n===== (2) DELTA-BAND SWEEP at +5s (cheap), pooled =====")
g5 = G[G.off == 5]
for lo, hi in [(3, 999), (3, 12), (4, 12), (5, 12), (5, 999), (4, 10), (3, 8), (8, 999), (5, 15)]:
    s = g5[(g5.delta >= lo) & (g5.delta <= hi)]
    print(f"  delta in [{lo:3d},{hi:3d}]  {stat(s.pnl60.values)}")
print("\nREAD: a knob is robust only as a PLATEAU (neighbors agree). +5s is current; band [3,inf) current.")
print("CAVEAT: BBO top-of-book; SEARCH window. Any improved knob must re-confirm on L25 Apr22-Jun8.")
