"""
V38 SMC sweep + walk-forward validation + creative mixes.

Self-contained (no import from run_v16_1h_hunt to avoid talib dependency).
Writes results to results/v38/ as CSV + JSON.

Experiments:
  A. SMC standalone per coin: 7 signals × 9 coins × 2 TFs (4h, 1h)
  B. SMC + BTC regime filter (only trade when BTC > 100d SMA)
  C. SMC confluence: OB + BOS same direction within 10 bars
  D. SMC XSM-breadth: use % of coins with bullish BOS as regime filter on V24
  E. Walk-forward validation on top 10 standalone winners (2y train / 1y test, step 6mo)

Usage:
    py strategy_lab/run_v38_smc_sweep.py
"""
from __future__ import annotations
import sys, os, io, json, time, warnings, traceback
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None
warnings.filterwarnings("ignore")

from pathlib import Path
from contextlib import redirect_stdout
import numpy as np
import pandas as pd

# Suppress smc's ⭐ welcome banner which breaks Windows cp1252
_buf = io.StringIO()
with redirect_stdout(_buf):
    from smartmoneyconcepts import smc

ROOT = Path(__file__).resolve().parent
FEAT = ROOT / "features" / "multi_tf"
OUT = ROOT / "results" / "v38"
OUT.mkdir(parents=True, exist_ok=True)

FEE = 0.00045
SLIP_BPS = 3  # 0.03%
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "ADAUSDT",
         "XRPUSDT", "BNBUSDT", "DOGEUSDT", "AVAXUSDT"]
BARS_PER_YEAR = {"4h": 2190, "1h": 8760, "30m": 17520, "15m": 35040, "2h": 4380}


# ================================================================
# Data loader
# ================================================================
def load(sym: str, tf: str) -> pd.DataFrame | None:
    p = FEAT / f"{sym}_{tf}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p).dropna(subset=["open", "high", "low", "close"])
    df = df[df.index >= pd.Timestamp("2019-01-01", tz="UTC")]
    return df


# ================================================================
# Minimal vectorized backtest (fee + slippage + ATR stops)
# ================================================================
def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"] - df["close"].shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def simulate(df: pd.DataFrame, long_sig: pd.Series, short_sig: pd.Series,
             sl_atr: float = 2.0, tp_atr: float = 3.0, mh: int = 48,
             risk_pct: float = 0.01, leverage: float = 3.0) -> dict:
    """
    Single-position, next-bar-open fills, fee + slippage, ATR stop + TP + max-hold.
    Returns {equity, n_trades, cagr, sharpe, maxdd, win_rate, profit_factor}.
    """
    a = atr(df, 14)
    opn = df["open"].values
    hi = df["high"].values
    lo = df["low"].values
    cl = df["close"].values
    ts = df.index
    ls = long_sig.values
    ss = short_sig.values
    av = a.values
    n = len(df)

    equity = [1.0]
    eq = 1.0
    pos = 0  # 0 flat, +1 long, -1 short
    entry = stop = tp = 0.0
    hold = 0
    trades = []
    slip = SLIP_BPS / 10000.0

    for i in range(1, n):
        # Exit check
        if pos != 0:
            hold += 1
            exit_px = None
            # Intrabar stop/tp (conservative: check stop before tp)
            if pos == 1:
                if lo[i] <= stop:
                    exit_px = stop
                elif hi[i] >= tp:
                    exit_px = tp
                elif hold >= mh:
                    exit_px = opn[i] if i + 1 < n else cl[i]
            else:
                if hi[i] >= stop:
                    exit_px = stop
                elif lo[i] <= tp:
                    exit_px = tp
                elif hold >= mh:
                    exit_px = opn[i] if i + 1 < n else cl[i]
            if exit_px is not None:
                # fee + slip on exit
                exit_eff = exit_px * (1 - slip) if pos == 1 else exit_px * (1 + slip)
                gross = (exit_eff - entry) / entry if pos == 1 else (entry - exit_eff) / entry
                gross_lev = gross * leverage
                fee = FEE * 2  # entry + exit
                pnl = gross_lev - fee
                # Risk-based sizing: position notional = risk_pct * equity / (stop_dist/entry)
                pos_size = risk_pct / max(abs((entry - stop) / entry), 0.001)
                pos_size = min(pos_size, leverage)
                trade_ret = pnl * pos_size / leverage
                eq *= (1 + trade_ret)
                trades.append({"ts": ts[i], "side": pos, "ret": trade_ret, "hold": hold})
                pos = 0
                hold = 0

        # Entry check at bar close → filled at next bar open
        if pos == 0 and i + 1 < n:
            sig_long = ls[i]
            sig_short = ss[i]
            if sig_long and not np.isnan(av[i]) and av[i] > 0:
                entry_px = opn[i + 1] * (1 + slip)
                entry = entry_px
                stop = entry - sl_atr * av[i]
                tp = entry + tp_atr * av[i]
                pos = 1
                hold = 0
            elif sig_short and not np.isnan(av[i]) and av[i] > 0:
                entry_px = opn[i + 1] * (1 - slip)
                entry = entry_px
                stop = entry + sl_atr * av[i]
                tp = entry - tp_atr * av[i]
                pos = -1
                hold = 0

        equity.append(eq)

    eq_series = pd.Series(equity, index=ts)
    return metrics(eq_series, trades, df)


