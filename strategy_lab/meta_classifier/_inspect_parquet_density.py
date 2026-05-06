"""For each production trade slug, plot parquet book state vs time around fill moment.

If parquet has snapshots every ~100ms throughout the market, mid-market book should be visible.
If parquet only catches snapshots far from fill, it's a coverage gap.
"""
import pandas as pd
import pyarrow.parquet as pq
from pathlib import Path
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
CACHE = ROOT / "data/v4/refresh_2026_05_06/cache"

# A few production trades. prod_at = slug_ws + 120s (actual fill time, not resolution audit time).
samples = [
    ("btc","btc-updown-5m-1778043300","Down",0.4682, 1778043300 + 120),  # trade #16, won
    ("btc","btc-updown-5m-1778058600","Up",  0.5100, 1778058600 + 120),  # trade #31, lost
    ("sol","sol-updown-5m-1778049600","Up",  0.4804, 1778049600 + 120),  # trade #28 SELL, lost
    ("sol","sol-updown-5m-1778034600","Down",0.5197, 1778034600 + 120),  # trade #4, won
]
for asset, slug, held, prod_price, prod_at_unix in samples:
    prod_us = prod_at_unix * 1_000_000
    print(f"\n{'='*80}\n{slug}  held={held}  prod_price={prod_price}  fire_at={pd.to_datetime(prod_us, unit='us', utc=True)}\n{'='*80}")
    pf = pq.ParquetFile(CACHE / f"{asset}_orderbook_L25.parquet")
    cols = ["timestamp_us","slug","outcome","bid_price_0","ask_price_0","bid_size_0","ask_size_0"]
    chunks = []
    for batch in pf.iter_batches(batch_size=500_000, columns=cols):
        df = batch.to_pandas()
        f = df[(df.slug == slug) & (df.outcome == held)]
        if len(f):
            chunks.append(f)
    if not chunks:
        print(f"  NO ROWS for ({slug}, {held})")
        continue
    s = pd.concat(chunks).reset_index(drop=True).sort_values("timestamp_us")
    s["dt_s"] = (s.timestamp_us - prod_us) / 1_000_000
    print(f"total snapshots for ({slug}, {held}): {len(s)}")
    print(f"timestamp range: {pd.to_datetime(s.timestamp_us.min(), unit='us', utc=True)} -> {pd.to_datetime(s.timestamp_us.max(), unit='us', utc=True)}")
    print(f"prod fire time:  {pd.to_datetime(prod_us, unit='us', utc=True)}")
    print(f"snapshot dt_s relative to fill: min={s.dt_s.min():.0f}s, max={s.dt_s.max():.0f}s")
    print(f"snapshots within ±5s of fill: {((s.dt_s.abs() <= 5)).sum()}")
    print(f"snapshots within ±60s of fill: {((s.dt_s.abs() <= 60)).sum()}")
    # Show snapshots in ±60s window
    win = s[s.dt_s.abs() <= 60].copy()
    if len(win):
        print(f"\nbook state in ±60s window (15 closest):")
        print(win.iloc[(win.dt_s.abs()).values.argsort()][["dt_s","bid_price_0","bid_size_0","ask_price_0","ask_size_0"]].head(15).to_string(index=False))
    else:
        print(f"\n   NO snapshots within ±60s — closest is dt_s={s.iloc[s.dt_s.abs().values.argmin()].dt_s:+.1f}s")
        # Show book state at prod_at_us±300s window
        win2 = s[s.dt_s.abs() <= 300]
        print(f"   ±300s window has {len(win2)} snapshots")
        if len(win2):
            print(win2[["dt_s","bid_price_0","bid_size_0","ask_price_0","ask_size_0"]].to_string(index=False, max_rows=20))
