"""V30 OOS audit — replays each winner's config on IS (<2024) and OOS (>=2024)
separately, applies verdict rule: PASS if OOS Sharpe >= 0.5 * max(IS Sharpe, 0.1)."""
from __future__ import annotations
import pickle, sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import simulate, metrics
from strategy_lab.run_v30_creative import (
    _load, dedupe, sig_ttm_squeeze, sig_vwap_zfade, sig_connors_rsi,
    sig_supertrend_flip, sig_cci_extreme, scaled, FEE,
)

OUT = Path(__file__).resolve().parent / "results" / "v30"
SPLIT = pd.Timestamp("2024-01-01", tz="UTC")


def _sig(family, df, p, tf):
    if family == "TTM_Squeeze_Pop":
        return sig_ttm_squeeze(df, 20, p["bb_k"], 20, p["kc_mult"], p["mom_n"])
    if family == "VWAP_Zfade":
        return sig_vwap_zfade(df, scaled(p["vwap_n"], tf), p["z_thr"], p["adx_max"], 14)
    if family == "Connors_RSI":
        return sig_connors_rsi(df, p["crsi_lo"], p["crsi_hi"], p["adx_max"], 14)
    if family == "SuperTrend_Flip":
        return sig_supertrend_flip(df, p["st_n"], p["st_mult"], p["ema_reg"])
    if family == "CCI_Extreme_Rev":
        return sig_cci_extreme(df, p["cci_n"], -p["cci_thr"], p["cci_thr"], p["adx_max"], 14)
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
    pkl = OUT / "v30_creative_results.pkl"
    d = pickle.load(open(pkl, "rb"))
    rows = []

    for key, w in d.items():
        sym = w["sym"]; family = w["family"]; tf = w["tf"]
        p = dict(w["params"])
        df = _load(sym, tf)
        if df is None: continue
        try:
            lsig, ssig = _sig(family, df, p, tf)
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
    df.to_csv(OUT / "v30_oos.csv", index=False)

    pass_df = df[df["verdict"] == "PASS"].copy()
    print(f"\n=== V30 OOS AUDIT ===  total={len(df)}  pass={len(pass_df)}\n")
    pd.set_option('display.max_colwidth', 60)
    pd.set_option('display.width', 180)
    print(df[["sym","family","tf","IS_Sh","OOS_Sh","OOS_CAGR","OOS_DD","OOS_n","verdict"]].to_string(index=False))
    print(f"\n--- PASS ({len(pass_df)}) ---")
    if len(pass_df):
        print(pass_df[["sym","family","tf","IS_Sh","OOS_Sh","OOS_CAGR","OOS_DD","OOS_n"]].to_string(index=False))


if __name__ == "__main__":
    main()
