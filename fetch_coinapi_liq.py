"""
CoinAPI — pull liquidation event history for BTC/ETH/SOL perp.

Available metrics (only 13 are mapped for BINANCEFTS_PERP; LIQUIDITY_* require
separate Flat Files subscription and are not available on standard credits):
  LIQUIDATION_QUANTITY, LIQUIDATION_PRICE, LIQUIDATION_FILLED_ACCUMULATED_QUANTITY,
  LIQUIDATION_AVERAGE_PRICE
  (+ categorical: LIQUIDATION_ORDER_STATUS, _ORDER_TYPE, _SYMBOL — skip these)

Data starts ~2023-01-01 for Binance futures perp.
Aggregation: 1MIN per-bar { first, last, min, max, count, sum }.

Expected size: ~1.2M 1-min bars/symbol × 3 symbols × 4 metrics = 14.4M points.
At ~100 points/credit this is ~144k credits => ~$0.30-1 of $25 budget.
"""
from __future__ import annotations
import os, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import pandas as pd

K = os.environ.get("COINAPI_API_KEY") or "4e438807-b29b-4a91-9150-1165a85a12e9"
H = {"X-CoinAPI-Key": K}
BASE = "https://rest.coinapi.io/v1/metrics/symbol/history"
ROOT = Path(__file__).parent / "data" / "coinapi"

SYMBOLS = {
    "BTCUSDT": "BINANCEFTS_PERP_BTC_USDT",
    "ETHUSDT": "BINANCEFTS_PERP_ETH_USDT",
    "SOLUSDT": "BINANCEFTS_PERP_SOL_USDT",
}

LIQ_METRICS = [
    "LIQUIDATION_QUANTITY",
    "LIQUIDATION_PRICE",
    "LIQUIDATION_AVERAGE_PRICE",
    "LIQUIDATION_FILLED_ACCUMULATED_QUANTITY",
]

# Data discovered to exist from 2023-01-02 for Binance perp.
# Pull 2023-01-01 -> today (allow 1-day slide if first page empty).
HISTORY_START = datetime(2023, 1, 1, tzinfo=timezone.utc)


def fetch_range(symbol: str, metric: str, start: datetime, end: datetime,
                period_id: str = "1MIN", limit: int = 100000) -> pd.DataFrame:
    rows = []
    cursor = start
    empty_slides = 0
    while cursor < end:
        params = {
            "symbol_id": symbol,
            "metric_id": metric,
            "period_id": period_id,
            "time_start": cursor.strftime("%Y-%m-%dT%H:%M:%S"),
            "time_end":   end.strftime("%Y-%m-%dT%H:%M:%S"),
            "limit": limit,
        }
        r = requests.get(BASE, params=params, headers=H, timeout=180)
        if r.status_code == 429:
            print("    429 rate-limit, 10s sleep"); time.sleep(10); continue
        if r.status_code == 403:
            print("    403 QUOTA exhausted — stop"); break
        if r.status_code != 200:
            print(f"    HTTP {r.status_code}: {r.text[:200]}"); break
        batch = r.json()
        if not batch:
            # slide forward 30 days (no data in this window)
            empty_slides += 1
            if empty_slides > 12:      # ~1 year of empty window — give up
                break
            cursor = cursor + timedelta(days=30)
            continue
        empty_slides = 0
        rows.extend(batch)
        last_end = batch[-1]["time_period_end"]
        new_cursor = datetime.fromisoformat(last_end.replace("Z","+00:00"))
        if new_cursor <= cursor:
            break
        cursor = new_cursor
        if len(batch) < limit:
            break
        if len(rows) % 200000 < limit:
            print(f"    rows={len(rows):,}  cursor={cursor.date()}", flush=True)
        time.sleep(0.2)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["time_period_start"] = pd.to_datetime(df["time_period_start"], utc=True)
    df["time_period_end"]   = pd.to_datetime(df["time_period_end"],   utc=True)
    return df


def save(df: pd.DataFrame, sym: str, metric: str):
    if df.empty:
        print("    (no data)"); return
    out = ROOT / "liquidations" / sym / f"{metric}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, engine="pyarrow", compression="zstd", index=False)
    sz = out.stat().st_size / 1024 / 1024
    print(f"    {len(df):,} rows -> {out.name} ({sz:.1f} MB)")


def main():
    utc_now = datetime.now(timezone.utc)
    for sym, cid in SYMBOLS.items():
        print(f"\n=== {sym}  ({cid}) ===", flush=True)
        for m in LIQ_METRICS:
            print(f"  {m}  {HISTORY_START.date()} -> {utc_now.date()}", flush=True)
            df = fetch_range(cid, m, HISTORY_START, utc_now, "1MIN")
            save(df, sym, m)
    total_mb = sum(p.stat().st_size for p in ROOT.rglob("*") if p.is_file()) / 1024 / 1024
    print(f"\nDone. Disk: {total_mb:.1f} MB")


if __name__ == "__main__":
    sys.exit(main() or 0)
