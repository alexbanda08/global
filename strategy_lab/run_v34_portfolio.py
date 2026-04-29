"""V34 portfolio — correlation matrix across ALL audit-clean sleeves, plus
optimal portfolio hunt with coin diversification + yearly worst-year."""
from __future__ import annotations
import sys, pickle, warnings, time, itertools
warnings.filterwarnings("ignore")
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import simulate, metrics, atr, ema, bb
from strategy_lab.run_v23_all_coins import sig_bbbreak_short
from strategy_lab.run_v27_swing import sig_htf_donchian
from strategy_lab.run_v34_expand import _load, FEE, LEV, sig_bbbreak_ls, sig_htf_donchian_ls, scaled
# Also need V30 family sigs for ETH CCI, SOL SuperTrend, DOGE TTM, ETH VWAP
from strategy_lab.run_v30_creative import (
    sig_cci_extreme, sig_supertrend_flip, sig_ttm_squeeze, sig_vwap_zfade,
)

OUT = Path(__file__).resolve().parent / "results" / "v34"

# ===========================================================
# Define ALL audit-clean sleeves (16 total)
# ===========================================================
# Format: (label, coin, family, tf, params, exits, risk, lev, signal_fn_name)
SLEEVES = [
    # --- V28 P2 cores (V23 BBBreak + V27 Donchian) — V32 audited ---
    ("SOL_BBBreak_4h",      "SOLUSDT",  "BBBreak_LS",      "4h",
        dict(n=45, k=1.5, regime_len=225),
        dict(tp=10, sl=2.0, trail=6.0, mh=30), 0.05, 3.0, "bb_ls_scaled"),
    ("SUI_BBBreak_4h",      "SUIUSDT",  "BBBreak_LS",      "4h",
        dict(n=15, k=1.5, regime_len=150),
        dict(tp=10, sl=2.0, trail=6.0, mh=30), 0.05, 3.0, "bb_ls_raw"),
    ("DOGE_BBBreak_4h",     "DOGEUSDT", "BBBreak_LS",      "4h",
        dict(n=45, k=2.5, regime_len=75),
        dict(tp=10, sl=2.0, trail=6.0, mh=30), 0.05, 3.0, "bb_ls_raw"),
    ("ETH_Donchian_4h",     "ETHUSDT",  "HTF_Donchian",    "4h",
        dict(donch_n=20, ema_reg=200),
        dict(tp=10, sl=2.0, trail=6.0, mh=30), 0.05, 3.0, "donch_ls"),
    ("BTC_Donchian_4h",     "BTCUSDT",  "HTF_Donchian",    "4h",
        dict(donch_n=20, ema_reg=200),
        dict(tp=10, sl=2.0, trail=6.0, mh=30), 0.05, 3.0, "donch_ls"),
    ("SOL_Donchian_4h",     "SOLUSDT",  "HTF_Donchian",    "4h",
        dict(donch_n=20, ema_reg=200),
        dict(tp=10, sl=2.0, trail=6.0, mh=30), 0.05, 3.0, "donch_ls"),
    ("DOGE_Donchian_4h",    "DOGEUSDT", "HTF_Donchian",    "4h",
        dict(donch_n=20, ema_reg=100),
        dict(tp=10, sl=2.0, trail=6.0, mh=30), 0.05, 3.0, "donch_ls"),
    # --- V30 creative (V31 audited) ---
    ("ETH_CCI_4h",          "ETHUSDT",  "CCI_Extreme",     "4h",
        None, None, None, None, "v30_from_pickle"),
    ("SOL_SuperTrend_4h",   "SOLUSDT",  "SuperTrend_Flip", "4h",
        None, None, None, None, "v30_from_pickle"),
    ("DOGE_TTM_4h",         "DOGEUSDT", "TTM_Squeeze",     "4h",
        None, None, None, None, "v30_from_pickle"),
    ("ETH_VWAP_Zfade_4h",   "ETHUSDT",  "VWAP_Zfade",      "4h",
        None, None, None, None, "v30_from_pickle"),
    # --- V34 new (this round) ---
    ("AVAX_BBBreak_4h",     "AVAXUSDT", "BBBreak_LS",      "4h",
        None, None, None, None, "v34_from_pickle"),
    ("TON_BBBreak_4h",      "TONUSDT",  "BBBreak_LS",      "4h",
        None, None, None, None, "v34_from_pickle"),
    ("TON_Donchian_4h",     "TONUSDT",  "HTF_Donchian",    "4h",
        None, None, None, None, "v34_from_pickle"),
    ("LINK_BBBreak_4h",     "LINKUSDT", "BBBreak_LS",      "4h",
        None, None, None, None, "v34_from_pickle"),
    ("LINK_Donchian_4h",    "LINKUSDT", "HTF_Donchian",    "4h",
        None, None, None, None, "v34_from_pickle"),
]