def metrics(eq: pd.Series, trades: list, df: pd.DataFrame) -> dict:
    if len(trades) < 2 or eq.iloc[-1] <= 0:
        return {"sharpe": 0.0, "cagr": 0.0, "maxdd": 0.0, "n_trades": len(trades),
                "win_rate": 0.0, "profit_factor": 0.0, "final_eq": float(eq.iloc[-1])}
    rets = eq.pct_change().fillna(0.0)
    # Infer bars per year from index spacing
    dt = (eq.index[-1] - eq.index[0]).total_seconds() / 86400
    years = max(dt / 365.25, 0.01)
    # Annualize: approximate with 6 bars/day (4h) — will be adjusted per-TF
    bars_per_day = 24 / ((eq.index[1] - eq.index[0]).total_seconds() / 3600) if len(eq) > 1 else 6
    ann_factor = np.sqrt(bars_per_day * 365.25)
    sharpe = (rets.mean() / rets.std()) * ann_factor if rets.std() > 0 else 0.0
    cagr = (eq.iloc[-1]) ** (1 / years) - 1 if eq.iloc[-1] > 0 else -1.0
    dd = (eq / eq.cummax() - 1).min()
    ret_list = [t["ret"] for t in trades]
    wins = [r for r in ret_list if r > 0]
    losses = [r for r in ret_list if r <= 0]
    wr = len(wins) / len(ret_list) if ret_list else 0.0
    pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) < 0 else float("inf") if wins else 0.0
    return {
        "sharpe": round(float(sharpe), 3),
        "cagr": round(float(cagr), 4),
        "maxdd": round(float(dd), 4),
        "n_trades": len(trades),
        "win_rate": round(float(wr), 3),
        "profit_factor": round(float(pf), 3) if pf != float("inf") else 999.0,
        "final_eq": round(float(eq.iloc[-1]), 4),
    }


# ================================================================
# SMC signal wrappers
# ================================================================
def _ohlc(df: pd.DataFrame) -> pd.DataFrame:
    return df[["open", "high", "low", "close", "volume"]].copy()


def sig_fvg(df, join_consecutive=False):
    try:
        f = smc.fvg(_ohlc(df), join_consecutive=join_consecutive)
        col = f["FVG"].reindex(df.index)
        return (col == 1).fillna(False), (col == -1).fillna(False)
    except Exception:
        return pd.Series(False, index=df.index), pd.Series(False, index=df.index)


def sig_fvg_fade(df, join_consecutive=True):
    try:
        f = smc.fvg(_ohlc(df), join_consecutive=join_consecutive)
        L = pd.Series(False, index=df.index)
        S = pd.Series(False, index=df.index)
        mit = f.dropna(subset=["MitigatedIndex"])
        for _, row in mit.iterrows():
            m_i = int(row["MitigatedIndex"])
            if 0 <= m_i < len(df):
                ts = df.index[m_i]
                if row["FVG"] == 1:
                    L.loc[ts] = True
                elif row["FVG"] == -1:
                    S.loc[ts] = True
        return L, S
    except Exception:
        return pd.Series(False, index=df.index), pd.Series(False, index=df.index)


