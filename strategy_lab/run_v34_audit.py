"""V34 audit — 5-test overfit suite on V34 top candidates."""
from __future__ import annotations
import sys, pickle, warnings, math, time
warnings.filterwarnings("ignore")
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import simulate, metrics
from strategy_lab.run_v34_expand import (
    _load, FEE, SINCE, LEV,
    sig_bbbreak_ls, sig_htf_donchian_ls, sig_pair_ratio_revert,
    scaled,
)

OUT = Path(__file__).resolve().parent / "results" / "v34"
SPLIT = pd.Timestamp("2024-01-01", tz="UTC")
N_TRIALS_V34 = 1264

def build_signal(family, df, extras, params, tf):
    if family == "BBBreak_LS":
        p = dict(params)
        p["regime_len"] = scaled(p["regime_len"], tf)
        p["n"] = scaled(p["n"], tf)
        return sig_bbbreak_ls(df, **p)
    if family == "HTF_Donchian":
        return sig_htf_donchian_ls(df, **params)
    if family == "Pair_Ratio":
        return sig_pair_ratio_revert(df, extras, **params)
    raise ValueError(family)


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
    return metrics("IS", is_eq, is_tr), metrics("OOS", oos_eq, oos_tr)


def per_year_breakdown(eq):
    y = pd.DataFrame({"eq": eq.values}, index=eq.index)
    y["year"] = y.index.year
    rows = []
    for yr, g in y.groupby("year"):
        if len(g) < 5: continue
        rets = g["eq"].pct_change().dropna()
        cagr = (g["eq"].iloc[-1] / g["eq"].iloc[0]) ** (365 / max(1, (g.index[-1] - g.index[0]).days)) - 1
        sh = rets.mean() / rets.std() * math.sqrt(365 * 6) if rets.std() > 0 else 0
        dd = float((g["eq"] / g["eq"].cummax() - 1).min())
        lr = math.log(max(g["eq"].iloc[-1] / g["eq"].iloc[0], 1e-9))
        rows.append(dict(year=int(yr), cagr=round(cagr * 100, 1),
                         sharpe=round(sh, 2), dd=round(dd * 100, 1), log_ret=round(lr, 3)))
    return pd.DataFrame(rows)


PARAM_GRIDS = {
    "BBBreak_LS":   {"n": [30, 45, 90, 180], "k": [1.5, 2.0, 2.5], "regime_len": [150, 300, 600, 900]},
    "HTF_Donchian": {"donch_n": [10, 20, 30, 40], "ema_reg": [100, 200]},
    "Pair_Ratio":   {"z_lookback": [50, 100, 200], "z_thr": [1.5, 2.0, 2.5, 3.0]},
}


def neighbors(family, base):
    grid = PARAM_GRIDS[family]
    out = [dict(base)]
    for k in base:
        if k not in grid: continue
        vals = grid[k]
        # Find closest index (for BBBreak, base stores unscaled value)
        try:
            idx = vals.index(base[k])
        except ValueError:
            # find closest
            idx = min(range(len(vals)), key=lambda i: abs(vals[i] - base[k]))
        for step in (-1, 1):
            ni = idx + step
            if 0 <= ni < len(vals):
                n = dict(base); n[k] = vals[ni]
                if n != base: out.append(n)
    seen, uniq = set(), []
    for n in out:
        t = tuple(sorted(n.items()))
        if t not in seen:
            seen.add(t); uniq.append(n)
    return uniq


def plateau_test(df, extras, family, base_params, tf, exits, risk, lev):
    neighs = neighbors(family, base_params)
    results = []
    for p in neighs:
        try:
            ls, ss = build_signal(family, df, extras, p, tf)
            tr, eq = simulate(df, ls, ss,
                              tp_atr=exits["tp"], sl_atr=exits["sl"],
                              trail_atr=exits["trail"], max_hold=exits["mh"],
                              risk_per_trade=risk, leverage_cap=lev, fee=FEE)
            m = metrics("p", eq, tr)
            results.append(dict(params=p, cagr=m["cagr_net"], sharpe=m["sharpe"]))
        except Exception:
            continue
    n_pos = sum(1 for r in results if r["cagr"] > 0 and r["sharpe"] > 0.3)
    return n_pos, len(results)


