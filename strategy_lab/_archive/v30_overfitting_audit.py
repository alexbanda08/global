"""
V30 — Overfitting audit.

Five complementary tests on top candidate strategies:

  1. Per-year breakdown        — edge evenly distributed or carried by one year?
  2. Parameter plateau         — perturb ±1 grid step; robust winner sits in a plateau
  3. Randomized-entry null     — replace signals with random timestamps at same frequency
  4. Monte-Carlo bootstrap     — resample monthly returns 1000× with replacement
  5. Deflated Sharpe           — correct for multiple-testing bias (we picked best of ~N configs)

Strategies audited:
  A. V15 BALANCED     (k=4, lb=14d, rb=7d, lev=1×, BTC 100d-MA filter)         — our established champion
  B. V24 MULTI-FILTER (k=4, lb=14d, rb=7d, lev=1×, triple bear filter)         — new low-DD candidate
  C. V27 L/S DEFENSIVE (k=2, b=2, lb=14d, rb=7d, lev=0.5×)                     — long-short safest

Outputs:
  strategy_lab/results/v30_overfitting.json
  strategy_lab/results/v30_test{N}_*.csv
"""
from __future__ import annotations
import json
import itertools
from pathlib import Path
import numpy as np
import pandas as pd

from strategy_lab.v23_low_dd_xsm import low_dd_xsm, load_all, build_panel
from strategy_lab.v29_long_short_deep import long_short_backtest

OUT = Path(__file__).resolve().parent / "results"
RNG = np.random.default_rng(42)
INIT = 10_000.0
BPY = 365.25 * 24 / 4
BARS_PER_DAY = 6


def metrics(eq: pd.Series) -> dict:
    if len(eq) < 50 or eq.iloc[-1] <= 0:
        return {"cagr": 0.0, "sharpe": 0.0, "dd": 0.0, "calmar": 0.0, "final": 0.0}
    rets = eq.pct_change(fill_method=None).fillna(0)
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 0.01)) - 1
    sh = (rets.mean() * BPY) / (rets.std() * np.sqrt(BPY) + 1e-12)
    dd = float((eq / eq.cummax() - 1).min())
    return {"cagr": float(cagr), "sharpe": float(sh), "dd": dd,
            "calmar": cagr / abs(dd) if dd < 0 else 0.0,
            "final": float(eq.iloc[-1])}


def run_strategy(data, name, **kw):
    """Unified runner: dispatches to low_dd_xsm or long_short_backtest."""
    if name == "V15_BALANCED":
        return low_dd_xsm(data, mode="baseline",
                          lookback_days=kw.get("lb", 14), top_k=kw.get("k", 4),
                          rebal_days=kw.get("rb", 7), leverage=kw.get("lev", 1.0),
                          btc_ma_days=kw.get("btc_ma", 100))[0]
    elif name == "V24_MF":
        return low_dd_xsm(data, mode="multi_filter",
                          lookback_days=kw.get("lb", 14), top_k=kw.get("k", 4),
                          rebal_days=kw.get("rb", 7), leverage=kw.get("lev", 1.0),
                          btc_ma_days=kw.get("btc_ma", 100),
                          mf_breadth_min=kw.get("breadth", 5),
                          mf_btc_ma_fast=kw.get("ma_fast", 50))[0]
    elif name == "V27_LS":
        return long_short_backtest(data, lookback_days=kw.get("lb", 14),
                                    top_k=kw.get("k", 2), bottom_k=kw.get("b", 2),
                                    rebal_days=kw.get("rb", 7),
                                    leverage=kw.get("lev", 0.5))[0]
    raise ValueError(name)


