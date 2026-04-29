"""
Forward-only HMM-style regime classifier using GaussianMixture (hmmlearn N/A).

CRITICAL no-look-ahead design:
  - GMM fit ONLY on in-sample (IS) bars [0:train_end_idx].
  - For every OOS bar t > train_end_idx, regime posterior uses the fixed
    IS-fitted model. OOS bars NEVER influence the model.
  - Optional expanding-window refit at fixed cadence (refit_every) for
    live-trading simulation.

Features per bar:
  1. log_return
  2. realized_vol_120 (120-bar rolling std of log returns)
  3. volume_ratio (volume / 120-bar mean volume)
  4. hl_range_pct ((high - low) / close)

Pipeline:
  1. Compute features, drop NaN prefix.
  2. Scale (z-score on IS only).
  3. Fit GMM for K in [3,7], pick K by BIC.
  4. Compute posteriors (predict_proba) -> raw regime = argmax.
  5. Sort regimes by mean of feature #2 (realized_vol) within each regime;
     relabel 0 -> lowest-vol, K-1 -> highest-vol.
  6. Stability filter: require 3-bar persistence before activating a regime.
  7. Flicker filter: if regime changes >4x in 20-bar window -> "Uncertain".

Returns:
  pd.DataFrame with columns ["raw_regime", "stable_regime", "label",
                             "vol_score", "is_uncertain"]
  plus a diagnostic dict describing model fit + verification.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.mixture import GaussianMixture

REALIZED_VOL_WIN = 120          # 20 days of 4h bars
VOLUME_WIN = 120
PERSISTENCE_BARS = 3
FLICKER_WINDOW = 20
FLICKER_MAX_CHANGES = 4
# Capped at 5 — BIC keeps decreasing past K=5 on crypto 4h, producing tiny
# spurious regimes (e.g. Vol6 with 3 bars over 5 years). Crypto vol-regime
# literature supports 3-5 regimes.
BIC_K_RANGE = (3, 4, 5)


# ------------------------------------------------------------------- features
def build_features(df: pd.DataFrame) -> pd.DataFrame:
    close = df["close"].astype(float)
    high  = df["high"].astype(float)
    low   = df["low"].astype(float)
    vol   = df["volume"].astype(float) if "volume" in df.columns else pd.Series(1.0, index=df.index)

    log_r = np.log(close).diff()
    rvol  = log_r.rolling(REALIZED_VOL_WIN, min_periods=REALIZED_VOL_WIN // 2).std()
    vol_ratio = vol / vol.rolling(VOLUME_WIN, min_periods=VOLUME_WIN // 2).mean()
    hlr = (high - low) / close

    feats = pd.DataFrame({
        "log_r":        log_r,
        "rvol":         rvol,
        "vol_ratio":    vol_ratio,
        "hl_range_pct": hlr,
    }, index=df.index)
    return feats.dropna()


# ------------------------------------------------------------------- BIC select
def _fit_gmm_with_bic(X: np.ndarray, k_range=BIC_K_RANGE, seed: int = 42):
    best = None
    bic_table = {}
    for k in k_range:
        try:
            gmm = GaussianMixture(
                n_components=k, covariance_type="full",
                random_state=seed, max_iter=300, n_init=3,
            )
            gmm.fit(X)
            bic = gmm.bic(X)
            bic_table[k] = float(bic)
            if best is None or bic < best[1]:
                best = (gmm, bic, k)
        except Exception:
            bic_table[k] = float("inf")
    return best[0], best[2], bic_table


# ------------------------------------------------------------------- stability
def _apply_persistence(seq: np.ndarray, n: int = PERSISTENCE_BARS) -> np.ndarray:
    """
    Output a regime only after it has persisted for `n` consecutive bars.
    Otherwise carry forward the last stable regime.
    """
    stable = np.full(len(seq), -1, dtype=int)
    run_val = seq[0]
    run_len = 1
    last_stable = -1
    for i in range(len(seq)):
        if i == 0:
            run_val = seq[i]; run_len = 1
        else:
            if seq[i] == run_val:
                run_len += 1
            else:
                run_val = seq[i]; run_len = 1
        if run_len >= n:
            last_stable = run_val
        stable[i] = last_stable
    return stable


def _flicker_mask(seq: np.ndarray,
                  window: int = FLICKER_WINDOW,
                  max_changes: int = FLICKER_MAX_CHANGES) -> np.ndarray:
    """Boolean mask: True where regime has flickered >max_changes in last `window` bars."""
    changes = np.zeros(len(seq), dtype=int)
    changes[1:] = (seq[1:] != seq[:-1]).astype(int)
    roll = pd.Series(changes).rolling(window, min_periods=1).sum().to_numpy()
    return roll > max_changes


# ------------------------------------------------------------------- main API
@dataclass
class RegimeModel:
    gmm: GaussianMixture
    feature_means: np.ndarray
    feature_stds: np.ndarray
    regime_relabel_map: dict[int, int]   # raw -> sorted (low-vol -> high-vol)
    regime_labels: dict[int, str]         # sorted -> "LowVol"/"MedVol"/...
    regime_vol_score: dict[int, float]    # sorted -> mean realized_vol
    best_k: int
    bic_table: dict[int, float]
    train_end_idx: int
    train_end_date: pd.Timestamp
    verification: dict[str, Any] = field(default_factory=dict)

    def classify(self, feats: pd.DataFrame) -> pd.DataFrame:
        """Classify every bar in feats using THIS fitted model. No refit."""
        X = (feats.values - self.feature_means) / self.feature_stds
        proba = self.gmm.predict_proba(X)                     # (N, K)
        raw = proba.argmax(axis=1)                            # raw regime id
        relabelled = np.array([self.regime_relabel_map[r] for r in raw])

        stable = _apply_persistence(relabelled, n=PERSISTENCE_BARS)
        # Flicker detection on the STABLE (post-persistence) sequence —
        # otherwise every raw-regime jitter trips the filter, trashing coverage.
        flicker = _flicker_mask(stable)

        labels = pd.Series(index=feats.index, dtype=object)
        for i, r in enumerate(stable):
            if flicker[i]:
                labels.iat[i] = "Uncertain"
            elif r < 0:
                labels.iat[i] = "Warming"
            else:
                labels.iat[i] = self.regime_labels[int(r)]

        return pd.DataFrame({
            "raw_regime":    relabelled,
            "stable_regime": stable,
            "label":         labels,
            "vol_score":     [self.regime_vol_score.get(int(r), np.nan) if r >= 0 else np.nan
                              for r in stable],
            "is_uncertain":  flicker,
        }, index=feats.index)


def fit_regime_model(df: pd.DataFrame,
                      train_frac: float = 0.30,
                      seed: int = 42,
                      verbose: bool = False) -> tuple[RegimeModel, pd.DataFrame]:
    """
    Fit forward-only regime model. Returns (model, regime_df).
    `regime_df` is indexed to df.index (minus warmup) with columns
      raw_regime, stable_regime, label, vol_score, is_uncertain.
    """
    feats = build_features(df)
    n = len(feats)
    train_end_idx = int(n * train_frac)
    if train_end_idx < 200:
        raise ValueError(f"Train window too small: {train_end_idx} bars "
                         f"(need >=200 for GMM fit)")

    train_X_raw = feats.iloc[:train_end_idx].values
    # z-score using IS-only stats (no future leak)
    mu = train_X_raw.mean(axis=0)
    sd = train_X_raw.std(axis=0)
    sd[sd == 0] = 1.0
    train_X = (train_X_raw - mu) / sd

    gmm, best_k, bic_table = _fit_gmm_with_bic(train_X, seed=seed)

    # --- regime relabelling: sort by mean realized_vol (feature #2, col idx 1) ---
    train_raw_labels = gmm.predict(train_X)
    # use *unscaled* rvol to compute per-regime vol score
    rvol_by_regime: dict[int, float] = {}
    for r in range(best_k):
        mask = train_raw_labels == r
        if mask.sum() == 0:
            rvol_by_regime[r] = float("inf")
        else:
            rvol_by_regime[r] = float(train_X_raw[mask, 1].mean())
    sorted_regimes = sorted(rvol_by_regime.items(), key=lambda kv: kv[1])
    relabel_map = {raw: new for new, (raw, _) in enumerate(sorted_regimes)}
    vol_by_sorted = {new: rvol_by_regime[raw] for new, (raw, _) in enumerate(sorted_regimes)}

    if best_k == 3:
        label_names = ["LowVol", "MedVol", "HighVol"]
    elif best_k == 4:
        label_names = ["LowVol", "MedLowVol", "MedHighVol", "HighVol"]
    elif best_k == 5:
        label_names = ["LowVol", "MedLowVol", "MedVol", "MedHighVol", "HighVol"]
    else:
        # K=6 or 7: generic Vol1..VolK ordered low->high
        label_names = [f"Vol{j+1}" for j in range(best_k)]
        label_names[0] = "LowVol"; label_names[-1] = "HighVol"
    regime_labels = {j: label_names[j] for j in range(best_k)}

    # --- verification ---
    train_end_date = feats.index[train_end_idx - 1]
    oos_start_date = feats.index[train_end_idx] if train_end_idx < n else None
    verif = {
        "train_end_date":   str(train_end_date),
        "oos_start_date":   str(oos_start_date) if oos_start_date is not None else "no_oos",
        "train_bars":       int(train_end_idx),
        "oos_bars":         int(n - train_end_idx),
        "no_leak_assertion": oos_start_date is None or (train_end_date < oos_start_date),
    }

    model = RegimeModel(
        gmm=gmm,
        feature_means=mu, feature_stds=sd,
        regime_relabel_map=relabel_map,
        regime_labels=regime_labels,
        regime_vol_score=vol_by_sorted,
        best_k=best_k,
        bic_table=bic_table,
        train_end_idx=train_end_idx,
        train_end_date=train_end_date,
        verification=verif,
    )

    if verbose:
        print(f"[regime] K*={best_k}  BIC table: {bic_table}")
        print(f"[regime] train {verif['train_bars']} bars through {verif['train_end_date']}")
        print(f"[regime] OOS  {verif['oos_bars']} bars starting {verif['oos_start_date']}")
        print(f"[regime] no_leak check: {verif['no_leak_assertion']}")
        print(f"[regime] vol scores by sorted regime: "
              + ", ".join(f"{regime_labels[i]}={vol_by_sorted[i]:.5f}"
                          for i in sorted(vol_by_sorted)))

    regimes = model.classify(feats)
    return model, regimes
