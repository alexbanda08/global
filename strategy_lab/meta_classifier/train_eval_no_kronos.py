"""
train_eval_no_kronos — same pipeline as train_eval.py but ALL Kronos features removed
from the trained meta-classifier (ablations C, D, E, F, G).

Hypothesis: removing dead-weight Kronos features (kr_pred_*) lifts AUC + hit rate of
the full ensemble. v2 found D_Kronos+TA AUC (0.506) was WORSE than C_TA_only (0.512),
and Kronos features had near-zero permutation importance in E_full.

Ablations:
  A — V3 baseline (prob_stack direct)                            [unchanged]
  B — Kronos handcrafted (control, single signal source)         [unchanged]
  C — TA + time only HGB                                         [unchanged]
  D — TA + DerivZScore + time HGB (replaces old Kronos+TA)      [NEW: was Kronos+TA]
  E — V3 + TA + DerivZScore + regime + time HGB (full, NO Kronos) [MODIFIED]
  F — E + ATR/ADX gate                                            [unchanged structure]
  G — V3 + TA + time HGB (clean comparison; no DerivZ, no Kronos) [NEW]

Outputs (under v3_no_kronos prefix by default):
  strategy_lab/results/meta_classifier/v3_no_kronos_ablation_table.csv
  strategy_lab/results/meta_classifier/v3_no_kronos_feature_importance.csv
  strategy_lab/results/meta_classifier/v3_no_kronos_predictions_oof.parquet
  strategy_lab/results/meta_classifier/v3_no_kronos_calibration_curve.csv
"""
from __future__ import annotations
from pathlib import Path
import os
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.model_selection import TimeSeriesSplit

ROOT = Path(__file__).resolve().parents[2]
LABELED = Path(os.environ.get("LABELED_OVERRIDE",
    str(ROOT / "strategy_lab" / "data" / "meta_classifier" / "labeled_v2.parquet")))
OUT_DIR = ROOT / "strategy_lab" / "results" / "meta_classifier"
OUT_PREFIX = os.environ.get("OUT_PREFIX", "v3_no_kronos")

# Feature sets
TA_FEATURES = ["ta_atr_14", "ta_atr_pct", "ta_adx_14", "ta_plus_di_14",
               "ta_minus_di_14", "ta_atr_quantile_30d",
               "ta_above_ma200", "ta_price_vs_ma200_pct",
               "ta_rvol_24h", "ta_rvol_quintile_30d"]
TA_GATE_FEATURES = ["ta_atr_quantile_30d", "ta_adx_above_25"]
KRONOS_FEATURES = ["kr_pred_dir_5m", "kr_pred_dir_15m", "kr_pred_ret_5m", "kr_pred_ret_15m"]  # used ONLY for control B
V3_FEATURES = ["abs_move_pct", "ret_5m", "ret_15m", "ret_1h",
               "oi_now", "oi_delta_5m", "oi_delta_15m", "oi_delta_1h", "oiv_delta_5m",
               "ls_count", "ls_count_delta_5m", "ls_top_count", "ls_top_sum",
               "smart_minus_retail", "taker_ratio", "taker_delta_5m",
               "book_skew", "entry_yes_ask", "entry_no_ask",
               "prob_a", "prob_b", "prob_c", "prob_stack"]
DERIV_REGIME_FEATURES = [
    "dz_funding_rate", "dz_z_fund",
    "dz_z_lsr", "dz_brigalS",
    "dz_z_top_lsr_count", "dz_z_top_lsr_sum",
    "dz_z_oi", "dz_z_oi_silent", "dz_oilsr",
    "dz_z_taker_ratio", "dz_z_dom_stables",
    "dz_cross_institutional_lead", "dz_cross_retail_lead",
    "dz_cross_leverage_heat", "dz_cross_risk_off", "dz_cross_real_money",
    "dz_score_bull_scaled", "dz_score_bear_scaled",
]
TIME_FEATURES = ["hour_utc", "dow_utc"]


