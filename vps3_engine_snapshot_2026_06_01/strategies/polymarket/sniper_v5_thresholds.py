"""Phase 35 — pre-computed threshold constants per spec §9.

Derived from May 1-22 2026 training window. Recompute monthly via
``tools/sniper_v5/recompute_thresholds.py`` (operator-run; out of scope
for Phase 35 plan-time deploy).

All values are LITERAL CONSTANTS — NOT runtime-fetched, NOT env-overridable.
The whole point of this module is to lockbox the thresholds at deploy time
so live signals match the backtest evidence in spec §4. Test
``test_thresholds.py`` lockboxes the exact numbers; ANY edit to this file
that changes a value MUST also update the test (and the operator MUST
re-run the spec §4 backtest validation against the new value).

Phase 35 explicitly OMITS the CCI threshold from spec §9 (defined but no
sleeve uses it — see CONTEXT.md Deferred §4). The constant is NOT exported.

Pure module: no IO, no network, zero engine/venues/feed imports. Safe to
import from any gate function or test fixture without side effects.
"""
from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------
# Per-(asset, tf) thresholds (spec §9 lines 751-767)
# ---------------------------------------------------------------------

TREND_SLOPE_P75_THR: Final[dict[tuple[str, str], float]] = {
    ("BTC", "5m"):  0.385,
    ("ETH", "5m"):  0.398,
    ("SOL", "5m"):  0.412,
    ("BTC", "15m"): 0.612,
    ("ETH", "15m"): 0.624,
    ("SOL", "15m"): 0.643,
}

VOL_HIGH_RV60_THR: Final[dict[tuple[str, str], float]] = {
    ("BTC", "5m"):  0.0084,
    ("ETH", "5m"):  0.0109,
    ("SOL", "5m"):  0.0142,
    ("BTC", "15m"): 0.0162,
    ("ETH", "15m"): 0.0203,
    ("SOL", "15m"): 0.0271,
}

# FAST_TAKER_LAGV2 (g_top_depth_ge_median) — per-(asset,tf) median of the
# BUY-SIDE best-ask resting $ over the backtest window. LAG_TAKER_GATES report
# (2026-05-29) measured a pooled top-of-book median of ~$19.2 across BTC+ETH;
# applied here per cell pending a per-cell recompute. SOL is excluded (the LAGV2
# family does not trade SOL — net drag, thin book).
DEPTH_MEDIAN_USD: Final[dict[tuple[str, str], float]] = {
    ("BTC", "5m"):  19.2,
    ("ETH", "5m"):  19.2,
    ("BTC", "15m"): 19.2,
    ("ETH", "15m"): 19.2,
}

# ---------------------------------------------------------------------
# Scalar thresholds (spec §9 lines 769-781)
# ---------------------------------------------------------------------

MP_NO_EXTREME_BPS_THR: Final[float] = 100.0          # g_mp_no_extreme upper bound
MP_SKEW_STRONG_BPS_THR: Final[float] = 50.0          # g_mp_skew_strong_with lower bound
RIBBON_TIGHT_BPS_THR: Final[float] = 8.0             # g_tight_ribbon upper bound
NEAR_PIVOT_PCT_THR: Final[float] = 0.005             # g_near_pivot — |close-pp|/close < 0.5%
RF_AGED_MIN_S: Final[int] = 60                       # g_rf_aged minimum age
RF_FRESH_MAX_S: Final[int] = 60                      # g_rf_fresh maximum age
HOD_US_AFTERNOON_UTC: Final[list[int]] = [18, 19, 20, 21, 22]   # US afternoon UTC hours (inclusive)
OFFSET_EARLY_MAX_S: Final[int] = 60                  # g_offset_early upper bound
DEPTH_SUPPORTS_250_MIN_USD: Final[float] = 1500.0    # raw §9 value (the GATE in Plan 35-11 demotes to $150 per §10.6)
DEPTH_250_STRICT_OTHER_MIN_USD: Final[float] = 750.0 # g_depth_250_strict other-side min
SPARSE_BOOK_MIN_EVENTS_60S: Final[int] = 25          # §6 fill_min_book_events sparse filter


