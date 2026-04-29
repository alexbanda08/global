"""
Phase 5 extension — score the EXISTING 50-strategy book with the same
metrics pipeline used for adaptive candidates.

Why: we now have a uniform evaluation harness (Deflated Sharpe,
Probabilistic Sharpe, Calmar, Ulcer, regime-conditional Sharpe, etc.).
Applying it to the existing book gives us:
  1. A clean performance baseline for every strategy in `strategies.yaml`,
     under today's fee schedule and slippage assumptions.
  2. Real per-strategy equity curves so Phase 1's correlation matrix can
     finally be computed (replacing the buy-and-hold proxy).
  3. A before/after comparison if any existing strategy is migrated to
     limit-mode execution (maker-preferred).

Scope of this V1 driver: runs the 8 "original architectures" from
strategy_lab/strategies.py under mode="v1" (market-next-bar-open, flat
0.1% fees) on BTC/ETH/SOL at 4h. Produces the same CSV schema as
run_phase5_matrix.py so the two outputs can be concatenated.

Extending to all 50 rows is mechanical: import the right function from
the V2/V3/.../V25 modules listed in `strategies.yaml` and add it to the
ROSTER below. Doing it incrementally preserves correctness — each
existing run has an authoritative legacy Sharpe to diff against.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "strategy_lab"))

import engine                                    # noqa: E402
from regime import classify_regime, REGIME_4H_PRESET  # noqa: E402
import eval as ev                                # noqa: E402
from run_phase5_matrix import score_run, OUTPUT_DIR, EQUITY_DIR  # noqa: E402  (EQUITY_DIR side-effect imports mkdir)

# ---------------------------------------------------------------------
# Roster — map existing strategies to runnable signal generators.
# Each entry: id → (timeframe, fn(df) -> dict[entries, exits])
# Extending to all 50 rows = adding imports + runners here.
# ---------------------------------------------------------------------
# The new `strategies/` package (adaptive) shadows the legacy single-file
# strategies.py module under the same name. Load legacy files by absolute
# path via importlib so both coexist.
import importlib.util as _il


def _load_module_from_path(name: str, path: Path):
    if not path.is_file():
        return None
    spec = _il.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        return None
    mod = _il.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        print(f"WARN: failed to load {name} from {path}: {e}")
        return None


_legacy_v1 = _load_module_from_path(
    "_legacy_strategies",    REPO / "strategy_lab" / "strategies.py",
)
_legacy_v2 = _load_module_from_path(
    "_legacy_strategies_v2", REPO / "strategy_lab" / "strategies_v2.py",
)

def _wrap_signals(fn):
    """Legacy signal generators return a dict or (entries, exits) tuple."""
    def runner(df):
        out = fn(df)
        if isinstance(out, tuple) and len(out) == 2:
            return {"entries": out[0], "exits": out[1]}
        return out
    return runner


# Strategy IDs are aligned with entries in docs/research/strategies.yaml.
ROSTER: dict[str, tuple[str, callable]] = {}

# -- strategies.py (8 original architectures, 4h)
if _legacy_v1 is not None:
    for name in [
        "ema_trend_adx", "donchian_breakout", "rsi_mean_reversion",
        "squeeze_breakout", "macd_htf", "supertrend",
        "gaussian_channel", "volume_breakout",
    ]:
        fn = getattr(_legacy_v1, name, None)
        if fn is not None:
            ROSTER[name] = ("4h", _wrap_signals(fn))

# -- strategies_v2.py (6 variants — trend-gated, ensemble, longer Donchian)
if _legacy_v2 is not None:
    for name in [
        "ema_trend_adx_v2", "volume_breakout_v2", "donchian_v2",
        "supertrend_v2", "ensemble_trend_vol", "gaussian_channel_v2",
    ]:
        fn = getattr(_legacy_v2, name, None)
        if fn is not None:
            ROSTER[name] = ("4h", _wrap_signals(fn))

# -- Auto-load every signal-compatible function from legacy_scan.json.
# The scanner (scan_legacy_strategies.py) smoke-tested each on synthetic
# OHLCV; we skip names already wired above, plus ICT/SMC sub-primitives
# from v38/v39 that return zone DataFrames rather than entry/exit bools.
import json as _json
_scan_path = REPO / "strategy_lab" / "legacy_scan.json"
_EXCLUDE_FNS = {
    # v38/v39 SMC primitives that return zone/event DataFrames, not signals
    "bos_recent", "fvg_recent", "liquidity_sweeps", "ob_zones",
    "smc_bos_series", "smc_ob_touch_zone",
}
if _scan_path.is_file():
    _scan = _json.loads(_scan_path.read_text(encoding="utf-8"))
    for row in _scan:
        file_stem = row["file"].replace(".py", "")
        fn_name = row["function"]
        if fn_name in ROSTER or fn_name in _EXCLUDE_FNS:
            continue
        # 15m timeframe for scalp files, else 4h
        tf = "15m" if "15m" in file_stem or "scalp" in file_stem else "4h"
        mod = _load_module_from_path(f"_scan_{file_stem}",
                                     REPO / "strategy_lab" / row["file"])
        if mod is None:
            continue
        fn = getattr(mod, fn_name, None)
        if fn is not None:
            ROSTER[fn_name] = (tf, _wrap_signals(fn))

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=SYMBOLS)
    parser.add_argument("--strategies", nargs="+", default=list(ROSTER.keys()))
    args = parser.parse_args(argv)

    if not ROSTER:
        print("No existing-book strategies wired up. See module docstring.")
        return 1

    rows = []
    cell = 0
    total = len(args.strategies) * len(args.symbols)

    for strategy_id in args.strategies:
        tf, signal_fn = ROSTER[strategy_id]
        for symbol in args.symbols:
            cell += 1
            print(f"[{cell}/{total}] {strategy_id} on {symbol} @ {tf} ... ",
                  end="", flush=True)
            try:
                df = engine.load(symbol, tf, start="2022-01-01", end="2024-12-31")
                sig = signal_fn(df)
                # Run under v1 (market, flat fees) for the legacy baseline.
                res = engine.run_backtest(
                    df,
                    entries=sig["entries"], exits=sig["exits"],
                    sl_stop=sig.get("sl_stop"), tsl_stop=sig.get("tsl_stop"),
                    tp_stop=sig.get("tp_stop"),
                )
                regime_df = classify_regime(df, config=REGIME_4H_PRESET)
                row = score_run(
                    strategy_id, symbol, tf, df, res, regime_df,
                    n_trials_for_dsr=max(total, 10),
                )
                row["execution_mode"] = "v1"
                rows.append(row)
                print(
                    f"n_trades={row['n_trades']:>3} | "
                    f"Sharpe_oos={row['oos_sharpe']:>+5.2f} | "
                    f"Calmar={row['oos_calmar']:>+5.2f} | "
                    f"MDD={row['oos_max_dd']*100:>+6.1f}% | "
                    f"gates={row['gates_passed']}/7"
                )
            except Exception as e:
                import traceback
                print(f"ERROR: {type(e).__name__}: {e}")
                if cell <= 2:  # only print traceback for first 2 to save context
                    traceback.print_exc()
                rows.append({"strategy_id": strategy_id, "symbol": symbol,
                             "tf": tf, "status": f"error: {e}"})

            # Incremental CSV write every 20 cells — so a process kill
            # mid-run still leaves a usable snapshot on disk.
            if cell % 20 == 0 or cell == total:
                try:
                    _snap = pd.DataFrame(rows)
                    import json as _json
                    for _col in ("regime_sharpes", "gate_detail",
                                 "monthly_returns", "yearly_returns"):
                        if _col in _snap.columns:
                            _snap[_col] = _snap[_col].apply(
                                lambda v: _json.dumps(v)
                                if isinstance(v, (dict, list)) else v
                            )
                    _snap.to_csv(OUTPUT_DIR / "phase5_existing_book_results.csv",
                                 index=False)
                except Exception:
                    pass

    df_out = pd.DataFrame(rows)
    import json
    for col in ("regime_sharpes", "gate_detail", "monthly_returns", "yearly_returns"):
        if col in df_out.columns:
            df_out[col] = df_out[col].apply(
                lambda v: json.dumps(v) if isinstance(v, (dict, list)) else v
            )
    csv_path = OUTPUT_DIR / "phase5_existing_book_results.csv"
    df_out.to_csv(csv_path, index=False)
    print(f"\nResults CSV: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