def safe_features(df, feats):
    return [f for f in feats if f in df.columns]


def calibration_curve(p_pred, outcome, n_bins=10):
    confidence = np.maximum(p_pred, 1 - p_pred)
    pred_dir = (p_pred > 0.5).astype(int)
    correct = (pred_dir == outcome).astype(int)
    bins = np.linspace(0.5, 1.0, n_bins + 1)
    rows = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        mask = (confidence >= lo) & (confidence < hi if hi < 1.0 else confidence <= hi)
        if mask.sum() == 0:
            continue
        mean_pred = float(confidence[mask].mean())
        observed = float(correct[mask].mean())
        diff = observed - mean_pred
        if abs(diff) < 0.02:
            interp = "well-calibrated"
        elif diff < -0.05:
            interp = "SEVERELY overconfident — do not trade"
        elif diff < -0.02:
            interp = "overconfident — reduce sizing"
        elif diff > 0.05:
            interp = "underconfident — model conservative"
        else:
            interp = "slightly underconfident"
        rows.append({"bin_lo": round(lo, 3), "bin_hi": round(hi, 3),
                     "n": int(mask.sum()), "mean_pred": round(mean_pred, 4),
                     "observed": round(observed, 4), "diff": round(diff, 4),
                     "interpretation": interp})
    return pd.DataFrame(rows)


def kelly_fraction(p_win, payout=1.98):
    b = payout - 1.0
    f = (b * p_win - (1.0 - p_win)) / b
    return max(0.0, min(f, 1.0))


def trade_economics(p_pred, outcome, threshold, bankroll=1000.0, max_kelly=0.25):
    fee = 0.01
    payout = 1.98
    bet_mask = np.maximum(p_pred, 1 - p_pred) > threshold
    if bet_mask.sum() == 0:
        return {"n_bets": 0, "hit_rate": np.nan, "mean_p": np.nan,
                "roi_per_bet": np.nan, "total_pnl_flat": 0.0,
                "kelly_final_eq": bankroll, "half_kelly_final_eq": bankroll,
                "kelly_max_dd_pct": 0.0, "half_kelly_max_dd_pct": 0.0}
    pred_dir = (p_pred > 0.5).astype(int)
    win = (pred_dir == outcome).astype(int)
    confidence = np.maximum(p_pred, 1 - p_pred)
    pnl_flat = np.where(win == 1, 1.00 - 0.50 - fee, 0.00 - 0.50 - fee)
    bal_k = bal_hk = bankroll
    eq_k, eq_hk = [], []
    for i in np.where(bet_mask)[0]:
        f_full = min(kelly_fraction(confidence[i], payout), max_kelly)
        f_half = f_full * 0.5
        stake_k = bal_k * f_full
        stake_hk = bal_hk * f_half
        if win[i] == 1:
            bal_k += stake_k * (payout - 1)
            bal_hk += stake_hk * (payout - 1)
        else:
            bal_k -= stake_k
            bal_hk -= stake_hk
        eq_k.append(bal_k)
        eq_hk.append(bal_hk)
    eq_k = np.array(eq_k); eq_hk = np.array(eq_hk)
    dd_k = ((eq_k / np.maximum.accumulate(eq_k)) - 1).min() if len(eq_k) else 0.0
    dd_hk = ((eq_hk / np.maximum.accumulate(eq_hk)) - 1).min() if len(eq_hk) else 0.0
    return {"n_bets": int(bet_mask.sum()),
            "hit_rate": float(win[bet_mask].mean()),
            "mean_p": float(confidence[bet_mask].mean()),
            "roi_per_bet": float(pnl_flat[bet_mask].mean() / 0.50),
            "total_pnl_flat": float(pnl_flat[bet_mask].sum()),
            "kelly_final_eq": float(bal_k),
            "half_kelly_final_eq": float(bal_hk),
            "kelly_max_dd_pct": float(dd_k * 100),
            "half_kelly_max_dd_pct": float(dd_hk * 100)}