# ---------------------------------------------------------------------
# TEST 1 — Per-year breakdown
# ---------------------------------------------------------------------
def test1_yearly(eq: pd.Series) -> dict:
    rets_all = eq.pct_change(fill_method=None).fillna(0)
    years = sorted(set(eq.index.year))
    yearly = []
    for y in years:
        s = pd.Timestamp(f"{y}-01-01", tz="UTC")
        e = pd.Timestamp(f"{y+1}-01-01", tz="UTC")
        sub = eq[(eq.index >= s) & (eq.index < e)]
        if len(sub) < 20: continue
        ret = sub.iloc[-1] / sub.iloc[0] - 1
        dd = float((sub / sub.cummax() - 1).min())
        sub_rets = sub.pct_change(fill_method=None).fillna(0)
        sh = (sub_rets.mean() * BPY) / (sub_rets.std() * np.sqrt(BPY) + 1e-12)
        yearly.append({"year": y, "ret": float(ret), "dd": dd, "sharpe": float(sh)})
    if not yearly:
        return {}
    yrets = np.array([y["ret"] for y in yearly])
    pos = (yrets > 0).mean()
    # Concentration: max|yearly PNL| / sum|yearly PNL|
    concentration = float(np.max(np.abs(yrets)) / (np.sum(np.abs(yrets)) + 1e-12))
    return {
        "yearly": yearly,
        "n_years": len(yearly),
        "pct_positive_years": float(pos),
        "best_year_contribution": concentration,
        "yearly_sharpe_std": float(np.std([y["sharpe"] for y in yearly])),
    }


# ---------------------------------------------------------------------
# TEST 2 — Parameter plateau
# ---------------------------------------------------------------------
def test2_param_plateau(data, name: str, base: dict,
                        deltas: dict) -> dict:
    base_eq = run_strategy(data, name, **base)
    base_m = metrics(base_eq)
    rows = [{"label": "BASE", **base, **base_m}]
    for p, variants in deltas.items():
        for v in variants:
            kw = {**base, p: v}
            try:
                eq = run_strategy(data, name, **kw)
                m = metrics(eq)
            except Exception as e:
                m = {"cagr":0,"sharpe":0,"dd":0,"calmar":0,"final":0}
            rows.append({"label": f"{p}={v}", **kw, **m})
    df = pd.DataFrame(rows)
    # Percentage of neighbors within 30% of base Sharpe AND positive
    sh_base = base_m["sharpe"]
    nbrs = df[df["label"] != "BASE"]
    if sh_base > 0:
        within = ((nbrs["sharpe"] > 0.7 * sh_base) & (nbrs["sharpe"] < 1.3 * sh_base)).mean()
    else:
        within = 0.0
    pos = (nbrs["sharpe"] > 0).mean()
    # Spread
    sh_std = float(nbrs["sharpe"].std())
    return {
        "base_sharpe": sh_base,
        "neighbor_sharpe_std": sh_std,
        "pct_in_30pct_plateau": float(within),
        "pct_positive_neighbors": float(pos),
        "table": df.to_dict(orient="records"),
    }


