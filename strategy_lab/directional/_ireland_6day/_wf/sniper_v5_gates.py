"""Phase 35 — Polymarket sniper-v5 gate library (30+ pure functions).

Per spec §3 + CONTEXT.md `### Gate library (spec §3)`. Each gate:
    - Returns bool (True = pass, False = skip)
    - Is a pure function (no IO, no module-level mutable state)
    - Returns False on missing data (None lookup) — graceful skip
    - Uses thresholds from sniper_v5_thresholds (Plan 35-02 output)
    - Takes uniform (direction, fire_us) positional args so the
      controller in Plan 35-12 can compose them generically

CCI gate (spec §3.7) NOT EXPORTED — see CONTEXT.md Deferred §4.

CLAUDE.md inv #4: gates fire BEFORE signal. They are the pre-trade
filter; failure means "skip this fire" not "kill the strategy".

CLAUDE.md inv #13: no Storedata reads — panel handles passed by
parameter are the only data source.

Exported gates (§ source-of-truth: SHADOW_DEPLOY_SPEC_2026_05_27.md §3):
    §3.1 book/depth (2):
        g_book_depth_supports_250 (demoted no-op per §10.6)
        g_depth_250_strict        (sleeve 06 only)
    §3.2 trend/regime (3):
        g_trend_slope_with, g_trend_slope_strong_with, g_regime_stack_with
    §3.3 microprice (4):
        g_mp_skew_with, g_mp_skew_strong_with,
        g_mp_no_extreme, g_mp_no_extreme_100 (alias)
    §3.4 range filter (4):
        g_rf_with, g_rf_aged, g_rf_fresh, g_rf_strict_align
    §3.5 traders' reality (10):
        g_tr_above_ema50/200/800/cloud/pp,
        g_tr_stack_with, g_tr_stack_full_with, g_tr_partial_stack_with,
        g_tr_within_adr, g_tr_in_active_session
    §3.6 ribbon (2):
        g_ribbon_agrees, g_ribbon_slope_with
    §3.7 CCI: OMITTED (CONTEXT.md Deferred §4)
    §3.8 SMS (2):
        g_sms_liq_reclaim_with, g_sms_no_liquidity_above
    §3.9 vol (1):
        g_vol_high
    §3.10 daily VWAP (2):
        above_1h_dailyvwap, g_above_1h_dailyvwap_with
    §3.11 pivot (1):
        g_near_pivot
    §3.12 offset/time-of-day/direction (4):
        g_offset_early, g_hod_us_afternoon, g_dir_up, g_dir_down
    §3.13 tight ribbon (1):
        g_tight_ribbon

Total: 36 exported gates.
"""
from __future__ import annotations

import math
from typing import Any

from backend.app.features.hawkes_flow import hawkes_lambda_imbalance_for_fire

# ANNUAL_FACTOR_BY_TF — the SAME per-tf annualization the VolHurstPanel applies
# to rv_60 (vol_hurst.py:187). g_vol_contracting still de-annualizes with it
# (legacy, see its own flag). g_vol_high no longer uses it:
# TV_FIX_VOL_HIGH_PERCENTILE_2026_06_03 switched g_vol_high to the backtest's
# rolling-24h percentile gate (VolHurstRow.rv_pct_24h > VOL_HIGH_PCT_THR),
# which is unit-free. vol_hurst is stdlib-only → no circular import.
from backend.app.features.vol_hurst import ANNUAL_FACTOR_BY_TF
from backend.app.strategies.polymarket.sniper_v5_thresholds import (
    # V6 / V7 / V8 extension (2026-05-27)
    ADX_STRONG_THR,
    BB_POS_DN_THR,
    BB_POS_UP_THR,
    BTC_SLOPE_STRONG_15M_THR,
    BTC_VOL_LOW_5M_MEDIAN,
    CCI_EXTREME_THR,
    CCI_STRONG_THR,
    # Phase 35 (V5)
    DEPTH_250_STRICT_OTHER_MIN_USD,
    DEPTH_SUPPORTS_250_MIN_USD,
    ETH_VOL_LOW_5M_MEDIAN,
    F7_OVERBOUGHT_THR,
    F7_OVERSOLD_THR,
    GRANDPARENT_SLOPE_STRONG_THR,
    HAWKES_LOOSE_THR,
    HOD_US_AFTERNOON_UTC,
    HURST_REGIME_THR,
    HURST_REVERTING_THR,
    HURST_TRENDING_THR,
    IMB5_STRONG_THR,
    MFI_STRONG_DN_THR,
    MFI_STRONG_UP_THR,
    MP_NO_EXTREME_150_BPS_THR,
    MP_NO_EXTREME_BPS_THR,
    MP_SKEW_STRONG_BPS_THR,
    NEAR_PIVOT_PCT_THR,
    OFFSET_60_240_HI_S,
    OFFSET_60_240_LO_S,
    OFFSET_EARLY_MAX_S,
    RF_AGED_MIN_S,
    RF_FRESH_MAX_S,
    RIBBON_TIGHT_BPS_THR,
    TOD_ASIA_MORNING_UTC,
    TOD_EUROPE_US_WINDOW_UTC,
    TOD_EUROPEAN_MORNING_UTC,
    TOD_US_AFTERNOON_UTC,
    TOD_US_EVENING_UTC,
    TOD_US_OPEN_UTC,
    TREND_SLOPE_P75_THR,
    VOL_HIGH_PCT_THR,
    VOL_HIGH_RV60_THR,
    VOL_LOW_PCT_THR,
    VWAP_30_70_HIGH_THR,
    VWAP_30_70_LOW_THR,
    VWAP_45_85_HIGH_THR,
    VWAP_45_85_LOW_THR,
    VWAP_55_80_HIGH_THR,
    VWAP_55_80_LOW_THR,
    VWAP_BAND_HIGH_THR,
    VWAP_BAND_LOW_THR,
    VWAP_NARROW_HIGH_THR,
    VWAP_NARROW_LOW_THR,
    VWAP_PREMIUM_THR,
)

# =====================================================================
# §3.1 — Book depth gates
# =====================================================================


def _cum_depth_usd(book: dict | None, levels: int = 25) -> float:
    """Sum (price * size) for the top `levels` ask levels of a book dict.

    Defensive: returns 0.0 on None book, missing/malformed levels, or
    non-numeric price/size. Used only by the §3.1 depth gates.
    """
    if not book:
        return 0.0
    asks = book.get("asks") or []
    total = 0.0
    for lvl in asks[:levels]:
        try:
            total += float(lvl["price"]) * float(lvl["size"])
        except (KeyError, TypeError, ValueError):
            pass
    return total


def _imb5_within(book: dict | None, levels: int = 5) -> float | None:
    """Within-token L5 order imbalance ``(bid_vol - ask_vol)/(bid_vol+ask_vol)``
    over the top ``levels`` levels each side, in shares.

    TV_FIX_IMB5_WITHIN_TOKEN_2026_06_03 — matches the backtest micro panel's
    ``up_imb5``/``dn_imb5`` (build_micro_panel.py:69). Returns None on empty /
    zero-volume book. Range [-1, +1]; >0 = bid-heavy (buying pressure).
    """
    if not book:
        return None

    def _side_vol(side: str) -> float:
        tot = 0.0
        for lvl in (book.get(side) or [])[:levels]:
            try:
                tot += float(lvl["size"])
            except (KeyError, TypeError, ValueError):
                pass
        return tot

    bid = _side_vol("bids")
    ask = _side_vol("asks")
    if bid + ask <= 0.0:
        return None
    return (bid - ask) / (bid + ask)


def g_book_depth_supports_250(
    direction: str,
    fire_us: int,
    *,
    slug: str,
    book_mirror: Any,
    token_id_up: str,
    token_id_dn: str,
    **_kw: Any,
) -> bool:
    """Demoted no-op floor per CONTEXT.md §10.6 — returns True if cum_depth_usd > 150.

    Original spec §3.1 required >$1500 ($250 notional with 6x conservative cushion).
    Operator demoted (no plan to scale to $250) — this gate becomes a near-no-op
    floor. Kept in the registry for stable sleeve definitions. Sleeve 06 uses
    `g_depth_250_strict` instead for the original strict semantics.
    """
    if book_mirror is None:
        return False
    token = token_id_up if direction == "UP" else token_id_dn
    book = book_mirror.get(token)
    return _cum_depth_usd(book) > 150.0


def g_depth_250_strict(
    direction: str,
    fire_us: int,
    *,
    slug: str,
    book_mirror: Any,
    token_id_up: str,
    token_id_dn: str,
    **_kw: Any,
) -> bool:
    """Strict sleeve-06 depth check: chosen-side $1500 AND other-side $750.

    Per CONTEXT.md `### Sleeve 06 special case` (and spec §3.1 strict form).
    Both sides must hit their respective thresholds to pass.
    """
    if book_mirror is None:
        return False
    chosen_token = token_id_up if direction == "UP" else token_id_dn
    other_token = token_id_dn if direction == "UP" else token_id_up
    chosen_depth = _cum_depth_usd(book_mirror.get(chosen_token))
    other_depth = _cum_depth_usd(book_mirror.get(other_token))
    return (
        chosen_depth > DEPTH_SUPPORTS_250_MIN_USD
        and other_depth > DEPTH_250_STRICT_OTHER_MIN_USD
    )


# =====================================================================
# §3.2 — Trend / regime gates
# =====================================================================


def g_trend_slope_with(
    direction: str,
    fire_us: int,
    *,
    asset: str,
    tf: str,
    regime_panel: Any,
    **_kw: Any,
) -> bool:
    """Pass iff sign(trend_slope_30m) matches direction (non-zero slope required)."""
    row = regime_panel.lookup(asset, tf, fire_us)
    if row is None or row.trend_slope_30m is None:
        return False
    slope = row.trend_slope_30m
    if slope == 0:
        return False
    return (slope > 0 and direction == "UP") or (slope < 0 and direction == "DOWN")


def g_trend_slope_strong_with(
    direction: str,
    fire_us: int,
    *,
    asset: str,
    tf: str,
    regime_panel: Any,
    **_kw: Any,
) -> bool:
    """Pass iff |trend_slope_30m| > TREND_SLOPE_P75_THR[(asset,tf)] AND sign matches dir."""
    row = regime_panel.lookup(asset, tf, fire_us)
    if row is None or row.trend_slope_30m is None:
        return False
    slope = row.trend_slope_30m
    thr = TREND_SLOPE_P75_THR.get((asset, tf))
    if thr is None:
        return False
    if abs(slope) <= thr:
        return False
    return (slope > 0 and direction == "UP") or (slope < 0 and direction == "DOWN")


def g_regime_stack_with(
    direction: str,
    fire_us: int,
    *,
    asset: str,
    tf: str,
    regime_panel: Any,
    **_kw: Any,
) -> bool:
    """Pass iff regime_label is `trending_up`/`trending_dn` matching direction."""
    row = regime_panel.lookup(asset, tf, fire_us)
    if row is None or row.regime_label is None:
        return False
    label = row.regime_label
    return (
        (label == "trending_up" and direction == "UP")
        or (label == "trending_dn" and direction == "DOWN")
    )


# =====================================================================
# §3.3 — Microprice gates (MicropricePanel.mp_skew(slug, ts_us))
# =====================================================================


def g_mp_skew_with(
    direction: str,
    fire_us: int,
    *,
    slug: str,
    microprice_panel: Any,
    **_kw: Any,
) -> bool:
    """Pass iff sign(mp_skew_bps) matches direction (non-zero skew required)."""
    s = microprice_panel.mp_skew(slug, fire_us)
    if s is None:
        return False
    if s == 0:
        return False
    return (s > 0 and direction == "UP") or (s < 0 and direction == "DOWN")


def g_mp_skew_strong_with(
    direction: str,
    fire_us: int,
    *,
    slug: str,
    microprice_panel: Any,
    **_kw: Any,
) -> bool:
    """Pass iff |mp_skew_bps| > 50 AND sign matches direction."""
    s = microprice_panel.mp_skew(slug, fire_us)
    if s is None:
        return False
    if abs(s) <= MP_SKEW_STRONG_BPS_THR:
        return False
    return (s > 0 and direction == "UP") or (s < 0 and direction == "DOWN")


def g_mp_no_extreme(
    direction: str,
    fire_us: int,
    *,
    slug: str,
    microprice_panel: Any,
    **_kw: Any,
) -> bool:
    """Pass iff |mp_skew_bps| < 100 (direction-independent — anti-extreme filter)."""
    s = microprice_panel.mp_skew(slug, fire_us)
    if s is None:
        return False
    return abs(s) < MP_NO_EXTREME_BPS_THR


# Spec §3.3 alias: same implementation, just a different name in the sleeve list.
g_mp_no_extreme_100 = g_mp_no_extreme


# =====================================================================
# §3.4 — Range Filter gates (RangeFilterPanel.lookup(asset, ts_us))
# =====================================================================


def g_rf_with(
    direction: str,
    fire_us: int,
    *,
    asset: str,
    rf_panel: Any,
    **_kw: Any,
) -> bool:
    """Pass iff rf_dir matches direction (+1=UP, -1=DOWN). 0 fails both."""
    row = rf_panel.lookup(asset, fire_us)
    if row is None:
        return False
    d = row.rf_dir
    return (d == 1 and direction == "UP") or (d == -1 and direction == "DOWN")


def g_rf_aged(
    direction: str,
    fire_us: int,
    *,
    asset: str,
    rf_panel: Any,
    **_kw: Any,
) -> bool:
    """Pass iff rf_dir matches direction AND rf_dir_age_s >= 60."""
    row = rf_panel.lookup(asset, fire_us)
    if row is None:
        return False
    if row.rf_dir_age_s < RF_AGED_MIN_S:
        return False
    d = row.rf_dir
    return (d == 1 and direction == "UP") or (d == -1 and direction == "DOWN")


