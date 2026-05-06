"""Naive backtest of the Crypto Derivatives Z-Score indicator.

Implements the entry/exit logic from the Pine spec (sections 6.1–6.3) on hourly bars.
Long-short, no leverage, 1 unit position. Costs: 5bp per side (taker on Binance perp).

Inputs:
  data/v4/derivatives_zscore/panels/{symbol}_zscore.parquet  (5-min)
  data/v4/derivatives_zscore/spot/BINANCE-BTC-1h.parquet     (BTC only, for now)

Output:
  strategy_lab/reports/derivatives_zscore/{symbol}_backtest.parquet  (per-bar log)
  printed: trade list + summary stats

NOTE: Liquidations component (15 of 100 score points) is dropped — uses score_bull_scaled
      / score_bear_scaled which rescale to 0..100 from the available 85-point max.
"""
from __future__ import annotations
from pathlib import Path
import argparse
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PANELS = ROOT / "data" / "v4" / "derivatives_zscore" / "panels"
SPOT = ROOT / "data" / "v4" / "derivatives_zscore" / "spot"
REPORTS = ROOT / "strategy_lab" / "reports" / "derivatives_zscore"
REPORTS.mkdir(parents=True, exist_ok=True)

FEE_BPS = 5.0  # 5 basis points per side (taker, generous)


# ────────────────────────────────────────────────────────────
#  Entry / exit per Pine spec §6
# ────────────────────────────────────────────────────────────

def signal_long(row) -> bool:
    """6.1 ENTRADA PRIMÁRIA — Sinal Forte (LONG)."""
    return (
        row["score_bull_scaled"] >= 70
        and row["cross_institutional_lead"] > 0
        and row["z_oi"] > 0
        # brigaliqui filter dropped (no liquidation data)
        and row["spot_above_ema21"]
    )


def signal_short(row) -> bool:
    """6.2 ENTRADA PRIMÁRIA — Sinal Forte (SHORT)."""
    return (
        row["score_bear_scaled"] >= 70
        and row["cross_leverage_heat"] > 1.5
        and row["z_dom_stables"] > 1.0
        and row["spot_below_ema21"]
    )


def should_close_long(row) -> bool:
    """6.3 SAÍDA LONG."""
    return (
        row["score_bull_scaled"] < 35
        or row["score_bear_scaled"] > 60
        or row["z_fund"] > 2.5
        or row["z_lsr"] > 2.5
    )


def should_close_short(row) -> bool:
    """6.3 SAÍDA SHORT."""
    return (
        row["score_bear_scaled"] < 35
        or row["score_bull_scaled"] > 60
        or row["z_fund"] < -2.5
        # brigaliqui exit dropped
    )


# ────────────────────────────────────────────────────────────
#  Run
# ────────────────────────────────────────────────────────────

def load_aligned(symbol: str) -> pd.DataFrame:
    p = pd.read_parquet(PANELS / f"{symbol}_zscore.parquet")
    # Resample 5min -> 1h (last value at hour close); ffill cross/regime cols
    p_h = p.resample("1h").last()

    if symbol == "BTCUSDT":
        spot = pd.read_parquet(SPOT / "BINANCE-BTC-1h.parquet").set_index("time")["close"].astype(float)
    else:
        # fall back to indicator's own spot_price (mark price proxy from OI value)
        spot = p["spot_price"].resample("1h").last()

    df = p_h.copy()
    df["price"] = spot.reindex(df.index, method="ffill")
    df["ema21"] = df["price"].ewm(span=21, adjust=False).mean()
    df["spot_above_ema21"] = df["price"] > df["ema21"]
    df["spot_below_ema21"] = df["price"] < df["ema21"]
    return df.dropna(subset=["price", "score_bull_scaled", "score_bear_scaled"])


