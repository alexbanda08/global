"""TASK 2 — Hayashi-Yoshida (2005) cross-correlation for irregularly-sampled prices.

Estimator:
    HY(X, Y) = sum_i sum_j Δlog X_i * Δlog Y_j * 1[overlap(I_i, J_j) > 0]
where I_i = (t_{i-1}, t_i] are inter-observation intervals on X, J_j similar for Y.

Normalize: HY_corr = HY(X, Y) / sqrt(HY(X, X) * HY(Y, Y))

Apply: BTC binance 1S vs coinbase 1MIN; compute over rolling 7-day windows.
Compare lag profile vs Agent P's bucketed xcorr findings (peak lag 0 at 1min).

Implementation:
  - Treat binance 1s closes as price observations at end_us = start+1s
  - Treat coinbase 1m closes as price observations at end_us = start+60s
  - For each lag L in [-60, -10, -5, -1, 0, 1, 5, 10, 60] seconds, shift coinbase
    timestamps by L and compute HY(binance, coinbase_shifted)
  - This is asymmetric in granularity — HY handles that natively.

For computational tractability:
  - Use the chunked formulation: for each Y interval J_j, sum over all X intervals
    I_i with overlap(I_i, J_j) > 0. Since X is dense (1s) and Y is sparse (60s),
    each Y interval J_j contains ~60 X intervals → O(N_Y * 60) which is ~22k * 60 = 1.3M ops.
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
import pandas as pd

ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
sys.path.insert(0, os.path.join(ROOT, "data", "v4", "canonical"))
from load import load_klines  # noqa: E402

OUT_DIR = os.path.join(ROOT, "strategy_lab", "avell_hayashi_2026_05_26")
KLINES_1S_PATH = os.path.join(ROOT, "data", "v4", "canonical", "klines_1s", "binance_1s_28d.parquet")

ASSETS = ("BTC", "ETH", "SOL")
SYM_MAP = {
    "BTC": "BINANCE_SPOT_BTC_USDT",
    "ETH": "BINANCE_SPOT_ETH_USDT",
    "SOL": "BINANCE_SPOT_SOL_USDT",
}

# Apply same window constraint as Agent P (cross-venue alt data ends May 16)
WIN_START_US = int(pd.Timestamp("2026-05-07 13:00", tz="UTC").value // 1000)
WIN_END_US = int(pd.Timestamp("2026-05-16 06:00", tz="UTC").value // 1000)


def hy_estimator(
    t_x_start_us: np.ndarray,  # interval start (us)
    t_x_end_us: np.ndarray,    # interval end (us)
    dx: np.ndarray,            # log returns on X
    t_y_start_us: np.ndarray,
    t_y_end_us: np.ndarray,
    dy: np.ndarray,
) -> float:
    """Compute HY(X, Y) cross-product sum.

    For each Y interval j, find X intervals i with overlap:
       overlap = max(0, min(t_x_end_us[i], t_y_end_us[j]) - max(t_x_start_us[i], t_y_start_us[j]))
       count if overlap > 0.
    We use binary search on X intervals because X is dense and sorted.
    """
    if len(dx) == 0 or len(dy) == 0:
        return 0.0
    # For each Y interval [a, b], find all X intervals where x_end > a AND x_start < b.
    # x_start < b → bsearch_right(t_x_start_us, b) gives idx upper bound (exclusive)
    # x_end > a → bsearch_right(t_x_end_us, a) gives idx lower bound
    total = 0.0
    for j in range(len(dy)):
        a = t_y_start_us[j]
        b = t_y_end_us[j]
        if not np.isfinite(dy[j]):
            continue
        lo = np.searchsorted(t_x_end_us, a, side="right")
        hi = np.searchsorted(t_x_start_us, b, side="left")
        # Use [lo, hi) — both conditions covered (X intervals strictly intersect Y interval)
        if hi <= lo:
            continue
        # Sum dx[lo:hi] - they all overlap with Y interval j
        sub = dx[lo:hi]
        s = sub[np.isfinite(sub)].sum()
        total += s * dy[j]
    return float(total)


def hy_self(
    t_start_us: np.ndarray,
    t_end_us: np.ndarray,
    d: np.ndarray,
) -> float:
    """HY(X,X) = sum_i d_i^2 (since each interval overlaps only with itself)."""
    finite = np.isfinite(d)
    return float((d[finite] ** 2).sum())


def hy_aggregate_x_into_y(
    t_x_start_us: np.ndarray,
    t_x_end_us: np.ndarray,
    dx: np.ndarray,
    t_y_start_us: np.ndarray,
    t_y_end_us: np.ndarray,
) -> np.ndarray:
    """Aggregate X log-returns into each Y interval (sum dx_i for I_i overlapping J_j).
    Returns array of aggregated X returns per Y interval (same shape as Y).
    """
    out = np.zeros(len(t_y_start_us), dtype=np.float64)
    for j in range(len(t_y_start_us)):
        a = t_y_start_us[j]; b = t_y_end_us[j]
        lo = np.searchsorted(t_x_end_us, a, side="right")
        hi = np.searchsorted(t_x_start_us, b, side="left")
        if hi <= lo:
            out[j] = np.nan; continue
        sub = dx[lo:hi]
        out[j] = sub[np.isfinite(sub)].sum() if np.isfinite(sub).any() else np.nan
    return out


def hy_corr_at_lag(
    binance: pd.DataFrame,
    cb: pd.DataFrame,
    lag_s: int,
) -> tuple[float, int, int]:
    """Compute HY correlation: shift cb by +lag seconds. lag>0 = cb shifted FORWARD
    in time → its past matches binance's present → if peak at lag>0: cb LEADS binance.
    """
    shift_us = int(lag_s * 1_000_000)
    cb_s_start = cb["start_us"].to_numpy() + shift_us
    cb_s_end = cb["end_us"].to_numpy() + shift_us
    cb_dy = cb["lr"].to_numpy()

    # restrict to common window after shift
    lo = max(binance["start_us"].min(), cb_s_start.min())
    hi = min(binance["end_us"].max(), cb_s_end.max())
    bmask = (binance["start_us"].to_numpy() >= lo) & (binance["end_us"].to_numpy() <= hi)
    cmask = (cb_s_start >= lo) & (cb_s_end <= hi)
    bx_start = binance["start_us"].to_numpy()[bmask]
    bx_end = binance["end_us"].to_numpy()[bmask]
    bx_dx = binance["lr"].to_numpy()[bmask]
    cy_start = cb_s_start[cmask]
    cy_end = cb_s_end[cmask]
    cy_dy = cb_dy[cmask]

    if len(bx_dx) < 100 or len(cy_dy) < 10:
        return np.nan, len(bx_dx), len(cy_dy)

    # Proper HY normalization for the SAME overlap set:
    # First, aggregate X log-returns into Y intervals (sum dx_i for X intervals overlapping Y_j).
    # Then use those aggregated values for HXX(grid-Y) — this gives a Pearson correlation
    # of dy_j vs (aggregated dx into J_j). With this normalization HY corr is bounded [-1, 1].
    agg_dx_in_y = hy_aggregate_x_into_y(bx_start, bx_end, bx_dx, cy_start, cy_end)
    mask = np.isfinite(agg_dx_in_y) & np.isfinite(cy_dy)
    if mask.sum() < 10:
        return np.nan, len(bx_dx), len(cy_dy)
    a = agg_dx_in_y[mask]
    b = cy_dy[mask]
    sa = a.std(); sb = b.std()
    if sa <= 0 or sb <= 0:
        return np.nan, len(bx_dx), len(cy_dy)
    corr = float(np.corrcoef(a, b)[0, 1])
    return corr, len(bx_dx), len(cy_dy)


def main() -> None:
    t0 = time.time()
    print("[HY] loading binance 1s klines...", flush=True)
    klines_1s = pd.read_parquet(KLINES_1S_PATH)
    # filter to common analysis window
    klines_1s = klines_1s[
        (klines_1s["time_period_start_us"] >= WIN_START_US)
        & (klines_1s["time_period_start_us"] <= WIN_END_US)
    ].copy()
    print(f"  {len(klines_1s):,} rows after window filter t={time.time()-t0:.1f}s")

    results = []

    for asset in ASSETS:
        print(f"\n=== {asset} ===", flush=True)
        sym = SYM_MAP[asset]
        bin_df = klines_1s[klines_1s["symbol_id"] == sym].sort_values("time_period_start_us").copy()
        bin_df = bin_df.reset_index(drop=True)
        if bin_df.empty:
            print(f"  no binance 1s {asset}, skip"); continue
        bin_df["start_us"] = bin_df["time_period_start_us"].astype(np.int64)
        bin_df["end_us"] = bin_df["start_us"] + 1_000_000
        bin_df["lr"] = np.concatenate([[np.nan], np.diff(np.log(bin_df["price_close"].astype(np.float64).to_numpy()))])

        print(f"  binance: {len(bin_df):,} 1s bars", flush=True)

        for venue in ("coinbase", "kraken", "okx"):
            print(f"  --- {venue} ---", flush=True)
            src_key = {
                "coinbase": "coinbase-spot-ws",
                "kraken": "kraken-spot-ws",
                "okx": "okx-spot-ws",
            }[venue]
            try:
                if venue == "okx":
                    from load import load_okx_klines
                    v = load_okx_klines(asset=asset, period_id="1MIN")
                else:
                    v = load_klines(asset, source=src_key, period_id="1MIN")
            except Exception as e:
                print(f"    {venue}: load failed {e}"); continue
            if v.empty:
                print(f"    {venue}: empty"); continue
            v = v[
                (v["time_period_start_us"] >= WIN_START_US)
                & (v["time_period_start_us"] <= WIN_END_US)
            ].copy()
            v = v.sort_values("time_period_start_us").drop_duplicates("time_period_start_us").reset_index(drop=True)
            if len(v) < 100:
                print(f"    {venue}: too few bars {len(v)}"); continue
            v["start_us"] = v["time_period_start_us"].astype(np.int64)
            v["end_us"] = v["start_us"] + 60_000_000
            v["lr"] = np.concatenate([[np.nan], np.diff(np.log(v["price_close"].astype(np.float64).to_numpy()))])
            print(f"    {venue}: {len(v):,} 1m bars", flush=True)

            lags_s = [-120, -60, -30, -10, -5, -1, 0, 1, 5, 10, 30, 60, 120]
            for lag in lags_s:
                t1 = time.time()
                corr, n_bin, n_v = hy_corr_at_lag(bin_df, v, lag)
                results.append({
                    "asset": asset,
                    "venue": venue,
                    "lag_s": lag,
                    "hy_corr": corr,
                    "n_bin_intervals": n_bin,
                    "n_venue_intervals": n_v,
                })
                print(f"    lag={lag:>+4}s hy={corr:+.4f}  ({time.time()-t1:.1f}s)", flush=True)

    res = pd.DataFrame(results)
    out_csv = os.path.join(OUT_DIR, "hy_xcorr_results.csv")
    res.to_csv(out_csv, index=False)
    print(f"\n[HY] saved {out_csv} ({len(res)} rows) t={time.time()-t0:.1f}s")

    # Peak lag per (asset, venue)
    print("\n--- Peak lag per asset/venue ---")
    for (asset, venue), grp in res.groupby(["asset", "venue"]):
        if grp["hy_corr"].isna().all():
            continue
        peak = grp.loc[grp["hy_corr"].idxmax()]
        print(f"  {asset} vs {venue}: peak hy={peak['hy_corr']:+.4f} at lag={peak['lag_s']:+}s")


if __name__ == "__main__":
    main()
