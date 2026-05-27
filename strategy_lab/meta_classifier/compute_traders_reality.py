"""Compute 'Traders Reality Main' (TradingView) features on 1s binance OHLCV.

Output: data/v4/canonical/_results/traders_reality_1s.parquet

Schema (one row per (asset, ts_us)):
  asset, ts_us, close,
  # EMA stack (5/13/50/200/800) and cloud:
  ema_5, ema_13, ema_50, ema_200, ema_800,
  ema_cloud_size, ema_cloud_upper, ema_cloud_lower, ema_cloud_pos,
  tr_ema_stack_bull, tr_ema_stack_bear, tr_ema_stack_score,
  tr_close_vs_ema50, tr_close_vs_ema200, tr_close_vs_ema800,  # bps
  # PVSRA candles:
  tr_pvsra,                       # int: 2=climax_up, -2=climax_dn, 1=rising_up, -1=rising_dn, 0=regular
  tr_bars_since_climax_up,
  tr_bars_since_climax_dn,
  # Daily/weekly anchors (yesterday's complete day H/L/O/C):
  dayHigh, dayLow, dayOpen, dayClose,
  weekHigh, weekLow,
  PP, R1, R2, R3, S1, S2, S3,
  M0, M1, M2, M3, M4, M5,
  adr, adr_high, adr_low, awr, awr_high, awr_low,
  tr_close_vs_PP, tr_close_vs_R1, tr_close_vs_S1, ... (bps signed),
  tr_above_pp, tr_within_adr,
  tr_close_vs_dayopen,           # bps signed vs today's daily open (== prior day close at midnight)
  # Sessions:
  tr_in_london, tr_in_ny, tr_in_tokyo, tr_in_hk, tr_in_sydney,
  tr_eu_brinks, tr_us_brinks, tr_active_session_count,
  # PsyLevels:
  psy_hi, psy_lo, tr_close_vs_psy_hi, tr_close_vs_psy_lo
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
KL1S = ROOT / "data" / "v4" / "canonical" / "klines_1s" / "binance_1s_28d.parquet"
OUT = ROOT / "data" / "v4" / "canonical" / "_results" / "traders_reality_1s.parquet"

SYM_MAP = {
    "BINANCE_SPOT_BTC_USDT": "BTC",
    "BINANCE_SPOT_ETH_USDT": "ETH",
    "BINANCE_SPOT_SOL_USDT": "SOL",
}

US_PER_S = 1_000_000
US_PER_DAY = 86_400 * US_PER_S
US_PER_WEEK = 7 * US_PER_DAY


def _bps(num, denom):
    """Signed bps. num and denom 1-D arrays/Series of same shape."""
    denom = np.where(np.abs(denom) < 1e-12, np.nan, denom)
    return (num / denom) * 10000.0


def _bars_since_flag(flag: np.ndarray) -> np.ndarray:
    """For each index i, count bars since the most recent True in flag (inclusive at fire).
    Returns int32 array (0 at hit, increments by 1, NaN/-1 before first hit)."""
    n = len(flag)
    out = np.full(n, -1, dtype=np.int32)
    cnt = -1
    for i in range(n):
        if flag[i]:
            cnt = 0
        elif cnt >= 0:
            cnt += 1
        out[i] = cnt
    return out


def compute_pvsra(df: pd.DataFrame, out: pd.DataFrame) -> None:
    """PVSRA classification using rolling vol and spread*vol."""
    vol = df["volume_traded"].fillna(0.0).values
    high = df["price_high"].values
    low = df["price_low"].values
    open_ = df["price_open"].values
    close = df["price_close"].values

    # SMA(vol, 10)
    vol_s = pd.Series(vol)
    sma_vol_10 = vol_s.rolling(10, min_periods=10).mean().values
    spread = (high - low)
    sv = spread * vol
    sv_s = pd.Series(sv)
    sv_max_10 = sv_s.rolling(10, min_periods=10).max().values

    # Avoid spurious climax when vol is 0
    climax = (vol >= 2.0 * sma_vol_10) | (sv >= sv_max_10)
    climax = np.where(np.isfinite(sma_vol_10) & np.isfinite(sv_max_10), climax, False)
    rising = (vol >= 1.5 * sma_vol_10) & (~climax)
    rising = np.where(np.isfinite(sma_vol_10), rising, False)

    bull = close > open_
    bear = close < open_

    # encode int
    pvsra = np.zeros(len(df), dtype=np.int8)
    pvsra[climax & bull] = 2
    pvsra[climax & bear] = -2
    pvsra[rising & bull] = 1
    pvsra[rising & bear] = -1
    out["tr_pvsra"] = pvsra

    out["tr_bars_since_climax_up"] = _bars_since_flag(pvsra == 2)
    out["tr_bars_since_climax_dn"] = _bars_since_flag(pvsra == -2)


def compute_ema_stack(df: pd.DataFrame, out: pd.DataFrame) -> None:
    close = df["price_close"]
    # ewm — adjust=False, min_periods=span
    spans = [5, 13, 50, 200, 800]
    emas = {}
    for s in spans:
        e = close.ewm(span=s, adjust=False, min_periods=s).mean()
        emas[s] = e.values
        out[f"ema_{s}"] = e.values

    # 50-EMA cloud
    stdev_100 = close.rolling(100, min_periods=100).std().values
    cloud_size = stdev_100 / 4.0
    cloud_upper = emas[50] + cloud_size
    cloud_lower = emas[50] - cloud_size
    span = (cloud_upper - cloud_lower)
    span = np.where(span < 1e-12, np.nan, span)
    cloud_pos = (close.values - cloud_lower) / span
    out["ema_cloud_size"] = cloud_size
    out["ema_cloud_upper"] = cloud_upper
    out["ema_cloud_lower"] = cloud_lower
    out["ema_cloud_pos"] = cloud_pos

    # Stack alignment
    e5, e13, e50, e200, e800 = emas[5], emas[13], emas[50], emas[200], emas[800]
    bull_full = (e5 > e13) & (e13 > e50) & (e50 > e200) & (e200 > e800)
    bear_full = (e5 < e13) & (e13 < e50) & (e50 < e200) & (e200 < e800)
    out["tr_ema_stack_bull"] = bull_full.astype(np.int8)
    out["tr_ema_stack_bear"] = bear_full.astype(np.int8)

    # Score: −2..+2 from consecutive bull pairs minus consecutive bear pairs from top of stack.
    # We adopt: score = (sum of bull-pair count from start until first non-bull pair)
    #         − (sum of bear-pair count from start until first non-bear pair).
    # Pairs: e5>e13, e13>e50, e50>e200, e200>e800  → 4 pairs.
    # We want range −2..+2 so clip after summing.
    bull_pairs = np.stack([e5 > e13, e13 > e50, e50 > e200, e200 > e800], axis=1)
    bear_pairs = np.stack([e5 < e13, e13 < e50, e50 < e200, e200 < e800], axis=1)

    # consecutive count from top
    def _consec(mask2d):
        # Count consecutive True from column 0 onward.
        n = mask2d.shape[0]
        out_arr = np.zeros(n, dtype=np.int16)
        for k in range(mask2d.shape[1]):
            col = mask2d[:, k]
            if k == 0:
                out_arr = col.astype(np.int16)
            else:
                out_arr = np.where((out_arr == k) & col, out_arr + 1, out_arr)
        return out_arr

    bull_consec = _consec(bull_pairs)
    bear_consec = _consec(bear_pairs)
    score = (bull_consec - bear_consec).clip(-2, 2).astype(np.int8)
    out["tr_ema_stack_score"] = score

    # close vs EMAs (bps)
    cl = close.values
    out["tr_close_vs_ema50"] = _bps(cl - e50, e50)
    out["tr_close_vs_ema200"] = _bps(cl - e200, e200)
    out["tr_close_vs_ema800"] = _bps(cl - e800, e800)


def compute_daily_weekly(df: pd.DataFrame, out: pd.DataFrame) -> None:
    """Build daily and weekly H/L/O/C from 1s, then forward-fill to per-1s row.
    For any 1s bar in day D, attach yesterday (D-1) H/L/O/C."""
    ts_us = df["time_period_start_us"].values.astype(np.int64)
    high = df["price_high"].values
    low = df["price_low"].values
    open_ = df["price_open"].values
    close = df["price_close"].values

    # Daily bucket index: floor(ts_us / US_PER_DAY)
    day_bucket = (ts_us // US_PER_DAY).astype(np.int64)

    g = pd.DataFrame({"day": day_bucket, "h": high, "l": low, "o": open_, "c": close})
    daily = g.groupby("day", sort=True).agg(dayH=("h", "max"), dayL=("l", "min"),
                                            dayO=("o", "first"), dayC=("c", "last")).reset_index()
    # Use PRIOR day's H/L/O/C → shift by 1
    daily["dayHigh"] = daily["dayH"].shift(1)
    daily["dayLow"] = daily["dayL"].shift(1)
    daily["dayOpen"] = daily["dayO"].shift(1)
    daily["dayClose"] = daily["dayC"].shift(1)

    # Weekly bucket. Crypto week conventionally starts Sat 22:00 UTC for psy levels.
    # Use plain ISO-week (Mon 00:00 UTC) for week H/L: simpler, common in TR.
    week_bucket = ((ts_us - 4 * US_PER_DAY) // US_PER_WEEK).astype(np.int64)
    gw = pd.DataFrame({"week": week_bucket, "h": high, "l": low})
    weekly = gw.groupby("week", sort=True).agg(wH=("h", "max"), wL=("l", "min")).reset_index()
    weekly["weekHigh"] = weekly["wH"].shift(1)
    weekly["weekLow"] = weekly["wL"].shift(1)

    # ADR/AWR: rolling 14d / 4w mean(H-L). Use prior-day H-L (already daily.dayH/dayL).
    daily["dHL"] = daily["dayH"] - daily["dayL"]
    daily["adr"] = daily["dHL"].rolling(14, min_periods=5).mean().shift(1)
    weekly["wHL"] = weekly["wH"] - weekly["wL"]
    weekly["awr"] = weekly["wHL"].rolling(4, min_periods=2).mean().shift(1)

    # Map daily back to 1s row
    daily_map = daily.set_index("day")[["dayHigh", "dayLow", "dayOpen", "dayClose", "adr"]]
    row_day = daily_map.reindex(day_bucket).values
    out["dayHigh"] = row_day[:, 0]
    out["dayLow"] = row_day[:, 1]
    out["dayOpen"] = row_day[:, 2]
    out["dayClose"] = row_day[:, 3]
    out["adr"] = row_day[:, 4]

    weekly_map = weekly.set_index("week")[["weekHigh", "weekLow", "awr"]]
    row_week = weekly_map.reindex(week_bucket).values
    out["weekHigh"] = row_week[:, 0]
    out["weekLow"] = row_week[:, 1]
    out["awr"] = row_week[:, 2]

    # Pivots
    dH = out["dayHigh"].values
    dL = out["dayLow"].values
    dC = out["dayClose"].values
    dO = out["dayOpen"].values
    PP = (dH + dL + dC) / 3.0
    R1 = 2.0 * PP - dL
    S1 = 2.0 * PP - dH
    R2 = PP - S1 + R1
    S2 = PP - R1 + S1
    R3 = 2.0 * PP + dH - 2.0 * dL
    S3 = 2.0 * PP - (2.0 * dH - dL)
    out["PP"] = PP
    out["R1"] = R1
    out["S1"] = S1
    out["R2"] = R2
    out["S2"] = S2
    out["R3"] = R3
    out["S3"] = S3
    out["M0"] = (S2 + S3) / 2.0
    out["M1"] = (S1 + S2) / 2.0
    out["M2"] = (PP + S1) / 2.0
    out["M3"] = (PP + R1) / 2.0
    out["M4"] = (R1 + R2) / 2.0
    out["M5"] = (R2 + R3) / 2.0

    adr = out["adr"].values
    awr = out["awr"].values
    out["adr_high"] = dO + adr
    out["adr_low"] = dO - adr
    out["awr_high"] = dO + awr
    out["awr_low"] = dO - awr

    # Distances in bps from close
    cl = close
    levels = ["PP", "R1", "R2", "R3", "S1", "S2", "S3",
              "M0", "M1", "M2", "M3", "M4", "M5",
              "adr_high", "adr_low", "awr_high", "awr_low",
              "dayHigh", "dayLow", "weekHigh", "weekLow"]
    for lv in levels:
        out[f"tr_close_vs_{lv}"] = _bps(cl - out[lv].values, out[lv].values)
    out["tr_above_pp"] = (cl > PP).astype(np.int8)
    out["tr_within_adr"] = ((cl >= out["adr_low"].values) & (cl <= out["adr_high"].values)).astype(np.int8)
    out["tr_close_vs_dayopen"] = _bps(cl - dO, dO)


def compute_sessions(df: pd.DataFrame, out: pd.DataFrame) -> None:
    ts_s = (df["time_period_start_us"].values // US_PER_S).astype(np.int64)
    # hour in UTC
    hour = ((ts_s // 3600) % 24).astype(np.int16)

    in_london = (hour >= 7) & (hour <= 16)
    in_ny = (hour >= 13) & (hour <= 21)
    in_tokyo = (hour >= 0) & (hour <= 6)
    in_hk = (hour >= 1) & (hour <= 8)
    in_sydney = (hour >= 22) | (hour <= 5)
    eu_brinks = (hour == 7)
    us_brinks = (hour >= 13) & (hour <= 14)
    active = (in_london.astype(np.int8) + in_ny.astype(np.int8) +
              in_tokyo.astype(np.int8) + in_hk.astype(np.int8) +
              in_sydney.astype(np.int8))

    out["tr_in_london"] = in_london.astype(np.int8)
    out["tr_in_ny"] = in_ny.astype(np.int8)
    out["tr_in_tokyo"] = in_tokyo.astype(np.int8)
    out["tr_in_hk"] = in_hk.astype(np.int8)
    out["tr_in_sydney"] = in_sydney.astype(np.int8)
    out["tr_eu_brinks"] = eu_brinks.astype(np.int8)
    out["tr_us_brinks"] = us_brinks.astype(np.int8)
    out["tr_active_session_count"] = active


def compute_psy(df: pd.DataFrame, out: pd.DataFrame) -> None:
    """PsyLevels: weekly high/low reset each Saturday 22:00 UTC.
    For each 1s bar, psy_hi = running max(high) since last Sat 22 UTC,
    psy_lo = running min(low) since same. Reset means: when a new psy week starts,
    the *current* psy_hi/psy_lo is what we expose for the rest of the week.
    But TR convention: psy_hi/psy_lo = extremes of the LAST COMPLETE psy week.
    So at any 1s bar in psy-week W, expose extremes of psy-week W-1."""
    ts_us = df["time_period_start_us"].values.astype(np.int64)
    high = df["price_high"].values
    low = df["price_low"].values

    # Define psy week index: anchor = Sat 22:00 UTC.
    # Unix epoch 1970-01-01 was Thursday. Sat 22 UTC means (5*86400 + 22*3600) seconds
    # from epoch midnight Thursday → 5d22h = 511200s. Use offset.
    PSY_OFFSET_S = 5 * 86400 + 22 * 3600
    psy_week = ((ts_us // US_PER_S - PSY_OFFSET_S) // (7 * 86400)).astype(np.int64)
    gp = pd.DataFrame({"pw": psy_week, "h": high, "l": low})
    pw_agg = gp.groupby("pw", sort=True).agg(pwH=("h", "max"), pwL=("l", "min")).reset_index()
    pw_agg["psy_hi"] = pw_agg["pwH"].shift(1)
    pw_agg["psy_lo"] = pw_agg["pwL"].shift(1)
    pw_map = pw_agg.set_index("pw")[["psy_hi", "psy_lo"]]
    row_pw = pw_map.reindex(psy_week).values
    out["psy_hi"] = row_pw[:, 0]
    out["psy_lo"] = row_pw[:, 1]

    cl = df["price_close"].values
    out["tr_close_vs_psy_hi"] = _bps(cl - out["psy_hi"].values, out["psy_hi"].values)
    out["tr_close_vs_psy_lo"] = _bps(cl - out["psy_lo"].values, out["psy_lo"].values)


def compute_per_asset(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("time_period_start_us").reset_index(drop=True)
    out = pd.DataFrame({
        "ts_us": df["time_period_start_us"].values.astype("int64"),
        "close": df["price_close"].values,
    })
    compute_ema_stack(df, out)
    compute_pvsra(df, out)
    compute_daily_weekly(df, out)
    compute_sessions(df, out)
    compute_psy(df, out)
    return out


def main():
    print(f"[1] loading 1s binance {KL1S.name}...")
    t0 = time.time()
    df = pd.read_parquet(KL1S)
    print(f"    {len(df):,} rows in {time.time()-t0:.1f}s")

    df = df.sort_values(["symbol_id", "time_period_start_us", "source"])
    df = df.drop_duplicates(["symbol_id", "time_period_start_us"], keep="last")
    df["asset"] = df["symbol_id"].map(SYM_MAP)
    df = df[df["asset"].notna()].copy()
    print(f"    after dedupe: {len(df):,}  per-asset: {df.asset.value_counts().to_dict()}")

    parts = []
    for asset in ("BTC", "ETH", "SOL"):
        t0 = time.time()
        sub = df[df["asset"] == asset]
        ind = compute_per_asset(sub)
        ind["asset"] = asset
        cols = ["asset", "ts_us"] + [c for c in ind.columns if c not in ("asset", "ts_us")]
        ind = ind[cols]
        print(f"    {asset}: {len(ind):,} bars in {time.time()-t0:.1f}s")
        parts.append(ind)

    all_ind = pd.concat(parts, ignore_index=True)
    all_ind = all_ind.sort_values(["asset", "ts_us"]).reset_index(drop=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    print(f"[2] writing {OUT}...")
    all_ind.to_parquet(OUT, index=False, compression="zstd")
    print(f"    wrote {os.path.getsize(OUT)/1024/1024:.1f} MB  rows={len(all_ind):,}")

    print("\n[3] BTC sanity — last 5 rows with stack & pvsra & PP:")
    sample = all_ind[all_ind.asset == "BTC"].tail(5)
    cols_show = ["ts_us", "close", "ema_5", "ema_13", "ema_50", "ema_200", "ema_800",
                 "tr_ema_stack_score", "tr_ema_stack_bull", "tr_pvsra",
                 "PP", "tr_close_vs_PP", "tr_in_london", "tr_in_ny"]
    print(sample[cols_show].to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
