"""
DEPRECATED FEE MODEL — DO NOT QUOTE PnL FROM THIS FILE FORWARD.

This file uses the legacy `FEE_RATE = 0.02` ("2% on profit only, winning leg")
approximation. The real Polymarket fee is:

    fee = C × feeRate × p × (1 − p)

charged on EVERY fill (not just the winner). For crypto markets feeRate = 0.07.
Use `strategy_lab/fees.py` (`poly_fee_usd`, `poly_maker_rebate_usd`) instead.

Kept here for historical reproducibility only. Numbers produced by this file
diverge materially from real Polymarket settlements — re-run via
`engine_v2.fill_at_book` + `fees.poly_fee_usd` before any decision.
"""

"""
Load and prepare production events for Path B GA.

Produces a per-event DataFrame with:
  cell_id            (sleeve_family, signal, hour_bucket, dow_group) tuple
  pnl_same           live PnL of SAME-side action (what production did)
  pnl_invert         estimated PnL of INVERT action (buy opposite side at ~1-entry+spread)
  pnl_skip           = 0
  date               for time-split
  hour               UTC hour
  dow                day of week
  ...
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_trading_events

NOTIONAL = 25.0
FEE_RATE = 0.02
SPREAD_FILTER = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}


def hour_bucket(h: int) -> str:
    if h < 6:  return "00-05"
    if h < 12: return "06-11"
    if h < 18: return "12-17"
    return "18-23"


def dow_group(d: int) -> str:
    return "weekday" if d < 5 else "weekend"


def asset_from_sleeve(sleeve_id: str) -> str:
    for a in ("btc", "eth", "sol"):
        if f"_{a}_" in sleeve_id.lower():
            return a.upper()
    return "?"


def family_from_sleeve(sleeve_id: str) -> str:
    """Extract strategy family (e.g. momo_HOLD, sniper, volume_INV_NIGHT)."""
    # poly_updown_<asset>_<tf>_<family>
    parts = sleeve_id.split("_", 4)
    if len(parts) >= 5:
        return parts[4]
    return sleeve_id


def load_path_b_events() -> pd.DataFrame:
    """Load + parse production trading_events into per-fire DataFrame with cell_id and pnl_invert."""
    ev = load_trading_events()
    res = ev[ev.kind == "poly_updown_resolution"].copy()
    parsed = res["data"].apply(json.loads).apply(pd.Series)
    res = pd.concat([res, parsed], axis=1)

    res["entry_price"] = pd.to_numeric(res["entry_price"], errors="coerce")
    res["pnl"] = pd.to_numeric(res["pnl_usd"], errors="coerce")
    res["at_ts"] = pd.to_datetime(res["at"], utc=True, errors="coerce")
    res["hour"] = res["at_ts"].dt.hour
    res["dow"] = res["at_ts"].dt.dayofweek
    res["date"] = res["at_ts"].dt.date

    # Derived: asset, family, tf
    res["asset"] = res["symbol"].fillna(res["sleeve_id"].apply(asset_from_sleeve)).str.upper()
    parts = res["sleeve_id"].str.split("_", n=4, expand=True)
    res["tf"] = parts[3] if 3 in parts.columns else "?"
    res["family"] = res["sleeve_id"].apply(family_from_sleeve)
    res["hour_bucket"] = res["hour"].apply(hour_bucket)
    res["dow_group"] = res["dow"].apply(dow_group)

    # cell_id = (sleeve_id, signal, hour_bucket, dow_group)
    res["cell_id"] = (res["sleeve_id"] + "|" + res["signal"].astype(str) +
                       "|" + res["hour_bucket"] + "|" + res["dow_group"])

    # Inverse PnL estimate (conservative: opposite side ask ≈ 1 - entry_price + spread)
    res["spread"] = res["asset"].map(SPREAD_FILTER).fillna(0.02)
    res["inv_entry_price"] = (1 - res["entry_price"] + res["spread"]).clip(0.01, 0.99)
    res["inv_won"] = ((res["won"] == False) & res["won"].notna()).astype(int)
    res["inv_shares"] = NOTIONAL / res["inv_entry_price"]
    res["inv_profit_raw"] = res["inv_shares"] * (res["inv_won"] - res["inv_entry_price"])
    res["pnl_invert"] = res["inv_profit_raw"] - np.maximum(res["inv_profit_raw"], 0) * FEE_RATE
    res["pnl_same"] = res["pnl"]
    res["pnl_skip"] = 0.0

    # Keep only resolved fires with valid pnl
    res = res.dropna(subset=["pnl_same", "won"]).copy()
    return res[[
        "event_id", "at_ts", "date", "hour", "dow", "sleeve_id", "asset",
        "tf", "family", "signal", "outcome", "won", "entry_price",
        "hour_bucket", "dow_group", "cell_id",
        "pnl_same", "pnl_invert", "pnl_skip",
    ]]
