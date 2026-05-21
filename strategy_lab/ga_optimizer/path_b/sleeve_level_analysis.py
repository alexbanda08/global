"""
SLEEVE-LEVEL analysis: which whole momo sleeves are profitable on VPS3 shadow,
with leak-free train/held split + permutation test on the AGGREGATE PnL.

This complements the sub-cell GA (which is too granular for many sleeves).
A sleeve can be aggregate-profitable even if no single (signal, hour, dow)
sub-cell passes FDR.

Output:
  sleeve_level.csv with columns:
    sleeve_id, n_full, n_train, n_held, pnl_train, pnl_held, win_train, win_held,
    perm_p_train, perm_p_held, verdict
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


def perm_test(pnls, B=2000, seed=42):
    n = len(pnls)
    if n < 5:
        return 1.0
    rng = np.random.default_rng(seed)
    observed = float(pnls.sum())
    sums = np.array([float((pnls * rng.choice([1,-1], size=n)).sum()) for _ in range(B)])
    return float((sums >= observed).mean())


def main():
    events = load_path_b_events()
    print(f"events: {len(events):,}  window: {events.at_ts.min()} → {events.at_ts.max()}")
    span = events.at_ts.max() - events.at_ts.min()
    train_end = events.at_ts.min() + span * 0.80
    train = events[events.at_ts < train_end]
    held = events[events.at_ts >= train_end]
    print(f"train: {len(train):,} ({events.at_ts.min()} → {train_end})")
    print(f"held:  {len(held):,}  ({train_end} → {events.at_ts.max()})")

    rows = []
    for slv, g in events.groupby("sleeve_id"):
        gt = train[train.sleeve_id == slv]
        gh = held[held.sleeve_id == slv]
        if len(gt) < 30:
            continue
        rec = {
            "sleeve_id": slv,
            "n_full": len(g),
            "n_train": len(gt),
            "n_held": len(gh),
            "pnl_train": float(gt.pnl_same.sum()),
            "pnl_held": float(gh.pnl_same.sum()) if len(gh) else 0.0,
            "win_train": float(gt.won.fillna(False).mean()),
            "win_held": float(gh.won.fillna(False).mean()) if len(gh) else 0.0,
            "perm_p_train": perm_test(gt.pnl_same.values, B=2000),
            "perm_p_held": perm_test(gh.pnl_same.values, B=2000) if len(gh) >= 10 else 1.0,
        }
        rec["ppt_train"] = rec["pnl_train"] / rec["n_train"] if rec["n_train"] else 0
        rec["ppt_held"] = rec["pnl_held"] / rec["n_held"] if rec["n_held"] else 0
        # Verdict
        if rec["pnl_train"] > 0 and rec["pnl_held"] > 0 and rec["perm_p_train"] < 0.05:
            rec["verdict"] = "KEEP_RIGOROUS"
        elif rec["pnl_train"] > 0 and rec["pnl_held"] > 0:
            rec["verdict"] = "KEEP_BOTH_POSITIVE"
        elif rec["pnl_train"] > 0:
            rec["verdict"] = "KEEP_TRAIN_ONLY"
        elif rec["pnl_train"] < 0 and rec["pnl_held"] < 0 and rec["perm_p_train"] > 0.95:
            rec["verdict"] = "FADE_RIGOROUS"   # consistently loses, fade
        else:
            rec["verdict"] = "NULL"
        rows.append(rec)

    df = pd.DataFrame(rows).sort_values("pnl_full" if "pnl_full" in pd.DataFrame(rows).columns else "pnl_train", ascending=False)
    df["pnl_full"] = df.pnl_train + df.pnl_held
    df = df.sort_values("pnl_full", ascending=False)

    print(f"\n=== ALL SLEEVES (sorted by full PnL) ===")
    print(f"{'sleeve_id':<42s} {'n':>5s} {'tr_pnl':>9s} {'tr_p':>6s} {'hd_pnl':>9s} {'hd_p':>6s} {'verdict':<22s}")
    print("-" * 110)
    for _, r in df.iterrows():
        print(f"{r.sleeve_id:<42s} {r.n_full:>5d} ${r.pnl_train:>+7.2f} {r.perm_p_train:>6.3f} "
              f"${r.pnl_held:>+7.2f} {r.perm_p_held:>6.3f} {r.verdict:<22s}")

    # Filter to actionable
    keep_rigorous = df[df.verdict == "KEEP_RIGOROUS"]
    keep_both = df[df.verdict == "KEEP_BOTH_POSITIVE"]
    fade_rigorous = df[df.verdict == "FADE_RIGOROUS"]

    print(f"\n=== SUMMARY ===")
    print(f"KEEP_RIGOROUS  (train>0, held>0, perm p<0.05): {len(keep_rigorous)} sleeves")
    if len(keep_rigorous):
        total_tr = float(keep_rigorous.pnl_train.sum())
        total_hd = float(keep_rigorous.pnl_held.sum())
        span_days = span.total_seconds() / 86400
        print(f"  train PnL: ${total_tr:+,.2f}  ({total_tr/(span_days*0.8):+,.2f}/day)")
        print(f"  held  PnL: ${total_hd:+,.2f}  ({total_hd/(span_days*0.2):+,.2f}/day)")
        print(f"  total  : ${total_tr + total_hd:+,.2f}  monthly proj: ${(total_tr+total_hd)/(span_days/30):+,.2f}")
    print(f"\nKEEP_BOTH_POSITIVE (train>0 + held>0, not necessarily significant): {len(keep_both)} sleeves")
    if len(keep_both):
        total_tr = float(keep_both.pnl_train.sum())
        total_hd = float(keep_both.pnl_held.sum())
        print(f"  train PnL: ${total_tr:+,.2f}")
        print(f"  held  PnL: ${total_hd:+,.2f}")
    print(f"\nFADE_RIGOROUS  (train<0, held<0, perm p>0.95): {len(fade_rigorous)} sleeves")
    if len(fade_rigorous):
        # If we INVERT these, we'd get positive PnL
        # use pnl_invert
        fade_tr_inv = 0.0; fade_hd_inv = 0.0
        for _, r in fade_rigorous.iterrows():
            sub_tr = events[(events.sleeve_id == r.sleeve_id) & (events.at_ts < train_end)]
            sub_hd = events[(events.sleeve_id == r.sleeve_id) & (events.at_ts >= train_end)]
            fade_tr_inv += float(sub_tr.pnl_invert.sum())
            fade_hd_inv += float(sub_hd.pnl_invert.sum())
        print(f"  INVERTED train PnL: ${fade_tr_inv:+,.2f}")
        print(f"  INVERTED held  PnL: ${fade_hd_inv:+,.2f}")

    df.to_csv(ROOT / "strategy_lab" / "ga_optimizer" / "runs" / "sleeve_level_analysis.csv", index=False)
    print(f"\nSaved: runs/sleeve_level_analysis.csv")

    # Combined deploy estimate
    print(f"\n=== COMBINED DEPLOY (sleeve-level + previous sub-cell FDR) ===")
    combined_full = float(keep_both.pnl_train.sum() + keep_both.pnl_held.sum())
    span_days = span.total_seconds() / 86400
    print(f"  Sleeve-level KEEP (both pos): ${combined_full:+,.2f} over {span_days:.1f}d → ${combined_full/span_days*30:+,.2f}/month")


if __name__ == "__main__":
    main()