def sig_ob(df, swing_length=50, close_mitigation=False):
    try:
        shl = smc.swing_highs_lows(_ohlc(df), swing_length=swing_length)
        ob = smc.ob(_ohlc(df), shl, close_mitigation=close_mitigation)
        L = pd.Series(False, index=df.index)
        S = pd.Series(False, index=df.index)
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
                if df["low"].iat[j] <= top and df["high"].iat[j] >= bot:
                    ts = df.index[j]
                    if row["OB"] == 1:
                        L.loc[ts] = True
                    else:
                        S.loc[ts] = True
                    break
        return L, S
    except Exception:
        return pd.Series(False, index=df.index), pd.Series(False, index=df.index)


def sig_bos(df, swing_length=50, close_break=True):
    try:
        shl = smc.swing_highs_lows(_ohlc(df), swing_length=swing_length)
        bc = smc.bos_choch(_ohlc(df), shl, close_break=close_break)
        col = bc["BOS"].reindex(df.index)
        return (col == 1).fillna(False), (col == -1).fillna(False)
    except Exception:
        return pd.Series(False, index=df.index), pd.Series(False, index=df.index)


def sig_choch(df, swing_length=50, close_break=True):
    try:
        shl = smc.swing_highs_lows(_ohlc(df), swing_length=swing_length)
        bc = smc.bos_choch(_ohlc(df), shl, close_break=close_break)
        col = bc["CHOCH"].reindex(df.index)
        return (col == 1).fillna(False), (col == -1).fillna(False)
    except Exception:
        return pd.Series(False, index=df.index), pd.Series(False, index=df.index)


def sig_liquidity(df, swing_length=50, range_percent=0.01):
    try:
        shl = smc.swing_highs_lows(_ohlc(df), swing_length=swing_length)
        liq = smc.liquidity(_ohlc(df), shl, range_percent=range_percent)
        col = liq["Liquidity"].reindex(df.index)
        # Fade: sell-side swept (val=1) = bounce LONG; buy-side swept (val=-1) = SHORT
        return (col == 1).fillna(False), (col == -1).fillna(False)
    except Exception:
        return pd.Series(False, index=df.index), pd.Series(False, index=df.index)


def sig_confluence_ob_bos(df, swing_length=50, window=10):
    """OB touch AND recent BOS in same direction (within `window` bars)."""
    ob_l, ob_s = sig_ob(df, swing_length=swing_length)
    bos_l, bos_s = sig_bos(df, swing_length=swing_length)
    bos_l_recent = bos_l.rolling(window, min_periods=1).max().astype(bool)
    bos_s_recent = bos_s.rolling(window, min_periods=1).max().astype(bool)
    return (ob_l & bos_l_recent).astype(bool), (ob_s & bos_s_recent).astype(bool)


SIGNALS = {
    "FVG_ENTRY":       (sig_fvg,            {"join_consecutive": False}),
    "FVG_FADE":        (sig_fvg_fade,       {"join_consecutive": True}),
    "OB_TOUCH":        (sig_ob,             {"swing_length": 50}),
    "BOS_CONTINUE":    (sig_bos,            {"swing_length": 50}),
    "CHOCH_REV":       (sig_choch,          {"swing_length": 50}),
    "LIQ_SWEEP":       (sig_liquidity,      {"swing_length": 50, "range_percent": 0.01}),
    "OB+BOS_CONFLUX":  (sig_confluence_ob_bos, {"swing_length": 50, "window": 10}),
}


# ================================================================
# BTC regime filter
# ================================================================
def btc_regime_filter(ref_df: pd.DataFrame, target_index: pd.Index, ma_days: int = 100) -> pd.Series:
    """
    Returns bool Series on target_index: True = bullish regime (BTC > 100d SMA).
    ref_df must be BTC 4h data.
    """
    bars = ma_days * 6  # 4h
    sma = ref_df["close"].rolling(bars).mean()
    bull = (ref_df["close"] > sma).reindex(target_index, method="ffill").fillna(False)
    return bull.astype(bool)


