"""
V9 "Chimera" — multi-layer regime-adaptive 15m strategy.

Inspired by the CYCLOPS architecture (cyclops_style_bot doc) and tuned for
HYPERLIQUID PERPETUALS:

  * Fees: 0.015 % maker / 0.045 % taker per side, 5 bps slip.
    Assume 70 % maker fills, 30 % taker → avg 0.024 % per side → 0.048 % round-trip.
    vs Binance spot's 0.2 %  =>  4x more room for small 15m edges.

Architecture (3 layers, no static rules):

  LAYER 1 — DATA
      15m OHLCV already on disk. Plus resampled 1h / 4h / 1d for context.

  LAYER 2 — THE BRAIN (regime-weighted voting)
      Regime detector (ADX + ATR percentile + trend direction):
          TREND_UP, TREND_DOWN, SIDEWAYS, VOLATILE_TREND, VOLATILE_CHOPPY
      Indicator zoo (6 categories × multiple indicators per cat):
          trend   : SuperTrend, EMA 9/21 cross
          momentum: MACD hist, price-accel (d²)
          osc     : StochRSI, RSI, BB %B
          flow    : volume-delta proxy (up vs down bar volume rolling)
          vol     : ATR percentile
          micro   : wick imbalance (upper_wick/lower_wick ratio)
      Each indicator returns (direction in {-1,0,+1}, strength in [0,1], cat).
      Regime-aware multipliers amplify leading signals in trends,
      structural signals in sideways.  Composite confidence = tanh(score).

      HYSTERESIS: regime only flips after 3 consecutive agreeing bars.

  LAYER 3 — FILTERS
      * Session filter: avoid 00:00-04:00 UTC (low-vol Asian sleep on weekends)
      * Signal memory: lock out re-entry within 8 bars (2 h) after any exit
      * Extreme-candle veto: skip if previous bar > 3× rolling ATR (news spike)
      * Risk gate: if drawdown from recent peak > 5 %, halve sizing

  DIRECTION GATE (regime-aware):
      TREND_UP         → LONGS ONLY
      TREND_DOWN       → SHORTS ONLY
      SIDEWAYS         → both, BB-mean-reversion bias
      VOLATILE_TREND   → both, size halved
      VOLATILE_CHOPPY  → FLAT
      UNKNOWN          → FLAT

  EXECUTION:
      * SL = 1.5 × ATR
      * TP = 3.0 × ATR (2:1 R:R)
      * Trail activates once +1.5 × ATR in profit; trail by 1 × ATR
      * Fixed-fraction sizing (20 % of equity per trade) — keeps it simple and
        avoids the phantom-leverage bug we had in V7

All three assets (BTC/ETH/SOL), own $10k each, 2018-01-01 → 2026-04-01.
"""
from __future__ import annotations
import time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "binance" / "parquet"
OUT  = ROOT / "strategy_lab" / "results"

# Hyperliquid cost assumption (70% maker / 30% taker blend)
FEE = 0.00024        # per side ≈ 0.024 %
SLIP = 0.0005
INIT = 10_000.0
START, END = "2018-01-01", "2026-04-01"


# -------- indicator primitives --------
def ema(s, n): return s.ewm(span=n, adjust=False).mean()
def rma(s, n): return s.ewm(alpha=1/n, adjust=False).mean()


def atr(df, n=14):
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"]  - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    return rma(tr, n)


def adx(df, n=14):
    up_move  = df["high"].diff()
    dn_move  = -df["low"].diff()
    plus_dm  = up_move.where((up_move > dn_move) & (up_move > 0), 0)
    minus_dm = dn_move.where((dn_move > up_move) & (dn_move > 0), 0)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"]  - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr_ = rma(tr, n)
    plus_di  = 100 * rma(plus_dm, n) / atr_
    minus_di = 100 * rma(minus_dm, n) / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return rma(dx, n)


def rsi(close, n=14):
    d = close.diff()
    u, v = d.clip(lower=0), (-d).clip(lower=0)
    return 100 - 100 / (1 + rma(u, n) / rma(v, n).replace(0, np.nan))


