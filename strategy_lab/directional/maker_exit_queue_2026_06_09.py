"""GAP #1: QUEUE-AWARE maker-exit + peg-to-ask trail vs pure-taker +60.
Upgrades maker_exit_sim_2026_06_06 (optimistic "first buy-trade>=target" fill) with:
  (a) QUEUE position: a resting SELL at price P fills only after incoming BUY volume at >=P
      EXCEEDS the L25 ask-queue resting at <=P when we post (you're behind that queue).
  (b) PEG-TO-ASK TRAIL: peg = current best ask, re-pegged up as the ask rises (captures runners),
      instead of a fixed 0.65 target (which caps runners).
Fallback: unfilled by +60s -> taker-cross bid_60 (the validated baseline).
Fidelity: L25 native 10Hz ask path + Poly buy-trade tape. Fees: taker 0.07*p*(1-p)/sh ; maker rebate 0.20x.
Judge: bootstrap CI + paired diff vs taker60, IS/OOS split, per-asset.
"""
import sys, math, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT/"strategy_lab")); sys.path.insert(0, str(ROOT/"data/v4/canonical"))
from engine_v2 import LiveMimicConfig, find_book_strict, sell_at_bid_partial  # noqa
from load import load_orderbook_l25_streaming  # noqa
CANON = ROOT/"data/v4/canonical"; cfg = LiveMimicConfig(); LAT=85_000; HOR=60; BATCH=300

c = pd.read_parquet(ROOT/"strategy_lab/directional/_results/scalp_hedge_physics_cache_2026_06_03.parquet")
c = c[(c.asset.isin(["BTC","ETH"]))&(c.filled==1)&(c.entry_vwap<0.55)].copy()
lf = pd.read_parquet(ROOT/"strategy_lab/lag_taker_fires_oos_2026_06_01.parquet")[["slug","direction"]].drop_duplicates("slug")
c = c.merge(lf,on="slug",how="left").dropna(subset=["direction"]).sort_values("fire_us").reset_index(drop=True)
print(f"gated scalp fires (BTC/ETH vwap<0.55) w/ direction = {len(c)}", flush=True)

tk=lambda p:0.07*p*(1-p); reb=lambda p:0.20*0.07*p*(1-p)

# buy-trade tape per (slug,lead)
TAPE={}
for a in ["btc","eth"]:
    ca=c[c.asset==a.upper()]
    if not len(ca): continue
    t=pd.read_parquet(CANON/"trades_polymarket"/f"{a}.parquet",
        columns=["slug","outcome","timestamp_us","price","size"],
        filters=[("slug","in",set(ca.slug)),("side","in",{"buy","BUY"})]).sort_values("timestamp_us")
    for k,v in t.groupby(["slug","outcome"]):
        TAPE[k]=(v["timestamp_us"].values, v["price"].values.astype(float), v["size"].values.astype(float))

def ask_snaps(books,slug,tok,t0,t1):
    rec=books.get((slug,tok));
    if rec is None: return None
    ts,ap,asz=rec[0],rec[1],rec[2]
    m=(ts>=t0)&(ts<=t1)
    if not m.any(): return None
    return ts[m],ap[m],asz[m]

def queue_ahead(ap_row,asz_row,peg):
    # total ask size resting at price <= peg (ahead of a new order posted at peg)
    px=np.asarray(ap_row,float); sz=np.asarray(asz_row,float)
    g=np.isfinite(px)&np.isfinite(sz)&(px>0)&(px<=peg+1e-9)
    return float(sz[g].sum())

