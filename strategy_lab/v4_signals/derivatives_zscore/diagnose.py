"""Diagnostic: where is the edge?

For each symbol:
  1. Bar-count at each score threshold (no filters)
  2. Filter pass-rates conditional on score >= 70
  3. Forward-return (1h, 4h, 24h) at each score threshold — pure predictive power
  4. Forward-return for each individual z-score crossing ±1.5σ — component ablation

This tells us BEFORE backtesting whether the signal has predictive power, and which
sub-components carry it. Crystal-clear edge / no-edge signal in 5 minutes.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
PANELS = ROOT / "data" / "v4" / "derivatives_zscore" / "panels"

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
HORIZONS_H = [1, 4, 24]


def load_h(symbol: str) -> pd.DataFrame:
    p = pd.read_parquet(PANELS / f"{symbol}_zscore.parquet")
    p_h = p.resample("1h").last()
    return p_h.dropna(subset=["score_bull_scaled", "score_bear_scaled", "spot_price"])


def fwd_return(prices: pd.Series, h: int) -> pd.Series:
    """Forward return: price(t+h) / price(t) - 1."""
    return prices.shift(-h) / prices - 1


def hit_rate(returns: pd.Series, direction: int) -> tuple[float, float]:
    """Return (mean_return, hit_rate) for a directional bet."""
    s = returns.dropna()
    if len(s) == 0:
        return (np.nan, np.nan)
    if direction > 0:
        return (s.mean(), (s > 0).mean())
    else:
        return (-s.mean(), (s < 0).mean())  # short: negate, count downs as wins


def diagnose(symbol: str):
    df = load_h(symbol)
    px = df["spot_price"]
    print(f"\n══════════ {symbol}  bars={len(df):,}  3y BTC={px.iloc[-1]/px.iloc[0]:.2f}× ══════════")

    # --- 1. Score histogram ---
    print("\n  Score-bull buckets:        Score-bear buckets:")
    for thr in [50, 60, 70, 75, 80]:
        nb = (df["score_bull_scaled"] >= thr).sum()
        nB = (df["score_bear_scaled"] >= thr).sum()
        print(f"    >={thr:3d}: {nb:6,} ({nb/len(df):.2%})    >={thr:3d}: {nB:6,} ({nB/len(df):.2%})")

    # --- 2. Forward return at score thresholds (NO filters) ---
    print(f"\n  FORWARD RETURN at score-bull threshold (no AND filters)")
    print(f"  {'thr':>5} | {'n':>6} | {'mean(1h)':>9} {'hit%(1h)':>9} | {'mean(4h)':>9} {'hit%(4h)':>9} | {'mean(24h)':>10} {'hit%(24h)':>10}")
    for thr in [50, 60, 70, 75]:
        mask = df["score_bull_scaled"] >= thr
        if mask.sum() < 10:
            continue
        row = [f"  {thr:>5} | {mask.sum():>6}"]
        for h in HORIZONS_H:
            ret = fwd_return(px, h)[mask]
            mr, hr = hit_rate(ret, +1)
            row.append(f" | {mr:>+9.4%} {hr:>9.1%}" if h == 24 else f" | {mr:>+9.4%} {hr:>9.1%}")
        print("".join(row))

    print(f"\n  FORWARD RETURN at score-bear threshold (short bet — wins when price drops)")
    print(f"  {'thr':>5} | {'n':>6} | {'mean(1h)':>9} {'hit%(1h)':>9} | {'mean(4h)':>9} {'hit%(4h)':>9} | {'mean(24h)':>10} {'hit%(24h)':>10}")
    for thr in [50, 60, 70, 75]:
        mask = df["score_bear_scaled"] >= thr
        if mask.sum() < 10:
            continue
        row = [f"  {thr:>5} | {mask.sum():>6}"]
        for h in HORIZONS_H:
            ret = fwd_return(px, h)[mask]
            mr, hr = hit_rate(ret, -1)
            row.append(f" | {mr:>+9.4%} {hr:>9.1%}" if h == 24 else f" | {mr:>+9.4%} {hr:>9.1%}")
        print("".join(row))

    # --- 3. Component ablation: each z-score crossing ±1.5σ → forward 4h return ---
    print(f"\n  COMPONENT ablation: bar-count, mean fwd-4h-ret, hit-rate (>0)")
    components_long = [
        ("z_lsr < -1.5", df["z_lsr"] < -1.5, +1),
        ("z_fund < -1.0", df["z_fund"] < -1.0, +1),
        ("z_oi > +1.0", df["z_oi"] > 1.0, +1),
        ("z_oi_silent > +1.5", df["z_oi_silent"] > 1.5, +1),
        ("z_cb_premium > +1.0", df["z_cb_premium"] > 1.0, +1),
        ("z_dom_stables < -1.0", df["z_dom_stables"] < -1.0, +1),
        ("cross_inst_lead > 0", df["cross_institutional_lead"] > 0, +1),
        ("brigalS < -1.0", df["brigalS"] < -1.0, +1),
    ]
    components_short = [
        ("z_lsr > +1.5", df["z_lsr"] > 1.5, -1),
        ("z_fund > +1.0", df["z_fund"] > 1.0, -1),
        ("z_oi < -1.0", df["z_oi"] < -1.0, -1),
        ("z_cb_premium < -1.0", df["z_cb_premium"] < -1.0, -1),
        ("z_dom_stables > +1.0", df["z_dom_stables"] > 1.0, -1),
        ("cross_lev_heat > 1.5", df["cross_leverage_heat"] > 1.5, -1),
        ("brigalS > +1.0", df["brigalS"] > 1.0, -1),
    ]
    print(f"  {'BULLISH bet':<30} {'n':>7} {'mean':>10} {'hit%':>7}  baseline-mean: {fwd_return(px,4).mean():+.4%}")
    for label, mask, dir_ in components_long:
        if mask.sum() < 10:
            continue
        ret = fwd_return(px, 4)[mask]
        mr, hr = hit_rate(ret, dir_)
        print(f"  {label:<30} {mask.sum():>7} {mr:>+10.4%} {hr:>7.1%}")
    print(f"\n  {'BEARISH bet':<30} {'n':>7} {'mean':>10} {'hit%':>7}")
    for label, mask, dir_ in components_short:
        if mask.sum() < 10:
            continue
        ret = fwd_return(px, 4)[mask]
        mr, hr = hit_rate(ret, dir_)
        print(f"  {label:<30} {mask.sum():>7} {mr:>+10.4%} {hr:>7.1%}")


def main():
    for sym in SYMBOLS:
        diagnose(sym)


if __name__ == "__main__":
    main()
