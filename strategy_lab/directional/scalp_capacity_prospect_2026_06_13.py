"""
SCALP CAPACITY PROSPECT — per market (coin x timeframe), per stake (2026-06-13).

Extends scalp_capacity_l25: splits 5m vs 15m, builds the time-ordered equity curve -> MaxDD,
fires/day, and projects 1-MONTH profit (in-sample AND OOS-anchored). Strategy = the live scalp
(pure +60s time-sell, causal signal, gate entry_vwap<0.55, delta>=3bps). Markets = BTC/ETH/SOL
x {5m,15m} (the only coins with production L25 depth; DOGE/XRP/BNB have NO L25 -> not sizeable here).

OOS ANCHOR: the L25 window (Apr22-Jun11) is IN-SAMPLE -> absolute $/tr is optimistic. The causal
OOS (scalp_causal_asof, BBO Mar30-Apr21) says $25 $/tr ~ +0.9 (ALL) to +1.5 (CLEAN) vs in-sample
+3.1 -> haircut factor ~0.30-0.45. We report BOTH: in-sample backtest + OOS-anchored (x0.35 central,
0.30-0.45 band). MaxDD shown is IN-SAMPLE = a FLOOR (real DD is worse since in-sample overstates edge).
"""
import os, sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
import pyarrow.parquet as pq

warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab/directional"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
from engine_v2 import sell_at_bid_partial                              # noqa: E402
from book_walk import book_walk_fill                                   # noqa: E402
from scalp_fill_lib_2026_06_10 import bpnl, held_value, boot           # noqa: E402

CANON = ROOT / "data/v4/canonical"; RES = ROOT / "strategy_lab/directional/_results"
LAT_US = 85_000; STALE_US = 120_000_000; NDAYS = 49.4
STAKES = [25, 50, 100, 150, 200, 300, 400, 600, 800]
HAIRCUT = 0.35; HC_LO, HC_HI = 0.30, 0.45     # OOS anchor band
COINS = os.environ.get("OOS_COINS", "BTC,ETH,SOL").split(",")
AP = [f"ask_price_{i}" for i in range(25)]; ASZ = [f"ask_size_{i}" for i in range(25)]
BP = [f"bid_price_{i}" for i in range(25)]; BSZ = [f"bid_size_{i}" for i in range(25)]
COLS = ["timestamp_us", "slug", "outcome"] + AP + ASZ + BP + BSZ


def unified_1s(coin):
    sym = f"BINANCE_SPOT_{coin.upper()}_USDT"
    df = pd.read_parquet(CANON / "klines_1s.parquet", columns=["symbol_id", "time_period_start_us", "price_close"],
                         filters=[("symbol_id", "==", sym)])
    df = df.sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    s = df.time_period_start_us.values.astype("int64")
    return s + 1_000_000, df.price_close.values.astype(float)


def asof(ts, v, t):
    i = np.searchsorted(ts, t, "right") - 1
    return np.where(i >= 0, v[np.clip(i, 0, len(v) - 1)], np.nan)


def scan_coin(coin, fires):
    lead = dict(zip(fires.slug, fires.lead))
    et = dict(zip(fires.slug, (fires.fire_us + LAT_US).astype("int64")))
    xt = dict(zip(fires.slug, (np.minimum(fires.fire_us + 60_000_000, fires.slot_end) + LAT_US).astype("int64")))
    gset = set(fires.slug); ebest, xbest = {}, {}
    pf = pq.ParquetFile(CANON / "orderbook_l25" / f"{coin.lower()}.parquet")
    for batch in pf.iter_batches(batch_size=300_000, columns=COLS):
        df = batch.to_pandas(); df = df[df.slug.isin(gset)]
        if not len(df): continue
        df["lead"] = df.slug.map(lead); df = df[df.outcome == df.lead]
        if not len(df): continue
        df["et"] = df.slug.map(et); df["xt"] = df.slug.map(xt)
        e = df[df.timestamp_us <= df.et]
        if len(e):
            for sl, i in e.groupby("slug").timestamp_us.idxmax().items():
                ts = int(e.at[i, "timestamp_us"])
                if sl not in ebest or ts > ebest[sl][0]:
                    ebest[sl] = (ts, e.loc[i, AP].to_numpy(float), e.loc[i, ASZ].to_numpy(float))
        x = df[df.timestamp_us <= df.xt]
        if len(x):
            for sl, i in x.groupby("slug").timestamp_us.idxmax().items():
                ts = int(x.at[i, "timestamp_us"])
                if sl not in xbest or ts > xbest[sl][0]:
                    xbest[sl] = (ts, x.loc[i, BP].to_numpy(float), x.loc[i, BSZ].to_numpy(float))
    return ebest, xbest, et, xt


r = pd.read_parquet(CANON / "resolutions.parquet")
r = r[r.outcome.isin(["Up", "Down"]) & r.timeframe.isin(["5m", "15m"])].drop_duplicates("slug")
REC = []   # long-format per-fire-per-stake records

