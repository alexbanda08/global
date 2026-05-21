"""FLOW feature computations — pure functions over OB snapshots and trade prints.

Design:
  - Each function takes raw arrays / pandas frames and returns scalars.
  - No I/O here — that lives in build_features.py.
  - Same functions can run online in production once we wire a live data source.

Conventions:
  - Imbalance: positive = bid pressure (good for the long side).
  - CVD: positive = net buying (good for the long side).
  - All features are computed on the HELD-side orderbook + trade stream.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

# Number of OB levels we read out (cache parquet has L25)
N_LEVELS = 25


# ---------------------------------------------------------------------------
# Snapshot-based features (book imbalance + depth)
# ---------------------------------------------------------------------------

def _book_arrays_from_row(row: pd.Series, levels: int = N_LEVELS) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Pull (bid_p, bid_s, ask_p, ask_s) arrays from a single OB row."""
    bid_p = np.array([row[f"bid_price_{i}"] for i in range(levels)], dtype=float)
    bid_s = np.array([row[f"bid_size_{i}"]  for i in range(levels)], dtype=float)
    ask_p = np.array([row[f"ask_price_{i}"] for i in range(levels)], dtype=float)
    ask_s = np.array([row[f"ask_size_{i}"]  for i in range(levels)], dtype=float)
    return bid_p, bid_s, ask_p, ask_s


def _safe_imbalance(bid_size_sum: float, ask_size_sum: float) -> float:
    total = bid_size_sum + ask_size_sum
    if total <= 0 or not np.isfinite(total):
        return 0.0
    return float((bid_size_sum - ask_size_sum) / total)


def compute_book_features(
    bid_p: np.ndarray,
    bid_s: np.ndarray,
    ask_p: np.ndarray,
    ask_s: np.ndarray,
) -> dict[str, float]:
    """Snapshot features at a single book observation.

    Returns dict with keys: imb_l1, imb_l5, imb_l10, imb_l25,
                            bid_max_size_l10_usd,
                            depth_l5_usd, depth_l10_usd, depth_l25_usd.
    """
    # Replace non-finite with 0 so sums work
    bs = np.where(np.isfinite(bid_s) & (bid_s > 0), bid_s, 0.0)
    as_ = np.where(np.isfinite(ask_s) & (ask_s > 0), ask_s, 0.0)
    bp = np.where(np.isfinite(bid_p) & (bid_p > 0) & (bid_p < 1), bid_p, 0.0)
    ap = np.where(np.isfinite(ask_p) & (ask_p > 0) & (ask_p < 1), ask_p, 0.0)

    imb_l1  = _safe_imbalance(bs[0],          as_[0])
    imb_l5  = _safe_imbalance(bs[:5].sum(),   as_[:5].sum())
    imb_l10 = _safe_imbalance(bs[:10].sum(),  as_[:10].sum())
    imb_l25 = _safe_imbalance(bs[:25].sum(),  as_[:25].sum())

    # USD depth (price × size, summed)
    depth_l5_usd  = float((bp[:5]  * bs[:5]).sum()  + (ap[:5]  * as_[:5]).sum())
    depth_l10_usd = float((bp[:10] * bs[:10]).sum() + (ap[:10] * as_[:10]).sum())
    depth_l25_usd = float((bp[:25] * bs[:25]).sum() + (ap[:25] * as_[:25]).sum())

    # Wall detection: largest single bid level USD in top 10
    bid_l10_usd_arr = bp[:10] * bs[:10]
    bid_max_size_l10_usd = float(bid_l10_usd_arr.max()) if bid_l10_usd_arr.size else 0.0

    return {
        "imb_l1":  imb_l1,
        "imb_l5":  imb_l5,
        "imb_l10": imb_l10,
        "imb_l25": imb_l25,
        "bid_max_size_l10_usd": bid_max_size_l10_usd,
        "depth_l5_usd":  depth_l5_usd,
        "depth_l10_usd": depth_l10_usd,
        "depth_l25_usd": depth_l25_usd,
    }


# ---------------------------------------------------------------------------
# Trade-based features (rolling windows ending at query_ts)
# ---------------------------------------------------------------------------

