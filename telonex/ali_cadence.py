"""Measure aliplayer BBO cadence (Hz) for 5m/15m + 1h, and rows-per-market-window."""
import numpy as np, pandas as pd
from huggingface_hub import hf_hub_download, HfApi
import os; TOKEN=os.environ.get("HF_TOKEN","")  # export HF_TOKEN=$(cat telonex/.hf_token)
REPO="aliplayer1/polymarket-crypto-updown"
api=HfApi()
files=[f.path for f in api.list_repo_tree(REPO,repo_type="dataset",recursive=True,token=TOKEN) if f.path.endswith(".parquet") and "/orderbook/" in f.path]

def analyze(path):
    lp=hf_hub_download(REPO,path,repo_type="dataset",token=TOKEN)
    df=pd.read_parquet(lp, columns=["ts_ms","market_id","token_id","best_bid","best_ask"])
    df["ts_ms"]=df["ts_ms"].astype("int64")
    # per (market,token) sorted delta
    df=df.sort_values(["market_id","token_id","ts_ms"])
    df["dt_ms"]=df.groupby(["market_id","token_id"])["ts_ms"].diff()
    d=df["dt_ms"].dropna()
    d=d[d>0]
    # rows per market-window (per token)
    rpw=df.groupby(["market_id","token_id"]).size()
    span=df.groupby(["market_id","token_id"])["ts_ms"].agg(lambda x:(x.max()-x.min())/1000.0)
    print(f"\n{path}")
    print(f"  total rows={len(df):,}  markets={df.market_id.nunique():,}")
    print(f"  inter-update dt (ms): median={d.median():.0f}  p25={d.quantile(.25):.0f}  p75={d.quantile(.75):.0f}  min={d.min():.0f}")
    print(f"  => median cadence ~{1000/max(d.median(),1):.1f} Hz  (p75 {1000/max(d.quantile(.75),1):.1f} Hz)")
    print(f"  rows per market-window (per token): median={rpw.median():.0f}  max={rpw.max():,}")
    print(f"  window span sec: median={span.median():.0f}")

# pick a 5-minute, a 15-minute, and a 1-hour file (BTC if present)
def pick(tf):
    cand=[f for f in files if f"/timeframe={tf}/" in f and "crypto=BTC" in f] or [f for f in files if f"/timeframe={tf}/" in f]
    return cand[0] if cand else None
for tf in ["5-minute","15-minute","1-hour"]:
    p=pick(tf)
    if p: analyze(p)
