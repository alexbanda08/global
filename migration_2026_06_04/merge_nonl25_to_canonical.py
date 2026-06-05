"""
Merge non-L25 deltas from refresh_2026_06_04/cache/ into canonical/.
Rebuilds resolutions_from_rtds at the end. (L25 + futures merged separately.)
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
TAG = "2026_06_04"
CACHE = ROOT / "data" / "v4" / f"refresh_{TAG}" / "cache"
CANON = ROOT / "data" / "v4" / "canonical"

def log(msg): print(f"[merge] {msg}", flush=True)

# 1. klines_1m
log("Merging 1MIN klines...")
old = pd.read_parquet(CANON / "klines_1m.parquet")
new = pd.read_parquet(CACHE / "binance_klines_1min_delta.parquet")
log(f"  old: {len(old):,}  new: {len(new):,}")
c = pd.concat([old, new], ignore_index=True)
c = c.drop_duplicates(["symbol_id","period_id","source","time_period_start_us"], keep="last")
c = c.sort_values(["symbol_id","period_id","source","time_period_start_us"]).reset_index(drop=True)
log(f"  merged: {len(c):,}  max ts: {pd.to_datetime(c.time_period_start_us.max(), unit='us', utc=True)}")
c.to_parquet(CANON / "klines_1m.parquet", index=False)

# 2. klines_1s
log("Merging 1SEC klines...")
old = pd.read_parquet(CANON / "klines_1s.parquet")
new = pd.read_parquet(CACHE / "binance_klines_1sec_delta.parquet")
log(f"  old: {len(old):,}  new: {len(new):,}")
c = pd.concat([old, new], ignore_index=True)
c = c.drop_duplicates(["symbol_id","source","time_period_start_us"], keep="last")
c = c.sort_values(["symbol_id","time_period_start_us"]).reset_index(drop=True)
log(f"  merged: {len(c):,}  max ts: {pd.to_datetime(c.time_period_start_us.max(), unit='us', utc=True)}")
c.to_parquet(CANON / "klines_1s.parquet", index=False)

# 3. chainlink_rtds
log("Merging chainlink RTDS...")
old = pd.read_parquet(CANON / "chainlink_rtds.parquet")
new = pd.read_parquet(CACHE / "oracle_prices_delta.parquet")
log(f"  old: {len(old):,}  new: {len(new):,}")
if 'source' in new.columns:
    new = new[new.source.str.contains('chainlink', case=False, na=False)]
    log(f"  new (chainlink-filtered): {len(new):,}")
c = pd.concat([old, new], ignore_index=True)
c = c.drop_duplicates(["symbol_id","timestamp_us"], keep="last")
c = c.sort_values(["symbol_id","timestamp_us"]).reset_index(drop=True)
log(f"  merged: {len(c):,}  max ts: {pd.to_datetime(c.timestamp_us.max(), unit='us', utc=True)}")
c.to_parquet(CANON / "chainlink_rtds.parquet", index=False)

# 4. resolutions (full pull, replace)
log("Replacing market_resolutions...")
new = pd.read_parquet(CACHE / "market_resolutions_full.parquet").sort_values("slot_start_us").reset_index(drop=True)
log(f"  rows: {len(new):,}  max slot_start: {pd.to_datetime(new.slot_start_us.max(), unit='us', utc=True)}")
new.to_parquet(CANON / "resolutions.parquet", index=False)

# 5. trades_polymarket
log("Merging polymarket trades...")
for asset in ["btc","eth","sol"]:
    op = CANON / "trades_polymarket" / f"{asset}.parquet"
    old = pd.read_parquet(op) if op.exists() else pd.DataFrame()
    new = pd.read_parquet(CACHE / f"{asset}_trades_delta.parquet")
    log(f"  {asset}: old={len(old):,}  new={len(new):,}")
    if len(old):
        for col in [c for c in old.columns if old[c].dtype == 'object']:
            old[col] = old[col].astype(str)
            if col in new.columns:
                new[col] = new[col].astype(str)
        c = pd.concat([old, new], ignore_index=True)
        if "trade_id" in c.columns:
            c = c.drop_duplicates("trade_id", keep="last")
        else:
            c = c.drop_duplicates(["slug","timestamp_us","outcome","price","size"], keep="last")
    else:
        c = new
    c = c.sort_values(["slug","timestamp_us"]).reset_index(drop=True)
    c.to_parquet(op, index=False)
    log(f"    merged {asset}: {len(c):,}  max ts: {pd.to_datetime(c.timestamp_us.max(), unit='us', utc=True)}")

# 6. trading_events_30d (full rolling replace)
log("Replacing trading_events_30d...")
new = pd.read_parquet(CACHE / "trading_events_30d.parquet")
log(f"  rows: {len(new):,}")
new.to_parquet(CANON / "trading_events_30d.parquet", index=False)

# 7. Rebuild resolutions_from_rtds
log("Rebuilding resolutions_from_rtds...")
res = pd.read_parquet(CANON / "resolutions.parquet")
res = res[res.slug.str.match(r"^(btc|eth|sol)-updown-")].copy()
cl = pd.read_parquet(CANON / "chainlink_rtds.parquet")
asof_arrays = {}
for asset in ["BTC","ETH","SOL"]:
    sub = cl[cl.symbol_id == f"CHAINLINK_{asset}_USD"].sort_values("timestamp_us")
    if len(sub) == 0:
        log(f"  WARN: no chainlink for {asset}"); continue
    asof_arrays[asset] = (sub.timestamp_us.values.astype("int64"), sub.price_value.values.astype("float64"))

def asof_chainlink(asset_u, target_us, max_lag_s=60):
    if asset_u not in asof_arrays:
        return np.nan
    ts, p = asof_arrays[asset_u]
    i = int(np.searchsorted(ts, target_us, side="right") - 1)
    if i < 0 or (target_us - ts[i]) > max_lag_s * 1_000_000:
        return np.nan
    return float(p[i])

out_rows = []; skip = 0
for _, r in res.iterrows():
    asset_u = r["ticker"].upper()
    strike = asof_chainlink(asset_u, r["slot_start_us"])
    settle = asof_chainlink(asset_u, r["slot_end_us"])
    if not (np.isfinite(strike) and np.isfinite(settle)):
        skip += 1; continue
    d = settle - strike
    if abs(d) < 1e-9: continue
    out_rows.append(dict(market_id=r["market_id"], slug=r["slug"], ticker=r["ticker"],
        timeframe=r["timeframe"], slot_start_us=r["slot_start_us"], slot_end_us=r["slot_end_us"],
        outcome="Up" if d > 0 else "Down", strike_price=float(strike), strike_ts_us=r["slot_start_us"],
        settlement_price=float(settle), settle_ts_us=r["slot_end_us"], delta_price=float(d),
        price_source="chainlink-rtds-local"))
log(f"  rebuilt: {len(out_rows):,}  skipped: {skip}")
pd.DataFrame(out_rows).sort_values("slot_start_us").reset_index(drop=True).to_parquet(
    CANON / "resolutions_from_rtds.parquet", index=False)

log("\n=== FINAL CANONICAL STATE (non-L25) ===")
for name, p, ts_col in [
    ("klines_1m", CANON/"klines_1m.parquet", "time_period_start_us"),
    ("klines_1s", CANON/"klines_1s.parquet", "time_period_start_us"),
    ("chainlink_rtds", CANON/"chainlink_rtds.parquet", "timestamp_us"),
    ("resolutions", CANON/"resolutions.parquet", "slot_start_us"),
    ("resolutions_from_rtds", CANON/"resolutions_from_rtds.parquet", "slot_start_us"),
]:
    df = pd.read_parquet(p, columns=[ts_col])
    log(f"  {name:<28s} {len(df):>10,} rows  max={pd.to_datetime(df[ts_col].max(), unit='us', utc=True)}")
for asset in ["btc","eth","sol"]:
    df = pd.read_parquet(CANON / "trades_polymarket" / f"{asset}.parquet", columns=["timestamp_us"])
    log(f"  trades_polymarket/{asset:<5s}  {len(df):>10,} rows  max={pd.to_datetime(df.timestamp_us.max(), unit='us', utc=True)}")