def compute_trade_features(
    trades_df: pd.DataFrame,
    query_ts_us: int,
    side: str,
) -> dict[str, float]:
    """Aggregate trade features over rolling windows ending at query_ts_us.

    Args:
      trades_df: pre-filtered to this slug + held outcome side.
        Must have columns: timestamp_us (int), price (float), size (float), side ('buy'/'sell').
      query_ts_us: feature timestamp (microseconds).
      side: 'Up' or 'Down' — the held side. (Used only for sanity assertions.)

    Returns dict: cvd_1m, cvd_5m, aggressor_ratio_30s, momentum_30s.
    """
    if trades_df is None or trades_df.empty:
        return {
            "cvd_1m": 0.0,
            "cvd_5m": 0.0,
            "aggressor_ratio_30s": 0.5,
            "momentum_30s": 0.0,
        }

    # Restrict to <= query_ts (no lookahead)
    df = trades_df[trades_df["timestamp_us"] <= query_ts_us].copy()
    if df.empty:
        return {
            "cvd_1m": 0.0,
            "cvd_5m": 0.0,
            "aggressor_ratio_30s": 0.5,
            "momentum_30s": 0.0,
        }

    # Time slices
    ts_1m_us = query_ts_us - 60   * 1_000_000
    ts_5m_us = query_ts_us - 300  * 1_000_000
    ts_30s_us = query_ts_us - 30  * 1_000_000

    df_1m  = df[df["timestamp_us"] >= ts_1m_us]
    df_5m  = df[df["timestamp_us"] >= ts_5m_us]
    df_30s = df[df["timestamp_us"] >= ts_30s_us]

    # CVD: signed volume. side == 'buy' is bullish for the held outcome
    # (someone is paying ask to acquire the outcome).
    def _cvd(d: pd.DataFrame) -> float:
        if d.empty:
            return 0.0
        signed = np.where(d["side"].values == "buy", d["size"].values, -d["size"].values)
        return float(signed.sum())

    cvd_1m = _cvd(df_1m)
    cvd_5m = _cvd(df_5m)

    # Aggressor ratio over last 30s (buys / total)
    if df_30s.empty:
        aggressor_ratio_30s = 0.5
    else:
        total_size = float(df_30s["size"].sum())
        if total_size <= 0:
            aggressor_ratio_30s = 0.5
        else:
            buy_size = float(df_30s.loc[df_30s["side"] == "buy", "size"].sum())
            aggressor_ratio_30s = buy_size / total_size

    # Price momentum: vwap of last 30s vs vwap of prior 30s
    if df_30s.empty or len(df_30s) < 2:
        momentum_30s = 0.0
    else:
        vwap_now = float((df_30s["price"] * df_30s["size"]).sum() /
                          max(df_30s["size"].sum(), 1e-9))
        prior_60s_us = query_ts_us - 60 * 1_000_000
        df_prior = df[(df["timestamp_us"] >= prior_60s_us) &
                       (df["timestamp_us"] < ts_30s_us)]
        if df_prior.empty:
            momentum_30s = 0.0
        else:
            vwap_prev = float((df_prior["price"] * df_prior["size"]).sum() /
                               max(df_prior["size"].sum(), 1e-9))
            if vwap_prev > 0:
                momentum_30s = (vwap_now - vwap_prev) / vwap_prev
            else:
                momentum_30s = 0.0

    return {
        "cvd_1m":  cvd_1m,
        "cvd_5m":  cvd_5m,
        "aggressor_ratio_30s": aggressor_ratio_30s,
        "momentum_30s": momentum_30s,
    }


# ---------------------------------------------------------------------------
# Composite flow_score
# ---------------------------------------------------------------------------

# Weights were chosen heuristically from Cyclops doc reading. Re-tune in Phase 5
# (G3 gate) if tier separation is poor.
_FLOW_WEIGHTS = {
    "imb_l5":              0.30,
    "cvd_1m_norm":         0.25,
    "aggressor_centered":  0.20,
    "momentum_30s_norm":   0.15,
    "imb_l10":             0.10,
}

# Normalization caps (saturation thresholds — values beyond cap are clipped)
_CVD_CAP_USD = 5000.0          # ~$5k net flow in 1m saturates the signal
_MOMENTUM_CAP = 0.02           # 2% price move in 30s saturates


