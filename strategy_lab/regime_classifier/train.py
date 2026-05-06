"""Walk-forward gradient-boosting classifier for daily up/down direction.

For each (asset):
  1. Load features parquet from feature_engineering.py
  2. Define folds: anchored walk-forward (train on first N days, test next K days,
     roll forward by K)
  3. Train HistGradientBoostingClassifier on each fold's train slice
  4. Apply isotonic-regression calibration on a held-out validation tail of train
  5. Predict probabilities on test slice
  6. Concatenate all OOS predictions → save predictions parquet
  7. Aggregate metrics: accuracy, log-loss, Brier, calibration, fold-by-fold

Output:
    strategy_lab/reports/regime_classifier/
      predictions_{sym}.parquet
      fold_metrics_{sym}.csv
      feature_importance_{sym}.csv
      SUMMARY.md (rebuilt at end)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "strategy_lab" / "reports" / "regime_classifier"
OUT.mkdir(parents=True, exist_ok=True)


# Columns NOT to use as features
DROP_COLS = {
    "open", "high", "low", "close", "volume", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote",  # raw market data, encoded elsewhere
    "close_next", "target_up_next_day", "next_day_ret",
    # MA absolute levels — use distance instead
    "ma_20", "ma_50", "ma_200",
    # OBV is non-stationary (cumulative); use slope/z instead
    "obv",
}


def feature_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in DROP_COLS and df[c].dtype.kind in "fic"]


def make_folds(n_rows: int, train_days: int = 730, test_days: int = 90,
               min_test_days: int = 60) -> list[tuple[int, int, int]]:
    """Yield (train_lo, train_hi, test_hi) row indices for anchored walk-forward.

    Anchored = train always starts at row 0; window grows. Each fold tests the
    next `test_days` after a `train_days`-or-larger train block.
    """
    folds = []
    train_hi = train_days
    while train_hi + min_test_days < n_rows:
        test_hi = min(train_hi + test_days, n_rows)
        if test_hi - train_hi >= min_test_days:
            folds.append((0, train_hi, test_hi))
        train_hi = test_hi
    return folds


def train_fold(
    X_train: pd.DataFrame, y_train: pd.Series,
    X_test: pd.DataFrame, y_test: pd.Series,
    seed: int = 42,
) -> tuple[np.ndarray, dict, HistGradientBoostingClassifier]:
    """Train calibrated HistGB and return (test_probs, metrics, fitted_model)."""
    base = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.05, max_depth=5,
        random_state=seed, class_weight="balanced",
        early_stopping=True, validation_fraction=0.15,
    )
    # Calibrated wrapper: 5-fold CV inside train slice, isotonic regression
    # for sklearn 1.5+: use 'estimator' param; fall back to 'base_estimator'
    try:
        cal = CalibratedClassifierCV(estimator=base, method="isotonic", cv=5)
    except TypeError:
        cal = CalibratedClassifierCV(base_estimator=base, method="isotonic", cv=5)
    cal.fit(X_train.fillna(0).to_numpy(), y_train.to_numpy())
    p_up = cal.predict_proba(X_test.fillna(0).to_numpy())[:, 1]
    pred = (p_up > 0.5).astype(int)

    metrics = {
        "n_train": len(X_train),
        "n_test": len(X_test),
        "test_acc": float(accuracy_score(y_test, pred)),
        "test_brier": float(brier_score_loss(y_test, p_up)),
        "test_logloss": float(log_loss(y_test, np.clip(p_up, 1e-6, 1 - 1e-6))),
        "base_rate_test": float(y_test.mean()),
        "predicted_up_rate": float(pred.mean()),
    }
    # Fit a fresh non-calibrated model for permutation importance (faster)
    model = HistGradientBoostingClassifier(
        max_iter=200, learning_rate=0.05, max_depth=5,
        random_state=seed, class_weight="balanced",
    )
    model.fit(X_train.fillna(0).to_numpy(), y_train.to_numpy())
    return p_up, metrics, model


def run_walk_forward(sym: str, train_days: int = 730, test_days: int = 90) -> dict:
    print(f"\n══════════ {sym} ══════════", flush=True)
    df = pd.read_parquet(OUT / f"features_{sym}.parquet")
    df = df.dropna(subset=["target_up_next_day", "ret_1d"]).copy()
    feats = feature_cols(df)
    print(f"  rows: {len(df):,}  features: {len(feats)}", flush=True)

    X = df[feats]
    y = df["target_up_next_day"].astype(int)

    folds = make_folds(len(df), train_days=train_days, test_days=test_days)
    print(f"  folds: {len(folds)}", flush=True)

    all_preds = []
    fold_metrics = []
    importances_acc: list[np.ndarray] = []

    for k, (lo, mid, hi) in enumerate(folds):
        Xtr, Xte = X.iloc[lo:mid], X.iloc[mid:hi]
        ytr, yte = y.iloc[lo:mid], y.iloc[mid:hi]
        if Xte.empty or ytr.nunique() < 2:
            continue
        p_up, m, model = train_fold(Xtr, ytr, Xte, yte)
        m["fold"] = k + 1
        m["test_start"] = str(df.index[mid].date())
        m["test_end"] = str(df.index[hi - 1].date())
        fold_metrics.append(m)
        for ts, p, real in zip(df.index[mid:hi], p_up, yte.values):
            all_preds.append({
                "timestamp": ts, "p_up": float(p), "y": int(real), "fold": k + 1,
            })
        # Permutation importance (top features only, for speed)
        try:
            pi = permutation_importance(
                model, Xte.fillna(0).to_numpy(), yte.to_numpy(),
                n_repeats=3, random_state=42, n_jobs=1, max_samples=min(len(Xte), 200),
            )
            importances_acc.append(pi.importances_mean)
        except Exception as e:
            print(f"    fold {k+1}: permutation importance failed ({e})", flush=True)

        print(f"  fold {k+1}: test {m['test_start']}→{m['test_end']}  "
              f"acc={m['test_acc']*100:.1f}%  brier={m['test_brier']:.4f}  "
              f"loss={m['test_logloss']:.4f}", flush=True)

    pred_df = pd.DataFrame(all_preds).set_index("timestamp")
    pred_df.to_parquet(OUT / f"predictions_{sym}.parquet")

    fm = pd.DataFrame(fold_metrics)
    fm.to_csv(OUT / f"fold_metrics_{sym}.csv", index=False)

    # Aggregate importance
    if importances_acc:
        avg_imp = np.mean(importances_acc, axis=0)
        imp_df = pd.DataFrame({"feature": feats, "permutation_importance": avg_imp})
        imp_df = imp_df.sort_values("permutation_importance", ascending=False)
        imp_df.to_csv(OUT / f"feature_importance_{sym}.csv", index=False)
    else:
        imp_df = pd.DataFrame()

    # Aggregate metrics
    overall = {
        "symbol": sym,
        "n_oos": len(pred_df),
        "n_folds": len(fold_metrics),
        "oos_acc": float(((pred_df["p_up"] > 0.5).astype(int) == pred_df["y"]).mean()),
        "oos_base_rate": float(pred_df["y"].mean()),
        "oos_brier": float(brier_score_loss(pred_df["y"], pred_df["p_up"])),
        "oos_logloss": float(log_loss(pred_df["y"], np.clip(pred_df["p_up"], 1e-6, 1 - 1e-6))),
        "min_fold_acc": float(fm["test_acc"].min()) if len(fm) else 0.0,
        "max_fold_acc": float(fm["test_acc"].max()) if len(fm) else 0.0,
    }
    print(f"  OVERALL: n_oos={overall['n_oos']}  acc={overall['oos_acc']*100:.2f}%  "
          f"base={overall['oos_base_rate']*100:.2f}%  brier={overall['oos_brier']:.4f}",
          flush=True)
    return overall


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    ap.add_argument("--train-days", type=int, default=730)
    ap.add_argument("--test-days", type=int, default=90)
    args = ap.parse_args()

    rows = []
    for sym in args.symbols:
        rows.append(run_walk_forward(sym, train_days=args.train_days, test_days=args.test_days))

    summary = pd.DataFrame(rows)
    summary.to_csv(OUT / "walk_forward_summary.csv", index=False)
    print("\n" + "═" * 80)
    print("WALK-FORWARD SUMMARY")
    print("═" * 80)
    print(summary.to_string(index=False))
    print(f"\nSaved: {OUT/'walk_forward_summary.csv'}")


if __name__ == "__main__":
    main()
