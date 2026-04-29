"""
V69 — Per-position leverage validation for V52* (alpha=0.75) x L=1.75.

Doc 38 (V68b gates) promoted V52* x L=1.75 as V69 candidate using BLEND-LEVEL
leverage:  levered_returns = (L * blend_returns).clip(lower=-0.99). That's an
upper-bound estimate.

This runner re-runs each underlying sleeve through `simulate_with_funding`
with leverage applied AT THE POSITION LEVEL via:

    size_mult     = 1.75   (multiply position size by 1.75 inside the simulator)
    leverage_cap  = 5.25   (raise from 3.0 -> 3.0 * 1.75 so the cap doesn't
                            artificially throttle the up-sized positions)

Then re-aggregates at alpha=0.75. Compares to:
  - V69 blend-level estimate     (CAGR +64.02%, MDD -12.59%, Sh 2.639)
  - V52* standalone               (CAGR +33.29%, MDD  -7.31%, Sh 2.639)

Pass criterion: each per-position headline metric within +/-10% of V69
blend-level estimate. If they diverge by more than 10%, the per-position
result is the truth and the kill-switch / sizing schedule must be re-tuned
to those numbers.

Three variants tested for robustness:
  (a) size_mult=1.75, leverage_cap=5.25   -- target spec
  (b) size_mult=1.75, leverage_cap=3.0    -- realistic if exchange caps at 3x
  (c) risk_per_trade=0.0525 (= 0.03 * 1.75), size_mult=1.0, cap=5.25
                                            -- alternative parameterization

Variant (a) is the headline. (b) and (c) bracket the answer.
"""
from __future__ import annotations
import json
import sys
import time
import warnings
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
from strategy_lab.run_v52_hl_gates import (
    V41_VARIANT_MAP, DIV_SPECS, SLEEVE_SPECS, import_sig,
)
from strategy_lab.run_leverage_audit import eqw_blend, invvol_blend

OUT = REPO / "docs" / "research" / "phase5_results"
OUT.mkdir(parents=True, exist_ok=True)
BPY = 365.25 * 6

ALPHA = 0.75
DIV_SHARE = (1.0 - ALPHA) / 4

START = "2024-01-12"
END = "2026-04-25"

# Default exit profile (matches build_v52_hl EXIT_4H)
EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)

# Blend-level V69 candidate headline (target for comparison)
V69_BLEND_HEADLINE = {
    "sharpe": 2.639,
    "cagr": 0.6402,
    "mdd": -0.1259,
    "calmar": 5.085,
}


# ---------------------------------------------------------------------------
# Levered sleeve builders (mirror build_v41_sleeve / build_diversifier
#  but accept lev kwargs)
# ---------------------------------------------------------------------------

def build_v41_sleeve_lev(sleeve, *, size_mult=1.0, leverage_cap=3.0,
                          risk_per_trade=0.03):
    """Same as run_v52_hl_gates.build_v41_sleeve but exposes lev kwargs."""
    script, fn, sym = SLEEVE_SPECS[sleeve]
    sig = import_sig(script, fn)
    df = load_hl(sym, "4h", start=START, end=END)
    out = sig(df)
    le, se = out if isinstance(out, tuple) else (out, None)
    fund = funding_per_4h_bar(sym, df.index)
    variant = V41_VARIANT_MAP[sleeve]

    common_kw = dict(size_mult=size_mult, leverage_cap=leverage_cap,
                      risk_per_trade=risk_per_trade)

    if variant == "baseline":
        _, eq = simulate_with_funding(df, le, se, fund,
                                       **EXIT_4H, **common_kw)
    elif variant == "V41":
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        _, eq = simulate_with_funding(df, le, se, fund,
                                       regime_labels=rdf["label"],
                                       regime_exits=REGIME_EXITS_4H,
                                       **common_kw)
    elif variant == "V45":
        vol = df["volume"]
        vmean = vol.rolling(20, min_periods=10).mean()
        active = vol > 1.1 * vmean
        le2 = le & active
        se2 = se & active if se is not None else None
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        _, eq = simulate_with_funding(df, le2, se2, fund,
                                       regime_labels=rdf["label"],
                                       regime_exits=REGIME_EXITS_4H,
                                       **common_kw)
    return eq


