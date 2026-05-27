"""TASK 2c — faster sub-minute cross-correlation. Pre-computes vectorized resample."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

import pandas as pd
import numpy as np
from load import load_klines_1s, load_hyperliquid_trades

OUT_DIR = ROOT / "strategy_lab" / "cross_exchange_leadlag_2026_05_26"

WIN_START = int(pd.Timestamp("2026-05-01 00:00", tz="UTC").value // 1000)
WIN_END   = int(pd.Timestamp("2026-05-16 06:00", tz="UTC").value // 1000)

def hl_trades_to_1s_fast(asset: str) -> pd.DataFrame:
    df = load_hyperliquid_trades(asset=asset)
    if df.empty: return df
    df = df[(df.time_exchange_us >= WIN_START) & (df.time_exchange_us <= WIN_END)]
    cols = df.columns.tolist()
    pcol = "px" if "px" in cols else ("price" if "price" in cols else next((c for c in cols if c.lower() in ("p","px","price","mark_px")), None))
    qcol = "sz" if "sz" in cols else ("size" if "size" in cols else next((c for c in cols if c.lower() in ("q","sz","size","qty","amount")), None))
    if pcol is None or qcol is None: raise ValueError(cols)
    ts_s = (df.time_exchange_us.values // 1_000_000).astype("int64")
    px = df[pcol].astype("float64").values
    sz = df[qcol].astype("float64").values
    # Vectorized vwap aggregation per second using pandas groupby on numpy arrays
    g = pd.DataFrame({"ts_s": ts_s, "pq": px*sz, "q": sz}).groupby("ts_s", sort=True).agg({"pq":"sum","q":"sum"})
    g = g[g.q > 0]
    g["vwap"] = g.pq / g.q
    return g.reset_index()[["ts_s","vwap","q"]]

def binance_1s(asset: str) -> pd.DataFrame:
    df = load_klines_1s(asset=asset)
    if df.empty: return df
    df = df[(df.time_period_start_us >= WIN_START) & (df.time_period_start_us <= WIN_END)].copy()
    df["ts_s"] = (df.time_period_start_us // 1_000_000).astype("int64")
    df = df.drop_duplicates("ts_s", keep="last").sort_values("ts_s")
    return df[["ts_s", "price_close"]].rename(columns={"price_close": "binance_close"}).reset_index(drop=True)

def xcorr(a: np.ndarray, b: np.ndarray, lags_s: list[int]) -> dict:
    """corr(a(t), b(t-lag)). Peak at lag>0 means b LEADS a."""
    out = {}
    for L in lags_s:
        if L > 0: xa, xb = a[L:], b[:-L]
        elif L < 0: k=-L; xa, xb = a[:-k], b[k:]
        else: xa, xb = a, b
        mask = np.isfinite(xa) & np.isfinite(xb)
        xa, xb = xa[mask], xb[mask]
        if len(xa) < 500 or xa.std()==0 or xb.std()==0: out[L]=None
        else: out[L] = float(np.corrcoef(xa, xb)[0, 1])
    return out

rows = []
for asset in ["BTC", "ETH", "SOL"]:
    print(f"\n=== {asset} ===", flush=True)
    bn = binance_1s(asset)
    print(f"  binance 1s: {len(bn):,}", flush=True)
    hl = hl_trades_to_1s_fast(asset)
    print(f"  hl 1s vwap: {len(hl):,}", flush=True)
    m = bn.merge(hl, on="ts_s", how="inner")
    print(f"  joined: {len(m):,}", flush=True)
    if len(m) < 5000: continue
    m["r_b"] = np.log(m.binance_close.values).astype("float64")
    m["r_b"] = m["r_b"].diff()
    m["r_h"] = np.log(m.vwap.values).astype("float64")
    m["r_h"] = m["r_h"].diff()
    m = m.dropna()
    r_b = m.r_b.values
    r_h = m.r_h.values
    print(f"  ret rows: {len(m):,}", flush=True)
    # Use only lags ±15s for speed
    lag_grid = list(range(-15, 16, 1)) + [-30, -20, 20, 30, -60, 60]
    xc = xcorr(r_b, r_h, sorted(set(lag_grid)))
    valid = [(L, v) for L, v in xc.items() if v is not None]
    if not valid: continue
    peak_L, peak_v = max(valid, key=lambda p: p[1])
    print(f"  peak corr={peak_v:.5f} at lag={peak_L}s (positive = HL leads binance)")
    row = {"asset": asset, "n_bars": len(m), "peak_lag_s": peak_L, "peak_corr": peak_v}
    for L in [-30,-10,-5,-2,-1,0,1,2,5,10,30]:
        row[f"xc_{L}s"] = xc.get(L)
    rows.append(row)

out = pd.DataFrame(rows)
out.to_csv(OUT_DIR / "_xcorr_subminute_hl_fast.csv", index=False)
print("\n=== RESULTS (HL trades 1s vs Binance 1s) ===")
print(out.to_string(index=False))
