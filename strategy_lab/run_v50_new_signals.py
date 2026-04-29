"""
V50 — scan new signal families across coin grid; find champion-beaters.

Strategies (from v50_new_signals.py):
  MFI_EX    Money Flow Index extreme reversal
  VWAP_BF   VWAP band fade (rolling ±2σ, VWAP-flat filter)
  VP_ROT    Volume profile rotation (POC/VAH/VAL)
  SVD_DIV   Signed-volume divergence (CVD proxy)

Exits: baseline (canonical) + V41 (regime-adaptive)
Coins: ETH, BTC, SOL, AVAX, DOGE, LINK

For each winner (pos_yrs >= 4 and Sharpe > 0.7), test blend with champion.
"""
from __future__ import annotations
import importlib.util, json, sys, time, warnings
from pathlib import Path
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from strategy_lab.engine import load as load_data
from strategy_lab.eval.perps_simulator import simulate as sim_canonical
from strategy_lab.eval.perps_simulator_adaptive_exit import simulate_adaptive_exit
from strategy_lab.regime.hmm_adaptive import fit_regime_model
from strategy_lab.run_leverage_audit import eqw_blend, invvol_blend
from strategy_lab.run_v41_expansion import metrics
from strategy_lab.run_v41_gates import build_sleeve_curve, BEST_VARIANT_MAP
from strategy_lab.strategies.v50_new_signals import (
    sig_mfi_extreme, sig_vwap_band_fade,
    sig_volume_profile_rot, sig_signed_vol_div,
)

OUT = REPO / "docs" / "research" / "phase5_results"
BPY = 365.25 * 6
EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)

COINS = ["ETHUSDT", "BTCUSDT", "SOLUSDT", "AVAXUSDT", "DOGEUSDT", "LINKUSDT"]
SIGNALS = [
    ("MFI_EX",  sig_mfi_extreme,          {}),
    ("VWAP_BF", sig_vwap_band_fade,       {}),
    ("VP_ROT",  sig_volume_profile_rot,   {}),
    ("SVD_DIV", sig_signed_vol_div,       {}),
]

