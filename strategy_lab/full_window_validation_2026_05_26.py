"""Full-window OOS validation — re-test top 15 sleeves on Apr 24 → May 25 (~33d).

Approach:
  1. Re-build the 1s feature panels (RF, TR, TA, SMS proxy) on the EXTENDED
     1s kline (Apr 22 → May 25 from canonical klines_1s.parquet).
  2. Build a full-window fire universe (S1.5 + S6 + V15m base fires) on the
     EXTENDED window using the same logic as the original joined-files but
     keyed off chainlink resolutions (the ground truth).
  3. Apply each of the top 15 sleeve gate stacks to score:
       - 22d reference (existing slice)
       - full 33d window
       - OOS-only slice (May 21 20:00 → May 25 19:10)
  4. Emit FULL_WINDOW_VALIDATION_2026_05_26.md.

This runs LARGE pieces of compute. Strategy: do everything in pandas/numba.

Conventions per CLAUDE.md:
  - Fee = LegacyConfig (2%-on-profit-only): pnl_legacy_usd handles this.
  - ws_s = slot_start - window_s
  - Outcome from chainlink (canonical resolutions parquet)
  - Spread filter: 0.02 BTC/ETH, 0.025 SOL
"""
from __future__ import annotations

import gc
import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

from load import (  # noqa: E402
    load_resolutions, load_klines_asof, load_klines, load_klines_1s,
    load_orderbook_l25_streaming,
)
from engine_v2 import LegacyConfig, fill_at_book  # noqa: E402

RES_DIR = ROOT / "data" / "v4" / "canonical" / "_results"
OOS_DIR = RES_DIR / "_full_window_2026_05_26"
OOS_DIR.mkdir(parents=True, exist_ok=True)

