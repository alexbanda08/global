"""MICRO tier backtest — SOL universe only.

Tests two new tiers against SILVER baseline on SOL confluence sleeve.

Tier hierarchy (precedence order):
  SILVER      = both layers sign-aligned AND struct_signed >= 0.30 AND flow_signed >= 0.40
  MICRO       = sign-aligned with EITHER struct_signed >= 0.20 OR flow_signed >= 0.30, NOT SILVER
  MICRO_strict= exactly one layer at SILVER thresholds (XOR: struct>=0.30 XOR flow>=0.40), NOT SILVER
  SKIP        = everything else

Where signed = raw_score × (1 if signal==1 else -1).
Stake engine uses NOTIONAL_USD=$25. Production projection at 0.5%×$1250=$6.25 = divide PnL by 4.

Usage:
    py -X utf8 -m strategy_lab.confluence.run_micro_tier_backtest > strategy_lab/results/micro_tier_backtest_run.log 2>&1
"""
from __future__ import annotations

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
REPORT = ROOT / "strategy_lab" / "reports" / "MICRO_TIER_BACKTEST_2026_05_07.md"

# SILVER thresholds (existing)
SILVER_STRUCT_MIN = 0.30
SILVER_FLOW_MIN = 0.40

# MICRO thresholds (softer)
MICRO_STRUCT_MIN = 0.20
MICRO_FLOW_MIN = 0.30

ASSETS = ("sol",)


def _classify(row: pd.Series) -> str:
    """Return SILVER / MICRO / MICRO_strict / SKIP for a fired row."""
    s = row.get("struct_score")
    f = row.get("flow_score")
    if pd.isna(s) or pd.isna(f):
        return "SKIP"
    sig_dir = 1 if int(row["signal"]) == 1 else -1
    s_signed = float(s) * sig_dir
    f_signed = float(f) * sig_dir

    s_at_silver = s_signed >= SILVER_STRUCT_MIN
    f_at_silver = f_signed >= SILVER_FLOW_MIN

    # SILVER: both layers at SILVER threshold
    if s_at_silver and f_at_silver:
        return "SILVER"

    # MICRO: either layer sign-aligned at softer threshold, not SILVER
    s_at_micro = s_signed >= MICRO_STRUCT_MIN
    f_at_micro = f_signed >= MICRO_FLOW_MIN
    if s_at_micro or f_at_micro:
        # Check MICRO_strict first: exactly one layer at SILVER thresholds (XOR)
        if s_at_silver ^ f_at_silver:
            return "MICRO_strict"
        return "MICRO"

    return "SKIP"


def _bootstrap_ci(pnls: np.ndarray, n_draws: int = 2000, ci: float = 0.95,
                  rng: np.random.Generator = None) -> tuple[float, float]:
    """Bootstrap CI on mean PnL."""
    if rng is None:
        rng = np.random.default_rng(42)
    if len(pnls) == 0:
        return (float("nan"), float("nan"))
    boot_means = np.array([
        rng.choice(pnls, size=len(pnls), replace=True).mean()
        for _ in range(n_draws)
    ])
    lo = (1 - ci) / 2
    return (float(np.quantile(boot_means, lo)), float(np.quantile(boot_means, 1 - lo)))


