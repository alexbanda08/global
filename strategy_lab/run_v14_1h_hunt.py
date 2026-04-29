"""
V14 — 1h strategy hunt for >=55% CAGR net (with up to 3x leverage, max DD <=-40%).

Uses the existing feature parquets under features/ and the engine conventions
(next-bar-open execution, ATR stops, Hyperliquid fees).

Strategies tested (long-only unless noted):
  S1  Donchian-fast     Donchian-55 break, regime_bull, ATR stops
  S2  Donchian-slow     Donchian-168 (1-week) break, regime_bull
  S3  Range-Kalman      V13A baseline (per-asset param grid)
  S4  Supertrend-ADX    Supertrend(10,3) + ADX>20 regime
  S5  Momentum-MTF      Daily>EMA200 AND 4h>EMA50 AND 1h Donchian-24 break
  S6  BB-break          Bollinger(120,2.2) upper break, regime_bull
  S7  OI-momo           OI 4h-pct_chg>thr AND price>EMA200-1h AND regime_bull
  S8  Range-Kalman+short V13A long/short: long on bull break, short on bear break

Parameter grids are small (3-5 neighbours per knob) to stay honest about overfit.

Execution costs are Hyperliquid-tier taker (0.00045/side) + 3bps slip.
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
OUT = ROOT / "strategy_lab" / "results" / "v14"
OUT.mkdir(parents=True, exist_ok=True)

# -------------------- execution constants --------------------
FEE = 0.00045          # Hyperliquid taker (conservative — maker is 0.00015)
SLIP = 0.0003          # 3 bps per side
INIT = 10_000.0

# Perp funding drag in %/year per 1x notional long exposure.
# Historically ~10% APR mean across BTC/ETH/SOL perps; use 8% as moderate.
FUNDING_APR = 0.08


# ================================================================
# Indicators (pure numpy/pandas so we never hit talib's slow path on massive sweeps)
# ================================================================
def atr(df: pd.DataFrame, n: int = 14) -> np.ndarray:
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    tr = np.maximum.reduce([h - l, np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))])
    s = pd.Series(tr, index=df.index).ewm(alpha=1 / n, adjust=False).mean()
    return s.values


def ema(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(span=n, adjust=False).mean()


def donchian_up(h: pd.Series, n: int) -> pd.Series:
    return h.rolling(n).max().shift(1)


def donchian_dn(l: pd.Series, n: int) -> pd.Series:
    return l.rolling(n).min().shift(1)


def bb(close: pd.Series, n: int = 120, k: float = 2.0):
    m = close.rolling(n).mean()
    s = close.rolling(n).std()
    return m, m + k * s, m - k * s


def supertrend(df: pd.DataFrame, n: int = 10, mult: float = 3.0):
    at = atr(df, n)
    hl2 = (df["high"].values + df["low"].values) / 2.0
    ub = hl2 + mult * at
    lb = hl2 - mult * at
    close = df["close"].values
    N = len(close)
    trend = np.ones(N, dtype=np.int8)
    final_ub = np.full(N, np.nan)
    final_lb = np.full(N, np.nan)
    for i in range(1, N):
        if not np.isfinite(ub[i]) or not np.isfinite(lb[i]):
            continue
        final_ub[i] = ub[i] if (np.isnan(final_ub[i - 1]) or ub[i] < final_ub[i - 1] or close[i - 1] > final_ub[i - 1]) else final_ub[i - 1]
        final_lb[i] = lb[i] if (np.isnan(final_lb[i - 1]) or lb[i] > final_lb[i - 1] or close[i - 1] < final_lb[i - 1]) else final_lb[i - 1]
        if close[i] > (final_ub[i - 1] if np.isfinite(final_ub[i - 1]) else ub[i]):
            trend[i] = 1
        elif close[i] < (final_lb[i - 1] if np.isfinite(final_lb[i - 1]) else lb[i]):
            trend[i] = -1
        else:
            trend[i] = trend[i - 1]
    return trend, final_ub, final_lb


def kalman_ema(c: np.ndarray, alpha: float) -> np.ndarray:
    n = len(c)
    k = np.zeros(n)
    k[0] = c[0]
    for i in range(1, n):
        k[i] = k[i - 1] + alpha * (c[i] - k[i - 1])
    return k


def adx(df: pd.DataFrame, n: int = 14) -> np.ndarray:
    return talib.ADX(df["high"].values, df["low"].values, df["close"].values, n)


# ================================================================
# Simulator — long-only or long/short with ATR stops + time exit.
# Supports leverage L (simple notional scaling, funding drag applied later).
# ================================================================
def simulate(df: pd.DataFrame,
             long_entries: pd.Series,
             short_entries: pd.Series | None = None,
             tp_atr: float = 5.0,
             sl_atr: float = 2.0,
             trail_atr: float | None = 3.5,
             max_hold: int = 72,
             leverage: float = 1.0,
             size_frac: float = 0.99):
    op = df["open"].values; hi = df["high"].values; lo = df["low"].values; cl = df["close"].values
    at = atr(df)
    sig_l = long_entries.values.astype(bool)
    sig_s = short_entries.values.astype(bool) if short_entries is not None else np.zeros(len(df), dtype=bool)

    N = len(df)
    cash = INIT
    eq = np.empty(N); eq[0] = cash
    pos = 0; entry_p = sl = tp = 0.0; size = 0.0; entry_idx = 0; last_exit = -9999; hh = 0.0; ll = 0.0
    trades = []

    for i in range(1, N - 1):
        if pos != 0:
            held = i - entry_idx
            # trailing stop
            if trail_atr is not None:
                if pos == 1:
                    hh = max(hh, hi[i])
                    new_sl = hh - trail_atr * at[i]
                    if new_sl > sl:
                        sl = new_sl
                else:
                    ll = min(ll, lo[i]) if ll > 0 else lo[i]
                    new_sl = ll + trail_atr * at[i]
                    if new_sl < sl:
                        sl = new_sl

            exited = False; ep = 0.0; reason = ""
            if pos == 1:
                if lo[i] <= sl:
                    ep = sl * (1 - SLIP); reason = "SL"; exited = True
                elif hi[i] >= tp:
                    ep = tp * (1 - SLIP); reason = "TP"; exited = True
                elif held >= max_hold:
                    ep = cl[i]; reason = "TIME"; exited = True
            else:  # pos == -1
                if hi[i] >= sl:
                    ep = sl * (1 + SLIP); reason = "SL"; exited = True
                elif lo[i] <= tp:
                    ep = tp * (1 + SLIP); reason = "TP"; exited = True
                elif held >= max_hold:
                    ep = cl[i]; reason = "TIME"; exited = True

            if exited:
                pnl_per_unit = (ep - entry_p) * pos
                # fees on both legs on leveraged notional
                fee_cost = size * (entry_p + ep) * FEE
                cash += size * pnl_per_unit - fee_cost
                ret = (pnl_per_unit / entry_p) * leverage - 2 * FEE * leverage
                trades.append({"ret": ret, "reason": reason, "side": pos,
                               "bars": held, "entry": entry_p, "exit": ep})
                pos = 0; last_exit = i
                eq[i] = cash
                continue

        if pos == 0 and (i - last_exit) > 2 and i + 1 < N:
            take_long = sig_l[i]
            take_short = sig_s[i]
            if take_long or take_short:
                direction = 1 if take_long else -1
                ep = op[i + 1] * (1 + SLIP * direction)
                s_stop = ep - sl_atr * at[i] * direction
                t_stop = ep + tp_atr * at[i] * direction
                if np.isfinite(s_stop) and np.isfinite(t_stop) and np.isfinite(at[i]) and at[i] > 0:
                    # size scaled by leverage — notional can exceed cash
                    size = (cash * size_frac * leverage) / ep
                    pos = direction; entry_p = ep; sl = s_stop; tp = t_stop; entry_idx = i + 1
                    hh = ep; ll = ep

        if pos == 0:
            eq[i] = cash
        else:
            unreal = size * (cl[i] - entry_p) * pos - size * entry_p * FEE
            eq[i] = cash + unreal
    eq[-1] = eq[-2]
    return trades, pd.Series(eq, index=df.index)


def report(label: str, eq: pd.Series, trades: list, leverage: float = 1.0) -> dict:
    if len(trades) < 3:
        return {"label": label, "leverage": leverage, "n": len(trades),
                "final": float(eq.iloc[-1]), "cagr": 0, "sharpe": 0, "dd": 0,
                "win": 0, "pf": 0, "cagr_net": 0}
    rets = eq.pct_change().dropna()
    dt = rets.index.to_series().diff().median()
    bpy = pd.Timedelta(days=365.25) / dt if dt else 1
    sh = rets.mean() / rets.std() * np.sqrt(bpy) if rets.std() > 0 else 0
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 1e-6)) - 1
    dd = float((eq / eq.cummax() - 1).min())
    pnl = np.array([t["ret"] for t in trades])
    pf = pnl[pnl > 0].sum() / abs(pnl[pnl < 0].sum()) if (pnl < 0).any() else 0
    # exposure fraction — used for funding drag estimate
    total_bars_in = sum(t["bars"] for t in trades)
    exposure = total_bars_in / max(len(eq), 1)
    funding_drag = FUNDING_APR * leverage * exposure
    cagr_net = cagr - funding_drag
    return dict(label=label, leverage=round(leverage, 2), n=len(trades),
                final=float(eq.iloc[-1]),
                cagr=round(cagr, 4), cagr_net=round(cagr_net, 4),
                sharpe=round(sh, 3), dd=round(dd, 4),
                win=round((pnl > 0).mean(), 3), pf=round(pf, 3),
                exposure=round(exposure, 3),
                funding_drag=round(funding_drag, 4))


# ================================================================
# Strategy signal builders
# ================================================================
def s1_donchian_fast(df, n=55, regime_len=600):
    up = donchian_up(df["high"], n).values
    regime = df["close"].values > df["close"].rolling(regime_len).mean().values
    sig = (df["close"].values > up) & regime
    return pd.Series(sig, index=df.index)


def s2_donchian_slow(df, n=168, regime_len=600):
    up = donchian_up(df["high"], n).values
    regime = df["close"].values > df["close"].rolling(regime_len).mean().values
    sig = (df["close"].values > up) & regime
    return pd.Series(sig, index=df.index)


def s3_range_kalman(df, alpha=0.05, rng_len=400, rng_mult=2.5, regime_len=800):
    c = df["close"].values
    kal = kalman_ema(c, alpha)
    abs_dev = np.abs(c - kal)
    rng = pd.Series(abs_dev, index=df.index).rolling(rng_len).mean().values * rng_mult
    upper = kal + rng
    regime = c > pd.Series(c, index=df.index).rolling(regime_len).mean().values
    N = len(c); sig = np.zeros(N, dtype=bool)
    upper_prev = np.roll(upper, 1); c_prev = np.roll(c, 1)
    sig = (c > upper) & (c_prev <= upper_prev) & regime
    sig[0] = False
    return pd.Series(sig, index=df.index)


def s3_range_kalman_short(df, alpha=0.05, rng_len=400, rng_mult=2.5, regime_len=800):
    c = df["close"].values
    kal = kalman_ema(c, alpha)
    abs_dev = np.abs(c - kal)
    rng = pd.Series(abs_dev, index=df.index).rolling(rng_len).mean().values * rng_mult
    lower = kal - rng
    regime_bear = c < pd.Series(c, index=df.index).rolling(regime_len).mean().values
    N = len(c); sig = np.zeros(N, dtype=bool)
    lower_prev = np.roll(lower, 1); c_prev = np.roll(c, 1)
    sig = (c < lower) & (c_prev >= lower_prev) & regime_bear
    sig[0] = False
    return pd.Series(sig, index=df.index)


def s4_supertrend_adx(df, st_n=10, st_mult=3.0, adx_min=20, regime_len=600):
    tr, ub, lb = supertrend(df, st_n, st_mult)
    ax = adx(df)
    regime = df["close"].values > df["close"].rolling(regime_len).mean().values
    tr_prev = np.roll(tr, 1)
    sig = (tr == 1) & (tr_prev == -1) & (ax > adx_min) & regime
    sig[0] = False
    return pd.Series(sig, index=df.index)


def s5_momentum_mtf(df, don_n=24, regime_d_len=200, regime_4h_len=50):
    # Daily bull: close > daily EMA200
    daily_close = df["close"].resample("1D").last().dropna()
    daily_ema = ema(daily_close, regime_d_len)
    daily_bull = (daily_close > daily_ema).reindex(df.index, method="ffill").fillna(False)
    # 4h bull: 4h close > 4h EMA50
    h4 = df["close"].resample("4h").last().dropna()
    h4_ema = ema(h4, regime_4h_len)
    h4_bull = (h4 > h4_ema).reindex(df.index, method="ffill").fillna(False)
    # 1h Donchian(24) break
    up = donchian_up(df["high"], don_n).values
    breakout = df["close"].values > up
    sig = breakout & daily_bull.values & h4_bull.values
    return pd.Series(sig, index=df.index)


def s6_bb_break(df, n=120, k=2.0, regime_len=600):
    _, ub, _ = bb(df["close"], n, k)
    regime = df["close"].values > df["close"].rolling(regime_len).mean().values
    ub_prev = ub.shift(1)
    sig = (df["close"] > ub) & (df["close"].shift(1) <= ub_prev) & pd.Series(regime, index=df.index)
    return sig.fillna(False).astype(bool)


def s7_oi_momo(df, oi_thr=0.02, ema_len=200, regime_len=600):
    if "oi_pct_chg_4" not in df.columns:
        return pd.Series(False, index=df.index)
    e = ema(df["close"], ema_len)
    oi = df["oi_pct_chg_4"].fillna(0)
    regime = df["close"].values > df["close"].rolling(regime_len).mean().values
    sig = (oi > oi_thr) & (df["close"] > e) & pd.Series(regime, index=df.index)
    return sig.fillna(False).astype(bool)


# ================================================================
# Runner
# ================================================================
def run_one(df, sig_fn, params, tp, sl, trail, max_hold, leverage, short_sig_fn=None, short_params=None):
    long_sig = sig_fn(df, **params)
    long_sig = long_sig & ~long_sig.shift(1).fillna(False)
    short_sig = None
    if short_sig_fn is not None:
        short_sig = short_sig_fn(df, **(short_params or params))
        short_sig = short_sig & ~short_sig.shift(1).fillna(False)
    trades, eq = simulate(df, long_sig, short_entries=short_sig,
                          tp_atr=tp, sl_atr=sl, trail_atr=trail,
                          max_hold=max_hold, leverage=leverage)
    return trades, eq


def fmt(r, extra=""):
    return (f"n={r['n']:4d} L={r['leverage']:.1f} Sh={r['sharpe']:5.2f} "
            f"CAGR={r['cagr']*100:+7.1f}% net={r['cagr_net']*100:+7.1f}% "
            f"DD={r['dd']*100:+6.1f}% Win={r['win']*100:4.1f}% PF={r['pf']:.2f} {extra}")


def main():
    START = pd.Timestamp("2019-01-01", tz="UTC")
    rows = []

    # Define strategy specs: (name, sig_fn, param grid dicts, tp, sl, trail, max_hold, [short_fn])
    specs = [
        # S1 Donchian fast — param grid over n and regime_len
        ("S1_Donchian55", s1_donchian_fast, [{"n": 55, "regime_len": 600},
                                             {"n": 40, "regime_len": 600},
                                             {"n": 80, "regime_len": 600},
                                             {"n": 55, "regime_len": 400},
                                             {"n": 55, "regime_len": 1000}], 5.0, 2.0, 3.5, 72, None),
        # S2 Donchian slow
        ("S2_Donchian168", s2_donchian_slow, [{"n": 168, "regime_len": 600},
                                              {"n": 120, "regime_len": 600},
                                              {"n": 240, "regime_len": 600}], 6.0, 2.5, 4.0, 120, None),
        # S3 Range Kalman — V13A default plus a tuned neighbour
        ("S3_RangeKalman", s3_range_kalman, [{"alpha": 0.05, "rng_len": 400, "rng_mult": 2.5, "regime_len": 800},
                                             {"alpha": 0.07, "rng_len": 400, "rng_mult": 2.5, "regime_len": 800},
                                             {"alpha": 0.05, "rng_len": 300, "rng_mult": 2.0, "regime_len": 800},
                                             {"alpha": 0.05, "rng_len": 500, "rng_mult": 3.0, "regime_len": 800}],
         5.0, 2.0, 3.5, 72, None),
        # S4 Supertrend + ADX
        ("S4_Supertrend_ADX", s4_supertrend_adx, [{"st_n": 10, "st_mult": 3.0, "adx_min": 20, "regime_len": 600},
                                                  {"st_n": 12, "st_mult": 3.0, "adx_min": 25, "regime_len": 600},
                                                  {"st_n": 14, "st_mult": 2.5, "adx_min": 18, "regime_len": 800}],
         5.0, 2.0, 3.5, 72, None),
        # S5 Momentum MTF
        ("S5_MomentumMTF", s5_momentum_mtf, [{"don_n": 24, "regime_d_len": 200, "regime_4h_len": 50},
                                             {"don_n": 48, "regime_d_len": 200, "regime_4h_len": 50},
                                             {"don_n": 24, "regime_d_len": 200, "regime_4h_len": 100}],
         5.0, 2.0, 3.5, 72, None),
        # S6 BB breakout
        ("S6_BBbreak", s6_bb_break, [{"n": 120, "k": 2.0, "regime_len": 600},
                                     {"n": 168, "k": 2.2, "regime_len": 600},
                                     {"n": 120, "k": 1.8, "regime_len": 600}],
         5.0, 2.0, 3.5, 72, None),
        # S7 OI momentum (only works where futures metrics exist, from ~2020-09)
        ("S7_OIMomo", s7_oi_momo, [{"oi_thr": 0.02, "ema_len": 200, "regime_len": 600},
                                   {"oi_thr": 0.01, "ema_len": 200, "regime_len": 600},
                                   {"oi_thr": 0.03, "ema_len": 200, "regime_len": 600}],
         5.0, 2.0, 3.5, 72, None),
        # S8 Range Kalman LONG+SHORT
        ("S8_RangeKalmanLS", s3_range_kalman, [{"alpha": 0.05, "rng_len": 400, "rng_mult": 2.5, "regime_len": 800},
                                               {"alpha": 0.07, "rng_len": 400, "rng_mult": 2.5, "regime_len": 800}],
         5.0, 2.0, 3.5, 72, s3_range_kalman_short),
    ]

    # Leverage ladder
    LEV = [1.0, 2.0, 3.0]

    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        df = pd.read_parquet(FEAT / f"{sym}_1h_features.parquet")
        df = df.dropna(subset=["open", "high", "low", "close", "volume"]).copy()
        df = df[df.index >= START]
        print(f"\n=== {sym}  ({len(df):,} bars 1h) ===", flush=True)

        for name, sig_fn, grid, tp, sl, trail, mh, short_fn in specs:
            for params in grid:
                plabel = ",".join(f"{k}={v}" for k, v in params.items())
                try:
                    # Compute signals once, then test each leverage by re-simulating
                    # (leverage affects position sizing path-dependently).
                    for L in LEV:
                        trades, eq = run_one(df, sig_fn, params, tp, sl, trail, mh, L,
                                             short_sig_fn=short_fn, short_params=None)
                        r = report(f"{sym}_{name}_{plabel}", eq, trades, leverage=L)
                        r["symbol"] = sym
                        r["strategy"] = name
                        r["params"] = plabel
                        rows.append(r)
                    # Only print 1x and 3x lines for readability
                    r1 = [x for x in rows if x["symbol"] == sym and x["strategy"] == name
                          and x["params"] == plabel and x["leverage"] == 1.0][-1]
                    r3 = [x for x in rows if x["symbol"] == sym and x["strategy"] == name
                          and x["params"] == plabel and x["leverage"] == 3.0][-1]
                    print(f"  {name:22s} {plabel:50s} 1x {fmt(r1)} | 3x {fmt(r3)}", flush=True)
                except Exception as e:
                    print(f"  {name:22s} {plabel}  ERROR: {e}")

    out = pd.DataFrame(rows)
    out.to_csv(OUT / "v14_hunt_results.csv", index=False)

    # Filter to winners: net CAGR >= 0.55 at any leverage, DD >= -0.40
    winners = out[(out["cagr_net"] >= 0.55) & (out["dd"] >= -0.40) & (out["sharpe"] >= 0.8)].copy()
    winners = winners.sort_values(["cagr_net", "sharpe"], ascending=False)
    winners.to_csv(OUT / "v14_winners.csv", index=False)

    print(f"\n\n=== SUMMARY ===\nTotal runs: {len(out)}")
    print(f"Candidates with CAGR_net>=55% AND DD>=-40% AND Sharpe>=0.8: {len(winners)}")
    if len(winners):
        cols = ["symbol", "strategy", "params", "leverage", "n", "cagr", "cagr_net",
                "sharpe", "dd", "win", "pf", "exposure", "funding_drag", "final"]
        print(winners[cols].head(25).to_string(index=False))

    print(f"\nSaved:\n  {OUT/'v14_hunt_results.csv'}\n  {OUT/'v14_winners.csv'}")


if __name__ == "__main__":
    sys.exit(main() or 0)
