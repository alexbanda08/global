"""
V10 "FadeTheCrowd" — mean-reversion 15m strategy grounded in measured alpha.

Signal summary (IC-backed, all features):
  PRIMARY:  fade recent drops  (ret_4 < -threshold)  —  IC -0.056
  CONFIRM:  liquidation pulse  (liq_notional_z_7d > threshold)
  GATE:     bull regime (close > daily EMA200 AND slope positive)
  SELECTIVE: selling pressure easing (taker_ratio_z_7d < 0)

Exits: ATR-scaled (1.5x target / 1.0x stop), max hold 16 bars (4 h).
Costs: 0.04% per side + 5 bps slippage (Binance futures taker OR Hyperliquid
       low-tier; roughly 0.085% round-trip).
"""
from __future__ import annotations
import time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
FEAT = ROOT / "strategy_lab" / "features"
OUT  = ROOT / "strategy_lab" / "results"

FEE  = 0.00015    # Hyperliquid maker-weighted (70% maker 30% taker ~= 0.024%/side)
SLIP = 0.0003
INIT = 10_000.0


def simulate(df: pd.DataFrame,
             ret_drop_thr: float = -0.005,     # 0.5% drop in 1h
             use_liq_gate: bool = False,       # disabled — too restrictive
             liq_z_thr: float = -99.0,
             use_taker_gate: bool = False,
             taker_z_thr: float = 99.0,
             tp_atr: float = 1.0,    # tighter — 1:1 R:R
             sl_atr: float = 1.0,
             max_hold: int = 8,      # shorter hold (2h)
             lockout: int = 4,
             size_frac: float = 0.25) -> tuple[list, pd.Series]:

    # Required for basic signal
    req = ["ret_4", "atr_14", "regime_bull", "open", "high", "low", "close"]
    if use_liq_gate:    req.append("liq_notional_z_7d")
    if use_taker_gate:  req.append("taker_ratio_z_7d")
    df = df.dropna(subset=req).copy()

    bull = df["regime_bull"].values == 1
    drop_ok   = df["ret_4"].values < ret_drop_thr
    liq_ok    = (df["liq_notional_z_7d"].values > liq_z_thr) if use_liq_gate else np.ones(len(df), dtype=bool)
    taker_ok  = (df["taker_ratio_z_7d"].values < taker_z_thr) if use_taker_gate else np.ones(len(df), dtype=bool)
    entry_sig = bull & drop_ok & liq_ok & taker_ok

    op, hi, lo, cl = (df["open"].values, df["high"].values,
                      df["low"].values,  df["close"].values)
    at = df["atr_14"].values

    N = len(df)
    cash = INIT
    equity = np.empty(N); equity[0] = cash
    pos = 0
    entry_p = sl = tp = 0.0
    size = 0.0
    entry_idx = 0
    last_exit = -9999
    trades = []

    for i in range(1, N - 1):
        if pos == 1:
            held = i - entry_idx
            exited = False
            # SL first
            if lo[i] <= sl:
                exit_p = sl * (1 - SLIP)
                ret = (exit_p / entry_p - 1) - 2 * FEE
                cash = cash + size * (exit_p - entry_p) - size * (entry_p + exit_p) * FEE
                trades.append(dict(entry=entry_p, exit=exit_p, ret=ret,
                                   reason="SL", bars=held))
                exited = True
            elif hi[i] >= tp:
                exit_p = tp * (1 - SLIP)
                ret = (exit_p / entry_p - 1) - 2 * FEE
                cash = cash + size * (exit_p - entry_p) - size * (entry_p + exit_p) * FEE
                trades.append(dict(entry=entry_p, exit=exit_p, ret=ret,
                                   reason="TP", bars=held))
                exited = True
            elif held >= max_hold:
                exit_p = cl[i] * (1 - SLIP)
                ret = (exit_p / entry_p - 1) - 2 * FEE
                cash = cash + size * (exit_p - entry_p) - size * (entry_p + exit_p) * FEE
                trades.append(dict(entry=entry_p, exit=exit_p, ret=ret,
                                   reason="TIME", bars=held))
                exited = True
            if exited:
                pos = 0; last_exit = i
                equity[i] = cash
                continue

        if pos == 0 and (i - last_exit) > lockout and entry_sig[i]:
            entry_p = op[i + 1] * (1 + SLIP)
            sl = entry_p - sl_atr * at[i]
            tp = entry_p + tp_atr * at[i]
            if sl > 0:
                size = (cash * size_frac) / entry_p
                pos = 1
                entry_idx = i + 1

        # mark to market
        if pos == 0:
            equity[i] = cash
        else:
            unreal = size * (cl[i] - entry_p) - size * entry_p * FEE
            equity[i] = cash + unreal
    equity[-1] = equity[-2]
    eq = pd.Series(equity, index=df.index)
    return trades, eq


