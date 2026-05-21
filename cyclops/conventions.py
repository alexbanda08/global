"""
DEPRECATED FEE MODEL — DO NOT QUOTE PnL FROM THIS FILE FORWARD.

This file uses the legacy `FEE_RATE = 0.02` ("2% on profit only, winning leg")
approximation. The real Polymarket fee is:

    fee = C × feeRate × p × (1 − p)

charged on EVERY fill (not just the winner). For crypto markets feeRate = 0.07.
Use `strategy_lab/fees.py` (`poly_fee_usd`, `poly_maker_rebate_usd`) instead.

Kept here for historical reproducibility only. Numbers produced by this file
diverge materially from real Polymarket settlements — re-run via
`engine_v2.fill_at_book` + `fees.poly_fee_usd` before any decision.
"""

"""Cyclops clone — constants and canonical paths.

Single source of truth for all tunables, thresholds, and paths used by
the cyclops package. Phase 1 values come from the spec §4.1. Phase 2
calibration may override TREND_*, LEVELS_*, MOMENTUM_* per ablation.

DO NOT inline magic numbers in other modules — import from here so the
TV-agent env-var contract (§10) stays the only override surface.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
CANONICAL = ROOT / "data" / "v4" / "canonical"
RESULTS_DIR = ROOT / "cyclops" / "_results"

# ---------------------------------------------------------------------------
# Fill model
# ---------------------------------------------------------------------------

NOTIONAL_USD = 25.0
FEE_RATE = 0.02                            # legacy fee model: 2% on profit only

# ---------------------------------------------------------------------------
# Anchor convention (see CLAUDE.md — ws_s != slot_start)
# ---------------------------------------------------------------------------

WINDOW_S = {"5m": 300, "15m": 900}
FIRE_OFFSET_S = 120                        # production momo fires at ws_s + 120

# ---------------------------------------------------------------------------
# Axis thresholds (Phase 1 values — tune in P2 calibration)
# ---------------------------------------------------------------------------

TREND_MIN_ABS = 1                          # |alignment| >= 1 to vote (range -3..+3)
LEVELS_MIN_CERTAINTY = 0.15                # |p_up - 0.5| >= 0.15 to vote
MOMENTUM_MIN_STRENGTH = 0.15               # |flow_score| >= 0.15 to vote

# Trend axis (Q1): K bars per TF + total-window-fraction threshold.
# K values are chosen so all three TFs cover ~24-25h of lookback, which is
# why a single fraction threshold (move-over-window / mean_close) is
# scale-invariant across the three timeframes.
# Eps target ~30% abstain / 35% +1 / 35% -1 — re-calibrate in P2.
TREND_K_BARS = {"1h": 25, "15m": 100, "5m": 288}
TREND_EPS_FRAC = 5e-3                      # |slope * K / mean_close| > 50bp ⇒ vote

# Levels axis (Q2): swing pivot detection + p_up scaling.
LEVELS_LOOKBACK_DAYS = 5                   # how far back to scan for pivots (15m bars)
LEVELS_K_CONFIRM = 5                       # bars-before/after to confirm a swing
LEVELS_SCALE = 0.4                         # p_up = 0.5 + scale * dist_ratio

# Momentum axis (Q3): composite weights + look-back windows.
MOMENTUM_W_IMBALANCE_L5 = 0.4
MOMENTUM_W_CVD_1M = 0.3
MOMENTUM_W_AGGRESSOR_30S = 0.3
MOMENTUM_WINDOW_S = 60                     # OB / trade lookback for imbalance + CVD
MOMENTUM_AGGRESSOR_WINDOW_S = 30
MOMENTUM_CVD_CAP_USD = 25_000.0            # normaliser for CVD score

# ---------------------------------------------------------------------------
# Conflict filter
# ---------------------------------------------------------------------------

ABSTAIN_LIMIT = 2                          # if 2+ axes abstain → skip

# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------

MAX_DRAWDOWN_PCT = 5.0
DAILY_LOSS_LIMIT_PCT = 2.0
RECOVERY_RESUME_FACTOR = 0.5

# ---------------------------------------------------------------------------
# Cooldowns
# ---------------------------------------------------------------------------

REENTRY_COOLDOWN_SEC = 30

# ---------------------------------------------------------------------------
# OB manipulation
# ---------------------------------------------------------------------------

OB_VOLATILITY_WINDOW_S = 5
OB_VOLATILITY_THRESHOLD = 0.5

# ---------------------------------------------------------------------------
# Blowoff guard (regime-ASYMMETRIC per Cyclops Day 3)
# ---------------------------------------------------------------------------

BLOWOFF_RSI_THRESHOLD = 60.0
BLOWOFF_MIN_MTF_ABS = 3
BLOWOFF_GUARD_UP = True                    # block UP-blowoff entries
BLOWOFF_GUARD_DOWN = False                 # allow DOWN-blowoff entries

# ---------------------------------------------------------------------------
# Trading hours (UTC, fractional hours supported)
# ---------------------------------------------------------------------------

TRADING_START_UTC = 13.0                   # placeholder — recalibrate via P3 hourly split
TRADING_STOP_UTC = 21.0
PAUSE_WINDOWS_UTC: list[tuple[float, float]] = []
WEEKEND_OFF = True

# ---------------------------------------------------------------------------
# VWAP / indicator windows
# ---------------------------------------------------------------------------

VWAP_WINDOW_BARS = 24                      # 2h of 5m bars
BB_PERIOD = 20
BB_STDEV = 2.0
RSI_PERIOD = 14

# ---------------------------------------------------------------------------
# Sizing bounds (Phase 2 confidence_scaled)
# ---------------------------------------------------------------------------

MIN_NOTIONAL_USD = 10.0
MAX_NOTIONAL_USD = 50.0

# ---------------------------------------------------------------------------
# Sleeve identity
# ---------------------------------------------------------------------------

SLEEVE_ID = "poly_updown_btc_5m_cyclops_v1"
