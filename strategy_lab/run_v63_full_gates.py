"""
V63 full 10-gate battery on V52 portfolio-leveraged at L=1.75.

Headline target: CAGR >= 50% AND MDD <= 20%.

Gates:
  1-6: verdict_8gate (per-year, bootstrap CIs, walk-forward)
  7  : asset-level permutation -- run on V52 (since leverage is invariant to
        sleeve permutation null distribution under linear scaling, V52 gate 7
        result transfers directly to leveraged variant: real_sh / null_mean
        ratio is unchanged; same p-value).
  9  : path-shuffle MC on the leveraged equity
  10 : forward 1y MC on the leveraged equity

Includes leverage variants summary so user can pick the aggressiveness/MDD
tradeoff they prefer.
"""
from __future__ import annotations
import json, sys, time, warnings
from pathlib import Path
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "strategy_lab"))

from strategy_lab.run_v52_hl_gates import build_v52_hl, shuffle_df_lr
from strategy_lab.util.hl_data import load_hl
from strategy_lab.run_leverage_audit import verdict_8gate
from strategy_lab.run_leverage_gates910 import gate9_path_shuffle, gate10_forward_paths

OUT = REPO / "docs/research/phase5_results"
OUT.mkdir(parents=True, exist_ok=True)
BPY = 365.25 * 6
START = "2024-01-12"
END = "2026-04-25"


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


def lever(v52_eq: pd.Series, L: float) -> pd.Series:
    r = v52_eq.pct_change().fillna(0) * L
    r = r.clip(lower=-0.99)
    return (1 + r).cumprod() * 10_000.0


