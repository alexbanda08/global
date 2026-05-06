"""VWAP-Bounce — fade pullback to VWAP from above, ride bounce back to session high.

Pattern (creative crypto adaptation):
  Strong asset trends up early in session → pulls back to VWAP from above →
  holds VWAP (does not close significantly below it) → bounces with money-flow
  confirmation (CMF turns up, MFI > 40, taker_buy spike).

Why this works in crypto:
  - VWAP is the institutional execution benchmark; algos buy pullbacks here
  - Daily-reset VWAP creates a fresh "fair value" anchor each UTC midnight
  - Combined with money-flow filters, weeds out continuation breakdowns

Detection (5m bars):
  1. Trend gate: close[t-N] < close[t-1] over recent N bars (was below) AND
     cum_delta_session > 0 at the bounce point (cumulative buying pressure)
  2. Pullback signature: at least one bar in [t-K..t-1] touched within
     PROX_PCT of VWAP from above. Lowest touch sets the "VWAP-test" bar.
  3. Hold check: low[VWAP_test_bar] >= vwap × (1 − HOLD_TOL_PCT). i.e., wick
     pierced but didn't close meaningfully through.
  4. Bounce trigger on bar t:
        close(t) > vwap_at_t  (back above VWAP)
        close(t) > close(t-1) (momentum up)
        cmf_20(t) > 0         (money flow positive)
        mfi_14(t) > 40        (not oversold panic — actual flow)
        taker_buy_ratio(t) > 0.55  (buyer aggression)

Trade params:
  - Stop: vwap × (1 − STOP_PCT) (just below VWAP — pattern invalid below VWAP)
  - Target: session_high or +TARGET_R_MULT × risk
  - Shot clock: 24 bars (2h)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "strategy_lab" / "reports" / "scalping" / "vwap_bounce"
OUT.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class VwapBounceParams:
    pullback_lookback: int = 10
    vwap_prox_pct: float = 0.0015
    hold_tol_pct: float = 0.0010
    trend_lookback: int = 12
    cum_delta_pos: bool = True

    # Bounce-bar gates (stricter to filter the 13/wk → 5-7/wk with real edge)
    require_cmf_pos: bool = True
    require_mfi_floor: float = 45.0          # was 40 — stricter
    require_taker_buy: float = 0.58          # was 0.55 — buyers must dominate, not just present
    require_close_above_3bar_high: bool = True  # NEW: real reversal confirmation
    require_obv_rising: bool = True             # NEW: OBV must be uptrending (cumul > 5-bar avg)

    # Trade params
    stop_pct_below_vwap: float = 0.0025  # slightly wider — VWAP can wick down 0.2%
    target_via_session_high: bool = True
    target_R_mult: float = 1.2           # tighter — 1.5R rarely hits in 2h
    max_target_R_mult: float = 2.5
    max_hold_bars: int = 18              # 1.5h (was 2h)
    cooldown_bars: int = 12


def detect(df: pd.DataFrame, p: VwapBounceParams = VwapBounceParams()) -> pd.DataFrame:
    """Scan for VWAP-bounce entries. Requires `add_extra` features."""
    n = len(df)
    if n < p.pullback_lookback + p.trend_lookback + 5:
        return pd.DataFrame()

    needed = ["vwap_session", "session_high", "cmf_20", "mfi_14", "taker_buy_ratio",
              "cum_delta_session"]
    for c in needed:
        if c not in df.columns:
            raise ValueError(f"detect_vwap_bounce requires column '{c}' — run with extra=True")

    cl = df["close"].to_numpy(dtype=float)
    op = df["open"].to_numpy(dtype=float)
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    vwap = df["vwap_session"].to_numpy(dtype=float)
    sh = df["session_high"].to_numpy(dtype=float)
    cmf = df["cmf_20"].to_numpy(dtype=float)
    mfi = df["mfi_14"].to_numpy(dtype=float)
    tbr = df["taker_buy_ratio"].to_numpy(dtype=float)
    cum_d = df["cum_delta_session"].to_numpy(dtype=float)
    obv_arr = df["obv"].to_numpy(dtype=float) if "obv" in df.columns else None
    sess = df["session"].to_numpy()
    idx = df.index

    # Pre-compute 3-bar prior high for confirmation gate
    high_3 = df["high"].rolling(3).max().shift(1).to_numpy(dtype=float)

    rows: list[dict] = []
    last_entry = -10_000

    min_t = max(p.pullback_lookback, p.trend_lookback) + 1
    for t in range(min_t, n - 1):
        if t - last_entry < p.cooldown_bars:
            continue

        v_t = vwap[t]
        if not np.isfinite(v_t) or v_t <= 0:
            continue

        # Bounce-bar gates
        if cl[t] <= v_t:
            continue
        if cl[t] <= cl[t - 1]:
            continue
        if p.require_cmf_pos and not (np.isfinite(cmf[t]) and cmf[t] > 0):
            continue
        if not (np.isfinite(mfi[t]) and mfi[t] > p.require_mfi_floor):
            continue
        if not (np.isfinite(tbr[t]) and tbr[t] > p.require_taker_buy):
            continue
        if p.cum_delta_pos and not (np.isfinite(cum_d[t]) and cum_d[t] > 0):
            continue
        # Trend was up but pulled back — close at bar (t - trend_lookback) was lower
        if t - p.trend_lookback < 0:
            continue
        if cl[t - p.trend_lookback] >= cl[t - 1]:
            continue
        # NEW (iter-2 fix): real-reversal confirmation — close above 3-bar high
        if p.require_close_above_3bar_high:
            if not (np.isfinite(high_3[t]) and cl[t] > high_3[t]):
                continue
        # NEW: OBV must be rising (cumul > its 5-bar SMA → buyer accumulation)
        if p.require_obv_rising and obv_arr is not None and t >= 5:
            obv_sma_5 = float(np.mean(obv_arr[t - 5: t]))
            if obv_arr[t] <= obv_sma_5:
                continue

        # Pullback signature: scan [t-K..t-1] for VWAP touch from above
        K = p.pullback_lookback
        touch_bar = -1
        touch_low = np.inf
        for k in range(t - K, t):
            if k < 0:
                continue
            v_k = vwap[k]
            if not np.isfinite(v_k) or v_k <= 0:
                continue
            # Touch = low within prox_pct of VWAP
            if abs(lo[k] - v_k) / v_k < p.vwap_prox_pct or (lo[k] <= v_k and hi[k] > v_k):
                if lo[k] < touch_low:
                    touch_low = lo[k]
                    touch_bar = k
        if touch_bar < 0:
            continue

        # Hold check: low at touch must not pierce > hold_tol_pct below VWAP
        v_touch = vwap[touch_bar]
        if (v_touch - touch_low) / v_touch > p.hold_tol_pct:
            continue

        entry_price = float(cl[t])
        stop = float(v_t * (1.0 - p.stop_pct_below_vwap))
        risk = entry_price - stop
        if risk <= 0:
            continue

        # Target: session_high or capped R-multiple
        sh_t = float(sh[t])
        target_at_R = entry_price + p.target_R_mult * risk
        max_target = entry_price + p.max_target_R_mult * risk
        if p.target_via_session_high and np.isfinite(sh_t) and sh_t > entry_price:
            tp = min(max_target, max(target_at_R, sh_t))
        else:
            tp = target_at_R

        rows.append({
            "entry_time": idx[t],
            "entry_idx": int(t),
            "side": 1,
            "entry_price": entry_price,
            "stop": stop,
            "tp": float(tp),
            "max_hold_bars": int(p.max_hold_bars),
            "vwap_at_entry": float(v_t),
            "session_high_at_entry": sh_t,
            "cmf_at_entry": float(cmf[t]),
            "mfi_at_entry": float(mfi[t]),
            "taker_buy_at_entry": float(tbr[t]),
            "cum_delta_at_entry": float(cum_d[t]),
            "touch_bar_offset": int(t - touch_bar),
            "session": str(sess[t]),
        })
        last_entry = t

    return pd.DataFrame(rows).set_index("entry_time") if rows else pd.DataFrame()