def report(eq: pd.Series, trades: list, label: str):
    EMPTY = dict(label=label, final=float(eq.iloc[-1]) if len(eq) else 0,
                 cagr=0, sharpe=0, max_dd=0, calmar=0, n_trades=0,
                 win_rate=0, profit_factor=0, avg_win_pct=0, avg_loss_pct=0,
                 sl_exits=0, tp_exits=0, time_exits=0)
    rets = eq.pct_change().dropna()
    if len(rets) < 2 or len(trades) == 0:
        return EMPTY
    dt = rets.index.to_series().diff().median()
    bpy = pd.Timedelta(days=365.25) / dt if dt else 1
    mu, sd = rets.mean(), rets.std()
    sharpe = (mu / sd) * np.sqrt(bpy) if sd else 0
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 1e-6)) - 1
    dd = float((eq / eq.cummax() - 1).min())
    pnl = np.array([t["ret"] for t in trades])
    wins = pnl[pnl > 0]; losses = pnl[pnl < 0]
    pf = float(wins.sum() / abs(losses.sum())) if len(losses) else 0
    out = dict(
        label=label,
        final=float(eq.iloc[-1]),
        cagr=float(cagr),
        sharpe=float(sharpe),
        max_dd=dd,
        calmar=float(cagr / abs(dd)) if dd else 0,
        n_trades=len(trades),
        win_rate=float((pnl > 0).mean()),
        profit_factor=pf,
        avg_win_pct=float(wins.mean()) if len(wins) else 0,
        avg_loss_pct=float(losses.mean()) if len(losses) else 0,
        sl_exits=sum(1 for t in trades if t["reason"] == "SL"),
        tp_exits=sum(1 for t in trades if t["reason"] == "TP"),
        time_exits=sum(1 for t in trades if t["reason"] == "TIME"),
    )
    return out


def main():
    rows = []
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        t0 = time.time()
        df = pd.read_parquet(FEAT / f"{sym}_15m_features.parquet")

        # Full period
        tr, eq = simulate(df)
        r = report(eq, tr, f"{sym}_full")
        r["symbol"] = sym; r["slice"] = "FULL"
        rows.append(r)

        # Walk-forward IS/OOS split at 2024-01-01
        cut = pd.Timestamp("2024-01-01", tz="UTC")
        tr_is, eq_is = simulate(df[df.index < cut])
        tr_oos, eq_oos = simulate(df[df.index >= cut])
        r_is  = report(eq_is,  tr_is,  f"{sym}_IS")
        r_oos = report(eq_oos, tr_oos, f"{sym}_OOS")
        r_is["symbol"] = sym;  r_is["slice"]  = "IS"
        r_oos["symbol"] = sym; r_oos["slice"] = "OOS"
        rows.extend([r_is, r_oos])

        print(f"{sym}  full: n={r['n_trades']}  Win%={r['win_rate']*100:.1f}  "
              f"CAGR={r['cagr']*100:+.1f}%  Sharpe={r['sharpe']:.2f}  "
              f"DD={r['max_dd']*100:+.1f}%  PF={r['profit_factor']:.2f}  "
              f"(SL={r['sl_exits']}, TP={r['tp_exits']}, TIME={r['time_exits']})  "
              f"({time.time()-t0:.1f}s)", flush=True)

        # Save equity curve
        eq.to_csv(OUT / f"V10_{sym}_equity.csv")

    df = pd.DataFrame(rows)[["symbol","slice","n_trades","win_rate","profit_factor",
                              "avg_win_pct","avg_loss_pct","cagr","sharpe","max_dd",
                              "calmar","final","sl_exits","tp_exits","time_exits"]]
    for c in ["win_rate","profit_factor","avg_win_pct","avg_loss_pct","cagr","sharpe","max_dd","calmar"]:
        df[c] = df[c].round(4)
    df.to_csv(OUT / "V10_fade_results.csv", index=False)
    print("\n=== V10 RESULTS ===")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
