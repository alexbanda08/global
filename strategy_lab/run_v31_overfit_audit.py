"""V31 — Overfitting audit on the top V28/V29/V30 winners.

Five complementary tests:

  1. PER-YEAR BREAKDOWN
     Annual CAGR, Sharpe, max-DD per calendar year. Flag years <-10% or
     years carrying >60% of cumulative log-return (concentration red flag).

  2. PARAM PLATEAU (V29/V30 only — re-simulatable)
     Perturb each param dimension ±1 grid step, rerun simulation, count
     how many of the 2N neighbors are still "positive" (CAGR > 0, Sh > 0.3).
     A robust winner sits in a plateau (most neighbors positive).

  3. RANDOMIZED-ENTRY NULL (V29/V30 only)
     Shuffle entry timestamps: keep same N entries at random positions,
     same exits / sizing. Run 100 replicates, report percentile of actual
     Sharpe vs null distribution. <90th percentile = weak evidence of edge.

  4. MC BOOTSTRAP on monthly returns
     Resample with replacement 1000×, compute 5th-percentile CAGR & Sharpe.

  5. DEFLATED SHARPE (López de Prado 2014, simplified)
     Adjusts for multiple-testing. Given ~6000 configs searched, the
     expected best-of-N Sharpe under the null is ~0.9-1.1. DSR > 0 and
     PSR > 0.95 indicates real edge beyond chance.
"""
from __future__ import annotations
import pickle, sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import simulate, metrics
from strategy_lab.run_v29_regime import (
    _load as load29, dedupe, sig_trend_grade, sig_lateral_bb_fade,
    sig_regime_switch, FEE,
)
from strategy_lab.run_v30_creative import (
    sig_ttm_squeeze, sig_vwap_zfade, sig_connors_rsi,
    sig_supertrend_flip, sig_cci_extreme, scaled,
)

OUT = Path(__file__).resolve().parent / "results" / "v31"
OUT.mkdir(parents=True, exist_ok=True)


# =====================================================================
# Top-10 audit list — the ones that matter for the peak portfolio
# =====================================================================

AUDIT = [
    # (label, sym, family, tf, params, exits, risk, lev, version)
    ("ETH CCI_Extreme_Rev 4h",   "ETHUSDT",  "CCI_Extreme_Rev", "4h",
        dict(cci_n=20, cci_thr=100, adx_max=28),
        dict(tp=6, sl=1.5, trail=3.5, mh=20), 0.05, 3.0, "V30"),
    ("SUI Lateral_BB_Fade 1h",   "SUIUSDT",  "Lateral_BB_Fade", "1h",
        dict(bb_n=20, bb_k=2.2, adx_max=22, bw_q=0.60),
        dict(tp=10, sl=2.0, trail=5.0, mh=72), 0.05, 3.0, "V29"),
    ("SOL Lateral_BB_Fade 4h",   "SOLUSDT",  "Lateral_BB_Fade", "4h",
        dict(bb_n=20, bb_k=2.2, adx_max=22, bw_q=0.75),
        dict(tp=10, sl=2.0, trail=5.0, mh=40), 0.05, 3.0, "V29"),
    ("ETH Lateral_BB_Fade 4h",   "ETHUSDT",  "Lateral_BB_Fade", "4h",
        dict(bb_n=20, bb_k=2.2, adx_max=22, bw_q=0.60),
        dict(tp=10, sl=2.0, trail=5.0, mh=40), 0.05, 3.0, "V29"),
    ("TON CCI_Extreme_Rev 4h",   "TONUSDT",  "CCI_Extreme_Rev", "4h",
        dict(cci_n=30, cci_thr=100, adx_max=22),
        dict(tp=6, sl=1.5, trail=3.5, mh=20), 0.05, 3.0, "V30"),
    ("SUI CCI_Extreme_Rev 4h",   "SUIUSDT",  "CCI_Extreme_Rev", "4h",
        dict(cci_n=20, cci_thr=100, adx_max=28),
        dict(tp=6, sl=1.5, trail=3.5, mh=20), 0.05, 3.0, "V30"),
    ("DOGE TTM_Squeeze_Pop 4h",  "DOGEUSDT", "TTM_Squeeze_Pop", "4h",
        dict(bb_k=2.0, kc_mult=1.5, mom_n=20),
        dict(tp=10, sl=2.0, trail=5.0, mh=40), 0.05, 3.0, "V30"),
    ("SOL SuperTrend_Flip 4h",   "SOLUSDT",  "SuperTrend_Flip", "4h",
        dict(st_n=10, st_mult=3.0, ema_reg=200),
        dict(tp=10, sl=2.0, trail=5.0, mh=40), 0.05, 3.0, "V30"),
    ("AVAX VWAP_Zfade 1h",       "AVAXUSDT", "VWAP_Zfade", "1h",
        dict(vwap_n=100, z_thr=2.0, adx_max=22),
        dict(tp=10, sl=2.0, trail=5.0, mh=72), 0.05, 3.0, "V30"),
    ("ETH VWAP_Zfade 4h",        "ETHUSDT",  "VWAP_Zfade", "4h",
        dict(vwap_n=100, z_thr=2.0, adx_max=22),
        dict(tp=10, sl=2.0, trail=5.0, mh=40), 0.05, 3.0, "V30"),
]


