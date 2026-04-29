"""
V7 — Cycle-aware 15m trend strategy (no vectorbt, pure numpy/pandas).

Design (drawn from BTC 4-year cycle research + 2025 15m-TF practitioners):

  REGIME DETECTOR  (derived from 1-day aggregated close, resampled from 15m):
    bull   : close > EMA(200d)  AND  EMA(200d) rising over last 30 days
    bear   : close < EMA(200d)  AND  EMA(200d) falling over last 30 days
    neutral: everything else (no trades)

  DIRECTION GATE  (long-only or short-only, never both):
    bull regime  → LONGS ONLY
    bear regime  → SHORTS ONLY
    neutral      → FLAT

  15-MIN SIGNAL (SuperTrend + EMA + MACD + volume):
    ATR(10)*3 SuperTrend flipped in our favour
    AND EMA(50) > EMA(200) on 15m  (longs)  OR  EMA(50) < EMA(200) (shorts)
    AND MACD histogram sign matches direction
    AND volume > SMA(volume, 20) * 1.2  (weak confirmation to avoid dead hours)

  EXITS (ATR-scaled, 2:1 R:R, no fixed % nonsense):
    Stop       :  1.5 × ATR(14)        (≈ 3-5 % on 15m crypto)
    Target     :  3.0 × ATR(14)        (2:1)
    Trail      :  once +1.5 × ATR in profit, trail by ATR(14)

Costs: 0.1 % per side + 5 bps slippage (Binance spot).
One position at a time, execution at next-bar OPEN after signal close.

Note: cycle-regime is computed on DAILY bars and broadcast forward onto the
15m series — no look-ahead (we shift by 1 daily bar).
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


# ---------------- indicators ----------------
def ema(s, n): return s.ewm(span=n, adjust=False).mean()


def rma(s, n):
    """Wilder smoothing (used by ATR)."""
    return s.ewm(alpha=1/n, adjust=False).mean()


def atr(df, n=14):
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - df["close"].shift()).abs()
    tr3 = (df["low"]  - df["close"].shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return rma(tr, n)


def macd_hist(close, fast=12, slow=26, sig=9):
    macd = ema(close, fast) - ema(close, slow)
    signal = ema(macd, sig)
    return macd - signal


def supertrend(df, n=10, mult=3.0):
    a = atr(df, n)
    hl2 = (df["high"] + df["low"]) / 2
    up  = (hl2 - mult * a).values
    dn  = (hl2 + mult * a).values
    c   = df["close"].values
    N   = len(df)
    final_up = up.copy(); final_dn = dn.copy()
    trend = np.ones(N, dtype=np.int8)
    for i in range(1, N):
        if c[i-1] > final_up[i-1]:
            final_up[i] = max(up[i], final_up[i-1])
        if c[i-1] < final_dn[i-1]:
            final_dn[i] = min(dn[i], final_dn[i-1])
        if trend[i-1] == 1 and c[i] < final_up[i]:
            trend[i] = -1
        elif trend[i-1] == -1 and c[i] > final_dn[i]:
            trend[i] = 1
        else:
            trend[i] = trend[i-1]
    return pd.Series(trend, index=df.index)


# ---------------- data ----------------
def load(sym, tf):
    files = sorted((DATA / sym / tf).glob("year=*/part.parquet"))
    dfs = [pd.read_parquet(f) for f in files]
    d = pd.concat(dfs, ignore_index=True)
    d = d.drop_duplicates("open_time").sort_values("open_time").set_index("open_time")
    d = d[(d.index >= pd.Timestamp(START, tz="UTC")) & (d.index < pd.Timestamp(END, tz="UTC"))]
    return d[["open","high","low","close","volume"]].astype("float64")


# ---------------- regime ----------------
def cycle_regime(close_15m: pd.Series) -> pd.Series:
    """Return -1 (bear), +1 (bull), 0 (neutral) broadcast to the 15m index.
       Regime is computed on DAILY bars and shifted by 1 day (no look-ahead)."""
    d = close_15m.resample("1D").last().dropna()
    e200 = ema(d, 200)
    slope30 = e200 - e200.shift(30)
    bull =  (d > e200) & (slope30 > 0)
    bear =  (d < e200) & (slope30 < 0)
    r = np.where(bull, 1, np.where(bear, -1, 0))
    reg = pd.Series(r, index=d.index).shift(1)    # no peek
    return reg.reindex(close_15m.index, method="ffill").fillna(0).astype(int)


# ---------------- simulator ----------------
def simulate(df, risk_pct=0.01, atr_n=14, sl_mult=1.5, tp_mult=3.0,
             trail_after_mult=1.5, st_n=10, st_mult=3.0,
             vol_mult=1.2):
    reg = cycle_regime(df["close"])
    st  = supertrend(df, st_n, st_mult)
    st_flip_up   = (st == 1)  & (st.shift(1) == -1)
    st_flip_dn   = (st == -1) & (st.shift(1) == 1)
    e50  = ema(df["close"], 50)
    e200 = ema(df["close"], 200)
    mh   = macd_hist(df["close"])
    vavg = df["volume"].rolling(20).mean()
    vol_ok = df["volume"] > vavg * vol_mult
    a    = atr(df, atr_n)

    bull_trigger = st_flip_up & (e50 > e200) & (mh > 0) & vol_ok
    bear_trigger = st_flip_dn & (e50 < e200) & (mh < 0) & vol_ok

    # broadcast to arrays
    op = df["open"].values
    hi = df["high"].values
    lo = df["low"].values
    cl = df["close"].values
    at = a.values
    reg_v = reg.values
    bull_v = bull_trigger.values
    bear_v = bear_trigger.values

    N = len(df)
    cash = INIT
    equity = np.empty(N)
    equity[0] = INIT
    pos = 0
    entry = sl = tp = 0.0
    size = 0.0
    hh_since = ll_since = 0.0
    entry_idx = 0

    trades = []

    for i in range(1, N - 1):
        # --- intra-bar exit check on current bar ---
        if pos == 1:
            hh_since = max(hh_since, hi[i])
            # trail after 1.5*ATR profit
            if hh_since - entry >= trail_after_mult * at[i]:
                sl = max(sl, hh_since - sl_mult * at[i])
            # SL first (worst case)
            if lo[i] <= sl:
                exit_p = sl * (1 - SLIP)
                ret = (exit_p / entry - 1) - FEE * 2
                cash = cash * (1 + ret * size / cash) if False else cash + size * (exit_p - entry) - size * entry * FEE * 2
                trades.append(dict(side=1, entry=entry, exit=exit_p,
                                   ret=ret, reason="SL", bars=i-entry_idx))
                pos = 0; size = 0
            elif hi[i] >= tp:
                exit_p = tp * (1 - SLIP)
                ret = (exit_p / entry - 1) - FEE * 2
                cash = cash + size * (exit_p - entry) - size * entry * FEE * 2
                trades.append(dict(side=1, entry=entry, exit=exit_p,
                                   ret=ret, reason="TP", bars=i-entry_idx))
                pos = 0; size = 0
        elif pos == -1:
            ll_since = min(ll_since, lo[i])
            if entry - ll_since >= trail_after_mult * at[i]:
                sl = min(sl, ll_since + sl_mult * at[i])
            if hi[i] >= sl:
                exit_p = sl * (1 + SLIP)
                ret = (entry / exit_p - 1) - FEE * 2
                cash = cash + size * (entry - exit_p) - size * entry * FEE * 2
                trades.append(dict(side=-1, entry=entry, exit=exit_p,
                                   ret=ret, reason="SL", bars=i-entry_idx))
                pos = 0; size = 0
            elif lo[i] <= tp:
                exit_p = tp * (1 + SLIP)
                ret = (entry / exit_p - 1) - FEE * 2
                cash = cash + size * (entry - exit_p) - size * entry * FEE * 2
                trades.append(dict(side=-1, entry=entry, exit=exit_p,
                                   ret=ret, reason="TP", bars=i-entry_idx))
                pos = 0; size = 0

        # --- new entries on close of bar i, executed at open of bar i+1 ---
        if pos == 0 and i + 1 < N:
            # cycle gate: only long in bull, only short in bear
            if reg_v[i] == 1 and bull_v[i]:
                entry = op[i+1] * (1 + SLIP)
                sl = entry - sl_mult * at[i]
                tp = entry + tp_mult * at[i]
                # risk-based sizing: lose (risk_pct * cash) on SL hit
                risk_per_unit = entry - sl
                size = (cash * risk_pct) / risk_per_unit if risk_per_unit > 0 else 0
                if size > 0:
                    pos = 1; entry_idx = i + 1
                    hh_since = entry
            elif reg_v[i] == -1 and bear_v[i]:
                entry = op[i+1] * (1 - SLIP)
                sl = entry + sl_mult * at[i]
                tp = entry - tp_mult * at[i]
                risk_per_unit = sl - entry
                size = (cash * risk_pct) / risk_per_unit if risk_per_unit > 0 else 0
                if size > 0:
                    pos = -1; entry_idx = i + 1
                    ll_since = entry

        # mark-to-market equity
        if pos == 0:
            equity[i] = cash
        else:
            p = cl[i]
            if pos == 1:
                unreal = size * (p - entry) - size * entry * FEE
            else:
                unreal = size * (entry - p) - size * entry * FEE
            equity[i] = cash + unreal
    equity[-1] = equity[-2]

    eq = pd.Series(equity, index=df.index)
    return trades, eq, reg


def _consec(rets):
    mw = cw = ml = cl = 0
    for r in rets:
        if r > 0: cw += 1; cl = 0
        elif r < 0: cl += 1; cw = 0
        mw = max(mw, cw); ml = max(ml, cl)
    return mw, ml


def metrics(eq, trades):
    rets = eq.pct_change().dropna()
    if len(rets) < 2:
        return dict(final=float(eq.iloc[-1]), cagr=0, sharpe=0, max_dd=0,
                    calmar=0, n_trades=0, win_rate=0, profit_factor=0,
                    avg_win_pct=0, avg_loss_pct=0, max_cw=0, max_cl=0)
    dt = rets.index.to_series().diff().median()
    bpy = pd.Timedelta(days=365.25) / dt if dt else 1
    mu, sd = rets.mean(), rets.std()
    dn = rets[rets < 0].std()
    sh  = (mu / sd) * np.sqrt(bpy) if sd else 0
    so  = (mu / dn) * np.sqrt(bpy) if dn else 0
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 1e-6)) - 1
    dd = (eq / eq.cummax() - 1).min()
    calmar = cagr / abs(dd) if dd else 0
    pnl = np.array([t["ret"] for t in trades])
    wins = pnl[pnl > 0]; losses = pnl[pnl < 0]
    pf = (wins.sum() / abs(losses.sum())) if len(losses) else 0
    mcw, mcl = _consec(pnl)
    longs  = [t for t in trades if t["side"] == 1]
    shorts = [t for t in trades if t["side"] == -1]
    return dict(
        final=float(eq.iloc[-1]),
        cagr=float(cagr),
        sharpe=float(sh),
        sortino=float(so),
        max_dd=float(dd),
        calmar=float(calmar),
        n_trades=len(trades),
        n_longs=len(longs),
        n_shorts=len(shorts),
        n_wins=int((pnl > 0).sum()),
        n_losses=int((pnl < 0).sum()),
        win_rate=float((pnl > 0).mean()) if len(pnl) else 0,
        profit_factor=float(pf),
        avg_win_pct=float(wins.mean()) if len(wins) else 0,
        avg_loss_pct=float(losses.mean()) if len(losses) else 0,
        largest_win_pct=float(wins.max()) if len(wins) else 0,
        largest_loss_pct=float(losses.min()) if len(losses) else 0,
        max_cw=int(mcw), max_cl=int(mcl),
    )


# ---------------- main ----------------
def main():
    rows = []
    t0 = time.time()
    for tf in ["15m"]:
        for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
            t = time.time()
            df = load(sym, tf)
            trades, eq, reg = simulate(df)
            m = metrics(eq, trades)
            bh = float(df["close"].iloc[-1] / df["close"].iloc[0] - 1)
            rows.append({"symbol": sym, "tf": tf, "bars": len(df),
                         **{k: round(v, 5) if isinstance(v, float) else v
                            for k, v in m.items()},
                         "bh_return": round(bh, 4)})
            print(f"  {sym}/{tf}  trades={m['n_trades']:<4d} "
                  f"(L={m['n_longs']}, S={m['n_shorts']})  "
                  f"CAGR={m['cagr']*100:+7.2f}%  Sharpe={m['sharpe']:>5.2f}  "
                  f"DD={m['max_dd']*100:+7.2f}%  PF={m['profit_factor']:.2f}  "
                  f"Win%={m['win_rate']*100:>5.1f}  "
                  f"Final=${m['final']:>9,.0f}  BH={bh*100:+.0f}%   "
                  f"({time.time()-t:.1f}s)", flush=True)

            eq.to_csv(OUT / f"V7_{sym}_equity.csv")

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "V7_cycle_aware.csv", index=False)
    print(f"\nSaved V7_cycle_aware.csv  ({time.time()-t0:.1f}s)")
    print("\nSUMMARY:")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