def cv_oof_predict(df, feature_cols, target_col="outcome_up", n_splits=3):
    df = df.sort_values("window_start_unix").reset_index(drop=True)
    X = df[feature_cols].values
    y = df[target_col].values
    oof_pred = np.full(len(df), np.nan)
    tscv = TimeSeriesSplit(n_splits=n_splits)
    for fold, (train_idx, test_idx) in enumerate(tscv.split(X)):
        n_cal = max(50, int(0.2 * len(train_idx)))
        fit_idx = train_idx[:-n_cal]
        cal_idx = train_idx[-n_cal:]
        base = HistGradientBoostingClassifier(max_iter=200, max_depth=4, learning_rate=0.05,
                                              min_samples_leaf=20, random_state=42)
        base.fit(X[fit_idx], y[fit_idx])
        try:
            cal = CalibratedClassifierCV(base, method="isotonic", cv="prefit")
            cal.fit(X[cal_idx], y[cal_idx])
            p = cal.predict_proba(X[test_idx])[:, 1]
        except Exception:
            p = base.predict_proba(X[test_idx])[:, 1]
        oof_pred[test_idx] = p
        print(f"  fold {fold+1}/{n_splits}: train={len(fit_idx)} cal={len(cal_idx)} test={len(test_idx)}", flush=True)
    return oof_pred


def baseline_v3_quantile(df):
    return df["prob_stack"].fillna(0.5).values


def kronos_only(df):
    p5 = df["kr_pred_dir_5m"].fillna(0.5)
    p15 = df["kr_pred_dir_15m"].fillna(0.5)
    avg = (p5 + p15) / 2.0
    return 0.5 + (avg - 0.5) * 0.20


def run_hgb_ablation(df, feats, label, rows, has_mask=None, save_oof=False):
    """Helper: train HGB OOF, score and append rows for thresholds."""
    sub = df.copy()
    if has_mask is not None:
        sub = sub[has_mask].reset_index(drop=True)
    feats = safe_features(sub, feats)
    sub = sub.dropna(subset=feats + ["outcome_up"]).reset_index(drop=True)
    if len(sub) <= 200:
        print(f"\n[{label}] SKIP — only {len(sub)} rows")
        return None, None
    print(f"\n[{label}] HGB on {len(feats)} features (n={len(sub)})")
    oof = cv_oof_predict(sub, feats)
    valid = ~np.isnan(oof)
    auc = roc_auc_score(sub["outcome_up"][valid], oof[valid])
    brier = brier_score_loss(sub["outcome_up"][valid], oof[valid])
    print(f"  AUC={auc:.3f}  Brier={brier:.4f}")
    for thr in [0.50, 0.55, 0.60, 0.65]:
        res = trade_economics(oof[valid], sub["outcome_up"][valid].values, thr)
        res.update({"feature_set": label, "threshold": thr,
                    "auc": auc, "brier": brier, "n_universe": int(valid.sum())})
        rows.append(res)
        if res['n_bets'] > 0:
            print(f"  thr={thr}: n={res['n_bets']} hit={res['hit_rate']:.1%} flat_ROI={res['roi_per_bet']:+.2%} "
                  f"halfK_eq=${res['half_kelly_final_eq']:.0f} halfK_dd={res['half_kelly_max_dd_pct']:.1f}%")
        else:
            print(f"  thr={thr}: n=0")
    return sub, oof


