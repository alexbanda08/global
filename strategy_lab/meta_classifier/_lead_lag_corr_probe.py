"""Lead-lag correlation probe: BTC -> ETH/SOL.

Sample 1000 random timestamps; compute:
  btc_ret_30s, btc_ret_60s
  eth_ret_30s_fwd, sol_ret_30s_fwd, eth_ret_60s_fwd, sol_ret_60s_fwd

Returns a correlation matrix. Decides if full backtest worth running.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
KL1S = ROOT / "data" / "v4" / "canonical" / "klines_1s" / "binance_1s_28d.parquet"

SYM_MAP = {
    "BINANCE_SPOT_BTC_USDT": "BTC",
    "BINANCE_SPOT_ETH_USDT": "ETH",
    "BINANCE_SPOT_SOL_USDT": "SOL",
}


def load_per_asset() -> dict:
    df = pd.read_parquet(KL1S)
    df = df.sort_values(["symbol_id", "time_period_start_us", "source"])
    df = df.drop_duplicates(["symbol_id", "time_period_start_us"], keep="last")
    df["asset"] = df["symbol_id"].map(SYM_MAP)
    out = {}
    for asset in ("BTC", "ETH", "SOL"):
        sub = df[df.asset == asset].copy().sort_values("time_period_start_us").reset_index(drop=True)
        ts = sub.time_period_start_us.values.astype("int64")
        cl = sub.price_close.values.astype("float64")
        vol = sub.volume_traded.fillna(0).values.astype("float64")
        tbb = sub.taker_buy_base.fillna(0).values.astype("float64")
        # CVD = 2*taker_buy - vol (per-second delta)
        cvd_delta = 2.0 * tbb - vol
        out[asset] = {"ts": ts, "cl": cl, "vol": vol, "cvd": cvd_delta}
        print(f"  {asset}: {len(ts):,} rows  ts [{ts.min()} .. {ts.max()}]")
    return out


def asof_idx(ts: np.ndarray, target_us: int) -> int:
    i = int(np.searchsorted(ts, target_us, side="right")) - 1
    if i < 0 or i >= len(ts):
        return -1
    return i


def ret_bps(price_now: float, price_then: float) -> float:
    if price_now > 0 and price_then > 0:
        return 10_000.0 * np.log(price_now / price_then)
    return np.nan


def cvd_window(arr: dict, t_us: int, window_s: int) -> float:
    """Sum cvd_delta over [t-window, t)."""
    ts = arr["ts"]
    cvd = arr["cvd"]
    i_end = asof_idx(ts, t_us)
    i_start = asof_idx(ts, t_us - window_s * 1_000_000)
    if i_end < 0 or i_start < 0 or i_end <= i_start:
        return np.nan
    return float(cvd[i_start + 1 : i_end + 1].sum())


def main() -> int:
    np.random.seed(42)
    print("[1] loading 1s data...")
    arrs = load_per_asset()

    # Need common ts range
    ts_min = max(arrs[a]["ts"][0] for a in arrs)
    ts_max = min(arrs[a]["ts"][-1] for a in arrs)
    # Buffer: skip first 120s (need 60s lookback) and last 120s (need 60s forward)
    ts_min += 120 * 1_000_000
    ts_max -= 120 * 1_000_000
    print(f"  common range: {ts_min} .. {ts_max}")

    N = 1000
    rng = np.random.default_rng(42)
    sample_ts = rng.integers(ts_min, ts_max, N, dtype=np.int64)

    print(f"[2] computing features at {N} random timestamps...")
    btc = arrs["BTC"]
    rows = []
    for t in sample_ts:
        i_btc = asof_idx(btc["ts"], int(t))
        i_btc_m30 = asof_idx(btc["ts"], int(t) - 30 * 1_000_000)
        i_btc_m60 = asof_idx(btc["ts"], int(t) - 60 * 1_000_000)
        if i_btc < 0 or i_btc_m30 < 0 or i_btc_m60 < 0:
            continue
        btc_now = btc["cl"][i_btc]
        btc_30s_ret = ret_bps(btc_now, btc["cl"][i_btc_m30])
        btc_60s_ret = ret_bps(btc_now, btc["cl"][i_btc_m60])
        btc_cvd_30s = cvd_window(btc, int(t), 30)
        btc_cvd_60s = cvd_window(btc, int(t), 60)

        row = {"t_us": int(t),
               "btc_ret_30s": btc_30s_ret,
               "btc_ret_60s": btc_60s_ret,
               "btc_cvd_30s": btc_cvd_30s,
               "btc_cvd_60s": btc_cvd_60s,
               }
        for asset in ("ETH", "SOL"):
            a = arrs[asset]
            i_now = asof_idx(a["ts"], int(t))
            i_p30 = asof_idx(a["ts"], int(t) + 30 * 1_000_000)
            i_p60 = asof_idx(a["ts"], int(t) + 60 * 1_000_000)
            i_m30 = asof_idx(a["ts"], int(t) - 30 * 1_000_000)
            if i_now < 0 or i_p30 < 0 or i_p60 < 0 or i_m30 < 0:
                row[f"{asset.lower()}_ret_30s_fwd"] = np.nan
                row[f"{asset.lower()}_ret_60s_fwd"] = np.nan
                row[f"{asset.lower()}_ret_30s_back"] = np.nan
                continue
            row[f"{asset.lower()}_ret_30s_fwd"] = ret_bps(a["cl"][i_p30], a["cl"][i_now])
            row[f"{asset.lower()}_ret_60s_fwd"] = ret_bps(a["cl"][i_p60], a["cl"][i_now])
            row[f"{asset.lower()}_ret_30s_back"] = ret_bps(a["cl"][i_now], a["cl"][i_m30])
        rows.append(row)
    df = pd.DataFrame(rows).dropna()
    print(f"  valid samples: {len(df):,}")

    print("\n[3] correlation matrix:")
    cols_of_interest = [
        "btc_ret_30s", "btc_ret_60s", "btc_cvd_30s", "btc_cvd_60s",
        "eth_ret_30s_fwd", "eth_ret_60s_fwd",
        "sol_ret_30s_fwd", "sol_ret_60s_fwd",
    ]
    cm = df[cols_of_interest].corr().round(4)
    print(cm.to_string())

    # Targeted lead-lag pairs
    print("\n[4] lead-lag pairs:")
    pairs = [
        ("btc_ret_30s", "eth_ret_30s_fwd"),
        ("btc_ret_60s", "eth_ret_30s_fwd"),
        ("btc_ret_30s", "eth_ret_60s_fwd"),
        ("btc_ret_60s", "eth_ret_60s_fwd"),
        ("btc_ret_30s", "sol_ret_30s_fwd"),
        ("btc_ret_60s", "sol_ret_30s_fwd"),
        ("btc_ret_30s", "sol_ret_60s_fwd"),
        ("btc_ret_60s", "sol_ret_60s_fwd"),
        ("btc_cvd_30s", "eth_ret_30s_fwd"),
        ("btc_cvd_30s", "sol_ret_30s_fwd"),
        # Contemporaneous (sanity check — should be high)
        ("btc_ret_30s", "eth_ret_30s_back"),
        ("btc_ret_30s", "sol_ret_30s_back"),
    ]
    out_lines = []
    for a, b in pairs:
        c = df[a].corr(df[b])
        msg = f"  corr({a:18s}, {b:22s}) = {c:+.4f}"
        out_lines.append((a, b, c))
        print(msg)

    # Best lead-lag for decision
    print("\n[5] DECISION:")
    leadlag_corrs = [c for a, b, c in out_lines if "fwd" in b and "back" not in b]
    max_corr = max(abs(c) for c in leadlag_corrs)
    print(f"  max |lead-lag corr| = {max_corr:.4f}")
    if max_corr < 0.15:
        print("  CONCLUSION: NO LEAD-LAG DETECTABLE (max < 0.15). Strategy not viable.")
    else:
        print("  CONCLUSION: Lead-lag exists. Proceed with full backtest.")

    # Save
    OUT = ROOT / "data" / "v4" / "canonical" / "_results" / "_lead_lag_probe.csv"
    cm.to_csv(OUT)
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
