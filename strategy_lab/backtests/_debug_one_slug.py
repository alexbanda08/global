"""Debug one slug to figure out why backtest produces zero fills."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab/backtests"))

import pandas as pd
from load import load_resolutions
from acc_pc_backtest import load_slug_l25, load_slug_trades, L25_BASELINE

# Check what slot_start_us looks like in resolutions
res = load_resolutions(assets=["BTC"], timeframes=["5m"])
print(f"BTC 5m resolutions: {len(res)} rows")
print(f"Columns: {list(res.columns)}")
print(f"slot_start_us dtype: {res.slot_start_us.dtype}")
print(f"slot_start_us sample: {res.slot_start_us.head(3).tolist()}")
print(f"slot_start_us min/max: {res.slot_start_us.min()} / {res.slot_start_us.max()}")

# Convert one to readable time
sample_us = int(res.slot_start_us.iloc[0])
print(f"First slot_start_us = {sample_us}")
print(f"  as us: {pd.Timestamp(sample_us, unit='us', tz='UTC')}")
print(f"  as s : {pd.Timestamp(sample_us, unit='s', tz='UTC')}")
print()

# Pick a slug in the BASELINE window (Apr 22 → May 6)
window_start = int(pd.Timestamp("2026-04-23", tz="UTC").timestamp()) * 1_000_000
window_end   = int(pd.Timestamp("2026-05-05", tz="UTC").timestamp()) * 1_000_000
print(f"Window: {window_start} → {window_end}")
print(f"  in s: {window_start/1_000_000} → {window_end/1_000_000}")

# Filter — try both units (us and s)
mask_us = (res.slot_start_us >= window_start) & (res.slot_start_us < window_end)
mask_s  = (res.slot_start_us >= window_start/1_000_000) & (res.slot_start_us < window_end/1_000_000)
print(f"With slot_start_us in US units: {mask_us.sum()} slugs match")
print(f"With slot_start_us in  S units: {mask_s.sum()} slugs match")

# Pick the right unit, sample a slug
correct = res[mask_s] if mask_s.sum() > mask_us.sum() else res[mask_us]
correct = correct.sort_values("slot_start_us").reset_index(drop=True)
print(f"\nSelected {len(correct)} slugs in window")

# Pick one slug with trades activity (later in the window)
target = correct.iloc[len(correct) // 2]
slug = target["slug"]
outcome = target["outcome"]
slot_s = int(slug.rsplit("-", 1)[1])
print(f"\nProbing slug: {slug}")
print(f"  outcome: {outcome}")
print(f"  slot_start (s): {slot_s} = {pd.Timestamp(slot_s, unit='s', tz='UTC')}")

# Load L25
import time
t0 = time.time()
l25 = load_slug_l25(L25_BASELINE, slug)
dt = time.time() - t0
print(f"\nLoaded L25 in {dt:.1f}s")
print(f"  outcomes: {list(l25.keys())}")
for oc, data in l25.items():
    n = len(data["ts"])
    t_first = data["ts"][0] / 1e6 if n > 0 else 0
    t_last  = data["ts"][-1] / 1e6 if n > 0 else 0
    print(f"  {oc}: {n} L25 events, ts range [{t_first:.0f}s, {t_last:.0f}s]")
    print(f"     slot_start_s = {slot_s}, "
          f"events before slot_start: {(data['ts']/1e6 < slot_s).sum() if n else 0}, "
          f"during slug: {((data['ts']/1e6 >= slot_s) & (data['ts']/1e6 <= slot_s+300)).sum() if n else 0}")
    # Show book at first event INSIDE the live window
    if n > 0:
        ts_arr = data["ts"]/1e6
        live_mask = (ts_arr >= slot_s) & (ts_arr <= slot_s+300)
        if live_mask.any():
            first_live_idx = live_mask.argmax()
            print(f"     first live event at offset_s={ts_arr[first_live_idx]-slot_s:.1f}: "
                  f"best_bid={data['bp0'][first_live_idx]:.4f} best_ask={data['ap0'][first_live_idx]:.4f} "
                  f"bid_sz={data['bs0'][first_live_idx]:.1f}")
            mid_live_idx = first_live_idx + (n - first_live_idx) // 2
            print(f"     mid live event at offset_s={ts_arr[mid_live_idx]-slot_s:.1f}: "
                  f"best_bid={data['bp0'][mid_live_idx]:.4f} best_ask={data['ap0'][mid_live_idx]:.4f}")
            # sum_bids check
            other_oc = "Down" if oc == "Up" else "Up"

# Load trades
t0 = time.time()
trades = load_slug_trades(slug)
dt = time.time() - t0
print(f"\nLoaded trades in {dt:.1f}s")
print(f"  outcomes: {list(trades.keys())}")
for oc, df in trades.items():
    n = len(df)
    if n > 0:
        ts_arr = df["timestamp_us"].values / 1e6
        live_mask = (ts_arr >= slot_s) & (ts_arr <= slot_s+300)
        print(f"  {oc}: {n} trades, {live_mask.sum()} during live window")
        if live_mask.any():
            live = df[live_mask]
            print(f"     sides: {live['side'].value_counts().to_dict()}")
            print(f"     price range: ${live['price'].min():.3f} - ${live['price'].max():.3f}")
            print(f"     size median: {live['size'].median():.2f}")
