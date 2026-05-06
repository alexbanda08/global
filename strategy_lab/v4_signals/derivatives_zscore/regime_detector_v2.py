"""regime_detector_v2 — addresses the 5 limitations from v1:

  Fix 1 (small linear corrs)    → multi-timeframe analysis on 1h / 4h / 1d resamples
  Fix 2 (±inf in cross_*)       → fixed upstream in compute_zscores.py (must re-run that first)
  Fix 3 (single label cell)     → multi-cell label robustness — run analysis on 3 cells
  Fix 4 (linear-only)           → sklearn HistGradientBoostingClassifier feature importance
  Fix 5 (BTC only)              → run pipeline on BTC, ETH, SOL

Outputs:
  strategy_lab/reports/derivatives_zscore/regime_detector_v2/
    {SYMBOL}/
      tf_correlations.csv         — Pearson corr per timeframe (1h, 4h, 1d)
      multi_label_sequencing.csv  — sequencing for 3 label cells
      gb_feature_importance.csv   — gradient-boosting feature importance per side / horizon
      SUMMARY.md
"""
from __future__ import annotations
from pathlib import Path
import argparse
import sys
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=UserWarning)

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "strategy_lab"))

PANELS = ROOT / "data" / "v4" / "derivatives_zscore" / "panels"
SPOT = ROOT / "data" / "v4" / "derivatives_zscore" / "spot"
OUT_BASE = ROOT / "strategy_lab" / "reports" / "derivatives_zscore" / "regime_detector_v2"
OUT_BASE.mkdir(parents=True, exist_ok=True)


INDICATORS = [
    "z_lsr", "z_fund", "z_oi", "z_oi_silent", "z_cb_premium",
    "z_dom_stables", "z_top_lsr_count", "z_top_lsr_sum", "z_taker_ratio",
    "brigalS", "oilsr",
    "cross_institutional_lead", "cross_leverage_heat", "cross_risk_off", "cross_real_money",
]


# ─────────────────────────────────────────
#  Load + feature engineering
# ─────────────────────────────────────────

def load_symbol(symbol: str, freq: str = "1h") -> pd.DataFrame:
    """Load panel + spot, resampled to `freq`."""
    p = pd.read_parquet(PANELS / f"{symbol}_zscore.parquet").resample(freq).last()
    tag = symbol.replace("USDT", "")
    spot = pd.read_parquet(SPOT / f"BINANCE-{tag}-1h.parquet").set_index("time")
    for c in ["open", "high", "low", "close"]:
        p[c] = spot[c].astype(float).reindex(p.index, method="ffill")
    # clean inf/nan from indicator columns
    for c in INDICATORS:
        if c in p.columns:
            p[c] = p[c].replace([np.inf, -np.inf], np.nan)
    return p.dropna(subset=["close", "z_lsr"])


# ─────────────────────────────────────────
#  Fix 3 — multi-cell label robustness
# ─────────────────────────────────────────

LABEL_CELLS = [
    ("loose",  0.02, 12, 0.005),  # 2% in 12h with ±0.5% counter (more events, noisier)
    ("medium", 0.03, 24, 0.010),  # 3% in 24h with ±1% counter (chosen in v1)
    ("tight",  0.05, 48, 0.015),  # 5% in 48h with ±1.5% counter (cleaner, fewer events)
]


def label_trend_starts(df: pd.DataFrame, X: float, Y: int, Z: float):
    """Same logic as v1 — vectorize-ish via numpy loops for clarity."""
    n = len(df)
    close = df["close"].to_numpy()
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    bull = np.zeros(n, dtype=bool)
    bear = np.zeros(n, dtype=bool)
    for i in range(n - Y):
        c0 = close[i]
        bull_target = c0 * (1 + X)
        bull_floor = c0 * (1 - Z)
        bear_target = c0 * (1 - X)
        bear_ceil = c0 * (1 + Z)
        bull_seen = False
        bull_clean = True
        bear_seen = False
        bear_clean = True
        for j in range(i + 1, i + Y + 1):
            if low[j] <= bull_floor:
                bull_clean = False
            if high[j] >= bull_target and bull_clean and not bull_seen:
                bull_seen = True
            if high[j] >= bear_ceil:
                bear_clean = False
            if low[j] <= bear_target and bear_clean and not bear_seen:
                bear_seen = True
            if not bull_clean and not bear_clean:
                break
        bull[i] = bull_seen and bull_clean
        bear[i] = bear_seen and bear_clean
    return pd.Series(bull, index=df.index), pd.Series(bear, index=df.index)