# ---------------------------------------------------------------------
# TEST 3 — Randomized-entry null
# ---------------------------------------------------------------------
def test3_random_null(data, name: str, base: dict, n_sims: int = 100) -> dict:
    """
    Replace the rank-based pick with a RANDOM pick at the same frequency.
    Builds a null distribution of Sharpe ratios.
    """
    close, open_, idx = build_panel(data)
    n = len(idx)
    lookback_bars = base.get("lb", 14) * BARS_PER_DAY
    step = base.get("rb", 7) * BARS_PER_DAY
    k = base.get("k", 4)
    lev = base.get("lev", 1.0)
    fee = 0.00015

    # Eligible coin mask per bar
    coins = list(close.columns)
    starts = {s: pd.Timestamp(s_data, tz="UTC") for s, s_data in {
        "BTCUSDT":"2018-01-01","ETHUSDT":"2018-01-01","BNBUSDT":"2018-01-01",
        "XRPUSDT":"2018-06-01","ADAUSDT":"2018-06-01",
        "LINKUSDT":"2019-03-01","DOGEUSDT":"2019-09-01",
        "SOLUSDT":"2020-10-01","AVAXUSDT":"2020-11-01",
    }.items()}

    null_sharpes = []
    for sim in range(n_sims):
        rng = np.random.default_rng(1000 + sim)
        equity = np.empty(n); equity[0] = INIT
        cash = INIT
        positions = {s: 0.0 for s in coins}
        for i in range(n):
            mv = sum(positions[s] * close.iloc[i][s] for s in positions
                     if not np.isnan(close.iloc[i][s]))
            eq = cash + mv
            equity[i] = eq
            if i < lookback_bars or (i - lookback_bars) % step != 0:
                continue
            # Random pick
            eligible = [s for s in coins if idx[i] >= starts[s]
                        and not np.isnan(close.iloc[i][s])]
            if len(eligible) < k + 1: continue
            picks = list(rng.choice(eligible, size=k, replace=False))
            targets = {s: 0.0 for s in coins}
            w = lev / k
            for s in picks: targets[s] = w
            # Rebalance
            for s in coins:
                target_notional = eq * targets[s]
                px = open_.iloc[min(i+1, n-1)][s]
                if np.isnan(px): continue
                target_shares = target_notional / px
                diff = target_shares - positions[s]
                if abs(diff) * px < 0.005 * eq: continue
                gross = diff * px
                feeu = abs(gross) * fee
                cash -= gross + feeu
                positions[s] = target_shares
        eq_s = pd.Series(equity, index=idx)
        if eq_s.iloc[-1] > 0:
            rets = eq_s.pct_change(fill_method=None).fillna(0)
            sh = (rets.mean() * BPY) / (rets.std() * np.sqrt(BPY) + 1e-12)
            null_sharpes.append(float(sh))

    null_sharpes = np.array(null_sharpes)
    base_eq = run_strategy(data, name, **base)
    base_sh = metrics(base_eq)["sharpe"]
    p_value = float((null_sharpes >= base_sh).mean())
    return {
        "base_sharpe": float(base_sh),
        "null_mean":   float(null_sharpes.mean()),
        "null_std":    float(null_sharpes.std()),
        "null_p95":    float(np.quantile(null_sharpes, 0.95)),
        "null_p99":    float(np.quantile(null_sharpes, 0.99)),
        "null_max":    float(null_sharpes.max()),
        "p_value":     p_value,
        "n_sims":      len(null_sharpes),
    }


# ---------------------------------------------------------------------
# TEST 4 — Monte Carlo bootstrap on monthly returns
# ---------------------------------------------------------------------
def test4_mc_bootstrap(eq: pd.Series, n_sims: int = 1000) -> dict:
    # Monthly returns
    monthly = eq.resample("1ME").last().pct_change(fill_method=None).dropna()
    if len(monthly) < 12:
        return {"error": "need >= 12 months"}
    mvals = monthly.values
    n_months = len(mvals)

    rng = np.random.default_rng(42)
    final_cagrs = []
    max_dds = []
    for _ in range(n_sims):
        sample = rng.choice(mvals, size=n_months, replace=True)
        cum = np.cumprod(1 + sample)
        final = cum[-1]
        dd = float(np.min(cum / np.maximum.accumulate(cum) - 1))
        cagr = final ** (12 / n_months) - 1
        final_cagrs.append(cagr)
        max_dds.append(dd)
    return {
        "n_months_sampled": n_months,
        "n_sims": n_sims,
        "cagr_p5":  float(np.quantile(final_cagrs, 0.05)),
        "cagr_p25": float(np.quantile(final_cagrs, 0.25)),
        "cagr_p50": float(np.quantile(final_cagrs, 0.50)),
        "cagr_p75": float(np.quantile(final_cagrs, 0.75)),
        "cagr_p95": float(np.quantile(final_cagrs, 0.95)),
        "dd_p5":    float(np.quantile(max_dds, 0.05)),
        "dd_p50":   float(np.quantile(max_dds, 0.50)),
        "dd_p95":   float(np.quantile(max_dds, 0.95)),
        "prob_cagr_positive": float((np.array(final_cagrs) > 0).mean()),
        "prob_cagr_over_50pct": float((np.array(final_cagrs) > 0.5).mean()),
    }


