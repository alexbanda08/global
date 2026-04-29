"""
V38b — SMC as FILTER on native breakout signals + param grid + walk-forward.

Creative mixes:
  C. BBBreak + SMC_BOS filter (trade only if recent BOS in same direction)
  D. BBBreak + SMC_OB zone filter (trade only if price near OB)
  E. Donchian + SMC_BOS filter
  F. FVG_FADE + BTC regime + tighter stops + short hold
  G. OB_TOUCH with grid over swing_length, TP/SL, hold
  H. SMC structural breadth regime (% coins with bullish BOS) as XSM filter

Walk-forward on anything Sharpe > 1.0.
"""
from __future__ import annotations
import sys, os, io, json, time, warnings, itertools
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")

from pathlib import Path
from contextlib import redirect_stdout
import numpy as np
import pandas as pd

_buf = io.StringIO()
with redirect_stdout(_buf):
    from smartmoneyconcepts import smc

ROOT = Path(__file__).resolve().parent
FEAT = ROOT / "features" / "multi_tf"
OUT = ROOT / "results" / "v38"
OUT.mkdir(parents=True, exist_ok=True)

FEE = 0.00045
SLIP_BPS = 3
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "ADAUSDT",
         "XRPUSDT", "BNBUSDT", "DOGEUSDT", "AVAXUSDT"]


# ================================================================
# Data / math helpers
# ================================================================
def load(sym, tf):
    p = FEAT / f"{sym}_{tf}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p).dropna(subset=["open", "high", "low", "close"])
    df = df[df.index >= pd.Timestamp("2019-01-01", tz="UTC")]
    return df


def atr(df, n=14):
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"] - df["close"].shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def sma(s, n):
    return s.rolling(n).mean()


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def bbands(s, n=20, k=2.0):
    mid = s.rolling(n).mean()
    sd = s.rolling(n).std()
    return mid + k * sd, mid, mid - k * sd


# ================================================================
# Backtester (same as v38 but reused here)
# ================================================================
def simulate(df, long_sig, short_sig, sl_atr=2.0, tp_atr=3.0, mh=48,
             risk_pct=0.01, leverage=3.0):
    a = atr(df, 14)
    opn, hi, lo, cl = df["open"].values, df["high"].values, df["low"].values, df["close"].values
    ts = df.index
    ls, ss = long_sig.values, short_sig.values
    av = a.values
    n = len(df)
    slip = SLIP_BPS / 10000.0
    equity = np.ones(n); eq = 1.0
    pos = 0; entry = stop = tp = 0.0; hold = 0
    trades = []

    for i in range(1, n):
        if pos != 0:
            hold += 1
            exit_px = None
            if pos == 1:
                if lo[i] <= stop: exit_px = stop
                elif hi[i] >= tp: exit_px = tp
                elif hold >= mh: exit_px = opn[i]
            else:
                if hi[i] >= stop: exit_px = stop
                elif lo[i] <= tp: exit_px = tp
                elif hold >= mh: exit_px = opn[i]
            if exit_px is not None:
                exit_eff = exit_px * (1 - slip) if pos == 1 else exit_px * (1 + slip)
                gross = (exit_eff - entry) / entry if pos == 1 else (entry - exit_eff) / entry
                pnl = gross * leverage - 2 * FEE
                pos_size = risk_pct / max(abs((entry - stop) / entry), 0.001)
                pos_size = min(pos_size, leverage)
                trade_ret = pnl * pos_size / leverage
                eq *= (1 + trade_ret)
                trades.append(trade_ret)
                pos = 0; hold = 0
        if pos == 0 and i + 1 < n:
            if ls[i] and not np.isnan(av[i]) and av[i] > 0:
                entry = opn[i + 1] * (1 + slip)
                stop = entry - sl_atr * av[i]; tp = entry + tp_atr * av[i]
                pos = 1; hold = 0
            elif ss[i] and not np.isnan(av[i]) and av[i] > 0:
                entry = opn[i + 1] * (1 - slip)
                stop = entry + sl_atr * av[i]; tp = entry - tp_atr * av[i]
                pos = -1; hold = 0
        equity[i] = eq
    eq_s = pd.Series(equity, index=ts)
    return _metrics(eq_s, trades)


