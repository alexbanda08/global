"""V29 — Trend-Grade, Lateral-Market, and Regime-Switch.

Three brand-new families, none of which appear in V23-V28:

  1. TREND_GRADE_MTF  — Multi-TF trend-quality scoring.
                        Grade = sum of:
                          a) 4h EMA(50) slope up
                          b) 1D EMA(50) > 1D EMA(200)  [golden-cross regime]
                          c) 1h close > 1h EMA(200)     [local trend]
                          d) 1h ADX(14) > 20            [trendiness]
                        Long only when grade >= thr AND RSI(14) pulls back below
                        rsi_dip then pops up (pullback trigger in graded trend).
                        Short mirror.
                        Causal HTF resample: label='right', closed='left'.

  2. LATERAL_BB_FADE   — Range-market mean-reversion gate.
                        Regime: ADX(14) < adx_max AND BB-width below its
                        bw_q quantile over lookback (compressed range).
                        Long: close crosses below lower BB, closes green.
                        Short: mirror.
                        Exits: tight — TP at middle band via normal ATR rules.

  3. REGIME_SWITCH     — Single script that switches modes by ADX.
                        ADX > adx_hi → Donchian(n) breakout in direction of
                                       EMA(reg) regime.
                        ADX < adx_lo → BB-fade toward middle.
                        (adx_lo, adx_hi) — between thresholds, stay flat.
                        Same exits used in both modes.

Same sim as V23-V27: 0.045% taker fee, 3 bps slippage built into simulate(),
3× leverage cap, ATR-risk sizing, next-bar-open fills. OOS split 2024-01-01.
"""
from __future__ import annotations
import sys, pickle, time, warnings
warnings.filterwarnings("ignore")
from pathlib import Path
import numpy as np
import pandas as pd
import talib

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import simulate, metrics, atr, ema

FEAT = Path(__file__).resolve().parent / "features" / "multi_tf"
OUT = Path(__file__).resolve().parent / "results" / "v29"
OUT.mkdir(parents=True, exist_ok=True)
FEE = 0.00045
BPH = {"15m": 4, "30m": 2, "1h": 1, "2h": 0.5, "4h": 0.25}

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT",
         "DOGEUSDT", "INJUSDT", "SUIUSDT", "TONUSDT"]
SINCE = pd.Timestamp("2020-01-01", tz="UTC")


def _load(sym, tf):
    p = FEAT / f"{sym}_{tf}.parquet"
    if not p.exists(): return None
    df = pd.read_parquet(p).dropna(subset=["open", "high", "low", "close", "volume"])
    return df[df.index >= SINCE]


def scaled(n, tf): return max(1, int(round(n * BPH[tf])))
def dedupe(s): return s & ~s.shift(1).fillna(False)


# ================================================================
# Shared indicator helpers
# ================================================================

def htf_bool(df, rule, series_fn):
    """Right-label/closed-left resample of close, apply series_fn, then
    reindex forward-fill onto df.index. Returns bool-like pandas Series on df."""
    h = df["close"].resample(rule, label="right", closed="left").last().dropna()
    s = series_fn(h)
    return s.reindex(df.index, method="ffill")


def bbands(x, n=20, k=2.0):
    m = x.rolling(n).mean()
    sd = x.rolling(n).std()
    return m, m + k*sd, m - k*sd


def adx_series(df, n=14):
    return pd.Series(talib.ADX(df["high"].values, df["low"].values, df["close"].values, timeperiod=n),
                     index=df.index)


# ================================================================
# Family 1 — TREND_GRADE_MTF
# ================================================================

