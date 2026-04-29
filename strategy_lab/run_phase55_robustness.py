"""
Phase 5.5 robustness battery driver.

Runs the 4-test battery (per-year, permutation, bootstrap, walk-forward)
on a curated list of candidate cells. Outputs:
  docs/research/phase5_results/robustness_reports.json
  console-friendly summary
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "strategy_lab"))

import engine                                            # noqa: E402
from regime import classify_regime, REGIME_4H_PRESET    # noqa: E402
from eval.robustness import run_robustness              # noqa: E402

OUTPUT_JSON = REPO / "docs" / "research" / "phase5_results" / "robustness_reports.json"


def _eq_from_result(res, df):
    eq = getattr(res, "equity", None)
    if eq is None and getattr(res, "pf", None) is not None:
        eq = res.pf.value()
    return eq


# ---------------------------------------------------------------------
# Adaptive — C1 via its runner
# ---------------------------------------------------------------------
def c1_runner_on_df(df: pd.DataFrame) -> pd.Series:
    from strategies.adaptive.c1_meta_labeled_donchian import generate_signals as c1_gen
    sig = c1_gen(df)
    cfg = engine.ExecutionConfig(
        mode="limit", fee_schedule="binance_spot",
        limit_valid_bars=3, limit_offset_pct=0.0,
        queue_position_penalty_bps=1.0, max_fill_pct_of_bar_volume=0.2,
        slippage_bps=5.0,
    )
    res = engine.run_backtest(
        df, entries=sig["entries"], exits=sig["exits"],
        sl_stop=sig["_meta"]["atr_pct_suggested_sl"],
        tp_stop=sig["_meta"]["atr_pct_suggested_tp"],
        execution=cfg,
    )
    return _eq_from_result(res, df)


# ---------------------------------------------------------------------
# Legacy gaussian_channel_v2 via importlib
# ---------------------------------------------------------------------
def _load_legacy_fn(module_file: str, fn_name: str):
    import importlib.util as il
    p = REPO / "strategy_lab" / module_file
    spec = il.spec_from_file_location(f"_legacy_{fn_name}", p)
    mod = il.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, fn_name)


def gc_v2_runner_on_df(df: pd.DataFrame) -> pd.Series:
    fn = _load_legacy_fn("strategies_v2.py", "gaussian_channel_v2")
    sig = fn(df)
    if isinstance(sig, tuple):
        sig = {"entries": sig[0], "exits": sig[1]}
    res = engine.run_backtest(
        df, entries=sig["entries"], exits=sig["exits"],
        sl_stop=sig.get("sl_stop"), tsl_stop=sig.get("tsl_stop"),
        tp_stop=sig.get("tp_stop"),
    )
    return _eq_from_result(res, df)


# ---------------------------------------------------------------------
# Matrix
# ---------------------------------------------------------------------
CELLS = [
    # (id, symbol, tf, runner_fn, bars_per_year)
    ("c1_meta_labeled_donchian",  "ETHUSDT", "4h", c1_runner_on_df,   2190.0),
    ("c1_meta_labeled_donchian",  "BTCUSDT", "4h", c1_runner_on_df,   2190.0),
    ("gaussian_channel_v2",       "BTCUSDT", "4h", gc_v2_runner_on_df, 2190.0),
    ("gaussian_channel_v2",       "ETHUSDT", "4h", gc_v2_runner_on_df, 2190.0),
]


def _load_df(symbol: str, tf: str) -> pd.DataFrame:
    return engine.load(symbol, tf, start="2022-01-01", end="2024-12-31")


def main():
    all_reports = []
    for strategy_id, symbol, tf, runner, bpy in CELLS:
        print(f"\n=== {strategy_id}  |  {symbol}  |  {tf} ===")
        df = _load_df(symbol, tf)
        equity = runner(df)
        if equity is None or len(equity) < 100:
            print("  no equity — skipping")
            continue

        rep = run_robustness(
            strategy_id, symbol, tf, equity, runner, df,
            bars_per_year=bpy, n_perm=30, n_bootstrap=1000,
        )
        v = rep.verdict()
        print(f"  tests_passed: {v['tests_passed']}/{v['tests_total']}")
        for k, val in v.items():
            if k in ("tests_passed", "tests_total"):
                continue
            symbol_ = "OK " if val is True else "NO " if val is False else "?  "
            print(f"    [{symbol_}] {k}")
        # per-year headline
        if rep.per_year:
            yrs = sorted(rep.per_year.keys())
            print("  per-year Sharpe:",
                  " ".join(f"{y}:{rep.per_year[y]['sharpe']:+.2f}" for y in yrs))
        # bootstrap headline
        if rep.bootstrap:
            sh = rep.bootstrap.get("sharpe", {})
            cl = rep.bootstrap.get("calmar", {})
            md = rep.bootstrap.get("max_dd", {})
            print(f"  bootstrap CI (95%): Sharpe [{sh.get('ci_lo')}, {sh.get('ci_hi')}]  "
                  f"Calmar [{cl.get('ci_lo')}, {cl.get('ci_hi')}]  "
                  f"MDD [{md.get('ci_lo')}, {md.get('ci_hi')}]")
        if rep.walk_forward:
            wf = rep.walk_forward
            print(f"  walk-forward: efficiency={wf.get('efficiency_ratio')}  "
                  f"pos_folds={wf.get('n_positive_folds')}/{wf.get('n_folds')}  "
                  f"worst_fold_sharpe={wf.get('worst_fold_sharpe')}")
        if rep.permutation:
            p = rep.permutation
            print(f"  permutation: p={p.get('p_value')}  "
                  f"real_sharpe={p.get('real_sharpe')}  null_mean={p.get('null_mean')}  "
                  f"null_99th={p.get('null_99th')}")
        all_reports.append({**asdict(rep), "verdict": v})

    OUTPUT_JSON.write_text(json.dumps(all_reports, indent=2), encoding="utf-8")
    print(f"\nReports JSON: {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
