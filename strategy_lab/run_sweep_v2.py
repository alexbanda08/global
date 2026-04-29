"""
Run the v2 strategy sweep (with stop-losses + regime filters).
"""
from __future__ import annotations

import itertools
import sys
import time
from pathlib import Path

import pandas as pd

from strategy_lab import engine
from strategy_lab.strategies_v2 import STRATEGIES_V2

OUT_DIR = Path(__file__).resolve().parent / "results"
OUT_DIR.mkdir(exist_ok=True)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TIMEFRAMES = ["1h", "4h", "1d"]   # drop 15m — Round-1 showed low TFs bleed on costs
START = "2018-01-01"
END = "2026-04-01"


def main() -> int:
    rows = []
    total = len(STRATEGIES_V2) * len(SYMBOLS) * len(TIMEFRAMES)
    done = 0
    t0 = time.time()

    for sym, tf in itertools.product(SYMBOLS, TIMEFRAMES):
        try:
            df = engine.load(sym, tf, START, END)
        except FileNotFoundError:
            continue
        if len(df) < 500:
            continue

        for name, fn in STRATEGIES_V2.items():
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
            if done % 6 == 0:
                print(f"  progress {done}/{total}  elapsed {time.time()-t0:.1f}s")

    df_out = pd.DataFrame(rows)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_path = OUT_DIR / f"sweep_v2_{stamp}.csv"
    df_out.to_csv(out_path, index=False)
    print(f"Saved {len(df_out)} rows -> {out_path}")
    print(f"Elapsed: {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