def build_eq_v30(label, sym, family, tf):
    """Load cached equity curve from V30 pickle (eq_index + eq_values already stored)."""
    v30_pkl = Path(__file__).resolve().parent / "results" / "v30" / "v30_creative_results.pkl"
    if not v30_pkl.exists():
        return None
    d = pickle.load(open(v30_pkl, "rb"))
    fam_map = {"CCI_Extreme": "CCI_EXTREME_REV", "SuperTrend_Flip": "SUPERTREND_FLIP",
               "TTM_Squeeze": "TTM_SQUEEZE_POP", "VWAP_Zfade": "VWAP_ZFADE"}
    key = f"{sym}_{fam_map[family]}"
    if key not in d:
        return None
    w = d[key]
    if w.get("tf") != tf:
        return None
    eq = pd.Series(w["eq_values"], index=pd.DatetimeIndex(w["eq_index"]))
    return eq


def build_eq_v34(label, sym, family, tf):
    v34_pkl = OUT / "v34_sweep_results.pkl"
    d = pickle.load(open(v34_pkl, "rb"))
    key = f"{sym}_{family}_{tf}"
    if key not in d: return None
    w = d[key]
    df = _load(sym, tf)
    params = w["params"]; exits = w["exits"]; risk = w["risk"]; lev = w["lev"]
    if family == "BBBreak_LS":
        p = dict(params)
        p["regime_len"] = scaled(p["regime_len"], tf)
        p["n"] = scaled(p["n"], tf)
        ls, ss = sig_bbbreak_ls(df, **p)
    elif family == "HTF_Donchian":
        ls, ss = sig_htf_donchian_ls(df, **params)
    else:
        return None
    tr, eq = simulate(df, ls, ss,
                      tp_atr=exits["tp"], sl_atr=exits["sl"],
                      trail_atr=exits["trail"], max_hold=exits["mh"],
                      risk_per_trade=risk, leverage_cap=lev, fee=FEE)
    return eq


def build_eq_core(label, sym, family, tf, params, exits, risk, lev, fn_name):
    df = _load(sym, tf)
    if fn_name == "bb_ls_scaled":
        p = dict(params)
        p["regime_len"] = p["regime_len"]  # V32 used already-scaled values
        p["n"] = p["n"]
        ls, ss = sig_bbbreak_ls(df, **p)
    elif fn_name == "bb_ls_raw":
        ls, ss = sig_bbbreak_ls(df, **params)
    elif fn_name == "donch_ls":
        ls, ss = sig_htf_donchian_ls(df, **params)
    else:
        return None
    tr, eq = simulate(df, ls, ss,
                      tp_atr=exits["tp"], sl_atr=exits["sl"],
                      trail_atr=exits["trail"], max_hold=exits["mh"],
                      risk_per_trade=risk, leverage_cap=lev, fee=FEE)
    return eq


