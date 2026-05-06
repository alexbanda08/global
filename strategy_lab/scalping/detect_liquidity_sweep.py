"""Liquidity-Sweep — fade the session-high/low takeout that reverses immediately.

Pattern (crypto-native — extremely common around session opens / round numbers):
  Price spikes through the session high (or low), takes out stop-loss orders
  parked there, then immediately closes BACK below (or above) the level. This
  creates trapped late breakout traders + stopped-out short scalpers; price
  reverses fast.

Why this works in crypto:
  - 24/7 markets concentrate stops at obvious levels (prior session high/low,
    daily open, round numbers). Market makers + algos hunt these.
  - The "sweep + reclaim" candle pattern is the cleanest evidence of a
    successful raid — a long upper wick with a close back inside.
  - Combined with a taker-delta divergence (price up, but taker buys NOT
    dominating), the reversal is high-probability.

Detection (5m bars, requires features.py extras):
  1. SHORT trigger:
       sweep_reclaim_high(t-1) == 1   (prior bar swept session_high but reclaimed)
       OR sweep_reclaim_high(t) == 1  (current bar IS the sweep+reclaim)
       AND close(t) < open(t)         (current bar bearish — confirmation)
       AND vol_z_20(t-1 or t) > 1.0   (volume spike during sweep)
       AND taker_delta on sweep bar < 0 (sellers stepping in despite price up)
  2. LONG trigger: mirror.

  3. Filters:
     - Skip OFF-session sweeps (low-liquidity hours often produce continuation)
     - Skip if the sweep bar's RANGE > 3× ATR(20) — that's not a sweep, that's
       a real news-driven move
     - Require RVOL > 0.8 (ensure asset has real activity)

Trade params:
  - Stop: sweep_extreme × (1 ± stop_buffer_pct)  (just beyond the wick)
  - Target: VWAP (mean-reversion target) capped at target_R_mult
  - Shot clock: 12 bars (reversal should be fast)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "strategy_lab" / "reports" / "scalping" / "liquidity_sweep"
OUT.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class LiquiditySweepParams:
    sweep_lookback: int = 2          # check current bar t and t-1 for sweep+reclaim

    # Confirmation gates
    require_bar_color: bool = True   # SHORT: close<open; LONG: close>open
    require_vol_spike: bool = True
    vol_z_floor: float = 0.5         # lowered from 1.0 — sweep wicks aren't always huge volume
    require_delta_divergence: bool = True
    skip_off_session: bool = True
    require_rvol: float = 0.8
    max_sweep_range_atr: float = 3.0

    # Side controls
    allow_long: bool = True
    allow_short: bool = True

    # Trade params
    stop_buffer_pct: float = 0.0008    # 0.08% beyond the sweep extreme
    target_via_vwap: bool = True
    target_R_mult: float = 1.0         # fallback target if VWAP not far enough
    max_target_R_mult: float = 2.5
    max_hold_bars: int = 12            # 1h shot clock — reversal should be fast
    cooldown_bars: int = 8


def detect(df: pd.DataFrame, p: LiquiditySweepParams = LiquiditySweepParams()) -> pd.DataFrame:
    """Detect liquidity-sweep reversals. Requires `add_extra` features."""
    n = len(df)
    if n < 50:
        return pd.DataFrame()

    needed = ["sweep_reclaim_high", "sweep_reclaim_low", "session_high",
              "session_low", "vwap_session", "vol_z_20", "taker_delta",
              "atr_20", "rvol", "session"]
    for c in needed:
        if c not in df.columns:
            raise ValueError(f"detect_liquidity_sweep requires '{c}' — run with extra=True")

    op = df["open"].to_numpy(dtype=float)
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    cl = df["close"].to_numpy(dtype=float)
    sr_hi = df["sweep_reclaim_high"].to_numpy(dtype=np.int8)
    sr_lo = df["sweep_reclaim_low"].to_numpy(dtype=np.int8)
    sh = df["session_high"].to_numpy(dtype=float)
    sl = df["session_low"].to_numpy(dtype=float)
    vwap = df["vwap_session"].to_numpy(dtype=float)
    vol_z = df["vol_z_20"].to_numpy(dtype=float)
    td = df["taker_delta"].to_numpy(dtype=float)
    atr = df["atr_20"].to_numpy(dtype=float)
    rvol = df["rvol"].to_numpy(dtype=float)
    sess = df["session"].to_numpy()
    range_bar = (df["high"] - df["low"]).to_numpy(dtype=float)
    idx = df.index

    rows: list[dict] = []
    last_entry = -10_000

    for t in range(2, n - 1):
        if t - last_entry < p.cooldown_bars:
            continue

        # Filter: session
        if p.skip_off_session and sess[t] == "OFF":
            continue
        # Filter: rvol
        if p.require_rvol and (not np.isfinite(rvol[t]) or rvol[t] < p.require_rvol):
            continue

        # Find a sweep bar STRICTLY BEFORE t (so bar t is a confirmation bar
        # following the sweep — not the sweep itself)
        sweep_bar = None
        side = None
        for k in range(max(0, t - p.sweep_lookback), t):  # exclude t
            if p.allow_short and sr_hi[k] == 1:
                sweep_bar = k
                side = -1
                break
            if p.allow_long and sr_lo[k] == 1:
                sweep_bar = k
                side = 1
                break
        if sweep_bar is None:
            continue

        # Skip if sweep bar's range was huge (real news, not a stop-hunt)
        atr_at = atr[sweep_bar]
        if np.isfinite(atr_at) and atr_at > 0:
            if range_bar[sweep_bar] > p.max_sweep_range_atr * atr_at:
                continue

        # Volume spike on sweep bar
        if p.require_vol_spike:
            if not (np.isfinite(vol_z[sweep_bar]) and vol_z[sweep_bar] > p.vol_z_floor):
                continue

        # Delta divergence: SHORT setup wants negative delta on sweep bar (sellers
        # absorbing the up-spike); LONG setup wants positive delta on sweep bar.
        if p.require_delta_divergence:
            if side == -1 and not (np.isfinite(td[sweep_bar]) and td[sweep_bar] < 0):
                continue
            if side == 1 and not (np.isfinite(td[sweep_bar]) and td[sweep_bar] > 0):
                continue

        # Bar-color confirmation on the entry bar t (or sweep bar if t == sweep)
        if p.require_bar_color:
            if side == -1 and not (cl[t] < op[t]):
                continue
            if side == 1 and not (cl[t] > op[t]):
                continue

        # Sweep extreme = the wick that took out liquidity
        if side == -1:
            sweep_extreme = float(hi[sweep_bar])
            stop = sweep_extreme * (1.0 + p.stop_buffer_pct)
        else:
            sweep_extreme = float(lo[sweep_bar])
            stop = sweep_extreme * (1.0 - p.stop_buffer_pct)

        entry_price = float(cl[t])
        risk = (stop - entry_price) if side == -1 else (entry_price - stop)
        if risk <= 0:
            continue

        # Target: VWAP if it's reasonable; else R-multiple fallback
        v_t = float(vwap[t])
        target_R = entry_price - p.target_R_mult * risk if side == -1 else entry_price + p.target_R_mult * risk
        max_R = entry_price - p.max_target_R_mult * risk if side == -1 else entry_price + p.max_target_R_mult * risk
        if p.target_via_vwap and np.isfinite(v_t):
            if side == -1:
                # VWAP target only useful if it's BELOW entry
                tp = min(target_R, v_t) if v_t < entry_price else target_R
                tp = max(tp, max_R)  # cap downside (don't go too far)
            else:
                tp = max(target_R, v_t) if v_t > entry_price else target_R
                tp = min(tp, max_R)  # cap upside
        else:
            tp = target_R

        rows.append({
            "entry_time": idx[t],
            "entry_idx": int(t),
            "side": int(side),
            "entry_price": entry_price,
            "stop": float(stop),
            "tp": float(tp),
            "max_hold_bars": int(p.max_hold_bars),
            "sweep_bar_offset": int(t - sweep_bar),
            "sweep_extreme": float(sweep_extreme),
            "session_high_at_sweep": float(sh[sweep_bar]),
            "session_low_at_sweep": float(sl[sweep_bar]),
            "vol_z_at_sweep": float(vol_z[sweep_bar]),
            "taker_delta_at_sweep": float(td[sweep_bar]),
            "atr_at_entry": float(atr[t]) if np.isfinite(atr[t]) else 0.0,
            "rvol_at_entry": float(rvol[t]) if np.isfinite(rvol[t]) else 0.0,
            "session": str(sess[t]),
        })
        last_entry = t

    return pd.DataFrame(rows).set_index("entry_time") if rows else pd.DataFrame()
