"""
V55: Pair the price-action sleeves with V41 (vol-HMM) and the new
directional-regime (Bull/Bear/Sideline) adaptive exits.

Goal: see if MDD compresses from -34..-44% (canonical EXIT_4H) toward V52's
-5.8% target while preserving the standalone Sharpe.

Configs tested per sleeve:
  A. canonical  EXIT_4H (baseline, from V54 scan)
  B. V41 vol-HMM adaptive exits
  C. directional-regime adaptive exits (custom profiles)
  D. directional + vol stacked: tighter exit if HighVol AND Bear, looser if LowVol AND Bull

Sleeves (top from V54 + 2 short-side hedges with negative rho_proxy):
  inside_bar_break_both_ETH
  inside_bar_break_both_BTC
  inside_bar_break_long_SOL
  inside_bar_break_short_ETH      (rho_proxy = -0.26)
  inside_bar_break_short_AVAX     (rho_proxy = -0.25)
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from strategy_lab.util.hl_data import load_hl
from strategy_lab.eval.perps_simulator import simulate as sim_canonical, compute_metrics
from strategy_lab.eval.perps_simulator_adaptive_exit import (
    simulate_adaptive_exit, REGIME_EXITS_4H,
)
from strategy_lab.regime.hmm_adaptive import fit_regime_model
from strategy_lab.regime.directional_regime import fit_directional_regime
from strategy_lab.strategies.v54_priceaction import sig_inside_bar_break

OUT = REPO / "docs/research/phase5_results"
OUT.mkdir(parents=True, exist_ok=True)
BPY = 6 * 365  # 4h bars per year

EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)

# Directional-regime exit profiles. Format: (sl_atr, tp_atr, trail_atr, max_hold)
_DEF = (2.0, 10.0, 6.0, 60)  # canonical fallback
DIR_EXITS_LONG = {
    "Bull":     (2.0, 14.0, 8.0, 80),
    "Sideline": _DEF,
    "Bear":     (2.5,  6.0, 2.5, 24),
    "MedVol":   _DEF,  # simulator default-key fallback
    "Uncertain": _DEF, "Warming": _DEF,
}
DIR_EXITS_SHORT = {
    "Bull":     (2.5,  6.0, 2.5, 24),
    "Sideline": _DEF,
    "Bear":     (2.0, 14.0, 8.0, 80),
    "MedVol":   _DEF,
    "Uncertain": _DEF, "Warming": _DEF,
}


# ----------------------------------------------------------------- sleeves
SLEEVES = [
    ("ibb_both_ETH",   "ETH",  "both"),
    ("ibb_both_BTC",   "BTC",  "both"),
    ("ibb_long_SOL",   "SOL",  "long"),
    ("ibb_short_ETH",  "ETH",  "short"),
    ("ibb_short_AVAX", "AVAX", "short"),
]


def get_signals(df: pd.DataFrame, side: str):
    l, s = sig_inside_bar_break(df)
    if side == "long":
        return l, pd.Series(False, index=df.index)
    if side == "short":
        return pd.Series(False, index=df.index), s
    return l, s


def run_canonical(df, l, s, label):
    trades, eq = sim_canonical(df, l, s,
        risk_per_trade=0.03, leverage_cap=4.0, **EXIT_4H,
    )
    return compute_metrics(label, eq, trades, bars_per_year=BPY), eq, trades


def run_vol_hmm(df, l, s, label):
    _, regimes = fit_regime_model(df, train_frac=0.30)
    reg_labels = regimes["label"].reindex(df.index).ffill().fillna("MedVol")
    trades, eq = simulate_adaptive_exit(df, l, s, reg_labels,
        regime_exits=REGIME_EXITS_4H,
        risk_per_trade=0.03, leverage_cap=4.0,
    )
    return compute_metrics(label, eq, trades, bars_per_year=BPY), eq, trades


def run_directional(df, btc_regimes, l, s, side, label):
    """Use BTC's directional regime as the global label.
    side selects which exit-profile dict to use."""
    reg_labels = btc_regimes["label"].reindex(df.index).ffill().fillna("Sideline")
    if side == "long":
        prof = DIR_EXITS_LONG
    elif side == "short":
        prof = DIR_EXITS_SHORT
    else:
        # both: pick the side-aware profile by majority -- here we average to long
        prof = DIR_EXITS_LONG
    trades, eq = simulate_adaptive_exit(df, l, s, reg_labels,
        regime_exits=prof,
        risk_per_trade=0.03, leverage_cap=4.0,
    )
    return compute_metrics(label, eq, trades, bars_per_year=BPY), eq, trades


def run_stacked(df, btc_regimes, l, s, side, label):
    """Stacked exit: combine vol-regime + dir-regime into 9 cells.
    Cell rule: tightest trail/TP wins (tight if HighVol OR Bear-vs-long etc.)"""
    _, vol_reg = fit_regime_model(df, train_frac=0.30)
    vol_lbl = vol_reg["label"].reindex(df.index).ffill().fillna("MedVol")
    dir_lbl = btc_regimes["label"].reindex(df.index).ffill().fillna("Sideline")

    # Build a synthetic regime label per bar like "{dir}_{vol}" and a stacked profile dict
    stacked_lbl = (dir_lbl + "_" + vol_lbl).astype(object)

    if side == "long":
        dir_prof = DIR_EXITS_LONG
    else:
        dir_prof = DIR_EXITS_SHORT

    cells = {"MedVol": _DEF}  # simulator fallback key
    for d, (sld, tpd, trd, mhd) in dir_prof.items():
        for v, (slv, tpv, trv, mhv) in REGIME_EXITS_4H.items():
            cells[f"{d}_{v}"] = (
                max(sld, slv),
                min(tpd, tpv),
                min(trd, trv),
                min(mhd, mhv),
            )
    trades, eq = simulate_adaptive_exit(df, l, s, stacked_lbl,
        regime_exits=cells,
        risk_per_trade=0.03, leverage_cap=4.0,
    )
    return compute_metrics(label, eq, trades, bars_per_year=BPY), eq, trades


# ----------------------------------------------------------------- main
def main():
    print("=" * 72)
    print("V55: Price-Action Sleeves x Adaptive Exits")
    print("=" * 72)

    print("\n[1] Loading BTC for global directional regime...")
    btc = load_hl("BTC", "4h")
    _, btc_regimes = fit_directional_regime(btc, verbose=False)
    dist = btc_regimes["label"].value_counts(normalize=True).to_dict()
    print(f"    Dir regime dist: {dist}")

    rows = []
    for lbl, sym, side in SLEEVES:
        print(f"\n>>> {lbl} (sym={sym} side={side})")
        df = load_hl(sym, "4h")
        l, s = get_signals(df, side)

        configs = [
            ("A_canonical", lambda: run_canonical(df, l, s, lbl)),
            ("B_vol_hmm",   lambda: run_vol_hmm(df, l, s, lbl)),
            ("C_dir",       lambda: run_directional(df, btc_regimes, l, s, side, lbl)),
            ("D_stacked",   lambda: run_stacked(df, btc_regimes, l, s, side, lbl)),
        ]

        for cname, fn in configs:
            m, eq, tr = fn()
            row = {
                "sleeve": lbl, "config": cname,
                "n":      int(m["n_trades"]),
                "sharpe": round(float(m["sharpe"]), 3),
                "cagr":   round(float(m["cagr"]) * 100, 2),
                "mdd":    round(float(m.get("max_dd", 0)) * 100, 2),
                "calmar": round(float(m.get("calmar", 0)), 3),
            }
            rows.append(row)
            print(f"    {cname:<14}  n={row['n']:>3}  Sh={row['sharpe']:>5.2f}  "
                  f"CAGR={row['cagr']:>6.2f}%  MDD={row['mdd']:>6.2f}%  Calmar={row['calmar']:>5.2f}")

    # Compare configs head-to-head
    print("\n" + "=" * 72)
    print("HEAD-TO-HEAD: BEST CONFIG PER SLEEVE (by Calmar)")
    print("=" * 72)
    by_sleeve = {}
    for r in rows:
        by_sleeve.setdefault(r["sleeve"], []).append(r)
    best_rows = []
    for sl, items in by_sleeve.items():
        # baseline = canonical
        base = next(x for x in items if x["config"] == "A_canonical")
        best = max(items, key=lambda x: x["calmar"])
        delta_mdd = best["mdd"] - base["mdd"]   # less negative = improvement
        delta_sh = best["sharpe"] - base["sharpe"]
        print(f"  {sl:<18}  best={best['config']}  Sh={best['sharpe']:>5.2f} (d={delta_sh:+.2f})  "
              f"MDD={best['mdd']:>6.2f}% (d={delta_mdd:+.2f}pp)  Calmar={best['calmar']:>5.2f}")
        best_rows.append({"sleeve": sl, "best": best, "vs_baseline_mdd_pp": delta_mdd, "vs_baseline_sh": delta_sh})

    # Promotion: MDD <= -15% AND Sharpe >= 0.8 AND n >= 30
    promo = [r for r in rows if r["mdd"] >= -15 and r["sharpe"] >= 0.8 and r["n"] >= 30]
    print(f"\nPROMO (MDD<=15%, Sh>=0.8, n>=30): {len(promo)}")
    for r in promo:
        print(f"  {r['sleeve']:<18} {r['config']:<14}  Sh={r['sharpe']:>5.2f}  "
              f"CAGR={r['cagr']:>6.2f}%  MDD={r['mdd']:>6.2f}%  Calmar={r['calmar']:>5.2f}")

    out = OUT / "v55_priceaction_adaptive.json"
    out.write_text(json.dumps({"rows": rows, "best_per_sleeve": best_rows, "promo": promo},
                              indent=2, default=str))
    print(f"\nWrote: {out}")


if __name__ == "__main__":
    main()
