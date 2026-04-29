import numpy as np
import pandas as pd
from strategy_lab.v2_signals.build_stack import fit_stack, apply_stack


def test_fit_stack_returns_calibrated_classifier():
    n = 1000
    rng = np.random.RandomState(0)
    X = pd.DataFrame({
        "prob_a": rng.uniform(0, 1, n),
        "prob_b": rng.uniform(0, 1, n),
        "prob_c": rng.uniform(0, 1, n),
    })
    y = (X.prob_a + 0.1 * rng.randn(n) > 0.5).astype(int)
    clf = fit_stack(X, y)
    assert hasattr(clf, "predict_proba")


def test_apply_stack_outputs_in_unit_interval():
    n = 500
    rng = np.random.RandomState(1)
    X = pd.DataFrame({c: rng.uniform(0, 1, n) for c in ["prob_a", "prob_b", "prob_c"]})
    y = rng.randint(0, 2, n)
    clf = fit_stack(X, y)
    p = apply_stack(clf, X)
    assert ((p >= 0) & (p <= 1)).all()
