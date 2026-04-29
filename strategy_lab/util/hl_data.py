"""
Hyperliquid data loader. Drop-in replacement for `engine.load` for HL parquets.

Symbol mapping: Binance uses "BTCUSDT" / "ETHUSDT", HL uses "BTC" / "ETH".
This loader accepts either form and strips the USDT suffix.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parent.parent.parent
HL_KLINE = REPO / "data" / "hyperliquid" / "parquet"
HL_FUNDING = REPO / "data" / "hyperliquid" / "funding"


def hl_symbol(symbol: str) -> str:
    """Map BTCUSDT -> BTC; pass through if already short form."""
    s = symbol.upper().strip()
    if s.endswith("USDT"):
        s = s[:-4]
    return s


def load_hl(symbol: str, tf: str = "4h",
             start: str | None = None, end: str | None = None) -> pd.DataFrame:
    sym = hl_symbol(symbol)
    path = HL_KLINE / sym / f"{tf}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"HL kline not found: {path}")
    df = pd.read_parquet(path)
    if start is not None:
        df = df[df.index >= pd.Timestamp(start, tz="UTC")]
    if end is not None:
        df = df[df.index <= pd.Timestamp(end, tz="UTC")]
    return df


def load_hl_funding(symbol: str) -> pd.DataFrame:
    """Returns DataFrame indexed by hourly UTC timestamp with columns
    fundingRate (decimal hourly rate) and premium."""
    sym = hl_symbol(symbol)
    path = HL_FUNDING / f"{sym}_funding.parquet"
    if not path.exists():
        raise FileNotFoundError(f"HL funding not found: {path}")
    return pd.read_parquet(path)


def funding_per_4h_bar(symbol: str, kline_index: pd.DatetimeIndex) -> pd.Series:
    """
    Aggregate hourly funding rates into per-4h-bar cumulative funding.
    Returns Series aligned to kline_index. Each value is the SUM of the
    4 hourly fundingRate values that occurred during that bar
    (so total funding rate paid/received over the bar's duration).

    Signed convention (HL spec): fundingRate > 0 → longs pay shorts.
    Position P&L impact = -direction * notional * funding_per_bar.
    """
    f = load_hl_funding(symbol)
    f = f["fundingRate"].astype(float)
    # Round to hour and group into 4h buckets aligned to kline open times.
    # Kline timestamps are 4h-aligned (00:00, 04:00, 08:00, ...). Bar covers
    # [t, t+4h). So we bucket funding by the bar-start.
    hour_to_bar = f.index.floor("4h")
    grouped = f.groupby(hour_to_bar).sum()
    # Reindex to the kline_index, fill missing with 0 (rare gaps)
    out = grouped.reindex(kline_index).fillna(0.0)
    return out
