"""Confluence sleeve runner — wraps `extended_backtest_with_robustness.run_cell`.

This is the bridge between the existing momo backtest engine and the new
4-layer confluence stack. It does NOT duplicate the simulator — it filters
and re-sizes the universe BEFORE delegating to the existing `simulate()`.

Phase 0 contract:
  When `enable_confluence=False` → identical behavior to vanilla `run_cell`.
  When `enable_confluence=True`  → enrich universe, apply classifier,
    drop SKIP rows, scale per-row stake, then delegate.

Sizing model:
  Each tier has a `size_pct` of bankroll. We pass that into a per-row
  `notional_usd` override so `simulate()` walks the book for the right
  USD amount. Existing fixed `NOTIONAL_USD = $25` becomes the SILVER baseline
  at bankroll=$1250 (1.5% × $1250 = $18.75) — close enough; tune in Phase 5.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import sys
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))

from strategy_lab.confluence.feature_join import (
    apply_classifier,
    enrich_universe,
    summarize,
)
from strategy_lab.confluence.schema import BANKROLL_DEFAULT


def run_confluence_cell(
    df: pd.DataFrame,
    k1m: pd.DataFrame,
    entry_book: dict,
    bucket_book: dict,
    policy: str,
    label: str,
    asset: str,
    *,
    enable_confluence: bool = True,
    bankroll_usd: float = BANKROLL_DEFAULT,
    feature_paths: dict[str, Path] | None = None,
) -> dict:
    """Drop-in replacement for `run_cell` that applies the confluence stack.

    Args mirror `extended_backtest_with_robustness.run_cell` plus:
      enable_confluence: when False, this is a passthrough (returns vanilla
        run_cell result for an apples-to-apples baseline).
      bankroll_usd: per-sleeve bankroll for size_pct → USD conversion.
      feature_paths: optional layer parquet path overrides; see feature_join.

    Returns the same dict shape as `run_cell`, plus:
      tier_breakdown: {"GOLD": {n, hit, mean_pnl}, "SILVER": ..., "BRONZE": ...}
      skip_count: int
      enrichment_summary: dict from feature_join.summarize()
    """
    # Lazy import — avoids circular when this module is imported by the engine
    from strategy_lab.meta_classifier.extended_backtest_with_robustness import run_cell

    if not enable_confluence:
        return run_cell(df, k1m, entry_book, bucket_book, policy, label, asset)

    # 1. Enrich universe with all 4 layer parquets
    df_enriched = enrich_universe(df, feature_paths=feature_paths)

    # 2. Apply classifier → tier per row
    df_classified = apply_classifier(df_enriched, bankroll_usd=bankroll_usd)
    enrich_stats = summarize(df_classified)

    # 3. Drop SKIPs
    fired = df_classified[df_classified["tier"] != "SKIP"].copy()
    skip_count = int((df_classified["tier"] == "SKIP").sum())

    if len(fired) == 0:
        return dict(
            label=label,
            n=0,
            wins=0,
            tier_breakdown={},
            skip_count=skip_count,
            enrichment_summary=enrich_stats,
            note="all rows classified SKIP",
        )

    # 4. Per-tier sub-cells (so we can report tier breakdown for G3 gate)
    tier_results: dict[str, dict] = {}
    all_pnls: list[float] = []
    all_per_trade: list[dict] = []
    for tier_name in ("GOLD", "SILVER", "BRONZE"):
        sub = fired[fired["tier"] == tier_name]
        if len(sub) == 0:
            continue
        # Note: vanilla run_cell uses fixed NOTIONAL_USD. For Phase 0 passthrough
        # we run each tier through run_cell unchanged — sizing override goes in
        # Phase 5 when we wire dynamic notional. Document this clearly.
        sub_label = f"{label}__{tier_name}"
        r = run_cell(sub, k1m, entry_book, bucket_book, policy, sub_label, asset)
        tier_results[tier_name] = {
            "n": r["n"],
            "hit": r.get("hit", 0.0),
            "pnl_total": r.get("pnl_total", 0.0),
            "pnl_mean": r.get("pnl_mean", 0.0),
            "size_pct": float(sub["size_pct"].iloc[0]),  # all same within tier
            "target_stake_usd": float(sub["target_stake_usd"].iloc[0]),
        }
        # Accumulate
        for trade in r.get("per_trade", []):
            trade = dict(trade)
            trade["tier"] = tier_name
            all_per_trade.append(trade)
            all_pnls.append(trade["pnl"])

    if not all_pnls:
        return dict(
            label=label,
            n=0,
            wins=0,
            tier_breakdown=tier_results,
            skip_count=skip_count,
            enrichment_summary=enrich_stats,
        )

    pnls = np.array(all_pnls)
    n = len(pnls)
    return dict(
        label=label,
        n=n,
        wins=int(sum(1 for t in all_per_trade
                     if int(t["signal"]) == int(t["outcome_up"]))),
        hit=float((pnls > 0).mean()),
        pnl_total=float(pnls.sum()),
        pnl_mean=float(pnls.mean()),
        pnl_std=float(pnls.std()),
        tier_breakdown=tier_results,
        skip_count=skip_count,
        enrichment_summary=enrich_stats,
        per_trade=all_per_trade,
    )


def diagnose_no_op(df: pd.DataFrame) -> dict[str, Any]:
    """Phase 0 sanity check.

    With no layer parquets present, `enrich_universe` returns NaN features and
    `classify` returns SKIP for everything. Use this in tests to confirm the
    skeleton wires correctly.
    """
    enriched = enrich_universe(df)
    classified = apply_classifier(enriched)
    return summarize(classified)
