"""
V5 — SOL hardened with a liquidity filter (fixes fold-2 blow-up from
2019-07 to 2021-01 when SOL had thin volume and 3 trades lost -53%).

Filter: dollar-volume (close × volume) must be in the top 60 % over a
252-bar rolling lookback (~ 42 days at 4h). This skips early-SOL weeks
with anaemic flow.
"""
from __future__ import annotations
import pandas as pd
import talib


def _atr(df, n=14):
    return pd.Series(
        talib.ATR(df["high"].values, df["low"].values, df["close"].values, n),
        index=df.index,
    )


def v5_volume_breakout_liqfilter(df,
                                 don_len: int = 30, vol_avg: int = 20,
                                 vol_mult: float = 1.3, regime_len: int = 150,
                                 atr_len: int = 14, tsl_atr: float = 4.5,
                                 liq_lookback: int = 252,
                                 liq_min_pct: float = 0.40) -> dict:
    """V2B_volume_breakout + dollar-volume percentile gate."""
    hi = df["high"].rolling(don_len).max().shift(1)
    vavg = df["volume"].rolling(vol_avg).mean()
    vol_spike = df["volume"] > vavg * vol_mult
    regime = df["close"] > df["close"].rolling(regime_len).mean()

    # Liquidity gate — dollar notional must exceed its rolling percentile floor
    dollar_vol = df["close"] * df["volume"]
    dv_rank = dollar_vol.rolling(liq_lookback).rank(pct=True)
    liq_ok = dv_rank > liq_min_pct

    entries = (df["close"] > hi) & vol_spike & regime & liq_ok
    exits = df["close"] < df["close"].rolling(regime_len).mean()
    atr = _atr(df, atr_len)
    return dict(entries=entries, exits=exits,
                short_entries=None, short_exits=None,
                tsl_stop=(atr * tsl_atr) / df["close"])


STRATEGIES_V5 = {
    "V5_vol_breakout_liqfilter": v5_volume_breakout_liqfilter,
}
