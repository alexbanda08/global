"""Build a fire universe + feature panel extension for May 22-25 (the "lockbox").

Reuses the v15m_joined_all schema but extends to May 22 00:00 - May 25 23:59 UTC.
Outputs:
  data/v4/canonical/_results/hybrid_fire_universe_15m_lockbox.parquet
  data/v4/canonical/_results/v15m_joined_all_lockbox.parquet (with direction/PnL/g_ gates)
  data/v4/canonical/_results/sleeve_hunt_15m_full_features.parquet (concat: R2 + lockbox, full 32d)
"""
from __future__ import annotations

import gc
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

from load import (  # noqa: E402
    load_resolutions, load_klines_asof, load_klines_1s,
    load_orderbook_l25_streaming,
)
from engine_v2 import LegacyConfig, fill_at_book  # noqa: E402

OUT_DIR = ROOT / "data" / "v4" / "canonical" / "_results"
ASSETS = ("BTC", "ETH", "SOL")
OFFSETS_15M = (60, 120, 240, 360, 480, 600, 720, 840)
SPREAD_FILTER = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}
WINDOW_S = 900
NOTIONAL = 25.0
Q90_PATH = OUT_DIR / "prod_q90_calibration" / "hourly_thresholds.parquet"

# Lockbox window: May 22 00:00 UTC -> May 25 23:59 UTC (4 days)
LOCKBOX_START_US = int(pd.Timestamp("2026-05-22T00:00:00Z").value // 1000)
LOCKBOX_END_US = int(pd.Timestamp("2026-05-25T23:59:00Z").value // 1000)


def _asof_strict(end_us: np.ndarray, prices: np.ndarray, target_us: int) -> float:
    pos = int(np.searchsorted(end_us, int(target_us), side="right")) - 1
    if pos < 0:
        return float("nan")
    return float(prices[pos])


def _build_q90_lookup() -> dict:
    out: dict = {}
    if not Q90_PATH.exists():
        return out
    df = pd.read_parquet(Q90_PATH)
    for asset, sub in df.groupby("asset"):
        s = sub.sort_values("anchor_us")
        out[asset] = (s.anchor_us.values.astype("int64"),
                       s.prod_q90.values.astype("float64"))
    return out


def _q90_at(q90_idx: dict, asset: str, ws_us: int) -> float:
    rec = q90_idx.get(asset)
    if rec is None:
        return float("nan")
    anchors, q = rec
    pos = int(np.searchsorted(anchors, int(ws_us), side="right")) - 1
    if pos < 0:
        return float("nan")
    return float(q[pos])


def _vwap_since_slot_open(
    ts_us: np.ndarray, close: np.ndarray,
    slot_start_us: int, fire_us: int,
) -> float:
    lo = int(np.searchsorted(ts_us, slot_start_us, side="left"))
    hi = int(np.searchsorted(ts_us, fire_us, side="right"))
    if hi - lo < 2:
        return float("nan")
    seg = close[lo:hi]
    seg = seg[np.isfinite(seg)]
    if seg.size < 2:
        return float("nan")
    mean_p = float(seg.mean())
    last_p = float(seg[-1])
    if mean_p <= 0:
        return float("nan")
    return (last_p - mean_p) / mean_p * 10000.0


def _ret_2m_at_ws(end_us_1m: np.ndarray, close_1m: np.ndarray, ws_s: int) -> float:
    t0 = int(ws_s) * 1_000_000
    t1 = (int(ws_s) + 120) * 1_000_000
    c0 = _asof_strict(end_us_1m, close_1m, t0)
    c1 = _asof_strict(end_us_1m, close_1m, t1)
    if not (c0 > 0 and c1 > 0):
        return float("nan")
    return math.log(c1 / c0)


def build_lockbox_universe(klines_1m: dict, klines_1s_idx: dict, q90_idx: dict) -> pd.DataFrame:
    print(f"\n=== building 15m LOCKBOX (May 22-25) ===")
    res = load_resolutions(assets=list(ASSETS), timeframes=["15m"])
    res = res[res["outcome"].isin(("Up", "Down"))].copy()
    res = res[(res["slot_start_us"] >= LOCKBOX_START_US) &
              (res["slot_start_us"] <= LOCKBOX_END_US)].copy()
    res["ws_s"] = (res["slot_start_us"] // 1_000_000) - WINDOW_S
    res["window_s"] = WINDOW_S
    print(f"  resolutions: {len(res):,}")
    print(f"  per asset: {res.groupby('ticker').size().to_dict()}")

    cfg = LegacyConfig()
    out_rows: list = []

    for asset in ASSETS:
        rsub = res[res["ticker"] == asset].copy()
        if rsub.empty:
            continue
        slugs_set = set(rsub["slug"].tolist())
        print(f"  [{asset}] {len(rsub):,} slugs; streaming L25...")
        t0 = time.time()
        min_us = int(rsub["slot_start_us"].min()) - 3600 * 1_000_000
        max_us = int(rsub["slot_end_us"].max()) + 3600 * 1_000_000
        books = load_orderbook_l25_streaming(
            asset.lower(), slugs=slugs_set, subsample_1hz=True,
            min_ts_us=min_us, max_ts_us=max_us,
        )
        print(f"    L25 in {time.time()-t0:.1f}s -> {len(books)} (slug,outcome), "
              f"{sum(len(v[0]) for v in books.values()):,} snaps")

        end_us_1m, close_1m = klines_1m[asset]
        ts_1s_us, close_1s = klines_1s_idx[asset]
        spread = SPREAD_FILTER[asset]

        for r in rsub.itertuples(index=False):
            slug = r.slug
            slot_start_us = int(r.slot_start_us)
            slot_end_us = int(r.slot_end_us)
            ws_s = int(r.ws_s)
            outcome = str(r.outcome)
            strike_price = _asof_strict(end_us_1m, close_1m, slot_start_us)
            settle_price = _asof_strict(end_us_1m, close_1m, slot_end_us)
            r2m = _ret_2m_at_ws(end_us_1m, close_1m, ws_s)
            q90 = _q90_at(q90_idx, asset, ws_s * 1_000_000)
            mag_ratio = (abs(r2m) / q90) if (math.isfinite(r2m) and math.isfinite(q90) and q90 > 0) else float("nan")

            for off in OFFSETS_15M:
                fire_us = slot_start_us + off * 1_000_000
                vwap_bps = _vwap_since_slot_open(ts_1s_us, close_1s, slot_start_us, fire_us)
                up_fill = fill_at_book(books, slug, "Up", fire_us, cfg=cfg,
                                        spread_filter=spread, notional_usd=NOTIONAL)
                dn_fill = fill_at_book(books, slug, "Down", fire_us, cfg=cfg,
                                        spread_filter=spread, notional_usd=NOTIONAL)

                row = {
                    "asset": asset, "slug": slug, "tf": "15m",
                    "slot_start_us": slot_start_us, "slot_end_us": slot_end_us,
                    "ws_s": ws_s, "fire_offset_s": int(off), "fire_us": fire_us,
                    "strike_price": strike_price, "settle_price": settle_price,
                    "outcome": outcome,
                    "vwap_since_open_bps": vwap_bps,
                    "ret_2m_at_ws": r2m, "prod_q90": q90, "mag_ratio": mag_ratio,
                    "up_fill_ok": up_fill is not None,
                    "dn_fill_ok": dn_fill is not None,
                }
                if up_fill is not None:
                    row.update({"up_vwap": up_fill["vwap"], "up_shares": up_fill["shares"],
                                "up_usd": up_fill["usd"], "up_ask0": up_fill["ask0"],
                                "up_bid0": up_fill["bid0"], "up_book_dt_us": up_fill["dt_us"]})
                else:
                    row.update({"up_vwap": float("nan"), "up_shares": float("nan"),
                                "up_usd": float("nan"), "up_ask0": float("nan"),
                                "up_bid0": float("nan"), "up_book_dt_us": -1})
                if dn_fill is not None:
                    row.update({"dn_vwap": dn_fill["vwap"], "dn_shares": dn_fill["shares"],
                                "dn_usd": dn_fill["usd"], "dn_ask0": dn_fill["ask0"],
                                "dn_bid0": dn_fill["bid0"], "dn_book_dt_us": dn_fill["dt_us"]})
                else:
                    row.update({"dn_vwap": float("nan"), "dn_shares": float("nan"),
                                "dn_usd": float("nan"), "dn_ask0": float("nan"),
                                "dn_bid0": float("nan"), "dn_book_dt_us": -1})
                out_rows.append(row)
        del books
        gc.collect()
        print(f"    {asset}: rows so far = {len(out_rows):,}")

    df = pd.DataFrame(out_rows)
    return df


def _load_klines_1s_idx() -> dict:
    out: dict = {}
    p = ROOT / "data" / "v4" / "canonical" / "klines_1s" / "binance_1s_28d.parquet"
    if p.exists():
        print(f"  loading klines_1s from {p.name}...")
        df = pd.read_parquet(p)
        sym_map = {
            "BINANCE_SPOT_BTC_USDT": "BTC",
            "BINANCE_SPOT_ETH_USDT": "ETH",
            "BINANCE_SPOT_SOL_USDT": "SOL",
        }
        df = df.sort_values(["symbol_id", "time_period_start_us"])
        df = df.drop_duplicates(["symbol_id", "time_period_start_us"], keep="last")
        df["asset"] = df["symbol_id"].map(sym_map)
        for a in ASSETS:
            sub = df[df["asset"] == a].sort_values("time_period_start_us")
            out[a] = (sub["time_period_start_us"].values.astype("int64"),
                       sub["price_close"].values.astype("float64"))
            print(f"    {a}: {len(sub):,} 1s bars")
        # Pull a fresher 1s from load_klines_1s if our cached file truncates pre May 22
        last_us = out["BTC"][0].max() if len(out["BTC"][0]) else 0
        cutoff = int(pd.Timestamp("2026-05-21T12:00:00Z").value // 1000)
        if last_us < cutoff:
            print(f"  [WARN] cached 1s ends {pd.Timestamp(last_us, unit='us', tz='UTC')}; falling back to full load_klines_1s")
        else:
            return out
    for a in ASSETS:
        df = load_klines_1s(a)
        out[a] = (df["time_period_start_us"].values.astype("int64"),
                   df["price_close"].values.astype("float64"))
        print(f"    {a}: {len(df):,} 1s bars (fallback)")
    return out


def main():
    print("[1] load 1MIN klines (binance-spot-ws)...")
    klines_1m: dict = {}
    for a in ASSETS:
        end_us, close = load_klines_asof(a, source="binance-spot-ws", period_id="1MIN")
        klines_1m[a] = (end_us.astype("int64"), close.astype("float64"))
        print(f"  {a}: {len(end_us):,} 1m bars (latest {pd.Timestamp(int(end_us[-1]), unit='us', tz='UTC')})")

    print("[2] load 1s klines...")
    klines_1s_idx = _load_klines_1s_idx()

    print("[3] load prod_q90...")
    q90_idx = _build_q90_lookup()

    print("\n[4] build LOCKBOX universe...")
    t0 = time.time()
    df = build_lockbox_universe(klines_1m, klines_1s_idx, q90_idx)
    df = df.sort_values(["asset", "slot_start_us", "fire_offset_s"]).reset_index(drop=True)
    out_path = OUT_DIR / "hybrid_fire_universe_15m_lockbox.parquet"
    df.to_parquet(out_path, index=False, compression="zstd")
    elapsed = time.time() - t0
    print(f"  wrote {out_path.name}: {len(df):,} rows × {len(df.columns)} cols in {elapsed/60:.1f} min")
    print("  per asset:")
    print(df.groupby("asset").agg(n=("slug","size"), n_slugs=("slug","nunique"),
                                    any_fill_pct=("up_fill_ok", lambda s: round(100 *
                                        ((df.loc[s.index, "up_fill_ok"]) |
                                         (df.loc[s.index, "dn_fill_ok"])).sum() / len(s), 1))).to_string())


if __name__ == "__main__":
    main()
