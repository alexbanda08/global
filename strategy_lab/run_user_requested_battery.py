"""
Focused battery on the user's requested cells (2026-04-24):

    SOL  BBBreak_LS            -> sig_bbbreak  (run_v38b_smc_mixes.py)
    SUI  BBBreak_LS            -> NO DATA (SUI not in 10-symbol universe)
    DOGE TTM_Squeeze_Pop       -> sig_ttm_squeeze (run_v30_creative.py)
    SOL  SuperTrend_Flip       -> sig_supertrend_flip (run_v30_creative.py)
    DOGE HTF_Donchian          -> sig_htf_donchian_ls (run_v34_expand.py)
    TON  BBBreak_LS            -> NO DATA (TON not in 10-symbol universe)
    V24_MF_1x                  -> portfolio config, not a bare signal fn (SKIP)
    _5SLEEVE_EQW               -> portfolio config, not a bare signal fn (SKIP)
    ETH  CCI_Extreme_Rev @ 4h  -> sig_cci_extreme (run_v30_creative.py)

For each resolvable cell: Phase 5 score_run metrics + 4-test robustness
+ parameter plateau sweep. Output:
  docs/research/phase5_results/user_requested_battery.json
  stdout summary
"""
from __future__ import annotations

import contextlib
import importlib.util as _il
import inspect
import io
import json
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "strategy_lab"))

import engine                                                  # noqa: E402
from regime import classify_regime, REGIME_4H_PRESET           # noqa: E402
from eval.robustness import run_robustness                     # noqa: E402
from eval.plateau import parameter_plateau                     # noqa: E402
from run_phase5_matrix import score_run                        # noqa: E402


OUT = REPO / "docs" / "research" / "phase5_results" / "user_requested_battery.json"


AVAILABLE_SYMBOLS = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT",
                     "AVAXUSDT", "BNBUSDT", "DOGEUSDT", "LINKUSDT", "XRPUSDT"}


# (label, module_file, fn_name, symbol, tf)
CELLS = [
    ("SOL_BBBreak_LS",         "run_v38b_smc_mixes.py",   "sig_bbbreak",
     "SOLUSDT", "4h"),
    ("DOGE_TTM_Squeeze_Pop",   "run_v30_creative.py",     "sig_ttm_squeeze",
     "DOGEUSDT", "4h"),
    ("SOL_SuperTrend_Flip",    "run_v30_creative.py",     "sig_supertrend_flip",
     "SOLUSDT", "4h"),
    ("DOGE_HTF_Donchian",      "run_v34_expand.py",       "sig_htf_donchian_ls",
     "DOGEUSDT", "4h"),
    ("ETH_CCI_Extreme_Rev",    "run_v30_creative.py",     "sig_cci_extreme",
     "ETHUSDT", "4h"),
]

UNAVAILABLE = [
    ("SUI_BBBreak_LS",    "SUI not in 10-symbol Binance-parquet universe"),
    ("TON_BBBreak_LS",    "TON not in 10-symbol Binance-parquet universe"),
    ("V24_MF_1x",         "portfolio-config label, not a bare signal fn"),
    ("_5SLEEVE_EQW",      "portfolio-combination label, not a bare signal fn"),
]


def _load_mod(fname: str):
    p = REPO / "strategy_lab" / fname
    spec = _il.spec_from_file_location(f"_uq_{p.stem}", p)
    mod = _il.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        spec.loader.exec_module(mod)
    return mod


def _signal_to_dict(out):
    if isinstance(out, tuple) and len(out) == 2:
        return {"entries": out[0], "exits": out[1]}
    return out