# Window definitions:
#   reference = existing s6_joined_all etc (May 1 -> May 21 20:00)
#   full      = Apr 30 00:00 -> May 25 19:15 (entire L25/resolutions coverage)
#   oos_only  = May 21 20:00:30 (last fire in ref) -> May 25 19:10:00
REF_END_US = int(pd.Timestamp("2026-05-21T20:01:00Z").value // 1000)
FULL_START_US = int(pd.Timestamp("2026-04-30T00:00:00Z").value // 1000)
FULL_END_US = int(pd.Timestamp("2026-05-25T19:15:00Z").value // 1000)
OOS_START_US = REF_END_US  # picks up where the original ref ended
OOS_END_US = FULL_END_US

ASSETS = ("BTC", "ETH", "SOL")
SPREAD = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}
NOTIONAL = 25.0


# ---------------------------------------------------------------------------
# Feature builders — minimum needed for top 15 sleeves
# ---------------------------------------------------------------------------

def load_1s_panel(min_us: int, max_us: int) -> pd.DataFrame:
    """Load 1s binance OHLCV for all 3 assets within window, sorted by (asset, ts)."""
    print(f"[1s panel] loading klines_1s for [{min_us},{max_us}]...", flush=True)
    t0 = time.time()
    df_full = pd.read_parquet(
        ROOT / "data" / "v4" / "canonical" / "klines_1s.parquet",
        columns=["symbol_id", "time_period_start_us", "price_close",
                 "price_open", "price_high", "price_low", "volume_traded",
                 "taker_buy_base"]
    )
    sym_map = {
        "BINANCE_SPOT_BTC_USDT": "BTC",
        "BINANCE_SPOT_ETH_USDT": "ETH",
        "BINANCE_SPOT_SOL_USDT": "SOL",
    }
    df_full["asset"] = df_full["symbol_id"].map(sym_map)
    df_full = df_full[df_full["asset"].notna()]
    df_full = df_full.rename(columns={"time_period_start_us": "ts_us",
                                      "price_close": "close",
                                      "price_open": "open",
                                      "price_high": "high",
                                      "price_low": "low",
                                      "volume_traded": "volume"})
    df_full = df_full[(df_full["ts_us"] >= min_us) & (df_full["ts_us"] <= max_us)]
    df_full = df_full.drop_duplicates(["asset", "ts_us"], keep="last")
    df_full = df_full.sort_values(["asset", "ts_us"]).reset_index(drop=True)
    print(f"  done {len(df_full):,} rows in {time.time()-t0:.1f}s; "
          f"per asset: {df_full.groupby('asset').size().to_dict()}", flush=True)
    return df_full[["asset", "ts_us", "open", "high", "low", "close",
                    "volume", "taker_buy_base"]]


# ---- RF [DW] ----

def range_filter_panel(panel: pd.DataFrame, n: int = 14, sn: int = 27,
                        qty: float = 2.618) -> pd.DataFrame:
    """Compute Range Filter [DW] per asset. Returns subset of panel cols + RF cols."""
    print("[RF] computing range_filter on full-window 1s panel...", flush=True)
    pieces = []
    for asset, grp in panel.groupby("asset", sort=False):
        t0 = time.time()
        grp = grp.reset_index(drop=True)
        close = grp["close"].values.astype(np.float64)
        N = len(close)
        rf_close = np.empty(N, dtype=np.float64)
        rf_hi = np.empty(N, dtype=np.float64)
        rf_lo = np.empty(N, dtype=np.float64)
        rf_r = np.empty(N, dtype=np.float64)
        rf_dir = np.zeros(N, dtype=np.int8)
        alpha_n = 2.0 / (n + 1.0)
        alpha_sn = 2.0 / (sn + 1.0)
        ac = 0.0
        rng_smooth = 0.0
        rfilt = close[0]
        rfilt_prev = close[0]
        dir_prev = 0
        for t in range(N):
            c = close[t]
            d = 0.0 if t == 0 else abs(c - close[t - 1])
            ac = d if t == 0 else (ac + alpha_n * (d - ac))
            rng_size = qty * ac
            rng_smooth = rng_size if t == 0 else (rng_smooth + alpha_sn * (rng_size - rng_smooth))
            r = rng_smooth
            if t == 0:
                rfilt = c
            else:
                if c - r > rfilt_prev:
                    rfilt = c - r
                elif c + r < rfilt_prev:
                    rfilt = c + r
                else:
                    rfilt = rfilt_prev
            if rfilt > rfilt_prev:
                d_now = 1
            elif rfilt < rfilt_prev:
                d_now = -1
            else:
                d_now = dir_prev
            rf_close[t] = rfilt
            rf_r[t] = r
            rf_hi[t] = rfilt + r
            rf_lo[t] = rfilt - r
            rf_dir[t] = d_now
            rfilt_prev = rfilt
            dir_prev = d_now
        # dir_age
        flips = (np.r_[True, rf_dir[1:] != rf_dir[:-1]])
        age = np.empty(N, dtype=np.int32)
        a = -1
        for i in range(N):
            if flips[i]:
                a = 0
            else:
                a += 1
            age[i] = a
        out = pd.DataFrame({
            "asset": asset,
            "ts_us": grp["ts_us"].values,
            "rf_close": rf_close,
            "rf_hi": rf_hi,
            "rf_lo": rf_lo,
            "rf_r": rf_r,
            "rf_dir": rf_dir.astype("int8"),
            "rf_dir_age": age,
        })
        out["rf_dist_bps"] = (close - rf_close) / rf_close * 1e4
        denom = (rf_hi - rf_lo)
        denom = np.where(denom == 0, np.nan, denom)
        out["rf_band_pos"] = (close - rf_lo) / denom
        pieces.append(out)
        print(f"  RF {asset}: {N:,} bars in {time.time()-t0:.1f}s", flush=True)
    return pd.concat(pieces, ignore_index=True)


# ---- Ribbon (subset of compute_ta_indicators) ----

def ribbon_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Compute MA Ribbon + ribbon_color + a subset of TA indicators."""
    print("[TA] computing ribbon + stoch + cci + bb + mfi on full-window 1s...", flush=True)
    EMA_PERIODS = list(range(5, 105, 5))  # 5..100 step 5
    pieces = []
    for asset, grp in panel.groupby("asset", sort=False):
        t0 = time.time()
        g = grp.sort_values("ts_us").reset_index(drop=True)
        close = g["close"].astype(np.float64)
        high = g["high"].astype(np.float64)
        low = g["low"].astype(np.float64)
        volume = g["volume"].astype(np.float64).fillna(0.0)
        tbb = g["taker_buy_base"].astype(np.float64).fillna(0.0)

        out = pd.DataFrame({"asset": asset, "ts_us": g["ts_us"].values,
                            "close": close.values, "volume": volume.values,
                            "taker_buy_base": tbb.values})
        ema_cols = {}
        for p in EMA_PERIODS:
            out[f"ema_{p}"] = close.ewm(span=p, adjust=False).mean().values
            ema_cols[p] = out[f"ema_{p}"].values
        # ribbon_color (Pine logic: lime/green if ema5>ema100, red/maroon otherwise)
        # simplified per project conventions
        ema5 = ema_cols[5]
        ema100 = ema_cols[100]
        # slope of ema5
        ribbon_lead_slope_bps = pd.Series(ema5).pct_change(periods=5).values * 1e4
        ribbon_lead_vs_ref_bps = (ema5 - ema100) / ema100 * 1e4
        # alignment: count pairs in monotone order
        ema_stack = np.column_stack([ema_cols[p] for p in EMA_PERIODS])
        align_up = (ema_stack[:, :-1] > ema_stack[:, 1:]).sum(axis=1)
        ribbon_alignment_pct = align_up / (len(EMA_PERIODS) - 1) * 100.0
        # compression
        stack_mean = ema_stack.mean(axis=1)
        stack_std = ema_stack.std(axis=1)
        ribbon_compression_bps = stack_std / np.maximum(stack_mean, 1e-12) * 1e4
        # color: 1=lime (strong up), 4=green (up), 2=maroon (strong dn), 3=red (dn), 0=gray
        color = np.zeros(len(close), dtype=np.int8)
        is_up = ema5 > ema100
        slope_pos = ribbon_lead_slope_bps > 0.5
        slope_neg = ribbon_lead_slope_bps < -0.5
        color[is_up & slope_pos] = 1  # lime
        color[is_up & ~slope_pos] = 4  # green
        color[~is_up & slope_neg] = 2  # maroon
        color[~is_up & ~slope_neg] = 3  # red
        out["ribbon_lead_slope_bps"] = ribbon_lead_slope_bps
        out["ribbon_lead_vs_ref_bps"] = ribbon_lead_vs_ref_bps
        out["ribbon_alignment_pct"] = ribbon_alignment_pct
        out["ribbon_compression_bps"] = ribbon_compression_bps
        out["ribbon_color"] = color

        # Slow Stoch on 60s rolling proxy (length=14 bars × 60s window):
        # Use 60s rolling close for stoch since our 1s panel has been resampled
        # to 1s — the "length" parameter is the # of 60s bars to look back.
        # The original compute_ta_indicators implementation uses windows of
        # 14*60=840 seconds for stoch_60s. Approximation here.
        window_60 = 14 * 60
        ll = low.rolling(window_60, min_periods=window_60).min()
        hh = high.rolling(window_60, min_periods=window_60).max()
        denom = (hh - ll).replace(0, np.nan)
        raw_k = 100.0 * (close - ll) / denom
        k = raw_k.rolling(3 * 60, min_periods=1).mean()
        d_ = k.rolling(3 * 60, min_periods=1).mean()
        out["stoch_k_60s"] = k.values
        out["stoch_d_60s"] = d_.values
        window_300 = 14 * 300
        ll5 = low.rolling(window_300, min_periods=window_300).min()
        hh5 = high.rolling(window_300, min_periods=window_300).max()
        denom5 = (hh5 - ll5).replace(0, np.nan)
        raw_k5 = 100.0 * (close - ll5) / denom5
        k5 = raw_k5.rolling(3 * 300, min_periods=1).mean()
        d5 = k5.rolling(3 * 300, min_periods=1).mean()
        out["stoch_k_300s"] = k5.values
        out["stoch_d_300s"] = d5.values

        # Bollinger 60s + 120s
        for win in (60, 120):
            mid = close.rolling(win, min_periods=win).mean()
            std = close.rolling(win, min_periods=win).std()
            up_b = mid + 2.0 * std
            lo_b = mid - 2.0 * std
            width = (up_b - lo_b) / mid * 1e4
            pos = (close - lo_b) / (up_b - lo_b).replace(0, np.nan)
            out[f"bb_pos_{win}s"] = pos.values
            out[f"bb_width_{win}s"] = width.values

        # MFI 60s + 300s
        for win in (60, 300):
            tp = (high + low + close) / 3.0
            tp_diff = tp.diff()
            mf = tp * volume
            pos_mf = pd.Series(np.where(tp_diff > 0, mf, 0.0)).rolling(win, min_periods=win).sum().values
            neg_mf = pd.Series(np.where(tp_diff < 0, mf, 0.0)).rolling(win, min_periods=win).sum().values
            ratio = pos_mf / np.maximum(neg_mf, 1e-12)
            out[f"mfi_{win}s"] = 100.0 - 100.0 / (1.0 + ratio)

        # CCI 60s
        tp = (high + low + close) / 3.0
        sma = tp.rolling(60, min_periods=60).mean()
        md = (tp - sma).abs().rolling(60, min_periods=60).mean()
        cci = (tp - sma) / (0.015 * md.replace(0, np.nan))
        out["cci_60s"] = cci.values

        pieces.append(out)
        print(f"  TA {asset}: {len(out):,} bars in {time.time()-t0:.1f}s", flush=True)

    return pd.concat(pieces, ignore_index=True)


# ---- TR (subset of compute_traders_reality) ----

def tr_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Compute Traders Reality EMAs (5/13/50/200/800) + pivots + cloud + sessions."""
    print("[TR] computing traders_reality on full-window 1s...", flush=True)
    pieces = []
    for asset, grp in panel.groupby("asset", sort=False):
        t0 = time.time()
        g = grp.sort_values("ts_us").reset_index(drop=True)
        close = g["close"].astype(np.float64)
        # EMAs
        ema_5 = close.ewm(span=5, adjust=False).mean().values
        ema_13 = close.ewm(span=13, adjust=False).mean().values
        ema_50 = close.ewm(span=50, adjust=False).mean().values
        ema_200 = close.ewm(span=200, adjust=False).mean().values
        ema_800 = close.ewm(span=800, adjust=False).mean().values

        # Cloud (ema_50 to ema_200)
        ec_upper = np.maximum(ema_50, ema_200)
        ec_lower = np.minimum(ema_50, ema_200)
        ec_size = ec_upper - ec_lower
        # pos: 1 above, -1 below, 0 inside
        ec_pos = np.where(close > ec_upper, 1, np.where(close < ec_lower, -1, 0))

        # close vs EMA bps
        tr_close_vs_50 = (close.values - ema_50) / ema_50 * 1e4
        tr_close_vs_200 = (close.values - ema_200) / ema_200 * 1e4
        tr_close_vs_800 = (close.values - ema_800) / ema_800 * 1e4
        tr_above_50 = (tr_close_vs_50 > 0).astype(np.int8)
        tr_above_200 = (tr_close_vs_200 > 0).astype(np.int8)
        tr_above_800 = (tr_close_vs_800 > 0).astype(np.int8)
        tr_above_cloud = (close.values > ec_upper).astype(np.int8)

        # PivotPoints — yesterday's complete day H/L/C
        # Resample to daily UTC and compute pivots, then forward-fill
        ts = g["ts_us"].values.astype(np.int64)
        # daily key
        day_key = ts // (86400 * 1_000_000)
        # We compute per day the H/L/C of THIS day, then for THIS day's pivots we
        # use prior day's H/L/C.
        df_day = pd.DataFrame({
            "day_key": day_key,
            "high": g["high"].values,
            "low": g["low"].values,
            "close": close.values,
            "open": g["open"].values,
        })
        day_agg = df_day.groupby("day_key").agg(
            dayHigh=("high", "max"),
            dayLow=("low", "min"),
            dayClose=("close", "last"),
            dayOpen=("open", "first"),
        ).reset_index()
        # Prior-day values (shift)
        for c in ("dayHigh", "dayLow", "dayClose", "dayOpen"):
            day_agg[f"prev_{c}"] = day_agg[c].shift(1)
        # standard floor pivots
        pH = day_agg["prev_dayHigh"]
        pL = day_agg["prev_dayLow"]
        pC = day_agg["prev_dayClose"]
        PP = (pH + pL + pC) / 3.0
        R1 = 2 * PP - pL
        S1 = 2 * PP - pH
        R2 = PP + (pH - pL)
        S2 = PP - (pH - pL)
        R3 = pH + 2 * (PP - pL)
        S3 = pL - 2 * (pH - PP)
        day_agg["PP"] = PP
        day_agg["R1"] = R1
        day_agg["R2"] = R2
        day_agg["R3"] = R3
        day_agg["S1"] = S1
        day_agg["S2"] = S2
        day_agg["S3"] = S3
        day_agg["adr"] = pH - pL
        day_agg["adr_high"] = day_agg["dayOpen"] + day_agg["adr"] / 2  # approximation
        day_agg["adr_low"] = day_agg["dayOpen"] - day_agg["adr"] / 2

        # join back via merge
        out = pd.DataFrame({"asset": asset,
                            "ts_us": ts,
                            "close": close.values,
                            "ema_5": ema_5, "ema_13": ema_13,
                            "ema_50": ema_50, "ema_200": ema_200, "ema_800": ema_800,
                            "ema_cloud_size": ec_size,
                            "ema_cloud_upper": ec_upper,
                            "ema_cloud_lower": ec_lower,
                            "ema_cloud_pos": ec_pos,
                            "tr_close_vs_ema50": tr_close_vs_50,
                            "tr_close_vs_ema200": tr_close_vs_200,
                            "tr_close_vs_ema800": tr_close_vs_800,
                            "tr_above_ema50": tr_above_50,
                            "tr_above_ema200": tr_above_200,
                            "tr_above_ema800": tr_above_800,
                            "tr_above_cloud": tr_above_cloud,
                            "day_key": day_key,
                            })
        # merge pivot info
        out = out.merge(day_agg[["day_key", "PP", "R1", "R2", "R3", "S1", "S2", "S3",
                                  "adr", "adr_high", "adr_low",
                                  "dayHigh", "dayLow", "dayClose", "dayOpen"]],
                        on="day_key", how="left")
        out["tr_above_pp"] = (out["close"] > out["PP"]).astype(np.int8)
        out["tr_within_adr"] = ((out["close"] >= out["adr_low"]) &
                                (out["close"] <= out["adr_high"])).astype(np.int8)
        out = out.drop(columns=["day_key"])

        # active sessions (UTC time bins)
        # London 07-15, NY 13-21, Tokyo 23-07, HK 01-09, Sydney 22-04
        hod = (ts % (86400 * 1_000_000)) // (3600 * 1_000_000)
        in_london = ((hod >= 7) & (hod < 15)).astype(np.int8)
        in_ny = ((hod >= 13) & (hod < 21)).astype(np.int8)
        in_tokyo = ((hod >= 23) | (hod < 7)).astype(np.int8)
        out["tr_in_london"] = in_london
        out["tr_in_ny"] = in_ny
        out["tr_in_tokyo"] = in_tokyo
        out["tr_active_session_count"] = in_london + in_ny + in_tokyo

        # PVSRA approximate (vol vs SMA(10))
        vol = g["volume"].astype(np.float64).fillna(0.0).values
        sma_vol_10 = pd.Series(vol).rolling(10, min_periods=10).mean().values
        climax = (vol >= 2.0 * sma_vol_10).astype(np.int8)
        rising = ((vol >= 1.5 * sma_vol_10) & (vol < 2.0 * sma_vol_10)).astype(np.int8)
        is_bull = (close.values > g["open"].astype(np.float64).values).astype(np.int8)
        pvsra = np.zeros(len(close), dtype=np.int8)
        pvsra[(climax > 0) & (is_bull > 0)] = 2
        pvsra[(climax > 0) & (is_bull == 0)] = -2
        pvsra[(rising > 0) & (is_bull > 0)] = 1
        pvsra[(rising > 0) & (is_bull == 0)] = -1
        out["tr_pvsra"] = pvsra

        # tr_ema_stack metrics
        stack_up = ((ema_5 > ema_13) & (ema_13 > ema_50) & (ema_50 > ema_200) &
                    (ema_200 > ema_800)).astype(np.int8)
        stack_dn = ((ema_5 < ema_13) & (ema_13 < ema_50) & (ema_50 < ema_200) &
                    (ema_200 < ema_800)).astype(np.int8)
        out["tr_ema_stack_bull"] = stack_up
        out["tr_ema_stack_bear"] = stack_dn
        out["tr_ema_stack_score"] = stack_up - stack_dn

        pieces.append(out)
        print(f"  TR {asset}: {len(out):,} bars in {time.time()-t0:.1f}s", flush=True)
    return pd.concat(pieces, ignore_index=True)


# ---- SMS panel (5m bar features for liquidity_reclaim) ----

def sms_panel_5m(panel_1s: pd.DataFrame) -> pd.DataFrame:
    """Build per-5m sms-style panel from 1s OHLCV: liquidity_up/dn (rolling 20-bar
    sweep), pivot_high/low, BOS, CHoCH."""
    print("[SMS5m] computing SMS panel on 5m resampled bars...", flush=True)
    pieces = []
    for asset, grp in panel_1s.groupby("asset", sort=False):
        t0 = time.time()
        g = grp.sort_values("ts_us").reset_index(drop=True)
        g["dt"] = pd.to_datetime(g["ts_us"], unit="us", utc=True)
        g = g.set_index("dt")
        bar = g.resample("5min").agg({"open": "first", "high": "max", "low": "min",
                                       "close": "last", "volume": "sum"}).dropna()
        if bar.empty:
            continue
        # Pivot high = last_high_20bars; pivot_low = last_low_20bars
        rolling_high = bar["high"].rolling(20).max()
        rolling_low = bar["low"].rolling(20).min()
        bar["last_high"] = rolling_high.shift(1)  # excludes current bar
        bar["last_low"] = rolling_low.shift(1)
        # liquidity sweep: high tap last_high (sweep up) -> sets liquidity_up = 1
        bar["liquidity_up"] = (bar["high"] >= bar["last_high"]).fillna(False).astype(np.int8)
        bar["liquidity_dn"] = (bar["low"] <= bar["last_low"]).fillna(False).astype(np.int8)
        # ts_us at bar START
        bar["ts_us"] = (bar.index.view("int64") // 1000).astype("int64")
        bar["asset"] = asset
        out = bar.reset_index(drop=True)[
            ["asset", "ts_us", "high", "low", "close", "last_high", "last_low",
             "liquidity_up", "liquidity_dn"]
        ]
        pieces.append(out)
        print(f"  SMS5m {asset}: {len(out):,} bars in {time.time()-t0:.1f}s", flush=True)
    return pd.concat(pieces, ignore_index=True)


# ---------------------------------------------------------------------------
# Fire universe build — recreate S6, S1.5, V15m for the OOS window
# ---------------------------------------------------------------------------

def _asof_strict(end_us: np.ndarray, prices: np.ndarray, target_us: int) -> float:
    pos = int(np.searchsorted(end_us, int(target_us), side="right")) - 1
    if pos < 0:
        return float("nan")
    return float(prices[pos])


def build_oos_fires(panel_1s: pd.DataFrame,
                    ta_panel: pd.DataFrame,
                    tr_data: pd.DataFrame,
                    rf_data: pd.DataFrame,
                    sms_5m: pd.DataFrame,
                    klines_1m: dict) -> dict[str, pd.DataFrame]:
    """For each tf (5m/15m), build a per-fire DataFrame on the OOS window with:
       - resolved markets (chainlink-only)
       - direction & outcome
       - pnl_legacy_usd (from L25 fill)
       - all features (RF / TR / TA / SMS) joined at fire_us

    Returns dict with 'oos_5m_s6', 'oos_5m_s15', 'oos_15m_s7' fire DataFrames.
    Each is structured like the existing joined-all files.
    """
    print(f"\n=== Build OOS fires for window {pd.Timestamp(OOS_START_US * 1000)} -> "
          f"{pd.Timestamp(OOS_END_US * 1000)} ===", flush=True)

    out = {}
    for tf, window_s, offsets, suffix in [
        ("5m", 300, list(range(15, 301, 15)), "s6_s15"),
        ("15m", 900, [60, 120, 180, 240, 300, 360, 420, 480, 540, 600, 660, 720, 780, 840], "v15m"),
    ]:
        print(f"\n[OOS-{tf}] starting...", flush=True)
        res = load_resolutions(assets=list(ASSETS), timeframes=[tf])
        res = res[res["outcome"].isin(("Up", "Down"))].copy()
        # constrain to OOS window
        res = res[(res["slot_start_us"] >= OOS_START_US) &
                  (res["slot_start_us"] <= OOS_END_US)].copy()
        if res.empty:
            continue
        res["ws_s"] = (res["slot_start_us"] // 1_000_000) - window_s
        res["window_s"] = window_s
        print(f"  resolutions: {len(res):,}")

        cfg = LegacyConfig()
        rows = []
        for asset in ASSETS:
            rsub = res[res["ticker"] == asset].copy()
            if rsub.empty:
                continue
            print(f"  [{asset}] streaming L25 for {len(rsub):,} slugs...", flush=True)
            t0 = time.time()
            min_us = int(rsub["slot_start_us"].min()) - 3600 * 1_000_000
            max_us = int(rsub["slot_end_us"].max()) + 3600 * 1_000_000
            books = load_orderbook_l25_streaming(
                asset.lower(), slugs=set(rsub["slug"].tolist()),
                subsample_1hz=True, min_ts_us=min_us, max_ts_us=max_us,
            )
            print(f"    L25 streamed {time.time()-t0:.1f}s, "
                  f"{len(books)} (slug,outcome) pairs", flush=True)
            spread = SPREAD[asset]
            end_us_1m, close_1m = klines_1m[asset]

            for r in rsub.itertuples(index=False):
                slug = r.slug
                ss = int(r.slot_start_us)
                se = int(r.slot_end_us)
                ws_s = int(r.ws_s)
                outcome = str(r.outcome)
                strike = _asof_strict(end_us_1m, close_1m, ss)
                settle = _asof_strict(end_us_1m, close_1m, se)
                for off in offsets:
                    fire_us = ss + off * 1_000_000
                    # try both directions
                    up_fill = fill_at_book(books, slug, "Up", fire_us, cfg=cfg,
                                            spread_filter=spread, notional_usd=NOTIONAL)
                    dn_fill = fill_at_book(books, slug, "Down", fire_us, cfg=cfg,
                                            spread_filter=spread, notional_usd=NOTIONAL)
                    if up_fill is not None:
                        won_up = (outcome == "Up")
                        from engine_v2 import hold_pnl
                        pnl_up = hold_pnl(up_fill, won=won_up, cfg=cfg)
                        rows.append({
                            "asset": asset, "slug": slug, "tf": tf,
                            "slot_start_us": ss, "slot_end_us": se, "ws_s": ws_s,
                            "fire_offset_s": int(off), "fire_us": fire_us,
                            "strike_price": strike, "settle_price": settle,
                            "outcome": outcome, "direction": "UP",
                            "pnl_legacy_usd": pnl_up, "won": int(won_up),
                            "entry_vwap": up_fill["vwap"],
                            "fill_shares": up_fill["shares"],
                            "spread_ok": True,
                        })
                    if dn_fill is not None:
                        won_dn = (outcome == "Down")
                        from engine_v2 import hold_pnl
                        pnl_dn = hold_pnl(dn_fill, won=won_dn, cfg=cfg)
                        rows.append({
                            "asset": asset, "slug": slug, "tf": tf,
                            "slot_start_us": ss, "slot_end_us": se, "ws_s": ws_s,
                            "fire_offset_s": int(off), "fire_us": fire_us,
                            "strike_price": strike, "settle_price": settle,
                            "outcome": outcome, "direction": "DOWN",
                            "pnl_legacy_usd": pnl_dn, "won": int(won_dn),
                            "entry_vwap": dn_fill["vwap"],
                            "fill_shares": dn_fill["shares"],
                            "spread_ok": True,
                        })
            del books
            gc.collect()
        df = pd.DataFrame(rows)
        if df.empty:
            print(f"  no fires for {tf}!")
            continue
        # Join features (RF/TR/TA at fire_us-1us via merge_asof)
        df["lookup_us"] = df["fire_us"].astype("int64") - 1_000_000
        df = df.sort_values(["asset", "lookup_us"]).reset_index(drop=True)
        # RF
        rf_join_cols = ["rf_close", "rf_hi", "rf_lo", "rf_r", "rf_dir",
                        "rf_dir_age", "rf_dist_bps", "rf_band_pos"]
        rf2 = rf_data[["asset", "ts_us"] + rf_join_cols].copy()
        rf2["lookup_us"] = rf2["ts_us"]
        rf2 = rf2.sort_values(["asset", "lookup_us"]).reset_index(drop=True)
        parts = []
        for asset in df["asset"].unique():
            da = df[df.asset == asset].sort_values("lookup_us")
            ra = rf2[rf2.asset == asset].sort_values("lookup_us")
            if len(ra) == 0:
                da[rf_join_cols] = np.nan
                parts.append(da)
                continue
            m = pd.merge_asof(da, ra[["lookup_us"] + rf_join_cols],
                              on="lookup_us", direction="backward",
                              tolerance=5_000_000)
            parts.append(m)
        df = pd.concat(parts, ignore_index=True)

        # TA join
        ta_cols = ["close", "ema_5", "ema_50", "ema_100",
                   "ribbon_lead_slope_bps", "ribbon_alignment_pct",
                   "ribbon_compression_bps", "ribbon_color",
                   "stoch_k_60s", "stoch_d_60s", "stoch_k_300s", "stoch_d_300s",
                   "bb_pos_60s", "bb_width_60s", "bb_pos_120s",
                   "mfi_60s", "mfi_300s", "cci_60s"]
        ta_cols = [c for c in ta_cols if c in ta_panel.columns]
        ta2 = ta_panel[["asset", "ts_us"] + ta_cols].copy()
        ta2["lookup_us"] = ta2["ts_us"]
        ta2 = ta2.sort_values(["asset", "lookup_us"]).reset_index(drop=True)
        parts = []
        for asset in df["asset"].unique():
            da = df[df.asset == asset].sort_values("lookup_us")
            ra = ta2[ta2.asset == asset].sort_values("lookup_us")
            if len(ra) == 0:
                da[ta_cols] = np.nan
                parts.append(da)
                continue
            ra_rename = {c: f"ta_{c}" if c in da.columns and c not in ("lookup_us",) else c
                         for c in ta_cols}
            ra = ra.rename(columns=ra_rename)
            new_cols = [ra_rename.get(c, c) for c in ta_cols]
            m = pd.merge_asof(da, ra[["lookup_us"] + new_cols],
                              on="lookup_us", direction="backward",
                              tolerance=5_000_000)
            parts.append(m)
        df = pd.concat(parts, ignore_index=True)

        # TR join
        tr_cols = ["ema_50", "ema_200", "ema_800",
                   "ema_cloud_size", "ema_cloud_upper", "ema_cloud_lower", "ema_cloud_pos",
                   "tr_close_vs_ema50", "tr_close_vs_ema200", "tr_close_vs_ema800",
                   "tr_above_ema50", "tr_above_ema200", "tr_above_ema800",
                   "tr_above_cloud", "PP", "R1", "R2", "S1", "S2",
                   "tr_above_pp", "tr_within_adr",
                   "tr_in_london", "tr_in_ny", "tr_in_tokyo",
                   "tr_active_session_count", "tr_pvsra",
                   "tr_ema_stack_bull", "tr_ema_stack_bear", "tr_ema_stack_score"]
        tr_cols = [c for c in tr_cols if c in tr_data.columns]
        tr2 = tr_data[["asset", "ts_us"] + tr_cols].copy()
        tr2["lookup_us"] = tr2["ts_us"]
        tr2 = tr2.sort_values(["asset", "lookup_us"]).reset_index(drop=True)
        parts = []
        for asset in df["asset"].unique():
            da = df[df.asset == asset].sort_values("lookup_us")
            ra = tr2[tr2.asset == asset].sort_values("lookup_us")
            if len(ra) == 0:
                da[tr_cols] = np.nan
                parts.append(da)
                continue
            ra_rename = {c: f"tr_{c}" if c in da.columns and c not in ("lookup_us",) else c
                         for c in tr_cols}
            ra = ra.rename(columns=ra_rename)
            new_cols = [ra_rename.get(c, c) for c in tr_cols]
            m = pd.merge_asof(da, ra[["lookup_us"] + new_cols],
                              on="lookup_us", direction="backward",
                              tolerance=5_000_000)
            parts.append(m)
        df = pd.concat(parts, ignore_index=True)

        # SMS join (5m bar lookback)
        if tf == "5m" and not sms_5m.empty:
            bar_us = 5 * 60 * 1_000_000
            df["sms_lookup_us"] = df["fire_us"].astype("int64") - bar_us
            sms2 = sms_5m.copy()
            sms2["lookup_us"] = sms2["ts_us"]
            parts = []
            for asset in df["asset"].unique():
                da = df[df.asset == asset].sort_values("sms_lookup_us")
                ra = sms2[sms2.asset == asset].sort_values("lookup_us")
                if len(ra) == 0:
                    da["liquidity_up"] = np.nan
                    da["liquidity_dn"] = np.nan
                    parts.append(da)
                    continue
                m = pd.merge_asof(da, ra[["lookup_us", "liquidity_up", "liquidity_dn"]],
                                  left_on="sms_lookup_us", right_on="lookup_us",
                                  direction="backward",
                                  tolerance=2 * bar_us)
                parts.append(m)
            df = pd.concat(parts, ignore_index=True)

        # Compute gate columns (matching sms_gate_overlay + base hybrid gates)
        df = compute_gates(df)
        # Save
        out_path = OOS_DIR / f"oos_{tf}_fires.parquet"
        df.to_parquet(out_path, index=False, compression="zstd")
        print(f"  wrote {out_path.name}: {len(df):,} rows")
        out[tf] = df
    return out


def compute_gates(df: pd.DataFrame) -> pd.DataFrame:
    """Add g_* binary gate columns matching hybrid_join_and_gates + sms_gate_overlay."""
    df = df.copy()
    is_up = (df["direction"] == "UP").astype(np.int8)
    is_dn = (df["direction"] == "DOWN").astype(np.int8)

    # RF gates
    if "rf_dir" in df.columns:
        df["g_rf_with"] = ((is_up & (df["rf_dir"] == 1)) |
                           (is_dn & (df["rf_dir"] == -1))).fillna(0).astype(np.int8)
        df["g_rf_fresh"] = (df["rf_dir_age"].fillna(999) <= 60).astype(np.int8)
        df["g_rf_aged"] = (df["rf_dir_age"].fillna(0) >= 60).astype(np.int8)
        df["g_rf_strong"] = ((is_up & (df["rf_band_pos"].fillna(0.5) > 0.7)) |
                              (is_dn & (df["rf_band_pos"].fillna(0.5) < 0.3))).astype(np.int8)
        df["g_rf_in_band"] = ((df["rf_band_pos"].fillna(0.5) >= 0.2) &
                               (df["rf_band_pos"].fillna(0.5) <= 0.8)).astype(np.int8)

    # TR gates
    df["g_tr_stack_with"] = ((is_up & (df.get("tr_ema_stack_bull", 0) == 1)) |
                               (is_dn & (df.get("tr_ema_stack_bear", 0) == 1))).astype(np.int8)
    df["g_tr_stack_full_with"] = df["g_tr_stack_with"]
    df["g_tr_pvsra_with"] = ((is_up & (df.get("tr_pvsra", 0) > 0)) |
                              (is_dn & (df.get("tr_pvsra", 0) < 0))).astype(np.int8)
    if "tr_above_cloud" in df.columns:
        df["g_tr_above_cloud"] = ((is_up & (df["tr_above_cloud"] == 1)) |
                                   (is_dn & (df["tr_above_cloud"] == 0))).astype(np.int8)
    df["g_tr_within_adr"] = df.get("tr_within_adr", 0).astype(np.int8)
    df["g_tr_in_active_session"] = (df.get("tr_active_session_count", 0) >= 1).astype(np.int8)
    if "tr_above_pp" in df.columns:
        df["g_tr_above_pp"] = ((is_up & (df["tr_above_pp"] == 1)) |
                                (is_dn & (df["tr_above_pp"] == 0))).astype(np.int8)
    if "tr_above_ema50" in df.columns:
        df["g_tr_above_ema50"] = ((is_up & (df["tr_above_ema50"] == 1)) |
                                    (is_dn & (df["tr_above_ema50"] == 0))).astype(np.int8)
    if "tr_above_ema200" in df.columns:
        df["g_tr_above_ema200"] = ((is_up & (df["tr_above_ema200"] == 1)) |
                                     (is_dn & (df["tr_above_ema200"] == 0))).astype(np.int8)
    if "tr_above_ema800" in df.columns:
        df["g_tr_above_ema800"] = ((is_up & (df["tr_above_ema800"] == 1)) |
                                     (is_dn & (df["tr_above_ema800"] == 0))).astype(np.int8)

    # Ribbon gates
    if "ribbon_color" in df.columns:
        df["g_ribbon_agrees"] = ((is_up & df["ribbon_color"].isin([1, 4])) |
                                  (is_dn & df["ribbon_color"].isin([2, 3]))).astype(np.int8)
        df["g_ribbon_slope_with"] = ((is_up & (df.get("ribbon_lead_slope_bps", 0) > 0)) |
                                       (is_dn & (df.get("ribbon_lead_slope_bps", 0) < 0))).astype(np.int8)
    if "ribbon_compression_bps" in df.columns:
        df["g_tight_ribbon"] = (df["ribbon_compression_bps"].fillna(999) < 2.0).astype(np.int8)

    # BB/stoch/mfi/cci gates (use 60s)
    if "bb_pos_60s" in df.columns:
        df["g_bb_pos_with"] = ((is_up & (df["bb_pos_60s"].fillna(0.5) > 0.5)) |
                                (is_dn & (df["bb_pos_60s"].fillna(0.5) < 0.5))).astype(np.int8)
    if "stoch_k_60s" in df.columns:
        df["g_stoch_with"] = ((is_up & (df["stoch_k_60s"].fillna(50) > 50)) |
                                (is_dn & (df["stoch_k_60s"].fillna(50) < 50))).astype(np.int8)
    if "mfi_60s" in df.columns:
        df["g_mfi_with"] = ((is_up & (df["mfi_60s"].fillna(50) > 50)) |
                              (is_dn & (df["mfi_60s"].fillna(50) < 50))).astype(np.int8)
    if "cci_60s" in df.columns:
        df["g_cci_with"] = ((is_up & (df["cci_60s"].fillna(0) > 0)) |
                              (is_dn & (df["cci_60s"].fillna(0) < 0))).astype(np.int8)

    # Dev gates (require vwap_since_open / dev_bps_vwap; skip if unavailable)
    df["g_within_dev"] = 1
    df["g_dev_extreme"] = 0

    # SMS gates (5m only)
    if "liquidity_up" in df.columns:
        df["g_sms_liq_reclaim_with"] = (
            (is_up & (df["liquidity_dn"].fillna(0) == 1)) |
            (is_dn & (df["liquidity_up"].fillna(0) == 1))
        ).astype(np.int8)
        df["g_sms_no_liquidity_above"] = (
            (is_up & (df["liquidity_up"].fillna(0) == 0)) |
            (is_dn & (df["liquidity_dn"].fillna(0) == 0))
        ).astype(np.int8)

    return df


# ---------------------------------------------------------------------------
# Sleeve scoring
# ---------------------------------------------------------------------------

@dataclass
class Sleeve:
    sleeve_id: str
    asset: str
    tf: str          # '5m' | '15m'
    base: str        # 's6' | 's15' | 'v15m' | 'standalone'
    offset_range: tuple
    gate_stack: list[str]   # AND of these
    direction_pick: str = "BOTH"    # 'UP'|'DOWN'|'BOTH'
    ref_n: int = 0
    ref_wr: float = 0.0
    ref_dpt: float = 0.0
    ref_sum: float = 0.0


def score_sleeve(df_ref: pd.DataFrame,
                  df_full: pd.DataFrame,
                  df_oos: pd.DataFrame,
                  sl: Sleeve) -> dict:
    def apply_filter(df):
        if df is None or len(df) == 0:
            return df
        m = (df["asset"] == sl.asset) & (df["tf"] == sl.tf)
        lo, hi = sl.offset_range
        m &= (df["fire_offset_s"] >= lo) & (df["fire_offset_s"] <= hi)
        for g in sl.gate_stack:
            if g in df.columns:
                m &= (df[g] == 1)
            else:
                # Skip if gate missing
                pass
        if sl.direction_pick != "BOTH":
            m &= (df["direction"] == sl.direction_pick)
        return df[m]

    def stats(sub):
        n = len(sub)
        if n == 0:
            return {"n": 0, "wr": np.nan, "dpt": np.nan, "sum": 0.0}
        sum_pnl = float(sub["pnl_legacy_usd"].sum())
        wins = int(sub["won"].sum())
        return {"n": n, "wr": wins / n, "dpt": sum_pnl / n, "sum": sum_pnl}

    ref_sub = apply_filter(df_ref) if df_ref is not None else None
    full_sub = apply_filter(df_full) if df_full is not None else None
    oos_sub = apply_filter(df_oos) if df_oos is not None else None

    return {
        "sleeve_id": sl.sleeve_id,
        "asset": sl.asset, "tf": sl.tf, "base": sl.base,
        "offset_range": f"{sl.offset_range[0]}-{sl.offset_range[1]}",
        "gates": "&".join(sl.gate_stack),
        "ref_22d_n": sl.ref_n, "ref_22d_wr": sl.ref_wr,
        "ref_22d_dpt": sl.ref_dpt, "ref_22d_sum": sl.ref_sum,
        "rerun_ref_n": stats(ref_sub)["n"] if ref_sub is not None else None,
        "rerun_ref_wr": stats(ref_sub)["wr"] if ref_sub is not None else None,
        "rerun_ref_dpt": stats(ref_sub)["dpt"] if ref_sub is not None else None,
        "rerun_ref_sum": stats(ref_sub)["sum"] if ref_sub is not None else None,
        "full_n": stats(full_sub)["n"] if full_sub is not None else None,
        "full_wr": stats(full_sub)["wr"] if full_sub is not None else None,
        "full_dpt": stats(full_sub)["dpt"] if full_sub is not None else None,
        "full_sum": stats(full_sub)["sum"] if full_sub is not None else None,
        "oos_n": stats(oos_sub)["n"] if oos_sub is not None else None,
        "oos_wr": stats(oos_sub)["wr"] if oos_sub is not None else None,
        "oos_dpt": stats(oos_sub)["dpt"] if oos_sub is not None else None,
        "oos_sum": stats(oos_sub)["sum"] if oos_sub is not None else None,
    }


# ---------------------------------------------------------------------------
# Top 15 sleeves (from MASTER_DEPLOY_SPEC + NEW_INDICATORS_SYNTHESIS)
# ---------------------------------------------------------------------------

TOP_SLEEVES: list[Sleeve] = [
    Sleeve("poly_updown_btc_5m_s6_hybrid_v2_sms",
           "BTC", "5m", "s6", (60, 150),
           ["g_cci_with", "g_stoch_with", "g_rf_with",
            "g_tr_above_ema50", "g_ribbon_agrees",
            "g_sms_liq_reclaim_with"],
           ref_n=699, ref_wr=0.883, ref_dpt=18.71, ref_sum=13075),
    Sleeve("poly_updown_btc_5m_s6_hybrid_v1",
           "BTC", "5m", "s6", (60, 150),
           ["g_cci_with", "g_stoch_with", "g_rf_with",
            "g_tr_above_ema50", "g_ribbon_agrees"],
           ref_n=2764, ref_wr=0.778, ref_dpt=5.10, ref_sum=14103),
    Sleeve("poly_updown_eth_5m_s6_hybrid_v2_sms",
           "ETH", "5m", "s6", (60, 150),
           ["g_cci_with", "g_bb_pos_with", "g_ribbon_agrees",
            "g_sms_liq_reclaim_with"],
           ref_n=324, ref_wr=0.614, ref_dpt=10.52, ref_sum=3410),
    Sleeve("poly_updown_eth_5m_s6_hybrid_v1",
           "ETH", "5m", "s6", (60, 150),
           ["g_cci_with", "g_bb_pos_with", "g_ribbon_agrees"],
           ref_n=3531, ref_wr=0.760, ref_dpt=1.57, ref_sum=5553),
    Sleeve("poly_updown_btc_5m_off120_sms_liq",
           "BTC", "5m", "s6", (120, 120),
           ["g_sms_liq_reclaim_with"],
           ref_n=166, ref_wr=0.771, ref_dpt=20.68, ref_sum=3432),
    Sleeve("poly_updown_eth_5m_s15_hybrid_v1",
           "ETH", "5m", "s15", (150, 240),
           ["g_ribbon_agrees", "g_tr_above_ema200", "g_stoch_with",
            "g_bb_pos_with", "g_cci_with"],
           ref_n=3420, ref_wr=0.851, ref_dpt=1.34, ref_sum=4596),
    Sleeve("poly_updown_btc_5m_s15_hybrid_v1",
           "BTC", "5m", "s15", (150, 240),
           ["g_tr_above_pp", "g_ribbon_agrees", "g_stoch_with",
            "g_tight_ribbon"],
           ref_n=1365, ref_wr=0.856, ref_dpt=3.06, ref_sum=4176),
    Sleeve("poly_updown_sol_5m_s6_hybrid_v1",
           "SOL", "5m", "s6", (60, 150),
           ["g_mfi_with", "g_bb_pos_with", "g_ribbon_agrees"],
           ref_n=1503, ref_wr=0.929, ref_dpt=2.20, ref_sum=3307),
    Sleeve("poly_updown_btc_5m_xa_down",
           "BTC", "5m", "s6", (60, 300),
           ["g_rf_with"],
           direction_pick="DOWN",
           ref_n=2726, ref_wr=0.821, ref_dpt=1.64, ref_sum=4463),
    Sleeve("poly_updown_btc_15m_s7_hybrid_v1",
           "BTC", "15m", "v15m", (480, 840),
           ["g_tr_above_ema200", "g_stoch_with"],
           ref_n=816, ref_wr=0.880, ref_dpt=2.15, ref_sum=1752),
    Sleeve("poly_updown_eth_15m_off120_240",
           "ETH", "15m", "v15m", (120, 240),
           ["g_cci_with", "g_tr_above_pp", "g_tr_above_ema200"],
           ref_n=130, ref_wr=0.846, ref_dpt=3.81, ref_sum=495),
    Sleeve("poly_updown_eth_15m_off60_120",
           "ETH", "15m", "v15m", (60, 120),
           ["g_rf_aged", "g_ribbon_agrees"],
           ref_n=87, ref_wr=0.782, ref_dpt=4.48, ref_sum=390),
    Sleeve("poly_updown_pool_15m_offge480",
           "BTC", "15m", "v15m", (480, 840),  # pool = BTC+ETH+SOL; use BTC as proxy
           ["g_rf_in_band"],
           ref_n=86, ref_wr=0.872, ref_dpt=5.48, ref_sum=471),
    Sleeve("poly_updown_sol_5m_drz_res_down",
           "SOL", "5m", "s6", (60, 300),
           ["g_tr_above_pp"],
           direction_pick="DOWN",
           ref_n=291, ref_wr=0.639, ref_dpt=6.62, ref_sum=1927),
    Sleeve("poly_updown_btc_15m_s7_hybrid_v1_late",
           "BTC", "15m", "v15m", (480, 840),
           ["g_tr_above_ema200", "g_stoch_with", "g_tight_ribbon"],
           ref_n=816, ref_wr=0.880, ref_dpt=2.15, ref_sum=1752),
]


# ---------------------------------------------------------------------------
# Helpers — load existing joined-files as REF base
# ---------------------------------------------------------------------------

def load_ref_files() -> dict[str, pd.DataFrame]:
    """Load existing joined-all + sms-joined files as REF base."""
    print("\n[REF] loading existing joined files...", flush=True)
    s6 = pd.read_parquet(RES_DIR / "s6_joined_all.parquet")
    s15 = pd.read_parquet(RES_DIR / "s15_joined_all.parquet")
    v15m = pd.read_parquet(RES_DIR / "v15m_joined_all.parquet")
    sms = pd.read_parquet(RES_DIR / "s6_with_sms.parquet")

    # Add SMS columns onto s6 via slug+fire_us
    sms_cols = ["liquidity_up", "liquidity_dn", "trend_strength_raw",
                "system_confidence", "cvd_sign", "bos_buy", "bos_sell",
                "choch_buy", "choch_sell"]
    sms_cols = [c for c in sms_cols if c in sms.columns]
    sms_sub = sms[["slug", "fire_us", "definition"] + sms_cols].drop_duplicates(
        ["slug", "fire_us", "definition"])
    s6 = s6.merge(sms_sub, on=["slug", "fire_us", "definition"], how="left")
    s6 = compute_gates(s6.assign(tf="5m"))

    # Add SMS to s15 via merged
    sms15 = pd.read_parquet(RES_DIR / "s15_with_sms.parquet")
    sms15_sub = sms15[["slug", "fire_us"] + sms_cols].drop_duplicates(["slug", "fire_us"])
    s15 = s15.merge(sms15_sub, on=["slug", "fire_us"], how="left")
    s15 = compute_gates(s15.assign(tf="5m"))

    smsv = pd.read_parquet(RES_DIR / "v15m_with_sms.parquet")
    smsv_sub = smsv[["slug", "fire_us"] + sms_cols].drop_duplicates(["slug", "fire_us"])
    v15m = v15m.merge(smsv_sub, on=["slug", "fire_us"], how="left")
    v15m = compute_gates(v15m.assign(tf="15m"))

    return {"s6": s6, "s15": s15, "v15m": v15m}


# ---------------------------------------------------------------------------
# Stability — rolling per-week metrics
# ---------------------------------------------------------------------------

def rolling_stability(df_full: pd.DataFrame, sl: Sleeve, window_days: int = 7) -> pd.DataFrame:
    m = (df_full["asset"] == sl.asset) & (df_full["tf"] == sl.tf)
    lo, hi = sl.offset_range
    m &= (df_full["fire_offset_s"] >= lo) & (df_full["fire_offset_s"] <= hi)
    for g in sl.gate_stack:
        if g in df_full.columns:
            m &= (df_full[g] == 1)
    if sl.direction_pick != "BOTH":
        m &= (df_full["direction"] == sl.direction_pick)
    sub = df_full[m].copy()
    if len(sub) == 0:
        return pd.DataFrame()
    sub["dt"] = pd.to_datetime(sub["fire_us"], unit="us", utc=True)
    sub = sub.sort_values("dt").reset_index(drop=True)
    sub["pnl"] = sub["pnl_legacy_usd"]
    # rolling window stats
    sub["week"] = sub["dt"].dt.isocalendar().week
    grp = sub.groupby("week").agg(
        n=("won", "size"),
        wr=("won", "mean"),
        dpt=("pnl", "mean"),
        sum=("pnl", "sum"),
    ).reset_index()
    return grp


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    t_start = time.time()

    # Step 1: load REF data (existing joined files + sms merge + gates)
    ref_data = load_ref_files()

    # Step 2: load 1s panel for OOS-only window (we already have most days; we
    # only need the last ~5 days of feature extension for the OOS slice).
    # Use a buffer to ensure warmup of long EMAs etc.
    # For TR ema_800 warmup needs ~800 seconds; use ~3h buffer.
    buf_us = 3 * 3600 * 1_000_000
    panel = load_1s_panel(min_us=OOS_START_US - buf_us, max_us=OOS_END_US + 60_000_000)

    # Step 3: compute feature panels on this 1s panel
    rf = range_filter_panel(panel)
    ta = ribbon_panel(panel)
    tr = tr_panel(panel)
    sms5m = sms_panel_5m(panel)

    # Step 4: load 1m klines for strike/settle
    klines_1m = {}
    for a in ASSETS:
        end_us, close = load_klines_asof(a, source="binance-spot-ws", period_id="1MIN")
        klines_1m[a] = (end_us.astype("int64"), close.astype("float64"))

    # Step 5: build OOS fire universe and join features
    oos_fires = build_oos_fires(panel, ta, tr, rf, sms5m, klines_1m)

    # OOS data per base:
    oos_5m = oos_fires.get("5m")
    oos_15m = oos_fires.get("15m")

    # Step 6: score top 15 sleeves
    rows = []
    for sl in TOP_SLEEVES:
        # Pick correct REF base
        if sl.base == "s6":
            ref_df = ref_data["s6"]
        elif sl.base == "s15":
            ref_df = ref_data["s15"]
        elif sl.base == "v15m":
            ref_df = ref_data["v15m"]
        else:
            ref_df = ref_data["s6"]

        # Add tf column if missing
        if "tf" not in ref_df.columns:
            ref_df = ref_df.copy()
            ref_df["tf"] = sl.tf
        if sl.tf == "5m":
            oos_df = oos_5m
        else:
            oos_df = oos_15m

        # Full = ref + oos concat for this base (only matching tf)
        # Note: OOS may include fires that overlap with REF; we de-dupe by slug+fire_us+direction
        if oos_df is not None and len(oos_df) > 0:
            ref_for_full = ref_df.copy()
            oos_filtered = oos_df[(oos_df["tf"] == sl.tf) & (oos_df["asset"] == sl.asset)]
            # remove rows in REF that are within OOS time window to avoid double count
            full_df = pd.concat([ref_for_full, oos_filtered], ignore_index=True)
            full_df = full_df.drop_duplicates(["slug", "fire_us", "direction"], keep="first")
        else:
            full_df = ref_df.copy()
        result = score_sleeve(ref_df, full_df, oos_df, sl)
        rows.append(result)
        print(f"  scored {sl.sleeve_id}: ref_n={result['rerun_ref_n']}, "
              f"full_n={result['full_n']}, oos_n={result['oos_n']}", flush=True)

    summary = pd.DataFrame(rows)
    out_csv = OOS_DIR / "sleeve_full_window_validation.csv"
    summary.to_csv(out_csv, index=False)
    print(f"\nwrote {out_csv}")

    # Stability per sleeve (top 5)
    print("\n[stability] computing rolling weekly per-sleeve...", flush=True)
    stab_rows = []
    # Use full_df from BTC s6 as a quick proxy: combine ref + oos for each sleeve's base
    # We re-score by week to detect degradation
    for sl in TOP_SLEEVES:
        if sl.base == "s6":
            ref_df = ref_data["s6"]
        elif sl.base == "s15":
            ref_df = ref_data["s15"]
        elif sl.base == "v15m":
            ref_df = ref_data["v15m"]
        else:
            ref_df = ref_data["s6"]
        ref_df = ref_df.copy()
        if "tf" not in ref_df.columns:
            ref_df["tf"] = sl.tf
        if sl.tf == "5m":
            oos_df = oos_5m
        else:
            oos_df = oos_15m
        if oos_df is not None and len(oos_df) > 0:
            oos_filtered = oos_df[(oos_df["tf"] == sl.tf) & (oos_df["asset"] == sl.asset)]
            full_df = pd.concat([ref_df, oos_filtered], ignore_index=True)
            full_df = full_df.drop_duplicates(["slug", "fire_us", "direction"], keep="first")
        else:
            full_df = ref_df
        stab = rolling_stability(full_df, sl)
        if not stab.empty:
            stab["sleeve_id"] = sl.sleeve_id
            stab_rows.append(stab)
    if stab_rows:
        stab_all = pd.concat(stab_rows, ignore_index=True)
        stab_all.to_csv(OOS_DIR / "sleeve_weekly_stability.csv", index=False)
        print(f"wrote {OOS_DIR}/sleeve_weekly_stability.csv ({len(stab_all)} rows)")

    print(f"\n[main] total runtime {(time.time()-t_start)/60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
