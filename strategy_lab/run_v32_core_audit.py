"""V32 — Apply the V31 overfit suite to the V28 P2 core sleeves.

These are the foundation of the 141.8%/yr peak portfolio — if they fail the
audit, the whole claim collapses.

Tested:
  V23 BBBreak_LS on SOL, SUI, DOGE  (V28 P2 core)
  V27 HTF_Donchian on ETH, BTC, SOL, DOGE
"""
from __future__ import annotations
import sys, pickle
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import (
    simulate, metrics, sig_bbbreak, bb, atr, ema,
)
from strategy_lab.run_v23_all_coins import sig_bbbreak_short, scaled, _load, dedupe, FEE
from strategy_lab.run_v27_swing import sig_htf_donchian

OUT = Path(__file__).resolve().parent / "results" / "v32"
OUT.mkdir(parents=True, exist_ok=True)


# =====================================================================
# Audit candidates — V28 P2 cores
# =====================================================================

AUDIT = [
    # (label, sym, family, tf, params, exits, risk, lev)
    ("SOL BBBreak_LS 4h",        "SOLUSDT",  "BBBreak_LS", "4h",
        dict(n=45, k=1.5, regime_len=225),
        dict(tp=10, sl=2.0, trail=6.0, mh=30), 0.05, 3.0),
    ("SUI BBBreak_LS 4h",        "SUIUSDT",  "BBBreak_LS", "4h",
        dict(n=15, k=1.5, regime_len=150),
        dict(tp=10, sl=2.0, trail=6.0, mh=30), 0.05, 3.0),
    ("DOGE BBBreak_LS 4h",       "DOGEUSDT", "BBBreak_LS", "4h",
        dict(n=45, k=2.5, regime_len=75),
        dict(tp=10, sl=2.0, trail=6.0, mh=30), 0.05, 3.0),
    ("ETH HTF_Donchian 4h",      "ETHUSDT",  "HTF_Donchian", "4h",
        dict(donch_n=20, ema_reg=200),
        dict(tp=10, sl=2.0, trail=6.0, mh=30), 0.05, 3.0),
    ("BTC HTF_Donchian 4h",      "BTCUSDT",  "HTF_Donchian", "4h",
        dict(donch_n=20, ema_reg=200),
        dict(tp=10, sl=2.0, trail=6.0, mh=30), 0.05, 3.0),
    ("SOL HTF_Donchian 4h",      "SOLUSDT",  "HTF_Donchian", "4h",
        dict(donch_n=20, ema_reg=200),
        dict(tp=10, sl=2.0, trail=6.0, mh=30), 0.05, 3.0),
    ("DOGE HTF_Donchian 4h",     "DOGEUSDT", "HTF_Donchian", "4h",
        dict(donch_n=20, ema_reg=100),
        dict(tp=10, sl=2.0, trail=6.0, mh=30), 0.05, 3.0),
]

PARAM_GRID = {
    "BBBreak_LS":   dict(n=[30, 45, 60, 90], k=[1.5, 2.0, 2.5], regime_len=[75, 150, 225, 600]),
    "HTF_Donchian": dict(donch_n=[10, 20, 40], ema_reg=[100, 200]),
}


def build_signal(family, df, p, tf):
    if family == "BBBreak_LS":
        l = sig_bbbreak(df, n=p["n"], k=p["k"], regime_len=p["regime_len"])
        s = sig_bbbreak_short(df, n=p["n"], k=p["k"], regime_len=p["regime_len"])
        return l, s
    if family == "HTF_Donchian":
        return sig_htf_donchian(df, donch_n=p["donch_n"], ema_reg=p["ema_reg"])
    raise ValueError(family)


def run_sim(df, lsig, ssig, exits, risk, lev, lbl):
    ls = dedupe(lsig); ss = dedupe(ssig) if ssig is not None else None
    trades, eq = simulate(df, ls, short_entries=ss,
                          tp_atr=exits["tp"], sl_atr=exits["sl"],
                          trail_atr=exits["trail"], max_hold=exits["mh"],
                          risk_per_trade=risk, leverage_cap=lev, fee=FEE)
    return metrics(lbl, eq, trades), trades, eq


