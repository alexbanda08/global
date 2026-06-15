"""Overlap: do the deployed 5s scalp and the momalign 30/60s scalp fire the SAME
slugs (markets) and the SAME side? Re-walk the 164 momalign slugs at offset 5,
evaluate the DEPLOYED gate (lag[3,12] & vwap<0.55) there. Compare side too.
"""
import sys, math
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT/"strategy_lab")); sys.path.insert(0, str(ROOT/"data"/"v4"/"canonical"))
from engine_v2 import LiveMimicConfig, fill_at_book  # noqa
from load import load_orderbook_l25_streaming, load_resolutions, load_klines_1s  # noqa
cfg = LiveMimicConfig(); NOTIONAL = 25.0; SPREAD = 0.05

C = pd.read_parquet(r"strategy_lab\directional\_results\midwindow_scalp_cache_2026_06_09.parquet")
M = C[(C.asset=="BTC")&(C.tf=="5m")&(C.offset.isin([30,60]))&(C.entry_vwap<0.55)
      &(C.abs_lag.between(3,12))&(np.sign(C.lag_bps)==np.sign(C.mom30))].copy()
# momalign fire per slug (keep the offset it fired + its side)
M = M.sort_values("offset").drop_duplicates("slug")  # 1 per slug
print(f"momalign slugs={len(M)}", flush=True)
slot = {r.slug: int(r.e_us//1_000_000 - r.offset) for r in M.itertuples()}  # slot_start sec
mtok = M.set_index("slug")["tok"].to_dict()

ts_b, px_b = (lambda k:(k["time_period_start_us"].to_numpy("int64"), k["price_close"].to_numpy(float)))(
    load_klines_1s("BTC").sort_values("time_period_start_us"))
def px_at(t):
    i=int(np.searchsorted(ts_b,t,side="right"))-1; return float(px_b[i]) if i>=0 else np.nan

slugs=sorted(M.slug.unique()); rows=[]
for b0 in range(0,len(slugs),300):
    bs=set(slugs[b0:b0+300]); ss=[slot[s] for s in bs]
    books=load_orderbook_l25_streaming("btc",slugs=bs,subsample_1hz=False,
            min_ts_us=min(ss)*1_000_000-5_000_000, max_ts_us=(max(ss)+300)*1_000_000+5_000_000)
    for slug in bs:
        e=(slot[slug]+5)*1_000_000; pe=px_at(e); p5=px_at(e-5_000_000)
        fires5=False; tok5=None; ev5=np.nan
        if math.isfinite(pe) and math.isfinite(p5) and p5>0:
            lag=(pe/p5-1)*1e4; tok5="Up" if lag>0 else "Down"
            f=fill_at_book(books,slug,tok5,e,cfg=cfg,spread_filter=SPREAD,notional_usd=NOTIONAL)
            if f is not None:
                ev5=f["vwap"]
                fires5 = (3<=abs(lag)<=12) and (ev5<0.55)
        rows.append(dict(slug=slug, mtok=mtok[slug], dep5_fires=fires5, tok5=tok5, ev5=ev5))
    del books
O=pd.DataFrame(rows)
n=len(O)
both = O.dep5_fires
same_side = both & (O.tok5==O.mtok)
opp_side = both & (O.tok5!=O.mtok)
print(f"\n=== of {n} MOMALIGN-fired slugs, does the DEPLOYED 5s scalp ALSO fire? ===")
print(f"  deployed ALSO fires (overlap)  : {int(both.sum())}  ({100*both.mean():.0f}%)")
print(f"     -> SAME side  (double-long)  : {int(same_side.sum())}  ({100*same_side.sum()/n:.0f}%)")
print(f"     -> OPP  side  (hedge)        : {int(opp_side.sum())}  ({100*opp_side.sum()/n:.0f}%)")
print(f"  deployed does NOT fire (momalign-ONLY): {int((~both).sum())}  ({100*(~both).mean():.0f}%)")
O.to_csv(r"strategy_lab\directional\_results\scalp_overlap_2026_06_09.csv", index=False)
