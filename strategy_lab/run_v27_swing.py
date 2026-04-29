"""
V27 — Swing/higher-TF/pullback round.

Four families that V23-V26 never tested:
  1. TREND_PULLBACK  — Retrace entry in confirmed trend.
                       Long: 4h EMA(50) slope up AND 1h close > 1h EMA(200)
                             AND 1h RSI(14) dips < 40 = buy the dip.
                       Short mirror with downtrend + RSI > 60.
  2. HTF_DONCHIAN    — Classic Turtle-style breakout on 4h bars.
                       Long:  close > Donch_hi(N) AND close > EMA(regime)
                       Short: close < Donch_lo(N) AND close < EMA(regime)
  3. VWAP_FADE       — Session-anchored VWAP (resets at 00 UTC daily). Fade
                       extensions beyond ±k * rolling stdev of (close - VWAP).
                       Long when close < VWAP - k*stdev in UP regime;
                       short mirror.
  4. DAILY_EMA_X     — Bog-standard EMA fast/slow cross on daily (resampled).
                       Long: EMA(12) crosses up EMA(26) on D, regime up.
                       Lowest frequency of any family we've tried — fee-safe.

Same sim as V23-V26 (0.045% fee, 3 bps slippage, 3× cap, next-bar-open fills).
OOS split at 2024-01-01.
"""
from __future__ import annotations
import sys, pickle, warnings, time
warnings.filterwarnings("ignore")
from pathlib import Path
import numpy as np
import pandas as pd
import talib

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import simulate, metrics, atr, ema

FEAT = Path(__file__).resolve().parent / "features" / "multi_tf"
OUT = Path(__file__).resolve().parent / "results" / "v27"
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


# ===================================================================
# Family 1 — Trend pullback (MTF: HTF trend + LTF RSI dip)
# ===================================================================

def sig_trend_pullback(df, htf="4h", htf_ema=50, ltf_ema=200, rsi_n=14,
                       rsi_lo=40, rsi_hi=60):
    """Long: HTF EMA slope up AND LTF close > LTF EMA(200) AND RSI dips <rsi_lo.
    Short: HTF EMA slope down AND LTF close < LTF EMA(200) AND RSI > rsi_hi.

    Causality: resample with label='right' + closed='left' so the HTF bar
    labelled t is the close of the [t-htf, t) bucket — i.e. fully known by
    LTF bar t. Without this, default left-labels leak HTF future into LTF."""
    # HTF trend  (right-labeled: value at t = close of (t-htf, t] bucket)
    h = df["close"].resample(htf, label="right", closed="left").last().dropna()
    h_ema = ema(h, htf_ema)
    h_slope_up = (h_ema > h_ema.shift(1)).reindex(df.index, method="ffill").fillna(False)
    h_slope_dn = (h_ema < h_ema.shift(1)).reindex(df.index, method="ffill").fillna(False)

    # LTF trend + pullback
    ltf_e = ema(df["close"], ltf_ema)
    rsi = pd.Series(talib.RSI(df["close"].values, rsi_n), index=df.index)

    # Dip edge: RSI crosses down through rsi_lo
    dip_down = (rsi < rsi_lo) & (rsi.shift(1) >= rsi_lo)
    pop_up = (rsi > rsi_hi) & (rsi.shift(1) <= rsi_hi)

    long_sig = h_slope_up & (df["close"] > ltf_e) & dip_down
    short_sig = h_slope_dn & (df["close"] < ltf_e) & pop_up
    return long_sig.fillna(False).astype(bool), short_sig.fillna(False).astype(bool)


# ===================================================================
# Family 2 — Higher-TF Donchian breakout (native 4h or 2h)
# ===================================================================

def sig_htf_donchian(df, donch_n=20, ema_reg=200):
    """Classic turtle — breakout of Donchian channel with regime filter.
    Entries fire at first close above/below the prior-bar channel."""
    hi = df["high"].rolling(donch_n).max().shift(1)
    lo = df["low"].rolling(donch_n).min().shift(1)
    reg = ema(df["close"], ema_reg)
    regime_up = df["close"] > reg
    regime_dn = df["close"] < reg

    long_sig = (df["close"] > hi) & (df["close"].shift(1) <= hi.shift(1)) & regime_up
    short_sig = (df["close"] < lo) & (df["close"].shift(1) >= lo.shift(1)) & regime_dn
    return long_sig.fillna(False).astype(bool), short_sig.fillna(False).astype(bool)


# ===================================================================
# Family 3 — Session-anchored VWAP deviation fade
# ===================================================================

