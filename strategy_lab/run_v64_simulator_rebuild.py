"""
V64: Simulator-level rebuild of V63 (V52 leveraged at 1.75x).

V63 was a return-multiplier screen: r_t -> L * r_t. Mathematically clean
under the assumption that sleeve `leverage_cap` is never binding. This
rebuild verifies that assumption by running each sleeve through the actual
funding-aware simulator with `risk_per_trade = 1.75 * 0.03 = 0.0525` and
`leverage_cap = 3.0` (V52 default), then composing them with V52's exact
weighting recipe.

Variants tested:
  - L=1.50 (risk=0.045)
  - L=1.75 (risk=0.0525)  <- the V63 candidate
  - L=2.00 (risk=0.060)
  - L=2.50 (risk=0.075)

For each, also test a leverage_cap=4.0 variant in case the default 3.0 is
binding (+1 row per L). If V64 (lev=3.0) materially underperforms V63 but
V64 (lev=4.0) matches V63, we know the cap is binding and need to raise it.

Promotion bar: V64 must hit CAGR >= 50% AND MDD >= -20% AND match V63
within +/- 10% on each metric.
"""
from __future__ import annotations
import json, sys, time, warnings, importlib.util
from pathlib import Path
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "strategy_lab"))

from strategy_lab.util.hl_data import load_hl, funding_per_4h_bar
from strategy_lab.eval.perps_simulator_funding import simulate_with_funding
from strategy_lab.eval.perps_simulator_adaptive_exit import REGIME_EXITS_4H
from strategy_lab.regime.hmm_adaptive import fit_regime_model
from strategy_lab.run_leverage_audit import eqw_blend, invvol_blend, verdict_8gate
from strategy_lab.run_v52_hl_gates import build_v52_hl  # for return-mult comparison
from strategy_lab.strategies.v50_new_signals import (
    sig_mfi_extreme, sig_signed_vol_div, sig_volume_profile_rot,
)

OUT = REPO / "docs/research/phase5_results"
OUT.mkdir(parents=True, exist_ok=True)
BPY = 365.25 * 6
START = "2024-01-12"
END = "2026-04-25"
EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)


# Mirror of V52 spec
V41_VARIANT_MAP = {
    "CCI_ETH_4h":    "V41",
    "STF_SOL_4h":    "baseline",
    "STF_AVAX_4h":   "V45",
    "LATBB_AVAX_4h": "baseline",
}
SLEEVE_SPECS = {
    "CCI_ETH_4h":    ("run_v30_creative.py",  "sig_cci_extreme",     "ETH"),
    "STF_SOL_4h":    ("run_v30_creative.py",  "sig_supertrend_flip", "SOL"),
    "STF_AVAX_4h":   ("run_v30_creative.py",  "sig_supertrend_flip", "AVAX"),
    "LATBB_AVAX_4h": ("run_v29_regime.py",    "sig_lateral_bb_fade", "AVAX"),
}
DIV_SPECS = [
    ("MFI_SOL",  "SOL",  sig_mfi_extreme,        dict(lower=25, upper=75), "V41"),
    ("VP_LINK",  "LINK", sig_volume_profile_rot, dict(win=60, n_bins=15), "baseline"),
    ("SVD_AVAX", "AVAX", sig_signed_vol_div,     dict(lookback=20, cvd_win=50, min_cvd_threshold=0.5), "baseline"),
    ("MFI_ETH",  "ETH",  sig_mfi_extreme,        dict(lower=25, upper=75), "baseline"),
]


