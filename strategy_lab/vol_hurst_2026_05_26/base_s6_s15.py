"""Compute BASE S6 and S15 (= S1.5 surrogate) sleeves WITHOUT gates to test
user hypothesis on regime conditionality of S6 vs S1.5 directly.

S6 = spike continuation: bet WITH the recent strong move (here approximated as
     sign(ret_2m_at_ws), which is the production controller's signal).
S15 = VWAP-revert (S1.5): bet TOWARD vwap_since_open (so direction = sign of
     -vwap_since_open_bps... if vwap_since_open_bps > 0 the price has been
     above session open VWAP, bet on revert to mean → Down; if < 0, bet Up).

For each fire, compute simulated $1 stake PnL (legacy 2% on profit) and join
to vol/hurst features, then compute WR / dpt by vol regime and Hurst bucket.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

OUT_DIR = "data/v4/canonical/_results"
WORK_DIR = "strategy_lab/vol_hurst_2026_05_26"


def synth_legacy_pnl(direction: np.ndarray, p_up: np.ndarray, p_dn: np.ndarray,
                     fill_up: np.ndarray, fill_dn: np.ndarray,
                     outcome: np.ndarray, stake: float = 1.0,
                     fee: float = 0.02):
    """Return per-fire pnl and won. NaN if not fillable in chosen direction."""
    n = len(direction)
    pnl = np.full(n, np.nan)
    won = np.full(n, False)
    keep = np.zeros(n, dtype=bool)
    # Up bets
    up_mask = (direction == 1) & fill_up & np.isfinite(p_up) & (p_up > 0)
    won_up = (outcome == "Up")
    q_up = np.where(p_up > 0, stake / p_up, 0)
    pnl_up = np.where(won_up, q_up * (1 - p_up) * (1 - fee), -q_up * p_up)
    pnl[up_mask] = pnl_up[up_mask]
    won[up_mask] = won_up[up_mask]
    keep |= up_mask
    # Down bets
    dn_mask = (direction == -1) & fill_dn & np.isfinite(p_dn) & (p_dn > 0)
    won_dn = (outcome == "Down")
    q_dn = np.where(p_dn > 0, stake / p_dn, 0)
    pnl_dn = np.where(won_dn, q_dn * (1 - p_dn) * (1 - fee), -q_dn * p_dn)
    pnl[dn_mask] = pnl_dn[dn_mask]
    won[dn_mask] = won_dn[dn_mask]
    keep |= dn_mask
    return pnl, won, keep


def per_regime(df, label_col="vol_regime", labels=(0, 1, 2), names=("low", "med", "high")):
    rows = []
    rows.append({"bucket": "all", "n": len(df), "wr": df["won"].mean(),
                 "dpt": df["pnl"].mean(), "sum_pnl": df["pnl"].sum()})
    for lbl, nm in zip(labels, names):
        sub = df[df[label_col] == lbl]
        rows.append({"bucket": nm, "n": len(sub),
                     "wr": sub["won"].mean() if len(sub) else np.nan,
                     "dpt": sub["pnl"].mean() if len(sub) else np.nan,
                     "sum_pnl": sub["pnl"].sum() if len(sub) else np.nan})
    return pd.DataFrame(rows)


def per_hurst(df, hurst_col="hurst_300s"):
    rows = []
    rows.append({"bucket": "all", "n": len(df), "wr": df["won"].mean(),
                 "dpt": df["pnl"].mean(), "sum_pnl": df["pnl"].sum()})
    buckets = [
        ("h_lt_04", lambda x: x < 0.4),
        ("h_04_05", lambda x: (x >= 0.4) & (x < 0.5)),
        ("h_05_06", lambda x: (x >= 0.5) & (x < 0.6)),
        ("h_ge_06", lambda x: x >= 0.6),
    ]
    for nm, pred in buckets:
        sub = df[pred(df[hurst_col])]
        rows.append({"bucket": nm, "n": len(sub),
                     "wr": sub["won"].mean() if len(sub) else np.nan,
                     "dpt": sub["pnl"].mean() if len(sub) else np.nan,
                     "sum_pnl": sub["pnl"].sum() if len(sub) else np.nan})
    return pd.DataFrame(rows)


def main():
    print("loading vol/hurst at fire...", flush=True)
    f5 = pd.read_parquet(f"{OUT_DIR}/vol_hurst_at_fire_5m.parquet")
    # Use 5m universe only (the user's S6 / S1.5 nomenclature is 5m).

    out_parts = []
    for asset in ("BTC", "ETH", "SOL"):
        sub = f5[f5["asset"] == asset].copy()
        outcome = sub["outcome"].to_numpy()
        p_up = sub["up_vwap"].to_numpy()
        p_dn = sub["dn_vwap"].to_numpy()
        fill_up = sub["up_fill_ok"].fillna(False).astype(bool).to_numpy()
        fill_dn = sub["dn_fill_ok"].fillna(False).astype(bool).to_numpy()
        # S6 base = momentum continuation on 2m anchor return
        ret2 = sub["ret_2m_at_ws"].to_numpy()
        dir_s6 = np.where(np.isfinite(ret2) & (ret2 > 0), 1,
                  np.where(np.isfinite(ret2) & (ret2 < 0), -1, 0))
        # S1.5 base = VWAP continuation (production uses vwap as trend signal).
        # If vwap_since_open_bps > 0 (price ABOVE session VWAP, uptrend), bet Up.
        vw = sub["vwap_since_open_bps"].to_numpy()
        dir_s15 = np.where(np.isfinite(vw) & (vw > 0), 1,
                   np.where(np.isfinite(vw) & (vw < 0), -1, 0))

        for label, direction in (("s6_base", dir_s6), ("s15_base", dir_s15)):
            pnl, won, keep = synth_legacy_pnl(
                direction, p_up, p_dn, fill_up, fill_dn, outcome
            )
            d = sub.loc[keep].copy()
            d["pnl"] = pnl[keep]
            d["won"] = won[keep].astype(int)
            d["sleeve"] = f"{asset}_{label}"
            out_parts.append(d[[
                "sleeve", "asset", "slug", "fire_us", "pnl", "won",
                "vol_regime", "hurst_100s", "hurst_300s", "hurst_900s",
                "rv_60s", "rv_300s", "rv_3600s",
                "g_vol_low", "g_vol_med", "g_vol_high",
                "g_hurst_trending", "g_hurst_reverting",
                "g_vol_expanding", "g_vol_contracting", "g_rv_with",
            ]])
    panel = pd.concat(out_parts, ignore_index=True)
    panel.to_parquet(f"{WORK_DIR}/base_s6_s15_panel.parquet", index=False)

    rows = []
    for sleeve, sub in panel.groupby("sleeve"):
        r_reg = per_regime(sub)
        r_reg["sleeve"] = sleeve
        r_reg["dim"] = "vol_regime"
        rows.append(r_reg)
        r_h = per_hurst(sub, "hurst_300s")
        r_h["sleeve"] = sleeve
        r_h["dim"] = "hurst_300s"
        rows.append(r_h)
    out = pd.concat(rows, ignore_index=True)
    out.to_csv(f"{WORK_DIR}/base_s6_s15_results.csv", index=False)
    print(out.to_string())


if __name__ == "__main__":
    main()
