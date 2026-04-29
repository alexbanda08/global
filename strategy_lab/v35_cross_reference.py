"""
V35 — Cross-reference the user's DEPLOYMENT_BLUEPRINT 5-sleeve portfolio
against my XSM / V24 multi-filter family.

Goal: find whether combining the two libraries is strictly better than
either alone on (Sharpe, Calmar, max-DD, profit).

Sources:
  * User side: `run_v34_portfolio.py` — 5 single-coin sleeves, 3× leverage,
    equal-weighted 20% each.  Rebuilds each equity curve from saved pickles.
  * My side:   saved V24 multi-filter 1× XSM equity + V15 balanced + V27 L/S.

Outputs:
  strategy_lab/results/v35_cross/sleeve_equities.csv
  strategy_lab/results/v35_cross/combined_portfolios.csv
  strategy_lab/results/v35_cross/correlation_matrix.csv
"""
from __future__ import annotations
import sys, pickle
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v34_portfolio import (
    build_eq_v30, build_eq_v34, build_eq_core, SLEEVES
)

OUT = Path(__file__).resolve().parent / "results" / "v35_cross"
OUT.mkdir(parents=True, exist_ok=True)
BPY = 365.25 * 24 / 4   # 4h bars per year


def metrics(eq: pd.Series, label: str = "") -> dict:
    if len(eq) < 50 or eq.iloc[-1] <= 0:
        return {"label": label, "cagr": 0, "sharpe": 0, "dd": 0, "calmar": 0, "final": 0}
    rets = eq.pct_change(fill_method=None).fillna(0)
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 0.01)) - 1
    sh = (rets.mean() * BPY) / (rets.std() * np.sqrt(BPY) + 1e-12)
    dd = float((eq / eq.cummax() - 1).min())
    return {"label": label, "cagr": float(cagr), "sharpe": float(sh),
            "dd": dd, "calmar": cagr / abs(dd) if dd < 0 else 0,
            "final": float(eq.iloc[-1])}


def load_user_live_five() -> dict[str, pd.Series]:
    """Rebuild their 5 live-portfolio sleeve equities."""
    targets = {
        "SOL_BBBreak_4h",
        "DOGE_Donchian_4h",
        "ETH_CCI_4h",
        "AVAX_BBBreak_4h",
        "TON_BBBreak_4h",
    }
    out = {}
    for row in SLEEVES:
        label, sym, family, tf, params, exits, risk, lev, fn_name = row
        if label not in targets: continue
        try:
            if fn_name == "v30_from_pickle":
                eq = build_eq_v30(label, sym, family, tf)
            elif fn_name == "v34_from_pickle":
                eq = build_eq_v34(label, sym, family, tf)
            else:
                eq = build_eq_core(label, sym, family, tf, params, exits, risk, lev, fn_name)
            if eq is not None:
                out[label] = eq
                print(f"  loaded {label}: {len(eq):,} bars  {eq.index[0].date()} -> {eq.index[-1].date()}  final {eq.iloc[-1]:,.0f}")
            else:
                print(f"  FAILED to load {label}")
        except Exception as e:
            print(f"  ERROR on {label}: {type(e).__name__}: {e}")
    return out


def combine_sleeves(sleeves: dict[str, pd.Series], weights: dict[str, float],
                    init: float = 10_000.0) -> pd.Series:
    idx = None
    for s, eq in sleeves.items():
        idx = eq.index if idx is None else idx.union(eq.index)
    idx = idx.sort_values()
    total = pd.Series(0.0, index=idx)
    for s, eq in sleeves.items():
        w = weights.get(s, 0.0)
        if w <= 0: continue
        norm = eq.reindex(idx).ffill().bfill() / eq.iloc[0]
        total = total + w * norm * init
    total.name = "equity"
    return total