def build_diversifier_lev(name, *, size_mult=1.0, leverage_cap=3.0,
                            risk_per_trade=0.03):
    spec = next(s for s in DIV_SPECS if s[0] == name)
    _, sym, sig_fn, kw, exit_style = spec
    df = load_hl(sym, "4h", start=START, end=END)
    out = sig_fn(df, **kw)
    le, se = out if isinstance(out, tuple) else (out, None)
    fund = funding_per_4h_bar(sym, df.index)
    common_kw = dict(size_mult=size_mult, leverage_cap=leverage_cap,
                      risk_per_trade=risk_per_trade)
    if exit_style == "V41":
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        _, eq = simulate_with_funding(df, le, se, fund,
                                       regime_labels=rdf["label"],
                                       regime_exits=REGIME_EXITS_4H,
                                       **common_kw)
    else:
        _, eq = simulate_with_funding(df, le, se, fund,
                                       **EXIT_4H, **common_kw)
    return eq


# ---------------------------------------------------------------------------
# V52* aggregator at alpha=0.75
# ---------------------------------------------------------------------------

def build_v52star_at_alpha(v41_curves: dict, div_curves: dict, alpha: float = ALPHA) -> pd.Series:
    """V41 inner-blend (0.6 invvol + 0.4 eqw) -> alpha-share with diversifiers."""
    p3 = invvol_blend({k: v41_curves[k] for k in ["CCI_ETH_4h", "STF_AVAX_4h", "STF_SOL_4h"]}, window=500)
    p5 = eqw_blend({k: v41_curves[k] for k in ["CCI_ETH_4h", "LATBB_AVAX_4h", "STF_SOL_4h"]})
    idx = p3.index.intersection(p5.index)
    v41_r = (
        0.6 * p3.reindex(idx).pct_change().fillna(0)
        + 0.4 * p5.reindex(idx).pct_change().fillna(0)
    )
    v41_eq = (1 + v41_r).cumprod() * 10_000.0

    all_idx = v41_eq.index
    for eq in div_curves.values():
        all_idx = all_idx.intersection(eq.index)
    cr = v41_eq.reindex(all_idx).pct_change().fillna(0)
    drs = {k: eq.reindex(all_idx).pct_change().fillna(0) for k, eq in div_curves.items()}

    div_share = (1 - alpha) / len(div_curves)
    combined = alpha * cr
    for k in div_curves:
        combined = combined + div_share * drs[k]
    return (1 + combined).cumprod() * 10_000.0


def headline(eq: pd.Series, label: str) -> dict:
    r = eq.pct_change().dropna()
    sd = float(r.std())
    sh = (float(r.mean()) / sd) * np.sqrt(BPY) if sd > 0 else 0.0
    pk = eq.cummax()
    mdd = float((eq / pk - 1).min())
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 1e-6)) - 1
    cal = float(cagr) / abs(mdd) if mdd != 0 else 0.0
    return {
        "label": label,
        "sharpe": round(float(sh), 3),
        "cagr": round(float(cagr), 4),
        "mdd": round(float(mdd), 4),
        "calmar": round(float(cal), 3),
    }


def divergence_pct(per_pos: dict, target: dict) -> dict:
    """Percent divergence per metric. Sign convention: positive = per-position
    is larger (more aggressive) than target."""
    out = {}
    for key in ["sharpe", "cagr", "mdd", "calmar"]:
        t = target[key]
        if t == 0:
            out[key] = float("inf")
        else:
            out[key] = round(100.0 * (per_pos[key] - t) / abs(t), 2)
    return out


# ---------------------------------------------------------------------------
# Variant runner
# ---------------------------------------------------------------------------