def random_entry_null(df, real_ls, real_ss, exits, risk, lev, n_trials=60, seed=42):
    rng = np.random.default_rng(seed)
    n_long = int(real_ls.sum()); n_short = int(real_ss.sum())
    N = len(df)
    shs = []
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
        shs.append(m["sharpe"])
    return np.array(shs)


def mc_bootstrap(eq, n_iters=500, seed=42):
    rng = np.random.default_rng(seed)
    rets = eq.resample("M").last().pct_change().dropna().values
    if len(rets) < 6:
        return dict(cagr_p5=np.nan, cagr_p50=np.nan, cagr_p95=np.nan)
    cagrs = []
    for _ in range(n_iters):
        sample = rng.choice(rets, size=len(rets), replace=True)
        mu = sample.mean()
        cagrs.append((1 + mu) ** 12 - 1)
    return dict(cagr_p5=round(np.percentile(cagrs, 5) * 100, 1),
                cagr_p50=round(np.percentile(cagrs, 50) * 100, 1),
                cagr_p95=round(np.percentile(cagrs, 95) * 100, 1))


def deflated_sharpe(actual_sh, n_trials, n_obs):
    """López de Prado DSR. actual_sh is annualized; n_obs is # daily return
    observations. The z-score form: z = (actual - max_expected_annualized)*sqrt(T-1).
    max_expected_annualized = max_of_N_normals / sqrt(T-1)."""
    from scipy.stats import norm
    if n_obs <= 1 or n_trials <= 1: return 1.0, 1.0
    em_c = 0.5772
    sh_max_z = math.sqrt(2 * math.log(n_trials)) * (1 - em_c) + em_c * norm.ppf(1 - 1 / (n_trials * math.e))
    # Convert z-max to annualized-Sharpe-max
    sh_max_annual = sh_max_z / math.sqrt(n_obs - 1)
    # z-score using T-1 (n_obs is days; Sharpe is annualized daily Sh)
    psr_z = actual_sh * math.sqrt(n_obs - 1)
    dsr_z = (actual_sh - sh_max_annual) * math.sqrt(n_obs - 1)
    return round(float(norm.cdf(psr_z)), 3), round(float(norm.cdf(dsr_z)), 3)


# Top V34 candidates to audit (by score)
CANDIDATES = [
    ("AVAX BBBreak_LS 4h",       "AVAXUSDT_BBBreak_LS_4h",       None),
    ("SUI HTF_Donchian 4h",      "SUIUSDT_HTF_Donchian_4h",      None),
    ("TON BBBreak_LS 4h",        "TONUSDT_BBBreak_LS_4h",        None),
    ("TON HTF_Donchian 4h",      "TONUSDT_HTF_Donchian_4h",      None),
    ("AVAX HTF_Donchian 4h",     "AVAXUSDT_HTF_Donchian_4h",     None),
    ("LINK BBBreak_LS 4h",       "LINKUSDT_BBBreak_LS_4h",       None),
    ("LINK HTF_Donchian 4h",     "LINKUSDT_HTF_Donchian_4h",     None),
    ("DOGE/SOL PairRatio 4h",    "DOGEUSDT_SOLUSDT_PairRatio_4h","SOLUSDT"),
    ("INJ/ETH PairRatio 4h",     "INJUSDT_ETHUSDT_PairRatio_4h", "ETHUSDT"),
]