def load_my_xsm() -> dict[str, pd.Series]:
    """Load my pre-computed XSM equity curves."""
    base = Path(__file__).resolve().parent / "results"
    files = {
        "MY_V15_BALANCED":  base / "v15_balanced_k4_lb14_rb7_equity.csv",
        "MY_V24_MF_1x":     None,  # needs re-generation; will compute below
        "MY_V27_LS_0.5x":   None,
    }
    out = {}
    for lbl, p in files.items():
        if p is not None and p.exists():
            df = pd.read_csv(p, index_col=0, parse_dates=[0])
            try:
                df.index = df.index.tz_convert("UTC")
            except Exception:
                df.index = df.index.tz_localize("UTC")
            out[lbl] = df.iloc[:, 0]
    # Generate V24 / V27 from v23_low_dd_xsm and v29_long_short_deep
    try:
        from strategy_lab.v23_low_dd_xsm import low_dd_xsm, load_all
        from strategy_lab.v29_long_short_deep import long_short_backtest
        data = load_all()
        print("  generating V24 multi-filter 1× equity ...", flush=True)
        eq_v24, _, _ = low_dd_xsm(data, mode="multi_filter",
                                   lookback_days=14, top_k=4, rebal_days=7,
                                   leverage=1.0, btc_ma_days=100,
                                   mf_breadth_min=5, mf_btc_ma_fast=50)
        out["MY_V24_MF_1x"] = eq_v24
        print("  generating V27 L/S 0.5× equity ...", flush=True)
        eq_v27, _ = long_short_backtest(data, lookback_days=14, top_k=2, bottom_k=2,
                                         rebal_days=7, leverage=0.5)
        out["MY_V27_LS_0.5x"] = eq_v27
    except Exception as e:
        print(f"  error regenerating XSM: {type(e).__name__}: {e}")
    return out


def align_all(sleeves: dict[str, pd.Series]) -> pd.DataFrame:
    idx = None
    for eq in sleeves.values():
        if idx is None: idx = eq.index
        else:            idx = idx.union(eq.index)
    idx = idx.sort_values()
    out = pd.DataFrame(index=idx)
    for name, eq in sleeves.items():
        out[name] = eq.reindex(idx).ffill().bfill()
    return out


