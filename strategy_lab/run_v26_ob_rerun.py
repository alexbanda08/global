"""
V26 OB rerun with the look-ahead fix applied.
Re-sweep and re-audit only the Order_Block family across all coins.
"""
from __future__ import annotations
import sys, pickle, warnings, time
warnings.filterwarnings("ignore")
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v26_priceaction import (
    _load, sweep_family, scaled,
)

SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT",
        "AVAXUSDT", "DOGEUSDT", "INJUSDT", "SUIUSDT", "TONUSDT"]

RES = Path(__file__).resolve().parent / "results" / "v26"
RES.mkdir(exist_ok=True)

def main():
    t0 = time.time()
    results = {}
    for sym in SYMS:
        print(f"\n=== {sym} ORDER_BLOCK (fixed) ===", flush=True)
        w = sweep_family(sym, "ORDER_BLOCK")
        if w is None:
            print("  NO VIABLE CONFIG", flush=True)
            continue
        r = w["metrics"]
        print(f"  {w['tf']}  Order_Block  CAGR {r['cagr_net']*100:+6.1f}%  Sh {r['sharpe']:+.2f}  "
              f"DD {r['dd']*100:+6.1f}%  n={r['n']:5d}  p={w['params']}", flush=True)
        results[f"{sym}_OB_FIXED"] = w

    with open(RES / "v26_ob_fixed_results.pkl", "wb") as f:
        light = {}
        for k, v in results.items():
            light[k] = {kk: vv for kk, vv in v.items() if kk not in ("trades",)}
            eq = v.get("eq")
            if eq is not None:
                light[k]["eq_index"] = list(eq.index)
                light[k]["eq_values"] = eq.values.tolist()
        pickle.dump(light, f)
    print(f"\nDone in {time.time()-t0:.0f}s. Winners: {len(results)}")


if __name__ == "__main__":
    main()
