"""TASK 1+2+3+4 — Build realized vol + Garman-Klass + Hurst panel.

Realized vol & Garman-Klass: compute on full 1s/5m/15m timeseries, save dense parquet.
Hurst: compute SPARSELY at each fire_us only (R/S is O(N log N) per window; doing
       it every second across 1.8M points × 3 windows × 3 assets is wasteful when
       we only need the value at ~150k fire timestamps).

Vol regime classifier: derive from rv_300s rolling-24h percentile.

Output:
- data/v4/canonical/_results/realized_vol_1s.parquet     (dense 1s)
- data/v4/canonical/_results/gk_vol_5m.parquet            (dense 5m)
- data/v4/canonical/_results/gk_vol_15m.parquet           (dense 15m)
- data/v4/canonical/_results/vol_hurst_at_fire_{5m,15m}.parquet (per-fire augment)
"""
from __future__ import annotations

import math
import os
import sys
import time

import numpy as np
import pandas as pd
from numba import njit, prange

sys.path.insert(0, "data/v4/canonical")
from load import load_klines  # noqa: E402

OUT_DIR = "data/v4/canonical/_results"
KLINES_1S_PATH = "data/v4/canonical/klines_1s/binance_1s_28d.parquet"

ASSETS = ("BTC", "ETH", "SOL")
SYM_MAP = {
    "BTC": "BINANCE_SPOT_BTC_USDT",
    "ETH": "BINANCE_SPOT_ETH_USDT",
    "SOL": "BINANCE_SPOT_SOL_USDT",
}

# ------------------------------------------------------------------
# Hurst (R/S method, numba-JIT)
# ------------------------------------------------------------------
@njit(cache=True, fastmath=True)
def _expected_rs(n: int) -> float:
    """Anis-Lloyd / Peters expected E[R/S] for white noise of length n."""
    if n <= 1:
        return 1.0
    s = 0.0
    nf = float(n)
    # sum_{i=1}^{n-1} sqrt((n-i)/i)
    for i in range(1, n):
        s += math.sqrt((nf - i) / i)
    # E[R/S] adjustment per Anis-Lloyd
    if n > 340:
        c = math.sqrt(nf * math.pi / 2.0)
    else:
        c = math.gamma(0.5 * (nf - 1.0)) / (math.gamma(0.5 * nf) * math.sqrt(math.pi))
    return ((nf - 0.5) / nf) * c * s


@njit(cache=True, fastmath=True)
def _rs_hurst_logprices(logp: np.ndarray) -> float:
    """Rescaled-range Hurst on a log-price series with Anis-Lloyd bias correction.
    Returns -1.0 if degenerate/too short.
    H is fit on (log(observed R/S) - log(expected R/S)) + 0.5 * log(n) vs log(n).
    """
    n = logp.shape[0]
    if n < 16:
        return -1.0
    m = n - 1
    r = np.empty(m, dtype=np.float64)
    for i in range(m):
        r[i] = logp[i + 1] - logp[i]
    all_zero = True
    for i in range(m):
        if r[i] != 0.0:
            all_zero = False
            break
    if all_zero:
        return -1.0

    sizes = (8, 16, 32, 64, 128, 256)
    xs = np.empty(6, dtype=np.float64)
    ys = np.empty(6, dtype=np.float64)
    n_pts = 0
    for si in range(6):
        sz = sizes[si]
        if sz > m // 2:
            break
        n_chunks = m // sz
        if n_chunks < 1:
            continue
        rs_sum = 0.0
        rs_cnt = 0
        for c in range(n_chunks):
            base = c * sz
            mean = 0.0
            for j in range(sz):
                mean += r[base + j]
            mean /= sz
            var = 0.0
            for j in range(sz):
                d = r[base + j] - mean
                var += d * d
            var /= sz
            if var <= 1e-24:
                continue
            std = math.sqrt(var)
            cum = 0.0
            mx = -1e18
            mn = 1e18
            for j in range(sz):
                cum += r[base + j] - mean
                if cum > mx:
                    mx = cum
                if cum < mn:
                    mn = cum
            R = mx - mn
            rs_sum += R / std
            rs_cnt += 1
        if rs_cnt == 0:
            continue
        mean_rs = rs_sum / rs_cnt
        e_rs = _expected_rs(sz)
        # corrected stat: log(observed/expected) + 0.5*log(n)
        # then slope vs log(n) ~ H
        xs[n_pts] = math.log(float(sz))
        ys[n_pts] = math.log(mean_rs) - math.log(e_rs) + 0.5 * math.log(float(sz))
        n_pts += 1
    if n_pts < 2:
        return -1.0
    mxv = 0.0
    myv = 0.0
    for i in range(n_pts):
        mxv += xs[i]
        myv += ys[i]
    mxv /= n_pts
    myv /= n_pts
    num = 0.0
    den = 0.0
    for i in range(n_pts):
        dx = xs[i] - mxv
        num += dx * (ys[i] - myv)
        den += dx * dx
    if den <= 0.0:
        return -1.0
    h = num / den
    if h < -0.05 or h > 1.5:
        return -1.0
    return h


