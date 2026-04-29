"""
Fetch 1h OHLCV from Binance for additional coins and resample BTC/ETH/SOL
existing data to multiple timeframes (15m, 30m, 1h, 2h, 4h).

Writes: strategy_lab/features/multi_tf/{SYM}_{TF}.parquet
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd
import requests

OUT = Path(__file__).resolve().parent / "features" / "multi_tf"
OUT.mkdir(parents=True, exist_ok=True)
FEAT = Path(__file__).resolve().parent / "features"

BINANCE = "https://api.binance.com/api/v3/klines"

NEW_COINS = ["LINKUSDT", "AVAXUSDT", "DOGEUSDT", "INJUSDT", "SUIUSDT", "TONUSDT"]
TARGET_TFS = ["15m", "30m", "1h", "2h", "4h"]


def fetch_binance(symbol, interval, start_ms, end_ms):
    """Paginate through Binance klines endpoint."""
    all_bars = []
    cur = start_ms
    while cur < end_ms:
        resp = requests.get(BINANCE, params={
            "symbol": symbol, "interval": interval, "startTime": cur,
            "endTime": end_ms, "limit": 1000
        }, timeout=15)
        if resp.status_code != 200:
            print(f"  !! {symbol} {interval}: HTTP {resp.status_code} {resp.text[:120]}")
            break
        data = resp.json()
        if not data:
            break
        all_bars.extend(data)
        cur = data[-1][0] + 1
        if len(data) < 1000:
            break
        time.sleep(0.1)
    if not all_bars:
        return None
    cols = ["open_time", "open", "high", "low", "close", "volume",
            "close_time", "qvol", "trades", "tbbv", "tbqv", "_"]
    df = pd.DataFrame(all_bars, columns=cols)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.set_index("open_time")[["open", "high", "low", "close", "volume"]]
    return df


def resample_ohlcv(df_src, target_tf):
    """Resample higher-frequency OHLCV to a target TF."""
    agg = df_src.resample(target_tf).agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"
    }).dropna(how="any")
    return agg


def pandas_tf_alias(tf):
    return {"15m": "15min", "30m": "30min", "1h": "1h", "2h": "2h", "4h": "4h"}[tf]


def main():
    # 1) Resample BTC/ETH/SOL from existing 15m parquet (which covers from 2017)
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        src = pd.read_parquet(FEAT / f"{sym}_15m_features.parquet")
        src = src.dropna(subset=["open", "high", "low", "close", "volume"])
        src = src[["open", "high", "low", "close", "volume"]]
        for tf in TARGET_TFS:
            alias = pandas_tf_alias(tf)
            res = resample_ohlcv(src, alias)
            res.to_parquet(OUT / f"{sym}_{tf}.parquet")
            print(f"  {sym} {tf}: {len(res):,} bars -> {OUT / f'{sym}_{tf}.parquet'}")

    # 2) Fetch new coins at 1h from Binance
    start_ms = int(pd.Timestamp("2019-01-01", tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp("2026-04-01", tz="UTC").timestamp() * 1000)
    for sym in NEW_COINS:
        print(f"\nFetching {sym} @ 1h ...")
        df = fetch_binance(sym, "1h", start_ms, end_ms)
        if df is None or len(df) < 1000:
            print(f"  {sym}: no data or too short")
            continue
        print(f"  {sym} 1h: {len(df):,} bars  {df.index[0]} -> {df.index[-1]}")
        df.to_parquet(OUT / f"{sym}_1h.parquet")
        # Resample to 2h and 4h
        for tf in ["2h", "4h"]:
            alias = pandas_tf_alias(tf)
            res = resample_ohlcv(df, alias)
            res.to_parquet(OUT / f"{sym}_{tf}.parquet")
            print(f"  {sym} {tf}: {len(res):,} bars")

    # 3) Also fetch 15m and 30m for new coins (shorter window: 2022-present to save time)
    s15_ms = int(pd.Timestamp("2022-01-01", tz="UTC").timestamp() * 1000)
    for sym in NEW_COINS:
        print(f"\nFetching {sym} @ 15m (2022+)...")
        df = fetch_binance(sym, "15m", s15_ms, end_ms)
        if df is None or len(df) < 5000:
            print(f"  {sym}: no 15m data")
            continue
        print(f"  {sym} 15m: {len(df):,} bars")
        df.to_parquet(OUT / f"{sym}_15m.parquet")
        res = resample_ohlcv(df, "30min")
        res.to_parquet(OUT / f"{sym}_30m.parquet")
        print(f"  {sym} 30m: {len(res):,} bars")


if __name__ == "__main__":
    sys.exit(main() or 0)
