"""
Per-wallet engagement classifier.

For each reference wallet:
  1. Restrict slugs to the wallet's active window [ws_min, ws_max]
  2. Label engaged=1 if wallet has fills in slug, 0 else
  3. Train logistic regression with 5-fold CV (stratified)
  4. (Optional) Also train GradientBoostingClassifier if sklearn available
  5. Report AUC, accuracy, top feature weights, precision @ threshold k
  6. Save per-wallet selected-slug lists for validation backtest

Outputs:
  strategy_lab/backtests/_wallet_classifier_metrics.csv   (one row per wallet/model)
  strategy_lab/backtests/_wallet_classifier_weights.csv   (per wallet/feature/model)
  strategy_lab/backtests/_wallet_selected_slugs.csv       (slug, wallet, prob, label)

Usage:
    py -3 -X utf8 strategy_lab/backtests/train_wallet_classifier.py
"""
from __future__ import annotations
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "strategy_lab" / "backtests"

# Wallets of interest (from _wallet_profile_per_slug_agg.csv)
WALLETS = [
    "0x04b6d7e9",  # MAS-pattern
    "0xeebde7a0",  # HYBRID (Bonereaper)
    "0x89b5cdaa",  # directional MAS (ohanism)
    "0xcfb103c3",  # PAT (xuanxuan008)
    "0xce25e214",  # mixed taker
]

# Features used in classifier (numeric only; tf encoded separately)
NUM_FEATURES = [
    "sum_bids", "sum_asks", "spread_up", "spread_dn", "mid_diff",
    "depth_up", "depth_dn", "depth_tot", "depth_imb",
    "ret_60s", "ret_120s", "abs_ret_60s", "abs_ret_120s",
    "vol_5m", "vol_10m",
    "hour_utc", "weekday", "min_in_hour",
]

CAT_FEATURES = ["tf"]  # one-hot encoded


def load_data():
    feats = pd.read_csv(OUT_DIR / "_per_slug_features_btc.csv")
    prof = pd.read_csv(OUT_DIR / "_wallet_profile_per_slug_agg.csv")
    prof = prof[prof["asset_sym"] == "BTC"].copy()
    return feats, prof


