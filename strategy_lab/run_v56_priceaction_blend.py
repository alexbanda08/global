"""
V56: Blend V52 (deployed champion) with the top inside-bar sleeves at small
weights and measure portfolio-level Sharpe / CAGR / MDD / Calmar.

Hypothesis: low-correlation inside-bar streams will compress blend MDD toward
V52's -5.8% baseline while raising CAGR by 3-5pp (the path that built V52
itself in study 23).

Sleeves blended:
  - V52 (full champion equity, with funding)
  - ibb_both_BTC, D_stacked (vol-HMM x directional exits, with funding)
  - ibb_long_SOL, C_dir (directional exits, with funding)
  - ibb_both_ETH, A_canonical (with funding)

Two blends:
  - blend_85_5_5_5: 0.85 * V52 + 0.05 each IBB sleeve
  - blend_85_15:    0.85 * V52 + 0.15 * invvol(IBB sleeves)

Promotion bar: blend Sharpe > 2.52 AND blend MDD > -10% AND blend Calmar > 5.42
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "strategy_lab"))  # so robustness.py can find `eval.metrics`

from strategy_lab.util.hl_data import load_hl, funding_per_4h_bar
from strategy_lab.eval.perps_simulator_funding import simulate_with_funding
from strategy_lab.eval.perps_simulator_adaptive_exit import REGIME_EXITS_4H
from strategy_lab.regime.hmm_adaptive import fit_regime_model
from strategy_lab.regime.directional_regime import fit_directional_regime
from strategy_lab.strategies.v54_priceaction import sig_inside_bar_break
from strategy_lab.run_v52_hl_gates import build_v52_hl
from strategy_lab.run_leverage_audit import invvol_blend

OUT = REPO / "docs/research/phase5_results"
OUT.mkdir(parents=True, exist_ok=True)
BPY = 6 * 365

EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)
_DEF = (2.0, 10.0, 6.0, 60)


# ----------------------------------------------------------------- helpers
def metrics(eq: pd.Series, label: str) -> dict:
    r = eq.pct_change().dropna()
    if r.std() == 0:
        return {"label": label, "sharpe": 0, "cagr": 0, "mdd": 0, "calmar": 0}
    sh = float(r.mean() / r.std() * np.sqrt(BPY))
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 1e-6)) - 1
    pk = eq.cummax(); mdd = float((eq / pk - 1).min())
    cal = cagr / abs(mdd) if mdd != 0 else 0
    return {"label": label, "sharpe": round(sh, 3),
            "cagr": round(float(cagr) * 100, 2),
            "mdd": round(mdd * 100, 2),
            "calmar": round(float(cal), 3)}


def build_ibb_sleeve_funded(symbol: str, side: str, exit_config: str,
                             btc_regimes: pd.DataFrame) -> pd.Series:
    """Build a single inside-bar sleeve with the requested exit config and HL funding."""
    df = load_hl(symbol, "4h")
    fund = funding_per_4h_bar(symbol, df.index)
    l, s = sig_inside_bar_break(df)
    if side == "long":
        s = pd.Series(False, index=df.index)
    elif side == "short":
        l = pd.Series(False, index=df.index)

    if exit_config == "A_canonical":
        _, eq = simulate_with_funding(df, l, s, fund, **EXIT_4H)
        return eq

    if exit_config == "C_dir":
        if side == "long":
            prof = {"Bull": (2.0, 14, 8, 80), "Sideline": _DEF, "Bear": (2.5, 6, 2.5, 24),
                    "MedVol": _DEF, "Uncertain": _DEF, "Warming": _DEF}
        else:
            prof = {"Bull": (2.5, 6, 2.5, 24), "Sideline": _DEF, "Bear": (2.0, 14, 8, 80),
                    "MedVol": _DEF, "Uncertain": _DEF, "Warming": _DEF}
        labels = btc_regimes["label"].reindex(df.index).ffill().fillna("Sideline")
        _, eq = simulate_with_funding(df, l, s, fund, regime_labels=labels, regime_exits=prof)
        return eq

    if exit_config == "D_stacked":
        _, vol_reg = fit_regime_model(df, train_frac=0.30)
        vol_lbl = vol_reg["label"].reindex(df.index).ffill().fillna("MedVol")
        dir_lbl = btc_regimes["label"].reindex(df.index).ffill().fillna("Sideline")
        stacked_lbl = (dir_lbl + "_" + vol_lbl).astype(object)

        if side == "long":
            dir_prof = {"Bull": (2.0, 14, 8, 80), "Sideline": _DEF, "Bear": (2.5, 6, 2.5, 24)}
        else:
            dir_prof = {"Bull": (2.5, 6, 2.5, 24), "Sideline": _DEF, "Bear": (2.0, 14, 8, 80)}
        cells = {"MedVol": _DEF}
        for d, (sld, tpd, trd, mhd) in dir_prof.items():
            for v, (slv, tpv, trv, mhv) in REGIME_EXITS_4H.items():
                cells[f"{d}_{v}"] = (max(sld, slv), min(tpd, tpv), min(trd, trv), min(mhd, mhv))
        _, eq = simulate_with_funding(df, l, s, fund, regime_labels=stacked_lbl, regime_exits=cells)
        return eq

    raise ValueError(exit_config)


def blend_returns(eqs: dict, weights: dict) -> pd.Series:
    """Weighted-sum blend on common index."""
    common = None
    for k, eq in eqs.items():
        idx = eq.index
        common = idx if common is None else common.intersection(idx)
    rets = {k: eqs[k].reindex(common).pct_change().fillna(0) for k in eqs}
    blend = sum(weights[k] * rets[k] for k in eqs)
    return (1 + blend).cumprod() * 10_000.0


# ----------------------------------------------------------------- main
def main():
    print("=" * 72)
    print("V56: V52 + Price-Action Blend Test")
    print("=" * 72)

    print("\n[1] Building V52 reference equity (full champion)...")
    v52_eq = build_v52_hl()
    print(f"    V52: {len(v52_eq)} bars  {v52_eq.index[0]} -> {v52_eq.index[-1]}")
    m_v52 = metrics(v52_eq, "V52_baseline")
    print(f"    {m_v52}")

    print("\n[2] Building global directional regime (BTC)...")
    btc = load_hl("BTC", "4h")
    _, btc_regimes = fit_directional_regime(btc, verbose=False)

    print("\n[3] Building inside-bar sleeves at best configs (with funding)...")
    sleeves = {
        "ibb_both_BTC_Dstacked": ("BTC", "both",  "D_stacked"),
        "ibb_long_SOL_Cdir":     ("SOL", "long",  "C_dir"),
        "ibb_both_ETH_canon":    ("ETH", "both",  "A_canonical"),
    }
    sleeve_eqs = {}
    sleeve_metrics = []
    for name, (sym, side, cfg) in sleeves.items():
        eq = build_ibb_sleeve_funded(sym, side, cfg, btc_regimes)
        sleeve_eqs[name] = eq
        m = metrics(eq, name)
        sleeve_metrics.append(m)
        print(f"    {m}")

    # Correlation matrix vs V52
    print("\n[4] Correlations vs V52 (per-bar returns):")
    common = v52_eq.index
    for k, eq in sleeve_eqs.items():
        common = common.intersection(eq.index)
    v52_r = v52_eq.reindex(common).pct_change().fillna(0)
    corrs = {}
    for k, eq in sleeve_eqs.items():
        rk = eq.reindex(common).pct_change().fillna(0)
        rho = float(rk.corr(v52_r))
        corrs[k] = round(rho, 3)
        print(f"    rho({k}) = {rho:+.3f}")

    # Blend A: V52 85% + 5% each IBB sleeve
    print("\n[5] Blend A: 0.85*V52 + 0.05 each IBB sleeve")
    eqs_A = {"V52": v52_eq, **sleeve_eqs}
    weights_A = {"V52": 0.85, **{k: 0.05 for k in sleeve_eqs}}
    blend_A = blend_returns(eqs_A, weights_A)
    m_A = metrics(blend_A, "blend_85_5_5_5")
    print(f"    {m_A}")

    # Blend B: V52 85% + 15% invvol(IBB)
    print("\n[6] Blend B: 0.85*V52 + 0.15 * invvol(IBB sleeves)")
    common_ibb = sleeve_eqs[list(sleeve_eqs)[0]].index
    for eq in sleeve_eqs.values():
        common_ibb = common_ibb.intersection(eq.index)
    invvol_ibb = invvol_blend(
        {k: eq.reindex(common_ibb) for k, eq in sleeve_eqs.items()}, window=500,
    )
    eqs_B = {"V52": v52_eq, "IBB_invvol": invvol_ibb}
    weights_B = {"V52": 0.85, "IBB_invvol": 0.15}
    blend_B = blend_returns(eqs_B, weights_B)
    m_B = metrics(blend_B, "blend_85_invvol15")
    print(f"    {m_B}")

    # Blend C: V52 90% + 10% invvol(IBB) -- conservative variant
    print("\n[7] Blend C: 0.90*V52 + 0.10 * invvol(IBB sleeves)")
    weights_C = {"V52": 0.90, "IBB_invvol": 0.10}
    blend_C = blend_returns(eqs_B, weights_C)
    m_C = metrics(blend_C, "blend_90_invvol10")
    print(f"    {m_C}")

    # Comparison table
    print("\n" + "=" * 72)
    print("HEAD-TO-HEAD vs V52 baseline")
    print("=" * 72)
    base = m_v52
    for m in [m_A, m_B, m_C]:
        d_sh = m["sharpe"] - base["sharpe"]
        d_cagr = m["cagr"] - base["cagr"]
        d_mdd = m["mdd"] - base["mdd"]   # less negative = better
        d_cal = m["calmar"] - base["calmar"]
        verdict = "PROMO" if (m["sharpe"] > base["sharpe"] and m["mdd"] > base["mdd"]
                              and m["calmar"] > base["calmar"]) else "no"
        print(f"  {m['label']:<22} Sh={m['sharpe']:>5.2f} (d={d_sh:+.2f})  "
              f"CAGR={m['cagr']:>6.2f}% (d={d_cagr:+.2f})  "
              f"MDD={m['mdd']:>6.2f}% (d={d_mdd:+.2f})  "
              f"Calmar={m['calmar']:>5.2f} (d={d_cal:+.2f})  [{verdict}]")
    print(f"  {'V52_baseline':<22} Sh={base['sharpe']:>5.2f}            "
          f"CAGR={base['cagr']:>6.2f}%            "
          f"MDD={base['mdd']:>6.2f}%            "
          f"Calmar={base['calmar']:>5.2f}")

    # Hard promotion gate (V52 deployment-replacement bar)
    print("\nPROMOTION GATE: Sh > 2.52 AND MDD > -10% AND Calmar > 5.42")
    for m in [m_A, m_B, m_C]:
        passed = m["sharpe"] > 2.52 and m["mdd"] > -10.0 and m["calmar"] > 5.42
        print(f"  {m['label']:<22}  {'PASS' if passed else 'FAIL'}")

    summary = {
        "v52_baseline": m_v52,
        "sleeves": sleeve_metrics,
        "correlations_vs_v52": corrs,
        "blend_A_85_5_5_5": m_A,
        "blend_B_85_invvol15": m_B,
        "blend_C_90_invvol10": m_C,
    }
    out = OUT / "v56_blend.json"
    out.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nWrote: {out}")


if __name__ == "__main__":
    main()
