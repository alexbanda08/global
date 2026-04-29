"""
polymarket_forward_walk_v2.py — Out-of-sample test for E10 (rev15 + hedge-hold)
across all 3 assets and both timeframes.

Splits each asset's universe chronologically 80/20:
  TRAIN: oldest 80% by resolve_unix
  HOLDOUT: newest 20%

Quantile thresholds (q20) computed from TRAIN ONLY.

Reports per (signal × tf × asset) cell, train vs holdout side-by-side:
  hit rate, total PnL, 95% CI, ROI/bet.

If holdout hit% stays within ~5pp of train AND CI lower bound >0,
the strategy generalizes.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
# Reuse simulator + loaders from the v2 grid
from polymarket_signal_grid_v2 import (
    load_features, load_trajectories, load_klines_1m,
    simulate_market,
    add_prob_signal,
)

OUT_MD = HERE / "reports" / "POLYMARKET_FORWARD_WALK_V2.md"
RNG = np.random.default_rng(42)
ASSETS = ["btc", "eth", "sol"]


def split_chrono(df: pd.DataFrame, train_frac: float = 0.8) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.sort_values("window_start_unix").reset_index(drop=True)
    cut = int(len(df) * train_frac)
    return df.iloc[:cut].copy(), df.iloc[cut:].copy()


def evaluate(df: pd.DataFrame, traj_by_asset: dict, k1m_by_asset: dict,
             rev_bp: int, hedge_hold: bool) -> dict:
    pnls = []
    for _, row in df.iterrows():
        traj_g = traj_by_asset[row.asset].get(row.slug)
        if traj_g is None or traj_g.empty:
            continue
        k1m = k1m_by_asset[row.asset]
        pnls.append(simulate_market(row, traj_g, k1m,
                                    target=None, stop=None,
                                    rev_bp=rev_bp, merge_aware=False,
                                    hedge_hold=hedge_hold))
    pnls = np.array(pnls)
    if len(pnls) == 0:
        return {"n":0,"total_pnl":0.0,"ci_lo":0.0,"ci_hi":0.0,"hit":float("nan"),"roi":float("nan")}
    boot = RNG.choice(pnls, size=(2000, len(pnls)), replace=True).sum(axis=1)
    return {
        "n": len(pnls),
        "total_pnl": float(pnls.sum()),
        "ci_lo": float(np.quantile(boot, 0.025)),
        "ci_hi": float(np.quantile(boot, 0.975)),
        "hit": float((pnls > 0).mean()),
        "roi": float(pnls.sum() / max(len(pnls),1) * 100),
    }


def add_q20_signal_with_train_threshold(df: pd.DataFrame, train_df: pd.DataFrame) -> pd.DataFrame:
    """Compute q20 threshold per (asset, tf) from train_df only, apply to df."""
    out = df.copy()
    out["signal"] = -1
    for asset in df.asset.unique():
        for tf in df.timeframe.unique():
            tm = (train_df.asset == asset) & (train_df.timeframe == tf)
            ret_train = train_df.loc[tm, "ret_5m"].abs()
            if len(ret_train) < 50:
                continue
            q20 = ret_train.quantile(0.80)
            sel = (out.asset == asset) & (out.timeframe == tf) & out.ret_5m.notna() & (out.ret_5m.abs() >= q20)
            out.loc[sel, "signal"] = (out.loc[sel, "ret_5m"] > 0).astype(int)
    return out[out.signal != -1].copy()


def add_full_signal(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["signal"] = (out.ret_5m > 0).astype(int)
    out.loc[out.ret_5m.isna(), "signal"] = -1
    return out[out.signal != -1].copy()


def main():
    print("Loading features + trajectories + klines...")
    feats = pd.concat([load_features(a) for a in ASSETS], ignore_index=True)
    traj_by_asset = {a: load_trajectories(a) for a in ASSETS}
    k1m_by_asset  = {a: load_klines_1m(a)   for a in ASSETS}

    md = ["# Forward-Walk Holdout v2 — E10 hedge-hold, cross-asset\n",
          "Per (asset, timeframe, signal): chronological 80/20 split. q20 threshold "
          "fit on TRAIN only. Strategy = sig_ret5m + Binance reversal at 15 bps + "
          "buy-other-side-and-hold-to-resolution.\n"]

    PROB_COLS = {"prob_a", "prob_b", "prob_c", "prob_stack"}

    rows = []
    for sig_label in ["full", "q20", "prob_a", "prob_b", "prob_c", "prob_stack"]:
        for tf in ["5m", "15m"]:
            for asset_filter in [None, "btc", "eth", "sol"]:
                base = feats if asset_filter is None else feats[feats.asset == asset_filter]
                base = base[base.timeframe == tf].copy()
                if len(base) < 100:
                    continue

                # Chronological split on the SUBSET
                train_raw, holdout_raw = split_chrono(base, 0.8)

                if sig_label == "full":
                    train_signal   = add_full_signal(train_raw)
                    holdout_signal = add_full_signal(holdout_raw)
                elif sig_label in PROB_COLS:
                    # prob signals use calibrated threshold; no train/holdout leakage
                    train_signal   = add_prob_signal(train_raw,   sig_label)
                    holdout_signal = add_prob_signal(holdout_raw, sig_label)
                else:
                    # q20 threshold from TRAIN; then apply to both train and holdout
                    train_signal   = add_q20_signal_with_train_threshold(train_raw, train_raw)
                    holdout_signal = add_q20_signal_with_train_threshold(holdout_raw, train_raw)

                # Skip if either side too thin
                if len(train_signal) < 50 or len(holdout_signal) == 0:
                    continue

                tr_e0 = evaluate(train_signal,   traj_by_asset, k1m_by_asset, rev_bp=None, hedge_hold=False)
                tr_e10 = evaluate(train_signal,  traj_by_asset, k1m_by_asset, rev_bp=15,  hedge_hold=True)
                ho_e0 = evaluate(holdout_signal, traj_by_asset, k1m_by_asset, rev_bp=None, hedge_hold=False)
                ho_e10 = evaluate(holdout_signal,traj_by_asset, k1m_by_asset, rev_bp=15,  hedge_hold=True)

                rows.append({
                    "signal": sig_label, "tf": tf, "asset": asset_filter or "ALL",
                    "tr_n_e0": tr_e0["n"], "tr_pnl_e0": tr_e0["total_pnl"], "tr_hit_e0": tr_e0["hit"],
                    "tr_n_e10": tr_e10["n"], "tr_pnl_e10": tr_e10["total_pnl"], "tr_hit_e10": tr_e10["hit"],
                    "tr_ci_lo_e10": tr_e10["ci_lo"], "tr_ci_hi_e10": tr_e10["ci_hi"], "tr_roi_e10": tr_e10["roi"],
                    "ho_n_e0": ho_e0["n"], "ho_pnl_e0": ho_e0["total_pnl"], "ho_hit_e0": ho_e0["hit"],
                    "ho_n_e10": ho_e10["n"], "ho_pnl_e10": ho_e10["total_pnl"], "ho_hit_e10": ho_e10["hit"],
                    "ho_ci_lo_e10": ho_e10["ci_lo"], "ho_ci_hi_e10": ho_e10["ci_hi"], "ho_roi_e10": ho_e10["roi"],
                })

                print(f"{sig_label:4s} {tf:3s} {(asset_filter or 'ALL'):3s}  "
                      f"E10 TRAIN n={tr_e10['n']:4d} hit={tr_e10['hit']*100:5.1f}% pnl=${tr_e10['total_pnl']:+7.2f} CI=[${tr_e10['ci_lo']:+5.0f},${tr_e10['ci_hi']:+5.0f}] | "
                      f"HOLD n={ho_e10['n']:4d} hit={ho_e10['hit']*100:5.1f}% pnl=${ho_e10['total_pnl']:+7.2f} CI=[${ho_e10['ci_lo']:+5.0f},${ho_e10['ci_hi']:+5.0f}]")

    # Markdown
    for sig_label in ["full", "q20", "prob_a", "prob_b", "prob_c", "prob_stack"]:
        for tf in ["5m", "15m"]:
            sub = [r for r in rows if r["signal"] == sig_label and r["tf"] == tf]
            if not sub:
                continue
            md.append(f"\n## {sig_label} signal — {tf}\n")
            md.append("| Asset | Train n / hit / PnL [CI] | Holdout n / hit / PnL [CI] / ROI | E0_hold holdout (control) |")
            md.append("|---|---|---|---|")
            for r in sub:
                tr = (f"{r['tr_n_e10']} / {r['tr_hit_e10']*100:.1f}% / "
                      f"${r['tr_pnl_e10']:+.2f} [${r['tr_ci_lo_e10']:+.0f},${r['tr_ci_hi_e10']:+.0f}]")
                ho = (f"{r['ho_n_e10']} / {r['ho_hit_e10']*100:.1f}% / "
                      f"${r['ho_pnl_e10']:+.2f} [${r['ho_ci_lo_e10']:+.0f},${r['ho_ci_hi_e10']:+.0f}] / "
                      f"{r['ho_roi_e10']:+.2f}%")
                ctrl = (f"hit {r['ho_hit_e0']*100:.1f}% / "
                        f"${r['ho_pnl_e0']:+.2f}")
                md.append(f"| {r['asset']} | {tr} | {ho} | {ctrl} |")

    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {OUT_MD}")


if __name__ == "__main__":
    main()
