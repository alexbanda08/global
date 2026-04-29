"""
V25 — Creative round on the untested 30m and 1h timeframes.

Five new signal families, all L+S, none tried in V23 or V24:

  1. MTF_CONF    — Multi-TF confluence: 1h/30m entry signal gated by a 4h
                   EMA-trend filter. Long only when 4h trend up; short only
                   when 4h trend down. Reduces fade-the-trend losses.
  2. SQUEEZE     — Bollinger-inside-Keltner squeeze release (TTM-style).
                   Long when squeeze releases with positive momentum; short
                   with negative momentum.
  3. SEASONAL    — RSI+BB mean-revert, but restricted to a specific 6-hour
                   window per day. Sweeps over a few candidate windows;
                   picks the best-performing one per coin.
  4. KELT_RSI    — Keltner channel break confirmed by RSI momentum. Long
                   when close breaks above upper Keltner AND RSI > 55.
                   Shorts mirror.
  5. SWEEP       — Liquidity-sweep reversal. Price makes a new N-bar high
                   (sweeps buy-stops), then closes back inside the prior
                   range → short. Mirror for long.

Execution: same simulator as v23/v24 (0.045% fee, 3 bps slippage, 3× cap).
Walk-forward OOS done in a follow-up script (run_v25_oos.py).
"""
from __future__ import annotations
import sys, pickle, warnings
warnings.filterwarnings("ignore")
from pathlib import Path
import numpy as np
import pandas as pd
import talib

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import simulate, metrics, atr, ema

FEAT = Path(__file__).resolve().parent / "features" / "multi_tf"
OUT = Path(__file__).resolve().parent / "results" / "v25"
OUT.mkdir(parents=True, exist_ok=True)
FEE = 0.00045
BPH = {"15m": 4, "30m": 2, "1h": 1, "2h": 0.5, "4h": 0.25}

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT",
         "DOGEUSDT", "INJUSDT", "SUIUSDT", "TONUSDT"]

SINCE = pd.Timestamp("2020-01-01", tz="UTC")


def _load(sym, tf):
    p = FEAT / f"{sym}_{tf}.parquet"
    if not p.exists(): return None
    df = pd.read_parquet(p).dropna(subset=["open","high","low","close","volume"])
    return df[df.index >= SINCE]


def scaled(n, tf): return max(1, int(round(n * BPH[tf])))
def dedupe(s): return s & ~s.shift(1).fillna(False)


# =====================================================================
# Family 1 — MTF Confluence
# =====================================================================

def sig_mtf_conf(df, fast_n=20, slow_n=50, h4_ema=50):
    """30m/1h EMA-cross entry gated by 4h EMA trend direction.
       Long: fast>slow crossover AND 4h close > 4h EMA(h4_ema).
       Short: fast<slow crossover AND 4h close < 4h EMA(h4_ema)."""
    ef = ema(df["close"], fast_n)
    es = ema(df["close"], slow_n)
    cross_up = (ef > es) & (ef.shift(1) <= es.shift(1))
    cross_dn = (ef < es) & (ef.shift(1) >= es.shift(1))
    # Right-labeled resample: at 1h bar t, use only fully-closed 4h bars.
    # Default label='left' leaks the [t, t+4h) bar's close into LTF bar t.
    h4 = df["close"].resample("4h", label="right", closed="left").last().dropna()
    h4_trend = (h4 > ema(h4, h4_ema)).reindex(df.index, method="ffill").fillna(False)
    long_sig = cross_up & h4_trend
    short_sig = cross_dn & (~h4_trend)
    return long_sig.fillna(False).astype(bool), short_sig.fillna(False).astype(bool)


# =====================================================================
# Family 2 — Squeeze (Bollinger inside Keltner)
# =====================================================================

def sig_squeeze(df, bb_n=20, bb_k=2.0, kc_n=20, kc_mult=1.5, mom_n=12):
    """Classic TTM Squeeze:
         squeeze = BB(n,k) inside Keltner(n, mult*ATR).
         Fire on release (squeeze_prev AND NOT squeeze_now), directional by
         momentum (Donchian-mid slope over mom_n)."""
    m = df["close"].rolling(bb_n).mean()
    s = df["close"].rolling(bb_n).std()
    bb_u = m + bb_k * s; bb_l = m - bb_k * s
    at = atr(df, kc_n)
    kc_u = m + kc_mult * at
    kc_l = m - kc_mult * at
    sqz = (bb_u < kc_u) & (bb_l > kc_l)  # BB contained inside KC
    released = sqz.shift(1).fillna(False) & (~sqz.fillna(False))
    # Momentum: linreg slope of close over mom_n is a lot;
    # simpler proxy: close - SMA(mom_n) is positive/negative.
    momentum = df["close"] - df["close"].rolling(mom_n).mean()
    long_sig = released & (momentum > 0)
    short_sig = released & (momentum < 0)
    return long_sig.fillna(False).astype(bool), short_sig.fillna(False).astype(bool)


