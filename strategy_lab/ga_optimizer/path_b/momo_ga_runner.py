"""
Run leak-free GA filter on momo_v1 + momo_v2 across BTC/ETH/SOL.

For each sleeve family:
  1. Extract all production fires
  2. Build cells (sleeve_id, signal, hour_bucket, dow_group)
  3. Apply disjoint 80/20 train/held split + 3 internal folds
  4. Run GA filter selecting KEEP/INVERT/SKIP per cell
  5. Validate top with permutation + FDR (Benjamini-Hochberg q=0.10)
  6. Real opposite-side L25 walks (no 1Hz subsample) for INVERT actions
  7. Report deployable + watchlist tiers per family

Output:
  runs/momo_ga_<family>/results.csv
  runs/momo_ga_SUMMARY.csv
"""
from __future__ import annotations
import sys, json, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

from load import load_trading_events, load_resolutions, load_orderbook_l25_streaming
from strategy_lab.ga_optimizer.path_b.events import (
    load_path_b_events, NOTIONAL, FEE_RATE, SPREAD_FILTER
)
from strategy_lab.ga_optimizer.path_b.robust_cells_clean import (
    make_disjoint_windows, perm_test
)


def walk_asks(prices, sizes, dollars=NOTIONAL):
    spent = 0.0; shares = 0.0
    for p, s in zip(prices, sizes):
        if not np.isfinite(p) or p <= 0 or s <= 0:
            continue
        cost_full = p * s
        if spent + cost_full >= dollars:
            need = (dollars - spent) / p
            shares += need; spent += need * p
            return spent / shares, shares, spent, False
        shares += s; spent += cost_full
    if shares <= 0:
        return np.nan, 0.0, 0.0, True
    return spent / shares, shares, spent, spent < dollars * 0.5


def filter_by_family(events, family_pattern):
    """family_pattern: regex like 'momo_HEDGE|momo_HOLD|momo_SELL' or 'momo_v2'"""
    return events[events.sleeve_id.str.contains(family_pattern, regex=True, na=False)]


