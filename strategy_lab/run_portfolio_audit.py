"""
Portfolio Audit — full 5-test canonical battery applied to blended equity.

Tests:
  1. Per-year consistency        (on blended equity)
  2. Block bootstrap CIs         (on blended returns)
  3. Walk-forward efficiency     (6 folds on blended equity)
  4. Null permutation            (shuffle each sleeve's source df, re-sim, re-blend)
  5. Parameter plateau           (for each sleeve, sweep its numeric params,
                                  re-sim just that sleeve, re-blend, score)

Usage:
    py -3.14 run_portfolio_audit.py --portfolio P2  (or P3, P4)

P2 = CCI_ETH + STF_SOL                                                 (2-sleeve)
P3 = CCI_ETH + STF_AVAX + STF_SOL                                      (3-sleeve)
P4 = CCI_ETH + STF_AVAX + STF_SOL + VWZ_INJ                            (4-sleeve)
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util as _il
import inspect
import io
import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "strategy_lab"))

import engine                                                 # noqa: E402
from eval.perps_simulator import simulate                     # noqa: E402
from eval.metrics import sharpe_ratio, max_drawdown, calmar_ratio  # noqa: E402
from eval.robustness import (                                 # noqa: E402
    per_year_stats, block_bootstrap_ci, walk_forward_efficiency,
)


BPY = 365.25 * 6      # 4h
EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)
DEFAULT_CFG = dict(risk_per_trade=0.03, leverage_cap=3.0,
                   fee=0.00045, slip=0.0003, init_cash=10_000.0)

OUT_DIR = REPO / "docs" / "research" / "phase5_results"


# ---------------------------------------------------------------------
# Portfolio specs — must match labels in equity_curves/perps/
# ---------------------------------------------------------------------
SLEEVE_SPECS = {
    "CCI_ETH_4h":  ("run_v30_creative.py",   "sig_cci_extreme",       "ETHUSDT",  "4h"),
    "STF_SOL_4h":  ("run_v30_creative.py",   "sig_supertrend_flip",   "SOLUSDT",  "4h"),
    "STF_AVAX_4h": ("run_v30_creative.py",   "sig_supertrend_flip",   "AVAXUSDT", "4h"),
    "VWZ_INJ_4h":  ("run_v30_creative.py",   "sig_vwap_zfade",        "LINKUSDT", "4h"),
    # --- new sleeves for P5/P6/P7 ---
    "LATBB_AVAX_4h": ("run_v29_regime.py",     "sig_lateral_bb_fade",  "AVAXUSDT", "4h"),
    "STF_DOGE_4h":   ("run_v30_creative.py",   "sig_supertrend_flip",  "DOGEUSDT", "4h"),
    "BB_AVAX_4h":    ("run_v38b_smc_mixes.py", "sig_bbbreak",          "AVAXUSDT", "4h"),
}

PORTFOLIOS = {
    "P2": ["CCI_ETH_4h", "STF_SOL_4h"],
    "P3": ["CCI_ETH_4h", "STF_AVAX_4h", "STF_SOL_4h"],
    "P4": ["CCI_ETH_4h", "STF_AVAX_4h", "STF_SOL_4h", "VWZ_INJ_4h"],
    # New from long-history hunt (Phase A expansion cells)
    "P5": ["CCI_ETH_4h", "LATBB_AVAX_4h", "STF_SOL_4h"],
    "P6": ["CCI_ETH_4h", "STF_DOGE_4h", "STF_SOL_4h"],
    "P7": ["BB_AVAX_4h", "CCI_ETH_4h", "STF_SOL_4h"],   # max min-year 12.8%
}

SLEEVE_SPECS_EXT = {
    "LATBB_AVAX_4h": ("run_v29_regime.py",       "sig_lateral_bb_fade",   "AVAXUSDT", "4h"),
    "STF_DOGE_4h":   ("run_v30_creative.py",     "sig_supertrend_flip",   "DOGEUSDT", "4h"),
    "BB_AVAX_4h":    ("run_v38b_smc_mixes.py",   "sig_bbbreak",           "AVAXUSDT", "4h"),
}


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _load_mod(fname: str):
    p = REPO / "strategy_lab" / fname
    spec = _il.spec_from_file_location(f"_au_{p.stem}", p)
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


def _numeric_params(fn) -> dict[str, float]:
    sig = inspect.signature(fn)
    out = {}
    for name, p in sig.parameters.items():
        if name in ("df", "ohlcv", "data"):
            continue
        if p.default is inspect.Parameter.empty or isinstance(p.default, bool):
            continue
        if isinstance(p.default, (int, float)) and p.default != 0:
            out[name] = float(p.default)
    return out


def _run_sleeve(sleeve_label: str, df_cache: dict, override: dict | None = None,
                df_override: pd.DataFrame | None = None) -> pd.Series:
    """Run a single sleeve with canonical simulator. Optional param override
    and df override (for permutation test)."""
    module_file, fn_name, sym, tf = SLEEVE_SPECS[sleeve_label]
    fn = getattr(_load_mod(module_file), fn_name, None)
    if fn is None:
        raise ImportError(f"{fn_name} in {module_file}")
    df = df_override if df_override is not None else df_cache.get((sym, tf))
    if df is None:
        df = engine.load(sym, tf, start="2021-01-01", end="2026-04-24")
        df_cache[(sym, tf)] = df
    kw = override or {}
    long_sig, short_sig = _unpack(fn(df, **kw))
    _, eq = simulate(df, long_sig, short_sig, **EXIT_4H, **DEFAULT_CFG)
    return eq


def _blend_daily_eqw(equities: list[pd.Series]) -> pd.Series:
    common = equities[0].index
    for eq in equities[1:]:
        common = common.intersection(eq.index)
    rets = pd.DataFrame({i: eq.reindex(common).pct_change().fillna(0)
                         for i, eq in enumerate(equities)})
    port_rets = rets.mean(axis=1)
    return (1.0 + port_rets).cumprod()


def _metrics_from_equity(port: pd.Series) -> dict:
    rets = port.pct_change().dropna()
    mu, sd = float(rets.mean()), float(rets.std())
    sh = (mu / sd) * np.sqrt(BPY) if sd > 0 else 0.0
    peak = port.cummax()
    mdd = float((port / peak - 1.0).min())
    yrs = (port.index[-1] - port.index[0]).total_seconds() / (365.25 * 86400)
    total = float(port.iloc[-1] / port.iloc[0]) - 1.0
    cagr = (1 + total) ** (1 / max(yrs, 1e-6)) - 1.0
    cal = cagr / abs(mdd) if mdd != 0 else 0.0
    return {"sharpe": round(sh, 3), "cagr": round(cagr, 4),
            "max_dd": round(mdd, 4), "calmar": round(cal, 3)}


# ---------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------
def audit_portfolio(portfolio_name: str) -> dict:
    sleeve_labels = PORTFOLIOS[portfolio_name]
    print(f"\n=== AUDIT {portfolio_name}: {' + '.join(sleeve_labels)} ===\n")

    df_cache: dict = {}
    baseline_sleeves = [_run_sleeve(s, df_cache) for s in sleeve_labels]
    baseline_port = _blend_daily_eqw(baseline_sleeves)
    baseline_metrics = _metrics_from_equity(baseline_port)
    print(f"Baseline: Sharpe={baseline_metrics['sharpe']}  "
          f"CAGR={baseline_metrics['cagr']*100:+.1f}%  "
          f"MDD={baseline_metrics['max_dd']*100:+.1f}%  "
          f"Calmar={baseline_metrics['calmar']}")

    # --- 1. Per-year
    py = per_year_stats(baseline_port, BPY)

    # --- 2. Bootstrap CIs
    rets = baseline_port.pct_change().dropna()
    bs = block_bootstrap_ci(rets, n_iter=500, bars_per_year=BPY)

    # --- 3. Walk-forward efficiency
    wf = walk_forward_efficiency(baseline_port, bars_per_year=BPY)

    # --- 4. Permutation (shuffle each sleeve's source df once per iter)
    real_sh = baseline_metrics["sharpe"]
    null_sh = []
    rng = np.random.default_rng(42)
    n_perm = 15   # budget compromise
    print(f"Running {n_perm} permutations ...", flush=True)
    for k in range(n_perm):
        try:
            perm_sleeves = []
            for label in sleeve_labels:
                sym, tf = SLEEVE_SPECS[label][2:]
                df = df_cache[(sym, tf)]
                close = df["close"].to_numpy()
                log_r = np.diff(np.log(close))
                perm = rng.permutation(log_r)
                new_close = np.exp(np.concatenate([[np.log(close[0])], np.cumsum(perm) + np.log(close[0])]))
                scale = new_close / close
                df_perm = df.copy()
                df_perm["close"] = new_close
                df_perm["open"]  = df["open"].to_numpy() * scale
                df_perm["high"]  = df["high"].to_numpy() * scale
                df_perm["low"]   = df["low"].to_numpy()  * scale
                eq = _run_sleeve(label, df_cache, df_override=df_perm)
                perm_sleeves.append(eq)
            port = _blend_daily_eqw(perm_sleeves)
            if len(port) >= 30:
                null_sh.append(sharpe_ratio(port.pct_change().dropna(), BPY))
        except Exception as e:
            print(f"  perm {k}: {e}")
            continue
    null_arr = np.asarray(null_sh, dtype=float)
    p_value = float((null_arr >= real_sh).mean()) if len(null_arr) else 1.0
    perm_result = {
        "n_permutations": len(null_arr),
        "real_sharpe": real_sh,
        "null_mean": float(null_arr.mean()) if len(null_arr) else None,
        "null_99th": float(np.quantile(null_arr, 0.99)) if len(null_arr) else None,
        "p_value": round(p_value, 4),
    }
    print(f"  perm: p={p_value:.3f}  real={real_sh}  "
          f"null_mean={perm_result['null_mean']}  "
          f"null_99th={perm_result['null_99th']}")

    # --- 5. Plateau: sweep each sleeve's numeric params, re-blend, score
    print("Running plateau sweep ...", flush=True)
    worst_25 = 0.0
    worst_50 = 0.0
    cliff = False
    plateau_details = {}
    for idx, label in enumerate(sleeve_labels):
        module_file, fn_name, _, _ = SLEEVE_SPECS[label]
        fn = getattr(_load_mod(module_file), fn_name, None)
        numeric = _numeric_params(fn)
        sleeve_report = {"baseline": {},  "sweep": {}}
        for pname, pval in numeric.items():
            for pct in (-0.5, -0.25, 0.25, 0.5):
                new_val = pval * (1 + pct)
                if any(t in pname for t in ("_n", "len", "period", "window", "lb", "reg", "mom")):
                    new_val = max(2, int(round(new_val)))
                override = {pname: new_val}
                try:
                    perturbed_eq = _run_sleeve(label, df_cache, override=override)
                    sleeves_new = [baseline_sleeves[i] if i != idx else perturbed_eq
                                   for i in range(len(sleeve_labels))]
                    port_new = _blend_daily_eqw(sleeves_new)
                    sh_new = sharpe_ratio(port_new.pct_change().dropna(), BPY)
                    if real_sh > 0:
                        drop = 1.0 - (sh_new / real_sh)
                    else:
                        drop = abs(sh_new - real_sh)
                    sleeve_report["sweep"][f"{pname}@{pct:+.0%}"] = round(sh_new, 3)
                    if abs(pct) <= 0.26 and drop > worst_25:
                        worst_25 = drop
                    if drop > worst_50:
                        worst_50 = drop
                    if real_sh > 0 and sh_new < 0.3 * real_sh:
                        cliff = True
                except Exception as e:
                    sleeve_report["sweep"][f"{pname}@{pct:+.0%}"] = f"ERR:{e}"
        plateau_details[label] = sleeve_report
    plateau_passed = worst_25 < 0.30 and worst_50 < 0.60 and not cliff
    print(f"  plateau: pass={plateau_passed}  worst25={worst_25:.1%}  "
          f"worst50={worst_50:.1%}  cliff={cliff}")

    # --- Aggregate verdict
    pos_years = sum(1 for y in py.values() if y.get("sharpe", 0) > 0)
    total_years = len(py)
    verdict = {
        "per_year_>=70pct":             pos_years / max(total_years, 1) >= 0.70,
        "permutation_p<0.01":           perm_result["p_value"] < 0.01,
        "bootstrap_sharpe_lowerCI>0.5": bs.get("sharpe", {}).get("ci_lo", 0) > 0.5,
        "bootstrap_calmar_lowerCI>1.0": bs.get("calmar", {}).get("ci_lo", 0) > 1.0,
        "bootstrap_mdd_upperCI<30%":    bs.get("max_dd", {}).get("ci_hi", 0) > -0.30,
        "walk_forward_efficiency>0.5":  wf.get("efficiency_ratio", 0) >= 0.5,
        "walk_forward_pos_folds>=5":    wf.get("n_positive_folds", 0) >= 5,
        "plateau_passed":               plateau_passed,
    }
    passed = sum(1 for v in verdict.values() if v)

    report = {
        "portfolio": portfolio_name,
        "sleeves": sleeve_labels,
        "baseline_metrics": baseline_metrics,
        "per_year": py,
        "bootstrap": bs,
        "walk_forward": wf,
        "permutation": perm_result,
        "plateau": {
            "passed": plateau_passed,
            "worst_25pct_drop": round(worst_25, 3),
            "worst_50pct_drop": round(worst_50, 3),
            "cliff": cliff,
            "per_sleeve": plateau_details,
        },
        "verdict": verdict,
        "tests_passed": passed,
        "tests_total": len(verdict),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"portfolio_audit_{portfolio_name}.json"
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nBATTERY: {passed}/{len(verdict)}")
    for k, v in verdict.items():
        print(f"  [{'OK' if v else '  '}] {k}")
    print(f"\nWrote {out_path}")
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--portfolio", choices=list(PORTFOLIOS.keys()), required=True)
    args = ap.parse_args()
    audit_portfolio(args.portfolio)


if __name__ == "__main__":
    main()
