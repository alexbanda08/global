"""Stack meta-model - logistic regression + isotonic calibration on (prob_a, prob_b, prob_c).

Fit on chronological train slice (80% by window_start_unix). Apply to full df.
Inspect base estimator coefficients for interpretability.
"""
from __future__ import annotations
import argparse, os
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from strategy_lab.v2_signals.common import load_features, save_features, ASSETS, chronological_split


def fit_stack(X: pd.DataFrame, y):
    base = LogisticRegression(C=1.0, fit_intercept=True, max_iter=1000)
    clf = CalibratedClassifierCV(base, cv=3, method="isotonic")
    clf.fit(X.values, y.values if hasattr(y, "values") else y)
    return clf


def apply_stack(clf, X: pd.DataFrame) -> np.ndarray:
    return clf.predict_proba(X.values)[:, 1]


def build_one_asset(asset: str) -> None:
    df = load_features(asset)
    cols = ["prob_a", "prob_b", "prob_c"]
    if not all(c in df.columns for c in cols):
        raise RuntimeError(f"{asset} missing one of {cols} - run build_signal_{{a,b,c}} first")
    train, _ = chronological_split(df)
    clf = fit_stack(train[cols], train["outcome_up"])
    df["prob_stack"] = apply_stack(clf, df[cols])
    save_features(asset, df)
    # Inspect base estimator coefficients (averaged across CV folds)
    base = clf.calibrated_classifiers_[0].estimator
    coefs = base.coef_[0]
    print(f"{asset}: stack written, mean={df['prob_stack'].mean():.3f}, "
          f"coefs(a,b,c)={coefs.round(3).tolist()}, intercept={base.intercept_[0]:.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default=os.getenv("ASSET", "all"))
    args = ap.parse_args()
    assets = ASSETS if args.asset == "all" else (args.asset,)
    for a in assets:
        build_one_asset(a)


if __name__ == "__main__":
    main()
