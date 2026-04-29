import pandas as pd
import numpy as np
from strategy_lab.v2_signals.build_signal_c import (
    flow_signal_per_market, book_imbalance_top5, combine_to_prob_c
)

def test_flow_signal_pure_yes_buy():
    # YES side has 100 buy, 0 sell. NO side empty. flow approx +1.
    df = pd.DataFrame({
        "slug": ["s","s"],
        "outcome": ["Up","Up"],
        "taker_side": ["buy","sell"],
        "total_size": [100, 0],
    })
    f = flow_signal_per_market(df)
    assert abs(f.loc["s"] - 1.0) < 1e-6

def test_flow_signal_balanced():
    df = pd.DataFrame({
        "slug": ["s"]*4,
        "outcome": ["Up","Up","Down","Down"],
        "taker_side": ["buy","sell","buy","sell"],
        "total_size": [50, 50, 50, 50],
    })
    assert abs(flow_signal_per_market(df).loc["s"]) < 1e-6

def test_book_imbalance_yes_thicker():
    # NO side has 1000 ask, YES has 100 -> imbalance = (1000-100)/1100 ~ +0.82 (positive = bullish UP)
    bd = pd.DataFrame({
        "slug":["s"]*2,
        "outcome":["Up","Down"],
        "ask_size_0":[100, 1000],
        "ask_size_1":[0,0],"ask_size_2":[0,0],"ask_size_3":[0,0],"ask_size_4":[0,0],
    })
    out = book_imbalance_top5(bd)
    assert abs(out.loc["s"] - (900/1100)) < 1e-3

def test_combine_squashes_to_band():
    raw_c = 0.6 * pd.Series([1.0, -1.0, 0.0]) + 0.4 * pd.Series([1.0, -1.0, 0.0])
    p = combine_to_prob_c(raw_c)
    assert abs(p.iloc[0] - 0.9) < 1e-6
    assert abs(p.iloc[1] - 0.1) < 1e-6
    assert abs(p.iloc[2] - 0.5) < 1e-6
