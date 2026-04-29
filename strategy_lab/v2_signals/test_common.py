import pandas as pd
import pytest
from strategy_lab.v2_signals.common import load_features, save_features, ASSETS

def test_load_features_returns_dataframe(tmp_path, monkeypatch):
    # Arrange: write a fake features CSV
    p = tmp_path / "data" / "polymarket"
    p.mkdir(parents=True)
    df = pd.DataFrame({"asset": ["btc"], "slug": ["s"], "outcome_up": [1]})
    df.to_csv(p / "btc_features_v3.csv", index=False)
    monkeypatch.setattr("strategy_lab.v2_signals.common.DATA_DIR", p.parent)

    out = load_features("btc")
    assert isinstance(out, pd.DataFrame)
    assert "asset" in out.columns

def test_assets_constant():
    assert ASSETS == ("btc", "eth", "sol")


def test_save_features_round_trip(tmp_path, monkeypatch):
    p = tmp_path / "data" / "polymarket"
    p.mkdir(parents=True)
    monkeypatch.setattr("strategy_lab.v2_signals.common.DATA_DIR", p.parent)
    df = pd.DataFrame({"asset": ["btc"], "slug": ["s"], "outcome_up": [1], "extra": [42]})
    save_features("btc", df)
    out = load_features("btc")
    pd.testing.assert_frame_equal(out, df)


def test_load_features_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("strategy_lab.v2_signals.common.DATA_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="Features file not found"):
        load_features("nonexistent")


def test_chronological_split_orders_by_time():
    from strategy_lab.v2_signals.common import chronological_split
    df = pd.DataFrame({
        "window_start_unix": [3, 1, 2, 4, 5],
        "outcome_up": [0, 1, 0, 1, 0],
    })
    train, holdout = chronological_split(df, train_frac=0.6)
    # 0.6 * 5 = 3 → train has 3 rows
    assert len(train) == 3
    assert len(holdout) == 2
    # Ordered ascending by window_start_unix
    assert list(train["window_start_unix"]) == [1, 2, 3]
    assert list(holdout["window_start_unix"]) == [4, 5]
