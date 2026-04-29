"""
V41-V44 Iteration — target: beat NEW 60/40 (Sharpe 2.25, CAGR 36.7%, MDD -13.8%)

Approach: keep the WINNING V30 entry signals, modify one dimension at a time.

  V41  Regime-adaptive EXIT stack (tight SL in HighVol, loose TP in LowVol)
  V42  Multi-timeframe confirmation (4h entry + 1h trend agreement)
  V43  Volume filter (entry only when vol > 1.1x 20-bar SMA)
  V44  TP1/TP2 partial exits on V30 canonical entries
  V45  Combined: V41 + V43 (best of both)

Tests each variant on the 4 production sleeves:
  CCI_ETH_4h, STF_AVAX_4h, STF_SOL_4h, LATBB_AVAX_4h

Then blends the best variant per sleeve and compares to NEW 60/40 baseline.
"""
from __future__ import annotations
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from strategy_lab.engine import load as load_data
from strategy_lab.eval.perps_simulator import simulate as sim_canonical
from strategy_lab.eval.perps_simulator_tp12 import simulate_tp12
from strategy_lab.eval.perps_simulator_adaptive_exit import (
    simulate_adaptive_exit, REGIME_EXITS_4H,
)
from strategy_lab.regime.hmm_adaptive import fit_regime_model
from strategy_lab.run_leverage_audit import eqw_blend, invvol_blend

OUT = REPO / "docs" / "research" / "phase5_results"
BPY = 365.25 * 6

EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)
TP12_4H = dict(tp1_atr=3.0, tp2_atr=10.0, tp1_frac=0.5,
               sl_atr=2.0, trail_atr=6.0, tight_trail_atr=2.5, max_hold=60)

SLEEVE_SPECS = {
    "CCI_ETH_4h":    ("run_v30_creative.py",  "sig_cci_extreme",     "ETHUSDT",  "4h"),
    "STF_SOL_4h":    ("run_v30_creative.py",  "sig_supertrend_flip", "SOLUSDT",  "4h"),
    "STF_AVAX_4h":   ("run_v30_creative.py",  "sig_supertrend_flip", "AVAXUSDT", "4h"),
    "LATBB_AVAX_4h": ("run_v29_regime.py",    "sig_lateral_bb_fade", "AVAXUSDT", "4h"),
}