def _run_cell(label, fname, fn_name, symbol, tf):
    if symbol not in AVAILABLE_SYMBOLS:
        return {"label": label, "error": f"{symbol} unavailable"}
    mod = _load_mod(fname)
    fn = getattr(mod, fn_name, None)
    if fn is None:
        return {"label": label, "error": f"{fn_name} not found in {fname}"}

    df = engine.load(symbol, tf, start="2022-01-01", end="2024-12-31")

    def runner(overrides):
        sig = _signal_to_dict(fn(df, **overrides))
        res = engine.run_backtest(
            df, entries=sig["entries"], exits=sig["exits"],
            sl_stop=sig.get("sl_stop"), tsl_stop=sig.get("tsl_stop"),
            tp_stop=sig.get("tp_stop"),
        )
        return res.pf.value()

    def perm_runner(df_perm):
        sig = _signal_to_dict(fn(df_perm))
        res = engine.run_backtest(
            df_perm, entries=sig["entries"], exits=sig["exits"],
            sl_stop=sig.get("sl_stop"), tsl_stop=sig.get("tsl_stop"),
            tp_stop=sig.get("tp_stop"),
        )
        return res.pf.value()

    # Baseline backtest + phase-5 metrics
    try:
        sig = _signal_to_dict(fn(df))
        res = engine.run_backtest(
            df, entries=sig["entries"], exits=sig["exits"],
            sl_stop=sig.get("sl_stop"), tsl_stop=sig.get("tsl_stop"),
            tp_stop=sig.get("tp_stop"),
        )
    except Exception as e:
        return {"label": label, "error": f"baseline: {type(e).__name__}: {e}"}

    regime_df = classify_regime(df, config=REGIME_4H_PRESET)
    row = score_run(label, symbol, tf, df, res, regime_df, n_trials_for_dsr=10)

    equity = res.pf.value()
    # 4-test robustness
    rep = run_robustness(
        label, symbol, tf, equity, perm_runner, df,
        bars_per_year=2190.0, n_perm=30, n_bootstrap=500,
    )
    v4 = rep.verdict()

    # Plateau
    try:
        plat = parameter_plateau(fn, runner, bars_per_year=2190.0)
    except Exception as e:
        plat = {"error": f"{type(e).__name__}: {e}", "passed": False}

    full = {
        "label": label, "symbol": symbol, "tf": tf,
        "fn": fn_name, "module": fname,
        "phase5_metrics": {
            k: row.get(k) for k in (
                "n_trades", "oos_sharpe", "oos_calmar", "oos_max_dd",
                "oos_cagr", "oos_sortino", "oos_dsr", "oos_psr",
                "win_rate", "profit_factor", "maker_fill_pct",
                "gates_passed", "n_profitable_regimes", "rho_buy_hold_oos",
            )
        },
        "phase5_gates": row.get("gate_detail", {}),
        "robustness_4test": {**asdict(rep), "verdict": v4},
        "plateau": plat,
        "tests_passed_8": v4["tests_passed"] + (1 if plat.get("passed") else 0),
        "tests_total_8": v4["tests_total"] + 1,
    }
    return full


def main():
    results = {"cells": [], "unavailable": []}
    for label, fname, fn_name, sym, tf in CELLS:
        print(f"\n=== {label} ({sym} {tf}) ===")
        r = _run_cell(label, fname, fn_name, sym, tf)
        if "error" in r:
            print(f"  ERROR: {r['error']}")
        else:
            m = r["phase5_metrics"]
            print(f"  n_trades={m['n_trades']}  Sharpe={m['oos_sharpe']:+.2f}  "
                  f"Calmar={m['oos_calmar']:+.2f}  MDD={m['oos_max_dd']*100:+.1f}%  "
                  f"Maker={m['maker_fill_pct']*100:.0f}%  "
                  f"Phase5={m['gates_passed']}/7")
            rv = r["robustness_4test"]["verdict"]
            print(f"  Robustness 4-test: {rv['tests_passed']}/{rv['tests_total']}")
            per_year = r["robustness_4test"].get("per_year", {})
            if per_year:
                yrs = sorted(per_year.keys())
                print("  per-year Sharpe:",
                      " ".join(f"{y}:{per_year[y]['sharpe']:+.2f}" for y in yrs))
            plat = r["plateau"]
            if "passed" in plat:
                print(f"  Plateau: passed={plat['passed']}  "
                      f"worst25%={plat.get('worst_25pct_sharpe_drop', 0):.1%}  "
                      f"worst50%={plat.get('worst_50pct_sharpe_drop', 0):.1%}  "
                      f"cliff={plat.get('cliff_detected', False)}")
            print(f"  FULL 5-TEST BATTERY: {r['tests_passed_8']}/{r['tests_total_8']}")
        results["cells"].append(r)

    for label, why in UNAVAILABLE:
        print(f"\n=== {label} — SKIPPED: {why} ===")
        results["unavailable"].append({"label": label, "reason": why})

    OUT.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
