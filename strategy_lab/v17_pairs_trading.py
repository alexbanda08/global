"""
V17 — Pairs-trading (statistical arbitrage) strategies.

Idea: highly-correlated coin pairs can be traded when their log-price spread
stretches N sigmas away from its rolling mean.  We test several pairs of
large-cap crypto assets that historically co-move.

Pair model (long-side only — Hyperliquid portfolio is currently long-only,
but we can hedge by going long one leg and passing the other — we model this
as a LONG ONLY on the cheap leg and EXIT when spread mean-reverts):

  spread_t = log(p_a_t) - beta * log(p_b_t)
  z_t     = (spread_t - rolling_mean(N)) / rolling_std(N)

  Entry (LONG leg A):  z_t < -entry_threshold  (A is cheap vs B)
  Exit (close A):      z_t > 0  (spread has mean-reverted)
  Stop (kill):         z_t < -stop_threshold  (spread blew out)

We test:
  ETH/BTC, SOL/ETH, AVAX/SOL, BNB/BTC, ADA/ETH, LINK/ETH, DOGE/BTC
  (in both directions — "long A when A is cheap vs B" for each pair)

All 4h bars, Hyperliquid maker fees 0.015 %, no slippage.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

from strategy_lab import portfolio_audit as pa

COINS = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT",
         "LINKUSDT","ADAUSDT","XRPUSDT","AVAXUSDT","DOGEUSDT"]
STARTS = {
    "BTCUSDT":"2018-01-01","ETHUSDT":"2018-01-01","BNBUSDT":"2018-01-01",
    "XRPUSDT":"2018-06-01","ADAUSDT":"2018-06-01",
    "LINKUSDT":"2019-03-01","DOGEUSDT":"2019-09-01",
    "SOLUSDT":"2020-10-01","AVAXUSDT":"2020-11-01",
}
END = "2026-04-01"
INIT = 10_000.0
FEE = 0.00015
OUT = Path(__file__).resolve().parent / "results"

PAIRS = [
    ("ETHUSDT",  "BTCUSDT"),
    ("SOLUSDT",  "ETHUSDT"),
    ("AVAXUSDT", "SOLUSDT"),
    ("BNBUSDT",  "BTCUSDT"),
    ("ADAUSDT",  "ETHUSDT"),
    ("LINKUSDT", "ETHUSDT"),
    ("DOGEUSDT", "BTCUSDT"),
    ("XRPUSDT",  "BTCUSDT"),
]


def pairs_backtest(a: str, b: str,
                   z_entry: float = -1.5,
                   z_exit: float = 0.0,
                   z_stop: float = -3.5,
                   window_bars: int = 168,   # 28 days × 6 bars
                   beta_window_bars: int = 336   # 56d rolling OLS slope
                   ) -> tuple[pd.Series, list[dict]]:
    start = max(pd.Timestamp(STARTS[a], tz="UTC"), pd.Timestamp(STARTS[b], tz="UTC"))
    df_a = pa.load_ohlcv(a, start.strftime("%Y-%m-%d"), END)
    df_b = pa.load_ohlcv(b, start.strftime("%Y-%m-%d"), END)

    idx = df_a.index.intersection(df_b.index)
    pa_arr = df_a.loc[idx, "close"].values
    pb_arr = df_b.loc[idx, "close"].values
    op_a   = df_a.loc[idx, "open"].values
    lo_a   = df_a.loc[idx, "low"].values
    hi_a   = df_a.loc[idx, "high"].values
    cl_a   = df_a.loc[idx, "close"].values

    la = np.log(pa_arr); lb_arr = np.log(pb_arr)

    # Rolling beta (OLS) on log prices
    la_s = pd.Series(la); lb_s = pd.Series(lb_arr)
    cov = la_s.rolling(beta_window_bars).cov(lb_s)
    var = lb_s.rolling(beta_window_bars).var()
    beta = (cov / var).replace([np.inf, -np.inf], np.nan).fillna(1.0).values

    spread = la - beta * lb_arr
    spread_s = pd.Series(spread)
    sp_mean = spread_s.rolling(window_bars).mean().values
    sp_std  = spread_s.rolling(window_bars).std().values
    z = (spread - sp_mean) / (sp_std + 1e-12)

    # Simulate long-A, flat otherwise
    n = len(idx)
    cash = INIT
    equity = np.empty(n); equity[0] = cash
    pos = 0.0
    entry_p = 0.0
    entry_i = -1
    trades = []

    for i in range(n):
        if pos > 0:
            # Exit on mean-revert
            if z[i] > z_exit or z[i] < z_stop:
                px = op_a[min(i+1, n-1)]
                gross = pos * px
                cash += gross - abs(gross) * FEE
                ret = px / entry_p - 1 - 2 * FEE
                reason = "EXIT" if z[i] > z_exit else "STOP"
                trades.append({"entry_time": idx[entry_i], "exit_time": idx[min(i+1, n-1)],
                               "entry_price": entry_p, "exit_price": px,
                               "return": ret, "bars_held": i - entry_i,
                               "reason": reason, "z_entry": z[entry_i], "z_exit": z[i]})
                pos = 0.0; entry_p = 0.0; entry_i = -1

        if pos == 0 and i >= max(window_bars, beta_window_bars) and i < n - 1:
            if z[i] < z_entry and not np.isnan(z[i]):
                px = op_a[i+1]
                size = cash / px
                cost = size * px
                fee = cost * FEE
                cash -= cost + fee
                pos = size
                entry_p = px
                entry_i = i + 1

        equity[i] = cash + pos * cl_a[i]

    if pos > 0:
        px = cl_a[-1]
        gross = pos * px
        cash += gross - abs(gross) * FEE
        trades.append({"entry_time": idx[entry_i], "exit_time": idx[-1],
                       "entry_price": entry_p, "exit_price": px,
                       "return": px / entry_p - 1 - 2 * FEE,
                       "bars_held": n - 1 - entry_i, "reason": "EOD",
                       "z_entry": z[entry_i], "z_exit": z[-1]})
        equity[-1] = cash

    eq = pd.Series(equity, index=idx, name="equity")
    return eq, trades


def mx(eq: pd.Series, trades: list) -> dict:
    if len(eq) < 20: return {}
    rets = eq.pct_change(fill_method=None).fillna(0)
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 0.01)) - 1
    bpy = pa.BARS_PER_YR
    sh = (rets.mean() * bpy) / (rets.std() * np.sqrt(bpy) + 1e-12)
    dd = float((eq / eq.cummax() - 1).min())
    tr = pd.DataFrame(trades) if trades else pd.DataFrame()
    wr = float((tr["return"] > 0).mean()) if len(tr) else 0
    pf = 0
    if len(tr):
        gw = tr.loc[tr["return"] > 0, "return"].sum()
        gl = abs(tr.loc[tr["return"] <= 0, "return"].sum())
        pf = round(float(gw/gl), 3) if gl > 0 else 0
    return {"cagr": round(float(cagr), 4), "sharpe": round(float(sh), 3),
            "dd": round(dd, 4), "calmar": round(cagr/abs(dd) if dd < 0 else 0, 3),
            "n_trades": len(tr), "wr": round(wr, 3), "pf": pf,
            "final": round(float(eq.iloc[-1]), 0)}


def main():
    rows = []
    for a, b in PAIRS:
        # Sweep a few entry-thresholds
        for z_entry, z_exit in [(-1.5, 0.0), (-2.0, 0.0), (-2.5, 0.0),
                                 (-1.5, -0.5), (-2.0, 0.5)]:
            try:
                eq, tr = pairs_backtest(a, b, z_entry=z_entry, z_exit=z_exit)
            except Exception as e:
                print(f"  {a}/{b} z={z_entry}: {e}"); continue
            m = mx(eq, tr)
            row = {"pair": f"{a}/{b}", "z_entry": z_entry, "z_exit": z_exit, **m}
            rows.append(row)
            print(f"  {a:<9}/{b:<9}  z_in={z_entry:+.1f}  z_out={z_exit:+.1f}  "
                  f"n={m.get('n_trades',0):3d}  wr={m.get('wr',0)*100:4.1f}%  "
                  f"pf={m.get('pf',0):.2f}  sharpe={m.get('sharpe',0):+.2f}  "
                  f"cagr={m.get('cagr',0)*100:+5.1f}%  dd={m.get('dd',0)*100:+5.1f}%  "
                  f"final=${m.get('final',0):,.0f}", flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "v17_pairs.csv", index=False)

    print("\n=== TOP 10 BY SHARPE (profitable only) ===")
    good = df[(df["final"] > INIT) & (df["n_trades"] >= 5)]
    if len(good):
        print(good.sort_values("sharpe", ascending=False).head(10).to_string(index=False))


if __name__ == "__main__":
    main()
