"""
Merge 2026-05-20 -> 2026-05-25 delta parquets into canonical/ layer.

Strategy: deduplicate by composite key and re-sort. Preserve existing data;
replace only where deltas overlap.
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
TAG = "2026_05_25"
CACHE = ROOT / "data" / "v4" / f"refresh_{TAG}" / "cache"
CANON = ROOT / "data" / "v4" / "canonical"
sys.path.insert(0, str(CANON))

def log(msg): print(f"[merge] {msg}", flush=True)

# --- 1. klines_1m.parquet ---
log("Merging 1MIN klines...")
old = pd.read_parquet(CANON / "klines_1m.parquet")
new = pd.read_parquet(CACHE / "binance_klines_1min_delta.parquet")
log(f"  old: {len(old):,}  new delta: {len(new):,}")
combined = pd.concat([old, new], ignore_index=True)
combined = combined.drop_duplicates(["symbol_id","period_id","source","time_period_start_us"], keep="last")
combined = combined.sort_values(["symbol_id","period_id","source","time_period_start_us"]).reset_index(drop=True)
log(f"  merged: {len(combined):,}")
combined.to_parquet(CANON / "klines_1m.parquet", index=False)
log(f"  max ts: {pd.to_datetime(combined.time_period_start_us.max(), unit='us', utc=True)}")

# --- 2. klines_1s.parquet ---
log("Merging 1SEC klines...")
old_path = CANON / "klines_1s.parquet"
if old_path.exists():
    old = pd.read_parquet(old_path)
else:
    old = pd.DataFrame()
new = pd.read_parquet(CACHE / "binance_klines_1sec_delta.parquet")
log(f"  old: {len(old):,}  new: {len(new):,}")
if len(old):
    combined = pd.concat([old, new], ignore_index=True)
    combined = combined.drop_duplicates(["symbol_id","source","time_period_start_us"], keep="last")
else:
    combined = new
combined = combined.sort_values(["symbol_id","time_period_start_us"]).reset_index(drop=True)
combined.to_parquet(old_path, index=False)
log(f"  merged: {len(combined):,}  max ts: {pd.to_datetime(combined.time_period_start_us.max(), unit='us', utc=True)}")

# --- 3. chainlink_rtds.parquet ---
log("Merging chainlink RTDS...")
old = pd.read_parquet(CANON / "chainlink_rtds.parquet")
new = pd.read_parquet(CACHE / "oracle_prices_delta.parquet")
log(f"  old: {len(old):,}  new: {len(new):,}")
if 'source' in new.columns:
    new = new[new.source.str.contains('chainlink', case=False, na=False)]
    log(f"  new (chainlink-filtered): {len(new):,}")
combined = pd.concat([old, new], ignore_index=True)
combined = combined.drop_duplicates(["symbol_id","timestamp_us"], keep="last")
combined = combined.sort_values(["symbol_id","timestamp_us"]).reset_index(drop=True)
combined.to_parquet(CANON / "chainlink_rtds.parquet", index=False)
log(f"  merged: {len(combined):,}  max ts: {pd.to_datetime(combined.timestamp_us.max(), unit='us', utc=True)}")

# --- 4. resolutions.parquet (full replace, table is small) ---
log("Replacing market_resolutions (full pull)...")
new = pd.read_parquet(CACHE / "market_resolutions_full.parquet")
log(f"  full pull: {len(new):,}")
new = new.sort_values("slot_start_us").reset_index(drop=True)
new.to_parquet(CANON / "resolutions.parquet", index=False)
log(f"  max slot_start_us: {pd.to_datetime(new.slot_start_us.max(), unit='us', utc=True)}")

# --- 5. trades_polymarket/{asset}.parquet ---
log("Merging polymarket trades...")
for asset in ["btc","eth","sol"]:
    old_path = CANON / "trades_polymarket" / f"{asset}.parquet"
    old = pd.read_parquet(old_path) if old_path.exists() else pd.DataFrame()
    new = pd.read_parquet(CACHE / f"{asset}_trades_delta.parquet")
    log(f"  {asset}: old={len(old):,}  new={len(new):,}")
    if len(old):
        obj_cols = [c for c in old.columns if old[c].dtype == "object"]
        for col in obj_cols:
            old[col] = old[col].astype(str)
            if col in new.columns:
                new[col] = new[col].astype(str)
        combined = pd.concat([old, new], ignore_index=True)
        if "trade_id" in combined.columns:
            combined = combined.drop_duplicates("trade_id", keep="last")
        else:
            combined = combined.drop_duplicates(["slug","timestamp_us","outcome","price","size"], keep="last")
    else:
        combined = new
    combined = combined.sort_values(["slug","timestamp_us"]).reset_index(drop=True)
    combined.to_parquet(old_path, index=False)
    log(f"    merged {asset}: {len(combined):,}  max ts: {pd.to_datetime(combined.timestamp_us.max(), unit='us', utc=True)}")

# --- 6. trading_events_30d.parquet (FULL replace, rolling window) ---
log("Replacing trading_events_30d (rolling)...")
new = pd.read_parquet(CACHE / "trading_events_30d.parquet")
log(f"  new full: {len(new):,}")
new.to_parquet(CANON / "trading_events_30d.parquet", index=False)
if 'at' in new.columns:
    at_ts = pd.to_datetime(new['at'], utc=True, format='mixed', errors='coerce')
    log(f"  events span: {at_ts.min()} -> {at_ts.max()}")

# --- 7. L25 orderbook — NO canonical write ---
# `canonical/orderbook_l25/` is NOT used. `load_orderbook_l25_streaming` in
# load.py reads `refresh_*/cache/{asset}_orderbook_L25_delta.parquet` directly,
# because the legacy pyarrow concat-write was unreliable for the 2.7-3GB BTC
# file (silent row-group truncation). The L25 delta parquets in
# refresh_2026_05_25/cache/ are sufficient — just verify load.py has the new
# refresh_2026_05_25 path appended in its sources list.
log("L25 orderbook: skipping canonical write (read path is refresh_*/cache/ via load.py)")
for asset in ["btc", "eth", "sol"]:
    src = CACHE / f"{asset}_orderbook_L25_delta.parquet"
    if src.exists():
        df = pd.read_parquet(src, columns=["timestamp_us"])
        log(f"  refresh_{TAG}/{asset}: {len(df):,} rows, max ts {pd.to_datetime(df.timestamp_us.max(), unit='us', utc=True)}")

# --- 8. Rebuild resolutions_from_rtds.parquet ---
log("Rebuilding resolutions_from_rtds (chainlink-derived outcomes)...")
res = pd.read_parquet(CANON / "resolutions.parquet")
res = res[res.slug.str.match(r"^(btc|eth|sol)-updown-")].copy()

cl = pd.read_parquet(CANON / "chainlink_rtds.parquet")
asof_arrays = {}
for asset in ["BTC","ETH","SOL"]:
    sym = f"CHAINLINK_{asset}_USD"
    sub = cl[cl.symbol_id == sym].sort_values("timestamp_us")
    if len(sub) == 0:
        log(f"  WARN: no chainlink data for {asset}")
        continue
    asof_arrays[asset] = (sub.timestamp_us.values.astype("int64"),
                          sub.price_value.values.astype("float64"))

def asof_chainlink(asset_upper, target_us, max_lag_s=60):
    if asset_upper not in asof_arrays:
        return np.nan
    ts, prices = asof_arrays[asset_upper]
    i = int(np.searchsorted(ts, target_us, side="right") - 1)
    if i < 0:
        return np.nan
    if (target_us - ts[i]) > max_lag_s * 1_000_000:
        return np.nan
    return float(prices[i])

out_rows = []
skip_count = 0
for _, r in res.iterrows():
    asset_u = r["ticker"].upper()
    strike = asof_chainlink(asset_u, r["slot_start_us"])
    settle = asof_chainlink(asset_u, r["slot_end_us"])
    if not (np.isfinite(strike) and np.isfinite(settle)):
        skip_count += 1
        continue
    delta = settle - strike
    if abs(delta) < 1e-9:
        continue
    outcome_chain = "Up" if delta > 0 else "Down"
    out_rows.append(dict(
        market_id=r["market_id"], slug=r["slug"], ticker=r["ticker"],
        timeframe=r["timeframe"], slot_start_us=r["slot_start_us"],
        slot_end_us=r["slot_end_us"], outcome=outcome_chain,
        strike_price=float(strike), strike_ts_us=r["slot_start_us"],
        settlement_price=float(settle), settle_ts_us=r["slot_end_us"],
        delta_price=float(delta), price_source="chainlink-rtds-local",
    ))
log(f"  rebuilt: {len(out_rows):,} (skipped {skip_count} for missing oracle data)")
rtds = pd.DataFrame(out_rows).sort_values("slot_start_us").reset_index(drop=True)
rtds.to_parquet(CANON / "resolutions_from_rtds.parquet", index=False)

# --- Summary ---
log("\n=== MERGE SUMMARY ===")
res_rtds = pd.read_parquet(CANON / "resolutions_from_rtds.parquet")
log(f"  resolutions_from_rtds: {len(res_rtds):,}")
log(f"    window: {pd.to_datetime(res_rtds.slot_start_us.min(), unit='us', utc=True)} -> "
    f"{pd.to_datetime(res_rtds.slot_start_us.max(), unit='us', utc=True)}")
log(f"    by asset x tf:")
print(res_rtds.groupby(['ticker','timeframe']).size().unstack(fill_value=0).to_string())

km = pd.read_parquet(CANON / "klines_1m.parquet")
log(f"  klines_1m max ts: {pd.to_datetime(km.time_period_start_us.max(), unit='us', utc=True)}")
