"""
aliplayer BBO + ticks -> canonical via DuckDB (out-of-core, handles billions of rows).
Output: D:/global_data/canonical_bbo/{coin}.parquet  + canonical_bbo_trades/{coin}.parquet
"""
import time, glob, re
from pathlib import Path
import numpy as np, pandas as pd
import duckdb

RAW=Path(r"D:\aliplayer_hf"); OUT=Path(r"D:\global_data\canonical_bbo"); OUT.mkdir(parents=True,exist_ok=True)
TR_OUT=Path(r"D:\global_data\canonical_bbo_trades"); TR_OUT.mkdir(parents=True,exist_ok=True)
TFMAP={"5-minute":"5m","15-minute":"15m","1-hour":"1h","4-hour":"4h"}
def log(m): print(f"[duck] {time.strftime('%H:%M:%S')} {m}", flush=True)

# build market_id -> slug map (markets.parquet small)
mk=pd.read_parquet(RAW/"data"/"markets.parquet")
mk["crypto_l"]=mk["crypto"].astype(str).str.lower()
mk["tf"]=mk["timeframe"].astype(str).map(TFMAP)
mk["start_ts"]=pd.to_numeric(mk["start_ts"],errors="coerce")
built=mk["crypto_l"]+"-updown-"+mk["tf"].astype(str)+"-"+mk["start_ts"].astype("Int64").astype(str)
mk["slug"]=np.where(mk["slug"].astype(str).str.len()>3, mk["slug"].astype(str), built)
mm=mk[["market_id","slug"]].copy(); mm["market_id"]=mm["market_id"].astype(str)
mm=mm.dropna(subset=["slug"]).drop_duplicates("market_id")
log(f"markets map: {len(mm):,}")

con=duckdb.connect()
con.execute("PRAGMA memory_limit='14GB'"); con.execute("PRAGMA threads=6")
con.register("mm", mm)
con.execute("CREATE TABLE mmap AS SELECT market_id, slug FROM mm")

coins=sorted({re.search(r"crypto=([A-Za-z]+)",p).group(1) for p in glob.glob(str(RAW/"data"/"orderbook"/"*"))})
log(f"coins: {coins}")
TFCASE="CASE timeframe WHEN '5-minute' THEN '5m' WHEN '15-minute' THEN '15m' WHEN '1-hour' THEN '1h' WHEN '4-hour' THEN '4h' ELSE timeframe END"

for c in coins:
    cl=c.lower(); t0=time.time()
    src=str(RAW/"data"/"orderbook"/f"crypto={c}"/"**"/"*.parquet").replace("\\","/")
    out=str(OUT/f"{cl}.parquet").replace("\\","/")
    con.execute(f"""
      COPY (
        SELECT CAST(ob.ts_ms AS BIGINT)*1000 AS timestamp_us, mm.slug AS slug, ob.outcome AS outcome,
               CAST(ob.best_bid AS FLOAT) AS best_bid, CAST(ob.best_ask AS FLOAT) AS best_ask,
               CAST(ob.best_bid_size AS FLOAT) AS best_bid_size, CAST(ob.best_ask_size AS FLOAT) AS best_ask_size,
               {TFCASE} AS timeframe
        FROM read_parquet('{src}', hive_partitioning=1) ob
        JOIN mmap mm ON CAST(ob.market_id AS VARCHAR)=mm.market_id
      ) TO '{out}' (FORMAT parquet, COMPRESSION snappy, ROW_GROUP_SIZE 500000)
    """)
    n=con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
    log(f"  BBO {cl}: {n:,} rows ({Path(out).stat().st_size//1024//1024}MB) ({time.time()-t0:.0f}s)")

# ticks -> trades
for c in coins:
    cl=c.lower(); t0=time.time()
    src=str(RAW/"data"/"ticks"/f"crypto={c}"/"**"/"*.parquet").replace("\\","/")
    if not glob.glob(str(RAW/"data"/"ticks"/f"crypto={c}"/"**"/"*.parquet"), recursive=True): continue
    out=str(TR_OUT/f"{cl}.parquet").replace("\\","/")
    con.execute(f"""
      COPY (
        SELECT CAST(tk.timestamp_ms AS BIGINT)*1000 AS timestamp_us, mm.slug AS slug, tk.outcome AS outcome,
               tk.side AS side, CAST(tk.price AS DOUBLE) AS price, CAST(tk.size_usdc AS DOUBLE) AS size_usdc,
               TRY_CAST(tk.spot_price_usdt AS DOUBLE) AS spot_price, {TFCASE} AS timeframe
        FROM read_parquet('{src}', hive_partitioning=1) tk
        JOIN mmap mm ON CAST(tk.market_id AS VARCHAR)=mm.market_id
        WHERE CAST(tk.timestamp_ms AS BIGINT) > 1735689600000  -- drop epoch-0 / pre-2025 (the 1970 bug)
      ) TO '{out}' (FORMAT parquet, COMPRESSION snappy)
    """)
    n=con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
    log(f"  trades {cl}: {n:,} rows ({Path(out).stat().st_size//1024//1024}MB) ({time.time()-t0:.0f}s)")

log("=== DONE ===")
for f in sorted(OUT.glob("*.parquet")): log(f"  bbo/{f.name}: {f.stat().st_size//1024//1024}MB")
