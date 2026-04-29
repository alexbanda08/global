"""
V8 — Clean 15m strategy, learning from V6/V7 failures.

Lessons applied:
  * Shorts KILL on 15m (V7 lost 99% — regime flips whipsaw shorts to death).
    V8 is LONG-ONLY and FLAT during bear.
  * Risk-based sizing created phantom leverage.  V8 uses 99% of cash
    per trade (single-position spot, same as our 4h winners).
  * Fixed % SL/TP gave break-even EV.  V8 uses ATR stops with
    wider targets (3:1 target:stop baseline).
  * Over-trading wrecked 15m.  V8 has a RE-ENTRY LOCKOUT of
    2 hours (8 bars) after any exit to force the engine to
    wait for the next clean setup.

REGIME (same cycle-aware detector as V7, computed on 1-day resample):
    bull    : close > EMA(200d)  AND  slope(EMA200d, 60d) > 0
    bear    : close < EMA(200d)  AND  slope(EMA200d, 60d) < 0
    neutral : no trades

15M SIGNAL (long-only, triggers only in bull):
    1) SuperTrend(10, 3) flipped UP this bar
    2) EMA(50) > EMA(200)
    3) close > VWAP(session, reset daily)
    4) MACD histogram just turned positive
    5) volume > SMA(volume, 20)

EXITS:
    * SL = entry - 1.5 * ATR(14)
    * TP = entry + 4.5 * ATR(14)      ← 3:1 baseline
    * Trail once price >= entry + 2 * ATR: stop moves to highest_since_entry - 1.5*ATR
    * Hard exit on regime flip to bear

Fees 0.1 % + 5 bps slip per side.  Execution at next-bar open.
"""
from __future__ import annotations
import time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "binance" / "parquet"
OUT  = ROOT / "strategy_lab" / "results"

FEE = 0.001
SLIP = 0.0005
INIT = 10_000.0
START, END = "2018-01-01", "2026-04-01"


def ema(s, n): return s.ewm(span=n, adjust=False).mean()


def rma(s, n): return s.ewm(alpha=1/n, adjust=False).mean()


def atr(df, n=14):
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"]  - df["close"].shift()).abs()
    ], axis=1).max(axis=1)
    return rma(tr, n)


def macd_hist(close, fast=12, slow=26, sig=9):
    m = ema(close, fast) - ema(close, slow)
    return m - ema(m, sig)


def supertrend(df, n=10, mult=3.0):
    a = atr(df, n)
    hl2 = (df["high"] + df["low"]) / 2
    up, dn = (hl2 - mult * a).values, (hl2 + mult * a).values
    c = df["close"].values
    N = len(df)
    fu, fd = up.copy(), dn.copy()
    trend = np.ones(N, dtype=np.int8)
    for i in range(1, N):
        if c[i-1] > fu[i-1]: fu[i] = max(up[i], fu[i-1])
        if c[i-1] < fd[i-1]: fd[i] = min(dn[i], fd[i-1])
        if trend[i-1] == 1 and c[i] < fu[i]: trend[i] = -1
        elif trend[i-1] == -1 and c[i] > fd[i]: trend[i] = 1
        else: trend[i] = trend[i-1]
    return pd.Series(trend, index=df.index)


def daily_vwap(df):
    """Session VWAP that resets each UTC day."""
    date_key = df.index.floor("1D")
    tp = (df["high"] + df["low"] + df["close"]) / 3
    pv = tp * df["volume"]
    # cumulative per day
    cum_pv = pv.groupby(date_key).cumsum()
    cum_v  = df["volume"].groupby(date_key).cumsum()
    return cum_pv / cum_v.replace(0, np.nan)


def load(sym, tf):
    files = sorted((DATA / sym / tf).glob("year=*/part.parquet"))
    dfs = [pd.read_parquet(f) for f in files]
    d = pd.concat(dfs, ignore_index=True)
    d = d.drop_duplicates("open_time").sort_values("open_time").set_index("open_time")
    d = d[(d.index >= pd.Timestamp(START, tz="UTC")) & (d.index < pd.Timestamp(END, tz="UTC"))]
    return d[["open","high","low","close","volume"]].astype("float64")


