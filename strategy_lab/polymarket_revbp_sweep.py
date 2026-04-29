"""
polymarket_revbp_sweep.py — Find the optimal rev_bp threshold for the
hedge-hold exit (E10 family).

Tests rev_bp ∈ {8, 10, 12, 15, 18, 20, 25, 30, 40, 50} on each
(signal × tf × asset) cell, with hedge_hold=True.

Output: reports/POLYMARKET_REVBP_SWEEP.md
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from polymarket_signal_grid_v2 import (
    load_features, load_trajectories, load_klines_1m,
    simulate_market, add_q20_signal, add_full_signal,
)

OUT_MD = HERE / "reports" / "POLYMARKET_REVBP_SWEEP.md"
RNG = np.random.default_rng(42)
ASSETS = ["btc", "eth", "sol"]
REV_BPS = [8, 10, 12, 15, 18, 20, 25, 30, 40, 50]


def evaluate(df, traj_by_asset, k1m_by_asset, rev_bp):
    pnls = []
    for _, row in df.iterrows():
        traj_g = traj_by_asset[row.asset].get(row.slug)
        if traj_g is None or traj_g.empty:
            continue
        k1m = k1m_by_asset[row.asset]
        pnls.append(simulate_market(row, traj_g, k1m,
                                    target=None, stop=None,
                                    rev_bp=rev_bp, merge_aware=False,
                                    hedge_hold=True))
    pnls = np.array(pnls)
    if len(pnls) == 0:
        return None
    boot = RNG.choice(pnls, size=(2000, len(pnls)), replace=True).sum(axis=1)
    return {
        "n": len(pnls),
        "pnl": float(pnls.sum()),
        "ci_lo": float(np.quantile(boot, 0.025)),
        "ci_hi": float(np.quantile(boot, 0.975)),
        "hit": float((pnls > 0).mean()),
        "roi": float(pnls.sum() / max(len(pnls),1) * 100),
    }


def main():
    print("Loading...")
    feats = pd.concat([load_features(a) for a in ASSETS], ignore_index=True)
    traj_by_asset = {a: load_trajectories(a) for a in ASSETS}
    k1m_by_asset  = {a: load_klines_1m(a)   for a in ASSETS}

    feats_q20  = add_q20_signal(feats)
    feats_full = add_full_signal(feats)

    rows = []
    for sig_label, sig_df in [("full", feats_full), ("q20", feats_q20)]:
        for tf in ["5m", "15m"]:
            sub = sig_df[sig_df.timeframe == tf]
            for rev_bp in REV_BPS:
                r = evaluate(sub, traj_by_asset, k1m_by_asset, rev_bp)
                if r is None:
                    continue
                r.update({"signal":sig_label, "tf":tf, "rev_bp":rev_bp})
                rows.append(r)
                print(f"{sig_label:4s} {tf:3s} rev={rev_bp:3d}bp → "
                      f"n={r['n']:4d} pnl=${r['pnl']:+8.2f} "
                      f"CI=[${r['ci_lo']:+5.0f},${r['ci_hi']:+5.0f}] "
                      f"hit={r['hit']*100:5.1f}% roi={r['roi']:+.2f}%")

    df = pd.DataFrame(rows)
    md = ["# rev_bp Sweep — E10 hedge-hold — Apr 22-27, all 3 assets\n",
          "Strategy: `sig_ret5m` (or q20 filter) + Binance-reversal trigger at "
          "`rev_bp` basis points + buy opposite side at ask + hold to resolution. "
          "Lower `rev_bp` = more sensitive trigger = more hedges fired.\n"]
    for sig_label in ["full", "q20"]:
        for tf in ["5m", "15m"]:
            sub = df[(df.signal == sig_label) & (df.tf == tf)].sort_values("rev_bp")
            md.append(f"\n## {sig_label} signal — {tf} — sweep\n")
            md.append("| rev_bp | n | PnL | 95% CI | Hit% | ROI/bet |")
            md.append("|---|---|---|---|---|---|")
            for _, r in sub.iterrows():
                md.append(
                    f"| {int(r['rev_bp'])} bp | {int(r['n'])} | ${r['pnl']:+.2f} | "
                    f"[${r['ci_lo']:+.0f}, ${r['ci_hi']:+.0f}] | "
                    f"{r['hit']*100:.1f}% | {r['roi']:+.2f}% |"
                )
            best = sub.loc[sub["pnl"].idxmax()]
            md.append(f"\n**Best: `rev_bp={int(best['rev_bp'])}` → ${best['pnl']:+.2f} "
                     f"[${best['ci_lo']:+.0f}, ${best['ci_hi']:+.0f}], "
                     f"hit={best['hit']*100:.1f}%, ROI={best['roi']:+.2f}%/bet**\n")

    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {OUT_MD}")


if __name__ == "__main__":
    main()