@njit(cache=True, parallel=True, fastmath=True)
def _hurst_at_indices(logp: np.ndarray, idx_last: np.ndarray, w: int) -> np.ndarray:
    n = idx_last.shape[0]
    out = np.full(n, np.nan, dtype=np.float64)
    for i in prange(n):
        last = idx_last[i]
        if last < w - 1:
            continue
        seg = logp[last - w + 1 : last + 1]
        h = _rs_hurst_logprices(seg)
        if h >= 0.0:
            out[i] = h
    return out


# ------------------------------------------------------------------
# Step 1: realized vol on 1s closes (dense + per-fire)
# ------------------------------------------------------------------
def build_realized_vol_1s() -> pd.DataFrame:
    print("[1] loading 1s klines...", flush=True)
    df = pd.read_parquet(KLINES_1S_PATH)
    out_parts = []
    for asset in ASSETS:
        sym = SYM_MAP[asset]
        sub = df[df["symbol_id"] == sym].copy()
        sub = sub.sort_values("time_period_start_us").reset_index(drop=True)
        # Use end_us = start_us + 1e6 (1s bars). Sample at exact end.
        sub["end_us"] = sub["time_period_start_us"] + 1_000_000
        c = sub["price_close"].astype(np.float64).to_numpy()
        # log returns
        lr = np.concatenate([[np.nan], np.diff(np.log(c))])
        sub["lr"] = lr
        # rolling realized vol (stdev of 1s log-returns) over window seconds
        # Use pandas rolling
        srs = pd.Series(lr)
        for w in (60, 300, 900, 3600):
            sub[f"rv_{w}s"] = srs.rolling(w, min_periods=max(8, w // 6)).std().to_numpy()
        sub["rv_ratio_60_to_3600"] = sub["rv_60s"] / sub["rv_3600s"]

        # rolling 24h percentile of rv_300s
        win = 24 * 3600
        rv300 = sub["rv_300s"].to_numpy()
        # rolling quantiles via pandas rank percentile
        rs = pd.Series(rv300)
        sub["rv_pct_24h"] = (
            rs.rolling(win, min_periods=3 * 3600).rank(pct=True).to_numpy()
        )
        sub["vol_regime"] = pd.cut(
            sub["rv_pct_24h"],
            bins=[-0.01, 1 / 3, 2 / 3, 1.01],
            labels=[0, 1, 2],
        ).astype("Int64")  # 0=low,1=med,2=high

        sub["asset"] = asset
        cols = [
            "asset",
            "end_us",
            "rv_60s",
            "rv_300s",
            "rv_900s",
            "rv_3600s",
            "rv_ratio_60_to_3600",
            "rv_pct_24h",
            "vol_regime",
        ]
        out_parts.append(sub[cols])
    out = pd.concat(out_parts, ignore_index=True)
    return out


# ------------------------------------------------------------------
# Step 2: Garman-Klass on 5m / 15m bars
# ------------------------------------------------------------------
def garman_klass(o, h, l, c) -> np.ndarray:
    """Garman-Klass variance per bar. Returns sigma (sqrt of variance)."""
    o = np.asarray(o, dtype=np.float64)
    h = np.asarray(h, dtype=np.float64)
    l = np.asarray(l, dtype=np.float64)
    c = np.asarray(c, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        a = 0.5 * np.log(h / l) ** 2
        b = (2 * np.log(2.0) - 1.0) * np.log(c / o) ** 2
    var = a - b
    var = np.where(var < 0, 0.0, var)  # GK can be slightly negative; clip
    return np.sqrt(var)


def build_gk_panel(period_id: str) -> pd.DataFrame:
    print(f"[2] building GK panel for {period_id}...", flush=True)
    parts = []
    for asset in ASSETS:
        k = load_klines(asset, "binance-spot-ws", period_id)
        if k.empty:
            print(f"  empty for {asset} {period_id}")
            continue
        k = k.sort_values("time_period_start_us").reset_index(drop=True)
        k["gk_sigma"] = garman_klass(
            k["price_open"], k["price_high"], k["price_low"], k["price_close"]
        )
        # rolling mean over 12 bars (~1h for 5m, ~3h for 15m) as smoother
        k["gk_sigma_ma12"] = (
            pd.Series(k["gk_sigma"]).rolling(12, min_periods=3).mean().to_numpy()
        )
        k["end_us"] = k["time_period_end_us"]
        k["asset"] = asset
        parts.append(k[["asset", "end_us", "gk_sigma", "gk_sigma_ma12"]])
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)


# ------------------------------------------------------------------
# Step 3: Hurst at fire timestamps (sparse, R/S on 1s log-close lookback)
# ------------------------------------------------------------------
def compute_hurst_at_fires(
    fires: pd.DataFrame, klines_1s: pd.DataFrame, windows=(100, 300, 900)
) -> pd.DataFrame:
    """For each fire row (asset, fire_us), compute Hurst using last W seconds
    of 1s log-close ending strictly before fire_us. JIT-vectorized."""
    print(f"[3] hurst on {len(fires):,} fires...", flush=True)
    parts = []
    for asset in ASSETS:
        sym = SYM_MAP[asset]
        ks = klines_1s[klines_1s["symbol_id"] == sym].sort_values(
            "time_period_start_us"
        )
        end_us = ks["time_period_start_us"].to_numpy() + 1_000_000
        close = ks["price_close"].to_numpy(dtype=np.float64)
        logc = np.log(close)
        f_asset = fires[fires["asset"] == asset]
        if f_asset.empty:
            continue
        fire_us = f_asset["fire_us"].to_numpy()
        idx_last = np.searchsorted(end_us, fire_us, side="right") - 1
        idx_last = idx_last.astype(np.int64)
        out_dict = {"fire_us": fire_us, "asset": asset}
        t0 = time.time()
        for w in windows:
            vals = _hurst_at_indices(logc, idx_last, int(w))
            out_dict[f"hurst_{w}s"] = vals
            print(f"    {asset} hurst_{w}s done t={time.time()-t0:.1f}s", flush=True)
        df_out = pd.DataFrame(out_dict)
        df_out["slug_idx"] = f_asset.index.to_numpy()
        parts.append(df_out)
    return pd.concat(parts, ignore_index=True)


# ------------------------------------------------------------------
# Step 4: augment fire universe with vol/hurst features (per tf)
# ------------------------------------------------------------------
def augment_fire_panel(tf: str, klines_1s: pd.DataFrame, rv_dense: pd.DataFrame,
                       gk_5m: pd.DataFrame, gk_15m: pd.DataFrame) -> pd.DataFrame:
    print(f"[4] augmenting {tf} fires...", flush=True)
    fires = pd.read_parquet(f"data/v4/canonical/_results/hybrid_fire_universe_{tf}.parquet")
    print(f"  {len(fires):,} fires loaded")
    fires = fires.reset_index(drop=True)
    fires["row_id"] = fires.index

    # merge_asof requires left sorted by 'on' key (within each 'by' group).
    # Easiest: sort by fire_us globally, sort right by end_us globally.
    rv_dense_sorted = rv_dense.sort_values("end_us").reset_index(drop=True)
    fires_sorted = fires.sort_values("fire_us").reset_index(drop=True)
    merged_rv = pd.merge_asof(
        fires_sorted,
        rv_dense_sorted.rename(columns={"end_us": "rv_end_us"}),
        left_on="fire_us",
        right_on="rv_end_us",
        by="asset",
        direction="backward",
    )
    # ---- GK 5m + 15m asof ----
    gk_choice = gk_5m if tf == "5m" else gk_15m
    gk_sorted = gk_choice.sort_values("end_us").reset_index(drop=True)
    merged_gk = pd.merge_asof(
        merged_rv.sort_values("fire_us").reset_index(drop=True),
        gk_sorted.rename(columns={"end_us": "gk_end_us"}),
        left_on="fire_us",
        right_on="gk_end_us",
        by="asset",
        direction="backward",
    )

    # ---- Hurst at fires ----
    hurst = compute_hurst_at_fires(fires, klines_1s)
    # join by (fire_us, asset) — but multiple fires can share fire_us per asset, so
    # we'll attach hurst by slug_idx (original row index of fires before sort)
    hurst_by_idx = hurst.set_index("slug_idx")
    # Use row_id which equals original idx
    merged_gk = merged_gk.set_index("row_id").join(
        hurst_by_idx[["hurst_100s", "hurst_300s", "hurst_900s"]],
        how="left",
    ).reset_index()

    # Derived gates
    merged_gk["g_vol_low"] = (merged_gk["vol_regime"] == 0).astype("Int8")
    merged_gk["g_vol_med"] = (merged_gk["vol_regime"] == 1).astype("Int8")
    merged_gk["g_vol_high"] = (merged_gk["vol_regime"] == 2).astype("Int8")
    merged_gk["g_hurst_trending"] = (merged_gk["hurst_300s"] > 0.55).astype("Int8")
    merged_gk["g_hurst_reverting"] = (merged_gk["hurst_300s"] < 0.45).astype("Int8")
    merged_gk["g_vol_expanding"] = (
        merged_gk["rv_60s"] > 1.5 * merged_gk["rv_300s"]
    ).astype("Int8")
    merged_gk["g_vol_contracting"] = (
        merged_gk["rv_60s"] < 0.7 * merged_gk["rv_300s"]
    ).astype("Int8")

    # Recent 30s return sign — for g_rv_with
    # Use 1s closes: ret over [fire_us-30s, fire_us]
    print(f"  computing ret_30s for {tf}...")
    ret30 = np.full(len(merged_gk), np.nan)
    for asset in ASSETS:
        ks = klines_1s[klines_1s["symbol_id"] == SYM_MAP[asset]].sort_values(
            "time_period_start_us"
        )
        end_us = ks["time_period_start_us"].to_numpy() + 1_000_000
        close = ks["price_close"].to_numpy(dtype=np.float64)
        mask = merged_gk["asset"].to_numpy() == asset
        rows = np.where(mask)[0]
        if rows.size == 0:
            continue
        fu = merged_gk.loc[rows, "fire_us"].to_numpy()
        idx_last = np.searchsorted(end_us, fu, side="right") - 1
        idx_prev = np.searchsorted(end_us, fu - 30_000_000, side="right") - 1
        valid = (idx_last >= 0) & (idx_prev >= 0)
        v = np.full(rows.size, np.nan)
        v[valid] = (
            close[idx_last[valid]] - close[idx_prev[valid]]
        ) / close[idx_prev[valid]]
        ret30[rows] = v
    merged_gk["ret_30s"] = ret30
    merged_gk["ret_30s_sign"] = np.sign(merged_gk["ret_30s"]).astype("Int8")
    merged_gk["g_rv_with"] = (
        (merged_gk["g_vol_expanding"] == 1)
        & (merged_gk["ret_30s_sign"].abs() == 1)
    ).astype("Int8")

    return merged_gk


# ------------------------------------------------------------------
# main
# ------------------------------------------------------------------
def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()

    # Step 1
    rv = build_realized_vol_1s()
    rv_path = f"{OUT_DIR}/realized_vol_1s.parquet"
    rv.to_parquet(rv_path, index=False)
    print(f"[1] saved {rv_path} ({len(rv):,} rows) t={time.time()-t0:.1f}s")

    # Step 2
    gk_5m = build_gk_panel("5MIN")
    gk_5m.to_parquet(f"{OUT_DIR}/gk_vol_5m.parquet", index=False)
    gk_15m = build_gk_panel("15MIN")
    gk_15m.to_parquet(f"{OUT_DIR}/gk_vol_15m.parquet", index=False)
    print(f"[2] saved GK panels t={time.time()-t0:.1f}s")

    # Step 4 needs 1s klines (raw, not the RV panel)
    klines_1s = pd.read_parquet(KLINES_1S_PATH)

    # Step 4: augment fires
    aug5 = augment_fire_panel("5m", klines_1s, rv, gk_5m, gk_15m)
    aug5.to_parquet(f"{OUT_DIR}/vol_hurst_at_fire_5m.parquet", index=False)
    print(f"[4] saved 5m augment ({len(aug5):,} rows)")

    aug15 = augment_fire_panel("15m", klines_1s, rv, gk_5m, gk_15m)
    aug15.to_parquet(f"{OUT_DIR}/vol_hurst_at_fire_15m.parquet", index=False)
    print(f"[4] saved 15m augment ({len(aug15):,} rows)")

    print(f"DONE t={time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
