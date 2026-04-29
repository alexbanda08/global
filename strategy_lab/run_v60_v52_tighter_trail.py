"""
V60: Apply trail x multiplier to V52's OWN sleeves (not just IBB).

Hypothesis from V58: tightening the trail (banks winners earlier, leaves SL
room) compresses MDD without much CAGR loss. If that lesson generalizes from
inside-bar breakouts to V52's own CCI/ST/MFI/VP/SVD/LATBB/STF sleeves, V52
itself gets a free MDD compression -> Calmar lower-CI may cross 1.0.

Sweep: trail_mult in [1.00 (V52 baseline), 0.85, 0.75, 0.65, 0.50]
Apply to BOTH EXIT_4H["trail_atr"] AND every entry in REGIME_EXITS_4H.

For each variant:
  - Headline (Sharpe / CAGR / MDD / Calmar)
  - Gates 1-6 via verdict_8gate (the bootstrap CIs are what matters here)
  - If a variant has Calmar lower-CI > 1.0  AND  point-Sharpe >= 2.4, flag for
    full 10-gate battery in V61.
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
from strategy_lab.eval.perps_simulator_adaptive_exit import REGIME_EXITS_4H as _BASE_REGIME_EXITS
from strategy_lab.regime.hmm_adaptive import fit_regime_model
from strategy_lab.run_leverage_audit import eqw_blend, invvol_blend, verdict_8gate
from strategy_lab.strategies.v50_new_signals import (
    sig_mfi_extreme, sig_signed_vol_div, sig_volume_profile_rot,
)

OUT = REPO / "docs/research/phase5_results"
OUT.mkdir(parents=True, exist_ok=True)
BPY = 365.25 * 6
START = "2024-01-12"
END = "2026-04-25"


# ----------------------------------------------------------------- V52 spec
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


def make_exits(trail_mult: float):
    """Return (exit_4h, regime_exits) with trail scaled by trail_mult."""
    exit4h = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0 * trail_mult, max_hold=60)
    regime = {}
    for k, (sl, tp, tr, mh) in _BASE_REGIME_EXITS.items():
        regime[k] = (sl, tp, tr * trail_mult, mh)
    return exit4h, regime


def build_v41_sleeve(sleeve, trail_mult: float, df_override=None):
    script, fn, sym = SLEEVE_SPECS[sleeve]
    sig = import_sig(script, fn)
    df = df_override if df_override is not None else load_hl(sym, "4h", start=START, end=END)
    out = sig(df); le, se = out if isinstance(out, tuple) else (out, None)
    fund = funding_per_4h_bar(sym, df.index)
    variant = V41_VARIANT_MAP[sleeve]
    exit4h, regime_exits = make_exits(trail_mult)

    if variant == "baseline":
        _, eq = simulate_with_funding(df, le, se, fund, **exit4h)
    elif variant == "V41":
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        _, eq = simulate_with_funding(df, le, se, fund,
                                       regime_labels=rdf["label"],
                                       regime_exits=regime_exits)
    elif variant == "V45":
        vol = df["volume"]; vmean = vol.rolling(20, min_periods=10).mean()
        active = vol > 1.1 * vmean
        le2 = le & active
        se2 = se & active if se is not None else None
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        _, eq = simulate_with_funding(df, le2, se2, fund,
                                       regime_labels=rdf["label"],
                                       regime_exits=regime_exits)
    return eq


def build_diversifier(name, trail_mult: float, df_override=None):
    spec = next(s for s in DIV_SPECS if s[0] == name)
    _, sym, sig_fn, kw, exit_style = spec
    df = df_override if df_override is not None else load_hl(sym, "4h", start=START, end=END)
    out = sig_fn(df, **kw); le, se = out if isinstance(out, tuple) else (out, None)
    fund = funding_per_4h_bar(sym, df.index)
    exit4h, regime_exits = make_exits(trail_mult)
    if exit_style == "V41":
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        _, eq = simulate_with_funding(df, le, se, fund,
                                       regime_labels=rdf["label"],
                                       regime_exits=regime_exits)
    else:
        _, eq = simulate_with_funding(df, le, se, fund, **exit4h)
    return eq


def build_v52_with_trail(trail_mult: float) -> pd.Series:
    """Same V52 recipe, but trail_atr scaled by trail_mult everywhere."""
    v41_curves = {s: build_v41_sleeve(s, trail_mult) for s in V41_VARIANT_MAP}
    p3 = invvol_blend({k: v41_curves[k] for k in ["CCI_ETH_4h", "STF_AVAX_4h", "STF_SOL_4h"]}, window=500)
    p5 = eqw_blend({k: v41_curves[k] for k in ["CCI_ETH_4h", "LATBB_AVAX_4h", "STF_SOL_4h"]})
    idx = p3.index.intersection(p5.index)
    v41_r = 0.6 * p3.reindex(idx).pct_change().fillna(0) + 0.4 * p5.reindex(idx).pct_change().fillna(0)
    v41_eq = (1 + v41_r).cumprod() * 10_000.0

    div_curves = {spec[0]: build_diversifier(spec[0], trail_mult) for spec in DIV_SPECS}
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
    sh = (float(r.mean()) / sd) * np.sqrt(BPY) if sd > 0 else 0
    pk = eq.cummax(); mdd = float((eq / pk - 1).min())
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 1e-6)) - 1
    cal = cagr / abs(mdd) if mdd != 0 else 0
    return {"sharpe": round(sh, 3), "cagr_pct": round(float(cagr) * 100, 2),
            "mdd_pct": round(mdd * 100, 2), "calmar": round(float(cal), 3)}


def main():
    t0 = time.time()
    print("=" * 72)
    print("V60: V52 with trail_atr x multiplier  (testing tight-trail lesson)")
    print("=" * 72)

    MULTS = [1.00, 0.85, 0.75, 0.65, 0.50]
    rows = []
    for tm in MULTS:
        print(f"\n>>> trail_mult = {tm:.2f}")
        eq = build_v52_with_trail(tm)
        h = headline(eq)
        gates = verdict_8gate(eq)
        passed = sum(1 for g in gates["gates"].values() if g["pass"] is True)
        sh_lci = gates["gates"]["bootstrap_sharpe_lowerCI_gt_0.5"]["value"]
        cal_lci = gates["gates"]["bootstrap_calmar_lowerCI_gt_1.0"]["value"]
        mdd_wci = gates["gates"]["bootstrap_mdd_worstCI_gt_neg30pct"]["value"]
        wf_eff = gates["gates"]["walk_forward_efficiency_gt_0.5"]["value"]

        row = {"trail_mult": tm, **h,
               "gates_passed_1_6": passed,
               "sharpe_lowerCI": round(float(sh_lci), 3),
               "calmar_lowerCI": round(float(cal_lci), 3),
               "mdd_worstCI": round(float(mdd_wci), 3),
               "wf_efficiency": round(float(wf_eff), 3)}
        rows.append(row)
        print(f"   Sh={h['sharpe']:.3f}  CAGR={h['cagr_pct']:+.2f}%  "
              f"MDD={h['mdd_pct']:+.2f}%  Calmar={h['calmar']:.2f}")
        print(f"   gates 1-6: {passed}/6  Sh_lci={sh_lci:.3f}  Cal_lci={cal_lci:.3f}  "
              f"MDD_wci={mdd_wci:.3f}  wf_eff={wf_eff:.3f}")

    # Comparison table
    print("\n" + "=" * 72)
    print("COMPARISON TABLE (vs trail_mult=1.00 baseline)")
    print("=" * 72)
    base = next(r for r in rows if r["trail_mult"] == 1.00)
    print(f"{'mult':>5} | {'Sh':>5} {'dSh':>5} | {'CAGR%':>6} {'dCAGR':>5} | "
          f"{'MDD%':>6} {'dMDD':>5} | {'Cal':>5} {'dCal':>5} | "
          f"{'Sh_lci':>6} {'Cal_lci':>7} {'g/6':>3}")
    for r in rows:
        d_sh = r["sharpe"] - base["sharpe"]
        d_cagr = r["cagr_pct"] - base["cagr_pct"]
        d_mdd = r["mdd_pct"] - base["mdd_pct"]
        d_cal = r["calmar"] - base["calmar"]
        flag = ""
        if r["calmar_lowerCI"] > 1.0 and r["sharpe"] >= 2.4:
            flag = "  *** CROSSES GATE 3 ***"
        print(f"{r['trail_mult']:>5.2f} | {r['sharpe']:>5.2f} {d_sh:>+5.2f} | "
              f"{r['cagr_pct']:>6.2f} {d_cagr:>+5.2f} | "
              f"{r['mdd_pct']:>+6.2f} {d_mdd:>+5.2f} | "
              f"{r['calmar']:>5.2f} {d_cal:>+5.2f} | "
              f"{r['sharpe_lowerCI']:>6.3f} {r['calmar_lowerCI']:>7.3f} "
              f"{r['gates_passed_1_6']:>3}{flag}")

    # Promotion check
    promoted = [r for r in rows if r["calmar_lowerCI"] > 1.0 and r["sharpe"] >= 2.4]
    print(f"\nVariants crossing Calmar lower-CI > 1.0: {len(promoted)}")
    for r in promoted:
        print(f"   trail_mult={r['trail_mult']}: Cal_lci={r['calmar_lowerCI']:.3f} "
              f"Sh={r['sharpe']:.2f} Cal={r['calmar']:.2f}")

    out = OUT / "v60_trail_sweep.json"
    out.write_text(json.dumps({"rows": rows, "promoted": promoted}, indent=2, default=str))
    print(f"\nWrote: {out}")
    print(f"Total: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
