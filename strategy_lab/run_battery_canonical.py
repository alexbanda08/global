"""
Phase 5.5 — full 5-test robustness battery on top perps-parity cells,
using the canonical simulator (eval/perps_simulator.py).

Tests:
  1. Per-year consistency    — Sharpe > 0 in ≥ 70% of years
  2. Parameter plateau       — sweep signal-fn numeric params ±25/50%
  3. Null permutation        — shuffle log-returns, rerun strategy
  4. Block bootstrap         — CI on Sharpe/Calmar/MDD
  5. Walk-forward efficiency — 6 folds on baseline equity

All runs use the canonical ATR-stack + 3x leverage + 2-bar cooldown
executor so numbers match the V22/V25/V28/V29/V30 reports.

Outputs:
  docs/research/phase5_results/battery_canonical.json
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
from typing import Callable

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "strategy_lab"))

import engine                                                  # noqa: E402
from eval.perps_simulator import simulate, compute_metrics    # noqa: E402
from eval.robustness import (                                  # noqa: E402
    per_year_stats, block_bootstrap_ci, permutation_test,
    walk_forward_efficiency,
)


OUT_JSON = REPO / "docs" / "research" / "phase5_results" / "battery_canonical.json"


BARS_PER_YEAR = {"15m": 365.25*96, "30m": 365.25*48, "1h": 365.25*24,
                 "2h":  365.25*12, "4h":  365.25*6,  "1d": 365.25}


EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)
EXIT_1H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=5.0, max_hold=72)
EXIT_15M = dict(tp_atr=6.0, sl_atr=1.5, trail_atr=3.5, max_hold=36)
DEFAULT_CFG = dict(risk_per_trade=0.03, leverage_cap=3.0,
                   fee=0.00045, slip=0.0003, init_cash=10_000.0)


# Only these cells — the strongest from perps-parity v2.
CELLS = [
    ("SOL_SuperTrend_Flip_4h", "run_v30_creative.py",   "sig_supertrend_flip",
     "SOLUSDT",  "4h", {}, "2021-01-01"),
    ("ETH_CCI_Extreme_Rev_4h", "run_v30_creative.py",   "sig_cci_extreme",
     "ETHUSDT",  "4h", {}, "2021-01-01"),
    ("DOGE_HTF_Donchian_4h",   "run_v34_expand.py",     "sig_htf_donchian_ls",
     "DOGEUSDT", "4h", {}, "2021-01-01"),
    ("SOL_BBBreak_LS_4h",      "run_v38b_smc_mixes.py", "sig_bbbreak",
     "SOLUSDT",  "4h", {}, "2021-01-01"),
]


def _load_mod(fname: str):
    p = REPO / "strategy_lab" / fname
    spec = _il.spec_from_file_location(f"_bc_{p.stem}", p)
    mod = _il.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        spec.loader.exec_module(mod)
    return mod


def _unpack(out):
    if isinstance(out, tuple) and len(out) == 2:
        return out[0], out[1]
    if isinstance(out, dict):
        return out.get("entries") or out.get("long_entries"), out.get("short_entries")
    raise TypeError


def _run_once(df, signal_fn, fn_kwargs, exit_cfg) -> pd.Series:
    long_sig, short_sig = _unpack(signal_fn(df, **fn_kwargs))
    _, equity = simulate(df, long_sig, short_sig, **exit_cfg, **DEFAULT_CFG)
    return equity


def _numeric_params(fn: Callable) -> dict[str, float]:
    sig = inspect.signature(fn)
    out = {}
    for name, p in sig.parameters.items():
        if name in ("df", "ohlcv", "data") or p.default is inspect.Parameter.empty:
            continue
        if isinstance(p.default, bool):
            continue
        if isinstance(p.default, (int, float)) and p.default != 0:
            out[name] = float(p.default)
    return out


def _plateau_canonical(fn, df, fn_kwargs, exit_cfg, bpy) -> dict:
    """Parameter plateau using the canonical simulator."""
    from eval.metrics import sharpe_ratio, max_drawdown, calmar_ratio
    numeric = _numeric_params(fn)
    base_eq = _run_once(df, fn, fn_kwargs, exit_cfg)
    base_sharpe = sharpe_ratio(base_eq.pct_change().dropna(), bpy)
    base_mdd = max_drawdown(base_eq)
    years = len(base_eq) / bpy
    base_cagr = (base_eq.iloc[-1] / base_eq.iloc[0]) ** (1/max(years, 1e-6)) - 1.0
    base_calmar = calmar_ratio(base_cagr, base_mdd)

    worst_25 = 0.0
    worst_50 = 0.0
    cliff = False
    worst_param = None
    param_results = {}

    for pname, pval in numeric.items():
        sweep = {}
        for pct in (-0.5, -0.25, 0.25, 0.5):
            new_val = pval * (1 + pct)
            if "period" in pname or "len" in pname or "window" in pname or \
               "lb" in pname.lower() or "_n" in pname:
                new_val = max(2, int(round(new_val)))
            overrides = {**fn_kwargs, pname: new_val}
            try:
                eq = _run_once(df, fn, overrides, exit_cfg)
            except Exception as e:
                sweep[pct] = {"error": str(e)}
                continue
            if eq is None or len(eq) < 30:
                sweep[pct] = {"error": "short"}
                continue
            sh = sharpe_ratio(eq.pct_change().dropna(), bpy)
            sweep[pct] = {"value": new_val, "sharpe": round(sh, 3)}
            if base_sharpe > 0:
                drop = 1.0 - (sh / base_sharpe)
            else:
                drop = abs(sh - base_sharpe)
            if abs(pct) <= 0.26 and drop > worst_25:
                worst_25 = drop
            if drop > worst_50:
                worst_50 = drop
                worst_param = pname
            if base_sharpe > 0 and sh < 0.3 * base_sharpe:
                cliff = True
        param_results[pname] = {"baseline_value": pval, "sweep": sweep}

    passed = worst_25 < 0.30 and worst_50 < 0.60 and not cliff
    return {
        "baseline_sharpe": round(base_sharpe, 3),
        "baseline_calmar": round(base_calmar, 3),
        "worst_25pct_sharpe_drop": round(worst_25, 3),
        "worst_50pct_sharpe_drop": round(worst_50, 3),
        "cliff_detected": bool(cliff),
        "worst_param": worst_param,
        "params": param_results,
        "passed": bool(passed),
    }


def run_battery_canonical(label, module_file, fn_name, symbol, tf,
                           fn_kwargs, data_start):
    fn = getattr(_load_mod(module_file), fn_name, None)
    if fn is None:
        raise ImportError(f"{fn_name} not in {module_file}")
    df = engine.load(symbol, tf, start=data_start, end="2026-04-24")
    exit_cfg = EXIT_4H if tf == "4h" else (EXIT_1H if tf == "1h" else EXIT_15M)
    bpy = BARS_PER_YEAR.get(tf, 2190.0)

    baseline_eq = _run_once(df, fn, fn_kwargs, exit_cfg)

    def perm_runner(df_perm: pd.DataFrame) -> pd.Series:
        return _run_once(df_perm, fn, fn_kwargs, exit_cfg)

    print(f"  Running tests (baseline equity len={len(baseline_eq)}) ...")
    py = per_year_stats(baseline_eq, bpy)
    rets = baseline_eq.pct_change().dropna()
    bs = block_bootstrap_ci(rets, n_iter=500, bars_per_year=bpy)
    wf = walk_forward_efficiency(baseline_eq, bars_per_year=bpy)
    perm = permutation_test(df, perm_runner, n_perm=20, bars_per_year=bpy)
    plat = _plateau_canonical(fn, df, fn_kwargs, exit_cfg, bpy)

    # Aggregate verdict
    pos_years = sum(1 for y in py.values() if y.get("sharpe", 0) > 0)
    total_years = len(py)
    verdict = {
        "per_year_>=70pct":             pos_years / max(total_years, 1) >= 0.70,
        "permutation_p<0.01":           perm.get("p_value", 1.0) < 0.01,
        "bootstrap_sharpe_lowerCI>0.5": bs.get("sharpe", {}).get("ci_lo", 0) > 0.5,
        "bootstrap_calmar_lowerCI>1.0": bs.get("calmar", {}).get("ci_lo", 0) > 1.0,
        "bootstrap_mdd_upperCI<30%":    bs.get("max_dd", {}).get("ci_hi", 0) > -0.30,
        "walk_forward_efficiency>0.5":  wf.get("efficiency_ratio", 0) >= 0.5,
        "walk_forward_pos_folds>=5":    wf.get("n_positive_folds", 0) >= 5,
        "plateau_passed":               plat.get("passed", False),
    }
    passed = sum(1 for v in verdict.values() if v)
    total = len(verdict)

    return {
        "label": label, "symbol": symbol, "tf": tf,
        "module": module_file, "fn": fn_name,
        "per_year": py,
        "bootstrap": bs,
        "walk_forward": wf,
        "permutation": perm,
        "plateau": plat,
        "verdict": verdict,
        "tests_passed": passed,
        "tests_total": total,
    }


def main():
    reports = []
    for label, mf, fn, sym, tf, kw, start in CELLS:
        print(f"\n=== {label} ({sym} {tf}) ===")
        try:
            r = run_battery_canonical(label, mf, fn, sym, tf, kw, start)
            reports.append(r)
            print(f"  FULL BATTERY: {r['tests_passed']}/{r['tests_total']}")
            for k, v in r["verdict"].items():
                print(f"    [{'OK' if v else '  '}] {k}")
            py_str = " ".join(f"{y}:{r['per_year'][y]['sharpe']:+.2f}"
                              for y in sorted(r["per_year"]))
            print(f"  per-year: {py_str}")
            bs = r["bootstrap"]
            if bs:
                print(f"  boot CI95: Sharpe[{bs['sharpe']['ci_lo']:+.2f},{bs['sharpe']['ci_hi']:+.2f}]  "
                      f"Calmar[{bs['calmar']['ci_lo']:+.2f},{bs['calmar']['ci_hi']:+.2f}]  "
                      f"MDD[{bs['max_dd']['ci_lo']*100:+.0f}%,{bs['max_dd']['ci_hi']*100:+.0f}%]")
            wf = r["walk_forward"]
            if wf and "efficiency_ratio" in wf:
                print(f"  WF: eff={wf['efficiency_ratio']}  "
                      f"pos={wf['n_positive_folds']}/{wf['n_folds']}  "
                      f"worst={wf['worst_fold_sharpe']}")
            perm = r["permutation"]
            if perm and "p_value" in perm:
                print(f"  Perm: p={perm['p_value']}  real={perm.get('real_sharpe')}  "
                      f"null_mean={perm.get('null_mean')}  99th={perm.get('null_99th')}")
            plat = r["plateau"]
            print(f"  Plateau: pass={plat['passed']}  "
                  f"worst25={plat['worst_25pct_sharpe_drop']:.1%}  "
                  f"worst50={plat['worst_50pct_sharpe_drop']:.1%}  "
                  f"cliff={plat['cliff_detected']}")
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  ERROR: {e}")
            reports.append({"label": label, "error": str(e)})

    OUT_JSON.write_text(json.dumps(reports, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {OUT_JSON}")


if __name__ == "__main__":
    main()
