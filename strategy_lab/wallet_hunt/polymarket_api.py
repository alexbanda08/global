"""
Polymarket data-api / lb-api client — canonical entry point for wallet PnL.

The local chain-decoder (Alchemy getAssetTransfers) drops every non-TRADE event
(REDEEM, MERGE, MAKER_REBATE, CONVERSION, REWARD, ...) which inverts the sign
on hold-to-expiry strategies. This module bypasses the chain decoder by going
straight to Polymarket's server-side aggregator at /activity.

Endpoints used:
  - lb-api.polymarket.com/profit       lifetime / 30d / 7d / 1d PnL (official)
  - lb-api.polymarket.com/volume       lifetime / 30d / 7d / 1d volume
  - data-api.polymarket.com/value      current open-position $
  - data-api.polymarket.com/positions  open-position breakdown
  - data-api.polymarket.com/activity   per-type event tape

Responses cached at: strategy_lab/wallet_hunt/cache/_pm_portfolio/<short>/<name>.json

Rate limit: 0.22 s between requests (~4.5 req/sec, under the 5/sec budget).

Drop-in canonical PnL formula in `cash_pnl.cash_pnl()` (this module's sibling).

Usage:
    from strategy_lab.wallet_hunt.polymarket_api import (
        fetch_lb_profit, fetch_activity, activity_to_df,
    )
    act = fetch_activity("0x9dae874a", "0x9dae874a2e804349e3004ccc98107799f15f97a2")
    df  = activity_to_df(act)
    # then: from strategy_lab.wallet_hunt.cash_pnl import cash_pnl
    # result = cash_pnl(df, positions_df=...)

CLI:
    py -X utf8 strategy_lab/wallet_hunt/polymarket_api.py --wallet 0x9dae874a...
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

CACHE_ROOT = Path(__file__).resolve().parent / "cache" / "_pm_portfolio"
CACHE_ROOT.mkdir(parents=True, exist_ok=True)

DATA = "https://data-api.polymarket.com"
LB = "http://lb-api.polymarket.com"

WINDOWS = ["all", "30d", "7d", "1d"]
RATE_LIMIT_DELAY = 0.22  # 0.22s => ~4.5 req/sec

# Per-type pagination caps. Defaults are HIGH because for any cashflow-PnL
# reconstruction, truncating one event class (e.g. TRADE at 500) while
# fully fetching another (REDEEM at 2000) biases realized PnL by tens of
# percent. Use --no-cache + explicit --max-per-type if you need to trade
# accuracy for speed.
MAX_PER_TYPE = {
    "TRADE":         50000,   # was 500 — capping trades biases cashflow PnL
    "MERGE":         50000,   # was 2000 — HFT wallets blow past 2k
    "SPLIT":         50000,
    "REDEEM":        50000,   # was 2000
    "REWARD":        50000,
    "CONVERSION":    50000,   # NB: API uses CONVERSION, not CONVERT (Fix #4)
    "MAKER_REBATE":  50000,
    "DEPOSIT":        2000,
    "WITHDRAWAL":     2000,
    "YIELD":          2000,
    "REFERRAL_REWARD": 2000,
}
ALL_TYPES = list(MAX_PER_TYPE.keys())


# ===========================================================================
# Generic HTTP helpers
# ===========================================================================

def _short(full: str) -> str:
    return full.lower()[:10]


def _save(short: str, name: str, payload) -> Path:
    d = CACHE_ROOT / short
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.json"
    p.write_text(json.dumps(payload, default=str, indent=2))
    return p


def _load(short: str, name: str):
    p = CACHE_ROOT / short / f"{name}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _get(url: str, params: dict | None = None, timeout: int = 12):
    """GET with rate-limit + error envelope. Returns parsed JSON or error dict."""
    time.sleep(RATE_LIMIT_DELAY)
    try:
        r = requests.get(url, params=params or {}, timeout=timeout)
        if r.status_code != 200:
            return {"_status": r.status_code, "_text": r.text[:300]}
        try:
            return r.json()
        except Exception:
            return {"_text": r.text[:500]}
    except Exception as e:
        return {"_err": str(e)}


# ===========================================================================
# Endpoint fetchers (each cached on disk)
# ===========================================================================

def fetch_lb_profit(full: str, use_cache: bool = True) -> dict:
    short = _short(full)
    cached = _load(short, "lb_profit") if use_cache else None
    if isinstance(cached, dict) and "all" in cached:
        return cached
    out = {}
    for w in WINDOWS:
        out[w] = _get(f"{LB}/profit", {"window": w, "address": full})
    _save(short, "lb_profit", out)
    return out


def fetch_lb_volume(full: str, use_cache: bool = True) -> dict:
    short = _short(full)
    cached = _load(short, "lb_volume") if use_cache else None
    if isinstance(cached, dict) and "all" in cached:
        return cached
    out = {}
    for w in WINDOWS:
        out[w] = _get(f"{LB}/volume", {"window": w, "address": full})
    _save(short, "lb_volume", out)
    return out


def fetch_value(full: str, use_cache: bool = True):
    short = _short(full)
    cached = _load(short, "value") if use_cache else None
    if cached is not None:
        return cached
    res = _get(f"{DATA}/value", {"user": full})
    _save(short, "value", res)
    return res


def fetch_positions(full: str, use_cache: bool = True):
    short = _short(full)
    cached = _load(short, "positions") if use_cache else None
    if cached is not None:
        return cached
    res = _get(f"{DATA}/positions", {"user": full})
    _save(short, "positions", res)
    return res


def fetch_activity_by_type(full: str, event_type: str, max_total: int = 2000,
                             use_cache: bool = True) -> list[dict]:
    """Type-filtered activity pagination."""
    short = _short(full)
    cache_name = f"activity_{event_type}"
    cached = _load(short, cache_name) if use_cache else None
    if isinstance(cached, list):
        return cached
    out: list[dict] = []
    offset = 0
    page_size = 500
    while len(out) < max_total:
        page = _get(f"{DATA}/activity", {
            "user": full, "limit": page_size, "offset": offset,
            "type": event_type,
        })
        if not isinstance(page, list) or not page:
            break
        out.extend(page)
        if len(page) < page_size:
            break
        offset += len(page)
    _save(short, cache_name, out)
    return out


def fetch_activity(full: str, use_cache: bool = True,
                    types: list[str] | None = None) -> dict[str, list[dict]]:
    """Fetch all known event types; return dict[type -> events]."""
    out = {}
    types = types or ALL_TYPES
    for t in types:
        cap = MAX_PER_TYPE.get(t, 2000)
        out[t] = fetch_activity_by_type(full, t, cap, use_cache=use_cache)
    return out


# ===========================================================================
# Parsing helpers
# ===========================================================================

def lb_amount(payload, window: str):
    """LB-API returns a list; extract `amount` of first entry."""
    if not isinstance(payload, dict):
        return None
    arr = payload.get(window)
    if isinstance(arr, list) and arr:
        first = arr[0]
        if isinstance(first, dict):
            return first.get("amount")
    return None


def value_amount(payload):
    if isinstance(payload, list) and payload:
        v = payload[0]
        if isinstance(v, dict):
            return v.get("value")
    return None


def positions_to_df(payload) -> pd.DataFrame:
    if not isinstance(payload, list) or not payload:
        return pd.DataFrame()
    return pd.DataFrame(payload)


def activity_to_df(activity_by_type: dict[str, list[dict]]) -> pd.DataFrame:
    """Flatten dict[type -> events] into a single DataFrame.

    Adds a `type` column on every row (the dict key). Each event's own dict
    fields (timestamp, usdcSize, side, conditionId, ...) carry through.
    """
    frames = []
    for t, events in (activity_by_type or {}).items():
        if not events:
            continue
        df = pd.DataFrame(events)
        # Some API responses already include a 'type' field; keep ours as truth.
        df["type"] = t
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["type", "side", "usdcSize", "timestamp"])
    return pd.concat(frames, ignore_index=True, sort=False)


# ===========================================================================
# CLI
# ===========================================================================

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--wallet", required=True, help="full hex address")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    use_cache = not args.no_cache
    full = args.wallet.lower()
    short = _short(full)

    print(f"== {short} ==")
    lb_profit = fetch_lb_profit(full, use_cache=use_cache)
    lb_volume = fetch_lb_volume(full, use_cache=use_cache)
    value = fetch_value(full, use_cache=use_cache)
    positions = fetch_positions(full, use_cache=use_cache)
    activity = fetch_activity(full, use_cache=use_cache)

    profit_all = lb_amount(lb_profit, "all")
    profit_30d = lb_amount(lb_profit, "30d")
    profit_7d = lb_amount(lb_profit, "7d")
    vol_all = lb_amount(lb_volume, "all")
    vol_30d = lb_amount(lb_volume, "30d")
    cur_value = value_amount(value)
    n_open = len(positions) if isinstance(positions, list) else 0
    df_act = activity_to_df(activity)

    print(f"lb_profit_all = ${profit_all}")
    print(f"lb_profit_30d = ${profit_30d}")
    print(f"lb_profit_7d  = ${profit_7d}")
    print(f"lb_volume_all = ${vol_all}")
    print(f"open_value    = ${cur_value}  (n={n_open})")
    print(f"activity rows = {len(df_act)} (by type: "
          f"{df_act['type'].value_counts().to_dict() if len(df_act) else {}})")


if __name__ == "__main__":
    main()
