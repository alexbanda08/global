"""Probe aliplayer1/polymarket-crypto-updown: safety + total size + structure + schema."""
import urllib.request, json, io
from collections import Counter, defaultdict
import pandas as pd

REPO="aliplayer1/polymarket-crypto-updown"
def get(u): return urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0"}),timeout=180).read()

# tree with sizes (recursive, paginated)
def tree():
    out=[]; url=f"https://huggingface.co/api/datasets/{REPO}/tree/main?recursive=true&expand=true"
    data=json.loads(get(url))
    return data
items=tree()
files=[i for i in items if i.get("type")=="file"]
print(f"=== {REPO} ===")
print(f"  total files: {len(files):,}")
total=sum(i.get("size",0) for i in files)
print(f"  TOTAL SIZE: {total/1024/1024/1024:.2f} GB ({total/1024/1024:.0f} MB)")

# size by top dir + extension
bydir=defaultdict(int); bydir_n=Counter(); exts=Counter()
for i in files:
    p=i["path"]; top=p.split("/")[0] if "/" in p else "(root)"
    bydir[top]+=i.get("size",0); bydir_n[top]+=1
    exts[p.rsplit(".",1)[-1] if "." in p else "noext"]+=1
print(f"\n  file types: {dict(exts)}")
nonpq=[i['path'] for i in files if not i['path'].endswith('.parquet')]
print(f"  NON-parquet: {nonpq[:20]}")
danger=[i['path'] for i in files if i['path'].endswith((".py",".sh",".exe",".dll",".bat",".ps1",".js",".pkl",".pickle",".zip"))]
print(f"  scripts/executables/loaders: {danger if danger else 'NONE — safe'}")
print(f"\n  size by top-level dir:")
for d,sz in sorted(bydir.items(), key=lambda x:-x[1])[:20]:
    print(f"    {d:<28} {sz/1024/1024:>8.0f} MB  ({bydir_n[d]} files)")

print(f"\n  sample paths:")
for i in files[:25]: print("    ", i["path"], f"({i.get('size',0)//1024}KB)")

# README
try:
    print("\n=== README head ===")
    print(get(f"https://huggingface.co/datasets/{REPO}/resolve/main/README.md").decode(errors="replace")[:1600])
except Exception as e: print("no readme", e)
