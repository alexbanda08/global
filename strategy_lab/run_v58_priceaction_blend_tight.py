"""
V58: Same as V56 but with tightened IBB exits.
Goal: compress sleeve MDDs from -29..-35% toward -20%, push blend Calmar > 5.42.

Variants tested per sleeve (with HL funding):
  - tightSL:  scale all SL atr by 0.75 (2.0 -> 1.5 ; 2.5 -> 1.875)
  - tightTrail: scale trail atr by 0.65 (6 -> 3.9, 8 -> 5.2)
  - tightBoth: both scalings combined

Blend recipes tested (always vs V52 baseline):
  - 0.85 V52 + 0.05 each (3 sleeves) -- 5/5/5
  - 0.90 V52 + 0.10 invvol(IBB)
  - 0.92 V52 + 0.08 invvol(IBB)  (more conservative)
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "strategy_lab"))

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


def _scale(profile: tuple, sl_mult: float = 1.0, trail_mult: float = 1.0) -> tuple:
    sl, tp, trail, hold = profile
    return (sl * sl_mult, tp, trail * trail_mult, hold)


def _scale_dict(d: dict, sl_mult: float, trail_mult: float) -> dict:
    return {k: _scale(v, sl_mult, trail_mult) for k, v in d.items()}


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


def build_ibb_sleeve(symbol: str, side: str, exit_config: str,
                      btc_regimes: pd.DataFrame,
                      sl_mult: float, trail_mult: float) -> pd.Series:
    df = load_hl(symbol, "4h")
    fund = funding_per_4h_bar(symbol, df.index)
    l, s = sig_inside_bar_break(df)
    if side == "long":
        s = pd.Series(False, index=df.index)
    elif side == "short":
        l = pd.Series(False, index=df.index)

    canon = (2.0 * sl_mult, 10.0, 6.0 * trail_mult, 60)

    if exit_config == "A_canonical":
        sl, tp, tr, mh = canon
        _, eq = simulate_with_funding(df, l, s, fund,
                                       tp_atr=tp, sl_atr=sl, trail_atr=tr, max_hold=mh)
        return eq

    base_long = {"Bull": (2.0, 14, 8, 80), "Sideline": (2.0, 10, 6, 60),
                 "Bear": (2.5, 6, 2.5, 24)}
    base_short = {"Bull": (2.5, 6, 2.5, 24), "Sideline": (2.0, 10, 6, 60),
                  "Bear": (2.0, 14, 8, 80)}
    base_long = _scale_dict(base_long, sl_mult, trail_mult)
    base_short = _scale_dict(base_short, sl_mult, trail_mult)
    fallback = {"MedVol": canon, "Uncertain": canon, "Warming": canon}

    if exit_config == "C_dir":
        prof = (base_long if side == "long" else base_short) | fallback
        labels = btc_regimes["label"].reindex(df.index).ffill().fillna("Sideline")
        _, eq = simulate_with_funding(df, l, s, fund,
                                       regime_labels=labels, regime_exits=prof)
        return eq

    if exit_config == "D_stacked":
        _, vol_reg = fit_regime_model(df, train_frac=0.30)
        vol_lbl = vol_reg["label"].reindex(df.index).ffill().fillna("MedVol")
        dir_lbl = btc_regimes["label"].reindex(df.index).ffill().fillna("Sideline")
        stacked_lbl = (dir_lbl + "_" + vol_lbl).astype(object)
        dir_prof = base_long if side == "long" else base_short
        vol_prof = _scale_dict(REGIME_EXITS_4H, sl_mult, trail_mult)
        cells = {"MedVol": canon}
        for d, (sld, tpd, trd, mhd) in dir_prof.items():
            for v, (slv, tpv, trv, mhv) in vol_prof.items():
                cells[f"{d}_{v}"] = (max(sld, slv), min(tpd, tpv),
                                       min(trd, trv), min(mhd, mhv))
        _, eq = simulate_with_funding(df, l, s, fund,
                                       regime_labels=stacked_lbl, regime_exits=cells)
        return eq
    raise ValueError(exit_config)


def blend_returns(eqs: dict, weights: dict) -> pd.Series:
    common = None
    for eq in eqs.values():
        common = eq.index if common is None else common.intersection(eq.index)
    rets = {k: eqs[k].reindex(common).pct_change().fillna(0) for k in eqs}
    blend = sum(weights[k] * rets[k] for k in eqs)
    return (1 + blend).cumprod() * 10_000.0


def main():
    print("=" * 72)
    print("V58: Tight-SL IBB blend test")
    print("=" * 72)

    print("\n[1] Building V52 baseline...")
    v52 = build_v52_hl()
    m_v52 = metrics(v52, "V52_baseline")
    print(f"    {m_v52}")

    print("\n[2] BTC directional regime...")
    _, btc_reg = fit_directional_regime(load_hl("BTC", "4h"), verbose=False)

    SLEEVE_DEFS = [
        ("BTC_Dstacked", "BTC", "both", "D_stacked"),
        ("SOL_Cdir",     "SOL", "long", "C_dir"),
        ("ETH_canon",    "ETH", "both", "A_canonical"),
    ]

    VARIANTS = [
        ("baseline", 1.00, 1.00),
        ("tightSL",  0.75, 1.00),
        ("tightTrail", 1.00, 0.65),
        ("tightBoth", 0.75, 0.65),
    ]

    print("\n[3] Sleeve metrics by tightness variant:")
    sleeve_rows = []
    eqs_by_variant: dict[str, dict[str, pd.Series]] = {}
    for vname, sl_m, tr_m in VARIANTS:
        eqs_by_variant[vname] = {}
        for nm, sym, side, cfg in SLEEVE_DEFS:
            eq = build_ibb_sleeve(sym, side, cfg, btc_reg, sl_m, tr_m)
            eqs_by_variant[vname][nm] = eq
            m = metrics(eq, f"{nm}_{vname}")
            sleeve_rows.append(m)
            print(f"    {m}")

    print("\n[4] Blends per variant (vs V52 baseline):")
    print(f"    BASELINE V52: Sh={m_v52['sharpe']:.2f}  MDD={m_v52['mdd']:.2f}%  Calmar={m_v52['calmar']:.2f}")
    blend_rows = []
    for vname in [v[0] for v in VARIANTS]:
        sl_eqs = eqs_by_variant[vname]
        # Common index for invvol
        common_ibb = list(sl_eqs.values())[0].index
        for eq in sl_eqs.values():
            common_ibb = common_ibb.intersection(eq.index)
        invvol_ibb = invvol_blend(
            {k: eq.reindex(common_ibb) for k, eq in sl_eqs.items()}, window=500,
        )
        # Three blend recipes
        for recipe_lbl, eqs_in, weights in [
            ("85_5_5_5",
             {"V52": v52, **sl_eqs},
             {"V52": 0.85, **{k: 0.05 for k in sl_eqs}}),
            ("90_10invvol",
             {"V52": v52, "IBB": invvol_ibb},
             {"V52": 0.90, "IBB": 0.10}),
            ("92_08invvol",
             {"V52": v52, "IBB": invvol_ibb},
             {"V52": 0.92, "IBB": 0.08}),
        ]:
            blend_eq = blend_returns(eqs_in, weights)
            m = metrics(blend_eq, f"{vname}_{recipe_lbl}")
            promo = (m["sharpe"] > m_v52["sharpe"]
                     and m["mdd"] > m_v52["mdd"]
                     and m["calmar"] > m_v52["calmar"])
            d_sh = m["sharpe"] - m_v52["sharpe"]
            d_mdd = m["mdd"] - m_v52["mdd"]
            d_cal = m["calmar"] - m_v52["calmar"]
            tag = "PROMO" if promo else "no"
            print(f"      {m['label']:<28}  Sh={m['sharpe']:>5.2f}(d={d_sh:+.2f})  "
                  f"MDD={m['mdd']:>6.2f}%(d={d_mdd:+.2f})  "
                  f"Calmar={m['calmar']:>5.2f}(d={d_cal:+.2f})  [{tag}]")
            blend_rows.append({**m, "promo": promo,
                                "d_sh": d_sh, "d_mdd": d_mdd, "d_cal": d_cal})

    promos = [r for r in blend_rows if r["promo"]]
    print(f"\nPROMOS: {len(promos)}/{len(blend_rows)}")
    for p in promos:
        print(f"  {p['label']}: Sh={p['sharpe']:.2f}  MDD={p['mdd']:.2f}%  Calmar={p['calmar']:.2f}")

    out = OUT / "v58_blend_tight.json"
    out.write_text(json.dumps({
        "v52_baseline": m_v52,
        "sleeve_rows": sleeve_rows,
        "blend_rows": blend_rows,
        "promos": promos,
    }, indent=2, default=str))
    print(f"\nWrote: {out}")


if __name__ == "__main__":
    main()