def run_variant(label: str, *, size_mult: float, leverage_cap: float,
                 risk_per_trade: float = 0.03) -> dict:
    print(f"\n[{label}] size_mult={size_mult}  leverage_cap={leverage_cap}  "
          f"risk_per_trade={risk_per_trade}")
    print("  Building 4 V41 sleeves at per-position leverage...")
    v41_curves = {
        s: build_v41_sleeve_lev(s, size_mult=size_mult, leverage_cap=leverage_cap,
                                  risk_per_trade=risk_per_trade)
        for s in V41_VARIANT_MAP
    }
    for s, eq in v41_curves.items():
        h = headline(eq, s)
        print(f"    {s:14s}  Sh={h['sharpe']:+5.2f}  CAGR={100*h['cagr']:+7.1f}%  "
              f"MDD={100*h['mdd']:+6.1f}%")

    print("  Building 4 diversifiers at per-position leverage...")
    div_curves = {
        spec[0]: build_diversifier_lev(spec[0], size_mult=size_mult,
                                          leverage_cap=leverage_cap,
                                          risk_per_trade=risk_per_trade)
        for spec in DIV_SPECS
    }
    for s, eq in div_curves.items():
        h = headline(eq, s)
        print(f"    {s:14s}  Sh={h['sharpe']:+5.2f}  CAGR={100*h['cagr']:+7.1f}%  "
              f"MDD={100*h['mdd']:+6.1f}%")

    eq = build_v52star_at_alpha(v41_curves, div_curves, ALPHA)
    h = headline(eq, label)
    div = divergence_pct(h, V69_BLEND_HEADLINE)
    print(f"\n  AGGREGATED V52* (alpha={ALPHA}) headline:")
    print(f"    Sharpe={h['sharpe']:+.3f}  CAGR={100*h['cagr']:+.2f}%  "
          f"MDD={100*h['mdd']:+.2f}%  Calmar={h['calmar']:.3f}")
    print(f"  Divergence vs V69 blend-level estimate (target):")
    print(f"    Sh:{div['sharpe']:+.1f}%  CAGR:{div['cagr']:+.1f}%  "
          f"MDD:{div['mdd']:+.1f}%  Cal:{div['calmar']:+.1f}%")

    within_10pct = all(abs(div[k]) <= 10.0 for k in ["sharpe", "cagr", "mdd", "calmar"])
    print(f"  Within +/-10% on all metrics: {within_10pct}")
    return {
        "label": label, "config": {"size_mult": size_mult, "leverage_cap": leverage_cap,
                                       "risk_per_trade": risk_per_trade},
        "headline": h, "divergence_pct": div, "within_10pct": within_10pct,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    t0 = time.time()
    print("=" * 78)
    print(f"V69: Per-position leverage validation for V52* (alpha={ALPHA}) x L=1.75")
    print(f"V69 blend-level target: Sh={V69_BLEND_HEADLINE['sharpe']}  "
          f"CAGR={100*V69_BLEND_HEADLINE['cagr']:+.2f}%  "
          f"MDD={100*V69_BLEND_HEADLINE['mdd']:+.2f}%  "
          f"Calmar={V69_BLEND_HEADLINE['calmar']}")
    print("=" * 78)

    results = []

    # Variant A: target spec — size_mult=1.75, leverage_cap=5.25
    results.append(run_variant("A_target_spec", size_mult=1.75, leverage_cap=5.25))

    # Variant B: realistic (HL caps at 3x for many coins) — same upsize, capped
    results.append(run_variant("B_capped_at_3x", size_mult=1.75, leverage_cap=3.0))

    # Variant C: alternative parameterization via risk_per_trade
    results.append(run_variant("C_via_risk_pct", size_mult=1.0, leverage_cap=5.25,
                                  risk_per_trade=0.0525))

    # Sanity: variant Z = no leverage (matches V52* standalone)
    results.append(run_variant("Z_no_leverage_sanity", size_mult=1.0, leverage_cap=3.0))

    # Decision
    print("\n" + "=" * 78)
    print("SUMMARY  (per-position vs V69 blend-level estimate)")
    print("=" * 78)
    print(f"{'variant':<24} {'Sh':>8} {'CAGR':>9} {'MDD':>9} {'Cal':>7}  "
          f"{'dSh%':>6} {'dCAGR%':>8} {'dMDD%':>7} {'within10%':>10}")
    for r in results:
        h = r["headline"]
        d = r["divergence_pct"]
        print(f"{r['label']:<24} "
              f"{h['sharpe']:+8.3f} {100*h['cagr']:+8.2f}% {100*h['mdd']:+8.2f}% "
              f"{h['calmar']:+7.2f}  "
              f"{d['sharpe']:+5.1f} {d['cagr']:+7.1f} {d['mdd']:+6.1f}  "
              f"{str(r['within_10pct']):>10}")

    target_pass = next((r for r in results if r["label"] == "A_target_spec"
                         and r["within_10pct"]), None)
    if target_pass:
        verdict = "PASS — V69 blend-level estimate is honest; per-position confirms it"
    else:
        verdict = ("DEVIATES — per-position differs from blend-level estimate by "
                   ">10% on at least one metric; use per-position numbers as truth "
                   "and re-tune kill-switch schedule")
    print(f"\nVERDICT: {verdict}")

    out = {
        "elapsed_s": round(time.time() - t0, 1),
        "v69_blend_target": V69_BLEND_HEADLINE,
        "variants": results,
        "verdict": verdict,
    }
    (OUT / "v69_per_position_lever.json").write_text(
        json.dumps(out, indent=2, default=str))
    print(f"\nWrote {OUT/'v69_per_position_lever.json'}")
    print(f"Elapsed: {out['elapsed_s']}s")
    return 0 if target_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
