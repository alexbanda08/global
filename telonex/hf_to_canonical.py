"""
Prototype: convert ONE HF episode (trentmkelly) -> our canonical orderbook_l25 wide schema.
Proves the backfill path. HF book_levels is LONG (step,outcome,side,level,price,size);
ours is WIDE (timestamp_us, slug, outcome, {ask,bid}_{price,size}_0..24).
"""
from __future__ import annotations
import re, io, urllib.request, json
from pathlib import Path
import numpy as np, pandas as pd

REPO = "trentmkelly/polymarket_crypto_derivatives"
SMP = Path(r"C:\Users\alexandre bandarra\Desktop\global\telonex\hf_sample")
EP_DIR_NAME = "btc15m_market1402567_2026-02-21_15-45-00_all"  # already downloaded by hf_sample.py
LEVELS = 25

steps = pd.read_parquet(SMP/"steps.parquet")
bl    = pd.read_parquet(SMP/"book_levels.parquet")

# --- derive slug/slot from dir name: {asset}{tf}_market{id}_{YYYY-MM-DD}_{HH-MM-SS}_all
m = re.match(r"^([a-z]+)(\d+m)_market(\d+)_(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})_", EP_DIR_NAME)
asset, tf, mkt_id, d, t = m.groups()
slot_dt = pd.Timestamp(f"{d} {t.replace('-',':')}", tz="UTC")
slot_epoch = int(slot_dt.timestamp())
slug = f"{asset}-updown-{tf}-{slot_epoch}"   # our canonical slug convention
print(f"episode -> asset={asset} tf={tf} market_id={mkt_id} slot={slot_dt} epoch={slot_epoch}")
print(f"derived slug: {slug}")

# --- timestamp per step (ms -> us)
steps = steps.copy()
steps["timestamp_us"] = (steps["ts"].astype("float64") * 1000).astype("int64")
step_ts = dict(zip(steps["step_index"].astype(float), steps["timestamp_us"]))

# --- pivot book_levels: (step, outcome) -> wide bid/ask price/size 0..24
bl = bl.copy()
for c in ["step_index","outcome","side","level_index"]:
    bl[c] = bl[c].astype(float)
bl = bl[bl["level_index"] < LEVELS]                  # cap to 25 levels
bl["price"] = bl["price"].astype("float32"); bl["size"] = bl["size"].astype("float32")
# side 0=bid, 1=ask ; outcome 0=Up, 1=Down
out_rows = []
for (si, oc), g in bl.groupby(["step_index","outcome"]):
    ts = step_ts.get(si)
    if ts is None: continue
    row = {"timestamp_us": ts, "slug": slug, "outcome": "Up" if oc==0 else "Down"}
    for side, pfx in [(0.0,"bid"), (1.0,"ask")]:
        gg = g[g["side"]==side].set_index("level_index")
        for i in range(LEVELS):
            if float(i) in gg.index:
                row[f"{pfx}_price_{i}"] = gg.at[float(i),"price"]
                row[f"{pfx}_size_{i}"]  = gg.at[float(i),"size"]
            else:
                row[f"{pfx}_price_{i}"] = np.nan; row[f"{pfx}_size_{i}"] = np.nan
    out_rows.append(row)

l25 = pd.DataFrame(out_rows).sort_values(["outcome","timestamp_us"]).reset_index(drop=True)
# reorder cols to match canonical
cols = ["timestamp_us","slug","outcome"]
cols += [f"ask_price_{i}" for i in range(LEVELS)] + [f"ask_size_{i}" for i in range(LEVELS)]
cols += [f"bid_price_{i}" for i in range(LEVELS)] + [f"bid_size_{i}" for i in range(LEVELS)]
l25 = l25[cols]

print(f"\n=== CONVERTED to canonical orderbook_l25 schema ===")
print(f"  rows: {len(l25):,}  (snapshots × 2 outcomes)")
print(f"  window: {pd.to_datetime(l25.timestamp_us.min(),unit='us',utc=True)} -> {pd.to_datetime(l25.timestamp_us.max(),unit='us',utc=True)}")
print(f"  outcomes: {l25.outcome.unique().tolist()}")
print(f"  cols match canonical: {cols[:6]} ... ({len(cols)} total)")
print(f"\n  sample row (Up, top 3 levels):")
r = l25[l25.outcome=='Up'].iloc[len(l25)//4]
print(f"    ts={pd.to_datetime(r.timestamp_us,unit='us',utc=True)}")
print(f"    asks: " + ", ".join(f"{r[f'ask_price_{i}']:.3f}@{r[f'ask_size_{i}']:.0f}" for i in range(3) if pd.notna(r['ask_price_0'])))
print(f"    bids: " + ", ".join(f"{r[f'bid_price_{i}']:.3f}@{r[f'bid_size_{i}']:.0f}" for i in range(3) if pd.notna(r['bid_price_0'])))

# compare to our real canonical schema
import sys; sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
canon_cols = pd.read_parquet(r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical\orderbook_l25\btc.parquet", columns=["timestamp_us"]).columns
import pyarrow.parquet as pq
sch = pq.ParquetFile(r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical\orderbook_l25\btc.parquet").schema_arrow
canon = [f.name for f in sch]
print(f"\n=== schema parity vs canonical/orderbook_l25/btc.parquet ===")
print(f"  canonical cols: {len(canon)}  converted cols: {len(cols)}")
missing = set(canon) - set(cols); extra = set(cols) - set(canon)
print(f"  in canonical, NOT in converted: {sorted(missing) if missing else 'NONE'}")
print(f"  in converted, NOT in canonical: {sorted(extra) if extra else 'NONE'}")