# =====================================================================
# Family 3 — Seasonal (hour-of-day window) RSI+BB
# =====================================================================

def sig_seasonal(df, tf, hour_start=12, hour_span=6,
                 rsi_n=14, rsi_lo=30, rsi_hi=70,
                 bb_n=40, bb_k=2.0, regime_len=400):
    """RSI+BB mean-revert gated by a [hour_start, hour_start+hour_span) UTC
    window and a regime SMA."""
    rsi = talib.RSI(df["close"].values, rsi_n)
    m = df["close"].rolling(bb_n).mean()
    s = df["close"].rolling(bb_n).std()
    ub = m + bb_k * s; lb = m - bb_k * s
    reg_sma = df["close"].rolling(regime_len).mean()
    regime_up = df["close"] > reg_sma
    regime_dn = df["close"] < reg_sma

    hours = df.index.hour
    h_end = (hour_start + hour_span) % 24
    if hour_start < h_end:
        in_window = (hours >= hour_start) & (hours < h_end)
    else:
        in_window = (hours >= hour_start) | (hours < h_end)
    in_window = pd.Series(in_window, index=df.index)

    rsi_s = pd.Series(rsi, index=df.index)
    long_sig = (rsi_s < rsi_lo) & (df["close"] < lb) & regime_up & in_window
    short_sig = (rsi_s > rsi_hi) & (df["close"] > ub) & regime_dn & in_window
    return long_sig.fillna(False).astype(bool), short_sig.fillna(False).astype(bool)


# =====================================================================
# Family 4 — Keltner + RSI
# =====================================================================

def sig_kelt_rsi(df, kc_n=20, kc_mult=2.0, rsi_n=14, rsi_mid=55):
    """Long when close crosses above upper Keltner AND RSI>rsi_mid.
       Short when close crosses below lower Keltner AND RSI<100-rsi_mid."""
    em = ema(df["close"], kc_n)
    at = atr(df, kc_n)
    kc_u = em + kc_mult * at
    kc_l = em - kc_mult * at
    rsi = pd.Series(talib.RSI(df["close"].values, rsi_n), index=df.index)
    up_break = (df["close"] > kc_u) & (df["close"].shift(1) <= kc_u.shift(1))
    dn_break = (df["close"] < kc_l) & (df["close"].shift(1) >= kc_l.shift(1))
    long_sig = up_break & (rsi > rsi_mid)
    short_sig = dn_break & (rsi < (100 - rsi_mid))
    return long_sig.fillna(False).astype(bool), short_sig.fillna(False).astype(bool)


# =====================================================================
# Family 5 — Liquidity Sweep Reversal
# =====================================================================

def sig_sweep(df, lookback=20, wick_mult=0.4, regime_len=400):
    """Liquidity sweep: bar pokes above the max of the previous `lookback`
    highs (stop hunt), but CLOSES back inside that prior range. Shows
    willing sellers above the highs → fade short.

    Long mirror: bar pokes below the previous lookback low, but closes
    back inside → fade long.

    Gated by regime SMA so we don't fade major trends (fade long only in
    uptrend regime, fade short only in downtrend regime)."""
    prev_hi = df["high"].rolling(lookback).max().shift(1)
    prev_lo = df["low"].rolling(lookback).min().shift(1)

    # Sweep up: high > prev_hi, but close is back below prev_hi
    wick_up = (df["high"] - df["close"]) > wick_mult * (df["high"] - df["low"]).rolling(20).mean()
    swept_up = (df["high"] > prev_hi) & (df["close"] < prev_hi) & wick_up

    # Sweep down: low < prev_lo, but close is back above prev_lo
    wick_dn = (df["close"] - df["low"]) > wick_mult * (df["high"] - df["low"]).rolling(20).mean()
    swept_dn = (df["low"] < prev_lo) & (df["close"] > prev_lo) & wick_dn

    reg_sma = df["close"].rolling(regime_len).mean()
    regime_up = df["close"] > reg_sma
    regime_dn = df["close"] < reg_sma

    # Contrarian: swept_up (trapped buyers above) → short; swept_dn → long
    short_sig = swept_up & regime_dn
    long_sig = swept_dn & regime_up
    return long_sig.fillna(False).astype(bool), short_sig.fillna(False).astype(bool)


