"""Inverse-signal generator — flip a losing strategy to potentially capture its mirror edge.

Logic:
  If strategy X has WR 40% / PF 0.66 / avg -0.20R per trade, then taking the
  OPPOSITE side at the SAME entry timestamp should approach
  WR 60% / PF 1.5+ / avg +0.20R per trade — IF the original signal has a
  stable directional bias (consistent miss in one direction).

  Two ways to flip:

  (A) MIRROR_RR  : keep the same R:R structure, flip side
      Original LONG with stop=E-S, target=E+T  →
      Inverse SHORT with stop=E+S, target=E-T  (same R:R, opposite direction)

  (B) SWAP_LEVELS: swap the original stop and target levels
      Original LONG with stop=E-S, target=E+T  →
      Inverse SHORT with stop=E+T (the original target becomes the SL),
                       target=E-S (the original stop becomes the TP)
      This effectively "trades AGAINST" the original entry: if the original
      strategy correctly predicted direction, inverse loses; if original
      missed, inverse wins.

  We prefer (A) MIRROR_RR for clean R-multiple comparison. The user's intuition
  (40% WR → 60% inverse WR) maps directly to this transformation if the
  pattern's directional miss is consistent.

Usage:
    from inverse_signals import inverse_signals
    inv = inverse_signals(original_sigs, mode="mirror_rr")
"""
from __future__ import annotations

import pandas as pd


def inverse_signals(sigs: pd.DataFrame, mode: str = "mirror_rr") -> pd.DataFrame:
    """Return the inverse-side signals.

    Required columns:
      - entry_idx, entry_price, stop, max_hold_bars
      - one of: tp (single target) OR tp1+tp2 (two-target)
      - side (optional; defaults to 1 if missing)

    Output: same columns, with side flipped and stop/target adjusted per `mode`.
    """
    if len(sigs) == 0:
        return sigs.copy()

    out = sigs.copy()
    if "side" not in out.columns:
        out["side"] = 1

    entry = out["entry_price"].astype(float)
    stop_orig = out["stop"].astype(float)
    side_orig = out["side"].astype(int)

    risk_orig = (entry - stop_orig).abs()  # always positive; per-unit risk distance

    if mode == "mirror_rr":
        # Keep the same risk-distance, flip side and target direction.
        # Original target distance from entry:
        if "tp" in out.columns:
            tp_dist = (out["tp"].astype(float) - entry) * side_orig  # signed reward
            new_side = -side_orig
            new_stop = entry + (risk_orig * new_side * -1.0)  # stop on opposite side of entry
            new_tp = entry + (tp_dist.abs() * new_side)
            out["side"] = new_side
            out["stop"] = new_stop
            out["tp"] = new_tp
        if "tp1" in out.columns and "tp2" in out.columns:
            tp1_dist = (out["tp1"].astype(float) - entry) * side_orig
            tp2_dist = (out["tp2"].astype(float) - entry) * side_orig
            new_side = -side_orig if "side" in sigs.columns else -1
            new_stop = entry + (risk_orig * new_side * -1.0)
            out["side"] = new_side
            out["stop"] = new_stop
            out["tp1"] = entry + (tp1_dist.abs() * new_side)
            out["tp2"] = entry + (tp2_dist.abs() * new_side)

    elif mode == "swap_levels":
        # The original stop becomes the inverse target; original target becomes inverse stop.
        if "tp" in out.columns:
            tp_orig = out["tp"].astype(float)
            new_side = -side_orig
            out["side"] = new_side
            out["stop"] = tp_orig                # original TP is now SL
            out["tp"] = stop_orig                # original SL is now TP
        if "tp1" in out.columns and "tp2" in out.columns:
            tp1_orig = out["tp1"].astype(float)
            tp2_orig = out["tp2"].astype(float)
            new_side = -side_orig
            out["side"] = new_side
            out["stop"] = tp2_orig
            out["tp1"] = entry + (entry - tp1_orig)  # symmetric reflect
            out["tp2"] = stop_orig

    else:
        raise ValueError(f"unknown mode: {mode}")

    return out


if __name__ == "__main__":
    # Quick self-test
    df = pd.DataFrame({
        "entry_idx": [10, 20, 30],
        "entry_price": [100.0, 200.0, 50.0],
        "stop": [99.0, 198.0, 49.5],   # 1% below
        "tp": [101.2, 202.4, 50.6],    # 1.2% above (1.2R)
        "max_hold_bars": [12, 12, 12],
        "side": [1, 1, 1],
    })
    inv = inverse_signals(df, mode="mirror_rr")
    print("ORIG (long):")
    print(df.to_string(index=False))
    print("\nINVERSE (short, mirror_rr):")
    print(inv.to_string(index=False))
    # Verify: same R, flipped direction
    for i in range(len(df)):
        e = df["entry_price"].iloc[i]
        orig_risk = e - df["stop"].iloc[i]
        orig_reward = df["tp"].iloc[i] - e
        inv_risk = inv["stop"].iloc[i] - e
        inv_reward = e - inv["tp"].iloc[i]
        print(f"  trade {i}: orig R={orig_risk:.2f}, T={orig_reward:.2f}  |  "
              f"inv R={inv_risk:.2f}, T={inv_reward:.2f}  | side {df['side'].iloc[i]} → {inv['side'].iloc[i]}")
