"""
Full inventory of canonical dataset + refresh_*/cache/ L25 sources.
Reports rows, time range, and key dimensions per source.
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
CANON = ROOT / "data" / "v4" / "canonical"
DATA = ROOT / "data" / "v4"

def fmt_ts(ts_us):
    return pd.to_datetime(int(ts_us), unit="us", utc=True).strftime("%Y-%m-%d %H:%M:%S")

def fmt_size(p):
    return f"{p.stat().st_size / 1024 / 1024:.1f} MB"

def section(name):
    print(f"\n{'='*70}\n{name}\n{'='*70}")

# === resolutions.parquet ===
section("resolutions.parquet  (chainlink-filtered Up/Down outcomes, full pull)")
df = pd.read_parquet(CANON / "resolutions.parquet")
print(f"  rows: {len(df):,}  size: {fmt_size(CANON / 'resolutions.parquet')}")
print(f"  slot_start_us window: {fmt_ts(df.slot_start_us.min())}  ->  {fmt_ts(df.slot_start_us.max())}")
print(f"  tickers: {sorted(df.ticker.dropna().unique().tolist())}")
print(f"  timeframes: {sorted(df.timeframe.dropna().unique().tolist())}")
print(f"  by ticker x timeframe:")
print(df.groupby(['ticker','timeframe']).size().unstack(fill_value=0).to_string().replace('\n', '\n    '))

# === resolutions_from_rtds.parquet ===
section("resolutions_from_rtds.parquet  (chainlink-derived outcomes — primary source for backtests)")
df = pd.read_parquet(CANON / "resolutions_from_rtds.parquet")
print(f"  rows: {len(df):,}  size: {fmt_size(CANON / 'resolutions_from_rtds.parquet')}")
print(f"  slot_start_us window: {fmt_ts(df.slot_start_us.min())}  ->  {fmt_ts(df.slot_start_us.max())}")
print(f"  by ticker x timeframe:")
print(df.groupby(['ticker','timeframe']).size().unstack(fill_value=0).to_string().replace('\n', '\n    '))

# === klines_1m.parquet ===
section("klines_1m.parquet  (binance-spot-ws + cex venues, 1m/5m/15m bars)")
df = pd.read_parquet(CANON / "klines_1m.parquet")
print(f"  rows: {len(df):,}  size: {fmt_size(CANON / 'klines_1m.parquet')}")
print(f"  time_period_start_us window: {fmt_ts(df.time_period_start_us.min())}  ->  {fmt_ts(df.time_period_start_us.max())}")
print(f"  source x period_id:")
g = df.groupby(['source','period_id']).size().unstack(fill_value=0)
print(g.to_string().replace('\n', '\n    '))
print(f"  symbols: {sorted(df.symbol_id.unique().tolist())}")

# === klines_1s.parquet ===
section("klines_1s.parquet  (binance-spot-ws 1-second bars, ultra-fine momentum)")
df = pd.read_parquet(CANON / "klines_1s.parquet")
print(f"  rows: {len(df):,}  size: {fmt_size(CANON / 'klines_1s.parquet')}")
print(f"  time_period_start_us window: {fmt_ts(df.time_period_start_us.min())}  ->  {fmt_ts(df.time_period_start_us.max())}")
print(f"  symbols: {sorted(df.symbol_id.unique().tolist())}")

# === chainlink_rtds.parquet ===
section("chainlink_rtds.parquet  (oracle feed, ~1Hz strike/settlement source)")
df = pd.read_parquet(CANON / "chainlink_rtds.parquet")
print(f"  rows: {len(df):,}  size: {fmt_size(CANON / 'chainlink_rtds.parquet')}")
print(f"  timestamp_us window: {fmt_ts(df.timestamp_us.min())}  ->  {fmt_ts(df.timestamp_us.max())}")
print(f"  symbols: {sorted(df.symbol_id.unique().tolist())}")
print(f"  rows per symbol:")
for sym, n in df.groupby('symbol_id').size().items():
    print(f"    {sym}: {n:,}")

# === trades_polymarket/{asset}.parquet ===
section("trades_polymarket/{btc,eth,sol}.parquet  (Polymarket CLOB taker trades)")
for asset in ["btc","eth","sol"]:
    p = CANON / "trades_polymarket" / f"{asset}.parquet"
    if not p.exists():
        print(f"  {asset}: MISSING")
        continue
    df = pd.read_parquet(p, columns=["timestamp_us","slug","side","price","size"])
    print(f"  {asset}: {len(df):,} rows  size: {fmt_size(p)}")
    print(f"       window: {fmt_ts(df.timestamp_us.min())}  ->  {fmt_ts(df.timestamp_us.max())}")
    print(f"       unique slugs: {df.slug.nunique():,}")

# === trading_events_30d.parquet ===
section("trading_events_30d.parquet  (production audit log, rolling 30d)")
df = pd.read_parquet(CANON / "trading_events_30d.parquet")
print(f"  rows: {len(df):,}  size: {fmt_size(CANON / 'trading_events_30d.parquet')}")
at = pd.to_datetime(df['at'], utc=True, format='mixed', errors='coerce')
print(f"  at window: {at.min()}  ->  {at.max()}")
print(f"  kinds: {sorted(df.kind.dropna().unique().tolist())[:15]}...")
sleeves = df.sleeve_id.dropna().unique()
print(f"  unique sleeves: {len(sleeves)}")

# === L25 (lives in refresh_*/cache/, read via load_orderbook_l25_streaming) ===
section("L25 orderbook  (per refresh dir — load_orderbook_l25_streaming aggregates these)")
sources = [
    ("refresh_2026_05_16/cache_pre", "_orderbook_L25_pre_apr22.parquet"),
    ("refresh_2026_05_06/cache",     "_orderbook_L25.parquet"),
    ("refresh_2026_05_16/cache",     "_orderbook_L25_delta.parquet"),
    ("refresh_2026_05_19/cache",     "_orderbook_L25_delta.parquet"),
    ("refresh_2026_05_21/cache",     "_orderbook_L25_delta.parquet"),
    ("refresh_2026_05_25/cache",     "_orderbook_L25_delta.parquet"),
]
totals = {a: {"rows": 0, "size": 0, "min": None, "max": None} for a in ["btc","eth","sol"]}
for subdir, suffix in sources:
    print(f"\n  {subdir}/")
    for asset in ["btc","eth","sol"]:
        p = DATA / subdir.split("/")[0] / subdir.split("/")[1] / f"{asset}{suffix}"
        if not p.exists():
            print(f"    {asset}: MISSING ({p.name})")
            continue
        df = pd.read_parquet(p, columns=["timestamp_us"])
        sz = p.stat().st_size / 1024 / 1024
        mn = int(df.timestamp_us.min())
        mx = int(df.timestamp_us.max())
        print(f"    {asset}: {len(df):>10,} rows  {sz:>6.0f} MB  [{fmt_ts(mn)} -> {fmt_ts(mx)}]")
        totals[asset]["rows"] += len(df)
        totals[asset]["size"] += sz
        if totals[asset]["min"] is None or mn < totals[asset]["min"]:
            totals[asset]["min"] = mn
        if totals[asset]["max"] is None or mx > totals[asset]["max"]:
            totals[asset]["max"] = mx

print("\n  --- L25 aggregate (across all refresh dirs) ---")
for asset, t in totals.items():
    if t["min"] is not None:
        print(f"  {asset}: {t['rows']:>11,} rows  {t['size']:>6.0f} MB  [{fmt_ts(t['min'])} -> {fmt_ts(t['max'])}]")

# === tier1_entries_at_t120/{asset}.parquet ===
section("tier1_entries_at_t120/{btc,eth,sol}.parquet  (pre-joined L25 snapshot at fire_us)")
for asset in ["btc","eth","sol"]:
    p = CANON / "tier1_entries_at_t120" / f"{asset}.parquet"
    if not p.exists():
        print(f"  {asset}: MISSING")
        continue
    df = pd.read_parquet(p, columns=["target_ts_us","slug","timestamp_us"])
    print(f"  {asset}: {len(df):,} rows  size: {fmt_size(p)}")
    print(f"       target_ts_us window: {fmt_ts(df.target_ts_us.min())}  ->  {fmt_ts(df.target_ts_us.max())}")

# === HL data (in refresh_*/cache/, not yet in canonical) ===
section("Hyperliquid  (in refresh_*/cache/, no canonical merge yet)")
for label, name in [("klines","hyperliquid_klines_delta.parquet"),
                    ("trades","hyperliquid_trades_delta.parquet"),
                    ("liqs","hyperliquid_liquidations_delta.parquet")]:
    found_any = False
    for subdir in ["refresh_2026_05_21/cache", "refresh_2026_05_25/cache"]:
        p = DATA / subdir.split("/")[0] / subdir.split("/")[1] / name
        if p.exists():
            df = pd.read_parquet(p)
            ts_col = "time_exchange_us" if "trades" in name or "liq" in name else "time_period_start_us"
            if ts_col in df.columns:
                print(f"  {subdir}/{name}: {len(df):,} rows  [{fmt_ts(df[ts_col].min())} -> {fmt_ts(df[ts_col].max())}]")
            else:
                print(f"  {subdir}/{name}: {len(df):,} rows  cols: {list(df.columns)[:6]}")
            found_any = True
    if not found_any:
        print(f"  {label}: no parquets found")

print("\n" + "="*70)
print("DONE.")