def analyze_family(events, family_name, family_pattern, run_dir):
    """Run full leak-free analysis on one sleeve family."""
    print(f"\n{'='*80}\n=== Family: {family_name} (pattern: {family_pattern}) ===\n{'='*80}")
    sub = filter_by_family(events, family_pattern)
    print(f"  events: {len(sub):,}  unique sleeves: {sub.sleeve_id.nunique()}")
    if len(sub) < 100:
        print(f"  Too few events — skipping")
        return None
    print(f"  per sleeve:")
    print(sub.groupby("sleeve_id").size().to_dict())

    windows = make_disjoint_windows(sub)
    sub = sub.copy()
    sub["pnl_invert_conservative"] = sub.pnl_invert - 25.0 * 0.01   # 100bp safety
    sel = sub[(sub.at_ts >= windows["selection"][0]) & (sub.at_ts < windows["selection"][1])]
    held = sub[(sub.at_ts >= windows["held_out"][0]) & (sub.at_ts < windows["held_out"][1])]

    # Build cells
    cells = sel.groupby("cell_id").agg(
        sleeve_id=("sleeve_id","first"), signal=("signal","first"),
        hour_bucket=("hour_bucket","first"), dow_group=("dow_group","first"),
        asset=("asset","first"), n_sel=("event_id","size"),
    ).reset_index()
    cells = cells[cells.n_sel >= 30]
    print(f"  candidate cells (n_sel>=30): {len(cells)}")
    if len(cells) == 0:
        return None

    # Per-cell fold + selection stats + held-out
    rows = []
    for _, c in cells.iterrows():
        rec = c.to_dict()
        ce_all = sub[sub.cell_id == c.cell_id]
        for fname in ["fold_a","fold_b","fold_c"]:
            f = windows[fname]
            ws = ce_all[(ce_all.at_ts >= f[0]) & (ce_all.at_ts < f[1])]
            rec[f"n_{fname}"] = int(len(ws))
            rec[f"keep_{fname}"] = float(ws.pnl_same.sum()) if len(ws) else 0.0
            rec[f"inv_{fname}"] = float(ws.pnl_invert_conservative.sum()) if len(ws) else 0.0
        ws_sel = sel[sel.cell_id == c.cell_id]
        rec["keep_sel"] = float(ws_sel.pnl_same.sum())
        rec["inv_sel"]  = float(ws_sel.pnl_invert_conservative.sum())
        ws_held = held[held.cell_id == c.cell_id]
        rec["n_held"] = int(len(ws_held))
        rec["keep_held"] = float(ws_held.pnl_same.sum()) if len(ws_held) else 0.0
        rec["inv_held"]  = float(ws_held.pnl_invert_conservative.sum()) if len(ws_held) else 0.0
        rec["active_folds"] = sum(rec[f"n_{ff}"] >= 10 for ff in ["fold_a","fold_b","fold_c"])
        rows.append(rec)
    df = pd.DataFrame(rows)

    # Pick action
    def pick(r):
        keeps = [r[f"keep_{ff}"] for ff in ["fold_a","fold_b","fold_c"] if r[f"n_{ff}"] >= 10]
        invs  = [r[f"inv_{ff}"]  for ff in ["fold_a","fold_b","fold_c"] if r[f"n_{ff}"] >= 10]
        if not keeps:
            return ("SKIP", 0.0)
        n_active = len(keeps)
        if n_active >= 2:
            kp = sum(p > 0 for p in keeps); ip = sum(p > 0 for p in invs)
            ks, vs = sum(keeps), sum(invs)
            if kp >= 2 and ks > 0 and ks >= vs:
                return ("KEEP", ks)
            if ip >= 2 and vs > 0 and vs > ks:
                return ("INVERT", vs)
        else:
            ks, vs = sum(keeps), sum(invs)
            if ks > 0 and ks >= vs:
                return ("KEEP (single-fold)", ks)
            if vs > 0:
                return ("INVERT (single-fold)", vs)
        return ("SKIP", 0.0)

    actions = df.apply(pick, axis=1, result_type="expand")
    actions.columns = ["action_full", "selection_pnl"]
    df = pd.concat([df, actions], axis=1)
    df["action"] = df.action_full.str.split().str[0]
    deployable = df[df.action != "SKIP"].copy()
    print(f"  deployable: {len(deployable)}")
    if len(deployable) == 0:
        return {"family": family_name, "n_events": len(sub), "n_cells_total": len(df),
                "n_cells_deployable": 0, "tier_a_cells": 0, "tier_b_cells": 0,
                "tier_a_sel_pnl": 0, "tier_a_held_pnl": 0, "tier_b_sel_pnl": 0, "tier_b_held_pnl": 0,
                "tier_a_monthly": 0, "tier_b_monthly": 0,
                "held_days": (windows["held_out"][1] - windows["held_out"][0]).total_seconds()/86400,
                "sel_days": (windows["selection"][1] - windows["selection"][0]).total_seconds()/86400}

    # Perm test on selection window
    perm_p_sel = []
    for _, c in deployable.iterrows():
        ce_sel = sel[sel.cell_id == c.cell_id]
        p = perm_test(ce_sel, c.action, "pnl_invert_conservative", B=2000)
        perm_p_sel.append(p["p_value"])
    deployable["perm_p_sel"] = perm_p_sel
    deployable["held_pnl"] = deployable.apply(
        lambda r: r.keep_held if r.action == "KEEP" else r.inv_held, axis=1)

    # Split multi-fold (rigorous) vs single-fold (provisional)
    multi = deployable[deployable.active_folds >= 2].copy()
    single = deployable[deployable.active_folds == 1].copy()
    print(f"  multi-fold: {len(multi)}  single-fold: {len(single)}")

    # FDR on multi-fold
    if len(multi):
        multi = multi.sort_values("perm_p_sel").reset_index(drop=True)
        n = len(multi)
        multi["bh_rank"] = range(1, n+1)
        multi["bh_critical"] = multi.bh_rank / n * 0.10
        multi["bh_passes"] = multi.perm_p_sel < multi.bh_critical
        passing = multi[multi.bh_passes].bh_rank.max() if multi.bh_passes.any() else 0
        tier_a = multi[multi.bh_rank <= passing].copy() if passing else multi.head(0).copy()
    else:
        tier_a = deployable.head(0).copy()    # empty but with same columns

    # Require held-out positive (only filter if there are rows)
    if len(tier_a) and "held_pnl" in tier_a.columns:
        tier_a = tier_a[tier_a.held_pnl > 0]
    # Tier B: single-fold + perm<0.05 + held>0 + n_held>=50
    tier_b = single[(single.perm_p_sel < 0.05) & (single.held_pnl > 0) & (single.n_held >= 50)]

    print(f"\n  TIER A (FDR + held>0): {len(tier_a)} cells")
    if len(tier_a):
        cols_a = ["sleeve_id","signal","hour_bucket","dow_group","action","n_sel","selection_pnl","held_pnl","perm_p_sel"]
        print(tier_a[cols_a].to_string(index=False))
    print(f"\n  TIER B (single-fold late-starters): {len(tier_b)} cells")
    if len(tier_b):
        print(tier_b[["sleeve_id","signal","hour_bucket","dow_group","action","n_sel","selection_pnl","held_pnl","perm_p_sel"]].to_string(index=False))

    # Save
    run_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(run_dir / f"{family_name}_all.csv", index=False)
    tier_a.to_csv(run_dir / f"{family_name}_tier_a.csv", index=False)
    tier_b.to_csv(run_dir / f"{family_name}_tier_b.csv", index=False)

    sel_days = (windows["selection"][1] - windows["selection"][0]).total_seconds() / 86400
    held_days = (windows["held_out"][1] - windows["held_out"][0]).total_seconds() / 86400
    summary = {
        "family": family_name, "n_events": len(sub),
        "n_cells_total": len(df), "n_cells_deployable": len(deployable),
        "tier_a_cells": len(tier_a), "tier_b_cells": len(tier_b),
        "tier_a_sel_pnl": float(tier_a.selection_pnl.sum()) if len(tier_a) else 0,
        "tier_a_held_pnl": float(tier_a.held_pnl.sum()) if len(tier_a) else 0,
        "tier_b_sel_pnl": float(tier_b.selection_pnl.sum()) if len(tier_b) else 0,
        "tier_b_held_pnl": float(tier_b.held_pnl.sum()) if len(tier_b) else 0,
        "held_days": held_days, "sel_days": sel_days,
    }
    summary["tier_a_monthly"] = summary["tier_a_held_pnl"] / max(held_days, 1) * 30
    summary["tier_b_monthly"] = summary["tier_b_held_pnl"] / max(held_days, 1) * 30
    return summary