def stoch_rsi(close, n=14, k_smooth=3, d_smooth=3):
    r = rsi(close, n)
    mn = r.rolling(n).min(); mx = r.rolling(n).max()
    raw = 100 * (r - mn) / (mx - mn).replace(0, np.nan)
    k = raw.rolling(k_smooth).mean()
    d = k.rolling(d_smooth).mean()
    return k, d


def bb_pct_b(close, n=20, mult=2.0):
    m = close.rolling(n).mean()
    s = close.rolling(n).std(ddof=0)
    upper, lower = m + mult * s, m - mult * s
    return (close - lower) / (upper - lower).replace(0, np.nan), m


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


# -------- regime detector --------
REGIME = {"TREND_UP":1, "TREND_DOWN":2, "SIDEWAYS":3,
          "VOLATILE_TREND":4, "VOLATILE_CHOPPY":5, "UNKNOWN":0}
REG_NAMES = {v: k for k, v in REGIME.items()}


def classify_regime(df, adx_n=14, atr_n=14):
    a = adx(df, adx_n)
    t = atr(df, atr_n) / df["close"]
    slope = df["close"].diff(20)           # 20-bar slope
    atr_pct = t.rolling(400).rank(pct=True)   # volatility percentile over 100h of 15m

    adx_strong = a > 25
    adx_weak   = a < 20
    vol_high   = atr_pct > 0.7
    up_dir     = slope > 0
    dn_dir     = slope < 0

    reg = np.full(len(df), REGIME["UNKNOWN"], dtype=np.int8)
    reg[(adx_strong & ~vol_high & up_dir).values] = REGIME["TREND_UP"]
    reg[(adx_strong & ~vol_high & dn_dir).values] = REGIME["TREND_DOWN"]
    reg[(adx_strong & vol_high).values]           = REGIME["VOLATILE_TREND"]
    reg[(adx_weak   & ~vol_high).values]          = REGIME["SIDEWAYS"]
    reg[(adx_weak   & vol_high).values]           = REGIME["VOLATILE_CHOPPY"]

    # Hysteresis: require 3 consecutive agreeing bars before switching
    out = np.full(len(df), REGIME["UNKNOWN"], dtype=np.int8)
    cur = REGIME["UNKNOWN"]; streak = 0; cand = REGIME["UNKNOWN"]
    for i, v in enumerate(reg):
        if v == cand:
            streak += 1
        else:
            cand = v; streak = 1
        if streak >= 3:
            cur = cand
        out[i] = cur
    return pd.Series(out, index=df.index)


# -------- indicator zoo → (direction, strength, category) --------
def build_indicators(df):
    st   = supertrend(df)                       # -1 / +1
    e9, e21 = ema(df["close"], 9), ema(df["close"], 21)
    ema_x = np.where(e9 > e21, 1, -1)
    macd_h = ema(df["close"], 12) - ema(df["close"], 26)
    macd_h = macd_h - ema(macd_h, 9)
    accel = df["close"].diff().diff()           # d²P/dt²
    sk, sd_ = stoch_rsi(df["close"])
    r = rsi(df["close"])
    b, _ = bb_pct_b(df["close"])
    atr_ = atr(df)
    atr_pct = (atr_ / df["close"]).rolling(400).rank(pct=True)
    # volume-delta proxy: bullish bar volume minus bearish bar volume, rolling
    bull_vol = df["volume"].where(df["close"] > df["open"], 0)
    bear_vol = df["volume"].where(df["close"] < df["open"], 0)
    vdelta = (bull_vol - bear_vol).rolling(20).sum() / df["volume"].rolling(20).sum()
    upper_wick = df["high"] - df[["open","close"]].max(axis=1)
    lower_wick = df[["open","close"]].min(axis=1) - df["low"]
    wick_imb = (lower_wick - upper_wick) / (upper_wick + lower_wick + 1e-9)

    def sign(x): return np.sign(x).fillna(0).astype(int)

    ind = {
        "SUPERTREND": (st.values,                       np.abs(st).fillna(0).values,                "trend"),
        "EMA9_21":    (ema_x,                           pd.Series(np.ones(len(df))).values,         "trend"),
        "MACD_HIST":  (sign(macd_h).values,             macd_h.abs().clip(upper=1).fillna(0).values,"mom"),
        "ACCEL":      (sign(accel).values,              accel.abs().clip(upper=1).fillna(0).values, "mom"),
        "STOCH_RSI":  (np.where(sk < 20, 1, np.where(sk > 80, -1, 0)),
                                                        np.minimum(np.abs(sk - 50) / 50, 1).fillna(0).values, "osc"),
        "RSI":        (np.where(r < 30, 1, np.where(r > 70, -1, 0)),
                                                        np.minimum(np.abs(r - 50) / 50, 1).fillna(0).values, "osc"),
        "BB_PCTB":    (np.where(b < 0.1, 1, np.where(b > 0.9, -1, 0)),
                                                        np.minimum(np.abs(b - 0.5) / 0.5, 1).fillna(0).values, "osc"),
        "VDELTA":     (sign(vdelta).values,             vdelta.abs().fillna(0).values,              "flow"),
        "ATR_PCT":    (np.zeros(len(df), dtype=int),    atr_pct.fillna(0).values,                   "vol"),
        "WICK_IMB":   (sign(wick_imb).values,           wick_imb.abs().fillna(0).values,            "micro"),
    }
    return ind


