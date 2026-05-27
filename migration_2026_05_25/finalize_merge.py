"""
Continuation of merge_to_canonical.py after the canonical/orderbook_l25/ write
crashed (that path is not used by load.py — L25 is loaded directly from
refresh_*/cache/ via load_orderbook_l25_streaming, so we skip the canonical write).

This script:
  - Rebuilds resolutions_from_rtds.parquet against the refreshed RTDS + resolutions.
  - Prints the final verification summary (max timestamps per source).
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
CANON = ROOT / "data" / "v4" / "canonical"

def log(msg): print(f"[finalize] {msg}", flush=True)

# --- Rebuild resolutions_from_rtds.parquet ---
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
log("\n=== FINAL CANONICAL STATE ===")
res_rtds = pd.read_parquet(CANON / "resolutions_from_rtds.parquet")
log(f"  resolutions_from_rtds: {len(res_rtds):,}")
log(f"    window: {pd.to_datetime(res_rtds.slot_start_us.min(), unit='us', utc=True)} -> "
    f"{pd.to_datetime(res_rtds.slot_start_us.max(), unit='us', utc=True)}")
log(f"    by asset x tf:")
print(res_rtds.groupby(['ticker','timeframe']).size().unstack(fill_value=0).to_string())

km = pd.read_parquet(CANON / "klines_1m.parquet")
log(f"  klines_1m max ts: {pd.to_datetime(km.time_period_start_us.max(), unit='us', utc=True)}")

ks = pd.read_parquet(CANON / "klines_1s.parquet")
log(f"  klines_1s max ts: {pd.to_datetime(ks.time_period_start_us.max(), unit='us', utc=True)}")

cl = pd.read_parquet(CANON / "chainlink_rtds.parquet")
log(f"  chainlink_rtds max ts: {pd.to_datetime(cl.timestamp_us.max(), unit='us', utc=True)}")

for asset in ["btc","eth","sol"]:
    p = CANON / "trades_polymarket" / f"{asset}.parquet"
    if p.exists():
        df = pd.read_parquet(p, columns=["timestamp_us"])
        log(f"  trades_polymarket/{asset} max ts: {pd.to_datetime(df.timestamp_us.max(), unit='us', utc=True)}  ({len(df):,} rows)")

# L25 source list verification (loaded from refresh_* dirs via load_orderbook_l25_streaming)
log("  L25 source dirs (load.py reads these directly — no canonical merge needed):")
for asset in ["btc","eth","sol"]:
    p = ROOT / "data" / "v4" / "refresh_2026_05_25" / "cache" / f"{asset}_orderbook_L25_delta.parquet"
    if p.exists():
        df = pd.read_parquet(p, columns=["timestamp_us"])
        log(f"    refresh_2026_05_25/{asset}: max ts {pd.to_datetime(df.timestamp_us.max(), unit='us', utc=True)}  ({len(df):,} rows)")
