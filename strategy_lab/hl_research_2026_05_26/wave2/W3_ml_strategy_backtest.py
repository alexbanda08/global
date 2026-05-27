"""
W3 ML-probability-sized strategy backtest.

Builds a "discovery strategy" from the LGB model directly:
  1) Walk-forward train LGB on (train_start, train_end)
  2) Predict on test window
  3) Enter LONG when p > 0.55 (high-confidence UP)
     Enter SHORT when p < 0.45 (high-confidence DOWN)
  4) Hold for `hold_bars` bars (1 by default — next-bar trade)
  5) Run through hl_engine with HL fees + funding

This is a TRUE ML-driven discovery: not a single-feature rule but a full
multi-feature ensemble trigger. We re-train per window (no leakage) and
concatenate the OOS trades across windows.

Validation: G1 (binomial p), G3 (total pnl > 0), G6 (bootstrap), and
G4 (shuffle labels — was already done in W3_train_ml.py).
"""
from __future__ import annotations

import os
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
os.environ["PYTHONUNBUFFERED"] = "1"
sys.stdout.reconfigure(line_buffering=True)

from sklearn.metrics import roc_auc_score
from scipy import stats as sps
import lightgbm as lgb

REPO = Path(__file__).resolve().parents[3]
PANELS_DIR = REPO / "strategy_lab" / "hl_research_2026_05_26" / "panels"
OUT_DIR = REPO / "strategy_lab" / "hl_research_2026_05_26" / "wave2"
FUNDING_DIR = REPO / "data" / "hyperliquid" / "funding"

sys.path.insert(0, str(REPO))
from strategy_lab.hl_research_2026_05_26.hl_engine import (
    HyperliquidConfig, run_backtest,
)
from strategy_lab.hl_research_2026_05_26.wave2.W3_train_ml import (
    select_features, build_walk_forward_splits,
)


def build_targets_engine_aligned(df: pd.DataFrame, hold_bars: int = 1) -> pd.Series:
    """Build y aligned with the actual ENGINE trade window.

    Signal at open_time[t] -> entry at open[t+1] -> exit at open[t+1+hold_bars].
    So we predict `sign(open[t+1+hold_bars] - open[t+1])`.

    Returns y in {0, 1, -1} where -1 = invalid (last hold_bars+1 rows).
    """
    op = df["open"].astype(float)
    fwd_ret = op.shift(-(1 + hold_bars)) / op.shift(-1) - 1.0
    y = (fwd_ret > 0).astype(int)
    y.iloc[-(1 + hold_bars):] = -1
    return y


TF_BAR_US = {
    "5m": 5 * 60 * 1_000_000,
    "15m": 15 * 60 * 1_000_000,
    "1h": 3600 * 1_000_000,
    "4h": 4 * 3600 * 1_000_000,
}
# Hold horizon: scale up so fees aren't dominant.
# 5m * 12 = 1h, 15m * 8 = 2h, 1h * 6 = 6h, 4h * 3 = 12h
TF_HOLDBARS = {"5m": 12, "15m": 8, "1h": 6, "4h": 3}


def load_funding(asset: str) -> pd.DataFrame:
    pq = FUNDING_DIR / f"{asset}_funding.parquet"
    if not pq.exists():
        return pd.DataFrame(columns=["funding_rate", "funding_time_us"])
    f = pd.read_parquet(pq)
    return f


def klines_from_panel(df: pd.DataFrame) -> pd.DataFrame:
    kl = df[["open_time", "open", "high", "low", "close", "volume"]].copy()
    ts = pd.to_datetime(kl["open_time"], utc=True)
    kl["open_time_us"] = (ts.astype("int64") // 1_000).astype("int64")
    return kl.sort_values("open_time_us").reset_index(drop=True)


def g1_pvalue(n_wins: int, n_trades: int) -> float:
    if n_trades < 1:
        return float("nan")
    return float(sps.binomtest(n_wins, n_trades, p=0.5).pvalue)


def g6_bootstrap(pnl: np.ndarray, n_resamples: int = 1000) -> tuple[float, float, float]:
    n = len(pnl)
    if n < 10:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(42)
    boot = np.empty(n_resamples)
    for k in range(n_resamples):
        boot[k] = pnl[rng.integers(0, n, size=n)].mean()
    return float((boot > 0).mean()), float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))


