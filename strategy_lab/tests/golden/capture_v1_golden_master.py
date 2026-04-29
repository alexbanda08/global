"""
Capture the pre-uplift v1 engine output as a golden master.

Runs 5 canonical scenarios end-to-end through `engine.run_backtest`,
pickles (metrics, equity curve) for each, and prints a per-scenario
hash so the before/after diff is visible in logs.

Usage (always from repo root):
    & "D:\\kronos-venv\\Scripts\\python.exe" strategy_lab/tests/golden/capture_v1_golden_master.py

Re-run AFTER engine uplift with the same command. The companion script
`check_v1_golden_master.py` asserts every scenario matches within 1e-9
on the equity curve and bit-exact on the metrics dict.
"""
from __future__ import annotations

import hashlib
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Make `import engine` work regardless of where the script is launched.
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "strategy_lab"))

import engine  # noqa: E402

GOLDEN_DIR = Path(__file__).resolve().parent
GOLDEN_FILE = GOLDEN_DIR / "v1_equity_curves.pkl"


def _build_sma_signals(df: pd.DataFrame, fast: int = 20, slow: int = 50):
    f = df["close"].rolling(fast).mean()
    s = df["close"].rolling(slow).mean()
    long_entries = (f > s) & (f.shift(1) <= s.shift(1))
    long_exits = (f < s) & (f.shift(1) >= s.shift(1))
    short_entries = long_exits.copy()
    short_exits = long_entries.copy()
    return long_entries, long_exits, short_entries, short_exits


def _eq_hash(eq: pd.Series) -> str:
    arr = eq.to_numpy(dtype=np.float64, copy=False)
    return hashlib.sha256(arr.tobytes()).hexdigest()[:16]


def _run_scenarios() -> dict:
    df = engine.load("BTCUSDT", "1d", "2022-01-01", "2024-01-01")
    le, lx, se, sx = _build_sma_signals(df)

    scenarios = {
        "sma_cross_no_stops": dict(
            entries=le, exits=lx, label="sma_cross_no_stops",
        ),
        "sma_cross_sl_only": dict(
            entries=le, exits=lx, sl_stop=0.05, label="sma_cross_sl_only",
        ),
        "sma_cross_tsl_only": dict(
            entries=le, exits=lx, tsl_stop=0.05, label="sma_cross_tsl_only",
        ),
        "sma_cross_tp_only": dict(
            entries=le, exits=lx, tp_stop=0.10, label="sma_cross_tp_only",
        ),
        "sma_cross_both_sides": dict(
            entries=le, exits=lx, short_entries=se, short_exits=sx,
            label="sma_cross_both_sides",
        ),
    }

    out = {}
    for name, kwargs in scenarios.items():
        res = engine.run_backtest(df, **kwargs)
        eq = res.pf.value()
        out[name] = {
            "metrics": dict(res.metrics),
            "equity": eq.copy(),
            "equity_hash": _eq_hash(eq),
            "n_bars": len(eq),
        }
        print(f"  {name:28s} hash={out[name]['equity_hash']} "
              f"final={eq.iloc[-1]:.4f} sharpe={res.metrics['sharpe']:.6f} "
              f"trades={res.metrics['n_trades']}")
    return out


def main() -> int:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

    print("Capturing v1 golden master...")
    print(f"  engine module: {engine.__file__}")
    print(f"  output file:   {GOLDEN_FILE}")
    print()

    snapshot = _run_scenarios()
    snapshot["_meta"] = {
        "numpy":  np.__version__,
        "pandas": pd.__version__,
        "engine_fee":  engine.FEE,
        "engine_slip": engine.SLIP,
    }

    with open(GOLDEN_FILE, "wb") as f:
        pickle.dump(snapshot, f, protocol=pickle.HIGHEST_PROTOCOL)

    print()
    print(f"Golden master written: {GOLDEN_FILE}")
    print("Re-run AFTER engine uplift and use check_v1_golden_master.py to diff.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
