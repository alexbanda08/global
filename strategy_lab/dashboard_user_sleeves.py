"""
dashboard_user_sleeves — load the 5 USER live-portfolio sleeves WITH per-trade
logs in the schema the native_to_iaf adapter expects.

Mirrors run_v34_portfolio.build_eq_v30 / build_eq_v34 / build_eq_core but
returns (equity_series, trades_df) instead of just equity. Each trades_df
has the columns: entry_time, exit_time, entry_price, exit_price, shares,
return, net_gain, reason, side, bars.

Used by run_dashboard.show() so the IAF dashboard can render per-trade
drill-down for each USER sleeve. The XSM (V15/V24/V27) side has no
per-trade log (rebalance-based), so those entries continue to pass None.
"""
from __future__ import annotations
import pickle
from pathlib import Path

import pandas as pd

from strategy_lab.run_v16_1h_hunt import simulate
from strategy_lab.run_v34_expand import (
    _load, FEE, sig_bbbreak_ls, sig_htf_donchian_ls, scaled,
)
from strategy_lab.run_v30_creative import sig_cci_extreme
from strategy_lab.run_v34_portfolio import OUT as V34_OUT, SLEEVES

V30_PKL = Path(__file__).resolve().parent / "results" / "v30" / "v30_creative_results.pkl"

USER_5_TARGETS = [
    "SOL_BBBreak_4h",
    "DOGE_Donchian_4h",
    "ETH_CCI_4h",
    "AVAX_BBBreak_4h",
    "TON_BBBreak_4h",
]


def _trades_to_df(trades: list[dict]) -> pd.DataFrame:
    """Native simulate() trade dicts -> dashboard-schema DataFrame."""
    if not trades:
        return pd.DataFrame(columns=[
            "entry_time", "exit_time", "entry_price", "exit_price",
            "shares", "return", "net_gain", "reason", "side", "bars",
        ])
    df = pd.DataFrame(trades)
    # The simulate() patch already adds entry_time/exit_time/entry_price/
    # exit_price/shares/net_gain. Rename ret -> return for the dashboard.
    if "ret" in df.columns and "return" not in df.columns:
        df = df.rename(columns={"ret": "return"})
    keep = [c for c in [
        "entry_time", "exit_time", "entry_price", "exit_price",
        "shares", "return", "net_gain", "reason", "side", "bars",
    ] if c in df.columns]
    return df[keep]


def _build_v34(sym, family, tf):
    """Re-run V34 BBBreak_LS / HTF_Donchian using the saved sweep winner."""
    d = pickle.load(open(V34_OUT / "v34_sweep_results.pkl", "rb"))
    key = f"{sym}_{family}_{tf}"
    if key not in d:
        return None, None
    w = d[key]
    df = _load(sym, tf)
    params = dict(w["params"])
    exits, risk, lev = w["exits"], w["risk"], w["lev"]
    if family == "BBBreak_LS":
        params["regime_len"] = scaled(params["regime_len"], tf)
        params["n"] = scaled(params["n"], tf)
        ls, ss = sig_bbbreak_ls(df, **params)
    elif family == "HTF_Donchian":
        ls, ss = sig_htf_donchian_ls(df, **params)
    else:
        return None, None
    trades, eq = simulate(df, ls, ss,
                          tp_atr=exits["tp"], sl_atr=exits["sl"],
                          trail_atr=exits["trail"], max_hold=exits["mh"],
                          risk_per_trade=risk, leverage_cap=lev, fee=FEE)
    return eq, _trades_to_df(trades)


def _build_v30_cci(sym, tf):
    """Re-run the V30 CCI_Extreme winner from the V30 pickle (params + exits)."""
    if not V30_PKL.exists():
        return None, None
    d = pickle.load(open(V30_PKL, "rb"))
    key = f"{sym}_CCI_EXTREME_REV"
    if key not in d:
        return None, None
    w = d[key]
    if w.get("tf") != tf:
        return None, None
    df = _load(sym, tf)
    p = w["params"]
    # V30 stores cci_thr; sig_cci_extreme takes cci_lo=-thr, cci_hi=+thr.
    thr = float(p["cci_thr"])
    ls = sig_cci_extreme(df, cci_n=int(p["cci_n"]), cci_lo=-thr, cci_hi=thr,
                         adx_max=int(p["adx_max"]), adx_n=14)
    # sig_cci_extreme returns a single long-only Series in the form used here.
    # If it returns a tuple (ls, ss), unpack; otherwise use ls only.
    ss = None
    if isinstance(ls, tuple):
        ls, ss = ls
    exits, risk, lev = w["exits"], w["risk"], w["lev"]
    trades, eq = simulate(df, ls, ss,
                          tp_atr=exits["tp"], sl_atr=exits["sl"],
                          trail_atr=exits["trail"], max_hold=exits["mh"],
                          risk_per_trade=risk, leverage_cap=lev, fee=FEE)
    return eq, _trades_to_df(trades)


def load_user_5sleeve_with_trades() -> dict[str, tuple[pd.Series, pd.DataFrame | None]]:
    """Returns {sleeve_label: (eq_series, trades_df_or_None)} for the 5 USER sleeves."""
    out: dict[str, tuple[pd.Series, pd.DataFrame | None]] = {}
    for row in SLEEVES:
        label, sym, family, tf, _params, _exits, _risk, _lev, fn_name = row
        if label not in USER_5_TARGETS:
            continue
        try:
            if fn_name == "v34_from_pickle":
                eq, trs = _build_v34(sym, family, tf)
            elif fn_name == "v30_from_pickle":
                eq, trs = _build_v30_cci(sym, tf)
            else:
                # bb_ls_scaled / bb_ls_raw / donch_ls (V32 audit-clean variants)
                df = _load(sym, tf)
                p = dict(_params)
                if fn_name in ("bb_ls_scaled", "bb_ls_raw"):
                    ls, ss = sig_bbbreak_ls(df, **p)
                elif fn_name == "donch_ls":
                    ls, ss = sig_htf_donchian_ls(df, **p)
                else:
                    eq, trs = None, None
                    out[label] = (eq, trs)
                    continue
                trades, eq = simulate(
                    df, ls, ss,
                    tp_atr=_exits["tp"], sl_atr=_exits["sl"],
                    trail_atr=_exits["trail"], max_hold=_exits["mh"],
                    risk_per_trade=_risk, leverage_cap=_lev, fee=FEE,
                )
                trs = _trades_to_df(trades)
            out[label] = (eq, trs)
            n_tr = 0 if trs is None else len(trs)
            print(f"  loaded {label}: bars={0 if eq is None else len(eq):,} trades={n_tr}")
        except Exception as e:
            print(f"  ERROR on {label}: {type(e).__name__}: {e}")
            out[label] = (None, None)
    return out


if __name__ == "__main__":
    print("Loading USER 5-sleeve with per-trade logs...")
    res = load_user_5sleeve_with_trades()
    print(f"\nLoaded {sum(1 for v in res.values() if v[0] is not None)}/{len(USER_5_TARGETS)} sleeves")
