"""
polymarket_revbp_floor_sweep.py — Combined in-sample sweep + forward-walk
holdout for tight rev_bp values {3, 4, 5, 6, 7, 8, 10, 12}.

Goal: find the rev_bp floor (where hedging too aggressively starts losing
to commission/spread costs) AND confirm the tight values generalize on
holdout.

Outputs:
  reports/POLYMARKET_REVBP_FLOOR_SWEEP.md
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
from polymarket_forward_walk_v2 import (
    split_chrono, add_q20_signal_with_train_threshold,
    add_full_signal as fw_add_full,
)

OUT_MD = HERE / "reports" / "POLYMARKET_REVBP_FLOOR_SWEEP.md"
RNG = np.random.default_rng(42)
ASSETS = ["btc", "eth", "sol"]
REV_BPS = [3, 4, 5, 6, 7, 8, 10, 12]


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
        return {"n":0,"pnl":0.0,"ci_lo":0.0,"ci_hi":0.0,"hit":float("nan"),"roi":float("nan")}
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

    # In-sample sweep across all 4 main universes
    print("\n=== IN-SAMPLE SWEEP ===")
    insample_rows = []
    for sig_label, sig_df in [("full", feats_full), ("q20", feats_q20)]:
        for tf in ["5m", "15m"]:
            sub = sig_df[sig_df.timeframe == tf]
            for rev_bp in REV_BPS:
                r = evaluate(sub, traj_by_asset, k1m_by_asset, rev_bp)
                r.update({"signal":sig_label, "tf":tf, "rev_bp":rev_bp})
                insample_rows.append(r)
                print(f"IS {sig_label:4s} {tf:3s} rev={rev_bp:2d}bp → "
                      f"n={r['n']:4d} pnl=${r['pnl']:+8.2f} "
                      f"CI=[${r['ci_lo']:+5.0f},${r['ci_hi']:+5.0f}] "
                      f"hit={r['hit']*100:5.1f}% roi={r['roi']:+.2f}%")

    # Forward-walk for the tight values {3, 5, 8}
    print("\n=== FORWARD-WALK HOLDOUT (chronological 80/20) ===")
    holdout_rows = []
    for rev_bp in [3, 5, 8]:
        for sig_label in ["full", "q20"]:
            for tf in ["5m", "15m"]:
                base = feats[feats.timeframe == tf].copy()
                train_raw, holdout_raw = split_chrono(base, 0.8)

                if sig_label == "full":
                    train_signal   = fw_add_full(train_raw)
                    holdout_signal = fw_add_full(holdout_raw)
                else:
                    train_signal   = add_q20_signal_with_train_threshold(train_raw, train_raw)
                    holdout_signal = add_q20_signal_with_train_threshold(holdout_raw, train_raw)

                if len(train_signal) < 50 or len(holdout_signal) == 0:
                    continue

                tr = evaluate(train_signal,   traj_by_asset, k1m_by_asset, rev_bp)
                ho = evaluate(holdout_signal, traj_by_asset, k1m_by_asset, rev_bp)
                holdout_rows.append({
                    "signal":sig_label, "tf":tf, "rev_bp":rev_bp,
                    **{f"tr_{k}":v for k,v in tr.items()},
                    **{f"ho_{k}":v for k,v in ho.items()},
                })
                print(f"FW rev={rev_bp:2d}bp {sig_label:4s} {tf:3s}  "
                      f"TR n={tr['n']:4d} hit={tr['hit']*100:5.1f}% pnl=${tr['pnl']:+7.2f} "
                      f"CI=[${tr['ci_lo']:+5.0f},${tr['ci_hi']:+5.0f}] | "
                      f"HO n={ho['n']:4d} hit={ho['hit']*100:5.1f}% pnl=${ho['pnl']:+7.2f} "
                      f"CI=[${ho['ci_lo']:+5.0f},${ho['ci_hi']:+5.0f}]")

    # Markdown
    md = ["# rev_bp Floor Sweep + Forward-Walk — E10 hedge-hold\n",
          "Apr 22-27, 5,742 markets across BTC/ETH/SOL. Strategy: `sig_ret5m` (or q20) "
          "+ Binance reversal + buy other side at ask + hold to resolution.\n"]

    md.append("\n## Part 1 — In-Sample Sweep (all data, ALL assets)\n")
    df_is = pd.DataFrame(insample_rows)
    for sig_label in ["full", "q20"]:
        for tf in ["5m", "15m"]:
            sub = df_is[(df_is.signal == sig_label) & (df_is.tf == tf)].sort_values("rev_bp")
            md.append(f"\n### {sig_label} signal — {tf}\n")
            md.append("| rev_bp | n | PnL | 95% CI | Hit% | ROI/bet |")
            md.append("|---|---|---|---|---|---|")
            for _, r in sub.iterrows():
                md.append(
                    f"| {int(r['rev_bp'])} bp | {int(r['n'])} | ${r['pnl']:+.2f} | "
                    f"[${r['ci_lo']:+.0f}, ${r['ci_hi']:+.0f}] | {r['hit']*100:.1f}% | {r['roi']:+.2f}% |"
                )
            best = sub.loc[sub["pnl"].idxmax()]
            md.append(f"\n**Best in-sample: `rev_bp={int(best['rev_bp'])}` → "
                     f"${best['pnl']:+.2f}, hit {best['hit']*100:.1f}%, ROI {best['roi']:+.2f}%/bet.**\n")

    md.append("\n## Part 2 — Forward-Walk Holdout (chronological 80/20)\n")
    df_ho = pd.DataFrame(holdout_rows)
    for rev_bp in [3, 5, 8]:
        for sig_label in ["full", "q20"]:
            for tf in ["5m", "15m"]:
                row = df_ho[(df_ho.rev_bp == rev_bp) & (df_ho.signal == sig_label) & (df_ho.tf == tf)]
                if row.empty:
                    continue
                r = row.iloc[0]
                md.append(f"\n### {sig_label} {tf} rev_bp={rev_bp}\n")
                md.append("| Phase | n | Hit% | Total PnL | 95% CI | ROI/bet |")
                md.append("|---|---|---|---|---|---|")
                md.append(f"| TRAIN (80%) | {int(r['tr_n'])} | {r['tr_hit']*100:.1f}% | "
                         f"${r['tr_pnl']:+.2f} | [${r['tr_ci_lo']:+.0f}, ${r['tr_ci_hi']:+.0f}] | {r['tr_roi']:+.2f}% |")
                md.append(f"| **HOLDOUT (20%)** | **{int(r['ho_n'])}** | **{r['ho_hit']*100:.1f}%** | "
                         f"**${r['ho_pnl']:+.2f}** | **[${r['ho_ci_lo']:+.0f}, ${r['ho_ci_hi']:+.0f}]** | "
                         f"**{r['ho_roi']:+.2f}%** |")

    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {OUT_MD}")


if __name__ == "__main__":
    main()