def multi_label_sequencing(df: pd.DataFrame) -> pd.DataFrame:
    """Compute mean indicator state at offset 0 for each label cell × side.
    Reveals which sequencing patterns are STABLE across label definitions
    (vs which only show up in one cell — likely overfit to that label)."""
    rows = []
    for cell_name, X, Y, Z in LABEL_CELLS:
        bull, bear = label_trend_starts(df, X, Y, Z)
        for side, mask in [("bull", bull), ("bear", bear)]:
            n_events = int(mask.sum())
            for ind in INDICATORS:
                if ind not in df.columns:
                    continue
                s = df.loc[mask.values & df[ind].notna().values, ind]
                if len(s) < 30:
                    continue
                rows.append({
                    "label_cell": cell_name,
                    "X": X, "Y": Y, "Z": Z,
                    "side": side,
                    "n_events": n_events,
                    "indicator": ind,
                    "mean": float(s.mean()),
                    "median": float(s.median()),
                    "std": float(s.std()),
                })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────
#  Fix 1 — multi-timeframe correlation
# ─────────────────────────────────────────

def tf_correlations(symbol: str) -> pd.DataFrame:
    """Re-run indicator × horizon Pearson at 1h, 4h, 1d resamples."""
    rows = []
    for freq, horizons in [("1h", [4, 12, 24, 48]),
                           ("4h", [1, 3, 6, 12]),    # 4h, 12h, 24h, 48h equivalent
                           ("1D", [1, 3, 7])]:        # 1d, 3d, 1w
        df = load_symbol(symbol, freq=freq)
        for h in horizons:
            fwd = df["close"].shift(-h) / df["close"] - 1
            for ind in INDICATORS:
                if ind not in df.columns:
                    continue
                joined = pd.concat([df[ind], fwd], axis=1, join="inner").dropna()
                if len(joined) < 100:
                    continue
                corr = joined.iloc[:, 0].corr(joined.iloc[:, 1])
                # tag horizon in hours for cross-tf comparability
                if freq == "1h":
                    h_hours = h
                elif freq == "4h":
                    h_hours = h * 4
                else:
                    h_hours = h * 24
                rows.append({"symbol": symbol, "timeframe": freq,
                             "horizon_h": h_hours,
                             "indicator": ind, "pearson_corr": float(corr),
                             "n": len(joined)})
    return pd.DataFrame(rows)


# ─────────────────────────────────────────
#  Fix 4 — gradient-boosting feature importance
# ─────────────────────────────────────────

def gb_feature_importance(df: pd.DataFrame, label_X: float = 0.03,
                          label_Y: int = 24, label_Z: float = 0.010) -> pd.DataFrame:
    """Train a HistGradientBoostingClassifier to predict bull/bear trend-starts at multiple horizons.

    Returns a long DataFrame: side × horizon × indicator × importance.
    Importance is permutation-style normalized to sum to 1 per (side, horizon).
    """
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.inspection import permutation_importance
    from sklearn.model_selection import train_test_split

    bull, bear = label_trend_starts(df, label_X, label_Y, label_Z)
    feat_cols = [c for c in INDICATORS if c in df.columns]
    X = df[feat_cols].copy()
    # Drop rows with too many NaN feature cells
    X = X.dropna(thresh=int(0.7 * len(feat_cols)))

    rows = []
    for side, mask in [("bull", bull), ("bear", bear)]:
        y = mask.reindex(X.index).fillna(False).astype(int)
        if y.sum() < 50:
            continue
        Xtr, Xte, ytr, yte = train_test_split(X.fillna(0), y, test_size=0.3,
                                              shuffle=False)
        model = HistGradientBoostingClassifier(
            max_iter=200, learning_rate=0.05, max_depth=4,
            random_state=42, class_weight="balanced",
        )
        model.fit(Xtr, ytr)
        score_tr = model.score(Xtr, ytr)
        score_te = model.score(Xte, yte)
        # Permutation importance (more honest than gain — tests actual contribution OOS)
        result = permutation_importance(model, Xte, yte, n_repeats=5,
                                        random_state=42, n_jobs=1)
        imps = result.importances_mean
        total = max(imps.sum(), 1e-9)
        for ind, imp in zip(feat_cols, imps):
            rows.append({
                "side": side,
                "indicator": ind,
                "permutation_importance": float(imp),
                "importance_normalized": float(imp / total),
                "train_acc": float(score_tr),
                "test_acc": float(score_te),
                "n_pos_events": int(y.sum()),
            })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────
#  Driver
# ─────────────────────────────────────────

