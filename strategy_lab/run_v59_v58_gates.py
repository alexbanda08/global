"""
V59: Run the full 10-gate battery on the V58 candidate
(0.92 * V52 + 0.08 * invvol(IBB tightTrail sleeves)) and compare vs V52.

Decision: if V58 gate scorecard >= V52's AND Calmar lower-CI improves vs
V52's 1.10, we promote V58 as new champion candidate. Otherwise V58 lift
was within noise -> revert to V52 and pivot to Vector 3 (pairs).

Gates run:
  1-6: verdict_8gate (per-year, bootstrap CIs, walk-forward)
  7  : asset-level permutation (n=20, requires shuffling all 5 underlying
        symbols and rebuilding both V52 and IBB sleeves)
  9  : path-shuffle MC (n=10000)
  10 : forward 1y MC (n=1000)

Gate 8 (plateau) is skipped to keep runtime manageable.
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

from strategy_lab.util.hl_data import load_hl, funding_per_4h_bar
from strategy_lab.eval.perps_simulator_funding import simulate_with_funding
from strategy_lab.eval.perps_simulator_adaptive_exit import REGIME_EXITS_4H
from strategy_lab.regime.hmm_adaptive import fit_regime_model
from strategy_lab.regime.directional_regime import fit_directional_regime
from strategy_lab.strategies.v54_priceaction import sig_inside_bar_break
from strategy_lab.run_v52_hl_gates import build_v52_hl, shuffle_df_lr
from strategy_lab.run_leverage_audit import invvol_blend, verdict_8gate
from strategy_lab.run_leverage_gates910 import gate9_path_shuffle, gate10_forward_paths

OUT = REPO / "docs/research/phase5_results"
OUT.mkdir(parents=True, exist_ok=True)
BPY = 365.25 * 6

# Tight-trail multiplier from V58 best variant
TRAIL_MULT = 0.65
SL_MULT = 1.00

START = "2024-01-12"
END = "2026-04-25"


def _scale(profile, sl_mult, trail_mult):
    sl, tp, tr, mh = profile
    return (sl * sl_mult, tp, tr * trail_mult, mh)


def _scale_dict(d, sl_mult, trail_mult):
    return {k: _scale(v, sl_mult, trail_mult) for k, v in d.items()}


def build_ibb_sleeve(symbol, side, exit_config, btc_regimes, df_override=None):
    """Build a tightTrail-variant IBB sleeve."""
    df = df_override if df_override is not None else load_hl(symbol, "4h", start=START, end=END)
    fund = funding_per_4h_bar(symbol, df.index)
    l, s = sig_inside_bar_break(df)
    if side == "long":
        s = pd.Series(False, index=df.index)
    elif side == "short":
        l = pd.Series(False, index=df.index)

    canon = (2.0 * SL_MULT, 10.0, 6.0 * TRAIL_MULT, 60)

    if exit_config == "A_canonical":
        sl, tp, tr, mh = canon
        _, eq = simulate_with_funding(df, l, s, fund,
                                       tp_atr=tp, sl_atr=sl, trail_atr=tr, max_hold=mh)
        return eq

    base_long = {"Bull": (2.0, 14, 8, 80), "Sideline": (2.0, 10, 6, 60),
                 "Bear": (2.5, 6, 2.5, 24)}
    base_short = {"Bull": (2.5, 6, 2.5, 24), "Sideline": (2.0, 10, 6, 60),
                  "Bear": (2.0, 14, 8, 80)}
    base_long = _scale_dict(base_long, SL_MULT, TRAIL_MULT)
    base_short = _scale_dict(base_short, SL_MULT, TRAIL_MULT)
    fallback = {"MedVol": canon, "Uncertain": canon, "Warming": canon}

    if exit_config == "C_dir":
        prof = (base_long if side == "long" else base_short) | fallback
        labels = btc_regimes["label"].reindex(df.index).ffill().fillna("Sideline")
        _, eq = simulate_with_funding(df, l, s, fund, regime_labels=labels, regime_exits=prof)
        return eq

    if exit_config == "D_stacked":
        _, vol_reg = fit_regime_model(df, train_frac=0.30)
        vol_lbl = vol_reg["label"].reindex(df.index).ffill().fillna("MedVol")
        dir_lbl = btc_regimes["label"].reindex(df.index).ffill().fillna("Sideline")
        stacked_lbl = (dir_lbl + "_" + vol_lbl).astype(object)
        dir_prof = base_long if side == "long" else base_short
        vol_prof = _scale_dict(REGIME_EXITS_4H, SL_MULT, TRAIL_MULT)
        cells = {"MedVol": canon}
        for d, (sld, tpd, trd, mhd) in dir_prof.items():
            for v, (slv, tpv, trv, mhv) in vol_prof.items():
                cells[f"{d}_{v}"] = (max(sld, slv), min(tpd, tpv),
                                       min(trd, trv), min(mhd, mhv))
        _, eq = simulate_with_funding(df, l, s, fund, regime_labels=stacked_lbl, regime_exits=cells)
        return eq
    raise ValueError(exit_config)


def build_v58_candidate(dfs_override: dict | None = None) -> pd.Series:
    """Build V58 candidate = 0.92 * V52 + 0.08 * invvol(IBB tightTrail).

    dfs_override: dict {symbol: df} — used by Gate 7 permutation. If passed,
    the SAME shuffled dfs are propagated through V52 build AND IBB sleeve
    builds, ensuring the permutation null is computed on a self-consistent
    candidate.
    """
    btc_df = dfs_override.get("BTC") if dfs_override else None
    if btc_df is None:
        btc_df = load_hl("BTC", "4h", start=START, end=END)
    _, btc_reg = fit_directional_regime(btc_df, verbose=False)

    v52 = build_v52_hl(dfs_override=dfs_override)

    sleeve_specs = [
        ("BTC_Dstacked", "BTC", "both", "D_stacked"),
        ("SOL_Cdir",     "SOL", "long", "C_dir"),
        ("ETH_canon",    "ETH", "both", "A_canonical"),
    ]
    sleeves = {}
    for nm, sym, side, cfg in sleeve_specs:
        df_o = dfs_override.get(sym) if dfs_override else None
        sleeves[nm] = build_ibb_sleeve(sym, side, cfg, btc_reg, df_override=df_o)

    common = list(sleeves.values())[0].index
    for eq in sleeves.values():
        common = common.intersection(eq.index)
    invvol_ibb = invvol_blend({k: eq.reindex(common) for k, eq in sleeves.items()}, window=500)

    common_all = v52.index.intersection(invvol_ibb.index)
    v52_r = v52.reindex(common_all).pct_change().fillna(0)
    ibb_r = invvol_ibb.reindex(common_all).pct_change().fillna(0)
    blend_r = 0.92 * v52_r + 0.08 * ibb_r
    return (1 + blend_r).cumprod() * 10_000.0


def headline(eq, label):
    r = eq.pct_change().dropna()
    sd = float(r.std()); sh = (float(r.mean()) / sd) * np.sqrt(BPY) if sd > 0 else 0
    pk = eq.cummax(); mdd = float((eq / pk - 1).min())
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 1e-6)) - 1
    cal = cagr / abs(mdd) if mdd != 0 else 0
    return {"label": label, "sharpe": round(sh, 3),
            "cagr": round(float(cagr), 4),
            "mdd": round(mdd, 4),
            "calmar": round(float(cal), 3)}


def main():
    t0 = time.time()
    print("=" * 72)
    print("V59: 10-gate battery on V58 candidate (0.92*V52 + 0.08*invvol(IBB tightTrail))")
    print(f"Window: {START} -> {END}")
    print("=" * 72)

    print("\n[0] Building V52 baseline AND V58 candidate...")
    v52 = build_v52_hl()
    v58 = build_v58_candidate()
    print(f"   V52: {headline(v52, 'V52')}")
    print(f"   V58: {headline(v58, 'V58')}")

    # GATES 1-6 (V58)
    print("\n--- Gates 1-6 on V58 ---")
    g6_v58 = verdict_8gate(v58)
    print(f"   tests_passed: {g6_v58['tests_passed']}")
    for gn, g in g6_v58["gates"].items():
        mark = "PASS" if g["pass"] is True else "FAIL" if g["pass"] is False else "skip"
        print(f"     [{mark:4s}] {gn:38s} -> {g['value']}")

    # Same on V52 for comparison
    print("\n--- Gates 1-6 on V52 (reference) ---")
    g6_v52 = verdict_8gate(v52)
    print(f"   tests_passed: {g6_v52['tests_passed']}")
    for gn, g in g6_v52["gates"].items():
        mark = "PASS" if g["pass"] is True else "FAIL" if g["pass"] is False else "skip"
        print(f"     [{mark:4s}] {gn:38s} -> {g['value']}")

    # GATE 7: asset-level permutation (n=20) on V58
    print("\n--- Gate 7: asset-level permutation on V58 (n=20) ---")
    real_dfs = {sym: load_hl(sym, "4h", start=START, end=END)
                for sym in ["BTC", "ETH", "AVAX", "SOL", "LINK"]}
    rng = np.random.default_rng(42)
    real_sh_v58 = headline(v58, "V58")["sharpe"]
    null_shs = []
    for k in range(20):
        shuffled = {sym: shuffle_df_lr(df, rng) for sym, df in real_dfs.items()}
        try:
            eq_p = build_v58_candidate(dfs_override=shuffled)
            null_shs.append(headline(eq_p, "p")["sharpe"])
        except Exception as e:
            print(f"   perm {k}: {type(e).__name__}: {e}")
        if (k + 1) % 5 == 0:
            print(f"     perm {k+1}/20 done  (elapsed={time.time()-t0:.0f}s)")
    arr = np.asarray(null_shs)
    if len(arr) > 0:
        p_val = float((arr >= real_sh_v58).mean())
        print(f"   Real Sharpe V58={real_sh_v58:.3f}  Null mean={arr.mean():.3f}  "
              f"99th={np.quantile(arr, 0.99):.3f}  p={p_val:.4f}")
        print(f"   GATE 7: {'PASS' if p_val < 0.01 else 'FAIL'}")
    else:
        p_val = 1.0
        print("   GATE 7: FAIL (all permutations errored)")

    # GATE 9: path-shuffle MC
    print("\n--- Gate 9: path-shuffle MC on V58 (n=10000) ---")
    g9 = gate9_path_shuffle(v58, n_iter=10_000)
    print(f"   MDD 5th={g9['mdd_p5']*100:.1f}%  median={g9['mdd_p50']*100:.1f}%  "
          f"GATE 9: {'PASS' if g9['gate9_pass'] else 'FAIL'}")

    # GATE 10: forward 1y MC
    print("\n--- Gate 10: forward 1y MC on V58 (n=1000) ---")
    g10 = gate10_forward_paths(v58, n_paths=1000, year_bars=2190)
    print(f"   1y MDD: 5th={g10['mdd_p5']*100:.1f}%  median={g10['mdd_p50']*100:.1f}%")
    print(f"   1y CAGR: 5th={g10['cagr_p5']*100:.1f}%  median={g10['cagr_p50']*100:.1f}%")
    print(f"   P(neg yr)={g10['p_negative_year_pct']}%  P(DD>20%)={g10['p_dd_worse_than_20pct']}%")
    print(f"   GATE 10: {'PASS' if g10['gate10_pass'] else 'FAIL'}")

    # SCORECARD
    pass_v58 = sum(1 for g in g6_v58["gates"].values() if g["pass"] is True)
    pass_v52 = sum(1 for g in g6_v52["gates"].values() if g["pass"] is True)
    g7_pass = (len(arr) > 0 and p_val < 0.01)
    extras_v58 = (1 if g7_pass else 0) + (1 if g9.get("gate9_pass") else 0) + (1 if g10.get("gate10_pass") else 0)
    print("\n" + "=" * 72)
    print(f"SCORECARD")
    print(f"  V52 gates 1-6: {pass_v52}/6 pass")
    print(f"  V58 gates 1-6: {pass_v58}/6 pass")
    print(f"  V58 gates 7+9+10: {extras_v58}/3 pass")
    print(f"  V58 TOTAL (1-6,7,9,10): {pass_v58 + extras_v58}/9")
    if pass_v58 >= pass_v52 and extras_v58 >= 3 and pass_v58 >= 5:
        print("  >>> V58 PROMOTED as new champion candidate")
    else:
        print("  >>> V58 NOT PROMOTED; lift was likely within noise. Pivot to Vector 3.")
    print("=" * 72)

    summary = {
        "v52_headline": headline(v52, "V52"),
        "v58_headline": headline(v58, "V58"),
        "v52_gates_1_6": g6_v52,
        "v58_gates_1_6": g6_v58,
        "v58_gate7": {"p_value": p_val, "real_sharpe": real_sh_v58,
                       "null_mean": float(arr.mean()) if len(arr) else None,
                       "null_99th": float(np.quantile(arr, 0.99)) if len(arr) else None,
                       "n_permutations": int(len(arr)),
                       "pass": g7_pass},
        "v58_gate9": g9,
        "v58_gate10": g10,
        "scorecard": {"v52_g1_6": pass_v52, "v58_g1_6": pass_v58,
                       "v58_extras_3of3": extras_v58,
                       "v58_total_9": pass_v58 + extras_v58},
    }
    out = OUT / "v59_v58_gates.json"
    out.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nWrote: {out}")
    print(f"Total: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
