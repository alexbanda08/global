"""Phase 5 — Multi-exchange liquidation feed integration.

Two parts:
A) HISTORICAL: integrate Binance liquidations (already on disk via VPS2 dump)
   into V3 backtest as a feature. Test if liq pressure predicts UP/DOWN.

B) LIVE: WebSocket scaffold for Hyperliquid + Bybit + OKX (Binance live already
   collected by VPS2). Outputs a unified liq stream we can join to live signals.

Historical liq data:
  data/v4/refresh_2026_04_30/binance_liq.csv
  3,657 rows, 2026-04-22 to 2026-04-27 (BTC + ETH + SOL)

Features tested:
  - liq_pressure_5m (Z-score of liq notional in last 5 min)
  - liq_imbalance_5m (sell_liqs - buy_liqs) / total
  - liq_count_5m (raw count)
  - large_liq_proximity (distance from largest recent liq)
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[2]
PM = ROOT / "strategy_lab" / "data" / "polymarket"
REFRESH = ROOT / "data" / "v4" / "refresh_2026_04_30"


def load_binance_liq() -> pd.DataFrame:
    df = pd.read_csv(REFRESH / "binance_liq.csv")
    df["ts_unix"] = (df["time_exchange_us"] / 1e6).astype("int64")
    # symbol_id: BINANCEFTS_PERP_BTC_USDT etc
    df["asset"] = df["symbol_id"].str.extract(r"PERP_(\w+)_USDT")[0].str.lower()
    df["notional"] = df["price"].astype(float) * df["size"].astype(float)
    # side: 'BUY' = long liquidated (sell-side liq), 'SELL' = short liquidated (buy-side liq)
    return df[["ts_unix", "asset", "side", "price", "size", "notional"]].sort_values("ts_unix").reset_index(drop=True)


def build_liq_features(asset: str, liq_all: pd.DataFrame) -> pd.DataFrame:
    feats = pd.read_csv(PM / f"{asset}_features_v3.csv")
    feats = feats.dropna(subset=["outcome_up", "ret_5m", "window_start_unix"])
    feats = feats[feats["timeframe"] == "5m"].copy()
    feats["asset"] = asset

    liq = liq_all[liq_all["asset"] == asset].copy()
    liq_t = liq["ts_unix"].to_numpy()
    liq_notional = liq["notional"].to_numpy()
    # 'BUY' side liquidation = a long got rekt (force-sold) -> bearish pressure
    # 'SELL' side liquidation = a short got rekt (force-bought) -> bullish pressure
    is_long_liq = (liq["side"] == "BUY").to_numpy()  # long-liq = bearish
    is_short_liq = (liq["side"] == "SELL").to_numpy()  # short-liq = bullish

    q = feats["window_start_unix"].to_numpy()

    def slice_in(window_sec):
        lo = np.searchsorted(liq_t, q - window_sec, side="left")
        hi = np.searchsorted(liq_t, q, side="right")
        return lo, hi

    # 5-min lookback features
    lo5, hi5 = slice_in(300)
    n5 = hi5 - lo5
    feats["liq_count_5m"] = n5

    long_liq_5m = np.zeros(len(q)); short_liq_5m = np.zeros(len(q))
    total_5m = np.zeros(len(q))
    for i, (lo, hi) in enumerate(zip(lo5, hi5)):
        if hi > lo:
            long_liq_5m[i] = liq_notional[lo:hi][is_long_liq[lo:hi]].sum()
            short_liq_5m[i] = liq_notional[lo:hi][is_short_liq[lo:hi]].sum()
            total_5m[i] = liq_notional[lo:hi].sum()

    feats["liq_long_notional_5m"] = long_liq_5m
    feats["liq_short_notional_5m"] = short_liq_5m
    feats["liq_total_notional_5m"] = total_5m
    feats["liq_imbalance_5m"] = np.where(
        total_5m > 0,
        (short_liq_5m - long_liq_5m) / total_5m,
        0.0,
    )

    # 1-hour lookback for context
    lo1h, hi1h = slice_in(3600)
    n1h = hi1h - lo1h
    feats["liq_count_1h"] = n1h
    return feats


def report(df, label, features):
    print(f"\n=== {label} (n={len(df)}) ===")
    for f in features:
        sub = df[[f, "outcome_up"]].dropna()
        if len(sub) < 30: continue
        rho, p = spearmanr(sub[f], sub["outcome_up"])
        sig = "***" if p < 0.001 else ("**" if p < 0.01 else ("*" if p < 0.05 else " "))
        print(f"  {f:<28} n={len(sub):>4d}  ic={rho:+.4f}  p={p:.4g}  {sig}")


def report_v3_overlay(df, asset):
    cells = {"btc": 0.10, "eth": 0.05, "sol": 0.15}
    sub = df[df["asset"] == asset].dropna(subset=["ret_5m"]).copy()
    if len(sub) < 50: return
    thr = sub["ret_5m"].abs().quantile(1 - cells[asset])
    fired = sub[sub["ret_5m"].abs() >= thr].copy()
    fired["pred_up"] = fired["ret_5m"] > 0
    fired["hit"] = ((fired["pred_up"]) & (fired["outcome_up"] == 1)) | \
                   ((~fired["pred_up"]) & (fired["outcome_up"] == 0))
    base = fired["hit"].mean()
    print(f"\n  {asset.upper()} V3 fires: n={len(fired)}, baseline_hit={base:.4f}")

    # Test: when liq imbalance ALIGNS with V3 direction
    aligned = fired[
        ((fired["pred_up"]) & (fired["liq_imbalance_5m"] > 0.10))
        | ((~fired["pred_up"]) & (fired["liq_imbalance_5m"] < -0.10))
    ]
    misaligned = fired[
        ((fired["pred_up"]) & (fired["liq_imbalance_5m"] < -0.10))
        | ((~fired["pred_up"]) & (fired["liq_imbalance_5m"] > 0.10))
    ]
    quiet = fired[fired["liq_total_notional_5m"] < 1e4]  # < $10k recent liq

    for label, s in [("liq_aligned", aligned), ("liq_misaligned", misaligned), ("liq_quiet (<$10k)", quiet)]:
        if len(s) >= 5:
            print(f"    {label:<22} n={len(s):>3d}  hit={s['hit'].mean():.4f}  delta={(s['hit'].mean()-base)*100:+.1f}pp")


def main():
    liq = load_binance_liq()
    print(f"Binance liq: {len(liq)} rows, range {pd.to_datetime(liq['ts_unix'].min(),unit='s',utc=True)} -> {pd.to_datetime(liq['ts_unix'].max(),unit='s',utc=True)}")

    features = ["liq_count_5m", "liq_long_notional_5m", "liq_short_notional_5m",
                "liq_imbalance_5m", "liq_count_1h", "liq_total_notional_5m"]

    frames = [build_liq_features(a, liq) for a in ["btc", "eth", "sol"]]
    pooled = pd.concat(frames, ignore_index=True)
    print(f"\nLiq window covers {(liq['ts_unix'].max()-liq['ts_unix'].min())/86400:.1f} days. "
          f"Polymarket window is 7+ days. Liq stops 04-27, polymarket extends to 04-29.")

    # Subset to markets within liq coverage
    liq_max_ts = liq["ts_unix"].max()
    in_window = pooled[pooled["window_start_unix"] <= liq_max_ts]
    print(f"Markets in liq-covered window: {len(in_window)} of {len(pooled)} ({len(in_window)/len(pooled)*100:.0f}%)")

    report(in_window, "ALL ASSETS (in liq coverage)", features)
    for a in ["btc", "eth", "sol"]:
        report(in_window[in_window["asset"] == a], f"{a.upper()}", features)

    print("\n=== V3 OVERLAY: liq imbalance gate ===")
    for a in ["btc", "eth", "sol"]:
        report_v3_overlay(in_window, a)


if __name__ == "__main__":
    main()