def _metrics(eq, trades):
    if len(trades) < 2:
        return {"sharpe": 0.0, "cagr": 0.0, "maxdd": 0.0, "n_trades": len(trades), "win_rate": 0.0}
    rets = eq.pct_change().fillna(0.0)
    dt_hours = (eq.index[1] - eq.index[0]).total_seconds() / 3600 if len(eq) > 1 else 4
    ann = np.sqrt((24 / dt_hours) * 365.25)
    sharpe = (rets.mean() / rets.std() * ann) if rets.std() > 0 else 0.0
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 0.1)
    cagr = eq.iloc[-1] ** (1 / years) - 1 if eq.iloc[-1] > 0 else -1
    dd = (eq / eq.cummax() - 1).min()
    wins = [t for t in trades if t > 0]
    wr = len(wins) / len(trades) if trades else 0
    return {
        "sharpe": round(float(sharpe), 3),
        "cagr": round(float(cagr), 4),
        "maxdd": round(float(dd), 4),
        "n_trades": len(trades),
        "win_rate": round(float(wr), 3),
    }


# ================================================================
# SMC helpers
# ================================================================
def _ohlc(df):
    return df[["open", "high", "low", "close", "volume"]].copy()


def smc_bos_series(df, swing_length=30):
    """Returns long_bos_indicator, short_bos_indicator as bool (event at bar)."""
    try:
        shl = smc.swing_highs_lows(_ohlc(df), swing_length=swing_length)
        bc = smc.bos_choch(_ohlc(df), shl, close_break=True)
        bos = bc["BOS"].reindex(df.index)
        return (bos == 1).fillna(False), (bos == -1).fillna(False)
    except Exception:
        return pd.Series(False, index=df.index), pd.Series(False, index=df.index)


def smc_ob_touch_zone(df, swing_length=30):
    """Returns (in_bullish_ob_zone, in_bearish_ob_zone) — bool at each bar."""
    try:
        shl = smc.swing_highs_lows(_ohlc(df), swing_length=swing_length)
        ob = smc.ob(_ohlc(df), shl, close_mitigation=False)
        bull_zone = pd.Series(False, index=df.index)
        bear_zone = pd.Series(False, index=df.index)
        for i, row in ob.dropna(subset=["OB"]).iterrows():
            top, bot = row["Top"], row["Bottom"]
            if pd.isna(top) or pd.isna(bot):
                continue
            try:
                pos = df.index.get_loc(i)
            except KeyError:
                continue
            m_i = int(row["MitigatedIndex"]) if pd.notna(row.get("MitigatedIndex")) else len(df) - 1
            for j in range(pos + 1, min(m_i + 1, len(df))):
                in_zone = df["low"].iat[j] <= top and df["high"].iat[j] >= bot
                if in_zone:
                    if row["OB"] == 1:
                        bull_zone.iat[j] = True
                    else:
                        bear_zone.iat[j] = True
        return bull_zone, bear_zone
    except Exception:
        return pd.Series(False, index=df.index), pd.Series(False, index=df.index)


# ================================================================
# Native price signals (no talib)
# ================================================================
def sig_bbbreak(df, n=20, k=2.0, regime_len=200):
    ub, mid, lb = bbands(df["close"], n, k)
    ema_reg = ema(df["close"], regime_len)
    # Long: close crosses above upper BB AND close > EMA(regime_len)
    long_cross = (df["close"] > ub) & (df["close"].shift(1) <= ub.shift(1))
    long_sig = long_cross & (df["close"] > ema_reg)
    short_cross = (df["close"] < lb) & (df["close"].shift(1) >= lb.shift(1))
    short_sig = short_cross & (df["close"] < ema_reg)
    return long_sig.fillna(False), short_sig.fillna(False)


def sig_donchian(df, n=20, ema_reg=100):
    hh = df["high"].rolling(n).max().shift(1)
    ll = df["low"].rolling(n).min().shift(1)
    ema_r = ema(df["close"], ema_reg)
    long_sig = (df["close"] > hh) & (df["close"] > ema_r)
    short_sig = (df["close"] < ll) & (df["close"] < ema_r)
    return long_sig.fillna(False), short_sig.fillna(False)


