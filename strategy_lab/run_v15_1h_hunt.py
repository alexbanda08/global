"""
V15 — 1h strategy hunt, round 2.

Changes vs V14:
  * Fixed-fractional risk sizing: each trade risks `risk_per_trade` (default 1.5%)
    of equity at its ATR stop. This is the standard approach on perps and
    gives dramatically smoother equity curves at higher leverage.
  * Notional cap at `leverage_cap * equity` so we never oversize a tight stop.
  * Added 3 new strategies (S9-S11): Keltner+ADX, MACD-RSI, Volatility-regime
    momentum.
  * Added per-asset parameter grids rather than one grid fits all.
  * Candidate filter: CAGR_net >= 55% AND DD >= -40% AND Sharpe >= 0.9.

Hyperliquid taker (0.00045/side) + 3bps slippage. Funding drag of 8% APR per
1x long-exposure-fraction.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
import talib

ROOT = Path(__file__).resolve().parent.parent
FEAT = ROOT / "strategy_lab" / "features"
OUT = ROOT / "strategy_lab" / "results" / "v15"
OUT.mkdir(parents=True, exist_ok=True)

FEE = 0.00045
SLIP = 0.0003
INIT = 10_000.0
FUNDING_APR = 0.08


# ================================================================
# Indicators
# ================================================================
def atr(df, n=14):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    tr = np.maximum.reduce([h - l, np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))])
    return pd.Series(tr, index=df.index).ewm(alpha=1 / n, adjust=False).mean().values


def ema(x, n): return x.ewm(span=n, adjust=False).mean()


def kalman_ema(c, alpha):
    n = len(c); k = np.zeros(n); k[0] = c[0]
    for i in range(1, n):
        k[i] = k[i - 1] + alpha * (c[i] - k[i - 1])
    return k


def supertrend(df, n=10, mult=3.0):
    at = atr(df, n)
    hl2 = (df["high"].values + df["low"].values) / 2.0
    ub = hl2 + mult * at; lb = hl2 - mult * at
    close = df["close"].values
    N = len(close); trend = np.ones(N, dtype=np.int8)
    fub = np.full(N, np.nan); flb = np.full(N, np.nan)
    for i in range(1, N):
        if not np.isfinite(ub[i]): continue
        fub[i] = ub[i] if (np.isnan(fub[i - 1]) or ub[i] < fub[i - 1] or close[i - 1] > fub[i - 1]) else fub[i - 1]
        flb[i] = lb[i] if (np.isnan(flb[i - 1]) or lb[i] > flb[i - 1] or close[i - 1] < flb[i - 1]) else flb[i - 1]
        if close[i] > (fub[i - 1] if np.isfinite(fub[i - 1]) else ub[i]):
            trend[i] = 1
        elif close[i] < (flb[i - 1] if np.isfinite(flb[i - 1]) else lb[i]):
            trend[i] = -1
        else:
            trend[i] = trend[i - 1]
    return trend, fub, flb


def keltner(df, n=20, mult=2.0):
    m = ema(df["close"], n)
    at = pd.Series(atr(df, n), index=df.index)
    return m, m + mult * at, m - mult * at


def bb(c, n=120, k=2.0):
    m = c.rolling(n).mean(); s = c.rolling(n).std()
    return m, m + k * s, m - k * s


# ================================================================
# Simulator — risk-per-trade sized, leverage-capped
# ================================================================
def simulate(df, long_entries, short_entries=None,
             tp_atr=5.0, sl_atr=2.0, trail_atr=3.5, max_hold=72,
             risk_per_trade=0.015, leverage_cap=3.0):
    op = df["open"].values; hi = df["high"].values; lo = df["low"].values; cl = df["close"].values
    at = atr(df)
    sig_l = long_entries.values.astype(bool)
    sig_s = short_entries.values.astype(bool) if short_entries is not None else np.zeros(len(df), dtype=bool)

    N = len(df); cash = INIT
    eq = np.empty(N); eq[0] = cash
    pos = 0; entry_p = sl = tp = 0.0; size = 0.0; entry_idx = 0; last_exit = -9999; hh = 0.0; ll = 0.0
    trades = []

    for i in range(1, N - 1):
        if pos != 0:
            held = i - entry_idx
            if trail_atr is not None:
                if pos == 1:
                    hh = max(hh, hi[i])
                    new_sl = hh - trail_atr * at[i]
                    if new_sl > sl: sl = new_sl
                else:
                    ll = min(ll, lo[i]) if ll > 0 else lo[i]
                    new_sl = ll + trail_atr * at[i]
                    if new_sl < sl: sl = new_sl

            exited = False; ep = 0.0; reason = ""
            if pos == 1:
                if lo[i] <= sl: ep = sl * (1 - SLIP); reason = "SL"; exited = True
                elif hi[i] >= tp: ep = tp * (1 - SLIP); reason = "TP"; exited = True
                elif held >= max_hold: ep = cl[i]; reason = "TIME"; exited = True
            else:
                if hi[i] >= sl: ep = sl * (1 + SLIP); reason = "SL"; exited = True
                elif lo[i] <= tp: ep = tp * (1 + SLIP); reason = "TP"; exited = True
                elif held >= max_hold: ep = cl[i]; reason = "TIME"; exited = True

            if exited:
                pnl_per_unit = (ep - entry_p) * pos
                fee_cost = size * (entry_p + ep) * FEE
                realized = size * pnl_per_unit - fee_cost
                cash += realized
                notional = size * entry_p
                # simple % return on equity-at-entry for reporting
                equity_at_entry = cash - realized   # equity before this trade's P&L landed
                ret = realized / max(equity_at_entry, 1.0)
                trades.append({"ret": ret, "realized": realized, "notional": notional,
                               "reason": reason, "side": pos, "bars": held,
                               "entry": entry_p, "exit": ep})
                pos = 0; last_exit = i
                eq[i] = cash; continue

        if pos == 0 and (i - last_exit) > 2 and i + 1 < N:
            take_long = sig_l[i]; take_short = sig_s[i]
            if take_long or take_short:
                direction = 1 if take_long else -1
                ep = op[i + 1] * (1 + SLIP * direction)
                if np.isfinite(at[i]) and at[i] > 0 and cash > 0:
                    # risk per trade = (entry - stop) × size = sl_atr × atr × size
                    risk_dollars = cash * risk_per_trade
                    stop_dist = sl_atr * at[i]
                    size_risk = risk_dollars / stop_dist
                    # cap size by leverage
                    size_cap = (cash * leverage_cap) / ep
                    size = min(size_risk, size_cap)
                    s_stop = ep - sl_atr * at[i] * direction
                    t_stop = ep + tp_atr * at[i] * direction
                    if size > 0 and np.isfinite(s_stop) and np.isfinite(t_stop):
                        pos = direction; entry_p = ep; sl = s_stop; tp = t_stop; entry_idx = i + 1
                        hh = ep; ll = ep

        if pos == 0:
            eq[i] = cash
        else:
            unreal = size * (cl[i] - entry_p) * pos
            eq[i] = cash + unreal
    eq[-1] = eq[-2]
    return trades, pd.Series(eq, index=df.index)


def report(label, eq, trades, leverage_cap=1.0):
    if len(trades) < 5:
        return {"label": label, "leverage": leverage_cap, "n": len(trades),
                "final": float(eq.iloc[-1]), "cagr": 0, "sharpe": 0, "dd": 0,
                "win": 0, "pf": 0, "cagr_net": 0, "exposure": 0, "funding_drag": 0}
    rets = eq.pct_change().dropna()
    dt = rets.index.to_series().diff().median()
    bpy = pd.Timedelta(days=365.25) / dt if dt else 1
    sh = rets.mean() / rets.std() * np.sqrt(bpy) if rets.std() > 0 else 0
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 1e-6)) - 1
    dd = float((eq / eq.cummax() - 1).min())
    pnl = np.array([t["ret"] for t in trades])
    pf = pnl[pnl > 0].sum() / abs(pnl[pnl < 0].sum()) if (pnl < 0).any() else 0
    # Exposure fraction weighted by notional × time / equity
    total_bars_in = sum(t["bars"] for t in trades)
    exposure = total_bars_in / max(len(eq), 1)
    # Rough funding drag: avg_leverage × exposure × FUNDING_APR
    avg_notional = np.mean([t["notional"] for t in trades]) if trades else 0
    avg_equity = float(eq.mean())
    avg_lev = avg_notional / max(avg_equity, 1.0)
    funding_drag = FUNDING_APR * avg_lev * exposure
    cagr_net = cagr - funding_drag
    return dict(label=label, leverage=round(leverage_cap, 2),
                avg_lev=round(avg_lev, 2),
                n=len(trades), final=float(eq.iloc[-1]),
                cagr=round(cagr, 4), cagr_net=round(cagr_net, 4),
                sharpe=round(sh, 3), dd=round(dd, 4),
                win=round((pnl > 0).mean(), 3), pf=round(pf, 3),
                exposure=round(exposure, 3), funding_drag=round(funding_drag, 4))


# ================================================================
# Signal builders
# ================================================================
def donchian_up(h, n): return h.rolling(n).max().shift(1)
def donchian_dn(l, n): return l.rolling(n).min().shift(1)


def sig_rangekalman(df, alpha=0.05, rng_len=400, rng_mult=2.5, regime_len=800):
    c = df["close"].values
    kal = kalman_ema(c, alpha)
    rng = pd.Series(np.abs(c - kal), index=df.index).rolling(rng_len).mean().values * rng_mult
    upper = kal + rng
    regime = c > pd.Series(c, index=df.index).rolling(regime_len).mean().values
    u_prev = np.roll(upper, 1); c_prev = np.roll(c, 1)
    sig = (c > upper) & (c_prev <= u_prev) & regime
    sig[0] = False
    return pd.Series(sig, index=df.index)


def sig_rangekalman_short(df, alpha=0.05, rng_len=400, rng_mult=2.5, regime_len=800):
    c = df["close"].values
    kal = kalman_ema(c, alpha)
    rng = pd.Series(np.abs(c - kal), index=df.index).rolling(rng_len).mean().values * rng_mult
    lower = kal - rng
    regime_bear = c < pd.Series(c, index=df.index).rolling(regime_len).mean().values
    l_prev = np.roll(lower, 1); c_prev = np.roll(c, 1)
    sig = (c < lower) & (c_prev >= l_prev) & regime_bear
    sig[0] = False
    return pd.Series(sig, index=df.index)


def sig_bb_break(df, n=120, k=2.0, regime_len=600):
    _, ub, _ = bb(df["close"], n, k)
    regime = df["close"].values > df["close"].rolling(regime_len).mean().values
    sig = (df["close"] > ub) & (df["close"].shift(1) <= ub.shift(1)) & pd.Series(regime, index=df.index)
    return sig.fillna(False).astype(bool)


def sig_bb_break_short(df, n=120, k=2.0, regime_len=600):
    _, _, lb = bb(df["close"], n, k)
    regime_bear = df["close"].values < df["close"].rolling(regime_len).mean().values
    sig = (df["close"] < lb) & (df["close"].shift(1) >= lb.shift(1)) & pd.Series(regime_bear, index=df.index)
    return sig.fillna(False).astype(bool)


def sig_donchian(df, n=55, regime_len=600):
    up = donchian_up(df["high"], n).values
    regime = df["close"].values > df["close"].rolling(regime_len).mean().values
    return pd.Series((df["close"].values > up) & regime, index=df.index)


def sig_donchian_short(df, n=55, regime_len=600):
    dn = donchian_dn(df["low"], n).values
    regime_bear = df["close"].values < df["close"].rolling(regime_len).mean().values
    return pd.Series((df["close"].values < dn) & regime_bear, index=df.index)


def sig_supertrend_adx(df, st_n=10, st_mult=3.0, adx_min=20, regime_len=600):
    tr, _, _ = supertrend(df, st_n, st_mult)
    ax = talib.ADX(df["high"].values, df["low"].values, df["close"].values, 14)
    regime = df["close"].values > df["close"].rolling(regime_len).mean().values
    tr_prev = np.roll(tr, 1)
    sig = (tr == 1) & (tr_prev == -1) & (ax > adx_min) & regime
    sig[0] = False
    return pd.Series(sig, index=df.index)


def sig_mtf_momentum(df, don_n=24, d_ema=200, h4_ema=50):
    daily = df["close"].resample("1D").last().dropna()
    d_bull = (daily > ema(daily, d_ema)).reindex(df.index, method="ffill").fillna(False)
    h4 = df["close"].resample("4h").last().dropna()
    h4_bull = (h4 > ema(h4, h4_ema)).reindex(df.index, method="ffill").fillna(False)
    up = donchian_up(df["high"], don_n).values
    sig = (df["close"].values > up) & d_bull.values & h4_bull.values
    return pd.Series(sig, index=df.index)


def sig_keltner_adx(df, k_n=20, k_mult=1.5, adx_min=18, regime_len=600):
    _, up, _ = keltner(df, k_n, k_mult)
    ax = talib.ADX(df["high"].values, df["low"].values, df["close"].values, 14)
    regime = df["close"].values > df["close"].rolling(regime_len).mean().values
    sig = (df["close"] > up) & (df["close"].shift(1) <= up.shift(1)) & (ax > adx_min) & pd.Series(regime, index=df.index)
    return sig.fillna(False).astype(bool)


def sig_macd_rsi(df, fast=12, slow=26, sig_len=9, rsi_min=40, rsi_max=65, regime_len=600):
    c = df["close"]
    macd_line = ema(c, fast) - ema(c, slow)
    macd_sig = ema(macd_line, sig_len)
    rsi = talib.RSI(c.values, 14)
    regime = c.values > c.rolling(regime_len).mean().values
    cross_up = (macd_line > macd_sig) & (macd_line.shift(1) <= macd_sig.shift(1))
    sig = cross_up & (rsi > rsi_min) & (rsi < rsi_max) & pd.Series(regime, index=df.index)
    return sig.fillna(False).astype(bool)


def sig_vol_regime_momo(df, vol_low=0.4, vol_high=1.2, don_n=48, regime_len=600):
    # Volatility regime via realized_vol_24 normalised by its trailing median
    rv = df["realized_vol_24"]
    med = rv.rolling(168).median()
    ratio = rv / med
    in_regime = (ratio > vol_low) & (ratio < vol_high)
    up = donchian_up(df["high"], don_n).values
    regime = df["close"].values > df["close"].rolling(regime_len).mean().values
    sig = (df["close"].values > up) & regime & in_regime.fillna(False).values
    return pd.Series(sig, index=df.index)


# ================================================================
# Runner
# ================================================================
def run_one(df, sig_fn, params, tp, sl, trail, max_hold, leverage,
            short_fn=None, risk=0.015):
    long_sig = sig_fn(df, **params)
    long_sig = long_sig & ~long_sig.shift(1).fillna(False)
    short_sig = None
    if short_fn is not None:
        short_sig = short_fn(df, **params)
        short_sig = short_sig & ~short_sig.shift(1).fillna(False)
    trades, eq = simulate(df, long_sig, short_entries=short_sig,
                          tp_atr=tp, sl_atr=sl, trail_atr=trail,
                          max_hold=max_hold, risk_per_trade=risk,
                          leverage_cap=leverage)
    return trades, eq


def fmt(r):
    return (f"n={r['n']:4d} L={r['leverage']:.1f} avgL={r['avg_lev']:.2f} "
            f"Sh={r['sharpe']:5.2f} CAGR={r['cagr']*100:+7.1f}% net={r['cagr_net']*100:+7.1f}% "
            f"DD={r['dd']*100:+6.1f}% Win={r['win']*100:4.1f}% PF={r['pf']:.2f}")


SPECS = [
    # (name, sig_fn, grid, tp, sl, trail, max_hold, short_fn)
    ("RangeKalman", sig_rangekalman, [
        {"alpha": 0.05, "rng_len": 400, "rng_mult": 2.5, "regime_len": 800},
        {"alpha": 0.07, "rng_len": 400, "rng_mult": 2.5, "regime_len": 800},
        {"alpha": 0.07, "rng_len": 300, "rng_mult": 2.5, "regime_len": 800},
        {"alpha": 0.07, "rng_len": 400, "rng_mult": 2.0, "regime_len": 800},
    ], 5.0, 2.0, 3.5, 72, None),
    ("RangeKalman_LS", sig_rangekalman, [
        {"alpha": 0.05, "rng_len": 400, "rng_mult": 2.5, "regime_len": 800},
        {"alpha": 0.07, "rng_len": 400, "rng_mult": 2.5, "regime_len": 800},
    ], 5.0, 2.0, 3.5, 72, sig_rangekalman_short),
    ("BBbreak", sig_bb_break, [
        {"n": 120, "k": 2.0, "regime_len": 600},
        {"n": 120, "k": 1.8, "regime_len": 600},
        {"n": 168, "k": 2.0, "regime_len": 600},
        {"n": 168, "k": 2.2, "regime_len": 600},
    ], 5.0, 2.0, 3.5, 72, None),
    ("BBbreak_LS", sig_bb_break, [
        {"n": 120, "k": 2.0, "regime_len": 600},
        {"n": 168, "k": 2.0, "regime_len": 600},
    ], 5.0, 2.0, 3.5, 72, sig_bb_break_short),
    ("Donchian55", sig_donchian, [
        {"n": 55, "regime_len": 600},
        {"n": 40, "regime_len": 600},
        {"n": 80, "regime_len": 600},
    ], 5.0, 2.0, 3.5, 72, None),
    ("Donchian_LS", sig_donchian, [
        {"n": 55, "regime_len": 600},
        {"n": 80, "regime_len": 600},
    ], 5.0, 2.0, 3.5, 72, sig_donchian_short),
    ("Supertrend_ADX", sig_supertrend_adx, [
        {"st_n": 10, "st_mult": 3.0, "adx_min": 20, "regime_len": 600},
        {"st_n": 12, "st_mult": 3.0, "adx_min": 25, "regime_len": 600},
    ], 5.0, 2.0, 3.5, 72, None),
    ("MTF_Momentum", sig_mtf_momentum, [
        {"don_n": 24, "d_ema": 200, "h4_ema": 50},
        {"don_n": 48, "d_ema": 200, "h4_ema": 50},
    ], 5.0, 2.0, 3.5, 72, None),
    ("Keltner_ADX", sig_keltner_adx, [
        {"k_n": 20, "k_mult": 1.5, "adx_min": 18, "regime_len": 600},
        {"k_n": 30, "k_mult": 1.8, "adx_min": 20, "regime_len": 600},
    ], 5.0, 2.0, 3.5, 72, None),
    ("MACD_RSI", sig_macd_rsi, [
        {"fast": 12, "slow": 26, "sig_len": 9, "rsi_min": 40, "rsi_max": 65, "regime_len": 600},
        {"fast": 8, "slow": 21, "sig_len": 5, "rsi_min": 45, "rsi_max": 70, "regime_len": 600},
    ], 5.0, 2.0, 3.5, 72, None),
    ("VolRegime_Momo", sig_vol_regime_momo, [
        {"vol_low": 0.4, "vol_high": 1.2, "don_n": 48, "regime_len": 600},
        {"vol_low": 0.5, "vol_high": 1.5, "don_n": 48, "regime_len": 600},
    ], 5.0, 2.0, 3.5, 72, None),
]


def main():
    START = pd.Timestamp("2019-01-01", tz="UTC")
    LEV = [1.0, 2.0, 3.0]
    RISK_PER_TRADE = 0.015   # 1.5%
    rows = []

    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        df = pd.read_parquet(FEAT / f"{sym}_1h_features.parquet")
        df = df.dropna(subset=["open", "high", "low", "close", "volume"]).copy()
        df = df[df.index >= START]
        print(f"\n=== {sym}  ({len(df):,} bars) ===", flush=True)

        for name, sig_fn, grid, tp, sl, trail, mh, short_fn in SPECS:
            for params in grid:
                plabel = ",".join(f"{k}={v}" for k, v in params.items())
                try:
                    for L in LEV:
                        trades, eq = run_one(df, sig_fn, params, tp, sl, trail, mh, L,
                                             short_fn=short_fn, risk=RISK_PER_TRADE)
                        r = report(f"{sym}_{name}_{plabel}", eq, trades, leverage_cap=L)
                        r["symbol"] = sym; r["strategy"] = name; r["params"] = plabel
                        rows.append(r)
                    r3 = next(x for x in rows if x["symbol"] == sym and x["strategy"] == name
                              and x["params"] == plabel and x["leverage"] == 3.0)
                    r1 = next(x for x in rows if x["symbol"] == sym and x["strategy"] == name
                              and x["params"] == plabel and x["leverage"] == 1.0)
                    print(f"  {name:18s} {plabel:55s} 1x {fmt(r1)} | 3x {fmt(r3)}", flush=True)
                except Exception as e:
                    print(f"  {name:18s} {plabel}  ERROR: {e}")

    out = pd.DataFrame(rows)
    out.to_csv(OUT / "v15_hunt_results.csv", index=False)

    cols = ["symbol", "strategy", "params", "leverage", "avg_lev", "n",
            "cagr", "cagr_net", "sharpe", "dd", "win", "pf", "exposure", "funding_drag", "final"]

    winners = out[(out["cagr_net"] >= 0.55) & (out["dd"] >= -0.40) & (out["sharpe"] >= 0.9)].copy()
    winners = winners.sort_values(["cagr_net", "sharpe"], ascending=False)
    winners.to_csv(OUT / "v15_winners.csv", index=False)

    near = out[(out["cagr_net"] >= 0.30) & (out["dd"] >= -0.40) & (out["sharpe"] >= 0.8)].copy()
    near = near.sort_values(["cagr_net", "sharpe"], ascending=False)
    near.to_csv(OUT / "v15_near_misses.csv", index=False)

    print(f"\n=== SUMMARY ===\nTotal runs: {len(out)}")
    print(f"Winners (net CAGR>=55%, DD>=-40%, Sharpe>=0.9): {len(winners)}")
    if len(winners):
        print(winners[cols].head(30).to_string(index=False))
    print(f"\nNear-misses (net CAGR>=30%, DD>=-40%, Sharpe>=0.8): {len(near)}")
    if len(near):
        print(near[cols].head(25).to_string(index=False))


if __name__ == "__main__":
    sys.exit(main() or 0)