def prep_features(df: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    """Return (X, feature_names) using NUM_FEATURES + one-hot of CAT_FEATURES."""
    df = df.copy()
    # Fill NaN with median (numeric)
    for f in NUM_FEATURES:
        if f in df.columns:
            med = df[f].median()
            df[f] = df[f].fillna(med)

    # One-hot tf
    onehot_cols = []
    for cf in CAT_FEATURES:
        if cf in df.columns:
            dummies = pd.get_dummies(df[cf], prefix=cf)
            df = pd.concat([df, dummies], axis=1)
            onehot_cols.extend(dummies.columns.tolist())

    fnames = NUM_FEATURES + onehot_cols
    fnames = [f for f in fnames if f in df.columns]
    X = df[fnames].astype("float64").values
    return X, fnames


def train_one_wallet(wallet: str, feats: pd.DataFrame, prof: pd.DataFrame) -> dict:
    """Train classifier for one wallet. Return metrics dict."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score, average_precision_score, accuracy_score
    from sklearn.model_selection import StratifiedKFold
    try:
        from sklearn.ensemble import GradientBoostingClassifier
        HAS_GBT = True
    except Exception:
        HAS_GBT = False

    wsub = prof[prof["wallet"] == wallet].copy()
    if wsub.empty:
        return {"wallet": wallet, "skip_reason": "no_profile_rows"}

    # Wallet active window in slot_start_s
    ws_min, ws_max = int(wsub["slot_start_s"].min()), int(wsub["slot_start_s"].max())
    in_window = feats[(feats["slot_start_s"] >= ws_min) &
                      (feats["slot_start_s"] <= ws_max)].copy()
    engaged_slugs = set(wsub["slug"].unique())
    in_window["engaged"] = in_window["slug"].isin(engaged_slugs).astype(int)
    y = in_window["engaged"].values
    n_eng = int(y.sum())
    n_total = len(y)
    print(f"\n{wallet}: window=[{ws_min},{ws_max}], engaged {n_eng}/{n_total} "
          f"({n_eng/n_total*100:.1f}%)")

    if n_eng < 10 or n_total - n_eng < 10:
        return {"wallet": wallet, "skip_reason": "too_few_examples",
                "n_engaged": n_eng, "n_unengaged": n_total - n_eng}

    X, fnames = prep_features(in_window)
    # Standardize for logistic regression
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)

    # 5-fold stratified CV
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    lr_aucs, lr_apr, lr_acc = [], [], []
    gb_aucs, gb_apr, gb_acc = [], [], []
    p_oof_lr = np.zeros(len(y))
    p_oof_gb = np.zeros(len(y))

    for tr_idx, te_idx in skf.split(Xs, y):
        # Logistic regression
        clf_lr = LogisticRegression(max_iter=1000, C=1.0,
                                    class_weight="balanced",
                                    solver="lbfgs")
        clf_lr.fit(Xs[tr_idx], y[tr_idx])
        p = clf_lr.predict_proba(Xs[te_idx])[:, 1]
        p_oof_lr[te_idx] = p
        lr_aucs.append(roc_auc_score(y[te_idx], p))
        lr_apr.append(average_precision_score(y[te_idx], p))
        lr_acc.append(accuracy_score(y[te_idx], (p >= 0.5).astype(int)))

        # Gradient boosting
        if HAS_GBT:
            clf_gb = GradientBoostingClassifier(n_estimators=120, max_depth=3,
                                                learning_rate=0.05,
                                                random_state=42)
            clf_gb.fit(X[tr_idx], y[tr_idx])
            p = clf_gb.predict_proba(X[te_idx])[:, 1]
            p_oof_gb[te_idx] = p
            gb_aucs.append(roc_auc_score(y[te_idx], p))
            gb_apr.append(average_precision_score(y[te_idx], p))
            gb_acc.append(accuracy_score(y[te_idx], (p >= 0.5).astype(int)))

    # Fit final LR on full data for feature weights
    final_lr = LogisticRegression(max_iter=1000, C=1.0,
                                  class_weight="balanced", solver="lbfgs")
    final_lr.fit(Xs, y)
    coefs = final_lr.coef_[0]
    weights = sorted(zip(fnames, coefs), key=lambda kv: -abs(kv[1]))

    # Save OOF predictions for validation
    in_window["prob_lr"] = p_oof_lr
    if HAS_GBT:
        in_window["prob_gb"] = p_oof_gb

    # Top-k precision/lift analysis
    base_rate = n_eng / n_total
    metrics = {
        "wallet": wallet,
        "n_engaged": n_eng,
        "n_unengaged": int(n_total - n_eng),
        "base_rate": round(base_rate, 4),
        "lr_auc_mean": round(np.mean(lr_aucs), 4),
        "lr_auc_std": round(np.std(lr_aucs), 4),
        "lr_apr_mean": round(np.mean(lr_apr), 4),
        "lr_acc_mean": round(np.mean(lr_acc), 4),
    }
    if HAS_GBT:
        metrics.update({
            "gb_auc_mean": round(np.mean(gb_aucs), 4),
            "gb_auc_std": round(np.std(gb_aucs), 4),
            "gb_apr_mean": round(np.mean(gb_apr), 4),
            "gb_acc_mean": round(np.mean(gb_acc), 4),
        })

    # Precision @ top-k for primary (gb if available else lr)
    p_oof = p_oof_gb if HAS_GBT else p_oof_lr
    order = np.argsort(-p_oof)
    for k_frac in [0.10, 0.20, 0.30, 0.50]:
        k = max(1, int(k_frac * n_total))
        top_k = order[:k]
        prec_k = y[top_k].mean()
        recall_k = y[top_k].sum() / n_eng
        lift_k = prec_k / base_rate if base_rate > 0 else float("nan")
        metrics[f"prec@{int(k_frac*100)}pct"] = round(float(prec_k), 4)
        metrics[f"recall@{int(k_frac*100)}pct"] = round(float(recall_k), 4)
        metrics[f"lift@{int(k_frac*100)}pct"] = round(float(lift_k), 4)

    weights_rows = [
        {"wallet": wallet, "feature": fname, "coef": float(c),
         "abs_coef": float(abs(c))}
        for fname, c in weights
    ]

    # Output selected-slug table for validation backtest
    in_window_out = in_window[["slug", "engaged", "prob_lr"]].copy()
    if HAS_GBT:
        in_window_out["prob_gb"] = p_oof_gb
    in_window_out["wallet"] = wallet
    in_window_out["rank"] = (-in_window_out.get("prob_gb", in_window_out["prob_lr"])).argsort().argsort()

    return {
        "metrics": metrics,
        "weights_rows": weights_rows,
        "slugs_df": in_window_out,
        "feature_names": fnames,
    }


def main():
    feats, prof = load_data()
    print(f"Loaded {len(feats)} feature rows, {len(prof)} wallet-slug rows")

    all_metrics = []
    all_weights = []
    all_slugs = []

    for w in WALLETS:
        res = train_one_wallet(w, feats, prof)
        if "skip_reason" in res:
            print(f"  SKIP {w}: {res['skip_reason']}")
            continue
        m = res["metrics"]
        all_metrics.append(m)
        all_weights.extend(res["weights_rows"])
        all_slugs.append(res["slugs_df"])
        print(f"  LR AUC={m['lr_auc_mean']:.3f}±{m['lr_auc_std']:.3f}, "
              f"GB AUC={m.get('gb_auc_mean', float('nan')):.3f}±"
              f"{m.get('gb_auc_std', float('nan')):.3f}, "
              f"lift@20%={m['lift@20pct']:.2f}x")

    metrics_df = pd.DataFrame(all_metrics)
    weights_df = pd.DataFrame(all_weights)
    slugs_df = pd.concat(all_slugs, ignore_index=True) if all_slugs else pd.DataFrame()

    metrics_df.to_csv(OUT_DIR / "_wallet_classifier_metrics.csv", index=False)
    weights_df.to_csv(OUT_DIR / "_wallet_classifier_weights.csv", index=False)
    slugs_df.to_csv(OUT_DIR / "_wallet_selected_slugs.csv", index=False)

    print(f"\n{'='*80}")
    print("CLASSIFIER METRICS")
    print(f"{'='*80}")
    print(metrics_df.to_string(index=False))

    print(f"\n{'='*80}")
    print("TOP-8 WEIGHTS PER WALLET (logistic regression, standardized)")
    print(f"{'='*80}")
    for w in metrics_df["wallet"]:
        sub = weights_df[weights_df["wallet"] == w].head(8)
        print(f"\n{w}:")
        print(sub[["feature", "coef"]].to_string(index=False))

    print(f"\nOutputs:")
    print(f"  {OUT_DIR / '_wallet_classifier_metrics.csv'}")
    print(f"  {OUT_DIR / '_wallet_classifier_weights.csv'}")
    print(f"  {OUT_DIR / '_wallet_selected_slugs.csv'}")


if __name__ == "__main__":
    main()