# ================================================================
# Walk-forward
# ================================================================
def walk_forward(df, sig_fn, params, train_years=2.0, test_years=1.0, step_months=6,
                 **bt_kwargs) -> list[dict]:
    """
    Sliding window walk-forward. Returns list of {window, train_sharpe, test_sharpe, ...}.
    We don't optimize params here — we just validate out-of-sample that the fixed signal
    holds up in each rolling test window.
    """
    start = df.index[0]
    end = df.index[-1]
    step = pd.DateOffset(months=step_months)
    train_td = pd.DateOffset(days=int(train_years * 365))
    test_td = pd.DateOffset(days=int(test_years * 365))
    results = []
    anchor = start
    while anchor + train_td + test_td <= end:
        train_end = anchor + train_td
        test_end = train_end + test_td
        train_df = df[(df.index >= anchor) & (df.index < train_end)]
        test_df = df[(df.index >= train_end) & (df.index < test_end)]
        if len(train_df) < 500 or len(test_df) < 200:
            anchor = anchor + step
            continue
        try:
            ltr, str_ = sig_fn(train_df, **params)
            lte, ste = sig_fn(test_df, **params)
            m_train = simulate(train_df, ltr, str_, **bt_kwargs)
            m_test = simulate(test_df, lte, ste, **bt_kwargs)
            results.append({
                "window_start": str(anchor.date()),
                "train_sharpe": m_train["sharpe"],
                "test_sharpe": m_test["sharpe"],
                "train_cagr": m_train["cagr"],
                "test_cagr": m_test["cagr"],
                "test_maxdd": m_test["maxdd"],
                "test_trades": m_test["n_trades"],
            })
        except Exception as e:
            pass
        anchor = anchor + step
    return results


