"""
polymarket_build_features_xasset.py — generic feature builder for any asset.

Reads:
  data/polymarket/{asset}_markets_v3.csv
  data/binance/{asset}_klines_window.csv
  data/binance/{asset}_metrics_window.csv

Writes:
  data/polymarket/{asset}_features_v3.csv

Plus a merged file with an `asset` column:
  data/polymarket/all_features_v3.csv

Same 17 features as polymarket_build_features.py, just generic.
"""
from __future__ import annotations
from pathlib import Path
import sys
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent


def load_klines(path: Path) -> dict[str, pd.DataFrame]:
    k = pd.read_csv(path)
    k["ts_s"] = (k.time_period_start_us // 1_000_000).astype(int)
    return {p: k[k.period_id == p].sort_values("ts_s").reset_index(drop=True)[["ts_s","price_close","volume_traded"]].copy()
            for p in ["1MIN","5MIN","15MIN"]}


def load_metrics(path: Path) -> pd.DataFrame:
    m = pd.read_csv(path)
    m["ts_s"] = (m.create_time_us // 1_000_000).astype(int)
    return m.sort_values("ts_s").reset_index(drop=True)


def asof(df: pd.DataFrame, ts: int, col: str) -> float:
    idx = df.ts_s.searchsorted(ts, side="right") - 1
    if idx < 0:
        return float("nan")
    return float(df[col].iloc[idx])


def build_for_asset(asset: str) -> pd.DataFrame:
    markets = pd.read_csv(HERE / "data" / "polymarket" / f"{asset}_markets_v3.csv")
    markets = markets[markets.entry_yes_ask.notna() & markets.entry_no_ask.notna() & markets.outcome_up.notna()].copy()
    klines = load_klines(HERE / "data" / "binance" / f"{asset}_klines_window.csv")
    metrics = load_metrics(HERE / "data" / "binance" / f"{asset}_metrics_window.csv")

    k1m = klines["1MIN"]
    rows = []
    for _, mk in markets.iterrows():
        ws = int(mk.window_start_unix)
        c_now = asof(k1m, ws, "price_close")
        c_5m  = asof(k1m, ws - 300, "price_close")
        c_15m = asof(k1m, ws - 900, "price_close")
        c_1h  = asof(k1m, ws - 3600, "price_close")

        def lret(a, b):
            if not (np.isfinite(a) and np.isfinite(b) and b > 0): return float("nan")
            return float(np.log(a / b))

        ret_5m, ret_15m, ret_1h = lret(c_now, c_5m), lret(c_now, c_15m), lret(c_now, c_1h)

        def m(col, ts=ws): return asof(metrics, ts, col)
        oi      = m("sum_open_interest")
        oi_5m   = m("sum_open_interest", ws - 300)
        oi_15m  = m("sum_open_interest", ws - 900)
        oi_1h   = m("sum_open_interest", ws - 3600)
        oiv     = m("sum_open_interest_value")
        oiv_5m  = m("sum_open_interest_value", ws - 300)

        def pct(a, b):
            if not (np.isfinite(a) and np.isfinite(b) and b > 0): return float("nan")
            return float(a / b - 1.0)

        ls_count        = m("count_long_short_ratio")
        ls_count_5m     = m("count_long_short_ratio", ws - 300)
        ls_top_count    = m("count_toptrader_long_short_ratio")
        ls_top_sum      = m("sum_toptrader_long_short_ratio")
        taker           = m("sum_taker_long_short_vol_ratio")
        taker_5m        = m("sum_taker_long_short_vol_ratio", ws - 300)

        ya, na = mk.entry_yes_ask_size, mk.entry_no_ask_size
        book_skew = float("nan")
        if pd.notna(ya) and pd.notna(na) and (ya + na) > 0:
            book_skew = (ya - na) / (ya + na)

        rows.append({
            "asset": asset,
            "slug": mk.slug,
            "timeframe": mk.timeframe,
            "outcome_up": int(mk.outcome_up),
            "window_start_unix": ws,
            "btc_close_at_ws": c_now,
            "ret_5m": ret_5m,
            "ret_15m": ret_15m,
            "ret_1h": ret_1h,
            "oi_delta_5m":  pct(oi, oi_5m),
            "oi_delta_15m": pct(oi, oi_15m),
            "oi_delta_1h":  pct(oi, oi_1h),
            "oiv_delta_5m": pct(oiv, oiv_5m),
            "ls_count": ls_count,
            "ls_count_delta_5m": (ls_count - ls_count_5m) if (np.isfinite(ls_count) and np.isfinite(ls_count_5m)) else float("nan"),
            "ls_top_count": ls_top_count,
            "ls_top_sum": ls_top_sum,
            "smart_minus_retail": (ls_top_count - ls_count) if (np.isfinite(ls_top_count) and np.isfinite(ls_count)) else float("nan"),
            "taker_ratio": taker,
            "taker_delta_5m": (taker - taker_5m) if (np.isfinite(taker) and np.isfinite(taker_5m)) else float("nan"),
            "book_skew": book_skew,
            "entry_yes_ask": mk.entry_yes_ask,
            "entry_no_ask":  mk.entry_no_ask,
            "strike_price": mk.strike_price,
            "settlement_price": mk.settlement_price,
        })
    return pd.DataFrame(rows)


def main():
    assets = sys.argv[1:] if len(sys.argv) > 1 else ["btc", "eth", "sol"]
    all_rows = []
    for asset in assets:
        df = build_for_asset(asset)
        out = HERE / "data" / "polymarket" / f"{asset}_features_v3.csv"
        df.to_csv(out, index=False)
        all_rows.append(df)
        cov = df[["ret_5m","oi_delta_5m","ls_count","taker_ratio"]].notna().mean()
        print(f"{asset}: {len(df)} rows, ret_5m cov={cov['ret_5m']*100:.0f}%, "
              f"oi_delta_5m cov={cov['oi_delta_5m']*100:.0f}%, "
              f"ls_count cov={cov['ls_count']*100:.0f}%, "
              f"taker cov={cov['taker_ratio']*100:.0f}%")
    if len(all_rows) > 1:
        merged = pd.concat(all_rows, ignore_index=True)
        out = HERE / "data" / "polymarket" / "all_features_v3.csv"
        merged.to_csv(out, index=False)
        print(f"\nMerged {len(merged)} rows → {out}")


if __name__ == "__main__":
    main()
