"""Exact asset×tf breakdown + date range + download 1 episode + map schema to our canonical L25."""
import urllib.request, json, io, re
from collections import Counter
import pandas as pd
from pathlib import Path
pd.set_option("display.width", 200)

REPO = "trentmkelly/polymarket_crypto_derivatives"
OUT = Path(r"C:\Users\alexandre bandarra\Desktop\global\telonex\hf_sample"); OUT.mkdir(parents=True, exist_ok=True)

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r: return r.read()

sib = json.loads(get(f"https://huggingface.co/api/datasets/{REPO}"))["siblings"]
dirs = sorted(set(p["rfilename"].split("/")[0] for p in sib if "/" in p["rfilename"]))

# parse {asset}{tf}_market{id}_{YYYY-MM-DD}_{HH-MM-SS}_all
rx = re.compile(r"^([a-z]+?)(\d+m)_market(\d+)_(\d{4}-\d{2}-\d{2})_")
combo = Counter(); dates = []
for d in dirs:
    m = rx.match(d)
    if m:
        combo[(m.group(1), m.group(2))] += 1
        dates.append(m.group(4))
print("=== episodes by asset × timeframe ===")
for (a,tf),n in sorted(combo.items()): print(f"  {a:<5} {tf:<4} {n:,}")
print(f"  TOTAL episodes: {sum(combo.values()):,}")
print(f"  date range: {min(dates)} -> {max(dates)}")
print(f"  distinct assets: {sorted(set(a for a,_ in combo))}")
print(f"  distinct timeframes: {sorted(set(tf for _,tf in combo))}")

# download one btc15m episode (3 parquets)
ep = next(d for d in dirs if d.startswith("btc15m"))
print(f"\n=== sample episode: {ep} ===")
frames = {}
for f in ["steps","events","book_levels"]:
    url = f"https://huggingface.co/datasets/{REPO}/resolve/main/{ep}/{f}.parquet"
    data = get(url); (OUT/f"{f}.parquet").write_bytes(data)
    df = pd.read_parquet(io.BytesIO(data)); frames[f] = df
    print(f"\n[{f}] rows={len(df)}  size={len(data)} bytes")
    print(f"  cols: {list(df.columns)}")
    if len(df): print(f"  row0: { {k:str(v)[:30] for k,v in df.iloc[0].to_dict().items()} }")

# map book_levels -> our canonical orderbook_l25 schema
print("\n=== MAP: HF book_levels vs our canonical orderbook_l25 ===")
bl = frames["book_levels"]
print("  HF book_levels cols:", list(bl.columns))
print("  our L25 cols: timestamp_us, slug, outcome, ask_price_0..24, ask_size_0..24, bid_price_0..24, bid_size_0..24")
if "outcome" in bl.columns: print("  HF outcome values:", sorted(bl["outcome"].unique())[:6])
if "side" in bl.columns: print("  HF side values:", sorted(bl["side"].unique())[:6])
# timestamp scale
for c in bl.columns:
    if "ts" in c.lower() or "time" in c.lower():
        v = bl[c].iloc[0]; print(f"  HF time col '{c}' sample={v} (len {len(str(int(v))) if str(v).replace('.','').isdigit() else '?'} digits -> {'us' if v>1e15 else 'ms' if v>1e12 else 's'})")
