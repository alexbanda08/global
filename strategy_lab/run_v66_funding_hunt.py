"""
V66 — Funding-Z fade hunt across 5 HL coins x small param grid.

Mission target: clear 50% WR AND 60% CAGR on at least one coin/param combo,
with OOS-gate (Sharpe retention >= 0.5x IS).

This is a *pre-registered* sweep — bounded grid, single signal family, no
optimization-target loop. We hunt 5 coins * 9 (z_long, z_short, atr_stretch)
combos = 45 cells. Each cell evaluated on:
  IS  : 2023-05-12 -> 2024-12-31  (initial training window)
  OOS : 2025-01-01 -> 2026-04-25  (held out)

Decision gate (per cell): IS_CAGR >= 60% AND IS_WR >= 50% AND OOS_Sharpe >=
0.5 * IS_Sharpe AND OOS_CAGR > 0.

Heuristic learned from V25/V27: when a sweep produces 'spectacular results'
on every cell, that's a structural bug, not a real edge. We expect 0-3 cells
to clear, not 30+.

Outputs:
  docs/research/phase5_results/v66_funding_hunt_grid.csv
  docs/research/phase5_results/v66_funding_hunt_winners.json
"""
from __future__ import annotations
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "strategy_lab"))

from strategy_lab.util.hl_data import load_hl, funding_per_4h_bar
from strategy_lab.eval.perps_simulator_funding import simulate_with_funding
from strategy_lab.strategies.funding_signals import sig_funding_z_fade

OUT = REPO / "docs" / "research" / "phase5_results"
OUT.mkdir(parents=True, exist_ok=True)
BPY = 365.25 * 6

START = "2023-05-12"
IS_END = "2024-12-31"
OOS_START = "2025-01-01"
END = "2026-04-25"

COINS = ["BTC", "ETH", "SOL", "AVAX", "LINK"]

# Pre-registered grid (small, single-family)
GRID = [
    # (z_long, z_short, atr_stretch)
    (-1.5, +1.5, 1.5),   # baseline
    (-2.0, +2.0, 1.5),   # tighter z
    (-2.5, +2.5, 1.5),   # very tight z (rare entries)
    (-1.5, +1.5, 1.0),   # looser ATR confluence
    (-1.5, +1.5, 2.0),   # tighter ATR confluence
    (-2.0, +2.0, 1.0),
    (-2.0, +2.0, 2.0),
    (-1.0, +1.0, 1.5),   # loose z (more trades)
    (-1.0, +1.0, 1.0),   # loosest combo
]

# Exit profile (canonical for 4h, mirrors V52 sleeves)
TP_ATR = 6.0
SL_ATR = 2.0
TRAIL_ATR = 4.0
MAX_HOLD = 24  # 24 * 4h = 4 days


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def metrics(eq: pd.Series, trades_df: pd.DataFrame | None) -> dict:
    if eq is None or len(eq) < 10:
        return {"sharpe": 0, "cagr": 0, "mdd": 0, "calmar": 0, "wr": 0, "n_trades": 0}
    r = eq.pct_change().dropna()
    sd = float(r.std())
    sh = (float(r.mean()) / sd) * np.sqrt(BPY) if sd > 0 else 0.0
    pk = eq.cummax()
    mdd = float((eq / pk - 1).min())
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 1e-6)) - 1
    cal = float(cagr) / abs(mdd) if mdd != 0 else 0.0

    if trades_df is not None and len(trades_df) > 0 and "pnl" in trades_df.columns:
        wr = 100.0 * (trades_df["pnl"] > 0).mean()
        n_trades = int(len(trades_df))
    else:
        wr = float("nan")
        n_trades = 0

    return {
        "sharpe": round(sh, 3),
        "cagr": round(float(cagr), 4),
        "mdd": round(mdd, 4),
        "calmar": round(cal, 3),
        "wr": round(float(wr), 2) if wr == wr else float("nan"),
        "n_trades": n_trades,
    }


def trades_to_df(trades: list, df_index: pd.DatetimeIndex) -> pd.DataFrame:
    """Convert simulator trades list (list of dicts) to DataFrame with
    pnl column and entry_time derived from entry_idx."""
    if not trades:
        return pd.DataFrame(columns=["pnl", "entry_time"])
    rows = []
    for t in trades:
        rows.append({
            "pnl": float(t["ret"]),
            "side": int(t["side"]),
            "entry_time": df_index[int(t["entry_idx"])] if 0 <= int(t["entry_idx"]) < len(df_index) else pd.NaT,
            "reason": t.get("reason", ""),
            "bars": int(t.get("bars", 0)),
        })
    return pd.DataFrame(rows)


def split_eq(eq: pd.Series, trades_df: pd.DataFrame, is_end: str, oos_start: str):
    is_eq = eq[:is_end]
    oos_eq = eq[oos_start:]
    if trades_df is None or len(trades_df) == 0:
        return is_eq, oos_eq, None, None
    et = trades_df["entry_time"]
    # Match tz of trade timestamps (HL data is tz-aware UTC)
    if hasattr(et.dtype, "tz") and et.dtype.tz is not None:
        is_cut = pd.Timestamp(is_end, tz=et.dtype.tz)
        oos_cut = pd.Timestamp(oos_start, tz=et.dtype.tz)
    else:
        is_cut = pd.Timestamp(is_end)
        oos_cut = pd.Timestamp(oos_start)
    is_tr = trades_df[et <= is_cut]
    oos_tr = trades_df[et >= oos_cut]
    return is_eq, oos_eq, is_tr, oos_tr