def g_rf_fresh(
    direction: str,
    fire_us: int,
    *,
    asset: str,
    rf_panel: Any,
    **_kw: Any,
) -> bool:
    """Pass iff rf_dir matches direction AND rf_dir_age_s <= 60."""
    row = rf_panel.lookup(asset, fire_us)
    if row is None:
        return False
    if row.rf_dir_age_s > RF_FRESH_MAX_S:
        return False
    d = row.rf_dir
    return (d == 1 and direction == "UP") or (d == -1 and direction == "DOWN")


def g_rf_strict_align(
    direction: str,
    fire_us: int,
    *,
    asset: str,
    rf_panel: Any,
    **_kw: Any,
) -> bool:
    """Pass iff rf_dir matches direction AND rf_band_pos aligns with direction.

    UP: rf_dir=+1 AND rf_band_pos>=0.5 (upper half of the RF band)
    DOWN: rf_dir=-1 AND rf_band_pos<=0.5 (lower half)
    """
    row = rf_panel.lookup(asset, fire_us)
    if row is None or row.rf_band_pos is None:
        return False
    d = row.rf_dir
    pos = row.rf_band_pos
    if direction == "UP":
        return d == 1 and pos >= 0.5
    return d == -1 and pos <= 0.5


# =====================================================================
# §3.5 — Traders' Reality / EMA gates (TradersRealityPanel.lookup(asset, ts_us))
# =====================================================================


def _tr_row(tr_panel: Any, asset: str, fire_us: int) -> Any:
    """Tiny adapter so each gate body is one expression."""
    return tr_panel.lookup(asset, fire_us)


def g_tr_above_ema50(
    direction: str, fire_us: int, *, asset: str, tr_panel: Any, **_kw: Any,
) -> bool:
    """Pass iff close vs ema_50 matches direction."""
    row = _tr_row(tr_panel, asset, fire_us)
    if row is None or row.ema_50 is None:
        return False
    return (
        (row.close > row.ema_50 and direction == "UP")
        or (row.close < row.ema_50 and direction == "DOWN")
    )


def g_tr_above_ema200(
    direction: str, fire_us: int, *, asset: str, tr_panel: Any, **_kw: Any,
) -> bool:
    """Pass iff close vs ema_200 matches direction."""
    row = _tr_row(tr_panel, asset, fire_us)
    if row is None or row.ema_200 is None:
        return False
    return (
        (row.close > row.ema_200 and direction == "UP")
        or (row.close < row.ema_200 and direction == "DOWN")
    )


def g_tr_above_ema800(
    direction: str, fire_us: int, *, asset: str, tr_panel: Any, **_kw: Any,
) -> bool:
    """Pass iff close vs ema_800 matches direction."""
    row = _tr_row(tr_panel, asset, fire_us)
    if row is None or row.ema_800 is None:
        return False
    return (
        (row.close > row.ema_800 and direction == "UP")
        or (row.close < row.ema_800 and direction == "DOWN")
    )


def g_tr_above_cloud(
    direction: str, fire_us: int, *, asset: str, tr_panel: Any, **_kw: Any,
) -> bool:
    """Pass iff close is above/below the Ichimoku cloud per direction.

    UP: close > max(ssa, ssb) (above the cloud)
    DOWN: close < min(ssa, ssb) (below the cloud)
    Mid-cloud (between ssa/ssb) fails both directions.
    """
    row = _tr_row(tr_panel, asset, fire_us)
    if row is None or row.ssa is None or row.ssb is None:
        return False
    cloud_top = max(row.ssa, row.ssb)
    cloud_bot = min(row.ssa, row.ssb)
    return (
        (row.close > cloud_top and direction == "UP")
        or (row.close < cloud_bot and direction == "DOWN")
    )


def g_tr_above_pp(
    direction: str, fire_us: int, *, asset: str, tr_panel: Any, **_kw: Any,
) -> bool:
    """Pass iff close vs classic daily pivot matches direction."""
    row = _tr_row(tr_panel, asset, fire_us)
    if row is None or row.pp_classic_daily is None:
        return False
    return (
        (row.close > row.pp_classic_daily and direction == "UP")
        or (row.close < row.pp_classic_daily and direction == "DOWN")
    )


def g_tr_stack_with(
    direction: str, fire_us: int, *, asset: str, tr_panel: Any, **_kw: Any,
) -> bool:
    """Pass iff stack_score >= 1 for UP or <= -1 for DOWN (partial or full)."""
    row = _tr_row(tr_panel, asset, fire_us)
    if row is None:
        return False
    s = row.tr_ema_stack_score
    return (s >= 1 and direction == "UP") or (s <= -1 and direction == "DOWN")


def g_tr_stack_full_with(
    direction: str, fire_us: int, *, asset: str, tr_panel: Any, **_kw: Any,
) -> bool:
    """Pass iff stack_score == +2 for UP or == -2 for DOWN (full bull/bear stack)."""
    row = _tr_row(tr_panel, asset, fire_us)
    if row is None:
        return False
    s = row.tr_ema_stack_score
    return (s == 2 and direction == "UP") or (s == -2 and direction == "DOWN")


def g_tr_partial_stack_with(
    direction: str, fire_us: int, *, asset: str, tr_panel: Any, **_kw: Any,
) -> bool:
    """Pass iff stack_score == +1 for UP or == -1 for DOWN (partial only — not full)."""
    row = _tr_row(tr_panel, asset, fire_us)
    if row is None:
        return False
    s = row.tr_ema_stack_score
    return (s == 1 and direction == "UP") or (s == -1 and direction == "DOWN")


def g_tr_within_adr(
    direction: str, fire_us: int, *, asset: str, tr_panel: Any, **_kw: Any,
) -> bool:
    """Pass iff |close/daily_open - 1| < adr_20_pct (direction-independent volatility gate)."""
    row = _tr_row(tr_panel, asset, fire_us)
    if (
        row is None
        or row.adr_20_pct is None
        or row.daily_open is None
        or row.daily_open == 0
    ):
        return False
    return abs(row.close / row.daily_open - 1) < row.adr_20_pct


def g_tr_in_active_session(
    direction: str, fire_us: int, *, asset: str, tr_panel: Any, **_kw: Any,
) -> bool:
    """Pass iff at least one trading session (London/NY/Tokyo) is currently active."""
    row = _tr_row(tr_panel, asset, fire_us)
    if row is None:
        return False
    return row.tr_active_session_count >= 1


# =====================================================================
# §3.6 — Ribbon gates
# =====================================================================


def g_ribbon_agrees(
    direction: str, fire_us: int, *, asset: str, tr_panel: Any, **_kw: Any,
) -> bool:
    """Pass iff ribbon_color is 'green' for UP or 'red' for DOWN. Neutral fails both."""
    row = _tr_row(tr_panel, asset, fire_us)
    if row is None or row.ribbon_color is None:
        return False
    c = row.ribbon_color
    return (
        (c == "green" and direction == "UP")
        or (c == "red" and direction == "DOWN")
    )


def g_ribbon_slope_with(
    direction: str, fire_us: int, *, asset: str, tr_panel: Any, **_kw: Any,
) -> bool:
    """Pass iff sign(ribbon_lead_slope_bps) matches direction (non-zero required)."""
    row = _tr_row(tr_panel, asset, fire_us)
    if row is None or row.ribbon_lead_slope_bps is None:
        return False
    s = row.ribbon_lead_slope_bps
    if s == 0:
        return False
    return (s > 0 and direction == "UP") or (s < 0 and direction == "DOWN")


# =====================================================================
# §3.7 — CCI: INTENTIONALLY OMITTED (CONTEXT.md Deferred §4)
# =====================================================================


# =====================================================================
# §3.8 — SMS / liquidity gates (SmsPanel.lookup(asset, tf, ts_us))
# =====================================================================


def g_sms_liq_reclaim_with(
    direction: str,
    fire_us: int,
    *,
    asset: str,
    tf: str,
    sms_panel: Any,
    **_kw: Any,
) -> bool:
    """Pass iff liq_reclaim_dir == +1 for UP or -1 for DOWN."""
    row = sms_panel.lookup(asset, tf, fire_us)
    if row is None:
        return False
    d = row.liq_reclaim_dir
    return (d == 1 and direction == "UP") or (d == -1 and direction == "DOWN")


def g_sms_no_liquidity_above(
    direction: str,
    fire_us: int,
    *,
    asset: str,
    tf: str,
    sms_panel: Any,
    **_kw: Any,
) -> bool:
    """Pass iff price is NOT sitting at the trailing-20-bar extreme in the
    trade direction (clear space ahead).

    TV_FIX_SMS_NO_LIQ_20BAR_2026_06_03 — was ``sms_liquidity_count_above == 0``
    (unswept fractal swings over 100 bars), which is almost never 0 → ~1% pass
    (vs the backtest's ~74%). The backtest "no liquidity above/below" is the
    binary inverse of the 20-bar-extreme flag (sms_gate_overlay.py): UP fires
    when the bar's HIGH is NOT within 0.05% of the trailing 20-bar high; DOWN
    when the LOW is NOT within 0.05% of the trailing 20-bar low.
    """
    row = sms_panel.lookup(asset, tf, fire_us)
    if row is None:
        return False
    if direction == "UP":
        return not getattr(row, "liq_near_high_20", False)
    return not getattr(row, "liq_near_low_20", False)


# =====================================================================
# §3.9 — Volatility (VolHurstPanel.lookup(asset, tf, ts_us))
# =====================================================================


def g_vol_high(
    direction: str,
    fire_us: int,
    *,
    asset: str,
    tf: str,
    vol_hurst_panel: Any,
    **_kw: Any,
) -> bool:
    """Pass iff realized vol is top-quartile of the trailing 24h
    (rv_pct_24h > VOL_HIGH_PCT_THR). Direction-independent.

    TV_FIX_VOL_HIGH_PERCENTILE_2026_06_03 — restores the backtest gate
    ``rv_pct_24h > 0.75`` (master_combinatorial_2026_05_26/03_compute_gates.py
    :143-147). The prior absolute-threshold form (``raw_rv > VOL_HIGH_RV60_THR``)
    was a mis-translation: the de-annualized rv_60 (~0.002-0.005) sits ~4-10x
    below the thresholds (~0.02), so the gate fired ~never → 10 trstack sleeves
    silent for days. The percentile is unit-free → immune to the rv_60
    annualization scale. ``rv_pct_24h`` is None during warmup / <3h of samples
    → fail-closed (no fire).
    """
    if vol_hurst_panel is None:
        return False
    row = vol_hurst_panel.lookup(asset, tf, fire_us)
    if row is None or getattr(row, "rv_pct_24h", None) is None:
        return False
    return row.rv_pct_24h > VOL_HIGH_PCT_THR


# =====================================================================
# §3.10 — Daily VWAP (DailyVwapPanel.lookup(asset, ts_us))
# =====================================================================


def above_1h_dailyvwap(
    asset: str,
    fire_us: int,
    *,
    daily_vwap_panel: Any,
    **_kw: Any,
) -> bool | None:
    """Helper: True if close > vwap, False if below, None if no row / no vwap.

    Direction-agnostic helper consumed by `g_above_1h_dailyvwap_with`. Spec §3.10
    exports this as a primitive distinct from the gate-form so downstream callers
    (e.g., shadow log enrichment) can record the tri-state.
    """
    row = daily_vwap_panel.lookup(asset, fire_us)
    if row is None or row.vwap is None or row.close is None:
        return None
    return row.close > row.vwap


def g_above_1h_dailyvwap_with(
    direction: str,
    fire_us: int,
    *,
    asset: str,
    daily_vwap_panel: Any,
    **_kw: Any,
) -> bool:
    """Pass iff above_1h_dailyvwap == True for UP, == False for DOWN.

    Returns False on None (graceful skip per the gate contract).
    """
    above = above_1h_dailyvwap(asset, fire_us, daily_vwap_panel=daily_vwap_panel)
    if above is None:
        return False
    return (above and direction == "UP") or ((not above) and direction == "DOWN")


# =====================================================================
# §3.11 — Pivot proximity (TradersRealityPanel)
# =====================================================================


def g_near_pivot(
    direction: str, fire_us: int, *, asset: str, tr_panel: Any, **_kw: Any,
) -> bool:
    """Pass iff |close - pp_classic_daily| / close < 0.5% (direction-independent)."""
    row = _tr_row(tr_panel, asset, fire_us)
    if (
        row is None
        or row.pp_classic_daily is None
        or row.close == 0
    ):
        return False
    return abs(row.close - row.pp_classic_daily) / row.close < NEAR_PIVOT_PCT_THR


# =====================================================================
# §3.12 — Offset / time-of-day / direction gates
# =====================================================================


def g_offset_early(
    direction: str, fire_us: int, *, slot_start_us: int, **_kw: Any,
) -> bool:
    """Pass iff 0 <= (fire_us - slot_start_us) / 1e6 <= 60.

    Filter for offsets in the first 60 seconds of a slot. Pre-slot fires
    (offset < 0) explicitly fail (defensive against scheduling races).
    """
    offset_s = (fire_us - slot_start_us) / 1_000_000
    return 0 <= offset_s <= OFFSET_EARLY_MAX_S


