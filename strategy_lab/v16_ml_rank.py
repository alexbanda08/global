"""
V16 — ML-ranked cross-sectional momentum.

Idea: replace the simple "14-day return" ranking in V14/V15 with a
GradientBoostingRegressor prediction of next-week return, trained on a
feature stack per coin:

  * 7d / 14d / 28d / 56d price returns (momentum at multiple horizons)
  * 28d realized volatility
  * ADX(14) — trend strength
  * RSI(14) — overbought/oversold
  * 14d / 56d momentum ratio (acceleration)
  * Return skewness over last 28d

Training / prediction protocol (walk-forward, no look-ahead):
  * At each weekly rebalance bar, collect (features, forward-7d-return)
    pairs from ALL prior history.
  * Train on last N_TRAIN bars of labelled data.
  * Predict each coin's next-7d return.
  * Long top-K predicted returns.  BTC-100d-MA bear filter gates trades.

Universe: 9 coins, 4h bars, Hyperliquid maker fees.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
import talib
from sklearn.ensemble import GradientBoostingRegressor

from strategy_lab import portfolio_audit as pa

COINS = ["BTCUSDT","ETHUSDT","SOLUSDT",
         "LINKUSDT","ADAUSDT","XRPUSDT",
         "BNBUSDT","DOGEUSDT","AVAXUSDT"]
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
BARS_PER_DAY = 6
BARS_PER_WEEK = 7 * BARS_PER_DAY


def load_all() -> dict[str, pd.DataFrame]:
    return {sym: pa.load_ohlcv(sym, STARTS[sym], END) for sym in COINS}


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    h = df["high"].values; l = df["low"].values; cv = df["close"].values
    f = pd.DataFrame(index=df.index)
    for d in (7, 14, 28, 56):
        lb = d * BARS_PER_DAY
        f[f"ret_{d}d"] = c.pct_change(lb, fill_method=None)
    rets = c.pct_change(fill_method=None)
    f["vol_28d"]  = rets.rolling(28 * BARS_PER_DAY).std()
    f["adx"]      = pd.Series(talib.ADX(h, l, cv, 14), index=df.index)
    f["rsi"]      = pd.Series(talib.RSI(cv, 14), index=df.index)
    f["mom_accel"] = f["ret_14d"] - f["ret_56d"]          # acceleration
    f["skew_28d"]  = rets.rolling(28 * BARS_PER_DAY).skew()
    return f


def v16_ml_rank(top_k: int = 4, rebal_days: int = 7,
                horizon_days: int = 7,
                train_bars: int = 4000,     # ~2.7 years of 4h bars
                btc_filter: bool = True,
                btc_ma_days: int = 100,
                min_samples: int = 500) -> tuple[pd.Series, int, dict]:
    data = load_all()
    idx = pd.DatetimeIndex(sorted(set().union(*[df.index for df in data.values()])))
    close = pd.DataFrame({s: df["close"].reindex(idx).ffill() for s, df in data.items()})
    open_ = pd.DataFrame({s: df["open"].reindex(idx).ffill() for s, df in data.items()})
    feats = {s: build_features(data[s]).reindex(idx) for s in data}
    fwd = {s: close[s].pct_change(horizon_days * BARS_PER_DAY, fill_method=None).shift(-horizon_days * BARS_PER_DAY)
           for s in close}

    btc_ma = close["BTCUSDT"].rolling(btc_ma_days * BARS_PER_DAY).mean()
    step = rebal_days * BARS_PER_DAY
    init_bars = max(56 * BARS_PER_DAY, train_bars)   # need history for features + training

    n = len(idx)
    equity = np.empty(n); equity[0] = INIT
    cash = INIT
    positions = {s: 0.0 for s in close}
    trade_legs = 0
    model_stats = {"n_fits": 0, "avg_n_samples": 0.0}
    last_model = None
    last_model_bar = -10**9

    for i in range(n):
        mv = 0.0
        for s, sh in positions.items():
            px_now = close.iloc[i][s]
            if sh != 0 and not np.isnan(px_now):
                mv += sh * px_now
        eq = cash + mv
        equity[i] = eq

        if i < init_bars or (i - init_bars) % step != 0:
            continue

        # Bear filter
        if btc_filter and not np.isnan(btc_ma.iloc[i]) and close["BTCUSDT"].iloc[i] < btc_ma.iloc[i]:
            for s in list(positions):
                if positions[s] != 0:
                    px = open_.iloc[min(i+1, n-1)][s]
                    if np.isnan(px): continue
                    gross = positions[s] * px
                    fee = abs(gross) * FEE
                    cash += gross - fee
                    trade_legs += 1
                    positions[s] = 0.0
            continue

        # Build training set from [i - train_bars, i) — labels are next-7d returns
        # (so labels are known at time i - horizon_bars back)
        horizon_bars = horizon_days * BARS_PER_DAY
        train_start = max(0, i - train_bars)
        rows_X, rows_y = [], []
        for s in close:
            start_ts = pd.Timestamp(STARTS[s], tz="UTC")
            # Valid labelled bars: features at j, label = fwd[s].iloc[j]
            # Only usable when j + horizon_bars < i (so no look-ahead)
            j_end = i - horizon_bars
            if j_end <= train_start + 100: continue
            fr = feats[s].iloc[train_start:j_end]
            yy = fwd[s].iloc[train_start:j_end]
            both = fr.join(yy.rename("y")).dropna()
            both = both[both.index >= start_ts]
            if len(both) < 50: continue
            rows_X.append(both.iloc[:, :-1].values)
            rows_y.append(both["y"].values)
        if not rows_X:
            continue
        X = np.vstack(rows_X); y = np.concatenate(rows_y)
        if len(X) < min_samples:
            continue

        # Fit model (occasional refit — expensive)
        if last_model is None or (i - last_model_bar) >= 30 * BARS_PER_DAY:  # refit monthly
            model = GradientBoostingRegressor(
                n_estimators=80, max_depth=3, learning_rate=0.05,
                subsample=0.8, random_state=42)
            model.fit(X, y)
            last_model = model
            last_model_bar = i
            model_stats["n_fits"] += 1
            model_stats["avg_n_samples"] = (
                (model_stats["avg_n_samples"] * (model_stats["n_fits"] - 1) + len(X))
                / model_stats["n_fits"])

        # Predict
        predictions = {}
        for s in close:
            if idx[i] < pd.Timestamp(STARTS[s], tz="UTC"):
                continue
            row = feats[s].iloc[i]
            if row.isnull().any(): continue
            predictions[s] = float(last_model.predict(row.values.reshape(1, -1))[0])

        if len(predictions) < top_k + 1:
            continue

        winners = sorted(predictions, key=lambda s: predictions[s], reverse=True)[:top_k]

        # Rebalance
        targets = {s: 0.0 for s in close}
        w = 1.0 / top_k
        for s in winners: targets[s] = w

        for s in close:
            target_notional = eq * targets[s]
            px = open_.iloc[min(i+1, n-1)][s]
            if np.isnan(px): continue
            target_shares = target_notional / px
            diff = target_shares - positions[s]
            if abs(diff) * px < 0.005 * eq: continue
            gross = diff * px
            fee = abs(gross) * FEE
            cash -= gross + fee
            trade_legs += 1
            positions[s] = target_shares

    return pd.Series(equity, index=idx, name="equity"), trade_legs, model_stats


def mx(eq: pd.Series) -> dict:
    if len(eq) < 20: return {}
    rets = eq.pct_change(fill_method=None).fillna(0)
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 0.01)) - 1
    bpy = pa.BARS_PER_YR
    sh = (rets.mean() * bpy) / (rets.std() * np.sqrt(bpy) + 1e-12)
    dd = float((eq / eq.cummax() - 1).min())
    return {"cagr": round(float(cagr), 4), "sharpe": round(float(sh), 3),
            "dd": round(dd, 4), "calmar": round(cagr/abs(dd) if dd < 0 else 0, 3),
            "final": round(float(eq.iloc[-1]), 0)}


def main():
    import sys
    configs = [
        (3, 7,  7),    # k=3, weekly rebal, 7d horizon
        (4, 7,  7),    # k=4 — matches V15 balanced
        (3, 7, 14),    # 14d horizon
        (4, 3,  7),    # 3d rebal
        (2, 7,  7),    # concentrated
    ]
    rows = []
    for k, rb, hz in configs:
        try:
            eq, legs, stats = v16_ml_rank(top_k=k, rebal_days=rb, horizon_days=hz)
        except Exception as e:
            print(f"  k={k} rb={rb} hz={hz}: error {e}", flush=True); continue
        m = mx(eq)
        yrs = {}
        for y in (2022, 2023, 2024, 2025):
            s = pd.Timestamp(f"{y}-01-01", tz="UTC"); e = pd.Timestamp(f"{y+1}-01-01", tz="UTC")
            sub = eq[(eq.index >= s) & (eq.index < e)]
            yrs[y] = round(float(sub.iloc[-1]/sub.iloc[0] - 1), 3) if len(sub) > 5 else None
        row = {"top_k": k, "rebal_d": rb, "horizon_d": hz,
               "trade_legs": legs, "n_fits": stats["n_fits"],
               "avg_samples": round(stats["avg_n_samples"]), **m,
               **{f"ret_{y-2000}": yrs[y] for y in (2022, 2023, 2024, 2025)}}
        rows.append(row)
        print(f"  ML k={k} rb={rb}d hz={hz}d  "
              f"CAGR {m.get('cagr',0)*100:+6.1f}% Sh {m.get('sharpe',0):.2f} "
              f"DD {m.get('dd',0)*100:+.1f}% Calmar {m.get('calmar',0):.2f} "
              f"Final ${m.get('final',0):,.0f}  "
              f"[{stats['n_fits']} fits, avg {stats['avg_n_samples']:.0f} samples]",
              flush=True)
        if k == 4 and rb == 7 and hz == 7:
            eq.to_csv(OUT / "v16_ml_rank_k4_rb7_equity.csv", header=["equity"])

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "v16_ml_rank.csv", index=False)


if __name__ == "__main__":
    main()
