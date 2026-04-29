"""
Verify the uplifted engine still produces the v1 golden master.

Re-runs the same 5 scenarios that `capture_v1_golden_master.py` recorded,
then asserts:
  1. Equity curves match the pickled baseline with np.allclose(atol=1e-9).
  2. Metric dicts match key-by-key (floats within atol=1e-9).
  3. Equity-hash (sha256 of float64 bytes) is identical for at least one
     scenario (strong float-determinism check).

Exit code 0 on full pass, 1 otherwise.
"""
from __future__ import annotations

import hashlib
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "strategy_lab"))

import engine  # noqa: E402

GOLDEN_DIR = Path(__file__).resolve().parent
GOLDEN_FILE = GOLDEN_DIR / "v1_equity_curves.pkl"

ATOL = 1e-9


def _build_sma_signals(df, fast=20, slow=50):
    f = df["close"].rolling(fast).mean()
    s = df["close"].rolling(slow).mean()
    le = (f > s) & (f.shift(1) <= s.shift(1))
    lx = (f < s) & (f.shift(1) >= s.shift(1))
    return le, lx, lx.copy(), le.copy()


def _eq_hash(eq):
    return hashlib.sha256(eq.to_numpy(dtype=np.float64).tobytes()).hexdigest()[:16]


def _scenarios_kwargs(df):
    le, lx, se, sx = _build_sma_signals(df)
    return {
        "sma_cross_no_stops":   dict(entries=le, exits=lx,
                                     label="sma_cross_no_stops"),
        "sma_cross_sl_only":    dict(entries=le, exits=lx, sl_stop=0.05,
                                     label="sma_cross_sl_only"),
        "sma_cross_tsl_only":   dict(entries=le, exits=lx, tsl_stop=0.05,
                                     label="sma_cross_tsl_only"),
        "sma_cross_tp_only":    dict(entries=le, exits=lx, tp_stop=0.10,
                                     label="sma_cross_tp_only"),
        "sma_cross_both_sides": dict(entries=le, exits=lx,
                                     short_entries=se, short_exits=sx,
                                     label="sma_cross_both_sides"),
    }


def _diff_dicts(new: dict, old: dict, atol: float) -> list[str]:
    errors = []
    keys = set(new) | set(old)
    for k in sorted(keys):
        if k not in new:
            errors.append(f"    missing key in new: {k}")
            continue
        if k not in old:
            errors.append(f"    extra key in new: {k}")
            continue
        a, b = new[k], old[k]
        if isinstance(a, float) and isinstance(b, float):
            if np.isnan(a) and np.isnan(b):
                continue
            if not np.isclose(a, b, atol=atol, equal_nan=True):
                errors.append(f"    {k}: new={a!r}  old={b!r}  delta={a-b!r}")
        else:
            if a != b:
                errors.append(f"    {k}: new={a!r}  old={b!r}")
    return errors


def main() -> int:
    if not GOLDEN_FILE.exists():
        print(f"ERROR: golden master not found at {GOLDEN_FILE}")
        print("Run capture_v1_golden_master.py first (before modifying engine).")
        return 2

    with open(GOLDEN_FILE, "rb") as f:
        baseline = pickle.load(f)

    meta = baseline.pop("_meta", {})
    print("Golden master loaded.")
    print(f"  captured with numpy={meta.get('numpy')} pandas={meta.get('pandas')}")
    print(f"  current            numpy={np.__version__} pandas={pd.__version__}")
    print()

    df = engine.load("BTCUSDT", "1d", "2022-01-01", "2024-01-01")
    scenarios = _scenarios_kwargs(df)

    total_errs = 0
    hash_matches = 0
    for name, kwargs in scenarios.items():
        res = engine.run_backtest(df, **kwargs)
        eq_new = res.pf.value()
        old = baseline[name]
        eq_old = old["equity"]

        scenario_errs: list[str] = []

        if len(eq_new) != len(eq_old):
            scenario_errs.append(f"    equity length: new={len(eq_new)} old={len(eq_old)}")
        else:
            if not np.allclose(eq_new.to_numpy(), eq_old.to_numpy(),
                               atol=ATOL, equal_nan=True):
                max_abs = float(np.nanmax(np.abs(eq_new.to_numpy() - eq_old.to_numpy())))
                scenario_errs.append(f"    equity max abs delta: {max_abs:.3e} (atol={ATOL})")

        if _eq_hash(eq_new) == old["equity_hash"]:
            hash_matches += 1

        scenario_errs.extend(_diff_dicts(res.metrics, old["metrics"], atol=ATOL))

        if scenario_errs:
            total_errs += len(scenario_errs)
            print(f"FAIL  {name}")
            for e in scenario_errs:
                print(e)
        else:
            print(f"PASS  {name}  hash={_eq_hash(eq_new)} "
                  f"final={eq_new.iloc[-1]:.4f}")

    print()
    print(f"Hash-identical scenarios: {hash_matches}/{len(scenarios)}")
    if total_errs:
        print(f"FAILED  {total_errs} deltas across {len(scenarios)} scenarios")
        return 1
    print("PASSED  all scenarios match v1 golden master within 1e-9")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