def run_ml_backtest(asset: str, tf: str, prob_threshold: float = 0.55) -> dict | None:
    pq = PANELS_DIR / f"hl_panel_{asset}_{tf}.parquet"
    if not pq.exists():
        return None
    df = pd.read_parquet(pq).sort_values("open_time").reset_index(drop=True)
    if tf == "5m":
        cutoff = df["open_time"].max() - pd.DateOffset(years=4)
        df = df.loc[df["open_time"] >= cutoff].reset_index(drop=True)
    elif tf == "15m":
        cutoff = df["open_time"].max() - pd.DateOffset(years=5)
        df = df.loc[df["open_time"] >= cutoff].reset_index(drop=True)

    hold_bars = TF_HOLDBARS[tf]
    y1 = build_targets_engine_aligned(df, hold_bars=hold_bars)
    feats = select_features(df)
    splits = build_walk_forward_splits(df, n_windows=4)
    klines = klines_from_panel(df)
    funding = load_funding(asset)

    if tf == "5m":
        lgb_kwargs = dict(n_estimators=200, max_depth=4, learning_rate=0.05, subsample=0.8,
                          colsample_bytree=0.8, num_leaves=15)
    elif tf == "15m":
        lgb_kwargs = dict(n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.8,
                          colsample_bytree=0.8, num_leaves=15)
    else:
        lgb_kwargs = dict(n_estimators=500, max_depth=4, learning_rate=0.05, subsample=0.8,
                          colsample_bytree=0.8, num_leaves=15)

    all_signals: list[dict] = []
    bar_us = TF_BAR_US[tf]

    for win_idx, (tr_start, tr_end, te_start, te_end) in enumerate(splits):
        tr_mask = (df["open_time"] >= tr_start) & (df["open_time"] < tr_end) & (y1 != -1)
        te_mask = (df["open_time"] >= te_start) & (df["open_time"] < te_end) & (y1 != -1)
        X_tr = feats.loc[tr_mask].to_numpy()
        X_te = feats.loc[te_mask].to_numpy()
        y_tr = y1.loc[tr_mask].to_numpy()
        if len(X_tr) < 1000 or len(X_te) < 500:
            continue
        if len(np.unique(y_tr)) < 2:
            continue

        model = lgb.LGBMClassifier(**lgb_kwargs, random_state=42, n_jobs=-1, verbose=-1)
        model.fit(X_tr, y_tr)
        proba = model.predict_proba(X_te)[:, 1]

        # Convert proba → signals at the actual bar times
        te_idx = df.loc[te_mask].index.to_numpy()
        ts_us = (pd.to_datetime(df["open_time"], utc=True).astype("int64") // 1_000).to_numpy()
        for i, idx in enumerate(te_idx):
            p = proba[i]
            if p > prob_threshold:
                direction = "LONG"
            elif p < (1 - prob_threshold):
                direction = "SHORT"
            else:
                continue
            sig_us = int(ts_us[idx])
            all_signals.append({
                "signal_us": sig_us,
                "direction": direction,
                "exit_us": sig_us + hold_bars * bar_us,
                "proba": float(p),
            })
        print(f"    {asset} {tf} win{win_idx}: n_pos={int((proba > prob_threshold).sum())} "
              f"n_neg={int((proba < 1 - prob_threshold).sum())} (test={len(X_te)})", flush=True)

    if not all_signals:
        return {"asset": asset, "tf": tf, "n_signals": 0, "skipped": True}

    sigs_df = pd.DataFrame(all_signals)
    trades, stats = run_backtest(
        klines, funding, sigs_df, asset,
        notional_usd=250.0, leverage=1.0,
        cfg=HyperliquidConfig(),
    )
    n = stats["n_trades"]
    wins = stats["n_wins"]
    pnl = trades["pnl_net_usd"].to_numpy() if n > 0 else np.array([0.0])
    p_g1 = g1_pvalue(wins, n) if n > 0 else float("nan")
    frac, lo, hi = g6_bootstrap(pnl) if n >= 10 else (float("nan"),) * 3

    return {
        "asset": asset, "tf": tf, "prob_threshold": prob_threshold,
        "n_signals": int(len(sigs_df)), "n_trades": n, "n_wins": wins,
        "win_rate": stats["win_rate"],
        "total_pnl_usd": stats["total_pnl_usd"],
        "avg_pnl_usd": stats["avg_pnl_usd"],
        "sharpe": stats["sharpe"],
        "max_dd_usd": stats["max_dd_usd"],
        "avg_fees_paid": stats["avg_fees_paid"],
        "avg_funding_paid": stats["avg_funding_paid"],
        "avg_bars_held": stats["avg_bars_held"],
        "g1_pvalue": p_g1,
        "g1_pass": bool((n >= 30) and (p_g1 < 0.05)) if not np.isnan(p_g1) else False,
        "g3_pass": bool(stats["total_pnl_usd"] > 0),
        "g6_frac_positive": frac,
        "g6_ci_lo": lo,
        "g6_ci_hi": hi,
        "g6_pass": bool(frac > 0.95) if not np.isnan(frac) else False,
    }


def main():
    results: list[dict] = []
    # Skip 4h panels (small n, unreliable signal in this exercise) and focus on
    # the panels where W3 walk-forward showed strongest LGB AUC > 0.53.
    # ETH 15m, ETH 1h, BTC 15m, BTC 1h, ETH 5m, SOL 15m, SOL 1h, BTC 5m, SOL 5m
    # Run all 12 anyway — fast.
    targets = [
        (a, tf) for tf in ["1h", "15m", "5m", "4h"] for a in ["BTC", "ETH", "SOL"]
    ]
    for thr in [0.55, 0.60]:
        for asset, tf in targets:
            t0 = time.time()
            print(f"\n=== {asset} {tf} thr={thr} ===", flush=True)
            try:
                row = run_ml_backtest(asset, tf, prob_threshold=thr)
                if row is not None:
                    results.append(row)
                    print(f"  n_trades={row.get('n_trades','-')} "
                          f"wr={row.get('win_rate','-')} "
                          f"pnl=${row.get('total_pnl_usd','-')} "
                          f"sharpe={row.get('sharpe','-')} "
                          f"g1={row.get('g1_pass','-')} g3={row.get('g3_pass','-')} g6={row.get('g6_pass','-')} "
                          f"({time.time()-t0:.1f}s)", flush=True)
            except Exception as e:
                print(f"  FAIL: {e}", flush=True)
                results.append({"asset": asset, "tf": tf, "prob_threshold": thr, "error": str(e)})

    df = pd.DataFrame(results)
    df.to_csv(OUT_DIR / "W3_ml_strategy_backtest.csv", index=False)
    print(f"\nWrote {len(df)} rows -> W3_ml_strategy_backtest.csv", flush=True)

    if "g3_pass" in df.columns:
        passing = df.loc[(df["g1_pass"] == True) & (df["g3_pass"] == True)]
        print(f"\nPassing G1+G3: {len(passing)}/{len(df)}", flush=True)
        if len(passing):
            print(passing[["asset","tf","prob_threshold","n_trades","win_rate",
                          "total_pnl_usd","sharpe","g6_frac_positive"]].to_string(), flush=True)


if __name__ == "__main__":
    main()
