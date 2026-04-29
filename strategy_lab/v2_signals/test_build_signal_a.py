import numpy as np
import pandas as pd
from strategy_lab.v2_signals.build_signal_a import compute_votes_up, calibrate_prob_a

def test_compute_votes_up_all_positive():
    df = pd.DataFrame({"ret_5m":[0.01], "ret_15m":[0.02], "ret_1h":[0.005]})
    assert compute_votes_up(df).iloc[0] == 3

def test_compute_votes_up_mixed():
    df = pd.DataFrame({"ret_5m":[0.01], "ret_15m":[-0.02], "ret_1h":[0.005]})
    assert compute_votes_up(df).iloc[0] == 2

def test_compute_votes_up_handles_zero_as_negative():
    # zero is treated as not > 0 (i.e. a "down" vote)
    df = pd.DataFrame({"ret_5m":[0.0], "ret_15m":[0.0], "ret_1h":[0.0]})
    assert compute_votes_up(df).iloc[0] == 0

def test_calibrate_prob_a_uses_train_buckets():
    # Build a 100-row train where votes=3 -> 80% up, votes=0 -> 20% up
    n = 100
    train = pd.DataFrame({
        "asset": ["btc"]*n,
        "timeframe": ["5m"]*n,
        "votes_up": [3]*50 + [0]*50,
        "outcome_up": [1]*40 + [0]*10 + [1]*10 + [0]*40,
    })
    full = train.copy()
    out = calibrate_prob_a(full, train)
    assert out.loc[0, "prob_a"] == 0.8
    assert out.loc[60, "prob_a"] == 0.2

def test_calibrate_prob_a_falls_back_when_thin_bucket():
    train = pd.DataFrame({
        "asset": ["btc"]*5,  # only 5 train rows in bucket
        "timeframe": ["5m"]*5,
        "votes_up": [3]*5,
        "outcome_up": [1]*5,
    })
    full = train.copy()
    out = calibrate_prob_a(full, train, min_samples=20)
    # Bucket too thin -> fall back to 0.5
    assert out.loc[0, "prob_a"] == 0.5
