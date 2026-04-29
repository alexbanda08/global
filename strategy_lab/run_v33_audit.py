"""
V33 audit — combines IS/OOS walk-forward + V31 overfit 5-test suite.
Applied ONLY to candidates with sharpe >= 0.4 and cagr_net >= 0.05 from V33 sweep.
"""
from __future__ import annotations
import sys, pickle, warnings, math, time
warnings.filterwarnings("ignore")
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import simulate, metrics
from strategy_lab.run_v33_scalp_creative import (
    FAMILIES, _load, SPLIT, FEE,
    sig_vwap_scalp, sig_keltner_pullback, sig_rsi_div, sig_atr_burst,
    sig_orb_break, sig_ethbtc_ratio_revert,
)

OUT = Path(__file__).resolve().parent / "results" / "v33"

# ----- IS/OOS slice -----
def slice_metrics(df, ls, ss, exits, risk, lev):
    is_mask = df.index < SPLIT
    oos_mask = ~is_mask
    is_df, oos_df = df[is_mask], df[oos_mask]
    is_ls, is_ss = ls[is_mask], ss[is_mask]
    oos_ls, oos_ss = ls[oos_mask], ss[oos_mask]

    is_tr, is_eq = simulate(is_df, is_ls, is_ss,
                            tp_atr=exits["tp"], sl_atr=exits["sl"],
                            trail_atr=exits["trail"], max_hold=exits["mh"],
                            risk_per_trade=risk, leverage_cap=lev, fee=FEE)
    oos_tr, oos_eq = simulate(oos_df, oos_ls, oos_ss,
                              tp_atr=exits["tp"], sl_atr=exits["sl"],
                              trail_atr=exits["trail"], max_hold=exits["mh"],
                              risk_per_trade=risk, leverage_cap=lev, fee=FEE)
    is_m = metrics("IS", is_eq, is_tr)
    oos_m = metrics("OOS", oos_eq, oos_tr)
    return is_m, oos_m


def build_signal(family, df, btc_df, params):
    """Dispatch to appropriate signal fn."""
    if family == "VWAP_Scalp":
        return sig_vwap_scalp(df, **params)
    if family == "Keltner_Pullback":
        return sig_keltner_pullback(df, **params)
    if family == "RSI_Div":
        return sig_rsi_div(df, **params)
    if family == "ATR_Burst":
        return sig_atr_burst(df, **params)
    if family == "ORB_Break":
        return sig_orb_break(df, **params)
    if family == "ETHBTC_Ratio":
        return sig_ethbtc_ratio_revert(df, btc_df, **params)
    raise ValueError(family)


# ----- Per-year breakdown -----
def per_year_breakdown(eq):
    y = pd.DataFrame({"eq": eq.values}, index=eq.index)
    y["year"] = y.index.year
    rows = []
    for yr, g in y.groupby("year"):
        if len(g) < 5: continue
        rets = g["eq"].pct_change().dropna()
        cagr = (g["eq"].iloc[-1] / g["eq"].iloc[0]) ** (365 / max(1, (g.index[-1] - g.index[0]).days)) - 1
        sh = rets.mean() / rets.std() * math.sqrt(365 * 24) if rets.std() > 0 else 0
        dd = float((g["eq"] / g["eq"].cummax() - 1).min())
        lr = math.log(max(g["eq"].iloc[-1] / g["eq"].iloc[0], 1e-9))
        rows.append(dict(year=int(yr), cagr=round(cagr * 100, 1),
                         sharpe=round(sh, 2), dd=round(dd * 100, 1), log_ret=round(lr, 3)))
    return pd.DataFrame(rows)


