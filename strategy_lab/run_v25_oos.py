"""
V25 OOS — walk-forward audit for each V25 family's per-coin winner.
Split: IS 2020-2023, OOS 2024-2026.
"""
from __future__ import annotations
import sys, pickle, warnings
warnings.filterwarnings("ignore")
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import simulate, metrics

from strategy_lab.run_v25_creative import (
    _load, sig_mtf_conf, sig_squeeze, sig_seasonal, sig_kelt_rsi, sig_sweep,
    dedupe, scaled,
)

RES = Path(__file__).resolve().parent / "results" / "v25"
FEE = 0.00045
SPLIT = pd.Timestamp("2024-01-01", tz="UTC")


def run_slice(df, lsig, ssig, exits, risk, lev, lbl):
    tp, sl, tr, mh = exits["tp"], exits["sl"], exits["trail"], exits["mh"]
    ls = dedupe(lsig); ss = dedupe(ssig) if ssig is not None else None
    trades, eq = simulate(df, ls, short_entries=ss,
                          tp_atr=tp, sl_atr=sl, trail_atr=tr, max_hold=mh,
                          risk_per_trade=risk, leverage_cap=lev, fee=FEE)
    return metrics(lbl, eq, trades), trades, eq


def verdict(r_is, r_oos):
    if r_oos["n"] < 10: return "insufficient OOS trades"
    if r_oos["sharpe"] <= 0: return "OOS LOSES"
    if r_oos["sharpe"] >= 0.5 * max(0.1, r_is["sharpe"]): return "✓ OOS holds"
    return "✗ OOS degrades"


def _sig_for(d, df):
    fam = d["family"]; p = d["params"]
    if fam == "MTF_Conf":
        return sig_mtf_conf(df, p["fast"], p["slow"], p["h4_ema"])
    if fam == "Squeeze":
        return sig_squeeze(df, p["bb_n"], p["bb_k"], p["bb_n"], p["kc_mult"], p["mom_n"])
    if fam == "Seasonal_RSI":
        return sig_seasonal(df, d["tf"], p["hour_start"], p["hour_span"],
                             14, p["rsi_lo"], p["rsi_hi"],
                             p["bb_n"], 2.0, scaled(400, d["tf"]))
    if fam == "Keltner_RSI":
        return sig_kelt_rsi(df, p["kc_n"], p["kc_mult"], 14, p["rsi_mid"])
    if fam == "Sweep_Reversal":
        return sig_sweep(df, p["lookback"], p["wick_mult"], scaled(400, d["tf"]))
    raise ValueError(fam)


def main():
    path = RES / "v25_creative_results.pkl"
    if not path.exists():
        print("no V25 results pickle")
        return 1
    with open(path, "rb") as f:
        results = pickle.load(f)

    rows = []
    for key, d in results.items():
        sym = d["sym"]; tf = d["tf"]; fam = d["family"]
        df = _load(sym, tf)
        if df is None:
            continue
        try:
            lsig, ssig = _sig_for(d, df)
        except Exception as e:
            print(f"SKIP {key}: {e}")
            continue

        # IS slice
        df_is = df[df.index < SPLIT]
        if len(df_is) > 200:
            l_is = lsig.reindex(df_is.index).fillna(False)
            s_is = ssig.reindex(df_is.index).fillna(False) if ssig is not None else None
            r_is, _, _ = run_slice(df_is, l_is, s_is, d["exits"], d["risk"], d["lev"], f"{key}_IS")
        else:
            r_is = {"n": 0, "sharpe": 0, "cagr_net": 0, "dd": 0}

        # OOS slice
        df_oos = df[df.index >= SPLIT]
        if len(df_oos) > 100:
            l_oos = lsig.reindex(df_oos.index).fillna(False)
            s_oos = ssig.reindex(df_oos.index).fillna(False) if ssig is not None else None
            r_oos, _, _ = run_slice(df_oos, l_oos, s_oos, d["exits"], d["risk"], d["lev"], f"{key}_OOS")
        else:
            r_oos = {"n": 0, "sharpe": 0, "cagr_net": 0, "dd": 0}

        v = verdict(r_is, r_oos)
        full = d["metrics"]
        rows.append({
            "sym": sym, "family": fam, "tf": tf,
            "full_cagr": round(full["cagr_net"] * 100, 1),
            "full_sh": round(full["sharpe"], 2),
            "full_n": int(full["n"]),
            "is_cagr": round(r_is["cagr_net"] * 100, 1),
            "is_sh": round(r_is["sharpe"], 2),
            "is_n": int(r_is.get("n", 0)),
            "oos_cagr": round(r_oos["cagr_net"] * 100, 1),
            "oos_sh": round(r_oos["sharpe"], 2),
            "oos_n": int(r_oos.get("n", 0)),
            "verdict": v,
        })
        print(f"{key:30s}  IS Sh {r_is.get('sharpe',0):+5.2f} (n={r_is.get('n',0):3d})  "
              f"OOS Sh {r_oos.get('sharpe',0):+5.2f} (n={r_oos.get('n',0):3d})  {v}", flush=True)

    df_out = pd.DataFrame(rows)
    df_out.to_csv(RES / "v25_oos_summary.csv", index=False)

    print("\n" + "=" * 80)
    print("V25 OOS VERDICTS")
    print("=" * 80)
    print(df_out.to_string(index=False))

    holds = df_out[df_out["verdict"] == "✓ OOS holds"]
    print(f"\n{len(holds)} / {len(df_out)} strategies held out of sample.")
    if len(holds):
        print("\nWinners:")
        print(holds.to_string(index=False))


if __name__ == "__main__":
    sys.exit(main() or 0)