def import_sig(script, fn):
    path = REPO / "strategy_lab" / script
    spec = importlib.util.spec_from_file_location(script.replace(".", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, fn)


def build_v41_sleeve(sleeve, risk: float, lev: float):
    script, fn, sym = SLEEVE_SPECS[sleeve]
    sig = import_sig(script, fn)
    df = load_hl(sym, "4h", start=START, end=END)
    out = sig(df); le, se = out if isinstance(out, tuple) else (out, None)
    fund = funding_per_4h_bar(sym, df.index)
    variant = V41_VARIANT_MAP[sleeve]
    common = dict(risk_per_trade=risk, leverage_cap=lev)
    if variant == "baseline":
        _, eq = simulate_with_funding(df, le, se, fund, **EXIT_4H, **common)
    elif variant == "V41":
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        _, eq = simulate_with_funding(df, le, se, fund,
                                       regime_labels=rdf["label"],
                                       regime_exits=REGIME_EXITS_4H,
                                       **common)
    elif variant == "V45":
        vol = df["volume"]; vmean = vol.rolling(20, min_periods=10).mean()
        active = vol > 1.1 * vmean
        le2 = le & active
        se2 = se & active if se is not None else None
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        _, eq = simulate_with_funding(df, le2, se2, fund,
                                       regime_labels=rdf["label"],
                                       regime_exits=REGIME_EXITS_4H,
                                       **common)
    return eq


def build_diversifier(name, risk: float, lev: float):
    spec = next(s for s in DIV_SPECS if s[0] == name)
    _, sym, sig_fn, kw, exit_style = spec
    df = load_hl(sym, "4h", start=START, end=END)
    out = sig_fn(df, **kw); le, se = out if isinstance(out, tuple) else (out, None)
    fund = funding_per_4h_bar(sym, df.index)
    common = dict(risk_per_trade=risk, leverage_cap=lev)
    if exit_style == "V41":
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        _, eq = simulate_with_funding(df, le, se, fund,
                                       regime_labels=rdf["label"],
                                       regime_exits=REGIME_EXITS_4H,
                                       **common)
    else:
        _, eq = simulate_with_funding(df, le, se, fund, **EXIT_4H, **common)
    return eq


def build_v52_levered(risk: float, lev: float) -> pd.Series:
    """Same V52 recipe but with parameterized risk and leverage_cap."""
    v41_curves = {s: build_v41_sleeve(s, risk, lev) for s in V41_VARIANT_MAP}
    p3 = invvol_blend({k: v41_curves[k] for k in ["CCI_ETH_4h", "STF_AVAX_4h", "STF_SOL_4h"]}, window=500)
    p5 = eqw_blend({k: v41_curves[k] for k in ["CCI_ETH_4h", "LATBB_AVAX_4h", "STF_SOL_4h"]})
    idx = p3.index.intersection(p5.index)
    v41_r = 0.6 * p3.reindex(idx).pct_change().fillna(0) + 0.4 * p5.reindex(idx).pct_change().fillna(0)
    v41_eq = (1 + v41_r).cumprod() * 10_000.0

    div_curves = {spec[0]: build_diversifier(spec[0], risk, lev) for spec in DIV_SPECS}
    all_idx = v41_eq.index
    for eq in div_curves.values():
        all_idx = all_idx.intersection(eq.index)
    cr = v41_eq.reindex(all_idx).pct_change().fillna(0)
    drs = {k: eq.reindex(all_idx).pct_change().fillna(0) for k, eq in div_curves.items()}
    combined = (0.60 * cr + 0.10 * drs["MFI_SOL"] + 0.10 * drs["VP_LINK"]
                + 0.10 * drs["SVD_AVAX"] + 0.10 * drs["MFI_ETH"])
    return (1 + combined).cumprod() * 10_000.0


def headline(eq: pd.Series) -> dict:
    r = eq.pct_change().dropna()
    sd = float(r.std())
    if sd == 0:
        return {"sharpe": 0, "cagr_pct": 0, "mdd_pct": 0, "calmar": 0}
    sh = (float(r.mean()) / sd) * np.sqrt(BPY)
    pk = eq.cummax(); mdd = float((eq / pk - 1).min())
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 1e-6)) - 1
    cal = cagr / abs(mdd) if mdd != 0 else 0
    return {"sharpe": round(sh, 3), "cagr_pct": round(float(cagr) * 100, 2),
            "mdd_pct": round(mdd * 100, 2), "calmar": round(float(cal), 3)}


def lever_returns(v52_eq: pd.Series, L: float) -> pd.Series:
    r = v52_eq.pct_change().fillna(0) * L
    r = r.clip(lower=-0.99)
    return (1 + r).cumprod() * 10_000.0


