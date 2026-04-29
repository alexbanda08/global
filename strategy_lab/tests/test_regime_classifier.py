"""
Phase 2 unit tests — regime classifier correctness on synthetic data.

Covers:
  * End-to-end smoke test with the default 3-voter ensemble.
  * Warmup returns the neutral label with 0 confidence.
  * No-lookahead shift invariance (classify(df[:-k]) == classify(df)[:-k]).
  * Hysteresis suppresses 1-bar whipsaws.
  * Label-mapping covers all (trend_score, vol_state) combinations.
  * Voter independence — disabling any single voter still produces valid labels.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "strategy_lab"))

from regime import classify_regime, RegimeConfig, REGIME_LABELS, REGIME_4H_PRESET  # noqa: E402
from regime.regime_classifier import _label_from_score_and_vol  # noqa: E402


# ---------------------------------------------------------------------
# Synthetic data generator
# ---------------------------------------------------------------------
def synthesize_ohlcv(
    n_bars: int = 2000,
    *,
    drift: float = 0.0,
    vol: float = 0.01,
    freq: str = "4h",
    start: str = "2020-01-01",
    seed: int = 42,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start=start, periods=n_bars, freq=freq, tz="UTC")
    rets = rng.normal(drift, vol, size=n_bars)
    close = 10000.0 * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[close[0]], close[:-1]])
    spread = np.abs(rng.normal(0, vol * 0.5, size=n_bars))
    high = np.maximum(open_, close) * (1 + spread)
    low = np.minimum(open_, close) * (1 - spread)
    volume = rng.lognormal(mean=np.log(1_000_000), sigma=0.3, size=n_bars)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


@pytest.fixture(scope="module")
def random_walk_4h():
    return synthesize_ohlcv(n_bars=2000, drift=0.0, vol=0.01)


@pytest.fixture(scope="module")
def strong_uptrend_4h():
    # 2000 bars with small positive drift → persistent up-trend
    return synthesize_ohlcv(n_bars=2000, drift=0.002, vol=0.008)


@pytest.fixture(scope="module")
def strong_downtrend_4h():
    return synthesize_ohlcv(n_bars=2000, drift=-0.002, vol=0.008)


# ---------------------------------------------------------------------
# 1. End-to-end smoke
# ---------------------------------------------------------------------
def test_smoke_runs_and_returns_valid_schema(random_walk_4h):
    res = classify_regime(random_walk_4h, config=REGIME_4H_PRESET)
    assert list(res.columns) == ["label", "confidence", "trend_score", "vol_state", "change_pt"]
    assert len(res) == len(random_walk_4h)
    assert set(res["label"].dropna().unique()).issubset(REGIME_LABELS)
    assert ((res["confidence"] >= 0.0) & (res["confidence"] <= 1.0)).all()
    assert ((res["trend_score"] >= -3.0) & (res["trend_score"] <= 3.0)).all()


# ---------------------------------------------------------------------
# 2. Warmup behaviour
# ---------------------------------------------------------------------
def test_warmup_returns_neutral_label_with_zero_confidence(random_walk_4h):
    cfg = REGIME_4H_PRESET
    res = classify_regime(random_walk_4h, config=cfg)
    warm_slice = res.iloc[: cfg.warmup_bars]
    assert (warm_slice["label"] == cfg.neutral_label).all()
    assert (warm_slice["confidence"] == 0.0).all()


# ---------------------------------------------------------------------
# 3. No-lookahead — truncating history must NOT change past labels.
# ---------------------------------------------------------------------
@pytest.mark.parametrize("k", [1, 5, 10, 100])
def test_no_lookahead_shift_invariance(random_walk_4h, k):
    # Use a config without GMM so we avoid the GMM refit fit-drift across
    # truncation boundaries. Trend + vol-quantile + hurst are strictly trailing.
    cfg = RegimeConfig(
        voters=("trend_adx_ema", "vol_quantile", "hurst"),
        trend_weights={"trend_adx_ema": 1.0, "hurst": 0.5},
        vol_weights={"vol_quantile": 1.0},
        n_confirm_bars=REGIME_4H_PRESET.n_confirm_bars,
        n_hold_floor_bars=REGIME_4H_PRESET.n_hold_floor_bars,
    )

    full = classify_regime(random_walk_4h, config=cfg)
    truncated = classify_regime(random_walk_4h.iloc[: len(random_walk_4h) - k], config=cfg)

    full_past = full.iloc[: len(truncated)]
    # Labels and trend_score past the warmup must match exactly.
    w = cfg.warmup_bars
    pd.testing.assert_series_equal(
        full_past["label"].iloc[w:].reset_index(drop=True),
        truncated["label"].iloc[w:].reset_index(drop=True),
        check_names=False, check_dtype=False,
    )
    np.testing.assert_allclose(
        full_past["trend_score"].iloc[w:].values,
        truncated["trend_score"].iloc[w:].values,
        atol=1e-10,
    )


# ---------------------------------------------------------------------
# 4. Label mapping covers every combination deterministically.
# ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "trend_score,vol_state,expected",
    [
        (+2.5, "low",    "strong_uptrend"),
        (+2.0, "high",   "strong_uptrend"),
        (+1.5, "normal", "weak_uptrend"),
        (+1.0, "low",    "weak_uptrend"),
        ( 0.5, "low",    "sideways_low_vol"),
        ( 0.0, "high",   "sideways_high_vol"),
        ( 0.0, "normal", "sideways_low_vol"),
        (-0.8, "high",   "sideways_high_vol"),
        (-1.0, "low",    "weak_downtrend"),
        (-1.5, "high",   "weak_downtrend"),   # trend dominates — vol only splits sideways
        (-2.0, "normal", "strong_downtrend"),
        (-3.0, "low",    "strong_downtrend"),
    ],
)
def test_label_mapping_covers_all_combinations(trend_score, vol_state, expected):
    assert _label_from_score_and_vol(trend_score, vol_state) == expected


# ---------------------------------------------------------------------
# 5. Hysteresis suppresses a one-bar whipsaw.
# ---------------------------------------------------------------------
def test_hysteresis_suppresses_single_bar_flip():
    """
    Craft raw labels with a 1-bar flip, feed through the hysteresis
    helper directly. It should NOT switch (n_confirm=3 > 1).
    """
    from regime.regime_classifier import _apply_hysteresis

    raw = pd.Series([
        "strong_uptrend"] * 20
      + ["strong_downtrend"]        # single-bar flip
      + ["strong_uptrend"] * 20
    )
    conf = pd.Series([0.9] * len(raw))
    smoothed = _apply_hysteresis(
        raw, conf, n_confirm=3, n_hold_floor=5, min_conf_for_category=0.6,
    )
    # The single flip should be absorbed — the whole series stays strong_uptrend.
    assert (smoothed == "strong_uptrend").all()


def test_hysteresis_allows_confirmed_switch():
    from regime.regime_classifier import _apply_hysteresis

    raw = pd.Series([
        "strong_uptrend"] * 10
      + ["strong_downtrend"] * 10        # sustained flip — must eventually switch
    )
    conf = pd.Series([0.9] * len(raw))
    smoothed = _apply_hysteresis(
        raw, conf, n_confirm=3, n_hold_floor=5, min_conf_for_category=0.6,
    )
    # Last value must be the new regime.
    assert smoothed.iloc[-1] == "strong_downtrend"
    # Switch point should be after warmup + n_confirm = bar 12 or 13.
    switch_bars = (smoothed != smoothed.shift(1)).sum()
    assert switch_bars == 2    # exactly one state change (+ the initial assignment)


# ---------------------------------------------------------------------
# 6. Voter independence — disable each voter one at a time.
# ---------------------------------------------------------------------
@pytest.mark.parametrize("disabled", ["trend_adx_ema", "vol_quantile", "gmm_trendvol"])
def test_voter_independence(random_walk_4h, disabled):
    voters = tuple(v for v in REGIME_4H_PRESET.voters if v != disabled)
    cfg = RegimeConfig(voters=voters)
    res = classify_regime(random_walk_4h, config=cfg)
    assert len(res) == len(random_walk_4h)
    assert set(res["label"].dropna().unique()).issubset(REGIME_LABELS)


# ---------------------------------------------------------------------
# 7. Strong-trend inputs produce trend labels above warmup.
# ---------------------------------------------------------------------
def test_strong_uptrend_synthetic_gets_up_labels(strong_uptrend_4h):
    cfg = REGIME_4H_PRESET
    res = classify_regime(strong_uptrend_4h, config=cfg)
    post = res.iloc[cfg.warmup_bars + 100:]   # skip warmup + ensemble spool-up
    up_frac = (post["label"].isin(["strong_uptrend", "weak_uptrend"])).mean()
    assert up_frac >= 0.4, f"expected ≥ 40% uptrend labels on synthetic uptrend, got {up_frac:.2%}"


def test_strong_downtrend_synthetic_gets_down_labels(strong_downtrend_4h):
    cfg = REGIME_4H_PRESET
    res = classify_regime(strong_downtrend_4h, config=cfg)
    post = res.iloc[cfg.warmup_bars + 100:]
    dn_frac = (post["label"].isin(["strong_downtrend", "weak_downtrend"])).mean()
    assert dn_frac >= 0.4, f"expected ≥ 40% downtrend labels on synthetic downtrend, got {dn_frac:.2%}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