def build_signal(family, df, p, tf):
    if family == "CCI_Extreme_Rev":
        return sig_cci_extreme(df, p["cci_n"], -p["cci_thr"], p["cci_thr"], p["adx_max"], 14)
    if family == "Lateral_BB_Fade":
        return sig_lateral_bb_fade(df, p["bb_n"], p["bb_k"], p["adx_max"], 14,
                                    scaled(200, tf), p["bw_q"])
    if family == "TTM_Squeeze_Pop":
        return sig_ttm_squeeze(df, 20, p["bb_k"], 20, p["kc_mult"], p["mom_n"])
    if family == "SuperTrend_Flip":
        return sig_supertrend_flip(df, p["st_n"], p["st_mult"], p["ema_reg"])
    if family == "VWAP_Zfade":
        return sig_vwap_zfade(df, scaled(p["vwap_n"], tf), p["z_thr"], p["adx_max"], 14)
    if family == "Trend_Grade_MTF":
        return sig_trend_grade(df, p["thr"], p["rsi_lo"], p["rsi_hi"], 14, p["adx_min"])
    if family == "Regime_Switch":
        return sig_regime_switch(df, p["donch_n"], p["ema_reg"], 20, 2.0, p["adx_lo"], p["adx_hi"], 14)
    raise ValueError(family)


def run_sim(df, lsig, ssig, exits, risk, lev, lbl):
    ls = dedupe(lsig); ss = dedupe(ssig) if ssig is not None else None
    trades, eq = simulate(df, ls, short_entries=ss,
                          tp_atr=exits["tp"], sl_atr=exits["sl"],
                          trail_atr=exits["trail"], max_hold=exits["mh"],
                          risk_per_trade=risk, leverage_cap=lev, fee=FEE)
    return metrics(lbl, eq, trades), trades, eq


# =====================================================================
# Test 1 — Per-year breakdown
# =====================================================================

def per_year_breakdown(eq):
    rows = []
    eq = eq.dropna()
    if len(eq) < 30: return pd.DataFrame()
    eq.index = pd.to_datetime(eq.index, utc=True)
    for y in range(2020, 2027):
        s = pd.Timestamp(f"{y}-01-01", tz="UTC")
        e = pd.Timestamp(f"{y+1}-01-01", tz="UTC")
        sub = eq[(eq.index >= s) & (eq.index < e)]
        if len(sub) < 50: continue
        ret = sub.iloc[-1] / sub.iloc[0] - 1
        days = (sub.index[-1] - sub.index[0]).total_seconds() / 86400
        cagr = (1 + ret) ** (365.25 / max(days, 1)) - 1 if days > 0 else 0
        # Daily-resampled Sharpe
        daily = sub.resample("1D").last().dropna().pct_change().dropna()
        sh = (daily.mean() / daily.std()) * np.sqrt(365) if daily.std() > 0 else 0
        dd = ((sub / sub.cummax()) - 1).min()
        rows.append(dict(year=y, cagr=round(cagr*100, 1), sharpe=round(sh, 2),
                         dd=round(dd*100, 1), log_ret=round(np.log(sub.iloc[-1]/sub.iloc[0]), 3)))
    return pd.DataFrame(rows)


# =====================================================================
# Test 2 — Parameter plateau
# =====================================================================

PARAM_GRID = {
    "CCI_Extreme_Rev": dict(cci_n=[14,20,30], cci_thr=[100,150,200], adx_max=[18,22,28]),
    "Lateral_BB_Fade": dict(bb_n=[20,30], bb_k=[1.8,2.2], adx_max=[15,18,22], bw_q=[0.40,0.60,0.75]),
    "TTM_Squeeze_Pop": dict(bb_k=[1.8,2.0,2.2], kc_mult=[1.2,1.5,1.8], mom_n=[10,20]),
    "SuperTrend_Flip": dict(st_n=[7,10,14], st_mult=[2.0,3.0,4.0], ema_reg=[100,200]),
    "VWAP_Zfade":      dict(vwap_n=[50,100,200], z_thr=[1.5,2.0,2.5], adx_max=[18,22,28]),
}