def sig_vwap_fade(df, std_n=40, dev_k=2.0, regime_len=400):
    """Anchored VWAP reset daily at 00:00 UTC. Fade extensions >k*std
    from VWAP, in direction of regime SMA(400)."""
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    v = df["volume"]
    # daily groups
    day = df.index.floor("1D")
    pv = (tp * v).groupby(day).cumsum()
    cv = v.groupby(day).cumsum()
    vwap = (pv / cv).reindex(df.index)

    dev = df["close"] - vwap
    dev_std = dev.rolling(std_n).std()
    reg_sma = df["close"].rolling(regime_len).mean()
    regime_up = df["close"] > reg_sma
    regime_dn = df["close"] < reg_sma

    # Long fade: close well below VWAP but bullish regime
    long_sig = (dev < -dev_k * dev_std) & regime_up
    short_sig = (dev > dev_k * dev_std) & regime_dn
    return long_sig.fillna(False).astype(bool), short_sig.fillna(False).astype(bool)


# ===================================================================
# Family 4 — Daily EMA cross (resampled to D)
# ===================================================================

def sig_daily_ema_cross(df, fast=12, slow=26, ema_reg=50):
    """EMA fast/slow cross on daily closes, propagated back to LTF. Long
    on bull cross in uptrend (D close > D EMA50); short on bear cross
    in downtrend."""
    # Right-labeled resample so daily close at label t represents the close
    # of day (t-1, t] — fully known at LTF bar t.
    d = df["close"].resample("1D", label="right", closed="left").last().dropna()
    ef = ema(d, fast); es = ema(d, slow); er = ema(d, ema_reg)
    xu = (ef > es) & (ef.shift(1) <= es.shift(1))
    xd = (ef < es) & (ef.shift(1) >= es.shift(1))
    reg_up = d > er
    reg_dn = d < er

    long_d = (xu & reg_up).reindex(d.index).fillna(False)
    short_d = (xd & reg_dn).reindex(d.index).fillna(False)

    # Propagate to LTF: signal fires on the first LTF bar of the day AFTER cross
    long_ltf = long_d.reindex(df.index, method="ffill").fillna(False)
    short_ltf = short_d.reindex(df.index, method="ffill").fillna(False)
    # Edge only (don't fire every bar of the day)
    long_edge = long_ltf & ~long_ltf.shift(1).fillna(False)
    short_edge = short_ltf & ~short_ltf.shift(1).fillna(False)
    return long_edge.astype(bool), short_edge.astype(bool)


# ===================================================================
# Runner
# ===================================================================

def run_one(df, lsig, ssig, tp, sl, tr, mh, risk, lev, lbl):
    ls = dedupe(lsig); ss = dedupe(ssig) if ssig is not None else None
    trades, eq = simulate(df, ls, short_entries=ss,
                          tp_atr=tp, sl_atr=sl, trail_atr=tr, max_hold=mh,
                          risk_per_trade=risk, leverage_cap=lev, fee=FEE)
    return metrics(lbl, eq, trades), trades, eq


EXITS_1H = [(6, 1.5, 3.5, 36), (10, 2.0, 5.0, 72)]
EXITS_4H = [(6, 1.5, 3.5, 20), (10, 2.0, 5.0, 40)]
EXITS_2H = [(6, 1.5, 3.5, 28), (10, 2.0, 5.0, 56)]
RISKS = [0.03, 0.05]