def _fire_sol_universe():
    """Fire momo top-10% on SOL universe. Returns (fired_df, klines, entry_books, bucket_books)."""
    uni = load_universe()
    klines = load_klines()

    for a in ASSETS:
        m = uni.asset == a
        ws_arr = uni.loc[m, "window_start_unix"].astype("int64").to_numpy()
        p0 = _vec_asof(klines[a], ws_arr)
        p2 = _vec_asof(klines[a], ws_arr + 120)
        with np.errstate(divide="ignore", invalid="ignore"):
            uni.loc[m, "asset_ret_2m"] = np.log(p2 / p0)

    active = uni[uni["asset_ret_2m"].notna() & np.isfinite(uni["asset_ret_2m"])].copy()

    fired = []
    for a in ASSETS:
        for tf in ("5m", "15m"):
            sub = active[(active.asset == a) & (active.timeframe == tf)].copy()
            if len(sub) < 50:
                print(f"  [fire] {a.upper()}_{tf}: skipped (n={len(sub)} < 50)")
                continue
            thr = sub["asset_ret_2m"].abs().quantile(0.90)
            f = sub[sub["asset_ret_2m"].abs() >= thr].copy()
            f["signal"] = (f["asset_ret_2m"] > 0).astype(int)
            fired.append(f)
            print(f"  [fire] {a.upper()}_{tf}: thr={thr:.5f}  fires={len(f)}/{len(sub)}")

    fired_all = pd.concat(fired, ignore_index=True) if fired else pd.DataFrame()
    entry_books = {a: load_tier1_entries(a) for a in ASSETS}
    bucket_books = {a: load_book_buckets(a) for a in ASSETS}
    return fired_all, klines, entry_books, bucket_books


def _run_tier(sub: pd.DataFrame, klines: dict, entry_books: dict, bucket_books: dict,
              label: str, asset: str) -> dict:
    """Run HOLD backtest on sub, compute perm p-value + bootstrap CI."""
    if len(sub) == 0:
        return {"label": label, "n": 0, "hit": float("nan"), "mean_usd": float("nan"),
                "total_usd": float("nan"), "std_usd": float("nan"),
                "max_dd": float("nan"), "p_value": float("nan"),
                "ci_lo": float("nan"), "ci_hi": float("nan")}

    r = run_cell(sub, klines[asset], entry_books[asset], bucket_books[asset],
                 "HOLD", label, asset)
    per_trade = r.pop("per_trade", [])
    pnls = np.array([t["pnl"] for t in per_trade]) if per_trade else np.array([])

    # Max drawdown from equity curve
    eq = np.cumsum(pnls) if len(pnls) else np.array([0.0])
    running_max = np.maximum.accumulate(eq)
    dd = running_max - eq
    max_dd = float(dd.max()) if len(dd) else float("nan")

    # Permutation p-value (only if n >= 5 — small sample but we still run)
    p_val = float("nan")
    if len(per_trade) >= 5:
        rng = np.random.default_rng(hash(label) % (2**32))
        p = permutation_test(per_trade, n_permutations=1000, rng=rng)
        p_val = p.get("p_value", float("nan"))

    # Bootstrap CI
    rng2 = np.random.default_rng(hash(label + "_boot") % (2**32))
    ci_lo, ci_hi = _bootstrap_ci(pnls, n_draws=2000, rng=rng2)

    return {
        "label": label,
        "n": r.get("n", 0),
        "hit": r.get("hit", float("nan")),
        "mean_usd": r.get("pnl_mean", float("nan")),
        "total_usd": r.get("pnl_total", float("nan")),
        "std_usd": r.get("pnl_std", float("nan")),
        "max_dd": max_dd,
        "p_value": p_val,
        "ci_lo": ci_lo,
        "ci_hi": ci_hi,
        "pnls": pnls,
        "per_trade_dates": [t.get("window_start_unix", 0) for t in per_trade],
    }


