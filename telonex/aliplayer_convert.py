"""
Convert aliplayer (native BBO, 7 coins) -> canonical/orderbook_bbo/{coin}.parquet on D:
  orderbook/crypto=X/timeframe=Y/*.parquet -> BBO rows (ts_us, slug, outcome, best_bid/ask + sizes, timeframe)
  ticks/...                                -> trades (per coin) -> trades_polymarket_hf2/{coin}.parquet on D:
Stream per partition-file (9.3B rows). slug from markets.parquet (market_id->slug), fallback constructed.
"""
from __future__ import annotations
import glob, re, time
from pathlib import Path
import numpy as np, pandas as pd
import pyarrow as pa, pyarrow.parquet as pq

RAW=Path(r"D:\aliplayer_hf"); OUT=Path(r"D:\global_data\canonical_bbo"); OUT.mkdir(parents=True, exist_ok=True)
TR_OUT=Path(r"D:\global_data\canonical_bbo_trades"); TR_OUT.mkdir(parents=True, exist_ok=True)
TFMAP={"5-minute":"5m","15-minute":"15m","1-hour":"1h","4-hour":"4h"}
def log(m): print(f"[ali] {time.strftime('%H:%M:%S')} {m}", flush=True)

# market_id -> slug map
mk=pd.read_parquet(RAW/"data"/"markets.parquet")
mk["crypto_l"]=mk["crypto"].astype(str).str.lower()
mk["tf"]=mk["timeframe"].astype(str).map(TFMAP)
mk["start_ts"]=pd.to_numeric(mk["start_ts"], errors="coerce")
mk["slug_built"]=mk["crypto_l"]+"-updown-"+mk["tf"].astype(str)+"-"+mk["start_ts"].astype("Int64").astype(str)
mk["slug_final"]=np.where(mk["slug"].astype(str).str.len()>3, mk["slug"].astype(str), mk["slug_built"])
m2s=dict(zip(mk["market_id"].astype(str), mk["slug_final"]))
log(f"markets map: {len(m2s):,} market_ids")

BBO_SCHEMA=pa.schema([pa.field("timestamp_us",pa.int64()),pa.field("slug",pa.string()),pa.field("outcome",pa.string()),
    pa.field("best_bid",pa.float32()),pa.field("best_ask",pa.float32()),
    pa.field("best_bid_size",pa.float32()),pa.field("best_ask_size",pa.float32()),pa.field("timeframe",pa.string())])

def coin_tf(path):
    m=re.search(r"crypto=([A-Za-z]+).*?timeframe=([\w-]+)", path);
    return (m.group(1).lower(), TFMAP.get(m.group(2),m.group(2))) if m else (None,None)

# ---- orderbook BBO (stream batches; some part files are multi-GB) ----
obf=sorted(glob.glob(str(RAW/"data"/"orderbook"/"**"/"*.parquet"), recursive=True))
log(f"{len(obf)} orderbook partition files")
writers={}; counts={}
OBCOLS=["ts_ms","market_id","outcome","best_bid","best_ask","best_bid_size","best_ask_size"]
for i,f in enumerate(obf):
    coin,tf=coin_tf(f)
    if not coin: continue
    pf=pq.ParquetFile(f)
    for bt in pf.iter_batches(batch_size=500_000, columns=OBCOLS):
        df=bt.to_pandas()
        if not len(df): continue
        df["timestamp_us"]=(pd.to_numeric(df["ts_ms"],errors="coerce")*1000).astype("int64")
        df["slug"]=df["market_id"].astype(str).map(m2s); df["timeframe"]=tf
        for c in ["best_bid","best_ask","best_bid_size","best_ask_size"]:
            df[c]=pd.to_numeric(df[c],errors="coerce").astype("float32")
        out=df[["timestamp_us","slug","outcome","best_bid","best_ask","best_bid_size","best_ask_size","timeframe"]]
        out=out[out["slug"].notna()]
        if not len(out): continue
        if coin not in writers:
            writers[coin]=pq.ParquetWriter(str(OUT/f"{coin}.parquet"), BBO_SCHEMA, compression="snappy"); counts[coin]=0
        writers[coin].write_table(pa.Table.from_pandas(out, schema=BBO_SCHEMA, preserve_index=False))
        counts[coin]+=len(out)
    if (i+1)%100==0: log(f"  orderbook {i+1}/{len(obf)}  counts={ {k:f'{v/1e6:.0f}M' for k,v in counts.items()} }")
for w in writers.values(): w.close()
log(f"orderbook_bbo DONE: {counts}")

# ---- ticks -> trades ----
tkf=sorted(glob.glob(str(RAW/"data"/"ticks"/"**"/"*.parquet"), recursive=True))
log(f"{len(tkf)} tick files")
tw={}; tc={}
TR_SCHEMA=pa.schema([pa.field("timestamp_us",pa.int64()),pa.field("slug",pa.string()),pa.field("outcome",pa.string()),
    pa.field("side",pa.string()),pa.field("price",pa.float64()),pa.field("size_usdc",pa.float64()),
    pa.field("spot_price",pa.float64()),pa.field("timeframe",pa.string())])
for i,f in enumerate(tkf):
    coin,tf=coin_tf(f)
    if not coin: continue
    pf=pq.ParquetFile(f)
    for bt in pf.iter_batches(batch_size=500_000):
        df=bt.to_pandas()
        if not len(df): continue
        df["timestamp_us"]=(pd.to_numeric(df["timestamp_ms"],errors="coerce")*1000).astype("int64")
        df["slug"]=df["market_id"].astype(str).map(m2s); df["timeframe"]=tf
        df["price"]=pd.to_numeric(df["price"],errors="coerce")
        df["size_usdc"]=pd.to_numeric(df.get("size_usdc"),errors="coerce")
        df["spot_price"]=pd.to_numeric(df.get("spot_price_usdt"),errors="coerce")
        out=df[["timestamp_us","slug","outcome","side","price","size_usdc","spot_price","timeframe"]]
        out=out[out["slug"].notna()]
        if not len(out): continue
        if coin not in tw:
            tw[coin]=pq.ParquetWriter(str(TR_OUT/f"{coin}.parquet"), TR_SCHEMA, compression="snappy"); tc[coin]=0
        tw[coin].write_table(pa.Table.from_pandas(out, schema=TR_SCHEMA, preserve_index=False))
        tc[coin]+=len(out)
for w in tw.values(): w.close()
log(f"trades DONE: {tc}")

log("=== FINAL ===")
for f in sorted(OUT.glob("*.parquet")):
    md=pq.ParquetFile(str(f)).metadata.num_rows; log(f"  orderbook_bbo/{f.name}: {md:,} rows ({f.stat().st_size//1024//1024}MB)")
for f in sorted(TR_OUT.glob("*.parquet")):
    md=pq.ParquetFile(str(f)).metadata.num_rows; log(f"  bbo_trades/{f.name}: {md:,} rows ({f.stat().st_size//1024//1024}MB)")
