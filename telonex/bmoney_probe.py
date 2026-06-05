"""Probe bmoney1321/polymarket-crypto-5m-15m: safety (file types/loader) + does it have L2 book depth?"""
import urllib.request, json, io
from collections import Counter
import pandas as pd

REPO="bmoney1321/polymarket-crypto-5m-15m"
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0"}),timeout=120).read()

info=json.loads(get(f"https://huggingface.co/api/datasets/{REPO}"))
sib=info["siblings"]; paths=[s["rfilename"] for s in sib]
print(f"=== {REPO} ===")
print(f"  lastModified: {info.get('lastModified')}  downloads: {info.get('downloads')}  total files: {len(paths)}")

# SAFETY: file types + any loader/executable
exts=Counter(p.rsplit('.',1)[-1] if '.' in p else 'noext' for p in paths)
print(f"  file types: {dict(exts)}")
nonpq=[p for p in paths if not p.endswith('.parquet')]
print(f"  NON-parquet files: {nonpq}")
danger=[p for p in paths if p.endswith((".py",".sh",".exe",".dll",".bat",".ps1",".js",".pkl",".pickle",".zip"))]
print(f"  executable/script/loader files: {danger if danger else 'NONE — safe'}")

# STRUCTURE: top-level dirs + asset/tf/datatype tokens
tops=Counter(p.split("/")[0] for p in paths if "/" in p)
print(f"\n  top-level dirs: {dict(list(tops.items())[:15])}")
print(f"  sample paths:")
for p in paths[:25]: print("    ", p)

# data-type subdirs (orderbook? trades? resolutions?)
kinds=Counter()
for p in paths:
    pl=p.lower()
    for k in ["orderbook","order_book","book","trade","price","resolution","metadata","quote","depth"]:
        if k in pl: kinds[k]+=1
print(f"\n  data-type tokens in paths: {dict(kinds)}")
assets=Counter()
for p in paths:
    pl=p.lower()
    for a in ["btc","eth","sol","xrp","doge","bnb","hype"]:
        if a in pl: assets[a]+=1
print(f"  asset tokens: {dict(assets)}")

# README
try:
    print("\n=== README head ===")
    print(get(f"https://huggingface.co/datasets/{REPO}/resolve/main/README.md").decode(errors="replace")[:1800])
except Exception as e: print("no readme", e)

# download ONE order-book-ish file and inspect schema -> is it L2 depth?
ob = next((p for p in paths if p.endswith(".parquet") and any(k in p.lower() for k in ["orderbook","order_book","book","depth"])), None)
if not ob:
    ob = next((p for p in paths if p.endswith(".parquet")), None)
print(f"\n=== sample file: {ob} ===")
if ob:
    data=get(f"https://huggingface.co/datasets/{REPO}/resolve/main/{ob}")
    print(f"  magic: {data[:4]}  size: {len(data)} bytes")
    if data[:4]==b"PAR1":
        df=pd.read_parquet(io.BytesIO(data))
        print(f"  rows={len(df)}  cols={list(df.columns)}")
        # detect depth: count bid_price_N / level columns
        depth=[c for c in df.columns if any(t in c.lower() for t in ["bid_price_","ask_price_","level","_0","_1","_2"])]
        print(f"  depth-looking cols ({len(depth)}): {depth[:20]}")
        if len(df): print(f"  row0={ {k:str(v)[:30] for k,v in df.iloc[0].to_dict().items()} }")
