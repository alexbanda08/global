"""
polymarket_build_features.py — Build feature vector per BTC Up/Down market.

For each market in btc_markets_v3.csv, evaluated AT window_start (no lookahead),
compute Binance/CoinAPI features:

  Spot returns (5m, 15m, 1h) — log return of close vs N min before
  OI delta (5m, 15m, 1h)     — % change of sum_open_interest
  OI value delta (5m)        — % change of USD value (price-aware)
  L/S overall (raw + 5m delta)            — retail crowding
  L/S top trader count + sum               — smart-money positioning
  Smart-vs-retail divergence              — ls_top_count - ls_count
  Taker buy/sell ratio (raw + 5m delta)   — aggressive flow
  Polymarket book skew                    — orderbook ask-size imbalance

Inputs:
  data/polymarket/btc_markets_v3.csv      — universe + outcomes
  data/binance/btc_klines_window.csv      — 1m/5m/15m OHLCV
  data/binance/btc_metrics_window.csv     — OI + L/S + taker (5min cadence)

Output:
  data/polymarket/btc_features_v3.csv     — 1 row per slug, ~17 features
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

import os
HERE = Path(__file__).resolve().parent
ASSET = os.environ.get("ASSET", "btc").lower()
MARKETS = HERE / "data" / "polymarket" / f"{ASSET}_markets_v3.csv"
KLINES  = HERE / "data" / "binance"    / f"{ASSET}_klines_window.csv"
METRICS = HERE / "data" / "binance"    / f"{ASSET}_metrics_window.csv"
OUT     = HERE / "data" / "polymarket" / f"{ASSET}_features_v3.csv"


def load_klines() -> dict[str, pd.DataFrame]:
    k = pd.read_csv(KLINES)
    k["ts_s"] = (k.time_period_start_us // 1_000_000).astype(int)
    out = {}
    for period in ["1MIN", "5MIN", "15MIN"]:
        sub = k[k.period_id == period].sort_values("ts_s").reset_index(drop=True)
        out[period] = sub[["ts_s", "price_close", "volume_traded"]].copy()
    return out


def load_metrics() -> pd.DataFrame:
    m = pd.read_csv(METRICS)
    m["ts_s"] = (m.create_time_us // 1_000_000).astype(int)
    return m.sort_values("ts_s").reset_index(drop=True)


def asof_lookup(df: pd.DataFrame, target_ts: int, col: str) -> float:
    """Last value of `col` where ts_s <= target_ts. Returns NaN if none."""
    idx = df.ts_s.searchsorted(target_ts, side="right") - 1
    if idx < 0:
        return float("nan")
    return float(df[col].iloc[idx])


def asof_close_at_offset(df: pd.DataFrame, target_ts: int) -> float:
    return asof_lookup(df, target_ts, "price_close")


def build_features(markets: pd.DataFrame, klines: dict, metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    k1m = klines["1MIN"]
    k5m = klines["5MIN"]
    k15m = klines["15MIN"]

    for _, mk in markets.iterrows():
        ws = int(mk.window_start_unix)
        # --- spot returns at window_start ---
        c_now    = asof_close_at_offset(k1m, ws)
        c_5m     = asof_close_at_offset(k1m, ws - 300)
        c_15m    = asof_close_at_offset(k1m, ws - 900)
        c_60m    = asof_close_at_offset(k1m, ws - 3600)

        ret_5m  = float("nan") if not (np.isfinite(c_now) and np.isfinite(c_5m)  and c_5m  > 0) else np.log(c_now / c_5m)
        ret_15m = float("nan") if not (np.isfinite(c_now) and np.isfinite(c_15m) and c_15m > 0) else np.log(c_now / c_15m)
        ret_1h  = float("nan") if not (np.isfinite(c_now) and np.isfinite(c_60m) and c_60m > 0) else np.log(c_now / c_60m)

        # --- metrics at window_start (asof) ---
        def m(col, ts=ws): return asof_lookup(metrics, ts, col)
        oi_now      = m("sum_open_interest")
        oi_5m_ago   = m("sum_open_interest", ws - 300)
        oi_15m_ago  = m("sum_open_interest", ws - 900)
        oi_1h_ago   = m("sum_open_interest", ws - 3600)
        oiv_now     = m("sum_open_interest_value")
        oiv_5m_ago  = m("sum_open_interest_value", ws - 300)

        oi_delta_5m  = float("nan") if not (np.isfinite(oi_now) and np.isfinite(oi_5m_ago)  and oi_5m_ago  > 0) else (oi_now / oi_5m_ago - 1.0)
        oi_delta_15m = float("nan") if not (np.isfinite(oi_now) and np.isfinite(oi_15m_ago) and oi_15m_ago > 0) else (oi_now / oi_15m_ago - 1.0)
        oi_delta_1h  = float("nan") if not (np.isfinite(oi_now) and np.isfinite(oi_1h_ago)  and oi_1h_ago  > 0) else (oi_now / oi_1h_ago - 1.0)
        oiv_delta_5m = float("nan") if not (np.isfinite(oiv_now) and np.isfinite(oiv_5m_ago) and oiv_5m_ago > 0) else (oiv_now / oiv_5m_ago - 1.0)

        ls_count        = m("count_long_short_ratio")
        ls_count_5m_ago = m("count_long_short_ratio", ws - 300)
        ls_count_delta_5m = ls_count - ls_count_5m_ago if (np.isfinite(ls_count) and np.isfinite(ls_count_5m_ago)) else float("nan")

        ls_top_count = m("count_toptrader_long_short_ratio")
        ls_top_sum   = m("sum_toptrader_long_short_ratio")
        smart_minus_retail = (ls_top_count - ls_count) if (np.isfinite(ls_top_count) and np.isfinite(ls_count)) else float("nan")

        taker        = m("sum_taker_long_short_vol_ratio")
        taker_5m_ago = m("sum_taker_long_short_vol_ratio", ws - 300)
        taker_delta_5m = taker - taker_5m_ago if (np.isfinite(taker) and np.isfinite(taker_5m_ago)) else float("nan")

        # --- Polymarket book skew at window_start (already in market row) ---
        ya, na = mk.entry_yes_ask_size, mk.entry_no_ask_size
        book_skew = float("nan")
        if pd.notna(ya) and pd.notna(na) and (ya + na) > 0:
            book_skew = (ya - na) / (ya + na)

        # --- assemble ---
        rows.append({
            "asset": ASSET,
            "slug": mk.slug,
            "timeframe": mk.timeframe,
            "window_start_unix": ws,
            "outcome_up": int(mk.outcome_up),
            "strike_price": mk.strike_price,
            "settlement_price": mk.settlement_price,
            "abs_move_pct": mk.abs_move_pct,
            "btc_close_at_ws": c_now,
            "ret_5m": ret_5m,
            "ret_15m": ret_15m,
            "ret_1h": ret_1h,
            "oi_now": oi_now,
            "oi_delta_5m": oi_delta_5m,
            "oi_delta_15m": oi_delta_15m,
            "oi_delta_1h": oi_delta_1h,
            "oiv_delta_5m": oiv_delta_5m,
            "ls_count": ls_count,
            "ls_count_delta_5m": ls_count_delta_5m,
            "ls_top_count": ls_top_count,
            "ls_top_sum": ls_top_sum,
            "smart_minus_retail": smart_minus_retail,
            "taker_ratio": taker,
            "taker_delta_5m": taker_delta_5m,
            "book_skew": book_skew,
            "entry_yes_ask": mk.entry_yes_ask,
            "entry_no_ask":  mk.entry_no_ask,
        })

    return pd.DataFrame(rows)


def main():
    markets = pd.read_csv(MARKETS)
    markets = markets[markets.entry_yes_ask.notna() & markets.entry_no_ask.notna() & markets.outcome_up.notna()].copy()
    klines = load_klines()
    metrics = load_metrics()
    feats = build_features(markets, klines, metrics)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    feats.to_csv(OUT, index=False)

    # Coverage report
    n = len(feats)
    print(f"Built {n} feature rows.")
    cov = feats.notna().mean().sort_values()
    print("\nNaN-free coverage per feature:")
    for col, v in cov.items():
        if v < 1.0:
            print(f"  {col:30s}: {v*100:5.1f}%  ({int(v*n)}/{n})")
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
