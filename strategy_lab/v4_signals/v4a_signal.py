"""V4-A signal builder + IC scan.

Joins Binance funding + OI/positioning features to Polymarket UP/DOWN markets
(BTC/ETH/SOL) and computes:
  - Univariate Spearman IC of each feature vs outcome_up (sign of UP=1, DOWN=0)
  - Sign-stratified hit-rate for top/bottom decile of each feature

Features built from Binance fapi funding + Binance Vision metrics (5min granular):
  funding_rate           (latest 8h/4h funding cycle rate)
  funding_rate_chg_4h    (delta vs 4h prior funding tick)
  oi_chg_5m              (% change in sum_open_interest, last 5min)
  oi_chg_15m             (% change, last 15min)
  oi_chg_1h              (% change, last 1h)
  top_ls_ratio           (sum_toptrader_long_short_ratio, latest)
  top_ls_chg_15m         (delta in top-trader L/S ratio over 15min)
  retail_ls_ratio        (count_long_short_ratio, latest)
  smart_minus_retail_ext (top_ls - retail_ls — positioning divergence)
  taker_lvol_ratio       (sum_taker_long_short_vol_ratio, latest)
  taker_lvol_chg_15m     (delta over 15min)
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[2]
FUNDING = ROOT / "data" / "v4" / "funding"
OI      = ROOT / "data" / "v4" / "oi"
PM_DIR  = ROOT / "strategy_lab" / "data" / "polymarket"

ASSETS = ["btc", "eth", "sol"]


def load_funding(asset: str) -> pd.DataFrame:
    sym = f"{asset.upper()}USDT"
    df = pd.read_parquet(FUNDING / f"{sym}.parquet").copy()
    df = df.sort_values("fundingTime").reset_index(drop=True)
    df["fundingTime_unix"] = df["fundingTime"].astype("int64") // 10**9
    return df


def load_oi(asset: str) -> pd.DataFrame:
    sym = f"{asset.upper()}USDT"
    df = pd.read_parquet(OI / f"{sym}.parquet").copy()
    df["create_time"] = pd.to_datetime(df["create_time"], utc=True)
    df["create_time_unix"] = df["create_time"].astype("int64") // 10**9
    df = df.sort_values("create_time_unix").reset_index(drop=True)
    # forward-only safe lookup
    return df


def load_pm(asset: str) -> pd.DataFrame:
    df = pd.read_csv(PM_DIR / f"{asset}_features_v3.csv")
    df = df.dropna(subset=["outcome_up", "ret_5m", "window_start_unix"])
    df = df[df["timeframe"] == "5m"].copy()  # match V3 universe (5m only)
    return df


def asof_lookup(values: pd.Series, times: np.ndarray, query_times: np.ndarray) -> np.ndarray:
    """For each q in query_times return values at the largest time <= q (asof). NaN if none."""
    idx = np.searchsorted(times, query_times, side="right") - 1
    out = np.where(idx >= 0, values.to_numpy()[np.maximum(idx, 0)], np.nan)
    return np.where(idx >= 0, out, np.nan)


def asof_at_offset(values: pd.Series, times: np.ndarray, query_times: np.ndarray, offset_sec: int) -> np.ndarray:
    """Lookup value at (query_time - offset_sec) using asof."""
    return asof_lookup(values, times, query_times - offset_sec)


def build_features(asset: str) -> pd.DataFrame:
    pm = load_pm(asset)
    f = load_funding(asset)
    o = load_oi(asset)

    q = pm["window_start_unix"].to_numpy()  # market start time (signal cutoff)

    # Funding: asof + 4h-ago
    f_t = f["fundingTime_unix"].to_numpy()
    f_r = f["fundingRate"]
    pm["funding_rate"]        = asof_lookup(f_r, f_t, q)
    pm["funding_rate_4h_ago"] = asof_at_offset(f_r, f_t, q, 4*3600)
    pm["funding_rate_chg_4h"] = pm["funding_rate"] - pm["funding_rate_4h_ago"]

    # OI: asof + 5/15/60min ago (5min granular)
    o_t = o["create_time_unix"].to_numpy()
    pm["oi_now_ext"]      = asof_lookup(o["sum_open_interest"], o_t, q)
    pm["oi_5m_ago"]       = asof_at_offset(o["sum_open_interest"], o_t, q, 5*60)
    pm["oi_15m_ago"]      = asof_at_offset(o["sum_open_interest"], o_t, q, 15*60)
    pm["oi_1h_ago"]       = asof_at_offset(o["sum_open_interest"], o_t, q, 60*60)
    pm["oi_chg_5m"]   = (pm["oi_now_ext"] - pm["oi_5m_ago"])  / pm["oi_5m_ago"]
    pm["oi_chg_15m"]  = (pm["oi_now_ext"] - pm["oi_15m_ago"]) / pm["oi_15m_ago"]
    pm["oi_chg_1h"]   = (pm["oi_now_ext"] - pm["oi_1h_ago"])  / pm["oi_1h_ago"]

    # Top-trader L/S (smart-money proxy)
    pm["top_ls_ratio"]    = asof_lookup(o["sum_toptrader_long_short_ratio"], o_t, q)
    pm["top_ls_15m_ago"]  = asof_at_offset(o["sum_toptrader_long_short_ratio"], o_t, q, 15*60)
    pm["top_ls_chg_15m"]  = pm["top_ls_ratio"] - pm["top_ls_15m_ago"]

    # Retail L/S
    pm["retail_ls_ratio"] = asof_lookup(o["count_long_short_ratio"], o_t, q)
    pm["smart_minus_retail_ext"] = pm["top_ls_ratio"] - pm["retail_ls_ratio"]

    # Taker buy/sell vol
    pm["taker_lvol_ratio"]    = asof_lookup(o["sum_taker_long_short_vol_ratio"], o_t, q)
    pm["taker_lvol_15m_ago"]  = asof_at_offset(o["sum_taker_long_short_vol_ratio"], o_t, q, 15*60)
    pm["taker_lvol_chg_15m"]  = pm["taker_lvol_ratio"] - pm["taker_lvol_15m_ago"]

    pm["asset"] = asset
    return pm


def ic_scan(df: pd.DataFrame, features: list[str], target: str = "outcome_up") -> pd.DataFrame:
    rows = []
    for f in features:
        sub = df[[f, target]].dropna()
        if len(sub) < 30:
            rows.append({"feature": f, "n": len(sub), "ic": np.nan, "p": np.nan})
            continue
        rho, p = spearmanr(sub[f], sub[target])
        rows.append({"feature": f, "n": len(sub), "ic": rho, "p": p})
    return pd.DataFrame(rows).sort_values("ic", key=lambda s: s.abs(), ascending=False)


def decile_hit(df: pd.DataFrame, feature: str, target: str = "outcome_up") -> dict:
    sub = df[[feature, target]].dropna()
    if len(sub) < 30:
        return {}
    q10 = sub[feature].quantile(0.10)
    q90 = sub[feature].quantile(0.90)
    bot = sub[sub[feature] <= q10]
    top = sub[sub[feature] >= q90]
    return {
        "n_top": len(top), "hit_top": top[target].mean(),
        "n_bot": len(bot), "hit_bot": bot[target].mean(),
    }


def main():
    frames = []
    for a in ASSETS:
        df = build_features(a)
        frames.append(df)
        print(f"{a}: rows={len(df)} (5m only)")
    big = pd.concat(frames, ignore_index=True)
    print(f"\nCombined: rows={len(big)}, hit-rate baseline (UP frequency)={big['outcome_up'].mean():.4f}")

    features = [
        "funding_rate", "funding_rate_chg_4h",
        "oi_chg_5m", "oi_chg_15m", "oi_chg_1h",
        "top_ls_ratio", "top_ls_chg_15m",
        "retail_ls_ratio", "smart_minus_retail_ext",
        "taker_lvol_ratio", "taker_lvol_chg_15m",
    ]

    print("\n=== Univariate IC vs outcome_up (Spearman, ALL ASSETS POOLED) ===")
    ic_all = ic_scan(big, features, target="outcome_up")
    for _, r in ic_all.iterrows():
        sig = "***" if r["p"] < 0.001 else ("**" if r["p"] < 0.01 else ("*" if r["p"] < 0.05 else ""))
        print(f"  {r['feature']:<30} n={r['n']:>4d}  ic={r['ic']:+.4f}  p={r['p']:.4g} {sig}")

    print("\n=== Per-asset IC vs outcome_up ===")
    for a in ASSETS:
        sub = big[big["asset"] == a]
        ic_a = ic_scan(sub, features)
        print(f"\n  -- {a} (n={len(sub)}) --")
        for _, r in ic_a.head(6).iterrows():
            sig = "***" if r["p"] < 0.001 else ("**" if r["p"] < 0.01 else ("*" if r["p"] < 0.05 else ""))
            print(f"    {r['feature']:<28} ic={r['ic']:+.4f} p={r['p']:.4g} {sig}")

    print("\n=== Top/Bottom-decile hit rates (ALL ASSETS POOLED) ===")
    for f in features:
        d = decile_hit(big, f)
        if d:
            edge_top = d['hit_top'] - 0.5
            edge_bot = d['hit_bot'] - 0.5
            print(f"  {f:<30} top10%(n={d['n_top']:>3d}) hit={d['hit_top']:.3f}({edge_top:+.3f})  "
                  f"bot10%(n={d['n_bot']:>3d}) hit={d['hit_bot']:.3f}({edge_bot:+.3f})")


if __name__ == "__main__":
    main()
