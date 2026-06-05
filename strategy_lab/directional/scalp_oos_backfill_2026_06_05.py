"""
SCALP DIFFERENT-WINDOW OOS (the §D-2 deflation gate) — run the confirmed lag-taker exit-scalp on the
Feb-Mar BACKFILL window the search NEVER saw, using the now-complete 1s signal + L25 backfill + resolutions_hf.

Search/in-sample window = Apr 22 -> Jun 4. This tests Feb 21 -> Mar 24 (BTC/ETH) + Mar 1-13 (SOL/XRP).
Same rules as the live scalp: delta_bps = |binance-1s 5s return| at slot_start; fire @ slot_start+5s;
lead = sign(ret); $25 taker entry (spread<=0.05); SELL on book at +60s. Gated cell entry_vwap<0.55.
If the gated edge holds OOS with CI>0 -> the scalp is deflation-proof validated on a disjoint window.
"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical")); sys.path.insert(0, str(ROOT / "strategy_lab"))
from engine_v2 import LiveMimicConfig, fill_at_book, sell_pnl_partial
CANON = ROOT / "data/v4/canonical"
cfg = LiveMimicConfig(); SPREAD = 0.05; NOTIONAL = 25.0

ASK_P = [f"ask_price_{i}" for i in range(25)]; ASK_S = [f"ask_size_{i}" for i in range(25)]
BID_P = [f"bid_price_{i}" for i in range(25)]; BID_S = [f"bid_size_{i}" for i in range(25)]

def load_l25_backfill(coin, slugs):
    """Flat backfill parquet -> engine_v2 dict {(slug,outcome): (ts, ap, asz, bp, bsz)}."""
    p = CANON / "orderbook_l25_backfill" / f"{coin}.parquet"
    df = pd.read_parquet(p, filters=[("slug", "in", set(slugs))])
    out = {}
    for (slug, oc), g in df.groupby(["slug", "outcome"]):
        g = g.sort_values("timestamp_us")
        out[(slug, oc)] = (g.timestamp_us.values.astype("int64"),
                           g[ASK_P].values.astype(float), g[ASK_S].values.astype(float),
                           g[BID_P].values.astype(float), g[BID_S].values.astype(float))
    return out

def unified_1s(coin):
    sym = f"BINANCE_SPOT_{coin.upper()}_USDT"
    df = pd.read_parquet(CANON / "klines_1s.parquet",
                         columns=["symbol_id", "time_period_start_us", "price_close"],
                         filters=[("symbol_id", "==", sym)])
    df = df.sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    return df.time_period_start_us.values.astype("int64"), df.price_close.values.astype(float)

def asof(ts, v, t):
    i = np.searchsorted(ts, t, "right") - 1
    return np.where(i >= 0, v[np.clip(i, 0, len(v) - 1)], np.nan)
def boot(v, nb=5000):
    v = np.asarray(v)
    if len(v) < 5: return (np.nan, np.nan)
    i = np.random.randint(0, len(v), (nb, len(v))); return tuple(np.percentile(v[i].mean(1), [2.5, 97.5]))

res = pd.read_parquet(CANON / "resolutions_hf.parquet")
res = res[res.outcome.isin(["Up", "Down"]) & res.timeframe.isin(["5m", "15m"])].drop_duplicates("slug")

# backfill L25 windows per coin (only run where L25 exists)
WIN = {"BTC": ("2026-02-21", "2026-03-24"), "ETH": ("2026-02-21", "2026-03-24"),
       "SOL": ("2026-03-01", "2026-03-13"), "XRP": ("2026-03-01", "2026-03-13")}

for coin in ["BTC", "ETH", "SOL", "XRP"]:
    lo_us = pd.Timestamp(WIN[coin][0], tz="UTC").value // 1000; hi_us = pd.Timestamp(WIN[coin][1], tz="UTC").value // 1000
    d = res[(res.ticker == coin) & (res.slot_start_us >= lo_us) & (res.slot_start_us <= hi_us)].copy()
    if not len(d):
        print(f"\n=== {coin}: no resolutions_hf in backfill window ==="); continue
    be, bc = unified_1s(coin)
    ss = d.slot_start_us.values // 1_000_000
    px_open = asof(be, bc, ss * 1_000_000); px_fire = asof(be, bc, (ss + 5) * 1_000_000)
    ret = px_fire / px_open - 1.0
    d = d.assign(ss=ss, fire_us=(ss + 5) * 1_000_000, ret=ret, delta_bps=np.abs(ret) * 1e4,
                 lead=np.where(ret > 0, "Up", "Down"))
    d = d[np.isfinite(d.ret) & (d.delta_bps >= 3.0)].reset_index(drop=True)
    print(f"\n=== {coin} OOS {WIN[coin][0]}..{WIN[coin][1]}: candidate fires (delta>=3) = {len(d)} ===", flush=True)
    # NOTE: backfill L25 books start ~75-150s after slot_start (timing anomaly) -> can't fire at +5s.
    # EXPLORATORY re-anchor: fire 30s into each slug's available book; recompute the 5s lag AT that moment.
    recs = []; slugs = d.slug.tolist(); B = 250
    dmap = {r.slug: r for _, r in d.iterrows()}
    for i in range(0, len(slugs), B):
        chunk = slugs[i:i + B]
        books = load_l25_backfill(coin.lower(), chunk)
        for slug in chunk:
            if (slug, "Up") not in books or (slug, "Down") not in books: continue
            r = dmap[slug]
            up_ts = books[(slug, "Up")][0]; dn_ts = books[(slug, "Down")][0]
            t0 = max(int(up_ts[0]), int(dn_ts[0]))           # both books present
            tend = min(int(up_ts[-1]), int(dn_ts[-1]))
            fire = t0 + 30_000_000                            # 30s into the available book
            if fire + 60_000_000 > tend or fire > int(r.slot_end_us): continue
            # 5s binance lag AT the (book-anchored) fire moment
            pf = asof(be, bc, fire); po = asof(be, bc, fire - 5_000_000)
            if not (np.isfinite(pf) and np.isfinite(po) and po > 0): continue
            ret = pf / po - 1.0; db = abs(ret) * 1e4
            if db < 3.0: continue
            lead = "Up" if ret > 0 else "Down"
            won = (ret > 0) == (r.outcome == "Up")
            fill = fill_at_book(books, slug, lead, fire, cfg=cfg, side="buy",
                                spread_filter=SPREAD, notional_usd=NOTIONAL)
            if fill is None:
                recs.append(dict(filled=0, ev=np.nan, won=won, pnl60=np.nan, delta=db)); continue
            p60 = sell_pnl_partial(fill, books, slug, lead, fire + 60_000_000, cfg=cfg)
            recs.append(dict(filled=1, ev=fill["vwap"], won=won, pnl60=p60, delta=db))
        del books
    F = pd.DataFrame(recs); nf = int(F.filled.sum())
    print(f"  fill_rate={nf}/{len(F)}={nf/max(len(F),1):.1%}")
    Ff = F[(F.filled == 1) & F.pnl60.notna()]
    for lab, sub in [("ALL filled", Ff), ("GATED vwap<0.55", Ff[Ff.ev < 0.55]),
                     ("GATED vwap<0.55 & d>=5", Ff[(Ff.ev < 0.55) & (Ff.delta >= 5)])]:
        v = sub.pnl60.values
        if len(v) < 5: print(f"  {lab:26s} n={len(v)} (few)"); continue
        t = v.mean() / v.std(ddof=1) * np.sqrt(len(v)) if v.std() > 0 else np.nan
        lo2, hi2 = boot(v)
        print(f"  {lab:26s} n={len(v):4d} $/tr={v.mean():+.3f} t={t:+.2f} CI=[{lo2:+.3f},{hi2:+.3f}] won={sub.won.mean():.3f}")
print("\nVERDICT: gated $/tr>0 with CI>0 on Feb-Mar BTC/ETH = scalp survives a DISJOINT-window OOS (deflation gate).")
