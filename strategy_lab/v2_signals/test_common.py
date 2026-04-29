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
