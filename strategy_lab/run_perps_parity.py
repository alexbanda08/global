"""
Perps-parity replication driver — uses the CANONICAL simulator from
eval/perps_simulator.py (ported verbatim from DEPLOYMENT_BLUEPRINT.md).

Critical fix (2026-04-24): signal functions in run_v30_creative.py,
run_v38b_smc_mixes.py etc. return a TUPLE (long_entries, short_entries).
Previous driver was treating tuple[1] as long-exits — that was wrong.
The canonical runner passes long_entries and short_entries SEPARATELY
to simulate(), and exits come entirely from the ATR stack + time-stop.

Fee schedule: 0.045% taker / 0.015% maker (user clarification — no rebate).
The simulator's `fee` param is applied on every fill; use taker for V30
family (signals are market-style), maker not applicable here.

Outputs:
  docs/research/phase5_results/perps_parity_v2.csv
  docs/research/phase5_results/perps_parity_v2.json
"""
from __future__ import annotations

import contextlib
import importlib.util as _il
import io
import json
import sys
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "strategy_lab"))

import engine                                                # noqa: E402
from eval.perps_simulator import simulate, compute_metrics   # noqa: E402


OUT_CSV  = REPO / "docs" / "research" / "phase5_results" / "perps_parity_v2.csv"
OUT_JSON = REPO / "docs" / "research" / "phase5_results" / "perps_parity_v2.json"


BARS_PER_YEAR = {"15m": 365.25*96, "30m": 365.25*48, "1h": 365.25*24,
                 "2h":  365.25*12, "4h":  365.25*6,  "1d": 365.25}


def _load_mod(fname: str):
    p = REPO / "strategy_lab" / fname
    spec = _il.spec_from_file_location(f"_v2_{p.stem}", p)
    mod = _il.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        spec.loader.exec_module(mod)
    return mod


def _unpack(out):
    """Canonical: signal fns return (long_entries, short_entries). Handle
    dict form too for backward compat."""
    if isinstance(out, tuple) and len(out) == 2:
        return out[0], out[1]
    if isinstance(out, dict):
        le = out.get("entries") or out.get("long_entries")
        se = out.get("short_entries")
        return le, se
    raise TypeError(f"unrecognized signal return type: {type(out)}")


# Canonical exit grids from the V-reports.
EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)
EXIT_1H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=5.0, max_hold=72)
EXIT_15M = dict(tp_atr=6.0, sl_atr=1.5, trail_atr=3.5, max_hold=36)

DEFAULT_CFG = dict(
    risk_per_trade=0.03,
    leverage_cap=3.0,
    fee=0.00045,          # 4.5 bps taker (user clarified no rebate)
    slip=0.0003,          # 3 bps
    init_cash=10_000.0,
)


# (label, module_file, fn_name, symbol, tf, fn_kwargs, data_start)
CELLS = [
    ("SOL_BBBreak_LS_4h",      "run_v38b_smc_mixes.py", "sig_bbbreak",
     "SOLUSDT",  "4h", {}, "2021-01-01"),
    ("DOGE_TTM_Squeeze_Pop_4h","run_v30_creative.py",   "sig_ttm_squeeze",
     "DOGEUSDT", "4h", {}, "2021-01-01"),
    ("SOL_SuperTrend_Flip_4h", "run_v30_creative.py",   "sig_supertrend_flip",
     "SOLUSDT",  "4h", {}, "2021-01-01"),
    ("DOGE_HTF_Donchian_4h",   "run_v34_expand.py",     "sig_htf_donchian_ls",
     "DOGEUSDT", "4h", {}, "2021-01-01"),
    ("ETH_CCI_Extreme_Rev_4h", "run_v30_creative.py",   "sig_cci_extreme",
     "ETHUSDT",  "4h", {}, "2021-01-01"),
]


def main():
    results = []
    for label, fname, fn_name, sym, tf, kw, start in CELLS:
        print(f"\n=== {label} ({sym} {tf}) ===")
        try:
            fn = getattr(_load_mod(fname), fn_name, None)
            if fn is None:
                raise ImportError(f"{fn_name} not found in {fname}")
            df = engine.load(sym, tf, start=start, end="2026-04-24")
            raw = fn(df, **kw)
            long_sig, short_sig = _unpack(raw)
            exit_cfg = EXIT_4H if tf == "4h" else (
                EXIT_1H if tf == "1h" else EXIT_15M
            )
            trades, equity = simulate(
                df, long_sig, short_sig,
                **exit_cfg, **DEFAULT_CFG,
            )
            bpy = BARS_PER_YEAR.get(tf, 2190.0)
            m = compute_metrics(label, equity, trades, bpy)
            m.update({
                "symbol": sym, "tf": tf, "module": fname, "fn": fn_name,
                "has_shorts": short_sig is not None,
                "n_long_entries":  int(long_sig.sum()),
                "n_short_entries": int(short_sig.sum()) if short_sig is not None else 0,
                "data_start": start,
            })
            results.append(m)
            py_str = " ".join(f"{y}:{m['per_year'][y]['sharpe']:+.2f}"
                              for y in sorted(m["per_year"]))
            print(f"  n_trades={m['n_trades']} (L={m['n_long_entries']} "
                  f"S={m['n_short_entries']})  Sharpe={m['sharpe']:+.2f}  "
                  f"CAGR={m['cagr']*100:+.1f}%  MDD={m['max_dd']*100:+.1f}%  "
                  f"Calmar={m['calmar']:+.2f}  win%={m['win_rate']*100:.0f}")
            print(f"  per-year Sharpe: {py_str}")
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  ERROR: {e}")
            results.append({"label": label, "error": str(e)})

    df_out = pd.DataFrame(results)
    if "per_year" in df_out.columns:
        df_out["per_year"] = df_out["per_year"].apply(
            lambda v: json.dumps(v) if isinstance(v, dict) else v
        )
    df_out.to_csv(OUT_CSV, index=False)
    OUT_JSON.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {OUT_CSV}  ({len(df_out)} rows)")


if __name__ == "__main__":
    main()