# ---------------------------------------------------------------------------
# One cell
# ---------------------------------------------------------------------------

def eval_cell(coin: str, z_long: float, z_short: float, atr_stretch: float) -> dict:
    df = load_hl(coin, "4h", start=START, end=END)
    fund = funding_per_4h_bar(coin, df.index)

    long_entries, short_entries = sig_funding_z_fade(
        df, fund, z_window=180, z_long=z_long, z_short=z_short,
        require_atr_stretch=True, atr_window=14, atr_stretch=atr_stretch,
    )

    n_long = int(long_entries.sum())
    n_short = int(short_entries.sum())

    if n_long + n_short < 10:
        return {
            "coin": coin, "z_long": z_long, "z_short": z_short, "atr_stretch": atr_stretch,
            "n_signals": n_long + n_short, "verdict": "too_few_signals",
            "is_sharpe": 0, "is_cagr": 0, "is_wr": 0, "is_mdd": 0,
            "oos_sharpe": 0, "oos_cagr": 0, "oos_wr": 0, "oos_mdd": 0,
        }

    trades_list, eq = simulate_with_funding(
        df, long_entries, short_entries, fund,
        tp_atr=TP_ATR, sl_atr=SL_ATR, trail_atr=TRAIL_ATR, max_hold=MAX_HOLD,
    )
    trades_df = trades_to_df(trades_list, df.index)

    is_eq, oos_eq, is_tr, oos_tr = split_eq(eq, trades_df, IS_END, OOS_START)

    is_m = metrics(is_eq, is_tr)
    oos_m = metrics(oos_eq, oos_tr)

    # Pass criteria
    is_pass = is_m["cagr"] >= 0.60 and (is_m["wr"] != is_m["wr"] or is_m["wr"] >= 50.0)
    sh_retention_ok = (is_m["sharpe"] <= 0) or (oos_m["sharpe"] >= 0.5 * is_m["sharpe"])
    oos_pass = oos_m["cagr"] > 0 and sh_retention_ok
    verdict = "PROMOTE" if (is_pass and oos_pass) else \
              ("IS_only" if is_pass else
               ("OOS_decent" if oos_m["cagr"] > 0.30 else "fail"))

    return {
        "coin": coin, "z_long": z_long, "z_short": z_short, "atr_stretch": atr_stretch,
        "n_signals": n_long + n_short,
        "n_long": n_long, "n_short": n_short,
        "is_sharpe": is_m["sharpe"], "is_cagr": is_m["cagr"],
        "is_mdd": is_m["mdd"], "is_wr": is_m["wr"], "is_n_trades": is_m["n_trades"],
        "oos_sharpe": oos_m["sharpe"], "oos_cagr": oos_m["cagr"],
        "oos_mdd": oos_m["mdd"], "oos_wr": oos_m["wr"], "oos_n_trades": oos_m["n_trades"],
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    t0 = time.time()
    print("=" * 72)
    print("V66: Funding-Z fade hunt")
    print(f"Coins: {COINS}")
    print(f"Grid cells: {len(GRID)}")
    print(f"IS:  {START} -> {IS_END}")
    print(f"OOS: {OOS_START} -> {END}")
    print(f"Target: IS_CAGR>=60% AND IS_WR>=50% AND OOS_Sh>=0.5*IS_Sh AND OOS_CAGR>0")
    print("=" * 72)

    rows = []
    for coin in COINS:
        for z_long, z_short, atr_s in GRID:
            try:
                r = eval_cell(coin, z_long, z_short, atr_s)
            except Exception as e:
                r = {"coin": coin, "z_long": z_long, "z_short": z_short,
                     "atr_stretch": atr_s, "error": str(e)[:120],
                     "verdict": "error"}
            print(f"  {coin:5s} z=({z_long:+.1f},{z_short:+.1f}) atr={atr_s:.1f} "
                  f"-> {r.get('verdict'):12s} "
                  f"IS=Sh{r.get('is_sharpe',0):.2f}/CAGR{100*r.get('is_cagr',0):+.1f}%/WR{r.get('is_wr',0):.0f}% "
                  f"OOS=Sh{r.get('oos_sharpe',0):.2f}/CAGR{100*r.get('oos_cagr',0):+.1f}%")
            rows.append(r)

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "v66_funding_hunt_grid.csv", index=False)

    promo = df[df["verdict"] == "PROMOTE"]
    is_only = df[df["verdict"] == "IS_only"]
    decent = df[df["verdict"] == "OOS_decent"]

    print()
    print(f"PROMOTE (full pass): {len(promo)} cells")
    if len(promo):
        print(promo[["coin","z_long","z_short","atr_stretch","is_cagr","is_wr","oos_sharpe","oos_cagr"]].to_string())
    print(f"IS_only (overfit risk):    {len(is_only)} cells")
    print(f"OOS_decent (>30% CAGR):    {len(decent)} cells")

    out = {
        "elapsed_s": round(time.time() - t0, 1),
        "n_cells": len(df),
        "n_promote": int(len(promo)),
        "n_is_only": int(len(is_only)),
        "n_oos_decent": int(len(decent)),
        "promoted": promo.to_dict("records"),
        "oos_decent": decent.to_dict("records"),
    }
    (OUT / "v66_funding_hunt_winners.json").write_text(json.dumps(out, indent=2, default=str))
    print(f"\nElapsed: {out['elapsed_s']}s")
    print(f"Wrote {OUT/'v66_funding_hunt_grid.csv'} and {OUT/'v66_funding_hunt_winners.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