def import_sig(script: str, fn: str):
    path = REPO / "strategy_lab" / script
    spec = importlib.util.spec_from_file_location(script.replace(".", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, fn)

# --------------- data cache ---------------
_DATA: dict[str, tuple[pd.DataFrame, pd.Series, pd.Series]] = {}
_REGIMES: dict[str, pd.Series] = {}

def sleeve_data(label: str):
    if label in _DATA:
        return _DATA[label]
    script, fn, sym, tf = SLEEVE_SPECS[label]
    df = load_data(sym, tf, start="2021-01-01", end="2026-03-31")
    sig = import_sig(script, fn)
    le, se = sig(df)
    _DATA[label] = (df, le, se)
    return df, le, se

def symbol_regimes(sym: str) -> pd.Series:
    if sym in _REGIMES:
        return _REGIMES[sym]
    df = load_data(sym, "4h", start="2021-01-01", end="2026-03-31")
    _, reg = fit_regime_model(df, train_frac=0.30, seed=42)
    _REGIMES[sym] = reg["label"]
    return reg["label"]


# --------------- metrics ---------------
def metrics(eq: pd.Series, trades: list[dict], label=""):
    n = len(trades)
    if len(eq) < 30:
        return {"label": label, "n": n, "sharpe": 0, "cagr": 0, "mdd": 0,
                "calmar": 0, "wr": 0, "min_yr": 0, "pos_yrs": 0, "pf": 0}
    rets = eq.pct_change().dropna()
    mu, sd = float(rets.mean()), float(rets.std())
    sh = (mu/sd)*np.sqrt(BPY) if sd > 0 else 0
    pk = eq.cummax(); mdd = float((eq/pk - 1).min())
    yrs = (eq.index[-1] - eq.index[0]).total_seconds()/(365.25*86400)
    total = float(eq.iloc[-1]/eq.iloc[0] - 1)
    cagr = (1+total)**(1/max(yrs,1e-6))-1
    cal = cagr/abs(mdd) if mdd != 0 else 0
    wins = [t for t in trades if t.get("ret",0) > 0] if trades else []
    losses = [t for t in trades if t.get("ret",0) <= 0] if trades else []
    wr = len(wins)/n if n > 0 else 0
    pf = abs(sum(t["ret"] for t in wins)/sum(t["ret"] for t in losses)) if (losses and sum(t["ret"] for t in losses) != 0) else 0
    yrs_map = {}
    for yr in sorted(set(eq.index.year)):
        e = eq[eq.index.year == yr]
        if len(e) >= 30:
            yrs_map[int(yr)] = float(e.iloc[-1]/e.iloc[0] - 1)
    min_yr = min(yrs_map.values()) if yrs_map else 0
    pos_yrs = sum(1 for r in yrs_map.values() if r > 0)
    return {"label": label, "n": n, "sharpe": round(sh, 3), "cagr": round(cagr, 4),
            "mdd": round(mdd, 4), "calmar": round(cal, 3), "wr": round(wr, 3),
            "min_yr": round(min_yr, 4), "pos_yrs": pos_yrs,
            "pf": round(pf, 2)}


# --------------- variants ---------------
def v41_regime_exit(label: str):
    df, le, se = sleeve_data(label)
    sym = SLEEVE_SPECS[label][2]
    reg = symbol_regimes(sym)
    tr, eq = simulate_adaptive_exit(df, le, se, reg)
    return tr, eq

def v42_multi_tf(label: str):
    """V30 entry on 4h, confirmed by 1h trend agreement."""
    df, le, se = sleeve_data(label)
    sym = SLEEVE_SPECS[label][2]
    # 1h trend
    df_1h = load_data(sym, "1h", start="2021-01-01", end="2026-03-31")
    ema20_1h = df_1h["close"].ewm(span=20, adjust=False).mean()
    ema50_1h = df_1h["close"].ewm(span=50, adjust=False).mean()
    trend_1h_up = (ema20_1h > ema50_1h)
    trend_1h_dn = (ema20_1h < ema50_1h)
    # reindex to 4h using last-known trend at each 4h bar (no future leak: ffill)
    up_at_4h = trend_1h_up.reindex(df.index, method="ffill").fillna(False)
    dn_at_4h = trend_1h_dn.reindex(df.index, method="ffill").fillna(False)
    le2 = le & up_at_4h
    se2 = se & dn_at_4h if se is not None else None
    tr, eq = sim_canonical(df, le2, se2, **EXIT_4H)
    return tr, eq

def v43_volume_filter(label: str):
    """V30 entry only when volume > 1.1x rolling 20-bar mean."""
    df, le, se = sleeve_data(label)
    vol = df["volume"] if "volume" in df.columns else pd.Series(1.0, index=df.index)
    vmean = vol.rolling(20, min_periods=10).mean()
    active = vol > 1.1 * vmean
    le2 = le & active
    se2 = se & active if se is not None else None
    tr, eq = sim_canonical(df, le2, se2, **EXIT_4H)
    return tr, eq

def v44_tp12(label: str):
    """V30 entries, TP1/TP2 exit stack."""
    df, le, se = sleeve_data(label)
    tr, eq = simulate_tp12(df, le, se, **TP12_4H)
    return tr, eq

def v45_combined(label: str):
    """V41 regime-adaptive exit + V43 volume filter combined."""
    df, le, se = sleeve_data(label)
    sym = SLEEVE_SPECS[label][2]
    reg = symbol_regimes(sym)
    vol = df["volume"] if "volume" in df.columns else pd.Series(1.0, index=df.index)
    vmean = vol.rolling(20, min_periods=10).mean()
    active = vol > 1.1 * vmean
    le2 = le & active
    se2 = se & active if se is not None else None
    tr, eq = simulate_adaptive_exit(df, le2, se2, reg)
    return tr, eq

def baseline(label: str):
    df, le, se = sleeve_data(label)
    tr, eq = sim_canonical(df, le, se, **EXIT_4H)
    return tr, eq


VARIANTS = {
    "baseline":  baseline,
    "V41_regxit": v41_regime_exit,
    "V42_mtf":    v42_multi_tf,
    "V43_vol":    v43_volume_filter,
    "V44_tp12":   v44_tp12,
    "V45_combo":  v45_combined,
}


# --------------- main ---------------
def main():
    t0 = time.time()
    print("Warming caches...")
    for lbl in SLEEVE_SPECS:
        sleeve_data(lbl)
        sym = SLEEVE_SPECS[lbl][2]
        symbol_regimes(sym)

    # Per-sleeve variant scan
    rows = []
    eqs: dict[tuple[str,str], pd.Series] = {}
    for lbl in SLEEVE_SPECS:
        print(f"\n=== {lbl} ===")
        for vname, fn in VARIANTS.items():
            try:
                tr, eq = fn(lbl)
                m = metrics(eq, tr, label=f"{lbl}::{vname}")
                m["sleeve"] = lbl; m["variant"] = vname
                rows.append(m)
                eqs[(lbl, vname)] = eq
                print(f"  {vname:12s} n={m['n']:4d} WR={m['wr']*100:5.1f}% "
                      f"Sh={m['sharpe']:6.3f} CAGR={m['cagr']*100:+6.1f}% "
                      f"MDD={m['mdd']*100:+6.1f}% Cal={m['calmar']:5.2f} "
                      f"PF={m['pf']:4.2f} minYr={m['min_yr']*100:+5.1f}%")
            except Exception as e:
                print(f"  {vname:12s} ERROR: {type(e).__name__}: {e}")

    df_out = pd.DataFrame(rows)
    df_out.to_csv(OUT / "v41_v45_grid.csv", index=False)

    # --- Blends: per-sleeve pick BEST VARIANT by Sharpe, build blend ---
    print("\n" + "=" * 70)
    print("BLENDED PORTFOLIOS — per-sleeve best variant")
    print("=" * 70)

    best_per_sleeve = {}
    for lbl in SLEEVE_SPECS:
        sub = [r for r in rows if r["sleeve"] == lbl and r["n"] >= 20]
        if not sub:
            continue
        best = max(sub, key=lambda x: x["sharpe"])
        best_per_sleeve[lbl] = best["variant"]
    print(f"  Best variant per sleeve: {best_per_sleeve}")

    # Blend P3 sleeves (CCI_ETH + STF_AVAX + STF_SOL) with their best variant
    P3_sleeves = ["CCI_ETH_4h", "STF_AVAX_4h", "STF_SOL_4h"]
    P5_sleeves = ["CCI_ETH_4h", "LATBB_AVAX_4h", "STF_SOL_4h"]

    def build_blend(sleeves, variant_map, weighting):
        curves = {}
        for s in sleeves:
            v = variant_map.get(s, "baseline")
            curves[s] = eqs[(s, v)]
        if weighting == "invvol":
            return invvol_blend(curves, window=500)
        return eqw_blend(curves)

    blends = {}
    blends["P3_V41_best_invvol"] = build_blend(P3_sleeves, best_per_sleeve, "invvol")
    blends["P3_V41_best_eqw"]     = build_blend(P3_sleeves, best_per_sleeve, "eqw")
    blends["P5_V41_best_eqw"]     = build_blend(P5_sleeves, best_per_sleeve, "eqw")
    # uniform all-V41 (forced)
    all_v41 = {s: "V41_regxit" for s in SLEEVE_SPECS}
    blends["P3_allV41_invvol"] = build_blend(P3_sleeves, all_v41, "invvol")
    blends["P5_allV41_eqw"]    = build_blend(P5_sleeves, all_v41, "eqw")
    # uniform all-V45
    all_v45 = {s: "V45_combo" for s in SLEEVE_SPECS}
    blends["P3_allV45_invvol"] = build_blend(P3_sleeves, all_v45, "invvol")
    blends["P5_allV45_eqw"]    = build_blend(P5_sleeves, all_v45, "eqw")
    # combined 60/40 using best-V41 per sleeve
    idx = blends["P3_V41_best_invvol"].index.intersection(blends["P5_V41_best_eqw"].index)
    r = (0.6 * blends["P3_V41_best_invvol"].reindex(idx).pct_change().fillna(0)
        + 0.4 * blends["P5_V41_best_eqw"].reindex(idx).pct_change().fillna(0))
    blends["NEW_60_40_V41"] = (1 + r).cumprod() * 10_000.0

    blend_results = {}
    for name, eq in blends.items():
        m = metrics(eq, [], label=name)
        m["name"] = name
        blend_results[name] = m
        print(f"  {name:28s} Sh={m['sharpe']:6.3f} CAGR={m['cagr']*100:+6.1f}% "
              f"MDD={m['mdd']*100:+6.1f}% Cal={m['calmar']:5.2f} minYr={m['min_yr']*100:+5.1f}% "
              f"pos={m['pos_yrs']}/6")

    # Reference — NEW 60/40 baseline
    print(f"\n  [reference] NEW 60/40 (from study 19): Sharpe=2.251 CAGR=+36.7% MDD=-13.8% Cal=2.67 minYr=+14.4%")

    with open(OUT / "v41_v45_blends.json", "w") as f:
        json.dump(blend_results, f, indent=2, default=str)

    print(f"\nTotal runtime: {time.time()-t0:.1f}s")
    print(f"Saved grid -> {OUT}/v41_v45_grid.csv")
    print(f"Saved blends -> {OUT}/v41_v45_blends.json")

if __name__ == "__main__":
    main()
