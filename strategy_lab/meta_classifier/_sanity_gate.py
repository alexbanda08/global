"""Check gate behavior: does signal direction predict outcome at the gated tail?"""
import math
import pandas as pd
import numpy as np

ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
REFRESH = rf"{ROOT}\data\v4\refresh_2026_05_06"
ASSET_BIN = {"BTC":"BINANCE_SPOT_BTC_USDT","ETH":"BINANCE_SPOT_ETH_USDT","SOL":"BINANCE_SPOT_SOL_USDT"}

print("loading…")
k = pd.read_csv(rf"{REFRESH}\klines_full.csv")
k["ts_s"] = (k.time_period_start_us // 1_000_000).astype("int64")
klines = {a: k[k.symbol_id == ASSET_BIN[a]].sort_values("ts_s")[["ts_s","price_close"]].reset_index(drop=True) for a in ("BTC","ETH","SOL")}

def asof(a, ts):
    """End-time-indexed asof (1MIN bars). Avoids the bar-open-indexed
    lookahead bug fixed in extended_backtest_with_robustness 2026-05-06."""
    df = klines[a]
    end_us = (df.ts_s.astype("int64") + 60).values * 1_000_000
    target_us = int(ts) * 1_000_000
    idx = int(np.searchsorted(end_us, target_us, side="right")) - 1
    return float("nan") if idx < 0 else float(df.price_close.iloc[idx])

m = pd.read_csv(rf"{REFRESH}\markets_full.csv")
r = pd.read_csv(rf"{REFRESH}\market_resolutions_full.csv")[["slug","outcome"]]
df = m.merge(r, on="slug", how="inner", suffixes=("_m",""))
df["outcome"] = df["outcome"].fillna(df.outcome_m)
df = df.dropna(subset=["outcome"])
df = df[df.ticker.isin(["BTC","ETH","SOL"]) & df.timeframe.isin(["5m","15m"])].copy()
df["ws"] = df.slug.str.extract(r"-(\d+)$")[0].astype("int64")
df["asset"] = df.ticker
df["window_s"] = df.timeframe.map({"5m":300,"15m":900})

# Compute ret_2m three ways
print("computing ret_2m candidates…")
def ret2m(r, anchor_offset):
    p0 = asof(r.asset, int(r.ws) + anchor_offset)
    p1 = asof(r.asset, int(r.ws) + anchor_offset + 120)
    if not (math.isfinite(p0) and math.isfinite(p1) and p0 > 0): return float("nan")
    return math.log(p1 / p0)

df["ret2m_at_ws"] = df.apply(lambda r: ret2m(r, 0), axis=1)
df["ret2m_at_strike"] = df.apply(lambda r: ret2m(r, -60), axis=1)
df["abs_ws"] = df.ret2m_at_ws.abs()
df["abs_strike"] = df.ret2m_at_strike.abs()

# Hit rate by quantile bucket of |ret_2m|, per (asset, tf)
print("\n=== Hit rate by |ret_2m| decile, anchor=ws ===")
out_rows = []
for (asset, tf), g in df.groupby(["asset","timeframe"]):
    g = g.dropna(subset=["ret2m_at_ws"]).copy()
    g["dec_ws"] = pd.qcut(g.abs_ws, 10, labels=False, duplicates="drop")
    for dec in range(10):
        sub = g[g.dec_ws == dec]
        if len(sub) < 5: continue
        wins = ((sub.ret2m_at_ws > 0) & (sub.outcome=="Up")) | ((sub.ret2m_at_ws < 0) & (sub.outcome=="Down"))
        out_rows.append([asset, tf, dec, int(len(sub)), float(wins.mean()), float(sub.abs_ws.median()*1e4)])

out = pd.DataFrame(out_rows, columns=["asset","timeframe","decile","n","hit","abs_ret_2m_bp_med"])
print(out.pivot_table(index=["asset","timeframe"], columns="decile", values="hit", aggfunc="first").round(2))

print("\n=== Hit rate by |ret_2m| decile, anchor=strike (ws-60) ===")
out_rows = []
for (asset, tf), g in df.groupby(["asset","timeframe"]):
    g = g.dropna(subset=["ret2m_at_strike"]).copy()
    g["dec"] = pd.qcut(g.abs_strike, 10, labels=False, duplicates="drop")
    for dec in range(10):
        sub = g[g.dec == dec]
        if len(sub) < 5: continue
        wins = ((sub.ret2m_at_strike > 0) & (sub.outcome=="Up")) | ((sub.ret2m_at_strike < 0) & (sub.outcome=="Down"))
        out_rows.append([asset, tf, dec, int(len(sub)), float(wins.mean()), float(sub.abs_strike.median()*1e4)])
out2 = pd.DataFrame(out_rows, columns=["asset","timeframe","decile","n","hit","abs_ret_2m_bp_med"])
print(out2.pivot_table(index=["asset","timeframe"], columns="decile", values="hit", aggfunc="first").round(2))

# Top decile (q90 gate equivalent) detail
print("\n=== Top decile only (=q90 gate equivalent), anchor=strike ===")
print(out2[out2.decile==9].to_string(index=False))
