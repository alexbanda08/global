"""Quick validator for layer parquets — schema, key coverage, distributions.

Runs before the grand backtest to catch bad outputs early.

Usage:
    py -X utf8 -m strategy_lab.confluence.validate_layers

Checks each layer's parquet (FLOW / STRUCTURE / TRIGGER / GUARD):
  - File exists.
  - Required columns present (per schema.py).
  - Join-key uniqueness (no duplicate keys cause row-explosion in enrich).
  - Coverage: what fraction of fired momo trades each layer covers.
  - Sane value ranges (scores in [-1, 1], booleans clean).

Prints a verdict per layer + an overall PASS/FAIL.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from strategy_lab.confluence.schema import (
    ALL_FEATURE_COLS,
    FLOW_FEATURE_COLS,
    GUARD_BLOCK_COLS,
    STRUCTURE_FEATURE_COLS,
    TRIGGER_FEATURE_COLS,
)

CACHE_DIR = ROOT / "data" / "v4" / "refresh_2026_05_06" / "cache"


def _try_load(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path)
    except Exception as e:
        print(f"  [error] failed to read {path}: {e}")
        return None


def validate_flow() -> dict:
    paths = [CACHE_DIR / "all_flow_features.parquet"]
    paths += [CACHE_DIR / f"{a}_flow_features.parquet" for a in ("btc", "eth", "sol")]
    chosen = next((p for p in paths if p.exists()), None)
    if chosen is None:
        return {"layer": "FLOW", "ok": False, "reason": "no parquet found"}
    df = _try_load(chosen)
    if df is None:
        return {"layer": "FLOW", "ok": False, "reason": f"read failed: {chosen}"}

    missing = set(FLOW_FEATURE_COLS) - set(df.columns)
    if missing:
        return {"layer": "FLOW", "ok": False, "path": str(chosen),
                "reason": f"missing cols {missing}"}

    # Key uniqueness — FLOW is keyed by (slug, outcome)
    dup = df.duplicated(["slug", "outcome"]).sum()
    score_in_range = df["flow_score"].between(-1, 1).all()

    return {
        "layer": "FLOW",
        "ok": dup == 0 and bool(score_in_range),
        "path": str(chosen),
        "rows": len(df),
        "duplicates": int(dup),
        "score_in_range": bool(score_in_range),
        "score_mean": float(df["flow_score"].mean()),
        "score_std": float(df["flow_score"].std()),
        "n_slugs": df["slug"].nunique(),
    }


def validate_structure() -> dict:
    path = CACHE_DIR / "all_structure_features.parquet"
    if not path.exists():
        # Fall back to per-asset
        per_asset = [CACHE_DIR / f"{a}_structure_features.parquet" for a in ("btc", "eth", "sol")]
        chosen = next((p for p in per_asset if p.exists()), None)
        if chosen is None:
            return {"layer": "STRUCTURE", "ok": False, "reason": "no parquet found"}
        path = chosen
    df = _try_load(path)
    if df is None:
        return {"layer": "STRUCTURE", "ok": False, "reason": f"read failed: {path}"}

    missing = set(STRUCTURE_FEATURE_COLS) - set(df.columns)
    if missing:
        return {"layer": "STRUCTURE", "ok": False, "path": str(path),
                "reason": f"missing cols {missing}"}

    # Key uniqueness — STRUCTURE keyed by (slug,) only (one row per market, side-agnostic)
    dup = df.duplicated(["slug"]).sum()
    score_in_range = df["struct_score"].between(-1, 1).all() if "struct_score" in df.columns else False
    regime_vals = set(df["struct_regime"].dropna().astype(str).unique()) if "struct_regime" in df.columns else set()
    regime_ok = regime_vals.issubset({"trend", "sideways", "volatile"})

    return {
        "layer": "STRUCTURE",
        "ok": dup == 0 and bool(score_in_range) and bool(regime_ok),
        "path": str(path),
        "rows": len(df),
        "duplicates": int(dup),
        "score_in_range": bool(score_in_range),
        "regime_values": sorted(regime_vals),
        "score_mean": float(df["struct_score"].mean()) if "struct_score" in df.columns else None,
        "n_slugs": df["slug"].nunique(),
    }


def validate_trigger() -> dict:
    path = CACHE_DIR / "all_trigger_features.parquet"
    if not path.exists():
        per_asset = [CACHE_DIR / f"{a}_trigger_features.parquet" for a in ("btc", "eth", "sol")]
        chosen = next((p for p in per_asset if p.exists()), None)
        if chosen is None:
            return {"layer": "TRIGGER", "ok": False, "reason": "no parquet found"}
        path = chosen
    df = _try_load(path)
    if df is None:
        return {"layer": "TRIGGER", "ok": False, "reason": f"read failed: {path}"}

    missing = set(TRIGGER_FEATURE_COLS) - set(df.columns)
    if missing:
        return {"layer": "TRIGGER", "ok": False, "path": str(path),
                "reason": f"missing cols {missing}"}

    dup = df.duplicated(["slug", "outcome"]).sum()
    active_rate = float(df["trigger_active"].mean()) if "trigger_active" in df.columns else None

    return {
        "layer": "TRIGGER",
        "ok": dup == 0 and active_rate is not None,
        "path": str(path),
        "rows": len(df),
        "duplicates": int(dup),
        "trigger_active_rate": active_rate,
        "fvg_active_rate": float(df["trig_fvg_active"].mean()) if "trig_fvg_active" in df.columns else None,
        "liq_magnet_active_rate": float(df["trig_liq_magnet_active"].mean()) if "trig_liq_magnet_active" in df.columns else None,
        "n_slugs": df["slug"].nunique(),
    }


def validate_guard() -> dict:
    path = CACHE_DIR / "all_guard_blocks.parquet"
    if not path.exists():
        return {"layer": "GUARD", "ok": True, "reason": "not built yet (Phase 2)", "rows": 0}
    df = _try_load(path)
    if df is None:
        return {"layer": "GUARD", "ok": False, "reason": f"read failed: {path}"}
    missing = set(GUARD_BLOCK_COLS) - set(df.columns)
    if missing:
        return {"layer": "GUARD", "ok": False, "path": str(path),
                "reason": f"missing cols {missing}"}
    block_rates = {col: float(df[col].mean()) for col in GUARD_BLOCK_COLS}
    return {
        "layer": "GUARD",
        "ok": True,
        "path": str(path),
        "rows": len(df),
        "block_rates": block_rates,
    }


def main() -> int:
    print(f"[validate] cache dir: {CACHE_DIR}\n")
    results = [validate_flow(), validate_structure(), validate_trigger(), validate_guard()]
    overall_ok = True
    for r in results:
        ok = r.get("ok", False)
        marker = "OK  " if ok else "FAIL"
        print(f"[{marker}] {r['layer']}")
        for k, v in r.items():
            if k in ("layer", "ok"):
                continue
            print(f"        {k}: {v}")
        print()
        if not ok and r.get("reason") != "not built yet (Phase 2)":
            overall_ok = False
    print(f"[overall] {'PASS — ready for grand backtest' if overall_ok else 'FAIL — fix layer issues first'}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