def sweep_family(sym, family):
    best = None
    # Choose TF per family
    if family == "TREND_PULLBACK":
        tfs = [("1h", EXITS_1H)]
    elif family == "HTF_DONCHIAN":
        tfs = [("4h", EXITS_4H), ("2h", EXITS_2H)]
    elif family == "VWAP_FADE":
        tfs = [("1h", EXITS_1H)]
    elif family == "DAILY_EMA_X":
        tfs = [("1h", EXITS_1H), ("4h", EXITS_4H)]
    else:
        return None

    for tf, exits in tfs:
        df = _load(sym, tf)
        if df is None or len(df) < 2000: continue

        if family == "TREND_PULLBACK":
            for htf_ema in [20, 50]:
                for ltf_ema in [100, 200]:
                    for rlo, rhi in [(35, 65), (40, 60)]:
                        try:
                            lsig, ssig = sig_trend_pullback(df, "4h", htf_ema, ltf_ema, 14, rlo, rhi)
                        except Exception: continue
                        if lsig.sum() < 10 and ssig.sum() < 10: continue
                        for risk in RISKS:
                            for (tp, sl, tr, mh) in exits:
                                r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                         f"{sym}_{tf}_PB")
                                if r["n"] < 30 or r["dd"] < -0.45: continue
                                score = r["cagr_net"] * (r["sharpe"] / 1.5)
                                if best is None or score > best["score"]:
                                    best = dict(sym=sym, family="Trend_Pullback", tf=tf,
                                                 params=dict(htf_ema=htf_ema, ltf_ema=ltf_ema,
                                                              rsi_lo=rlo, rsi_hi=rhi),
                                                 exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                                 risk=risk, lev=3.0, metrics=r, trades=trades,
                                                 eq=eq, score=score)

        elif family == "HTF_DONCHIAN":
            for dn in [20, 40, 60]:
                for er in [100, 200]:
                    try:
                        lsig, ssig = sig_htf_donchian(df, dn, er)
                    except Exception: continue
                    if lsig.sum() < 10 and ssig.sum() < 10: continue
                    for risk in RISKS:
                        for (tp, sl, tr, mh) in exits:
                            r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                     f"{sym}_{tf}_DC")
                            if r["n"] < 25 or r["dd"] < -0.45: continue
                            score = r["cagr_net"] * (r["sharpe"] / 1.5)
                            if best is None or score > best["score"]:
                                best = dict(sym=sym, family="HTF_Donchian", tf=tf,
                                             params=dict(donch_n=dn, ema_reg=er),
                                             exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                             risk=risk, lev=3.0, metrics=r, trades=trades,
                                             eq=eq, score=score)

        elif family == "VWAP_FADE":
            for sn in [30, 60]:
                for dk in [1.5, 2.0, 2.5]:
                    try:
                        lsig, ssig = sig_vwap_fade(df, sn, dk, scaled(400, tf))
                    except Exception: continue
                    if lsig.sum() < 10 and ssig.sum() < 10: continue
                    for risk in RISKS:
                        for (tp, sl, tr, mh) in exits:
                            r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                     f"{sym}_{tf}_VW")
                            if r["n"] < 30 or r["dd"] < -0.45: continue
                            score = r["cagr_net"] * (r["sharpe"] / 1.5)
                            if best is None or score > best["score"]:
                                best = dict(sym=sym, family="VWAP_Fade", tf=tf,
                                             params=dict(std_n=sn, dev_k=dk),
                                             exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                             risk=risk, lev=3.0, metrics=r, trades=trades,
                                             eq=eq, score=score)

        elif family == "DAILY_EMA_X":
            for fast, slow in [(12, 26), (20, 50)]:
                for er in [50, 100]:
                    try:
                        lsig, ssig = sig_daily_ema_cross(df, fast, slow, er)
                    except Exception: continue
                    if lsig.sum() < 5 and ssig.sum() < 5: continue
                    for risk in RISKS:
                        for (tp, sl, tr, mh) in exits:
                            r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                     f"{sym}_{tf}_DX")
                            if r["n"] < 15 or r["dd"] < -0.45: continue
                            score = r["cagr_net"] * (r["sharpe"] / 1.5)
                            if best is None or score > best["score"]:
                                best = dict(sym=sym, family="Daily_EMA_X", tf=tf,
                                             params=dict(fast=fast, slow=slow, ema_reg=er),
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
    families = ["TREND_PULLBACK", "HTF_DONCHIAN", "VWAP_FADE", "DAILY_EMA_X"]
    results = {}
    ckpt = OUT / "v27_swing_results.pkl"

    for sym in COINS:
        for fam in families:
            key = f"{sym}_{fam}"
            print(f"\n=== {key} ===", flush=True)
            w = sweep_family(sym, fam)
            if w is None:
                print("  NO VIABLE CONFIG", flush=True)
                continue
            r = w["metrics"]
            print(f"  {w['tf']:>3s}  {w['family']:<16s}  "
                  f"CAGR {r['cagr_net']*100:+6.1f}%  Sh {r['sharpe']:+.2f}  "
                  f"DD {r['dd']*100:+6.1f}%  n={r['n']:4d}  p={w['params']}", flush=True)
            results[key] = w
            _persist(results, ckpt)

    # Summary
    rows = []
    for key, w in results.items():
        r = w["metrics"]
        rows.append({
            "sym": w["sym"], "family": w["family"], "tf": w["tf"],
            "params": str(w["params"]), "n": int(r["n"]),
            "final": r.get("final", r.get("equity", 0)),
            "cagr": round(r["cagr"], 4), "cagr_net": round(r["cagr_net"], 4),
            "sharpe": round(r["sharpe"], 3), "dd": round(r["dd"], 4),
            "win": round(r["win"], 3), "pf": round(r["pf"], 3),
            "exposure": round(r["exposure"], 3), "avg_lev": round(r["avg_lev"], 2),
            "funding_drag": round(r["funding_drag"], 4),
        })
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "v27_swing_summary.csv", index=False)

    print("\n" + "=" * 80)
    print("V27 SWING — per-coin per-family winners")
    print("=" * 80)
    if len(df):
        print(df.to_string(index=False))
    print(f"\nDone in {time.time()-t0:.0f}s. Winners: {len(results)}")


if __name__ == "__main__":
    main()