recs=[]
slugs=sorted(c.slug.unique())
asset_of=c.set_index("slug")["asset"].to_dict()
for a in ["BTC","ETH"]:
    sa=[s for s in slugs if asset_of[s]==a]
    for b0 in range(0,len(sa),BATCH):
        bs=set(sa[b0:b0+BATCH]); cc=c[c.slug.isin(bs)]
        tmin=int(cc.fire_us.min())-2_000_000; tmax=int(cc.fire_us.max())+HOR*1_000_000+5_000_000
        books=load_orderbook_l25_streaming(a.lower(),slugs=bs,subsample_1hz=False,min_ts_us=tmin,max_ts_us=tmax)
        for r in cc.itertuples():
            ev,sh,lead=float(r.entry_vwap),float(r.shares),r.direction; fire=int(r.fire_us)
            b60=pd.to_numeric(pd.Series([r.bid_60]),errors="coerce").iloc[0]
            b60=float(b60) if np.isfinite(b60) else (1.0 if r.won else 0.0)
            taker60=(b60-ev)*sh - tk(b60)*sh
            snaps=ask_snaps(books,r.slug,lead,fire,fire+HOR*1_000_000)
            tape=TAPE.get((r.slug,lead))
            # ---- (A) queue-aware FIXED peg at entry best-ask ----
            maker_fix=taker60
            if snaps is not None:
                ts0,ap0,asz0=snaps
                peg=float(ap0[0,0]) if np.isfinite(ap0[0,0]) else np.nan
                if math.isfinite(peg) and peg>ev and tape is not None:
                    Q=queue_ahead(ap0[0],asz0[0],peg)
                    tt,pp,ss=tape; w=(tt>fire)&(tt<=fire+HOR*1_000_000)&(pp>=peg-1e-9)
                    cum=np.cumsum(ss[w]) if w.any() else np.array([])
                    if len(cum) and cum[-1] > Q:   # our sh clears after queue Q absorbed
                        maker_fix=(peg-ev)*sh + reb(peg)*sh
            # ---- (B) peg-to-ask TRAIL: re-peg to rising best-ask; fill at the level a buy clears ----
            maker_trail=taker60
            if snaps is not None and tape is not None:
                ts0,ap0,asz0=snaps; tt,pp,ss=tape
                filled=False; cur_peg=float(ap0[0,0]) if np.isfinite(ap0[0,0]) else np.nan
                qi=0  # ask-snapshot index
                if math.isfinite(cur_peg):
                    Q=queue_ahead(ap0[0],asz0[0],cur_peg); cum=0.0
                    order=np.argsort(tt)  # already sorted
                    w=(tt>fire)&(tt<=fire+HOR*1_000_000)
                    for j in np.where(w)[0]:
                        # advance peg to best-ask at this time
                        while qi+1<len(ts0) and ts0[qi+1]<=tt[j]:
                            qi+=1
                            na=float(ap0[qi,0])
                            if math.isfinite(na) and na>cur_peg:   # ask rose -> trail up, reset queue
                                cur_peg=na; Q=queue_ahead(ap0[qi],asz0[qi],cur_peg); cum=0.0
                        if pp[j]>=cur_peg-1e-9:
                            cum+=ss[j]
                            if cum>Q:
                                maker_trail=(cur_peg-ev)*sh + reb(cur_peg)*sh; filled=True; break
            recs.append(dict(asset=a,slug=r.slug,fire_us=fire,ev=ev,sh=sh,won=bool(r.won),
                             taker60=taker60,maker_fix=maker_fix,maker_trail=maker_trail))
        del books
    print(f"  [{a}] done rows={len(recs)}",flush=True)
D=pd.DataFrame(recs).sort_values("fire_us").reset_index(drop=True)
D.to_parquet(ROOT/"strategy_lab/directional/_results/maker_exit_queue_2026_06_09.parquet")

def boot(v,nb=5000):
    v=np.asarray(v); i=np.random.randint(0,len(v),(nb,len(v))); return tuple(np.percentile(v[i].mean(1),[2.5,97.5]))
def show(v,name):
    t=v.mean()/v.std(ddof=1)*np.sqrt(len(v)) if v.std()>0 else np.nan; lo,hi=boot(v)
    print(f"  {name:20s} n={len(v):4d} $/tr={v.mean():+.3f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}] {'POS' if lo>0 else '.'}")
cut=int(len(D)*0.6)
for split,sl in [("ALL",slice(None)),("IS",slice(0,cut)),("OOS",slice(cut,None))]:
    d=D.iloc[sl]
    print(f"\n=== {split} n={len(d)} ===")
    show(d.taker60.values,"taker60 [baseline]"); show(d.maker_fix.values,"maker queue-fixed"); show(d.maker_trail.values,"maker peg-trail")
    for col in ["maker_fix","maker_trail"]:
        diff=(d[col]-d.taker60).values; lo,hi=boot(diff)
        print(f"    {col} - taker60: {diff.mean():+.4f} CI=[{lo:+.4f},{hi:+.4f}] {'SIG+' if lo>0 else ('SIG-' if hi<0 else 'ns')}")
# per asset (ALL)
for a in ["BTC","ETH"]:
    d=D[D.asset==a]
    if len(d)<20: continue
    df=(d.maker_trail-d.taker60).values; lo,hi=boot(df)
    print(f"  [{a}] maker_trail-taker60: {df.mean():+.4f} CI=[{lo:+.4f},{hi:+.4f}]")
print("\nREAD: deploy maker-exit only if (queue-fixed OR peg-trail) beats taker60 with paired CI>0 AND both BTC+ETH positive.")