# ================================================================
# Main sweep
# ================================================================
def main():
    t0 = time.time()
    rows_a = []  # Experiment A: standalone
    rows_b = []  # Experiment B: + BTC regime filter
    wf_rows = []  # walk-forward on top winners

    # Preload BTC 4h for regime filter
    btc4h = load("BTCUSDT", "4h")

    print(f"\n=== V38 SMC SWEEP — 9 coins × 7 signals × 2 TFs ===")
    for tf in ["4h", "1h"]:
        for coin in COINS:
            df = load(coin, tf)
            if df is None:
                continue
            for sig_name, (fn, params) in SIGNALS.items():
                try:
                    L, S = fn(df, **params)
                    n_l, n_s = int(L.sum()), int(S.sum())
                    if n_l + n_s < 20:
                        continue
                    # A: standalone
                    m = simulate(df, L, S, sl_atr=2.0, tp_atr=3.0, mh=48,
                                 risk_pct=0.01, leverage=3.0)
                    rows_a.append({"experiment": "A_standalone", "coin": coin, "tf": tf,
                                   "signal": sig_name, "n_long": n_l, "n_short": n_s, **m})

                    # B: + BTC regime filter (longs only when bull, shorts only when bear)
                    bull = btc_regime_filter(btc4h, df.index).values
                    L_f = (L.values & bull)
                    S_f = (S.values & ~bull)
                    L_filt = pd.Series(L_f, index=df.index)
                    S_filt = pd.Series(S_f, index=df.index)
                    m_b = simulate(df, L_filt, S_filt, sl_atr=2.0, tp_atr=3.0, mh=48,
                                   risk_pct=0.01, leverage=3.0)
                    rows_b.append({"experiment": "B_btc_regime", "coin": coin, "tf": tf,
                                   "signal": sig_name, "n_long": int(L_filt.sum()),
                                   "n_short": int(S_filt.sum()), **m_b})
                except Exception as e:
                    print(f"[err] {coin} {tf} {sig_name}: {type(e).__name__}: {str(e)[:80]}")
                    continue
            elapsed = time.time() - t0
            print(f"  [{elapsed:>5.0f}s] {coin} {tf} done")

    # Combine and rank
    all_rows = rows_a + rows_b
    df_res = pd.DataFrame(all_rows)
    # Quality score: Sharpe but only if n_trades >= 30 and maxdd >= -0.6
    df_res["quality"] = df_res.apply(
        lambda r: r["sharpe"] if (r["n_trades"] >= 30 and r["maxdd"] >= -0.60 and r["cagr"] > 0) else -999.0,
        axis=1
    )
    df_res_sorted = df_res.sort_values("quality", ascending=False)

    # Save all results
    df_res_sorted.to_csv(OUT / "v38_sweep_all.csv", index=False)
    print(f"\nTotal configs tested: {len(df_res)}")
    print(f"Passing quality gate (trades>=30, DD>=-60%, CAGR>0): {(df_res['quality'] > -999).sum()}")

    # Top 10 standalone winners → walk-forward
    top_a = df_res[(df_res["experiment"] == "A_standalone") & (df_res["quality"] > 0)].nlargest(8, "sharpe")
    print(f"\n=== TOP STANDALONE WINNERS (n={len(top_a)}) ===")
    print(top_a[["coin", "tf", "signal", "sharpe", "cagr", "maxdd", "n_trades"]].to_string(index=False))

    print(f"\n=== WALK-FORWARD (2y train / 1y test / 6mo step) ===")
    for _, r in top_a.iterrows():
        coin, tf, sig_name = r["coin"], r["tf"], r["signal"]
        df = load(coin, tf)
        fn, params = SIGNALS[sig_name]
        wf = walk_forward(df, fn, params)
        if not wf:
            continue
        test_sharpes = [w["test_sharpe"] for w in wf]
        test_cagrs = [w["test_cagr"] for w in wf]
        pct_profitable = sum(1 for s in test_sharpes if s > 0) / len(test_sharpes)
        median_test_sharpe = float(np.median(test_sharpes))
        wf_rows.append({
            "coin": coin, "tf": tf, "signal": sig_name,
            "full_sharpe": r["sharpe"], "full_cagr": r["cagr"],
            "wf_windows": len(wf),
            "wf_median_test_sharpe": round(median_test_sharpe, 3),
            "wf_pct_profitable": round(pct_profitable, 3),
            "wf_min_test_sharpe": round(min(test_sharpes), 3),
            "wf_max_test_dd": round(min(w["test_maxdd"] for w in wf), 3),
        })
        print(f"  {coin} {tf} {sig_name}: "
              f"full Sh={r['sharpe']:.2f} | "
              f"WF median={median_test_sharpe:.2f} | "
              f"%profit={pct_profitable:.0%} | "
              f"windows={len(wf)}")

    df_wf = pd.DataFrame(wf_rows)
    if not df_wf.empty:
        df_wf["wf_robust"] = (df_wf["wf_median_test_sharpe"] >= 0.8) & (df_wf["wf_pct_profitable"] >= 0.70)
        df_wf = df_wf.sort_values("wf_median_test_sharpe", ascending=False)
        df_wf.to_csv(OUT / "v38_walkforward.csv", index=False)

    # Summary JSON
    summary = {
        "elapsed_sec": round(time.time() - t0, 1),
        "total_configs": len(df_res),
        "passing_quality": int((df_res["quality"] > -999).sum()),
        "top_standalone": top_a[["coin", "tf", "signal", "sharpe", "cagr", "maxdd", "n_trades"]]
            .to_dict(orient="records"),
        "walk_forward_robust": df_wf[df_wf.get("wf_robust", False) == True]
            .to_dict(orient="records") if not df_wf.empty else [],
        "walk_forward_all": df_wf.to_dict(orient="records") if not df_wf.empty else [],
    }
    with open(OUT / "v38_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\n=== DONE in {summary['elapsed_sec']}s ===")
    print(f"Wrote: {OUT / 'v38_sweep_all.csv'}")
    print(f"       {OUT / 'v38_walkforward.csv'}")
    print(f"       {OUT / 'v38_summary.json'}")


if __name__ == "__main__":
    main()