def main():
    t0 = time.time()
    print("=" * 72)
    print("V64: Simulator-level rebuild of V63 leveraged candidates")
    print("=" * 72)

    print("\n[1] Building V52 baseline (risk=0.03, lev=3.0)...")
    v52 = build_v52_hl()
    h_v52 = headline(v52)
    print(f"   V52: {h_v52}")

    BASE_RISK = 0.03
    LEVS = [1.50, 1.75, 2.00, 2.50]
    print(f"\n[2] Simulator-level builds at risk = {BASE_RISK} * L (lev_cap variants 3.0 and 4.0)...")
    print(f"\n   {'L':>4} | {'lev_cap':>7} | {'risk':>5} | "
          f"{'Sharpe':>6} | {'CAGR':>7} | {'MDD':>7} | {'Calmar':>6} | {'vs V63 ret-mult':>17}")
    rows = []
    for L in LEVS:
        risk = BASE_RISK * L
        # return-mult reference
        v63_ref = lever_returns(v52, L)
        h_ref = headline(v63_ref)
        for lev_cap in [3.0, 4.0]:
            eq = build_v52_levered(risk, lev_cap)
            h = headline(eq)
            d_sh = h["sharpe"] - h_ref["sharpe"]
            d_cagr = h["cagr_pct"] - h_ref["cagr_pct"]
            d_mdd = h["mdd_pct"] - h_ref["mdd_pct"]
            d_cal = h["calmar"] - h_ref["calmar"]
            cmp_str = (f"dSh={d_sh:+.2f} dCAGR={d_cagr:+.1f}pp "
                       f"dMDD={d_mdd:+.1f}pp dCal={d_cal:+.2f}")
            row = {"L": L, "lev_cap": lev_cap, "risk": risk, **h,
                   "ref_sharpe": h_ref["sharpe"], "ref_cagr_pct": h_ref["cagr_pct"],
                   "ref_mdd_pct": h_ref["mdd_pct"], "ref_calmar": h_ref["calmar"],
                   "delta_sh": round(d_sh, 3),
                   "delta_cagr_pp": round(d_cagr, 2),
                   "delta_mdd_pp": round(d_mdd, 2),
                   "delta_cal": round(d_cal, 3)}
            rows.append(row)
            print(f"   {L:>4.2f} | {lev_cap:>7.1f} | {risk:>5.3f} | "
                  f"{h['sharpe']:>6.2f} | {h['cagr_pct']:>+6.2f}% | "
                  f"{h['mdd_pct']:>+6.2f}% | {h['calmar']:>6.2f} | {cmp_str}")

    # Per-L pick the best lev_cap variant
    print(f"\n[3] Best lev_cap per L (closer to V63 return-mult is better):")
    best_per_L = {}
    for L in LEVS:
        candidates = [r for r in rows if r["L"] == L]
        # closest match to ref by sum of |deltas| in normalized terms
        def score(r):
            return abs(r["delta_sh"]) + abs(r["delta_cagr_pp"]) / 50 + abs(r["delta_mdd_pp"]) / 5
        best = min(candidates, key=score)
        best_per_L[L] = best
        match_pct = "OK" if (abs(best["delta_cagr_pp"]) <= 5 and abs(best["delta_mdd_pp"]) <= 2.5) else "DIVERGE"
        print(f"   L={L}  best_lev_cap={best['lev_cap']}  Sh={best['sharpe']:.2f}  "
              f"CAGR={best['cagr_pct']:+.2f}% (ref {best['ref_cagr_pct']:+.2f})  "
              f"MDD={best['mdd_pct']:+.2f}% (ref {best['ref_mdd_pct']:+.2f})  [{match_pct}]")

    # Run gates 1-6 on the best L=1.75 variant
    pick = best_per_L[1.75]
    print(f"\n[4] Gates 1-6 on V64 winner (L=1.75, lev_cap={pick['lev_cap']}, risk={pick['risk']:.4f})...")
    eq_v64 = build_v52_levered(pick["risk"], pick["lev_cap"])
    g6 = verdict_8gate(eq_v64)
    print(f"   tests_passed: {g6['tests_passed']}")
    for gn, g in g6["gates"].items():
        mark = "PASS" if g["pass"] is True else "FAIL" if g["pass"] is False else "skip"
        print(f"     [{mark:4s}] {gn:38s} -> {g['value']}")

    pass_count = sum(1 for g in g6["gates"].values() if g["pass"] is True)
    target_hit = pick["cagr_pct"] >= 50 and pick["mdd_pct"] >= -20

    print(f"\n{'=' * 72}")
    print(f"V64 SCORECARD (L=1.75, sim-level)")
    print(f"  Headline: Sh={pick['sharpe']:.2f}  CAGR={pick['cagr_pct']:+.2f}%  "
          f"MDD={pick['mdd_pct']:+.2f}%  Calmar={pick['calmar']:.2f}")
    print(f"  V63 return-mult ref: Sh={pick['ref_sharpe']:.2f}  CAGR={pick['ref_cagr_pct']:+.2f}%  "
          f"MDD={pick['ref_mdd_pct']:+.2f}%  Calmar={pick['ref_calmar']:.2f}")
    print(f"  Deltas: dSh={pick['delta_sh']:+.2f}  dCAGR={pick['delta_cagr_pp']:+.2f}pp  "
          f"dMDD={pick['delta_mdd_pp']:+.2f}pp  dCal={pick['delta_cal']:+.2f}")
    print(f"  Gates 1-6: {pass_count}/6")
    print(f"  Target (CAGR>=50% AND MDD>=-20%): {'YES' if target_hit else 'NO'}")
    confirms = (target_hit and abs(pick["delta_cagr_pp"]) <= 5
                and abs(pick["delta_mdd_pp"]) <= 2.5 and pass_count >= 5)
    print(f"  V63 CONFIRMED: {'YES' if confirms else 'NO'}")
    print(f"{'=' * 72}")

    summary = {
        "v52_baseline":   h_v52,
        "rows":           rows,
        "best_per_L":     {str(k): v for k, v in best_per_L.items()},
        "v64_pick":       pick,
        "v64_gates_1_6":  g6,
        "v64_target_hit": target_hit,
        "v63_confirmed":  confirms,
    }
    out = OUT / "v64_simulator_rebuild.json"
    out.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nWrote: {out}")
    print(f"Total: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