def main():
    print("=== train_eval_no_kronos ===")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"loading: {LABELED}")
    df = pd.read_parquet(LABELED)
    print(f"  {len(df)} rows, {len(df.columns)} cols")
    print(f"  outcome balance: {df['outcome_up'].mean():.1%}")
    print(f"  Kronos coverage: {df['kr_pred_dir_5m'].notna().mean():.1%}")
    has_kr = df["kr_pred_dir_5m"].notna()
    has_v3 = df["prob_a"].notna() if "prob_a" in df.columns else pd.Series([False] * len(df))
    has_all = has_kr & has_v3
    print(f"  has_kr: {has_kr.sum()}, has_v3: {has_v3.sum()}, has_both: {has_all.sum()}")

    rows = []

    # A — V3 baseline (no training)
    if has_v3.sum() > 100:
        sub = df[has_v3].reset_index(drop=True)
        print(f"\n[A_V3_baseline] (n={len(sub)})")
        p_pred = baseline_v3_quantile(sub)
        for thr in [0.50, 0.55, 0.60, 0.65]:
            res = trade_economics(p_pred, sub["outcome_up"].values, thr)
            res.update({"feature_set": "A_V3_baseline", "threshold": thr,
                        "auc": np.nan, "brier": np.nan, "n_universe": len(sub)})
            rows.append(res)
            print(f"  thr={thr}: n_bets={res['n_bets']} hit={res['hit_rate']:.1%} ROI={res['roi_per_bet']:+.2%}"
                  if res['n_bets'] > 0 else f"  thr={thr}: n_bets=0")

    # B — Kronos handcrafted CONTROL (kept to confirm Kronos is dead weight)
    if has_kr.sum() > 100:
        sub = df[has_kr].reset_index(drop=True)
        print(f"\n[B_Kronos_only] (n={len(sub)})")
        p_pred = kronos_only(sub)
        for thr in [0.50, 0.52, 0.55]:
            res = trade_economics(p_pred, sub["outcome_up"].values, thr)
            res.update({"feature_set": "B_Kronos_only", "threshold": thr,
                        "auc": np.nan, "brier": np.nan, "n_universe": len(sub)})
            rows.append(res)
            print(f"  thr={thr}: n_bets={res['n_bets']} hit={res['hit_rate']:.1%} ROI={res['roi_per_bet']:+.2%}"
                  if res['n_bets'] > 0 else f"  thr={thr}: n_bets=0")

    # C — TA + time only
    run_hgb_ablation(df, TA_FEATURES + TIME_FEATURES, "C_TA_only", rows)

    # D — TA + DerivZScore + time (replaces v2's Kronos+TA — Kronos REMOVED)
    regime_dummies_d = [c for c in df.columns if c.startswith("dz_regime_")]
    run_hgb_ablation(df, TA_FEATURES + DERIV_REGIME_FEATURES + regime_dummies_d + TIME_FEATURES,
                     "D_TA+DerivZ_no_kronos", rows)

    # E — Full set MINUS Kronos: V3 + TA + DerivZScore regime + time
    sub_e, oof_e = None, None
    if has_v3.sum() > 200:
        sub = df[has_v3].dropna(subset=safe_features(df, TA_FEATURES) + ["outcome_up"]).reset_index(drop=True)
        if len(sub) > 200:
            regime_dummies = [c for c in sub.columns if c.startswith("dz_regime_")]
            feats = safe_features(sub, V3_FEATURES + TA_FEATURES + DERIV_REGIME_FEATURES + regime_dummies + TIME_FEATURES)
            print(f"\n[E_full_no_kronos] HGB on V3+TA+DerivZ+regime+time (NO Kronos) (n={len(sub)}, {len(feats)} features)")
            oof = cv_oof_predict(sub, feats)
            valid = ~np.isnan(oof)
            auc = roc_auc_score(sub["outcome_up"][valid], oof[valid])
            brier = brier_score_loss(sub["outcome_up"][valid], oof[valid])
            print(f"  AUC={auc:.3f}  Brier={brier:.4f}")

            # Permutation importance
            from sklearn.inspection import permutation_importance
            X = sub[feats].fillna(-99).values
            y = sub["outcome_up"].values
            model = HistGradientBoostingClassifier(max_iter=200, max_depth=4,
                                                   learning_rate=0.05, min_samples_leaf=20, random_state=42)
            model.fit(X, y)
            try:
                pi = permutation_importance(model, X, y, n_repeats=5, random_state=42, n_jobs=1)
                imp_df = pd.DataFrame({"feature": feats,
                                       "importance_mean": pi.importances_mean,
                                       "importance_std": pi.importances_std}).sort_values("importance_mean", ascending=False)
                imp_df.to_csv(OUT_DIR / f"{OUT_PREFIX}_feature_importance.csv", index=False)
                print(f"  feature importance saved -> {OUT_PREFIX}_feature_importance.csv")
                print(imp_df.head(10).to_string(index=False))
            except Exception as e:
                print(f"  permutation importance failed: {e}")

            for thr in [0.50, 0.55, 0.60, 0.65]:
                res = trade_economics(oof[valid], sub["outcome_up"][valid].values, thr)
                res.update({"feature_set": "E_full_no_kronos", "threshold": thr,
                            "auc": auc, "brier": brier, "n_universe": int(valid.sum())})
                rows.append(res)
                if res['n_bets'] > 0:
                    print(f"  thr={thr}: n={res['n_bets']} hit={res['hit_rate']:.1%} flat_ROI={res['roi_per_bet']:+.2%} "
                          f"halfK_eq=${res['half_kelly_final_eq']:.0f} halfK_dd={res['half_kelly_max_dd_pct']:.1f}%")
                else:
                    print(f"  thr={thr}: n=0")

            sub_e, oof_e = sub, oof
            sub_out = sub[["slug", "timeframe", "window_start_unix", "outcome_up"]].copy()
            sub_out["oof_p"] = oof
            sub_out.to_parquet(OUT_DIR / f"{OUT_PREFIX}_predictions_oof.parquet", index=False)

    # F — E + ATR/ADX gate
    oof_path = OUT_DIR / f"{OUT_PREFIX}_predictions_oof.parquet"
    if oof_path.exists():
        oof_df = pd.read_parquet(oof_path)
        oof_df = oof_df.merge(df[["slug", "ta_atr_quantile_30d", "ta_adx_above_25"]], on="slug", how="left")
        gate = (oof_df["ta_atr_quantile_30d"] >= 0.50) & (oof_df["ta_adx_above_25"] == 1)
        sub = oof_df[gate & oof_df["oof_p"].notna()].reset_index(drop=True)
        print(f"\n[F_full+gate_no_kronos] (n={len(sub)} of {len(oof_df)} = {len(sub)/len(oof_df):.1%})")
        for thr in [0.50, 0.55, 0.60, 0.65]:
            res = trade_economics(sub["oof_p"].values, sub["outcome_up"].values, thr)
            res.update({"feature_set": "F_full+gate_no_kronos", "threshold": thr,
                        "auc": np.nan, "brier": np.nan, "n_universe": len(sub)})
            rows.append(res)
            print(f"  thr={thr}: n_bets={res['n_bets']} hit={res['hit_rate']:.1%} ROI={res['roi_per_bet']:+.2%}"
                  if res['n_bets'] > 0 else f"  thr={thr}: n_bets=0")

    # G — Clean comparison: V3 + TA + time (no Kronos, no DerivZ)
    run_hgb_ablation(df, V3_FEATURES + TA_FEATURES + TIME_FEATURES,
                     "G_V3+TA_no_kronos_no_derivz", rows, has_mask=has_v3)

    # Persist
    out = pd.DataFrame(rows)
    out_csv = OUT_DIR / f"{OUT_PREFIX}_ablation_table.csv"
    out.to_csv(out_csv, index=False)
    print(f"\n[done] ablation table -> {out_csv}")
    print(f"\n{out.to_string(index=False)}")

    # Calibration on E
    if oof_path.exists():
        oof_df = pd.read_parquet(oof_path).dropna(subset=["oof_p"])
        cc = calibration_curve(oof_df["oof_p"].values, oof_df["outcome_up"].values, n_bins=10)
        cc.to_csv(OUT_DIR / f"{OUT_PREFIX}_calibration_curve.csv", index=False)
        print(f"\n[calibration curve - E_full_no_kronos]")
        print(cc.to_string(index=False))


if __name__ == "__main__":
    main()