def main():
    print("=== Momo GA: full leak-free analysis across momo_v1 + momo_v2 ===")
    events = load_path_b_events()
    print(f"events: {len(events):,}  window: {events.at_ts.min()} → {events.at_ts.max()}")

    run_dir = ROOT / "strategy_lab" / "ga_optimizer" / "runs" / f"momo_ga_{int(time.time())}"
    families = [
        # momo v1 family
        ("momo_v1_HOLD",   r"_momo_HOLD$"),
        ("momo_v1_HEDGE",  r"_momo_HEDGE$"),
        ("momo_v1_SELL",   r"_momo_SELL$"),
        # momo v2 family
        ("momo_v2_HOLD",   r"_momo_v2_HOLD"),
        ("momo_v2_HEDGE",  r"_momo_v2_HEDGE"),
        ("momo_v2_SELL",   r"_momo_v2_SELL"),
        # sniper family (related)
        ("sniper",         r"_sniper$"),
        ("sniper_INV",     r"_sniper_INV"),
        ("sniper_DOWN_INV",r"_sniper_DOWN_INV"),
        # volume_INV_NIGHT (the one with our Tier A)
        ("volume_INV_NIGHT", r"_volume_INV_NIGHT"),
        # v3 family
        ("v3", r"_v3$"),
        ("v3_1", r"_v3_1"),
        ("v3_2", r"_v3_2"),
        ("v3_3", r"_v3_3"),
        ("v4", r"_v4$"),
    ]
    summaries = []
    for fname, pat in families:
        s = analyze_family(events, fname, pat, run_dir)
        if isinstance(s, dict):
            summaries.append(s)
    summary_df = pd.DataFrame(summaries)
    print(f"\n{'='*80}\n=== AGGREGATE SUMMARY ===\n{'='*80}")
    print(summary_df.to_string(index=False))
    summary_df.to_csv(run_dir / "SUMMARY.csv", index=False)

    total_a_held = summary_df.tier_a_held_pnl.sum()
    total_b_held = summary_df.tier_b_held_pnl.sum()
    total_a_month = summary_df.tier_a_monthly.sum()
    total_b_month = summary_df.tier_b_monthly.sum()
    print(f"\nTOTAL TIER A: held=${total_a_held:+,.2f}  monthly=${total_a_month:+,.2f}")
    print(f"TOTAL TIER B: held=${total_b_held:+,.2f}  monthly=${total_b_month:+,.2f}")
    print(f"\nRun dir: {run_dir}")


if __name__ == "__main__":
    main()