# ---------------------------------------------------------------------
# TEST 5 — Deflated Sharpe
# ---------------------------------------------------------------------
def test5_deflated_sharpe(sharpe: float, n_trials: int, n_years: float,
                          bars_per_year: float = BPY) -> dict:
    """
    Bailey & Lopez de Prado (2014) deflated Sharpe approximation.
    Simpler form: PSR = Prob[SR > sqrt(ln(N)) * sigma_SR], where
    sigma_SR ≈ sqrt((1 + 0.5*SR^2) / T_eff) with T_eff = n_years * ~20 obs/yr.

    We compute a back-of-envelope deflated Sharpe:
        SR_deflated = SR - sqrt(2 * ln(N) / T_eff)
    """
    T_eff = n_years * 12   # monthly proxy
    expected_max = np.sqrt(2 * np.log(max(n_trials, 2))) * np.sqrt(1.0 / T_eff)
    # proper DSR involves skew/kurt; we use simplified form
    sr_deflated = sharpe - expected_max
    # probability-of-genuine-edge via normal approximation
    sr_std = np.sqrt((1 + 0.5 * sharpe**2) / T_eff)
    z = sr_deflated / sr_std if sr_std > 0 else 0
    # Normal CDF approximation via erf
    from math import erf, sqrt
    p_genuine = 0.5 * (1 + erf(z / sqrt(2)))
    return {
        "raw_sharpe":       sharpe,
        "n_trials":         n_trials,
        "T_eff_months":     T_eff,
        "expected_max_from_N": float(expected_max),
        "deflated_sharpe":  float(sr_deflated),
        "prob_genuine_edge": float(p_genuine),
    }