def run_for_symbol(symbol: str):
    print(f"\n══════════ {symbol} ══════════")
    out = OUT_BASE / symbol
    out.mkdir(parents=True, exist_ok=True)

    # Fix 1: multi-timeframe corrs
    print("[1/3] Multi-timeframe correlations (1h / 4h / 1d)...")
    tf = tf_correlations(symbol)
    tf.to_csv(out / "tf_correlations.csv", index=False)
    # Show top 5 by |corr| at each timeframe
    for tfv in ["1h", "4h", "1D"]:
        sub = tf[tf["timeframe"] == tfv].copy()
        sub["abs"] = sub["pearson_corr"].abs()
        top = sub.sort_values("abs", ascending=False).head(3)
        print(f"  {tfv} top-3:")
        for _, r in top.iterrows():
            print(f"    {r['indicator']:<28} h={r['horizon_h']:>3}h  corr={r['pearson_corr']:+.4f}")

    # Fix 3: multi-label sequencing
    print("[2/3] Multi-cell label robustness ...")
    df_1h = load_symbol(symbol, freq="1h")
    seq = multi_label_sequencing(df_1h)
    seq.to_csv(out / "multi_label_sequencing.csv", index=False)
    # Cross-cell mean: which indicators are CONSISTENTLY directional across cells?
    consistency = (seq.groupby(["side", "indicator"])
                      .agg(mean_at_zero_avg=("mean", "mean"),
                           mean_at_zero_std=("mean", "std"),
                           cells=("mean", "count"))
                      .reset_index())
    consistency["sign_consistency"] = consistency.apply(
        lambda r: abs(r["mean_at_zero_avg"]) / max(r["mean_at_zero_std"], 1e-6), axis=1
    )
    consistency.to_csv(out / "label_robustness_consistency.csv", index=False)
    print("  Top 5 most label-robust indicators (high mean / low std across cells):")
    top_robust = consistency.sort_values("sign_consistency", ascending=False).head(8)
    for _, r in top_robust.iterrows():
        print(f"    {r['side']:<5} {r['indicator']:<28} "
              f"avg(mean)={r['mean_at_zero_avg']:+.3f}  std={r['mean_at_zero_std']:.3f}  "
              f"consistency={r['sign_consistency']:.2f}")

    # Fix 4: gradient boosting feature importance
    print("[3/3] Gradient boosting permutation importance ...")
    gb = gb_feature_importance(df_1h)
    gb.to_csv(out / "gb_feature_importance.csv", index=False)
    print("  Top 5 features per side (permutation importance):")
    for side in ["bull", "bear"]:
        sub = gb[gb["side"] == side].sort_values("permutation_importance", ascending=False).head(5)
        if len(sub) == 0:
            continue
        first = sub.iloc[0]
        print(f"  -- {side} -- (test_acc={first['test_acc']:.3f}, n_events={first['n_pos_events']})")
        for _, r in sub.iterrows():
            print(f"    {r['indicator']:<28} importance={r['permutation_importance']:+.4f} "
                  f"({r['importance_normalized']*100:.1f}%)")

    # Cross-method comparison: do GB importances agree with linear corrs?
    linear_top = (tf[tf["timeframe"] == "1h"]
                  .assign(abs_corr=lambda d: d["pearson_corr"].abs())
                  .groupby("indicator")["abs_corr"].max()
                  .reset_index()
                  .rename(columns={"abs_corr": "max_abs_linear_corr"}))
    gb_top = (gb[gb["side"] == "bull"]
              .groupby("indicator")["permutation_importance"].max()
              .reset_index()
              .rename(columns={"permutation_importance": "gb_importance_bull"}))
    cmp = linear_top.merge(gb_top, on="indicator", how="outer").fillna(0)
    cmp["linear_rank"] = cmp["max_abs_linear_corr"].rank(ascending=False)
    cmp["gb_rank"] = cmp["gb_importance_bull"].rank(ascending=False)
    cmp["rank_gap"] = (cmp["linear_rank"] - cmp["gb_rank"]).abs()
    cmp.to_csv(out / "linear_vs_gb_comparison.csv", index=False)
    print("\n  Linear vs GB rank comparison (top 5 indicators with biggest rank gap):")
    for _, r in cmp.sort_values("rank_gap", ascending=False).head(5).iterrows():
        print(f"    {r['indicator']:<28} linear=#{int(r['linear_rank'])}  GB=#{int(r['gb_rank'])}  "
              f"gap={int(r['rank_gap'])}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    args = ap.parse_args()

    for sym in args.symbols:
        run_for_symbol(sym)

    print(f"\nAll outputs in: {OUT_BASE}")


if __name__ == "__main__":
    main()
