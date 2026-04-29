"""
Discovery scanner — walks strategy_lab/*.py modules and identifies any
top-level function that behaves like a signal generator:

    fn(df: pd.DataFrame, ...) -> dict | tuple
      dict must contain 'entries' or 'exits' keys (bool Series)
      tuple must be length 2 of bool Series (legacy (entries, exits) form)

Safe-import each module; skip on exception. Smoke-call each candidate
with a 200-bar synthetic frame; if it returns a valid signal, record.

Output: strategy_lab/legacy_scan.json — the per-file discoveries.
The phase-5 existing-book runner will import from this manifest to
auto-wire everything.
"""
from __future__ import annotations

import contextlib
import importlib.util
import inspect
import io
import json
import os
import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
SCAN_OUT = REPO / "strategy_lab" / "legacy_scan.json"

# Files to skip — report builders, fetchers, harnesses, known bad.
SKIP_PATTERNS = (
    "build_", "fetch_", "analyze", "audit", "report", "dashboard",
    "alpha_analysis", "edge_hunt", "features_", "kronos_", "run_v37_claude",
    "live_forward", "iaf_multi", "native_to_iaf", "per_asset_report",
    "advanced_simulator", "hwr_hunt", "final_report", "detailed_metrics",
    "scan_legacy_strategies", "run_phase5_matrix", "run_phase5_existing_book",
    "run_phase55_robustness", "build_dashboard",
)


def make_smoke_df(n: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    idx = pd.date_range("2022-01-01", periods=n, freq="4h", tz="UTC")
    rets = rng.normal(0.001, 0.02, n)
    close = 30000 * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[close[0]], close[:-1]])
    spread = np.abs(rng.normal(0, 0.005, n))
    high = np.maximum(open_, close) * (1 + spread)
    low  = np.minimum(open_, close) * (1 - spread)
    volume = rng.lognormal(np.log(1e6), 0.3, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low,
         "close": close, "volume": volume},
        index=idx,
    )


def _looks_like_signal(obj) -> bool:
    """Validate a signal return: dict with entries/exits OR tuple of bool Series."""
    if isinstance(obj, dict):
        if "entries" in obj or "exits" in obj:
            for k in ("entries", "exits"):
                s = obj.get(k)
                if s is not None and not isinstance(s, pd.Series):
                    return False
            return True
        return False
    if isinstance(obj, tuple) and len(obj) == 2:
        return all(isinstance(x, pd.Series) for x in obj)
    return False


def _import_module_from_path(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    # Silence stdout / stderr during import (many scripts print on import).
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        spec.loader.exec_module(mod)
    return mod


def scan() -> list[dict]:
    discovered: list[dict] = []
    strategy_root = REPO / "strategy_lab"
    py_files = sorted(strategy_root.glob("*.py"))

    smoke_df = make_smoke_df()

    for path in py_files:
        name = path.stem
        if any(name.startswith(p) or p in name for p in SKIP_PATTERNS):
            continue
        if name.startswith("_") or name in ("engine",):
            continue

        try:
            mod = _import_module_from_path(path, f"_scan_{name}")
        except Exception:
            continue
        if mod is None:
            continue

        for attr_name in dir(mod):
            if attr_name.startswith("_"):
                continue
            try:
                fn = getattr(mod, attr_name)
            except Exception:
                continue
            if not inspect.isfunction(fn):
                continue
            if fn.__module__ != mod.__name__:
                continue                       # skip re-exports
            try:
                sig = inspect.signature(fn)
            except (TypeError, ValueError):
                continue
            params = list(sig.parameters.values())
            if not params:
                continue
            first = params[0]
            if first.name not in ("df", "ohlcv", "data"):
                continue

            # Try smoke-call with only the df positional — any other
            # required positional means signature isn't vanilla.
            has_other_required = any(
                p.default is inspect.Parameter.empty
                and p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                               inspect.Parameter.POSITIONAL_OR_KEYWORD)
                for p in params[1:]
            )
            if has_other_required:
                continue

            try:
                with contextlib.redirect_stdout(io.StringIO()), \
                     contextlib.redirect_stderr(io.StringIO()):
                    out = fn(smoke_df)
            except Exception:
                continue

            if _looks_like_signal(out):
                discovered.append({
                    "file":        path.name,
                    "function":    attr_name,
                    "qualified":   f"{path.stem}.{attr_name}",
                    "return_type": "dict" if isinstance(out, dict) else "tuple",
                })

    return discovered


def main():
    print("Scanning strategy_lab/ for signal-compatible functions ...")
    found = scan()
    SCAN_OUT.write_text(json.dumps(found, indent=2), encoding="utf-8")
    print(f"\nDiscovered {len(found)} signal-compatible functions:")
    by_file: dict[str, list[str]] = {}
    for row in found:
        by_file.setdefault(row["file"], []).append(row["function"])
    for file, fns in sorted(by_file.items()):
        print(f"  {file:<40} {fns}")
    print(f"\nManifest: {SCAN_OUT}")


if __name__ == "__main__":
    main()
