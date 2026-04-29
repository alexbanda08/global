"""
Honest walk-forward:
  * IS (In-Sample):       2018-01-01 -> 2022-12-31
  * OOS (Out-of-Sample):  2023-01-01 -> 2026-04-01

Step 1: Run the parameter grid ON IS ONLY. Pick best params (by Calmar).
Step 2: Apply those params to OOS data. Report both IS and OOS metrics side by side.

If OOS Calmar / Sharpe degrade by <50% from IS, the strategy is robust.
"""
from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
import pandas as pd

from strategy_lab import engine
from strategy_lab.strategies_v2 import volume_breakout_v2

OUT = Path(__file__).resolve().parent / "results"

ALLOC = {"BTCUSDT": 0.60, "ETHUSDT": 0.25, "SOLUSDT": 0.15}
SYMS  = list(ALLOC.keys())
TF    = "4h"
IS_START, IS_END  = "2018-01-01", "2023-01-01"
OOS_START, OOS_END = "2023-01-01", "2026-04-01"


def portfolio_run(params: dict, start: str, end: str) -> dict:
    sub_eqs = []
    for sym in SYMS:
        df = engine.load(sym, TF, start, end)
        sig = volume_breakout_v2(df, **params)
        init = ALLOC[sym] * engine.TOTAL_CAPITAL
        res = engine.run_backtest(
            df,
            entries=sig["entries"], exits=sig["exits"],
            sl_stop=sig.get("sl_stop"), tsl_stop=sig.get("tsl_stop"),
            init_cash=init, label=sym,
        )
        sub_eqs.append(res.pf.value())
    port = pd.concat(sub_eqs, axis=1).ffill().fillna(method="bfill").sum(axis=1)
    return engine.portfolio_metrics(port)


def main():
    grid = list(itertools.product(
        [15, 20, 25, 30],   # don_len
        [1.3, 1.5, 1.8],    # vol_mult
        [150, 200, 250],    # regime_len
        [2.5, 3.5, 4.5],    # tsl_atr
    ))

    # ---------------- IS phase ----------------
    print(f"=== IS grid {IS_START} -> {IS_END} ({len(grid)} combos) ===")
    is_rows = []
    for don_len, vol_mult, regime_len, tsl_atr in grid:
        params = dict(don_len=don_len, vol_mult=vol_mult,
                      regime_len=regime_len, tsl_atr=tsl_atr)
        m = portfolio_run(params, IS_START, IS_END)
        is_rows.append({**params, **{k: round(v, 3) for k, v in m.items()}})
    is_df = pd.DataFrame(is_rows).sort_values("calmar", ascending=False)
    is_df.to_csv(OUT / "WF_is_grid.csv", index=False)

    best = is_df.iloc[0]
    best_params = dict(don_len=int(best.don_len),
                       vol_mult=float(best.vol_mult),
                       regime_len=int(best.regime_len),
                       tsl_atr=float(best.tsl_atr))
    print(f"\nBEST IS params: {best_params}")
    print(f"  IS -> CAGR={best.cagr:.2%}  Sharpe={best.sharpe:.2f}  "
          f"DD={best.max_dd:.2%}  Calmar={best.calmar:.2f}  Final=${best.final:,.0f}")

    # ---------------- OOS phase ----------------
    print(f"\n=== OOS test {OOS_START} -> {OOS_END} (params frozen) ===")
    oos = portfolio_run(best_params, OOS_START, OOS_END)
    print(f"  OOS -> CAGR={oos['cagr']:.2%}  Sharpe={oos['sharpe']:.2f}  "
          f"DD={oos['max_dd']:.2%}  Calmar={oos['calmar']:.2f}  "
          f"Final=${oos['final']:,.0f}")

    # ---------------- Full period with best params ----------------
    print(f"\n=== FULL ({IS_START} -> {OOS_END}) params frozen ===")
    full = portfolio_run(best_params, IS_START, OOS_END)
    print(f"  CAGR={full['cagr']:.2%}  Sharpe={full['sharpe']:.2f}  "
          f"DD={full['max_dd']:.2%}  Calmar={full['calmar']:.2f}  "
          f"Final=${full['final']:,.0f}")

    # ---------------- Degradation analysis ----------------
    print("\n=== DEGRADATION IS -> OOS ===")
    print(f"  Sharpe degradation: {(oos['sharpe'] / max(best.sharpe, 1e-6) - 1) * 100:+.1f}%")
    print(f"  Calmar degradation: {(oos['calmar'] / max(best.calmar, 1e-6) - 1) * 100:+.1f}%")

    import json
    (OUT / "WF_summary.json").write_text(json.dumps({
        "best_params": best_params,
        "IS": {k: (float(v) if isinstance(v, (np.floating, np.integer)) else v) for k, v in best.to_dict().items()},
        "OOS": oos,
        "FULL": full,
    }, default=str, indent=2))


if __name__ == "__main__":
    main()