def main():
    print("=" * 70); print("USER 5-SLEEVE LIVE PORTFOLIO"); print("=" * 70)
    user_sleeves = load_user_live_five()
    if len(user_sleeves) < 5:
        print(f"WARNING: only loaded {len(user_sleeves)}/5 user sleeves.")

    print("\n" + "=" * 70); print("MY XSM PORTFOLIO FAMILY"); print("=" * 70)
    my_sleeves = load_my_xsm()

    # Equal-weight user portfolio (20% each)
    w_user = {s: 1/len(user_sleeves) for s in user_sleeves}
    user_eq = combine_sleeves(user_sleeves, w_user, init=10_000)

    # Individual MY equities (already portfolios themselves)
    all_eqs = dict(user_sleeves)
    all_eqs["USER_5SLEEVE_EQW"] = user_eq
    for k, eq in my_sleeves.items():
        all_eqs[k] = eq

    # Align and save
    df_all = align_all(all_eqs)
    df_all.to_csv(OUT / "sleeve_equities.csv")
    print(f"\nSaved {OUT/'sleeve_equities.csv'}  shape={df_all.shape}")

    # Cross-slice to common OVERLAP window only (2023-01 to min end)
    cut_start = pd.Timestamp("2023-01-01", tz="UTC")
    cut_end = min(eq.index[-1] for eq in all_eqs.values())
    mask = (df_all.index >= cut_start) & (df_all.index <= cut_end)
    sub = df_all.loc[mask]
    sub = sub.ffill().bfill()
    # Normalize each to $10k at start of window
    sub_norm = sub / sub.iloc[0] * 10_000
    sub_norm.to_csv(OUT / "sleeve_equities_2023plus_normed.csv")

    print(f"\nOverlap window: {sub.index[0].date()} -> {sub.index[-1].date()}  ({len(sub):,} bars)")
    print("\n=== Individual sleeve metrics (2023+ normalized to $10k) ===")
    m_rows = []
    for col in sub_norm.columns:
        m = metrics(sub_norm[col], col)
        m_rows.append(m)
        print(f"  {col:<25}  CAGR {m['cagr']*100:+7.1f}%  Sh {m['sharpe']:+.2f}  "
              f"DD {m['dd']*100:+6.1f}%  Calmar {m['calmar']:.2f}  "
              f"Final ${m['final']:,.0f}")
    pd.DataFrame(m_rows).to_csv(OUT / "sleeve_metrics.csv", index=False)

    # Correlation of weekly returns
    rets = sub_norm.pct_change(fill_method=None).dropna().resample("1W").sum()
    corr = rets.corr()
    corr.to_csv(OUT / "correlation_matrix.csv")
    print("\n=== Weekly-return correlation matrix ===")
    print(corr.round(2).to_string())

    # Combined portfolios
    print("\n=== COMBINED PORTFOLIOS ===")
    combos = [
        ("100% USER_5SLEEVE",          {"USER_5SLEEVE_EQW": 1.0}),
        ("100% MY_V24_MF",             {"MY_V24_MF_1x": 1.0}),
        ("100% MY_V15_BAL",            {"MY_V15_BALANCED": 1.0}),
        ("100% MY_V27_LS",             {"MY_V27_LS_0.5x": 1.0}),
        ("50/50  USER+V24",            {"USER_5SLEEVE_EQW": 0.5, "MY_V24_MF_1x": 0.5}),
        ("70/30  USER+V24",            {"USER_5SLEEVE_EQW": 0.7, "MY_V24_MF_1x": 0.3}),
        ("30/70  USER+V24",            {"USER_5SLEEVE_EQW": 0.3, "MY_V24_MF_1x": 0.7}),
        ("50/50  USER+V15",            {"USER_5SLEEVE_EQW": 0.5, "MY_V15_BALANCED": 0.5}),
        ("50/50  USER+V27",            {"USER_5SLEEVE_EQW": 0.5, "MY_V27_LS_0.5x": 0.5}),
        ("3-way 33/33/34  USER+V24+V27",
          {"USER_5SLEEVE_EQW": 0.34, "MY_V24_MF_1x": 0.33, "MY_V27_LS_0.5x": 0.33}),
        ("4-way 25% each",
          {"USER_5SLEEVE_EQW": 0.25, "MY_V24_MF_1x": 0.25,
           "MY_V15_BALANCED": 0.25, "MY_V27_LS_0.5x": 0.25}),
    ]
    cp_rows = []
    cp_eqs = {}
    for label, w in combos:
        eq = sum(sub_norm[k] * w[k] for k in w if k in sub_norm.columns)
        if isinstance(eq, (int, float)):
            continue
        eq = eq.ffill().bfill()
        cp_eqs[label] = eq
        m = metrics(eq, label)
        cp_rows.append(m)
        print(f"  {label:<35}  CAGR {m['cagr']*100:+7.1f}%  Sh {m['sharpe']:+.2f}  "
              f"DD {m['dd']*100:+6.1f}%  Calmar {m['calmar']:.2f}  "
              f"Final ${m['final']:,.0f}")
    cp_df = pd.DataFrame(cp_rows)
    cp_df.to_csv(OUT / "combined_portfolios.csv", index=False)
    pd.DataFrame(cp_eqs).to_csv(OUT / "combined_equities.csv")

    # Find best mix
    print("\n=== RANKED BY SHARPE ===")
    cp_df_s = cp_df.sort_values("sharpe", ascending=False)
    print(cp_df_s.to_string(index=False))
    print("\n=== RANKED BY CALMAR ===")
    print(cp_df.sort_values("calmar", ascending=False).to_string(index=False))
    print("\n=== RANKED BY |DD| (smallest first) ===")
    print(cp_df.sort_values("dd", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
