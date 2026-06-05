"""Explore trentmkelly/polymarket_crypto_derivatives: file tree, assets, timeframes. urllib only."""
import urllib.request, json
from collections import Counter

REPO = "trentmkelly/polymarket_crypto_derivatives"
API = f"https://huggingface.co/api/datasets/{REPO}"

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()

# 1. dataset metadata
print("=== dataset info ===")
info = json.loads(get(API))
print("  lastModified:", info.get("lastModified"))
print("  downloads:", info.get("downloads"), " likes:", info.get("likes"))
sib = info.get("siblings", [])
print("  total files (siblings):", len(sib))

# 2. file tree (recursive) — paginate
print("\n=== sampling file tree ===")
paths = [s["rfilename"] for s in sib]
print("  first 20 paths:")
for p in paths[:20]: print("   ", p)

# 3. infer structure: top-level dirs + asset/timeframe tokens
tops = Counter(p.split("/")[0] for p in paths)
print("\n  top-level entries (count):", dict(list(tops.items())[:20]))

# 4. hunt asset + timeframe tokens across all paths
assets = Counter()
tfs = Counter()
for p in paths:
    pl = p.lower()
    for a in ["btc","bitcoin","eth","ethereum","sol","solana","xrp","doge","dogecoin","bnb","hype"]:
        if a in pl: assets[a]+=1
    for t in ["5m","15m","1m","1h","-5-","-15-"]:
        if t in pl: tfs[t]+=1
print("\n  asset tokens in paths:", dict(assets))
print("  timeframe tokens in paths:", dict(tfs))

# 5. parquet file names present
pq = [p for p in paths if p.endswith(".parquet")]
print(f"\n  parquet files: {len(pq)}")
for p in pq[:15]: print("   ", p)

# 6. README
print("\n=== README (head) ===")
try:
    rd = get(f"https://huggingface.co/datasets/{REPO}/resolve/main/README.md").decode(errors="replace")
    print(rd[:1500])
except Exception as e:
    print("  no README:", e)
