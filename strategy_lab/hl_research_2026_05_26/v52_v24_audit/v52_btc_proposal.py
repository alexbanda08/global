"""
V52-BTC sleeve proposal — STF_BTC_V45 variant.

Findings from B1 candidate test (Sharpe / CAGR / MDD on HL BTC 4h 2024-01-12 → 2026-04-25):

| Candidate                  | Sh    | CAGR    | MDD    | Calmar | 2024 Sh | 2025 Sh | 2026 Sh |
|----------------------------|-------|---------|--------|--------|---------|---------|---------|
| CCI_BTC_baseline           | -0.31 | -8.6%   | -49.7% | -0.17  | 0.55    | -0.86   | -1.49   |
| CCI_BTC_V41                | -1.09 | -22.7%  | -53.6% | -0.42  | -1.34   | -0.76   | -2.47   |
| STF_BTC_baseline           | 0.23  | +2.7%   | -30.1% | 0.09   | -0.99   | 0.91    | 0.88    |
| STF_BTC_V45 (volume gate)  | 1.00  | +24.4%  | -28.4% | 0.86   | -0.59   | 0.87    | +3.61   |
| DONCH_BTC_20               | -0.52 | -24.5%  | -65.1% | -0.38  | -0.15   | -1.08   | 0.24    |
| DONCH_BTC_20_EMA200_V41    | 0.71  | +23.4%  | -30.6% | 0.77   | 1.04    | 0.04    | +1.92   |
| DONCH_BTC_20_LONGONLY      | 0.07  | -1.6%   | -39.2% | -0.04  | -0.05   | 0.27    | -0.19   |

WINNER: STF_BTC_V45 — best Sharpe (1.00), strong 2026 performance (+3.6 Sh), Calmar 0.86, MDD -28.4%.
RUNNER-UP: DONCH_BTC_20_EMA200_V41 — Sharpe 0.71, MDD -30.6%, 2026 Sh +1.92, regime-adaptive.

INTEGRATION INTO V52 (proposed):
- Add STF_BTC_V45 as the 5th V41-style sleeve.
- Adjust weighting: 5 V41 sleeves @ 12%/each (=60% total) + 4 diversifiers @ 10%/each (=40%).
- OR keep current 60/40 split and weight new BTC sleeve at 8% (carved out of V41 block).
- Recommended: try 12% to STF_BTC_V45 (8% from V41 block, 4% from cash-drag), since STF_BTC_V45 MDD is -28% (higher than the V41 sleeves' ~21% avg), so keep weight modest.

USAGE:
    from strategy_lab.util.hl_data import load_hl, funding_per_4h_bar
    from strategy_lab.eval.perps_simulator_funding import simulate_with_funding
    from strategy_lab.eval.perps_simulator_adaptive_exit import REGIME_EXITS_4H
    from strategy_lab.regime.hmm_adaptive import fit_regime_model
    from strategy_lab.run_v30_creative import sig_supertrend_flip

    df = load_hl("BTC", "4h", start="2024-01-12", end="2026-04-25")
    fund = funding_per_4h_bar("BTC", df.index)
    le, se = sig_supertrend_flip(df, st_n=10, st_mult=3.0, ema_reg=200)

    # V45 volume gate
    vmean = df["volume"].rolling(20, min_periods=10).mean()
    active = df["volume"] > 1.1 * vmean
    le = le & active
    se = se & active

    _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
    _, eq = simulate_with_funding(
        df, le, se, fund,
        regime_labels=rdf["label"],
        regime_exits=REGIME_EXITS_4H,
    )

    # eq is the STF_BTC_V45 equity curve. Use as 5th V41 sleeve in V52 blend.
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from strategy_lab.util.hl_data import load_hl, funding_per_4h_bar
from strategy_lab.eval.perps_simulator_funding import simulate_with_funding
from strategy_lab.eval.perps_simulator_adaptive_exit import REGIME_EXITS_4H
from strategy_lab.regime.hmm_adaptive import fit_regime_model

import importlib.util
def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

_repo = Path(__file__).resolve().parents[3]
_v30 = _load(str(_repo / "strategy_lab/run_v30_creative.py"), "v30c")


def build_stf_btc_v45(start: str = "2024-01-12", end: str = "2026-04-25") -> pd.Series:
    """Build the STF_BTC_V45 sleeve equity curve.

    Returns
    -------
    pd.Series
        Equity curve indexed at 4h.
    """
    df = load_hl("BTC", "4h", start=start, end=end)
    fund = funding_per_4h_bar("BTC", df.index)
    le, se = _v30.sig_supertrend_flip(df, st_n=10, st_mult=3.0, ema_reg=200)
    # V45: volume gate
    vmean = df["volume"].rolling(20, min_periods=10).mean()
    active = df["volume"] > 1.1 * vmean
    le = le & active
    se = se & active
    _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
    _, eq = simulate_with_funding(
        df, le, se, fund,
        regime_labels=rdf["label"],
        regime_exits=REGIME_EXITS_4H,
    )
    return eq


def build_donch_btc_v41(start: str = "2024-01-12", end: str = "2026-04-25") -> pd.Series:
    """Build alternative Donchian-V41 BTC sleeve (runner-up).

    Returns
    -------
    pd.Series
        Equity curve indexed at 4h.
    """
    df = load_hl("BTC", "4h", start=start, end=end)
    fund = funding_per_4h_bar("BTC", df.index)
    hi_n = df["high"].rolling(20).max().shift(1)
    lo_n = df["low"].rolling(20).min().shift(1)
    ema_r = df["close"].ewm(span=200, adjust=False).mean()
    le = (df["close"] > hi_n) & (df["close"] > ema_r)
    se = (df["close"] < lo_n) & (df["close"] < ema_r)
    le = le.fillna(False); se = se.fillna(False)
    _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
    _, eq = simulate_with_funding(
        df, le, se, fund,
        regime_labels=rdf["label"],
        regime_exits=REGIME_EXITS_4H,
    )
    return eq


if __name__ == "__main__":
    eq_stf = build_stf_btc_v45()
    print(f"STF_BTC_V45 equity: end ${float(eq_stf.iloc[-1]):,.0f}  (start $10,000)")
    rets = eq_stf.pct_change().dropna()
    sd = float(rets.std())
    sh = (float(rets.mean()) / sd) * np.sqrt(365.25 * 6) if sd > 0 else 0.0
    print(f"Sharpe: {sh:.3f}")

    eq_dch = build_donch_btc_v41()
    print(f"DONCH_BTC_V41 equity: end ${float(eq_dch.iloc[-1]):,.0f}  (start $10,000)")
    rets = eq_dch.pct_change().dropna()
    sd = float(rets.std())
    sh = (float(rets.mean()) / sd) * np.sqrt(365.25 * 6) if sd > 0 else 0.0
    print(f"Sharpe: {sh:.3f}")
