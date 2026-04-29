"""Regime voter registry."""
from .base import Voter, VoterOutput
from .trend_adx_ema import TrendAdxEmaVoter
from .vol_quantile import VolQuantileVoter
from .gmm_trendvol import GmmTrendVolVoter
from .hurst import HurstVoter

# Name → class dispatch used by regime_classifier.py
VOTER_REGISTRY: dict[str, type[Voter]] = {
    "trend_adx_ema": TrendAdxEmaVoter,
    "vol_quantile":  VolQuantileVoter,
    "gmm_trendvol":  GmmTrendVolVoter,
    "hurst":         HurstVoter,
}

__all__ = ["Voter", "VoterOutput", "VOTER_REGISTRY",
           "TrendAdxEmaVoter", "VolQuantileVoter",
           "GmmTrendVolVoter", "HurstVoter"]