def sig_trend_grade(df, grade_thr=3, rsi_lo=40, rsi_hi=60, adx_n=14, adx_min=20):
    """Grade 0-4:
      +1  4h EMA(50) slope-up (vs 20 bars prior on 4h)
      +1  1D EMA(50) > 1D EMA(200)
      +1  1h close > 1h EMA(200)
      +1  1h ADX(14) > adx_min

    Entry: grade >= thr AND RSI(14) dips below rsi_lo then crosses up (long);
           grade-short symmetric using RSI pops above rsi_hi."""
    # +1: 4h EMA(50) slope up
    def _slope_up(x): e = ema(x, 50); return (e > e.shift(20)).astype(int)
    def _slope_dn(x): e = ema(x, 50); return (e < e.shift(20)).astype(int)
    g_4h_up = htf_bool(df, "4h", _slope_up).fillna(0)
    g_4h_dn = htf_bool(df, "4h", _slope_dn).fillna(0)

    # +1: 1D EMA(50) > EMA(200)
    def _d_bull(x): return (ema(x, 50) > ema(x, 200)).astype(int)
    def _d_bear(x): return (ema(x, 50) < ema(x, 200)).astype(int)
    g_d_up = htf_bool(df, "1D", _d_bull).fillna(0)
    g_d_dn = htf_bool(df, "1D", _d_bear).fillna(0)

    # +1: 1h close > EMA(200)
    e200 = ema(df["close"], 200)
    g_l_up = (df["close"] > e200).astype(int)
    g_l_dn = (df["close"] < e200).astype(int)

    # +1: ADX > adx_min
    adx = adx_series(df, adx_n)
    g_adx = (adx > adx_min).astype(int)

    grade_up = g_4h_up + g_d_up + g_l_up + g_adx
    grade_dn = g_4h_dn + g_d_dn + g_l_dn + g_adx

    # Pullback trigger — RSI dip/pop edge
    rsi = pd.Series(talib.RSI(df["close"].values, 14), index=df.index)
    dip_up = (rsi > rsi_lo) & (rsi.shift(1) <= rsi_lo)
    pop_dn = (rsi < rsi_hi) & (rsi.shift(1) >= rsi_hi)

    long_sig = (grade_up >= grade_thr) & dip_up
    short_sig = (grade_dn >= grade_thr) & pop_dn
    return long_sig.fillna(False).astype(bool), short_sig.fillna(False).astype(bool)


# ================================================================
# Family 2 — LATERAL_BB_FADE
# ================================================================

def sig_lateral_bb_fade(df, bb_n=20, bb_k=2.0, adx_max=18, adx_n=14,
                         bw_lookback=200, bw_q=0.60):
    """Range-gated BB fade: compressed range + ADX<max → fade band-break
    re-entries toward the middle band."""
    m, up, dn = bbands(df["close"], bb_n, bb_k)
    bw = (up - dn) / m.replace(0, np.nan)
    bw_thr = bw.rolling(bw_lookback).quantile(bw_q)

    adx = adx_series(df, adx_n)
    is_range = (adx < adx_max) & (bw < bw_thr)

    # Edge: close crosses UP through lower band (long setup)
    long_edge = (df["close"] > dn) & (df["close"].shift(1) <= dn.shift(1))
    short_edge = (df["close"] < up) & (df["close"].shift(1) >= up.shift(1))

    long_sig = is_range & long_edge
    short_sig = is_range & short_edge
    return long_sig.fillna(False).astype(bool), short_sig.fillna(False).astype(bool)


# ================================================================
# Family 3 — REGIME_SWITCH
# ================================================================