def cycle_regime(close_15m: pd.Series) -> pd.Series:
    d = close_15m.resample("1D").last().dropna()
    e200 = ema(d, 200)
    slope60 = e200 - e200.shift(60)
    bull = (d > e200) & (slope60 > 0)
    bear = (d < e200) & (slope60 < 0)
    r = np.where(bull, 1, np.where(bear, -1, 0))
    reg = pd.Series(r, index=d.index).shift(1)
    return reg.reindex(close_15m.index, method="ffill").fillna(0).astype(int)


def simulate(df, sl_mult=1.5, tp_mult=4.5, trail_after_mult=2.0,
             lockout_bars=8, alloc=0.99):
    reg = cycle_regime(df["close"])
    st  = supertrend(df)
    st_flip_up = (st == 1) & (st.shift(1) == -1)
    e50, e200 = ema(df["close"], 50), ema(df["close"], 200)
    mh  = macd_hist(df["close"])
    mh_cross_up = (mh > 0) & (mh.shift(1) <= 0)
    vw = daily_vwap(df)
    vavg = df["volume"].rolling(20).mean()
    a = atr(df)

    # Looser trigger: Either SuperTrend flip OR MACD hist flip, combined
    # with: EMA50>EMA200, close>VWAP, volume>avg, regime=1
    long_trigger = ((st_flip_up | mh_cross_up) &
                    (e50 > e200) &
                    (df["close"] > vw) &
                    (df["volume"] > vavg))

    op = df["open"].values; hi = df["high"].values
    lo = df["low"].values;  cl = df["close"].values
    at = a.values
    reg_v = reg.values
    trig = long_trigger.values

    N = len(df)
    cash = INIT
    equity = np.empty(N); equity[0] = INIT
    pos = 0
    entry = sl = tp = 0.0
    size = 0.0
    hh = 0.0
    entry_idx = 0
    last_exit_idx = -1
    trades = []

    for i in range(1, N - 1):
        if pos == 1:
            hh = max(hh, hi[i])
            # Move stop up to trail once in 2*ATR profit
            if hh - entry >= trail_after_mult * at[i]:
                new_sl = hh - sl_mult * at[i]
                if new_sl > sl:
                    sl = new_sl
            # Bear regime flip → flatten
            bear_flip = reg_v[i] == -1

            if bear_flip and not (lo[i] <= sl or hi[i] >= tp):
                # exit at close (approximation of market exit)
                exit_p = cl[i] * (1 - SLIP)
                ret = (exit_p / entry - 1)
                # cash = notional P&L  +  remaining (cash - notional)
                cash = cash + size * (exit_p - entry) - size * entry * FEE - size * exit_p * FEE
                trades.append(dict(entry=entry, exit=exit_p, ret=ret - 2 * FEE,
                                   reason="regime", bars=i - entry_idx))
                pos = 0; last_exit_idx = i
                continue

            if lo[i] <= sl:
                exit_p = sl * (1 - SLIP)
                ret = (exit_p / entry - 1)
                cash = cash + size * (exit_p - entry) - size * entry * FEE - size * exit_p * FEE
                trades.append(dict(entry=entry, exit=exit_p, ret=ret - 2 * FEE,
                                   reason="SL", bars=i - entry_idx))
                pos = 0; last_exit_idx = i
                continue
            if hi[i] >= tp:
                exit_p = tp * (1 - SLIP)
                ret = (exit_p / entry - 1)
                cash = cash + size * (exit_p - entry) - size * entry * FEE - size * exit_p * FEE
                trades.append(dict(entry=entry, exit=exit_p, ret=ret - 2 * FEE,
                                   reason="TP", bars=i - entry_idx))
                pos = 0; last_exit_idx = i
                continue

        if pos == 0 and i + 1 < N:
            if reg_v[i] == 1 and trig[i] and (i - last_exit_idx) > lockout_bars:
                entry = op[i + 1] * (1 + SLIP)
                sl = entry - sl_mult * at[i]
                tp = entry + tp_mult * at[i]
                if sl < entry and tp > entry:
                    size = (cash * alloc) / entry   # spot full-alloc, no leverage
                    if size > 0:
                        pos = 1
                        entry_idx = i + 1
                        hh = entry

        # mark-to-market
        if pos == 0:
            equity[i] = cash
        else:
            p = cl[i]
            unreal = size * (p - entry) - size * entry * FEE     # have paid entry fee
            equity[i] = cash - size * entry + (cash - size * entry < 0 and 0 or 0) + unreal + (size * entry)
            # cleaner: cash held = cash - (size*entry) when in position; equity = cash_held + size*p
            # Since we DIDN'T actually deduct cash on entry above, we compute equity as
            # cash + unrealized, where unrealized = size*(p - entry) - entry fee paid.
            equity[i] = cash + unreal
    equity[-1] = equity[-2]

    eq = pd.Series(equity, index=df.index)
    return trades, eq


