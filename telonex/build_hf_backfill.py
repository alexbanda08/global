"""
HF backfill on disk D: (61GB free). trentmkelly/polymarket_crypto_derivatives.
 Phase 1: snapshot_download whole dataset -> D:/polymarket_hf/hf_raw (parallel, resumable)
 Phase 2: chunked convert -> D:/polymarket_hf/hf_staging/{asset}_{l25,trades}_{chunk}.parquet
          + resolutions_{chunk}.parquet (from final settle). Raw kept (D: has space), resumable.
Merge into canonical (C:) = merge_hf_to_canonical.py.
"""
from __future__ import annotations
import re, time, json, urllib.request
from pathlib import Path
import numpy as np, pandas as pd
from huggingface_hub import snapshot_download, hf_hub_download

REPO="trentmkelly/polymarket_crypto_derivatives"
BASE=Path(r"D:\polymarket_hf")
RAW=BASE/"hf_raw"; STAGE=BASE/"hf_staging"; STAGE.mkdir(parents=True,exist_ok=True)
DONE=STAGE/"_done_chunks.txt"
LEVELS=25; CHUNK=800
DIR_RX=re.compile(r"^([a-z]+)(\d+m)_market(\d+)_(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})_all$")
TF_SEC={"5m":300,"15m":900}
L25_COLS=["timestamp_us","slug","outcome"]+[f"{p}_{i}" for p in ["ask_price","ask_size","bid_price","bid_size"] for i in range(LEVELS)]
def log(m): print(f"[hf] {time.strftime('%H:%M:%S')} {m}", flush=True)

# ---- Phase 1: bulk download ----
log("Phase 1: snapshot_download (parallel, resumable) -> D:")
snapshot_download(repo_id=REPO, repo_type="dataset", local_dir=str(RAW),
                  max_workers=16, allow_patterns=["*.parquet"])
log("download complete")

# ---- enumerate episodes ----
eps=sorted([d.name for d in RAW.iterdir() if d.is_dir() and DIR_RX.match(d.name)])
log(f"{len(eps):,} episodes on disk")
done=set(DONE.read_text().split()) if DONE.exists() else set()
chunks=[eps[i:i+CHUNK] for i in range(0,len(eps),CHUNK)]
log(f"{len(chunks)} chunks; {len(done)} already converted")

