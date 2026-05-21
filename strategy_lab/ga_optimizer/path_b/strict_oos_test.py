"""
Strict out-of-sample test for sleeve-level selection.

THE QUESTION: when I select sleeves where train_pnl > 0 + train_perm_p<0.05,
does their held-out PnL sum significantly exceed what RANDOM selection
of equal-size would give?

If YES: real persistent alpha exists in the selection
If NO: my "deployable" set is selection bias / data dredging

Procedure:
1. Pick sleeves passing train-only criteria
2. Compute aggregate held-out PnL
3. Null distribution: random N-sleeve subsets of equal size, their held PnL
4. Real selection p-value = P(random sum >= observed sum)
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from strategy_lab.ga_optimizer.path_b.events import load_path_b_events


def perm_pnl(pnls, B=2000, seed=42):
    n = len(pnls)
    if n < 5:
        return 1.0
    rng = np.random.default_rng(seed)
    observed = float(pnls.sum())
    sums = np.array([float((pnls * rng.choice([1,-1], size=n)).sum()) for _ in range(B)])
    return float((sums >= observed).mean())


def main():
    print("=== STRICT OOS TEST — addresses selection-bias concern ===\n")

    # IMPORTANT: exclude mint_sell from this analysis (it's MM, not directional)
    events = load_path_b_events()
    events = events[~events.sleeve_id.str.startswith("poly_mint_sell_", na=False)]
    print(f"Directional events (mint_sell excluded): {len(events):,}")

    span = events.at_ts.max() - events.at_ts.min()
    train_end = events.at_ts.min() + span * 0.80
    train = events[events.at_ts < train_end]
    held = events[events.at_ts >= train_end]
    print(f"Train: {len(train):,}  Held: {len(held):,}")
    train_days = (train_end - events.at_ts.min()).total_seconds() / 86400
    held_days = (events.at_ts.max() - train_end).total_seconds() / 86400
    print(f"Train span: {train_days:.1f}d  Held: {held_days:.1f}d")

    # Per sleeve stats (train + held separately)
    per = {}
    for slv, g in events.groupby("sleeve_id"):
        gt = train[train.sleeve_id == slv]
        gh = held[held.sleeve_id == slv]
        if len(gt) < 30:
            continue
        per[slv] = {
            "n_train": len(gt), "n_held": len(gh),
            "train_pnl": float(gt.pnl_same.sum()),
            "held_pnl": float(gh.pnl_same.sum()) if len(gh) else 0.0,
            "train_perm_p": perm_pnl(gt.pnl_same.values, B=1000),
        }
    df = pd.DataFrame(per).T.reset_index().rename(columns={"index":"sleeve_id"})
    print(f"\nTotal sleeves (n>=30 train): {len(df)}")
    print(f"Production aggregate train: ${df.train_pnl.sum():+,.2f}")
    print(f"Production aggregate held : ${df.held_pnl.sum():+,.2f}")

    # ===== Test 1: train_pnl > 0 selection =====
    print(f"\n=== Test 1: select by train_pnl > 0 (no held peek) ===")
    selected = df[df.train_pnl > 0].copy()
    n_sel = len(selected)
    held_total_real = float(selected.held_pnl.sum())
    print(f"  selected n: {n_sel}")
    print(f"  train_pnl sum (selected): ${selected.train_pnl.sum():+,.2f}")
    print(f"  HELD_PNL sum (selected, truly OOS): ${held_total_real:+,.2f}")

    # Null: random N-sleeve subsets
    rng = np.random.default_rng(42)
    B = 5000
    null_sums = []
    held_pnls_all = df.held_pnl.values
    for _ in range(B):
        idx = rng.choice(len(df), size=n_sel, replace=False)
        null_sums.append(float(held_pnls_all[idx].sum()))
    null_sums = np.array(null_sums)
    p_value = float((null_sums >= held_total_real).mean())
    print(f"\n  Null distribution (random {n_sel}-sleeve subsets, {B} draws):")
    print(f"    mean: ${null_sums.mean():+,.2f}")
    print(f"    p10/p50/p90: ${np.percentile(null_sums,10):+,.0f} / ${np.percentile(null_sums,50):+,.0f} / ${np.percentile(null_sums,90):+,.0f}")
    print(f"    p (random >= observed): {p_value:.4f}")
    if p_value < 0.05:
        print(f"    VERDICT: Selection is SIGNIFICANTLY better than random — real alpha")
    elif p_value < 0.20:
        print(f"    VERDICT: Marginal — could be real but possibly selection noise")
    else:
        print(f"    VERDICT: NOT significantly better than random selection (p>0.20)")

    # ===== Test 2: train_pnl > 0 AND train_perm_p < 0.05 (rigorous) =====
    print(f"\n=== Test 2: stricter — train_pnl > 0 AND train_perm_p < 0.05 ===")
    rigorous = df[(df.train_pnl > 0) & (df.train_perm_p < 0.05)].copy()
    n_rig = len(rigorous)
    held_total_rig = float(rigorous.held_pnl.sum())
    print(f"  selected n: {n_rig}")
    print(f"  train_pnl sum: ${rigorous.train_pnl.sum():+,.2f}")
    print(f"  HELD_PNL sum: ${held_total_rig:+,.2f}")

    if n_rig > 0:
        null_sums_r = []
        for _ in range(B):
            idx = rng.choice(len(df), size=n_rig, replace=False)
            null_sums_r.append(float(held_pnls_all[idx].sum()))
        null_sums_r = np.array(null_sums_r)
        p_value_r = float((null_sums_r >= held_total_rig).mean())
        print(f"  null mean: ${null_sums_r.mean():+,.2f}")
        print(f"  p (random >= observed): {p_value_r:.4f}")

    # ===== Test 3: KILL the LOSERS, KEEP the rest (less aggressive) =====
    print(f"\n=== Test 3: KILL only severe losers (train_pnl < -200 AND p>0.95) ===")
    losers = df[(df.train_pnl < -200) & (df.train_perm_p > 0.95)].copy()
    keepers = df[~df.index.isin(losers.index)].copy()
    print(f"  killing {len(losers)} loser sleeves")
    print(f"  kept {len(keepers)} sleeves")
    print(f"  killed train_pnl: ${losers.train_pnl.sum():+,.2f}  held: ${losers.held_pnl.sum():+,.2f}")
    print(f"  KEPT train_pnl: ${keepers.train_pnl.sum():+,.2f}  held: ${keepers.held_pnl.sum():+,.2f}")
    print(f"  -> If we KILL the {len(losers)} confirmed losers:")
    print(f"     would save train: ${-losers.train_pnl.sum():+,.2f}")
    print(f"     would save held : ${-losers.held_pnl.sum():+,.2f}")

    # ===== Bottom-line: project monthly conservatively =====
    print(f"\n=== HONEST PROJECTIONS ===")
    full_days = train_days + held_days
    print(f"Production current aggregate (all directional): ${df.train_pnl.sum()+df.held_pnl.sum():+,.2f} over {full_days:.1f}d")
    print(f"   monthly equivalent: ${(df.train_pnl.sum()+df.held_pnl.sum())/full_days*30:+,.2f}/month")
    print()
    print(f"Strategy 1: select by train_pnl>0 alone")
    print(f"   train PnL of selected:  ${selected.train_pnl.sum():+,.2f}  ({selected.train_pnl.sum()/train_days*30:+,.0f}/mo)")
    print(f"   HELD PnL of selected:   ${held_total_real:+,.2f}  ({held_total_real/held_days*30:+,.0f}/mo)  [TRUE OOS]")
    print(f"   p-value vs random:      {p_value:.4f}")
    print()
    print(f"Strategy 2: kill confirmed-loser sleeves (train_pnl<-200 AND p>0.95)")
    print(f"   keeper held PnL: ${keepers.held_pnl.sum():+,.2f}")
    print(f"   This is conservative — only kills clear-losers, no winner-picking")

    # Save
    df.to_csv(ROOT / "strategy_lab" / "ga_optimizer" / "runs" / "strict_oos_per_sleeve.csv", index=False)
    print(f"\nSaved: strict_oos_per_sleeve.csv")


if __name__ == "__main__":
    main()