# ---------------------------------------------------------------------
# V6 / V7 / V8 thresholds (2026-05-27 extension)
# Spec sources:
#   * V6 §3.6 / §3.8 / §3.9 / §3.10 / §3.11 / §3.12 / §3.13
#   * V7 §3.2 / §3.3 / §3.4 / §3.5 / §3.8 / §3.9
#   * V8 §3.1 / §3.2 / §3.4 / §3.5 / §3.6 / §3.7 / §3.9
# ---------------------------------------------------------------------

# V6 §3.3 — wider microprice ceiling for V6_03 / V6_06 / V6_12 sleeves.
MP_NO_EXTREME_150_BPS_THR: Final[float] = 150.0

# V6 §3.6 — TA indicator thresholds (CCI / BB-position).
CCI_STRONG_THR: Final[float] = 100.0                 # V6 g_cci_strong_with
CCI_EXTREME_THR: Final[float] = 150.0                # V7 §3.8 g_cci_extreme_with
BB_POS_UP_THR: Final[float] = 0.55                   # V6 g_bb_pos_with UP
BB_POS_DN_THR: Final[float] = 0.45                   # V6 g_bb_pos_with DOWN

# V6 §3.9 — Hawkes (loose variant, V5 used 0.30 strong).
HAWKES_LOOSE_THR: Final[float] = 0.10

# V6 §3.8 + V7 §3.2 — Hurst exponent thresholds.
HURST_TRENDING_THR: Final[float] = 0.50              # V6 g_hurst_trending
HURST_REVERTING_THR: Final[float] = 0.40             # V7 g_hurst_reverting
HURST_REGIME_THR: Final[float] = 0.55                # V7 g_hurst_regime_with

# V6 §3.10 + V7 §3.9 — F7 RSI extreme zones.
F7_OVERBOUGHT_THR: Final[float] = 70.0
F7_OVERSOLD_THR: Final[float] = 30.0

# V6 §3.13 — Entry VWAP band filters (book-walk vwap @ stake=$25).
VWAP_BAND_LOW_THR: Final[float] = 0.20
VWAP_BAND_HIGH_THR: Final[float] = 0.80
VWAP_30_70_LOW_THR: Final[float] = 0.30
VWAP_30_70_HIGH_THR: Final[float] = 0.70
VWAP_45_85_LOW_THR: Final[float] = 0.45
VWAP_45_85_HIGH_THR: Final[float] = 0.85
VWAP_55_80_LOW_THR: Final[float] = 0.55
VWAP_55_80_HIGH_THR: Final[float] = 0.80
VWAP_PREMIUM_THR: Final[float] = 0.55
# V10 (2026-05-31) — cheap-entry narrow band (lab universe 01_build_universe_v6.py:260).
VWAP_NARROW_LOW_THR: Final[float] = 0.15
VWAP_NARROW_HIGH_THR: Final[float] = 0.55

# V6 §3.11 + V8 §3.4 — TOD bucket UTC hours (inclusive ranges).
TOD_ASIA_MORNING_UTC: Final[tuple[int, int]] = (0, 6)
TOD_EUROPEAN_MORNING_UTC: Final[tuple[int, int]] = (7, 12)
TOD_US_OPEN_UTC: Final[tuple[int, int]] = (13, 14)
TOD_US_AFTERNOON_UTC: Final[tuple[int, int]] = (13, 18)
TOD_US_EVENING_UTC: Final[tuple[int, int]] = (19, 23)
TOD_EUROPE_US_WINDOW_UTC: Final[tuple[int, int]] = (7, 18)

# V6 §3.12 — Offset window for off_60_240 gate.
OFFSET_60_240_LO_S: Final[int] = 60
OFFSET_60_240_HI_S: Final[int] = 240

# V7 §3.5 — ADX strength + realized-vol medians (training May 1-22).
ADX_STRONG_THR: Final[float] = 25.0
BTC_VOL_LOW_5M_MEDIAN: Final[float] = 0.0042         # V7 g_BTC_vol_low (5m)
ETH_VOL_LOW_5M_MEDIAN: Final[float] = 0.0055         # V7 g_ETH_vol_low (5m)