def main():
    results = pickle.load(open(OUT / "v34_sweep_results.pkl", "rb"))
    summary = []
    t0 = time.time()
    print(f"\n{'='*70}\nV34 — IS/OOS + OVERFIT AUDIT\n{'='*70}")

    for label, key, other_sym in CANDIDATES:
        if key not in results:
            print(f"  {label}: NOT FOUND"); continue
        w = results[key]
        sym = w["sym"]; family = w["family"]; tf = w["tf"]
        params = w["params"]; exits = w["exits"]; risk = w["risk"]; lev = w["lev"]
        df = _load(sym, tf)
        extras = _load(other_sym, tf) if other_sym else None

        print(f"\n{'='*70}\n  {label}\n{'='*70}")
        print(f"  Params={params}  Exits={exits}  Risk={risk}")
        print(f"  Sweep: CAGR={w['cagr_net']*100:+.1f}%  Sh={w['sharpe']:+.2f}  n={w['n']}")

        ls, ss = build_signal(family, df, extras, params, tf)
        # Guard IS/OOS slice for coins with no pre-split data (TON)
        is_mask = df.index < SPLIT
        if is_mask.sum() < 50:
            print(f"  (Insufficient IS data — {is_mask.sum()} bars before {SPLIT.date()}, "
                  f"treating as OOS-only)")
            is_m = dict(n=0, cagr_net=0, sharpe=0, dd=0)
            full_tr, full_eq = simulate(df, ls, ss,
                                        tp_atr=exits["tp"], sl_atr=exits["sl"],
                                        trail_atr=exits["trail"], max_hold=exits["mh"],
                                        risk_per_trade=risk, leverage_cap=lev, fee=FEE)
            oos_m = metrics("OOS", full_eq, full_tr)
            oos_pass = oos_m["sharpe"] >= 0.6  # stand-alone threshold
        else:
            is_m, oos_m = slice_metrics(df, ls, ss, exits, risk, lev)
            oos_pass = oos_m["sharpe"] >= 0.5 * max(0.1, is_m["sharpe"])
        print(f"  IS  n={is_m['n']:3d}  CAGR={is_m['cagr_net']*100:+6.1f}%  Sh={is_m['sharpe']:+.2f}")
        print(f"  OOS n={oos_m['n']:3d}  CAGR={oos_m['cagr_net']*100:+6.1f}%  Sh={oos_m['sharpe']:+.2f}")

        tr_full, eq_full = simulate(df, ls, ss,
                                    tp_atr=exits["tp"], sl_atr=exits["sl"],
                                    trail_atr=exits["trail"], max_hold=exits["mh"],
                                    risk_per_trade=risk, leverage_cap=lev, fee=FEE)
        yr = per_year_breakdown(eq_full)
        print(f"  PER-YEAR:"); print(yr.to_string(index=False))
        total_lr = yr["log_ret"].sum() if len(yr) else 0
        max_share = yr["log_ret"].abs().max() / abs(total_lr) if total_lr != 0 else 1.0
        neg_yrs = int((yr["cagr"] < 0).sum())

        n_pos, n_total = plateau_test(df, extras, family, params, tf, exits, risk, lev)
        plateau_pct = 100.0 * n_pos / max(1, n_total)
        null_shs = random_entry_null(df, ls, ss, exits, risk, lev, n_trials=50)
        actual_sh = w["sharpe"]
        null_pct = 100.0 * (actual_sh > null_shs).mean()
        mc = mc_bootstrap(eq_full)
        n_obs_daily = int((eq_full.index[-1] - eq_full.index[0]).days)
        psr, dsr = deflated_sharpe(w["sharpe"], N_TRIALS_V34, n_obs_daily)

        print(f"  PLATEAU: {n_pos}/{n_total}={plateau_pct:.0f}%  NULL: {null_pct:.0f}%  "
              f"MC p5={mc['cagr_p5']}%  DSR={dsr}")

        pass_plateau = plateau_pct >= 60
        pass_null = null_pct >= 80
        pass_dsr = dsr >= 0.9
        pass_yrs = neg_yrs <= 3 and max_share <= 0.5  # slightly relaxed for longer histories
        robust = oos_pass and pass_plateau and pass_null and pass_dsr and pass_yrs
        verdict = "ROBUST" if robust else ("FRAGILE" if (pass_plateau + pass_null + pass_dsr) >= 2 else "OVERFIT")
        print(f"  VERDICT: {verdict}  (oos={oos_pass} plateau={pass_plateau} "
              f"null={pass_null} dsr={pass_dsr} yrs={pass_yrs})")

        summary.append(dict(
            label=label, cagr=round(w["cagr_net"]*100,1), sh=round(w["sharpe"],2),
            is_sh=round(is_m["sharpe"],2), oos_sh=round(oos_m["sharpe"],2),
            oos_cagr=round(oos_m["cagr_net"]*100,1),
            neg_yrs=neg_yrs, max_yr_share=round(max_share,2),
            plateau_pct=round(plateau_pct,1), null_pct=round(null_pct,1),
            mc_p5=mc["cagr_p5"], psr=psr, dsr=dsr, verdict=verdict,
        ))

    print(f"\n{'='*80}\nSUMMARY\n{'='*80}")
    s = pd.DataFrame(summary)
    print(s.to_string(index=False))
    s.to_csv(OUT / "v34_audit.csv", index=False)
    print(f"\nSaved: {OUT/'v34_audit.csv'}  ({time.time()-t0:.1f}s)")


if __name__ == "__main__":
    main()
