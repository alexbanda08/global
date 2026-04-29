"""
V6 — Fixed SL/TP mean-reversion (port of the user's "Optimized BTC
Mean Reversion RSI 20/65" Pine strategy).

Logic (long+short):
  LONG entry : RSI < 20 AND stochK < 25 AND close > EMA(200) * 0.9
  SHORT entry: RSI > 65 AND stochK > 75 AND close < EMA(200)
  Exit: fixed % stop-loss (4%) or take-profit (6%)

Fees 0.04% in the Pine (Binance perp maker); our engine uses 0.1% spot,
so we call it out and let the engine enforce realistic spot fees.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import talib


def _stoch(df, k_len=14, d_len=3):
    """Classic Stochastic %K (fast) + %D (SMA smooth)."""
    hh = df["high"].rolling(k_len).max()
    ll = df["low"].rolling(k_len).min()
    stoch_k = 100 * (df["close"] - ll) / (hh - ll)
    stoch_d = stoch_k.rolling(d_len).mean()
    return stoch_k, stoch_d


def v6_rsi_2065(df,
                ema_len: int = 200,
                rsi_len: int = 14,
                rsi_buy: float = 20.0,
                rsi_sell: float = 65.0,
                stoch_k: int = 14, stoch_d: int = 3,
                stoch_ob: float = 75.0, stoch_os: float = 25.0,
                sl_pct: float = 0.04, tp_pct: float = 0.06) -> dict:
    ema = df["close"].ewm(span=ema_len, adjust=False).mean()
    rsi = pd.Series(talib.RSI(df["close"].values, rsi_len), index=df.index)
    k, _ = _stoch(df, stoch_k, stoch_d)

    long_in  = (rsi < rsi_buy)  & (k < stoch_os) & (df["close"] > ema * 0.9)
    short_in = (rsi > rsi_sell) & (k > stoch_ob) & (df["close"] < ema)

    # Exit is handled by fixed SL/TP — we do NOT emit signal-based exits
    # (except a safety exit on opposite signal to flatten stuck positions).
    long_out  = short_in.copy()
    short_out = long_in.copy()

    return dict(
        entries=long_in, exits=long_out,
        short_entries=short_in, short_exits=short_out,
        sl_stop=sl_pct,
        tp_stop=tp_pct,
    )


STRATEGIES_V6: dict[str, callable] = {
    "V6_rsi_2065_meanrev": v6_rsi_2065,
}
