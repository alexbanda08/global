"""
Merge HF staging (telonex/hf_staging/) into canonical:
  - {asset}_l25.parquet  -> canonical/orderbook_l25/{asset}.parquet   (stream dedup, atomic)
  - {asset}_trades.parquet -> canonical/trades_polymarket/{asset}.parquet (schema-aligned append-dedup)
  - resolutions.parquet  -> canonical/resolutions_from_rtds.parquet   (append-dedup by slug)
BTC + ETH only (the dataset's assets).
"""
from __future__ import annotations
import os, time
from pathlib import Path
import numpy as np, pandas as pd
import pyarrow as pa, pyarrow.parquet as pq

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
STAGE = Path(r"D:\polymarket_hf\hf_staging")
CANON = ROOT/"data"/"v4"/"canonical"
L25_DIR = CANON/"orderbook_l25"
ROW_GROUP=200_000; BATCH=100_000; LEVELS=25
ASSETS=["btc","eth"]

def log(m): print(f"[hf-merge] {time.strftime('%H:%M:%S')} {m}", flush=True)

# ---- L25 target schema ----
TCOLS=["timestamp_us","slug","outcome"]
for pfx in ["ask_price","ask_size","bid_price","bid_size"]:
    for i in range(LEVELS): TCOLS.append(f"{pfx}_{i}")
TFIELDS=[pa.field("timestamp_us",pa.int64()),pa.field("slug",pa.string()),pa.field("outcome",pa.string())]
for c in TCOLS[3:]: TFIELDS.append(pa.field(c,pa.float32()))
TSCHEMA=pa.schema(TFIELDS)

def project(batch):
    arrs=[]
    for c in TCOLS:
        a=batch.column(c); tt=TSCHEMA.field(c).type
        if a.type!=tt: a=a.cast(tt)
        arrs.append(a)
    return pa.RecordBatch.from_arrays(arrs, schema=TSCHEMA)

def merge_l25(asset):
    canon=L25_DIR/f"{asset}.parquet"
    chunks=sorted(STAGE.glob(f"{asset}_l25_*.parquet"))
    if not chunks: log(f"  {asset}: no staging L25 chunks, skip"); return
    tmp=L25_DIR/f"{asset}.parquet.tmp"
    if tmp.exists(): tmp.unlink()
    sources=([("canonical",canon)] if canon.exists() else []) + [("hf",c) for c in chunks]
    w=pq.ParquetWriter(str(tmp),TSCHEMA,compression="snappy")
    seen={}; tin=0; tkept=0
    for label,src in sources:
        pf=pq.ParquetFile(str(src)); s_in=0; s_k=0; t0=time.time()
        for b in pf.iter_batches(batch_size=BATCH, columns=TCOLS):
            s_in+=b.num_rows
            sl=b.column("slug").to_pylist(); oc=b.column("outcome").to_pylist(); ts=b.column("timestamp_us").to_pylist()
            keep=[False]*b.num_rows
            for i in range(b.num_rows):
                k=(sl[i],oc[i]); v=ts[i]; p=seen.get(k)
                if p is None or v>p: keep[i]=True; seen[k]=v
            nk=sum(keep)
            if nk==0: continue
            w.write_batch(project(b if nk==b.num_rows else b.filter(pa.array(keep))), row_group_size=ROW_GROUP)
            s_k+=nk
        tin+=s_in; tkept+=s_k
        log(f"  [{asset}] {label:<9} in={s_in:>10,} kept={s_k:>10,} ({time.time()-t0:.0f}s)")
    w.close()
    md=pq.ParquetFile(str(tmp)).metadata.num_rows
    if md!=tkept: log(f"  [{asset}] MISMATCH {tkept} vs {md} — abort"); tmp.unlink(); return
    os.replace(str(tmp),str(canon))
    log(f"  [{asset}] L25 OK -> {md:,} rows ({canon.stat().st_size//1024//1024}MB)")

def merge_trades(asset):
    chunks=sorted(STAGE.glob(f"{asset}_trades_*.parquet"))
    if not chunks: log(f"  {asset}: no staging trades chunks, skip"); return
    cp=CANON/"trades_polymarket"/f"{asset}.parquet"
    old=pd.read_parquet(cp) if cp.exists() else pd.DataFrame()
    new=pd.concat([pd.read_parquet(c) for c in chunks], ignore_index=True)
    # align to canonical schema
    new=new.rename(columns={})
    new["price"]=new["price"].astype("float64"); new["size"]=new["size"].astype("float64")
    for c,default in [("local_timestamp_us",pd.NA),("exchange","polymarket"),("market_id",pd.NA),
                      ("asset_id",pd.NA),("trade_id",pd.NA),("origin_asset_id",pd.NA),
                      ("outcome_id",pd.NA),("source","hf-trentmkelly")]:
        if c not in new.columns: new[c]=default
    if len(old):
        cols=list(old.columns)
        for c in cols:
            if c not in new.columns: new[c]=pd.NA
        new=new[cols]
        for c in old.columns:
            if old[c].dtype=="object": old[c]=old[c].astype(str)
            if c in new.columns and new[c].dtype=="object": new[c]=new[c].astype(str)
        c=pd.concat([old,new],ignore_index=True)
        c=c.drop_duplicates(["slug","timestamp_us","outcome","price","size","side"], keep="last")
    else:
        c=new
    c=c.sort_values(["slug","timestamp_us"]).reset_index(drop=True)
    c.to_parquet(cp,index=False)
    log(f"  [{asset}] trades -> {len(c):,} rows  (added {len(c)-len(old):,})")

def merge_resolutions():
    chunks=sorted(STAGE.glob("resolutions_*.parquet"))
    if not chunks: log("  no staging resolutions chunks, skip"); return
    cp=CANON/"resolutions_from_rtds.parquet"
    old=pd.read_parquet(cp) if cp.exists() else pd.DataFrame()
    new=pd.concat([pd.read_parquet(c) for c in chunks], ignore_index=True)
    log(f"  resolutions: old={len(old):,}  hf={len(new):,}")
    if len(old):
        for c in old.columns:
            if c not in new.columns: new[c]=pd.NA
        new=new[old.columns]
        c=pd.concat([old,new],ignore_index=True).drop_duplicates("slug", keep="first")
    else:
        c=new
    c=c.sort_values("slot_start_us").reset_index(drop=True)
    c.to_parquet(cp,index=False)
    log(f"  resolutions_from_rtds -> {len(c):,} rows (added {len(c)-len(old):,})")
    by=c[c.price_source=='hf-trentmkelly-settle'] if 'price_source' in c.columns else c.iloc[0:0]
    if len(by): log(f"    HF-derived: {len(by):,}  window {pd.to_datetime(by.slot_start_us.min(),unit='us',utc=True)} -> {pd.to_datetime(by.slot_start_us.max(),unit='us',utc=True)}")

def main():
    log("=== L25 ===")
    for a in ASSETS: merge_l25(a)
    log("=== trades ===")
    for a in ASSETS: merge_trades(a)
    log("=== resolutions ===")
    merge_resolutions()
    log("=== FINAL ===")
    for a in ASSETS:
        d=pd.read_parquet(L25_DIR/f"{a}.parquet", columns=["timestamp_us"])
        log(f"  L25/{a}: {len(d):,} rows  {pd.to_datetime(d.timestamp_us.min(),unit='us',utc=True)} -> {pd.to_datetime(d.timestamp_us.max(),unit='us',utc=True)}")

if __name__=="__main__": main()