# ----- Plateau test -----
PARAM_GRIDS = {
    "VWAP_Scalp":       {"z_thr": [1.5, 2.0, 2.5], "vwap_n": [20, 40, 80], "rsi_confirm": [30, 35, 40, 45]},
    "Keltner_Pullback": {"kc_n": [20, 30, 40], "kc_mult": [1.5, 2.0, 2.5], "ema_reg": [100, 150, 200, 300], "rsi_dip": [30, 35, 40, 45]},
    "RSI_Div":          {"rsi_n": [10, 14, 21, 28], "lookback": [15, 20, 30, 40], "rsi_lo": [25, 30, 35, 40]},
    "ATR_Burst":        {"atr_mult": [1.5, 1.8, 2.2, 2.8, 3.5], "lookback": [20, 40, 60], "adx_min": [15, 20, 25, 30]},
    "ORB_Break":        {"range_bars": [2, 4, 8, 12, 16], "regime_len": [100, 200, 300]},
    "ETHBTC_Ratio":     {"z_lookback": [30, 50, 100, 200, 300], "z_thr": [1.5, 2.0, 2.5, 3.0]},
}


def neighbors(family, base):
    grid = PARAM_GRIDS[family]
    neighs = [dict(base)]
    for k in base:
        vals = grid[k]
        idx = vals.index(base[k]) if base[k] in vals else -1
        for step in (-1, 1):
            ni = idx + step
            if 0 <= ni < len(vals):
                n = dict(base)
                n[k] = vals[ni]
                if n != base: neighs.append(n)
    # dedupe
    seen, uniq = set(), []
    for n in neighs:
        t = tuple(sorted(n.items()))
        if t not in seen:
            seen.add(t); uniq.append(n)
    return uniq


def plateau_test(df, btc_df, family, base_params, exits, risk, lev):
    neighs = neighbors(family, base_params)
    results = []
    for p in neighs:
        try:
            ls, ss = build_signal(family, df, btc_df, p)
            tr, eq = simulate(df, ls, ss,
                              tp_atr=exits["tp"], sl_atr=exits["sl"],
                              trail_atr=exits["trail"], max_hold=exits["mh"],
                              risk_per_trade=risk, leverage_cap=lev, fee=FEE)
            m = metrics("p", eq, tr)
            results.append(dict(params=p, cagr=m["cagr_net"], sharpe=m["sharpe"], n=m["n"]))
        except Exception:
            continue
    n_pos = sum(1 for r in results if r["cagr"] > 0 and r["sharpe"] > 0.3)
    return n_pos, len(results), results


# ----- Random entry null -----
def random_entry_null(df, real_ls, real_ss, exits, risk, lev, n_trials=60, seed=42):
    rng = np.random.default_rng(seed)
    n_long = int(real_ls.sum())
    n_short = int(real_ss.sum())
    N = len(df)
    sharpes = []
    for _ in range(n_trials):
        l_idx = rng.choice(N, size=n_long, replace=False) if n_long > 0 else np.array([], dtype=int)
        s_idx = rng.choice(N, size=n_short, replace=False) if n_short > 0 else np.array([], dtype=int)
        ls = pd.Series(False, index=df.index); ls.iloc[l_idx] = True
        ss = pd.Series(False, index=df.index); ss.iloc[s_idx] = True
        tr, eq = simulate(df, ls, ss,
                          tp_atr=exits["tp"], sl_atr=exits["sl"],
                          trail_atr=exits["trail"], max_hold=exits["mh"],
                          risk_per_trade=risk, leverage_cap=lev, fee=FEE)
        m = metrics("n", eq, tr)
        sharpes.append(m["sharpe"])
    return np.array(sharpes)


# ----- Monte Carlo bootstrap -----
def mc_bootstrap(eq, n_iters=500, seed=42):
    rng = np.random.default_rng(seed)
    rets = eq.resample("M").last().pct_change().dropna().values
    if len(rets) < 6:
        return dict(cagr_p5=np.nan, cagr_p50=np.nan, cagr_p95=np.nan,
                    sh_p5=np.nan, sh_p50=np.nan, sh_p95=np.nan)
    cagrs, sharpes = [], []
    for _ in range(n_iters):
        sample = rng.choice(rets, size=len(rets), replace=True)
        mu = sample.mean(); sd = sample.std()
        cagr = (1 + mu) ** 12 - 1
        sh = mu / sd * math.sqrt(12) if sd > 0 else 0
        cagrs.append(cagr); sharpes.append(sh)
    return dict(
        cagr_p5=round(np.percentile(cagrs, 5) * 100, 1),
        cagr_p50=round(np.percentile(cagrs, 50) * 100, 1),
        cagr_p95=round(np.percentile(cagrs, 95) * 100, 1),
        sh_p5=round(np.percentile(sharpes, 5), 2),
        sh_p50=round(np.percentile(sharpes, 50), 2),
        sh_p95=round(np.percentile(sharpes, 95), 2),
    )


