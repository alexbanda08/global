"""TASK 2b — Sub-minute cross-correlation via Hyperliquid TRADES vs Binance 1SEC.

Hyperliquid has tick-level trades (1-2 sec median dt). Binance has 1SEC OHLCV.
Build per-second VWAP from HL trades, then cross-correlate at 1-60s lags.

Output: _xcorr_subminute_hl.csv
"""
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

def hl_trades_to_1s(asset: str) -> pd.DataFrame:
    df = load_hyperliquid_trades(asset=asset)
    if df.empty: return df
    df = df[(df.time_exchange_us >= WIN_START) & (df.time_exchange_us <= WIN_END)].copy()
    # Determine price column
    pcol = "px" if "px" in df.columns else ("price" if "price" in df.columns else None)
    if pcol is None:
        print(f"HL trades columns: {df.columns.tolist()[:30]}")
        # Best guess
        for c in df.columns:
            if c.lower() in ("price","px","p"):
                pcol = c; break
    qcol = "sz" if "sz" in df.columns else ("size" if "size" in df.columns else ("qty" if "qty" in df.columns else None))
    if pcol is None or qcol is None:
        raise ValueError(f"can't find price/qty in {df.columns.tolist()}")
    df["ts_s"] = (df.time_exchange_us // 1_000_000).astype("int64")
    df[pcol] = df[pcol].astype("float64")
    df[qcol] = df[qcol].astype("float64")
    g = df.groupby("ts_s").apply(
        lambda d: pd.Series({
            "vwap": (d[pcol] * d[qcol]).sum() / max(d[qcol].sum(), 1e-12),
            "vol":  d[qcol].sum(),
        })
    ).reset_index()
    return g

def binance_1s(asset: str) -> pd.DataFrame:
    df = load_klines_1s(asset=asset)
    if df.empty: return df
    df = df[(df.time_period_start_us >= WIN_START) & (df.time_period_start_us <= WIN_END)].copy()
    df["ts_s"] = (df.time_period_start_us // 1_000_000).astype("int64")
    df = df.drop_duplicates("ts_s", keep="last").sort_values("ts_s")
    return df[["ts_s", "price_close"]].rename(columns={"price_close": "binance_close"}).reset_index(drop=True)

def xcorr(a: np.ndarray, b: np.ndarray, lags_s: list[int]) -> dict:
    """corr(a(t), b(t-lag)). Positive lag means b SHIFTED EARLIER => peak at lag>0 = b LEADS a."""
    out = {}
    for L in lags_s:
        if L >= 0:
            xa = a[L:] if L>0 else a
            xb = b[:-L] if L>0 else b
        else:
            k = -L
            xa = a[:-k]; xb = b[k:]
        mask = np.isfinite(xa) & np.isfinite(xb)
        xa, xb = xa[mask], xb[mask]
        if len(xa) < 200 or xa.std()==0 or xb.std()==0:
            out[L] = None
        else:
            out[L] = float(np.corrcoef(xa, xb)[0, 1])
    return out

rows = []
for asset in ["BTC", "ETH", "SOL"]:
    print(f"\n=== {asset} ===", flush=True)
    bn = binance_1s(asset)
    print(f"  binance 1s: {len(bn):,} bars", flush=True)
    hl = hl_trades_to_1s(asset)
    print(f"  hl 1s vwap: {len(hl):,} bars", flush=True)
    m = bn.merge(hl, on="ts_s", how="inner")
    print(f"  joined: {len(m):,}", flush=True)
    if len(m) < 5000: continue
    # restrict to non-zero hl volume
    m = m[m.vol > 0].reset_index(drop=True)
    print(f"  hl vol>0: {len(m):,}", flush=True)
    # Compute log returns
    m["r_b"] = np.log(m.binance_close).diff()
    m["r_h"] = np.log(m.vwap).diff()
    m = m.dropna()
    r_b = m.r_b.values
    r_h = m.r_h.values
    print(f"  ret rows: {len(m):,}", flush=True)
    # xcorr at multiple lag step sizes
    lag_grid = list(range(-60, 61, 1))  # ±60s in 1s steps
    xc = xcorr(r_b, r_h, lag_grid)
    # find peak
    valid = [(L, v) for L, v in xc.items() if v is not None]
    if not valid: continue
    peak_L, peak_v = max(valid, key=lambda p: p[1])
    abs_peak_L, abs_peak_v = max(valid, key=lambda p: abs(p[1]))
    print(f"  peak corr={peak_v:.4f} at lag={peak_L}s (HL leads if lag>0)")
    row = {"asset": asset, "n_bars": len(m), "peak_lag_s": peak_L, "peak_corr": peak_v,
           "abs_peak_lag_s": abs_peak_L, "abs_peak_corr": abs_peak_v}
    for L in [-30,-10,-5,-2,-1,0,1,2,5,10,30]:
        row[f"xc_{L}s"] = xc.get(L)
    rows.append(row)

out = pd.DataFrame(rows)
out.to_csv(OUT_DIR / "_xcorr_subminute_hl.csv", index=False)
print("\n=== RESULTS (HL trades 1s vs Binance 1s) ===")
print(out.to_string(index=False))
print(f"\nWrote {OUT_DIR / '_xcorr_subminute_hl.csv'}")