# =====================================================================
# Sweep runner
# =====================================================================

def run_one(df, lsig, ssig, tp, sl, tr, mh, risk, lev, lbl):
    ls = dedupe(lsig); ss = dedupe(ssig) if ssig is not None else None
    trades, eq = simulate(df, ls, short_entries=ss,
                          tp_atr=tp, sl_atr=sl, trail_atr=tr, max_hold=mh,
                          risk_per_trade=risk, leverage_cap=lev, fee=FEE)
    return metrics(lbl, eq, trades), trades, eq


# Trimmed exit grids tuned for 30m / 1h scalps
EXITS_30M = [
    (5, 1.5, 3.0, 48),   # 24h max hold
    (7, 2.0, 4.0, 80),   # 40h max hold
]
EXITS_1H = [
    (6, 1.5, 3.5, 36),   # 36h
    (10, 2.0, 5.0, 72),  # 72h
]
RISKS = [0.03, 0.05]


def sweep_family(sym, family):
    """Sweep one family across 30m + 1h. Return best-scoring config."""
    best = None
    for tf in ["30m", "1h"]:
        df = _load(sym, tf)
        if df is None or len(df) < 4000: continue
        exits = EXITS_30M if tf == "30m" else EXITS_1H

        if family == "MTF_CONF":
            grid = [(fast, slow, h4e) for fast in [scaled(12, tf), scaled(20, tf)]
                                       for slow in [scaled(30, tf), scaled(50, tf)]
                                       for h4e in [50]
                                       if fast < slow]
            for (fast, slow, h4e) in grid:
                try:
                    lsig, ssig = sig_mtf_conf(df, fast, slow, h4e)
                except Exception: continue
                if lsig.sum() < 10 and ssig.sum() < 10: continue
                for risk in RISKS:
                    for (tp, sl, tr, mh) in exits:
                        r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                 f"{sym}_{tf}_MTFCONF")
                        if r["n"] < 30 or r["dd"] < -0.45: continue
                        score = r["cagr_net"] * (r["sharpe"] / 1.5)
                        if best is None or score > best["score"]:
                            best = dict(sym=sym, family="MTF_Conf", tf=tf,
                                        params=dict(fast=fast, slow=slow, h4_ema=h4e),
                                        exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                        risk=risk, lev=3.0, metrics=r, trades=trades,
                                        eq=eq, score=score)

        elif family == "SQUEEZE":
            for bb_n in [scaled(20, tf), scaled(40, tf)]:
                for bb_k in [2.0]:
                    for kc_mult in [1.3, 1.8]:
                        for mom_n in [scaled(12, tf)]:
                            try:
                                lsig, ssig = sig_squeeze(df, bb_n, bb_k, bb_n, kc_mult, mom_n)
                            except Exception: continue
                            if lsig.sum() < 10 and ssig.sum() < 10: continue
                            for risk in RISKS:
                                for (tp, sl, tr, mh) in exits:
                                    r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                             f"{sym}_{tf}_SQZ")
                                    if r["n"] < 30 or r["dd"] < -0.45: continue
                                    score = r["cagr_net"] * (r["sharpe"] / 1.5)
                                    if best is None or score > best["score"]:
                                        best = dict(sym=sym, family="Squeeze", tf=tf,
                                                    params=dict(bb_n=bb_n, bb_k=bb_k,
                                                                kc_mult=kc_mult, mom_n=mom_n),
                                                    exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                                    risk=risk, lev=3.0, metrics=r, trades=trades,
                                                    eq=eq, score=score)

        elif family == "SEASONAL":
            # Sweep 4 candidate 6-hour windows (UTC)
            windows = [(0, 6), (6, 6), (12, 6), (18, 6)]
            for (h_start, h_span) in windows:
                for bb_n in [scaled(40, tf)]:
                    for rsi_lo, rsi_hi in [(30, 70), (25, 75)]:
                        try:
                            lsig, ssig = sig_seasonal(df, tf, h_start, h_span,
                                                       14, rsi_lo, rsi_hi,
                                                       bb_n, 2.0, scaled(400, tf))
                        except Exception: continue
                        if lsig.sum() < 10 and ssig.sum() < 10: continue
                        for risk in RISKS:
                            for (tp, sl, tr, mh) in exits:
                                r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                         f"{sym}_{tf}_SEAS")
                                if r["n"] < 30 or r["dd"] < -0.45: continue
                                score = r["cagr_net"] * (r["sharpe"] / 1.5)
                                if best is None or score > best["score"]:
                                    best = dict(sym=sym, family="Seasonal_RSI", tf=tf,
                                                params=dict(hour_start=h_start, hour_span=h_span,
                                                             rsi_lo=rsi_lo, rsi_hi=rsi_hi,
                                                             bb_n=bb_n),
                                                exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                                risk=risk, lev=3.0, metrics=r, trades=trades,
                                                eq=eq, score=score)

        elif family == "KELT_RSI":
            for kc_n in [scaled(20, tf), scaled(40, tf)]:
                for kc_mult in [1.5, 2.0]:
                    for rsi_mid in [52, 58]:
                        try:
                            lsig, ssig = sig_kelt_rsi(df, kc_n, kc_mult, 14, rsi_mid)
                        except Exception: continue
                        if lsig.sum() < 10 and ssig.sum() < 10: continue
                        for risk in RISKS:
                            for (tp, sl, tr, mh) in exits:
                                r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                         f"{sym}_{tf}_KRSI")
                                if r["n"] < 30 or r["dd"] < -0.45: continue
                                score = r["cagr_net"] * (r["sharpe"] / 1.5)
                                if best is None or score > best["score"]:
                                    best = dict(sym=sym, family="Keltner_RSI", tf=tf,
                                                params=dict(kc_n=kc_n, kc_mult=kc_mult,
                                                             rsi_mid=rsi_mid),
                                                exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                                risk=risk, lev=3.0, metrics=r, trades=trades,
                                                eq=eq, score=score)

        elif family == "SWEEP":
            for lb in [scaled(20, tf), scaled(40, tf)]:
                for wick in [0.35, 0.5]:
                    try:
                        lsig, ssig = sig_sweep(df, lb, wick, scaled(400, tf))
                    except Exception: continue
                    if lsig.sum() < 10 and ssig.sum() < 10: continue
                    for risk in RISKS:
                        for (tp, sl, tr, mh) in exits:
                            r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                     f"{sym}_{tf}_SWP")
                            if r["n"] < 30 or r["dd"] < -0.45: continue
                            score = r["cagr_net"] * (r["sharpe"] / 1.5)
                            if best is None or score > best["score"]:
                                best = dict(sym=sym, family="Sweep_Reversal", tf=tf,
                                            params=dict(lookback=lb, wick_mult=wick),
                                            exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                            risk=risk, lev=3.0, metrics=r, trades=trades,
                                            eq=eq, score=score)
    return best


