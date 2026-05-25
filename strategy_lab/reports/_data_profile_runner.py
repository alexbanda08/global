"""One-shot profiler for overnight research session.

Runs all 4 task buckets and dumps stdout. Caller pipes/captures output.

Reproduce:
    cd C:\\Users\\alexandre bandarra\\Desktop\\global
    py strategy_lab/reports/_data_profile_runner.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

from load import (  # noqa: E402
    load_klines_1s,
    load_orderbook_l25_streaming,
    load_trades,
    load_resolutions,
    slug_to_ws_s,
)


def hr(t: str) -> None:
    print()
    print("=" * 72)
    print(t)
    print("=" * 72)


# ---------------------------------------------------------------------------
# TASK 1 — 1s binance klines
# ---------------------------------------------------------------------------
hr("TASK 1: 1s binance klines")

t0 = time.time()
kg = load_klines_1s()  # no asset filter — full table
print(f"load_klines_1s() loaded in {time.time()-t0:.1f}s")
print(f"shape: {kg.shape}")
print("cols:", list(kg.columns))
print("dtypes:")
print(kg.dtypes.to_string())
print()
print("HEAD:")
print(kg.head(10).to_string())
print()
print("time range (UTC):")
tmin = pd.to_datetime(kg.time_period_start_us.min(), unit="us", utc=True)
tmax = pd.to_datetime(kg.time_period_start_us.max(), unit="us", utc=True)
print(f"  min = {tmin}")
print(f"  max = {tmax}")
print(f"  span = {(kg.time_period_start_us.max() - kg.time_period_start_us.min())/1e6/86400:.2f} days")
print()
print("per-symbol_id row counts:")
print(kg.symbol_id.value_counts().to_string())
print()
print("per-source row counts:")
if "source" in kg.columns:
    print(kg.source.value_counts().to_string())
print()
print("per-asset coverage span (BTC/ETH/SOL):")
for asset in ("BTC", "ETH", "SOL"):
    sym = f"BINANCE_SPOT_{asset}_USDT"
    sub = kg[kg.symbol_id == sym]
    if sub.empty:
        print(f"  {asset:>4}: 0 rows")
        continue
    tmn = pd.to_datetime(sub.time_period_start_us.min(), unit="us", utc=True)
    tmx = pd.to_datetime(sub.time_period_start_us.max(), unit="us", utc=True)
    print(f"  {asset:>4}: n={len(sub):>9,}  {tmn} -> {tmx}")

# 1s gap histogram per asset
print()
print("1s gap histogram per asset (BTC):")
btc = kg[kg.symbol_id == "BINANCE_SPOT_BTC_USDT"].sort_values("time_period_start_us")
btc_diff = btc.time_period_start_us.diff().dropna() // 1_000_000  # seconds
print("  diff_s value_counts (top 10):")
print(btc_diff.value_counts().sort_values(ascending=False).head(10).to_string())
print(f"  n_diffs={len(btc_diff)}, =1s: {(btc_diff==1).sum()} ({(btc_diff==1).mean()*100:.2f}%), >1s: {(btc_diff>1).sum()} ({(btc_diff>1).mean()*100:.2f}%)")
print(f"  max gap (s): {btc_diff.max()}")
print(f"  gaps >5s: {(btc_diff>5).sum()}")
print(f"  gaps >60s: {(btc_diff>60).sum()}")

for asset in ("ETH", "SOL"):
    sym = f"BINANCE_SPOT_{asset}_USDT"
    sub = kg[kg.symbol_id == sym].sort_values("time_period_start_us")
    d = sub.time_period_start_us.diff().dropna() // 1_000_000
    if len(d):
        print(f"  {asset}: 1s_pct={(d==1).mean()*100:.2f}%  max_gap_s={d.max()}  gaps>5s={(d>5).sum()}  gaps>60s={(d>60).sum()}")

# volume column inspection
print()
print("Volume column check:")
sample = kg[kg.symbol_id == "BINANCE_SPOT_BTC_USDT"].head(5)
vol_cols = [c for c in sample.columns if "vol" in c.lower() or "trade" in c.lower()]
print(f"  volume-ish cols: {vol_cols}")
if vol_cols:
    print(sample[["time_period_start_us", "price_open", "price_high", "price_low", "price_close"] + vol_cols].to_string())

# Free memory
del kg, btc, btc_diff
import gc; gc.collect()

# ---------------------------------------------------------------------------
# TASK 4 — slot timing convention (move up before L25 work uses fills)
# ---------------------------------------------------------------------------
hr("TASK 4: slot timing on one example fire")

fills = pd.read_csv(
    "strategy_lab/markov_filter/_results/backtest_prod_strats/fills.csv"
)
print("fills.csv shape:", fills.shape)
print("fills.csv cols:", list(fills.columns))
print("fills.csv dtypes:")
print(fills.dtypes.to_string())
print()
print("HEAD:")
print(fills.head(3).to_string())
print()
# unique strategies/timeframes
for c in ("strategy", "tf", "timeframe", "asset"):
    if c in fills.columns:
        print(f"  {c}.unique(): {sorted(fills[c].unique().tolist())[:10]}")
print()
# find F7-off + 5m
f7off = fills
for col in ("strategy",):
    if col in fills.columns:
        vals = sorted(fills[col].unique().tolist())
        print(f"  strategies in fills: {vals[:30]}")
        break
# pick one row
ex = fills.iloc[0]
print()
print(f"Example fire (row 0):")
print(ex.to_string())

# Slot math
slug = ex.get("slug") if "slug" in ex.index else None
tf = ex.get("timeframe", ex.get("tf", "5m"))
if slug:
    slot_start = int(slug.rsplit("-", 1)[1])
    window_s = {"5m": 300, "15m": 900}[tf]
    ws_s = slot_start - window_s
    slot_end = slot_start + window_s
    fire_us = (ws_s + 120) * 1_000_000  # v1 anchor
    print()
    print(f"  slug         = {slug}")
    print(f"  tf           = {tf}, window_s = {window_s}")
    print(f"  slot_start   = {slot_start} ({pd.Timestamp(slot_start, unit='s', tz='UTC')})")
    print(f"  slot_end     = {slot_end} ({pd.Timestamp(slot_end, unit='s', tz='UTC')})")
    print(f"  ws_s         = {ws_s} ({pd.Timestamp(ws_s, unit='s', tz='UTC')}) [SIGNAL ANCHOR]")
    print(f"  fire_us (v1) = {fire_us} ({pd.Timestamp(fire_us, unit='us', tz='UTC')})")

# ---------------------------------------------------------------------------
# TASK 2 — L25 books
# ---------------------------------------------------------------------------
hr("TASK 2: L25 books on 100 random BTC slugs")

# Filter to BTC 5m fires
btc_mask = (fills["asset"] == "BTC") if "asset" in fills.columns else None
tf_mask = (fills.get("timeframe", fills.get("tf")) == "5m") if ("timeframe" in fills.columns or "tf" in fills.columns) else None
f7_mask = (fills["strategy"] != "F7") if "strategy" in fills.columns else None  # F7-off interpretation

# Build joint mask
m = pd.Series([True] * len(fills))
if btc_mask is not None: m &= btc_mask
if tf_mask is not None: m &= tf_mask
if f7_mask is not None: m &= f7_mask

btc_5m_fires = fills[m]
print(f"BTC 5m non-F7 fires: {len(btc_5m_fires)}")

rng = np.random.default_rng(42)
sample_slugs = btc_5m_fires["slug"].drop_duplicates()
if len(sample_slugs) > 100:
    sample_slugs = sample_slugs.sample(100, random_state=42).tolist()
else:
    sample_slugs = sample_slugs.tolist()
print(f"sampled {len(sample_slugs)} unique BTC slugs")

# Map slug -> (ws_s, slot_end)
slot_bounds = {}
for sl in sample_slugs:
    slot_start = int(sl.rsplit("-", 1)[1])
    ws = slot_start - 300
    slot_bounds[sl] = (ws, slot_start + 300)  # ws to slot_end

# Load L25 only for these slugs
t0 = time.time()
print("loading L25 (subsample_1hz=True) for 100 BTC slugs...")
books = load_orderbook_l25_streaming("BTC", slugs=set(sample_slugs), subsample_1hz=True)
print(f"L25 load took {time.time()-t0:.1f}s; got {len(books)} (slug, outcome) entries")

# Count samples per slug within [ws_s, ws_s + 2*window_s] = [ws_s, slot_end]
sample_counts = []
sample_counts_yes = []
sample_counts_no = []
for sl in sample_slugs:
    ws, slot_end = slot_bounds[sl]
    lo, hi = ws * 1_000_000, slot_end * 1_000_000
    for oc in ("Up", "Down"):
        key = (sl, oc)
        if key in books:
            ts = books[key][0]
            n_in = ((ts >= lo) & (ts <= hi)).sum()
            sample_counts.append(n_in)
            if oc == "Up":
                sample_counts_yes.append(n_in)
            else:
                sample_counts_no.append(n_in)
        else:
            sample_counts.append(0)

sample_counts = np.array(sample_counts)
print(f"  samples-per-(slug,outcome) within [ws_s, slot_end] (span={2*300}s):")
print(f"    mean   = {sample_counts.mean():.1f}")
print(f"    median = {np.median(sample_counts):.1f}")
print(f"    p10/p25/p50/p75/p90 = "
      f"{np.percentile(sample_counts,10):.0f}/"
      f"{np.percentile(sample_counts,25):.0f}/"
      f"{np.percentile(sample_counts,50):.0f}/"
      f"{np.percentile(sample_counts,75):.0f}/"
      f"{np.percentile(sample_counts,90):.0f}")
print(f"    min/max = {sample_counts.min()}/{sample_counts.max()}")
print(f"    n_zero = {(sample_counts==0).sum()} of {len(sample_counts)} entries")

# Free
del books
gc.collect()

# ---------------------------------------------------------------------------
# TASK 3 — cross-coverage
# ---------------------------------------------------------------------------
hr("TASK 3: cross-coverage of 1s klines + L25 + polymarket trades on F7-off 5m fires")

# Reload 1s klines just BTC to keep RAM small for the coverage check (we'll do per-asset)
all_assets = ("BTC", "ETH", "SOL")

# Compute kline coverage per asset
print("(a) 1s binance kline coverage [fire_us-300s, fire_us+300s]")
print("(b) L25 book coverage [fire_us, slot_end]")
print("(c) polymarket trade coverage for slug")
print()

results_per_asset = {}
for asset in all_assets:
    sub_fires = btc_5m_fires if asset == "BTC" else fills[(fills.get("asset") == asset) & (fills.get("timeframe", fills.get("tf")) == "5m") & (fills["strategy"] != "F7")]
    n_fires = len(sub_fires)
    if n_fires == 0:
        print(f"  {asset}: 0 F7-off 5m fires; skip")
        continue
    print(f"  {asset}: {n_fires} F7-off 5m fires")

    # Subsample to keep checks fast
    if n_fires > 1500:
        sub_fires = sub_fires.sample(1500, random_state=42)
    n_check = len(sub_fires)

    # (a) kline coverage
    klines = load_klines_1s(asset)
    ts_k = klines.time_period_start_us.values.astype("int64")
    fire_us_arr = []
    slot_end_us_arr = []
    for _, r in sub_fires.iterrows():
        sl = r["slug"]
        slot_start = int(sl.rsplit("-", 1)[1])
        ws = slot_start - 300
        fire_us_arr.append((ws + 120) * 1_000_000)
        slot_end_us_arr.append((slot_start + 300) * 1_000_000)
    fire_us_arr = np.array(fire_us_arr, dtype="int64")
    slot_end_us_arr = np.array(slot_end_us_arr, dtype="int64")

    # Check coverage: at least 1 kline in [fire_us-300s, fire_us+300s]
    win_lo = fire_us_arr - 300_000_000
    win_hi = fire_us_arr + 300_000_000
    # Use searchsorted for vectorized check
    lo_idx = np.searchsorted(ts_k, win_lo, side="left")
    hi_idx = np.searchsorted(ts_k, win_hi, side="right")
    kline_count = hi_idx - lo_idx
    a_cov_pct = (kline_count >= 1).mean() * 100
    a_dense_pct = (kline_count >= 100).mean() * 100  # at least 100 of 600 expected
    print(f"    (a) kline-1s any in window: {a_cov_pct:.1f}% (>=100 samples: {a_dense_pct:.1f}%)")
    print(f"        kline_count median={np.median(kline_count):.0f}, mean={kline_count.mean():.0f} (full=600)")

    del klines, ts_k; gc.collect()

    # (b) L25 book coverage
    # Sample at most 300 slugs to bound memory for L25 load
    unique_sl = sub_fires["slug"].drop_duplicates()
    if len(unique_sl) > 300:
        unique_sl = unique_sl.sample(300, random_state=42).tolist()
    else:
        unique_sl = unique_sl.tolist()
    print(f"        L25 check on {len(unique_sl)} unique slugs (subset)...")
    t0 = time.time()
    books = load_orderbook_l25_streaming(asset, slugs=set(unique_sl), subsample_1hz=True)
    print(f"        L25 load took {time.time()-t0:.1f}s")
    have_book = 0
    for sl in unique_sl:
        slot_start = int(sl.rsplit("-", 1)[1])
        ws = slot_start - 300
        fire_us_local = (ws + 120) * 1_000_000
        slot_end_us_local = (slot_start + 300) * 1_000_000
        any_sample = False
        for oc in ("Up", "Down"):
            if (sl, oc) in books:
                ts = books[(sl, oc)][0]
                if ((ts >= fire_us_local) & (ts <= slot_end_us_local)).any():
                    any_sample = True
                    break
        if any_sample:
            have_book += 1
    b_cov_pct = have_book / len(unique_sl) * 100
    print(f"    (b) L25 any-sample in [fire_us, slot_end]: {b_cov_pct:.1f}% (of {len(unique_sl)} slug sample)")
    del books; gc.collect()

    # (c) polymarket trade coverage
    try:
        trades = load_trades(asset)
        # check if slug column exists
        if "slug" in trades.columns:
            slugs_with_trades = set(trades["slug"].unique().tolist())
            covered = sum(1 for sl in unique_sl if sl in slugs_with_trades)
            c_cov_pct = covered / len(unique_sl) * 100
        else:
            print(f"    trades cols: {list(trades.columns)[:15]}")
            c_cov_pct = float("nan")
        print(f"    (c) polymarket trades for slug: {c_cov_pct:.1f}% (of {len(unique_sl)} slug sample)")
        # joint coverage on the sampled slugs
        joint = 0
        for sl in unique_sl:
            slot_start = int(sl.rsplit("-", 1)[1])
            ws = slot_start - 300
            fire_us_local = (ws + 120) * 1_000_000
            slot_end_us_local = (slot_start + 300) * 1_000_000
            win_lo_local = fire_us_local - 300_000_000
            win_hi_local = fire_us_local + 300_000_000
            has_k = (((ts_k_cache := None) is None))  # placeholder
            # don't recompute kline; this is sampled differently
            joint += int(sl in slugs_with_trades)
        results_per_asset[asset] = {
            "kline_cov_pct": float(a_cov_pct),
            "l25_cov_pct": float(b_cov_pct),
            "trade_cov_pct": float(c_cov_pct),
            "fires_checked": int(n_check),
            "slugs_checked": int(len(unique_sl)),
        }
        del trades; gc.collect()
    except FileNotFoundError as e:
        print(f"    (c) trades unavailable: {e}")
        results_per_asset[asset] = {"kline_cov_pct": float(a_cov_pct), "l25_cov_pct": float(b_cov_pct), "trade_cov_pct": None, "fires_checked": int(n_check), "slugs_checked": int(len(unique_sl))}

hr("RESULTS SUMMARY")
print(results_per_asset)
print()
print("DONE")