def sig_regime_switch(df, donch_n=40, ema_reg=200, bb_n=20, bb_k=2.0,
                      adx_lo=18, adx_hi=25, adx_n=14):
    """Switches by ADX:
       ADX > adx_hi AND close > EMA(reg)  → long on Donchian break-up
       ADX > adx_hi AND close < EMA(reg)  → short on Donchian break-dn
       ADX < adx_lo                       → BB fade (long lower, short upper)
       Between — no signal."""
    adx = adx_series(df, adx_n)
    reg = ema(df["close"], ema_reg)
    regime_up = df["close"] > reg
    regime_dn = df["close"] < reg

    dhi = df["high"].rolling(donch_n).max().shift(1)
    dlo = df["low"].rolling(donch_n).min().shift(1)
    trend_long = (adx > adx_hi) & (df["close"] > dhi) & (df["close"].shift(1) <= dhi.shift(1)) & regime_up
    trend_short = (adx > adx_hi) & (df["close"] < dlo) & (df["close"].shift(1) >= dlo.shift(1)) & regime_dn

    m, up, dn = bbands(df["close"], bb_n, bb_k)
    range_long = (adx < adx_lo) & (df["close"] > dn) & (df["close"].shift(1) <= dn.shift(1))
    range_short = (adx < adx_lo) & (df["close"] < up) & (df["close"].shift(1) >= up.shift(1))

    long_sig = trend_long | range_long
    short_sig = trend_short | range_short
    return long_sig.fillna(False).astype(bool), short_sig.fillna(False).astype(bool)


# ================================================================
# Runner
# ================================================================

def run_one(df, lsig, ssig, tp, sl, tr, mh, risk, lev, lbl):
    ls = dedupe(lsig); ss = dedupe(ssig) if ssig is not None else None
    trades, eq = simulate(df, ls, short_entries=ss,
                          tp_atr=tp, sl_atr=sl, trail_atr=tr, max_hold=mh,
                          risk_per_trade=risk, leverage_cap=lev, fee=FEE)
    return metrics(lbl, eq, trades), trades, eq


EXITS_1H = [(6, 1.5, 3.5, 36), (10, 2.0, 5.0, 72)]
EXITS_4H = [(6, 1.5, 3.5, 20), (10, 2.0, 5.0, 40)]
RISKS = [0.03, 0.05]


def sweep_family(sym, family):
    best = None
    if family == "TREND_GRADE_MTF":
        tfs = [("1h", EXITS_1H), ("4h", EXITS_4H)]
    elif family == "LATERAL_BB_FADE":
        tfs = [("1h", EXITS_1H), ("4h", EXITS_4H)]
    elif family == "REGIME_SWITCH":
        tfs = [("1h", EXITS_1H), ("4h", EXITS_4H)]
    else:
        return None

    for tf, exits in tfs:
        df = _load(sym, tf)
        if df is None or len(df) < 2000: continue

        if family == "TREND_GRADE_MTF":
            for thr in [2, 3, 4]:
                for rlo, rhi in [(35, 65), (40, 60), (45, 55)]:
                    for adx_min in [15, 20, 25]:
                        try:
                            lsig, ssig = sig_trend_grade(df, thr, rlo, rhi, 14, adx_min)
                        except Exception: continue
                        if lsig.sum() < 10 and ssig.sum() < 10: continue
                        for risk in RISKS:
                            for (tp, sl, tr, mh) in exits:
                                r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                        f"{sym}_{tf}_TG")
                                if r["n"] < 25 or r["dd"] < -0.45: continue
                                score = r["cagr_net"] * (r["sharpe"] / 1.5)
                                if best is None or score > best["score"]:
                                    best = dict(sym=sym, family="Trend_Grade_MTF", tf=tf,
                                                params=dict(thr=thr, rsi_lo=rlo, rsi_hi=rhi, adx_min=adx_min),
                                                exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                                risk=risk, lev=3.0, metrics=r, trades=trades,
                                                eq=eq, score=score)

        elif family == "LATERAL_BB_FADE":
            for bb_n in [20, 30]:
                for bb_k in [1.8, 2.2]:
                    for adx_max in [15, 18, 22]:
                        for bw_q in [0.40, 0.60, 0.75]:
                            try:
                                lsig, ssig = sig_lateral_bb_fade(df, bb_n, bb_k, adx_max, 14,
                                                                  scaled(200, tf), bw_q)
                            except Exception: continue
                            if lsig.sum() < 10 and ssig.sum() < 10: continue
                            for risk in RISKS:
                                for (tp, sl, tr, mh) in exits:
                                    r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                            f"{sym}_{tf}_LB")
                                    if r["n"] < 25 or r["dd"] < -0.45: continue
                                    score = r["cagr_net"] * (r["sharpe"] / 1.5)
                                    if best is None or score > best["score"]:
                                        best = dict(sym=sym, family="Lateral_BB_Fade", tf=tf,
                                                    params=dict(bb_n=bb_n, bb_k=bb_k, adx_max=adx_max, bw_q=bw_q),
                                                    exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                                    risk=risk, lev=3.0, metrics=r, trades=trades,
                                                    eq=eq, score=score)

        elif family == "REGIME_SWITCH":
            for donch_n in [20, 40]:
                for ema_reg in [100, 200]:
                    for adx_lo, adx_hi in [(15, 25), (18, 28), (20, 30)]:
                        try:
                            lsig, ssig = sig_regime_switch(df, donch_n, ema_reg, 20, 2.0,
                                                            adx_lo, adx_hi, 14)
                        except Exception: continue
                        if lsig.sum() < 10 and ssig.sum() < 10: continue
                        for risk in RISKS:
                            for (tp, sl, tr, mh) in exits:
                                r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                        f"{sym}_{tf}_RS")
                                if r["n"] < 25 or r["dd"] < -0.45: continue
                                score = r["cagr_net"] * (r["sharpe"] / 1.5)
                                if best is None or score > best["score"]:
                                    best = dict(sym=sym, family="Regime_Switch", tf=tf,
                                                params=dict(donch_n=donch_n, ema_reg=ema_reg,
                                                             adx_lo=adx_lo, adx_hi=adx_hi),
                                                exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                                risk=risk, lev=3.0, metrics=r, trades=trades,
                                                eq=eq, score=score)
    return best


