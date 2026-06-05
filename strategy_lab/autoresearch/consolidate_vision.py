"""Consolidate downloaded Binance Vision month-parquets into {SYM}_{tf}_full.parquet,
normalizing the mixed ms/us open_time (Binance switched some 2025 files to microseconds)."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
D=Path(__file__).resolve().parent/"_data"/"binance_vision"
SYMS=["BTCUSDT","ETHUSDT","SOLUSDT"]; TFS=["1m","5m","15m","1h","4h","1d"]
def norm_ot(x):
    x=pd.to_numeric(x,errors="coerce").astype("float64")
    # ms ~1e12-1.8e13; us ~1e15-1.8e16. Anything >1e14 is microseconds -> /1000
    x=np.where(x>1e14, x/1000.0, x)
    return x.astype("int64")
for s in SYMS:
    for tf in TFS:
        d=D/s/tf
        parts=sorted(d.glob(f"{s}-{tf}-*.parquet")) if d.exists() else []
        if not parts: continue
        dfs=[]
        for p in parts:
            try:
                df=pd.read_parquet(p); df["open_time"]=norm_ot(df["open_time"]); dfs.append(df)
            except Exception as e: print("skip",p.name,e)
        big=pd.concat(dfs,ignore_index=True)
        big=big[(big.open_time>1.4e12)&(big.open_time<2.0e13)]  # keep sane 2014..2030 ms range
        big=big.sort_values("open_time").drop_duplicates("open_time")
        big.to_parquet(D/f"{s}_{tf}_full.parquet",index=False)
        print(f"{s} {tf}: {len(big):,} bars {pd.to_datetime(big.open_time.min(),unit='ms').date()} -> {pd.to_datetime(big.open_time.max(),unit='ms').date()}",flush=True)
print("done",flush=True)