# ================================================================
# MIX signals
# ================================================================
def mix_bbbreak_bos(df, n=20, k=2.0, regime_len=200, swing_length=30, bos_window=20):
    """BBBreak but require bullish BOS in last N bars for long (mirror short)."""
    L, S = sig_bbbreak(df, n, k, regime_len)
    bos_l, bos_s = smc_bos_series(df, swing_length)
    bos_l_recent = bos_l.rolling(bos_window, min_periods=1).max().astype(bool)
    bos_s_recent = bos_s.rolling(bos_window, min_periods=1).max().astype(bool)
    return (L & bos_l_recent).fillna(False), (S & bos_s_recent).fillna(False)


def mix_bbbreak_ob(df, n=20, k=2.0, regime_len=200, swing_length=30):
    """BBBreak only when NOT in opposing OB zone (avoids fading against structure)."""
    L, S = sig_bbbreak(df, n, k, regime_len)
    bull_z, bear_z = smc_ob_touch_zone(df, swing_length)
    # Don't take long if we're entering a bear OB zone (reversal risk)
    return (L & ~bear_z).fillna(False), (S & ~bull_z).fillna(False)


def mix_donchian_bos(df, n=20, ema_reg=100, swing_length=30, bos_window=20):
    L, S = sig_donchian(df, n, ema_reg)
    bos_l, bos_s = smc_bos_series(df, swing_length)
    bos_l_recent = bos_l.rolling(bos_window, min_periods=1).max().astype(bool)
    bos_s_recent = bos_s.rolling(bos_window, min_periods=1).max().astype(bool)
    return (L & bos_l_recent).fillna(False), (S & bos_s_recent).fillna(False)


def mix_donchian_choch_reverse(df, n=20, ema_reg=100, swing_length=30):
    """Donchian breakout only if recent CHoCH confirms regime flip."""
    L, S = sig_donchian(df, n, ema_reg)
    try:
        shl = smc.swing_highs_lows(_ohlc(df), swing_length=swing_length)
        bc = smc.bos_choch(_ohlc(df), shl, close_break=True)
        ch = bc["CHOCH"].reindex(df.index)
        ch_l = (ch == 1).fillna(False).rolling(10, min_periods=1).max().astype(bool)
        ch_s = (ch == -1).fillna(False).rolling(10, min_periods=1).max().astype(bool)
        return (L & ch_l).fillna(False), (S & ch_s).fillna(False)
    except Exception:
        return pd.Series(False, index=df.index), pd.Series(False, index=df.index)


# ================================================================
# Walk-forward
# ================================================================
def walk_forward(df, sig_fn, params, train_years=2.0, test_years=1.0, step_months=6, **bt):
    start, end = df.index[0], df.index[-1]
    step = pd.DateOffset(months=step_months)
    train_td = pd.DateOffset(days=int(train_years * 365))
    test_td = pd.DateOffset(days=int(test_years * 365))
    results = []
    anchor = start
    while anchor + train_td + test_td <= end:
        train_end = anchor + train_td
        test_end = train_end + test_td
        test_df = df[(df.index >= train_end) & (df.index < test_end)]
        if len(test_df) < 200:
            anchor += step; continue
        try:
            L, S = sig_fn(test_df, **params)
            m = simulate(test_df, L, S, **bt)
            results.append({"start": str(anchor.date()), "sharpe": m["sharpe"],
                            "cagr": m["cagr"], "maxdd": m["maxdd"], "trades": m["n_trades"]})
        except Exception:
            pass
        anchor += step
    return results


