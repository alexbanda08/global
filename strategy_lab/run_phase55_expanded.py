"""
Expanded Phase 5.5 driver — robustness battery on ALL Phase-5 cells
whose gates_passed >= `min_gates`. Also runs the regime-filtered
variants of C1 and gaussian_channel_v2 to see whether adding a regime
filter rescues them (Phase 5.5 hypothesis test).
"""
from __future__ import annotations

import importlib.util as _il
import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "strategy_lab"))

import engine                                             # noqa: E402
from regime import REGIME_4H_PRESET                       # noqa: E402
from strategies.adaptive.regime_filter import with_regime_filter  # noqa: E402
from eval.robustness import run_robustness                # noqa: E402

OUT_JSON = REPO / "docs" / "research" / "phase5_results" / "robustness_expanded.json"


def _load_module(file_name: str):
    p = REPO / "strategy_lab" / file_name
    spec = _il.spec_from_file_location(f"_exp_{p.stem}", p)
    mod = _il.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _v1_runner(signal_fn, tf: str):
    def _run(df: pd.DataFrame) -> pd.Series:
        out = signal_fn(df)
        if isinstance(out, tuple) and len(out) == 2:
            out = {"entries": out[0], "exits": out[1]}
        res = engine.run_backtest(
            df, entries=out["entries"], exits=out["exits"],
            sl_stop=out.get("sl_stop"), tsl_stop=out.get("tsl_stop"),
            tp_stop=out.get("tp_stop"),
        )
        eq = getattr(res, "equity", None)
        if eq is None and res.pf is not None:
            eq = res.pf.value()
        return eq
    return _run


def _limit_runner_c1(regime_filter: bool):
    from strategies.adaptive.c1_meta_labeled_donchian import generate_signals as c1
    inner = c1
    if regime_filter:
        inner = with_regime_filter(c1)

    def _run(df: pd.DataFrame) -> pd.Series:
        sig = inner(df)
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
        return getattr(res, "equity", None)
    return _run


def main():
    csv = REPO / "docs" / "research" / "phase5_results" / "phase5_existing_book_results.csv"
    if not csv.is_file():
        print(f"Missing {csv}; run run_phase5_existing_book.py first.")
        return 1
    df = pd.read_csv(csv)
    df = df[df["n_trades"].fillna(0) > 5].copy()
    df = df.sort_values("gates_passed", ascending=False)
    # Run robustness on every cell that reached at least 3/7 gates.
    top = df[df["gates_passed"] >= 3].head(20)
    print(f"Auditing {len(top)} cells with >=3/7 Phase-5 gates")

    v2 = _load_module("strategies_v2.py")
    v1 = _load_module("strategies.py")
    MODS = {**{n: v1 for n in dir(v1)}, **{n: v2 for n in dir(v2)}}

    reports = []
    for _, row in top.iterrows():
        sid = row["strategy_id"]; sym = row["symbol"]; tf = row["tf"]
        if sid not in dir(v1) and sid not in dir(v2):
            continue                    # scanner-loaded ones skipped here for brevity
        mod = v1 if sid in dir(v1) else v2
        fn = getattr(mod, sid)
        df_full = engine.load(sym, tf, start="2022-01-01", end="2024-12-31")
        runner = _v1_runner(fn, tf)
        try:
            equity = runner(df_full)
        except Exception as e:
            print(f"{sid}/{sym}: runner error {e}"); continue
        if equity is None or len(equity) < 100:
            continue
        print(f"\n== {sid} | {sym} | {tf} ==")
        rep = run_robustness(sid, sym, tf, equity, runner, df_full,
                             bars_per_year=2190.0, n_perm=20, n_bootstrap=500)
        v = rep.verdict()
        print(f"  robustness_tests_passed: {v['tests_passed']}/{v['tests_total']}")
        if rep.per_year:
            yrs = sorted(rep.per_year.keys())
            print("  per-year Sharpe:",
                  " ".join(f"{y}:{rep.per_year[y]['sharpe']:+.2f}" for y in yrs))
        reports.append({**asdict(rep), "verdict": v})

    # --- Regime-filter experiments on C1 ETH and gaussian_channel_v2 BTC
    print("\n=== Regime-filter experiments ===")
    rf_cells = [
        ("c1_meta_labeled_donchian_REGIME_FILTERED", "ETHUSDT", "4h",
         _limit_runner_c1(regime_filter=True)),
        ("c1_meta_labeled_donchian_VANILLA", "ETHUSDT", "4h",
         _limit_runner_c1(regime_filter=False)),
    ]
    gcv2 = getattr(v2, "gaussian_channel_v2", None)
    if gcv2 is not None:
        gcv2_rf = with_regime_filter(gcv2)
        rf_cells.append((
            "gaussian_channel_v2_REGIME_FILTERED", "BTCUSDT", "4h",
            _v1_runner(gcv2_rf, "4h"),
        ))
        rf_cells.append((
            "gaussian_channel_v2_VANILLA", "BTCUSDT", "4h",
            _v1_runner(gcv2, "4h"),
        ))

    for sid, sym, tf, runner in rf_cells:
        df_full = engine.load(sym, tf, start="2022-01-01", end="2024-12-31")
        try:
            equity = runner(df_full)
        except Exception as e:
            print(f"{sid}/{sym}: runner error {e}"); continue
        if equity is None or len(equity) < 100:
            print(f"{sid}/{sym}: no equity"); continue
        rep = run_robustness(sid, sym, tf, equity, runner, df_full,
                             bars_per_year=2190.0, n_perm=20, n_bootstrap=500)
        v = rep.verdict()
        print(f"\n== {sid} | {sym} ==")
        print(f"  robustness_tests_passed: {v['tests_passed']}/{v['tests_total']}")
        if rep.per_year:
            yrs = sorted(rep.per_year.keys())
            print("  per-year Sharpe:",
                  " ".join(f"{y}:{rep.per_year[y]['sharpe']:+.2f}" for y in yrs))
        if rep.walk_forward:
            wf = rep.walk_forward
            print(f"  WFE={wf.get('efficiency_ratio')}  "
                  f"pos_folds={wf.get('n_positive_folds')}/{wf.get('n_folds')}")
        reports.append({**asdict(rep), "verdict": v})

    OUT_JSON.write_text(json.dumps(reports, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
