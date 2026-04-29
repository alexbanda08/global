"""
V6 mean-reversion — direct (numpy/pandas only) backtest.
No vectorbt import.  Intra-bar SL / TP using bar high/low.

Logic (ported from user's Pine "Optimized BTC Mean Reversion RSI 20/65"):
  LONG : RSI(14) < 20  AND  Stoch%K(14) < 25  AND  close > EMA(200) * 0.9
  SHORT: RSI(14) > 65  AND  Stoch%K(14) > 75  AND  close < EMA(200)
  Fixed SL 4 %, TP 6 %, Binance spot costs 0.1 % + 5 bps slippage.
  One position at a time, execution at NEXT bar open.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "binance" / "parquet"
OUT  = ROOT / "strategy_lab" / "results"

FEE   = 0.001        # 0.1 % per side
SLIP  = 0.0005       # 5 bps

SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TFS  = ["5m", "15m", "1h"]
START, END = "2018-01-01", "2026-04-01"
INIT = 10_000.0


# ---------- indicator helpers ----------
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(close, n=14):
    delta = close.diff()
    up   = delta.clip(lower=0)
    dn   = (-delta).clip(lower=0)
    ru   = up.ewm(alpha=1/n, adjust=False).mean()
    rd   = dn.ewm(alpha=1/n, adjust=False).mean()
    rs = ru / rd.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def stoch_k(df, n=14):
    hh = df["high"].rolling(n).max()
    ll = df["low"].rolling(n).min()
    return 100 * (df["close"] - ll) / (hh - ll)


# ---------- data ----------
def load(sym, tf):
    files = sorted((DATA / sym / tf).glob("year=*/part.parquet"))
    dfs = [pd.read_parquet(f) for f in files]
    d = pd.concat(dfs, ignore_index=True)
    d = d.drop_duplicates("open_time").sort_values("open_time").set_index("open_time")
    d = d[(d.index >= pd.Timestamp(START, tz="UTC")) & (d.index < pd.Timestamp(END, tz="UTC"))]
    return d[["open","high","low","close","volume"]].astype("float64")


# ---------- simulator ----------
def simulate(df,
             ema_len=200, rsi_len=14,
             rsi_buy=20.0, rsi_sell=65.0,
             stoch_n=14, stoch_ob=75.0, stoch_os=25.0,
             sl_pct=0.04, tp_pct=0.06):
    e = ema(df["close"], ema_len)
    r = rsi(df["close"], rsi_len)
    k = stoch_k(df, stoch_n)

    long_sig  = (r < rsi_buy)  & (k < stoch_os) & (df["close"] > e * 0.9)
    short_sig = (r > rsi_sell) & (k > stoch_ob) & (df["close"] < e)

    # vectors for fast access
    op = df["open"].values
    hi = df["high"].values
    lo = df["low"].values
    ls = long_sig.values
    ss = short_sig.values
    n  = len(df)

    cash = INIT
    equity = [INIT]
    pos = 0            # +1 long, -1 short, 0 flat
    entry = sl = tp = 0.0
    trades = []        # list of dicts

    for i in range(1, n - 1):
        # --- intra-bar stop/target check on bar i ---
        if pos == 1:
            # SL first (worst case)
            if lo[i] <= sl:
                exit_p = sl * (1 - SLIP)
                pnl = (exit_p / entry - 1) - FEE * 2
                cash = cash * (1 + pnl)
                trades.append(dict(side=1, entry=entry, exit=exit_p, ret=pnl, reason="SL",
                                   bars_held=i - entry_idx, t_exit=df.index[i]))
                pos = 0
            elif hi[i] >= tp:
                exit_p = tp * (1 - SLIP)
                pnl = (exit_p / entry - 1) - FEE * 2
                cash = cash * (1 + pnl)
                trades.append(dict(side=1, entry=entry, exit=exit_p, ret=pnl, reason="TP",
                                   bars_held=i - entry_idx, t_exit=df.index[i]))
                pos = 0
        elif pos == -1:
            if hi[i] >= sl:
                exit_p = sl * (1 + SLIP)
                pnl = (entry / exit_p - 1) - FEE * 2
                cash = cash * (1 + pnl)
                trades.append(dict(side=-1, entry=entry, exit=exit_p, ret=pnl, reason="SL",
                                   bars_held=i - entry_idx, t_exit=df.index[i]))
                pos = 0
            elif lo[i] <= tp:
                exit_p = tp * (1 + SLIP)
                pnl = (entry / exit_p - 1) - FEE * 2
                cash = cash * (1 + pnl)
                trades.append(dict(side=-1, entry=entry, exit=exit_p, ret=pnl, reason="TP",
                                   bars_held=i - entry_idx, t_exit=df.index[i]))
                pos = 0

        # --- new entries on close of bar i, executed at open of bar i+1 ---
        if pos == 0:
            if ls[i]:
                entry = op[i + 1] * (1 + SLIP)
                sl = entry * (1 - sl_pct)
                tp = entry * (1 + tp_pct)
                pos = 1
                entry_idx = i + 1
            elif ss[i]:
                entry = op[i + 1] * (1 - SLIP)
                sl = entry * (1 + sl_pct)
                tp = entry * (1 - tp_pct)
                pos = -1
                entry_idx = i + 1

        # mark-to-market equity
        if pos == 0:
            equity.append(cash)
        else:
            p_now = df["close"].iloc[i]
            unrealized = (p_now / entry - 1) if pos == 1 else (entry / p_now - 1)
            unrealized -= FEE  # account for round-trip (we'll pay the exit fee)
            equity.append(cash * (1 + unrealized))

    # Flat-close any open position at the last bar open
    eq_series = pd.Series(equity, index=df.index[:len(equity)])
    return trades, eq_series


# ---------- metrics ----------
def metrics(eq: pd.Series, trades: list[dict], df_index: pd.DatetimeIndex) -> dict:
    rets = eq.pct_change().dropna()
    if len(rets) < 2:
        return dict(cagr=0, sharpe=0, sortino=0, max_dd=0, calmar=0,
                    final=float(eq.iloc[-1]), n_trades=0)
    dt = rets.index.to_series().diff().median()
    bars_per_year = pd.Timedelta(days=365.25) / dt if dt else 1
    mu, sd = rets.mean(), rets.std()
    dn = rets[rets < 0].std()
    sharpe  = (mu / sd) * np.sqrt(bars_per_year) if sd else 0
    sortino = (mu / dn) * np.sqrt(bars_per_year) if dn else 0
    years = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(years, 1e-6)) - 1
    peak = eq.cummax()
    dd = (eq / peak - 1)
    max_dd = float(dd.min())
    calmar = cagr / abs(max_dd) if max_dd else 0

    pnl = np.array([t["ret"] for t in trades]) if trades else np.array([])
    wins = pnl[pnl > 0]; losses = pnl[pnl < 0]
    gp, gl = wins.sum(), losses.sum()
    pf_ratio = gp / abs(gl) if gl else 0
    mcw = mcl = cw = cl = 0
    for p in pnl:
        if p > 0: cw += 1; cl = 0
        elif p < 0: cl += 1; cw = 0
        mcw = max(mcw, cw); mcl = max(mcl, cl)

    return dict(
        final = float(eq.iloc[-1]),
        cagr = float(cagr),
        sharpe = float(sharpe),
        sortino = float(sortino),
        max_dd = float(max_dd),
        calmar = float(calmar),
        n_trades = len(trades),
        n_wins = int((pnl > 0).sum()),
        n_losses = int((pnl < 0).sum()),
        win_rate = float((pnl > 0).mean()) if len(pnl) else 0,
        profit_factor = float(pf_ratio),
        avg_win_pct = float(wins.mean()) if len(wins) else 0,
        avg_loss_pct = float(losses.mean()) if len(losses) else 0,
        largest_win_pct = float(wins.max()) if len(wins) else 0,
        largest_loss_pct = float(losses.min()) if len(losses) else 0,
        max_cw = int(mcw), max_cl = int(mcl),
    )


# ---------- main ----------
def main():
    rows = []
    t0 = time.time()
    for tf in TFS:
        for sym in SYMS:
            t = time.time()
            df = load(sym, tf)
            trades, eq = simulate(df)
            m = metrics(eq, trades, df.index)
            bh = float(df["close"].iloc[-1] / df["close"].iloc[0] - 1)
            rows.append({
                "symbol": sym, "tf": tf, "bars": len(df), **m,
                "bh_return": round(bh, 4),
            })
            for k, v in rows[-1].items():
                if isinstance(v, float):
                    rows[-1][k] = round(v, 4)
            print(f"  {sym}/{tf:<3s}  trades={m['n_trades']:<5d}  "
                  f"CAGR={m['cagr']*100:+7.2f}%  Sharpe={m['sharpe']:>5.2f}  "
                  f"DD={m['max_dd']*100:+7.2f}%  PF={m['profit_factor']:.2f}  "
                  f"Win%={m['win_rate']*100:>5.1f}  BH={bh*100:+.0f}%  "
                  f"({time.time()-t:.1f}s)", flush=True)

    df = pd.DataFrame(rows)
    out_csv = OUT / "V6_meanrev_direct.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nSaved {out_csv}  total {time.time()-t0:.1f}s")
    print("\nTOP by Calmar:")
    print(df.sort_values("calmar", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