def per_year_breakdown(eq):
    rows = []
    eq = eq.dropna()
    if len(eq) < 30: return pd.DataFrame()
    eq.index = pd.to_datetime(eq.index, utc=True)
    for y in range(2020, 2027):
        s = pd.Timestamp(f"{y}-01-01", tz="UTC"); e = pd.Timestamp(f"{y+1}-01-01", tz="UTC")
        sub = eq[(eq.index >= s) & (eq.index < e)]
        if len(sub) < 50: continue
        ret = sub.iloc[-1] / sub.iloc[0] - 1
        days = (sub.index[-1] - sub.index[0]).total_seconds() / 86400
        cagr = (1 + ret) ** (365.25 / max(days, 1)) - 1 if days > 0 else 0
        daily = sub.resample("1D").last().dropna().pct_change().dropna()
        sh = (daily.mean() / daily.std()) * np.sqrt(365) if daily.std() > 0 else 0
        dd = ((sub / sub.cummax()) - 1).min()
        rows.append(dict(year=y, cagr=round(cagr*100, 1), sharpe=round(sh, 2),
                         dd=round(dd*100, 1), log_ret=round(np.log(sub.iloc[-1]/sub.iloc[0]), 3)))
    return pd.DataFrame(rows)


def neighbors(family, base):
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


def random_entry_null(df, real_lsig, real_ssig, exits, risk, lev, n_trials=80, seed=42):
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


def mc_bootstrap_monthly(eq, n_iters=1000, seed=42):
    eq = eq.dropna()
    if len(eq) < 60: return None
    eq.index = pd.to_datetime(eq.index, utc=True)
    monthly = eq.resample("1ME").last().dropna().pct_change().dropna()
    if len(monthly) < 12: return None
    rng = np.random.default_rng(seed)
    cagrs = []; sharpes = []
    for _ in range(n_iters):
        sample = rng.choice(monthly.values, size=len(monthly), replace=True)
        gross = np.prod(1 + sample)
        yrs = len(sample) / 12
        cagrs.append(gross ** (1 / max(yrs, 1e-6)) - 1)
        sd = sample.std()
        sharpes.append((sample.mean() / sd) * np.sqrt(12) if sd > 0 else 0)
    return dict(
        cagr_p5=np.percentile(cagrs, 5), cagr_p50=np.percentile(cagrs, 50),
        cagr_p95=np.percentile(cagrs, 95),
        sh_p5=np.percentile(sharpes, 5), sh_p50=np.percentile(sharpes, 50),
        sh_p95=np.percentile(sharpes, 95),
    )


def deflated_sharpe(actual_sh, n_trials, n_obs):
    if actual_sh is None or np.isnan(actual_sh): return None, None
    psr = stats.norm.cdf(actual_sh * np.sqrt(n_obs - 1))
    emc = 0.5772
    z_n = (1 - emc) * stats.norm.ppf(1 - 1/n_trials) + emc * stats.norm.ppf(1 - 1/(n_trials*np.e))
    sh_ref = z_n / np.sqrt(n_obs)
    dsr = stats.norm.cdf((actual_sh - sh_ref) * np.sqrt(n_obs - 1))
    return psr, dsr