def backtest(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Single position at a time, long or short. Returns (per-bar log, trade list)."""
    pos = 0  # +1 long, -1 short, 0 flat
    entry_px = None
    entry_t = None
    cash = 1.0       # account value (compounded)
    equity = []
    trades: list[dict] = []
    fee = FEE_BPS / 1e4

    for ts, r in df.iterrows():
        px = r["price"]

        # mark-to-market on existing position before potential exit
        if pos == 1:
            mark_eq = cash * (px / entry_px)
        elif pos == -1:
            mark_eq = cash * (entry_px / px) * (entry_px / entry_px)  # 1 + (entry-exit)/entry
            mark_eq = cash * (1 + (entry_px - px) / entry_px)
        else:
            mark_eq = cash

        # Exits
        if pos == 1 and should_close_long(r):
            ret = (px / entry_px) - 1 - 2 * fee
            cash = cash * (1 + ret)
            trades.append(dict(entry_t=entry_t, exit_t=ts, side="long",
                               entry_px=entry_px, exit_px=px, ret=ret, hours=(ts - entry_t).total_seconds()/3600))
            pos = 0
            entry_px = None
        elif pos == -1 and should_close_short(r):
            ret = (entry_px / px) - 1 - 2 * fee
            cash = cash * (1 + ret)
            trades.append(dict(entry_t=entry_t, exit_t=ts, side="short",
                               entry_px=entry_px, exit_px=px, ret=ret, hours=(ts - entry_t).total_seconds()/3600))
            pos = 0
            entry_px = None

        # Entries (only if flat)
        if pos == 0:
            if signal_long(r):
                pos = 1; entry_px = px; entry_t = ts
            elif signal_short(r):
                pos = -1; entry_px = px; entry_t = ts

        equity.append((ts, cash, mark_eq, pos, px))

    eq_df = pd.DataFrame(equity, columns=["time", "cash", "mark_eq", "pos", "price"]).set_index("time")
    return eq_df, trades


def stats(trades: list[dict], eq: pd.DataFrame, df: pd.DataFrame) -> dict:
    if not trades:
        return {"n_trades": 0, "n_long": 0, "n_short": 0,
                "win_rate": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
                "expectancy": 0.0, "median_hold_h": 0.0, "profit_factor": 0.0,
                "final_equity_x": 1.0, "buy_hold_x": float(df["price"].iloc[-1] / df["price"].iloc[0]),
                "sharpe": 0.0, "max_dd": 0.0}
    rets = np.array([t["ret"] for t in trades])
    wins = rets > 0
    bh_ret = df["price"].iloc[-1] / df["price"].iloc[0] - 1
    final_eq = eq["cash"].iloc[-1]
    # daily equity for sharpe
    daily = eq["mark_eq"].resample("1D").last().dropna()
    daily_ret = daily.pct_change().dropna()
    sharpe = daily_ret.mean() / daily_ret.std() * np.sqrt(365) if daily_ret.std() > 0 else 0
    # max DD
    peak = eq["mark_eq"].cummax()
    dd = (eq["mark_eq"] - peak) / peak
    return {
        "n_trades": len(trades),
        "n_long": sum(1 for t in trades if t["side"] == "long"),
        "n_short": sum(1 for t in trades if t["side"] == "short"),
        "win_rate": float(wins.mean()),
        "avg_win": float(rets[wins].mean()) if wins.any() else 0,
        "avg_loss": float(rets[~wins].mean()) if (~wins).any() else 0,
        "expectancy": float(rets.mean()),
        "median_hold_h": float(np.median([t["hours"] for t in trades])),
        "profit_factor": float(rets[wins].sum() / -rets[~wins].sum()) if (~wins).any() else float("inf"),
        "final_equity_x": float(final_eq),
        "buy_hold_x": float(1 + bh_ret),
        "sharpe": float(sharpe),
        "max_dd": float(dd.min()),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    args = ap.parse_args()

    summary = []
    for sym in args.symbols:
        print(f"\n══════════ {sym} ══════════")
        df = load_aligned(sym)
        print(f"  bars: {len(df):,}  range {df.index.min()} → {df.index.max()}")
        eq, trades = backtest(df)
        s = stats(trades, eq, df)
        s["symbol"] = sym
        summary.append(s)

        eq.to_parquet(REPORTS / f"{sym}_equity.parquet")
        if trades:
            pd.DataFrame(trades).to_parquet(REPORTS / f"{sym}_trades.parquet")

        print(f"  trades: {s['n_trades']}  ({s['n_long']} long / {s['n_short']} short)")
        if s.get("n_trades"):
            print(f"  win rate     : {s['win_rate']:6.1%}")
            print(f"  expectancy   : {s['expectancy']:+.4%}")
            print(f"  profit factor: {s['profit_factor']:.2f}")
            print(f"  median hold  : {s['median_hold_h']:.1f}h")
            print(f"  final equity : {s['final_equity_x']:.3f}×    (buy-hold: {s['buy_hold_x']:.3f}×)")
            print(f"  sharpe (ann) : {s['sharpe']:+.2f}")
            print(f"  max drawdown : {s['max_dd']:.1%}")

    print("\n══════════ SUMMARY ══════════")
    sm = pd.DataFrame(summary)
    if not sm.empty:
        print(sm.to_string(index=False))
        sm.to_parquet(REPORTS / "summary.parquet")


if __name__ == "__main__":
    main()
