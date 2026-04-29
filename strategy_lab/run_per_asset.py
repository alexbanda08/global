"""
Per-asset independent sweep.

Each asset starts with its OWN $10,000.  No portfolio mixing.
Strategies tested:  V2 + V3 + V4 families (V1 already shown to underperform).

Grid: 3 symbols x 4 timeframes x N strategies.
Output: strategy_lab/results/per_asset_sweep_<stamp>.csv
"""
from __future__ import annotations

import itertools
import time
from pathlib import Path

import pandas as pd

from strategy_lab import engine
from strategy_lab.strategies_v2 import STRATEGIES_V2
from strategy_lab.strategies_v3 import STRATEGIES_V3
from strategy_lab.strategies_v4 import STRATEGIES_V4

OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)

ALL_STRATS = {**STRATEGIES_V2, **STRATEGIES_V3, **STRATEGIES_V4}

SYMBOLS    = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TIMEFRAMES = ["15m", "1h", "4h", "1d"]
START      = "2018-01-01"
END        = "2026-04-01"
INIT_CASH  = 10_000.0


def main():
    rows = []
    total = len(SYMBOLS) * len(TIMEFRAMES) * len(ALL_STRATS)
    done = 0
    t0 = time.time()

    for sym, tf in itertools.product(SYMBOLS, TIMEFRAMES):
        try:
            df = engine.load(sym, tf, START, END)
        except FileNotFoundError:
            continue
        if len(df) < 500:
            continue

        for name, fn in ALL_STRATS.items():
            try:
                sig = fn(df)
            except Exception as e:
                print(f"  ERR sig {name} {sym}/{tf}: {e}")
                continue
            try:
                res = engine.run_backtest(
                    df,
                    entries=sig["entries"], exits=sig["exits"],
                    short_entries=sig.get("short_entries"),
                    short_exits=sig.get("short_exits"),
                    sl_stop=sig.get("sl_stop"),
                    tsl_stop=sig.get("tsl_stop"),
                    init_cash=INIT_CASH,
                    label=f"{name}|{sym}|{tf}",
                )
            except Exception as e:
                print(f"  ERR bt  {name} {sym}/{tf}: {e}")
                continue

            m = res.metrics
            m["strategy"] = name
            m["symbol"]   = sym
            m["tf"]       = tf
            m["bars"]     = len(df)
            rows.append(m)
            done += 1
            if done % 12 == 0:
                print(f"  {done}/{total}   {time.time()-t0:.1f}s")

    df = pd.DataFrame(rows)
    # Composite: rewards Calmar + Sharpe, penalises very-low-trade counts
    df["composite"] = df["calmar"].fillna(0) * 1.5 + df["sharpe"].fillna(0) * 1.0
    df.loc[df["n_trades"] < 15, "composite"] *= 0.5

    for c in ["cagr","sharpe","sortino","calmar","max_dd","win_rate","profit_factor","bh_return","composite"]:
        df[c] = df[c].round(3)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out = OUT / f"per_asset_sweep_{stamp}.csv"
    df.to_csv(out, index=False)
    print(f"\nSaved {len(df)} rows -> {out}  ({time.time()-t0:.1f}s)")

    # Best per cell
    best_cell = (df.sort_values("composite", ascending=False)
                   .groupby(["symbol", "tf"]).head(1)
                   [["symbol","tf","strategy","cagr","sharpe","calmar",
                     "max_dd","n_trades","win_rate","bh_return","final_equity"]])
    best_cell = best_cell.sort_values(["symbol","tf"])
    print("\n=== BEST PER (SYMBOL, TIMEFRAME) ===")
    print(best_cell.to_string(index=False))
    best_cell.to_csv(OUT / "per_asset_best_by_cell.csv", index=False)

    # Best strategy per asset (all timeframes considered)
    best_asset = (df.sort_values("composite", ascending=False)
                    .groupby("symbol").head(3)
                    [["symbol","tf","strategy","cagr","sharpe","calmar",
                      "max_dd","n_trades","bh_return","final_equity","composite"]])
    best_asset = best_asset.sort_values(["symbol","composite"], ascending=[True, False])
    print("\n=== TOP 3 PER ASSET (composite) ===")
    print(best_asset.to_string(index=False))
    best_asset.to_csv(OUT / "per_asset_top3.csv", index=False)


if __name__ == "__main__":
    main()
