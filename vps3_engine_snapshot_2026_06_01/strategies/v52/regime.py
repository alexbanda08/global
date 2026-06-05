"""V52 regime classifier — GMM fit/save/load + JSON roundtrip (Phase 8.1 Task 5).

JSON-persistence design (RESEARCH Q1):
  - Filesystem JSON at `/var/lib/tv/v52/regime_<coin>.json`.
  - DB pointer row in `engine.v52_regime_models` (table 0008) with audit
    fields (fit_hash, fit_timestamp, sklearn_version, train_bar_count).
  - Load-time SHA256 mismatch → CRITICAL alert (T-8.1-01).

JSON schema:
  {
    "schema_version": "1.0",
    "coin": "ETH",
    "weights": [...K floats...],
    "means": [[...]],          # shape (K, n_features)
    "covariances": [[[...]]],  # shape (K, n_features, n_features)
    "covariance_type": "full",
    "n_components": K,
    "label_map": {"0": "LowVol", "1": "MedVol", "2": "HighVol"},
    "sklearn_version": "1.5.2",
    "fit_hash": "<sha256 hex>",
    "fit_timestamp": "2026-04-24T12:34:56+00:00",
    "train_bar_count": 1500
  }

Roundtrip-loaded GMM uses `.set_params()` + manual attribute assignment so
`predict_proba(X)` reproduces the fit-time `predict_proba(X)` to 1e-12.

Frozen regime label set per canonical adaptive:31-39:
  LowVol, MedLowVol, MedVol, MedHighVol, HighVol, Uncertain, Warming
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

# Frozen label set per canonical perps_simulator_adaptive_exit:31-39.
REGIME_LABELS_FROZEN = (
    "LowVol",
    "MedLowVol",
    "MedVol",
    "MedHighVol",
    "HighVol",
    "Uncertain",
    "Warming",
)

# K=3 default label map (sorted by per-cluster mean-volatility ascending).
_K3_LABELS = ("LowVol", "MedVol", "HighVol")
_K5_LABELS = ("LowVol", "MedLowVol", "MedVol", "MedHighVol", "HighVol")


def _import_gmm() -> Any:
    """Lazy import sklearn so module is importable without sklearn at module-load."""
    from sklearn.mixture import GaussianMixture  # type: ignore[import-not-found]

    return GaussianMixture


def _sklearn_version() -> str:
    import sklearn  # type: ignore[import-not-found]

    return str(sklearn.__version__)


def _label_map_from_means(means: np.ndarray) -> dict[int, str]:
    """Sort components by mean volatility (feature 0 == log-return std proxy)
    ascending and assign frozen labels.

    For K=3 → (LowVol, MedVol, HighVol).
    For K=5 → (LowVol, MedLowVol, MedVol, MedHighVol, HighVol).
    Other K → fall back to numeric labels (caller should use K=3 or K=5).
    """
    K = means.shape[0]
    # Per-component variance proxy: use absolute mean as a stand-in if features
    # are 1-D log-returns; for multi-feature inputs the caller should ensure
    # feature 0 is the volatility proxy.
    proxy = np.abs(means).sum(axis=1) if means.ndim == 2 else np.abs(means)
    order = np.argsort(proxy)
    if K == 3:
        labels = _K3_LABELS
    elif K == 5:
        labels = _K5_LABELS
    else:
        return {int(idx): f"Regime{rank}" for rank, idx in enumerate(order)}
    return {int(idx): labels[rank] for rank, idx in enumerate(order)}


def _compute_fit_hash(
    means: np.ndarray,
    covariances: np.ndarray,
    weights: np.ndarray,
    label_map: dict[int, str],
) -> str:
    h = hashlib.sha256()
    h.update(means.tobytes())
    h.update(covariances.tobytes())
    h.update(weights.tobytes())
    h.update(json.dumps(label_map, sort_keys=True).encode("utf-8"))
    return h.hexdigest()


def fit_regime(
    returns: np.ndarray,
    n_components: int = 3,
    random_state: int = 42,
    n_init: int = 3,
) -> Any:
    """Fit a GaussianMixture on a 1-D returns array; returns fitted GMM.

    Inputs:
      returns: shape (N,) or (N, 1). Internally reshaped to (N, 1).
    Spec §3.2 mandates `random_state=42, n_init=3`. Reproducibility verified
    in `test_v52_regime_reproducibility.py` (3-fit parity to 1e-12).
    """
    GaussianMixture = _import_gmm()
    X = returns.reshape(-1, 1) if returns.ndim == 1 else returns
    gmm = GaussianMixture(
        n_components=n_components,
        random_state=random_state,
        n_init=n_init,
        covariance_type="full",
    )
    gmm.fit(X)
    return gmm


def save_regime_json(
    gmm: Any,
    coin: str,
    path: str | Path,
    train_bar_count: int,
) -> dict[str, Any]:
    """Serialize fitted GMM to disk (JSON) per RESEARCH Q1 schema.

    Returns the in-memory dict that was written (caller may persist a DB
    pointer row from `fit_hash` + `fit_timestamp`).
    """
    means = np.asarray(gmm.means_)
    covariances = np.asarray(gmm.covariances_)
    weights = np.asarray(gmm.weights_)
    label_map = _label_map_from_means(means)

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "coin": coin,
        "weights": weights.tolist(),
        "means": means.tolist(),
        "covariances": covariances.tolist(),
        "covariance_type": getattr(gmm, "covariance_type", "full"),
        "n_components": int(gmm.n_components),
        "label_map": {str(k): v for k, v in label_map.items()},
        "sklearn_version": _sklearn_version(),
        "fit_hash": _compute_fit_hash(means, covariances, weights, label_map),
        "fit_timestamp": _dt.datetime.now(_dt.UTC).isoformat(),
        "train_bar_count": int(train_bar_count),
    }
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def load_regime_json(path: str | Path) -> Any:
    """Reconstruct a fitted GMM from JSON. Verifies fit_hash on load.

    Raises ValueError if `fit_hash` doesn't match recomputed value (T-8.1-01).
    """
    GaussianMixture = _import_gmm()
    payload = json.loads(Path(path).read_text(encoding="utf-8"))

    means = np.asarray(payload["means"], dtype=float)
    covariances = np.asarray(payload["covariances"], dtype=float)
    weights = np.asarray(payload["weights"], dtype=float)
    label_map = {int(k): v for k, v in payload["label_map"].items()}

    expected_hash = payload["fit_hash"]
    actual_hash = _compute_fit_hash(means, covariances, weights, label_map)
    if expected_hash != actual_hash:
        raise ValueError(
            f"Regime classifier fit_hash mismatch (T-8.1-01): "
            f"expected={expected_hash} actual={actual_hash} path={path}"
        )

    n_components = int(payload["n_components"])
    cov_type = payload.get("covariance_type", "full")
    gmm = GaussianMixture(
        n_components=n_components,
        covariance_type=cov_type,
        random_state=42,
    )
    # Manually populate the fitted attributes so predict_proba works without
    # re-fitting. precisions_cholesky_ derived from covariances.
    gmm.weights_ = weights
    gmm.means_ = means
    gmm.covariances_ = covariances

    # Compute precisions_cholesky_ (required by predict_proba).
    from sklearn.mixture._gaussian_mixture import (  # type: ignore[import-not-found]
        _compute_precision_cholesky,
    )

    gmm.precisions_cholesky_ = _compute_precision_cholesky(covariances, cov_type)
    gmm.converged_ = True
    gmm.n_iter_ = 1
    gmm.lower_bound_ = 0.0
    gmm._label_map = label_map  # attach for predict_regime helper
    return gmm


def predict_regime(gmm: Any, features: np.ndarray) -> str:
    """Return the STRING regime label for the LAST row of `features`.

    Caller responsibility: `features` should be (N, n_features) volatility-
    proxy input matching what `fit_regime` was trained on.
    """
    X = features.reshape(-1, 1) if features.ndim == 1 else features
    cluster_int = int(gmm.predict(X[-1:])[0])
    label_map = getattr(gmm, "_label_map", None)
    if label_map is None:
        label_map = _label_map_from_means(np.asarray(gmm.means_))
    label = label_map.get(cluster_int, "MedVol")
    if label not in REGIME_LABELS_FROZEN:
        return "MedVol"
    return label


__all__ = [
    "REGIME_LABELS_FROZEN",
    "fit_regime",
    "save_regime_json",
    "load_regime_json",
    "predict_regime",
]
