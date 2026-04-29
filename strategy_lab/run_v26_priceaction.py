"""
V26 — Price-action creative round (6 families).

The V25 "Sweep_Reversal" was implemented naively (rolling max + wick fraction).
This round does it properly — at swing pivots, with volume + regime confirmation —
and adds 5 more price-action signal families that V23/V24/V25 never tested.

Families:
  1. LIQ_SWEEP   — Sweep at swing pivot highs/lows + volume + regime fade.
                   Long: low < pivot_low AND close > pivot_low AND close > SMA_regime
                   Short mirror.
  2. ORDER_BLOCK — Bullish OB = last red candle before a strong up-impulse
                   (+k*ATR in next N bars). Long when price retests that candle
                   zone and closes above the OB high. Short mirror.
  3. MSB         — Market Structure Break. After a downtrend (sequence of lower
                   highs + lower lows), first break above prior swing high with
                   volume = long reversal. Short mirror.
  4. ENGULF      — Bullish engulfing candle below BB lower with volume>1.3×avg
                   = long. Bearish engulf + above BB upper = short.
  5. RSI_DIV     — Regular bullish/bearish RSI(14) divergence at swing pivots.
                   Bullish: price lower low, RSI higher low → long.
  6. ATR_SQZ     — ATR compression (ATR/ATR_ma < 0.7) followed by Donchian(N)
                   breakout = directional expansion trade.

Execution: same sim as v23/v24/v25 (0.045% fee, 3 bps slippage, 3× cap).
Target TFs: 30m and 1h across all 9 coins.
Walk-forward OOS in run_v26_oos.py.
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
OUT = Path(__file__).resolve().parent / "results" / "v26"
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
# Helpers for pivot detection (swing highs / lows)
# ===================================================================

def swing_pivots(high, low, L=5, R=5):
    """Returns (swing_high_mask, swing_low_mask) — a swing high at index t
    is the highest high over [t-L, t+R]. The t+R look-ahead means the signal
    is only CONFIRMED R bars later; we shift(R) to reflect that."""
    hi = high.rolling(L + R + 1, center=True).max()
    lo = low.rolling(L + R + 1, center=True).min()
    sh = (high == hi)
    sl = (low == lo)
    # Shift by R so we only use pivot info that was already available at bar t
    return sh.shift(R).fillna(False), sl.shift(R).fillna(False)


# ===================================================================
# Family 1 — LIQ_SWEEP (proper, swing-pivot based)
# ===================================================================

def sig_liq_sweep(df, pivot_L=5, pivot_R=5, vol_mult=1.3, regime_len=400):
    """Proper liquidity sweep: bar pokes through the MOST RECENT confirmed
    swing high/low (not a rolling max), with a wick back inside, with volume
    confirmation, gated by trend regime."""
    sh, sl = swing_pivots(df["high"], df["low"], pivot_L, pivot_R)
    # For each bar, what's the most recent swing high level?
    pivot_hi = df["high"].where(sh).ffill()
    pivot_lo = df["low"].where(sl).ffill()

    vol_avg = df["volume"].rolling(20).mean()
    vol_ok = df["volume"] > vol_mult * vol_avg

    reg_sma = df["close"].rolling(regime_len).mean()
    regime_up = df["close"] > reg_sma
    regime_dn = df["close"] < reg_sma

    # Short: sweep of pivot high (high > piv_hi AND close < piv_hi) in downtrend
    swept_up = (df["high"] > pivot_hi) & (df["close"] < pivot_hi) & vol_ok
    # Long: sweep of pivot low in uptrend
    swept_dn = (df["low"] < pivot_lo) & (df["close"] > pivot_lo) & vol_ok

    long_sig = swept_dn & regime_up
    short_sig = swept_up & regime_dn
    return long_sig.fillna(False).astype(bool), short_sig.fillna(False).astype(bool)


# ===================================================================
# Family 2 — ORDER_BLOCK revisit
# ===================================================================

def sig_order_block(df, lookahead=6, atr_impulse=2.0, retrace_bars=60, regime_len=400):
    """Bullish order block: a red candle (close<open) IMMEDIATELY followed
    within `lookahead` bars by an up-impulse of +atr_impulse*ATR from the
    OB candle's low. When price returns to the OB zone (low..open) within
    `retrace_bars` bars and closes back above the OB high, fire long.

    Bearish OB: green candle followed by down-impulse; revisit + close below
    OB low = short.

    Regime gate: only fade in the prevailing trend direction."""
    red = (df["close"] < df["open"])
    green = (df["close"] > df["open"])
    atv = np.nan_to_num(atr(df), nan=0.0)

    close = df["close"].values
    low = df["low"].values
    high = df["high"].values
    openv = df["open"].values

    N = len(df)
    # For each bar, did the next `lookahead` bars push atr_impulse * ATR above/below?
    # Cheap check: max(high[t+1..t+lookahead]) - low[t] > atr_impulse*ATR[t]
    up_imp = np.zeros(N, dtype=bool)
    dn_imp = np.zeros(N, dtype=bool)
    for k in range(1, lookahead + 1):
        up_imp[:-k] |= (np.roll(high, -k)[:-k] - low[:-k]) > atr_impulse * atv[:-k]
        dn_imp[:-k] |= (high[:-k] - np.roll(low, -k)[:-k]) > atr_impulse * atv[:-k]

    # OBs  (FIX: OB at bar t relies on future bars t+1..t+lookahead, so the OB
    # is only "confirmed/observable" at bar t+lookahead. We therefore register
    # the OB in the running-zone arrays with a `lookahead`-bar delay — i.e.
    # when we're at bar i, we can see OB that occurred at bar i - lookahead.)
    bull_ob = red.values & up_imp
    bear_ob = green.values & dn_imp

    last_bull_idx = np.full(N, -10**9)
    last_bull_lo = np.full(N, np.nan)
    last_bull_hi = np.full(N, np.nan)
    last_bear_idx = np.full(N, -10**9)
    last_bear_lo = np.full(N, np.nan)
    last_bear_hi = np.full(N, np.nan)
    for i in range(N):
        if i > 0:
            last_bull_idx[i] = last_bull_idx[i-1]
            last_bull_lo[i] = last_bull_lo[i-1]
            last_bull_hi[i] = last_bull_hi[i-1]
            last_bear_idx[i] = last_bear_idx[i-1]
            last_bear_lo[i] = last_bear_lo[i-1]
            last_bear_hi[i] = last_bear_hi[i-1]
        t = i - lookahead  # OB at bar t is observable here
        if t >= 0 and bull_ob[t]:
            last_bull_idx[i] = t
            last_bull_lo[i] = low[t]
            last_bull_hi[i] = openv[t]
        if t >= 0 and bear_ob[t]:
            last_bear_idx[i] = t
            last_bear_lo[i] = openv[t]
            last_bear_hi[i] = high[t]

    idx = np.arange(N)
    bull_active = (idx - last_bull_idx) <= retrace_bars
    bear_active = (idx - last_bear_idx) <= retrace_bars

    # Retest condition: low[i] <= OB top AND close[i] > OB top
    retest_bull = bull_active & (low <= last_bull_hi) & (close > last_bull_hi)
    retest_bear = bear_active & (high >= last_bear_lo) & (close < last_bear_lo)

    # Regime gate
    reg_sma = df["close"].rolling(regime_len).mean()
    regime_up = (df["close"] > reg_sma).values
    regime_dn = (df["close"] < reg_sma).values

    long_sig = pd.Series(retest_bull & regime_up, index=df.index).fillna(False)
    short_sig = pd.Series(retest_bear & regime_dn, index=df.index).fillna(False)
    return long_sig.astype(bool), short_sig.astype(bool)


# ===================================================================
# Family 3 — Market Structure Break
# ===================================================================

def sig_msb(df, pivot_L=5, pivot_R=5, vol_mult=1.2):
    """After a downtrend (price < prior swing high for ≥ K bars), first break
    above the most recent pivot high with volume surge = long reversal.
    Short mirror."""
    sh, sl = swing_pivots(df["high"], df["low"], pivot_L, pivot_R)
    pivot_hi = df["high"].where(sh).ffill()
    pivot_lo = df["low"].where(sl).ffill()

    vol_avg = df["volume"].rolling(20).mean()
    vol_ok = df["volume"] > vol_mult * vol_avg

    # Break out above pivot high with volume
    break_up = (df["close"] > pivot_hi) & (df["close"].shift(1) <= pivot_hi.shift(1)) & vol_ok
    break_dn = (df["close"] < pivot_lo) & (df["close"].shift(1) >= pivot_lo.shift(1)) & vol_ok

    # Context: long only if we were recently below the previous pivot high
    # (= we're reversing from a downtrend). Proxy: close < SMA(50) in last 20 bars.
    sma50 = df["close"].rolling(50).mean()
    was_down = (df["close"] < sma50).rolling(20).sum() > 10
    was_up = (df["close"] > sma50).rolling(20).sum() > 10

    long_sig = break_up & was_down
    short_sig = break_dn & was_up
    return long_sig.fillna(False).astype(bool), short_sig.fillna(False).astype(bool)


# ===================================================================
# Family 4 — Engulfing + Volume
# ===================================================================

def sig_engulf(df, bb_n=40, bb_k=2.0, vol_mult=1.3):
    """Bullish engulf: body of current green candle fully engulfs prior red
    body AND bar's low below BB_lower AND volume surge = long.
    Bearish engulf + above BB_upper mirror = short."""
    m = df["close"].rolling(bb_n).mean()
    s = df["close"].rolling(bb_n).std()
    ub = m + bb_k * s; lb = m - bb_k * s

    prev_open = df["open"].shift(1)
    prev_close = df["close"].shift(1)
    prev_red = prev_close < prev_open
    prev_green = prev_close > prev_open

    cur_green = df["close"] > df["open"]
    cur_red = df["close"] < df["open"]

    bull_engulf = cur_green & prev_red & (df["open"] <= prev_close) & (df["close"] >= prev_open)
    bear_engulf = cur_red & prev_green & (df["open"] >= prev_close) & (df["close"] <= prev_open)

    vol_ok = df["volume"] > vol_mult * df["volume"].rolling(20).mean()

    long_sig = bull_engulf & (df["low"] < lb) & vol_ok
    short_sig = bear_engulf & (df["high"] > ub) & vol_ok
    return long_sig.fillna(False).astype(bool), short_sig.fillna(False).astype(bool)


# ===================================================================
# Family 5 — RSI Divergence
# ===================================================================

def sig_rsi_div(df, rsi_n=14, pivot_L=5, pivot_R=5, regime_len=400):
    """Bullish regular divergence: price lower low, RSI higher low at swing
    lows. Bearish: price higher high, RSI lower high at swing highs.

    Implementation: track last two confirmed swing lows (highs). If new pivot
    low is below previous but RSI at new pivot is above RSI at previous =
    bullish div = long signal on the bar R bars after the pivot (when confirmed).
    """
    rsi = pd.Series(talib.RSI(df["close"].values, rsi_n), index=df.index)

    # Shifted pivot masks — signal only when confirmed
    sh, sl = swing_pivots(df["high"], df["low"], pivot_L, pivot_R)

    # Get (value, rsi) at each pivot; then compare to prior pivot of same kind
    # Track last swing low's close and rsi, and last swing high's close and rsi.
    closes = df["close"].values
    rsi_v = rsi.values
    sh_v = sh.values
    sl_v = sl.values
    N = len(df)
    last_low_price = np.nan
    last_low_rsi = np.nan
    last_hi_price = np.nan
    last_hi_rsi = np.nan

    long_arr = np.zeros(N, dtype=bool)
    short_arr = np.zeros(N, dtype=bool)
    for i in range(N):
        if sl_v[i]:
            # Compare to prior swing low
            if not np.isnan(last_low_price):
                if closes[i] < last_low_price and rsi_v[i] > last_low_rsi and rsi_v[i] < 40:
                    long_arr[i] = True
            last_low_price = closes[i]
            last_low_rsi = rsi_v[i]
        if sh_v[i]:
            if not np.isnan(last_hi_price):
                if closes[i] > last_hi_price and rsi_v[i] < last_hi_rsi and rsi_v[i] > 60:
                    short_arr[i] = True
            last_hi_price = closes[i]
            last_hi_rsi = rsi_v[i]

    reg_sma = df["close"].rolling(regime_len).mean()
    regime_up = df["close"] > reg_sma
    regime_dn = df["close"] < reg_sma

    long_sig = pd.Series(long_arr, index=df.index) & regime_up
    short_sig = pd.Series(short_arr, index=df.index) & regime_dn
    return long_sig.fillna(False).astype(bool), short_sig.fillna(False).astype(bool)


# ===================================================================
# Family 6 — ATR squeeze breakout
# ===================================================================

def sig_atr_sqz(df, atr_n=14, sqz_ratio=0.7, donch_n=20, regime_len=400):
    """When ATR/rolling_mean(ATR) < sqz_ratio (volatility compression), a
    Donchian(n) breakout fires directional. ATR expansion should follow the
    compression, so trades are concentrated in regime transitions."""
    at = pd.Series(atr(df, atr_n), index=df.index)
    at_ma = at.rolling(atr_n * 5).mean()
    in_sqz = (at / at_ma) < sqz_ratio

    hi = df["high"].rolling(donch_n).max().shift(1)
    lo = df["low"].rolling(donch_n).min().shift(1)
    break_up = (df["close"] > hi) & in_sqz.shift(1).fillna(False)
    break_dn = (df["close"] < lo) & in_sqz.shift(1).fillna(False)

    reg_sma = df["close"].rolling(regime_len).mean()
    regime_up = df["close"] > reg_sma
    regime_dn = df["close"] < reg_sma

    long_sig = break_up & regime_up
    short_sig = break_dn & regime_dn
    return long_sig.fillna(False).astype(bool), short_sig.fillna(False).astype(bool)


# ===================================================================
# Runner
# ===================================================================

def run_one(df, lsig, ssig, tp, sl, tr, mh, risk, lev, lbl):
    ls = dedupe(lsig); ss = dedupe(ssig) if ssig is not None else None
    trades, eq = simulate(df, ls, short_entries=ss,
                          tp_atr=tp, sl_atr=sl, trail_atr=tr, max_hold=mh,
                          risk_per_trade=risk, leverage_cap=lev, fee=FEE)
    return metrics(lbl, eq, trades), trades, eq


EXITS_30M = [(5, 1.5, 3.0, 48), (7, 2.0, 4.0, 80)]
EXITS_1H  = [(6, 1.5, 3.5, 36), (10, 2.0, 5.0, 72)]
RISKS = [0.03, 0.05]


def sweep_family(sym, family):
    best = None
    for tf in ["30m", "1h"]:
        df = _load(sym, tf)
        if df is None or len(df) < 4000: continue
        exits = EXITS_30M if tf == "30m" else EXITS_1H

        if family == "LIQ_SWEEP":
            for L, R in [(5, 5), (8, 8)]:
                for vm in [1.2, 1.5]:
                    try:
                        lsig, ssig = sig_liq_sweep(df, L, R, vm, scaled(400, tf))
                    except Exception as e: continue
                    if lsig.sum() < 10 and ssig.sum() < 10: continue
                    for risk in RISKS:
                        for (tp, sl, tr, mh) in exits:
                            r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                     f"{sym}_{tf}_LSWP")
                            if r["n"] < 30 or r["dd"] < -0.45: continue
                            score = r["cagr_net"] * (r["sharpe"] / 1.5)
                            if best is None or score > best["score"]:
                                best = dict(sym=sym, family="Liq_Sweep", tf=tf,
                                             params=dict(L=L, R=R, vol_mult=vm),
                                             exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                             risk=risk, lev=3.0, metrics=r, trades=trades,
                                             eq=eq, score=score)

        elif family == "ORDER_BLOCK":
            for la in [4, 8]:
                for ai in [1.5, 2.5]:
                    for rb in [40, 80]:
                        try:
                            lsig, ssig = sig_order_block(df, la, ai, rb, scaled(400, tf))
                        except Exception: continue
                        if lsig.sum() < 10 and ssig.sum() < 10: continue
                        for risk in RISKS:
                            for (tp, sl, tr, mh) in exits:
                                r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                         f"{sym}_{tf}_OB")
                                if r["n"] < 30 or r["dd"] < -0.45: continue
                                score = r["cagr_net"] * (r["sharpe"] / 1.5)
                                if best is None or score > best["score"]:
                                    best = dict(sym=sym, family="Order_Block", tf=tf,
                                                 params=dict(lookahead=la, atr_impulse=ai,
                                                              retrace_bars=rb),
                                                 exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                                 risk=risk, lev=3.0, metrics=r, trades=trades,
                                                 eq=eq, score=score)

        elif family == "MSB":
            for L, R in [(5, 5), (8, 8)]:
                for vm in [1.1, 1.3]:
                    try:
                        lsig, ssig = sig_msb(df, L, R, vm)
                    except Exception: continue
                    if lsig.sum() < 10 and ssig.sum() < 10: continue
                    for risk in RISKS:
                        for (tp, sl, tr, mh) in exits:
                            r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                     f"{sym}_{tf}_MSB")
                            if r["n"] < 30 or r["dd"] < -0.45: continue
                            score = r["cagr_net"] * (r["sharpe"] / 1.5)
                            if best is None or score > best["score"]:
                                best = dict(sym=sym, family="MSB", tf=tf,
                                             params=dict(L=L, R=R, vol_mult=vm),
                                             exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                             risk=risk, lev=3.0, metrics=r, trades=trades,
                                             eq=eq, score=score)

        elif family == "ENGULF":
            for bb_n in [scaled(40, tf)]:
                for vm in [1.2, 1.5]:
                    try:
                        lsig, ssig = sig_engulf(df, bb_n, 2.0, vm)
                    except Exception: continue
                    if lsig.sum() < 10 and ssig.sum() < 10: continue
                    for risk in RISKS:
                        for (tp, sl, tr, mh) in exits:
                            r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                     f"{sym}_{tf}_ENG")
                            if r["n"] < 30 or r["dd"] < -0.45: continue
                            score = r["cagr_net"] * (r["sharpe"] / 1.5)
                            if best is None or score > best["score"]:
                                best = dict(sym=sym, family="Engulf_Vol", tf=tf,
                                             params=dict(bb_n=bb_n, bb_k=2.0, vol_mult=vm),
                                             exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                             risk=risk, lev=3.0, metrics=r, trades=trades,
                                             eq=eq, score=score)

        elif family == "RSI_DIV":
            for L, R in [(5, 5), (8, 8)]:
                try:
                    lsig, ssig = sig_rsi_div(df, 14, L, R, scaled(400, tf))
                except Exception: continue
                if lsig.sum() < 10 and ssig.sum() < 10: continue
                for risk in RISKS:
                    for (tp, sl, tr, mh) in exits:
                        r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                 f"{sym}_{tf}_DIV")
                        if r["n"] < 30 or r["dd"] < -0.45: continue
                        score = r["cagr_net"] * (r["sharpe"] / 1.5)
                        if best is None or score > best["score"]:
                            best = dict(sym=sym, family="RSI_Divergence", tf=tf,
                                         params=dict(L=L, R=R),
                                         exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                         risk=risk, lev=3.0, metrics=r, trades=trades,
                                         eq=eq, score=score)

        elif family == "ATR_SQZ":
            for sqr in [0.6, 0.75]:
                for dn in [scaled(20, tf), scaled(40, tf)]:
                    try:
                        lsig, ssig = sig_atr_sqz(df, 14, sqr, dn, scaled(400, tf))
                    except Exception: continue
                    if lsig.sum() < 10 and ssig.sum() < 10: continue
                    for risk in RISKS:
                        for (tp, sl, tr, mh) in exits:
                            r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                     f"{sym}_{tf}_SQZ")
                            if r["n"] < 30 or r["dd"] < -0.45: continue
                            score = r["cagr_net"] * (r["sharpe"] / 1.5)
                            if best is None or score > best["score"]:
                                best = dict(sym=sym, family="ATR_Squeeze", tf=tf,
                                             params=dict(sqz_ratio=sqr, donch_n=dn),
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
    ckpt = OUT / "v26_priceaction_results.pkl"
    families = ["LIQ_SWEEP", "ORDER_BLOCK", "MSB", "ENGULF", "RSI_DIV", "ATR_SQZ"]

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
            print(f"  {b['tf']:3s}  {b['family']:16s}  CAGR {m['cagr_net']*100:6.1f}%  "
                  f"Sh {m['sharpe']:+.2f}  DD {m['dd']*100:+6.1f}%  n={m['n']:4d}  "
                  f"p={b['params']}", flush=True)
            _persist(results, ckpt)

    _persist(results, ckpt)

    flat = [{"sym": w["sym"], "family": w["family"], "tf": w["tf"],
             "params": str(w["params"]),
             **{k: v for k, v in w["metrics"].items() if k != "label"}}
            for _, w in results.items()]
    pd.DataFrame(flat).to_csv(OUT / "v26_priceaction_summary.csv", index=False)

    print("\n" + "=" * 80)
    print("V26 PRICE-ACTION — per-coin per-family winners")
    print("=" * 80)
    if flat:
        print(pd.DataFrame(flat).to_string(index=False))
    else:
        print("(no viable configs)")


if __name__ == "__main__":
    sys.exit(main() or 0)