def g_hod_us_afternoon(direction: str, fire_us: int, **_kw: Any) -> bool:
    """Pass iff hour-of-day-UTC in [18, 19, 20, 21, 22] (US afternoon)."""
    hour_utc = (fire_us // 1_000_000 // 3600) % 24
    return hour_utc in HOD_US_AFTERNOON_UTC


def g_dir_up(direction: str, *_args: Any, **_kw: Any) -> bool:
    """Pass iff direction == 'UP'. Accepts arbitrary extra args for uniform callsig."""
    return direction == "UP"


def g_dir_down(direction: str, *_args: Any, **_kw: Any) -> bool:
    """Pass iff direction == 'DOWN'. Accepts arbitrary extra args for uniform callsig."""
    return direction == "DOWN"


def g_oracle_lag_bps_ge(
    direction: str,
    fire_us: int,
    *,
    oracle_lag: Any = None,
    threshold_bps: str = "3.0",
    **_kw: Any,
) -> bool:
    """fast_taker fire signal: binance-vs-chainlink staleness exceeds threshold,
    AND the proposed ``direction`` matches the LEADING side.

    ``oracle_lag`` is the ``OracleLagSnapshot`` (``price_delta_bps`` =
    (feed - oracle)/oracle * 10_000) supplied by the controller at fire time
    (see ``_build_gate_kwargs``); ``None`` when the feed/oracle isn't readable
    → graceful skip (no fire), matching every other gate's missing-data
    contract.

    Sign convention: ``price_delta_bps > 0`` means binance (feed) is ABOVE the
    chainlink oracle → the up-leg is the stale-cheap leading side → fire UP.
    ``< 0`` → fire DOWN. So for a BOTH sleeve only the leading side passes; the
    other side fails on the sign check and never fires.

    ``threshold_bps`` arrives as a string from the GateRef static kwargs
    (3.0 = the OOS sweet spot per LATENCY_EDGE_FINDING).
    """
    if oracle_lag is None:
        return False
    try:
        thr = float(threshold_bps)
    except (TypeError, ValueError):
        thr = 3.0
    bps = float(oracle_lag.price_delta_bps)
    if abs(bps) < thr:
        return False
    return (direction == "UP") if bps > 0 else (direction == "DOWN")


# =====================================================================
# FAST_TAKER_LAGV2 gates (2026-05-29) — directional oracle-lag taker.
# Pure + direction-aware; runtime kwargs routed in the controller's
# _build_gate_kwargs. See docs spec TV_AGENT_SPEC_FAST_TAKER_LAGV2.
# =====================================================================

# Hours-of-day (UTC) where the lag edge degrades — rejected by
# g_not_us_close_hours (LAG_TAKER_GATES: OOS t=3.29 standalone).
_LAGV2_EXCLUDE_HOURS_UTC = frozenset({18, 19, 20, 21, 22, 23})


def _top_ask_depth_usd(book: dict | None) -> float:
    """Resting $ at the BEST ask level (price*size of asks[0]). 0.0 if missing.

    Top-of-book (NOT cumulative) — matches the LAG_TAKER_GATES "best-ask $"
    median semantics, distinct from _cum_depth_usd's L25 sum.
    """
    if not book:
        return 0.0
    asks = book.get("asks") or []
    if not asks:
        return 0.0
    try:
        return float(asks[0]["price"]) * float(asks[0]["size"])
    except (KeyError, TypeError, ValueError, IndexError):
        return 0.0


def g_oracle_lag_with(
    direction: str,
    fire_us: int,
    *,
    oracle_lag: Any = None,
    lo_bps: str = "3.0",
    hi_bps: str = "12.0",
    **_kw: Any,
) -> bool:
    """LAGV2 fire signal + direction selector.

    Pass iff |price_delta_bps| is in [lo,hi] AND its sign matches ``direction``
    (>0 ⇒ feed above oracle ⇒ leading side UP; <0 ⇒ DOWN). For a BOTH sleeve
    only the leading side passes. The ``hi`` cap is LOAD-BEARING: moves > hi are
    already priced and REVERSE (−EV, WR 56%). Stale snapshots fail (no fire).
    ``lo_bps``/``hi_bps`` arrive as strings from the GateRef static kwargs.
    """
    if oracle_lag is None:
        return False
    if getattr(oracle_lag, "stale", False):
        return False
    try:
        lo = float(lo_bps)
        hi = float(hi_bps)
    except (TypeError, ValueError):
        lo, hi = 3.0, 12.0
    bps = float(oracle_lag.price_delta_bps)
    if not (lo <= abs(bps) <= hi):
        return False
    leading = "UP" if bps > 0 else "DOWN"
    return direction == leading


def g_not_us_close_hours(direction: str, fire_us: int, **_kw: Any) -> bool:
    """Reject fires in 18-23 UTC (the lag edge degrades there)."""
    hour_utc = (fire_us // 1_000_000 // 3600) % 24
    return hour_utc not in _LAGV2_EXCLUDE_HOURS_UTC


def g_cross_asset_lag_confluence(
    direction: str,
    fire_us: int,
    *,
    oracle_lag_other: Any = None,
    conf_bps: str = "3.0",
    **_kw: Any,
) -> bool:
    """Pass iff the OTHER asset (BTC↔ETH) is leading the SAME ``direction`` by
    >= conf_bps. Sharpens WR + cuts maxDD. ``oracle_lag_other`` is the paired
    asset's OracleLagSnapshot, injected by the controller (SOL not used).
    """
    if oracle_lag_other is None:
        return False
    if getattr(oracle_lag_other, "stale", False):
        return False
    try:
        conf = float(conf_bps)
    except (TypeError, ValueError):
        conf = 3.0
    bps = float(oracle_lag_other.price_delta_bps)
    other_leading = "UP" if bps > 0 else "DOWN"
    return abs(bps) >= conf and other_leading == direction


def g_lag_momentum_align(
    direction: str,
    fire_us: int,
    *,
    oracle_lag: Any = None,
    vwap_store: Any = None,
    asset: str = "",
    mom_win_s: str = "30",
    **_kw: Any,
) -> bool:
    """TV_AGENT_SPEC_SCALP_MOMALIGN_BTC5M_2026_06_09 — momentum-alignment refinement
    of the lag scalp (``shadow_scalp_momalign_btc_5m_v1``).

    Pass iff the oracle-lag direction AGREES with the trailing ``mom_win_s``-second
    binance return AND it is the leading side. The momalign gate is what adds the
    edge (OOS +4.24/tr vs +2.77 without).

    ``oracle_lag`` = the SAME OracleLagSnapshot the lag scalp reads (intra-window
    binance return, ``price_delta_bps``). ``vwap_store`` = the engine's 1s binance
    store (injected by the controller, mirroring g_disagr_hawkes) so the gate stays
    pure — ``vwap_store.close_at`` is exactly what the controller's
    ``_binance_close_at`` calls. ``asset`` / ``mom_win_s`` arrive as GateRef static
    kwargs (strings). Fail-CLOSED on any missing input (no snapshot / stale / no 1s
    bar / zero sign).
    """
    if oracle_lag is None or getattr(oracle_lag, "stale", False):
        return False
    if vwap_store is None:
        return False
    try:
        lag = float(oracle_lag.price_delta_bps)
        win_s = int(mom_win_s)
    except (TypeError, ValueError):
        return False
    px_now = vwap_store.close_at(asset, fire_us)
    px_then = vwap_store.close_at(asset, fire_us - win_s * 1_000_000)
    if not px_now or not px_then or px_then <= 0:
        return False  # fail-closed on missing 1s data
    mom = px_now / px_then - 1.0
    if lag == 0 or mom == 0:
        return False
    if (lag > 0) != (mom > 0):  # signs must AGREE
        return False
    return direction == ("UP" if lag > 0 else "DOWN")  # leading side only


def g_oracle_decided(
    direction: str,
    fire_us: int,
    *,
    book_mirror: Any = None,
    token_id_up: str = "",
    token_id_dn: str = "",
    chainlink_price: Any = None,
    strike_price: Any = None,
    dist_bp_min: Any = "15.0",
    max_ask: Any = "0.95",
    **_kw: Any,
) -> bool:
    """TV_AGENT_SPEC_SHADOW_ORACLE_SETTLE_2026_06_05 — STRUCTURAL settlement edge
    (NOT prediction). Fire iff the Chainlink oracle has effectively DECIDED the
    window outcome AND the oracle-implied winner token is still cheap (the poly
    price lags the oracle). The direction is SET BY THE ORACLE — this gate only
    passes for the winner side, so the BOTH-direction sleeve fires the winner.

      strike      = Chainlink price at slot_start (``get_boundary_snapshot`` — the
                    value the market settles against), injected per fire.
      chainlink   = current live RTDS chainlink value at fire (``get_chainlink_price``).
      winner side = 'UP' if chainlink > strike else 'DOWN'  (MUST equal direction)
      decided     = |chainlink - strike| / strike * 1e4 >= dist_bp_min  (default 15bp)
      cheap       = best ask of the winner token < max_ask  (default 0.95)

    Fail-closed: any missing input (warm-up / no strike / empty book / bad parse)
    → no fire. ``dist_bp_min`` / ``max_ask`` arrive as strings from the GateRef
    binding and are parsed here.
    """
    if chainlink_price is None or strike_price is None:
        return False  # warm-up / no strike → no fire
    try:
        cl = float(chainlink_price)
        strike = float(strike_price)
        lo_bp = float(dist_bp_min)
        cap = float(max_ask)
    except (TypeError, ValueError):
        return False
    if strike <= 0:
        return False
    dist_bp = abs(cl - strike) / strike * 1e4
    if dist_bp < lo_bp:
        return False
    winner = "UP" if cl > strike else "DOWN"
    if direction != winner:
        return False  # sleeve fires the winner side only
    tok = token_id_up if winner == "UP" else token_id_dn
    book = (book_mirror or {}).get(tok)
    if not book or not book.get("asks"):
        return False
    try:
        best_ask = float(book["asks"][0]["price"])
    except (KeyError, IndexError, TypeError, ValueError):
        return False
    return best_ask < cap


def g_top_depth_ge_median(
    direction: str,
    fire_us: int,
    *,
    book_mirror: Any = None,
    token_id_up: str = "",
    token_id_dn: str = "",
    asset: str = "",
    tf: str = "",
    depth_median_usd: Any = None,
    **_kw: Any,
) -> bool:
    """Pass iff resting $ at the BUY-SIDE best-ask level >= the per-(asset,tf)
    median (DEPTH_MEDIAN_USD, injected by the controller). The buy side is the
    leading side's token (UP→up token, DOWN→dn token). Most OOS-robust single
    LAGV2 gate (+$0.67/tr, OOS t=2.80).
    """
    if book_mirror is None or depth_median_usd is None:
        return False
    token = token_id_up if direction == "UP" else token_id_dn
    top_usd = _top_ask_depth_usd(book_mirror.get(token))
    median = float(depth_median_usd.get((asset, tf), 0.0))
    return top_usd >= median


# =====================================================================
# §3.13 — Tight ribbon
# =====================================================================


def g_tight_ribbon(
    direction: str, fire_us: int, *, asset: str, tr_panel: Any, **_kw: Any,
) -> bool:
    """Pass iff ribbon_compression_bps < 8 (direction-independent compression filter)."""
    row = _tr_row(tr_panel, asset, fire_us)
    if row is None or row.ribbon_compression_bps is None:
        return False
    return row.ribbon_compression_bps < RIBBON_TIGHT_BPS_THR


# =====================================================================
# V6 / V7 / V8 GATE LIBRARY (2026-05-27 extension)
# =====================================================================
#
# All gates below follow the existing Phase 35 contract: pure functions,
# (direction, fire_us, *, kwargs) signature, return False on missing data,
# panel handles are keyword-only. Sections grouped by data source.
#
# Spec sources:
#   * V6: SHADOW_DEPLOY_SPEC_V6_SELECTED_2026_05_27.md §3
#   * V7: SHADOW_DEPLOY_SPEC_V7_SELECTED_2026_05_27.md §3
#   * V8: SHADOW_DEPLOY_SPEC_UNIFIED_V6_V7_V8_2026_05_27.md §3
# =====================================================================


# =====================================================================
# §3.14 — TA indicator gates (TAIndicatorsPanel — CCI / MFI / BB / Stoch)
# =====================================================================


def _ta_row(ta_indicators: Any, asset: str, fire_us: int):
    if ta_indicators is None:
        return None
    return ta_indicators.lookup(asset, fire_us)


def g_cci_strong_with(
    direction: str, fire_us: int, *, asset: str, ta_indicators: Any, **_kw: Any,
) -> bool:
    """V6 §3.6 — |CCI_60s| > 100 and sign matches direction."""
    row = _ta_row(ta_indicators, asset, fire_us)
    if row is None or row.cci_60s is None:
        return False
    cci = row.cci_60s
    if abs(cci) <= CCI_STRONG_THR:
        return False
    return (cci > 0 and direction == "UP") or (cci < 0 and direction == "DOWN")


def g_cci_extreme_with(
    direction: str, fire_us: int, *, asset: str, ta_indicators: Any, **_kw: Any,
) -> bool:
    """V7 §3.8 — strict variant: |CCI_60s| > 150 and sign matches direction."""
    row = _ta_row(ta_indicators, asset, fire_us)
    if row is None or row.cci_60s is None:
        return False
    cci = row.cci_60s
    if abs(cci) <= CCI_EXTREME_THR:
        return False
    return (cci > 0 and direction == "UP") or (cci < 0 and direction == "DOWN")


def g_cci_with(
    direction: str, fire_us: int, *, asset: str, ta_indicators: Any, **_kw: Any,
) -> bool:
    """V8 §3.9 — loose variant: CCI_60s sign matches direction (no magnitude gate)."""
    row = _ta_row(ta_indicators, asset, fire_us)
    if row is None or row.cci_60s is None:
        return False
    cci = row.cci_60s
    if cci == 0:
        return False
    return (cci > 0 and direction == "UP") or (cci < 0 and direction == "DOWN")


def g_mfi_with(
    direction: str, fire_us: int, *, asset: str, ta_indicators: Any, **_kw: Any,
) -> bool:
    """V6 §3.6 — MFI_60s vs 50 midpoint."""
    row = _ta_row(ta_indicators, asset, fire_us)
    if row is None or row.mfi_60s is None:
        return False
    if direction == "UP":
        return row.mfi_60s > 50.0
    return row.mfi_60s < 50.0


def g_mfi_strong_with(
    direction: str, fire_us: int, *, asset: str, ta_indicators: Any, **_kw: Any,
) -> bool:
    """V8 §3.9 — stricter MFI: > 60 for UP, < 40 for DOWN."""
    row = _ta_row(ta_indicators, asset, fire_us)
    if row is None or row.mfi_60s is None:
        return False
    if direction == "UP":
        return row.mfi_60s > MFI_STRONG_UP_THR
    return row.mfi_60s < MFI_STRONG_DN_THR


def g_bb_pos_with(
    direction: str, fire_us: int, *, asset: str, ta_indicators: Any, **_kw: Any,
) -> bool:
    """V6 §3.6 — BB-position 60s: > 0.55 for UP, < 0.45 for DOWN."""
    row = _ta_row(ta_indicators, asset, fire_us)
    if row is None or row.bb_pos_60s is None:
        return False
    if direction == "UP":
        return row.bb_pos_60s > BB_POS_UP_THR
    return row.bb_pos_60s < BB_POS_DN_THR


def g_stoch_with(
    direction: str, fire_us: int, *, asset: str, ta_indicators: Any, **_kw: Any,
) -> bool:
    """V8 §3.9 (V5 R1 base) — Stochastic %K-60s vs 50 midpoint."""
    row = _ta_row(ta_indicators, asset, fire_us)
    if row is None or row.stoch_k_60s is None:
        return False
    if direction == "UP":
        return row.stoch_k_60s > 50.0
    return row.stoch_k_60s < 50.0


# =====================================================================
# §3.15 — Hawkes (HawkesPanel.lambda_imbalance)
# =====================================================================


def g_hawkes_imb_loose_with(
    direction: str, fire_us: int, *, asset: str, hawkes_panel: Any, **_kw: Any,
) -> bool:
    """V6 §3.9 — |λ_imbalance| > 0.10 and sign matches direction."""
    if hawkes_panel is None:
        return False
    row = hawkes_panel.lookup(asset, fire_us)
    if row is None:
        return False
    imb = row.lambda_imbalance
    if abs(imb) <= HAWKES_LOOSE_THR:
        return False
    return (imb > 0 and direction == "UP") or (imb < 0 and direction == "DOWN")


# =====================================================================
# §3.16 — Hurst variants (VolHurstPanel.hurst_60)
# =====================================================================


def g_hurst_trending(
    direction: str, fire_us: int, *, asset: str, tf: str, vol_hurst_panel: Any, **_kw: Any,
) -> bool:
    """V6 §3.8 — hurst_60 > 0.50 (direction-independent trending regime)."""
    if vol_hurst_panel is None:
        return False
    row = vol_hurst_panel.lookup(asset, tf, fire_us)
    if row is None or row.hurst_60 is None:
        return False
    return row.hurst_60 > HURST_TRENDING_THR


def g_hurst_reverting(
    direction: str, fire_us: int, *, asset: str, tf: str, vol_hurst_panel: Any, **_kw: Any,
) -> bool:
    """V7 §3.2 — mean-reverting regime (direction-agnostic): hurst_300s < 0.40.

    TV_FIX_HURST_ANISLLOYD_2026_06_03 — reads the backtest-faithful
    ``hurst_300s`` (Anis-Lloyd bias-corrected chunked R/S over 300 1s
    log-prices; white-noise mean ~0.44) instead of the 1m single-block
    ``hurst_60`` (white-noise mean ~0.52 → ``hurst_60 < 0.40`` ≈ never; the
    gate was 0% true over 20k+ evals → both SOL hurst-rev sleeves silent).
    ``hurst_300s`` is per-asset / tf-independent (always a 5-minute window).
    The TRENDING hurst gates still read ``hurst_60`` — their high single-block
    bias is what makes them fire — so they stay on the old estimator.
    """
    if vol_hurst_panel is None or not hasattr(vol_hurst_panel, "hurst_300s"):
        return False
    h = vol_hurst_panel.hurst_300s(asset)
    if h is None:
        return False
    return h < HURST_REVERTING_THR


def g_hurst_regime_with(
    direction: str, fire_us: int, *, asset: str, tf: str,
    vol_hurst_panel: Any, regime_panel: Any, **_kw: Any,
) -> bool:
    """V7 §3.2 — hurst > 0.55 AND price-trend sign matches direction."""
    if vol_hurst_panel is None or regime_panel is None:
        return False
    h_row = vol_hurst_panel.lookup(asset, tf, fire_us)
    r_row = regime_panel.lookup(asset, tf, fire_us)
    if h_row is None or h_row.hurst_60 is None:
        return False
    if r_row is None or r_row.trend_slope_30m is None:
        return False
    if h_row.hurst_60 < HURST_REGIME_THR:
        return False
    slope = r_row.trend_slope_30m
    return (slope > 0 and direction == "UP") or (slope < 0 and direction == "DOWN")


def g_hurst_mp_trend_with(
    direction: str, fire_us: int, *, asset: str, slug: str,
    vol_hurst_panel: Any, microprice_panel: Any, **_kw: Any,
) -> bool:
    """V7 §3.2 — hurst > 0.50 AND microprice skew sign matches direction."""
    if vol_hurst_panel is None or microprice_panel is None:
        return False
    h_row = vol_hurst_panel.lookup(asset, "5m", fire_us)
    if h_row is None or h_row.hurst_60 is None:
        return False
    if h_row.hurst_60 < HURST_TRENDING_THR:
        return False
    mp_s = microprice_panel.mp_skew(slug, fire_us)
    if mp_s is None or mp_s == 0:
        return False
    return (mp_s > 0 and direction == "UP") or (mp_s < 0 and direction == "DOWN")


# V8 §3.9 alias — same as g_hurst_regime_with semantics
g_hurst_trend_with = g_hurst_regime_with


# =====================================================================
# §3.17 — F7 v7 RSI (F7V7Panel)
# =====================================================================


def g_f7_v7_overbought(
    direction: str, fire_us: int, *, asset: str, f7_v7_panel: Any, **_kw: Any,
) -> bool:
    """V7 §3.9 — F7 RSI >= 70 (direction-agnostic; combine with directional gate)."""
    if f7_v7_panel is None:
        return False
    row = f7_v7_panel.lookup(asset, fire_us)
    if row is None or row.rsi_60_p7 is None:
        return False
    return row.rsi_60_p7 >= F7_OVERBOUGHT_THR


def g_f7_v7_oversold(
    direction: str, fire_us: int, *, asset: str, f7_v7_panel: Any, **_kw: Any,
) -> bool:
    """V7 §3.9 — F7 RSI <= 30."""
    if f7_v7_panel is None:
        return False
    row = f7_v7_panel.lookup(asset, fire_us)
    if row is None or row.rsi_60_p7 is None:
        return False
    return row.rsi_60_p7 <= F7_OVERSOLD_THR


def g_f7_v7_with(
    direction: str, fire_us: int, *, asset: str, f7_v7_panel: Any, **_kw: Any,
) -> bool:
    """V7 §3.9 — F7 RSI extreme MATCHES direction (≥70 + UP, or ≤30 + DOWN)."""
    if f7_v7_panel is None:
        return False
    row = f7_v7_panel.lookup(asset, fire_us)
    if row is None or row.rsi_60_p7 is None:
        return False
    rsi = row.rsi_60_p7
    if direction == "UP":
        return rsi >= F7_OVERBOUGHT_THR
    return rsi <= F7_OVERSOLD_THR


def g_btc_f7_with(
    direction: str, fire_us: int, *, f7_v7_panel: Any, **_kw: Any,
) -> bool:
    """V7 §3.4 — BTC F7 extreme matches fire direction (cross-asset trend confirm)."""
    if f7_v7_panel is None:
        return False
    row = f7_v7_panel.lookup("BTC", fire_us)
    if row is None or row.rsi_60_p7 is None:
        return False
    rsi = row.rsi_60_p7
    if direction == "UP":
        return rsi >= F7_OVERBOUGHT_THR
    return rsi <= F7_OVERSOLD_THR


def g_btc_f7_against(
    direction: str, fire_us: int, *, f7_v7_panel: Any, **_kw: Any,
) -> bool:
    """V7 §3.4 — BTC F7 extreme AGAINST fire direction (mean-revert play)."""
    if f7_v7_panel is None:
        return False
    row = f7_v7_panel.lookup("BTC", fire_us)
    if row is None or row.rsi_60_p7 is None:
        return False
    rsi = row.rsi_60_p7
    if direction == "UP":
        return rsi <= F7_OVERSOLD_THR    # BTC oversold → bet UP (reversion)
    return rsi >= F7_OVERBOUGHT_THR      # BTC overbought → bet DOWN


# V6 §3.10 — direction-agnostic extreme (used by V6 sleeves)
def g_f7_rsi_with(
    direction: str, fire_us: int, *, asset: str, f7_v7_panel: Any, **_kw: Any,
) -> bool:
    """V6 §3.10 — F7 RSI in extreme zone (>=70 OR <=30), direction-agnostic.

    V6 spec says: "the gate fires when RSI is in extreme zone regardless of
    direction combined with other directional gates."
    """
    if f7_v7_panel is None:
        return False
    row = f7_v7_panel.lookup(asset, fire_us)
    if row is None or row.rsi_60_p7 is None:
        return False
    rsi = row.rsi_60_p7
    return rsi >= F7_OVERBOUGHT_THR or rsi <= F7_OVERSOLD_THR


# =====================================================================
# §3.18 — TOD bucket gates (UTC hour only — no panel needed)
# =====================================================================


def _utc_hour(fire_us: int) -> int:
    return (fire_us // 1_000_000 // 3600) % 24


def g_tod_asia_morning(
    direction: str, fire_us: int, **_kw: Any,
) -> bool:
    """V8 §3.4 — UTC hour 0..6."""
    h = _utc_hour(fire_us)
    return TOD_ASIA_MORNING_UTC[0] <= h <= TOD_ASIA_MORNING_UTC[1]


def g_tod_european_morning(
    direction: str, fire_us: int, **_kw: Any,
) -> bool:
    """V8 §3.4 — UTC hour 7..12 (wider than V5 g_hod_european_morning which is 7..11)."""
    h = _utc_hour(fire_us)
    return TOD_EUROPEAN_MORNING_UTC[0] <= h <= TOD_EUROPEAN_MORNING_UTC[1]


def g_tod_us_open(
    direction: str, fire_us: int, **_kw: Any,
) -> bool:
    """V8 §3.4 — UTC hour 13..14."""
    h = _utc_hour(fire_us)
    return TOD_US_OPEN_UTC[0] <= h <= TOD_US_OPEN_UTC[1]


def g_tod_us_afternoon(
    direction: str, fire_us: int, **_kw: Any,
) -> bool:
    """V8 §3.4 — UTC hour 13..18 (wider than V5 g_hod_us_afternoon which is 18..22)."""
    h = _utc_hour(fire_us)
    return TOD_US_AFTERNOON_UTC[0] <= h <= TOD_US_AFTERNOON_UTC[1]


def g_tod_us_evening(
    direction: str, fire_us: int, **_kw: Any,
) -> bool:
    """V8 §3.4 — UTC hour 19..23."""
    h = _utc_hour(fire_us)
    return TOD_US_EVENING_UTC[0] <= h <= TOD_US_EVENING_UTC[1]


def g_tod_europe_us_window(
    direction: str, fire_us: int, **_kw: Any,
) -> bool:
    """V8 §3.4 — combined EU+US active hours 7..18 UTC."""
    h = _utc_hour(fire_us)
    return TOD_EUROPE_US_WINDOW_UTC[0] <= h <= TOD_EUROPE_US_WINDOW_UTC[1]


def g_hod_european_morning(
    direction: str, fire_us: int, **_kw: Any,
) -> bool:
    """V6 §3.12 — UTC hour 7..11 (the V6 spec form; narrower than V8 g_tod_european_morning)."""
    h = _utc_hour(fire_us)
    return 7 <= h <= 11


def g_hour_not_in(
    direction: str, fire_us: int, *, excluded_hours: Any = "", **_kw: Any,
) -> bool:
    """TV_AGENT_SPEC_SCALP_TOD_GATE_2026_06_05 — block the fire when the UTC hour
    of ``fire_us`` is in ``excluded_hours`` (the scalp edge is ~2× in 22–02 UTC
    and dead at h12/17; excluding the dead hours lifts $/tr with ~no volume loss).

    ``excluded_hours`` is a comma-separated string ("12,17") baked into the
    GateRef binding — the controller passes static GateRef kwargs as strings — so
    we parse it here; a set/iterable is also accepted defensively. Empty → no-op
    (always passes). Hour anchor = UTC hour of fire_us, matching the backtest's
    ``(fire_us//1e6 % 86400)//3600``.
    """
    if isinstance(excluded_hours, str):
        excluded = {int(x) for x in excluded_hours.split(",") if x.strip()}
    else:
        excluded = {int(x) for x in excluded_hours}
    return _utc_hour(fire_us) not in excluded


# =====================================================================
# §3.19 — Offset / pre-window gates
# =====================================================================


def g_off_60_240(
    direction: str, fire_us: int, *, slot_start_us: int, **_kw: Any,
) -> bool:
    """V6 §3.12 — offset_s ∈ [60, 240]."""
    elapsed_s = (fire_us - int(slot_start_us)) / 1_000_000.0
    return OFFSET_60_240_LO_S <= elapsed_s <= OFFSET_60_240_HI_S


def g_pw_trend_slope_with(
    direction: str, fire_us: int, *, asset: str, tf: str,
    slot_start_us: int, window_s: int, regime_panel: Any, **_kw: Any,
) -> bool:
    """V6 §3.2 — PRE-WINDOW: anchor at ws_s (= slot_start_us - window_s) not fire_us."""
    ws_s_us = int(slot_start_us) - int(window_s) * 1_000_000
    return g_trend_slope_with(
        direction, ws_s_us, asset=asset, tf=tf, regime_panel=regime_panel,
    )


# =====================================================================
# §3.20 — Entry-VWAP band filters (book-walk vwap at fire_us)
# =====================================================================


def _book_walk_vwap(
    book: dict | None, stake_usd: float = 25.0,
) -> float | None:
    """Walk the asks side of an L25 book and compute the vwap a ``stake_usd``
    fill would receive. Returns None on insufficient depth or malformed book.

    ``book`` is the per-token Polymarket L25 snapshot from BookMirror, shape
    ``{"asks": [{"price": "0.42", "size": "100.0"}, ...], "bids": ...}``.
    """
    if not book:
        return None
    asks = book.get("asks") or []
    remaining = float(stake_usd)
    total_shares = 0.0
    total_cost = 0.0
    for lvl in asks:
        try:
            price = float(lvl["price"])
            size = float(lvl["size"])
        except (KeyError, TypeError, ValueError):
            continue
        if price <= 0 or size <= 0:
            continue
        level_cost = price * size
        if level_cost >= remaining:
            shares_at_level = remaining / price
            total_shares += shares_at_level
            total_cost += remaining
            remaining = 0.0
            break
        total_shares += size
        total_cost += level_cost
        remaining -= level_cost
    if remaining > 0:
        # Insufficient depth — cannot fill the stake.
        return None
    if total_shares <= 0:
        return None
    return total_cost / total_shares


def _entry_vwap_for_dir(
    direction: str, slug: str, fire_us: int, stake_usd: float,
    book_mirror: Any, token_id_up: str, token_id_dn: str,
) -> float | None:
    if book_mirror is None:
        return None
    token = token_id_up if direction == "UP" else token_id_dn
    book = book_mirror.get(token)
    return _book_walk_vwap(book, stake_usd=stake_usd)


def g_entry_vwap_in_band(
    direction: str, fire_us: int, *, slug: str, book_mirror: Any,
    token_id_up: str, token_id_dn: str, **_kw: Any,
) -> bool:
    """V6 §3.13 — book-walk vwap ∈ [0.20, 0.80]."""
    v = _entry_vwap_for_dir(
        direction, slug, fire_us, 25.0, book_mirror, token_id_up, token_id_dn,
    )
    if v is None:
        return False
    return VWAP_BAND_LOW_THR <= v <= VWAP_BAND_HIGH_THR


def g_entry_vwap_not_coinflip(
    direction: str, fire_us: int, *, slug: str, book_mirror: Any,
    token_id_up: str, token_id_dn: str, **_kw: Any,
) -> bool:
    """Skip the (0.49, 0.51) book-walk-vwap coinflip dead-zone — no edge,
    -0.79/tr in shadow OOS (TV_AGENT_SPEC_CLOUDVWAP_V7_COINFLIP_FILTER_2026_06_09).
    Pass (True) outside the band; fail (False) inside or if vwap is None
    (fail-closed, same as g_entry_vwap_in_band)."""
    v = _entry_vwap_for_dir(
        direction, slug, fire_us, 25.0, book_mirror, token_id_up, token_id_dn,
    )
    if v is None:
        return False
    return not (0.49 < v < 0.51)


def g_entry_vwap_in_band_narrow(
    direction: str, fire_us: int, *, slug: str, book_mirror: Any,
    token_id_up: str, token_id_dn: str, **_kw: Any,
) -> bool:
    """V10 — book-walk vwap ∈ [0.15, 0.55] (cheap-entry narrow band).

    Lab universe `01_build_universe_v6.py:260`:
    ``g_entry_vwap_in_band_narrow = (ev >= 0.15) & (ev <= 0.55)``.
    Tighter, low-priced replacement for ``g_entry_vwap_in_band`` on the ETH
    winners — gates out overpaid entries, lifting per-trade EV.
    """
    v = _entry_vwap_for_dir(
        direction, slug, fire_us, 25.0, book_mirror, token_id_up, token_id_dn,
    )
    if v is None:
        return False
    return VWAP_NARROW_LOW_THR <= v <= VWAP_NARROW_HIGH_THR


def g_entry_vwap_in_30_70(
    direction: str, fire_us: int, *, slug: str, book_mirror: Any,
    token_id_up: str, token_id_dn: str, **_kw: Any,
) -> bool:
    """V6 §3.13 — book-walk vwap ∈ [0.30, 0.70]."""
    v = _entry_vwap_for_dir(
        direction, slug, fire_us, 25.0, book_mirror, token_id_up, token_id_dn,
    )
    if v is None:
        return False
    return VWAP_30_70_LOW_THR <= v <= VWAP_30_70_HIGH_THR


def g_vwap_in_45_85(
    direction: str, fire_us: int, *, slug: str, book_mirror: Any,
    token_id_up: str, token_id_dn: str, **_kw: Any,
) -> bool:
    """V6 §3.13 — book-walk vwap ∈ [0.45, 0.85]."""
    v = _entry_vwap_for_dir(
        direction, slug, fire_us, 25.0, book_mirror, token_id_up, token_id_dn,
    )
    if v is None:
        return False
    return VWAP_45_85_LOW_THR <= v <= VWAP_45_85_HIGH_THR


def g_vwap_in_55_80(
    direction: str, fire_us: int, *, slug: str, book_mirror: Any,
    token_id_up: str, token_id_dn: str, **_kw: Any,
) -> bool:
    """V6 §3.13 — book-walk vwap ∈ [0.55, 0.80]."""
    v = _entry_vwap_for_dir(
        direction, slug, fire_us, 25.0, book_mirror, token_id_up, token_id_dn,
    )
    if v is None:
        return False
    return VWAP_55_80_LOW_THR <= v <= VWAP_55_80_HIGH_THR


def g_vwap_premium(
    direction: str, fire_us: int, *, slug: str, book_mirror: Any,
    token_id_up: str, token_id_dn: str, **_kw: Any,
) -> bool:
    """V6 §3.13 — book-walk vwap >= 0.55."""
    v = _entry_vwap_for_dir(
        direction, slug, fire_us, 25.0, book_mirror, token_id_up, token_id_dn,
    )
    if v is None:
        return False
    return v >= VWAP_PREMIUM_THR


# =====================================================================
# §3.21 — Microprice no-extreme 150 (V6 §3.3 variant)
# =====================================================================


def g_mp_no_extreme_150(
    direction: str, fire_us: int, *, slug: str, microprice_panel: Any, **_kw: Any,
) -> bool:
    """V6 §3.3 — |mp_skew_bps| < 150 (wider than V5 g_mp_no_extreme=100)."""
    s = microprice_panel.mp_skew(slug, fire_us) if microprice_panel else None
    if s is None:
        return False
    return abs(s) < MP_NO_EXTREME_150_BPS_THR


# =====================================================================
# §3.22 — Parent 15m regime gates (V7 §3.1)
# =====================================================================


def g_parent_15m_regime_with(
    direction: str, fire_us: int, *, asset: str, regime_panel: Any, **_kw: Any,
) -> bool:
    """V7 §3.1 — parent 15m regime_label == trending_<direction>."""
    if regime_panel is None:
        return False
    row = regime_panel.lookup(asset, "15m", fire_us)
    if row is None or row.regime_label is None:
        return False
    return (
        (row.regime_label == "trending_up" and direction == "UP")
        or (row.regime_label == "trending_dn" and direction == "DOWN")
    )


def g_parent_15m_slope_with(
    direction: str, fire_us: int, *, asset: str, regime_panel: Any, **_kw: Any,
) -> bool:
    """V7 §3.1 — parent 15m trend_slope_30m sign matches direction."""
    if regime_panel is None:
        return False
    row = regime_panel.lookup(asset, "15m", fire_us)
    if row is None or row.trend_slope_30m is None:
        return False
    slope = row.trend_slope_30m
    return (slope > 0 and direction == "UP") or (slope < 0 and direction == "DOWN")


def g_parent_15m_not_ranging(
    direction: str, fire_us: int, *, asset: str, regime_panel: Any, **_kw: Any,
) -> bool:
    """V7 §3.1 — parent 15m regime_label != 'ranging' (works for both directions)."""
    if regime_panel is None:
        return False
    row = regime_panel.lookup(asset, "15m", fire_us)
    if row is None or row.regime_label is None:
        return False
    return row.regime_label != "ranging"


def g_parent15m_ranging(
    direction: str, fire_us: int, *, asset: str, regime_panel: Any, **_kw: Any,
) -> bool:
    """V7 §3.1 — parent 15m regime_label == 'ranging' (mean-reversion sweet spot)."""
    if regime_panel is None:
        return False
    row = regime_panel.lookup(asset, "15m", fire_us)
    if row is None:
        return False
    return row.regime_label == "ranging"


def g_q_prev15m_agrees(
    direction: str, fire_us: int, *, asset: str, regime_panel: Any, **_kw: Any,
) -> bool:
    """V8 §3.5 (Path Q) — previous closed 15m bar's trend_slope sign matches direction."""
    return g_parent_15m_slope_with(
        direction, fire_us, asset=asset, regime_panel=regime_panel,
    )


def g_regime_ranging_at_ws(
    direction: str, fire_us: int, *, asset: str,
    slot_start_us: int, window_s: int, regime_panel: Any, **_kw: Any,
) -> bool:
    """V7 §3.7 — 5m regime at ws_s == 'ranging'."""
    ws_s_us = int(slot_start_us) - int(window_s) * 1_000_000
    if regime_panel is None:
        return False
    row = regime_panel.lookup(asset, "5m", ws_s_us)
    if row is None:
        return False
    return row.regime_label == "ranging"


# =====================================================================
# §3.23 — Cross-asset feature gates (V7 §3.4 / §3.5, V8 §3.6)
# =====================================================================


def _slope(regime_panel: Any, asset: str, tf: str, ts_us: int) -> float | None:
    if regime_panel is None:
        return None
    row = regime_panel.lookup(asset, tf, ts_us)
    if row is None or row.trend_slope_30m is None:
        return None
    return row.trend_slope_30m


def g_btc_trend_30m_with(
    direction: str, fire_us: int, *, regime_panel: Any, **_kw: Any,
) -> bool:
    """V7 §3.4 — BTC 5m trend_slope sign matches fire direction."""
    s = _slope(regime_panel, "BTC", "5m", fire_us)
    if s is None or s == 0:
        return False
    return (s > 0 and direction == "UP") or (s < 0 and direction == "DOWN")


def g_sol_trend_slope_with(
    direction: str, fire_us: int, *, regime_panel: Any, **_kw: Any,
) -> bool:
    """V8 §3.6 — SOL 5m trend_slope sign matches direction."""
    s = _slope(regime_panel, "SOL", "5m", fire_us)
    if s is None or s == 0:
        return False
    return (s > 0 and direction == "UP") or (s < 0 and direction == "DOWN")


def g_BTC_slope_with(
    direction: str, fire_us: int, *, regime_panel: Any, **_kw: Any,
) -> bool:
    """V7 §3.5 — BTC 15m trend_slope sign matches direction (for SOL 15m fires)."""
    s = _slope(regime_panel, "BTC", "15m", fire_us)
    if s is None or s == 0:
        return False
    return (s > 0 and direction == "UP") or (s < 0 and direction == "DOWN")


def g_BTC_slope_strong_with(
    direction: str, fire_us: int, *, regime_panel: Any, **_kw: Any,
) -> bool:
    """V7 §3.5 — BTC 15m |slope| > 0.612 AND sign matches direction."""
    s = _slope(regime_panel, "BTC", "15m", fire_us)
    if s is None:
        return False
    if abs(s) <= BTC_SLOPE_STRONG_15M_THR:
        return False
    return (s > 0 and direction == "UP") or (s < 0 and direction == "DOWN")


def _adx(regime_panel: Any, asset: str, tf: str, ts_us: int) -> float | None:
    if regime_panel is None:
        return None
    row = regime_panel.lookup(asset, tf, ts_us)
    if row is None or row.adx_14 is None:
        return None
    return row.adx_14


def _rv_60m(regime_panel: Any, asset: str, tf: str, ts_us: int) -> float | None:
    if regime_panel is None:
        return None
    row = regime_panel.lookup(asset, tf, ts_us)
    if row is None or row.realized_vol_60m is None:
        return None
    return row.realized_vol_60m


def g_BTC_adx_strong(
    direction: str, fire_us: int, *, regime_panel: Any, **_kw: Any,
) -> bool:
    """V7 §3.5 — BTC 5m ADX-14 >= 25."""
    adx = _adx(regime_panel, "BTC", "5m", fire_us)
    if adx is None:
        return False
    return adx >= ADX_STRONG_THR


def g_ETH_adx_strong(
    direction: str, fire_us: int, *, regime_panel: Any, **_kw: Any,
) -> bool:
    """V7 §3.5 — ETH 5m ADX-14 >= 25."""
    adx = _adx(regime_panel, "ETH", "5m", fire_us)
    if adx is None:
        return False
    return adx >= ADX_STRONG_THR


def _rv_pct_below(
    vol_hurst_panel: Any, asset: str, fire_us: int, thr: float,
) -> bool:
    """True iff the asset's 5m rv_pct_24h (rolling-24h percentile of realized
    vol) is below ``thr``. Fail-closed on missing panel / warmup."""
    if vol_hurst_panel is None:
        return False
    row = vol_hurst_panel.lookup(asset, "5m", fire_us)
    pct = getattr(row, "rv_pct_24h", None) if row is not None else None
    return pct is not None and pct < thr


def g_BTC_vol_low(
    direction: str, fire_us: int, *, vol_hurst_panel: Any, **_kw: Any,
) -> bool:
    """V7 §3.5 — BTC 5m vol in the BOTTOM HALF of its trailing-24h
    distribution (rv_pct_24h < 0.50).

    TV_FIX_VOL_LOW_PERCENTILE_2026_06_03 — the prior absolute threshold
    (BTC_VOL_LOW_5M_MEDIAN=0.0042) was ~12.5x the real training median (and
    exceeded even the backtest max) → the gate was always True (dead no-op,
    even in-sample). Now a percentile gate (unit/formula-immune), mirroring
    the g_vol_high fix; reuses VolHurstPanel.rv_pct_24h(asset,'5m').
    """
    return _rv_pct_below(vol_hurst_panel, "BTC", fire_us, VOL_LOW_PCT_THR)


def g_ETH_vol_low(
    direction: str, fire_us: int, *, vol_hurst_panel: Any, **_kw: Any,
) -> bool:
    """V7 §3.5 — ETH 5m vol in the bottom half of its trailing-24h
    distribution (rv_pct_24h < 0.50). TV_FIX_VOL_LOW_PERCENTILE_2026_06_03
    (see g_BTC_vol_low)."""
    return _rv_pct_below(vol_hurst_panel, "ETH", fire_us, VOL_LOW_PCT_THR)


def g_BTC_tr_stack(
    direction: str, fire_us: int, *, tr_panel: Any, **_kw: Any,
) -> bool:
    """V7 §3.5 — BTC traders' reality EMA stack score has |abs| >= 1 (direction-agnostic)."""
    if tr_panel is None:
        return False
    row = tr_panel.lookup("BTC", fire_us)
    if row is None or row.tr_ema_stack_score is None:
        return False
    return abs(row.tr_ema_stack_score) >= 1


def g_J_btc_eth_vol_both_low(
    direction: str, fire_us: int, *, vol_hurst_panel: Any, **_kw: Any,
) -> bool:
    """V8 §3.2 — both BTC and ETH 5m vol in the bottom half of their
    trailing-24h distribution. TV_FIX_VOL_LOW_PERCENTILE_2026_06_03 (see
    g_BTC_vol_low)."""
    return (
        _rv_pct_below(vol_hurst_panel, "BTC", fire_us, VOL_LOW_PCT_THR)
        and _rv_pct_below(vol_hurst_panel, "ETH", fire_us, VOL_LOW_PCT_THR)
    )


def g_L_ETH_grandparent_adx_strong(
    direction: str, fire_us: int, *, regime_panel: Any, **_kw: Any,
) -> bool:
    """V8 §3.6 — ETH 1h ADX-14 >= 25 (strong trend in 1h grandparent)."""
    adx = _adx(regime_panel, "ETH", "1h", fire_us)
    if adx is None:
        return False
    return adx >= ADX_STRONG_THR


# =====================================================================
# §3.24 — Pre-window cross-asset (V7 §3.6, V8 §3.3)
# =====================================================================


def g_pw_btc_15m_trend_with(
    direction: str, fire_us: int, *, slot_start_us: int, window_s: int,
    regime_panel: Any, **_kw: Any,
) -> bool:
    """V7 §3.6 / V8 §3.3 — BTC 15m trend_slope at ws_s sign matches direction."""
    ws_s_us = int(slot_start_us) - int(window_s) * 1_000_000
    s = _slope(regime_panel, "BTC", "15m", ws_s_us)
    if s is None or s == 0:
        return False
    return (s > 0 and direction == "UP") or (s < 0 and direction == "DOWN")


def g_pw_sol_15m_trend_with(
    direction: str, fire_us: int, *, slot_start_us: int, window_s: int,
    regime_panel: Any, **_kw: Any,
) -> bool:
    """V8 §3.3 — SOL 15m trend_slope at ws_s sign matches direction."""
    ws_s_us = int(slot_start_us) - int(window_s) * 1_000_000
    s = _slope(regime_panel, "SOL", "15m", ws_s_us)
    if s is None or s == 0:
        return False
    return (s > 0 and direction == "UP") or (s < 0 and direction == "DOWN")


# =====================================================================
# §3.25 — 1h grandparent (V8 §3.1)
# =====================================================================


def g_grandparent_trend_with(
    direction: str, fire_us: int, *, asset: str, regime_panel: Any, **_kw: Any,
) -> bool:
    """V8 §3.1 — 1h trend_slope sign matches direction."""
    s = _slope(regime_panel, asset, "1h", fire_us)
    if s is None or s == 0:
        return False
    return (s > 0 and direction == "UP") or (s < 0 and direction == "DOWN")


def g_grandparent_1h_slope_strong_with(
    direction: str, fire_us: int, *, asset: str, regime_panel: Any, **_kw: Any,
) -> bool:
    """V8 §3.1 — 1h |trend_slope| > 0.85 AND sign matches direction."""
    s = _slope(regime_panel, asset, "1h", fire_us)
    if s is None:
        return False
    if abs(s) <= GRANDPARENT_SLOPE_STRONG_THR:
        return False
    return (s > 0 and direction == "UP") or (s < 0 and direction == "DOWN")


def g_1h_rf_with(
    direction: str, fire_us: int, *, asset: str, range_filter_1h: Any, **_kw: Any,
) -> bool:
    """V8 §3.1 — 1h Range Filter rf_dir sign matches direction."""
    if range_filter_1h is None:
        return False
    row = range_filter_1h.lookup(asset, fire_us)
    if row is None:
        return False
    if direction == "UP":
        return row.rf_dir == 1
    return row.rf_dir == -1


# =====================================================================
# §3.26 — Confluence gates (V8 §3.2, multi-asset)
# =====================================================================


def g_2asset_btc_eth_with(
    direction: str, fire_us: int, *, regime_panel: Any, **_kw: Any,
) -> bool:
    """V8 §3.2 — BOTH BTC and ETH 5m trend_slope sign match direction."""
    btc = _slope(regime_panel, "BTC", "5m", fire_us)
    eth = _slope(regime_panel, "ETH", "5m", fire_us)
    if btc is None or eth is None:
        return False
    if direction == "UP":
        return btc > 0 and eth > 0
    return btc < 0 and eth < 0


def g_2asset_either_trending_with(
    direction: str, fire_us: int, *, regime_panel: Any, **_kw: Any,
) -> bool:
    """V8 §3.2 — at least ONE of BTC / ETH 5m trends matches direction."""
    btc = _slope(regime_panel, "BTC", "5m", fire_us)
    eth = _slope(regime_panel, "ETH", "5m", fire_us)
    if btc is None and eth is None:
        return False
    if direction == "UP":
        return (btc is not None and btc > 0) or (eth is not None and eth > 0)
    return (btc is not None and btc < 0) or (eth is not None and eth < 0)


def g_btc_sol_confluence_5m_with(
    direction: str, fire_us: int, *, regime_panel: Any, **_kw: Any,
) -> bool:
    """V8 §3.2 — BTC 5m + SOL 5m trend slope BOTH match direction."""
    btc = _slope(regime_panel, "BTC", "5m", fire_us)
    sol = _slope(regime_panel, "SOL", "5m", fire_us)
    if btc is None or sol is None:
        return False
    if direction == "UP":
        return btc > 0 and sol > 0
    return btc < 0 and sol < 0


# V8 alias — used by 15m sleeves that name the gate distinctly
g_2a_btc_sol_trend_with = g_btc_sol_confluence_5m_with


def g_btc_eth_confluence_5m_with(
    direction: str, fire_us: int, *, regime_panel: Any, **_kw: Any,
) -> bool:
    """V8 §3.2 — alias of g_2asset_btc_eth_with."""
    return g_2asset_btc_eth_with(direction, fire_us, regime_panel=regime_panel)


def g_xa_unanimity_5m_with(
    direction: str, fire_us: int, *, regime_panel: Any, **_kw: Any,
) -> bool:
    """V8 §3.2 — all 3 assets' 5m trend slopes unanimously match direction."""
    btc = _slope(regime_panel, "BTC", "5m", fire_us)
    eth = _slope(regime_panel, "ETH", "5m", fire_us)
    sol = _slope(regime_panel, "SOL", "5m", fire_us)
    if btc is None or eth is None or sol is None:
        return False
    if direction == "UP":
        return btc > 0 and eth > 0 and sol > 0
    return btc < 0 and eth < 0 and sol < 0


def g_3asset_combined_unanimity(
    direction: str, fire_us: int, *,
    regime_panel: Any, range_filter_panel: Any, **_kw: Any,
) -> bool:
    """V8 §3.2 — all 3 assets agree via BOTH rf_dir AND trend_slope (high conviction)."""
    if regime_panel is None or range_filter_panel is None:
        return False
    for asset in ("BTC", "ETH", "SOL"):
        rf_row = range_filter_panel.lookup(asset, fire_us)
        if rf_row is None:
            return False
        s = _slope(regime_panel, asset, "5m", fire_us)
        if s is None:
            return False
        if direction == "UP":
            if not (rf_row.rf_dir == 1 and s > 0):
                return False
        else:
            if not (rf_row.rf_dir == -1 and s < 0):
                return False
    return True


def g_btc_eth_divergence(
    direction: str, fire_us: int, *, regime_panel: Any, **_kw: Any,
) -> bool:
    """V8 §3.2 — BTC and ETH 5m trend slopes have OPPOSITE signs (divergence signal).

    Direction-agnostic; combined with directional gate downstream.
    """
    btc = _slope(regime_panel, "BTC", "5m", fire_us)
    eth = _slope(regime_panel, "ETH", "5m", fire_us)
    if btc is None or eth is None:
        return False
    return (btc > 0 and eth < 0) or (btc < 0 and eth > 0)


def g_xa_3source_trend_with(
    direction: str, fire_us: int, *, range_filter_panel: Any, **_kw: Any,
) -> bool:
    """V7 §3.4 — BTC + ETH + SOL all have the same rf_dir direction at fire_us."""
    if range_filter_panel is None:
        return False
    rows = [range_filter_panel.lookup(a, fire_us) for a in ("BTC", "ETH", "SOL")]
    if any(r is None for r in rows):
        return False
    if direction == "UP":
        return all(r.rf_dir == 1 for r in rows)
    return all(r.rf_dir == -1 for r in rows)


# =====================================================================
# §3.27 — DI agrees (V8 §3.7)
# =====================================================================


def g_di_agrees(
    direction: str, fire_us: int, *, asset: str, tf: str,
    regime_panel: Any, **_kw: Any,
) -> bool:
    """V8 §3.7 — +DI > -DI for UP, -DI > +DI for DOWN at (asset, tf=15m)."""
    if regime_panel is None:
        return False
    row = regime_panel.lookup(asset, tf, fire_us)
    if row is None or row.plus_di_14 is None or row.minus_di_14 is None:
        return False
    if direction == "UP":
        return row.plus_di_14 > row.minus_di_14
    return row.minus_di_14 > row.plus_di_14


# =====================================================================
# §3.28 — Liquidity shock (V8 §3.7)
# =====================================================================


def g_liq_shock_against(
    direction: str, fire_us: int, *, slug: str, book_mirror: Any,
    token_id_up: str, token_id_dn: str, **_kw: Any,
) -> bool:
    """V8 §3.7 — depth on opposite side dropped > 30 % in last 5s (mean-revert play).

    Limitation: requires a 5-second-ago book snapshot. The current BookMirror
    exposes only the LATEST snapshot, so this gate returns False until the
    panel adds a rolling history (or the controller threads in the snapshot
    timestamp). Acts as a "skip" until that wiring lands.
    """
    # TODO(V8-liq-shock): wire a 5s book-mirror history.
    return False


# =====================================================================
# §3.29 — Imb5 strong (V6 §3.13 / V8 — book imbalance)
# =====================================================================


def g_imb5_strong_with(
    direction: str, fire_us: int, *, slug: str, book_mirror: Any,
    token_id_up: str, token_id_dn: str, **_kw: Any,
) -> bool:
    """V6/V8 — within-token L5 order-imbalance DIFF > 0.20 AND sign matches dir.

    imb5_diff = up_imb5 - dn_imb5, where each token's imb5 = (bid_vol - ask_vol)
    / (bid_vol + ask_vol) over its top 5 levels.

    TV_FIX_IMB5_WITHIN_TOKEN_2026_06_03 — was a cross-token L25 ASK-depth ratio
    ``(up_ask_depth - dn_ask_depth)/sum`` (asks-only, different normalization).
    The backtest imb5 is the difference of each token's OWN L5 bid-vs-ask
    imbalance (build_micro_panel.py:69) — restores the feature the 0.20
    threshold was calibrated against. (NOTE: IMB5_STRONG_THR=0.20 was set on the
    backtest's imb5_diff distribution (~±1.4); recompute from live Poly-book
    data when convenient — see sniper_v5_thresholds comment.)
    """
    if book_mirror is None:
        return False
    up_imb = _imb5_within(book_mirror.get(token_id_up))
    dn_imb = _imb5_within(book_mirror.get(token_id_dn))
    if up_imb is None or dn_imb is None:
        return False
    imb = up_imb - dn_imb
    if abs(imb) <= IMB5_STRONG_THR:
        return False
    return (imb > 0 and direction == "UP") or (imb < 0 and direction == "DOWN")


# =====================================================================
# §3.30 — Slot-end OFI (V7 §3.3 — STUB pending trade subscriber)
# =====================================================================


# Slot-end OFI thresholds (TV_FIX_SLOT_END_OFI_2026_06_07). Scale-free: a net
# taker-imbalance RATIO (NOT the original spec's absolute $100) so the same
# thresholds hold across BTC/ETH/SOL/DOGE/BNB/XRP; a 60s notional floor fails
# closed on a too-thin window.
SLOT_END_OFI_RATIO_THR: float = 0.05            # net 5% taker imbalance
SLOT_END_OFI_MIN_NOTIONAL_USD: float = 50_000.0  # 60s quote-volume floor
SLOT_END_OFI_LOOKBACK_S: int = 60


def g_slot_end_ofi_with(
    direction: str, fire_us: int, *,
    asset: str = "", vwap_store: Any = None, **_kw: Any,
) -> bool:
    """V7 §3.3 — slot-end order-flow imbalance, directional.

    Net taker-flow imbalance over the trailing ``SLOT_END_OFI_LOOKBACK_S`` (60s)
    of 1s Binance spot bars, anchored at ``fire_us`` (the causal 'now' — the
    V7_02 consumer fires at late offsets {240,270}s, so this window IS the
    run-up into slot-end). Fires when the net taker-imbalance RATIO agrees with
    ``direction`` and clears both the ratio floor and the 60s notional floor.

    TV_FIX_SLOT_END_OFI_2026_06_07 — replaces the long-standing ``return False``
    stub. Computed from the TV-native Binance 1s flow
    (``vwap_store.flow_window`` → ``(ts_us, taker_buy_quote, quote_volume,
    trade_count)``), NOT the original spec's per-slug Polymarket trade-print OFI
    (that needs a Polymarket trade subscriber which does not exist). It is
    therefore a SPOT order-flow proxy and scale-free (ratio, not absolute $).
    Returns False (no fire) on warm-up / a too-thin window — fail closed.
    Mirrors g_disagr_hawkes: the controller can't precompute (no fire_us in
    ``_build_gate_kwargs``), so the gate reads the flow window itself.
    """
    if vwap_store is None or not asset:
        return False
    bars = vwap_store.flow_window(asset, fire_us, SLOT_END_OFI_LOOKBACK_S)
    if not bars:
        return False
    buy_quote = sum(b[1] for b in bars)
    total_quote = sum(b[2] for b in bars)
    if total_quote < SLOT_END_OFI_MIN_NOTIONAL_USD:
        return False
    # OFI = buy - sell = buy - (total - buy) = 2*buy - total; ratio in [-1, +1].
    ratio = (2.0 * buy_quote - total_quote) / total_quote
    if abs(ratio) < SLOT_END_OFI_RATIO_THR:
        return False
    return (ratio > 0 and direction == "UP") or (ratio < 0 and direction == "DOWN")


# =====================================================================
# §3.31 — Vol contracting (V8 §3.9 — V5 R3 base)
# =====================================================================


def g_vol_contracting(
    direction: str, fire_us: int, *, asset: str, tf: str,
    regime_panel: Any, vol_hurst_panel: Any, **_kw: Any,
) -> bool:
    """V8 §3.9 — vol contracting: short-window realized vol below long-window
    (rv_60s < rv_900s), direction-agnostic — the backtest definition
    (03_compute_gates.py: ``g_vol_contracting = rv_60s < rv_900s``).

    TV_FIX_VOL_CONTRACTING_2026_06_03 — replaces the prior absolute
    ``raw_rv < VOL_HIGH_RV60_THR*0.5`` proxy, which was mis-defined vs the
    backtest AND mis-scaled (de-annualized rv ≪ thr*0.5 → ~always True, an
    inverted no-op). Now reads the TV-native 1s realized-vol windows. Returns
    False on missing panel / warmup.
    """
    if vol_hurst_panel is None or not hasattr(vol_hurst_panel, "realized_vol_1s"):
        return False
    rv_60s = vol_hurst_panel.realized_vol_1s(asset, 60)
    rv_900s = vol_hurst_panel.realized_vol_1s(asset, 900)
    if rv_60s is None or rv_900s is None:
        return False
    return rv_60s < rv_900s


# =====================================================================
# Aliases (V8 §3.9 — spec-named variants of existing gates)
# =====================================================================


# V8 §3.9 lists ``g_tr_full_stack_with`` as an alias of g_tr_stack_full_with.
g_tr_full_stack_with = g_tr_stack_full_with

# V8 §3.9 lists ``g_above_1h_dailyvwap`` and ``g_tr_stack_full`` as names
# the V8 spec uses interchangeably with the existing _with form.
g_above_1h_dailyvwap_no_dir = g_above_1h_dailyvwap_with  # no-rename alias
g_tr_stack_full = g_tr_stack_full_with


# =====================================================================
# V9 — Polymarket flow + HL cascade gates
# (SHADOW_DEPLOY_SPEC_V9_AND_VL_2026_05_27.md §2.1-§2.4)
# =====================================================================
#
# Data sources injected at fire time by ``polymarket_sniper_v5._build_gate_kwargs``:
#   * ``asset_trades`` — recent Polymarket trade prints from the in-memory
#     ``V9DataStore`` (fed live by TradeMirror; CLAUDE.md inv #13), filtered to
#     the sleeve's asset (one DataFrame per asset). Columns the B-gates read:
#     slug, timestamp_us, outcome ('Up'/'Down'), side ('buy'/'sell'), size.
#   * ``hl_short_proxy`` — pre-filtered Hyperliquid liquidations (Close Short +
#     Open Long, market fills only) with pre-computed ``notional = size * price``.
#     Columns the A2 gate reads: coin, time_exchange_us, notional. Sourced from
#     the in-memory ``V9DataStore`` HL proxy (currently returns None pending the
#     TV-native Binance feed; A2 stays defensive/no-fire until then).
#
# All gates return False on missing/empty inputs (defensive — engine boot
# succeeds even if the in-memory buffer is still warming up; gates simply
# never fire until trade flow accumulates per CLAUDE.md inv #13).


def _flow_legs_usd(w: Any) -> tuple[float, float, float, float]:
    """USD notional per (outcome, side) leg over a windowed trade slice ``w``.

    Returns ``(up_buy, up_sell, dn_buy, dn_sell)`` in USD = sum(size*price).
    TV_FIX_B1_USD_TWOLEG_2026_06_03 — the backtest Polymarket flow features
    measure USD notional (price*size), not raw shares
    (pm_trade_flow_2026_05_26/01_build_pm_flow_features.py). Falls back to
    shares (price absent / all-zero) so a buffer that predates the price
    column still produces a non-degenerate (if mis-unit) signal.
    """
    usd = (w["size"] * w["price"]) if "price" in w.columns else w["size"]
    up = w["outcome"] == "Up"
    dn = w["outcome"] == "Down"
    buy = w["side"] == "buy"
    sell = w["side"] == "sell"
    return (
        float(usd[up & buy].sum()),
        float(usd[up & sell].sum()),
        float(usd[dn & buy].sum()),
        float(usd[dn & sell].sum()),
    )


def g_b1_poly_flow_aligned(
    direction: str,
    fire_us: int,
    *,
    slug: str | None = None,
    asset_trades: Any = None,
    window_s: int | str = 60,
    thresh_shares: int | str = 500,
    **_kw: Any,
) -> bool:
    """B1: Polymarket aggressor flow ALIGNED with our direction in the
    ``window_s`` seconds before ``fire_us``.

    Net flow = (outcome_buys − outcome_sells) on OUR direction's outcome
    side, in shares. True iff > ``thresh_shares``.

    Asset-specific signal strength (per spec §2.1):
      * SOL: primary (+9.1pp lift at $500, n=788).
      * BTC: weaker (+2.6pp at $1k), prefer B2/B3 instead.
      * ETH: marginal — not recommended as primary.

    Returns False on missing slug / asset_trades / empty window — defensive
    against engine boot before the in-memory V9DataStore buffer has warmed up.
    """
    if asset_trades is None or slug is None:
        return False
    try:
        if len(asset_trades) == 0:
            return False
    except (TypeError, ValueError):
        return False
    ws = int(window_s)
    thr = float(thresh_shares)
    t_start = int(fire_us) - ws * 1_000_000
    w = asset_trades[
        (asset_trades["slug"] == slug)
        & (asset_trades["timestamp_us"] >= t_start)
        & (asset_trades["timestamp_us"] < fire_us)
    ]
    if len(w) == 0:
        return False
    # TV_FIX_B1_USD_TWOLEG_2026_06_03 — backtest aligned flow is TWO-LEG in USD:
    # bull = up_buy + down_sell, bear = up_sell + down_buy; aligned = bull-bear
    # for UP (bear-bull for DOWN). thr is now USD ($500), matching the backtest.
    up_buy, up_sell, dn_buy, dn_sell = _flow_legs_usd(w)
    bull = up_buy + dn_sell
    bear = up_sell + dn_buy
    aligned = (bull - bear) if direction == "UP" else (bear - bull)
    return aligned > thr


def g_b2_poly_flow_contrarian(
    direction: str,
    fire_us: int,
    *,
    slug: str | None = None,
    asset_trades: Any = None,
    window_s: int | str = 60,
    thresh_shares: int | str = 2000,
    **_kw: Any,
) -> bool:
    """B2: Polymarket aggressor flow OPPOSING our direction in the
    ``window_s`` seconds before ``fire_us``.

    True iff net opposing flow > ``thresh_shares`` (the contrarian effect
    is positive for BTC at +10.97pp aggregated, strongest on DOWN fires).

    Asset-specific signal strength (per spec §2.2):
      * BTC: contrarian IS positive signal (use at $2k threshold).
      * SOL: contrarian is ANTI-signal (-18.5pp). DO NOT use as positive gate
        on SOL sleeves — see ``g_b2_poly_flow_NOT_opposing`` for the inverse
        wrapper used in V9_10.
      * ETH: mild positive at $500 (+4.6pp).
    """
    if asset_trades is None or slug is None:
        return False
    try:
        if len(asset_trades) == 0:
            return False
    except (TypeError, ValueError):
        return False
    ws = int(window_s)
    thr = float(thresh_shares)
    t_start = int(fire_us) - ws * 1_000_000
    w = asset_trades[
        (asset_trades["slug"] == slug)
        & (asset_trades["timestamp_us"] >= t_start)
        & (asset_trades["timestamp_us"] < fire_us)
    ]
    if len(w) == 0:
        return False
    # TV_FIX_B1_USD_TWOLEG_2026_06_03 — opposing flow, two-leg USD: for an UP
    # fire the bearish combo is bear-bull (bull-bear for a DOWN fire). USD thr.
    up_buy, up_sell, dn_buy, dn_sell = _flow_legs_usd(w)
    bull = up_buy + dn_sell
    bear = up_sell + dn_buy
    opposing = (bear - bull) if direction == "UP" else (bull - bear)
    return opposing > thr


def g_b2_poly_flow_NOT_opposing(
    direction: str,
    fire_us: int,
    *,
    slug: str | None = None,
    asset_trades: Any = None,
    window_s: int | str = 60,
    thresh_shares: int | str = 500,
    **_kw: Any,
) -> bool:
    """B2-NOT: True iff the OPPOSING-direction flow is BELOW ``thresh_shares``
    in the window — i.e. no big contrarian push against us.

    Used by V9_10 (SOL_5M_B3_ABS500_NO_OPP_V9) where SOL B2 contrarian is an
    anti-signal — we filter OUT fires where opposing flow is heavy. Inverts
    ``g_b2_poly_flow_contrarian`` with a lower threshold (500 vs 2000).

    Defensive: returns False on missing data so this gate is conservative.
    This means if asset_trades is empty, the sleeve will NOT fire (consistent
    with B1/B2/B3 behavior).
    """
    if asset_trades is None or slug is None:
        return False
    try:
        if len(asset_trades) == 0:
            return False
    except (TypeError, ValueError):
        return False
    return not g_b2_poly_flow_contrarian(
        direction,
        fire_us,
        slug=slug,
        asset_trades=asset_trades,
        window_s=window_s,
        thresh_shares=thresh_shares,
    )


def g_b3_poly_flow_abs(
    direction: str,
    fire_us: int,
    *,
    slug: str | None = None,
    asset_trades: Any = None,
    window_s: int | str = 60,
    thresh_shares: int | str = 500,
    **_kw: Any,
) -> bool:
    """B3: Direction-agnostic strong directional flow on EITHER side.

    True iff |net_up| + |net_dn| > ``thresh_shares``. Signal: active price
    discovery, trend signals more reliable.

    SOL +13.7pp at $500; ALL +8.5pp at $2k. Combine with directional gates
    (V9_08 uses BOTH direction with no further filter; V9_10 adds NOT-opp).
    Defensive: returns False on missing data.
    """
    if asset_trades is None or slug is None:
        return False
    try:
        if len(asset_trades) == 0:
            return False
    except (TypeError, ValueError):
        return False
    ws = int(window_s)
    thr = float(thresh_shares)
    t_start = int(fire_us) - ws * 1_000_000
    w = asset_trades[
        (asset_trades["slug"] == slug)
        & (asset_trades["timestamp_us"] >= t_start)
        & (asset_trades["timestamp_us"] < fire_us)
    ]
    if len(w) == 0:
        return False
    # TV_FIX_B1_USD_TWOLEG_2026_06_03 — abs directional flow in USD notional.
    up_buy, up_sell, dn_buy, dn_sell = _flow_legs_usd(w)
    up_net = up_buy - up_sell
    dn_net = dn_buy - dn_sell
    return (abs(up_net) + abs(dn_net)) > thr


def g_a2_hl_short_cascade(
    direction: str,
    fire_us: int,
    *,
    asset_coin: str = "BTC",
    hl_short_proxy: Any = None,
    window_s: int | str = 300,
    thresh_usd: int | str = 100_000,
    **_kw: Any,
) -> bool:
    """A2: Hyperliquid short-liquidation cascade in the ``window_s`` seconds
    pre-fire → predicts price UP.

    HL "short proxy" rows are pre-filtered at boot to:
      (dir=='Close Short' AND source=='hl-s3-fills' AND method=='market') OR
      (dir=='Open Long' AND source=='hl-s3-fills' AND method=='market')
    with ``notional = size * price`` pre-computed.

    True iff sum(notional) for ``asset_coin`` within the window > ``thresh_usd``.

    Asset coverage:
      * BTC: well-populated, $100k threshold gives WR=95.7% (n=140, t=7.5).
      * ETH/SOL: ENABLED 2026-05-30 — the multi-CEX liq feed (OKX/Bybit/Gate/
        Bitget, $5k cap removed) now carries ETH/SOL liquidations, so the
        per-(asset) cascade is computable. Thresholds are scaled-down
        provisionals (ETH 50k/25k, SOL 25k/15k) pending shadow calibration —
        the original "insufficient data" caveat was the frozen HL-fills source.

    Defensive: returns False on missing data so the A2 sleeves silently skip
    until the V9DataStore proxy is populated (None when the CEX liq feed is
    not wired).
    """
    if hl_short_proxy is None:
        return False
    try:
        if len(hl_short_proxy) == 0:
            return False
    except (TypeError, ValueError):
        return False
    ws = int(window_s)
    thr = float(thresh_usd)
    asset_proxy = hl_short_proxy[hl_short_proxy["coin"] == asset_coin]
    if len(asset_proxy) == 0:
        return False
    t_start = int(fire_us) - ws * 1_000_000
    mask = (
        (asset_proxy["time_exchange_us"] >= t_start)
        & (asset_proxy["time_exchange_us"] < fire_us)
    )
    return float(asset_proxy.loc[mask, "notional"].sum()) > thr


# =====================================================================
# §3.32 — DISAGR-HAWKES (TV_AGENT_SPEC_SHADOW_DISAGR_HAWKES_SOL5M_2026_06_03)
# =====================================================================


def _l1_dev_bps_dollar(book: dict | None) -> float | None:
    """Stoikov L1 microprice deviation from mid, in bps, using DOLLAR sizes.

    mid = (ask0+bid0)/2; mp = (bid$*ask0 + ask$*bid0)/(bid$+ask$) where
    bid$/ask$ are L1 price*size (dollar) sizes; dev_bps = (mp-mid)/mid*1e4.
    None if L1 missing / non-finite / degenerate (spec §1).
    """
    if not book:
        return None
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    if not bids or not asks:
        return None
    try:
        bid0 = float(bids[0]["price"]); bid0_sz = float(bids[0]["size"])
        ask0 = float(asks[0]["price"]); ask0_sz = float(asks[0]["size"])
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    bsz0 = bid0 * bid0_sz   # bid L1 dollar size
    asz0 = ask0 * ask0_sz   # ask L1 dollar size
    denom = bsz0 + asz0
    mid = (ask0 + bid0) / 2.0
    if denom <= 0.0 or mid <= 0.0:
        return None
    mp = (bsz0 * ask0 + asz0 * bid0) / denom
    if not math.isfinite(mp):
        return None
    return (mp - mid) / mid * 1e4


def _imb5_dollar(book: dict | None) -> float | None:
    """Cross-token L5 book imbalance in DOLLAR sizes (spec §2):
    (bid$5 - ask$5)/(bid$5 + ask$5), 0.0 if total is 0, range [-1,1].
    None only on missing book.
    """
    if not book:
        return None

    def _dollar(side: str) -> float:
        tot = 0.0
        for lvl in (book.get(side) or [])[:5]:
            try:
                p = float(lvl["price"]); s = float(lvl["size"])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(p) and math.isfinite(s):
                tot += p * s
        return tot

    bid5 = _dollar("bids")
    ask5 = _dollar("asks")
    s = bid5 + ask5
    if s <= 0.0:
        return 0.0
    return (bid5 - ask5) / s


def disagr_hawkes_features(
    book_mirror: Any, token_id_up: str, token_id_dn: str,
) -> tuple[float | None, float | None]:
    """Returns ``(mp_skew, imb5_diff)`` for the disagr-hawkes sleeve.

    mp_skew = up_dev_bps - dn_dev_bps (Stoikov L1, dollar sizes);
    imb5_diff = up_imb5 - dn_imb5 (L5, dollar sizes). Either is None when the
    corresponding token's book is missing/degenerate. Shared by the gate AND
    the controller's audit row so both see identical values.
    """
    if book_mirror is None:
        return (None, None)
    up_book = book_mirror.get(token_id_up)
    dn_book = book_mirror.get(token_id_dn)
    up_dev = _l1_dev_bps_dollar(up_book)
    dn_dev = _l1_dev_bps_dollar(dn_book)
    up_imb = _imb5_dollar(up_book)
    dn_imb = _imb5_dollar(dn_book)
    mp_skew = (up_dev - dn_dev) if (up_dev is not None and dn_dev is not None) else None
    imb5_diff = (up_imb - dn_imb) if (up_imb is not None and dn_imb is not None) else None
    return (mp_skew, imb5_diff)


def g_disagr_hawkes(
    direction: str,
    fire_us: int,
    *,
    book_mirror: Any = None,
    token_id_up: str = "",
    token_id_dn: str = "",
    hawkes_imbalance: float | None = None,
    vwap_store: Any = None,
    asset: str = "",
    **_kw: Any,
) -> bool:
    """DISAGR-HAWKES DN fire predicate (shadow_disagr_hawkes_sol_5m_dn).

    Fire iff direction is DOWN AND:
      mp_skew < 0  (microprice leans DOWN) AND
      imb5_diff > 0  (L5 depth disagrees, leans UP) AND
      hawkes_lambda_imbalance < -0.2  (Binance flow confirms net SELL).

    The Hawkes imbalance is either passed directly (``hawkes_imbalance``, used
    by unit tests) or computed here from the 1s order-flow window
    (``vwap_store`` + ``asset``, the production path — the controller can't
    precompute it because ``_build_gate_kwargs`` has no fire_us). None during
    warm-up → no fire (``hawkes_warmup``). DN-only sleeve.
    """
    if direction != "DOWN":
        return False
    h = hawkes_imbalance
    if h is None and vwap_store is not None:
        h = hawkes_lambda_imbalance_for_fire(vwap_store, asset, fire_us)
    if h is None:
        return False
    mp_skew, imb5_diff = disagr_hawkes_features(book_mirror, token_id_up, token_id_dn)
    if mp_skew is None or imb5_diff is None:
        return False
    return mp_skew < 0.0 and imb5_diff > 0.0 and h < -0.2


# =====================================================================
# §3.33 Cross-sleeve confirmation (TV_AGENT_SPEC_ETH_MERGE_HURST_2026_06_08)
# =====================================================================


def g_sleeve_confirms(
    direction: str,
    fire_us: int,
    *,
    sibling_sleeve_id: str,
    require_same_direction: str = "true",
    sibling_confirm_fn: Any = None,
    **_kw: Any,
) -> bool:
    """Conviction gate — pass iff a SIBLING sleeve's full gate-stack ALSO passes
    for the SAME slug at the SAME ``fire_us`` (and, when ``require_same_direction``,
    on the candidate's direction).

    The controller injects ``sibling_confirm_fn`` (a closure over the current
    slot + per-fire oracle snapshot) so the sibling is evaluated over the SAME
    per-cycle panels — no book/kline re-fetch. Fail-CLOSED: if the fn is not
    wired (unit/paper context) or the sibling is unknown, return False so the
    candidate does NOT fire on an unconfirmed signal.
    """
    if sibling_confirm_fn is None:
        return False
    same_dir = str(require_same_direction).strip().lower() in ("true", "1", "yes")
    return bool(sibling_confirm_fn(sibling_sleeve_id, direction, fire_us, same_dir))


# =====================================================================
# Public surface
# =====================================================================


__all__ = [
    # §3.32
    "disagr_hawkes_features", "g_disagr_hawkes",
    # §3.33 Cross-sleeve confirmation
    "g_sleeve_confirms",
    # §3.1
    "g_book_depth_supports_250", "g_depth_250_strict",
    # §3.2
    "g_trend_slope_with", "g_trend_slope_strong_with", "g_regime_stack_with",
    # §3.3
    "g_mp_skew_with", "g_mp_skew_strong_with",
    "g_mp_no_extreme", "g_mp_no_extreme_100",
    # §3.4
    "g_rf_with", "g_rf_aged", "g_rf_fresh", "g_rf_strict_align",
    # §3.5
    "g_tr_above_ema50", "g_tr_above_ema200", "g_tr_above_ema800",
    "g_tr_above_cloud", "g_tr_above_pp",
    "g_tr_stack_with", "g_tr_stack_full_with", "g_tr_partial_stack_with",
    "g_tr_within_adr", "g_tr_in_active_session",
    # §3.6
    "g_ribbon_agrees", "g_ribbon_slope_with",
    # §3.8
    "g_sms_liq_reclaim_with", "g_sms_no_liquidity_above",
    # §3.9
    "g_vol_high",
    # §3.10
    "above_1h_dailyvwap", "g_above_1h_dailyvwap_with",
    # §3.11
    "g_near_pivot",
    # §3.12
    "g_offset_early", "g_hod_us_afternoon", "g_dir_up", "g_dir_down",
    # §3.13
    "g_tight_ribbon",
    # V6 / V7 / V8 extension (2026-05-27) — sections §3.14 .. §3.31
    # §3.14 TA indicators
    "g_cci_strong_with", "g_cci_extreme_with", "g_cci_with",
    "g_mfi_with", "g_mfi_strong_with",
    "g_bb_pos_with",
    "g_stoch_with",
    # §3.15 Hawkes
    "g_hawkes_imb_loose_with",
    # §3.16 Hurst variants
    "g_hurst_trending", "g_hurst_reverting",
    "g_hurst_regime_with", "g_hurst_mp_trend_with", "g_hurst_trend_with",
    # §3.17 F7 v7
    "g_f7_v7_overbought", "g_f7_v7_oversold", "g_f7_v7_with",
    "g_btc_f7_with", "g_btc_f7_against",
    "g_f7_rsi_with",
    # §3.18 TOD
    "g_tod_asia_morning", "g_tod_european_morning",
    "g_tod_us_open", "g_tod_us_afternoon",
    "g_tod_us_evening", "g_tod_europe_us_window",
    "g_hod_european_morning",
    "g_hour_not_in",
    # §3.19 Offsets / pre-window
    "g_off_60_240", "g_pw_trend_slope_with",
    # §3.20 Entry-VWAP
    "g_entry_vwap_in_band", "g_entry_vwap_in_band_narrow", "g_entry_vwap_in_30_70",
    "g_vwap_in_45_85", "g_vwap_in_55_80", "g_vwap_premium",
    # §3.21 Microprice variant
    "g_mp_no_extreme_150",
    # §3.22 Parent 15m
    "g_parent_15m_regime_with", "g_parent_15m_slope_with",
    "g_parent_15m_not_ranging", "g_parent15m_ranging",
    "g_q_prev15m_agrees", "g_regime_ranging_at_ws",
    # §3.23 Cross-asset
    "g_btc_trend_30m_with", "g_sol_trend_slope_with",
    "g_BTC_slope_with", "g_BTC_slope_strong_with",
    "g_BTC_adx_strong", "g_ETH_adx_strong",
    "g_BTC_vol_low", "g_ETH_vol_low",
    "g_BTC_tr_stack",
    "g_J_btc_eth_vol_both_low",
    "g_L_ETH_grandparent_adx_strong",
    # §3.24 Pre-window cross-asset
    "g_pw_btc_15m_trend_with", "g_pw_sol_15m_trend_with",
    # §3.25 1h grandparent
    "g_grandparent_trend_with", "g_grandparent_1h_slope_strong_with",
    "g_1h_rf_with",
    # §3.26 Confluence
    "g_2asset_btc_eth_with", "g_2asset_either_trending_with",
    "g_btc_sol_confluence_5m_with", "g_2a_btc_sol_trend_with",
    "g_btc_eth_confluence_5m_with",
    "g_xa_unanimity_5m_with", "g_3asset_combined_unanimity",
    "g_btc_eth_divergence",
    "g_xa_3source_trend_with",
    # §3.27 DI agrees
    "g_di_agrees",
    # §3.28 Liquidity shock (stub)
    "g_liq_shock_against",
    # §3.29 Book imbalance
    "g_imb5_strong_with",
    # §3.30 Slot-end OFI (stub)
    "g_slot_end_ofi_with",
    # §3.31 Vol contracting
    "g_vol_contracting",
    # V9 (SHADOW_DEPLOY_SPEC_V9_AND_VL_2026_05_27.md §2.1-§2.4)
    "g_b1_poly_flow_aligned",
    "g_b2_poly_flow_contrarian",
    "g_b2_poly_flow_NOT_opposing",
    "g_b3_poly_flow_abs",
    "g_a2_hl_short_cascade",
    # Aliases
    "g_tr_full_stack_with", "g_tr_stack_full",
]
