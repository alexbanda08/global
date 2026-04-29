"""
C1 — Meta-Labeled Donchian (Triple Barrier).

Primary model: Donchian-20 breakout on `df["close"]` crossing the
trailing-20 high. Secondary model: a gradient-boosted classifier trained
on **triple-barrier** labels — for each historical primary signal,
label = 1 if TP (2×ATR up) is hit before SL (1×ATR down) or time-stop
(16 bars); label = 0 otherwise. Source: López de Prado, "Advances in
Financial Machine Learning" Ch.3.

At inference the secondary model outputs P(success). Entry is taken only
when P > `meta_threshold`. If training data is insufficient the strategy
degrades to vanilla Donchian (all primary signals taken).

V1 scope: long-only. Strict time-series train/test split with a small
embargo — no purged K-fold yet. The Phase 5.5 robustness battery is
where a proper purged CV would live.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from regime import classify_regime, REGIME_4H_PRESET
from regime.features import adx as _adx, ema_slope as _ema_slope, realized_vol as _rv
from strategies.adaptive.common import time_stop_signal, atr_pct, rsi

try:
    from sklearn.ensemble import HistGradientBoostingClassifier as _HGB
    _HAS_SK = True
except ImportError:
    _HAS_SK = False


def _compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev = close.shift(1)
    tr = pd.concat([
        (high - low).abs(), (high - prev).abs(), (low - prev).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def _triple_barrier_labels(
    df: pd.DataFrame, signal_idxs: np.ndarray,
    tp_atr_mult: float, sl_atr_mult: float, horizon_bars: int,
) -> np.ndarray:
    """
    For each bar index where a primary signal fired, compute the triple-
    barrier label: 1 if TP hit first, 0 if SL or time-stop first.
    """
    atr = _compute_atr(df).to_numpy()
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    close = df["close"].to_numpy()
    n = len(df)
    labels = np.full(len(signal_idxs), np.nan)

    for k, i in enumerate(signal_idxs):
        if i >= n - 1 or np.isnan(atr[i]) or atr[i] <= 0:
            continue
        entry = close[i]
        tp = entry + tp_atr_mult * atr[i]
        sl = entry - sl_atr_mult * atr[i]
        end = min(i + horizon_bars, n - 1)
        # Scan bars (i+1 .. end) for first-touch
        hit_tp = -1; hit_sl = -1
        for j in range(i + 1, end + 1):
            if high[j] >= tp and hit_tp == -1:
                hit_tp = j
            if low[j] <= sl and hit_sl == -1:
                hit_sl = j
            if hit_tp != -1 and hit_sl != -1:
                break
        if hit_tp == -1 and hit_sl == -1:
            labels[k] = 0.0                  # time-stop — conservative fail
        elif hit_tp != -1 and (hit_sl == -1 or hit_tp < hit_sl):
            labels[k] = 1.0                  # TP first
        else:
            labels[k] = 0.0                  # SL first
    return labels


def _build_feature_frame(df: pd.DataFrame, regime_df: pd.DataFrame) -> pd.DataFrame:
    """Per-bar feature frame for the meta-labeler classifier."""
    close = df["close"]
    feat = pd.DataFrame(index=df.index)
    feat["adx"]         = _adx(df["high"], df["low"], close, period=14)
    feat["ema_slope"]   = _ema_slope(close, fast=20, slow=50)
    feat["realized_vol"] = _rv(close, window=20)
    feat["rsi14"]       = rsi(close, period=14)
    feat["dist_sma20"]  = (close / close.rolling(20).mean() - 1.0)
    feat["vol_ratio"]   = df["volume"] / df["volume"].rolling(20).mean()
    feat["trend_score"] = regime_df["trend_score"]
    feat["confidence"]  = regime_df["confidence"]
    return feat


def generate_signals(
    df: pd.DataFrame,
    *,
    regime_config=REGIME_4H_PRESET,
    don_lookback: int = 20,
    tp_atr_mult: float = 2.0,
    sl_atr_mult: float = 1.0,
    horizon_bars: int = 16,
    train_frac: float = 0.6,
    embargo_bars: int = 8,
    meta_threshold: float = 0.55,
    time_stop_bars: int = 32,
    entry_offset_pct: float = 0.0002,
    limit_valid_bars: int = 3,
) -> dict:
    close = df["close"]
    high = df["high"]

    # Primary signal: Donchian-20 breakout (close > trailing 20-bar high)
    don_high = high.rolling(don_lookback).max().shift(1)
    primary = (close > don_high).fillna(False).astype(bool)

    # Triple-barrier labels on EVERY primary signal
    signal_idxs = np.flatnonzero(primary.values)

    # Short-circuit: if no signals OR sklearn missing → vanilla Donchian
    fitted = False
    entries = primary.copy()
    n_trained_on = 0
    auc = np.nan
    if _HAS_SK and len(signal_idxs) >= 40:
        labels = _triple_barrier_labels(
            df, signal_idxs, tp_atr_mult, sl_atr_mult, horizon_bars,
        )
        regime_df = classify_regime(df, config=regime_config)
        feat = _build_feature_frame(df, regime_df)

        # Split signals: first train_frac go to training, rest to live
        n_total = len(signal_idxs)
        n_train = int(n_total * train_frac)
        n_trained_on = n_train

        # Filter out NaN labels / NaN features from training set
        train_idxs = signal_idxs[:n_train]
        train_X = feat.iloc[train_idxs].to_numpy()
        train_y = labels[:n_train]
        valid = ~np.isnan(train_y) & ~np.isnan(train_X).any(axis=1)
        train_X = train_X[valid]
        train_y = train_y[valid].astype(int)

        # Need both classes to train
        if len(train_X) >= 20 and len(np.unique(train_y)) == 2:
            clf = _HGB(
                max_iter=100, max_depth=4, learning_rate=0.05,
                random_state=42, early_stopping=False,
            )
            clf.fit(train_X, train_y)
            fitted = True
            # Score training AUC for diagnostics
            try:
                from sklearn.metrics import roc_auc_score
                auc = float(roc_auc_score(train_y, clf.predict_proba(train_X)[:, 1]))
            except Exception:
                pass

            # Apply embargo — first live signal is (last train signal idx) + embargo_bars
            cutoff_bar = signal_idxs[n_train - 1] + embargo_bars if n_train > 0 else 0
            live_primary = primary.copy()
            live_primary.iloc[:cutoff_bar] = False  # zero-out pre-cutoff
            live_feat = feat[live_primary].dropna()
            if len(live_feat) > 0:
                proba = clf.predict_proba(live_feat.to_numpy())[:, 1]
                proba_s = pd.Series(proba, index=live_feat.index)
                gated = proba_s > meta_threshold
                # Rebuild entries: only bars that survived gating + pre-cutoff zeroed out
                entries = pd.Series(False, index=df.index)
                entries.loc[gated.index] = gated
            else:
                entries = pd.Series(False, index=df.index)

    # Exits: Donchian lower-band break (close < trailing 20-bar low) OR
    # time-stop OR regime flip out of trend family.
    don_low = df["low"].rolling(don_lookback).min().shift(1)
    donch_exit = close < don_low
    time_exit = time_stop_signal(entries, time_stop_bars)
    # Regime-flip (cheap — classify again is free after caching)
    regime_df = classify_regime(df, config=regime_config)
    in_trend = regime_df["label"].astype(str).isin(
        ["strong_uptrend", "weak_uptrend"]
    )
    regime_flip = (~in_trend) & in_trend.shift(1).fillna(False)

    exits = (donch_exit | time_exit | regime_flip).fillna(False).astype(bool)

    return {
        "entries": entries,
        "exits":   exits,
        "short_entries": None,
        "short_exits":   None,
        "entry_limit_offset": pd.Series(entry_offset_pct, index=df.index),
        "_meta": {
            "strategy_id": "c1_meta_labeled_donchian",
            "primary_signals_total": int(len(signal_idxs)),
            "primary_signals_trained_on": int(n_trained_on),
            "primary_signals_after_gate": int(entries.sum()),
            "reject_rate":
                1.0 - entries.sum() / max(1, (len(signal_idxs) - n_trained_on))
                if fitted else 0.0,
            "classifier_fitted": bool(fitted),
            "train_auc": auc,
            "atr_pct_suggested_sl":  atr_pct(df) * sl_atr_mult,
            "atr_pct_suggested_tp":  atr_pct(df) * tp_atr_mult,
            "limit_valid_bars": limit_valid_bars,
        },
    }
