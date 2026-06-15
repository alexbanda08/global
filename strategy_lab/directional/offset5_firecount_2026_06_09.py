"""Fire-count the DEPLOYED 5s scalp vs momalign over the SAME window (Apr24-Jun8).
Lean: BTC 5m, offset 5s, entry fill only (no bid path). Count fires under each gate.
"""
import sys, math
from pathlib import Path
import numpy as np, pandas as pd, datetime as dt
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT/"strategy_lab")); sys.path.insert(0, str(ROOT/"data"/"v4"/"canonical"))
from engine_v2 import LiveMimicConfig, fill_at_book  # noqa
from load import load_orderbook_l25_streaming, load_resolutions, load_klines_1s  # noqa
cfg = LiveMimicConfig(); NOTIONAL = 25.0; SPREAD = 0.05; OFF = 5; BATCH = 300

ts_b, px_b = (lambda k:(k["time_period_start_us"].to_numpy("int64"), k["price_close"].to_numpy(float)))(
    load_klines_1s("BTC").sort_values("time_period_start_us"))
def px_at(t):
    i=int(np.searchsorted(ts_b,t,side="right"))-1; return float(px_b[i]) if i>=0 else np.nan

res = load_resolutions(assets=["BTC"], timeframes=["5m"]).dropna(subset=["slug"]).copy()
res["slot_s"]=(res["slot_start_us"]//1_000_000).astype("int64")
res=res[res.slug.str.contains("-5m-")].drop_duplicates("slug")
out_map=res.set_index("slug")["outcome"].astype(str).to_dict(); slot_map=res.set_index("slug")["slot_s"].to_dict()
slugs=sorted(res.slug.unique()); print(f"BTC 5m slugs={len(slugs)}", flush=True)

rows=[]
for b0 in range(0,len(slugs),BATCH):
    bs=set(slugs[b0:b0+BATCH]); ss=[slot_map[s] for s in bs]
    books=load_orderbook_l25_streaming("btc",slugs=bs,subsample_1hz=False,
            min_ts_us=min(ss)*1_000_000-5_000_000, max_ts_us=(max(ss)+300)*1_000_000+5_000_000)
    for slug in bs:
        s0=slot_map[slug]; e=(s0+OFF)*1_000_000
        pe=px_at(e); p5=px_at(e-5_000_000); p30=px_at(e-30_000_000)
        if not(math.isfinite(pe) and math.isfinite(p5) and p5>0): continue
        lag=(pe/p5-1)*1e4; tok="Up" if lag>0 else "Down"
        mom=(pe/p30-1)*1e4 if (math.isfinite(p30) and p30>0) else np.nan
        f=fill_at_book(books,slug,tok,e,cfg=cfg,spread_filter=SPREAD,notional_usd=NOTIONAL)
        if f is None: continue
        rows.append(dict(slug=slug,e_us=e,lag=lag,abslag=abs(lag),mom=mom,ev=f["vwap"],
                         won=(out_map.get(slug,"")==tok)))
    del books
    if (b0//BATCH)%5==0: print(f"  batch {b0//BATCH} rows={len(rows)}",flush=True)
F=pd.DataFrame(rows)
def d(us): return dt.datetime.utcfromtimestamp(us/1e6).strftime("%Y-%m-%d")
print(f"\nfilled offset-5 entries={len(F)}  period {d(F.e_us.min())}->{d(F.e_us.max())}")
g_cheap=F.ev<0.55; g_lag=F.abslag.between(3,12); g_mom=np.sign(F.lag)==np.sign(F.mom)
print("\n=== FIRE COUNTS (BTC 5m, offset 5s, same Apr24-Jun8 window) ===")
print(f"  deployed d3  (lag[3,12] & vwap<0.55)          : {int((g_lag&g_cheap).sum())} fires")
print(f"  + momalign   (lag[3,12] & vwap<0.55 & momalign): {int((g_lag&g_cheap&g_mom).sum())} fires")
print(f"  (ref) momalign cell at offset 30/60           : 164 fires")
F.to_parquet(r"strategy_lab\directional\_results\offset5_firecount_2026_06_09.parquet",index=False)