# V7 §3.5 — BTC 15m trend-slope strong threshold (matches TREND_SLOPE_P75_THR[("BTC","15m")] = 0.612).
BTC_SLOPE_STRONG_15M_THR: Final[float] = 0.612

# V8 §3.1 — 1h grandparent slope strong threshold.
GRANDPARENT_SLOPE_STRONG_THR: Final[float] = 0.85

# V8 §3.7 — Liquidity-shock ratio (depth_now / depth_5s_ago < ratio → shock).
LIQ_SHOCK_RATIO_THR: Final[float] = 0.7

# V8 §3.9 — MFI strong-zone thresholds (vs V6 g_mfi_with midpoint 50).
MFI_STRONG_UP_THR: Final[float] = 60.0
MFI_STRONG_DN_THR: Final[float] = 40.0

# V7 §3.3 — slot-end OFI USD threshold (gate stubbed pending trade subscriber).
SLOT_END_OFI_THR_USD: Final[float] = 100.0

# V6 §3.13 / V8 — L25 book-imbalance "strong" threshold.
# Heuristic; recompute monthly from polymarket book data once gate is live.
IMB5_STRONG_THR: Final[float] = 0.20


__all__ = [
    # Phase 35 (V5)
    "DEPTH_250_STRICT_OTHER_MIN_USD",
    "DEPTH_MEDIAN_USD",
    "DEPTH_SUPPORTS_250_MIN_USD",
    "HOD_US_AFTERNOON_UTC",
    "MP_NO_EXTREME_BPS_THR",
    "MP_SKEW_STRONG_BPS_THR",
    "NEAR_PIVOT_PCT_THR",
    "OFFSET_EARLY_MAX_S",
    "RF_AGED_MIN_S",
    "RF_FRESH_MAX_S",
    "RIBBON_TIGHT_BPS_THR",
    "SPARSE_BOOK_MIN_EVENTS_60S",
    "TREND_SLOPE_P75_THR",
    "VOL_HIGH_RV60_THR",
    # V6 / V7 / V8 (2026-05-27)
    "ADX_STRONG_THR",
    "BB_POS_DN_THR",
    "BB_POS_UP_THR",
    "BTC_SLOPE_STRONG_15M_THR",
    "BTC_VOL_LOW_5M_MEDIAN",
    "CCI_EXTREME_THR",
    "CCI_STRONG_THR",
    "ETH_VOL_LOW_5M_MEDIAN",
    "F7_OVERBOUGHT_THR",
    "F7_OVERSOLD_THR",
    "GRANDPARENT_SLOPE_STRONG_THR",
    "HAWKES_LOOSE_THR",
    "HURST_REGIME_THR",
    "HURST_REVERTING_THR",
    "HURST_TRENDING_THR",
    "IMB5_STRONG_THR",
    "LIQ_SHOCK_RATIO_THR",
    "MFI_STRONG_DN_THR",
    "MFI_STRONG_UP_THR",
    "MP_NO_EXTREME_150_BPS_THR",
    "OFFSET_60_240_HI_S",
    "OFFSET_60_240_LO_S",
    "SLOT_END_OFI_THR_USD",
    "TOD_ASIA_MORNING_UTC",
    "TOD_EUROPEAN_MORNING_UTC",
    "TOD_EUROPE_US_WINDOW_UTC",
    "TOD_US_AFTERNOON_UTC",
    "TOD_US_EVENING_UTC",
    "TOD_US_OPEN_UTC",
    "VWAP_30_70_HIGH_THR",
    "VWAP_30_70_LOW_THR",
    "VWAP_45_85_HIGH_THR",
    "VWAP_45_85_LOW_THR",
    "VWAP_55_80_HIGH_THR",
    "VWAP_55_80_LOW_THR",
    "VWAP_BAND_HIGH_THR",
    "VWAP_BAND_LOW_THR",
    "VWAP_PREMIUM_THR",
]
