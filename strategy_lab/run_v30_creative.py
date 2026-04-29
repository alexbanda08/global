"""V30 — Five brand-new families, none of which appear in V23-V29.

  1. TTM_SQUEEZE_POP   — Bollinger inside Keltner (squeeze on); on squeeze release,
                         enter in direction of momentum (close vs prior N-bar midline).

  2. VWAP_ZFADE        — Rolling-window VWAP z-score mean reversion.
                         Fade extremes when ADX < adx_max (range gate).
                         z = (close - rolling_vwap) / rolling_std.

  3. CONNORS_RSI       — Larry Connors' CRSI = (RSI(3) + RSI_streak(2) + PctRank(ROC,100))/3.
                         Long when CRSI < crsi_lo, short > crsi_hi. Vol-regime filter.

  4. SUPERTREND_FLIP   — Classic ATR-band SuperTrend direction change. Enter on
                         flip, confirmed by EMA(200) regime (long only above).

  5. CCI_EXTREME_REV   — CCI <= -cci_thr + bullish reversal candle → long.
                         Mirror for short. ADX range filter.

Same sim harness as V23-V29: 0.045% fee + 3 bps slippage in simulate(),
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
OUT = Path(__file__).resolve().parent / "results" / "v30"
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
# Shared helpers
# ================================================================

def bbands(x, n=20, k=2.0):
    m = x.rolling(n).mean()
    sd = x.rolling(n).std()
    return m, m + k*sd, m - k*sd


def kelt(df, n=20, mult=1.5):
    m = ema(df["close"], n)
    a = pd.Series(atr(df, n=n), index=df.index)
    return m, m + mult * a, m - mult * a


def adx_series(df, n=14):
    return pd.Series(talib.ADX(df["high"].values, df["low"].values, df["close"].values, timeperiod=n),
                     index=df.index)


# ================================================================
# Family 1 — TTM_SQUEEZE_POP
# ================================================================

def sig_ttm_squeeze(df, bb_n=20, bb_k=2.0, kc_n=20, kc_mult=1.5, mom_n=12):
    """Squeeze on: BB fully inside Keltner. Release edge = squeeze off after on.
    Direction: close vs midline of Donchian(mom_n). Long if above, short if below."""
    _, bb_up, bb_dn = bbands(df["close"], bb_n, bb_k)
    _, kc_up, kc_dn = kelt(df, kc_n, kc_mult)

    squeeze_on = (bb_up < kc_up) & (bb_dn > kc_dn)
    # release = squeeze was ON last bar, OFF this bar
    release = (~squeeze_on) & squeeze_on.shift(1).fillna(False)

    # Momentum direction: close vs midline(mom_n) Donchian
    dhi = df["high"].rolling(mom_n).max()
    dlo = df["low"].rolling(mom_n).min()
    mid = (dhi + dlo) / 2
    long_sig = release & (df["close"] > mid)
    short_sig = release & (df["close"] < mid)
    return long_sig.fillna(False).astype(bool), short_sig.fillna(False).astype(bool)


# ================================================================
# Family 2 — VWAP_ZFADE
# ================================================================

def sig_vwap_zfade(df, vwap_n=100, z_thr=2.0, adx_max=20, adx_n=14):
    """Rolling-window VWAP z-score fade in range regime."""
    pv = (df["close"] * df["volume"]).rolling(vwap_n).sum()
    vv = df["volume"].rolling(vwap_n).sum().replace(0, np.nan)
    vwap = pv / vv
    dev = df["close"] - vwap
    zsd = dev.rolling(vwap_n).std().replace(0, np.nan)
    z = dev / zsd

    adx = adx_series(df, adx_n)
    range_ok = adx < adx_max

    # Edge: z crosses from >= +z_thr to below (long fade? no — if above VWAP, short)
    # Fade logic: very negative z → long (price way below VWAP); very positive z → short
    long_edge = (z > -z_thr) & (z.shift(1) <= -z_thr)   # crosses back up through -z_thr
    short_edge = (z < z_thr) & (z.shift(1) >= z_thr)   # crosses back down through +z_thr

    long_sig = range_ok & long_edge
    short_sig = range_ok & short_edge
    return long_sig.fillna(False).astype(bool), short_sig.fillna(False).astype(bool)


# ================================================================
# Family 3 — CONNORS_RSI
# ================================================================

def _streak_len(close):
    """Signed streak length: +N if N consecutive up closes, -N for down."""
    direction = np.sign((close - close.shift(1)).fillna(0))
    streak = np.zeros(len(close), dtype=float)
    for i in range(1, len(close)):
        if direction.iat[i] == 0:
            streak[i] = 0
        elif direction.iat[i] == direction.iat[i-1] or streak[i-1] == 0:
            streak[i] = streak[i-1] + direction.iat[i] if np.sign(streak[i-1]) == direction.iat[i] else direction.iat[i]
        else:
            streak[i] = direction.iat[i]
    return pd.Series(streak, index=close.index)


def _pct_rank(series, n):
    return series.rolling(n).apply(lambda x: (x[-1] >= x).sum() / len(x) * 100, raw=False)


def sig_connors_rsi(df, crsi_lo=10, crsi_hi=90, adx_max=25, adx_n=14):
    """CRSI = (RSI(3) + RSI(streak, 2) + PctRank(ROC_1, 100)) / 3.
    Long when CRSI <= lo, short when >= hi. Low-ADX range filter."""
    close = df["close"]
    rsi3 = pd.Series(talib.RSI(close.values, 3), index=close.index)
    streak = _streak_len(close)
    rsi_streak = pd.Series(talib.RSI(streak.fillna(0).values, 2), index=close.index)
    roc1 = close.pct_change(1) * 100
    pct_rank = _pct_rank(roc1, 100)

    crsi = (rsi3 + rsi_streak + pct_rank) / 3

    adx = adx_series(df, adx_n)
    range_ok = adx < adx_max

    # Edge: CRSI crosses back UP through crsi_lo → long
    long_edge = (crsi > crsi_lo) & (crsi.shift(1) <= crsi_lo)
    short_edge = (crsi < crsi_hi) & (crsi.shift(1) >= crsi_hi)

    long_sig = range_ok & long_edge
    short_sig = range_ok & short_edge
    return long_sig.fillna(False).astype(bool), short_sig.fillna(False).astype(bool)


# ================================================================
# Family 4 — SUPERTREND_FLIP
# ================================================================

def _supertrend(df, n=10, mult=3.0):
    """Classic SuperTrend: bands = HL/2 +/- mult*ATR, lockstep trailing."""
    hl2 = (df["high"] + df["low"]) / 2
    a = pd.Series(atr(df, n=n), index=df.index)
    upper = hl2 + mult * a
    lower = hl2 - mult * a

    # Lock-step
    final_upper = upper.copy()
    final_lower = lower.copy()
    direction = pd.Series(1.0, index=df.index)  # +1 uptrend, -1 downtrend

    close = df["close"].values
    fu = final_upper.values.copy()
    fl = final_lower.values.copy()
    dire = direction.values.copy()
    up_arr = upper.values
    lo_arr = lower.values

    for i in range(1, len(df)):
        if np.isnan(up_arr[i]) or np.isnan(lo_arr[i]):
            continue
        # Upper
        if close[i-1] <= fu[i-1]:
            fu[i] = min(up_arr[i], fu[i-1]) if not np.isnan(fu[i-1]) else up_arr[i]
        else:
            fu[i] = up_arr[i]
        # Lower
        if close[i-1] >= fl[i-1]:
            fl[i] = max(lo_arr[i], fl[i-1]) if not np.isnan(fl[i-1]) else lo_arr[i]
        else:
            fl[i] = lo_arr[i]
        # Direction
        if dire[i-1] == 1 and close[i] < fl[i]:
            dire[i] = -1
        elif dire[i-1] == -1 and close[i] > fu[i]:
            dire[i] = 1
        else:
            dire[i] = dire[i-1]

    return pd.Series(dire, index=df.index)


def sig_supertrend_flip(df, st_n=10, st_mult=3.0, ema_reg=200):
    d = _supertrend(df, st_n, st_mult)
    reg = ema(df["close"], ema_reg)
    flip_up = (d > 0) & (d.shift(1) < 0)
    flip_dn = (d < 0) & (d.shift(1) > 0)
    long_sig = flip_up & (df["close"] > reg)
    short_sig = flip_dn & (df["close"] < reg)
    return long_sig.fillna(False).astype(bool), short_sig.fillna(False).astype(bool)


# ================================================================
# Family 5 — CCI_EXTREME_REV
# ================================================================

def sig_cci_extreme(df, cci_n=20, cci_lo=-150, cci_hi=150, adx_max=22, adx_n=14):
    cci = pd.Series(talib.CCI(df["high"].values, df["low"].values, df["close"].values, timeperiod=cci_n),
                    index=df.index)
    # Edge: crosses back UP through cci_lo (exiting deep oversold)
    long_edge = (cci > cci_lo) & (cci.shift(1) <= cci_lo) & (df["close"] > df["open"])
    short_edge = (cci < cci_hi) & (cci.shift(1) >= cci_hi) & (df["close"] < df["open"])

    adx = adx_series(df, adx_n)
    range_ok = adx < adx_max

    long_sig = range_ok & long_edge
    short_sig = range_ok & short_edge
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

# Track total configs tested
TOTAL_CONFIGS = 0


def sweep_family(sym, family):
    global TOTAL_CONFIGS
    best = None
    tfs = [("1h", EXITS_1H), ("4h", EXITS_4H)]

    for tf, exits in tfs:
        df = _load(sym, tf)
        if df is None or len(df) < 2000: continue

        if family == "TTM_SQUEEZE_POP":
            for bb_k in [1.8, 2.0, 2.2]:
                for kc_mult in [1.2, 1.5, 1.8]:
                    for mom_n in [10, 20]:
                        try:
                            lsig, ssig = sig_ttm_squeeze(df, 20, bb_k, 20, kc_mult, mom_n)
                        except Exception: continue
                        if lsig.sum() < 10 and ssig.sum() < 10: continue
                        for risk in RISKS:
                            for (tp, sl, tr, mh) in exits:
                                TOTAL_CONFIGS += 1
                                r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                        f"{sym}_{tf}_TTM")
                                if r["n"] < 25 or r["dd"] < -0.45: continue
                                score = r["cagr_net"] * (r["sharpe"] / 1.5)
                                if best is None or score > best["score"]:
                                    best = dict(sym=sym, family="TTM_Squeeze_Pop", tf=tf,
                                                params=dict(bb_k=bb_k, kc_mult=kc_mult, mom_n=mom_n),
                                                exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                                risk=risk, lev=3.0, metrics=r, trades=trades,
                                                eq=eq, score=score)

        elif family == "VWAP_ZFADE":
            for vn in [50, 100, 200]:
                for zthr in [1.5, 2.0, 2.5]:
                    for amx in [18, 22, 28]:
                        try:
                            lsig, ssig = sig_vwap_zfade(df, scaled(vn, tf), zthr, amx, 14)
                        except Exception: continue
                        if lsig.sum() < 10 and ssig.sum() < 10: continue
                        for risk in RISKS:
                            for (tp, sl, tr, mh) in exits:
                                TOTAL_CONFIGS += 1
                                r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                        f"{sym}_{tf}_VZ")
                                if r["n"] < 25 or r["dd"] < -0.45: continue
                                score = r["cagr_net"] * (r["sharpe"] / 1.5)
                                if best is None or score > best["score"]:
                                    best = dict(sym=sym, family="VWAP_Zfade", tf=tf,
                                                params=dict(vwap_n=vn, z_thr=zthr, adx_max=amx),
                                                exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                                risk=risk, lev=3.0, metrics=r, trades=trades,
                                                eq=eq, score=score)

        elif family == "CONNORS_RSI":
            for lo, hi in [(5, 95), (10, 90), (15, 85)]:
                for amx in [20, 28]:
                    try:
                        lsig, ssig = sig_connors_rsi(df, lo, hi, amx, 14)
                    except Exception: continue
                    if lsig.sum() < 10 and ssig.sum() < 10: continue
                    for risk in RISKS:
                        for (tp, sl, tr, mh) in exits:
                            TOTAL_CONFIGS += 1
                            r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                    f"{sym}_{tf}_CR")
                            if r["n"] < 25 or r["dd"] < -0.45: continue
                            score = r["cagr_net"] * (r["sharpe"] / 1.5)
                            if best is None or score > best["score"]:
                                best = dict(sym=sym, family="Connors_RSI", tf=tf,
                                            params=dict(crsi_lo=lo, crsi_hi=hi, adx_max=amx),
                                            exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                            risk=risk, lev=3.0, metrics=r, trades=trades,
                                            eq=eq, score=score)

        elif family == "SUPERTREND_FLIP":
            for st_n in [7, 10, 14]:
                for st_mult in [2.0, 3.0, 4.0]:
                    for ema_reg in [100, 200]:
                        try:
                            lsig, ssig = sig_supertrend_flip(df, st_n, st_mult, ema_reg)
                        except Exception: continue
                        if lsig.sum() < 10 and ssig.sum() < 10: continue
                        for risk in RISKS:
                            for (tp, sl, tr, mh) in exits:
                                TOTAL_CONFIGS += 1
                                r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                        f"{sym}_{tf}_ST")
                                if r["n"] < 25 or r["dd"] < -0.45: continue
                                score = r["cagr_net"] * (r["sharpe"] / 1.5)
                                if best is None or score > best["score"]:
                                    best = dict(sym=sym, family="SuperTrend_Flip", tf=tf,
                                                params=dict(st_n=st_n, st_mult=st_mult, ema_reg=ema_reg),
                                                exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                                risk=risk, lev=3.0, metrics=r, trades=trades,
                                                eq=eq, score=score)

        elif family == "CCI_EXTREME_REV":
            for cn in [14, 20, 30]:
                for thr in [100, 150, 200]:
                    for amx in [18, 22, 28]:
                        try:
                            lsig, ssig = sig_cci_extreme(df, cn, -thr, thr, amx, 14)
                        except Exception: continue
                        if lsig.sum() < 10 and ssig.sum() < 10: continue
                        for risk in RISKS:
                            for (tp, sl, tr, mh) in exits:
                                TOTAL_CONFIGS += 1
                                r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                        f"{sym}_{tf}_CCI")
                                if r["n"] < 25 or r["dd"] < -0.45: continue
                                score = r["cagr_net"] * (r["sharpe"] / 1.5)
                                if best is None or score > best["score"]:
                                    best = dict(sym=sym, family="CCI_Extreme_Rev", tf=tf,
                                                params=dict(cci_n=cn, cci_thr=thr, adx_max=amx),
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
    families = ["TTM_SQUEEZE_POP", "VWAP_ZFADE", "CONNORS_RSI",
                "SUPERTREND_FLIP", "CCI_EXTREME_REV"]
    results = {}
    ckpt = OUT / "v30_creative_results.pkl"

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
        df.to_csv(OUT / "v30_summary.csv", index=False)
        print("\n--- V30 SUMMARY (full-period, IS+OOS) ---")
        print(df.to_string(index=False))

    print(f"\ntotal configs tested: {TOTAL_CONFIGS}")
    print(f"elapsed: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