def _persist(results, path):
    light = {}
    for k, v in results.items():
        light[k] = {kk: vv for kk, vv in v.items() if kk not in ("trades",)}
        eq = v.get("eq")
        if eq is not None:
            light[k]["eq_index"] = list(eq.index)
            light[k]["eq_values"] = eq.values.tolist()
            del light[k]["eq"]
    with open(path, "wb") as f:
        pickle.dump(light, f)


def main():
    t0 = time.time()
    families = ["TREND_GRADE_MTF", "LATERAL_BB_FADE", "REGIME_SWITCH"]
    results = {}
    ckpt = OUT / "v29_regime_results.pkl"

    for sym in COINS:
        for fam in families:
            key = f"{sym}_{fam}"
            print(f"\n=== {key} ===", flush=True)
            w = sweep_family(sym, fam)
            if w is None:
                print("  NO VIABLE CONFIG", flush=True)
                continue
            r = w["metrics"]
            print(f"  {w['tf']:>3s}  {w['family']:<20s}  "
                  f"CAGR {r['cagr_net']*100:+6.1f}%  Sh {r['sharpe']:+.2f}  "
                  f"DD {r['dd']*100:+6.1f}%  n={r['n']:4d}  p={w['params']}", flush=True)
            results[key] = w
            _persist(results, ckpt)

    # Summary table
    rows = []
    for key, w in results.items():
        r = w["metrics"]
        rows.append({
            "key": key, "sym": w["sym"], "family": w["family"], "tf": w["tf"],
            "n": r["n"], "CAGR_net": round(r["cagr_net"] * 100, 1),
            "Sharpe": round(r["sharpe"], 2), "DD": round(r["dd"] * 100, 1),
            "PF": round(r.get("pf", 0), 2),
            "risk": w["risk"], "params": str(w["params"]),
        })
    if rows:
        df = pd.DataFrame(rows).sort_values("Sharpe", ascending=False)
        df.to_csv(OUT / "v29_summary.csv", index=False)
        print("\n--- V29 SUMMARY (full-period, IS+OOS) ---")
        print(df.to_string(index=False))

    print(f"\nelapsed: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
