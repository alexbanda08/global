"""Probe data coverage to bound the lag-taker OOS re-validation window."""
import sys
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
CANON = ROOT / "data" / "v4" / "canonical"
sys.path.insert(0, str(CANON))

SYM = {"BTC": "BINANCE_SPOT_BTC_USDT", "ETH": "BINANCE_SPOT_ETH_USDT", "SOL": "BINANCE_SPOT_SOL_USDT"}

# 1) binance-spot-ws 1SEC coverage per asset
df = pd.read_parquet(CANON / "klines_1s.parquet",
                     columns=["time_period_start_us", "symbol_id", "source", "period_id"])
m = (df.source == "binance-spot-ws") & (df.period_id == "1SEC")
print("=== klines_1s binance-spot-ws 1SEC coverage ===")
for a, s in SYM.items():
    sub = df[m & (df.symbol_id == s)]
    lo = pd.Timestamp(int(sub.time_period_start_us.min()), unit="us", tz="UTC")
    hi = pd.Timestamp(int(sub.time_period_start_us.max()), unit="us", tz="UTC")
    print(f"  {a}: {lo} -> {hi}  n={len(sub):,}")

# 2) resolutions ss range
from load import load_resolutions  # noqa: E402
res = load_resolutions(); res["slug"] = res["slug"].astype(str)
print("=== resolutions ss (slot_start) range ===")
for a in ["BTC", "ETH", "SOL"]:
    for tf in ["5m", "15m"]:
        pref = f"{a.lower()}-updown-{tf}-"
        sub = res[(res.ticker == a) & (res.timeframe == tf) & res.slug.str.startswith(pref)].copy()
        if sub.empty:
            print(f"  {a} {tf}: EMPTY"); continue
        ss = sub.slug.str.rsplit("-", n=1).str[-1].astype(np.int64)
        print(f"  {a} {tf}: {pd.Timestamp(int(ss.min()),unit='s',tz='UTC')} -> "
              f"{pd.Timestamp(int(ss.max()),unit='s',tz='UTC')}  n={len(sub):,}")

# 3) L25 coverage via row-group metadata (cheap)
import pyarrow.parquet as pq  # noqa: E402
print("=== L25 orderbook coverage (from column stats) ===")
for a in ["btc", "eth", "sol"]:
    p = CANON / "orderbook_l25" / f"{a}.parquet"
    if not p.exists():
        print(f"  {a}: MISSING {p}"); continue
    pf = pq.ParquetFile(p)
    # find a timestamp-ish column
    names = pf.schema_arrow.names
    tcol = next((c for c in names if c.endswith("_us") or "timestamp" in c or c == "ts"), None)
    md = pf.metadata
    ci = names.index(tcol)
    mn = min(md.row_group(i).column(ci).statistics.min for i in range(md.num_row_groups))
    mx = max(md.row_group(i).column(ci).statistics.max for i in range(md.num_row_groups))
    # detect unit
    unit = "us" if mn > 1e15 else ("ms" if mn > 1e12 else "s")
    print(f"  {a}: col={tcol} {pd.Timestamp(int(mn),unit=unit,tz='UTC')} -> "
          f"{pd.Timestamp(int(mx),unit=unit,tz='UTC')}  rows={md.num_rows:,}")