def conv(ep):
    m=DIR_RX.match(ep); asset,tf,mkt,dd,tt=m.groups()
    try:
        steps=pd.read_parquet(RAW/ep/"steps.parquet")
        bl=pd.read_parquet(RAW/ep/"book_levels.parquet")
        ev=pd.read_parquet(RAW/ep/"events.parquet")
    except Exception: return None
    ss=pd.Timestamp(f"{dd} {tt.replace('-',':')}",tz="UTC")
    ss_us=int(ss.timestamp()*1_000_000); se_us=ss_us+TF_SEC[tf]*1_000_000
    slug=f"{asset}-updown-{tf}-{int(ss.timestamp())}"
    steps=steps.copy(); steps["timestamp_us"]=(steps["ts"].astype("float64")*1000).astype("int64")
    step_ts=dict(zip(steps["step_index"].astype(float),steps["timestamp_us"]))
    l25=[]
    if len(bl):
        b=bl.copy()
        for c in ["step_index","outcome","side","level_index"]: b[c]=b[c].astype(float)
        b=b[b["level_index"]<LEVELS]; b["price"]=b["price"].astype("float32"); b["size"]=b["size"].astype("float32")
        for (si,oc),g in b.groupby(["step_index","outcome"]):
            ts=step_ts.get(si)
            if ts is None: continue
            row={"timestamp_us":ts,"slug":slug,"outcome":"Up" if oc==0 else "Down"}
            for side,pfx in [(0.0,"bid"),(1.0,"ask")]:
                gg=g[g["side"]==side].set_index("level_index")
                for i in range(LEVELS):
                    fi=float(i)
                    if fi in gg.index: row[f"{pfx}_price_{i}"]=gg.at[fi,"price"]; row[f"{pfx}_size_{i}"]=gg.at[fi,"size"]
                    else: row[f"{pfx}_price_{i}"]=np.nan; row[f"{pfx}_size_{i}"]=np.nan
            l25.append(row)
    trades=[]
    if len(ev):
        e=ev.copy(); e["event_type"]=e["event_type"].astype(float); tr=e[e["event_type"]==1]
        if len(tr):
            tr=tr.copy()
            tr["timestamp_us"]=(tr["ts"].astype("float64")*1000).astype("int64"); tr["slug"]=slug
            tr["outcome"]=np.where(tr["is_down"].astype(str).isin(["True","1","1.0"]),"Down","Up")
            tr["price"]=tr["price"].astype("float64"); tr["size"]=tr["size"].astype("float64")
            tr["side"]=np.where(tr["is_sell"].astype(str).isin(["True","1","1.0"]),"sell","buy")
            trades=tr[["timestamp_us","slug","outcome","price","size","side"]].to_dict("records")
    outcome=None; strike=np.nan; settle=np.nan
    if "up_mid" in steps.columns:
        s=steps.dropna(subset=["up_mid"]).sort_values("timestamp_us")
        if len(s): outcome="Up" if float(s["up_mid"].iloc[-1])>0.5 else "Down"
    if "chainlink_price" in steps.columns:
        cl=steps.dropna(subset=["chainlink_price"]).sort_values("timestamp_us")
        if len(cl):
            strike=float(cl["chainlink_price"].iloc[0]); settle=float(cl["chainlink_price"].iloc[-1])
            if outcome is None and np.isfinite(strike) and np.isfinite(settle): outcome="Up" if settle>strike else "Down"
    res=dict(market_id=mkt,slug=slug,ticker=asset.upper(),timeframe=tf,slot_start_us=ss_us,slot_end_us=se_us,
        outcome=outcome,strike_price=strike,strike_ts_us=ss_us,settlement_price=settle,settle_ts_us=se_us,
        delta_price=(settle-strike if np.isfinite(strike) and np.isfinite(settle) else np.nan),
        price_source="hf-trentmkelly-settle") if outcome else None
    return asset,l25,trades,res

log("Phase 2: convert")
t0=time.time(); n0=len(done)
for ci,chunk in enumerate(chunks):
    cid=f"{ci:04d}"
    if cid in done: continue
    acc={"btc":{"l25":[],"tr":[]},"eth":{"l25":[],"tr":[]}}; res=[]
    for ep in chunk:
        r=conv(ep)
        if r:
            a,l,t,re_=r; acc[a]["l25"]+=l; acc[a]["tr"]+=t
            if re_: res.append(re_)
    for a in ["btc","eth"]:
        if acc[a]["l25"]: pd.DataFrame(acc[a]["l25"])[L25_COLS].to_parquet(STAGE/f"{a}_l25_{cid}.parquet",index=False)
        if acc[a]["tr"]: pd.DataFrame(acc[a]["tr"]).to_parquet(STAGE/f"{a}_trades_{cid}.parquet",index=False)
    if res: pd.DataFrame(res).to_parquet(STAGE/f"resolutions_{cid}.parquet",index=False)
    with open(DONE,"a") as fh: fh.write(cid+"\n")
    dn=ci+1-n0
    log(f"chunk {ci+1}/{len(chunks)} ({(time.time()-t0)/max(dn,1):.0f}s/chunk)")

log("=== DONE ===")
for kind in ["l25","trades"]:
    for a in ["btc","eth"]:
        fs=list(STAGE.glob(f"{a}_{kind}_*.parquet"))
        n=sum(len(pd.read_parquet(f,columns=['timestamp_us'])) for f in fs) if fs else 0
        log(f"  {a}_{kind}: {len(fs)} files, {n:,} rows")
rf=list(STAGE.glob("resolutions_*.parquet"))
log(f"  resolutions: {len(rf)} files, {sum(len(pd.read_parquet(f)) for f in rf):,} rows")
