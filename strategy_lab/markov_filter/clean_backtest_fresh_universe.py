"""Re-run clean backtest using FRESH VPS3 resolutions universe (Apr 22 → May 22).

Replaces the canonical resolutions.parquet which was stale at 2026-05-21 17:36.
Production fires on slugs after that cutoff — they were missing from clean universe.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

OUT_DIR = Path("strategy_lab/markov_filter/_results/clean_backtest_fresh")
OUT_DIR.mkdir(parents=True, exist_ok=True)

FRESH_KLINES = "strategy_lab/markov_filter/_vps3_pull/binance_1m_fresh.csv"
RESOL_CSV    = "strategy_lab/markov_filter/_vps3_pull/all_resolutions_apr22_may22.csv"

ASSETS = ("BTC", "ETH", "SOL")
TIMEFRAMES = {"5m": 300, "15m": 900}


def load_klines():
    k = pd.read_csv(FRESH_KLINES)
    out = {}
    for asset in ASSETS:
        sym = f"BINANCE_SPOT_{asset}_USDT"
        sub = k[k["symbol_id"]==sym].drop_duplicates("time_period_start_us") \
                                     .sort_values("time_period_start_us")
        end_us = sub["time_period_start_us"].values.astype("int64") + 60_000_000
        close  = sub["price_close"].values.astype("float64")
        out[asset] = (end_us, close)
    return out


def close_at(end_us, close, target_us):
    i = int(np.searchsorted(end_us, int(target_us), side="right")) - 1
    if i < 0 or i >= len(close): return float("nan")
    return float(close[i])


def main():
    print("[1] Loading fresh VPS3 resolutions...")
    r = pd.read_csv(RESOL_CSV)
    print(f"   {len(r):,} rows, outcomes: {r['outcome'].value_counts().to_dict()}")
    r["slot_start_s"] = (r["slot_start_us"] / 1_000_000).astype("int64")
    # Map ticker to asset name (CRYPTO_BTC → BTC)
    r["asset"] = r["ticker"].str.replace("CRYPTO_", "", regex=False).str.upper()
    r = r[r["asset"].isin(ASSETS)].copy()
    r["tf"] = r["timeframe"]
    r = r[r["tf"].isin(["5m","15m"])].copy()
    r["window_s"] = r["tf"].map(TIMEFRAMES)
    r["ws_s"] = r["slot_start_s"] - r["window_s"]
    print(f"   After filtering: {len(r):,} ETH/BTC/SOL 5m/15m slugs")
    print(f"   Date range: {pd.Timestamp(r['slot_start_s'].min(), unit='s', tz='UTC')} → {pd.Timestamp(r['slot_start_s'].max(), unit='s', tz='UTC')}")
    print(f"   By cell: {r.groupby(['asset','tf']).size().to_dict()}")

    kcache = load_klines()

    print("\n[2] Computing ret_v1 / ret_v2 per slug...")
    n = len(r)
    ret_v1 = np.full(n, np.nan)
    ret_v2 = np.full(n, np.nan)
    for i, row in enumerate(r.itertuples(index=False)):
        end_us, c = kcache[row.asset]
        ws_us = int(row.ws_s) * 1_000_000
        c0 = close_at(end_us, c, ws_us)
        c120 = close_at(end_us, c, ws_us + 120_000_000)
        if np.isfinite(c0) and np.isfinite(c120) and c0 > 0:
            ret_v1[i] = np.log(c120 / c0)
        cm60 = close_at(end_us, c, ws_us - 60_000_000)
        c60  = close_at(end_us, c, ws_us + 60_000_000)
        if np.isfinite(cm60) and np.isfinite(c60) and cm60 > 0:
            ret_v2[i] = np.log(c60 / cm60)
        if (i+1) % 5000 == 0:
            print(f"   {i+1:,}/{n:,}")
    r = r.copy()
    r["ret_v1"] = ret_v1
    r["ret_v2"] = ret_v2

    print("\n[3] Computing q90 thresholds...")
    r = r.sort_values("slot_start_s").reset_index(drop=True).copy()
    r["thr_v1"] = np.nan
    r["thr_v2"] = np.nan
    LOOKBACK_S = 14 * 86400
    for (asset, tf), idxs in r.groupby(["asset","tf"]).groups.items():
        sub = r.loc[idxs].copy()
        abs_v1 = np.abs(sub["ret_v1"].values)
        abs_v2 = np.abs(sub["ret_v2"].values)
        ss = sub["slot_start_s"].values
        thr_v1 = np.full(len(sub), np.nan)
        thr_v2 = np.full(len(sub), np.nan)
        for j in range(len(sub)):
            t_now = ss[j]
            mask = (ss >= t_now - LOOKBACK_S) & (ss < t_now)
            if mask.sum() < 50: continue
            valid_v1 = abs_v1[mask][~np.isnan(abs_v1[mask])]
            valid_v2 = abs_v2[mask][~np.isnan(abs_v2[mask])]
            if len(valid_v1) >= 50:
                thr_v1[j] = float(np.quantile(valid_v1, 0.90))
            if len(valid_v2) >= 50:
                thr_v2[j] = float(np.quantile(valid_v2, 0.90))
        r.loc[idxs, "thr_v1"] = thr_v1
        r.loc[idxs, "thr_v2"] = thr_v2
        print(f"   {asset} {tf}: thr_v2 mean={np.nanmean(thr_v2):.6f}")

    r.to_csv(OUT_DIR / "universe.csv", index=False)

    # Fire tables
    print("\n[4] Per-strategy fire tables + WR cross-tabs...")
    for strat, rcol, tcol in [("momo_v1","ret_v1","thr_v1"),
                              ("momo_v2","ret_v2","thr_v2")]:
        fires = r[(r[rcol].notna()) & (r[tcol].notna()) &
                  (r[rcol].abs() >= r[tcol])].copy()
        fires["signal"] = np.where(fires[rcol] > 0, "UP", "DOWN")
        fires["won"] = ((fires["signal"]=="UP") & (fires["outcome"]=="Up")) | \
                       ((fires["signal"]=="DOWN") & (fires["outcome"]=="Down"))
        fires["cell"] = fires["asset"].str.lower() + "_" + fires["tf"]
        fires.to_csv(OUT_DIR / f"fires_{strat}.csv", index=False)

        # Full window summary
        print(f"\n=== {strat} (FULL window) ===")
        agg = fires.groupby("cell").agg(
            n=("won","size"), wins=("won","sum"), wr=("won","mean")
        ).round({"wr":4})
        agg["wr"] = (agg["wr"]*100).round(2)
        print(agg.to_string())

        # Post-F7 23.5h subset
        W = (1779292620, 1779394800)  # May 20 19:57 → May 21 19:20+ for full data
        sub = fires[(fires["ws_s"] >= W[0] - 300) & (fires["ws_s"] <= W[1])].copy()
        print(f"\n   --- POST-F7 23.5h subset ---")
        if len(sub):
            agg2 = sub.groupby("cell").agg(n=("won","size"), wr=("won","mean")).round({"wr":4})
            agg2["wr"] = (agg2["wr"]*100).round(2)
            print(agg2.to_string())
            for cell, g in sub.groupby("cell"):
                if cell not in ("eth_5m","btc_15m"): continue
                ct = pd.crosstab(g["signal"], g["outcome"], margins=True)
                print(f"\n   {cell} cross-tab:\n{ct}")


if __name__ == "__main__":
    main()
