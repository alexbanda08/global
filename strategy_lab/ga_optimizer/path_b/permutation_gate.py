"""
Permutation test on robust cells before final deployment.

For each deployable cell:
  - Take the events in that cell (held-out window for harshest test)
  - Apply chosen action → realized PnL
  - Permute the action outcome (flip won/lost randomly per event 1000×)
  - Real PnL must beat 95th percentile of permuted distribution → keep

Final deployable = robust + permutation-significant.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from strategy_lab.ga_optimizer.path_b.events import load_path_b_events


def perm_test_cell(events_in_cell: pd.DataFrame, action: str, B: int = 1000,
                   rng_seed: int = 42) -> dict:
    """
    Permutation test: real PnL vs random sign-flips.
    Returns p_value (one-sided, P(perm >= observed)).
    """
    rng = np.random.default_rng(rng_seed)
    if action == "KEEP":
        pnls = events_in_cell.pnl_same.values
    elif action == "INVERT":
        pnls = events_in_cell.pnl_invert.values
    else:
        return dict(observed=0.0, p_value=1.0)
    observed = float(pnls.sum())
    n = len(pnls)
    if n == 0:
        return dict(observed=observed, p_value=1.0, n=0)
    perm_sums = []
    for _ in range(B):
        signs = rng.choice([1, -1], size=n)
        perm_sums.append(float((pnls * signs).sum()))
    perm_sums = np.array(perm_sums)
    p = float((perm_sums >= observed).mean())
    return dict(observed=observed, p_value=p, n=n,
                perm_p05=float(np.percentile(perm_sums, 5)),
                perm_p95=float(np.percentile(perm_sums, 95)))


def main():
    print("=== Permutation gate on robust cells ===")
    deployable = pd.read_csv(ROOT / "strategy_lab" / "ga_optimizer" / "runs" / "robust_cells_deployable.csv")
    print(f"deployable cells (pre-permutation): {len(deployable)}")

    events = load_path_b_events()
    events = events.sort_values("at_ts").reset_index(drop=True)
    ts_min = events.at_ts.min(); ts_max = events.at_ts.max()
    val_end = ts_min + (ts_max - ts_min) * 0.80
    events_held = events[events.at_ts >= val_end]
    events_full = events

    # Per cell: perm on held-out + perm on full
    results = []
    for _, c in deployable.iterrows():
        ev_full = events_full[events_full.cell_id == c.cell_id]
        ev_held = events_held[events_held.cell_id == c.cell_id]
        # Test on full window (more samples = tighter test)
        perm_full = perm_test_cell(ev_full, c.action, B=1000)
        perm_held = perm_test_cell(ev_held, c.action, B=1000) if len(ev_held) >= 5 else dict(p_value=1.0, n=0)
        rec = {**c.to_dict(),
                "perm_p_full": perm_full["p_value"],
                "perm_p_held": perm_held["p_value"],
                "n_held": perm_held["n"],
                "perm_full_observed": perm_full["observed"],
                "perm_full_p95": perm_full.get("perm_p95", 0)}
        results.append(rec)

    out = pd.DataFrame(results)
    out.to_csv(ROOT / "strategy_lab" / "ga_optimizer" / "runs" / "robust_cells_with_perm.csv", index=False)

    # Tier 1: permutation p < 0.05 on FULL window AND positive on held-out
    out["held_pnl"] = out.apply(
        lambda r: r["pnl_keep_held"] if r["action"] == "KEEP" else r["pnl_invert_held"], axis=1)
    tier1 = out[(out.perm_p_full < 0.05) & (out.held_pnl > 0)]
    tier2 = out[(out.perm_p_full < 0.10) & (out.held_pnl > 0) & ~out.index.isin(tier1.index)]
    tier3 = out[(out.perm_p_full < 0.20) & (out.held_pnl > 0) & ~out.index.isin(tier1.index) & ~out.index.isin(tier2.index)]

    print(f"\n=== TIER 1 (p<0.05 full + held>0): {len(tier1)} cells ===")
    cols = ["sleeve_id", "signal", "hour_bucket", "dow_group", "action",
            "n_full", "deploy_pnl_full", "held_pnl", "perm_p_full", "perm_p_held"]
    print(tier1[cols].sort_values("deploy_pnl_full", ascending=False).to_string(index=False))

    print(f"\n=== TIER 2 (0.05<p<0.10 full + held>0): {len(tier2)} cells ===")
    print(tier2[cols].sort_values("deploy_pnl_full", ascending=False).to_string(index=False))

    print(f"\n=== TIER 3 (0.10<p<0.20 full + held>0): {len(tier3)} cells ===")
    print(tier3[cols].sort_values("deploy_pnl_full", ascending=False).head(15).to_string(index=False))

    # Aggregate per tier
    print(f"\n=== Aggregate (held-out 2.6 days) ===")
    for name, t in [("TIER 1", tier1), ("TIER 2", tier2), ("TIER 3", tier3)]:
        if len(t) == 0:
            print(f"  {name}: 0 cells"); continue
        full_pnl = float(t["deploy_pnl_full"].sum())
        held_pnl = float(t["held_pnl"].sum())
        n_trades_held = int(t["n_held"].sum())
        print(f"  {name}: {len(t)} cells, full_pnl=${full_pnl:+,.2f}, held_pnl=${held_pnl:+,.2f} (n_held={n_trades_held})")

    combined = pd.concat([tier1, tier2])
    combined_held = float(combined["held_pnl"].sum())
    combined_full = float(combined["deploy_pnl_full"].sum())
    print(f"\n  TIER 1+2 combined: {len(combined)} cells, full ${combined_full:+,.2f}, held ${combined_held:+,.2f}")
    print(f"    daily rate (held): ${combined_held/2.6:+,.2f}/day")
    print(f"    conservative monthly (held×11.5): ${combined_held * (30/2.6):+,.2f}")
    print(f"    full-window monthly (full×2.3): ${combined_full * (30/13):+,.2f}")

    # Final deploy list
    deploy_list = pd.concat([tier1, tier2]).sort_values("deploy_pnl_full", ascending=False)
    deploy_list.to_csv(ROOT / "strategy_lab" / "ga_optimizer" / "runs" / "FINAL_DEPLOY_LIST.csv", index=False)
    print(f"\nFINAL deploy list saved: strategy_lab/ga_optimizer/runs/FINAL_DEPLOY_LIST.csv")


if __name__ == "__main__":
    main()
