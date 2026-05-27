"""TASK 2 — Cross-correlation of log returns between binance and each venue.

Native granularity: 1MIN bars (60s) for all venues except binance 1SEC.
So cross-corr is computed on 1MIN log-returns with lags in MINUTES (±10 min).

For sub-minute precision we'd need 1SEC data on alt venues, which we don't have.

Approach:
  1. Load 1MIN bars per (asset, venue).
  2. Align on a common minute grid.
  3. Compute log returns r_v(t) = log(close_v(t) / close_v(t-1)).
  4. xcorr(lag) = corr(r_binance(t), r_other(t - lag)) for lag ∈ [-10, +10] min.
  5. negative lag with positive max xcorr => OTHER LEADS BINANCE.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra/Desktop/global".replace("/", "\\"))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

import pandas as pd
import numpy as np
from load import load_klines, load_okx_klines, load_hyperliquid_klines

OUT_DIR = ROOT / "strategy_lab" / "cross_exchange_leadlag_2026_05_26"

# Common window — bounded by all venues having data
# Kraken starts May 7, all alt-venues end May 16 ~07:00
WIN_START = pd.Timestamp("2026-05-07 13:00", tz="UTC").value // 1000  # us
WIN_END   = pd.Timestamp("2026-05-16 06:00", tz="UTC").value // 1000  # us  (~9d window)

def fetch_1min(asset: str, venue_key: str) -> pd.DataFrame:
    """Returns df with columns: ts_min (int, minute index), close."""
    if venue_key == "binance":
        df = load_klines(asset, source="binance-spot-ws", period_id="1MIN")
    elif venue_key == "coinbase":
        df = load_klines(asset, source="coinbase-spot-ws", period_id="1MIN")
    elif venue_key == "kraken":
        df = load_klines(asset, source="kraken-spot-ws", period_id="1MIN")
    elif venue_key == "okx":
        df = load_okx_klines(asset=asset, period_id="1MIN")
    elif venue_key == "hyperliquid":
        df = load_hyperliquid_klines(asset=asset, period_id="1MIN")
    else:
        raise ValueError(venue_key)
    if df.empty:
        return df
    df = df[(df.time_period_start_us >= WIN_START) & (df.time_period_start_us <= WIN_END)].copy()
    df["ts_min"] = (df.time_period_start_us // 60_000_000).astype("int64")
    df = df.drop_duplicates("ts_min", keep="last").sort_values("ts_min")
    return df[["ts_min", "price_close"]].reset_index(drop=True)

def xcorr_lag(r_a: np.ndarray, r_b: np.ndarray, max_lag: int = 10) -> tuple[np.ndarray, np.ndarray]:
    """Returns (lags, xcorr) where xcorr[i] = corr(r_a(t), r_b(t - lags[i])).
    Negative lag => r_b is shifted EARLIER => if xcorr peaks at negative lag, b leads a.
    Actually convention: corr(r_a(t), r_b(t-lag)). If lag<0, we're comparing r_a(t) with r_b(t+|lag|) (b in the future of a).
    So PEAK at NEGATIVE lag = b leads a (since b's future predicts a's present == b's present predicts a's future).
    Standard convention used here: lag>0 means we shift b BACK by `lag` (so b at earlier time correlates with a now)
        => peak at lag>0 means b LEADS a.
        => peak at lag<0 means a LEADS b.
    """
    lags = np.arange(-max_lag, max_lag + 1)
    out = np.full(len(lags), np.nan)
    n = len(r_a)
    for i, L in enumerate(lags):
        if L >= 0:
            # b shifted back by L minutes: align r_a[L:] with r_b[:-L]
            if L == 0:
                xa, xb = r_a, r_b
            else:
                xa, xb = r_a[L:], r_b[:-L]
        else:
            k = -L
            xa, xb = r_a[:-k], r_b[k:]
        if len(xa) < 50:
            continue
        mask = np.isfinite(xa) & np.isfinite(xb)
        xa, xb = xa[mask], xb[mask]
        if len(xa) < 50 or xa.std() == 0 or xb.std() == 0:
            continue
        out[i] = float(np.corrcoef(xa, xb)[0, 1])
    return lags, out

rows = []
diags = []

# Pre-fetch binance once per asset
for asset in ["BTC", "ETH", "SOL"]:
    print(f"\n=== {asset} ===", flush=True)
    bb = fetch_1min(asset, "binance")
    if bb.empty:
        print(f"  binance {asset} empty — skip")
        continue
    print(f"  binance: {len(bb):,} bars", flush=True)
    for venue in ["coinbase", "kraken", "okx", "hyperliquid"]:
        oo = fetch_1min(asset, venue)
        if oo.empty:
            print(f"  {venue} {asset} empty — skip", flush=True)
            continue
        # Inner-join on ts_min
        m = bb.merge(oo, on="ts_min", suffixes=("_b", "_o"), how="inner")
        print(f"  {venue}: {len(oo):,} bars, joined {len(m):,}", flush=True)
        if len(m) < 200:
            continue
        m["r_b"] = np.log(m.price_close_b).diff()
        m["r_o"] = np.log(m.price_close_o).diff()
        m = m.dropna()
        r_b = m.r_b.values
        r_o = m.r_o.values
        lags, xc = xcorr_lag(r_b, r_o, max_lag=10)
        # max abs xcorr
        valid = np.isfinite(xc)
        if not valid.any():
            continue
        i_max = int(np.nanargmax(np.abs(xc)))
        # Find max positive correlation
        i_pos = int(np.nanargmax(xc))
        # Restrict to high-volume regime — abs(r_b) above 70th percentile
        thresh = np.nanquantile(np.abs(r_b), 0.7)
        hi_mask = np.abs(r_b) >= thresh
        r_b_hi = r_b[hi_mask]
        r_o_hi = r_o[hi_mask]
        lags_hi, xc_hi = xcorr_lag(r_b_hi, r_o_hi, max_lag=10)
        if np.isfinite(xc_hi).any():
            i_pos_hi = int(np.nanargmax(xc_hi))
            best_lag_hi = int(lags_hi[i_pos_hi])
            best_xc_hi = float(xc_hi[i_pos_hi])
        else:
            best_lag_hi, best_xc_hi = None, None

        rows.append({
            "asset": asset, "venue": venue,
            "n_bars": int(len(m)),
            "xc_lag_min10": float(xc[lags == -10][0]) if -10 in lags else None,
            "xc_lag_min5":  float(xc[lags == -5][0])  if -5 in lags else None,
            "xc_lag_min2":  float(xc[lags == -2][0])  if -2 in lags else None,
            "xc_lag_min1":  float(xc[lags == -1][0])  if -1 in lags else None,
            "xc_lag_0":     float(xc[lags == 0][0]),
            "xc_lag_pos1":  float(xc[lags == 1][0])   if 1 in lags else None,
            "xc_lag_pos2":  float(xc[lags == 2][0])   if 2 in lags else None,
            "xc_lag_pos5":  float(xc[lags == 5][0])   if 5 in lags else None,
            "best_lag_min_at_max_xc": int(lags[i_pos]),
            "best_xc": float(xc[i_pos]),
            "best_lag_min_at_max_abs": int(lags[i_max]),
            "best_abs_xc": float(xc[i_max]),
            "best_lag_hi_vol": best_lag_hi,
            "best_xc_hi_vol": best_xc_hi,
        })
        # Save full xcorr curve to diagnostics
        for L, v in zip(lags, xc):
            diags.append({"asset": asset, "venue": venue, "lag_min": int(L), "xc": float(v) if np.isfinite(v) else None})

out = pd.DataFrame(rows)
out.to_csv(OUT_DIR / "_xcorr_1min.csv", index=False)
print("\n=== RESULTS ===")
print(out.to_string(index=False))
pd.DataFrame(diags).to_csv(OUT_DIR / "_xcorr_full_curves.csv", index=False)
print(f"\nWrote {OUT_DIR / '_xcorr_1min.csv'} and full curves")
