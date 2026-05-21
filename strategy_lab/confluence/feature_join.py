"""Feature-join adapter — enrich a momo universe DataFrame with confluence features.

Phase 0 contract: given the universe `df` produced by `extended_backtest_with_robustness.load_universe()`
plus a feature-source-paths dict, return a copy of `df` with all confluence
feature columns populated (NaN where source data is missing).

Then `apply_classifier(df_enriched)` adds tier columns by calling the classifier per row.

Phase 1-4 each plug in by writing parquet files at the agreed paths and this
module loads them — no engine code changes required after Phase 0.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from strategy_lab.confluence.schema import (
    ALL_FEATURE_COLS,
    BANKROLL_DEFAULT,
    CONTRACT,
    FLOW_FEATURE_COLS,
    GUARD_BLOCK_COLS,
    STRUCTURE_FEATURE_COLS,
    TRIGGER_FEATURE_COLS,
)
from strategy_lab.confluence.tier_classifier import classify

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
DEFAULT_FEATURE_DIR = ROOT / "data" / "v4" / "refresh_2026_05_06" / "cache"


def _empty_features_df(index: pd.Index) -> pd.DataFrame:
    """All-NaN feature dataframe matching ALL_FEATURE_COLS shape."""
    out = pd.DataFrame(index=index)
    for col in FLOW_FEATURE_COLS + STRUCTURE_FEATURE_COLS + TRIGGER_FEATURE_COLS:
        out[col] = np.nan
    for col in GUARD_BLOCK_COLS:
        out[col] = False
    return out


def _load_layer_parquet(path: Path) -> pd.DataFrame | None:
    """Best-effort load. Missing file → None (caller treats as 'layer not built yet')."""
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path)
    except Exception as e:
        print(f"[feature_join] WARN failed to read {path}: {e}")
        return None


def enrich_universe(
    df: pd.DataFrame,
    feature_paths: dict[str, Path] | None = None,
    feature_dir: Path = DEFAULT_FEATURE_DIR,
) -> pd.DataFrame:
    """Join confluence feature parquets onto the momo universe `df`.

    Args:
      df: the momo universe (must contain CONTRACT.required_input_cols).
      feature_paths: optional explicit path overrides per layer:
        {"flow": Path(...), "structure": Path(...), "trigger": Path(...),
         "guard": Path(...)}
        Each parquet must be keyed by (slug, window_start_unix) so a left-join
        works cleanly. Missing layers → NaN columns (treated as SKIP downstream).
      feature_dir: default directory to look in if `feature_paths` not given.

    Returns:
      Copy of df with ALL_FEATURE_COLS appended. Original columns untouched.
    """
    missing = set(CONTRACT.required_input_cols) - set(df.columns)
    if missing:
        raise ValueError(f"enrich_universe: input df missing columns {missing}")

    out = df.copy()
    fpaths = feature_paths or {}

    # Derive held_outcome from signal (1→Up, 0→Down). Required for FLOW + TRIGGER
    # joins that are keyed by (slug, outcome). If signal column missing (Phase 0
    # diagnostic mode), default to 'Up' for join shape only — features will land
    # on the same key, but the data is meaningful only when signal is present.
    if "signal" in out.columns:
        out["held_outcome"] = np.where(out["signal"].astype(int) == 1, "Up", "Down")
    else:
        out["held_outcome"] = "Up"

    # --- FLOW ----------------------------------------------------------------
    # Per-asset parquets get joined first if they exist; falls back to merged "all_flow".
    flow_path = fpaths.get("flow", feature_dir / "all_flow_features.parquet")
    flow_df = _load_layer_parquet(flow_path)
    if flow_df is None:
        # Try per-asset concat fallback (build can produce these before merge step)
        per_asset = []
        for a in ("btc", "eth", "sol"):
            ap = feature_dir / f"{a}_flow_features.parquet"
            sub = _load_layer_parquet(ap)
            if sub is not None:
                per_asset.append(sub)
        if per_asset:
            flow_df = pd.concat(per_asset, ignore_index=True)

    if flow_df is not None:
        # Join on (slug, held_outcome) where parquet has 'outcome'
        flow_subset = flow_df[["slug", "outcome", *FLOW_FEATURE_COLS]].rename(
            columns={"outcome": "held_outcome"}
        )
        out = out.merge(flow_subset, on=["slug", "held_outcome"], how="left")
    else:
        for col in FLOW_FEATURE_COLS:
            out[col] = np.nan

    # --- STRUCTURE ----------------------------------------------------------
    struct_path = fpaths.get("structure", feature_dir / "all_structure_features.parquet")
    struct_df = _load_layer_parquet(struct_path)
    if struct_df is not None:
        out = out.merge(
            struct_df[["slug", "window_start_unix", *STRUCTURE_FEATURE_COLS]],
            on=["slug", "window_start_unix"],
            how="left",
        )
    else:
        for col in STRUCTURE_FEATURE_COLS:
            out[col] = np.nan

    # --- TRIGGER ------------------------------------------------------------
    # TRIGGER is keyed by (slug, outcome) like FLOW — OFI is direction-conditional.
    trig_path = fpaths.get("trigger", feature_dir / "all_trigger_features.parquet")
    trig_df = _load_layer_parquet(trig_path)
    if trig_df is not None:
        trig_subset = trig_df[["slug", "outcome", *TRIGGER_FEATURE_COLS]].rename(
            columns={"outcome": "held_outcome"}
        )
        out = out.merge(trig_subset, on=["slug", "held_outcome"], how="left")
    else:
        for col in TRIGGER_FEATURE_COLS:
            out[col] = np.nan

    # --- GUARD --------------------------------------------------------------
    guard_path = fpaths.get("guard", feature_dir / "all_guard_blocks.parquet")
    guard_df = _load_layer_parquet(guard_path)
    if guard_df is not None:
        out = out.merge(
            guard_df[["slug", "window_start_unix", *GUARD_BLOCK_COLS]],
            on=["slug", "window_start_unix"],
            how="left",
        )
        # missing guard rows → no block (False)
        for col in GUARD_BLOCK_COLS:
            out[col] = out[col].fillna(False).astype(bool)
    else:
        for col in GUARD_BLOCK_COLS:
            out[col] = False

    # Sanity: no row duplication from joins
    if len(out) != len(df):
        raise RuntimeError(
            f"enrich_universe: row count changed {len(df)} → {len(out)} "
            f"— check feature parquets for duplicate (slug, ws) keys"
        )
    return out


def apply_classifier(df: pd.DataFrame, bankroll_usd: float = BANKROLL_DEFAULT) -> pd.DataFrame:
    """Add tier columns to an enriched universe by calling classify() per row.

    Adds: tier, fair_prob, size_pct, skip_reasons, target_stake_usd.
    """
    missing = set(ALL_FEATURE_COLS) - set(df.columns)
    if missing:
        raise ValueError(f"apply_classifier: df missing feature columns {missing} — call enrich_universe first")

    out = df.copy()
    tiers, probs, sizes, reasons, stakes = [], [], [], [], []
    for _, row in out.iterrows():
        guards_active = [g for g in GUARD_BLOCK_COLS if bool(row[g])]
        tr = classify(
            structure_score=row["struct_score"] if pd.notna(row["struct_score"]) else None,
            flow_score=row["flow_score"] if pd.notna(row["flow_score"]) else None,
            trigger_active=bool(row["trigger_active"]) if pd.notna(row["trigger_active"]) else None,
            guard_blocks=guards_active,
        )
        tiers.append(tr["tier"])
        probs.append(tr["fair_prob"])
        sizes.append(tr["size_pct"])
        reasons.append(",".join(tr["skip_reasons"]))
        stakes.append(bankroll_usd * tr["size_pct"])

    out["tier"] = tiers
    out["fair_prob"] = probs
    out["size_pct"] = sizes
    out["skip_reasons"] = reasons
    out["target_stake_usd"] = stakes
    return out


def summarize(df_enriched: pd.DataFrame) -> dict:
    """Quick stats for sanity-checking enrichment + classification."""
    if "tier" not in df_enriched.columns:
        return {"error": "df not classified — call apply_classifier first"}
    counts = df_enriched["tier"].value_counts().to_dict()
    return {
        "total_rows": len(df_enriched),
        "tier_counts": counts,
        "skip_rate": counts.get("SKIP", 0) / max(len(df_enriched), 1),
        "fire_rate": 1.0 - counts.get("SKIP", 0) / max(len(df_enriched), 1),
        "feature_coverage": {
            "flow_score":   df_enriched["flow_score"].notna().mean(),
            "struct_score": df_enriched["struct_score"].notna().mean(),
            "trigger_active": df_enriched["trigger_active"].notna().mean(),
        },
    }
