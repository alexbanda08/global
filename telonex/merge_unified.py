"""
Unified merge: trentmkelly + bmoney staging -> canonical backfill layer.
  L25 (10Hz btc/eth from trentmkelly + full-depth btc/eth/sol/xrp from bmoney)
     -> canonical/orderbook_l25_backfill/{asset}.parquet  (stream dedup, atomic)
  resolutions (bmoney REAL > trentmkelly settle, by slug)
     -> canonical/resolutions_hf.parquet
  trades (trentmkelly btc/eth)
     -> canonical/trades_polymarket_hf/{asset}.parquet
Separate from production 10Hz orderbook_l25/ (different provenance + period); loader unions.
"""
from __future__ import annotations
import os, time, glob
from pathlib import Path
import numpy as np, pandas as pd
import pyarrow as pa, pyarrow.parquet as pq

ROOT=Path(r"C:\Users\alexandre bandarra\Desktop\global")
CANON=ROOT/"data"/"v4"/"canonical"
TRENT=Path(r"D:\polymarket_hf\hf_staging")
BMONEY=Path(r"D:\bmoney_hf\staging")
BACKFILL=CANON/"orderbook_l25_backfill"; BACKFILL.mkdir(parents=True, exist_ok=True)
TRADES_HF=CANON/"trades_polymarket_hf"; TRADES_HF.mkdir(parents=True, exist_ok=True)
ROW_GROUP=200_000; BATCH=100_000; LEVELS=25
def log(m): print(f"[merge] {time.strftime('%H:%M:%S')} {m}", flush=True)

TCOLS=["timestamp_us","slug","outcome"]+[f"{p}_{i}" for p in ["ask_price","ask_size","bid_price","bid_size"] for i in range(LEVELS)]
TFIELDS=[pa.field("timestamp_us",pa.int64()),pa.field("slug",pa.string()),pa.field("outcome",pa.string())]
for c in TCOLS[3:]: TFIELDS.append(pa.field(c,pa.float32()))
TSCHEMA=pa.schema(TFIELDS)
def project(b):
    arrs=[]
    for c in TCOLS:
        a=b.column(c); tt=TSCHEMA.field(c).type
        if a.type!=tt: a=a.cast(tt)
        arrs.append(a)
    return pa.RecordBatch.from_arrays(arrs, schema=TSCHEMA)

def merge_l25(asset):
    srcs=sorted(glob.glob(str(TRENT/f"{asset}_l25_*.parquet")))+sorted(glob.glob(str(BMONEY/f"{asset}_l25.parquet")))
    if not srcs: log(f"  {asset}: no L25 sources"); return
    out=BACKFILL/f"{asset}.parquet"; tmp=BACKFILL/f"{asset}.parquet.tmp"
    if tmp.exists(): tmp.unlink()
    w=pq.ParquetWriter(str(tmp),TSCHEMA,compression="snappy"); seen={}; tin=0; tkept=0
    for src in srcs:
        pf=pq.ParquetFile(src); s_in=0; s_k=0; t0=time.time()
        for b in pf.iter_batches(batch_size=BATCH, columns=TCOLS):
            s_in+=b.num_rows
            sl=b.column("slug").to_pylist(); oc=b.column("outcome").to_pylist(); ts=b.column("timestamp_us").to_pylist()
            keep=[False]*b.num_rows
            for i in range(b.num_rows):
                k=(sl[i],oc[i]); v=ts[i]; p=seen.get(k)
                if p is None or v>p: keep[i]=True; seen[k]=v
            nk=sum(keep)
            if nk: w.write_batch(project(b if nk==b.num_rows else b.filter(pa.array(keep))), row_group_size=ROW_GROUP); s_k+=nk
        tin+=s_in; tkept+=s_k; log(f"  [{asset}] {os.path.basename(src):<22} in={s_in:>9,} kept={s_k:>9,} ({time.time()-t0:.0f}s)")
    w.close(); md=pq.ParquetFile(str(tmp)).metadata.num_rows
    if md!=tkept: log(f"  [{asset}] MISMATCH {tkept} vs {md}"); tmp.unlink(); return
    os.replace(str(tmp),str(out)); log(f"  [{asset}] OK -> orderbook_l25_backfill/{asset}.parquet {md:,} rows ({out.stat().st_size//1024//1024}MB)")

def merge_resolutions():
    parts=[]
    bm=BMONEY/"resolutions.parquet"
    if bm.exists():
        d=pd.read_parquet(bm);
        # normalize to common cols
        d=d.rename(columns={}); d["price_source"]="bmoney-real"; parts.append(("real",d))
    tr=sorted(glob.glob(str(TRENT/"resolutions_*.parquet")))
    if tr:
        d=pd.concat([pd.read_parquet(f) for f in tr], ignore_index=True)
        keep=["slug","ticker","timeframe","slot_start_us","slot_end_us","outcome","price_source"]
        d=d[[c for c in keep if c in d.columns]]; parts.append(("settle",d))
    if not parts: log("  no resolutions"); return
    allr=pd.concat([p[1] for p in parts], ignore_index=True)
    # bmoney-real precedence: sort so real first, dedup by slug keep first
    allr["_pri"]=np.where(allr["price_source"].astype(str).str.contains("real"),0,1)
    allr=allr.sort_values(["slug","_pri"]).drop_duplicates("slug",keep="first").drop(columns="_pri")
    allr=allr.sort_values("slot_start_us").reset_index(drop=True)
    allr.to_parquet(CANON/"resolutions_hf.parquet", index=False)
    log(f"  resolutions_hf: {len(allr):,} rows (real={int((allr.price_source.str.contains('real')).sum()):,}, settle={int((~allr.price_source.str.contains('real')).sum()):,})")
    log(f"    window {pd.to_datetime(allr.slot_start_us.min(),unit='us',utc=True)} -> {pd.to_datetime(allr.slot_start_us.max(),unit='us',utc=True)}  by ticker: {allr.ticker.value_counts().to_dict()}")

def merge_trades():
    for a in ["btc","eth"]:
        fs=sorted(glob.glob(str(TRENT/f"{a}_trades_*.parquet")))
        if not fs: continue
        d=pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)
        d=d.sort_values(["slug","timestamp_us"]).reset_index(drop=True)
        d.to_parquet(TRADES_HF/f"{a}.parquet", index=False)
        log(f"  trades_hf/{a}: {len(d):,} rows  {pd.to_datetime(d.timestamp_us.min(),unit='us',utc=True)} -> {pd.to_datetime(d.timestamp_us.max(),unit='us',utc=True)}")

def main():
    log("=== L25 backfill ===");
    for a in ["sol","xrp","eth","btc"]: merge_l25(a)
    log("=== resolutions_hf ==="); merge_resolutions()
    log("=== trades_hf ==="); merge_trades()
    log("=== FINAL backfill layer ===")
    for f in sorted(BACKFILL.glob("*.parquet")):
        d=pd.read_parquet(f, columns=["timestamp_us"])
        log(f"  orderbook_l25_backfill/{f.name}: {len(d):,} rows ({f.stat().st_size//1024//1024}MB)  {pd.to_datetime(d.timestamp_us.min(),unit='us',utc=True)} -> {pd.to_datetime(d.timestamp_us.max(),unit='us',utc=True)}")

if __name__=="__main__": main()