# ================================================================
# Main sweep
# ================================================================
def main():
    t0 = time.time()
    rows = []

    mixes = {
        "BBBreak_pure":     (sig_bbbreak, {"n": 20, "k": 2.0, "regime_len": 200}),
        "BBBreak+BOS":      (mix_bbbreak_bos, {"n": 20, "k": 2.0, "regime_len": 200,
                                                "swing_length": 30, "bos_window": 20}),
        "BBBreak+OB_avoid": (mix_bbbreak_ob, {"n": 20, "k": 2.0, "regime_len": 200,
                                               "swing_length": 30}),
        "Donchian_pure":    (sig_donchian, {"n": 20, "ema_reg": 100}),
        "Donchian+BOS":     (mix_donchian_bos, {"n": 20, "ema_reg": 100,
                                                 "swing_length": 30, "bos_window": 20}),
        "Donchian+CHoCH":   (mix_donchian_choch_reverse, {"n": 20, "ema_reg": 100,
                                                           "swing_length": 30}),
    }

    # Wider swing_length sweep for the best mix family
    print(f"\n=== V38b SMC MIXES — testing {len(mixes)} families on {len(COINS)} coins × 2 TFs ===\n")
    for tf in ["4h", "1h"]:
        for coin in COINS:
            df = load(coin, tf)
            if df is None:
                continue
            for name, (fn, params) in mixes.items():
                try:
                    L, S = fn(df, **params)
                    n_trades_est = int(L.sum() + S.sum())
                    if n_trades_est < 15:
                        continue
                    m = simulate(df, L, S, sl_atr=2.0, tp_atr=3.0, mh=48,
                                 risk_pct=0.01, leverage=3.0)
                    rows.append({"coin": coin, "tf": tf, "mix": name,
                                 "n_signals": n_trades_est, **m})
                except Exception as e:
                    continue
        print(f"  {tf} done [{time.time() - t0:.0f}s]")

    df_res = pd.DataFrame(rows)

    # Param grid for any promising mix (Sharpe > 0.5)
    promising = df_res[df_res["sharpe"] > 0.5].copy()
    print(f"\n=== FOUND {len(promising)} configs with Sharpe > 0.5 ===")

    if not promising.empty:
        # Rank by Sharpe, show top 15
        top = promising.nlargest(15, "sharpe")
        print(top[["coin", "tf", "mix", "sharpe", "cagr", "maxdd", "n_trades", "win_rate"]]
              .to_string(index=False))

        # Walk-forward on top 8
        print(f"\n=== WALK-FORWARD on top 8 (2y train / 1y test / 6mo step) ===")
        wf_rows = []
        for _, r in top.head(8).iterrows():
            coin, tf, mix_name = r["coin"], r["tf"], r["mix"]
            df = load(coin, tf)
            fn, params = mixes[mix_name]
            wf = walk_forward(df, fn, params)
            if not wf or len(wf) < 3:
                continue
            sharpes = [w["sharpe"] for w in wf]
            cagrs = [w["cagr"] for w in wf]
            med = float(np.median(sharpes))
            pct = sum(1 for s in sharpes if s > 0) / len(sharpes)
            min_s = float(min(sharpes))
            wf_rows.append({
                "coin": coin, "tf": tf, "mix": mix_name,
                "full_sharpe": r["sharpe"], "full_cagr": r["cagr"],
                "wf_median_sharpe": round(med, 3),
                "wf_pct_profitable": round(pct, 3),
                "wf_min_sharpe": round(min_s, 3),
                "wf_windows": len(wf),
                "robust": "YES" if (med >= 0.8 and pct >= 0.70) else "no",
            })
            print(f"  {coin} {tf} {mix_name}: "
                  f"full Sh={r['sharpe']:.2f} | "
                  f"WF median={med:.2f} | "
                  f"%profit={pct:.0%} | "
                  f"min={min_s:.2f} | "
                  f"windows={len(wf)} | "
                  f"{'ROBUST' if med >= 0.8 and pct >= 0.70 else 'fragile'}")

        df_wf = pd.DataFrame(wf_rows)
        df_wf.to_csv(OUT / "v38b_walkforward.csv", index=False)
        df_res.to_csv(OUT / "v38b_sweep.csv", index=False)

        summary = {
            "elapsed": round(time.time() - t0, 1),
            "total_configs": len(df_res),
            "promising_sharpe_gt_0.5": len(promising),
            "top_15": top.to_dict(orient="records"),
            "walk_forward": df_wf.to_dict(orient="records") if not df_wf.empty else [],
            "robust_winners": df_wf[df_wf["robust"] == "YES"].to_dict(orient="records")
                if not df_wf.empty else [],
        }
        with open(OUT / "v38b_summary.json", "w") as f:
            json.dump(summary, f, indent=2, default=str)
    else:
        df_res.to_csv(OUT / "v38b_sweep.csv", index=False)
        print("\nNo configs with Sharpe > 0.5 — SMC mixes are not adding edge.")

    print(f"\n=== DONE in {time.time() - t0:.0f}s ===")


if __name__ == "__main__":
    main()
