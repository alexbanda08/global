"""TASK 1 — Data availability across exchanges for BTC/ETH/SOL.

Checks date range, granularity, schema, sample counts for each exchange × asset.
Outputs:
  strategy_lab/cross_exchange_leadlag_2026_05_26/_data_availability.csv
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

import pandas as pd
import numpy as np
from load import (
    load_klines, load_klines_1s, load_okx_klines,
    load_hyperliquid_klines, load_hyperliquid_trades, load_hyperliquid_liquidations,
    load_chainlink_rtds,
)

OUT_DIR = ROOT / "strategy_lab" / "cross_exchange_leadlag_2026_05_26"
OUT_DIR.mkdir(exist_ok=True, parents=True)

# Date window of interest for the study
WIN_START_S = pd.Timestamp("2026-04-30", tz="UTC").timestamp()
WIN_END_S   = pd.Timestamp("2026-05-22", tz="UTC").timestamp()

rows = []

def summarize(name: str, ts_us: np.ndarray, extra: dict | None = None) -> dict:
    if len(ts_us) == 0:
        return {"name": name, "n_rows": 0, "min_ts": None, "max_ts": None,
                "median_dt_s": None, "max_gap_s": None,
                "n_in_window": 0, "pct_coverage_window": 0.0, **(extra or {})}
    ts_us = np.asarray(ts_us, dtype="int64")
    ts_s = ts_us // 1_000_000
    dt = np.diff(np.unique(ts_s))
    in_win = ((ts_s >= int(WIN_START_S)) & (ts_s <= int(WIN_END_S))).sum()
    expected_secs_in_window = int(WIN_END_S - WIN_START_S)  # for 1Hz reference
    return {
        "name": name,
        "n_rows": int(len(ts_us)),
        "min_ts": pd.Timestamp(int(ts_s.min()), unit="s", tz="UTC").isoformat(),
        "max_ts": pd.Timestamp(int(ts_s.max()), unit="s", tz="UTC").isoformat(),
        "median_dt_s": float(np.median(dt)) if len(dt) else None,
        "max_gap_s": float(np.max(dt)) if len(dt) else None,
        "n_in_window": int(in_win),
        "expected_1hz_rows": expected_secs_in_window,
        **(extra or {}),
    }

# Multi-venue 1MIN klines
KLINE_SOURCES = ["binance-spot-ws", "coinbase-spot-ws", "kraken-spot-ws", "okx-ws"]
for asset in ["BTC", "ETH", "SOL"]:
    for src in KLINE_SOURCES:
        try:
            if src == "okx-ws":
                df = load_okx_klines(asset=asset, period_id="1MIN")
            else:
                df = load_klines(asset, source=src, period_id="1MIN")
            ts = df.time_period_start_us.values if not df.empty else np.array([], dtype="int64")
            rows.append(summarize(f"{src}_{asset}_1MIN", ts,
                                   extra={"asset": asset, "venue": src, "tf": "1MIN",
                                          "schema": "OHLCV"}))
        except Exception as e:
            rows.append({"name": f"{src}_{asset}_1MIN", "error": str(e), "n_rows": 0,
                          "asset": asset, "venue": src, "tf": "1MIN"})

# Binance 1s klines (sub-minute)
for asset in ["BTC", "ETH", "SOL"]:
    try:
        df = load_klines_1s(asset=asset)
        ts = df.time_period_start_us.values if not df.empty else np.array([], dtype="int64")
        rows.append(summarize(f"binance_1s_{asset}", ts,
                               extra={"asset": asset, "venue": "binance-spot-ws", "tf": "1SEC",
                                      "schema": "OHLCV"}))
    except Exception as e:
        rows.append({"name": f"binance_1s_{asset}", "error": str(e), "n_rows": 0,
                      "asset": asset, "venue": "binance-spot-ws", "tf": "1SEC"})

# Hyperliquid 1MIN klines
for asset in ["BTC", "ETH", "SOL"]:
    try:
        df = load_hyperliquid_klines(asset=asset, period_id="1MIN")
        ts = df.time_period_start_us.values if not df.empty else np.array([], dtype="int64")
        rows.append(summarize(f"hyperliquid_{asset}_1MIN", ts,
                               extra={"asset": asset, "venue": "hyperliquid", "tf": "1MIN",
                                      "schema": "OHLCV"}))
    except Exception as e:
        rows.append({"name": f"hyperliquid_{asset}_1MIN", "error": str(e), "n_rows": 0,
                      "asset": asset, "venue": "hyperliquid", "tf": "1MIN"})

# Hyperliquid trades (sub-second possible)
for asset in ["BTC", "ETH", "SOL"]:
    try:
        df = load_hyperliquid_trades(asset=asset)
        ts = df.time_exchange_us.values if not df.empty else np.array([], dtype="int64")
        rows.append(summarize(f"hyperliquid_trades_{asset}", ts,
                               extra={"asset": asset, "venue": "hyperliquid", "tf": "TICK",
                                      "schema": "trades"}))
    except Exception as e:
        rows.append({"name": f"hyperliquid_trades_{asset}", "error": str(e), "n_rows": 0,
                      "asset": asset, "venue": "hyperliquid", "tf": "TICK"})

# Hyperliquid liquidations
for asset in ["BTC", "ETH", "SOL"]:
    try:
        df = load_hyperliquid_liquidations(asset=asset)
        ts = df.time_exchange_us.values if not df.empty else np.array([], dtype="int64")
        rows.append(summarize(f"hyperliquid_liqs_{asset}", ts,
                               extra={"asset": asset, "venue": "hyperliquid", "tf": "EVENT",
                                      "schema": "liquidations"}))
    except Exception as e:
        rows.append({"name": f"hyperliquid_liqs_{asset}", "error": str(e), "n_rows": 0,
                      "asset": asset, "venue": "hyperliquid", "tf": "EVENT"})

# Chainlink RTDS reference
for asset in ["BTC", "ETH", "SOL"]:
    try:
        df = load_chainlink_rtds(asset=asset)
        ts = df.timestamp_us.values if not df.empty else np.array([], dtype="int64")
        rows.append(summarize(f"chainlink_{asset}", ts,
                               extra={"asset": asset, "venue": "chainlink", "tf": "1HZ",
                                      "schema": "price-tick"}))
    except Exception as e:
        rows.append({"name": f"chainlink_{asset}", "error": str(e), "n_rows": 0,
                      "asset": asset, "venue": "chainlink", "tf": "1HZ"})

out = pd.DataFrame(rows)
out.to_csv(OUT_DIR / "_data_availability.csv", index=False)
print(out.to_string(index=False))
print(f"\nWrote {OUT_DIR / '_data_availability.csv'}")