for coin in COINS:
    d = r[r.ticker == coin].copy()
    be, bc = unified_1s(coin); ss = d.slot_start_us.values
    ret = asof(be, bc, ss + 5_000_000) / asof(be, bc, ss) - 1.0
    d = d.assign(fire_us=ss + 5_000_000, slot_end=d.slot_end_us.values, ret=ret,
                 delta=np.abs(ret) * 1e4, lead=np.where(ret > 0, "Up", "Down"))
    d = d[np.isfinite(d.ret) & (d.delta >= 3.0)].reset_index(drop=True)
    print(f"=== {coin}: gated fires={len(d)} ({(d.timeframe=='5m').sum()} 5m / {(d.timeframe=='15m').sum()} 15m) — scanning L25 ===", flush=True)
    ebest, xbest, et, xt = scan_coin(coin, d)
    for _, row in d.iterrows():
        sl = row.slug
        if sl not in ebest or (et[sl] - ebest[sl][0]) > STALE_US: continue
        _, ap, asz = ebest[sl]
        won = (row.ret > 0) == (row.outcome == "Up"); xs = xbest.get(sl)
        for stake in STAKES:
            ve, shares, usd, _l, _u = book_walk_fill(list(ap), list(asz), float(stake), side="buy")
            if shares <= 0 or ve <= 0 or ve >= 0.55: continue
            if xs is not None and (xt[sl] - xs[0]) <= STALE_US:
                vx, sold, _ = sell_at_bid_partial(list(xs[1]), list(xs[2]), shares)
            else:
                vx, sold = np.nan, 0.0
            pnl = (bpnl(vx, ve, sold) if sold > 0 else 0.0) + held_value(shares - sold, ve, won)
            REC.append((coin, row.timeframe, int(row.fire_us), stake, pnl, usd))
    del ebest, xbest

A = pd.DataFrame(REC, columns=["coin", "tf", "fire_us", "stake", "pnl", "dep"])
A.to_parquet(RES / "scalp_capacity_prospect_2026_06_13.parquet")


def maxdd(sub):
    eq = sub.sort_values("fire_us").pnl.cumsum().values
    return float((np.maximum.accumulate(eq) - eq).max()) if len(eq) else np.nan


def ci(v):
    v = np.asarray(v, float); v = v[np.isfinite(v)]
    if len(v) < 5: return (np.nan, np.nan)
    return boot(v)


best_stake = {}
print("\n" + "=" * 118)
print("PER-MARKET CAPACITY TABLE (in-sample L25; gated entry_vwap<0.55). $/tr & $/mo(IS) are IN-SAMPLE; OOS table below.")
hdr = f"{'market':<10}{'stake':>6}{'n':>6}{'fires/d':>8}{'fillf':>6}{'$/tr':>8}{'CI95':>20}{'$/day':>8}{'$/mo(IS)':>9}{'MaxDD$':>9}{'DD/stk':>7}"
print(hdr)
for (coin, tf), g in A.groupby(["coin", "tf"]):
    mkt = f"{coin} {tf}"; safe = None
    for s in STAKES:
        sub = g[g.stake == s]
        if len(sub) < 5: continue
        lo, hi = ci(sub.pnl.values); mean = sub.pnl.mean(); n = len(sub)
        fd = n / NDAYS; dd = maxdd(sub); perday = mean * fd; permo = perday * 30
        flag = ""
        if lo > 0:
            safe = s; flag = ""
        print(f"{mkt:<10}{s:>6}{n:>6}{fd:>8.1f}{sub.dep.mean()/s:>6.2f}{mean:>+8.2f}"
              f"[{lo:>+7.2f},{hi:>+7.2f}]{perday:>+8.1f}{permo:>+9.0f}{dd:>+9.1f}{dd/s:>7.1f}")
    best_stake[(coin, tf)] = safe
    print(f"  -> max stake with CI95 lo>0 (in-sample): {safe}")

print("\n" + "=" * 118)
print("PROSPECT @ recommended stake (= largest in-sample CI-positive stake). 1-MONTH PROFIT OOS-ANCHORED (x0.35; band x0.30-0.45).")
print(f"{'market':<10}{'rec$':>6}{'fires/d':>8}{'$/tr IS':>9}{'$/tr OOS':>9}{'$/mo IS':>9}"
      f"{'$/mo OOS':>10}{'$/mo band':>16}{'MaxDD$ IS':>10}")
tot_is = tot_oos = tot_dd = 0.0; band_lo = band_hi = 0.0
for (coin, tf), s in best_stake.items():
    if s is None:
        print(f"{coin+' '+tf:<10}{'--':>6}  (no CI-positive stake)"); continue
    sub = A[(A.coin == coin) & (A.tf == tf) & (A.stake == s)]
    mean = sub.pnl.mean(); n = len(sub); fd = n / NDAYS
    mo_is = mean * fd * 30; mo_oos = mo_is * HAIRCUT; dd = maxdd(sub)
    blo, bhi = mo_is * HC_LO, mo_is * HC_HI
    tot_is += mo_is; tot_oos += mo_oos; tot_dd += dd; band_lo += blo; band_hi += bhi
    print(f"{coin+' '+tf:<10}{s:>6}{fd:>8.1f}{mean:>+9.2f}{mean*HAIRCUT:>+9.2f}{mo_is:>+9.0f}"
          f"{mo_oos:>+10.0f}[{blo:>+6.0f},{bhi:>+6.0f}]{dd:>+10.1f}")
print(f"{'TOTAL':<10}{'':>6}{'':>8}{'':>9}{'':>9}{tot_is:>+9.0f}{tot_oos:>+10.0f}[{band_lo:>+6.0f},{band_hi:>+6.0f}]{tot_dd:>+10.1f}")
print("\nNOTES: MaxDD is IN-SAMPLE over the 49.4d window = a FLOOR (real DD worse). fillf<1 = size-capped on asks.")
print("  fires/d already nets the ~64% entry-fill rate (fires w/o an L25 book at fire+85ms are dropped).")
print("  DOGE/XRP/BNB EXCLUDED: no production L25 depth -> not depth-sizeable (BBO top-of-book only).")
