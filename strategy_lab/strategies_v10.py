"""
V10 — ORDERFLOW strategies.

New information sources (BTC/ETH/SOL only; other coins have no local futures data):
  * Binance futures metrics (5 min) — Open Interest, top-trader L/S ratio,
    count L/S ratio, taker-buy/sell volume ratio
  * Binance funding rate (8 h) — perp-spot basis premium
  * CoinAPI liquidations (1 min, 2023+) — liquidation quantity per minute

All orderflow series are resampled to 4h and forward-filled so they align
with our existing V3B/V4C signal grid.

Strategies (all long-only, schema = advanced simulator):

  V10A_funding_fade_v3b
    V3B entry, but skip when 3-day mean funding > +0.015% (longs crowded).
    Enter aggressively when funding < -0.005% (short squeeze fuel).

  V10B_oi_confirm_v4c
    V4C entry + Open Interest rising over last 24h (rising commitment = real
    breakout, not short cover).

  V10C_ls_extreme_long
    Enter long when top-trader L/S > 1.30 (smart money long) AND close > EMA50.
    Exit when L/S falls below 1.10 or EMA50 breaks.

  V10D_liq_cascade_rebound
    After a liquidation spike (quantity > 5x rolling mean over last 12h)
    price typically over-shoots; enter long within next 4h IF trend still
    intact (close > EMA200).  Tight stop, quick TP.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
import talib

from strategy_lab.strategies_v3 import v3b_adx
from strategy_lab.strategies_v4 import v4c_range_kalman

FUT = Path(__file__).resolve().parent.parent / "data" / "binance" / "futures"
LIQ = Path(__file__).resolve().parent.parent / "data" / "coinapi" / "liquidations"


# ---------------------------------------------------------------------
# Loaders — read each orderflow series, resample to 4h, align to df.index
# ---------------------------------------------------------------------
def _read_metrics(sym: str) -> pd.DataFrame:
    p = FUT / "metrics" / sym / "parquet"
    files = sorted(p.glob("year=*/*.parquet"))
    if not files: raise FileNotFoundError(p)
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df = df.drop_duplicates("create_time").sort_values("create_time").set_index("create_time")
    return df


def _read_funding(sym: str) -> pd.Series:
    p = FUT / "fundingRate" / sym / "parquet"
    files = sorted(p.glob("*.parquet"))
    if not files: raise FileNotFoundError(p)
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df = df.drop_duplicates("calc_time").sort_values("calc_time").set_index("calc_time")
    return df["last_funding_rate"].astype("float64")


def _read_liquidations(sym: str) -> pd.Series:
    p = LIQ / sym / "LIQUIDATION_QUANTITY.parquet"
    if not p.exists(): return pd.Series(dtype="float64")
    df = pd.read_parquet(p)
    df = df.drop_duplicates("time_period_start").sort_values("time_period_start")
    df = df.set_index("time_period_start")
    return df["sum"].astype("float64")   # per-minute liquidation quantity (USD-ish)


def _align_4h(s: pd.Series | pd.DataFrame, target_index: pd.DatetimeIndex,
              how: str = "last") -> pd.DataFrame | pd.Series:
    if isinstance(s.index, pd.DatetimeIndex) and s.index.tz is None:
        s.index = s.index.tz_localize("UTC")
    if how == "sum":
        out = s.resample("4h", label="left", closed="left").sum()
    else:
        out = s.resample("4h", label="left", closed="left").last()
    out = out.reindex(target_index, method="ffill")
    return out


def orderflow_features(df: pd.DataFrame, sym: str) -> pd.DataFrame:
    """Return a DataFrame indexed like df with orderflow features."""
    idx = df.index
    out = pd.DataFrame(index=idx)

    m = _read_metrics(sym)
    for col in ("sum_open_interest", "sum_toptrader_long_short_ratio",
                "count_long_short_ratio", "sum_taker_long_short_vol_ratio"):
        if col in m.columns:
            out[col] = _align_4h(m[col], idx)

    fr = _read_funding(sym)
    out["funding_8h"] = _align_4h(fr, idx)
    out["funding_3d_avg"] = out["funding_8h"].rolling(9).mean()   # 9 x 8h = 3 days

    liq = _read_liquidations(sym)
    if len(liq):
        liq_4h = _align_4h(liq, idx, how="sum")
        out["liq_qty"] = liq_4h.fillna(0)
        out["liq_spike"] = out["liq_qty"] / (out["liq_qty"].rolling(36).mean() + 1e-9)  # 36 * 4h = 6 days

    # OI slope (24h) and dollar-value proxy
    if "sum_open_interest" in out.columns:
        out["oi_slope_24h"] = out["sum_open_interest"].pct_change(6)   # 6 * 4h = 24h
        out["oi_slope_72h"] = out["sum_open_interest"].pct_change(18)  # 3 days

    return out


# ---------------------------------------------------------------------
# Helpers for building signal dicts in the advanced-simulator schema
# ---------------------------------------------------------------------
def _atr_pct(df, n=14):
    atr = pd.Series(talib.ATR(df["high"].values, df["low"].values,
                              df["close"].values, n), index=df.index)
    return atr / df["close"]


def _ladder_schema(df: pd.DataFrame, entries: pd.Series, exits: pd.Series,
                   sl_r: float = 1.5,
                   tp1_r: float = 1.0, tp1_frac: float = 0.40,
                   tp2_r: float = 2.0, tp2_frac: float = 0.30,
                   tp3_r: float = 3.5, tp3_frac: float = 0.30,
                   trail_r: float = 2.5, atr_n: int = 14) -> dict:
    atr = _atr_pct(df, atr_n)
    sl = (atr * sl_r).clip(0.005, 0.15)
    tp1 = (atr * tp1_r).clip(0.003, 0.10)
    tp2 = (atr * tp2_r).clip(0.005, 0.20)
    tp3 = (atr * tp3_r).clip(0.008, 0.35)
    trail = (atr * trail_r).clip(0.005, 0.15)
    entries = entries & ~entries.astype("boolean").shift(1).fillna(False).astype(bool)
    return dict(
        entries=entries.fillna(False).astype(bool),
        exits=exits.fillna(False).astype(bool),
        sl_pct=sl,
        tp1_pct=tp1, tp1_frac=tp1_frac,
        tp2_pct=tp2, tp2_frac=tp2_frac,
        tp3_pct=tp3, tp3_frac=tp3_frac,
        trail_pct=trail,
    )


# ---------------------------------------------------------------------
# V10A — Funding-fade V3B
# ---------------------------------------------------------------------
def v10a_funding_fade_v3b(df: pd.DataFrame, sym: str,
                          funding_skip_above: float = 0.00015,   # 0.015 % per 8h
                          funding_boost_below: float = -0.00005) -> dict:
    leg = v3b_adx(df)
    of  = orderflow_features(df, sym)
    f3d = of["funding_3d_avg"]
    skip = f3d > funding_skip_above
    boost = f3d < funding_boost_below
    # Base V3B entries, GATED: drop when funding crowded bullish (skip),
    # keep all otherwise.  When funding is deeply negative, we lean in by
    # also accepting V3B-like entries when HTF regime is up even if
    # original V3B didn't fire (not implemented here — stays conservative).
    entries = leg["entries"] & ~skip
    exits   = leg.get("exits", pd.Series(False, index=df.index))
    return _ladder_schema(df, entries, exits)


# ---------------------------------------------------------------------
# V10B — OI-confirmed V4C
# ---------------------------------------------------------------------
def v10b_oi_confirm_v4c(df: pd.DataFrame, sym: str,
                        min_oi_slope_24h: float = 0.00) -> dict:
    leg = v4c_range_kalman(df)
    of  = orderflow_features(df, sym)
    oi_ok = of.get("oi_slope_24h", pd.Series(0.0, index=df.index)) > min_oi_slope_24h
    entries = leg["entries"] & oi_ok.fillna(False)
    exits   = leg.get("exits", pd.Series(False, index=df.index))
    return _ladder_schema(df, entries, exits)


# ---------------------------------------------------------------------
# V10C — Top-trader L/S extreme long
# ---------------------------------------------------------------------
def v10c_ls_extreme_long(df: pd.DataFrame, sym: str,
                         ls_enter: float = 1.30, ls_exit: float = 1.10,
                         ema_len: int = 50) -> dict:
    of  = orderflow_features(df, sym)
    ls  = of.get("sum_toptrader_long_short_ratio",
                 pd.Series(1.0, index=df.index)).fillna(1.0)
    ema = df["close"].ewm(span=ema_len, adjust=False).mean()
    entries = (ls > ls_enter) & (df["close"] > ema)
    exits   = (ls < ls_exit)  | (df["close"] < ema)
    return _ladder_schema(df, entries, exits,
                          sl_r=1.2, tp1_r=0.8, tp2_r=1.8, tp3_r=3.0, trail_r=2.0)


# ---------------------------------------------------------------------
# V10D — Liquidation cascade rebound
# ---------------------------------------------------------------------
def v10d_liq_cascade_rebound(df: pd.DataFrame, sym: str,
                             spike_mult: float = 5.0,
                             ema_trend: int = 200) -> dict:
    of = orderflow_features(df, sym)
    liq_spike = of.get("liq_spike", pd.Series(0.0, index=df.index)).fillna(0.0)
    et = df["close"].ewm(span=ema_trend, adjust=False).mean()
    # Entry: fresh spike AND price above HTF EMA (bull-regime fade)
    spike = liq_spike > spike_mult
    fresh_spike = spike & ~spike.shift(1).fillna(False).astype(bool)
    entries = fresh_spike & (df["close"] > et)
    exits   = df["close"] < et
    return _ladder_schema(df, entries, exits,
                          sl_r=1.0, tp1_r=1.0, tp2_r=2.0, tp3_r=3.0, trail_r=1.5,
                          tp1_frac=0.50, tp2_frac=0.30, tp3_frac=0.20)


STRATEGIES_V10 = {
    "V10A_funding_fade_v3b":    v10a_funding_fade_v3b,
    "V10B_oi_confirm_v4c":      v10b_oi_confirm_v4c,
    "V10C_ls_extreme_long":     v10c_ls_extreme_long,
    "V10D_liq_cascade_rebound": v10d_liq_cascade_rebound,
}