# Regime-weighted multipliers
MULT = {
    REGIME["TREND_UP"]:        {"trend":1.2, "mom":1.1, "osc":0.5, "flow":1.3, "vol":1.0, "micro":1.1},
    REGIME["TREND_DOWN"]:      {"trend":1.2, "mom":1.1, "osc":0.5, "flow":1.3, "vol":1.0, "micro":1.1},
    REGIME["SIDEWAYS"]:        {"trend":1.0, "mom":0.7, "osc":1.5, "flow":0.7, "vol":1.0, "micro":0.6},
    REGIME["VOLATILE_TREND"]:  {"trend":1.0, "mom":1.0, "osc":0.4, "flow":1.4, "vol":1.2, "micro":1.2},
    REGIME["VOLATILE_CHOPPY"]: {"trend":0.6, "mom":0.6, "osc":0.8, "flow":0.7, "vol":0.5, "micro":0.5},
    REGIME["UNKNOWN"]:         {"trend":1.0, "mom":1.0, "osc":1.0, "flow":1.0, "vol":1.0, "micro":1.0},
}


def confidence(ind, regime_series):
    """Compute regime-weighted confidence per bar ∈ [-1, +1]."""
    N = len(regime_series)
    score = np.zeros(N)
    max_weight = np.zeros(N)
    reg = regime_series.values
    for bar in range(N):
        m = MULT[reg[bar]]
        s = 0.0
        mw = 0.0
        for name, (dir_arr, str_arr, cat) in ind.items():
            w = m[cat]
            s  += float(dir_arr[bar]) * float(str_arr[bar]) * w
            mw += w
        score[bar] = s
        max_weight[bar] = mw if mw > 0 else 1
    # normalize then squash
    normalized = score / max_weight
    return np.tanh(normalized * 3)  # sharper squash


# -------- data --------
def load(sym, tf):
    files = sorted((DATA / sym / tf).glob("year=*/part.parquet"))
    dfs = [pd.read_parquet(f) for f in files]
    d = pd.concat(dfs, ignore_index=True)
    d = d.drop_duplicates("open_time").sort_values("open_time").set_index("open_time")
    d = d[(d.index >= pd.Timestamp(START, tz="UTC")) & (d.index < pd.Timestamp(END, tz="UTC"))]
    return d[["open","high","low","close","volume"]].astype("float64")


