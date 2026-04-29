"""
V68b — Full 10-gate battery on V52* (alpha=0.75) leveraged 1.75x.

Mirrors run_v59_v58_gates.py / run_v52_hl_gates.py structure. Decision rule:
the V52* x L=1.75 stack is promoted to V69 candidate ONLY if its gate
scorecard is >= V52 baseline scorecard AND its bootstrap Calmar lower-CI
is non-worse than V52's.

Gates run:
  1-6 : verdict_8gate (per-year, bootstrap CIs, walk-forward) on candidate
        AND on V52 baseline (apples-to-apples comparison)
  7   : asset-level permutation (n=20) on candidate only
  9   : path-shuffle MC (n=10_000) on candidate only
  10  : forward 1y MC (n=1000) on candidate only

Gate 8 (plateau) is skipped per V59 convention.

V52* is constructed by reusing build_v41_sleeve and build_diversifier
from run_v52_hl_gates, swapping ONLY the outer blend weights:

  V52  : 0.60 * V41 + 4 * 0.10  * diversifier
  V52* : 0.75 * V41 + 4 * 0.0625 * diversifier
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

from strategy_lab.util.hl_data import load_hl
from strategy_lab.run_v52_hl_gates import (
    V41_VARIANT_MAP, DIV_SPECS, SLEEVE_SPECS,
    build_v41_sleeve, build_diversifier, build_v52_hl, shuffle_df_lr,
)
from strategy_lab.run_leverage_audit import eqw_blend, invvol_blend, verdict_8gate
from strategy_lab.run_leverage_gates910 import gate9_path_shuffle, gate10_forward_paths

OUT = REPO / "docs" / "research" / "phase5_results"
OUT.mkdir(parents=True, exist_ok=True)
BPY = 365.25 * 6

# V52* design constants — established empirically by V68b alpha sweep (peak Sharpe at alpha=0.75)
ALPHA = 0.75
DIV_SHARE = (1.0 - ALPHA) / 4   # 0.0625 each for the 4 diversifiers
LEVERAGE = 1.75                  # established by V67 leverage audit

START = "2024-01-12"
END = "2026-04-25"


# ---------------------------------------------------------------------------
# V52* builder (alpha=0.75)
# ---------------------------------------------------------------------------

def build_v52star_hl(dfs_override: dict | None = None) -> pd.Series:
    """V52* = ALPHA * V41 + DIV_SHARE * sum(4 diversifiers).

    Reuses the V52 V41-internal blend (0.6 invvol + 0.4 eqw); only the OUTER
    V41-vs-diversifier share differs. dfs_override is forwarded to both V41
    and diversifier builders for asset-permutation testing.
    """
    # 4 V41 sleeves with regime-aware variants
    v41_curves = {}
    for s in V41_VARIANT_MAP:
        sym = SLEEVE_SPECS[s][2]
        df_o = dfs_override.get(sym) if dfs_override else None
        v41_curves[s] = build_v41_sleeve(s, df_override=df_o)

    p3 = invvol_blend({k: v41_curves[k] for k in ["CCI_ETH_4h", "STF_AVAX_4h", "STF_SOL_4h"]}, window=500)
    p5 = eqw_blend({k: v41_curves[k] for k in ["CCI_ETH_4h", "LATBB_AVAX_4h", "STF_SOL_4h"]})
    idx = p3.index.intersection(p5.index)
    v41_r = (
        0.6 * p3.reindex(idx).pct_change().fillna(0)
        + 0.4 * p5.reindex(idx).pct_change().fillna(0)
    )
    v41_eq = (1 + v41_r).cumprod() * 10_000.0

    # 4 diversifiers
    div_curves = {}
    for spec in DIV_SPECS:
        sym = spec[1]
        df_o = dfs_override.get(sym) if dfs_override else None
        div_curves[spec[0]] = build_diversifier(spec[0], df_override=df_o)

    # Common index across V41 + 4 diversifiers
    all_idx = v41_eq.index
    for eq in div_curves.values():
        all_idx = all_idx.intersection(eq.index)

    cr = v41_eq.reindex(all_idx).pct_change().fillna(0)
    drs = {k: eq.reindex(all_idx).pct_change().fillna(0) for k, eq in div_curves.items()}

    combined = (
        ALPHA * cr
        + DIV_SHARE * drs["MFI_SOL"]
        + DIV_SHARE * drs["VP_LINK"]
        + DIV_SHARE * drs["SVD_AVAX"]
        + DIV_SHARE * drs["MFI_ETH"]
    )
    return (1 + combined).cumprod() * 10_000.0


# ---------------------------------------------------------------------------
# Leverage helper (matches V67)
# ---------------------------------------------------------------------------

def lever(eq: pd.Series, L: float) -> pd.Series:
    r = eq.pct_change().fillna(0.0)
    return (1 + (L * r).clip(lower=-0.99)).cumprod() * float(eq.iloc[0])


# ---------------------------------------------------------------------------
# Pretty-print helpers
# ---------------------------------------------------------------------------

def print_gates_1_6(label: str, g6: dict) -> int:
    print(f"\n--- Gates 1-6 on {label} ---")
    print(f"  {g6['tests_passed']}")
    passed = 0
    for gn, g in g6["gates"].items():
        if g["pass"] is True:
            mark, sym = "PASS", "+"
            passed += 1
        elif g["pass"] is False:
            mark, sym = "FAIL", "-"
        else:
            mark, sym = "skip", "."
        print(f"    [{sym} {mark:4s}] {gn:42s} -> {g['value']}")
    return passed


def headline_dict(eq: pd.Series) -> dict:
    r = eq.pct_change().dropna()
    sd = float(r.std())
    sh = (float(r.mean()) / sd) * np.sqrt(BPY) if sd > 0 else 0.0
    pk = eq.cummax()
    mdd = float((eq / pk - 1).min())
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 1e-6)) - 1
    cal = float(cagr) / abs(mdd) if mdd != 0 else 0.0
    return {
        "sharpe": round(sh, 3), "cagr": round(float(cagr), 4),
        "mdd": round(mdd, 4), "calmar": round(cal, 3),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    t0 = time.time()
    print("=" * 78)
    print(f"V68b: Full 10-gate battery on V52* (alpha={ALPHA}) x L={LEVERAGE}")
    print(f"Window: {START} -> {END}")
    print("=" * 78)

    # Build the four candidate equities
    print("\n[0] Building candidate equities...")
    v52_base = build_v52_hl()
    v52_lev = lever(v52_base, LEVERAGE)
    v52star_base = build_v52star_hl()
    v52star_lev = lever(v52star_base, LEVERAGE)

    print(f"   V52  baseline    : {headline_dict(v52_base)}")
    print(f"   V52  L={LEVERAGE} (V67) : {headline_dict(v52_lev)}")
    print(f"   V52* alpha=0.75  : {headline_dict(v52star_base)}")
    print(f"   V52* alpha=0.75 L={LEVERAGE} : {headline_dict(v52star_lev)}")

    # ---- Gates 1-6 on each ----
    g6_v52 = verdict_8gate(v52_base)
    g6_v52_lev = verdict_8gate(v52_lev)
    g6_v52star = verdict_8gate(v52star_base)
    g6_v52star_lev = verdict_8gate(v52star_lev)

    p_v52 = print_gates_1_6("V52 baseline", g6_v52)
    p_v52_lev = print_gates_1_6(f"V52 levered L={LEVERAGE} (V67)", g6_v52_lev)
    p_v52star = print_gates_1_6("V52* alpha=0.75", g6_v52star)
    p_v52star_lev = print_gates_1_6(f"V52* alpha=0.75 levered L={LEVERAGE} (V69 candidate)", g6_v52star_lev)

    # ---- Gate 7: asset-level permutation on V52* lev ----
    print(f"\n--- Gate 7: asset-level permutation on V52* levered (n=20) ---")
    real_dfs = {sym: load_hl(sym, "4h", start=START, end=END)
                for sym in ["ETH", "AVAX", "SOL", "LINK"]}
    rng = np.random.default_rng(42)
    real_sh = headline_dict(v52star_lev)["sharpe"]
    null_shs = []
    for k in range(20):
        shuffled = {sym: shuffle_df_lr(df, rng) for sym, df in real_dfs.items()}
        try:
            eq_p = build_v52star_hl(dfs_override=shuffled)
            eq_p_lev = lever(eq_p, LEVERAGE)
            null_shs.append(headline_dict(eq_p_lev)["sharpe"])
        except Exception as e:
            print(f"  perm {k}: skipped ({type(e).__name__}: {str(e)[:60]})")
        if (k + 1) % 5 == 0:
            print(f"  perm {k+1}/20 done  (current null mean Sh = "
                  f"{float(np.mean(null_shs)):.3f})" if null_shs else f"  perm {k+1}/20 done")

    arr = np.asarray(null_shs)
    p_val = float((arr >= real_sh).mean()) if len(arr) else float("nan")
    pass7 = (p_val < 0.05) if len(arr) else False
    print(f"  observed Sh={real_sh:.3f}  null mean={float(arr.mean()):.3f}  "
          f"null 99th={float(np.quantile(arr, 0.99)):.3f}  "
          f"p_val={p_val:.4f}  -> {'PASS' if pass7 else 'FAIL'}")

    # ---- Gate 9: path-shuffle MC ----
    print(f"\n--- Gate 9: path-shuffle MC on V52* levered (n=10000) ---")
    g9 = gate9_path_shuffle(v52star_lev, n_iter=10_000)
    pass9 = g9["mdd_p5"] > -0.30
    print(f"  MDD: p5={100*g9['mdd_p5']:+.1f}% p50={100*g9['mdd_p50']:+.1f}% "
          f"p95={100*g9['mdd_p95']:+.1f}%")
    print(f"  RET: p5={100*g9['ret_p5']:+.1f}% p50={100*g9['ret_p50']:+.1f}% "
          f"p95={100*g9['ret_p95']:+.1f}%")
    print(f"  -> Gate 9 (worst-5% MDD > -30%): {'PASS' if pass9 else 'FAIL'}")

    # ---- Gate 10: forward 1y MC ----
    print(f"\n--- Gate 10: forward 1y MC on V52* levered (n=1000) ---")
    g10 = gate10_forward_paths(v52star_lev, n_paths=1000, year_bars=int(BPY))
    pass10 = g10["gate10_mdd_p5_gt_neg25"] and g10["gate10_median_cagr_gt_15"]
    print(f"  1y MDD: p5={100*g10['mdd_p5']:+.1f}% p50={100*g10['mdd_p50']:+.1f}%")
    print(f"  1y CAGR: p5={100*g10['cagr_p5']:+.1f}% p50={100*g10['cagr_p50']:+.1f}%")
    print(f"  P(neg yr)={g10['p_negative_year_pct']}%  "
          f"P(DD>20%)={g10['p_dd_worse_than_20pct']}%  "
          f"P(DD>30%)={g10['p_dd_worse_than_30pct']}%")
    print(f"  -> Gate 10 (mdd_p5 > -25% AND median_cagr > 15%): "
          f"{'PASS' if pass10 else 'FAIL'}")

    # ---- Decision ----
    total_v52 = p_v52
    total_v52star_lev = p_v52star_lev + (1 if pass7 else 0) + (1 if pass9 else 0) + (1 if pass10 else 0)
    total_v52_with_extra = p_v52  # V52 reference doesn't need gate 7/9/10 re-run; it has been audited before

    cal_lo_v52 = g6_v52["bootstrap"]["calmar"]["ci_lo"]
    cal_lo_v52star_lev = g6_v52star_lev["bootstrap"]["calmar"]["ci_lo"]

    print(f"\n{'=' * 78}")
    print("DECISION")
    print(f"{'=' * 78}")
    print(f"  V52 baseline gates 1-6 passed:        {p_v52}/6")
    print(f"  V52 levered (V67) gates 1-6 passed:    {p_v52_lev}/6")
    print(f"  V52* standalone gates 1-6 passed:      {p_v52star}/6")
    print(f"  V52* levered gates 1-6 passed:        {p_v52star_lev}/6")
    print(f"  Plus gate 7  (perm):    {'PASS' if pass7 else 'FAIL'}")
    print(f"  Plus gate 9  (MC path): {'PASS' if pass9 else 'FAIL'}")
    print(f"  Plus gate 10 (MC fwd):  {'PASS' if pass10 else 'FAIL'}")
    print(f"  V52* levered total:     {total_v52star_lev}/9")
    print()
    print(f"  Calmar lower-CI:  V52 = {cal_lo_v52:.3f}  vs  V52* lev = {cal_lo_v52star_lev:.3f}  "
          f"(delta = {cal_lo_v52star_lev - cal_lo_v52:+.3f})")

    promoted = (
        p_v52star_lev >= p_v52
        and pass7 and pass9 and pass10
        and cal_lo_v52star_lev >= cal_lo_v52
    )
    print(f"\n  PROMOTION VERDICT: {'PROMOTE V52* x L=1.75 as V69 champion candidate' if promoted else 'HOLD — does not clear all gates strictly above V52'}")

    # ---- Write structured output ----
    out = {
        "config": {"alpha": ALPHA, "leverage": LEVERAGE, "window": [START, END]},
        "headline": {
            "v52_baseline": headline_dict(v52_base),
            "v52_levered_v67": headline_dict(v52_lev),
            "v52star_baseline": headline_dict(v52star_base),
            "v52star_levered_v69_candidate": headline_dict(v52star_lev),
        },
        "gates_1_6": {
            "v52_baseline": g6_v52,
            "v52_levered_v67": g6_v52_lev,
            "v52star_baseline": g6_v52star,
            "v52star_levered_v69_candidate": g6_v52star_lev,
        },
        "gate_7_permutation": {
            "n": int(len(arr)),
            "observed_sharpe": real_sh,
            "null_mean": float(arr.mean()) if len(arr) else None,
            "null_99th": float(np.quantile(arr, 0.99)) if len(arr) else None,
            "p_value": p_val,
            "pass": pass7,
        },
        "gate_9_path_shuffle": g9,
        "gate_10_forward_mc": g10,
        "calmar_lower_ci": {
            "v52": cal_lo_v52,
            "v52star_levered": cal_lo_v52star_lev,
            "delta": cal_lo_v52star_lev - cal_lo_v52,
        },
        "promoted": promoted,
        "elapsed_s": round(time.time() - t0, 1),
    }
    (OUT / "v68b_full_gates.json").write_text(json.dumps(out, indent=2, default=str))
    print(f"\nWrote {OUT/'v68b_full_gates.json'}")
    print(f"Elapsed: {out['elapsed_s']}s")
    return 0 if promoted else 1


if __name__ == "__main__":
    raise SystemExit(main())
