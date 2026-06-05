"""aliplayer1 size+structure via HfApi.list_repo_tree + schema samples."""
import io
from collections import Counter, defaultdict
import pandas as pd
from huggingface_hub import HfApi, hf_hub_download

REPO="aliplayer1/polymarket-crypto-updown"
api=HfApi()
files=[f for f in api.list_repo_tree(REPO, repo_type="dataset", recursive=True) if getattr(f,"size",None) is not None]
print(f"=== {REPO} ===")
print(f"  total files: {len(files):,}")
total=sum(f.size for f in files)
print(f"  TOTAL SIZE: {total/1024/1024/1024:.2f} GB ({total/1024/1024:.0f} MB)")
bydir=defaultdict(int); bydir_n=Counter(); exts=Counter()
for f in files:
    p=f.path; seg=p.split("/")
    top="/".join(seg[:2]) if len(seg)>1 else p
    bydir[top]+=f.size; bydir_n[top]+=1
    exts[p.rsplit(".",1)[-1] if "." in p else "noext"]+=1
print(f"  file types: {dict(exts)}")
danger=[f.path for f in files if f.path.endswith((".py",".sh",".exe",".dll",".bat",".ps1",".js",".pkl",".pickle",".zip"))]
print(f"  scripts/executables/loaders: {danger if danger else 'NONE — safe'}")
print(f"\n  size by dir prefix:")
for d,sz in sorted(bydir.items(), key=lambda x:-x[1])[:25]:
    print(f"    {d:<34} {sz/1024/1024:>8.1f} MB ({bydir_n[d]})")

# sample schemas: orderbook + ticks + markets
def sample(path):
    try:
        lp=hf_hub_download(REPO, path, repo_type="dataset")
        df=pd.read_parquet(lp)
        print(f"\n=== {path} ===  rows={len(df):,}")
        print(f"  cols: {list(df.columns)}")
        if len(df): print(f"  row0: { {k:str(v)[:30] for k,v in df.iloc[0].to_dict().items()} }")
    except Exception as e: print(f"\n{path}: ERR {e}")

ob=next((f.path for f in files if "/orderbook/" in f.path and f.path.endswith(".parquet")), None)
tk=next((f.path for f in files if "/ticks/" in f.path and f.path.endswith(".parquet")), None)
mk=next((f.path for f in files if f.path.endswith("markets.parquet")), None)
sp=next((f.path for f in files if "/spot_prices/" in f.path and f.path.endswith(".parquet")), None)
for p in [mk, ob, tk, sp]:
    if p: sample(p)

# date range + asset coverage from markets
if mk:
    mdf=pd.read_parquet(hf_hub_download(REPO, mk, repo_type="dataset"))
    for c in mdf.columns:
        if c.lower() in ("asset","ticker","symbol"): print(f"\n  markets assets: {sorted(mdf[c].astype(str).unique())}")
        if c.lower() in ("slug","market_slug"): print(f"  markets slug samples: {mdf[c].astype(str).unique()[:8].tolist()}")
        if "timeframe" in c.lower() or c.lower()=="market_type": print(f"  timeframes: {sorted(mdf[c].astype(str).unique())[:10]}")
