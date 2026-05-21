"""Micro-scale Markov regime detection — adapted from Roan's framework for
sub-day timeframes.

Source method (jackson-video-resources/markov-hedge-fund-method):
  1. label_regimes:        rolling N-bar return → Bull/Bear/Sideways
  2. build_transition_matrix: MLE 3x3 from label sequence
  3. stationary_distribution: left eigenvector of P
  4. signal = bull_prob - bear_prob from row of P given current_state

Original defaults (daily): window=20, threshold=0.05.
Adapted defaults here (1m bars): window=20, threshold=vol-adaptive (q33/q66
of rolling returns over the prior 14d) so it self-calibrates per asset.

State indices fixed: 0=Bear, 1=Sideways, 2=Bull.

Causal at every step: state_at_us(t) uses only data with end_us <= t.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

STATES = ["Bear", "Sideways", "Bull"]
BEAR, SIDEWAYS, BULL = 0, 1, 2


# --------------------------------------------------------------------------- #
# Label assignment
# --------------------------------------------------------------------------- #
def label_regimes_vol_adaptive(
    closes: np.ndarray,
    window_bars: int,
    bars_per_day: int = 1440,
    calib_lookback_days: int = 14,
) -> np.ndarray:
    """Vol-adaptive labels: at each bar t, use the prior `calib_lookback_days`
    of rolling `window_bars`-return distributions to set q33/q66 thresholds.
    Then label bar t's rolling return as Bear (< q33), Bull (> q66), else Sideways.

    Returns int array of same length as closes. NaN values before warmup → -1.
    """
    n = len(closes)
    out = np.full(n, -1, dtype=np.int8)
    if n < window_bars + 2:
        return out

    log_close = np.log(closes)
    # rolling window-bar log returns
    rr = np.empty(n, dtype=np.float64)
    rr[:window_bars] = np.nan
    rr[window_bars:] = log_close[window_bars:] - log_close[:-window_bars]

    calib_len = calib_lookback_days * bars_per_day
    warmup = window_bars + calib_len

    if n < warmup + 1:
        return out

    for t in range(warmup, n):
        history = rr[t - calib_len:t]
        history = history[~np.isnan(history)]
        if len(history) < 100:
            continue
        q33, q66 = np.quantile(history, [1/3, 2/3])
        r = rr[t]
        if not np.isfinite(r):
            continue
        if r < q33:
            out[t] = BEAR
        elif r > q66:
            out[t] = BULL
        else:
            out[t] = SIDEWAYS
    return out


def label_regimes_fixed(
    closes: np.ndarray,
    window_bars: int,
    threshold: float,
) -> np.ndarray:
    """Fixed-threshold labels: Bull/Bear/Sideways from rolling window-bar return
    vs +/- threshold (in log-return units)."""
    n = len(closes)
    out = np.full(n, -1, dtype=np.int8)
    if n < window_bars + 1:
        return out
    log_close = np.log(closes)
    rr = np.empty(n, dtype=np.float64)
    rr[:window_bars] = np.nan
    rr[window_bars:] = log_close[window_bars:] - log_close[:-window_bars]
    for t in range(window_bars, n):
        r = rr[t]
        if not np.isfinite(r):
            continue
        if r < -threshold:
            out[t] = BEAR
        elif r > threshold:
            out[t] = BULL
        else:
            out[t] = SIDEWAYS
    return out


# --------------------------------------------------------------------------- #
# Transition matrix + stationary distribution
# --------------------------------------------------------------------------- #
def build_transition_matrix(labels: np.ndarray) -> np.ndarray:
    """3x3 MLE. labels: int array with -1 marking pre-warmup; we skip those."""
    counts = np.zeros((3, 3), dtype=float)
    for i in range(len(labels) - 1):
        a, b = labels[i], labels[i + 1]
        if a < 0 or b < 0:
            continue
        counts[a, b] += 1.0
    row_sums = counts.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1.0
    return counts / row_sums


def stationary_distribution(P: np.ndarray) -> np.ndarray:
    """Left eigenvector of P with eigenvalue 1, normalized to sum to 1."""
    eigvals, eigvecs = np.linalg.eig(P.T)
    idx = np.argmin(np.abs(eigvals - 1.0))
    pi = np.real(eigvecs[:, idx])
    pi = pi / pi.sum()
    pi = np.maximum(pi, 0.0)
    return pi / pi.sum()


# --------------------------------------------------------------------------- #
# Causal lookups
# --------------------------------------------------------------------------- #
def asof_label_idx(end_us: np.ndarray, target_us: int) -> int:
    """Index of last bar that ENDED at-or-before target_us. -1 if none."""
    i = int(np.searchsorted(end_us, target_us, side="right")) - 1
    return i


def regime_at_us(end_us: np.ndarray, labels: np.ndarray, target_us: int) -> int:
    """Current regime (causal) at target_us."""
    i = asof_label_idx(end_us, target_us)
    if i < 0 or i >= len(labels):
        return -1
    return int(labels[i])


def transition_matrix_asof(end_us: np.ndarray, labels: np.ndarray,
                           target_us: int) -> np.ndarray:
    """3x3 MLE built ONLY from labels up to and including target_us. Causal."""
    i = asof_label_idx(end_us, target_us)
    if i < 1:
        return np.full((3, 3), 1/3)
    return build_transition_matrix(labels[:i + 1])


def markov_signal_at_us(end_us: np.ndarray, labels: np.ndarray,
                        target_us: int) -> tuple[int, float]:
    """Return (current_regime, signal) at target_us.
    signal = P(next=Bull | current) - P(next=Bear | current). Range [-1, +1].
    Causal: matrix and labels both up to target_us only."""
    regime = regime_at_us(end_us, labels, target_us)
    if regime < 0:
        return -1, 0.0
    P = transition_matrix_asof(end_us, labels, target_us)
    p_bull = P[regime, BULL]
    p_bear = P[regime, BEAR]
    return regime, float(p_bull - p_bear)


# --------------------------------------------------------------------------- #
# Convenience: build labels for an asset from canonical 1m klines
# --------------------------------------------------------------------------- #
def build_labels_for_asset(
    asset: str,
    window_bars: int = 20,
    mode: str = "vol_adaptive",   # 'vol_adaptive' | 'fixed'
    fixed_threshold: float = 0.003,
    bar_minutes: int = 1,
    source: str = "binance-spot-ws",
    fresh_klines_csv: str | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (end_us, closes, labels) for `asset` from canonical klines.

    window_bars: rolling-return window in BARS (e.g. 20 with bar_minutes=1 → 20m,
                 20 with bar_minutes=5 → 100m).
    bar_minutes: 1 or 5 (klines are 1m natively; we downsample to 5m if needed).
    fresh_klines_csv: optional path to a VPS3-pulled CSV with cols
        (symbol_id, time_period_start_us, price_close). When provided, used
        instead of canonical klines — needed when canonical is stale.
    """
    import sys
    import pandas as pd  # local to avoid global circularity

    if fresh_klines_csv:
        kdf = pd.read_csv(fresh_klines_csv)
        sym = f"BINANCE_SPOT_{asset.upper()}_USDT"
        df = kdf[kdf["symbol_id"] == sym].copy()
        if df.empty:
            return (np.array([], dtype="int64"),
                    np.array([], dtype="float64"),
                    np.array([], dtype="int8"))
        df = df.drop_duplicates("time_period_start_us").sort_values("time_period_start_us")
        df["ts_s"] = (df["time_period_start_us"] // 1_000_000).astype("int64")
    else:
        sys.path.insert(0, "data/v4/canonical")
        from load import load_klines  # noqa: E402
        period_id = "1MIN"  # always pull 1m, downsample below if needed
        df = load_klines(asset, source=source, period_id=period_id)
        if df.empty:
            return (np.array([], dtype="int64"),
                    np.array([], dtype="float64"),
                    np.array([], dtype="int8"))

    if bar_minutes != 1:
        # downsample to 5m bars: take every Nth row using time alignment
        ts_s = df["ts_s"].values
        keep_mask = (ts_s % (bar_minutes * 60)) == 0
        df = df[keep_mask].reset_index(drop=True)

    period_s = bar_minutes * 60
    end_us = (df["time_period_start_us"].values.astype("int64") +
              period_s * 1_000_000)
    closes = df["price_close"].values.astype("float64")

    if mode == "vol_adaptive":
        bars_per_day = (24 * 60) // bar_minutes
        labels = label_regimes_vol_adaptive(
            closes, window_bars=window_bars,
            bars_per_day=bars_per_day,
            calib_lookback_days=14,
        )
    elif mode == "fixed":
        labels = label_regimes_fixed(closes, window_bars=window_bars,
                                     threshold=fixed_threshold)
    else:
        raise ValueError(f"unknown mode: {mode}")
    return end_us, closes, labels


if __name__ == "__main__":
    # smoke test
    for asset in ("BTC", "ETH", "SOL"):
        end_us, closes, labels = build_labels_for_asset(
            asset, window_bars=20, mode="vol_adaptive", bar_minutes=1)
        labelled = labels[labels >= 0]
        if len(labelled) == 0:
            print(f"{asset}: NO LABELS (insufficient data)")
            continue
        from collections import Counter
        c = Counter(labelled.tolist())
        n = len(labelled)
        print(f"{asset}: n_bars={len(closes)}, labelled={n}, "
              f"Bear={c[BEAR]/n*100:.1f}% Side={c[SIDEWAYS]/n*100:.1f}% Bull={c[BULL]/n*100:.1f}%")
        P = build_transition_matrix(labels)
        pi = stationary_distribution(P)
        print(f"  P (Bear/Side/Bull rows):")
        for i, name in enumerate(STATES):
            print(f"    {name:8s} → Bear={P[i,0]:.3f} Side={P[i,1]:.3f} Bull={P[i,2]:.3f}")
        print(f"  stationary: Bear={pi[0]:.3f} Side={pi[1]:.3f} Bull={pi[2]:.3f}")
        print(f"  persistence diag: {P[0,0]:.3f} / {P[1,1]:.3f} / {P[2,2]:.3f}")
        print()
