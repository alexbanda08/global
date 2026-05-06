"""Offside detector — fade trapped traders after a failed range breakout.

Pattern (paraphrased from tutorial):
  Trending move → consolidation range with ≥2 tests of top, ≥2 tests of bottom,
  near VWAP. Breakout attempt fails → trapped traders panic-cover → fast move
  to the opposite side of the range.

5-minute crypto translation:
  1. Trending move:    |close[t-W] - close[t-W-T]| > 1.5 × ATR(20)  (T=20 bars,
     W = range window, so the trend precedes the consolidation)
  2. Consolidation range over W=8..20 bars ending at t-K:
        (range_high - range_low) / mid < RANGE_PCT
        ≥2 highs within RANGE_TOUCH_PCT of range_high
        ≥2 lows within RANGE_TOUCH_PCT of range_low
        |close - vwap| / close < VWAP_PROX  for ≥50% of bars in window
  3. Failed breakout (or breakdown):
        UP-FAIL  : at least one bar in [t-K..t-1] closed > range_high
                   AND close(t) < range_high (back inside or below)
                   AND volume on the failure-direction bar > 1.5× window-avg
        DOWN-FAIL: mirror image
  4. Entry trigger on bar t:
        SHORT after UP-FAIL  + close(t) < (range_low + 0.5*range_height)
                              + taker_buy_ratio(t) < 0.50
        LONG  after DOWN-FAIL+ close(t) > (range_high - 0.5*range_height)
                              + taker_buy_ratio(t) > 0.50
  5. Stops + targets:
        SHORT: stop = range_high * (1 + STOP_BUFFER_PCT); tp = breakdown - range_height
        LONG:  stop = range_low  * (1 - STOP_BUFFER_PCT); tp = breakup    + range_height
  6. Shot clock: range_window_bars / 2 (panic should be fast)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "strategy_lab" / "reports" / "scalping" / "offside"
OUT.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class OffsideParams:
    """Iter 2 defaults.

    Changes vs iter 1:
      - allow_long / allow_short: short-only by default (long side was negative)
      - require_retest: wait for ONE retest of the broken level before entering
      - require_vol_spike: volume on entry bar > 1.2× window-avg (panic visible)
      - require_obv_divergence: OBV at range top must NOT be making new high
        on the up-fail bar (classic divergence signal)
      - range_pct: 0.7% (was 0.5%) — crypto rarely consolidates that tightly
      - tp_r_multiple: 0.7× measured-move (was 1.0×) — exit before mean-reversion
    """
    range_w_min: int = 8
    range_w_max: int = 20
    range_pct: float = 0.007
    range_touch_pct: float = 0.001
    min_top_tests: int = 2
    min_bot_tests: int = 2
    vwap_prox_pct: float = 0.004
    vwap_prox_min_frac: float = 0.40

    trend_lookback: int = 20
    trend_atr_mult: float = 1.0

    fail_lookback: int = 4
    fail_vol_mult: float = 1.3

    momentum_taker_thr: float = 0.50
    cooldown_bars: int = 12

    # Iter-2 side controls
    allow_long: bool = False
    allow_short: bool = True

    # Iter-2 confirmation gates
    require_retest: bool = True
    retest_tol_pct: float = 0.0008
    require_vol_spike_on_entry: bool = False  # disabled — retest already filters heavily
    entry_vol_mult: float = 1.2
    require_obv_divergence: bool = True   # at up-fail bar, OBV not at new high vs range start

    # Trade params
    stop_buffer_pct: float = 0.001
    tp_r_multiple: float = 0.7
    max_hold_factor: float = 0.5


def _rolling_max(x: np.ndarray, w: int) -> np.ndarray:
    s = pd.Series(x).rolling(w, min_periods=w).max()
    return s.to_numpy()


def _rolling_min(x: np.ndarray, w: int) -> np.ndarray:
    s = pd.Series(x).rolling(w, min_periods=w).min()
    return s.to_numpy()


def _check_range(df: pd.DataFrame, t_end: int, w: int, p: OffsideParams) -> dict | None:
    """Validate that bars [t_end-w : t_end] form a consolidation range.
    Returns dict with range_high/low/height/touches if valid, else None.
    """
    sub = df.iloc[t_end - w : t_end]
    if len(sub) != w:
        return None
    rh = float(sub["high"].max())
    rl = float(sub["low"].min())
    if rh <= rl:
        return None
    mid = (rh + rl) / 2.0
    height = rh - rl
    if height / mid >= p.range_pct:
        return None

    # Top/bottom tests
    top_thr = rh * (1 - p.range_touch_pct)
    bot_thr = rl * (1 + p.range_touch_pct)
    n_top = int((sub["high"] >= top_thr).sum())
    n_bot = int((sub["low"] <= bot_thr).sum())
    if n_top < p.min_top_tests or n_bot < p.min_bot_tests:
        return None

    # VWAP proximity
    vwap = sub["vwap_session"]
    if vwap.notna().sum() < w * 0.8:
        return None
    near_vwap = (np.abs(sub["close"] - vwap) / sub["close"]) < p.vwap_prox_pct
    if near_vwap.mean() < p.vwap_prox_min_frac:
        return None

    return {
        "range_w": w,
        "range_high": rh,
        "range_low": rl,
        "range_height": height,
        "range_pct": height / mid,
        "n_top_tests": n_top,
        "n_bot_tests": n_bot,
    }


def _check_trend(df: pd.DataFrame, t: int, range_w: int, p: OffsideParams) -> tuple[int, float] | None:
    """Verify the trend BEFORE the range. Returns (direction, magnitude_atr) or None.
    direction: +1 up, -1 down.
    """
    a = t - range_w - 1
    b = a - p.trend_lookback
    if b < 0:
        return None
    move = float(df["close"].iloc[a]) - float(df["close"].iloc[b])
    atr = float(df["atr_20"].iloc[a])
    if not np.isfinite(atr) or atr <= 0:
        return None
    mag = abs(move) / atr
    if mag < p.trend_atr_mult:
        return None
    return (1 if move > 0 else -1, mag)


def _precompute_range_stats(df: pd.DataFrame, p: OffsideParams) -> dict[int, dict]:
    """Precompute per-w rolling stats so the per-bar loop is O(1) lookup.

    For each w, output arrays aligned to df.index:
      rh[t], rl[t]   = rolling-w high / low ENDING at bar t (i.e., bars [t-w+1..t])
      rng_pct[t]     = (rh - rl) / mid
      n_top[t]       = count of high[i] >= rh[t]*(1-tch_pct) for i in [t-w+1..t]
      n_bot[t]       = count of low[i]  <= rl[t]*(1+tch_pct)
      near_vwap_frac[t] = fraction of bars in window with |close-vwap|/close < vwap_prox_pct
      win_avg_qv[t]  = mean quote_volume over [t-w+1..t]
    """
    hi = df["high"]
    lo = df["low"]
    cl = df["close"]
    qv = df["quote_volume"]
    vw = df["vwap_session"]

    near_vwap = (np.abs(cl - vw) / cl) < p.vwap_prox_pct

    out = {}
    for w in range(p.range_w_min, p.range_w_max + 1):
        rh = hi.rolling(w, min_periods=w).max()
        rl = lo.rolling(w, min_periods=w).min()
        mid = (rh + rl) / 2.0
        rng_pct = (rh - rl) / mid
        # touch counts: count rows in window where high >= top_thr (computed
        # per bar relative to per-bar rh — so we need a different formulation).
        # Approximation: use rolling-w sum of (high >= rh_at_bar_t * (1-tch)).
        # Since rh_at_bar_t is the max over the window, exactly 1 bar achieves it,
        # but bars within tch_pct might also count. We compute as a true count by
        # rolling over (high >= rh_per_bar - tol).
        top_thr = rh * (1 - p.range_touch_pct)
        bot_thr = rl * (1 + p.range_touch_pct)
        # pandas rolling apply is too slow; use the trick: count =
        #   rolling_sum( high >= top_thr_t ) but top_thr_t is per-bar. We can't
        #   shift cleanly; approximation: use rolling_sum of bars >= 0.998× rh
        # within the window. We compute via rolling_max over a tighter percentile.
        # Cleaner: for each bar t, count bars in [t-w+1..t] with high in
        # [top_thr_t, rh_t]. We can do: rolling_sum over (high >= top_thr_t) but
        # top_thr_t is bar-aligned, so use:
        n_top = (hi >= top_thr).rolling(w, min_periods=w).sum()
        n_bot = (lo <= bot_thr).rolling(w, min_periods=w).sum()
        nvf = near_vwap.rolling(w, min_periods=w).mean()
        wq = qv.rolling(w, min_periods=w).mean()
        out[w] = {
            "rh": rh.to_numpy(), "rl": rl.to_numpy(),
            "rng_pct": rng_pct.to_numpy(),
            "n_top": n_top.to_numpy(), "n_bot": n_bot.to_numpy(),
            "near_vwap_frac": nvf.to_numpy(),
            "win_avg_qv": wq.to_numpy(),
        }
    return out


def detect(df: pd.DataFrame, p: OffsideParams = OffsideParams()) -> pd.DataFrame:
    """Scan a 5m feature DataFrame for Offside entries.

    Returns DataFrame indexed by entry timestamp.
    """
    n = len(df)
    if n < p.range_w_max + p.trend_lookback + 5:
        return pd.DataFrame()

    rs = _precompute_range_stats(df, p)

    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    cl = df["close"].to_numpy(dtype=float)
    qv = df["quote_volume"].to_numpy(dtype=float)
    tbr = df["taker_buy_ratio"].to_numpy(dtype=float)
    atr = df["atr_20"].to_numpy(dtype=float)
    sess = df["session"].to_numpy()
    rvol = df["rvol"].to_numpy(dtype=float)
    obv = df["obv"].to_numpy(dtype=float) if "obv" in df.columns else None
    vol_z = df["vol_z_20"].to_numpy(dtype=float) if "vol_z_20" in df.columns else None
    cmf = df["cmf_20"].to_numpy(dtype=float) if "cmf_20" in df.columns else None
    idx = df.index

    rows: list[dict] = []
    last_entry = -10_000
    K = p.fail_lookback
    min_t = p.range_w_max + p.trend_lookback + K + 1

    for t in range(min_t, n - 1):
        if t - last_entry < p.cooldown_bars:
            continue

        # 1. Try each w (largest first — biggest range = strongest signal)
        match_w = None
        match = None
        t_end = t - K  # range ends K bars before t (room for failure scan)
        for w in range(p.range_w_max, p.range_w_min - 1, -1):
            stats = rs[w]
            rh_t = stats["rh"][t_end]
            rl_t = stats["rl"][t_end]
            if not np.isfinite(rh_t) or not np.isfinite(rl_t):
                continue
            if stats["rng_pct"][t_end] >= p.range_pct:
                continue
            if stats["n_top"][t_end] < p.min_top_tests:
                continue
            if stats["n_bot"][t_end] < p.min_bot_tests:
                continue
            if stats["near_vwap_frac"][t_end] < p.vwap_prox_min_frac:
                continue
            match_w = w
            match = {
                "range_high": float(rh_t),
                "range_low": float(rl_t),
                "win_avg_qv": float(stats["win_avg_qv"][t_end]),
            }
            break
        if match is None:
            continue

        # 2. Trend before range
        a = t_end - 1  # last bar BEFORE the range
        b = a - p.trend_lookback
        if b < 0:
            continue
        move = cl[a] - cl[b]
        atr_a = atr[a]
        if not np.isfinite(atr_a) or atr_a <= 0:
            continue
        trend_mag = abs(move) / atr_a
        if trend_mag < p.trend_atr_mult:
            continue
        trend_dir = 1 if move > 0 else -1

        rh = match["range_high"]
        rl = match["range_low"]
        height = rh - rl
        mid = (rh + rl) / 2.0
        win_avg_qv = match["win_avg_qv"]
        if win_avg_qv <= 0:
            continue

        # 3. Scan failure bars in [t-K..t-1]
        up_fail_bar = None
        down_fail_bar = None
        for f in range(t - K, t):
            if cl[f] > rh and qv[f] > p.fail_vol_mult * win_avg_qv:
                up_fail_bar = f
            if cl[f] < rl and qv[f] > p.fail_vol_mult * win_avg_qv:
                down_fail_bar = f

        # Entry trigger: opposite-side BREAK with iter-2 confirmation gates.
        cur = cl[t]
        side = None
        fail_extreme = None

        # OBV divergence at the failed-breakout bar:
        # for an up-fail, OBV at the fail bar should NOT exceed OBV at range start
        # (price made new high but order-flow didn't follow).
        def _obv_div_up(fb_idx: int, range_start_idx: int) -> bool:
            if obv is None or fb_idx < 0 or range_start_idx < 0:
                return True  # gate disabled if data missing
            return obv[fb_idx] <= obv[range_start_idx]

        def _obv_div_down(fb_idx: int, range_start_idx: int) -> bool:
            if obv is None or fb_idx < 0 or range_start_idx < 0:
                return True
            return obv[fb_idx] >= obv[range_start_idx]

        range_start = t_end - match_w  # first bar of consolidation

        if p.allow_short and up_fail_bar is not None and cur < rl:
            if tbr[t] < p.momentum_taker_thr:
                # Volume spike on entry?
                if p.require_vol_spike_on_entry and vol_z is not None:
                    if not (np.isfinite(vol_z[t]) and vol_z[t] > 0.5):
                        continue
                # OBV divergence at up-fail?
                if p.require_obv_divergence and not _obv_div_up(up_fail_bar, range_start):
                    continue
                # Wait-for-retest: at least one bar between up-fail and now
                # must have re-touched range_high (close to it within tol)
                if p.require_retest:
                    retest_tol = rh * p.retest_tol_pct
                    seen_retest = False
                    for k in range(up_fail_bar + 1, t):
                        if hi[k] >= rh - retest_tol and cl[k] < rh:
                            seen_retest = True
                            break
                    if not seen_retest:
                        continue
                side = -1
                fail_extreme = float(hi[up_fail_bar])
        elif p.allow_long and down_fail_bar is not None and cur > rh:
            if tbr[t] > p.momentum_taker_thr:
                if p.require_vol_spike_on_entry and vol_z is not None:
                    if not (np.isfinite(vol_z[t]) and vol_z[t] > 0.5):
                        continue
                if p.require_obv_divergence and not _obv_div_down(down_fail_bar, range_start):
                    continue
                if p.require_retest:
                    retest_tol = rl * p.retest_tol_pct
                    seen_retest = False
                    for k in range(down_fail_bar + 1, t):
                        if lo[k] <= rl + retest_tol and cl[k] > rl:
                            seen_retest = True
                            break
                    if not seen_retest:
                        continue
                side = 1
                fail_extreme = float(lo[down_fail_bar])
        if side is None:
            continue

        entry_price = float(cur)
        if side == -1:
            stop = fail_extreme * (1.0 + p.stop_buffer_pct)
            risk = stop - entry_price
            tp = entry_price - p.tp_r_multiple * height
        else:
            stop = fail_extreme * (1.0 - p.stop_buffer_pct)
            risk = entry_price - stop
            tp = entry_price + p.tp_r_multiple * height
        if risk <= 0:
            continue

        rows.append({
            "entry_time": idx[t],
            "entry_idx": int(t),
            "side": int(side),
            "entry_price": entry_price,
            "stop": float(stop),
            "tp": float(tp),
            "max_hold_bars": max(4, int(match_w * p.max_hold_factor)),
            "range_high": float(rh),
            "range_low": float(rl),
            "range_height_pct": float(height / mid),
            "range_w": int(match_w),
            "trend_dir": int(trend_dir),
            "trend_mag_atr": float(trend_mag),
            "session": str(sess[t]),
            "rvol": float(rvol[t]) if np.isfinite(rvol[t]) else 0.0,
            "fail_extreme": float(fail_extreme),
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

    p = OffsideParams()
    print(f"Offside params: {p}\n")

    for sym in args.symbols:
        df = load_5m_with_features(sym, start=args.start, end=args.end)
        sigs = detect(df, p)
        weeks = (df.index[-1] - df.index[0]).total_seconds() / (7 * 86400)
        print(f"{sym}: {len(sigs):>5} setups over {weeks:.1f}w = {len(sigs)/weeks:.1f}/week")
        if len(sigs):
            sides = sigs["side"].value_counts().to_dict()
            print(f"  side split: {sides}")
            # raw edge: forward 6-bar return × side
            fwd6 = df["close"].pct_change(6).shift(-6).reindex(sigs.index)
            edge = (fwd6 * sigs["side"]).mean()
            print(f"  raw fwd-6b directional return: {edge*100:+.3f}%")
            sigs.to_parquet(OUT / f"{sym}_signals.parquet")