# ---------------------------------------------------------------------
# Orchestrate
# ---------------------------------------------------------------------
def main():
    data = load_all()

    strategies = [
        {"id": "A_V15_BALANCED_1x", "name": "V15_BALANCED",
         "params": {"lb": 14, "k": 4, "rb": 7, "lev": 1.0},
         "deltas": {"lb": [7, 21, 28], "k": [3, 5], "rb": [3, 14], "lev": [0.5, 1.5]}},
        {"id": "B_V24_MF_1x", "name": "V24_MF",
         "params": {"lb": 14, "k": 4, "rb": 7, "lev": 1.0, "breadth": 5},
         "deltas": {"lb": [7, 21], "k": [3, 5], "rb": [3, 14], "lev": [0.5, 1.5], "breadth": [4, 6]}},
        {"id": "C_V27_LS_DEFENSIVE", "name": "V27_LS",
         "params": {"lb": 14, "k": 2, "b": 2, "rb": 7, "lev": 0.5},
         "deltas": {"lb": [7, 21], "k": [1, 3], "b": [1, 3], "rb": [3, 14], "lev": [1.0]}},
    ]

    results = {}
    for s in strategies:
        print(f"\n================= {s['id']} =================", flush=True)
        eq = run_strategy(data, s["name"], **s["params"])
        base_m = metrics(eq)
        print(f"  BASE: CAGR {base_m['cagr']*100:+.1f}%  Sh {base_m['sharpe']:+.2f}  "
              f"DD {base_m['dd']*100:+.1f}%  Final ${base_m['final']:,.0f}", flush=True)

        print("  [1/5] per-year breakdown ...", flush=True)
        t1 = test1_yearly(eq)
        print(f"    positive years {t1.get('pct_positive_years',0)*100:.0f}%  "
              f"best-year concentration {t1.get('best_year_contribution',0)*100:.0f}%  "
              f"yearly Sharpe stdev {t1.get('yearly_sharpe_std',0):.2f}", flush=True)

        print("  [2/5] parameter plateau ...", flush=True)
        t2 = test2_param_plateau(data, s["name"], s["params"], s["deltas"])
        print(f"    {t2['pct_in_30pct_plateau']*100:.0f}% of neighbors within 30% of base Sharpe  "
              f"({t2['pct_positive_neighbors']*100:.0f}% positive)", flush=True)
        pd.DataFrame(t2["table"]).to_csv(OUT/f"v30_test2_{s['id']}.csv", index=False)

        print("  [3/5] random-entry null (100 sims) ...", flush=True)
        t3 = test3_random_null(data, s["name"], s["params"], n_sims=100)
        print(f"    base Sh {t3['base_sharpe']:+.2f}  null mean {t3['null_mean']:+.2f}  "
              f"null p95 {t3['null_p95']:+.2f}  p-value {t3['p_value']:.3f}", flush=True)

        print("  [4/5] monthly-bootstrap (1000 sims) ...", flush=True)
        t4 = test4_mc_bootstrap(eq, n_sims=1000)
        print(f"    CAGR p5/p50/p95 = {t4['cagr_p5']*100:+.1f}% / "
              f"{t4['cagr_p50']*100:+.1f}% / {t4['cagr_p95']*100:+.1f}%  "
              f"DD p50 {t4['dd_p50']*100:+.1f}%  "
              f"prob CAGR > 0 = {t4['prob_cagr_positive']*100:.0f}%", flush=True)

        print("  [5/5] deflated Sharpe (N=200 configs tested) ...", flush=True)
        yrs = (eq.index[-1] - eq.index[0]).days / 365.25
        t5 = test5_deflated_sharpe(base_m["sharpe"], n_trials=200, n_years=yrs)
        print(f"    SR {t5['raw_sharpe']:+.2f} -> deflated {t5['deflated_sharpe']:+.2f}  "
              f"(probability genuine edge: {t5['prob_genuine_edge']*100:.0f}%)", flush=True)

        results[s["id"]] = {
            "base_metrics": base_m,
            "test1_yearly": t1,
            "test2_plateau": t2,
            "test3_random_null": t3,
            "test4_bootstrap": t4,
            "test5_deflated_sharpe": t5,
            "params": s["params"],
        }

    (OUT/"v30_overfitting.json").write_text(json.dumps(results, indent=2, default=str))
    print("\nSaved v30_overfitting.json")

    # Summary table
    print("\n=============== SUMMARY ===============")
    hdr = ["Strategy", "SR", "SR deflated", "p-value", "% plateau", "% yrs +", "MC p5 CAGR", "verdict"]
    print(" | ".join(f"{h:<14}" for h in hdr))
    for sid, r in results.items():
        verdict = "ROBUST" if (
            r["test3_random_null"]["p_value"] < 0.05 and
            r["test5_deflated_sharpe"]["prob_genuine_edge"] > 0.80 and
            r["test2_plateau"]["pct_in_30pct_plateau"] > 0.40 and
            r["test4_bootstrap"]["prob_cagr_positive"] > 0.80
        ) else "FRAGILE"
        row = [
            sid[:14],
            f"{r['base_metrics']['sharpe']:+.2f}",
            f"{r['test5_deflated_sharpe']['deflated_sharpe']:+.2f}",
            f"{r['test3_random_null']['p_value']:.3f}",
            f"{r['test2_plateau']['pct_in_30pct_plateau']*100:.0f}%",
            f"{r['test1_yearly'].get('pct_positive_years', 0)*100:.0f}%",
            f"{r['test4_bootstrap']['cagr_p5']*100:+.1f}%",
            verdict,
        ]
        print(" | ".join(f"{c:<14}" for c in row))


if __name__ == "__main__":
    main()
