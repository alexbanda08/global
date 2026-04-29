"""V29 OOS audit — re-simulate each winner on IS (pre-2024) and OOS (2024+)
separately, compute Sharpe on each side, apply the verdict rule:

  PASS if OOS Sharpe >= 0.5 * max(IS Sharpe, 0.1).

Uses the winning config's exact params for apples-to-apples comparison."""
from __future__ import annotations
import pickle, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import simulate, metrics
from strategy_lab.run_v29_regime import (
    _load, dedupe, sig_trend_grade, sig_lateral_bb_fade, sig_regime_switch,
    FEE,
)

OUT = Path(__file__).resolve().parent / "results" / "v29"
SPLIT = pd.Timestamp("2024-01-01", tz="UTC")


def _sig(family, df, p):
    if family == "Trend_Grade_MTF":
        return sig_trend_grade(df, p["thr"], p["rsi_lo"], p["rsi_hi"], 14, p["adx_min"])
    if family == "Lateral_BB_Fade":
        bw_lb = max(1, int(round(200 * {"15m":4,"30m":2,"1h":1,"2h":0.5,"4h":0.25}.get(p.get("tf","4h"),0.25))))
        return sig_lateral_bb_fade(df, p["bb_n"], p["bb_k"], p["adx_max"], 14, bw_lb, p["bw_q"])
    if family == "Regime_Switch":
        return sig_regime_switch(df, p["donch_n"], p["ema_reg"], 20, 2.0, p["adx_lo"], p["adx_hi"], 14)
    raise ValueError(family)


def slice_metrics(df, lsig, ssig, exits, risk, lev, start, end, lbl):
    mask = (df.index >= start) & (df.index < end)
    sub = df.loc[mask].copy()
    l = lsig.reindex(sub.index, fill_value=False)
    s = ssig.reindex(sub.index, fill_value=False)
    if len(sub) < 200: return None
    trades, eq = simulate(sub, dedupe(l), short_entries=dedupe(s),
                          tp_atr=exits["tp"], sl_atr=exits["sl"],
                          trail_atr=exits["trail"], max_hold=exits["mh"],
                          risk_per_trade=risk, leverage_cap=lev, fee=FEE)
    return metrics(lbl, eq, trades)


def main():
    pkl = OUT / "v29_regime_results.pkl"
    d = pickle.load(open(pkl, "rb"))
    rows = []

    for key, w in d.items():
        sym = w["sym"]; family = w["family"]; tf = w["tf"]
        p = dict(w["params"]); p["tf"] = tf
        df = _load(sym, tf)
        if df is None: continue
        try:
            lsig, ssig = _sig(family, df, p)
        except Exception as e:
            print(f"{key}: signal error {e}")
            continue

        m_full = slice_metrics(df, lsig, ssig, w["exits"], w["risk"], w["lev"],
                                df.index[0], df.index[-1] + pd.Timedelta(seconds=1),
                                f"{key}_full")
        m_is = slice_metrics(df, lsig, ssig, w["exits"], w["risk"], w["lev"],
                              df.index[0], SPLIT, f"{key}_is")
        m_oos = slice_metrics(df, lsig, ssig, w["exits"], w["risk"], w["lev"],
                               SPLIT, df.index[-1] + pd.Timedelta(seconds=1),
                               f"{key}_oos")

        if m_oos is None: continue

        full_sh = m_full["sharpe"] if m_full else 0
        is_sh = m_is["sharpe"] if m_is else 0
        oos_sh = m_oos["sharpe"]

        oos_cagr = m_oos["cagr_net"]
        is_cagr = (m_is["cagr_net"] if m_is else 0)
        is_dd = (m_is["dd"] if m_is else 0)
        oos_dd = m_oos["dd"]

        bar = 0.5 * max(is_sh, 0.1)
        verdict = "PASS" if oos_sh >= bar else "FAIL"

        rows.append({
            "key": key, "sym": sym, "family": family, "tf": tf,
            "full_n": m_full["n"] if m_full else 0, "full_Sh": round(full_sh, 2),
            "full_CAGR": round((m_full["cagr_net"] if m_full else 0)*100, 1),
            "IS_n": m_is["n"] if m_is else 0, "IS_Sh": round(is_sh, 2),
            "IS_CAGR": round(is_cagr*100, 1), "IS_DD": round(is_dd*100,1),
            "OOS_n": m_oos["n"], "OOS_Sh": round(oos_sh, 2),
            "OOS_CAGR": round(oos_cagr*100, 1), "OOS_DD": round(oos_dd*100,1),
            "bar": round(bar, 2), "verdict": verdict,
            "params": str(w["params"]),
        })

    df = pd.DataFrame(rows).sort_values(["verdict", "OOS_Sh"], ascending=[True, False])
    df.to_csv(OUT / "v29_oos.csv", index=False)

    pass_df = df[df["verdict"] == "PASS"].copy()
    print(f"\n=== V29 OOS AUDIT ===  total={len(df)}  pass={len(pass_df)}\n")
    print(df.to_string(index=False))
    print(f"\n--- PASS ({len(pass_df)}) ---")
    if len(pass_df):
        print(pass_df[["sym","family","tf","IS_Sh","OOS_Sh","OOS_CAGR","OOS_DD","OOS_n"]].to_string(index=False))


if __name__ == "__main__":
    main()
