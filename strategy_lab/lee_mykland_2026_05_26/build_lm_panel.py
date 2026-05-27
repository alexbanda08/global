"""TASK 1 — Lee-Mykland (2008) jump panel on 1s binance closes.

Test statistic L(t) = |r(t)| / sigma_BV(t)
sigma_BV(t) = (pi/2) * sqrt((1/K) * sum_{s in window} |r(s) * r(s-1)|)

Critical value (Lee-Mykland §2.3) for n observations:
  C_n = (2 ln(n))^0.5
  S_n = 1 / (2 ln(n))^0.5
  beta_n = C_n - (ln(pi) + ln(ln(n))) * S_n / 2
  Threshold at alpha: |L| > -log(-log(1-alpha)) * S_n + C_n
    alpha=0.01 -> beta = 4.6001
    alpha=0.05 -> beta = 2.9702

Window K = 270 (4.5 minutes of 1s bars) per Lee-Mykland §3 default.

Output: data/v4/canonical/_results/lee_mykland_panel.parquet
  columns: asset, ts_us, log_ret, bv_sigma, L_stat, is_jump_01, is_jump_05,
           jump_dir_01, jump_dir_05
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
KL1S = ROOT / "data" / "v4" / "canonical" / "klines_1s" / "binance_1s_28d.parquet"
OUT = ROOT / "data" / "v4" / "canonical" / "_results" / "lee_mykland_panel.parquet"

WINDOW_K = 270  # bars used for bipower variation
BAR_S = 5       # seconds per bar — coarsen 1s to 5s to avoid zero-return microstructure
                # (LM literature uses 5min for daily; for HF intraday, 5s avoids
                #  bipower deflation from rest-bar zeros). 270 bars * 5s = 22.5min window.
SYM_MAP = {
    "BINANCE_SPOT_BTC_USDT": "BTC",
    "BINANCE_SPOT_ETH_USDT": "ETH",
    "BINANCE_SPOT_SOL_USDT": "SOL",
}

# Lee-Mykland constants
# Under H0, max_{t<=n} L(t) -> Gumbel
# Reject H0 at level alpha if max_{s in [t-K, t]} L(s) > beta_n
# where beta_n depends on alpha and number of observations n in the test set
# Per LM eq.(5): test statistic for individual bar is |r(t)|/sigma_BV.
# Reject when |L(t)| - C_n)/S_n > -log(-log(1-alpha))
#   -> equivalently |L(t)| > C_n - S_n * log(-log(1-alpha))
# alpha=0.01: -log(-log(0.99)) = 4.6001
# alpha=0.05: -log(-log(0.95)) = 2.9702


@njit(cache=True, fastmath=True)
def _bipower_window(abs_r: np.ndarray, K: int) -> np.ndarray:
    """Compute bipower variation sigma over a rolling window of K returns.

    sigma_BV(t) = sqrt(pi/2 * (1/(K-1)) * sum_{s=t-K+2}^{t-1} |r(s)| * |r(s-1)|)

    NOTE: window excludes time t to avoid contamination by the candidate jump
    being tested. Standard LM convention.

    Returns array same length as abs_r; positions < K are NaN.
    """
    n = abs_r.shape[0]
    out = np.empty(n, dtype=np.float64)
    out[:] = np.nan
    if n < K + 2:
        return out
    # rolling sum of |r(s)| * |r(s-1)| for s in [t-K+1, t-1] inclusive (K-1 terms)
    # bipower at t uses r(s) and r(s-1) for s in this window.
    # Build product series p(s) = |r(s)| * |r(s-1)| for s >= 1
    p = np.empty(n, dtype=np.float64)
    p[0] = 0.0
    for i in range(1, n):
        p[i] = abs_r[i] * abs_r[i - 1]
    # Rolling sum over [t-K+1, t-1] inclusive (K-1 terms ending one bar before t).
    # i.e. for the test bar t, the window does NOT include t itself.
    csum = np.empty(n, dtype=np.float64)
    csum[0] = p[0]
    for i in range(1, n):
        csum[i] = csum[i - 1] + p[i]
    coef = math.pi / 2.0
    K_minus = K - 1
    for t in range(K + 1, n):
        # sum from idx (t-K) inclusive to (t-1) inclusive = csum[t-1] - csum[t-K-1]
        lo = t - K  # included
        # csum[lo .. t-1] sum
        if lo - 1 >= 0:
            s = csum[t - 1] - csum[lo - 1]
        else:
            s = csum[t - 1]
        if s <= 0:
            out[t] = np.nan
        else:
            out[t] = math.sqrt(coef * s / K_minus)
    return out


def critical_value(alpha: float, n_obs: int) -> float:
    """Lee-Mykland Gumbel-tail critical value for jump rejection.

    Reject H0 at level alpha if (max L - C_n) / S_n > -log(-log(1-alpha))
    Equivalent threshold on |L|: C_n - S_n * log(-log(1-alpha))

    For practical use on per-bar testing (not max-over-sample), we directly
    use the implied threshold beta = -log(-log(1-alpha)) * S_n + C_n, which
    is the level at which the test would reject ANY of n_obs bars.
    """
    C_n = math.sqrt(2.0 * math.log(n_obs))
    S_n = 1.0 / math.sqrt(2.0 * math.log(n_obs))
    # universal LM critical at alpha: -log(-log(1-alpha))
    gumbel = -math.log(-math.log(1.0 - alpha))
    return C_n + S_n * gumbel


def process_asset(asset: str, df_sub: pd.DataFrame) -> pd.DataFrame:
    df_sub = df_sub.sort_values("time_period_start_us").drop_duplicates(
        "time_period_start_us", keep="last"
    ).reset_index(drop=True)
    ts_us = df_sub["time_period_start_us"].values.astype("int64")
    close = df_sub["price_close"].values.astype("float64")

    # Build dense per-second arrays (fill missing seconds with previous close)
    ts_s = ts_us // 1_000_000
    sec_min = int(ts_s.min())
    sec_max = int(ts_s.max())
    n_sec = sec_max - sec_min + 1
    dense_close_1s = np.full(n_sec, np.nan, dtype=np.float64)
    ix = (ts_s - sec_min).astype("int64")
    dense_close_1s[ix] = close
    # forward-fill
    last = np.nan
    for i in range(n_sec):
        if math.isfinite(dense_close_1s[i]):
            last = dense_close_1s[i]
        else:
            dense_close_1s[i] = last
    # back-fill leading NaNs (in case first second missing)
    first_valid = -1
    for i in range(n_sec):
        if math.isfinite(dense_close_1s[i]):
            first_valid = i
            break
    if first_valid > 0:
        dense_close_1s[:first_valid] = dense_close_1s[first_valid]

    # Sub-sample 1s -> BAR_S bars (take close at end of each BAR_S block).
    # Bar k spans seconds [k*BAR_S, k*BAR_S + BAR_S - 1] starting at sec_min.
    # Bar count = floor(n_sec / BAR_S).
    n = n_sec // BAR_S
    # Close of bar k = close at index (k+1)*BAR_S - 1 in 1s grid (last second of the bar).
    bar_close_idx = np.arange(1, n + 1) * BAR_S - 1
    bar_close_idx = bar_close_idx[bar_close_idx < n_sec]
    n = len(bar_close_idx)
    dense_close = dense_close_1s[bar_close_idx]

    # log returns (bar-level)
    log_close = np.log(dense_close)
    log_ret = np.empty(n, dtype=np.float64)
    log_ret[0] = 0.0
    log_ret[1:] = np.diff(log_close)
    abs_r = np.abs(log_ret)

    bv_sigma = _bipower_window(abs_r, WINDOW_K)
    with np.errstate(divide="ignore", invalid="ignore"):
        L_stat = np.where(bv_sigma > 0, abs_r / bv_sigma, np.nan)

    # n_obs = number of valid L_stat observations
    n_obs = int(np.isfinite(L_stat).sum())
    thr_01 = critical_value(0.01, n_obs)
    thr_05 = critical_value(0.05, n_obs)

    is_jump_01 = (np.isfinite(L_stat)) & (L_stat > thr_01)
    is_jump_05 = (np.isfinite(L_stat)) & (L_stat > thr_05)
    # "extreme" tier — empirically calibrated; L>10 is well into the heavy tail
    # and corresponds to ~3-sigma rare events even under heavy-tailed null.
    is_jump_extreme = (np.isfinite(L_stat)) & (L_stat > 10.0)
    jump_dir_01 = np.where(is_jump_01, np.sign(log_ret).astype("int8"), 0).astype("int8")
    jump_dir_05 = np.where(is_jump_05, np.sign(log_ret).astype("int8"), 0).astype("int8")
    jump_dir_extreme = np.where(is_jump_extreme, np.sign(log_ret).astype("int8"), 0).astype("int8")

    # ts of each bar = end-of-bar second (i.e. close timestamp)
    sec_arr = sec_min + bar_close_idx.astype("int64")
    ts_out = (sec_arr * 1_000_000).astype("int64")

    out = pd.DataFrame({
        "asset": asset,
        "ts_us": ts_out,
        "log_ret": log_ret.astype("float32"),
        "bv_sigma": bv_sigma.astype("float32"),
        "L_stat": L_stat.astype("float32"),
        "is_jump_01": is_jump_01,
        "is_jump_05": is_jump_05,
        "is_jump_extreme": is_jump_extreme,
        "jump_dir_01": jump_dir_01,
        "jump_dir_05": jump_dir_05,
        "jump_dir_extreme": jump_dir_extreme,
    })
    print(f"  {asset}: n_obs={n_obs:,}  thr01={thr_01:.3f}  thr05={thr_05:.3f}  "
          f"jumps01={int(is_jump_01.sum()):,}  jumps05={int(is_jump_05.sum()):,}  "
          f"jumps_extreme(L>10)={int(is_jump_extreme.sum()):,}")
    return out


def main() -> int:
    t0 = time.time()
    print(f"[1] loading 1s binance from {KL1S} ...")
    df = pd.read_parquet(KL1S, columns=["symbol_id", "time_period_start_us", "price_close"])
    df["asset"] = df["symbol_id"].map(SYM_MAP)
    df = df[df["asset"].isin(("BTC", "ETH", "SOL"))]
    print(f"    {len(df):,} rows in {time.time()-t0:.1f}s")

    outs = []
    for asset in ("BTC", "ETH", "SOL"):
        sub = df[df["asset"] == asset]
        if len(sub) == 0:
            continue
        outs.append(process_asset(asset, sub))

    panel = pd.concat(outs, ignore_index=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(OUT, index=False)
    print(f"[done] wrote {OUT} ({len(panel):,} rows) in {time.time()-t0:.1f}s")

    # Quick summary
    print("\n=== JUMP COUNTS ===")
    for asset in ("BTC", "ETH", "SOL"):
        sub = panel[panel["asset"] == asset]
        n_jumps_01 = int(sub["is_jump_01"].sum())
        n_jumps_05 = int(sub["is_jump_05"].sum())
        n_jumps_ex = int(sub["is_jump_extreme"].sum())
        up_01 = int((sub["jump_dir_01"] > 0).sum())
        dn_01 = int((sub["jump_dir_01"] < 0).sum())
        up_ex = int((sub["jump_dir_extreme"] > 0).sum())
        dn_ex = int((sub["jump_dir_extreme"] < 0).sum())
        print(f"  {asset}: alpha=0.01 -> {n_jumps_01:,} jumps (UP={up_01:,}, DN={dn_01:,}); "
              f"alpha=0.05 -> {n_jumps_05:,} jumps; "
              f"extreme(L>10) -> {n_jumps_ex:,} (UP={up_ex:,}, DN={dn_ex:,})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