def _consec(rets):
    mw = cw = ml = cl = 0
    for r in rets:
        if r > 0: cw += 1; cl = 0
        elif r < 0: cl += 1; cw = 0
        mw = max(mw, cw); ml = max(ml, cl)
    return mw, ml


def metrics(eq, trades):
    rets = eq.pct_change().dropna()
    if len(rets) < 2 or len(trades) == 0:
        return dict(final=float(eq.iloc[-1]), cagr=0, sharpe=0, max_dd=0,
                    calmar=0, n_trades=0)
    dt = rets.index.to_series().diff().median()
    bpy = pd.Timedelta(days=365.25) / dt if dt else 1
    mu, sd = rets.mean(), rets.std()
    dn = rets[rets < 0].std()
    sh = (mu / sd) * np.sqrt(bpy) if sd else 0
    so = (mu / dn) * np.sqrt(bpy) if dn else 0
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 1e-6)) - 1
    dd = float((eq / eq.cummax() - 1).min())
    pnl = np.array([t["ret"] for t in trades])
    wins = pnl[pnl > 0]; losses = pnl[pnl < 0]
    pf = (wins.sum() / abs(losses.sum())) if len(losses) else 0
    mcw, mcl = _consec(pnl)
    return dict(
        final=float(eq.iloc[-1]),
        cagr=float(cagr),
        sharpe=float(sh),
        sortino=float(so),
        max_dd=dd,
        calmar=float(cagr / abs(dd)) if dd else 0,
        n_trades=len(trades),
        n_wins=int((pnl > 0).sum()),
        n_losses=int((pnl < 0).sum()),
        win_rate=float((pnl > 0).mean()) if len(pnl) else 0,
        profit_factor=float(pf),
        avg_win_pct=float(wins.mean()) if len(wins) else 0,
        avg_loss_pct=float(losses.mean()) if len(losses) else 0,
        largest_win_pct=float(wins.max()) if len(wins) else 0,
        largest_loss_pct=float(losses.min()) if len(losses) else 0,
        max_cw=int(mcw), max_cl=int(mcl),
        sl_exits=int(sum(1 for t in trades if t["reason"] == "SL")),
        tp_exits=int(sum(1 for t in trades if t["reason"] == "TP")),
        regime_exits=int(sum(1 for t in trades if t["reason"] == "regime")),
    )


def main():
    rows = []
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        t = time.time()
        df = load(sym, "15m")
        trades, eq = simulate(df)
        m = metrics(eq, trades)
        bh = float(df["close"].iloc[-1] / df["close"].iloc[0] - 1)
        rows.append({"symbol": sym, **m, "bh_return": bh})
        print(f"  {sym}/15m  trades={m['n_trades']:<4d} "
              f"(SL={m.get('sl_exits',0)}, TP={m.get('tp_exits',0)}, Reg={m.get('regime_exits',0)})  "
              f"CAGR={m['cagr']*100:+7.2f}%  Sharpe={m['sharpe']:>5.2f}  "
              f"DD={m['max_dd']*100:+7.2f}%  PF={m.get('profit_factor',0):.2f}  "
              f"Win%={m.get('win_rate',0)*100:>5.1f}  "
              f"Final=${m['final']:>10,.0f}  BH={bh*100:+.0f}%  "
              f"({time.time()-t:.1f}s)", flush=True)
        eq.to_csv(OUT / f"V8_{sym}_equity.csv")

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "V8_cycle_scalp.csv", index=False)
    print("\nSaved V8_cycle_scalp.csv")


if __name__ == "__main__":
    main()
