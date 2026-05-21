"""Grand confluence backtest — Phase 6 of CONFLUENCE_BUILD_PLAN_2026_05_07.md.

Combines all 4 layers (FLOW + STRUCTURE + TRIGGER + GUARD) via tier_classifier
and produces:
  - Per-cell, per-tier breakdown (n, hit, mean_pnl, p-value)
  - G3 gate verdict: GOLD vs BRONZE win-rate spread
  - Comparison to baseline momo

Runs independently of the universal "confluence is a layer ON momo" framing —
this version BOTH:
  (a) tests confluence as a momo refiner (tier filter on momo fires)
  (b) tests confluence as a STANDALONE signal (fire on tier!=SKIP from full active universe, direction = sign(flow_score) when flow dominant, sign(struct_score) otherwise)

Use SOL-only mode (--sol-only) to focus on the cell where FLOW G1 showed alpha.

Usage:
    py -X utf8 -m strategy_lab.confluence.run_grand_backtest [--sol-only]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from strategy_lab.meta_classifier.extended_backtest_with_robustness import (
    asof,
    load_universe,
    load_klines,
    load_tier1_entries,
    load_book_buckets,
    permutation_test,
    run_cell,
)
from strategy_lab.confluence.feature_join import apply_classifier, enrich_universe

OUT_DIR = ROOT / "strategy_lab" / "results" / "meta_classifier"
REPORT = ROOT / "strategy_lab" / "reports" / "CONFLUENCE_GRAND_BACKTEST_2026_05_07.md"


def _vec_asof(k1m: pd.DataFrame, ts_arr: np.ndarray) -> np.ndarray:
    """Vectorized end-time-indexed asof across many query timestamps.

    Replaces repeated `asof()` calls — each one allocated a 4 MiB temp.
    Computes the kline `end_us` array ONCE per asset and reuses it.
    """
    end_us = (k1m["ts_s"].to_numpy(dtype="int64") + 60) * 1_000_000
    target_us = ts_arr.astype("int64") * 1_000_000
    idx = np.searchsorted(end_us, target_us, side="right") - 1
    out = np.full(len(ts_arr), np.nan, dtype=float)
    valid = idx >= 0
    closes = k1m["price_close"].to_numpy(dtype=float)
    out[valid] = closes[idx[valid]]
    return out


def _fire_universe(assets: tuple[str, ...] = ("btc", "eth", "sol")):
    """Re-create the fired-momo universe (top-10% |ret_2m| per cell)."""
    uni = load_universe()
    klines = load_klines()
    for a in assets:
        m = uni.asset == a
        ws_arr = uni.loc[m, "window_start_unix"].astype("int64").to_numpy()
        p0 = _vec_asof(klines[a], ws_arr)
        p2 = _vec_asof(klines[a], ws_arr + 120)
        with np.errstate(divide="ignore", invalid="ignore"):
            uni.loc[m, "asset_ret_2m"] = np.log(p2 / p0)
    active = uni[uni["asset_ret_2m"].notna() & np.isfinite(uni["asset_ret_2m"])].copy()
    entry_books  = {a: load_tier1_entries(a) for a in assets}
    bucket_books = {a: load_book_buckets(a)  for a in assets}

    fired = []
    for a in assets:
        for tf in ("5m", "15m"):
            sub = active[(active.asset == a) & (active.timeframe == tf)].copy()
            if len(sub) < 50:
                continue
            thr = sub["asset_ret_2m"].abs().quantile(0.90)
            f = sub[sub["asset_ret_2m"].abs() >= thr].copy()
            f["signal"] = (f["asset_ret_2m"] > 0).astype(int)
            fired.append(f)
    fired_all = pd.concat(fired, ignore_index=True)
    return active, fired_all, klines, entry_books, bucket_books


def _backtest_subset(sub: pd.DataFrame, klines, entry_books, bucket_books, label: str, asset: str) -> dict:
    if len(sub) == 0:
        return {"label": label, "n": 0}
    return run_cell(sub, klines[asset], entry_books[asset], bucket_books[asset],
                     "HOLD", label, asset)


def _per_cell_per_tier(fired_classified: pd.DataFrame, klines, entry_books, bucket_books) -> pd.DataFrame:
    rows = []
    for asset in fired_classified["asset"].unique():
        for tf in fired_classified["timeframe"].unique():
            sub_cell = fired_classified[(fired_classified.asset == asset) & (fired_classified.timeframe == tf)]
            if len(sub_cell) == 0:
                continue
            cell = f"{asset.upper()}_{tf}"
            # Baseline (all momo fires, ignoring confluence)
            baseline = _backtest_subset(sub_cell, klines, entry_books, bucket_books,
                                         f"{cell}_BASELINE", asset)
            rows.append({
                "cell": cell, "tier": "BASELINE_MOMO",
                "n": baseline.get("n", 0),
                "hit": baseline.get("hit", 0.0),
                "pnl_mean": baseline.get("pnl_mean", 0.0),
                "pnl_total": baseline.get("pnl_total", 0.0),
            })
            for tier in ("GOLD", "SILVER", "BRONZE"):
                sub_tier = sub_cell[sub_cell["tier"] == tier]
                r = _backtest_subset(sub_tier, klines, entry_books, bucket_books,
                                     f"{cell}_{tier}", asset)
                p_val = float("nan")
                if r.get("n", 0) > 30:
                    rng = np.random.default_rng(hash((asset, tf, tier)) % (2**32))
                    perm = permutation_test(r.get("per_trade", []), n_permutations=1000, rng=rng)
                    p_val = perm["p_value"]
                rows.append({
                    "cell": cell, "tier": tier,
                    "n": r.get("n", 0),
                    "hit": r.get("hit", 0.0),
                    "pnl_mean": r.get("pnl_mean", 0.0),
                    "pnl_total": r.get("pnl_total", 0.0),
                    "p_value": p_val,
                })
            # SKIP cell stats (sanity)
            sub_skip = sub_cell[sub_cell["tier"] == "SKIP"]
            r = _backtest_subset(sub_skip, klines, entry_books, bucket_books,
                                 f"{cell}_SKIP", asset)
            rows.append({
                "cell": cell, "tier": "SKIP",
                "n": r.get("n", 0),
                "hit": r.get("hit", 0.0),
                "pnl_mean": r.get("pnl_mean", 0.0),
                "pnl_total": r.get("pnl_total", 0.0),
            })
    return pd.DataFrame(rows)


def _g3_gate(per_tier: pd.DataFrame) -> dict:
    """GOLD vs BRONZE win-rate spread should be ≥ 8pp."""
    pivot = per_tier[per_tier["tier"].isin(["GOLD", "BRONZE"])].pivot_table(
        index="cell", columns="tier", values=["n", "hit"], aggfunc="first"
    )
    cells_with_both = []
    for cell in pivot.index:
        try:
            g_n = pivot.loc[cell, ("n", "GOLD")]
            b_n = pivot.loc[cell, ("n", "BRONZE")]
            g_hit = pivot.loc[cell, ("hit", "GOLD")]
            b_hit = pivot.loc[cell, ("hit", "BRONZE")]
            if pd.notna(g_n) and pd.notna(b_n) and g_n >= 20 and b_n >= 20:
                cells_with_both.append({
                    "cell": cell, "gold_n": int(g_n), "bronze_n": int(b_n),
                    "gold_hit": float(g_hit), "bronze_hit": float(b_hit),
                    "spread_pp": float((g_hit - b_hit) * 100),
                })
        except KeyError:
            continue
    if not cells_with_both:
        return {"pass": False, "reason": "insufficient samples in GOLD or BRONZE", "data": []}
    avg_spread = float(np.mean([c["spread_pp"] for c in cells_with_both]))
    return {
        "pass": avg_spread >= 8.0,
        "avg_spread_pp": avg_spread,
        "cells": cells_with_both,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sol-only", action="store_true",
                    help="Restrict to SOL (where G1 found FLOW alpha)")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    assets = ("sol",) if args.sol_only else ("btc", "eth", "sol")
    print(f"[grand] assets: {assets}")

    print("[grand] loading universe + firing momo…")
    active, fired, klines, entry_books, bucket_books = _fire_universe(assets)
    print(f"[grand] fired: {len(fired)} markets")

    print("[grand] enriching with all 4 layers…")
    enriched = enrich_universe(fired)
    classified = apply_classifier(enriched)

    print("[grand] tier breakdown of fired universe:")
    print(classified["tier"].value_counts().to_string())

    print("\n[grand] per-cell per-tier backtest (HOLD policy)…")
    per_tier = _per_cell_per_tier(classified, klines, entry_books, bucket_books)
    out_csv = OUT_DIR / ("confluence_grand_sol.csv" if args.sol_only else "confluence_grand_all.csv")
    per_tier.to_csv(out_csv, index=False)
    print(f"[grand] wrote {out_csv}")
    print(per_tier.to_string(index=False))

    g3 = _g3_gate(per_tier)
    print(f"\n[grand] G3 gate (GOLD vs BRONZE WR spread ≥ 8pp): "
          f"{'PASS' if g3.get('pass') else 'FAIL'} (avg_spread={g3.get('avg_spread_pp', 0):.1f}pp)")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    L = [
        "# Confluence Grand Backtest",
        "",
        "**Date:** 2026-05-07",
        f"**Mode:** {'SOL-only' if args.sol_only else 'all assets'}",
        "",
        "## Tier breakdown",
        "",
        "```",
        classified["tier"].value_counts().to_string(),
        "```",
        "",
        "## Per-cell, per-tier results",
        "",
        per_tier.to_markdown(index=False) if not per_tier.empty else "(no data)",
        "",
        "## G3 gate",
        "",
        f"- Average GOLD vs BRONZE win-rate spread: {g3.get('avg_spread_pp', 0):.1f}pp (bar: ≥8pp)",
        f"- Verdict: **{'PASS' if g3.get('pass') else 'FAIL'}**",
        "",
    ]
    if g3.get("cells"):
        L.append("Cells with both GOLD and BRONZE samples:\n")
        L.append(pd.DataFrame(g3["cells"]).to_markdown(index=False))
    REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"\n[grand] wrote report {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
