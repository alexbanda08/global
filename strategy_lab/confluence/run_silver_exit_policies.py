"""Silver exit-policy sweep — SOL only, HOLD vs HEDGE vs SELL × rev_bp grid.

Extends run_struct_flow_backtest.py:
  - Restricts to SOL asset only
  - Applies SILVER filter (struct+flow sign-aligned, struct>=0.30, flow>=0.40)
  - For SILVER subset: sweeps HOLD (1 cell) + HEDGE×5 + SELL×5 rev_bp values
  - Bonus: same matrix on unfiltered SOL momo (top-10% |ret_2m|)
  - Outputs: CSV + report

Usage:
    py -X utf8 strategy_lab/confluence/run_silver_exit_policies.py
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
    simulate,
    SPREAD_FILTER,
)
from strategy_lab.confluence.feature_join import enrich_universe
from strategy_lab.confluence.run_grand_backtest import _vec_asof
from polymarket_stats import equity_curve_stats

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STRUCT_MIN = 0.30
FLOW_MIN = 0.40
REV_BP_GRID = [2, 3, 5, 8, 10]
ASSET = "sol"

OUT_DIR = ROOT / "strategy_lab" / "results" / "silver_exit_policies"
REPORT = ROOT / "strategy_lab" / "reports" / "SILVER_EXIT_POLICY_BACKTEST_2026_05_07.md"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _classify_struct_flow(row: pd.Series, struct_min: float, flow_min: float) -> str:
    s = row.get("struct_score")
    f = row.get("flow_score")
    if pd.isna(s) or pd.isna(f):
        return "SKIP"
    sig = int(row["signal"])
    sig_dir = 1 if sig == 1 else -1
    s_aligned = (abs(s) >= struct_min) and (np.sign(s) == sig_dir)
    f_aligned = (abs(f) >= flow_min) and (np.sign(f) == sig_dir)
    return "SILVER" if (s_aligned and f_aligned) else "SKIP"


def _run_cell_with_rev_bp(
    df: pd.DataFrame,
    k1m: pd.DataFrame,
    entry_book: dict,
    bucket_book: dict,
    policy: str,
    rev_bp: int,
    label: str,
) -> dict:
    """Mirror run_cell internals but pass rev_bp through to simulate()."""
    pnls, costs, ws_list, vwaps = [], [], [], []
    sk_thin = sk_no_book = sk_spread = wins = 0
    n_hold = n_hedge = n_sell = 0
    per_trade = []

    for _, row in df.iterrows():
        max_b = 89 if row.timeframe == "15m" else 29
        r = simulate(
            row, k1m, entry_book, bucket_book, max_b, policy,
            rev_bp=rev_bp,
            spread_filter=SPREAD_FILTER[ASSET],
        )
        if r is None:
            sk_no_book += 1; continue
        if r.get("skipped_spread"):
            sk_spread += 1; continue
        if r.get("skipped_thin"):
            sk_thin += 1; continue

        pnls.append(r["pnl"])
        costs.append(r["cost"])
        ws_list.append(int(row.window_start_unix))
        vwaps.append(r["vwap_e"])
        if r["sig_won"]:
            wins += 1
        reason = r["exit_reason"]
        if reason == "hold": n_hold += 1
        elif reason == "hedge": n_hedge += 1
        elif reason == "sell": n_sell += 1
        per_trade.append(dict(
            slug=row.slug, ws_s=row.window_start_unix,
            signal=row.signal, outcome_up=row.outcome_up, pnl=r["pnl"],
        ))

    pnls = np.array(pnls)
    n = len(pnls)
    if n == 0:
        return {"label": label, "n": 0, "per_trade": []}

    eq = equity_curve_stats(pnls, trade_timestamps=np.array(ws_list, dtype=float))
    return dict(
        label=label, n=n, wins=wins,
        hit=float((pnls > 0).mean()),
        pnl_total=float(pnls.sum()),
        pnl_mean=float(pnls.mean()),
        pnl_std=float(pnls.std()),
        sharpe=eq["sharpe"],
        max_dd=eq["max_dd"],
        n_hold=n_hold, n_hedge=n_hedge, n_sell=n_sell,
        sk_thin=sk_thin, sk_no_book=sk_no_book, sk_spread=sk_spread,
        per_trade=per_trade,
    )


def _sweep_df(subset: pd.DataFrame, k1m, entry_book, bucket_book, label_prefix: str) -> list[dict]:
    """Run all 11 (policy, rev_bp) combinations on subset. Return rows for table."""
    rows = []

    # --- HOLD (rev_bp not applicable) ---
    r = _run_cell_with_rev_bp(subset, k1m, entry_book, bucket_book, "HOLD", 5, f"{label_prefix}_HOLD")
    perm = permutation_test(r.get("per_trade", []), n_permutations=1000, rng=np.random.default_rng(42))
    rows.append({
        "subset": label_prefix,
        "policy": "HOLD",
        "rev_bp": "n/a",
        "n": r.get("n", 0),
        "hit_pct": round(r.get("hit", float("nan")) * 100, 1),
        "mean_usd": round(r.get("pnl_mean", float("nan")), 4),
        "total_usd": round(r.get("pnl_total", float("nan")), 2),
        "std_usd": round(r.get("pnl_std", float("nan")), 4),
        "sharpe": round(r.get("sharpe", float("nan")), 3),
        "max_dd": round(r.get("max_dd", float("nan")), 2),
        "p_value": round(perm.get("p_value", float("nan")), 4),
        "n_hold": r.get("n_hold", 0),
        "n_hedge": r.get("n_hedge", 0),
        "n_sell": r.get("n_sell", 0),
    })
    print(f"  [{label_prefix}] HOLD n={r.get('n',0)} hit={r.get('hit',0)*100:.1f}% mean=${r.get('pnl_mean',0):+.4f} p={perm.get('p_value',float('nan')):.4f}")

    # --- HEDGE × rev_bp ---
    for bp in REV_BP_GRID:
        r = _run_cell_with_rev_bp(subset, k1m, entry_book, bucket_book, "HEDGE", bp, f"{label_prefix}_HEDGE_bp{bp}")
        perm = permutation_test(r.get("per_trade", []), n_permutations=1000, rng=np.random.default_rng(42 + bp))
        rows.append({
            "subset": label_prefix,
            "policy": "HEDGE",
            "rev_bp": bp,
            "n": r.get("n", 0),
            "hit_pct": round(r.get("hit", float("nan")) * 100, 1),
            "mean_usd": round(r.get("pnl_mean", float("nan")), 4),
            "total_usd": round(r.get("pnl_total", float("nan")), 2),
            "std_usd": round(r.get("pnl_std", float("nan")), 4),
            "sharpe": round(r.get("sharpe", float("nan")), 3),
            "max_dd": round(r.get("max_dd", float("nan")), 2),
            "p_value": round(perm.get("p_value", float("nan")), 4),
            "n_hold": r.get("n_hold", 0),
            "n_hedge": r.get("n_hedge", 0),
            "n_sell": r.get("n_sell", 0),
        })
        print(f"  [{label_prefix}] HEDGE bp={bp} n={r.get('n',0)} hit={r.get('hit',0)*100:.1f}% mean=${r.get('pnl_mean',0):+.4f}")

    # --- SELL × rev_bp ---
    for bp in REV_BP_GRID:
        r = _run_cell_with_rev_bp(subset, k1m, entry_book, bucket_book, "SELL", bp, f"{label_prefix}_SELL_bp{bp}")
        perm = permutation_test(r.get("per_trade", []), n_permutations=1000, rng=np.random.default_rng(100 + bp))
        rows.append({
            "subset": label_prefix,
            "policy": "SELL",
            "rev_bp": bp,
            "n": r.get("n", 0),
            "hit_pct": round(r.get("hit", float("nan")) * 100, 1),
            "mean_usd": round(r.get("pnl_mean", float("nan")), 4),
            "total_usd": round(r.get("pnl_total", float("nan")), 2),
            "std_usd": round(r.get("pnl_std", float("nan")), 4),
            "sharpe": round(r.get("sharpe", float("nan")), 3),
            "max_dd": round(r.get("max_dd", float("nan")), 2),
            "p_value": round(perm.get("p_value", float("nan")), 4),
            "n_hold": r.get("n_hold", 0),
            "n_hedge": r.get("n_hedge", 0),
            "n_sell": r.get("n_sell", 0),
        })
        print(f"  [{label_prefix}] SELL  bp={bp} n={r.get('n',0)} hit={r.get('hit',0)*100:.1f}% mean=${r.get('pnl_mean',0):+.4f}")

    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[1] Loading universe + klines ...")
    uni = load_universe()
    klines = load_klines()

    # Compute 2m returns for SOL
    m = uni.asset == ASSET
    ws_arr = uni.loc[m, "window_start_unix"].astype("int64").to_numpy()
    p0 = _vec_asof(klines[ASSET], ws_arr)
    p2 = _vec_asof(klines[ASSET], ws_arr + 120)
    with np.errstate(divide="ignore", invalid="ignore"):
        uni.loc[m, "asset_ret_2m"] = np.log(p2 / p0)

    active = uni[(uni.asset == ASSET) & uni["asset_ret_2m"].notna() & np.isfinite(uni["asset_ret_2m"])].copy()

    # Fire momo: top-10% |ret_2m| per timeframe
    fired_parts = []
    for tf in ("5m", "15m"):
        sub = active[active.timeframe == tf].copy()
        if len(sub) < 50:
            print(f"[warn] SOL {tf}: only {len(sub)} rows, skipping")
            continue
        thr = sub["asset_ret_2m"].abs().quantile(0.90)
        f = sub[sub["asset_ret_2m"].abs() >= thr].copy()
        f["signal"] = (f["asset_ret_2m"] > 0).astype(int)
        fired_parts.append(f)
        print(f"[1] SOL {tf}: {len(sub)} active → {len(f)} fired (thr={thr:.5f})")

    if not fired_parts:
        print("[ERROR] No fired trades for SOL. Aborting.")
        return 1

    fired_all = pd.concat(fired_parts, ignore_index=True)
    print(f"[1] Total SOL fired: {len(fired_all)}")

    print("[2] Loading entry books + bucket books ...")
    entry_book = load_tier1_entries(ASSET)
    bucket_book = load_book_buckets(ASSET)

    print("[3] Enriching with struct+flow features ...")
    enriched = enrich_universe(fired_all)
    enriched["sf_tier"] = enriched.apply(
        lambda row: _classify_struct_flow(row, STRUCT_MIN, FLOW_MIN), axis=1
    )
    counts = enriched["sf_tier"].value_counts().to_dict()
    print(f"[3] Tier counts: {counts}")

    silver = enriched[enriched["sf_tier"] == "SILVER"].copy()
    print(f"[3] SILVER subset: n={len(silver)}")

    k1m = klines[ASSET]

    all_rows: list[dict] = []

    # --- SILVER subset sweep ---
    print("\n[4] Sweeping exit policies on SILVER subset ...")
    if len(silver) > 0:
        silver_rows = _sweep_df(silver, k1m, entry_book, bucket_book, "SOL_SILVER")
        all_rows.extend(silver_rows)
    else:
        print("[warn] No SILVER trades — skipping SILVER sweep")

    # --- Full SOL momo (unfiltered) bonus sweep ---
    print("\n[5] Sweeping exit policies on full SOL momo (unfiltered) ...")
    unfiltered_rows = _sweep_df(enriched, k1m, entry_book, bucket_book, "SOL_MOMO")
    all_rows.extend(unfiltered_rows)

    # ---------------------------------------------------------------------------
    # Save CSV
    # ---------------------------------------------------------------------------
    df_out = pd.DataFrame(all_rows)
    csv_path = OUT_DIR / "silver_exit_policy_sweep.csv"
    df_out.to_csv(csv_path, index=False)
    print(f"\n[6] Wrote CSV: {csv_path}")
    print(df_out.to_string(index=False))

    # ---------------------------------------------------------------------------
    # Find best variant per subset
    # ---------------------------------------------------------------------------
    best_rows = {}
    for subset_label in df_out["subset"].unique():
        sub = df_out[df_out["subset"] == subset_label].copy()
        sub_n = sub[sub["n"] > 0]
        if len(sub_n) == 0:
            best_rows[subset_label] = None
            continue
        best_idx = sub_n["mean_usd"].idxmax()
        best_rows[subset_label] = sub_n.loc[best_idx]

    # ---------------------------------------------------------------------------
    # Build report
    # ---------------------------------------------------------------------------
    silver_table = df_out[df_out["subset"] == "SOL_SILVER"] if "SOL_SILVER" in df_out["subset"].values else pd.DataFrame()
    momo_table = df_out[df_out["subset"] == "SOL_MOMO"] if "SOL_MOMO" in df_out["subset"].values else pd.DataFrame()

    hold_row = silver_table[silver_table["policy"] == "HOLD"] if not silver_table.empty else pd.DataFrame()
    baseline_mean = hold_row["mean_usd"].iloc[0] if not hold_row.empty else float("nan")
    baseline_hit = hold_row["hit_pct"].iloc[0] if not hold_row.empty else float("nan")
    baseline_n = int(hold_row["n"].iloc[0]) if not hold_row.empty else 0

    best_silver = best_rows.get("SOL_SILVER")
    beat_hold = (
        best_silver is not None
        and best_silver["policy"] != "HOLD"
        and float(best_silver["mean_usd"]) > float(baseline_mean)
    ) if best_silver is not None and not pd.isna(baseline_mean) else False

    tldr_lines = [
        f"Baseline SILVER+HOLD: n={baseline_n}, hit={baseline_hit}%, mean=${baseline_mean:+.4f}" if not pd.isna(baseline_mean) else "Baseline SILVER+HOLD: no data",
    ]
    if best_silver is not None and best_silver["n"] > 0:
        tldr_lines.append(
            f"Best SILVER variant: {best_silver['policy']} rev_bp={best_silver['rev_bp']}, "
            f"n={best_silver['n']}, hit={best_silver['hit_pct']}%, mean=${float(best_silver['mean_usd']):+.4f}"
        )
        tldr_lines.append(
            "HEDGE/SELL BEATS HOLD on SILVER" if beat_hold else "HOLD still best on SILVER (or tied)"
        )
    else:
        tldr_lines.append("SILVER subset too small for HEDGE/SELL comparison")

    def _fmt_table(t: pd.DataFrame) -> str:
        if t.empty:
            return "(no data)"
        cols = ["policy", "rev_bp", "n", "hit_pct", "mean_usd", "total_usd", "std_usd", "sharpe", "max_dd", "p_value"]
        return t[cols].to_markdown(index=False)

    L = [
        "# SILVER Exit-Policy Backtest — SOL",
        "",
        "**Date:** 2026-05-07",
        f"**SILVER gate:** struct_min={STRUCT_MIN}, flow_min={FLOW_MIN}, sign-aligned",
        f"**rev_bp grid:** {REV_BP_GRID}",
        "",
        "## TL;DR",
        "",
    ]
    for line in tldr_lines:
        L.append(f"- {line}")
    L += [
        "",
        "## SILVER subset — full sweep",
        "",
        "(Baseline SILVER+HOLD: n=8, 100% hit, +$4.08/trade — from SILVER_VALIDATION_FINAL_2026_05_07.md)",
        "",
        _fmt_table(silver_table),
        "",
        "## Full SOL momo (unfiltered top-10%) — same matrix for context",
        "",
        _fmt_table(momo_table),
        "",
        "## Best variant per subset",
        "",
    ]
    for subset_label, brow in best_rows.items():
        if brow is None or int(brow["n"]) == 0:
            L.append(f"- **{subset_label}**: no trades")
        else:
            L.append(
                f"- **{subset_label}**: {brow['policy']} rev_bp={brow['rev_bp']} "
                f"n={brow['n']} hit={brow['hit_pct']}% mean=${float(brow['mean_usd']):+.4f} "
                f"sharpe={brow['sharpe']} p={brow['p_value']}"
            )
    L += [
        "",
        "## Caveats",
        "",
        "- **Sample bottleneck:** SILVER n=8 over Apr22–May6. HEDGE/SELL may skip more "
          "trades (no bucket-book match), so effective n could be even smaller. "
          "All statistics with n<30 are illustrative only.",
        "- **Upper bound:** BACKTEST engine has lookahead bug fixed (end-time-indexed asof). "
          "Production SHADOW data shows realfill leaving $7.30/trade on the table because "
          "the production hedge bug prevents exit-policy from firing. "
          "Lab numbers are the ceiling AFTER TV_AGENT_FIX_OPPOSITE_BOOK_FALLBACK lands.",
        "- **HEDGE/SELL skip trades** when the opposite-side book is absent at the trigger "
          "bucket. On thin markets (SOL SILVER) this further reduces n.",
        "- **Permutation test:** shuffles outcome_up within fired trades. With n<30, "
          "p-values are unreliable; treat as directional signal only.",
        f"- **CSV:** `{csv_path}`",
    ]

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"[7] Wrote report: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
