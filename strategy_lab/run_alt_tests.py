"""
4 alternative alpha tests on 15m — testing genuinely different hypotheses
before declaring 15m dead for rule-based.

Test 1 — Cross-asset BTC/ETH spread mean reversion
         When BTC/ETH ratio deviates N stddev from rolling mean, fade it.
Test 2 — Funding-rate extreme fade
         When funding_rate_z < -2 (shorts crowded, paying) → LONG (squeeze coming)
         When funding_rate_z > +2 (longs crowded, paying) → SHORT (flush coming)
Test 3 — Session / time-of-day return distribution
         Bucket 15m bars by UTC hour, measure mean return per bucket.
Test 4 — Volatility-regime switching
         Compute realized vol percentile over 24h.
         High-vol regime → momentum (breakout follow-through)
         Low-vol regime → mean reversion

Each test runs on BTC/ETH/SOL, 2023-01 → 2026-04, Hyperliquid fees (0.03% rt).
Reports: Sharpe, CAGR, n_trades, win_rate, max_dd.
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
FEAT = ROOT / "strategy_lab" / "features"
OUT  = ROOT / "strategy_lab" / "results"

FEE  = 0.00015
SLIP = 0.0003
INIT = 10_000.0


def simulate_signal(df: pd.DataFrame, entries: pd.Series, exits: pd.Series,
                    direction: int = 1, tp_atr: float = 1.0, sl_atr: float = 1.0,
                    max_hold: int = 16, size_frac: float = 0.25) -> tuple[list, pd.Series]:
    """Execute long (direction=1) or short (-1) signals with ATR barriers."""
    df = df.copy()
    op, hi, lo, cl = df["open"].values, df["high"].values, df["low"].values, df["close"].values
    at = df["atr_14"].values
    e_sig = entries.values.astype(bool)
    N = len(df)
    cash = INIT
    equity = np.empty(N); equity[0] = cash
    pos = 0; entry_p = sl = tp = 0.0; size = 0.0; entry_idx = 0
    last_exit = -9999
    trades = []

    for i in range(1, N - 1):
        if pos != 0:
            held = i - entry_idx
            hit_sl = (lo[i] <= sl) if pos == 1 else (hi[i] >= sl)
            hit_tp = (hi[i] >= tp) if pos == 1 else (lo[i] <= tp)
            exited = False
            if hit_sl:
                exit_p = sl * (1 - SLIP * pos)
                raw = (exit_p - entry_p) * pos
                cash += size * raw - size * (entry_p + exit_p) * FEE
                trades.append(dict(ret=raw/entry_p - 2*FEE, reason="SL", side=pos, bars=held))
                exited = True
            elif hit_tp:
                exit_p = tp * (1 - SLIP * pos)
                raw = (exit_p - entry_p) * pos
                cash += size * raw - size * (entry_p + exit_p) * FEE
                trades.append(dict(ret=raw/entry_p - 2*FEE, reason="TP", side=pos, bars=held))
                exited = True
            elif held >= max_hold:
                exit_p = cl[i]
                raw = (exit_p - entry_p) * pos
                cash += size * raw - size * (entry_p + exit_p) * FEE
                trades.append(dict(ret=raw/entry_p - 2*FEE, reason="TIME", side=pos, bars=held))
                exited = True
            if exited:
                pos = 0; last_exit = i
                equity[i] = cash; continue

        if pos == 0 and (i - last_exit) > 4 and e_sig[i]:
            entry_p = op[i+1] * (1 + SLIP * direction)
            sl = entry_p - sl_atr * at[i] * direction
            tp = entry_p + tp_atr * at[i] * direction
            if np.isfinite(sl) and np.isfinite(tp) and entry_p > 0:
                size = (cash * size_frac) / entry_p
                pos = direction
                entry_idx = i + 1

        if pos == 0: equity[i] = cash
        else:
            unreal = size * (cl[i] - entry_p) * pos - size * entry_p * FEE
            equity[i] = cash + unreal
    equity[-1] = equity[-2]
    return trades, pd.Series(equity, index=df.index)


def summarize(label: str, eq: pd.Series, trades: list) -> dict:
    if len(trades) < 5:
        return dict(test=label, n=len(trades), final=float(eq.iloc[-1]),
                    cagr=0, sharpe=0, dd=0, win=0, pf=0)
    rets = eq.pct_change().dropna()
    dt = rets.index.to_series().diff().median()
    bpy = pd.Timedelta(days=365.25) / dt if dt else 1
    sh = rets.mean() / rets.std() * np.sqrt(bpy) if rets.std() > 0 else 0
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25*86400)
    cagr = (eq.iloc[-1]/eq.iloc[0])**(1/max(yrs,1e-6)) - 1
    dd = float((eq/eq.cummax()-1).min())
    pnl = np.array([t["ret"] for t in trades])
    pf_r = pnl[pnl>0].sum() / abs(pnl[pnl<0].sum()) if (pnl<0).any() else 0
    return dict(test=label, n=len(trades), final=float(eq.iloc[-1]),
                cagr=round(cagr,4), sharpe=round(sh,3), dd=round(dd,4),
                win=round((pnl>0).mean(),3), pf=round(pf_r,3))


# ------------- TEST 1: BTC/ETH spread mean reversion -------------
def test_cross_asset():
    """Z-score of BTC/ETH ratio, fade extreme deviations on BTC."""
    print("\n--- TEST 1: BTC/ETH spread mean reversion ---")
    btc = pd.read_parquet(FEAT / "BTCUSDT_15m_features.parquet")
    eth = pd.read_parquet(FEAT / "ETHUSDT_15m_features.parquet")
    idx = btc.index.intersection(eth.index)
    btc = btc.loc[idx]; eth = eth.loc[idx]
    ratio = btc["close"] / eth["close"]
    r_mean = ratio.rolling(672).mean()        # 7d
    r_std  = ratio.rolling(672).std()
    z = (ratio - r_mean) / r_std
    rows = []
    for sym, df in [("BTCUSDT", btc), ("ETHUSDT", eth)]:
        # When z is very positive → BTC rich vs ETH → short BTC / long ETH
        # Simpler single-leg test: short BTC when z > +2 (BTC rich), long BTC when z < -2 (BTC cheap)
        for direction, thr in [(1, -2.0), (-1, +2.0)]:
            # Apply direction to sym: BTC goes direction, ETH goes -direction
            if sym == "BTCUSDT":
                entries = (z < thr) if direction == 1 else (z > thr)
            else:
                entries = (z > -thr) if direction == 1 else (z < -thr)
            trades, eq = simulate_signal(df, entries, pd.Series(False, index=df.index),
                                         direction=direction)
            tag = f"{sym}_dir={direction}_thr={thr}"
            r = summarize(tag, eq, trades)
            rows.append(r)
            print(f"  {tag:32s} n={r['n']:4d}  CAGR={r['cagr']*100:+7.2f}%  Sh={r['sharpe']:5.2f}  DD={r['dd']*100:+6.1f}%  Win%={r['win']*100:4.1f}  PF={r['pf']:.2f}")
    return rows


# ------------- TEST 2: Funding-rate extreme fade -------------
def test_funding_fade():
    """Fade crowded positioning when funding_rate_z hits extreme."""
    print("\n--- TEST 2: Funding-rate extreme fade ---")
    rows = []
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        df = pd.read_parquet(FEAT / f"{sym}_15m_features.parquet")
        df = df.dropna(subset=["funding_rate_z_30d","atr_14","open","high","low","close"])
        for thr, direction in [(-2.0, 1), (2.0, -1)]:   # crowded shorts → long, crowded longs → short
            entries = (df["funding_rate_z_30d"] < thr) if direction == 1 else (df["funding_rate_z_30d"] > thr)
            # Fire once at threshold cross, not continuously
            entries = entries & (~entries.shift(1).fillna(False))
            trades, eq = simulate_signal(df, entries, pd.Series(False, index=df.index), direction=direction)
            tag = f"{sym}_funding_{'long' if direction==1 else 'short'}_z{thr}"
            r = summarize(tag, eq, trades)
            rows.append(r)
            print(f"  {tag:36s} n={r['n']:4d}  CAGR={r['cagr']*100:+7.2f}%  Sh={r['sharpe']:5.2f}  DD={r['dd']*100:+6.1f}%  Win%={r['win']*100:4.1f}  PF={r['pf']:.2f}")
    return rows


# ------------- TEST 3: Time-of-day / session -------------
def test_time_of_day():
    """Bucket by UTC hour. Find hours with persistent directional drift."""
    print("\n--- TEST 3: Time-of-day return distribution ---")
    rows = []
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        df = pd.read_parquet(FEAT / f"{sym}_15m_features.parquet")
        df = df.dropna(subset=["target_ret_1"])
        df = df[df.index.year >= 2023]
        df["hour"] = df.index.hour
        mean_by_h = df.groupby("hour")["target_ret_1"].agg(["mean","count","std"])
        mean_by_h["t_stat"] = mean_by_h["mean"] / (mean_by_h["std"] / np.sqrt(mean_by_h["count"]))
        best_hour = mean_by_h["mean"].idxmax()
        worst_hour = mean_by_h["mean"].idxmin()
        print(f"  {sym}: best hour UTC={best_hour:2d} mean={mean_by_h.loc[best_hour,'mean']*100:+.4f}%  "
              f"worst hour UTC={worst_hour:2d} mean={mean_by_h.loc[worst_hour,'mean']*100:+.4f}%  "
              f"best t-stat={mean_by_h['t_stat'].max():.2f}")
        # Simulate trading only in the top-3 and bottom-3 hours
        top3 = mean_by_h["mean"].nlargest(3).index.tolist()
        bot3 = mean_by_h["mean"].nsmallest(3).index.tolist()
        # Long only during top-3 hours
        entries = df.index.hour.isin(top3)
        entries = pd.Series(entries, index=df.index)
        trades, eq = simulate_signal(df, entries, pd.Series(False, index=df.index), direction=1, max_hold=1)
        r = summarize(f"{sym}_tod_long_best3h", eq, trades)
        rows.append(r)
        print(f"   long top-3h       n={r['n']:4d}  CAGR={r['cagr']*100:+7.2f}%  Sh={r['sharpe']:5.2f}  DD={r['dd']*100:+6.1f}%  Win%={r['win']*100:4.1f}")
        # Short only during worst-3 hours
        entries2 = pd.Series(df.index.hour.isin(bot3), index=df.index)
        trades2, eq2 = simulate_signal(df, entries2, pd.Series(False, index=df.index), direction=-1, max_hold=1)
        r2 = summarize(f"{sym}_tod_short_worst3h", eq2, trades2)
        rows.append(r2)
        print(f"   short worst-3h    n={r2['n']:4d}  CAGR={r2['cagr']*100:+7.2f}%  Sh={r2['sharpe']:5.2f}  DD={r2['dd']*100:+6.1f}%  Win%={r2['win']*100:4.1f}")
    return rows


# ------------- TEST 4: Volatility regime switching -------------
def test_vol_regime():
    """High-vol: momentum (ret_4 > 0 → long).  Low-vol: mean-rev (ret_4 < -0.5% → long)."""
    print("\n--- TEST 4: Volatility regime switching ---")
    rows = []
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        df = pd.read_parquet(FEAT / f"{sym}_15m_features.parquet")
        df = df.dropna(subset=["realized_vol_24","ret_4","atr_14","regime_bull"]).copy()
        # Vol percentile
        df["vol_pct"] = df["realized_vol_24"].rolling(500).rank(pct=True)
        df = df.dropna(subset=["vol_pct"])
        bull = df["regime_bull"] == 1
        high_vol = df["vol_pct"] > 0.80
        low_vol  = df["vol_pct"] < 0.20
        # momentum in high vol: last 1h positive AND bull regime
        mom_long = bull & high_vol & (df["ret_4"] > 0.005)
        mom_long = mom_long & (~mom_long.shift(1).fillna(False))
        trades, eq = simulate_signal(df, mom_long, pd.Series(False, index=df.index), direction=1, tp_atr=1.5, sl_atr=1.0)
        r = summarize(f"{sym}_vol_momentum_high", eq, trades)
        rows.append(r)
        print(f"  {sym}_mom_highvol_long   n={r['n']:4d}  CAGR={r['cagr']*100:+7.2f}%  Sh={r['sharpe']:5.2f}  DD={r['dd']*100:+6.1f}%  Win%={r['win']*100:4.1f}  PF={r['pf']:.2f}")
        # mean-rev in low vol
        mr_long = bull & low_vol & (df["ret_4"] < -0.005)
        mr_long = mr_long & (~mr_long.shift(1).fillna(False))
        trades2, eq2 = simulate_signal(df, mr_long, pd.Series(False, index=df.index), direction=1, tp_atr=1.5, sl_atr=1.0)
        r2 = summarize(f"{sym}_vol_meanrev_low", eq2, trades2)
        rows.append(r2)
        print(f"  {sym}_rev_lowvol_long    n={r2['n']:4d}  CAGR={r2['cagr']*100:+7.2f}%  Sh={r2['sharpe']:5.2f}  DD={r2['dd']*100:+6.1f}%  Win%={r2['win']*100:4.1f}  PF={r2['pf']:.2f}")
        # combined regime-adaptive: mom in high vol + mean-rev in low vol (alternating)
        combo = mom_long | mr_long
        combo = combo & (~combo.shift(1).fillna(False))
        trades3, eq3 = simulate_signal(df, combo, pd.Series(False, index=df.index), direction=1, tp_atr=1.5, sl_atr=1.0)
        r3 = summarize(f"{sym}_vol_combined", eq3, trades3)
        rows.append(r3)
        print(f"  {sym}_combined          n={r3['n']:4d}  CAGR={r3['cagr']*100:+7.2f}%  Sh={r3['sharpe']:5.2f}  DD={r3['dd']*100:+6.1f}%  Win%={r3['win']*100:4.1f}  PF={r3['pf']:.2f}")
    return rows


def main():
    all_rows = []
    for test_fn in [test_cross_asset, test_funding_fade, test_time_of_day, test_vol_regime]:
        rows = test_fn()
        all_rows.extend(rows)
    df = pd.DataFrame(all_rows)
    df.to_csv(OUT / "alt_tests_results.csv", index=False)
    print("\n=== ALL RESULTS RANKED BY SHARPE ===")
    print(df.sort_values("sharpe", ascending=False).to_string(index=False))


if __name__ == "__main__":
    sys.exit(main() or 0)
