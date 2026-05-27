"""HL feature panel builder — port of Polymarket research stack to HL/Binance kline data.

Outputs per (asset, timeframe, source):
  strategy_lab/hl_research_2026_05_26/panels/hl_panel_{ASSET}_{TF}.parquet
  strategy_lab/hl_research_2026_05_26/panels/hl_native_panel_{ASSET}_{TF}.parquet

Causal contract:
  - All features computed at bar i depend only on bars <= i.
  - Convention: signal computed at bar CLOSE of bar i; consumed at bar i+1 open.
  - For HL-extra joins (funding/liq), we asof-merge with direction='backward'.

Indicator families:
  classic_ta:   rsi_14, atr_14, adx_14, +DI/-DI, stoch, BB, MFI, CCI
  ema_basic:    ema_5/13/21/50/100/200/800
  madrid:       20 EMAs spanning 5-100, ribbon_color, lead_slope, alignment, compression
  qr:           Quantum Ribbon Lite — qr_state/regime/health/confidence/volume_ratio
  sms:          BOS/CHoCH, liquidity_up/dn, RSI div, CVD tiers, multi-TF trend
  tr:           Traders Reality — EMA stack, PVSRA, daily pivots, Camarilla, sessions, psy, ADR/AWR
  rf:           Donovan Wall Range Filter — rf_close/hi/lo/dir/age/band_pos/in_band/aged/fresh
  regime:       3-state regime_label (trending_up/dn/ranging) + regime_score
  markov:       3-state markov_state (vol-adaptive q33/q66) + fixed-threshold variant
  drz:          Delta Reaction Zones — in_support/resistance, dist_bps, recent_RC/RE
  hl_extra:     hl_funding_rate, hl_funding_annualized, hl_funding_z,
                hl_liq_long/short_sum_60m, hl_liq_cascade_60m, hl_oi

Usage:
  py strategy_lab/hl_research_2026_05_26/build_hl_panel.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import talib  # type: ignore
    HAVE_TALIB = True
except Exception:
    HAVE_TALIB = False

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
OUT_DIR = ROOT / "strategy_lab" / "hl_research_2026_05_26" / "panels"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TF_TO_BINANCE_DIR = {"5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d", "1m": "1m"}
TF_TO_HL_PERIOD = {
    "1m": "1MIN", "5m": "5MIN", "15m": "15MIN",
    "1h": "1HRS", "4h": "4HRS", "1d": "1DAY",
}
TF_TO_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
TF_TO_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}

# Asset -> Binance USDT symbol
ASSET_TO_BINANCE = {
    "BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT",
    "BNB": "BNBUSDT", "ADA": "ADAUSDT", "AVAX": "AVAXUSDT",
    "DOGE": "DOGEUSDT", "LINK": "LINKUSDT", "XRP": "XRPUSDT",
    "SUI": "SUIUSDT", "TON": "TONUSDT",
}
# Asset -> HL symbol_id
ASSET_TO_HL = lambda a: f"HYPERLIQUID_PERP_{a.upper()}_USD"

# Madrid ribbon — 20 EMAs spaced 5
MADRID_EMA_PERIODS = list(range(5, 105, 5))  # 5,10,...,100

# Quantum Ribbon Lite layers (short, long)
QR_LAYERS = [(21, 28), (29, 36), (37, 44), (45, 52), (53, 60)]
QR_ALIGN_W = np.array([1.0, 1.2, 1.4, 1.6, 2.0])

# TR EMA stack spans
TR_EMA_SPANS = [5, 13, 50, 200, 800]

# Markov asset-specific fixed thresholds (log-return scale)
MARKOV_FIXED_THR = {"BTC": 0.003, "ETH": 0.004, "SOL": 0.006, "HYPE": 0.008}

# DRZ params
DRZ_DELTA_SMOOTH = 3
DRZ_PIVOT_LB = 12
DRZ_ATR_LEN = 14
DRZ_ZONE_ATR_MULT = 0.35
DRZ_IMPULSE_WIN = 100
DRZ_RECLAIM_WIN = 5

# SMS params
SMS_PIVOT_LB = 5
SMS_RSI_LEN = 14
SMS_LIQ_LB = 20
SMS_LIQ_TOL = 0.0005

# Regime / ADX threshold
REGIME_ADX_MIN = 25.0
REGIME_ALIGN_MIN = 70.0


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def load_binance_klines(sym: str, tf: str, start: pd.Timestamp | None = None,
                        end: pd.Timestamp | None = None) -> pd.DataFrame:
    """Load Binance spot klines for `sym` (e.g. BTCUSDT) at `tf`.

    Returns DataFrame indexed by RangeIndex with columns:
      ts_us (int64), open_time (UTC), open, high, low, close, volume,
      quote_volume, trades, taker_buy_base, taker_buy_quote.
    Sorted by open_time ascending. Deduped.
    """
    base = ROOT / "data" / "binance" / "parquet" / sym / tf
    if not base.exists():
        raise FileNotFoundError(f"missing binance parquet dir: {base}")
    parts = []
    for ydir in sorted(base.glob("year=*")):
        p = ydir / "part.parquet"
        if not p.exists():
            continue
        parts.append(pd.read_parquet(p))
    if not parts:
        raise RuntimeError(f"no binance year= parquet for {sym}/{tf}")
    df = pd.concat(parts, ignore_index=True)
    df = df.sort_values("open_time").drop_duplicates("open_time").reset_index(drop=True)
    if start is not None:
        df = df[df["open_time"] >= start]
    if end is not None:
        df = df[df["open_time"] <= end]
    df["ts_us"] = (df["open_time"].astype("int64") // 1000).astype("int64")
    df = df.reset_index(drop=True)
    return df


def load_hl_klines(asset: str, tf: str, start: pd.Timestamp | None = None,
                    end: pd.Timestamp | None = None) -> pd.DataFrame:
    """Load HL klines parquet, filter to (asset, period_id) and normalize cols.

    Returns DataFrame with cols: ts_us, open_time, open, high, low, close, volume, trades.
    """
    p = ROOT / "data" / "v4" / "canonical" / "hyperliquid_klines.parquet"
    sym_id = ASSET_TO_HL(asset)
    period_id = TF_TO_HL_PERIOD[tf]
    df = pd.read_parquet(p)
    df = df[(df["symbol_id"] == sym_id) & (df["period_id"] == period_id)].copy()
    df = df.sort_values("time_period_start_us").drop_duplicates("time_period_start_us").reset_index(drop=True)
    if df.empty:
        return df
    df["ts_us"] = df["time_period_start_us"].astype("int64")
    df["open_time"] = pd.to_datetime(df["ts_us"], unit="us", utc=True)
    df = df.rename(columns={
        "price_open": "open", "price_high": "high",
        "price_low": "low", "price_close": "close",
        "volume_traded": "volume", "trades_count": "trades",
    })
    if start is not None:
        df = df[df["open_time"] >= start]
    if end is not None:
        df = df[df["open_time"] <= end]
    df = df.reset_index(drop=True)
    return df[["ts_us", "open_time", "open", "high", "low", "close", "volume", "trades"]]


def load_hl_funding(asset: str) -> pd.DataFrame:
    """Hourly HL funding for `asset`."""
    p = ROOT / "data" / "v4" / "canonical" / "hyperliquid_funding.parquet"
    df = pd.read_parquet(p)
    df = df[df["symbol"] == asset].copy()
    if df.empty:
        return df
    df["funding_rate"] = pd.to_numeric(df["funding_rate"], errors="coerce")
    df["premium"] = pd.to_numeric(df["premium"], errors="coerce")
    df["ts_us"] = df["funding_time_us"].astype("int64")
    df = df.sort_values("ts_us").drop_duplicates("ts_us").reset_index(drop=True)
    return df[["ts_us", "funding_rate", "premium"]]


def load_hl_liqs(asset: str) -> pd.DataFrame:
    """HL liquidations (use _30d). Filter to `asset` coin, return signed long/short notional."""
    p = ROOT / "data" / "v4" / "canonical" / "hyperliquid_liquidations_30d.parquet"
    df = pd.read_parquet(p, columns=["time_exchange_us", "coin", "side", "dir", "price", "size"])
    df = df[df["coin"] == asset].copy()
    if df.empty:
        return df
    df["notional"] = df["price"] * df["size"]
    df["is_long_liq"] = df["dir"].astype(str).str.contains("Liquidated.*Long|Auto-Deleveraging.*Long", regex=True, na=False)
    df["is_short_liq"] = df["dir"].astype(str).str.contains("Liquidated.*Short|Auto-Deleveraging.*Short", regex=True, na=False)
    # Fallback: any "Liquidated" row counts as a liq event
    df["is_liq_event"] = df["dir"].astype(str).str.startswith("Liquidated") | df["dir"].astype(str).str.startswith("Auto-Deleveraging")
    df["ts_us"] = df["time_exchange_us"].astype("int64")
    df = df.sort_values("ts_us").reset_index(drop=True)
    return df[["ts_us", "side", "dir", "price", "size", "notional",
               "is_long_liq", "is_short_liq", "is_liq_event"]]


def load_binance_futures_metrics(sym: str) -> pd.DataFrame:
    """Load 5-min futures metrics (OI, taker L/S) — concatenate all year= partitions."""
    base = ROOT / "data" / "binance" / "futures" / "metrics" / sym / "parquet"
    if not base.exists():
        return pd.DataFrame()
    parts = []
    for ydir in sorted(base.glob("year=*")):
        p = ydir / "part.parquet"
        if p.exists():
            parts.append(pd.read_parquet(p))
    if not parts:
        return pd.DataFrame()
    df = pd.concat(parts, ignore_index=True)
    df = df.sort_values("create_time").drop_duplicates("create_time").reset_index(drop=True)
    df["ts_us"] = (df["create_time"].astype("int64") // 1000).astype("int64")
    return df


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ewm(x: pd.Series, span: int) -> pd.Series:
    return x.ewm(span=span, adjust=False, min_periods=span).mean()


def _bps(num, denom):
    denom_arr = np.asarray(denom, dtype="float64")
    denom_safe = np.where(np.abs(denom_arr) < 1e-12, np.nan, denom_arr)
    return (np.asarray(num, dtype="float64") / denom_safe) * 10000.0


def _bars_since_flag(flag) -> np.ndarray:
    n = len(flag)
    out = np.full(n, -1, dtype=np.int32)
    arr = np.asarray(flag, dtype=bool)
    cnt = -1
    for i in range(n):
        if arr[i]:
            cnt = 0
        elif cnt >= 0:
            cnt += 1
        out[i] = cnt
    return out


def _crossover(a: pd.Series, b: pd.Series) -> pd.Series:
    a_prev = a.shift(1); b_prev = b.shift(1)
    return (a > b) & (a_prev <= b_prev)


def _crossunder(a: pd.Series, b: pd.Series) -> pd.Series:
    a_prev = a.shift(1); b_prev = b.shift(1)
    return (a < b) & (a_prev >= b_prev)


def rsi_wilder(close: pd.Series, length: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0.0)
    dn = (-d).clip(lower=0.0)
    avg_up = up.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    avg_dn = dn.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    rs = avg_up / avg_dn.replace(0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def atr_wilder(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    pc = close.shift(1)
    tr = pd.concat([(high - low).abs(),
                    (high - pc).abs(),
                    (low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


def adx_wilder(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14):
    """Returns (adx, +DI, -DI) using Wilder smoothing."""
    up = high.diff()
    dn = -low.diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=high.index)
    pc = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    plus_di = 100.0 * (plus_dm.ewm(alpha=1.0/length, adjust=False, min_periods=length).mean() / atr.replace(0, np.nan))
    minus_di = 100.0 * (minus_dm.ewm(alpha=1.0/length, adjust=False, min_periods=length).mean() / atr.replace(0, np.nan))
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1.0/length, adjust=False, min_periods=length).mean()
    return adx, plus_di, minus_di


def stoch_kd(close, high, low, length=14, smooth_k=3, smooth_d=3):
    ll = low.rolling(length, min_periods=length).min()
    hh = high.rolling(length, min_periods=length).max()
    raw_k = 100.0 * (close - ll) / (hh - ll).replace(0, np.nan)
    k = raw_k.rolling(smooth_k, min_periods=1).mean()
    d = k.rolling(smooth_d, min_periods=1).mean()
    return k, d


def bb_pos_width(close, length=20, std_mult=2.0):
    mid = close.rolling(length, min_periods=length).mean()
    std = close.rolling(length, min_periods=length).std()
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    width = (upper - lower) / mid
    pos = (close - lower) / (upper - lower).replace(0, np.nan)
    return pos.clip(-0.5, 1.5), width


def mfi_calc(high, low, close, vol, length=14):
    tp = (high + low + close) / 3.0
    mf = tp * vol
    tp_diff = tp.diff()
    pos_mf = mf.where(tp_diff > 0, 0.0).rolling(length, min_periods=length).sum()
    neg_mf = mf.where(tp_diff < 0, 0.0).rolling(length, min_periods=length).sum()
    ratio = pos_mf / neg_mf.replace(0, np.nan)
    return 100.0 - 100.0 / (1.0 + ratio)


def cci_calc(close, high, low, length=20):
    tp = (high + low + close) / 3.0
    sma_tp = tp.rolling(length, min_periods=length).mean()
    mean_dev = (tp - sma_tp).abs().rolling(length, min_periods=length).mean()
    return (tp - sma_tp) / (0.015 * mean_dev.replace(0, np.nan))


# ---------------------------------------------------------------------------
# Family: classic TA + EMA basic
# ---------------------------------------------------------------------------

def add_classic_ta(df: pd.DataFrame) -> None:
    """Mutates df in-place."""
    close = df["close"]; high = df["high"]; low = df["low"]; vol = df["volume"].fillna(0)
    df["rsi_14"] = rsi_wilder(close, 14)
    df["atr_14"] = atr_wilder(high, low, close, 14)
    adx, pdi, mdi = adx_wilder(high, low, close, 14)
    df["adx_14"] = adx
    df["plus_di_14"] = pdi
    df["minus_di_14"] = mdi
    k, d = stoch_kd(close, high, low, length=14, smooth_k=3, smooth_d=3)
    df["stoch_k_14"] = k
    df["stoch_d_3"] = d
    bb_pos, bb_w = bb_pos_width(close, length=20, std_mult=2.0)
    df["bb_pos_20"] = bb_pos
    df["bb_width_20"] = bb_w
    df["mfi_14"] = mfi_calc(high, low, close, vol, length=14)
    df["cci_20"] = cci_calc(close, high, low, length=20)


def add_basic_emas(df: pd.DataFrame) -> None:
    """Mutates df in-place with ema_5/13/21/50/100/200/800."""
    close = df["close"]
    for span in (5, 13, 21, 50, 100, 200, 800):
        df[f"ema_{span}"] = _ewm(close, span)


# ---------------------------------------------------------------------------
# Family: Madrid ribbon
# ---------------------------------------------------------------------------

def add_madrid_ribbon(df: pd.DataFrame) -> None:
    """Mutates df: ribbon_lead_slope_bps, ribbon_lead_vs_ref_bps, ribbon_alignment_pct,
    ribbon_compression_bps, ribbon_color (0=gray, 1=lime, 2=maroon, 3=red, 4=green),
    tight_ribbon (bool: compression < 2bps)."""
    close = df["close"]
    ema_matrix = []
    for p in MADRID_EMA_PERIODS:
        e = _ewm(close, p)
        ema_matrix.append(e.values)
    ema_matrix = np.array(ema_matrix)  # (20, N)
    ema_5_arr = ema_matrix[0]
    ema_100_arr = ema_matrix[-1]
    lead_slope = pd.Series(ema_5_arr).diff(5)
    df["ribbon_lead_slope_bps"] = (lead_slope.values / ema_5_arr) * 10000.0
    df["ribbon_lead_vs_ref_bps"] = ((ema_5_arr - ema_100_arr) / ema_100_arr) * 10000.0
    in_order = np.zeros(ema_matrix.shape[1], dtype=np.int16)
    for i in range(len(MADRID_EMA_PERIODS) - 1):
        in_order += (ema_matrix[i] > ema_matrix[i + 1]).astype(np.int16)
    df["ribbon_alignment_pct"] = (in_order / (len(MADRID_EMA_PERIODS) - 1)) * 100.0
    mean_emas = ema_matrix.mean(axis=0)
    std_emas = ema_matrix.std(axis=0)
    df["ribbon_compression_bps"] = (std_emas / np.where(mean_emas == 0, np.nan, mean_emas)) * 10000.0
    slope_pos = (lead_slope >= 0).values
    above_ref = (ema_5_arr > ema_100_arr)
    color = np.zeros(len(df), dtype=np.int8)
    color[slope_pos & above_ref] = 1   # lime
    color[(~slope_pos) & above_ref] = 2  # maroon
    color[(~slope_pos) & (~above_ref)] = 3  # red
    color[slope_pos & (~above_ref)] = 4  # green
    df["ribbon_color"] = color
    df["tight_ribbon"] = (df["ribbon_compression_bps"] < 2.0).astype(np.int8)


# ---------------------------------------------------------------------------
# Family: Quantum Ribbon Lite
# ---------------------------------------------------------------------------

def add_qr_panel(df: pd.DataFrame) -> None:
    """Mutates df: qr_state(-2..+2), qr_regime(0/1), qr_health(0..100),
    qr_confidence(0..8), qr_volume_ratio."""
    close = df["close"].astype("float64")
    vol = df["volume"].astype("float64").fillna(0.0)
    emas_s = {}
    emas_l = {}
    for i, (s, l) in enumerate(QR_LAYERS, start=1):
        emas_s[i] = _ewm(close, s).values
        emas_l[i] = _ewm(close, l).values
    ms = np.column_stack([emas_s[i] for i in range(1, 6)])
    ml = np.column_stack([emas_l[i] for i in range(1, 6)])
    bull_mask = (ms >= ml)
    bear_mask = (ms < ml)
    bull_score = (bull_mask * QR_ALIGN_W).sum(axis=1)
    bear_score = (bear_mask * QR_ALIGN_W).sum(axis=1)
    total = bull_score + bear_score
    bull_align = np.where(total > 0, bull_score / np.where(total == 0, 1, total), 0.5)
    state = np.zeros(len(df), dtype=np.int8)
    state[bull_align >= 0.75] = 2
    state[(bull_align >= 0.60) & (bull_align < 0.75)] = 1
    state[(bull_align > 0.40) & (bull_align < 0.60)] = 0
    state[(bull_align > 0.25) & (bull_align <= 0.40)] = -1
    state[bull_align <= 0.25] = -2
    df["qr_state"] = state
    bullish_emas = bull_mask.sum(axis=1)
    bearish_emas = bear_mask.sum(axis=1)
    ribbon_aligned = ((bullish_emas >= 4) | (bearish_emas >= 4)).astype(np.int8)
    spread = np.abs(emas_s[1] - emas_l[5])
    past_spread = np.roll(spread, 10).astype("float64")
    past_spread[:10] = np.nan
    ribbon_expanding = (spread > past_spread * 0.9).astype(np.int8)
    ribbon_expanding[~np.isfinite(past_spread)] = 0
    ribbon_center = (emas_s[1] + emas_l[5]) / 2.0
    above_ind = (close.values > ribbon_center).astype(np.int8)
    below_ind = (close.values < ribbon_center).astype(np.int8)
    bars_above = pd.Series(above_ind).rolling(10, min_periods=10).sum().values
    bars_below = pd.Series(below_ind).rolling(10, min_periods=10).sum().values
    price_consistent = ((bars_above >= 8) | (bars_below >= 8)).astype(np.int8)
    price_consistent = np.where(np.isnan(bars_above) | np.isnan(bars_below), 0, price_consistent)
    qr_regime = ((ribbon_aligned == 1) & (price_consistent == 1) & (ribbon_expanding == 1)).astype(np.int8)
    df["qr_regime"] = qr_regime
    alignment_strength = np.maximum(bullish_emas, bearish_emas)
    h_align = np.where(alignment_strength == 5, 40, np.where(alignment_strength == 4, 30, 20))
    h_regime = np.where(qr_regime == 1, 30, 15)
    vol_sma20 = vol.rolling(20, min_periods=20).mean()
    volume_ratio = (vol / vol_sma20.replace(0, np.nan)).fillna(0)
    df["qr_volume_ratio"] = volume_ratio.values
    h_vol = np.where(volume_ratio.values > 1.1, 20, 10)
    avg_spacing = (np.abs(emas_s[1] - emas_l[1]) + np.abs(emas_s[5] - emas_l[5])) / 2.0
    normalized = np.where(close.values > 0, avg_spacing / close.values * 100.0, 0.0)
    h_spacing = np.where(normalized > 1.0, 10, np.where(normalized > 0.5, 5, 0))
    health = (h_align + h_regime + h_vol + h_spacing).astype("float32")
    df["qr_health"] = health
    # confidence
    conf = np.zeros(len(df), dtype="float32")
    is_trending = qr_regime == 1
    conf[is_trending & (health > 80)] += 4
    conf[is_trending & (health > 70) & (health <= 80)] += 3.5
    conf[is_trending & (health > 60) & (health <= 70)] += 3
    conf[is_trending & (health <= 60)] += 2
    conf[(~is_trending) & (health > 70)] += 3
    conf[(~is_trending) & (health > 50) & (health <= 70)] += 2
    conf[(~is_trending) & (health <= 50)] += 1
    conf[volume_ratio.values > 1.3] += 1
    abs_state = np.abs(state)
    base_boost = np.where(abs_state == 2, 1.5, np.where(abs_state == 1, 0.9, 0.0))
    boost_mult = np.where(conf < 3.0, 1.5, 0.8)
    conf += base_boost * boost_mult
    conf = np.minimum(conf, 8.0)
    df["qr_confidence"] = conf


# ---------------------------------------------------------------------------
# Family: SMS (BOS, CHoCH, liquidity, RSI div, CVD, multi-TF trend)
# ---------------------------------------------------------------------------

def _rolling_pivot_centered(s: pd.Series, lb: int, kind: str) -> pd.Series:
    """At bar `i`, the bar i-lb is the pivot if its value is max/min of [i-2lb, i].
    Returns pivot VALUE at confirmation bar i (causal — lookforward complete at i)."""
    win = 2 * lb + 1
    if kind == "high":
        center_max = s.rolling(win, center=False, min_periods=win).max()
        is_pivot = (s.shift(lb) == center_max)
        return s.shift(lb).where(is_pivot)
    elif kind == "low":
        center_min = s.rolling(win, center=False, min_periods=win).min()
        is_pivot = (s.shift(lb) == center_min)
        return s.shift(lb).where(is_pivot)
    raise ValueError(kind)


def add_sms(df: pd.DataFrame, parent_df: pd.DataFrame | None = None) -> None:
    """Mutates df: pivot_high/low, bos_buy/sell, choch_buy/sell, bars_since_bos,
    liquidity_up/dn, rsi_div_bull/bear, cvd_60s/120s/300s (rolling-window CVD,
    where window is in BAR count = window_seconds / tf_seconds), trend_strength_multi_tf.

    parent_df: optional same-asset higher-TF kline (e.g. for 5m panel pass 15m bars)
    for multi-TF EMA20+VWAP coherence component.
    """
    close = df["close"]; high = df["high"]; low = df["low"]
    open_ = df["open"]; vol = df["volume"].astype("float64").fillna(0.0)

    df["pivot_high"] = _rolling_pivot_centered(high, SMS_PIVOT_LB, "high")
    df["pivot_low"] = _rolling_pivot_centered(low, SMS_PIVOT_LB, "low")
    df["last_high"] = df["pivot_high"].ffill()
    df["last_low"] = df["pivot_low"].ffill()

    # last_high_prev / last_low_prev (the prior pivot)
    n = len(df)
    lhp = np.full(n, np.nan); llp = np.full(n, np.nan)
    ph = df["pivot_high"].values; pl = df["pivot_low"].values
    cur_h = np.nan; prev_h = np.nan; cur_l = np.nan; prev_l = np.nan
    for i in range(n):
        if not np.isnan(ph[i]):
            prev_h = cur_h; cur_h = ph[i]
        if not np.isnan(pl[i]):
            prev_l = cur_l; cur_l = pl[i]
        lhp[i] = prev_h; llp[i] = prev_l
    df["last_high_prev"] = lhp
    df["last_low_prev"] = llp

    bull_body = close > open_
    bear_body = close < open_
    df["choch_sell"] = (_crossunder(low, df["last_high"]) & bear_body).fillna(False).astype(np.int8)
    df["choch_buy"] = (_crossover(high, df["last_low"]) & bull_body).fillna(False).astype(np.int8)
    df["bos_sell"] = (_crossunder(low, df["last_low_prev"]) & bear_body).fillna(False).astype(np.int8)
    df["bos_buy"] = (_crossover(high, df["last_high_prev"]) & bull_body).fillna(False).astype(np.int8)

    for col in ("bos_buy", "bos_sell", "choch_buy", "choch_sell"):
        df[f"bars_since_{col}"] = _bars_since_flag(df[col].values.astype(bool))

    # RSI divergence (5-bar pivots, same as compute_sms_panel)
    rsi = df.get("rsi_14")
    if rsi is None:
        rsi = rsi_wilder(close, length=SMS_RSI_LEN)
    low_5 = low.shift(5); low_10 = low.shift(10)
    rsi_5 = rsi.shift(5); rsi_10 = rsi.shift(10)
    df["rsi_div_bull"] = (
        (low < low_5) & (low_5 < low_10) &
        (rsi > rsi_5) & (rsi_5 > rsi_10) &
        (rsi < 40.0)
    ).fillna(False).astype(np.int8)
    high_5 = high.shift(5); high_10 = high.shift(10)
    df["rsi_div_bear"] = (
        (high > high_5) & (high_5 > high_10) &
        (rsi < rsi_5) & (rsi_5 < rsi_10) &
        (rsi > 60.0)
    ).fillna(False).astype(np.int8)

    # CVD windows: compute_sms used cumulative cvd over whole series + tier on rolling abs.
    # For HL we expose ROLLING-window CVD in 60s/120s/300s (converted to bars).
    # delta = volume signed by close-open
    sign_oc = np.where(close > open_, 1.0, np.where(close < open_, -1.0, 0.0))
    delta_vol = sign_oc * vol.values
    delta_ser = pd.Series(delta_vol)
    # Convert windows to bars given tf_minutes
    tf_min = int(df.attrs.get("tf_minutes", 5))
    for w_sec, w_label in [(60, "60s"), (120, "120s"), (300, "300s")]:
        n_bars = max(1, int(round(w_sec / 60.0 / tf_min)))
        df[f"cvd_{w_label}"] = delta_ser.rolling(n_bars, min_periods=1).sum().values

    # Liquidity zones: high tested vs recent 20-bar high (within tol), low vs recent low
    rolling_high = high.rolling(SMS_LIQ_LB, min_periods=SMS_LIQ_LB).max()
    rolling_low = low.rolling(SMS_LIQ_LB, min_periods=SMS_LIQ_LB).min()
    df["recent_high_20"] = rolling_high
    df["recent_low_20"] = rolling_low
    df["liquidity_up"] = (
        ((high - rolling_high).abs() / rolling_high.replace(0, np.nan) < SMS_LIQ_TOL)
    ).fillna(False).astype(np.int8)
    df["liquidity_dn"] = (
        ((low - rolling_low).abs() / rolling_low.replace(0, np.nan) < SMS_LIQ_TOL)
    ).fillna(False).astype(np.int8)

    # Multi-TF trend strength — current TF + parent TF (if provided)
    # Each TF contributes +1 if close > EMA20 AND close > rolling-24h-VWAP, -1 if both below, else 0.
    own_trend = _ema_vwap_trend(close, high, low, vol, tf_min)
    df["trend_self"] = own_trend
    if parent_df is not None and len(parent_df) > 5:
        parent_tf_min = int(parent_df.attrs.get("tf_minutes", tf_min * 3))
        parent_trend_series = _ema_vwap_trend(parent_df["close"], parent_df["high"],
                                              parent_df["low"], parent_df["volume"].fillna(0),
                                              parent_tf_min)
        # asof-merge backward by ts_us
        parent = pd.DataFrame({"ts_us": parent_df["ts_us"].values + TF_TO_SECONDS.get(
            _tf_label_from_minutes(parent_tf_min), parent_tf_min * 60) * 1_000_000,
                               "parent_trend": parent_trend_series.values})
        parent = parent.dropna(subset=["parent_trend"]).reset_index(drop=True)
        m = pd.merge_asof(
            df[["ts_us"]].copy().sort_values("ts_us"),
            parent.sort_values("ts_us"),
            on="ts_us", direction="backward",
        )
        df["trend_parent"] = m["parent_trend"].astype("float32").fillna(0).values
    else:
        df["trend_parent"] = 0
    df["trend_strength_multi_tf"] = (df["trend_self"].astype("float32") +
                                     df["trend_parent"].astype("float32"))


def _tf_label_from_minutes(m: int) -> str:
    for tf, mm in TF_TO_MINUTES.items():
        if mm == m:
            return tf
    return "5m"


def _ema_vwap_trend(close: pd.Series, high: pd.Series, low: pd.Series,
                    vol: pd.Series, tf_minutes: int) -> pd.Series:
    """Per-bar trend: +1 if close > EMA20 AND close > rolling-24h-VWAP, -1 if both below, else 0."""
    ema20 = _ewm(close, 20)
    hlc3 = (high + low + close) / 3.0
    bars24 = max(5, int(round(24 * 60 / tf_minutes)))
    num = (hlc3 * vol).rolling(bars24, min_periods=5).sum()
    den = vol.rolling(bars24, min_periods=5).sum()
    vwap = num / den.replace(0, np.nan)
    trend = np.where((close > ema20) & (close > vwap), 1,
            np.where((close < ema20) & (close < vwap), -1, 0))
    return pd.Series(trend, index=close.index, dtype="int8")


# ---------------------------------------------------------------------------
# Family: Traders Reality
# ---------------------------------------------------------------------------

def add_traders_reality(df: pd.DataFrame) -> None:
    """Mutates df with: tr_ema_5/13/50/200/800, tr_ema_stack_score, ema_cloud_size_bps,
    PVSRA class (-2..+2), bars_since_climax_up/dn,
    daily pivots (PP, R1-R3, S1-S3, M0-M5), close_vs_pp_bps,
    ADR/AWR, tr_within_adr, session flags, psy levels."""
    close = df["close"]; high = df["high"]; low = df["low"]
    open_ = df["open"]; vol = df["volume"].astype("float64").fillna(0.0)
    cl_arr = close.values

    # EMA stack
    spans = TR_EMA_SPANS
    emas = {}
    for s in spans:
        e = _ewm(close, s)
        emas[s] = e.values
        df[f"tr_ema_{s}"] = e.values
    e5, e13, e50, e200, e800 = emas[5], emas[13], emas[50], emas[200], emas[800]
    stdev_100 = close.rolling(100, min_periods=100).std().values
    cloud_size = stdev_100 / 4.0
    df["cloud_size_bps"] = (cloud_size / np.where(cl_arr == 0, np.nan, cl_arr)) * 10000.0
    # stack score (-2..+2): consecutive bull-pairs from top minus consecutive bear pairs
    bull_pairs = np.stack([e5 > e13, e13 > e50, e50 > e200, e200 > e800], axis=1)
    bear_pairs = np.stack([e5 < e13, e13 < e50, e50 < e200, e200 < e800], axis=1)

    def _consec(mask2d):
        n_ = mask2d.shape[0]
        out_arr = mask2d[:, 0].astype(np.int16)
        for k in range(1, mask2d.shape[1]):
            out_arr = np.where((out_arr == k) & mask2d[:, k], out_arr + 1, out_arr)
        return out_arr

    bull_consec = _consec(bull_pairs)
    bear_consec = _consec(bear_pairs)
    df["tr_ema_stack_score"] = (bull_consec - bear_consec).clip(-2, 2).astype(np.int8)

    # PVSRA
    vol_arr = vol.values
    sma_vol_10 = pd.Series(vol_arr).rolling(10, min_periods=10).mean().values
    spread = (high - low).values
    sv = spread * vol_arr
    sv_max_10 = pd.Series(sv).rolling(10, min_periods=10).max().values
    climax = (vol_arr >= 2.0 * sma_vol_10) | (sv >= sv_max_10)
    climax = np.where(np.isfinite(sma_vol_10) & np.isfinite(sv_max_10), climax, False)
    rising = (vol_arr >= 1.5 * sma_vol_10) & (~climax)
    rising = np.where(np.isfinite(sma_vol_10), rising, False)
    bull = (close > open_).values
    bear = (close < open_).values
    pvsra = np.zeros(len(df), dtype=np.int8)
    pvsra[climax & bull] = 2
    pvsra[climax & bear] = -2
    pvsra[rising & bull] = 1
    pvsra[rising & bear] = -1
    df["pvsra_class"] = pvsra
    df["bars_since_climax_up"] = _bars_since_flag(pvsra == 2)
    df["bars_since_climax_dn"] = _bars_since_flag(pvsra == -2)

    # Daily / weekly pivots (computed from a daily-resampled view of df)
    ts_us = df["ts_us"].values.astype(np.int64)
    US_DAY = 86_400 * 1_000_000
    day_bucket = (ts_us // US_DAY).astype(np.int64)
    g = pd.DataFrame({"day": day_bucket, "h": high.values, "l": low.values,
                      "o": open_.values, "c": close.values})
    daily = g.groupby("day", sort=True).agg(
        dayH=("h", "max"), dayL=("l", "min"),
        dayO=("o", "first"), dayC=("c", "last")
    ).reset_index()
    daily["dayHigh"] = daily["dayH"].shift(1)
    daily["dayLow"] = daily["dayL"].shift(1)
    daily["dayOpen"] = daily["dayO"].shift(1)
    daily["dayClose"] = daily["dayC"].shift(1)
    daily["dHL"] = daily["dayH"] - daily["dayL"]
    daily["adr"] = daily["dHL"].rolling(14, min_periods=5).mean().shift(1)
    daily_map = daily.set_index("day")[["dayHigh", "dayLow", "dayOpen", "dayClose", "adr"]]
    row_day = daily_map.reindex(day_bucket).values
    df["dayHigh"] = row_day[:, 0]
    df["dayLow"] = row_day[:, 1]
    df["dayOpen"] = row_day[:, 2]
    df["dayClose"] = row_day[:, 3]
    df["adr"] = row_day[:, 4]
    dH = df["dayHigh"].values; dL = df["dayLow"].values
    dC = df["dayClose"].values; dO = df["dayOpen"].values
    PP = (dH + dL + dC) / 3.0
    R1 = 2.0 * PP - dL
    S1 = 2.0 * PP - dH
    R2 = PP - S1 + R1
    S2 = PP - R1 + S1
    R3 = 2.0 * PP + dH - 2.0 * dL
    S3 = 2.0 * PP - (2.0 * dH - dL)
    df["PP"] = PP; df["R1"] = R1; df["S1"] = S1
    df["R2"] = R2; df["S2"] = S2; df["R3"] = R3; df["S3"] = S3
    df["M0"] = (S2 + S3) / 2.0
    df["M1"] = (S1 + S2) / 2.0
    df["M2"] = (PP + S1) / 2.0
    df["M3"] = (PP + R1) / 2.0
    df["M4"] = (R1 + R2) / 2.0
    df["M5"] = (R2 + R3) / 2.0
    df["close_vs_pp_bps"] = _bps(cl_arr - PP, PP)
    df["close_vs_dayopen_bps"] = _bps(cl_arr - dO, dO)
    df["tr_above_pp"] = (cl_arr > PP).astype(np.int8)
    df["adr_high"] = dO + df["adr"].values
    df["adr_low"] = dO - df["adr"].values
    df["tr_within_adr"] = ((cl_arr >= df["adr_low"].values) &
                            (cl_arr <= df["adr_high"].values)).astype(np.int8)

    # AWR (weekly): 4 prior weeks
    US_WEEK = 7 * US_DAY
    week_bucket = ((ts_us - 4 * US_DAY) // US_WEEK).astype(np.int64)
    gw = pd.DataFrame({"week": week_bucket, "h": high.values, "l": low.values})
    weekly = gw.groupby("week", sort=True).agg(wH=("h", "max"), wL=("l", "min")).reset_index()
    weekly["weekHigh"] = weekly["wH"].shift(1)
    weekly["weekLow"] = weekly["wL"].shift(1)
    weekly["wHL"] = weekly["wH"] - weekly["wL"]
    weekly["awr"] = weekly["wHL"].rolling(8, min_periods=2).mean().shift(1)
    weekly_map = weekly.set_index("week")[["weekHigh", "weekLow", "awr"]]
    rw = weekly_map.reindex(week_bucket).values
    df["weekHigh"] = rw[:, 0]; df["weekLow"] = rw[:, 1]; df["awr"] = rw[:, 2]

    # Sessions (UTC hours)
    ts_s = (ts_us // 1_000_000).astype(np.int64)
    hour = ((ts_s // 3600) % 24).astype(np.int16)
    df["tr_in_london"] = ((hour >= 7) & (hour <= 16)).astype(np.int8)
    df["tr_in_ny"] = ((hour >= 12) & (hour <= 21)).astype(np.int8)
    df["tr_in_tokyo"] = ((hour >= 23) | (hour <= 8)).astype(np.int8)

    # Psy levels (weekly, anchored Sat 22:00 UTC)
    PSY_OFFSET_S = 5 * 86400 + 22 * 3600
    psy_week = ((ts_s - PSY_OFFSET_S) // (7 * 86400)).astype(np.int64)
    gp = pd.DataFrame({"pw": psy_week, "h": high.values, "l": low.values})
    pw_agg = gp.groupby("pw", sort=True).agg(pwH=("h", "max"), pwL=("l", "min")).reset_index()
    pw_agg["psy_hi"] = pw_agg["pwH"].shift(1)
    pw_agg["psy_lo"] = pw_agg["pwL"].shift(1)
    pw_map = pw_agg.set_index("pw")[["psy_hi", "psy_lo"]]
    row_pw = pw_map.reindex(psy_week).values
    df["psy_hi"] = row_pw[:, 0]; df["psy_lo"] = row_pw[:, 1]
    df["close_vs_psy_hi_bps"] = _bps(cl_arr - df["psy_hi"].values, df["psy_hi"].values)
    df["close_vs_psy_lo_bps"] = _bps(cl_arr - df["psy_lo"].values, df["psy_lo"].values)
    # within psy band: between psy_lo and psy_hi
    df["within_psy_band"] = ((cl_arr >= df["psy_lo"].values) &
                              (cl_arr <= df["psy_hi"].values)).astype(np.int8)


# ---------------------------------------------------------------------------
# Family: Range Filter [DW]
# ---------------------------------------------------------------------------

def _range_filter_loop(close: np.ndarray, n: int = 14, sn: int = 27, qty: float = 2.618):
    N = close.shape[0]
    rf_close = np.empty(N, dtype=np.float64)
    rf_hi    = np.empty(N, dtype=np.float64)
    rf_lo    = np.empty(N, dtype=np.float64)
    rf_r     = np.empty(N, dtype=np.float64)
    rf_dir   = np.zeros(N, dtype=np.int8)
    alpha_n  = 2.0 / (n + 1.0)
    alpha_sn = 2.0 / (sn + 1.0)
    ac = 0.0
    rng_smooth = 0.0
    rfilt = close[0] if N else 0.0
    rfilt_prev = rfilt
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
    return rf_close, rf_hi, rf_lo, rf_r, rf_dir


def add_range_filter(df: pd.DataFrame) -> None:
    """Mutates df: rf_close, rf_hi_band, rf_lo_band, rf_r, rf_dir, rf_dir_age,
    rf_dist_bps, rf_band_pos, rf_in_band, rf_aged, rf_fresh."""
    close = df["close"].to_numpy(dtype=np.float64)
    rf_close, rf_hi, rf_lo, rf_r, rf_dir = _range_filter_loop(close)
    df["rf_close"] = rf_close
    df["rf_hi_band"] = rf_hi
    df["rf_lo_band"] = rf_lo
    df["rf_r"] = rf_r
    df["rf_dir"] = rf_dir
    # age since last flip
    flips = (rf_dir != np.roll(rf_dir, 1)).astype(np.int64)
    if len(flips):
        flips[0] = 1
    age = np.empty(len(df), dtype=np.int64)
    a = 0
    for i in range(len(df)):
        if flips[i] == 1:
            a = 0
        else:
            a += 1
        age[i] = a
    df["rf_dir_age"] = age.astype(np.int32)
    df["rf_dist_bps"] = (df["close"].values - rf_close) / np.where(rf_close == 0, np.nan, rf_close) * 1e4
    denom = (rf_hi - rf_lo)
    df["rf_band_pos"] = (df["close"].values - rf_lo) / np.where(denom == 0, np.nan, denom)
    df["rf_in_band"] = ((df["rf_band_pos"] >= 0) & (df["rf_band_pos"] <= 1)).astype(np.int8)
    df["rf_aged"] = (age >= 5).astype(np.int8)
    df["rf_fresh"] = (age <= 2).astype(np.int8)


# ---------------------------------------------------------------------------
# Family: Regime panel
# ---------------------------------------------------------------------------

def add_regime(df: pd.DataFrame) -> None:
    """Mutates df: regime_label (categorical: trending_up/trending_dn/ranging),
    regime_score (-1..+1). Requires: adx_14, ribbon_alignment_pct, tr_ema_stack_score."""
    adx = df["adx_14"].values
    stack = df["tr_ema_stack_score"].values.astype("float32")
    align = df["ribbon_alignment_pct"].values
    # label
    trending_up = (adx > REGIME_ADX_MIN) & (stack >= 1) & (align >= REGIME_ALIGN_MIN)
    trending_dn = (adx > REGIME_ADX_MIN) & (stack <= -1) & (align >= REGIME_ALIGN_MIN)
    label = np.full(len(df), "ranging", dtype=object)
    label[trending_up] = "trending_up"
    label[trending_dn] = "trending_dn"
    df["regime_label"] = label
    # score (continuous)
    direction = np.tanh(stack / 2.0)
    strength = np.minimum(adx / 50.0, 1.0) * np.minimum(align / 100.0, 1.0)
    df["regime_score"] = (direction * strength).astype("float32")


# ---------------------------------------------------------------------------
# Family: Markov regime (3-state)
# ---------------------------------------------------------------------------

def add_markov_states(df: pd.DataFrame, asset: str) -> None:
    """Mutates df: markov_state (-1=BEAR, 0=SIDEWAYS, +1=BULL, vol-adaptive m1v variant),
    markov_state_fixed (-1/0/+1, asset-specific fixed threshold m1f variant).

    Uses 20-bar rolling log-return; q33/q66 of trailing 14-day distribution for vol_adaptive,
    asset fixed threshold for fixed variant."""
    closes = df["close"].values.astype("float64")
    n = len(closes)
    window_bars = 20
    log_close = np.log(np.where(closes > 0, closes, np.nan))
    rr = np.full(n, np.nan)
    if n > window_bars:
        rr[window_bars:] = log_close[window_bars:] - log_close[:-window_bars]
    # calib lookback: 14 days of bars
    tf_min = int(df.attrs.get("tf_minutes", 5))
    bars_per_day = max(1, int(round(24 * 60 / tf_min)))
    calib_len = 14 * bars_per_day
    warmup = window_bars + calib_len

    out_va = np.full(n, 0, dtype=np.int8)  # default SIDEWAYS=0
    out_va[:] = -127  # sentinel meaning "no label" - we'll convert
    for t in range(min(warmup, n), n):
        history = rr[max(0, t - calib_len):t]
        history = history[~np.isnan(history)]
        if len(history) < 100:
            out_va[t] = 0
            continue
        q33, q66 = np.quantile(history, [1/3, 2/3])
        r = rr[t]
        if not np.isfinite(r):
            out_va[t] = 0
        elif r < q33:
            out_va[t] = -1  # BEAR
        elif r > q66:
            out_va[t] = 1   # BULL
        else:
            out_va[t] = 0   # SIDEWAYS
    # mark pre-warmup as nan via float - keep int with 0=missing actually no, encode as int8 with -127 for missing
    df["markov_state"] = np.where(out_va == -127, np.nan, out_va).astype("float32")

    # Fixed-threshold variant
    thr = MARKOV_FIXED_THR.get(asset.upper(), 0.005)
    out_fx = np.full(n, np.nan, dtype="float32")
    for t in range(window_bars, n):
        r = rr[t]
        if not np.isfinite(r):
            continue
        if r < -thr:
            out_fx[t] = -1.0
        elif r > thr:
            out_fx[t] = 1.0
        else:
            out_fx[t] = 0.0
    df["markov_state_fixed"] = out_fx


# ---------------------------------------------------------------------------
# Family: DRZ (Delta Reaction Zones)
# ---------------------------------------------------------------------------

def _find_pivots_centered(x: np.ndarray, lb: int):
    """Pine ta.pivothigh/low: pivot CENTERED at i prints at bar i+lb."""
    n = len(x)
    pivhi = np.full(n, -1, dtype=np.int64)
    pivlo = np.full(n, -1, dtype=np.int64)
    for i in range(lb, n - lb):
        win_left = x[i - lb:i]
        win_right = x[i + 1:i + lb + 1]
        center = x[i]
        if not np.isfinite(center):
            continue
        if np.isfinite(win_left).sum() < lb or np.isfinite(win_right).sum() < lb:
            continue
        full = np.concatenate([win_left, win_right])
        if center > full.max():
            pivhi[i + lb] = i
        if center < full.min():
            pivlo[i + lb] = i
    return pivhi, pivlo


def add_drz(df: pd.DataFrame) -> None:
    """Mutates df: drz_in_support_zone, drz_in_resistance_zone, drz_dist_bps,
    drz_recent_RC, drz_recent_RE, drz_n_zones."""
    o = df["open"].values.astype("float64")
    h = df["high"].values.astype("float64")
    l = df["low"].values.astype("float64")
    c = df["close"].values.astype("float64")
    v = df["volume"].astype("float64").fillna(0).values
    n = len(c)
    sign_oc = np.where(c > o, 1.0, np.where(c < o, -1.0, 0.0))
    raw_delta = sign_oc * v
    # EMA smooth on raw_delta
    alpha = 2.0 / (DRZ_DELTA_SMOOTH + 1.0)
    sm = np.full(n, np.nan)
    cur = None
    for i in range(n):
        x = raw_delta[i]
        if not np.isfinite(x):
            sm[i] = cur if cur is not None else np.nan
            continue
        if cur is None:
            cur = x
        else:
            cur = alpha * x + (1 - alpha) * cur
        sm[i] = cur
    sm_filled = np.where(np.isfinite(sm), sm, 0.0)
    cvd = np.cumsum(sm_filled)
    atr14 = atr_wilder(pd.Series(h), pd.Series(l), pd.Series(c), 14).values
    pivhi, pivlo = _find_pivots_centered(cvd, DRZ_PIVOT_LB)

    sup_low_a = np.full(n, np.nan)
    sup_hi_a = np.full(n, np.nan)
    sup_mid_a = np.full(n, np.nan)
    sup_active = np.zeros(n, dtype=np.int8)
    res_low_a = np.full(n, np.nan)
    res_hi_a = np.full(n, np.nan)
    res_mid_a = np.full(n, np.nan)
    res_active = np.zeros(n, dtype=np.int8)
    sig_rc = np.zeros(n, dtype=np.int8)
    sig_re = np.zeros(n, dtype=np.int8)
    cur_sup = None; cur_res = None
    for i in range(n):
        if pivhi[i] >= 0:
            center = pivhi[i]
            if np.isfinite(atr14[center]) and atr14[center] > 0:
                half = atr14[center] * DRZ_ZONE_ATR_MULT
                mid = h[center]
                cur_res = {"mid": mid, "lo": mid - half, "hi": mid + half,
                           "breached": False, "last_side": None}
        if pivlo[i] >= 0:
            center = pivlo[i]
            if np.isfinite(atr14[center]) and atr14[center] > 0:
                half = atr14[center] * DRZ_ZONE_ATR_MULT
                mid = l[center]
                cur_sup = {"mid": mid, "lo": mid - half, "hi": mid + half,
                           "breached": False, "last_side": None}
        ci = c[i]
        if cur_sup is not None and np.isfinite(ci):
            side_now = "above" if ci > cur_sup["mid"] else ("below" if ci < cur_sup["mid"] else "in")
            if not cur_sup["breached"]:
                if ci < cur_sup["lo"]:
                    cur_sup["breached"] = True
                elif cur_sup["last_side"] == "below" and side_now == "above":
                    sig_rc[i] = 1
            cur_sup["last_side"] = side_now
        if cur_res is not None and np.isfinite(ci):
            side_now = "above" if ci > cur_res["mid"] else ("below" if ci < cur_res["mid"] else "in")
            if not cur_res["breached"]:
                if ci > cur_res["hi"]:
                    cur_res["breached"] = True
                elif cur_res["last_side"] == "above" and side_now == "below":
                    sig_re[i] = 1
            cur_res["last_side"] = side_now
        if cur_sup is not None and not cur_sup["breached"]:
            sup_low_a[i] = cur_sup["lo"]
            sup_hi_a[i] = cur_sup["hi"]
            sup_mid_a[i] = cur_sup["mid"]
            sup_active[i] = 1
        if cur_res is not None and not cur_res["breached"]:
            res_low_a[i] = cur_res["lo"]
            res_hi_a[i] = cur_res["hi"]
            res_mid_a[i] = cur_res["mid"]
            res_active[i] = 1

    df["drz_in_support_zone"] = ((c >= sup_low_a) & (c <= sup_hi_a) & (sup_active == 1)).astype(np.int8)
    df["drz_in_resistance_zone"] = ((c >= res_low_a) & (c <= res_hi_a) & (res_active == 1)).astype(np.int8)
    # nearest zone distance: pick min(|c-sup_mid|, |c-res_mid|) where active; sign convention: pos = above mid
    dist_sup = np.where(sup_active == 1, (c - sup_mid_a) / np.where(c == 0, np.nan, c) * 1e4, np.nan)
    dist_res = np.where(res_active == 1, (c - res_mid_a) / np.where(c == 0, np.nan, c) * 1e4, np.nan)
    df["drz_dist_sup_bps"] = dist_sup
    df["drz_dist_res_bps"] = dist_res
    # nearest (signed distance to the closer-by-abs zone)
    abs_sup = np.where(np.isfinite(dist_sup), np.abs(dist_sup), np.inf)
    abs_res = np.where(np.isfinite(dist_res), np.abs(dist_res), np.inf)
    nearer_sup = abs_sup < abs_res
    drz_dist_bps = np.where(nearer_sup, dist_sup, dist_res)
    drz_dist_bps = np.where(np.isfinite(drz_dist_bps), drz_dist_bps, np.nan)
    df["drz_dist_bps"] = drz_dist_bps
    df["drz_n_zones"] = (sup_active + res_active).astype(np.int8)
    # recent RC/RE within RECLAIM_WINDOW_BARS (=5)
    rc_ser = pd.Series(sig_rc).rolling(DRZ_RECLAIM_WIN, min_periods=1).sum()
    re_ser = pd.Series(sig_re).rolling(DRZ_RECLAIM_WIN, min_periods=1).sum()
    df["drz_recent_RC"] = (rc_ser.values > 0).astype(np.int8)
    df["drz_recent_RE"] = (re_ser.values > 0).astype(np.int8)


# ---------------------------------------------------------------------------
# Family: HL-extra (funding, liqs, OI)
# ---------------------------------------------------------------------------

def add_hl_extras(df: pd.DataFrame, asset: str,
                  hl_funding: pd.DataFrame | None,
                  hl_liqs: pd.DataFrame | None,
                  hl_metrics: pd.DataFrame | None = None) -> None:
    """Mutates df: hl_funding_rate, hl_funding_annualized, hl_funding_z,
    hl_liq_long_size_sum_60m, hl_liq_short_size_sum_60m, hl_liq_cascade_60m,
    hl_oi (if metrics available)."""
    df_ts = df[["ts_us"]].copy().sort_values("ts_us").reset_index(drop=True)

    # Funding: asof-merge backward
    if hl_funding is not None and not hl_funding.empty:
        fnd = hl_funding[["ts_us", "funding_rate"]].sort_values("ts_us").reset_index(drop=True)
        merged = pd.merge_asof(df_ts, fnd, on="ts_us", direction="backward")
        df["hl_funding_rate"] = merged["funding_rate"].values
        df["hl_funding_annualized"] = df["hl_funding_rate"] * 8760.0
        # z-score over rolling 30d window. tf-bar count for 30d
        tf_min = int(df.attrs.get("tf_minutes", 5))
        bars_30d = max(20, int(round(30 * 24 * 60 / tf_min)))
        fr = df["hl_funding_rate"]
        df["hl_funding_z"] = (fr - fr.rolling(bars_30d, min_periods=20).mean()) / \
                              fr.rolling(bars_30d, min_periods=20).std().replace(0, np.nan)
    else:
        df["hl_funding_rate"] = np.nan
        df["hl_funding_annualized"] = np.nan
        df["hl_funding_z"] = np.nan

    # Liquidations — bucket into 60-minute trailing window aligned to each bar's CLOSE
    tf_sec = TF_TO_SECONDS.get(_tf_label_from_minutes(int(df.attrs.get("tf_minutes", 5))), 300)
    bar_end_us = df["ts_us"].values + tf_sec * 1_000_000
    if hl_liqs is not None and not hl_liqs.empty:
        liq = hl_liqs.copy()
        # use only actual liq events (Liquidated*/Auto-Deleveraging*) where notional is large enough
        liq_real = liq[liq["is_liq_event"]].copy()
        if liq_real.empty:
            # Fallback to entire frame so we get SOMETHING (HL liq_30d mixes fills + true liqs)
            liq_real = liq.copy()
        liq_real = liq_real.sort_values("ts_us").reset_index(drop=True)
        ts_arr = liq_real["ts_us"].values.astype(np.int64)
        # For each bar i, find liquidations in (bar_end_us - 3600s*1e6, bar_end_us]
        win_us = 3600 * 1_000_000
        long_size = np.zeros(len(df), dtype="float32")
        short_size = np.zeros(len(df), dtype="float32")
        cascade = np.zeros(len(df), dtype=np.int32)
        is_long = liq_real["is_long_liq"].values
        is_short = liq_real["is_short_liq"].values
        side_b = (liq_real["side"].values == "B")
        side_a = (liq_real["side"].values == "A")
        notional = liq_real["notional"].values.astype("float64")
        for i in range(len(df)):
            end = bar_end_us[i]
            start = end - win_us
            li = np.searchsorted(ts_arr, start, side="left")
            hi = np.searchsorted(ts_arr, end, side="right")
            if hi <= li:
                continue
            sl = slice(li, hi)
            # If true-liq filter yields any, prefer it; else use side as proxy
            if is_long[sl].any() or is_short[sl].any():
                long_size[i] = float(notional[sl][is_long[sl]].sum())
                short_size[i] = float(notional[sl][is_short[sl]].sum())
                cascade[i] = int(is_long[sl].sum() + is_short[sl].sum())
            else:
                # Proxy: side A (ask-side fill) = long-liq; side B = short-liq
                long_size[i] = float(notional[sl][side_a[sl]].sum())
                short_size[i] = float(notional[sl][side_b[sl]].sum())
                cascade[i] = hi - li
        df["hl_liq_long_size_sum_60m"] = long_size
        df["hl_liq_short_size_sum_60m"] = short_size
        df["hl_liq_cascade_60m"] = cascade
    else:
        df["hl_liq_long_size_sum_60m"] = 0.0
        df["hl_liq_short_size_sum_60m"] = 0.0
        df["hl_liq_cascade_60m"] = 0

    # OI from HL metrics (string-encoded float)
    if hl_metrics is not None and not hl_metrics.empty:
        oim = hl_metrics[["ts_us", "open_interest"]].copy()
        oim["open_interest"] = pd.to_numeric(oim["open_interest"], errors="coerce")
        oim = oim.dropna(subset=["open_interest"]).sort_values("ts_us").reset_index(drop=True)
        m = pd.merge_asof(df_ts, oim, on="ts_us", direction="backward")
        df["hl_oi"] = m["open_interest"].values
    else:
        df["hl_oi"] = np.nan


def load_hl_metrics(asset: str) -> pd.DataFrame:
    p = ROOT / "data" / "v4" / "canonical" / "hyperliquid_metrics.parquet"
    df = pd.read_parquet(p)
    df = df[df["symbol"] == asset].copy()
    if df.empty:
        return df
    df["ts_us"] = df["time_exchange_us"].astype("int64")
    df = df.sort_values("ts_us").drop_duplicates("ts_us").reset_index(drop=True)
    return df[["ts_us", "mark_price", "open_interest"]]


# ---------------------------------------------------------------------------
# Top-level compute_panel
# ---------------------------------------------------------------------------

def compute_panel(klines: pd.DataFrame, asset: str, tf: str,
                  parent_klines: pd.DataFrame | None = None,
                  hl_funding: pd.DataFrame | None = None,
                  hl_liqs: pd.DataFrame | None = None,
                  hl_metrics: pd.DataFrame | None = None) -> pd.DataFrame:
    """Compute the full HL feature panel for one (asset, tf).

    klines: DataFrame with columns ts_us, open_time, open, high, low, close, volume.
    parent_klines: optional same-asset higher TF kline (e.g. 15m for 5m base) — used by SMS
        multi-TF trend strength.
    hl_funding/hl_liqs/hl_metrics: optional HL native feeds; if None, hl_* cols are NaN/0.
    """
    df = klines.copy().reset_index(drop=True)
    if df.empty:
        return df
    df.attrs["tf_minutes"] = TF_TO_MINUTES[tf]
    df.attrs["asset"] = asset
    df.attrs["tf"] = tf

    # 1. Classic TA + basic EMAs
    add_basic_emas(df)
    add_classic_ta(df)

    # 2. Madrid ribbon
    add_madrid_ribbon(df)

    # 3. QR Lite
    add_qr_panel(df)

    # 4. Traders Reality (sets tr_ema_stack_score needed for regime)
    add_traders_reality(df)

    # 5. SMS (needs rsi_14 which classic_ta set)
    if parent_klines is not None and not parent_klines.empty:
        parent_klines.attrs["tf_minutes"] = TF_TO_MINUTES.get(parent_klines.attrs.get("tf", "15m"),
                                                              TF_TO_MINUTES[tf] * 3)
    add_sms(df, parent_df=parent_klines)

    # 6. Range Filter
    add_range_filter(df)

    # 7. Regime (uses adx_14, ribbon_alignment_pct, tr_ema_stack_score)
    add_regime(df)

    # 8. Markov
    add_markov_states(df, asset)

    # 9. DRZ
    add_drz(df)

    # 10. HL extras
    add_hl_extras(df, asset, hl_funding=hl_funding, hl_liqs=hl_liqs, hl_metrics=hl_metrics)

    # Add identifying cols
    df["asset"] = asset
    df["tf"] = tf
    return df


# ---------------------------------------------------------------------------
# Build & save
# ---------------------------------------------------------------------------

def _summarize(df: pd.DataFrame, label: str) -> dict:
    """Print and return a sanity summary dict."""
    n = len(df)
    if n == 0:
        return {"label": label, "rows": 0}
    tmin = pd.to_datetime(df["ts_us"].min(), unit="us", utc=True)
    tmax = pd.to_datetime(df["ts_us"].max(), unit="us", utc=True)
    # NaN% per family group
    families = {
        "classic_ta":  ["rsi_14", "atr_14", "adx_14", "plus_di_14", "minus_di_14",
                        "stoch_k_14", "stoch_d_3", "bb_pos_20", "bb_width_20",
                        "mfi_14", "cci_20"],
        "ema_basic":   [f"ema_{s}" for s in (5, 13, 21, 50, 100, 200, 800)],
        "madrid":      ["ribbon_lead_slope_bps", "ribbon_lead_vs_ref_bps",
                        "ribbon_alignment_pct", "ribbon_compression_bps",
                        "ribbon_color", "tight_ribbon"],
        "qr":          ["qr_state", "qr_regime", "qr_health", "qr_confidence",
                        "qr_volume_ratio"],
        "sms":         ["pivot_high", "pivot_low", "bos_buy", "bos_sell",
                        "bars_since_bos_buy", "bars_since_bos_sell",
                        "choch_buy", "choch_sell",
                        "liquidity_up", "liquidity_dn",
                        "rsi_div_bull", "rsi_div_bear",
                        "cvd_60s", "cvd_120s", "cvd_300s",
                        "trend_strength_multi_tf"],
        "tr":          ["tr_ema_5", "tr_ema_13", "tr_ema_50", "tr_ema_200", "tr_ema_800",
                        "tr_ema_stack_score", "cloud_size_bps",
                        "pvsra_class", "bars_since_climax_up", "bars_since_climax_dn",
                        "PP", "R1", "R2", "R3", "S1", "S2", "S3",
                        "M0", "M1", "M2", "M3", "M4", "M5",
                        "close_vs_pp_bps", "adr", "awr",
                        "tr_in_london", "tr_in_ny", "tr_in_tokyo",
                        "close_vs_psy_hi_bps", "within_psy_band"],
        "rf":          ["rf_close", "rf_hi_band", "rf_lo_band", "rf_dir",
                        "rf_dir_age", "rf_dist_bps", "rf_band_pos",
                        "rf_in_band", "rf_aged", "rf_fresh"],
        "regime":      ["regime_label", "regime_score"],
        "markov":      ["markov_state", "markov_state_fixed"],
        "drz":         ["drz_in_support_zone", "drz_in_resistance_zone",
                        "drz_dist_bps", "drz_recent_RC", "drz_recent_RE",
                        "drz_n_zones"],
        "hl_extra":    ["hl_funding_rate", "hl_funding_annualized", "hl_funding_z",
                        "hl_liq_long_size_sum_60m", "hl_liq_short_size_sum_60m",
                        "hl_liq_cascade_60m", "hl_oi"],
    }
    nan_pct = {}
    for fam, cols in families.items():
        in_df = [c for c in cols if c in df.columns]
        if not in_df:
            continue
        total = 0; nans = 0
        for c in in_df:
            total += n
            try:
                nans += int(df[c].isna().sum())
            except Exception:
                pass
        nan_pct[fam] = 100.0 * nans / total if total else 0.0
    nan_str = " ".join(f"{f}:{p:.1f}%" for f, p in nan_pct.items())
    print(f"  [SANITY] {label} rows={n:,} range=[{tmin} .. {tmax}]")
    print(f"           NaN% by family: {nan_str}")
    # Quick value-range checks
    rsi_v = df["rsi_14"].dropna()
    atr_v = df["atr_14"].dropna()
    if len(rsi_v):
        in_bounds = ((rsi_v >= 0) & (rsi_v <= 100)).all()
        print(f"           rsi_14 in [0,100]? {in_bounds}  range=[{rsi_v.min():.2f}, {rsi_v.max():.2f}]")
    if len(atr_v):
        pos = (atr_v > 0).all()
        print(f"           atr_14 > 0?      {pos}  median={atr_v.median():.4f}")
    return {"label": label, "rows": n, "tmin": tmin, "tmax": tmax,
            "nan_pct_by_family": nan_pct}


def build_and_save(asset: str, tf: str, source: str = "binance",
                   start: pd.Timestamp | None = None,
                   end: pd.Timestamp | None = None,
                   load_hl_extras_for_binance: bool = True) -> tuple[Path, dict]:
    """Top-level builder. source ∈ {'binance','hl'}."""
    t0 = time.time()
    if source == "binance":
        sym = ASSET_TO_BINANCE[asset]
        kl = load_binance_klines(sym, tf, start=start, end=end)
        out_name = f"hl_panel_{asset}_{tf}.parquet"
    elif source == "hl":
        kl = load_hl_klines(asset, tf, start=start, end=end)
        out_name = f"hl_native_panel_{asset}_{tf}.parquet"
    else:
        raise ValueError(source)
    if kl.empty:
        print(f"  SKIP {asset}/{tf}/{source}: no klines")
        return None, {}
    kl.attrs["tf"] = tf
    # Parent TF for SMS multi-TF trend
    parent_tf_map = {"1m": "5m", "5m": "15m", "15m": "1h", "1h": "4h", "4h": "1d", "1d": None}
    parent_tf = parent_tf_map.get(tf)
    parent_kl = None
    if parent_tf is not None:
        try:
            if source == "binance":
                parent_kl = load_binance_klines(sym, parent_tf, start=start, end=end)
            else:
                parent_kl = load_hl_klines(asset, parent_tf, start=start, end=end)
            parent_kl.attrs["tf"] = parent_tf
            parent_kl.attrs["tf_minutes"] = TF_TO_MINUTES[parent_tf]
        except Exception as e:
            print(f"  WARN no parent_tf={parent_tf} for {asset}: {e}")
            parent_kl = None

    # HL extras (funding/liqs/metrics)
    hl_f = None; hl_l = None; hl_m = None
    if source == "hl" or (source == "binance" and load_hl_extras_for_binance):
        try:
            hl_f = load_hl_funding(asset)
        except Exception as e:
            print(f"  no hl_funding for {asset}: {e}")
        try:
            hl_l = load_hl_liqs(asset)
        except Exception as e:
            print(f"  no hl_liqs for {asset}: {e}")
        try:
            hl_m = load_hl_metrics(asset)
        except Exception as e:
            hl_m = None

    print(f"\n[BUILD] {asset}/{tf}/{source}  klines={len(kl):,}  parent_tf={parent_tf} ({0 if parent_kl is None else len(parent_kl)} bars)")
    panel = compute_panel(kl, asset, tf, parent_klines=parent_kl,
                          hl_funding=hl_f, hl_liqs=hl_l, hl_metrics=hl_m)
    out_path = OUT_DIR / out_name
    panel.to_parquet(out_path, index=False, compression="zstd")
    mb = os.path.getsize(out_path) / 1024 / 1024
    print(f"  wrote {out_path.name} ({len(panel):,} rows, {mb:.1f} MB) in {time.time()-t0:.1f}s")
    summary = _summarize(panel, label=f"{asset}/{tf}/{source}")
    summary["path"] = str(out_path)
    summary["size_mb"] = mb
    return out_path, summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    t0 = time.time()
    all_summaries = []

    # ----- Binance backbone panels (multi-year for BTC/ETH/SOL) -----
    binance_targets = []
    for asset in ("BTC", "ETH", "SOL"):
        for tf in ("5m", "15m", "1h", "4h"):
            binance_targets.append((asset, tf))

    print("=" * 72)
    print(f"BUILDING {len(binance_targets)} BINANCE PANELS")
    print("=" * 72)
    for asset, tf in binance_targets:
        try:
            _, s = build_and_save(asset, tf, source="binance",
                                  start=None, end=None,
                                  load_hl_extras_for_binance=True)
            if s:
                all_summaries.append(s)
        except Exception as e:
            print(f"  ERROR {asset}/{tf}: {e}")
            import traceback; traceback.print_exc()

    # ----- HL-native panels for BTC/ETH/SOL/HYPE × {15m, 1h, 4h} -----
    hl_targets = []
    for asset in ("BTC", "ETH", "SOL", "HYPE"):
        for tf in ("15m", "1h", "4h"):
            hl_targets.append((asset, tf))

    print("\n" + "=" * 72)
    print(f"BUILDING {len(hl_targets)} HL-NATIVE PANELS")
    print("=" * 72)
    for asset, tf in hl_targets:
        try:
            _, s = build_and_save(asset, tf, source="hl",
                                  start=None, end=None,
                                  load_hl_extras_for_binance=True)
            if s:
                all_summaries.append(s)
        except Exception as e:
            print(f"  ERROR {asset}/{tf} hl: {e}")
            import traceback; traceback.print_exc()

    print("\n" + "=" * 72)
    print(f"DONE — {len(all_summaries)} panels in {time.time()-t0:.1f}s")
    print("=" * 72)
    # Write a brief summary CSV
    if all_summaries:
        rows = []
        for s in all_summaries:
            d = {"label": s.get("label"),
                 "path": s.get("path"),
                 "rows": s.get("rows"),
                 "size_mb": s.get("size_mb"),
                 "tmin": str(s.get("tmin", "")),
                 "tmax": str(s.get("tmax", ""))}
            d.update({f"nan_pct_{k}": v for k, v in s.get("nan_pct_by_family", {}).items()})
            rows.append(d)
        sum_df = pd.DataFrame(rows)
        sum_csv = OUT_DIR / "_panels_summary.csv"
        sum_df.to_csv(sum_csv, index=False)
        print(f"  summary CSV: {sum_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
