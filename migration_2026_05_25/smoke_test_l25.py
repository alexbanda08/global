"""
Smoke test: verify load_orderbook_l25_streaming reads refresh_2026_05_25 path.
"""
import sys
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
from load import load_orderbook_l25_streaming, load_resolutions
import pandas as pd

res = load_resolutions()
res = res[res.ticker.str.upper() == "BTC"].copy()
# May 25 00:00 UTC threshold
THR = 1779667200_000_000
late = res[res.slot_start_us > THR]
print(f"BTC resolutions in May 25 window: {len(late)}")
assert len(late) > 0, "no late BTC resolutions"

sample_slugs = set(late.slug.head(5))
print(f"sample slugs (first 3): {list(sample_slugs)[:3]}")
books = load_orderbook_l25_streaming("btc", slugs=sample_slugs)
print(f"loaded {len(books)} (slug,outcome) keys")

all_max_ts = 0
for k, (ts, ap, asz, bp, bsz) in books.items():
    if len(ts) and ts.max() > all_max_ts:
        all_max_ts = int(ts.max())

print(f"max ts across loaded books: {pd.to_datetime(all_max_ts, unit='us', utc=True)}" if all_max_ts else "no rows")
if all_max_ts > THR:
    print("PASS: refresh_2026_05_25 path is being read")
else:
    print(f"FAIL: max ts predates May 25 threshold ({pd.to_datetime(THR, unit='us', utc=True)})")