def _breakeven_hit(pnls: np.ndarray) -> float:
    """Breakeven hit rate = mean_win / (mean_win + |mean_loss|)."""
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    if len(wins) == 0 or len(losses) == 0:
        return float("nan")
    mean_win = wins.mean()
    mean_loss = abs(losses.mean())
    return mean_win / (mean_win + mean_loss)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)

    print(f"[micro] assets={ASSETS}")
    print(f"[micro] SILVER: struct>={SILVER_STRUCT_MIN}, flow>={SILVER_FLOW_MIN}")
    print(f"[micro] MICRO:  struct>={MICRO_STRUCT_MIN} OR flow>={MICRO_FLOW_MIN}, not SILVER")
    print(f"[micro] MICRO_strict: exactly one layer at SILVER thresholds (XOR), not SILVER")

    fired, klines, entry_books, bucket_books = _fire_sol_universe()
    print(f"[micro] total fired: {len(fired)}")

    enriched = enrich_universe(fired)
    enriched["tier"] = enriched.apply(_classify, axis=1)
    tier_counts = enriched["tier"].value_counts().to_dict()
    print(f"[micro] tier counts: {tier_counts}")

    # ── Per-cell breakdown ──────────────────────────────────────────────────
    results = []
    for a in ASSETS:
        for tf in ("5m", "15m"):
            cell = f"{a.upper()}_{tf}"
            sub_cell = enriched[(enriched.asset == a) & (enriched.timeframe == tf)]
            if len(sub_cell) == 0:
                continue

            baseline = _run_tier(sub_cell, klines, entry_books, bucket_books,
                                  f"{cell}_BASELINE", a)
            print(f"  {cell} BASELINE n={baseline['n']} hit={baseline['hit']*100:.1f}%"
                  f" mean=${baseline['mean_usd']:+.4f}")

            for tier_name in ("SILVER", "MICRO", "MICRO_strict"):
                sub_tier = sub_cell[sub_cell["tier"] == tier_name]
                r = _run_tier(sub_tier, klines, entry_books, bucket_books,
                               f"{cell}_{tier_name}", a)
                r["cell"] = cell
                r["tier"] = tier_name
                results.append(r)
                n = r["n"]
                if n > 0:
                    hit_pct = r["hit"] * 100 if not np.isnan(r["hit"]) else float("nan")
                    print(f"  {cell} {tier_name:<12} n={n:3d} hit={hit_pct:5.1f}%"
                          f" mean=${r['mean_usd']:+.4f} total=${r['total_usd']:+.6f}"
                          f" p={r['p_value']:.4f}"
                          f" CI=[${r['ci_lo']:+.4f}, ${r['ci_hi']:+.4f}]")

    # ── Sample concentration: MICRO days with SILVER overlap ────────────────
    print("\n[micro] sample concentration analysis")
    # Get dates where SILVER fired
    silver_rows = enriched[enriched["tier"] == "SILVER"].copy()
    micro_rows = enriched[enriched["tier"] == "MICRO"].copy()
    micro_strict_rows = enriched[enriched["tier"] == "MICRO_strict"].copy()

    def _dates(df: pd.DataFrame) -> set:
        """Convert window_start_unix to day strings."""
        if len(df) == 0 or "window_start_unix" not in df.columns:
            return set()
        return set(pd.to_datetime(df["window_start_unix"], unit="s").dt.date.astype(str))

    silver_days = _dates(silver_rows)
    micro_days = _dates(micro_rows)
    micro_strict_days = _dates(micro_strict_rows)

    micro_overlap = micro_days & silver_days
    micro_orthogonal = micro_days - silver_days
    ms_overlap = micro_strict_days & silver_days
    ms_orthogonal = micro_strict_days - silver_days

    print(f"  SILVER days: {len(silver_days)}")
    print(f"  MICRO  days: {len(micro_days)} | overlap={len(micro_overlap)} orthogonal={len(micro_orthogonal)}")
    print(f"  MICRO_strict days: {len(micro_strict_days)} | overlap={len(ms_overlap)} orthogonal={len(ms_orthogonal)}")

    # ── Consolidate SOL all-cells for each tier (combined 5m+15m) ───────────
    print("\n[micro] combined SOL (5m+15m) per tier")
    combined_results = {}
    for tier_name in ("SILVER", "MICRO", "MICRO_strict"):
        sub = enriched[enriched["tier"] == tier_name]
        r = _run_tier(sub, klines, entry_books, bucket_books, f"SOL_COMBINED_{tier_name}", "sol")
        combined_results[tier_name] = r
        n = r["n"]
        if n > 0:
            be = _breakeven_hit(r["pnls"])
            print(f"  SOL COMBINED {tier_name:<12} n={n:3d} hit={r['hit']*100:.1f}%"
                  f" mean=${r['mean_usd']:+.4f} total=${r['total_usd']:+.6f}"
                  f" be_hit={be*100:.1f}% p={r['p_value']:.4f}"
                  f" CI=[${r['ci_lo']:+.4f}, ${r['ci_hi']:+.4f}]")

    # ── Save CSV ─────────────────────────────────────────────────────────────
    csv_rows = []
    for r in results:
        row = {k: v for k, v in r.items() if k not in ("pnls", "per_trade_dates")}
        csv_rows.append(row)
    df_csv = pd.DataFrame(csv_rows)
    csv_path = OUT_DIR / "micro_tier_backtest.csv"
    df_csv.to_csv(csv_path, index=False)
    print(f"\n[micro] wrote {csv_path}")

    # ── Build report ──────────────────────────────────────────────────────────
    def _fmt(v, fmt=".4f"):
        return f"{v:{fmt}}" if not (isinstance(v, float) and np.isnan(v)) else "n/a"

    def _tier_row(r: dict, prod_scale: float = 4.0) -> str:
        n = r["n"]
        if n == 0:
            return f"| {r.get('cell','')} {r.get('tier',r.get('label',''))} | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |"
        hit = r["hit"] * 100 if not np.isnan(r["hit"]) else float("nan")
        be = _breakeven_hit(r["pnls"]) * 100 if len(r.get("pnls", [])) > 1 else float("nan")
        mean_prod = r["mean_usd"] / prod_scale if not np.isnan(r["mean_usd"]) else float("nan")
        return (
            f"| {r.get('cell','')} | {r.get('tier','')} | {n} "
            f"| {_fmt(hit, '.1f')}% | ${_fmt(r['mean_usd'],'+.4f')} | ${_fmt(r['total_usd'],'+.4f')} "
            f"| ${_fmt(r['std_usd'],'.4f')} | ${_fmt(r['max_dd'],'.4f')} "
            f"| {_fmt(r['p_value'],'.4f')} | [${_fmt(r['ci_lo'],'+.4f')}, ${_fmt(r['ci_hi'],'+.4f')}] "
            f"| {_fmt(be, '.1f')}% | ${_fmt(mean_prod,'+.4f')} |"
        )

    # Determine recommendation
    micro_r = combined_results.get("MICRO", {})
    silver_r = combined_results.get("SILVER", {})
    micro_n = micro_r.get("n", 0)
    micro_mean = micro_r.get("mean_usd", float("nan"))
    micro_p = micro_r.get("p_value", float("nan"))
    silver_n = silver_r.get("n", 0)
    silver_mean = silver_r.get("mean_usd", float("nan"))

    if micro_n == 0:
        tldr = "MICRO tier produced zero samples on SOL. No additional alpha. Keep SILVER-only."
        rec = "Keep SILVER-only. MICRO gate is too tight — no trades pass on this universe/period."
    elif not np.isnan(micro_mean) and micro_mean > 0 and (np.isnan(micro_p) or micro_p < 0.20):
        tldr = (f"MICRO adds {micro_n} trades (vs SILVER n={silver_n}) with positive mean ${micro_mean:+.4f}. "
                f"Marginal edge — monitor before sizing up.")
        rec = "Consider MICRO as a 2nd sub-sleeve at half-stake. Re-evaluate after 20+ live trades."
    elif not np.isnan(micro_mean) and micro_mean > 0:
        tldr = (f"MICRO adds {micro_n} trades with positive mean ${micro_mean:+.4f} but p={micro_p:.3f} "
                f"(not significant). Likely noise at n={micro_n}.")
        rec = "Keep SILVER-only for now. MICRO shows tentative positive mean but insufficient sample to distinguish from noise."
    else:
        tldr = (f"MICRO adds {micro_n} trades but mean ${micro_mean:+.4f} is negative or noisy. "
                f"Do not ship MICRO.")
        rec = "Do not add MICRO tier. It degrades expectancy vs SILVER."

    L = [
        "# MICRO Tier Backtest — SOL Universe",
        "",
        f"**Date:** 2026-05-07  |  **Universe:** SOL 2026-04-22 → 2026-05-06  |  **Engine:** $25/trade HOLD",
        "",
        "## TL;DR",
        "",
        tldr,
        "",
        "## Tier definitions",
        "",
        "| Tier | Rule |",
        "|---|---|",
        f"| SILVER | struct_signed ≥ {SILVER_STRUCT_MIN} AND flow_signed ≥ {SILVER_FLOW_MIN} (both layers) |",
        f"| MICRO | (struct_signed ≥ {MICRO_STRUCT_MIN} OR flow_signed ≥ {MICRO_FLOW_MIN}), NOT SILVER |",
        f"| MICRO_strict | exactly one of (struct_signed ≥ {SILVER_STRUCT_MIN}, flow_signed ≥ {SILVER_FLOW_MIN}) is True (XOR), NOT SILVER |",
        "| SKIP | everything else |",
        "",
        "signed = raw_score × (+1 if signal==1 else -1)",
        "",
        "## Tier counts (SOL 5m+15m combined)",
        "",
        "```",
        str(tier_counts),
        "```",
        "",
        "## Per-cell results",
        "",
        "Engine: $25 stake, HOLD policy. prod_mean = engine_mean ÷ 4 (0.5%×$1250=$6.25 sizing).",
        "",
        "| Cell | Tier | n | hit% | mean$ | total$ | std$ | maxDD$ | p-value | bootstrap 95% CI | BE hit% | prod mean$ |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        L.append(_tier_row(r))

    L += [
        "",
        "## Combined SOL (5m+15m) per tier",
        "",
        "| Tier | n | hit% | mean$ | total$ | std$ | maxDD$ | p-value | bootstrap 95% CI | BE hit% | prod mean$ |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for tier_name in ("SILVER", "MICRO", "MICRO_strict"):
        r = combined_results[tier_name]
        n = r["n"]
        if n == 0:
            L.append(f"| {tier_name} | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |")
            continue
        hit = r["hit"] * 100 if not np.isnan(r["hit"]) else float("nan")
        be = _breakeven_hit(r["pnls"]) * 100 if len(r.get("pnls", [])) > 1 else float("nan")
        mean_prod = r["mean_usd"] / 4.0 if not np.isnan(r["mean_usd"]) else float("nan")
        L.append(
            f"| {tier_name} | {n} | {_fmt(hit,'.1f')}% | ${_fmt(r['mean_usd'],'+.4f')} "
            f"| ${_fmt(r['total_usd'],'+.4f')} | ${_fmt(r['std_usd'],'.4f')} | ${_fmt(r['max_dd'],'.4f')} "
            f"| {_fmt(r['p_value'],'.4f')} | [${_fmt(r['ci_lo'],'+.4f')}, ${_fmt(r['ci_hi'],'+.4f')}] "
            f"| {_fmt(be,'.1f')}% | ${_fmt(mean_prod,'+.4f')} |"
        )

    L += [
        "",
        "## Sample concentration",
        "",
        f"| | Days with SILVER | Days MICRO only (orthogonal) | Total MICRO days |",
        f"|---|---:|---:|---:|",
        f"| MICRO | {len(micro_overlap)} | {len(micro_orthogonal)} | {len(micro_days)} |",
        f"| MICRO_strict | {len(ms_overlap)} | {len(ms_orthogonal)} | {len(micro_strict_days)} |",
        "",
        f"SILVER fired on {len(silver_days)} distinct days.",
        f"MICRO orthogonal days = {len(micro_orthogonal)} — trades where only MICRO fires (no SILVER same day).",
        "",
        "## Production sizing implication",
        "",
        "Engine uses $25 notional. Production target: 0.5% × $1250 bankroll = **$6.25/trade**.",
        "Scale factor = 6.25 / 25 = **0.25×** (÷4 on all PnL numbers).",
        "SILVER prod mean = engine mean ÷ 4.",
        "MICRO prod mean = engine mean ÷ 4 (same sizing assumption).",
        "",
        "## Recommendation",
        "",
        rec,
        "",
        "## Files",
        "",
        f"- Backtest CSV: `strategy_lab/results/meta_classifier/micro_tier_backtest.csv`",
        f"- This report: `strategy_lab/reports/MICRO_TIER_BACKTEST_2026_05_07.md`",
        f"- Script: `strategy_lab/confluence/run_micro_tier_backtest.py`",
    ]

    REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"[micro] wrote {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
