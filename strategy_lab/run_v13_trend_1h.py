"""
V13 — Port our 4h trend winners to 1h.

Hypothesis: mean-reversion at 1h is real (IC -0.07) but NOT tradeable at fee floor.
Trend-following, which won at 4h, might scale down to 1h with parameter retuning.

Test: V4C Range Kalman, V3B ADX Gate, V2B Volume Breakout — at 1h.

Params scaled for 1h: lookbacks 4x larger, stops similar (ATR-scaled so self-adapts).
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
FEAT = ROOT/"strategy_lab"/"features"
OUT  = ROOT/"strategy_lab"/"results"

FEE  = 0.00015; SLIP = 0.0003; INIT = 10_000.0


def _atr(df, n=14):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    tr = np.maximum.reduce([h-l, np.abs(h-np.roll(c,1)), np.abs(l-np.roll(c,1))])
    return pd.Series(tr, index=df.index).ewm(alpha=1/n, adjust=False).mean().values


def v13_range_kalman(df, alpha=0.05, rng_len=400, rng_mult=2.5, regime_len=800,
                    trail_atr=3.5, atr_len=14):
    """V4C ported to 1h (~4x longer lookbacks)."""
    c = df["close"].values
    n = len(c)
    # Kalman-ish smoother (simple EMA proxy)
    kal = np.zeros(n); kal[0] = c[0]
    for i in range(1, n):
        kal[i] = kal[i-1] + alpha*(c[i] - kal[i-1])
    abs_dev = np.abs(c - kal)
    rng = pd.Series(abs_dev, index=df.index).rolling(rng_len).mean().values * rng_mult
    upper = kal + rng; lower = kal - rng
    regime = c > pd.Series(c, index=df.index).rolling(regime_len).mean().values
    breakout = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if c[i] > upper[i] and c[i-1] <= upper[i-1] and regime[i]:
            breakout[i] = True
    return pd.Series(breakout, index=df.index)


def v13_adx_gate(df, don_len=120, vol_len=80, vol_mult=1.3, regime_len=600,
                 adx_min=20):
    import talib
    hi = df["high"].rolling(don_len).max().shift(1).values
    vavg = df["volume"].rolling(vol_len).mean().values
    vol_spike = df["volume"].values > vavg * vol_mult
    regime = df["close"].values > df["close"].rolling(regime_len).mean().values
    adx = talib.ADX(df["high"].values, df["low"].values, df["close"].values, 14)
    sig = (df["close"].values > hi) & vol_spike & regime & (adx > adx_min)
    return pd.Series(sig, index=df.index)


def v13_volume_breakout(df, don_len=120, vol_len=80, vol_mult=1.3, regime_len=600):
    hi = df["high"].rolling(don_len).max().shift(1).values
    vavg = df["volume"].rolling(vol_len).mean().values
    vol_spike = df["volume"].values > vavg * vol_mult
    regime = df["close"].values > df["close"].rolling(regime_len).mean().values
    sig = (df["close"].values > hi) & vol_spike & regime
    return pd.Series(sig, index=df.index)


def simulate(df, entries, tp_atr=5.0, sl_atr=2.0, trail_atr=None, max_hold=72,
             size_frac=0.99):
    op, hi, lo, cl = df["open"].values, df["high"].values, df["low"].values, df["close"].values
    at = _atr(df)
    sig = entries.values.astype(bool)
    n = len(df)
    cash = INIT
    eq = np.empty(n); eq[0] = cash
    pos=0; entry_p=sl=tp=0.0; size=0.0; entry_idx=0; last_exit=-9999; hh=0.0
    trades=[]
    for i in range(1, n-1):
        if pos == 1:
            held = i - entry_idx
            # Trail stop (optional)
            if trail_atr is not None:
                hh = max(hh, hi[i])
                new_sl = hh - trail_atr * at[i]
                if new_sl > sl: sl = new_sl
            if lo[i] <= sl:
                ep = sl*(1-SLIP); ret=(ep/entry_p-1) - 2*FEE
                cash += size*(ep-entry_p) - size*(entry_p+ep)*FEE
                trades.append({"ret":ret,"reason":"SL","bars":held}); pos=0; last_exit=i
                eq[i]=cash; continue
            if hi[i] >= tp:
                ep = tp*(1-SLIP); ret=(ep/entry_p-1) - 2*FEE
                cash += size*(ep-entry_p) - size*(entry_p+ep)*FEE
                trades.append({"ret":ret,"reason":"TP","bars":held}); pos=0; last_exit=i
                eq[i]=cash; continue
            if held >= max_hold:
                ep = cl[i]; ret=(ep/entry_p-1) - 2*FEE
                cash += size*(ep-entry_p) - size*(entry_p+ep)*FEE
                trades.append({"ret":ret,"reason":"TIME","bars":held}); pos=0; last_exit=i
                eq[i]=cash; continue
        if pos==0 and (i-last_exit)>2 and sig[i] and i+1<n:
            ep = op[i+1]*(1+SLIP)
            sl = ep - sl_atr*at[i]
            tp = ep + tp_atr*at[i]
            if np.isfinite(sl) and np.isfinite(tp):
                size = (cash*size_frac)/ep
                pos=1; entry_p=ep; entry_idx=i+1; hh=ep
        if pos==0: eq[i]=cash
        else: eq[i] = cash + size*(cl[i]-entry_p) - size*entry_p*FEE
    eq[-1] = eq[-2]
    return trades, pd.Series(eq, index=df.index)


def report(label, eq, trades):
    if len(trades) < 3: return {"label":label,"n":len(trades),"final":float(eq.iloc[-1]),
                                 "cagr":0,"sharpe":0,"dd":0,"win":0,"pf":0}
    rets = eq.pct_change().dropna()
    dt = rets.index.to_series().diff().median()
    bpy = pd.Timedelta(days=365.25)/dt if dt else 1
    sh = rets.mean()/rets.std()*np.sqrt(bpy) if rets.std()>0 else 0
    yrs = (eq.index[-1]-eq.index[0]).total_seconds()/(365.25*86400)
    cagr = (eq.iloc[-1]/eq.iloc[0])**(1/max(yrs,1e-6))-1
    dd = float((eq/eq.cummax()-1).min())
    pnl = np.array([t["ret"] for t in trades])
    pf = pnl[pnl>0].sum()/abs(pnl[pnl<0].sum()) if (pnl<0).any() else 0
    return dict(label=label, n=len(trades), final=float(eq.iloc[-1]),
                cagr=round(cagr,4), sharpe=round(sh,3), dd=round(dd,4),
                win=round((pnl>0).mean(),3), pf=round(pf,3))


def main():
    rows=[]
    for sym in ["BTCUSDT","ETHUSDT","SOLUSDT"]:
        df = pd.read_parquet(FEAT/f"{sym}_1h_features.parquet")
        df = df.dropna(subset=["open","high","low","close","volume"]).copy()
        # start from 2019 where enough history exists
        df = df[df.index >= pd.Timestamp("2019-01-01", tz="UTC")]

        print(f"\n=== {sym}  ({len(df):,} bars 1h) ===", flush=True)

        for name, sig_fn, tp, sl, trail in [
            ("V13A_RangeKalman", v13_range_kalman, 5.0, 2.0, 3.5),
            ("V13B_ADXGate",     v13_adx_gate,     5.0, 2.0, 3.5),
            ("V13C_VolBreakout", v13_volume_breakout, 5.0, 2.0, 3.5),
        ]:
            sig = sig_fn(df)
            # Fire only on fresh signals
            sig = sig & ~sig.shift(1).fillna(False)
            tr, eq = simulate(df, sig, tp_atr=tp, sl_atr=sl, trail_atr=trail,
                              max_hold=72)
            r = report(f"{sym}_{name}", eq, tr)
            rows.append(r)

            # OOS split
            cut = pd.Timestamp("2024-01-01", tz="UTC")
            tr_o, eq_o = simulate(df[df.index>=cut], sig[df.index>=cut],
                                  tp_atr=tp, sl_atr=sl, trail_atr=trail, max_hold=72)
            r_o = report(f"{sym}_{name}_OOS", eq_o, tr_o)
            rows.append(r_o)

            print(f"  {name:20s} FULL n={r['n']:4d} Sh={r['sharpe']:5.2f} CAGR={r['cagr']*100:+7.1f}% DD={r['dd']*100:+6.1f}% Win={r['win']*100:4.1f}% PF={r['pf']:.2f} | "
                  f"OOS n={r_o['n']:4d} Sh={r_o['sharpe']:5.2f} CAGR={r_o['cagr']*100:+7.1f}%", flush=True)

    df_out = pd.DataFrame(rows)
    df_out.to_csv(OUT/"V13_trend_1h_results.csv", index=False)
    print(f"\nSaved V13_trend_1h_results.csv ({len(df_out)} rows)")


if __name__ == "__main__":
    sys.exit(main() or 0)