def main():
    t0 = time.time()
    print(f"Scanning {len(COINS)} coins x {len(SIGNALS)} new signals x 2 exits...")
    rows = []
    curves = {}
    regime_cache = {}

    for coin in COINS:
        df = load_data(coin, "4h", start="2021-01-01", end="2026-03-31")
        if coin not in regime_cache:
            _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
            regime_cache[coin] = rdf["label"]
        reg = regime_cache[coin]

        for sname, sfn, skw in SIGNALS:
            try:
                out = sfn(df, **skw)
                le, se = out if isinstance(out, tuple) else (out, None)
            except Exception as e:
                print(f"  [sig-err] {coin} {sname}: {type(e).__name__}: {e}")
                continue

            n_long = int(le.sum()); n_short = int(se.sum()) if se is not None else 0
            if n_long + n_short < 10:
                rows.append({"coin": coin[:-4], "sig": sname, "exit": "baseline",
                             "n": 0, "sharpe": 0, "cagr": 0, "mdd": 0,
                             "calmar": 0, "wr": 0, "min_yr": 0, "pos_yrs": 0,
                             "pf": 0, "n_long_sig": n_long, "n_short_sig": n_short})
                continue

            # baseline
            try:
                tr, eq = sim_canonical(df, le, se, **EXIT_4H)
                m = metrics(eq, tr)
                m.update({"coin": coin[:-4], "sig": sname, "exit": "baseline",
                          "n_long_sig": n_long, "n_short_sig": n_short})
                rows.append(m)
                curves[(coin, sname, "baseline")] = eq
            except Exception as e:
                print(f"  [sim-err] {coin} {sname} baseline: {type(e).__name__}")

            # V41
            try:
                tr, eq = simulate_adaptive_exit(df, le, se, reg)
                m = metrics(eq, tr)
                m.update({"coin": coin[:-4], "sig": sname, "exit": "V41",
                          "n_long_sig": n_long, "n_short_sig": n_short})
                rows.append(m)
                curves[(coin, sname, "V41")] = eq
            except Exception as e:
                print(f"  [sim-err] {coin} {sname} V41: {type(e).__name__}")

    df_out = pd.DataFrame(rows)
    df_out.to_csv(OUT / "v50_new_signals_grid.csv", index=False)
    print(f"\nGrid complete: {len(df_out)} rows in {time.time()-t0:.1f}s")

    # ---- rank single-sleeve winners ----
    print("\n" + "=" * 88)
    print("TOP 15 SINGLE-SLEEVE (pos_yrs >= 4, Sharpe > 0.7, n >= 20)")
    print("=" * 88)
    winners = (df_out[(df_out["pos_yrs"] >= 4) &
                        (df_out["sharpe"] > 0.7) &
                        (df_out["n"] >= 20)]
                .sort_values("sharpe", ascending=False).head(15))
    if len(winners) == 0:
        print("  No single-sleeve winners at this threshold.")
    else:
        print(winners[["coin","sig","exit","n","wr","sharpe","cagr","mdd",
                        "calmar","min_yr","pos_yrs","pf"]].to_string(index=False))

    # ---- blend test: layer each top-10 winner onto champion ----
    print("\n" + "=" * 88)
    print("BLEND TEST: champion + new_sleeve at 10%, 20%, 30% weight")
    print("=" * 88)
    # Build champion
    base_curves = {s: build_sleeve_curve(s, v) for s, v in BEST_VARIANT_MAP.items()}
    p3_eq = invvol_blend({k: base_curves[k] for k in ["CCI_ETH_4h","STF_AVAX_4h","STF_SOL_4h"]}, window=500)
    p5_eq = eqw_blend({k: base_curves[k] for k in ["CCI_ETH_4h","LATBB_AVAX_4h","STF_SOL_4h"]})
    idx = p3_eq.index.intersection(p5_eq.index)
    champ_r = 0.6 * p3_eq.reindex(idx).pct_change().fillna(0) + 0.4 * p5_eq.reindex(idx).pct_change().fillna(0)
    champ_eq = (1 + champ_r).cumprod() * 10_000.0
    mc = metrics(champ_eq, [])
    print(f"Champion: Sharpe={mc['sharpe']} CAGR={mc['cagr']*100:+.1f}% "
          f"MDD={mc['mdd']*100:+.1f}% Cal={mc['calmar']}")

    # Candidates to layer
    top10 = winners.head(10) if len(winners) else pd.DataFrame()
    blend_results = []
    for _, w in top10.iterrows():
        key = (w["coin"] + "USDT", w["sig"], w["exit"])
        if key not in curves: continue
        sleeve_eq = curves[key]
        com = champ_eq.index.intersection(sleeve_eq.index)
        cr = champ_eq.reindex(com).pct_change().fillna(0)
        sr = sleeve_eq.reindex(com).pct_change().fillna(0)
        for wt in [0.10, 0.20, 0.30]:
            blended = (1-wt)*cr + wt*sr
            eq = (1 + blended).cumprod() * 10_000.0
            m = metrics(eq, [])
            m.update({"sleeve_name": f"{w['coin']}_{w['sig']}_{w['exit']}", "weight": wt})
            blend_results.append(m)
            better_sh = m["sharpe"] > mc["sharpe"]
            better_cal = m["calmar"] > mc["calmar"]
            flag = "WIN" if better_sh and better_cal else ("SH+" if better_sh else ("CAL+" if better_cal else "   "))
            print(f"  [{flag:4s}] champ@{1-wt:.0%} + {w['coin']}_{w['sig']}_{w['exit']}@{wt:.0%}: "
                  f"Sh={m['sharpe']:.3f} CAGR={m['cagr']*100:+5.1f}% MDD={m['mdd']*100:+6.1f}% "
                  f"Cal={m['calmar']:.2f} minYr={m['min_yr']*100:+5.1f}%")

    with open(OUT / "v50_new_signals_blends.json", "w") as f:
        json.dump(blend_results, f, indent=2, default=str)

    print(f"\nTotal runtime: {time.time()-t0:.1f}s")
    print(f"Saved -> {OUT}/v50_new_signals_grid.csv, v50_new_signals_blends.json")


if __name__ == "__main__":
    main()