def main():
    N_TRIALS = 2000  # rough count for V23 + V27 sweeps combined
    summary = []

    for label, sym, family, tf, params, exits, risk, lev in AUDIT:
        print(f"\n{'='*70}\n  {label}\n{'='*70}", flush=True)
        df = _load(sym, tf)
        if df is None:
            print("  NO DATA"); continue

        try:
            lsig, ssig = build_signal(family, df, params, tf)
        except Exception as e:
            print(f"  SIGNAL ERR: {e}"); continue
        r, trades, eq = run_sim(df, lsig, ssig, exits, risk, lev, label)
        actual_cagr = r["cagr_net"]; actual_sh = r["sharpe"]; actual_n = r["n"]
        n_daily = len(eq.resample("1D").last().dropna())
        print(f"  Real: CAGR={actual_cagr*100:+.1f}%  Sh={actual_sh:+.2f}  n={actual_n}")

        py = per_year_breakdown(eq)
        print(f"\n  PER-YEAR:")
        print(py.to_string(index=False) if not py.empty else "  (no years)")
        neg_years = (py["cagr"] < -10).sum() if not py.empty else 0
        if not py.empty:
            lr = py["log_ret"].fillna(0)
            max_year_share = (lr.abs().max() / lr.abs().sum()) if lr.abs().sum() > 0 else 0
        else:
            max_year_share = 0

        pl = plateau_test(df, family, params, tf, exits, risk, lev)
        n_neighbors = len(pl)
        n_pos = sum(1 for x in pl if x["cagr"] > 0 and x["sharpe"] > 0.3)
        plateau_pct = n_pos / max(n_neighbors, 1) * 100
        print(f"\n  PLATEAU: {n_pos}/{n_neighbors} neighbors positive  ({plateau_pct:.0f}%)")
        for x in pl[:6]:
            print(f"    p={x['params']}  CAGR={x['cagr']*100:+.1f}%  Sh={x['sharpe']:+.2f}")

        null_shs = random_entry_null(df, lsig, ssig, exits, risk, lev, n_trials=80)
        if null_shs is not None:
            null_shs = null_shs[~np.isnan(null_shs)]
            pct = (null_shs < actual_sh).sum() / len(null_shs) * 100 if len(null_shs) else 0
            null_mean = float(np.mean(null_shs)) if len(null_shs) else 0
            null_p95 = float(np.percentile(null_shs, 95)) if len(null_shs) else 0
            print(f"\n  RANDOM-ENTRY NULL: actual Sh {actual_sh:+.2f} vs null mean {null_mean:+.2f}, p95 {null_p95:+.2f}")
            print(f"                     actual beats {pct:.0f}% of null trials")
        else:
            pct = None; null_mean = None

        mc = mc_bootstrap_monthly(eq)
        if mc:
            print(f"\n  MC BOOTSTRAP:")
            print(f"    CAGR  5%={mc['cagr_p5']*100:+6.1f}%   50%={mc['cagr_p50']*100:+6.1f}%   95%={mc['cagr_p95']*100:+6.1f}%")
            print(f"    Sh    5%={mc['sh_p5']:+.2f}          50%={mc['sh_p50']:+.2f}          95%={mc['sh_p95']:+.2f}")

        psr, dsr = deflated_sharpe(actual_sh, N_TRIALS, n_daily)
        print(f"\n  DSR: PSR={psr:.3f}  DSR={dsr:.3f}  (N_trials≈{N_TRIALS}, N_obs(daily)={n_daily})")

        summary.append(dict(
            label=label, real_CAGR=round(actual_cagr*100, 1), real_Sh=round(actual_sh, 2),
            neg_yrs=neg_years, max_yr_share=round(max_year_share, 2),
            plateau_pct=round(plateau_pct, 0),
            null_pct=round(pct, 0) if pct is not None else None,
            null_mean=round(null_mean, 2) if null_mean is not None else None,
            mc_CAGR_p5=round(mc["cagr_p5"]*100, 1) if mc else None,
            mc_Sh_p5=round(mc["sh_p5"], 2) if mc else None,
            PSR=round(psr, 3) if psr else None,
            DSR=round(dsr, 3) if dsr else None,
        ))

    df = pd.DataFrame(summary)
    df.to_csv(OUT / "v32_core_audit.csv", index=False)
    print(f"\n\n{'='*100}\nV32 CORE AUDIT — SUMMARY\n{'='*100}")
    pd.set_option('display.width', 200); pd.set_option('display.max_colwidth', 32)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
