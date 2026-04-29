"""
Directional regime classifier — Bull / Bear / Sideline.

Complements (does NOT replace) the volatility HMM in hmm_adaptive.py.

Design:
  - Rule-based, fully deterministic, no fitted model -> no leakage by construction.
  - All features are causal (only data <= t).
  - Persistence filter (6-bar = 1 day on 4h) to avoid label thrash.
  - API parity with hmm_adaptive: returns labels mapped to {0=Bear, 1=Sideline, 2=Bull}.

Features per bar:
  1. ema200_slope_atr  : EMA200 slope over 50 bars / ATR50 -> trend direction, vol-normalized
  2. dd_from_peak_180d : drawdown from rolling 180d (1080-bar @ 4h) high
  3. ret_60d           : log-return over rolling 60d (360-bar @ 4h)
  4. ma50_vs_ma200     : sign(MA50 - MA200) -- golden/death cross indicator
  5. hh_ll_net         : net (higher-highs - lower-lows) over 30 bars

Labeling rule:
  Bear     : dd_from_peak > 0.15 AND ema_slope < 0 AND ret_60d < 0
  Bull     : ret_60d > 0.10 AND ema_slope > 0 AND ma50 > ma200
  Sideline : otherwise

Persistence: require 6-bar confirmation before activating a regime change.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

# 4h bars per period
BPD = 6
EMA_LONG = 200
EMA_SLOPE_WIN = 50
ATR_WIN = 50
DD_LOOKBACK = 180 * BPD
RET_LOOKBACK = 60 * BPD
MA_SHORT = 50
HH_LL_WIN = 30
PERSISTENCE_BARS = 6

BEAR_DD_THR = 0.15
BEAR_RET_THR = 0.0
BULL_RET_THR = 0.10

REGIME_LABELS = {0: "Bear", 1: "Sideline", 2: "Bull"}


def _atr(df: pd.DataFrame, n: int = ATR_WIN) -> pd.Series:
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    c = df["close"].astype(float).shift(1)
    tr = pd.concat([(h - l).abs(), (h - c).abs(), (l - c).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=n).mean()


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)

    log_close = np.log(close)
    ema200 = _ema(close, EMA_LONG)
    ema_slope = (ema200 - ema200.shift(EMA_SLOPE_WIN)) / EMA_SLOPE_WIN
    atr = _atr(df, ATR_WIN)
    ema_slope_atr = ema_slope / atr

    rolling_high = high.rolling(DD_LOOKBACK, min_periods=DD_LOOKBACK // 4).max()
    dd_from_peak = 1.0 - close / rolling_high

    ret_60d = log_close - log_close.shift(RET_LOOKBACK)

    ma50 = close.rolling(MA_SHORT * BPD, min_periods=MA_SHORT * BPD // 2).mean()
    ma200 = close.rolling(EMA_LONG * BPD, min_periods=EMA_LONG * BPD // 2).mean()
    ma50_gt_ma200 = (ma50 > ma200).astype(int)

    # Higher-highs / lower-lows: count over HH_LL_WIN bars
    rh = high.rolling(HH_LL_WIN).max()
    rl = low.rolling(HH_LL_WIN).min()
    hh = (high >= rh).astype(int)
    ll = (low <= rl).astype(int)
    hh_count = hh.rolling(HH_LL_WIN).sum()
    ll_count = ll.rolling(HH_LL_WIN).sum()
    hh_ll_net = hh_count - ll_count

    feats = pd.DataFrame({
        "ema_slope_atr":  ema_slope_atr,
        "dd_from_peak":   dd_from_peak,
        "ret_60d":        ret_60d,
        "ma50_gt_ma200":  ma50_gt_ma200,
        "hh_ll_net":      hh_ll_net,
    }, index=df.index).dropna()
    return feats


def _classify_row(ema_slope: float, dd: float, ret60: float, ma_cross: int) -> int:
    if dd > BEAR_DD_THR and ema_slope < 0 and ret60 < BEAR_RET_THR:
        return 0  # Bear
    if ret60 > BULL_RET_THR and ema_slope > 0 and ma_cross == 1:
        return 2  # Bull
    return 1  # Sideline


def _apply_persistence(seq: np.ndarray, n: int = PERSISTENCE_BARS) -> np.ndarray:
    """A regime change activates only after `n` consecutive matching bars.
    Until then carry forward the previous stable regime."""
    out = np.full(len(seq), seq[0], dtype=int)
    cur = seq[0]
    cand = seq[0]
    cand_run = 1
    for i in range(1, len(seq)):
        if seq[i] == cand:
            cand_run += 1
        else:
            cand = seq[i]
            cand_run = 1
        if cand_run >= n and cand != cur:
            cur = cand
        out[i] = cur
    return out


@dataclass
class DirectionalRegimeModel:
    regime_labels: dict
    verification: dict

    def classify(self, feats: pd.DataFrame) -> pd.DataFrame:
        raw = np.array([
            _classify_row(r.ema_slope_atr, r.dd_from_peak, r.ret_60d, int(r.ma50_gt_ma200))
            for r in feats.itertuples(index=False)
        ])
        stable = _apply_persistence(raw, n=PERSISTENCE_BARS)
        labels = pd.Series([self.regime_labels[int(s)] for s in stable], index=feats.index)
        return pd.DataFrame({
            "raw_regime":    raw,
            "stable_regime": stable,
            "label":         labels,
        }, index=feats.index)


def fit_directional_regime(df: pd.DataFrame, verbose: bool = False
                           ) -> tuple[DirectionalRegimeModel, pd.DataFrame]:
    feats = build_features(df)
    if len(feats) < 200:
        raise ValueError(f"Need >=200 valid feature bars; got {len(feats)}")
    model = DirectionalRegimeModel(
        regime_labels=dict(REGIME_LABELS),
        verification={
            "n_bars": int(len(feats)),
            "first_date": str(feats.index[0]),
            "last_date":  str(feats.index[-1]),
            "rule_based": True,
            "no_leak":    True,
        },
    )
    regimes = model.classify(feats)
    if verbose:
        dist = regimes["label"].value_counts(normalize=True).to_dict()
        print(f"[dir-regime] {len(feats)} bars, distribution: {dist}")
    return model, regimes
