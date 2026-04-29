"""
V51 — refine new signals: fix VWAP_BF, widen MFI thresholds,
try SVD_DIV parameter variants. Then correlation + blend test with champion.
"""
from __future__ import annotations
import sys, time, json
from pathlib import Path
import numpy as np
import pandas as pd

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
    sig_signed_vol_div, sig_volume_profile_rot,
)

OUT = REPO / "docs" / "research" / "phase5_results"
BPY = 365.25 * 6
EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)

COINS = ["ETHUSDT", "BTCUSDT", "SOLUSDT", "AVAXUSDT", "DOGEUSDT", "LINKUSDT"]

# Variants to try
VARIANTS = [
    # (name, sig_fn, kwargs)
    ("VWAP_BF_std",  sig_vwap_band_fade, dict(n=100, sigma=2.0, slope_eps=0.01)),
    ("VWAP_BF_lax",  sig_vwap_band_fade, dict(n=100, sigma=2.0, slope_eps=0.05)),
    ("VWAP_BF_tight",sig_vwap_band_fade, dict(n=100, sigma=2.5, slope_eps=0.02)),
    ("MFI_75_25",    sig_mfi_extreme,    dict(lower=25, upper=75)),
    ("MFI_70_30",    sig_mfi_extreme,    dict(lower=30, upper=70)),
    ("MFI_NoCross_80_20",  sig_mfi_extreme, dict(lower=20, upper=80, require_cross=False)),
    ("SVD_30",       sig_signed_vol_div, dict(lookback=30, cvd_win=50, min_cvd_threshold=0.3)),
    ("SVD_50",       sig_signed_vol_div, dict(lookback=50, cvd_win=80, min_cvd_threshold=0.2)),
    ("SVD_tight",    sig_signed_vol_div, dict(lookback=20, cvd_win=50, min_cvd_threshold=0.5)),
    ("VP_ROT_60",    sig_volume_profile_rot, dict(win=60, n_bins=15)),
    ("VP_ROT_240",   sig_volume_profile_rot, dict(win=240, n_bins=25)),
]