def compute_flow_score(book_features: dict, trade_features: dict) -> float:
    """Composite [-1, +1]. Positive = flow confirms long-the-held-side.

    Treats each input as a directional vote, weights, sums, clips.
    """
    imb_l5  = float(book_features.get("imb_l5", 0.0))
    imb_l10 = float(book_features.get("imb_l10", 0.0))
    cvd_1m  = float(trade_features.get("cvd_1m", 0.0))
    aggr    = float(trade_features.get("aggressor_ratio_30s", 0.5))
    mom     = float(trade_features.get("momentum_30s", 0.0))

    cvd_norm = max(-1.0, min(1.0, cvd_1m / _CVD_CAP_USD))
    aggr_centered = (aggr - 0.5) * 2.0  # [-1, +1]
    mom_norm = max(-1.0, min(1.0, mom / _MOMENTUM_CAP))

    score = (
        _FLOW_WEIGHTS["imb_l5"]             * imb_l5 +
        _FLOW_WEIGHTS["cvd_1m_norm"]        * cvd_norm +
        _FLOW_WEIGHTS["aggressor_centered"] * aggr_centered +
        _FLOW_WEIGHTS["momentum_30s_norm"]  * mom_norm +
        _FLOW_WEIGHTS["imb_l10"]            * imb_l10
    )
    return max(-1.0, min(1.0, float(score)))


# ---------------------------------------------------------------------------
# Per-(slug, side) batch driver
# ---------------------------------------------------------------------------

def compute_all_for_slug_side(
    ob_df_slug_side: pd.DataFrame,
    trades_df_slug_side: pd.DataFrame,
    ws_unix: int,
    outcome_side: str,
    query_offset_s: int = 120,
) -> dict[str, float] | None:
    """Compute the full FLOW feature set for one (slug, outcome side) pair
    at the entry decision time (ws_unix + 120s).

    Args:
      ob_df_slug_side: OB rows pre-filtered to this slug + this side, sorted by timestamp_us asc.
      trades_df_slug_side: trade rows pre-filtered to this slug + this side, sorted asc.
      ws_unix: market window_start_unix (seconds).
      outcome_side: 'Up' or 'Down'.
      query_offset_s: when to query — 120 = entry time for momo at t+120.

    Returns:
      dict with all FLOW_FEATURE_COLS values, or None if no OB snapshot ≤ query_ts.
    """
    query_ts_us = (ws_unix + query_offset_s) * 1_000_000

    # Strict asof: pick the most recent OB snapshot whose timestamp ≤ query_ts
    if ob_df_slug_side.empty:
        return None
    mask = ob_df_slug_side["timestamp_us"].values <= query_ts_us
    if not mask.any():
        return None
    last_idx = int(np.flatnonzero(mask).max())
    ob_row = ob_df_slug_side.iloc[last_idx]

    bp, bs, ap, as_ = _book_arrays_from_row(ob_row)
    book_feats = compute_book_features(bp, bs, ap, as_)
    trade_feats = compute_trade_features(trades_df_slug_side, query_ts_us, outcome_side)
    score = compute_flow_score(book_feats, trade_feats)

    return {
        "flow_imb_l1":              book_feats["imb_l1"],
        "flow_imb_l5":              book_feats["imb_l5"],
        "flow_imb_l10":             book_feats["imb_l10"],
        "flow_imb_l25":             book_feats["imb_l25"],
        "flow_bid_max_size_l10_usd": book_feats["bid_max_size_l10_usd"],
        "flow_depth_l5_usd":        book_feats["depth_l5_usd"],
        "flow_depth_l10_usd":       book_feats["depth_l10_usd"],
        "flow_depth_l25_usd":       book_feats["depth_l25_usd"],
        "flow_cvd_1m":              trade_feats["cvd_1m"],
        "flow_cvd_5m":              trade_feats["cvd_5m"],
        "flow_aggressor_ratio_30s": trade_feats["aggressor_ratio_30s"],
        "flow_momentum_30s":        trade_feats["momentum_30s"],
        "flow_score":               score,
    }
