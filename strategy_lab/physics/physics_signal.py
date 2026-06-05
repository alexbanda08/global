"""
physics_signal.py — "physics of BTC" market features for the up-down markets.

Reusable, feed-agnostic. Mirrors the article's snapshot:
    speed=$/m  dist=$(price-strike)  cross=min-to-return-to-strike  have=min-left

Convention (matches canonical):
- strike = chainlink reference price at slot_start (market_resolutions.strike_price).
- "current" price = a causal asof read of whatever feed you pass (chainlink_rtds
  primary, binance-1s ablation). Outcome is chainlink-settled, so tune on chainlink.
- side = +1 if price is ABOVE strike (Up favored), -1 if below. The "physics bet" is
  CONTINUATION: bet the side BTC is currently on (inertia is hard to reverse).
- speed_away > 0 means price is moving AWAY from strike (inertia confirms the side).
  speed_toward = -speed_away; cross = |dist|/speed_toward (min to roll back); if moving
  away, cross = CROSS_CAP (never returns at current speed).

All *_us are UTC microseconds.
"""
from __future__ import annotations
import numpy as np

CROSS_CAP = 999.0  # minutes; "won't return at current speed"


def asof(ts_us: np.ndarray, px: np.ndarray, t_us: int) -> float:
    """Last price at-or-before t_us (causal). NaN if none."""
    i = int(np.searchsorted(ts_us, t_us, side="right")) - 1
    return float(px[i]) if i >= 0 else float("nan")


def physics_at(ts_us: np.ndarray, px: np.ndarray, strike: float,
               fire_us: int, slot_end_us: int, speed_win_s: int = 60) -> dict | None:
    """
    Compute the physics snapshot at fire_us. Returns None if price coverage missing.

    Returns dict:
      now, dist (signed $), dist_abs, side (+1/-1), bet ('Up'/'Down'),
      speed (signed $/min, +=up), speed_abs, speed_away (signed; +=away from strike),
      cross (min to return to strike), have_m (min left), margin (cross-have_m),
      moving_away (bool)
    """
    now = asof(ts_us, px, fire_us)
    prev = asof(ts_us, px, fire_us - speed_win_s * 1_000_000)
    if not (np.isfinite(now) and np.isfinite(prev)):
        return None
    dist = now - strike
    side = 1 if dist >= 0 else -1
    speed = (now - prev) / (speed_win_s / 60.0)        # $/min, signed (+=rising)
    speed_away = speed * side                           # +=moving away from strike
    speed_toward = -speed_away
    cross = (abs(dist) / speed_toward) if speed_toward > 1e-9 else CROSS_CAP
    cross = min(cross, CROSS_CAP)
    have_m = (slot_end_us - fire_us) / 60_000_000.0
    return dict(
        now=now, dist=dist, dist_abs=abs(dist), side=side,
        bet=("Up" if side > 0 else "Down"),
        speed=speed, speed_abs=abs(speed), speed_away=speed_away,
        cross=cross, have_m=have_m, margin=cross - have_m,
        moving_away=bool(speed_away > 0),
    )


def speed_bucket(speed_abs: float) -> str:
    if speed_abs < 5:    return "quiet <5"
    if speed_abs < 10:   return "normal 5-10"
    if speed_abs < 15:   return "active 10-15"
    if speed_abs < 25:   return "storm 15-25"
    return "hurricane >=25"


def weak_combo_block(feat: dict, pa: str, thr_a: float, pb: str, thr_b: float) -> bool:
    """
    The article's WEAK_COMBO rule: block (WAIT) iff BOTH entry params are weak.
        if feat[pa] < thr_a and feat[pb] < thr_b: return True  # skip
    Higher param value = stronger. Returns True => SKIP the trade.
    """
    return (feat[pa] < thr_a) and (feat[pb] < thr_b)