def neighbors(family, base):
    """One-step neighbors (including base)."""
    grid = PARAM_GRID.get(family)
    if grid is None: return []
    out = []
    for k, values in grid.items():
        if k not in base: continue
        try: idx = values.index(base[k])
        except ValueError: continue
        for offset in (-1, 0, 1):
            ni = idx + offset
            if 0 <= ni < len(values):
                p = dict(base); p[k] = values[ni]
                out.append(p)
    # dedupe
    seen = set(); uniq = []
    for p in out:
        key = tuple(sorted(p.items()))
        if key in seen: continue
        seen.add(key); uniq.append(p)
    return uniq


def plateau_test(df, family, base_params, tf, exits, risk, lev):
    results = []
    for p in neighbors(family, base_params):
        try: lsig, ssig = build_signal(family, df, p, tf)
        except Exception: continue
        if (lsig.sum() + ssig.sum()) < 10: continue
        r, _, _ = run_sim(df, lsig, ssig, exits, risk, lev, "pl")
        results.append(dict(params=p, cagr=r["cagr_net"], sharpe=r["sharpe"], n=r["n"], dd=r["dd"]))
    return results


# =====================================================================
# Test 3 — Randomized-entry null
# =====================================================================

def random_entry_null(df, real_lsig, real_ssig, exits, risk, lev, n_trials=100, seed=42):
    rng = np.random.default_rng(seed)
    n_long = int(real_lsig.sum()); n_short = int(real_ssig.sum())
    if n_long + n_short < 10: return None
    null_sharpes = []
    idx = np.arange(len(df))
    for _ in range(n_trials):
        l_pos = rng.choice(idx, size=n_long, replace=False)
        s_pos = rng.choice(idx, size=n_short, replace=False)
        lsig = pd.Series(False, index=df.index); lsig.iloc[l_pos] = True
        ssig = pd.Series(False, index=df.index); ssig.iloc[s_pos] = True
        try:
            r, _, _ = run_sim(df, lsig, ssig, exits, risk, lev, "null")
            null_sharpes.append(r["sharpe"])
        except Exception:
            null_sharpes.append(np.nan)
    return np.array(null_sharpes)


# =====================================================================
# Test 4 — Monte Carlo bootstrap on monthly returns
# =====================================================================

def mc_bootstrap_monthly(eq, n_iters=1000, seed=42):
    eq = eq.dropna()
    if len(eq) < 60: return None
    eq.index = pd.to_datetime(eq.index, utc=True)
    monthly = eq.resample("1ME").last().dropna().pct_change().dropna()
    if len(monthly) < 12: return None
    months_per_year = 12
    rng = np.random.default_rng(seed)
    cagrs = []; sharpes = []
    for _ in range(n_iters):
        sample = rng.choice(monthly.values, size=len(monthly), replace=True)
        gross = np.prod(1 + sample)
        yrs = len(sample) / months_per_year
        cagrs.append(gross ** (1 / max(yrs, 1e-6)) - 1)
        sd = sample.std()
        sharpes.append((sample.mean() / sd) * np.sqrt(12) if sd > 0 else 0)
    return dict(
        cagr_p5=np.percentile(cagrs, 5), cagr_p50=np.percentile(cagrs, 50),
        cagr_p95=np.percentile(cagrs, 95),
        sh_p5=np.percentile(sharpes, 5), sh_p50=np.percentile(sharpes, 50),
        sh_p95=np.percentile(sharpes, 95),
    )


# =====================================================================
# Test 5 — Deflated / probabilistic Sharpe
# =====================================================================

def deflated_sharpe(actual_sh, n_trials, n_obs):
    """
    Probabilistic Sharpe: P(true Sh > 0 | observed actual_sh).
    Deflated Sharpe: P(true Sh > expected best-of-N | observed actual_sh).
    Assuming null Sh~N(0,1/sqrt(N_obs)). Simplified Lopez de Prado.
    """
    if actual_sh is None or np.isnan(actual_sh): return None, None
    # PSR — prob that observed > 0
    psr = stats.norm.cdf(actual_sh * np.sqrt(n_obs - 1))
    # Expected best-of-N Sharpe assuming null (standard normal order statistics approx)
    emc = 0.5772  # Euler-Mascheroni
    z_n = (1 - emc) * stats.norm.ppf(1 - 1/n_trials) + emc * stats.norm.ppf(1 - 1/(n_trials*np.e))
    sh_ref = z_n / np.sqrt(n_obs)  # reference Sh under null after N trials
    # DSR — prob observed > reference
    dsr = stats.norm.cdf((actual_sh - sh_ref) * np.sqrt(n_obs - 1))
    return psr, dsr


# =====================================================================
# Main runner
# =====================================================================

