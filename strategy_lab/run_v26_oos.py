"""
V26 OOS — walk-forward audit for each V26 price-action family's per-coin winner.
Split: IS 2020-2023, OOS 2024-2026.

Mirrors run_v25_oos.py. Key validation targets after the sweep:
  * BTC  Order_Block  1h   CAGR +240%  Sharpe +1.96  n=1902  DD -43.6%
  * AVAX Order_Block 30m   CAGR +7902% Sharpe +4.85  n=1872  DD -36%   (overfit suspect)
  * SUI  Order_Block 30m   CAGR +1453% Sharpe +3.03  n=1642  DD -43.6%
  * TON  Order_Block 30m   CAGR +686%  Sharpe +2.61  n= 743  DD -38.8%
  * INJ  Order_Block 1h    CAGR +423%  Sharpe +2.51  n=1076
  * AVAX ATR_Squeeze 1h    CAGR +64%   Sharpe +1.32  n= 142
  * TON  Liq_Sweep   1h    CAGR +50%   Sharpe +1.11  n= 145
  * LINK ATR_Squeeze 1h    CAGR +17%   Sharpe +0.60  n=  99
Order_Block is suspect because of the very high trade count → fee-sensitive and
over-optimistic fills can turn a paper-gold strategy into OOS lead. OOS will
tell us which are real.
"""
from __future__ import annotations
import sys, pickle, warnings
warnings.filterwarnings("ignore")
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import simulate, metrics

from strategy_lab.run_v26_priceaction import (
    _load, dedupe, scaled,
    sig_liq_sweep, sig_order_block, sig_msb, sig_engulf, sig_rsi_div, sig_atr_sqz,
)

RES = Path(__file__).resolve().parent / "results" / "v26"
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
    fam = d["family"]; p = d["params"]; tf = d["tf"]
    if fam == "Liq_Sweep":
        return sig_liq_sweep(df, p["L"], p["R"], p["vol_mult"], scaled(400, tf))
    if fam == "Order_Block":
        return sig_order_block(df, p["lookahead"], p["atr_impulse"],
                                p["retrace_bars"], scaled(400, tf))
    if fam == "MSB":
        return sig_msb(df, p["L"], p["R"], p["vol_mult"])
    if fam == "Engulf_Vol":
        return sig_engulf(df, p["bb_n"], p["bb_k"], p["vol_mult"])
    if fam == "RSI_Divergence":
        return sig_rsi_div(df, 14, p["L"], p["R"], scaled(400, tf))
    if fam == "ATR_Squeeze":
        return sig_atr_sqz(df, 14, p["sqz_ratio"], p["donch_n"], scaled(400, tf))
    raise ValueError(fam)


def main():
    path = RES / "v26_priceaction_results.pkl"
    if not path.exists():
        print("no V26 results pickle")
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
        print(f"{key:30s}  IS Sh {r_is.get('sharpe',0):+5.2f} (n={r_is.get('n',0):4d})  "
              f"OOS Sh {r_oos.get('sharpe',0):+5.2f} (n={r_oos.get('n',0):4d})  {v}", flush=True)

    df_out = pd.DataFrame(rows)
    df_out.to_csv(RES / "v26_oos_summary.csv", index=False)

    print("\n" + "=" * 80)
    print("V26 OOS VERDICTS")
    print("=" * 80)
    print(df_out.to_string(index=False))

    holds = df_out[df_out["verdict"] == "✓ OOS holds"]
    print(f"\n{len(holds)} / {len(df_out)} strategies held out of sample.")
    if len(holds):
        print("\nWinners:")
        print(holds.to_string(index=False))


if __name__ == "__main__":
    sys.exit(main() or 0)