# ----- Deflated Sharpe (Lopez de Prado 2014) -----
from math import sqrt, log, erf
def norm_cdf(x): return 0.5 * (1 + erf(x / sqrt(2)))
def norm_ppf(q):
    # rough approx (Beasley-Springer / Moro). For q in (0.01, 0.99).
    # Good enough for our purposes.
    from scipy.stats import norm
    return norm.ppf(q)

def deflated_sharpe(actual_sh, n_trials, n_obs, skew=0.0, kurt=3.0):
    if n_obs <= 1 or n_trials <= 1: return 1.0, 1.0
    # Max Sharpe expected under null (uncorrelated trials)
    em_c = 0.5772
    sh_max = sqrt(2 * log(n_trials)) * (1 - em_c) + em_c * norm_ppf(1 - 1 / (n_trials * math.e))
    # PSR with DSR threshold
    denom = sqrt(1 - skew * actual_sh + (kurt - 1) / 4 * actual_sh**2) / sqrt(n_obs - 1)
    psr = norm_cdf((actual_sh - 0) / max(denom, 1e-9))
    dsr = norm_cdf((actual_sh - sh_max) / max(denom, 1e-9))
    return round(psr, 3), round(dsr, 3)


# ----- Candidates to audit -----
N_TRIALS_V33 = 2232  # configs tested in V33 sweep

CANDIDATES = [
    # (label, sym, family, tf)
    ("SUI RSI_Div 1h",          "SUIUSDT", "RSI_Div",          "1h"),
    ("SUI Keltner_Pullback 1h", "SUIUSDT", "Keltner_Pullback", "1h"),
    ("DOGE RSI_Div 4h",         "DOGEUSDT","RSI_Div",          "4h"),
    ("ETH ETHBTC_Ratio 4h",     "ETHUSDT", "ETHBTC_Ratio",     "4h"),
    ("SOL ATR_Burst 1h",        "SOLUSDT", "ATR_Burst",        "1h"),
    ("DOGE Keltner_Pullback 1h","DOGEUSDT","Keltner_Pullback", "1h"),
    ("SOL Keltner_Pullback 15m","SOLUSDT", "Keltner_Pullback", "15m"),
]