def main():
    print("Building equity curves for all 16 audit-clean sleeves...")
    eqs = {}
    for row in SLEEVES:
        label, sym, family, tf, params, exits, risk, lev, fn = row
        if fn == "v30_from_pickle":
            eq = build_eq_v30(label, sym, family, tf)
        elif fn == "v34_from_pickle":
            eq = build_eq_v34(label, sym, family, tf)
        else:
            eq = build_eq_core(label, sym, family, tf, params, exits, risk, lev, fn)
        if eq is None:
            print(f"  !! {label}: failed to build")
            continue
        eqs[label] = eq
        print(f"  {label:30s}  rows={len(eq):5d}  final={eq.iloc[-1]:>12,.0f}")

    # ----- Compute monthly returns correlation -----
    monthly = pd.DataFrame({k: v.resample("M").last().pct_change() for k, v in eqs.items()})
    corr = monthly.corr()
    print(f"\n{'='*80}\nMONTHLY-RETURN CORRELATION MATRIX\n{'='*80}")
    # Truncate labels for display
    short = {k: k[:20] for k in eqs}
    cshort = corr.rename(index=short, columns=short)
    print(cshort.round(2).to_string())
    corr.to_csv(OUT / "v34_correlation_matrix.csv")

    # ----- Per-sleeve year-by-year CAGR -----
    print(f"\n{'='*80}\nPER-YEAR CAGR PER SLEEVE\n{'='*80}")
    year_cagr = {}
    for label, eq in eqs.items():
        df_y = pd.DataFrame({"eq": eq.values}, index=eq.index)
        df_y["year"] = df_y.index.year
        yr_cagrs = {}
        for yr, g in df_y.groupby("year"):
            if len(g) < 30: continue
            cagr = (g["eq"].iloc[-1] / g["eq"].iloc[0]) ** (365 / max(1, (g.index[-1] - g.index[0]).days)) - 1
            yr_cagrs[int(yr)] = round(cagr * 100, 1)
        year_cagr[label] = yr_cagrs

    yr_df = pd.DataFrame(year_cagr).T
    print(yr_df.to_string())
    yr_df.to_csv(OUT / "v34_year_cagr_per_sleeve.csv")

    # ----- Portfolio hunt: yearly equal-weighted combos -----
    print(f"\n{'='*80}\nOPTIMAL PORTFOLIO HUNT (yearly equal-weight across distinct coins)\n{'='*80}")
    # Constrain to one sleeve per coin for coin-diversification... or not?
    # Allow multiple sleeves per coin but give correlation penalty

    sleeves = list(year_cagr.keys())
    YEARS = [2023, 2024, 2025]

    def portfolio_metrics(combo_labels):
        """Compute yearly equal-weighted portfolio CAGRs across years."""
        per_year = []
        for yr in YEARS:
            cagrs = [year_cagr[l].get(yr) for l in combo_labels]
            cagrs = [c for c in cagrs if c is not None]
            if len(cagrs) < len(combo_labels) * 0.8:
                return None  # Skip if too many missing
            per_year.append(np.mean(cagrs))
        return dict(worst=min(per_year), avg=np.mean(per_year),
                    by_year={y: round(c, 1) for y, c in zip(YEARS, per_year)})

    def coin_of(label):
        return label.split("_")[0]

    # Try all 3-sleeve, 4-sleeve, 5-sleeve portfolios.
    # Constraint: at least 3 distinct coins per portfolio.
    all_results = []
    for size in (3, 4, 5):
        for combo in itertools.combinations(sleeves, size):
            coins = set(coin_of(l) for l in combo)
            if len(coins) < min(size, 3): continue
            m = portfolio_metrics(combo)
            if m is None: continue
            all_results.append(dict(size=size, combo=combo, coins=coins, **m))
    all_results.sort(key=lambda x: -x["worst"])

    print(f"\nTop 10 portfolios by worst-year CAGR (2023-2025):\n")
    print(f"{'Rank':<5}{'Size':<5}{'Worst':>8}{'Avg':>8}  Members")
    for i, r in enumerate(all_results[:10]):
        members = " + ".join(r["combo"])
        print(f"{i+1:<5}{r['size']:<5}{r['worst']:>7.1f}%{r['avg']:>7.1f}%  {members}")

    # Also highlight best 5-sleeve (most diversified)
    best_5 = max([r for r in all_results if r["size"] == 5], key=lambda x: x["worst"])
    best_5_div = max([r for r in all_results if r["size"] == 5 and len(r["coins"]) == 5],
                     key=lambda x: x["worst"], default=None)
    print(f"\nBest 5-sleeve (any coins): worst={best_5['worst']:.1f}%  {' + '.join(best_5['combo'])}")
    if best_5_div:
        print(f"Best 5-sleeve (5 distinct coins): worst={best_5_div['worst']:.1f}%  "
              f"{' + '.join(best_5_div['combo'])}")

    # Save
    out_df = pd.DataFrame([{
        "size": r["size"], "worst": round(r["worst"], 1),
        "avg": round(r["avg"], 1), "by_year": r["by_year"],
        "members": " + ".join(r["combo"]),
    } for r in all_results[:50]])
    out_df.to_csv(OUT / "v34_top_portfolios.csv", index=False)
    print(f"\nSaved top 50 portfolios to {OUT/'v34_top_portfolios.csv'}")


if __name__ == "__main__":
    main()
