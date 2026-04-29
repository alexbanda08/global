"""
V21 — Leverage + portfolio-split sweep to find the Kelly-optimal spec.

Two-dimensional grid:
  1. XSM leverage ∈ {0.5, 1.0, 1.5, 2.0, 2.5, 3.0}
  2. Portfolio split w_xsm ∈ {0.0, 0.2, 0.3, 0.5, 0.7, 0.8, 1.0}

For each (lev, w) combo we compute:
  - Full 2018-26 CAGR, Sharpe, MaxDD, Calmar, final $
  - OOS 2022-26 metrics
  - Kelly growth rate estimate (log-return mean × 252 weeks/yr)

Outputs:
  strategy_lab/results/v21_leverage_sweep.csv
"""
from __future__ import annotations
from pathlib import Path
import itertools
import numpy as np
import pandas as pd

from strategy_lab.v15_xsm_variants import xsm_generic, load_all_4h

OUT = Path(__file__).resolve().parent / "results"
IS_END = pd.Timestamp("2022-01-01", tz="UTC")
INIT = 10_000.0
BPY = 365.25 * 24 / 4


def metrics(eq: pd.Series) -> dict:
    if len(eq) < 50 or eq.iloc[-1] <= 0:
        return {"cagr":0,"sharpe":0,"dd":0,"calmar":0,"final":0,"kelly":0}
    rets = eq.pct_change(fill_method=None).fillna(0)
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1]/eq.iloc[0]) ** (1/max(yrs,0.01)) - 1
    sh = (rets.mean()*BPY)/(rets.std()*np.sqrt(BPY) + 1e-12)
    dd = float((eq/eq.cummax()-1).min())
    # Kelly growth rate ≈ log-return mean annualised
    log_rets = np.log1p(rets)
    kelly_g = float(log_rets.mean() * BPY)
    return {"cagr":round(float(cagr),4),"sharpe":round(float(sh),3),
            "dd":round(dd,4),
            "calmar":round(cagr/abs(dd) if dd < 0 else 0, 3),
            "final":round(float(eq.iloc[-1]),0),
            "kelly":round(kelly_g,3)}


def main():
    data = load_all_4h()

    # 1. Build base XSM equity (1x leverage) for various k/lb configs
    # Focus on our 3 profiles:
    profiles = {
        "CONSERVATIVE (k=2 lb=28d)": dict(lookback_days=28, top_k=2),
        "BALANCED     (k=4 lb=14d)": dict(lookback_days=14, top_k=4),
        "AGGRESSIVE   (k=3 lb=14d rb=3d)": dict(lookback_days=14, top_k=3, rebal_days=3),
    }

    # 2. Load trend baseline equity
    trend_eq = pd.read_csv(OUT/"portfolio/portfolio_equity.csv",
                           index_col=0, parse_dates=[0])
    trend_eq.index = trend_eq.index.tz_convert("UTC") if trend_eq.index.tz else trend_eq.index.tz_localize("UTC")
    trend_eq = trend_eq.iloc[:, 0]

    rows = []
    # XSM-only leverage sweep
    for prof_name, base_kw in profiles.items():
        for lev in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
            eq, legs = xsm_generic(
                data, mode="mom", rebal_days=base_kw.get("rebal_days", 7),
                lookback_days=base_kw["lookback_days"],
                top_k=base_kw["top_k"],
                btc_filter=True, leverage=lev)
            m = metrics(eq)
            oos = eq[eq.index >= IS_END]
            m_oos = metrics(oos) if len(oos) > 20 else {}
            row = {"profile": prof_name, "xsm_lev": lev, "w_xsm": 1.0,
                   **{f"full_{k}": v for k, v in m.items()},
                   **{f"oos_{k}":  v for k, v in m_oos.items()}}
            rows.append(row)
            print(f"  {prof_name:<38}  lev={lev:.1f}x  "
                  f"CAGR {m['cagr']*100:+7.1f}%  Sh {m['sharpe']:+.2f}  "
                  f"DD {m['dd']*100:+6.1f}%  Calmar {m['calmar']:5.2f}  "
                  f"Kelly-g {m['kelly']:.2f}  Final ${m['final']:,.0f}",
                  flush=True)

    # XSM × trend split sweep — use BALANCED profile only for blends
    bal_eq_1x, _ = xsm_generic(data, mode="mom", lookback_days=14, top_k=4,
                               rebal_days=7, btc_filter=True, leverage=1.0)

    # Align both to a common index
    idx = bal_eq_1x.index.union(trend_eq.index)
    x_a = bal_eq_1x.reindex(idx).ffill().fillna(INIT)
    t_a = trend_eq.reindex(idx).ffill().fillna(INIT)
    x_norm = x_a / x_a.iloc[0]
    t_norm = t_a / t_a.iloc[0]

    for w_xsm in [0.0, 0.2, 0.3, 0.5, 0.7, 0.8, 1.0]:
        combined = INIT * (w_xsm * x_norm + (1 - w_xsm) * t_norm)
        m = metrics(combined)
        oos = combined[combined.index >= IS_END]
        m_oos = metrics(oos)
        row = {"profile": "BLEND balanced 1x XSM + Trend",
               "xsm_lev": 1.0, "w_xsm": w_xsm,
               **{f"full_{k}": v for k, v in m.items()},
               **{f"oos_{k}":  v for k, v in m_oos.items()}}
        rows.append(row)
        print(f"  BLEND w_xsm={w_xsm:.1f}  CAGR {m['cagr']*100:+6.1f}%  "
              f"Sh {m['sharpe']:+.2f}  DD {m['dd']*100:+6.1f}%  "
              f"Calmar {m['calmar']:5.2f}  Kelly-g {m['kelly']:.2f}",
              flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(OUT/"v21_leverage_sweep.csv", index=False)

    print("\n=== TOP 10 BY FULL-PERIOD CALMAR ===")
    print(df.sort_values("full_calmar", ascending=False).head(10)[
        ["profile","xsm_lev","w_xsm","full_cagr","full_sharpe","full_dd","full_calmar","full_kelly","full_final"]
    ].to_string(index=False))
    print("\n=== TOP 10 BY OOS KELLY-G (geometric growth rate OOS) ===")
    print(df.sort_values("oos_kelly", ascending=False).head(10)[
        ["profile","xsm_lev","w_xsm","oos_cagr","oos_sharpe","oos_dd","oos_calmar","oos_kelly"]
    ].to_string(index=False))


if __name__ == "__main__":
    main()
