"""
Run the full strategy × symbol × timeframe sweep.

Output: strategy_lab/results/sweep_<stamp>.csv
"""
from __future__ import annotations

import itertools
import sys
import time
from pathlib import Path

import pandas as pd

from strategy_lab import engine, strategies

OUT_DIR = Path(__file__).resolve().parent / "results"
OUT_DIR.mkdir(exist_ok=True)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TIMEFRAMES = ["15m", "1h", "4h", "1d"]
START = "2018-01-01"
END = "2026-04-01"


def main() -> int:
    rows = []
    total = len(strategies.STRATEGIES) * len(SYMBOLS) * len(TIMEFRAMES)
    done = 0
    t0 = time.time()

    for sym, tf in itertools.product(SYMBOLS, TIMEFRAMES):
        # SOL didn't exist in 2018 — engine.load will simply yield shorter df.
        try:
            df = engine.load(sym, tf, START, END)
        except FileNotFoundError as e:
            print(f"  skip {sym}/{tf}: {e}")
            continue
        if len(df) < 500:
            print(f"  skip {sym}/{tf}: only {len(df)} bars")
            continue

        for name, fn in strategies.STRATEGIES.items():
            try:
                sig = fn(df)
            except Exception as e:
                print(f"  ERR sig {name} {sym}/{tf}: {type(e).__name__}: {e}")
                continue
            try:
                res = engine.run_backtest(
                    df,
                    entries=sig["entries"], exits=sig["exits"],
                    short_entries=sig.get("short_entries"),
                    short_exits=sig.get("short_exits"),
                    label=f"{name}|{sym}|{tf}",
                )
            except Exception as e:
                print(f"  ERR bt  {name} {sym}/{tf}: {type(e).__name__}: {e}")
                continue

            m = res.metrics
            m["strategy"] = name
            m["symbol"]   = sym
            m["tf"]       = tf
            m["bars"]     = len(df)
            rows.append(m)
            done += 1
            if done % 10 == 0:
                print(f"  progress {done}/{total}  elapsed {time.time()-t0:.1f}s")

    df_out = pd.DataFrame(rows)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_path = OUT_DIR / f"sweep_{stamp}.csv"
    df_out.to_csv(out_path, index=False)
    print(f"Saved {len(df_out)} rows → {out_path}")
    print(f"Elapsed: {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