# -------- simulator --------
def simulate(df, conf_enter=0.65, sl_mult=2.0, tp_mult=5.0, trail_after=2.0,
             lockout=96, max_loss_in_dd=0.05):
    """Very strict: conf ≥ 0.65 (was 0.35), lockout 24h (was 2h),
    wider targets (5:2 R:R), long/short only in actual TREND regimes."""

    reg = classify_regime(df)
    ind = build_indicators(df)
    conf = confidence(ind, reg)
    a = atr(df).values

    # Extreme-candle veto
    atr_roll = pd.Series(a, index=df.index).rolling(100).mean().values
    bar_range = (df["high"] - df["low"]).values
    extreme = bar_range > 3 * atr_roll

    # Session filter: skip 00:00-04:00 UTC (low-liquidity hours)
    hours = df.index.hour.values
    session_ok = ~((hours >= 0) & (hours < 4))

    op, hi, lo, cl = (df["open"].values, df["high"].values,
                      df["low"].values,  df["close"].values)

    N = len(df)
    cash = INIT
    equity = np.empty(N); equity[0] = INIT
    pos = 0
    entry = sl = tp = 0.0
    size = 0.0
    hh = ll = 0.0
    entry_idx = 0
    last_exit_idx = -999
    trades = []
    peak_eq = INIT

    for i in range(1, N - 1):
        peak_eq = max(peak_eq, equity[i-1])
        dd_now = equity[i-1] / peak_eq - 1

        if pos == 1:
            hh = max(hh, hi[i])
            if hh - entry >= trail_after * a[i]:
                new_sl = hh - sl_mult * a[i]
                if new_sl > sl: sl = new_sl
            if lo[i] <= sl:
                exit_p = sl * (1 - SLIP)
                ret = (exit_p / entry - 1) - 2 * FEE
                cash = cash + size * (exit_p - entry) - size * (entry + exit_p) * FEE
                trades.append(dict(side=1, entry=entry, exit=exit_p, ret=ret,
                                   reason="SL", bars=i-entry_idx,
                                   regime=int(reg.iloc[i]), conf=float(conf[i-1])))
                pos = 0; last_exit_idx = i; continue
            if hi[i] >= tp:
                exit_p = tp * (1 - SLIP)
                ret = (exit_p / entry - 1) - 2 * FEE
                cash = cash + size * (exit_p - entry) - size * (entry + exit_p) * FEE
                trades.append(dict(side=1, entry=entry, exit=exit_p, ret=ret,
                                   reason="TP", bars=i-entry_idx,
                                   regime=int(reg.iloc[i]), conf=float(conf[i-1])))
                pos = 0; last_exit_idx = i; continue
        elif pos == -1:
            ll = min(ll, lo[i])
            if entry - ll >= trail_after * a[i]:
                new_sl = ll + sl_mult * a[i]
                if new_sl < sl: sl = new_sl
            if hi[i] >= sl:
                exit_p = sl * (1 + SLIP)
                ret = (entry / exit_p - 1) - 2 * FEE
                cash = cash + size * (entry - exit_p) - size * (entry + exit_p) * FEE
                trades.append(dict(side=-1, entry=entry, exit=exit_p, ret=ret,
                                   reason="SL", bars=i-entry_idx,
                                   regime=int(reg.iloc[i]), conf=float(conf[i-1])))
                pos = 0; last_exit_idx = i; continue
            if lo[i] <= tp:
                exit_p = tp * (1 + SLIP)
                ret = (entry / exit_p - 1) - 2 * FEE
                cash = cash + size * (entry - exit_p) - size * (entry + exit_p) * FEE
                trades.append(dict(side=-1, entry=entry, exit=exit_p, ret=ret,
                                   reason="TP", bars=i-entry_idx,
                                   regime=int(reg.iloc[i]), conf=float(conf[i-1])))
                pos = 0; last_exit_idx = i; continue

        if pos == 0 and i + 1 < N and (i - last_exit_idx) > lockout:
            if not session_ok[i]:       continue
            if extreme[i-1]:            continue
            r = reg.iloc[i]
            c = conf[i]

            # Direction gate
            want_long  = False
            want_short = False
            if r == REGIME["TREND_UP"]:
                want_long  = c > conf_enter
            elif r == REGIME["TREND_DOWN"]:
                want_short = c < -conf_enter
            # ALL other regimes (SIDEWAYS / VOLATILE_*): FLAT — only clean trends.

            size_frac = 0.20                            # 20 % of equity per trade
            if dd_now < -max_loss_in_dd:
                size_frac *= 0.5                        # halve in drawdown

            if r == REGIME["VOLATILE_TREND"]:
                size_frac *= 0.5                        # halve in high-vol

            if want_long:
                entry = op[i+1] * (1 + SLIP)
                sl = entry - sl_mult * a[i]
                tp = entry + tp_mult * a[i]
                size = (cash * size_frac) / entry
                pos = 1; entry_idx = i+1; hh = entry
            elif want_short:
                entry = op[i+1] * (1 - SLIP)
                sl = entry + sl_mult * a[i]
                tp = entry - tp_mult * a[i]
                size = (cash * size_frac) / entry
                pos = -1; entry_idx = i+1; ll = entry

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
    return trades, pd.Series(equity, index=df.index), reg