def _persist(results, path):
    light = {}
    for k, w in results.items():
        light[k] = {
            "sym": w["sym"], "family": w["family"], "tf": w["tf"],
            "params": w["params"], "exits": w["exits"],
            "risk": w["risk"], "lev": w["lev"],
            "metrics": w["metrics"], "trades": w["trades"],
            "eq_index": list(w["eq"].index.astype("int64").tolist()),
            "eq_values": w["eq"].values.tolist(),
        }
    with open(path, "wb") as f:
        pickle.dump(light, f)


def main():
    results = {}
    ckpt = OUT / "v25_creative_results.pkl"
    families = ["MTF_CONF", "SQUEEZE", "SEASONAL", "KELT_RSI", "SWEEP"]

    for sym in COINS:
        for fam in families:
            key = f"{sym}_{fam}"
            print(f"\n=== {key} ===", flush=True)
            try:
                b = sweep_family(sym, fam)
            except Exception as e:
                print(f"  FAIL: {e}")
                continue
            if b is None:
                print(f"  NO VIABLE CONFIG")
                continue
            results[key] = b
            m = b["metrics"]
            print(f"  {b['tf']:3s}  {b['family']:14s}  CAGR {m['cagr_net']*100:6.1f}%  "
                  f"Sh {m['sharpe']:+.2f}  DD {m['dd']*100:+6.1f}%  n={m['n']:4d}  "
                  f"p={b['params']}", flush=True)
            _persist(results, ckpt)

    _persist(results, ckpt)

    flat = [{"sym": w["sym"], "family": w["family"], "tf": w["tf"],
             "params": str(w["params"]),
             **{k: v for k, v in w["metrics"].items() if k != "label"}}
            for _, w in results.items()]
    pd.DataFrame(flat).to_csv(OUT / "v25_creative_summary.csv", index=False)

    print("\n" + "=" * 80)
    print("V25 CREATIVE — per-coin per-family winners")
    print("=" * 80)
    if flat:
        print(pd.DataFrame(flat).to_string(index=False))
    else:
        print("(no viable configs)")


if __name__ == "__main__":
    sys.exit(main() or 0)
