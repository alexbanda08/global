"""
LEVERAGE IMPACT STUDY
=====================
Tests 5 leverage variants vs fixed 3x baseline across the 7 promotion-grade
sleeves used in P2-P7 portfolios:

  Exp 1  Static risk_per_trade sweep  (0.02 -> 0.10) x leverage_cap (3, 5)
  Exp 2  Leverage-cap sweep           (2x -> 10x) at fixed risk 0.03
  Exp 3  Regime-gated size            (trend x vol quadrants)
  Exp 4  Signal-confidence gate       (per-strategy extremity boost)
  Exp 5  Portfolio-DD throttle        (reduce size as DD deepens)
  Exp 6  Combined-best portfolio      (best per-sleeve -> blend vs P3/P5/P7)

Outputs:
  docs/research/phase5_results/leverage_exp1_static.csv
  docs/research/phase5_results/leverage_exp2_cap.csv
  docs/research/phase5_results/leverage_exp3_regime.csv
  docs/research/phase5_results/leverage_exp4_conf.csv
  docs/research/phase5_results/leverage_exp5_ddthrottle.csv
  docs/research/phase5_results/leverage_exp6_combined.json
  docs/research/phase5_results/leverage_summary.csv
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

from strategy_lab.engine import load
from strategy_lab.eval.perps_simulator import atr, FEE_DEFAULT, SLIP_DEFAULT

OUT = REPO / "docs" / "research" / "phase5_results"
OUT.mkdir(parents=True, exist_ok=True)
BPY = 365.25 * 6   # bars per year for 4h

SLEEVE_SPECS = {
    "CCI_ETH_4h":    ("run_v30_creative.py",   "sig_cci_extreme",     "ETHUSDT",  "4h"),
    "STF_SOL_4h":    ("run_v30_creative.py",   "sig_supertrend_flip", "SOLUSDT",  "4h"),
    "STF_AVAX_4h":   ("run_v30_creative.py",   "sig_supertrend_flip", "AVAXUSDT", "4h"),
    "STF_DOGE_4h":   ("run_v30_creative.py",   "sig_supertrend_flip", "DOGEUSDT", "4h"),
    "VWZ_INJ_4h":    ("run_v30_creative.py",   "sig_vwap_zfade",      "LINKUSDT", "4h"),
    "LATBB_AVAX_4h": ("run_v29_regime.py",     "sig_lateral_bb_fade", "AVAXUSDT", "4h"),
    "BB_AVAX_4h":    ("run_v38b_smc_mixes.py", "sig_bbbreak",         "AVAXUSDT", "4h"),
}

# Portfolios reused
PORTFOLIOS = {
    "P3": ["CCI_ETH_4h", "STF_AVAX_4h", "STF_SOL_4h"],
    "P5": ["CCI_ETH_4h", "LATBB_AVAX_4h", "STF_SOL_4h"],
    "P7": ["BB_AVAX_4h", "CCI_ETH_4h", "STF_SOL_4h"],
}

# ---------------------------------------------------------------- signal loader
_SIG_FN = {}
def _import_sig(script: str, fn: str):
    key = f"{script}:{fn}"
    if key in _SIG_FN:
        return _SIG_FN[key]
    path = REPO / "strategy_lab" / script
    spec = importlib.util.spec_from_file_location(script.replace(".", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _SIG_FN[key] = getattr(mod, fn)
    return _SIG_FN[key]

# ---------------------------------------------------------------- data cache
_DATA_CACHE: dict[str, tuple[pd.DataFrame, pd.Series, pd.Series]] = {}
def sleeve_data(label: str):
    if label in _DATA_CACHE:
        return _DATA_CACHE[label]
    script, fn, sym, tf = SLEEVE_SPECS[label]
    df = load(sym, tf, start="2021-01-01", end="2026-03-31")
    if "open" not in df.columns and "Open" in df.columns:
        df = df.rename(columns=str.lower)
    sig = _import_sig(script, fn)
    out = sig(df)
    # sig returns (long_entries, short_entries)
    le, se = out if isinstance(out, tuple) else (out, None)
    _DATA_CACHE[label] = (df, le, se)
    return df, le, se

# ---------------------------------------------------------------- leveraged sim
def simulate_lev(
    df: pd.DataFrame,
    long_entries: pd.Series,
    short_entries: pd.Series | None = None,
    size_mult=1.0,                   # scalar or per-bar pd.Series
    risk_per_trade: float = 0.03,
    leverage_cap: float = 3.0,
    tp_atr: float = 5.0, sl_atr: float = 2.0,
    trail_atr: float | None = 3.5, max_hold: int = 72,
    fee: float = FEE_DEFAULT, slip: float = SLIP_DEFAULT,
    init_cash: float = 10_000.0,
) -> tuple[list[dict], pd.Series]:
    """Canonical simulator + per-bar size multiplier."""
    op = df["open"].to_numpy(dtype=float); hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float);  cl = df["close"].to_numpy(dtype=float)
    at = atr(df)

    sig_l = long_entries.reindex(df.index).fillna(False).to_numpy(dtype=bool)
    sig_s = (short_entries.reindex(df.index).fillna(False).to_numpy(dtype=bool)
             if short_entries is not None else np.zeros(len(df), dtype=bool))

    if isinstance(size_mult, pd.Series):
        smult = size_mult.reindex(df.index).fillna(1.0).to_numpy(dtype=float)
    else:
        smult = np.full(len(df), float(size_mult))

    N = len(df); cash = init_cash
    eq = np.empty(N); eq[0] = cash
    pos = 0; entry_p = 0.0; sl = 0.0; tp = 0.0
    size = 0.0; entry_idx = 0; last_exit = -9999
    hh = 0.0; ll = 0.0
    trades: list[dict] = []

    for i in range(1, N - 1):
        if pos != 0:
            held = i - entry_idx
            if trail_atr is not None and np.isfinite(at[i]) and at[i] > 0:
                if pos == 1:
                    hh = max(hh, hi[i]); new_sl = hh - trail_atr * at[i]
                    if new_sl > sl: sl = new_sl
                else:
                    ll = min(ll, lo[i]) if ll > 0 else lo[i]
                    new_sl = ll + trail_atr * at[i]
                    if new_sl < sl: sl = new_sl

            exited = False; ep = 0.0; reason = ""
            if pos == 1:
                if   lo[i] <= sl: ep, reason, exited = sl*(1-slip), "SL", True
                elif hi[i] >= tp: ep, reason, exited = tp*(1-slip), "TP", True
                elif held >= max_hold: ep, reason, exited = cl[i], "TIME", True
            else:
                if   hi[i] >= sl: ep, reason, exited = sl*(1+slip), "SL", True
                elif lo[i] <= tp: ep, reason, exited = tp*(1+slip), "TP", True
                elif held >= max_hold: ep, reason, exited = cl[i], "TIME", True

            if exited:
                pnl = (ep - entry_p) * pos
                fee_cost = size * (entry_p + ep) * fee
                realized = size * pnl - fee_cost
                eq_at_entry = cash; cash += realized
                ret = realized / max(eq_at_entry, 1.0)
                trades.append({"ret": ret, "realized": realized,
                               "reason": reason, "side": pos, "bars": held,
                               "entry": entry_p, "exit": ep,
                               "entry_idx": entry_idx, "exit_idx": i})
                pos = 0; last_exit = i; eq[i] = cash
                continue

        if pos == 0 and (i - last_exit) > 2 and i + 1 < N:
            take_long = sig_l[i]; take_short = sig_s[i]
            if take_long or take_short:
                direction = 1 if take_long else -1
                ep_new = op[i+1] * (1 + slip * direction)
                if np.isfinite(at[i]) and at[i] > 0 and cash > 0 and ep_new > 0:
                    risk_dollars = cash * risk_per_trade
                    stop_dist = sl_atr * at[i]
                    if stop_dist > 0:
                        size_risk = risk_dollars / stop_dist
                        size_cap  = (cash * leverage_cap) / ep_new
                        new_size  = min(size_risk, size_cap) * smult[i+1]
                        s_stop = ep_new - sl_atr * at[i] * direction
                        t_stop = ep_new + tp_atr * at[i] * direction
                        if new_size > 0 and np.isfinite(s_stop) and np.isfinite(t_stop):
                            pos = direction; entry_p = ep_new
                            sl = s_stop; tp = t_stop; size = new_size
                            entry_idx = i + 1; hh = ep_new; ll = ep_new

        eq[i] = cash if pos == 0 else cash + size * (cl[i] - entry_p) * pos

    eq[-1] = eq[-2]
    return trades, pd.Series(eq, index=df.index)

# ---------------------------------------------------------------- metrics
def metrics(eq: pd.Series, trades: list[dict], label: str = "") -> dict:
    n = len(trades)
    if n < 2 or len(eq) < 30:
        return {"label": label, "n": n, "sharpe": 0, "cagr": 0,
                "mdd": 0, "calmar": 0, "win": 0, "min_yr": 0}
    rets = eq.pct_change().dropna()
    mu = float(rets.mean()); sd = float(rets.std())
    sh = (mu / sd) * np.sqrt(BPY) if sd > 0 else 0.0
    peak = eq.cummax()
    mdd = float((eq / peak - 1.0).min())
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    total = float(eq.iloc[-1] / eq.iloc[0]) - 1.0
    cagr = (1 + total) ** (1 / max(yrs, 1e-6)) - 1.0
    cal = cagr / abs(mdd) if mdd != 0 else 0.0
    win = sum(1 for t in trades if t.get("ret", 0) > 0) / n
    # min-yr
    yrs_pos = []
    for yr in sorted(set(eq.index.year)):
        e = eq[eq.index.year == yr]
        if len(e) >= 30:
            yrs_pos.append(float(e.iloc[-1] / e.iloc[0] - 1))
    min_yr = min(yrs_pos) if yrs_pos else 0
    return {"label": label, "n": n, "sharpe": round(sh, 2),
            "cagr": round(cagr, 3), "mdd": round(mdd, 3),
            "calmar": round(cal, 2), "win": round(win, 2),
            "min_yr": round(min_yr, 3)}

# ---------------------------------------------------------------- regime labels
def compute_regimes(df: pd.DataFrame) -> pd.DataFrame:
    """Return per-bar DataFrame with columns: trend_strong (bool), vol_low (bool)."""
    close = df["close"]
    # Trend via EMA slope + price vs EMA-200
    ema200 = close.ewm(span=200, adjust=False).mean()
    ema50  = close.ewm(span=50,  adjust=False).mean()
    trend_strong = ((close > ema200) & (ema50 > ema200)) | ((close < ema200) & (ema50 < ema200))
    # Vol via ATR / price rolling rank
    a = pd.Series(atr(df), index=df.index)
    vol_ratio = a / close
    # rolling quantile over 500 bars ~= 3 mo
    vol_rank = vol_ratio.rolling(500, min_periods=100).rank(pct=True)
    vol_low = vol_rank < 0.5
    return pd.DataFrame({"trend_strong": trend_strong.fillna(False),
                         "vol_low": vol_low.fillna(False)}, index=df.index)

# ---------------------------------------------------------------- confidence
def compute_confidence(df: pd.DataFrame, sleeve_label: str) -> pd.Series:
    """Return per-bar confidence score in [0.5, 2.0] specific to sleeve family."""
    close = df["close"]; high = df["high"]; low = df["low"]
    a = pd.Series(atr(df), index=df.index)

    if "CCI" in sleeve_label:
        # CCI(20) magnitude — higher |CCI| at entry = higher confidence
        tp = (high + low + close) / 3
        sma = tp.rolling(20).mean()
        mad = tp.rolling(20).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
        cci = (tp - sma) / (0.015 * mad.replace(0, np.nan))
        score = cci.abs() / 150.0
        return score.clip(0.5, 2.0).fillna(1.0)

    if "STF" in sleeve_label or "BB_AVAX" in sleeve_label:
        # Distance from EMA200 in ATR units — stronger regime = higher conf
        ema200 = close.ewm(span=200, adjust=False).mean()
        dist_atr = (close - ema200).abs() / a.replace(0, np.nan)
        score = 0.5 + dist_atr.clip(upper=6) / 4.0   # 0.5 at 0 ATR -> 2.0 at 6 ATR
        return score.clip(0.5, 2.0).fillna(1.0)

    if "LATBB" in sleeve_label:
        # BB %b extremity — %b close to 0 or 1 = higher conf
        ma = close.rolling(20).mean(); sd = close.rolling(20).std()
        bb_up = ma + 2.0 * sd; bb_dn = ma - 2.0 * sd
        pctb = (close - bb_dn) / (bb_up - bb_dn)
        ext = (pctb - 0.5).abs() * 2.0   # 0 center -> 1 edge
        score = 0.5 + ext.clip(upper=1.0) * 1.5
        return score.clip(0.5, 2.0).fillna(1.0)

    if "VWZ" in sleeve_label:
        # Z-score magnitude
        vwap = close.rolling(100).mean()  # simplified vwap
        resid = close - vwap
        z = resid / resid.rolling(100).std().replace(0, np.nan)
        score = z.abs() / 2.0
        return score.clip(0.5, 2.0).fillna(1.0)

    return pd.Series(1.0, index=df.index)

# ---------------------------------------------------------------- portfolio blender
def blend_daily(curves: dict[str, pd.Series]) -> pd.Series:
    idx = None
    for eq in curves.values():
        idx = eq.index if idx is None else idx.intersection(eq.index)
    rets = pd.DataFrame({k: curves[k].reindex(idx).pct_change().fillna(0)
                         for k in curves})
    port_rets = rets.mean(axis=1)
    return (1.0 + port_rets).cumprod() * 10_000.0

def blend_metrics(curves: dict[str, pd.Series], label: str) -> dict:
    eq = blend_daily(curves)
    rets = eq.pct_change().dropna()
    mu = float(rets.mean()); sd = float(rets.std())
    sh = (mu / sd) * np.sqrt(BPY) if sd > 0 else 0
    peak = eq.cummax()
    mdd = float((eq / peak - 1).min())
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    total = float(eq.iloc[-1] / eq.iloc[0]) - 1
    cagr = (1 + total) ** (1 / max(yrs, 1e-6)) - 1
    cal = cagr / abs(mdd) if mdd != 0 else 0
    yrs_pos = []
    for yr in sorted(set(eq.index.year)):
        e = eq[eq.index.year == yr]
        if len(e) >= 30:
            yrs_pos.append(float(e.iloc[-1] / e.iloc[0] - 1))
    return {"label": label, "sharpe": round(sh, 2),
            "cagr": round(cagr, 3), "mdd": round(mdd, 3),
            "calmar": round(cal, 2),
            "min_yr": round(min(yrs_pos), 3) if yrs_pos else 0,
            "pos_yrs": sum(1 for r in yrs_pos if r > 0)}

# ==============================================================================
# EXPERIMENTS
# ==============================================================================
def exp1_static():
    print("\n=== EXP 1: Static risk sweep ===")
    risks = [0.02, 0.03, 0.04, 0.05, 0.06, 0.08]
    caps  = [3.0, 5.0]
    rows = []
    for lbl in SLEEVE_SPECS:
        df, le, se = sleeve_data(lbl)
        for r in risks:
            for c in caps:
                t, eq = simulate_lev(df, le, se, risk_per_trade=r, leverage_cap=c)
                m = metrics(eq, t, lbl)
                m.update({"risk_pct": r, "cap": c})
                rows.append(m)
        best = max([x for x in rows if x["label"] == lbl], key=lambda x: x["sharpe"])
        print(f"  {lbl:14s} best @ risk={best['risk_pct']} cap={best['cap']}  "
              f"Sharpe={best['sharpe']} Calmar={best['calmar']} MDD={best['mdd']}")
    df_out = pd.DataFrame(rows)
    df_out.to_csv(OUT / "leverage_exp1_static.csv", index=False)
    return df_out

def exp2_cap():
    print("\n=== EXP 2: Leverage-cap binding point ===")
    caps = [2.0, 3.0, 5.0, 8.0, 10.0]
    rows = []
    for lbl in SLEEVE_SPECS:
        df, le, se = sleeve_data(lbl)
        for c in caps:
            t, eq = simulate_lev(df, le, se, risk_per_trade=0.03, leverage_cap=c)
            m = metrics(eq, t, lbl)
            m.update({"cap": c})
            rows.append(m)
    df_out = pd.DataFrame(rows)
    df_out.to_csv(OUT / "leverage_exp2_cap.csv", index=False)
    # print delta vs cap=3
    pivot = df_out.pivot(index="label", columns="cap", values="sharpe")
    print(pivot.to_string())
    return df_out

def exp3_regime():
    print("\n=== EXP 3: Regime-gated size ===")
    # Variants: (name, trend_strong_mult, vol_low_mult, both_mult, none_mult)
    variants = {
        "trend_only":   {"TS_V-": 1.5, "TS_V+": 1.5, "T-_V-": 1.0, "T-_V+": 1.0},
        "vol_only":     {"TS_V-": 1.5, "TS_V+": 1.0, "T-_V-": 1.5, "T-_V+": 1.0},
        "trend_x_vol":  {"TS_V-": 2.0, "TS_V+": 1.25,"T-_V-": 1.0, "T-_V+": 0.5},
        "defensive":    {"TS_V-": 1.25,"TS_V+": 0.75,"T-_V-": 1.0, "T-_V+": 0.5},
        "aggressive":   {"TS_V-": 2.5, "TS_V+": 1.5, "T-_V-": 1.25,"T-_V+": 0.75},
    }
    rows = []
    for lbl in SLEEVE_SPECS:
        df, le, se = sleeve_data(lbl)
        reg = compute_regimes(df)
        # baseline
        t, eq = simulate_lev(df, le, se, risk_per_trade=0.03, leverage_cap=3.0)
        m = metrics(eq, t, lbl); m["variant"] = "baseline_1x"; rows.append(m)
        for vname, mults in variants.items():
            mult = pd.Series(1.0, index=df.index)
            mult[ reg["trend_strong"] &  reg["vol_low"]] = mults["TS_V-"]
            mult[ reg["trend_strong"] & ~reg["vol_low"]] = mults["TS_V+"]
            mult[~reg["trend_strong"] &  reg["vol_low"]] = mults["T-_V-"]
            mult[~reg["trend_strong"] & ~reg["vol_low"]] = mults["T-_V+"]
            t, eq = simulate_lev(df, le, se, size_mult=mult,
                                 risk_per_trade=0.03, leverage_cap=5.0)
            m = metrics(eq, t, lbl); m["variant"] = vname; rows.append(m)
        best = max([x for x in rows if x["label"] == lbl], key=lambda x: x["sharpe"])
        print(f"  {lbl:14s} best={best['variant']:14s}  "
              f"Sharpe={best['sharpe']} Calmar={best['calmar']}")
    df_out = pd.DataFrame(rows)
    df_out.to_csv(OUT / "leverage_exp3_regime.csv", index=False)
    return df_out

def exp4_conf():
    print("\n=== EXP 4: Signal-confidence gate ===")
    # Variants: tilt sizing by signal strength (per-sleeve confidence score)
    #   mild:   score clipped to [0.75, 1.5]
    #   medium: score as-is (0.5, 2.0)
    #   strong: square the score (0.25, 4.0 clipped at 3.0)
    rows = []
    for lbl in SLEEVE_SPECS:
        df, le, se = sleeve_data(lbl)
        conf = compute_confidence(df, lbl)
        # baseline
        t, eq = simulate_lev(df, le, se, risk_per_trade=0.03, leverage_cap=3.0)
        m = metrics(eq, t, lbl); m["variant"] = "baseline_1x"; rows.append(m)
        for vname, transform in [
            ("mild",   lambda s: s.clip(0.75, 1.5)),
            ("medium", lambda s: s),
            ("strong", lambda s: (s ** 2).clip(0.25, 3.0)),
        ]:
            mult = transform(conf)
            t, eq = simulate_lev(df, le, se, size_mult=mult,
                                 risk_per_trade=0.03, leverage_cap=5.0)
            m = metrics(eq, t, lbl); m["variant"] = vname; rows.append(m)
        best = max([x for x in rows if x["label"] == lbl], key=lambda x: x["sharpe"])
        print(f"  {lbl:14s} best={best['variant']:10s}  "
              f"Sharpe={best['sharpe']} Calmar={best['calmar']} "
              f"CAGR={best['cagr']}")
    df_out = pd.DataFrame(rows)
    df_out.to_csv(OUT / "leverage_exp4_conf.csv", index=False)
    return df_out

def exp5_dd_throttle(sleeve_curves: dict[str, pd.Series]):
    """
    Portfolio-level drawdown throttle. Since throttle depends on running DD
    of the blend, we replay the blend bar-by-bar (daily resample).
    """
    print("\n=== EXP 5: Portfolio-DD throttle ===")
    variants = {
        "none":        [( 0.00, 1.00), ( 1.00, 1.00)],
        "mild":        [( 0.00, 1.00), ( 0.05, 0.80), ( 0.10, 0.60), ( 0.15, 0.40)],
        "medium":      [( 0.00, 1.00), ( 0.05, 0.70), ( 0.10, 0.40), ( 0.15, 0.20)],
        "hard":        [( 0.00, 1.00), ( 0.05, 0.50), ( 0.10, 0.25), ( 0.15, 0.10)],
    }
    rows = []
    for pname, sleeves in PORTFOLIOS.items():
        # base blend (no throttle, daily EQW)
        idx = None
        for lbl in sleeves:
            eq = sleeve_curves[lbl]
            idx = eq.index if idx is None else idx.intersection(eq.index)
        rets = pd.DataFrame({lbl: sleeve_curves[lbl].reindex(idx).pct_change().fillna(0)
                             for lbl in sleeves})
        # apply throttle each day based on current DD
        for vname, schedule in variants.items():
            throttle = np.ones(len(idx))
            eq = np.empty(len(idx)); eq[0] = 1.0
            peak = 1.0
            for i in range(1, len(idx)):
                # current DD
                curr_peak = max(peak, eq[i-1])
                dd = (eq[i-1] - curr_peak) / curr_peak
                # select multiplier from schedule (last threshold crossed)
                mult = 1.0
                for thr, m in schedule:
                    if -dd >= thr:
                        mult = m
                throttle[i] = mult
                r = rets.iloc[i].mean() * mult
                eq[i] = eq[i-1] * (1 + r)
                peak = max(peak, eq[i])
            port_eq = pd.Series(eq, index=idx) * 10_000.0
            rs = port_eq.pct_change().dropna()
            mu = float(rs.mean()); sd = float(rs.std())
            sh = (mu/sd)*np.sqrt(BPY) if sd>0 else 0
            pk = port_eq.cummax(); mdd = float((port_eq/pk - 1).min())
            yrs = (port_eq.index[-1]-port_eq.index[0]).total_seconds()/(365.25*86400)
            total = float(port_eq.iloc[-1]/port_eq.iloc[0] - 1)
            cagr = (1+total)**(1/max(yrs,1e-6))-1
            cal = cagr/abs(mdd) if mdd!=0 else 0
            yrs_pos = []
            for yr in sorted(set(port_eq.index.year)):
                e = port_eq[port_eq.index.year == yr]
                if len(e) >= 30:
                    yrs_pos.append(float(e.iloc[-1]/e.iloc[0]-1))
            rows.append({
                "portfolio": pname, "variant": vname,
                "sharpe": round(sh, 2), "cagr": round(cagr, 3),
                "mdd": round(mdd, 3), "calmar": round(cal, 2),
                "min_yr": round(min(yrs_pos), 3) if yrs_pos else 0,
                "pos_yrs": sum(1 for r in yrs_pos if r > 0),
            })
        best = max([x for x in rows if x["portfolio"] == pname], key=lambda x: x["calmar"])
        print(f"  {pname} best={best['variant']:8s}  "
              f"Sharpe={best['sharpe']} Calmar={best['calmar']} "
              f"MDD={best['mdd']} min_yr={best['min_yr']}")
    df_out = pd.DataFrame(rows)
    df_out.to_csv(OUT / "leverage_exp5_ddthrottle.csv", index=False)
    return df_out

def exp6_combined(exp1: pd.DataFrame, exp3: pd.DataFrame, exp4: pd.DataFrame):
    """Best per-sleeve config -> rebuild curves -> blend & compare."""
    print("\n=== EXP 6: Combined-best leveraged portfolios ===")
    # pick best config per sleeve from each experiment family
    best_per = {}
    for lbl in SLEEVE_SPECS:
        # gather all rows pertaining to this sleeve
        e1 = exp1[exp1["label"] == lbl].sort_values("sharpe", ascending=False).head(1)
        e3 = exp3[exp3["label"] == lbl].sort_values("sharpe", ascending=False).head(1)
        e4 = exp4[exp4["label"] == lbl].sort_values("sharpe", ascending=False).head(1)
        candidates = {
            "static":  (e1["sharpe"].iloc[0], {"risk": float(e1["risk_pct"].iloc[0]),
                                               "cap": float(e1["cap"].iloc[0]),
                                               "mode": "static"}),
            "regime":  (e3["sharpe"].iloc[0], {"variant": e3["variant"].iloc[0],
                                               "mode": "regime"}),
            "conf":    (e4["sharpe"].iloc[0], {"variant": e4["variant"].iloc[0],
                                               "mode": "conf"}),
        }
        # pick best by sharpe
        best = max(candidates.items(), key=lambda kv: kv[1][0])
        best_per[lbl] = {"name": best[0], "sharpe": best[1][0], "cfg": best[1][1]}
        print(f"  {lbl:14s} -> {best[0]:8s}  Sharpe={best[1][0]}  cfg={best[1][1]}")

    # rebuild equity curves with best config per sleeve
    leveraged_curves: dict[str, pd.Series] = {}
    for lbl, info in best_per.items():
        cfg = info["cfg"]; df, le, se = sleeve_data(lbl)
        if cfg["mode"] == "static":
            t, eq = simulate_lev(df, le, se,
                                 risk_per_trade=cfg["risk"],
                                 leverage_cap=cfg["cap"])
        elif cfg["mode"] == "regime":
            reg = compute_regimes(df)
            variants = {
                "trend_only":  {"TS_V-":1.5,"TS_V+":1.5,"T-_V-":1.0,"T-_V+":1.0},
                "vol_only":    {"TS_V-":1.5,"TS_V+":1.0,"T-_V-":1.5,"T-_V+":1.0},
                "trend_x_vol": {"TS_V-":2.0,"TS_V+":1.25,"T-_V-":1.0,"T-_V+":0.5},
                "defensive":   {"TS_V-":1.25,"TS_V+":0.75,"T-_V-":1.0,"T-_V+":0.5},
                "aggressive":  {"TS_V-":2.5,"TS_V+":1.5,"T-_V-":1.25,"T-_V+":0.75},
                "baseline_1x": None,
            }
            v = cfg["variant"]
            if v == "baseline_1x":
                t, eq = simulate_lev(df, le, se, risk_per_trade=0.03, leverage_cap=3.0)
            else:
                mults = variants[v]
                mult = pd.Series(1.0, index=df.index)
                mult[ reg["trend_strong"] &  reg["vol_low"]] = mults["TS_V-"]
                mult[ reg["trend_strong"] & ~reg["vol_low"]] = mults["TS_V+"]
                mult[~reg["trend_strong"] &  reg["vol_low"]] = mults["T-_V-"]
                mult[~reg["trend_strong"] & ~reg["vol_low"]] = mults["T-_V+"]
                t, eq = simulate_lev(df, le, se, size_mult=mult,
                                     risk_per_trade=0.03, leverage_cap=5.0)
        elif cfg["mode"] == "conf":
            conf = compute_confidence(df, lbl); v = cfg["variant"]
            if v == "baseline_1x":
                t, eq = simulate_lev(df, le, se, risk_per_trade=0.03, leverage_cap=3.0)
            else:
                if v == "mild":   conf = conf.clip(0.75, 1.5)
                elif v == "strong": conf = (conf ** 2).clip(0.25, 3.0)
                t, eq = simulate_lev(df, le, se, size_mult=conf,
                                     risk_per_trade=0.03, leverage_cap=5.0)
        leveraged_curves[lbl] = eq

    # Re-blend all known portfolios w/ leveraged curves and compare
    results = {}
    for pname, sleeves in PORTFOLIOS.items():
        curves = {s: leveraged_curves[s] for s in sleeves}
        results[pname + "_LEV"] = blend_metrics(curves, pname + "_LEV")

    # Also try a fresh best-4 blend (ETH + SOL + AVAX + DOGE — top 4 by sharpe)
    ranked = sorted(best_per.items(), key=lambda kv: kv[1]["sharpe"], reverse=True)
    top3 = [k for k, _ in ranked[:3]]
    top4 = [k for k, _ in ranked[:4]]
    results["TOP3_LEV"] = blend_metrics({s: leveraged_curves[s] for s in top3}, "TOP3_LEV")
    results["TOP4_LEV"] = blend_metrics({s: leveraged_curves[s] for s in top4}, "TOP4_LEV")

    with open(OUT / "leverage_exp6_combined.json", "w") as f:
        json.dump({"best_per_sleeve": best_per,
                   "blended": results,
                   "top3_members": top3,
                   "top4_members": top4}, f, indent=2, default=str)
    print("\n  Combined portfolio results:")
    for k, v in results.items():
        print(f"    {k:14s}  Sharpe={v['sharpe']} CAGR={v['cagr']} "
              f"MDD={v['mdd']} Calmar={v['calmar']} min_yr={v['min_yr']}")
    return results, best_per

# ==============================================================================
# MAIN
# ==============================================================================
def main():
    t0 = time.time()
    print("Warming sleeve data cache...")
    for lbl in SLEEVE_SPECS:
        sleeve_data(lbl)
        print(f"  {lbl} loaded")

    # baseline curves for exp 5 (no leverage tweaks, canonical)
    baseline_curves = {}
    for lbl in SLEEVE_SPECS:
        df, le, se = sleeve_data(lbl)
        _, eq = simulate_lev(df, le, se, risk_per_trade=0.03, leverage_cap=3.0)
        baseline_curves[lbl] = eq

    e1 = exp1_static()
    e2 = exp2_cap()
    e3 = exp3_regime()
    e4 = exp4_conf()
    e5 = exp5_dd_throttle(baseline_curves)
    combined, best_per = exp6_combined(e1, e3, e4)

    # Final summary
    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    print("\nBaseline portfolios (from 18_PORTFOLIO_FINAL.md):")
    print(f"  P3 (CCI_ETH+STF_AVAX+STF_SOL)    Sharpe=2.13 CAGR=+38.5% MDD=-12.4% Calmar=3.11")
    print(f"  P5 (CCI_ETH+LATBB_AVAX+STF_SOL)  Sharpe=2.14 CAGR=+31.7% MDD=-18.1% Calmar=1.75")
    print(f"  P7 (BB_AVAX+CCI_ETH+STF_SOL)     Sharpe=2.03 CAGR=+42.9% MDD=-15.2% Calmar=2.83")
    print("\nLeveraged blends:")
    for k, v in combined.items():
        tag = "* " if v["sharpe"] > 2.14 else "  "
        print(f"  {tag}{k:12s} Sharpe={v['sharpe']} CAGR={v['cagr']} "
              f"MDD={v['mdd']} Calmar={v['calmar']} min_yr={v['min_yr']} "
              f"pos_yrs={v['pos_yrs']}/6")
    print(f"\nDone in {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
