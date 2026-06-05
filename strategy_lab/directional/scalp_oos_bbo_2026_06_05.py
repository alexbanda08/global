"""
SCALP DIFFERENT-WINDOW OOS (clean) — aliplayer BBO, Mar 30 -> Apr 21 (pre-search = disjoint from Apr22-Jun4).
BBO is slot-aligned w/ full pre-slot coverage (load_orderbook_bbo), so we CAN fire at the deployed +5s.
Rules: delta_bps=|binance-1s 5s return| at slot_start; fire @ slot_start+5s; lead=sign(ret);
entry = $25 at best_ask (top-of-book; fill only if best_ask_size covers, spread<=0.05);
exit = SELL at best_bid at +60s (clamped to slot_end). Gated cell entry_vwap<0.55.
NOTE: BBO = top-of-book only (no L25 depth walk) -> entry slightly optimistic vs full walk; flag it.
If gated $/tr>0 with CI>0 here -> scalp survives a clean disjoint-window OOS (the deflation gate).
"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
from load import load_orderbook_bbo
CANON = ROOT / "data/v4/canonical"
SPREAD = 0.05; STAKE = 25.0; LAT_US = 85_000

import os
COINS = os.environ.get("OOS_COINS", "BTC,ETH,SOL").split(",")
_FULL = ("2026-03-30", "2026-04-21"); _NEW = ("2026-04-06", "2026-04-21")  # DOGE/BNB markets+1s align Apr6-21
WIN = {"BTC": _FULL, "ETH": _FULL, "SOL": _FULL, "DOGE": _NEW, "BNB": _NEW}
OUTTAG = os.environ.get("OOS_TAG", "")
ALL_FIRES = []

def unified_1s(coin):
    sym = f"BINANCE_SPOT_{coin.upper()}_USDT"
    df = pd.read_parquet(CANON / "klines_1s.parquet", columns=["symbol_id", "time_period_start_us", "price_close"],
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
def bpnl(sell, ev, sh): return (sell - ev) * sh - 0.015 * sh * (ev * (1 - ev) + sell * (1 - sell))

res = pd.read_parquet(CANON / "resolutions_hf.parquet")
res = res[res.outcome.isin(["Up", "Down"]) & res.timeframe.isin(["5m", "15m"])].drop_duplicates("slug")
BCOLS = ["timestamp_us", "slug", "outcome", "best_bid", "best_ask", "best_bid_size", "best_ask_size"]

for coin in COINS:
    lo = pd.Timestamp(WIN[coin][0], tz="UTC").value // 1000; hi = pd.Timestamp(WIN[coin][1], tz="UTC").value // 1000
    d = res[(res.ticker == coin) & (res.slot_start_us >= lo) & (res.slot_start_us <= hi)].copy()
    if not len(d):
        print(f"\n=== {coin}: no slugs in window ==="); continue
    be, bc = unified_1s(coin)
    ss = d.slot_start_us.values
    ret = asof(be, bc, ss + 5_000_000) / asof(be, bc, ss) - 1.0
    d = d.assign(fire_us=ss + 5_000_000, slot_end=d.slot_end_us.values, ret=ret,
                 delta_bps=np.abs(ret) * 1e4, lead=np.where(ret > 0, "Up", "Down"))
    d = d[np.isfinite(d.ret) & (d.delta_bps >= 3.0)].reset_index(drop=True)
    print(f"\n=== {coin} OOS {WIN[coin][0]}..{WIN[coin][1]}: candidate fires (delta>=3) = {len(d)} ===", flush=True)
    recs = []; slugs = d.slug.tolist(); B = 120
    for i in range(0, len(slugs), B):
        chunk = d.iloc[i:i + B]
        cmin = int(chunk.fire_us.min()) - 2_000_000; cmax = int(chunk.slot_end.max()) + 2_000_000
        bbo = load_orderbook_bbo(coin, slugs=set(chunk.slug), min_ts_us=cmin, max_ts_us=cmax, columns=BCOLS)
        bk = {}
        for (sl, oc), g in bbo.groupby(["slug", "outcome"]):
            g = g.sort_values("timestamp_us")
            bk[(sl, oc)] = (g.timestamp_us.values.astype("int64"), g.best_ask.values.astype(float),
                            g.best_bid.values.astype(float), g.best_ask_size.values.astype(float))
        for _, r in chunk.iterrows():
            key = (r.slug, r.lead)
            if key not in bk: continue
            ts, ask, bid, asz = bk[key]
            won = (r.ret > 0) == (r.outcome == "Up")
            je = np.searchsorted(ts, int(r.fire_us) + LAT_US, "right") - 1
            if je < 0 or je >= len(ts): continue
            a0, b0, s0 = ask[je], bid[je], asz[je]
            if not (np.isfinite(a0) and np.isfinite(b0)) or (a0 - b0) > SPREAD: continue
            shares = min(STAKE / a0, s0)                       # top-of-book fill (size-capped)
            if shares * a0 < STAKE * 0.5: continue             # underfill
            ev = a0
            ext = min(int(r.fire_us) + 60_000_000, int(r.slot_end))   # clamp to slot_end
            jx = np.searchsorted(ts, ext, "right") - 1
            sell = bid[jx] if (0 <= jx < len(ts) and np.isfinite(bid[jx])) else (1.0 if won else 0.0)
            hour = (int(r.fire_us) // 1_000_000 % 86_400) // 3600
            recs.append(dict(coin=coin, fire_us=int(r.fire_us), hour=hour, ev=ev, won=won,
                             pnl60=bpnl(sell, ev, shares), delta=r.delta_bps))
        del bbo, bk
    F = pd.DataFrame(recs)
    ALL_FIRES.extend(recs)
    print(f"  filled fires: {len(F)} (of {len(d)} candidates)")
    for lab, sub in [("ALL filled", F), ("GATED vwap<0.55", F[F.ev < 0.55]),
                     ("GATED vwap<0.55 & d>=5", F[(F.ev < 0.55) & (F.delta >= 5)])]:
        if len(sub) < 5: print(f"  {lab:26s} n={len(sub)} (few)"); continue
        v = sub.pnl60.values; t = v.mean()/v.std(ddof=1)*np.sqrt(len(v)) if v.std() > 0 else np.nan
        lo2, hi2 = boot(v)
        print(f"  {lab:26s} n={len(sub):4d} $/tr={v.mean():+.3f} t={t:+.2f} CI=[{lo2:+.3f},{hi2:+.3f}] won={sub.won.mean():.3f}")
print("\nVERDICT: gated $/tr>0 with CI>0 on Mar30-Apr21 (disjoint from search) = scalp survives clean OOS.")
print("CAVEAT: BBO top-of-book fill (no L25 depth walk) -> entry slightly optimistic; re-check on full L25 if it passes.")

# save + TIME-OF-DAY OOS cross-validation (pooled BTC+ETH+SOL, gated cell)
A = pd.DataFrame(ALL_FIRES)
A.to_parquet(ROOT / "strategy_lab/directional/_results/scalp_oos_bbo_fires_2026_06_05{OUTTAG}.parquet".format(OUTTAG=OUTTAG))
g = A[A.ev < 0.55]
print(f"\n===== TIME-OF-DAY OOS (pooled BTC+ETH+SOL, gated vwap<0.55, n={len(g)}) =====")
def cell(v):
    v = np.asarray(v); t = v.mean()/v.std(ddof=1)*np.sqrt(len(v)) if len(v) > 2 and v.std() > 0 else np.nan
    lo, hi = boot(v); return f"n={len(v):4d} $/tr={v.mean():+.3f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}]"
print(f"  base (all hours)        {cell(g.pnl60.values)}")
print(f"  22-02 UTC               {cell(g[g.hour.isin([22,23,0,1])].pnl60.values)}")
print(f"  exclude dead {{12,17}}    {cell(g[~g.hour.isin([12,17])].pnl60.values)}")
print(f"  exclude {{2,12,16,17,18}} {cell(g[~g.hour.isin([2,12,16,17,18])].pnl60.values)}")
print(f"  dead hours {{12,17}} only {cell(g[g.hour.isin([12,17])].pnl60.values)}")
print("READ: time-of-day gate validated OOS if 22-02 > base and exclude-dead >= base on Mar30-Apr21.")