def main():
    N_TRIALS_ESTIMATE = 6000   # rough count from V30 sweep
    summary = []
    detail_tables = {}

    for label, sym, family, tf, params, exits, risk, lev, ver in AUDIT:
        print(f"\n{'='*70}\n  {label}  [{ver}]\n{'='*70}", flush=True)
        df = load29(sym, tf)
        if df is None:
            print("  NO DATA"); continue

        # Re-run the actual simulation
        try:
            lsig, ssig = build_signal(family, df, params, tf)
        except Exception as e:
            print(f"  SIGNAL ERR: {e}"); continue
        r, trades, eq = run_sim(df, lsig, ssig, exits, risk, lev, label)
        actual_cagr = r["cagr_net"]; actual_sh = r["sharpe"]; actual_n = r["n"]
        n_daily = len(eq.resample("1D").last().dropna())
        print(f"  Real: CAGR={actual_cagr*100:+.1f}%  Sh={actual_sh:+.2f}  n={actual_n}")

        # Test 1 — per-year
        py = per_year_breakdown(eq)
        print(f"\n  PER-YEAR:")
        print(py.to_string(index=False) if not py.empty else "  (no years)")
        neg_years = (py["cagr"] < -10).sum() if not py.empty else 0
        if not py.empty:
            lr = py["log_ret"].fillna(0)
            max_year_share = (lr.abs().max() / lr.abs().sum()) if lr.abs().sum() > 0 else 0
        else:
            max_year_share = 0

        # Test 2 — plateau (V29/V30 only)
        pl = plateau_test(df, family, params, tf, exits, risk, lev)
        n_neighbors = len(pl)
        n_pos = sum(1 for x in pl if x["cagr"] > 0 and x["sharpe"] > 0.3)
        plateau_pct = n_pos / max(n_neighbors, 1) * 100
        print(f"\n  PLATEAU: {n_pos}/{n_neighbors} neighbors positive  ({plateau_pct:.0f}%)")
        if pl:
            for x in pl[:5]:
                print(f"    p={x['params']}  CAGR={x['cagr']*100:+.1f}%  Sh={x['sharpe']:+.2f}")

        # Test 3 — random-entry null
        null_shs = random_entry_null(df, lsig, ssig, exits, risk, lev, n_trials=80, seed=42)
        if null_shs is not None:
            null_shs = null_shs[~np.isnan(null_shs)]
            pct = (null_shs < actual_sh).sum() / len(null_shs) * 100 if len(null_shs) else 0
            null_mean = float(np.mean(null_shs)) if len(null_shs) else 0
            null_p95 = float(np.percentile(null_shs, 95)) if len(null_shs) else 0
            print(f"\n  RANDOM-ENTRY NULL: actual Sh {actual_sh:+.2f} vs null mean {null_mean:+.2f}, p95 {null_p95:+.2f}")
            print(f"                     actual beats {pct:.0f}% of null trials")
        else:
            pct = None; null_mean = None

        # Test 4 — MC bootstrap
        mc = mc_bootstrap_monthly(eq)
        if mc:
            print(f"\n  MC BOOTSTRAP (1000 iters, monthly returns):")
            print(f"    CAGR  5%={mc['cagr_p5']*100:+6.1f}%   50%={mc['cagr_p50']*100:+6.1f}%   95%={mc['cagr_p95']*100:+6.1f}%")
            print(f"    Sh    5%={mc['sh_p5']:+.2f}          50%={mc['sh_p50']:+.2f}          95%={mc['sh_p95']:+.2f}")

        # Test 5 — DSR/PSR
        psr, dsr = deflated_sharpe(actual_sh, N_TRIALS_ESTIMATE, n_daily)
        print(f"\n  DEFLATED SH: N_trials≈{N_TRIALS_ESTIMATE}, N_obs(daily)={n_daily}")
        print(f"               PSR={psr:.3f}  DSR={dsr:.3f}")

        summary.append(dict(
            label=label, version=ver,
            real_CAGR=round(actual_cagr*100, 1), real_Sh=round(actual_sh, 2),
            neg_yrs=neg_years, max_yr_share=round(max_year_share, 2),
            plateau_pct=round(plateau_pct, 0),
            null_pct=round(pct, 0) if pct is not None else None,
            null_mean=round(null_mean, 2) if null_mean is not None else None,
            mc_CAGR_p5=round(mc["cagr_p5"]*100, 1) if mc else None,
            mc_Sh_p5=round(mc["sh_p5"], 2) if mc else None,
            PSR=round(psr, 3) if psr else None,
            DSR=round(dsr, 3) if dsr else None,
        ))
        detail_tables[label] = py

    df = pd.DataFrame(summary)
    df.to_csv(OUT / "v31_overfit_summary.csv", index=False)
    print(f"\n\n{'='*90}")
    print("V31 OVERFITTING AUDIT — SUMMARY")
    print("="*90)
    pd.set_option('display.width', 200)
    pd.set_option('display.max_colwidth', 40)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
