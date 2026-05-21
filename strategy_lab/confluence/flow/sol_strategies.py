"""SOL FLOW strategy variants — exploring whether FLOW unlocks alpha on SOL.

Context (G1 alpha gate findings):
  SOL_5m:  confirms (FLOW agrees w/ momo) = +$1.85/trade, opposes = -$0.23 (n=76 vs 83)
  SOL_15m: confirms = +$1.83/trade, opposes = -$3.10 (n=32 vs 44)
  BTC/ETH: no edge

Variants tested (all SOL-only):
  V1: FLOW-ONLY standalone — fire on FULL active SOL universe; direction = sign(flow_score),
       gate by |flow_score| > T. Threshold sweep T ∈ {0.15, 0.25, 0.35, 0.45}.
  V2: FLOW-VETO momo — keep momo fires only when flow agrees AND |flow_score| > 0.10.
       Baseline = full momo SOL.
  V3: FLOW-INVERSE momo — momo fires where flow OPPOSES, FLIP signal direction.
  V4: FLOW-magnitude sizing (subgroup-bucketed) — among momo+flow-agree fires, bucket by
       |flow_score| quartile and report each quartile separately.
  V5: V2 + extreme-price SKIP — apply V2 gate AND skip if entry top-of-book mid < 0.35 or > 0.65.

Outputs:
  strategy_lab/results/meta_classifier/sol_flow_strategies.csv
  strategy_lab/reports/SOL_FLOW_STRATEGIES_2026_05_07.md

Usage:
  py -X utf8 -m strategy_lab.confluence.flow.sol_strategies
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from strategy_lab.meta_classifier.extended_backtest_with_robustness import (  # noqa: E402
    asof,
    load_universe,
    load_klines,
    load_tier1_entries,
    load_book_buckets,
    permutation_test,
    run_cell,
)

CACHE_DIR = ROOT / "data" / "v4" / "refresh_2026_05_06" / "cache"
OUT_DIR = ROOT / "strategy_lab" / "results" / "meta_classifier"
REPORT = ROOT / "strategy_lab" / "reports" / "SOL_FLOW_STRATEGIES_2026_05_07.md"

ASSET = "sol"
PERM_DRAWS = 1000
FLOW_FLOOR_VETO = 0.10        # V2/V3/V5 directional gate
FLOW_THRESHOLDS = (0.15, 0.25, 0.35, 0.45)  # V1 sweep
EXTREME_PRICE_LOW = 0.35
EXTREME_PRICE_HIGH = 0.65


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_sol_flow() -> pd.DataFrame:
    p = CACHE_DIR / "sol_flow_features.parquet"
    df = pd.read_parquet(p)
    print(f"[load] sol_flow rows: {len(df):,}")
    return df


def attach_flow(df: pd.DataFrame, flow_df: pd.DataFrame) -> pd.DataFrame:
    """Attach flow_score keyed by (slug, held_outcome).

    Adds columns: flow_score, flow_dir (+1/-1/0), flow_agrees, flow_opposes.
    Caller must have set `signal` already so we know which outcome is held.
    """
    out = df.copy()
    out["held_outcome"] = np.where(out["signal"].astype(int) == 1, "Up", "Down")
    fl = flow_df[["slug", "outcome", "flow_score"]].rename(
        columns={"outcome": "held_outcome"}
    )
    out = out.merge(fl, on=["slug", "held_outcome"], how="left")
    out["flow_dir"] = np.sign(out["flow_score"]).fillna(0).astype(int)
    sig_dir = np.where(out["signal"].astype(int) == 1, 1, -1)
    out["flow_agrees"] = (out["flow_dir"] == sig_dir) & (
        out["flow_score"].abs() >= FLOW_FLOOR_VETO
    )
    out["flow_opposes"] = (out["flow_dir"] == -sig_dir) & (
        out["flow_score"].abs() >= FLOW_FLOOR_VETO
    )
    return out


def attach_entry_price(df: pd.DataFrame, entry_book: dict) -> pd.DataFrame:
    """Attach top-of-book mid (entry_price) for the held outcome side.

    Used by V5 extreme-price skip. We use the held side's (best ask + best bid)/2.
    """
    out = df.copy()
    if "held_outcome" not in out.columns:
        out["held_outcome"] = np.where(out["signal"].astype(int) == 1, "Up", "Down")
    eps = []
    for slug, ho in zip(out["slug"], out["held_outcome"]):
        rec = entry_book.get((slug, ho))
        if rec is None:
            eps.append(float("nan"))
            continue
        ask_p, _, bid_p, _ = rec
        ap = ask_p[0] if len(ask_p) else float("nan")
        bp = bid_p[0] if len(bid_p) else float("nan")
        if np.isfinite(ap) and np.isfinite(bp):
            eps.append(0.5 * (ap + bp))
        else:
            eps.append(float("nan"))
    out["entry_price"] = eps
    return out


def fired_sol_universe() -> tuple[pd.DataFrame, pd.DataFrame, dict, dict]:
    """Build SOL active universe + momo-fired subset (top-10% per tf).

    Returns:
      active_sol  — full active SOL universe (asset_ret_2m valid)
      fired_sol   — momo fires (top-10% |asset_ret_2m| per tf), with `signal` set
      entry_book  — SOL tier1 entries
      bucket_book — SOL bucket book
    """
    print("[universe] loading universe + klines + books…")
    uni = load_universe()
    klines = load_klines()
    a = ASSET
    m = uni.asset == a
    ws_arr = uni.loc[m, "window_start_unix"].astype("int64").values
    p0 = np.array([asof(klines[a], int(w)) for w in ws_arr])
    p2 = np.array([asof(klines[a], int(w) + 120) for w in ws_arr])
    with np.errstate(divide="ignore", invalid="ignore"):
        uni.loc[m, "asset_ret_2m"] = np.log(p2 / p0)
    active = uni[
        (uni.asset == a)
        & uni["asset_ret_2m"].notna()
        & np.isfinite(uni["asset_ret_2m"])
    ].copy()
    print(f"[universe] active SOL: {len(active)}  tfs={active.timeframe.value_counts().to_dict()}")

    entry_book = load_tier1_entries(a)
    bucket_book = load_book_buckets(a)
    print(f"[universe] tier1 entries: {len(entry_book)}  bucket-book slugs: {len(bucket_book)}")

    # Momo fires
    fired = []
    for tf in ("5m", "15m"):
        sub = active[active.timeframe == tf].copy()
        if len(sub) < 50:
            continue
        thr = sub["asset_ret_2m"].abs().quantile(0.90)
        f = sub[sub["asset_ret_2m"].abs() >= thr].copy()
        f["signal"] = (f["asset_ret_2m"] > 0).astype(int)
        fired.append(f)
        print(f"[momo] SOL_{tf} thr={thr:.5f}  fires={len(f)}/{len(sub)}")
    fired_sol = pd.concat(fired, ignore_index=True) if fired else pd.DataFrame()
    print(f"[momo] total SOL fires: {len(fired_sol)}")

    # store per-asset dicts to keep run_cell signature happy
    return active, fired_sol, klines, entry_book, bucket_book


def _summarize(label: str, r: dict, baseline_hit: float | None = None) -> dict:
    if r.get("n", 0) == 0:
        return dict(label=label, n=0, hit=0.0, pnl_mean=0.0, pnl_total=0.0,
                     pnl_std=0.0, sharpe=0.0, p_value=float("nan"),
                     hit_lift=float("nan"))
    hit = r["hit"]
    return dict(
        label=label,
        n=r["n"],
        hit=hit,
        pnl_mean=r["pnl_mean"],
        pnl_total=r["pnl_total"],
        pnl_std=r["pnl_std"],
        sharpe=r["sharpe"],
        p_value=float("nan"),
        hit_lift=(hit - baseline_hit) if baseline_hit is not None else float("nan"),
    )


def _perm(per_trade: list, key: tuple) -> float:
    if not per_trade:
        return float("nan")
    rng = np.random.default_rng(hash(key) % (2**32))
    p = permutation_test(per_trade, n_permutations=PERM_DRAWS, rng=rng)
    return float(p.get("p_value", float("nan")))


# ---------------------------------------------------------------------------
# V1 — FLOW-ONLY standalone (full SOL universe)
# ---------------------------------------------------------------------------

def variant_1_flow_only(
    active: pd.DataFrame,
    flow_df: pd.DataFrame,
    klines: dict,
    entry_book: dict,
    bucket_book: dict,
) -> list[dict]:
    """Fire on FULL active SOL universe; direction = sign(flow_score),
    gate by |flow_score| > threshold. Sweep threshold values.
    """
    print("\n[V1] FLOW-only standalone (full SOL universe)")
    rows = []
    a = ASSET
    # Need to attach flow first using a TENTATIVE signal — but signal IS sign(flow_score).
    # So attach raw flow_score per (slug, outcome) for both Up and Down independently.
    # Simpler: assign signal = (flow_score > 0) directly per held side; we just look up
    # flow_score with held=Up if flow>0 else Down → that's the outcome we'll bet on.
    fl = flow_df[["slug", "outcome", "flow_score"]].copy()
    # For each slug, take the "Up" row (per-outcome rows are symmetric in our flow build:
    # flow_score for Up is +score, Down is -score; but easier to just use Up row).
    fl_up = fl[fl["outcome"] == "Up"][["slug", "flow_score"]]
    base = active.merge(fl_up, on="slug", how="left")
    base = base[base["flow_score"].notna()].copy()
    base["signal"] = (base["flow_score"] > 0).astype(int)
    print(f"[V1] base universe (flow-coverage): {len(base)} (from {len(active)})")

    for tf in ("5m", "15m"):
        sub_tf = base[base.timeframe == tf]
        if len(sub_tf) == 0:
            continue
        for T in FLOW_THRESHOLDS:
            sub = sub_tf[sub_tf["flow_score"].abs() >= T].copy()
            label = f"V1_FLOW_ONLY_T{T:.2f}_SOL_{tf}"
            if len(sub) == 0:
                rows.append(dict(variant="V1", cell=f"SOL_{tf}", param=f"T={T}",
                                  n=0, hit=0.0, pnl_mean=0.0, pnl_total=0.0,
                                  pnl_std=0.0, sharpe=0.0, p_value=float("nan"),
                                  hit_lift=float("nan")))
                continue
            r = run_cell(sub, klines[a], entry_book, bucket_book, "HOLD", label, a)
            per_trade = r.pop("per_trade", [])
            p_val = _perm(per_trade, ("V1", tf, T))
            row = _summarize(label, r)
            row.update(variant="V1", cell=f"SOL_{tf}", param=f"T={T}",
                        p_value=p_val)
            rows.append(row)
            print(f"  {label}  n={r.get('n',0):4d}  hit={r.get('hit',0)*100:5.1f}%  "
                   f"mean=${r.get('pnl_mean',0):+.4f}  p={p_val:.3f}")
    return rows


# ---------------------------------------------------------------------------
# V2 — FLOW-VETO momo (only fire when flow agrees AND |flow|>0.10)
# ---------------------------------------------------------------------------

def variant_2_flow_veto(
    fired: pd.DataFrame,
    flow_df: pd.DataFrame,
    klines: dict,
    entry_book: dict,
    bucket_book: dict,
) -> list[dict]:
    print("\n[V2] FLOW-veto momo (keep only flow_agrees & |flow|>=0.10)")
    rows = []
    a = ASSET
    fired_with_flow = attach_flow(fired, flow_df)

    for tf in ("5m", "15m"):
        sub_tf = fired_with_flow[fired_with_flow.timeframe == tf]
        if len(sub_tf) == 0:
            continue
        # Baseline = full momo SOL on this tf
        r_full = run_cell(sub_tf, klines[a], entry_book, bucket_book,
                            "HOLD", f"V2_BASE_SOL_{tf}", a)
        full_per = r_full.pop("per_trade", [])
        full_p = _perm(full_per, ("V2_BASE", tf))
        baseline_hit = r_full.get("hit", 0.0)
        rb = _summarize(f"V2_BASELINE_FULL_MOMO_SOL_{tf}", r_full,
                          baseline_hit=baseline_hit)
        rb.update(variant="V2", cell=f"SOL_{tf}", param="baseline (full momo)",
                    p_value=full_p, hit_lift=0.0)
        rows.append(rb)

        # FLOW-veto: keep only flow_agrees
        veto = sub_tf[sub_tf["flow_agrees"]].copy()
        label = f"V2_FLOW_VETO_SOL_{tf}"
        if len(veto) == 0:
            rows.append(dict(variant="V2", cell=f"SOL_{tf}",
                              param="flow_agrees & |flow|>=0.10",
                              n=0, hit=0.0, pnl_mean=0.0, pnl_total=0.0,
                              pnl_std=0.0, sharpe=0.0, p_value=float("nan"),
                              hit_lift=float("nan")))
            continue
        r = run_cell(veto, klines[a], entry_book, bucket_book, "HOLD", label, a)
        per = r.pop("per_trade", [])
        p_val = _perm(per, ("V2_VETO", tf))
        row = _summarize(label, r, baseline_hit=baseline_hit)
        row.update(variant="V2", cell=f"SOL_{tf}",
                    param="flow_agrees & |flow|>=0.10",
                    p_value=p_val)
        rows.append(row)
        print(f"  baseline SOL_{tf}: n={r_full.get('n',0):4d} mean=${r_full.get('pnl_mean',0):+.4f}")
        print(f"  V2_VETO SOL_{tf}: n={r.get('n',0):4d} mean=${r.get('pnl_mean',0):+.4f}  "
               f"hit_lift={(r.get('hit',0)-baseline_hit)*100:+.2f}pp  p={p_val:.3f}")
    return rows


# ---------------------------------------------------------------------------
# V3 — FLOW-INVERSE momo (FLIP signal where flow opposes, |flow|>=0.10)
# ---------------------------------------------------------------------------

def variant_3_flow_inverse(
    fired: pd.DataFrame,
    flow_df: pd.DataFrame,
    klines: dict,
    entry_book: dict,
    bucket_book: dict,
) -> list[dict]:
    print("\n[V3] FLOW-inverse — momo fires where flow OPPOSES, FLIP signal")
    rows = []
    a = ASSET
    fired_with_flow = attach_flow(fired, flow_df)
    for tf in ("5m", "15m"):
        sub_tf = fired_with_flow[fired_with_flow.timeframe == tf]
        if len(sub_tf) == 0:
            continue
        opp = sub_tf[sub_tf["flow_opposes"]].copy()
        label = f"V3_FLOW_INVERSE_SOL_{tf}"
        if len(opp) == 0:
            rows.append(dict(variant="V3", cell=f"SOL_{tf}", param="flip on opposes",
                              n=0, hit=0.0, pnl_mean=0.0, pnl_total=0.0,
                              pnl_std=0.0, sharpe=0.0, p_value=float("nan"),
                              hit_lift=float("nan")))
            continue
        # FLIP signal
        opp["signal"] = (1 - opp["signal"].astype(int)).astype(int)
        r = run_cell(opp, klines[a], entry_book, bucket_book, "HOLD", label, a)
        per = r.pop("per_trade", [])
        p_val = _perm(per, ("V3", tf))
        row = _summarize(label, r)
        row.update(variant="V3", cell=f"SOL_{tf}", param="flip on opposes",
                    p_value=p_val)
        rows.append(row)
        print(f"  {label}  n={r.get('n',0):4d}  hit={r.get('hit',0)*100:5.1f}%  "
               f"mean=${r.get('pnl_mean',0):+.4f}  p={p_val:.3f}")
    return rows


# ---------------------------------------------------------------------------
# V4 — FLOW-magnitude sizing (subgroup-bucketed approach)
# ---------------------------------------------------------------------------

def variant_4_flow_magnitude(
    fired: pd.DataFrame,
    flow_df: pd.DataFrame,
    klines: dict,
    entry_book: dict,
    bucket_book: dict,
) -> list[dict]:
    """Bucket the V2 universe (momo + flow_agrees) by |flow_score| quartile.
    Run each quartile separately. Higher mean PnL in upper quartiles ⇒ sizing signal.
    """
    print("\n[V4] FLOW-magnitude — quartile-bucketed PnL within momo+flow-agree")
    rows = []
    a = ASSET
    fired_with_flow = attach_flow(fired, flow_df)
    for tf in ("5m", "15m"):
        sub_tf = fired_with_flow[
            (fired_with_flow.timeframe == tf) & (fired_with_flow["flow_agrees"])
        ].copy()
        if len(sub_tf) < 8:
            continue
        sub_tf["abs_flow"] = sub_tf["flow_score"].abs()
        try:
            sub_tf["q"] = pd.qcut(sub_tf["abs_flow"], 4, labels=["Q1", "Q2", "Q3", "Q4"])
        except ValueError:
            # not enough unique values; fall back to ranks
            sub_tf["q"] = pd.cut(sub_tf["abs_flow"], 4, labels=["Q1", "Q2", "Q3", "Q4"])
        for q in ("Q1", "Q2", "Q3", "Q4"):
            qsub = sub_tf[sub_tf["q"] == q].copy()
            label = f"V4_MAG_{q}_SOL_{tf}"
            if len(qsub) == 0:
                rows.append(dict(variant="V4", cell=f"SOL_{tf}", param=q,
                                  n=0, hit=0.0, pnl_mean=0.0, pnl_total=0.0,
                                  pnl_std=0.0, sharpe=0.0, p_value=float("nan"),
                                  hit_lift=float("nan")))
                continue
            r = run_cell(qsub, klines[a], entry_book, bucket_book,
                           "HOLD", label, a)
            per = r.pop("per_trade", [])
            p_val = _perm(per, ("V4", tf, q))
            row = _summarize(label, r)
            row.update(variant="V4", cell=f"SOL_{tf}", param=q, p_value=p_val)
            rows.append(row)
            print(f"  {label}  n={r.get('n',0):3d}  mean=${r.get('pnl_mean',0):+.4f}  "
                   f"|flow|∈[{qsub['abs_flow'].min():.3f}, {qsub['abs_flow'].max():.3f}]  p={p_val:.3f}")
    return rows


# ---------------------------------------------------------------------------
# V5 — V2 + extreme-price skip (entry_price < 0.35 or > 0.65)
# ---------------------------------------------------------------------------

def variant_5_v2_plus_skip(
    fired: pd.DataFrame,
    flow_df: pd.DataFrame,
    klines: dict,
    entry_book: dict,
    bucket_book: dict,
) -> list[dict]:
    print("\n[V5] V2 + extreme-price SKIP (0.35 ≤ entry_price ≤ 0.65)")
    rows = []
    a = ASSET
    fired_with_flow = attach_flow(fired, flow_df)
    fired_with_price = attach_entry_price(fired_with_flow, entry_book)

    for tf in ("5m", "15m"):
        sub_tf = fired_with_price[fired_with_price.timeframe == tf]
        if len(sub_tf) == 0:
            continue
        keep = sub_tf[
            sub_tf["flow_agrees"]
            & sub_tf["entry_price"].notna()
            & (sub_tf["entry_price"] >= EXTREME_PRICE_LOW)
            & (sub_tf["entry_price"] <= EXTREME_PRICE_HIGH)
        ].copy()
        label = f"V5_VETO_PLUS_SKIP_SOL_{tf}"
        if len(keep) == 0:
            rows.append(dict(variant="V5", cell=f"SOL_{tf}",
                              param="agree & 0.35-0.65",
                              n=0, hit=0.0, pnl_mean=0.0, pnl_total=0.0,
                              pnl_std=0.0, sharpe=0.0, p_value=float("nan"),
                              hit_lift=float("nan")))
            continue
        r = run_cell(keep, klines[a], entry_book, bucket_book, "HOLD", label, a)
        per = r.pop("per_trade", [])
        p_val = _perm(per, ("V5", tf))
        row = _summarize(label, r)
        row.update(variant="V5", cell=f"SOL_{tf}",
                    param="agree & 0.35-0.65", p_value=p_val)
        rows.append(row)
        print(f"  {label}  n={r.get('n',0):3d}  mean=${r.get('pnl_mean',0):+.4f}  p={p_val:.3f}")
    return rows


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------

def _fmt_table(rows: list[dict]) -> list[str]:
    L = [
        "| Variant | Cell | Param | n | hit% | mean $ | total $ | p | hit_lift |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        hit_pct = f"{r['hit']*100:.1f}" if r["n"] else "-"
        mean_s = f"{r['pnl_mean']:+.4f}" if r["n"] else "-"
        total_s = f"{r['pnl_total']:+.2f}" if r["n"] else "-"
        p_s = "-" if not np.isfinite(r["p_value"]) else f"{r['p_value']:.3f}"
        lift_s = "-" if not np.isfinite(r.get("hit_lift", float("nan"))) else f"{r['hit_lift']*100:+.1f}pp"
        L.append(f"| {r['variant']} | {r['cell']} | {r['param']} | {r['n']} | "
                 f"{hit_pct} | {mean_s} | {total_s} | {p_s} | {lift_s} |")
    return L


def write_report(all_rows: list[dict]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)

    # Find winner by criteria: n>=80, mean>=$5, p<0.05
    winners = [
        r for r in all_rows
        if r["n"] >= 80
        and r["pnl_mean"] >= 5.0
        and np.isfinite(r["p_value"])
        and r["p_value"] < 0.05
    ]
    near_misses = [
        r for r in all_rows
        if r["n"] >= 30
        and r["pnl_mean"] >= 2.0
        and np.isfinite(r["p_value"])
        and r["p_value"] < 0.10
        and r not in winners
    ]

    if winners:
        # pick highest mean*sqrt(n)
        winners.sort(key=lambda r: r["pnl_mean"] * np.sqrt(r["n"]), reverse=True)
        top = winners[0]
        tldr = (f"**SHIP {top['variant']}** — `{top['cell']} / {top['param']}`: "
                 f"n={top['n']}, mean=${top['pnl_mean']:+.2f}, p={top['p_value']:.3f}.")
    elif near_misses:
        near_misses.sort(key=lambda r: r["pnl_mean"] * np.sqrt(r["n"]), reverse=True)
        top = near_misses[0]
        tldr = (f"**NO CLEAR WINNER** — best near-miss: {top['variant']} "
                 f"`{top['cell']} / {top['param']}` "
                 f"n={top['n']}, mean=${top['pnl_mean']:+.2f}, p={top['p_value']:.3f}. "
                 "Below ship bar (mean>=$5, p<0.05, n>=80).")
    else:
        tldr = ("**NO WINNER** — no SOL FLOW variant clears mean>=$5, p<0.05, n>=80. "
                 "FLOW signal is informative on direction (G1) but does not generate "
                 "tradeable alpha at the structural sample size we have on SOL.")

    L = [
        "# SOL FLOW Strategy Variants — 2026-05-07",
        "",
        f"**Date:** 2026-05-07  |  **Asset:** SOL  |  **Period:** Apr 22 → May 6 2026  "
        f"|  **Stake:** $25  |  **Policy:** HOLD  |  **Permutations:** {PERM_DRAWS}",
        "",
        "## TL;DR",
        "",
        tldr,
        "",
        "**Ship bar:** mean $/trade ≥ +5, p<0.05, n≥80.",
        "",
        "## All variants — combined results",
        "",
    ]
    L += _fmt_table(all_rows)
    L += [
        "",
        "## Variant definitions",
        "",
        "| Variant | Description |",
        "|---|---|",
        "| V1 | FLOW-only standalone — full SOL universe; signal=sign(flow_score), gate by |flow_score|>T (T sweep). |",
        "| V2 | FLOW-veto momo — keep momo fires where flow_agrees & |flow|>=0.10; baseline=full momo SOL. |",
        "| V3 | FLOW-inverse momo — momo fires where flow opposes, FLIP signal direction. |",
        "| V4 | FLOW-magnitude bucketing — among V2 set, split by |flow_score| quartile. |",
        "| V5 | V2 + extreme-price skip — V2 set AND 0.35 ≤ entry_price ≤ 0.65. |",
        "",
        "## Permutation test summary",
        "",
        f"All p-values from 1000-draw permutation test on `extended_backtest_with_robustness.permutation_test`. "
        "H0: outcome direction is independent of fired signal direction (within fired sample).",
        "",
    ]
    sig = [r for r in all_rows if np.isfinite(r["p_value"]) and r["p_value"] < 0.05]
    L.append(f"- {len(sig)} / {sum(1 for r in all_rows if np.isfinite(r['p_value']))} "
              f"variants reach p<0.05.")
    if sig:
        L.append("- Significant variants:")
        for r in sig:
            L.append(f"  - **{r['variant']}** `{r['cell']} / {r['param']}` "
                      f"n={r['n']} mean=${r['pnl_mean']:+.2f} p={r['p_value']:.3f}")
    L.append("")

    # Recommendation block
    L += ["## Recommendation", ""]
    if winners:
        top = winners[0]
        L.append(f"**Ship {top['variant']} — `{top['cell']} / {top['param']}`.**")
        L.append("")
        L.append(f"- n={top['n']}, hit={top['hit']*100:.1f}%, mean=${top['pnl_mean']:+.4f}, "
                  f"total=${top['pnl_total']:+.2f}, p={top['p_value']:.3f}, sharpe={top['sharpe']:+.2f}.")
        L.append("- Clears all gates: n≥80, mean≥+5, p<0.05.")
        L.append("")
        # TV agent prompt
        L.append("### TV Agent prompt (for live deployment)")
        L.append("")
        L.append("```")
        L.append(f"# SOL FLOW {top['variant']} sleeve — TV/agent rules")
        L.append(f"Universe: SOL Polymarket Up/Down {top['cell'].split('_')[1]} markets, decisions at ws+120s.")
        L.append("Pre-fire gates (must all be true):")
        if top["variant"] == "V2":
            L.append("  - momo top-10% fired (|asset_ret_2m| >= q90 within current cell)")
            L.append("  - flow_score sign matches momo signal direction")
            L.append("  - |flow_score| >= 0.10")
        elif top["variant"] == "V3":
            L.append("  - momo top-10% fired (|asset_ret_2m| >= q90 within current cell)")
            L.append("  - flow_score sign OPPOSES momo signal direction")
            L.append("  - |flow_score| >= 0.10")
            L.append("  - FLIP signal direction (bet against the original momo direction)")
        elif top["variant"] == "V1":
            T = float(top["param"].split("=")[1])
            L.append(f"  - |flow_score| >= {T} (no momo gate)")
            L.append("  - signal direction = sign(flow_score)")
        elif top["variant"] == "V5":
            L.append("  - momo top-10% fired (|asset_ret_2m| >= q90)")
            L.append("  - flow_score sign matches momo signal AND |flow_score| >= 0.10")
            L.append("  - 0.35 <= entry_top_of_book_mid <= 0.65")
        elif top["variant"] == "V4":
            L.append(f"  - V2 set (momo fired & flow agrees & |flow|>=0.10)")
            L.append(f"  - additionally: |flow_score| in {top['param']} quartile (within SOL_{top['cell'].split('_')[1]} live distribution)")
        L.append("Stake: $25 fixed.")
        L.append("Policy: HOLD to resolution (no hedge/sell exit).")
        L.append("Spread filter: SOL = 0.025 max ask-bid at entry.")
        L.append("```")
    else:
        L.append("**Do not ship.** No variant clears mean≥+5, p<0.05, n≥80.")
        L.append("")
        L.append("### Next steps")
        L.append("")
        L.append("- Re-test after additional 2-3 weeks of data — current SOL n is structurally small (≈250 momo fires).")
        L.append("- Consider FLOW as a tier classifier input (probabilistic up-weight) "
                  "rather than a binary fire gate.")
        L.append("- Re-evaluate whether FLOW combined with other layers (STRUCTURE, TRIGGER) yields confluence.")
    L += [
        "",
        "## Reproduction",
        "",
        "```",
        "cd \"C:\\Users\\alexandre bandarra\\Desktop\\global\"",
        "py -X utf8 -m strategy_lab.confluence.flow.sol_strategies",
        "```",
        "",
        f"Outputs: `strategy_lab/results/meta_classifier/sol_flow_strategies.csv` and this report.",
        "",
    ]
    REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"\n[report] wrote {REPORT}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    flow_df = load_sol_flow()
    active, fired_sol, klines, entry_book, bucket_book = fired_sol_universe()
    if len(fired_sol) == 0:
        print("ERROR: no SOL momo fires — abort.")
        return 1

    rows = []
    rows += variant_1_flow_only(active, flow_df, klines, entry_book, bucket_book)
    rows += variant_2_flow_veto(fired_sol, flow_df, klines, entry_book, bucket_book)
    rows += variant_3_flow_inverse(fired_sol, flow_df, klines, entry_book, bucket_book)
    rows += variant_4_flow_magnitude(fired_sol, flow_df, klines, entry_book, bucket_book)
    rows += variant_5_v2_plus_skip(fired_sol, flow_df, klines, entry_book, bucket_book)

    df = pd.DataFrame(rows)
    csv_path = OUT_DIR / "sol_flow_strategies.csv"
    df.to_csv(csv_path, index=False)
    print(f"\n[csv] wrote {csv_path} ({len(df)} rows)")

    write_report(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
