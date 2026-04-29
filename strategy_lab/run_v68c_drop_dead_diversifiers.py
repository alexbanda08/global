"""
V68c — Drop dead-weight diversifiers from V52*.

V69 per-position validation (doc 39) surfaced two diversifiers with
near-zero alpha at L=1.75 leverage:

  SVD_AVAX  Sh +0.30  CAGR  +3.9%  MDD -61.7%
  MFI_ETH   Sh +0.25  CAGR  -1.4%  MDD -44.9%

Each currently allocated 0.0625 in the V52* alpha=0.75 blend (= 6.25%
of risk capital each, 12.5% total). This runner tests four surgical
variants:

  base     : keep all 4 diversifiers   (V69, alpha=0.75)
  drop_SVD : keep MFI_SOL/VP_LINK/MFI_ETH; redistribute 0.0625 to V41 core
              -> alpha = 0.8125
  drop_MFI : keep MFI_SOL/VP_LINK/SVD_AVAX; redistribute 0.0625 to V41 core
              -> alpha = 0.8125
  drop_both: keep MFI_SOL/VP_LINK only; redistribute 0.125 to V41 core
              -> alpha = 0.875

Each variant evaluated at:
  (a) standalone (no leverage)
  (b) per-position L=1.75 (size_mult=1.75, leverage_cap=5.25 — variant A spec
      from V69 doc 39)

Decision rule for promotion:
  - Levered Sharpe >= V69 baseline levered Sharpe (2.614)
  - Levered MDD non-worse than V69 baseline (-12.42%)
  - Levered CAGR >= 60% (still hits user target)

Pick smallest delta from V69 (i.e., drop_SVD or drop_MFI in preference to
drop_both, all else equal — preserves more diversification).
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

from strategy_lab.run_v52_hl_gates import V41_VARIANT_MAP, DIV_SPECS
from strategy_lab.run_leverage_audit import eqw_blend, invvol_blend
from strategy_lab.run_v69_per_position_lever import (
    build_v41_sleeve_lev, build_diversifier_lev,
)

OUT = REPO / "docs" / "research" / "phase5_results"
OUT.mkdir(parents=True, exist_ok=True)
BPY = 365.25 * 6

# V69 baseline targets (per-position from doc 39 variant A)
V69_BASELINE_LEVERED = {"sharpe": 2.614, "cagr": 0.6111, "mdd": -0.1242, "calmar": 4.92}
V69_BASELINE_BASE   = {"sharpe": 2.639, "cagr": 0.3329, "mdd": -0.0731, "calmar": 4.55}

# Per-position leverage spec (from V69 variant A)
LEV_SIZE_MULT = 1.75
LEV_CAP = 5.25


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def headline(eq: pd.Series) -> dict:
    r = eq.pct_change().dropna()
    sd = float(r.std())
    sh = (float(r.mean()) / sd) * np.sqrt(BPY) if sd > 0 else 0.0
    pk = eq.cummax()
    mdd = float((eq / pk - 1).min())
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 1e-6)) - 1
    cal = float(cagr) / abs(mdd) if mdd != 0 else 0.0
    daily = (1 + r).resample("D").prod() - 1
    daily_active = daily[daily.abs() > 1e-7]
    wr_d = 100.0 * (daily_active > 0).mean() if len(daily_active) else float("nan")
    return {
        "sharpe": round(float(sh), 3),
        "cagr": round(float(cagr), 4),
        "mdd": round(float(mdd), 4),
        "calmar": round(float(cal), 3),
        "wr_daily": round(float(wr_d), 2),
    }


# ---------------------------------------------------------------------------
# V52* aggregator (parametric in alpha + diversifier set)
# ---------------------------------------------------------------------------

def build_blend(v41_curves: dict, div_curves: dict, keep_divs: list[str], alpha: float) -> pd.Series:
    """Build V52* with arbitrary V41-share alpha and a subset of diversifiers.
    Remaining (1 - alpha) is split equally across keep_divs."""
    p3 = invvol_blend({k: v41_curves[k] for k in ["CCI_ETH_4h", "STF_AVAX_4h", "STF_SOL_4h"]}, window=500)
    p5 = eqw_blend({k: v41_curves[k] for k in ["CCI_ETH_4h", "LATBB_AVAX_4h", "STF_SOL_4h"]})
    idx = p3.index.intersection(p5.index)
    v41_r = (
        0.6 * p3.reindex(idx).pct_change().fillna(0)
        + 0.4 * p5.reindex(idx).pct_change().fillna(0)
    )
    v41_eq = (1 + v41_r).cumprod() * 10_000.0

    all_idx = v41_eq.index
    for d in keep_divs:
        all_idx = all_idx.intersection(div_curves[d].index)

    cr = v41_eq.reindex(all_idx).pct_change().fillna(0)
    drs = {k: div_curves[k].reindex(all_idx).pct_change().fillna(0) for k in keep_divs}

    if len(keep_divs) > 0:
        per_div = (1 - alpha) / len(keep_divs)
        combined = alpha * cr
        for k in keep_divs:
            combined = combined + per_div * drs[k]
    else:
        combined = cr  # alpha must be 1.0 here
    return (1 + combined).cumprod() * 10_000.0


# ---------------------------------------------------------------------------
# Build all 8 sleeves at both leverage settings (cached)
# ---------------------------------------------------------------------------

def build_all(size_mult: float, leverage_cap: float):
    """Returns dict of all 8 sleeve equity curves."""
    print(f"  building 4 V41 sleeves (size_mult={size_mult}, cap={leverage_cap})...")
    v41 = {
        s: build_v41_sleeve_lev(s, size_mult=size_mult, leverage_cap=leverage_cap)
        for s in V41_VARIANT_MAP
    }
    print(f"  building 4 diversifiers (size_mult={size_mult}, cap={leverage_cap})...")
    div = {
        spec[0]: build_diversifier_lev(spec[0], size_mult=size_mult, leverage_cap=leverage_cap)
        for spec in DIV_SPECS
    }
    return v41, div


# ---------------------------------------------------------------------------
# Variant evaluator
# ---------------------------------------------------------------------------

DIVERSIFIERS_ALL = ["MFI_SOL", "VP_LINK", "SVD_AVAX", "MFI_ETH"]

VARIANTS = [
    {"label": "V69_baseline_keep_all_4",
      "keep_divs": ["MFI_SOL", "VP_LINK", "SVD_AVAX", "MFI_ETH"], "alpha": 0.75},
    {"label": "drop_SVD_AVAX",
      "keep_divs": ["MFI_SOL", "VP_LINK", "MFI_ETH"], "alpha": 0.8125},
    {"label": "drop_MFI_ETH",
      "keep_divs": ["MFI_SOL", "VP_LINK", "SVD_AVAX"], "alpha": 0.8125},
    {"label": "drop_both",
      "keep_divs": ["MFI_SOL", "VP_LINK"], "alpha": 0.875},
    # Bonus: drop everything (pure V41) for reference
    {"label": "pure_V41_only",
      "keep_divs": [], "alpha": 1.0},
]


def evaluate_variants(v41_base: dict, div_base: dict, v41_lev: dict, div_lev: dict) -> list[dict]:
    rows = []
    for v in VARIANTS:
        eq_base = build_blend(v41_base, div_base, v["keep_divs"], v["alpha"])
        eq_lev = build_blend(v41_lev, div_lev, v["keep_divs"], v["alpha"])
        h_base = headline(eq_base)
        h_lev = headline(eq_lev)
        rows.append({
            "label": v["label"],
            "keep_divs": v["keep_divs"],
            "alpha": v["alpha"],
            "standalone": h_base,
            "levered_pos": h_lev,
        })
    return rows


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

def grade_variant(row: dict, baseline_lev: dict) -> dict:
    """Compare against V69 baseline levered headline."""
    h = row["levered_pos"]
    sh_lift = h["sharpe"] - baseline_lev["sharpe"]
    cagr_lift = h["cagr"] - baseline_lev["cagr"]
    mdd_diff = h["mdd"] - baseline_lev["mdd"]   # +ve = less DD = better
    target_pass = h["cagr"] >= 0.60 and h["mdd"] >= -0.40 and h["wr_daily"] >= 50.0
    sharpe_lift = sh_lift >= 0
    mdd_non_worse = mdd_diff >= -0.005          # within 50 bps tolerance
    promote = sharpe_lift and mdd_non_worse and target_pass
    return {
        "delta_sharpe": round(sh_lift, 3),
        "delta_cagr_pp": round(100 * cagr_lift, 2),
        "delta_mdd_pp": round(100 * mdd_diff, 2),
        "passes_target": target_pass,
        "promote": promote,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    t0 = time.time()
    print("=" * 78)
    print("V68c: Drop dead-weight diversifiers (SVD_AVAX, MFI_ETH)")
    print(f"V69 baseline levered: Sh={V69_BASELINE_LEVERED['sharpe']}  "
          f"CAGR={100*V69_BASELINE_LEVERED['cagr']:+.2f}%  "
          f"MDD={100*V69_BASELINE_LEVERED['mdd']:+.2f}%")
    print("=" * 78)

    # Build the 8 sleeve curves at both leverage settings
    print("\n[0] Building all 8 sleeves at standalone leverage (size_mult=1.0)...")
    v41_base, div_base = build_all(size_mult=1.0, leverage_cap=3.0)

    print(f"\n[1] Building all 8 sleeves at per-position L={LEV_SIZE_MULT} "
          f"(cap={LEV_CAP})...")
    v41_lev, div_lev = build_all(size_mult=LEV_SIZE_MULT, leverage_cap=LEV_CAP)

    print(f"\n[2] Evaluating {len(VARIANTS)} variants...")
    rows = evaluate_variants(v41_base, div_base, v41_lev, div_lev)

    # Print summary table
    print()
    print(f"{'variant':<26} {'alpha':>6}  ──── standalone ────   ──── levered (per-pos) ────  vs V69 baseline")
    print(f"{'':26} {'':6}  {'Sh':>5} {'CAGR':>7} {'MDD':>7}    "
          f"{'Sh':>5} {'CAGR':>7} {'MDD':>7} {'WR_d':>5}    {'dSh':>5} {'dCAGR':>6} {'dMDD':>6}  {'verdict':<10}")
    print("─" * 130)
    grades = {}
    for r in rows:
        sb = r["standalone"]; sl = r["levered_pos"]
        g = grade_variant(r, V69_BASELINE_LEVERED)
        grades[r["label"]] = g
        verdict = "PROMOTE" if g["promote"] else (
            "target_fail" if not g["passes_target"] else "no_lift")
        print(f"{r['label']:<26} {r['alpha']:>6.4f}  "
              f"{sb['sharpe']:>+5.2f} {100*sb['cagr']:>+6.1f}% {100*sb['mdd']:>+6.1f}%   "
              f"{sl['sharpe']:>+5.2f} {100*sl['cagr']:>+6.1f}% {100*sl['mdd']:>+6.1f}% "
              f"{sl['wr_daily']:>5.1f}    "
              f"{g['delta_sharpe']:>+5.2f} {g['delta_cagr_pp']:>+5.1f} {g['delta_mdd_pp']:>+5.1f}  "
              f"{verdict:<10}")

    # Recommend
    print()
    promotes = [r for r in rows if grades[r["label"]]["promote"] and r["label"] != "V69_baseline_keep_all_4"]
    if promotes:
        # Pick smallest disruption: prefer drop_SVD or drop_MFI over drop_both;
        # tiebreak on Sharpe lift
        priority = ["drop_SVD_AVAX", "drop_MFI_ETH", "drop_both", "pure_V41_only"]
        chosen = None
        for label in priority:
            for r in promotes:
                if r["label"] == label:
                    chosen = r; break
            if chosen: break
        chosen = chosen or max(promotes, key=lambda r: grades[r["label"]]["delta_sharpe"])
        g = grades[chosen["label"]]
        print(f"RECOMMENDATION: {chosen['label']}  alpha={chosen['alpha']:.4f}")
        print(f"  Levered: Sh={chosen['levered_pos']['sharpe']:+.3f}  "
              f"CAGR={100*chosen['levered_pos']['cagr']:+.2f}%  "
              f"MDD={100*chosen['levered_pos']['mdd']:+.2f}%  "
              f"Calmar={chosen['levered_pos']['calmar']}")
        print(f"  vs V69 baseline: dSh={g['delta_sharpe']:+.3f}  "
              f"dCAGR={g['delta_cagr_pp']:+.2f}pp  dMDD={g['delta_mdd_pp']:+.2f}pp")
    else:
        print("RECOMMENDATION: HOLD — no variant strictly improves on V69 baseline")
        chosen = None

    out = {
        "elapsed_s": round(time.time() - t0, 1),
        "v69_baseline_levered": V69_BASELINE_LEVERED,
        "lev_config": {"size_mult": LEV_SIZE_MULT, "leverage_cap": LEV_CAP},
        "variants": rows,
        "grades": grades,
        "recommended": chosen["label"] if chosen else None,
    }
    (OUT / "v68c_drop_diversifiers.json").write_text(json.dumps(out, indent=2, default=str))
    print(f"\nWrote {OUT/'v68c_drop_diversifiers.json'}")
    print(f"Elapsed: {out['elapsed_s']}s")
    return 0 if promotes else 1


if __name__ == "__main__":
    raise SystemExit(main())
