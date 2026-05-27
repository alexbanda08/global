"""TASK 1 — Avellaneda-Stoikov uncertainty panel.

For each fire (5m + 15m):
  - sigma = rv_300s (already in vol_hurst_at_fire panels, simple-mean Wilder
            realized vol over last 300s of 1s binance log-returns)
  - time_to_slot_end_s = (slot_end_us - fire_us) / 1e6
  - as_uncertainty = sigma^2 * time_to_slot_end_s
  - as_uncertainty_norm = as_uncertainty / mean(as_uncertainty in last 24h)
  - as_reservation_price_skew = (close - vwap_slot) * gamma * sigma^2 * tte
    where gamma = risk aversion (default 1.0 = neutral; we keep simple),
          close = binance close at fire_us, vwap = slot VWAP up-to fire.

Causal: all features at fire_us use bars whose END_US <= fire_us.

Output: data/v4/canonical/_results/as_panel.parquet
  cols: asset, tf, slug, fire_us, slot_end_us, sigma_300s, tte_s,
        as_uncertainty, as_uncertainty_norm_24h, as_uncertainty_pct_24h,
        as_skew, close_fire, vwap_slot, outcome, won_up, won_dn,
        up_vwap, dn_vwap, dn_pnl_legacy_up, dn_pnl_legacy_dn
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
import pandas as pd

ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
sys.path.insert(0, os.path.join(ROOT, "data", "v4", "canonical"))

OUT_DIR = os.path.join(ROOT, "data", "v4", "canonical", "_results")
KLINES_1S_PATH = os.path.join(ROOT, "data", "v4", "canonical", "klines_1s", "binance_1s_28d.parquet")

ASSETS = ("BTC", "ETH", "SOL")
SYM_MAP = {
    "BTC": "BINANCE_SPOT_BTC_USDT",
    "ETH": "BINANCE_SPOT_ETH_USDT",
    "SOL": "BINANCE_SPOT_SOL_USDT",
}


def legacy_pnl(direction_vwap: float, won: bool, notional: float = 25.0) -> float:
    """Legacy 2%-on-profit fee. Loss = -notional (full). Win = notional*(1-vwap)/vwap * 0.98."""
    if not np.isfinite(direction_vwap) or direction_vwap <= 0:
        return np.nan
    if won:
        shares = notional / direction_vwap
        gross = shares * (1.0 - direction_vwap)  # binary pays $1 per share
        return gross * 0.98
    return -notional


def build_for_tf(tf: str, klines_1s: pd.DataFrame) -> pd.DataFrame:
    print(f"[AS] tf={tf} loading fire universe...", flush=True)
    vh_path = os.path.join(OUT_DIR, f"vol_hurst_at_fire_{tf}.parquet")
    vh = pd.read_parquet(vh_path)
    print(f"  loaded {len(vh):,} rows", flush=True)

    # rv_300s is sigma per sec (stdev of 1s log returns). Need sigma in returns/sec; rv_300s already is that.
    sigma = vh["rv_300s"].astype(np.float64).to_numpy()
    tte_s = (vh["slot_end_us"].astype(np.int64).to_numpy() - vh["fire_us"].astype(np.int64).to_numpy()) / 1_000_000.0
    tte_s = np.clip(tte_s, 0.0, 24 * 3600.0)

    as_uncert = sigma * sigma * tte_s
    # Asset-specific close at fire_us + slot VWAP (1s close avg from slot_start->fire_us)
    print("  fetching close/VWAP per asset...", flush=True)
    close_fire = np.full(len(vh), np.nan)
    vwap_slot = np.full(len(vh), np.nan)

    fire_us_arr = vh["fire_us"].astype(np.int64).to_numpy()
    slot_start_us_arr = vh["slot_start_us"].astype(np.int64).to_numpy()

    for asset in ASSETS:
        mask = (vh["asset"].to_numpy() == asset)
        if not mask.any():
            continue
        rows = np.where(mask)[0]
        ks = klines_1s[klines_1s["symbol_id"] == SYM_MAP[asset]].sort_values("time_period_start_us")
        end_us = ks["time_period_start_us"].to_numpy() + 1_000_000  # 1s bar ends 1s after start
        close = ks["price_close"].to_numpy(dtype=np.float64)

        # close at fire (last bar ending <= fire_us)
        fu = fire_us_arr[rows]
        idx_last = np.searchsorted(end_us, fu, side="right") - 1
        valid = idx_last >= 0
        cv = np.full(rows.size, np.nan)
        cv[valid] = close[idx_last[valid]]
        close_fire[rows] = cv

        # vwap from slot_start to fire_us (mean close over slot bars before fire)
        ss = slot_start_us_arr[rows]
        # slot_start in seconds, fire in us. Use closes for bars with end_us in (slot_start, fire_us].
        idx_start = np.searchsorted(end_us, ss, side="left")
        idx_end = np.searchsorted(end_us, fu, side="right")
        # Manual loop is acceptable because ~190k fires only.
        vw = np.full(rows.size, np.nan)
        for j in range(rows.size):
            a = idx_start[j]
            b = idx_end[j]
            if b > a:
                vw[j] = close[a:b].mean()
        vwap_slot[rows] = vw

    # Reservation-price skew = (close - vwap) * gamma * sigma^2 * tte
    gamma = 1.0
    skew = (close_fire - vwap_slot) * gamma * sigma * sigma * tte_s

    # Normalize as_uncertainty by rolling 24h mean per asset
    print("  computing rolling 24h mean of as_uncertainty per asset...", flush=True)
    norm = np.full(len(vh), np.nan)
    pct = np.full(len(vh), np.nan)
    out = vh[["asset", "tf", "slug", "fire_us", "slot_end_us", "outcome",
              "up_vwap", "dn_vwap", "up_fill_ok", "dn_fill_ok"]].copy()
    out["sigma_300s"] = sigma
    out["tte_s"] = tte_s
    out["as_uncertainty"] = as_uncert
    out["close_fire"] = close_fire
    out["vwap_slot"] = vwap_slot
    out["as_skew"] = skew

    for asset in ASSETS:
        m = out["asset"].to_numpy() == asset
        rows = np.where(m)[0]
        if rows.size == 0:
            continue
        sub = out.iloc[rows].sort_values("fire_us").copy()
        sub_idx = sub.index.to_numpy()
        fu = sub["fire_us"].to_numpy()
        au = sub["as_uncertainty"].to_numpy()
        # rolling 24h = 86_400_000_000 us window over fires (event-time)
        win_us = 86_400_000_000
        # use deque-based rolling: but we have ~63k fires per asset, simple two-pointer over sorted timestamps.
        n = len(sub)
        left = 0
        running_sum = 0.0
        running_cnt = 0
        rolling_means = np.full(n, np.nan)
        rolling_pcts = np.full(n, np.nan)
        # Build window iteratively
        for i in range(n):
            # Advance left while fu[left] < fu[i] - win_us
            while left < i and fu[left] < fu[i] - win_us:
                if np.isfinite(au[left]):
                    running_sum -= au[left]
                    running_cnt -= 1
                left += 1
            # Add new au[i] AFTER computing mean (we want past-only for causality, exclude current)
            # Mean of window [left, i-1] inclusive (past).
            if running_cnt >= 30:  # need at least 30 recent fires
                rolling_means[i] = running_sum / running_cnt
            # add current
            if np.isfinite(au[i]):
                running_sum += au[i]
                running_cnt += 1
        # Percentile: for each i, what fraction of past au's are <= current au?
        # That's expensive in pure python; approximate via sorted-window quantile is overkill.
        # Use forward-rolling rank instead via pandas:
        srs = pd.Series(au, index=range(n))
        # Use rolling-rank over a count-based window of ~ avg fires per day.
        # 63k fires / 32 d ~ 2000/d → window of last 1500 fires ~ proxy for "last 24h"
        rank_pct = srs.rolling(2000, min_periods=200).rank(pct=True).to_numpy()
        rolling_pcts[:] = rank_pct

        norm_vals = np.full(n, np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            ok = np.isfinite(rolling_means) & (rolling_means > 0)
            norm_vals[ok] = au[ok] / rolling_means[ok]

        # write back to out using sub_idx
        norm[sub_idx] = norm_vals
        pct[sub_idx] = rolling_pcts

    out["as_uncertainty_norm_24h"] = norm
    out["as_uncertainty_pct_24h"] = pct

    # Add legacy PnL per direction
    won_up = (out["outcome"] == "Up").to_numpy()
    won_dn = (out["outcome"] == "Down").to_numpy()
    pnl_up = np.array([legacy_pnl(v, w) for v, w in zip(out["up_vwap"].to_numpy(), won_up)])
    pnl_dn = np.array([legacy_pnl(v, w) for v, w in zip(out["dn_vwap"].to_numpy(), won_dn)])
    out["pnl_legacy_up"] = pnl_up
    out["pnl_legacy_dn"] = pnl_dn
    out["won_up"] = won_up.astype(np.int8)
    out["won_dn"] = won_dn.astype(np.int8)
    return out


def main() -> None:
    t0 = time.time()
    print("[AS] loading 1s klines...", flush=True)
    klines_1s = pd.read_parquet(KLINES_1S_PATH)
    print(f"  loaded {len(klines_1s):,} bars t={time.time()-t0:.1f}s")

    parts = []
    for tf in ("5m", "15m"):
        p = build_for_tf(tf, klines_1s)
        parts.append(p)
        print(f"[AS] tf={tf} built {len(p):,} rows t={time.time()-t0:.1f}s")

    full = pd.concat(parts, ignore_index=True)
    out_path = os.path.join(OUT_DIR, "as_panel.parquet")
    full.to_parquet(out_path, index=False)
    print(f"[AS] saved {out_path} ({len(full):,} rows, {full.shape[1]} cols) t={time.time()-t0:.1f}s")

    # Quick summary stats
    print("\n--- AS panel quick stats ---")
    for tf in ("5m", "15m"):
        sub = full[full["tf"] == tf]
        valid = sub["as_uncertainty"].dropna()
        print(f"  {tf}: n={len(sub):,} valid_au={len(valid):,} "
              f"au_p50={valid.median():.3e} au_norm_p50={sub['as_uncertainty_norm_24h'].median():.3f}")


if __name__ == "__main__":
    main()
