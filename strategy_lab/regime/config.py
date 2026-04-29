"""
RegimeConfig — frozen dataclass driving classify_regime().

Presets for 4h, 1h, 15m. 30m derives from 1h at runtime.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class RegimeConfig:
    """
    Ensemble configuration for the 6-label regime classifier.
    """

    voters: tuple[str, ...] = ("trend_adx_ema", "vol_quantile", "gmm_trendvol")
    # Rebalanced 2026-04-23 after historical regression showed GMM over-flipping
    # during bear-market relief rallies. ADX+EMA is now the dominant trend voice.
    trend_weights: Mapping[str, float] = field(default_factory=lambda: {
        "trend_adx_ema": 1.5,
        "gmm_trendvol":  0.5,
        "hurst":         0.5,
    })
    vol_weights: Mapping[str, float] = field(default_factory=lambda: {
        "vol_quantile":  1.0,
        "gmm_trendvol":  0.5,
    })

    # --- Hysteresis (trailing-only) -----------------------------------
    n_confirm_bars: int = 3
    n_hold_floor_bars: int = 5
    category_switch_min_confidence: float = 0.6

    # --- Trend (ADX + EMA slope) voter --------------------------------
    # Retuned 2026-04-23: longer EMAs capture structural crypto trends
    # (monthly+), weak-slope floor prevents ADX>20 + near-flat slope from
    # being called a weak trend.
    adx_period: int = 14
    adx_weak_threshold: float = 25.0     # raised from 22 so ranges with mild ADX stay sideways
    adx_strong_threshold: float = 30.0
    ema_slope_fast: int = 50
    ema_slope_slow: int = 200
    ema_slope_weak_pct: float = 0.010    # 1% minimum slope magnitude for weak trend
    ema_slope_strong_pct: float = 0.025  # 2.5% for strong trend

    # --- GMM voter (HMM stand-in; see 02_REGIME_LAYER_RESEARCH.md § 1b)
    gmm_n_components: int = 3
    gmm_covariance_type: str = "full"
    gmm_random_state: int = 42
    gmm_train_window: int = 2000      # in-sample window for fit (expanding)
    gmm_refit_bars: int = 500         # re-fit cadence after initial training

    # --- Vol quantile voter ------------------------------------------
    vol_window: int = 20
    vol_low_quantile: float = 0.33
    vol_high_quantile: float = 0.66
    vol_expanding_min_bars: int = 500

    # --- Hurst voter (optional) --------------------------------------
    hurst_window: int = 100
    hurst_trend_threshold: float = 0.55
    hurst_revert_threshold: float = 0.45

    # --- Global ------------------------------------------------------
    warmup_bars: int = 500
    neutral_label: str = "sideways_low_vol"

    def config_hash(self) -> str:
        """Stable hash for cache filenames."""
        import hashlib, json
        payload = json.dumps({
            "voters": list(self.voters),
            "tw": dict(sorted(self.trend_weights.items())),
            "vw": dict(sorted(self.vol_weights.items())),
            "conf": self.n_confirm_bars,
            "hold": self.n_hold_floor_bars,
            "min_conf": self.category_switch_min_confidence,
            "adx": (self.adx_period, self.adx_weak_threshold, self.adx_strong_threshold),
            "ema": (self.ema_slope_fast, self.ema_slope_slow, self.ema_slope_strong_pct),
            "gmm": (self.gmm_n_components, self.gmm_covariance_type,
                    self.gmm_random_state, self.gmm_train_window, self.gmm_refit_bars),
            "vol": (self.vol_window, self.vol_low_quantile,
                    self.vol_high_quantile, self.vol_expanding_min_bars),
            "hurst": (self.hurst_window, self.hurst_trend_threshold, self.hurst_revert_threshold),
            "warmup": self.warmup_bars,
        }, sort_keys=True)
        return hashlib.sha1(payload.encode()).hexdigest()[:10]


# -----------------------------------------------------------------------
# Per-TF presets
# -----------------------------------------------------------------------
REGIME_4H_PRESET = RegimeConfig(
    n_confirm_bars=3,
    n_hold_floor_bars=5,
    adx_period=14,
    ema_slope_fast=50,
    ema_slope_slow=200,
    vol_window=20,
    warmup_bars=500,
)

REGIME_1H_PRESET = RegimeConfig(
    n_confirm_bars=6,
    n_hold_floor_bars=12,
    adx_period=14,
    ema_slope_fast=200,
    ema_slope_slow=800,
    vol_window=48,
    warmup_bars=1000,
)

REGIME_15M_PRESET = RegimeConfig(
    n_confirm_bars=12,
    n_hold_floor_bars=24,
    adx_period=14,
    ema_slope_fast=800,
    ema_slope_slow=3200,
    vol_window=96,
    warmup_bars=2000,
)