def main():
    t0 = time.time()
    rows = []
    curves = {}
    regime_cache = {}

    print(f"Running {len(VARIANTS)} variants x {len(COINS)} coins x 2 exits...")
    for coin in COINS:
        df = load_data(coin, "4h", start="2021-01-01", end="2026-03-31")
        if coin not in regime_cache:
            _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
            regime_cache[coin] = rdf["label"]
        reg = regime_cache[coin]

        for vname, vfn, vkw in VARIANTS:
            try:
                out = vfn(df, **vkw)
                le, se = out if isinstance(out, tuple) else (out, None)
                if int(le.sum()) + int(se.sum() if se is not None else 0) < 15:
                    continue
            except Exception:
                continue

            for ex, runfn in [("baseline", lambda: sim_canonical(df, le, se, **EXIT_4H)),
                              ("V41",       lambda: simulate_adaptive_exit(df, le, se, reg))]:
                try:
                    tr, eq = runfn()
                    m = metrics(eq, tr)
                    m.update({"coin": coin[:-4], "variant": vname, "exit": ex})
                    rows.append(m)
                    curves[(coin, vname, ex)] = eq
                except Exception:
                    pass

    df_out = pd.DataFrame(rows)
    df_out.to_csv(OUT / "v51_refine_grid.csv", index=False)

    # Top performers
    print("\n" + "=" * 90)
    print("TOP 20 by Sharpe (pos_yrs >= 4, n >= 30)")
    print("=" * 90)
    top = (df_out[(df_out["pos_yrs"] >= 4) & (df_out["n"] >= 30)]
           .sort_values("sharpe", ascending=False).head(20))
    if len(top):
        print(top[["coin","variant","exit","n","wr","sharpe","cagr","mdd",
                    "calmar","min_yr","pos_yrs","pf"]].to_string(index=False))
    else:
        print("  (no candidates meet threshold; showing top 20 unfiltered)")
        top = df_out.sort_values("sharpe", ascending=False).head(20)
        print(top[["coin","variant","exit","n","wr","sharpe","cagr","mdd",
                    "calmar","pos_yrs"]].to_string(index=False))

    # --- Champion + correlation analysis ---
    print("\n" + "=" * 90)
    print("CORRELATION vs CHAMPION + BLEND TEST (top candidates with Sharpe > 0.4 & pos_yrs >= 4)")
    print("=" * 90)
    base_curves = {s: build_sleeve_curve(s, v) for s, v in BEST_VARIANT_MAP.items()}
    p3_eq = invvol_blend({k: base_curves[k] for k in ["CCI_ETH_4h","STF_AVAX_4h","STF_SOL_4h"]}, window=500)
    p5_eq = eqw_blend({k: base_curves[k] for k in ["CCI_ETH_4h","LATBB_AVAX_4h","STF_SOL_4h"]})
    idx = p3_eq.index.intersection(p5_eq.index)
    champ_r = 0.6 * p3_eq.reindex(idx).pct_change().fillna(0) + 0.4 * p5_eq.reindex(idx).pct_change().fillna(0)
    champ_eq = (1 + champ_r).cumprod() * 10_000.0
    mc = metrics(champ_eq, [])
    print(f"Champion: Sh={mc['sharpe']} CAGR={mc['cagr']*100:+.1f}% MDD={mc['mdd']*100:+.1f}% Cal={mc['calmar']}")

    cand = df_out[(df_out["sharpe"] > 0.4) & (df_out["pos_yrs"] >= 4) & (df_out["n"] >= 30)]
    cand = cand.sort_values("sharpe", ascending=False).head(10)
    print(f"\nScanning {len(cand)} diversifier candidates...")

    blend_rows = []
    for _, row in cand.iterrows():
        key = (row["coin"] + "USDT", row["variant"], row["exit"])
        if key not in curves: continue
        sleeve_eq = curves[key]
        com = champ_eq.index.intersection(sleeve_eq.index)
        cr = champ_eq.reindex(com).pct_change().fillna(0)
        sr = sleeve_eq.reindex(com).pct_change().fillna(0)
        corr = float(cr.corr(sr))

        best_at = None
        for wt in [0.10, 0.15, 0.20, 0.25]:
            blended = (1-wt)*cr + wt*sr
            eq = (1 + blended).cumprod() * 10_000.0
            m = metrics(eq, [])
            if best_at is None or m["sharpe"] > best_at[1]["sharpe"]:
                best_at = (wt, m)
        wt, m = best_at
        better_sh = m["sharpe"] > mc["sharpe"]
        better_cal = m["calmar"] > mc["calmar"]
        flag = "WIN" if better_sh and better_cal else ("SH+" if better_sh else ("CAL+" if better_cal else "   "))
        print(f"  [{flag:4s}] {row['coin']:5s} {row['variant']:18s} {row['exit']:8s}  "
              f"sleeve_sh={row['sharpe']:.2f} corr={corr:+.2f}  "
              f"best@{wt:.0%}: Sh={m['sharpe']:.3f} CAGR={m['cagr']*100:+.1f}% "
              f"MDD={m['mdd']*100:+.1f}% Cal={m['calmar']:.2f}")
        blend_rows.append({"candidate": f"{row['coin']}_{row['variant']}_{row['exit']}",
                            "sleeve_sharpe": row["sharpe"], "correlation": corr,
                            "best_weight": wt, "blend_sharpe": m["sharpe"],
                            "blend_cagr": m["cagr"], "blend_mdd": m["mdd"],
                            "blend_calmar": m["calmar"], "flag": flag})

    with open(OUT / "v51_blend_results.json", "w") as f:
        json.dump(blend_rows, f, indent=2, default=str)
    print(f"\nTime: {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