# -------- metrics --------
def metrics(eq, trades):
    rets = eq.pct_change().dropna()
    if len(rets) < 2 or len(trades) == 0:
        return dict(final=float(eq.iloc[-1]), n_trades=0)
    dt = rets.index.to_series().diff().median()
    bpy = pd.Timedelta(days=365.25) / dt if dt else 1
    mu, sd = rets.mean(), rets.std()
    dn = rets[rets < 0].std()
    sh = (mu / sd) * np.sqrt(bpy) if sd else 0
    so = (mu / dn) * np.sqrt(bpy) if dn else 0
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25*86400)
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1/max(yrs, 1e-6)) - 1
    dd = float((eq / eq.cummax() - 1).min())
    pnl = np.array([t["ret"] for t in trades])
    w, l = pnl[pnl>0], pnl[pnl<0]
    pf = w.sum() / abs(l.sum()) if len(l) else 0
    longs  = [t for t in trades if t["side"] == 1]
    shorts = [t for t in trades if t["side"] == -1]
    long_wins  = sum(1 for t in longs  if t["ret"]>0)
    short_wins = sum(1 for t in shorts if t["ret"]>0)
    return dict(
        final=float(eq.iloc[-1]),
        cagr=float(cagr),
        sharpe=float(sh), sortino=float(so),
        max_dd=dd, calmar=float(cagr/abs(dd)) if dd else 0,
        n_trades=len(trades),
        n_longs=len(longs), n_shorts=len(shorts),
        long_win_rate=long_wins/len(longs) if longs else 0,
        short_win_rate=short_wins/len(shorts) if shorts else 0,
        win_rate=float((pnl>0).mean()),
        profit_factor=float(pf),
        avg_win_pct=float(w.mean()) if len(w) else 0,
        avg_loss_pct=float(l.mean()) if len(l) else 0,
        max_cw=max_streak(pnl, True),
        max_cl=max_streak(pnl, False),
    )


def max_streak(pnl, wins):
    best = cur = 0
    for p in pnl:
        if (p > 0) if wins else (p < 0):
            cur += 1; best = max(best, cur)
        else:
            cur = 0
    return int(best)


def main():
    rows = []
    t0 = time.time()
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        t = time.time()
        df = load(sym, "15m")
        trades, eq, reg = simulate(df)
        m = metrics(eq, trades)
        bh = float(df["close"].iloc[-1] / df["close"].iloc[0] - 1)
        rows.append({"symbol": sym, **m, "bh_return": bh})
        print(f"  {sym}/15m  n={m['n_trades']:<4d} "
              f"(L={m['n_longs']},S={m['n_shorts']})  "
              f"CAGR={m['cagr']*100:+7.2f}%  Sharpe={m['sharpe']:>5.2f}  "
              f"DD={m['max_dd']*100:+7.2f}%  PF={m['profit_factor']:.2f}  "
              f"W%={m['win_rate']*100:>5.1f} (L={m['long_win_rate']*100:.0f},S={m['short_win_rate']*100:.0f})  "
              f"Final=${m['final']:>10,.0f}  BH={bh*100:+.0f}%  "
              f"({time.time()-t:.1f}s)", flush=True)
        eq.to_csv(OUT / f"V9_{sym}_equity.csv")

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "V9_chimera.csv", index=False)
    print(f"\nSaved V9_chimera.csv  total {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
