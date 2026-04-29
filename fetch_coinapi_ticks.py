"""
CoinAPI tick-data POC — pull ~1 week of BTC perp TRADES, aggregate into 15m
microstructure features (CVD, taker ratio, VWAP deviation, trade intensity).

Cost projection:
  * 1 BTC day ≈ 1.2M trades ≈ 12,000 credits ($2.4)
  * 7 days × BTC alone ≈ 85k credits (~$17 of $25)

Output: data/coinapi/trades/<SYM>/YYYY-MM-DD.parquet (raw)
        data/coinapi/micro_features/<SYM>_15m_micro.parquet (aggregated)
"""
from __future__ import annotations
import os, sys, time, json
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

import requests
import pandas as pd
import numpy as np

K = os.environ.get("COINAPI_API_KEY") or "4e438807-b29b-4a91-9150-1165a85a12e9"
H = {"X-CoinAPI-Key": K}
ROOT = Path(__file__).parent / "data" / "coinapi"

SYMBOLS = {
    "BTCUSDT": "BINANCEFTS_PERP_BTC_USDT",
}

DAYS = 7
END   = date.today() - timedelta(days=2)    # avoid incomplete day
START = END - timedelta(days=DAYS - 1)

LIMIT = 100000     # max per request (CoinAPI caps at 100k)


def fetch_day_trades(symbol: str, coinapi_sym: str, d: date) -> pd.DataFrame:
    """Pull all trades for one UTC day, paginating by time_start."""
    out_dir = ROOT / "trades" / symbol
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{d}.parquet"
    if out_path.exists() and out_path.stat().st_size > 0:
        print(f"  skip (cached) {d}")
        return pd.read_parquet(out_path)

    end_iso = f"{d + timedelta(days=1)}T00:00:00"
    cursor  = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    end_dt  = datetime.fromisoformat(end_iso + "+00:00")
    all_rows = []
    total_credits = 0

    while cursor < end_dt:
        # CoinAPI expects ISO format up to seconds (no microseconds), .0000000 suffix allowed
        ts = cursor.strftime("%Y-%m-%dT%H:%M:%S")
        params = {
            "time_start": ts,
            "time_end":   end_iso,
            "limit": LIMIT,
        }
        r = requests.get(
            f"https://rest.coinapi.io/v1/trades/{coinapi_sym}/history",
            params=params, headers=H, timeout=120,
        )
        if r.status_code == 429:
            print(f"    429 — sleep 10s"); time.sleep(10); continue
        if r.status_code == 403:
            print(f"    403 QUOTA — stop"); break
        if r.status_code != 200:
            print(f"    HTTP {r.status_code}: {r.text[:150]}"); break
        cost = int(r.headers.get("x-ratelimit-request-cost", "0"))
        total_credits += cost
        batch = r.json()
        if not batch: break
        all_rows.extend(batch)
        last_t = batch[-1]["time_exchange"]
        new_cursor = datetime.fromisoformat(last_t.replace("Z", "+00:00")) + timedelta(microseconds=1)
        if new_cursor <= cursor: break
        cursor = new_cursor
        if len(all_rows) % 500000 < LIMIT:
            print(f"    {d} rows={len(all_rows):,} cursor={cursor.strftime('%H:%M:%S')} credits={total_credits}",
                  flush=True)
        if len(batch) < LIMIT:
            break

    if not all_rows:
        print(f"  {d}: no data")
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    df["time_exchange"] = pd.to_datetime(df["time_exchange"], utc=True)
    df = df[["time_exchange","price","size","taker_side"]].sort_values("time_exchange")
    df.to_parquet(out_path, engine="pyarrow", compression="zstd", index=False)
    print(f"  {d}: {len(df):,} trades, {total_credits:,} credits, -> {out_path.name}")
    return df


def aggregate_micro_features(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate trade ticks into 15m bar features."""
    df = df.copy()
    df["is_buy"]  = df["taker_side"].str.upper() == "BUY"
    df["is_sell"] = df["taker_side"].str.upper() == "SELL"
    df["buy_vol"]  = df["size"] * df["is_buy"]
    df["sell_vol"] = df["size"] * df["is_sell"]
    df["notional"] = df["size"] * df["price"]
    # 15m bar indexer
    df = df.set_index("time_exchange")
    g = df.resample("15min", label="left", closed="left")
    agg = pd.DataFrame({
        "n_trades":     g.size(),
        "volume":       g["size"].sum(),
        "notional":     g["notional"].sum(),
        "buy_vol":      g["buy_vol"].sum(),
        "sell_vol":     g["sell_vol"].sum(),
        "avg_price":    (g["price"].sum() * 0).replace(0, np.nan),   # placeholder; compute below
    })
    # VWAP per bar (proper calc)
    agg["avg_price"] = agg["notional"] / (agg["volume"] + 1e-9)
    # Order-flow features
    agg["cvd_15m"]        = agg["buy_vol"] - agg["sell_vol"]
    agg["taker_ratio"]    = agg["buy_vol"] / (agg["buy_vol"] + agg["sell_vol"] + 1e-9)
    agg["trade_intensity"] = agg["n_trades"]           # for z-score later
    # Rolling normalisation (7 days at 96 bars/day — will be short on POC; use smaller window)
    N = min(len(agg), 4 * 24)   # 1 day rolling
    agg["cvd_z"]    = (agg["cvd_15m"] - agg["cvd_15m"].rolling(N).mean()) / agg["cvd_15m"].rolling(N).std()
    agg["taker_z"]  = (agg["taker_ratio"] - agg["taker_ratio"].rolling(N).mean()) / agg["taker_ratio"].rolling(N).std()
    agg["intensity_z"] = (agg["n_trades"] - agg["n_trades"].rolling(N).mean()) / agg["n_trades"].rolling(N).std()
    return agg


def main():
    total_start = time.time()
    for sym, cid in SYMBOLS.items():
        print(f"\n=== {sym}  ({cid}) — {START} to {END} ({DAYS} days) ===")
        day_dfs = []
        for i in range(DAYS):
            d = START + timedelta(days=i)
            try:
                df = fetch_day_trades(sym, cid, d)
                if not df.empty:
                    day_dfs.append(df)
            except Exception as e:
                print(f"  {d}: ERROR {type(e).__name__} {e}")
        if not day_dfs:
            print(f"  no data for {sym}"); continue
        all_ticks = pd.concat(day_dfs, ignore_index=True).drop_duplicates("time_exchange")
        print(f"\n  Total ticks: {len(all_ticks):,}")
        # Aggregate 15m features
        feat = aggregate_micro_features(all_ticks)
        out = ROOT / "micro_features" / f"{sym}_15m_micro.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        feat.to_parquet(out, engine="pyarrow", compression="zstd")
        print(f"  15m micro-features: {len(feat):,} bars -> {out}")
        print(f"  cvd_z dist: mean={feat['cvd_z'].mean():.2f} std={feat['cvd_z'].std():.2f}")

    total_size = sum(p.stat().st_size for p in ROOT.rglob("*") if p.is_file()) / 1024 / 1024
    print(f"\n[done] total disk: {total_size:.1f} MB   elapsed {time.time()-total_start:.0f}s")


if __name__ == "__main__":
    sys.exit(main() or 0)
