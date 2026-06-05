"""Convert trentmkelly -> 10Hz L25 (matches our canonical) + trades + settle-resolutions.
Multiprocessing over episodes. Chunked + resumable. Reads local raw on D:."""
from __future__ import annotations
import re, time, os
from pathlib import Path
import numpy as np, pandas as pd
from multiprocessing import Pool

BASE=Path(r"D:\polymarket_hf"); RAW=BASE/"hf_raw"; STAGE=BASE/"hf_staging"; STAGE.mkdir(parents=True,exist_ok=True)
DONE=STAGE/"_done_chunks.txt"
LEVELS=25; CHUNK=1600; BUCKET_US=100_000  # 10Hz
DIR_RX=re.compile(r"^([a-z]+)(\d+m)_market(\d+)_(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})_all$")
TF_SEC={"5m":300,"15m":900}
L25_COLS=["timestamp_us","slug","outcome"]+[f"{p}_{i}" for p in ["ask_price","ask_size","bid_price","bid_size"] for i in range(LEVELS)]
def log(m): print(f"[conv] {time.strftime('%H:%M:%S')} {m}", flush=True)

def book_wide(bl, step_ts, slug):
    """Vectorized numpy-scatter long->wide. Col layout matches L25_COLS[3:]:
    ask_price_0..24(0-24), ask_size_0..24(25-49), bid_price_0..24(50-74), bid_size_0..24(75-99)."""
    si=bl["step_index"].to_numpy(); oc=bl["outcome"].to_numpy().astype(np.int64)
    side=bl["side"].to_numpy().astype(np.int64); lvl=bl["level_index"].to_numpy().astype(np.int64)
    price=bl["price"].to_numpy().astype(np.float32); size=bl["size"].to_numpy().astype(np.float32)
    m=lvl<LEVELS
    if not m.any(): return None
    si=si[m]; oc=oc[m]; side=side[m]; lvl=lvl[m]; price=price[m]; size=size[m]
    # unique (step,outcome) -> row id
    key=si.astype(np.float64)*2+oc
    uniq,codes=np.unique(key, return_inverse=True)
    n=len(uniq)
    arr=np.full((n,100), np.nan, dtype=np.float32)
    is_bid=(side==0)
    price_col=np.where(is_bid, 50+lvl, lvl)       # bid_price 50.., ask_price 0..
    size_col =np.where(is_bid, 75+lvl, 25+lvl)    # bid_size 75.., ask_size 25..
    arr[codes, price_col]=price
    arr[codes, size_col]=size
    # meta per unique row
    u_si=(uniq//2); u_oc=(uniq%2).astype(np.int64)  # uniq=si*2+oc but si float -> recompute
    # robust: take first si,oc per code
    first=np.full(n,-1,dtype=np.int64)
    order=np.argsort(codes, kind="stable")
    seen=np.zeros(n,dtype=bool)
    cc=codes[order]
    # first occurrence index per code
    firstpos=np.full(n,-1,dtype=np.int64)
    fo=np.where(np.concatenate(([True], cc[1:]!=cc[:-1])))[0]
    firstpos[cc[fo]]=order[fo]
    si_u=si[firstpos]; oc_u=oc[firstpos]
    ts=np.array([step_ts.get(float(x), np.nan) for x in si_u], dtype=np.float64)
    keep=np.isfinite(ts)
    if not keep.any(): return None
    arr=arr[keep]; ts=ts[keep].astype(np.int64); oc_u=oc_u[keep]
    out=pd.DataFrame(arr, columns=L25_COLS[3:])
    out.insert(0,"timestamp_us",ts); out.insert(1,"slug",slug)
    out.insert(2,"outcome",np.where(oc_u==0,"Up","Down"))
    return out

def conv(ep):
    m=DIR_RX.match(ep); asset,tf,mkt,dd,tt=m.groups()
    try:
        steps=pd.read_parquet(RAW/ep/"steps.parquet"); bl=pd.read_parquet(RAW/ep/"book_levels.parquet"); ev=pd.read_parquet(RAW/ep/"events.parquet")
    except Exception: return None
    ss=pd.Timestamp(f"{dd} {tt.replace('-',':')}",tz="UTC"); ss_us=int(ss.timestamp()*1_000_000); se_us=ss_us+TF_SEC[tf]*1_000_000
    slug=f"{asset}-updown-{tf}-{int(ss.timestamp())}"
    steps=steps.copy(); steps["timestamp_us"]=(steps["ts"].astype("float64")*1000).astype("int64")
    steps["_b"]=steps["timestamp_us"]//BUCKET_US
    keep=set(steps.sort_values("timestamp_us").drop_duplicates("_b",keep="first")["step_index"].astype(float))
    step_ts=dict(zip(steps["step_index"].astype(float),steps["timestamp_us"]))
    if len(bl): bl=bl[bl["step_index"].astype(float).isin(keep)]
    l25=book_wide(bl, step_ts, slug) if len(bl) else None
    trades=None
    if len(ev):
        e=ev[ev["event_type"].astype(float)==1]
        if len(e):
            e=e.copy(); e["timestamp_us"]=(e["ts"].astype("float64")*1000).astype("int64"); e["slug"]=slug
            e["outcome"]=np.where(e["is_down"].astype(str).isin(["True","1","1.0"]),"Down","Up")
            e["price"]=e["price"].astype("float64"); e["size"]=e["size"].astype("float64")
            e["side"]=np.where(e["is_sell"].astype(str).isin(["True","1","1.0"]),"sell","buy")
            trades=e[["timestamp_us","slug","outcome","price","size","side"]]
    outcome=None; strike=np.nan; settle=np.nan
    if "up_mid" in steps.columns:
        s=steps.dropna(subset=["up_mid"]).sort_values("timestamp_us")
        if len(s): outcome="Up" if float(s["up_mid"].iloc[-1])>0.5 else "Down"
    if "chainlink_price" in steps.columns:
        cl=steps.dropna(subset=["chainlink_price"]).sort_values("timestamp_us")
        if len(cl):
            strike=float(cl["chainlink_price"].iloc[0]); settle=float(cl["chainlink_price"].iloc[-1])
            if outcome is None and np.isfinite(strike) and np.isfinite(settle): outcome="Up" if settle>strike else "Down"
    res=dict(market_id=mkt,slug=slug,ticker=asset.upper(),timeframe=tf,slot_start_us=ss_us,slot_end_us=se_us,outcome=outcome,
        strike_price=strike,strike_ts_us=ss_us,settlement_price=settle,settle_ts_us=se_us,
        delta_price=(settle-strike if np.isfinite(strike) and np.isfinite(settle) else np.nan),
        price_source="hf-trentmkelly-settle") if outcome else None
    return asset, (None if l25 is None else l25), (None if trades is None else trades), res

def main():
    eps=sorted([d.name for d in RAW.iterdir() if d.is_dir() and DIR_RX.match(d.name)])
    log(f"{len(eps):,} episode dirs")
    done=set(DONE.read_text().split()) if DONE.exists() else set()
    chunks=[eps[i:i+CHUNK] for i in range(0,len(eps),CHUNK)]
    log(f"{len(chunks)} chunks of {CHUNK}; {len(done)} done; pool={max(1,os.cpu_count()-2)}")
    t0=time.time(); n0=len(done)
    with Pool(processes=max(1,os.cpu_count()-2)) as pool:
        for ci,chunk in enumerate(chunks):
            cid=f"{ci:04d}"
            if cid in done: continue
            acc={"btc":{"l25":[],"tr":[]},"eth":{"l25":[],"tr":[]}}; res=[]
            for r in pool.imap_unordered(conv, chunk, chunksize=8):
                if not r: continue
                a,l,t,re_=r
                if a not in acc: continue
                if l is not None: acc[a]["l25"].append(l)
                if t is not None: acc[a]["tr"].append(t)
                if re_: res.append(re_)
            for a in ["btc","eth"]:
                if acc[a]["l25"]: pd.concat(acc[a]["l25"], ignore_index=True).to_parquet(STAGE/f"{a}_l25_{cid}.parquet",index=False)
                if acc[a]["tr"]: pd.concat(acc[a]["tr"], ignore_index=True).to_parquet(STAGE/f"{a}_trades_{cid}.parquet",index=False)
            if res: pd.DataFrame(res).to_parquet(STAGE/f"resolutions_{cid}.parquet",index=False)
            with open(DONE,"a") as fh: fh.write(cid+"\n")
            log(f"chunk {ci+1}/{len(chunks)} ({(time.time()-t0)/max(ci+1-n0,1):.1f}s/chunk, ETA {((time.time()-t0)/max(ci+1-n0,1)*(len(chunks)-ci-1))/60:.0f}min)")
    log("CONVERT DONE")
    for kind in ["l25","trades"]:
        for a in ["btc","eth"]:
            fs=list(STAGE.glob(f"{a}_{kind}_*.parquet")); n=sum(len(pd.read_parquet(f,columns=['timestamp_us'])) for f in fs) if fs else 0
            log(f"  {a}_{kind}: {len(fs)} files, {n:,} rows")
    rf=list(STAGE.glob("resolutions_*.parquet")); log(f"  resolutions: {len(rf)} files, {sum(len(pd.read_parquet(f)) for f in rf):,} rows")

if __name__=="__main__":
    main()
