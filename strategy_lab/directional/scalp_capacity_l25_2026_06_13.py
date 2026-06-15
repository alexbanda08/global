"""
SCALP CAPACITY vs BOOK DEPTH — production L25 multi-level walk (2026-06-13).

QUESTION: how much capital can the +60s oracle-lag scalp absorb before depth slippage kills the edge?
The validated OOS is BBO (top-of-book only) → cannot answer depth. Only production L25 (Apr22-Jun11,
BTC/ETH/SOL, 25 levels, native 10Hz) has multi-level depth WITH early-slot coverage to fill a +5s entry.

CAVEAT (declared): this is the IN-SAMPLE window, so the ABSOLUTE $/tr at $25 is optimistic (the causal
OOS says ~+$0.9-1.5/tr — see scalp_causal_asof_oneshot). But capacity = a LIQUIDITY/slippage property,
robust to edge-overfit. The deliverable is the DECAY SHAPE: entry vwap rises + exit vwap falls as stake
grows; $/tr and ROI%/notional decay; $/day = $/tr × fills/day peaks then falls. Read the shape, anchor
the $25 level to the OOS number.

MODEL (consistent with the corrected scalp lib):
  signal: causal 5s binance-1s return at slot_start (end-time asof, the patched convention), delta>=3bps.
  fire: slot_start+5s +85ms latency. entry: walk LEAD-token ASKS for $STAKE (real depth) -> vwap_e, shares,
        filled_usd. gate vwap_e<0.55. exit: +60s (clamp slot_end)+85ms, walk LEAD BIDS for shares ->
        sold_sh, vwap_x. pnl = bpnl(vwap_x,vwap_e,sold_sh) + held_value(shares-sold_sh, vwap_e, won).
  120s asof-staleness guard on both snapshots (else entry skip / exit held-full).

STAKE SWEEP: 25,50,100,200,400,800,1600,3200. Per coin + pooled, gated vwap_e<0.55:
  fills, entry_fillfrac (filled_usd/stake), vwap_e, vwap_x, exit_fillfrac (sold/shares),
  $/tr (+t,CI), ROI%/deployed, $/day (=mean$/tr × fills/day). Plus capacity verdict.
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

CANON = ROOT / "data/v4/canonical"
RES = ROOT / "strategy_lab/directional/_results"
LAT_US = 85_000; STALE_US = 120_000_000
STAKES = [25, 50, 100, 200, 400, 800, 1600, 3200]
COINS = os.environ.get("OOS_COINS", "BTC,ETH,SOL").split(",")
LIMIT = int(os.environ.get("CAP_LIMIT", "0"))   # smoke: first N gated slugs/coin
AP = [f"ask_price_{i}" for i in range(25)]; ASZ = [f"ask_size_{i}" for i in range(25)]
BP = [f"bid_price_{i}" for i in range(25)]; BSZ = [f"bid_size_{i}" for i in range(25)]
COLS = ["timestamp_us", "slug", "outcome"] + AP + ASZ + BP + BSZ


def unified_1s(coin):
    sym = f"BINANCE_SPOT_{coin.upper()}_USDT"
    df = pd.read_parquet(CANON / "klines_1s.parquet", columns=["symbol_id", "time_period_start_us", "price_close"],
                         filters=[("symbol_id", "==", sym)])
    df = df.sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    s = df.time_period_start_us.values.astype("int64")
    return s + 1_000_000, df.price_close.values.astype(float)   # END-time index (causal)


def asof(ts, v, t):
    i = np.searchsorted(ts, t, "right") - 1
    return np.where(i >= 0, v[np.clip(i, 0, len(v) - 1)], np.nan)


def cell(v):
    v = np.asarray(v, float); v = v[np.isfinite(v)]
    if len(v) < 5: return (len(v), np.nan, np.nan, np.nan, np.nan)
    t = v.mean() / v.std(ddof=1) * np.sqrt(len(v)) if v.std() > 0 else np.nan
    lo, hi = boot(v)
    return (len(v), v.mean(), t, lo, hi)


def scan_coin(coin, fires):
    """Single streaming pass over the L25 parquet; keep entry(asks)+exit(bids) snapshot per lead slug."""
    lead = dict(zip(fires.slug, fires.lead))
    et = dict(zip(fires.slug, (fires.fire_us + LAT_US).astype("int64")))
    xt = dict(zip(fires.slug, (np.minimum(fires.fire_us + 60_000_000, fires.slot_end) + LAT_US).astype("int64")))
    gset = set(fires.slug)
    ebest, xbest = {}, {}   # slug -> (ts, ap[25], asz[25]) / (ts, bp[25], bsz[25])
    p = CANON / "orderbook_l25" / f"{coin.lower()}.parquet"
    pf = pq.ParquetFile(p)
    for batch in pf.iter_batches(batch_size=300_000, columns=COLS):
        df = batch.to_pandas()
        df = df[df.slug.isin(gset)]
        if not len(df):
            continue
        df["lead"] = df.slug.map(lead)
        df = df[df.outcome == df.lead]
        if not len(df):
            continue
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
POOL = {s: [] for s in STAKES}          # pnl per stake (pooled, gated)
POOL_DEP = {s: [] for s in STAKES}      # deployed notional per fire
POOL_VE = {s: [] for s in STAKES}; POOL_VX = {s: [] for s in STAKES}; POOL_EFF = {s: [] for s in STAKES}
NDAYS = 49.4

for coin in COINS:
    d = r[r.ticker == coin].copy()
    be, bc = unified_1s(coin); ss = d.slot_start_us.values
    ret = asof(be, bc, ss + 5_000_000) / asof(be, bc, ss) - 1.0
    d = d.assign(fire_us=ss + 5_000_000, slot_end=d.slot_end_us.values, ret=ret,
                 delta=np.abs(ret) * 1e4, lead=np.where(ret > 0, "Up", "Down"))
    d = d[np.isfinite(d.ret) & (d.delta >= 3.0)].reset_index(drop=True)
    if LIMIT > 0:
        d = d.iloc[:LIMIT].reset_index(drop=True)
    print(f"\n=== {coin}: gated fires={len(d)} — scanning L25 ===", flush=True)
    ebest, xbest, et, xt = scan_coin(coin, d)
    print(f"  snapshots: entry={len(ebest)} exit={len(xbest)} (of {len(d)} fires)", flush=True)

    per = {s: dict(pnl=[], dep=[], ve=[], vx=[], eff=[]) for s in STAKES}
    for _, row in d.iterrows():
        sl = row.slug
        if sl not in ebest:
            continue
        ets, ap, asz = ebest[sl]
        if (et[sl] - ets) > STALE_US:
            continue
        won = (row.ret > 0) == (row.outcome == "Up")
        xs = xbest.get(sl)
        for stake in STAKES:
            ve, shares, usd, _lv, _u = book_walk_fill(list(ap), list(asz), float(stake), side="buy")
            if shares <= 0 or ve <= 0 or ve >= 1 or ve >= 0.55:   # gate vwap_e<0.55
                continue
            if xs is not None and (xt[sl] - xs[0]) <= STALE_US:
                vx, sold, _su = sell_at_bid_partial(list(xs[1]), list(xs[2]), shares)
            else:
                vx, sold = np.nan, 0.0
            rem = shares - sold
            pnl = (bpnl(vx, ve, sold) if sold > 0 else 0.0) + held_value(rem, ve, won)
            per[stake]["pnl"].append(pnl); per[stake]["dep"].append(usd)
            per[stake]["ve"].append(ve); per[stake]["eff"].append(sold / shares if shares > 0 else 0.0)
            if sold > 0: per[stake]["vx"].append(vx)
        # only count a fire once for fills/day accounting at the base stake handled via per-stake n

    print(f"  {'stake':>6} {'n':>5} {'fillfrac':>8} {'vwap_e':>7} {'vwap_x':>7} {'exitfrac':>8} "
          f"{'$/tr':>8} {'t':>6} {'CI95':>18} {'ROI%/dep':>9} {'$/day':>9}")
    for s in STAKES:
        pnl = per[s]["pnl"]; POOL[s] += pnl; POOL_DEP[s] += per[s]["dep"]
        POOL_VE[s] += per[s]["ve"]; POOL_VX[s] += per[s]["vx"]; POOL_EFF[s] += per[s]["eff"]
        n, mean, t, lo, hi = cell(pnl)
        if n < 5:
            print(f"  {s:>6} {n:>5} (few)"); continue
        dep = np.mean(per[s]["dep"]); ff = dep / s
        roi = 100 * mean / dep if dep > 0 else np.nan
        perday = mean * n / NDAYS
        print(f"  {s:>6} {n:>5} {ff:>8.2f} {np.mean(per[s]['ve']):>7.3f} "
              f"{(np.mean(per[s]['vx']) if per[s]['vx'] else np.nan):>7.3f} {np.mean(per[s]['eff']):>8.2f} "
              f"{mean:>+8.3f} {t:>+6.2f} [{lo:>+7.3f},{hi:>+7.3f}] {roi:>+9.3f} {perday:>+9.1f}")
    del ebest, xbest

print("\n" + "=" * 100)
print("POOLED (BTC+ETH+SOL, gated vwap_e<0.55):")
print(f"  {'stake':>6} {'n':>6} {'fillfrac':>8} {'vwap_e':>7} {'vwap_x':>7} {'exitfrac':>8} "
      f"{'$/tr':>8} {'t':>6} {'CI95':>20} {'ROI%/dep':>9} {'$/day':>9} {'depl/day$':>10}")
for s in STAKES:
    n, mean, t, lo, hi = cell(POOL[s])
    if n < 5:
        print(f"  {s:>6} {n:>6} (few)"); continue
    dep = np.mean(POOL_DEP[s]); ff = dep / s
    roi = 100 * mean / dep if dep > 0 else np.nan
    perday = mean * n / NDAYS; depday = dep * n / NDAYS
    print(f"  {s:>6} {n:>6} {ff:>8.2f} {np.mean(POOL_VE[s]):>7.3f} "
          f"{(np.mean(POOL_VX[s]) if POOL_VX[s] else np.nan):>7.3f} {np.mean(POOL_EFF[s]):>8.2f} "
          f"{mean:>+8.3f} {t:>+6.2f} [{lo:>+7.3f},{hi:>+7.3f}] {roi:>+9.3f} {perday:>+9.1f} {depday:>+10.0f}")

pd.to_pickle({s: dict(pnl=POOL[s], dep=POOL_DEP[s], ve=POOL_VE[s], eff=POOL_EFF[s]) for s in STAKES},
             RES / "scalp_capacity_l25_2026_06_13.pkl")
print("\nREAD: $/tr decays as vwap_e rises & vwap_x falls (depth slippage). $/day = $/tr × fills/day;")
print("  capacity-optimal stake = where $/day peaks; max usable = last stake with CI95 lo>0.")
print("  ROI%/dep -> 0 = depth saturated. fillfrac<1 = stake exceeds available ask depth (size-capped).")
print("CAVEAT: in-sample window -> ABSOLUTE $/tr optimistic; anchor $25 to OOS +$0.9-1.5; DECAY shape is the result.")
