"""
V36 — Find the best leverage regime for the hybrid USER+MY portfolio.

Tests:
  A. Static leverage on MY side (V24) — scale XSM sleeve only
     (USER side stays at its natively-tuned 3x cap)
  B. Dynamic leverage: vol-scaled MY side
     lev = target_ann_vol / realised_vol_28d  (clip [0.5, 2.5])
  C. Dynamic leverage: DD-based de-risk
     if portfolio DD from ATH > 15% -> halve MY-side sleeve
     if DD > 30% -> zero MY-side until recovery

All combos tested against 6 fixed USER/MY splits: {50/50, 60/40, 70/30, 80/20}.
Common window 2023-04 to 2026-04 (where both libraries have data).
Output: strategy_lab/results/v35_cross/v36_leverage_grid.csv
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
V35  = BASE / "results" / "v35_cross"
OUT  = V35

BPY = 365.25 * 24 / 4
INIT = 10_000.0


def metrics(eq: pd.Series) -> dict:
    if len(eq) < 20 or eq.iloc[-1] <= 0: return {}
    rets = eq.pct_change(fill_method=None).fillna(0)
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1/max(yrs,0.01)) - 1
    sh = (rets.mean() * BPY) / (rets.std() * np.sqrt(BPY) + 1e-12)
    dd = float((eq / eq.cummax() - 1).min())
    return {"cagr": float(cagr), "sharpe": float(sh),
            "dd": dd, "calmar": cagr / abs(dd) if dd < 0 else 0,
            "final": float(eq.iloc[-1])}


def _apply_leverage(norm: pd.Series, lev: float) -> pd.Series:
    """Apply leverage to a normalised equity curve via its returns."""
    rets = norm.pct_change(fill_method=None).fillna(0)
    lev_rets = rets * lev
    return (1 + lev_rets).cumprod()


def _dyn_lev_vol(norm: pd.Series, target_ann: float = 0.60,
                 lookback_bars: int = 168) -> pd.Series:
    """Dynamic leverage scaled by realised vol; lookback = 28 days of 4h bars."""
    rets = norm.pct_change(fill_method=None).fillna(0)
    roll_vol = rets.rolling(lookback_bars).std() * np.sqrt(BPY)
    lev_series = (target_ann / roll_vol.replace(0, np.nan)).fillna(1.0)
    lev_series = lev_series.clip(0.5, 2.5)
    lev_rets = rets * lev_series.values
    return (1 + lev_rets).cumprod()


def _dyn_lev_dd(norm: pd.Series, dd_soft: float = 0.15,
                dd_hard: float = 0.30, base_lev: float = 1.5) -> pd.Series:
    """DD-based leverage: halve at 15% DD, zero at 30%, full back at ATH."""
    rets = norm.pct_change(fill_method=None).fillna(0)
    cum = np.empty(len(rets)); cum[0] = 1.0
    peak = 1.0; levs = np.empty(len(rets)); levs[0] = base_lev
    for i in range(1, len(rets)):
        dd = cum[i-1] / peak - 1
        if dd <= -dd_hard:     lev = 0.0
        elif dd <= -dd_soft:   lev = 0.5 * base_lev
        else:                  lev = base_lev
        levs[i] = lev
        cum[i] = cum[i-1] * (1 + rets.iloc[i] * lev)
        peak = max(peak, cum[i])
    return pd.Series(cum, index=norm.index)


def main():
    df = pd.read_csv(V35 / "sleeve_equities_2023plus_normed.csv",
                     index_col=0, parse_dates=[0])
    print(f"Window: {df.index[0].date()} -> {df.index[-1].date()}  ({len(df):,} bars)")

    user = df["USER_5SLEEVE_EQW"] / df["USER_5SLEEVE_EQW"].iloc[0]
    v24  = df["MY_V24_MF_1x"]     / df["MY_V24_MF_1x"].iloc[0]
    v15  = df["MY_V15_BALANCED"]  / df["MY_V15_BALANCED"].iloc[0]
    v27  = df["MY_V27_LS_0.5x"]   / df["MY_V27_LS_0.5x"].iloc[0]

    rows = []

    def run_combo(label, w_user, user_lev_delta, my_eq, my_lev, mode):
        """
        w_user: fraction of capital on USER side (w_my = 1 - w_user).
        user_lev_delta: 1.0 = keep USER at native 3x; 1.5 = bump to 4.5x; etc.
        my_eq: normalised equity of my XSM sleeve
        my_lev: leverage applied to MY side returns
        mode: static | dyn_vol | dyn_dd
        """
        u_norm = _apply_leverage(user, user_lev_delta)
        if mode == "static":
            m_norm = _apply_leverage(my_eq, my_lev)
        elif mode == "dyn_vol":
            m_norm = _dyn_lev_vol(my_eq, target_ann=0.60)
        elif mode == "dyn_dd":
            m_norm = _dyn_lev_dd(my_eq, base_lev=my_lev)
        # Combine with fixed weights
        comb = INIT * (w_user * u_norm + (1 - w_user) * m_norm)
        m = metrics(comb)
        row = {"label": label, "w_user": w_user,
               "user_lev_delta": user_lev_delta,
               "my_lev": my_lev, "mode": mode, **m}
        rows.append(row)

    # ------- A. Static leverage grid on V24 XSM sleeve -------
    for w in [0.50, 0.60, 0.70, 0.80]:
        for user_delta in [1.00, 1.33, 1.67]:        # native 3x, bump to 4x, 5x
            for my_lev in [1.0, 1.25, 1.5, 1.75, 2.0, 2.5]:
                label = f"STATIC w={w:.2f} USER_x{int(user_delta*3)} MY_x{my_lev:.2f}"
                run_combo(label, w, user_delta, v24, my_lev, "static")

    # ------- B. Dynamic vol-target leverage -------
    for w in [0.50, 0.70]:
        for target in [0.40, 0.60, 0.80]:
            my = _dyn_lev_vol(v24, target_ann=target)
            u_norm = _apply_leverage(user, 1.00)
            comb = INIT * (w * u_norm + (1 - w) * my)
            m = metrics(comb)
            rows.append({"label": f"DYN_VOL w={w:.2f} target={target:.2f}",
                         "w_user": w, "user_lev_delta": 1.0,
                         "my_lev": target, "mode": "dyn_vol", **m})

    # ------- C. DD-based de-risk -------
    for w in [0.70]:
        for dd_soft in [0.10, 0.15, 0.20]:
            for base in [1.5, 2.0]:
                my = _dyn_lev_dd(v24, dd_soft=dd_soft, dd_hard=0.30, base_lev=base)
                u_norm = _apply_leverage(user, 1.00)
                comb = INIT * (w * u_norm + (1 - w) * my)
                m = metrics(comb)
                rows.append({
                    "label": f"DYN_DD w={w:.2f} base={base} halt@{dd_soft*100:.0f}%",
                    "w_user": w, "user_lev_delta": 1.0, "my_lev": base,
                    "mode": "dyn_dd", **m})

    # ------- D. V15 blend leverage (alt-season heavy) -------
    for w in [0.50, 0.70]:
        for my_lev in [1.0, 1.25, 1.5, 1.75, 2.0]:
            u_norm = _apply_leverage(user, 1.00)
            m_norm = _apply_leverage(v15, my_lev)
            comb = INIT * (w * u_norm + (1 - w) * m_norm)
            m = metrics(comb)
            rows.append({"label": f"V15_MIX w={w:.2f} my_x{my_lev:.2f}",
                         "w_user": w, "user_lev_delta": 1.0,
                         "my_lev": my_lev, "mode": "v15_static", **m})

    # ------- E. V27 (long-short, defensive) -------
    for w in [0.50, 0.70]:
        for my_lev in [0.5, 1.0, 1.5, 2.0]:
            u_norm = _apply_leverage(user, 1.00)
            m_norm = _apply_leverage(v27, my_lev)
            comb = INIT * (w * u_norm + (1 - w) * m_norm)
            m = metrics(comb)
            rows.append({"label": f"V27_MIX w={w:.2f} my_x{my_lev:.2f}",
                         "w_user": w, "user_lev_delta": 1.0,
                         "my_lev": my_lev, "mode": "v27_static", **m})

    res = pd.DataFrame(rows)
    res.to_csv(OUT / "v36_leverage_grid.csv", index=False)
    print(f"\nTested {len(res)} configs.  Saved v36_leverage_grid.csv\n")

    print("=== TOP 10 BY SHARPE (DD < -30% excluded) ===")
    good = res[res["dd"] > -0.30].copy()
    print(good.sort_values("sharpe", ascending=False).head(10)[
        ["label","w_user","my_lev","mode","cagr","sharpe","dd","calmar","final"]
    ].to_string(index=False))

    print("\n=== TOP 10 BY CALMAR (DD < -30% excluded) ===")
    print(good.sort_values("calmar", ascending=False).head(10)[
        ["label","w_user","my_lev","mode","cagr","sharpe","dd","calmar","final"]
    ].to_string(index=False))

    print("\n=== TOP 10 BY CAGR (DD < -35% allowed) ===")
    tall = res[res["dd"] > -0.35]
    print(tall.sort_values("cagr", ascending=False).head(10)[
        ["label","w_user","my_lev","mode","cagr","sharpe","dd","calmar","final"]
    ].to_string(index=False))


if __name__ == "__main__":
    main()