def main():
    t0 = time.time()
    print("=" * 72)
    print("V63 — Full 10-gate battery on V52 leveraged at L=1.75")
    print(f"Window: {START} -> {END}")
    print("=" * 72)

    print("\n[0] Building V52 baseline + V63 candidate (L=1.75)...")
    v52 = build_v52_hl()
    L = 1.75
    cand = lever(v52, L)
    print(f"    V52 (1x): {headline(v52)}")
    print(f"    V63 (L={L}): {headline(cand)}")

    # GATES 1-6
    print(f"\n--- Gates 1-6 on V63 ---")
    g6 = verdict_8gate(cand)
    print(f"   tests_passed: {g6['tests_passed']}")
    for gn, g in g6["gates"].items():
        mark = "PASS" if g["pass"] is True else "FAIL" if g["pass"] is False else "skip"
        print(f"     [{mark:4s}] {gn:38s} -> {g['value']}")

    # GATE 7 on V52 (transfers under linear scaling — leverage is multiplier
    # in returns, so for any L > 0: real_sh(L*v52) = real_sh(v52) and
    # null_sh distribution scales the same, so p-value is invariant)
    print(f"\n--- Gate 7: asset-permutation on V52 (transfers to V63 under L>0) ---")
    real_dfs = {sym: load_hl(sym, "4h", start=START, end=END)
                for sym in ["BTC", "ETH", "AVAX", "SOL", "LINK"]}
    rng = np.random.default_rng(42)
    real_sh_v52 = headline(v52)["sharpe"]
    null_shs = []
    for k in range(20):
        shuffled = {sym: shuffle_df_lr(df, rng) for sym, df in real_dfs.items()}
        try:
            eq_p = build_v52_hl(dfs_override=shuffled)
            null_shs.append(headline(eq_p)["sharpe"])
        except Exception as e:
            print(f"   perm {k}: {type(e).__name__}: {e}")
        if (k + 1) % 5 == 0:
            print(f"     perm {k+1}/20  (elapsed={time.time()-t0:.0f}s)")
    arr = np.asarray(null_shs)
    if len(arr) > 0:
        p_val = float((arr >= real_sh_v52).mean())
        print(f"   Real Sh V52={real_sh_v52:.3f}  Null mean={arr.mean():.3f}  "
              f"99th={np.quantile(arr, 0.99):.3f}  p={p_val:.4f}")
        g7_pass = p_val < 0.01
        print(f"   GATE 7: {'PASS' if g7_pass else 'FAIL'}")
    else:
        p_val = 1.0; g7_pass = False
        print("   GATE 7: FAIL (all permutations errored)")

    # GATE 9
    print(f"\n--- Gate 9: path-shuffle MC on V63 (n=10000) ---")
    g9 = gate9_path_shuffle(cand, n_iter=10_000)
    print(f"   MDD 5th={g9['mdd_p5']*100:.1f}%  median={g9['mdd_p50']*100:.1f}%  "
          f"GATE 9: {'PASS' if g9['gate9_pass'] else 'FAIL'}")

    # GATE 10
    print(f"\n--- Gate 10: forward 1y MC on V63 (n=1000) ---")
    g10 = gate10_forward_paths(cand, n_paths=1000, year_bars=2190)
    print(f"   1y MDD: 5th={g10['mdd_p5']*100:.1f}%  median={g10['mdd_p50']*100:.1f}%")
    print(f"   1y CAGR: 5th={g10['cagr_p5']*100:.1f}%  median={g10['cagr_p50']*100:.1f}%")
    print(f"   P(neg yr)={g10['p_negative_year_pct']}%  P(DD>20%)={g10['p_dd_worse_than_20pct']}%  "
          f"P(DD>30%)={g10['p_dd_worse_than_30pct']}%")
    print(f"   GATE 10: {'PASS' if g10['gate10_pass'] else 'FAIL'}")

    # Leverage menu
    print(f"\n[5] Leverage variant menu (pick aggressiveness):")
    print(f"   {'L':>4} | {'Sharpe':>6} | {'CAGR':>7} | {'MDD':>7} | {'Calmar':>6}")
    for Lv in [1.00, 1.50, 1.75, 2.00, 2.50, 3.00, 3.50]:
        h = headline(lever(v52, Lv))
        marker = " <-- V63 candidate" if Lv == L else ""
        print(f"   {Lv:>4.2f} | {h['sharpe']:>6.2f} | {h['cagr_pct']:>6.2f}% | "
              f"{h['mdd_pct']:>+6.2f}% | {h['calmar']:>6.2f}{marker}")

    # Final scorecard
    g6_pass = sum(1 for g in g6["gates"].values() if g["pass"] is True)
    extras = (1 if g7_pass else 0) + (1 if g9.get("gate9_pass") else 0) + (1 if g10.get("gate10_pass") else 0)
    total = g6_pass + extras
    print(f"\n{'=' * 72}")
    print(f"V63 SCORECARD: gates 1-6: {g6_pass}/6  +  7+9+10: {extras}/3  =  {total}/9")
    print(f"  Headline: CAGR={headline(cand)['cagr_pct']:.2f}%, MDD={headline(cand)['mdd_pct']:.2f}%, "
          f"Sharpe={headline(cand)['sharpe']:.2f}, Calmar={headline(cand)['calmar']:.2f}")
    print(f"  Target met: CAGR >= 50% AND MDD <= 20% -> "
          f"{'YES' if (headline(cand)['cagr_pct']>=50 and headline(cand)['mdd_pct']>=-20) else 'NO'}")
    print(f"{'=' * 72}")

    summary = {
        "candidate": f"V52_x_L={L}",
        "v52_baseline": headline(v52),
        "v63_headline": headline(cand),
        "gates_1_6":    g6,
        "gate7":        {"p_value": p_val, "real_sh": real_sh_v52,
                          "null_mean": float(arr.mean()) if len(arr) else None,
                          "n_perms": int(len(arr)), "pass": g7_pass},
        "gate9":        g9,
        "gate10":       g10,
        "scorecard":    {"g1_6": g6_pass, "g7_9_10": extras, "total_9": total},
    }
    out = OUT / "v63_full_gates.json"
    out.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nWrote: {out}")
    print(f"Total: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
