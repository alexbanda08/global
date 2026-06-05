"""
Verify canonical tables advanced past ~Jun 1 09:00 UTC after 2026_06_03 refresh.
Checks: max-ts > 2026-06-02, row count > 0, L25 writer-kept == metadata.num_rows.
STOP and print FAIL before any delete step.
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
CANON = ROOT / "data" / "v4" / "canonical"

MIN_TS = datetime(2026, 6, 2, 0, 0, 0, tzinfo=timezone.utc)  # must be > this
FAIL = []

def check(name, path, ts_col, min_ts=MIN_TS):
    if not path.exists():
        print(f"  MISSING  {name}")
        FAIL.append(f"MISSING: {name}")
        return
    df = pd.read_parquet(path, columns=[ts_col])
    n = len(df)
    max_ts = pd.to_datetime(df[ts_col].max(), unit='us', utc=True)
    ok = "OK  " if max_ts > pd.Timestamp(min_ts) and n > 0 else "FAIL"
    if ok == "FAIL":
        FAIL.append(f"{name}: max={max_ts} n={n}")
    print(f"  {ok}  {name:<35s} {n:>12,} rows  max={max_ts}")

print("=== CANONICAL VERIFY (2026-06-03 refresh) ===\n")

# Non-L25
check("klines_1m",           CANON/"klines_1m.parquet",           "time_period_start_us")
check("klines_1s",           CANON/"klines_1s.parquet",           "time_period_start_us")
check("chainlink_rtds",      CANON/"chainlink_rtds.parquet",      "timestamp_us")
check("resolutions",         CANON/"resolutions.parquet",         "slot_start_us")
check("resolutions_from_rtds", CANON/"resolutions_from_rtds.parquet", "slot_start_us")
for asset in ["btc","eth","sol"]:
    check(f"trades_polymarket/{asset}", CANON/"trades_polymarket"/f"{asset}.parquet", "timestamp_us")
check("trading_events_30d",  CANON/"trading_events_30d.parquet",  "at",
      min_ts=datetime(2026, 5, 1, tzinfo=timezone.utc))  # rolling 30d — just check has rows

# Futures
check("cex_futures_klines",       CANON/"cex_futures_klines.parquet",       "time_period_start_us")
check("cex_futures_ticker",       CANON/"cex_futures_ticker.parquet",       "time_exchange_us")
check("cex_futures_trades",       CANON/"cex_futures_trades.parquet",       "time_exchange_us")
check("cex_futures_liquidations", CANON/"cex_futures_liquidations.parquet", "time_exchange_us")
check("cex_futures_book",         CANON/"cex_futures_book.parquet",         "time_exchange_us")

# L25 — extra check: writer-kept == metadata rows (ParquetWriter integrity)
print("\n  --- L25 integrity ---")
for asset in ["btc","eth","sol"]:
    p = CANON / "orderbook_l25" / f"{asset}.parquet"
    if not p.exists():
        print(f"  MISSING  L25/{asset}")
        FAIL.append(f"MISSING: L25/{asset}")
        continue
    pf = pq.ParquetFile(str(p))
    md_rows = pf.metadata.num_rows
    df_ts = pd.read_parquet(p, columns=["timestamp_us"])
    n = len(df_ts)
    max_ts = pd.to_datetime(df_ts.timestamp_us.max(), unit='us', utc=True)
    integrity = "OK" if md_rows == n else f"MISMATCH writer={n} meta={md_rows}"
    ts_ok = "OK" if max_ts > pd.Timestamp(MIN_TS) else "FAIL"
    status = "OK  " if integrity == "OK" and ts_ok == "OK" else "FAIL"
    if status == "FAIL":
        FAIL.append(f"L25/{asset}: ts_ok={ts_ok} integrity={integrity}")
    print(f"  {status}  L25/{asset:<5s}  {n:>12,} rows  max={max_ts}  integrity={integrity}")

print()
if FAIL:
    print("!!! FAILURES — DO NOT DELETE refresh dir or VPS3 /tmp !!!")
    for f in FAIL:
        print(f"  FAIL: {f}")
    raise SystemExit(1)
else:
    print("ALL CHECKS PASSED — safe to delete refresh_2026_06_03/ and VPS3 /tmp dirs.")
