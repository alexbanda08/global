"""Bella Fade detector — long-only dip-buy after seller exhaustion.

Pattern (paraphrased from tutorial):
  Strong "in-play" asset gets dumped at session open by an aggressive seller.
  When the seller exhausts, natural strength reverts price up.

5-minute crypto translation:
  1. In-play long: rvol_24h > 1.5 AND price > MA(4h)  (recent strength)
  2. Selloff window (last K bars, K=4..8 ending at t-1):
        cumulative return < -SELLOFF_PCT
        ≥ MIN_RED_BARS consecutive red closes
        avg(taker_buy_ratio) over window < SELLER_THR (sellers dominant)
        avg(range) over window > SLOPPY_MULT × rolling_range_med (sloppy)
  3. Trendline-break entry on bar t:
        close(t) > max(high[t-3:t-1])  (clears recent down-trend cap)
        close(t) > close(t-1)            (momentum reversal)
        taker_buy_ratio(t) > 0.50        (buyers stepping in)
  4. Anchor proximity: setup must be within ANCHOR_WINDOW_BARS of a session
     anchor (LONDON / NY) — Asia anchor is too thin in crypto for clean fades.

Output: per-symbol parquet of detected setups + the implied trade params
(entry, stop, tp1, tp2, max_hold) for downstream simulator.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "strategy_lab" / "reports" / "scalping" / "bella_fade"
OUT.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class BellaFadeParams:
    """Iter 2 defaults for crypto 5m.

    Changes vs iter 1:
      - Pre-selloff strength filter RESTORED (close[t-w] > ma_24h[t-w])
      - Whipsaw pre-check: skip if last 3 bars closed below LOD-buffer
      - ATR-based stop floor (max of 0.20% buffer or 0.5×ATR)
      - Single TP at 1.2R (was 2R) — winners come fast in crypto
      - Tighter shot clock (12 bars = 1h)
      - NEW: OBV trend confirmation (obv_slope_20 not strongly negative)
      - NEW: CMF buyer-stepin (cmf_20 turning positive at entry)
      - NEW: Volume Z spike (vol_z_20 > 0.5 on the reversal bar)
      - NEW: Inside value area (entry must be near POC, not far stretched)
    """
    selloff_window_min: int = 4
    selloff_window_max: int = 8
    selloff_pct_min: float = 0.003
    min_red_bars: int = 2
    seller_thr: float = 0.50
    sloppy_mult: float = 1.0
    rvol_thr: float = 1.0
    require_pre_selloff_strength: bool = True
    anchor_session: tuple[str, ...] = ("ASIA", "LONDON", "NY", "OFF")
    anchor_window_bars: int = 999
    cooldown_bars: int = 12

    # NEW: extended-feature gates (tuned softer in iter-2 fix-up)
    require_obv_not_collapsing: bool = False  # disabled — too restrictive
    require_cmf_turning_up: bool = True       # cmf_20 > -0.10 on entry bar (cheap, broad filter)
    require_vol_spike: bool = False           # disabled — kills frequency too much
    require_inside_value_area: bool = False
    whipsaw_lookback: int = 3                 # last N bars must not have closed below LOD-buffer

    # Trade params (iter 2 fixes)
    stop_buffer_pct: float = 0.002      # 0.20% below LOD (was 0.10%)
    stop_atr_mult: float = 0.5          # stop = LOD - max(buffer, atr_mult × ATR)
    tp_R: float = 1.2                   # single target (no partial)
    max_hold_bars: int = 12             # 1h shot clock (was 24)


def _detect_one_window(df: pd.DataFrame, t: int, w: int, p: BellaFadeParams) -> dict | None:
    """Check whether bars [t-w : t] form a valid selloff ending at t-1.

    Returns dict of measurements if valid, else None. Tutorial intent:
    asset was strong BEFORE the dump (price > MA at t-w), then aggressive
    seller hits, then exhausts.
    """
    sub = df.iloc[t - w : t]
    if len(sub) != w:
        return None

    # Pre-selloff strength: price was above its 24h MA at the START of the window
    if p.require_pre_selloff_strength:
        ma_at_start = df["ma_24h"].iloc[t - w]
        close_at_start = df["close"].iloc[t - w]
        if not np.isfinite(ma_at_start) or close_at_start <= ma_at_start:
            return None

    # Cumulative return across the window
    cum_ret = sub["close"].iloc[-1] / sub["close"].iloc[0] - 1.0
    if cum_ret > -p.selloff_pct_min:
        return None

    # Red-bar streak ending at t-1
    red_streak_at_end = 0
    for i in range(len(sub) - 1, -1, -1):
        if sub["is_red"].iloc[i] == 1:
            red_streak_at_end += 1
        else:
            break
    if red_streak_at_end < p.min_red_bars:
        return None

    # Aggressive-seller signature
    avg_taker_buy = sub["taker_buy_ratio"].mean()
    if not (avg_taker_buy < p.seller_thr):
        return None

    # Sloppy bars (above-median range)
    rolling_med_at_t = df["rolling_range_med"].iloc[t]
    if not np.isfinite(rolling_med_at_t) or rolling_med_at_t <= 0:
        return None
    avg_range = sub["range"].mean()
    if not (avg_range > p.sloppy_mult * rolling_med_at_t):
        return None

    return {
        "selloff_w": w,
        "selloff_cum_ret": float(cum_ret),
        "selloff_avg_taker_buy": float(avg_taker_buy),
        "selloff_red_streak": int(red_streak_at_end),
        "selloff_avg_range": float(avg_range),
        "selloff_rolling_range_med": float(rolling_med_at_t),
        "lod": float(sub["low"].min()),
    }


def detect(df: pd.DataFrame, p: BellaFadeParams = BellaFadeParams()) -> pd.DataFrame:
    """Scan a 5m feature DataFrame for Bella Fade entries.

    Returns a DataFrame indexed by entry timestamp with columns:
      symbol, entry_idx, entry_price, stop, tp1, tp2, max_hold_bars,
      lod, selloff_*, rvol, dist_vwap_pct, session, bars_since_anchor
    """
    n = len(df)
    if n < p.selloff_window_max + 25:
        return pd.DataFrame()

    in_play_now = (df["rvol"] > p.rvol_thr)
    near_anchor = (
        df["session"].isin(p.anchor_session)
        & (df["bars_since_anchor"] <= p.anchor_window_bars)
    )
    # Reversal-bar conditions on `t`
    high_3 = df["high"].rolling(3).max().shift(1)
    reversal_bar = (
        (df["close"] > high_3)
        & (df["close"] > df["close"].shift(1))
        & (df["taker_buy_ratio"] > 0.50)
    )

    # Iter-2 extra-feature gates (each optional)
    extra_ok = pd.Series(True, index=df.index)
    if p.require_obv_not_collapsing and "obv_slope_20" in df.columns:
        # Reject only the bottom-quintile of obv slope (genuine sell-off momentum)
        thr = df["obv_slope_20"].quantile(0.20)
        extra_ok &= df["obv_slope_20"] > thr
    if p.require_cmf_turning_up and "cmf_20" in df.columns:
        extra_ok &= df["cmf_20"] > -0.10
    if p.require_vol_spike and "vol_z_20" in df.columns:
        extra_ok &= df["vol_z_20"] > 0.5
    if p.require_inside_value_area and "dist_poc_pct" in df.columns:
        extra_ok &= df["dist_poc_pct"].abs() < 0.005

    candidate = (in_play_now & near_anchor & reversal_bar & extra_ok).fillna(False).to_numpy()

    rows = []
    arr_open = df["open"].to_numpy()
    arr_high = df["high"].to_numpy()
    arr_low = df["low"].to_numpy()
    arr_close = df["close"].to_numpy()
    idx = df.index

    last_entry = -10_000
    for t in np.where(candidate)[0]:
        # Cooldown to avoid stacked signals
        if t - last_entry < p.cooldown_bars:
            continue
        # Need enough back-history for the largest window
        if t < p.selloff_window_max + 1:
            continue

        match = None
        for w in range(p.selloff_window_max, p.selloff_window_min - 1, -1):
            m = _detect_one_window(df, t, w, p)
            if m is not None:
                match = m
                break
        if match is None:
            continue

        entry_price = float(arr_close[t])
        lod = match["lod"]

        # Whipsaw pre-check: any of the last `whipsaw_lookback` bars closed
        # *below* the LOD-buffer? If so, the LOD has already failed once;
        # skip — high probability of stop-hunt.
        wb = int(p.whipsaw_lookback)
        if wb > 0:
            recent_closes = arr_close[max(0, t - wb): t]
            buffer_floor = lod * (1.0 - p.stop_buffer_pct)
            if (recent_closes < buffer_floor).any():
                continue

        # Stop = LOD - max(buffer_pct, 0.5×ATR) for crypto-noise tolerance
        atr_at_t = float(df["atr_20"].iloc[t]) if "atr_20" in df.columns else 0.0
        atr_floor = (p.stop_atr_mult * atr_at_t) if np.isfinite(atr_at_t) and atr_at_t > 0 else 0.0
        buffer_dist = max(p.stop_buffer_pct * lod, atr_floor)
        stop = lod - buffer_dist
        risk_per_unit = entry_price - stop
        if risk_per_unit <= 0:
            continue

        tp = entry_price + p.tp_R * risk_per_unit
        # Keep tp1/tp2 columns for back-compat with two-target sim
        tp1 = entry_price + 1.0 * risk_per_unit
        tp2 = entry_price + p.tp_R * risk_per_unit

        rows.append({
            "entry_time": idx[t],
            "entry_idx": int(t),
            "entry_price": entry_price,
            "stop": float(stop),
            "tp": float(tp),
            "tp1": float(tp1),
            "tp2": float(tp2),
            "side": 1,
            "lod": float(lod),
            "max_hold_bars": int(p.max_hold_bars),
            "rvol": float(df["rvol"].iloc[t]),
            "dist_vwap_pct": float(df["dist_vwap_pct"].iloc[t]),
            "session": str(df["session"].iloc[t]),
            "bars_since_anchor": int(df["bars_since_anchor"].iloc[t]),
            "atr_at_entry": float(atr_at_t),
            "obv_slope_at_entry": float(df["obv_slope_20"].iloc[t]) if "obv_slope_20" in df.columns else 0.0,
            "cmf_at_entry": float(df["cmf_20"].iloc[t]) if "cmf_20" in df.columns else 0.0,
            "vol_z_at_entry": float(df["vol_z_20"].iloc[t]) if "vol_z_20" in df.columns else 0.0,
            **match,
        })
        last_entry = t

    return pd.DataFrame(rows).set_index("entry_time") if rows else pd.DataFrame()


if __name__ == "__main__":
    import argparse
    from data_loader import load_5m_with_features

    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--end", default="2026-03-31")
    args = ap.parse_args()

    p = BellaFadeParams()
    print(f"Bella Fade params: {p}\n")

    for sym in args.symbols:
        df = load_5m_with_features(sym, start=args.start, end=args.end)
        sigs = detect(df, p)
        weeks = (df.index[-1] - df.index[0]).total_seconds() / (7 * 86400)
        per_week = len(sigs) / weeks if weeks > 0 else 0.0
        print(f"{sym}: {len(sigs):>5} setups over {weeks:.1f}w = {per_week:.1f}/week")
        sigs.to_parquet(OUT / f"{sym}_signals.parquet")
        if len(sigs):
            # Quick raw-edge check: average forward 12-bar return
            fwd = df["close"].pct_change(12).shift(-12)
            edge = fwd.reindex(sigs.index).mean()
            print(f"  raw fwd-12b mean return: {edge*100:+.3f}%")
            print(f"  session split: {sigs['session'].value_counts().to_dict()}")
