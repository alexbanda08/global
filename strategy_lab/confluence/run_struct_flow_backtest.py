"""Simplified 2-tier confluence — STRUCTURE + FLOW agreement only.

Drops TRIGGER and GUARD from the gate. Two tiers: SILVER (both layers aligned
with held side) or SKIP. This implements option (c) of the verdict report:
the cleanest variant after grand backtest showed TRIGGER doesn't differentiate.

Tier rule:
  SILVER iff:
    - flow_score available and >= 0.40
    - struct_score available and >= 0.30
    - both signs aligned with the held outcome direction
      (signal=1 ↔ Up: positive scores agree; signal=0 ↔ Down: negative scores agree)
  else SKIP

Usage:
    py -X utf8 -m strategy_lab.confluence.run_struct_flow_backtest
    py -X utf8 -m strategy_lab.confluence.run_struct_flow_backtest --sol-eth-only
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
    load_universe,
    load_klines,
    load_tier1_entries,
    load_book_buckets,
    permutation_test,
    run_cell,
)
from strategy_lab.confluence.feature_join import enrich_universe
from strategy_lab.confluence.run_grand_backtest import _vec_asof

OUT_DIR = ROOT / "strategy_lab" / "results" / "meta_classifier"
REPORT = ROOT / "strategy_lab" / "reports" / "STRUCT_FLOW_BACKTEST_2026_05_07.md"

STRUCT_MIN = 0.30
FLOW_MIN = 0.40


def _classify_struct_flow(row: pd.Series, struct_min: float, flow_min: float) -> str:
    """Return 'SILVER' or 'SKIP' for a single fired row."""
    s = row.get("struct_score")
    f = row.get("flow_score")
    if pd.isna(s) or pd.isna(f):
        return "SKIP"
    sig = int(row["signal"])
    sig_dir = 1 if sig == 1 else -1
    s_aligned = (abs(s) >= struct_min) and (np.sign(s) == sig_dir)
    f_aligned = (abs(f) >= flow_min) and (np.sign(f) == sig_dir)
    return "SILVER" if (s_aligned and f_aligned) else "SKIP"


def _fire_universe(assets: tuple[str, ...]):
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

    fired_all = pd.concat(fired, ignore_index=True) if fired else pd.DataFrame()
    entry_books  = {a: load_tier1_entries(a) for a in assets}
    bucket_books = {a: load_book_buckets(a)  for a in assets}
    return fired_all, klines, entry_books, bucket_books


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sol-eth-only", action="store_true",
                    help="Restrict to SOL+ETH (drop BTC, where SILVER showed no edge)")
    ap.add_argument("--struct-min", type=float, default=STRUCT_MIN)
    ap.add_argument("--flow-min", type=float, default=FLOW_MIN)
    args = ap.parse_args()

    struct_min = args.struct_min
    flow_min = args.flow_min

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    assets = ("eth", "sol") if args.sol_eth_only else ("btc", "eth", "sol")
    print(f"[sf] assets={assets}  struct_min={struct_min}  flow_min={flow_min}")
    fired, klines, entry_books, bucket_books = _fire_universe(assets)
    print(f"[sf] fired: {len(fired)}")

    enriched = enrich_universe(fired)
    enriched["sf_tier"] = enriched.apply(
        lambda row: _classify_struct_flow(row, struct_min, flow_min), axis=1
    )
    counts = enriched["sf_tier"].value_counts().to_dict()
    print(f"[sf] tier counts: {counts}")

    rows = []
    for a in assets:
        for tf in ("5m", "15m"):
            cell = f"{a.upper()}_{tf}"
            sub_cell = enriched[(enriched.asset == a) & (enriched.timeframe == tf)]
            if len(sub_cell) == 0:
                continue
            baseline = run_cell(sub_cell, klines[a], entry_books[a], bucket_books[a],
                                 "HOLD", f"{cell}_BASELINE", a)
            silver = sub_cell[sub_cell["sf_tier"] == "SILVER"]
            r = run_cell(silver, klines[a], entry_books[a], bucket_books[a],
                          "HOLD", f"{cell}_SILVER", a) if len(silver) else {"n": 0}
            p_val = float("nan")
            if r.get("n", 0) > 30:
                rng = np.random.default_rng(hash((a, tf, "sf")) % (2**32))
                p = permutation_test(r.get("per_trade", []), n_permutations=1000, rng=rng)
                p_val = p["p_value"]
            rows.append({
                "cell": cell,
                "n_baseline": baseline.get("n", 0),
                "hit_baseline": baseline.get("hit", 0.0),
                "mean_baseline": baseline.get("pnl_mean", 0.0),
                "n_silver": r.get("n", 0),
                "hit_silver": r.get("hit", 0.0),
                "mean_silver": r.get("pnl_mean", 0.0),
                "total_silver": r.get("pnl_total", 0.0),
                "lift_pp": (r.get("hit", 0.0) - baseline.get("hit", 0.0)) * 100,
                "p_value": p_val,
            })
    df = pd.DataFrame(rows)
    csv_path = OUT_DIR / "struct_flow_backtest.csv"
    df.to_csv(csv_path, index=False)
    print(f"[sf] wrote {csv_path}")
    print(df.to_string(index=False))

    # Combined SOL+ETH_15m where SILVER concentrates alpha
    silver_rows = enriched[enriched["sf_tier"] == "SILVER"]
    if len(silver_rows) > 0:
        focus = silver_rows[
            ((silver_rows.asset == "sol") & silver_rows.timeframe.isin(["5m", "15m"]))
            | ((silver_rows.asset == "eth") & (silver_rows.timeframe == "15m"))
        ]
        per_trade_focus = []
        for a in ("eth", "sol"):
            sub = focus[focus.asset == a]
            if len(sub) == 0:
                continue
            r = run_cell(sub, klines[a], entry_books[a], bucket_books[a],
                          "HOLD", f"FOCUS_{a}", a)
            per_trade_focus.extend(r.get("per_trade", []))
        if per_trade_focus:
            pnls = np.array([t["pnl"] for t in per_trade_focus])
            print(f"\n[sf] FOCUS SOL+ETH_15m SILVER: n={len(pnls)} hit={(pnls>0).mean()*100:.1f}% mean=${pnls.mean():+.4f} total=${pnls.sum():+.2f}")
            rng = np.random.default_rng(42)
            p = permutation_test(per_trade_focus, n_permutations=1000, rng=rng)
            print(f"[sf] FOCUS perm p_value={p['p_value']:.4f}")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    L = [
        "# Struct+Flow Backtest (TRIGGER dropped — option C)",
        "",
        "**Date:** 2026-05-07",
        f"**Mode:** {'SOL+ETH only' if args.sol_eth_only else 'all assets'}",
        f"**Thresholds:** struct_min={STRUCT_MIN}, flow_min={FLOW_MIN}",
        "",
        "## Tier counts",
        "",
        "```",
        str(counts),
        "```",
        "",
        "## Per-cell SILVER vs baseline momo",
        "",
        df.to_markdown(index=False) if not df.empty else "(no data)",
        "",
        "## Notes",
        "",
        "- TRIGGER dropped: this isolates the STRUCT+FLOW agreement signal",
        "- SKIP fires when either layer is missing or sign-misaligned with held side",
        "- Sample size still bottleneck (n<80 per cell over Apr-May)",
    ]
    REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"[sf] wrote {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