def main():
    results = pickle.load(open(OUT / "v33_sweep_results.pkl", "rb"))
    btc_by_tf = {}
    for tf in ("1h", "4h"):
        b = _load("BTCUSDT", tf)
        if b is not None: btc_by_tf[tf] = b

    summary = []
    t0 = time.time()
    print(f"\n{'='*70}")
    print("V33 — IS/OOS + OVERFIT AUDIT")
    print(f"{'='*70}")

    for label, sym, family, tf in CANDIDATES:
        key = f"{sym}_{family}_{tf}"
        if key not in results:
            print(f"\n!! {label}: NOT FOUND in sweep results"); continue
        w = results[key]
        df = _load(sym, tf)
        btc_df = btc_by_tf.get(tf)
        params = w["params"]; exits = w["exits"]; risk = w["risk"]; lev = w["lev"]

        print(f"\n{'='*70}\n  {label}\n{'='*70}")
        print(f"  Params: {params}  Exits: {exits}  Risk={risk}  Lev={lev}")
        print(f"  Sweep full-period: CAGR={w['cagr_net']*100:+.1f}%  Sh={w['sharpe']:+.2f}  n={w['n']}")

        # --- IS/OOS ---
        ls, ss = build_signal(family, df, btc_df, params)
        is_m, oos_m = slice_metrics(df, ls, ss, exits, risk, lev)
        print(f"  IS  n={is_m['n']:3d}  CAGR={is_m['cagr_net']*100:+6.1f}%  Sh={is_m['sharpe']:+.2f}  DD={is_m['dd']*100:+.1f}%")
        print(f"  OOS n={oos_m['n']:3d}  CAGR={oos_m['cagr_net']*100:+6.1f}%  Sh={oos_m['sharpe']:+.2f}  DD={oos_m['dd']*100:+.1f}%")
        oos_pass = oos_m["sharpe"] >= 0.5 * max(0.1, is_m["sharpe"])
        print(f"  OOS verdict: {'PASS' if oos_pass else 'FAIL'}")

        # --- Full-period rerun for audit tests ---
        tr_full, eq_full = simulate(df, ls, ss,
                                    tp_atr=exits["tp"], sl_atr=exits["sl"],
                                    trail_atr=exits["trail"], max_hold=exits["mh"],
                                    risk_per_trade=risk, leverage_cap=lev, fee=FEE)

        # --- Per-year ---
        yr = per_year_breakdown(eq_full)
        print(f"  PER-YEAR:"); print(yr.to_string(index=False))
        total_lr = yr["log_ret"].sum() if len(yr) else 0
        max_share = yr["log_ret"].abs().max() / abs(total_lr) if total_lr != 0 else 1.0
        neg_yrs = (yr["cagr"] < 0).sum()

        # --- Plateau ---
        n_pos, n_total, _ = plateau_test(df, btc_df, family, params, exits, risk, lev)
        plateau_pct = 100.0 * n_pos / max(1, n_total)
        print(f"  PLATEAU: {n_pos}/{n_total}={plateau_pct:.0f}%")

        # --- Random entry null ---
        null_shs = random_entry_null(df, ls, ss, exits, risk, lev, n_trials=60)
        actual_sh = oos_m["sharpe"] if oos_m["sharpe"] != 0 else w["sharpe"]
        null_pct = 100.0 * (actual_sh > null_shs).mean()
        print(f"  NULL: actual Sh {actual_sh:+.2f} beats {null_pct:.0f}% of 60 trials  (null mean={null_shs.mean():+.2f})")

        # --- MC bootstrap ---
        mc = mc_bootstrap(eq_full)
        print(f"  MC: CAGR p5/50/95 = {mc['cagr_p5']}/{mc['cagr_p50']}/{mc['cagr_p95']}%")

        # --- DSR ---
        n_obs_daily = int((eq_full.index[-1] - eq_full.index[0]).days)
        psr, dsr = deflated_sharpe(w["sharpe"], N_TRIALS_V33, n_obs_daily)
        print(f"  DSR: PSR={psr}  DSR={dsr}  (n_trials={N_TRIALS_V33}, n_obs_daily={n_obs_daily})")

        # Verdict
        pass_plateau = plateau_pct >= 60
        pass_null = null_pct >= 80
        pass_dsr = dsr >= 0.9
        pass_yrs = neg_yrs <= 2 and max_share <= 0.5
        robust = all([pass_plateau, pass_null, pass_dsr, pass_yrs, oos_pass])
        verdict = "ROBUST" if robust else ("FRAGILE" if (pass_plateau + pass_null + pass_dsr) >= 2 else "OVERFIT")
        print(f"  VERDICT: {verdict}")

        summary.append(dict(label=label, cagr=w["cagr_net"]*100, sh=w["sharpe"],
                             is_sh=is_m["sharpe"], oos_sh=oos_m["sharpe"],
                             oos_cagr=oos_m["cagr_net"]*100,
                             neg_yrs=int(neg_yrs), max_yr_share=round(max_share, 2),
                             plateau_pct=round(plateau_pct, 1),
                             null_pct=round(null_pct, 1),
                             mc_p5=mc["cagr_p5"], psr=psr, dsr=dsr, verdict=verdict))

    print(f"\n{'='*80}\nSUMMARY\n{'='*80}")
    s = pd.DataFrame(summary)
    print(s.to_string(index=False))
    s.to_csv(OUT / "v33_audit.csv", index=False)
    print(f"\nSaved: {OUT/'v33_audit.csv'}  ({time.time()-t0:.1f}s)")


if __name__ == "__main__":
    main()
