"""
Full 5-test robustness battery on volume_breakout ETH 4h — the single
cell with positive Sharpe in every year 2022/2023/2024.

Tests:
  1. Per-year consistency
  2. Parameter plateau  (NEW — wasn't in the prior run)
  3. Null permutation
  4. Block bootstrap
  5. Walk-forward efficiency

Outputs:
  docs/research/phase5_results/vb_eth_full_battery.json
"""
from __future__ import annotations

import importlib.util as _il
import inspect
import json
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "strategy_lab"))

import engine                                       # noqa: E402
from eval.robustness import run_robustness          # noqa: E402
from eval.plateau import parameter_plateau, _numeric_params  # noqa: E402

OUT_JSON = REPO / "docs" / "research" / "phase5_results" / "vb_eth_full_battery.json"


def _load_legacy():
    spec = _il.spec_from_file_location(
        "_legacy", REPO / "strategy_lab" / "strategies.py",
    )
    mod = _il.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    legacy = _load_legacy()
    fn = getattr(legacy, "volume_breakout", None)
    if fn is None:
        print("volume_breakout not found"); return 1

    df = engine.load("ETHUSDT", "4h", start="2022-01-01", end="2024-12-31")
    numeric = _numeric_params(fn)
    print(f"Numeric params discovered: {numeric}")

    def _runner(overrides: dict) -> pd.Series:
        out = fn(df, **overrides)
        if isinstance(out, tuple) and len(out) == 2:
            out = {"entries": out[0], "exits": out[1]}
        res = engine.run_backtest(
            df, entries=out["entries"], exits=out["exits"],
            sl_stop=out.get("sl_stop"), tsl_stop=out.get("tsl_stop"),
            tp_stop=out.get("tp_stop"),
        )
        return res.pf.value()

    # Generic runner(df) for permutation — fresh df per shuffle
    def _perm_runner(df_perm: pd.DataFrame) -> pd.Series:
        out = fn(df_perm)
        if isinstance(out, tuple) and len(out) == 2:
            out = {"entries": out[0], "exits": out[1]}
        res = engine.run_backtest(
            df_perm, entries=out["entries"], exits=out["exits"],
            sl_stop=out.get("sl_stop"), tsl_stop=out.get("tsl_stop"),
            tp_stop=out.get("tp_stop"),
        )
        return res.pf.value()

    print("\n=== Running baseline ===")
    baseline_eq = _runner({})
    print(f"  equity bars: {len(baseline_eq)}")

    print("\n=== Test 1, 3, 4, 5 — 4-test battery ===")
    rep = run_robustness(
        "volume_breakout", "ETHUSDT", "4h",
        baseline_eq, _perm_runner, df,
        bars_per_year=2190.0, n_perm=40, n_bootstrap=1000,
    )
    v = rep.verdict()
    print(f"  tests_passed: {v['tests_passed']}/{v['tests_total']}")

    print("\n=== Test 2 — parameter plateau sweep ===")
    plateau = parameter_plateau(fn, _runner, bars_per_year=2190.0)
    print(f"  worst 25pct Sharpe drop: {plateau['worst_25pct_sharpe_drop']:.1%}")
    print(f"  worst 50pct Sharpe drop: {plateau['worst_50pct_sharpe_drop']:.1%}")
    print(f"  cliff detected: {plateau['cliff_detected']}")
    print(f"  worst_param: {plateau['worst_param']}")
    print(f"  plateau test passed: {plateau['passed']}")
    for pname, pdata in plateau["params"].items():
        base_v = pdata["baseline_value"]
        row = [f"{pname}(baseline={base_v})"]
        for pct in (-0.5, -0.25, 0.25, 0.5):
            s = pdata["sweep"].get(pct, {})
            sh = s.get("sharpe", "ERR")
            row.append(f"{pct:+.0%}:{sh}")
        print("   ", " | ".join(row))

    out = {
        "strategy": "volume_breakout",
        "symbol": "ETHUSDT", "tf": "4h",
        "four_test": {**asdict(rep), "verdict": v},
        "plateau": plateau,
        "full_battery_tests_passed": (
            v["tests_passed"] + (1 if plateau["passed"] else 0)
        ),
        "full_battery_tests_total": v["tests_total"] + 1,
    }
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nFull 5-test battery: "
          f"{out['full_battery_tests_passed']}/{out['full_battery_tests_total']}")
    print(f"Wrote {OUT_JSON}")


if __name__ == "__main__":
    raise SystemExit(main())
