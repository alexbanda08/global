"""Shared utilities for v2_signals builders."""
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent.parent
DATA_DIR = HERE / "data"
ASSETS = ("btc", "eth", "sol")
# Available timeframes — for callers iterating over markets.
# Not used by load_features/save_features; the file stores all timeframes mixed.
TIMEFRAMES = ("5m", "15m")


def load_features(asset: str) -> pd.DataFrame:
    p = DATA_DIR / "polymarket" / f"{asset}_features_v3.csv"
    if not p.exists():
        raise FileNotFoundError(f"Features file not found: {p}")
    return pd.read_csv(p)


def save_features(asset: str, df: pd.DataFrame) -> None:
    p = DATA_DIR / "polymarket" / f"{asset}_features_v3.csv"
    df.to_csv(p, index=False)
