"""Robustly consolidate downloaded Binance Vision derivatives parts into {SYM}_{kind}_full.parquet.
Defensive parsing (coerce numerics, drop header-leak rows, normalize ms/us open_time)."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
D=Path(__file__).resolve().parent/"_data"/"binance_vision_deriv"
SYMS=["BTCUSDT","ETHUSDT","SOLUSDT"]
def norm_ot(x):
    x=pd.to_numeric(x,errors="coerce"); x=np.where(x>1e14,x/1000.0,x); return x
for kind in ["klines","funding","metrics"]:
    for s in SYMS:
        base=D/kind/s
        parts=list(base.rglob("*.parquet")) if base.exists() else []
        if not parts: continue
        dfs=[]
        for p in parts:
            try: dfs.append(pd.read_parquet(p))
            except Exception: pass
        if not dfs: continue
        big=pd.concat(dfs,ignore_index=True)
        # coerce any header-leak object cols to numeric where possible
        for col in big.columns:
            if big[col].dtype==object:
                big[col]=pd.to_numeric(big[col],errors="coerce")
        if "open_time" in big.columns:
            big["open_time"]=norm_ot(big["open_time"]); big=big[(big.open_time>1.4e12)&(big.open_time<2.0e13)]
            big=big.sort_values("open_time").drop_duplicates("open_time")
        big=big.dropna(how="all")
        big.to_parquet(D/f"{s}_{kind}_full.parquet",index=False)
        rng=""
        if "open_time" in big.columns and len(big):
            rng=f"{pd.to_datetime(big.open_time.min(),unit='ms').date()}→{pd.to_datetime(big.open_time.max(),unit='ms').date()}"
        print(f"{s} {kind}: {len(big):,} rows {rng}",flush=True)
print("done",flush=True)
