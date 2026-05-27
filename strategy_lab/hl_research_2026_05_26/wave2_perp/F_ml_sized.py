"""
W2P-F — ML-driven perp strategies (probability sizing, ensemble vote,
feature-rule discovery).

Three strategies, all walk-forward (4 windows, train 2y / test 6m):

  F1 — Probability-gated + sized trend
       LightGBM. Per-bar P(up). Enter LONG if p>0.55 AND tr_ema_stack_score>0;
       SHORT if p<0.45 AND tr_ema_stack_score<0. Size = clip(|p-0.5|*4, 0.0, 1.0)
       × base_notional. Exit: prob crosses 0.5 (signal flip) OR ATR trail mult=2
       OR time stop (40 bars cap).

  F2 — Ensemble vote (RF + LGB + XGB)
       Train all 3 on the same train slice. Require 2-of-3 same direction
       to fire. Size = avg(prob) when LONG, 1-avg(prob) when SHORT, scaled
       by |avg - 0.5| * 4. Exit: ensemble flips OR time stop OR ATR trail.

  F3 — Single-feature z-score rule from top W3 importance
       For each (asset, TF), take the top-1 feature from W3_feature_importance.
       Discovery rule: z-score with tested thresholds (+/- 1.0, 1.5).
       LONG when z > thr AND tr_ema_stack_score >= 0;
       SHORT when z < -thr AND tr_ema_stack_score <= 0.
       Exit: ATR trail mult=2 OR time stop. Tests momentum AND fade.

Validation:
  - Walk-forward 4 windows (2-year train / 6-month test) — only OOS PnL counts.
  - G4 permutation test: shuffle y_train labels, retrain, OOS PnL ~ 0 expected.
  - Compare to A2 EMA-stack baseline (loaded from existing W2 results if present).

Output:
  - F_results.csv (one row per asset/TF/strategy/window with OOS stats)
  - F_summary.csv (aggregated per asset/TF/strategy across 4 windows)
"""
from __future__ import annotations

import os
import sys
import time
import warnings
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

os.environ["PYTHONUNBUFFERED"] = "1"
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score
import lightgbm as lgb
import xgboost as xgb

REPO = Path(__file__).resolve().parents[3]
PANELS_DIR = REPO / "strategy_lab" / "hl_research_2026_05_26" / "panels"
OUT_DIR = REPO / "strategy_lab" / "hl_research_2026_05_26" / "wave2_perp"
W3_DIR = REPO / "strategy_lab" / "hl_research_2026_05_26" / "wave2"
FUNDING_DIR = REPO / "data" / "hyperliquid" / "funding"
OUT_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(REPO))
from strategy_lab.hl_research_2026_05_26.hl_engine import (
    HyperliquidConfig, run_backtest,
)

ASSETS = ["BTC", "ETH"]      # W3 showed edge here; SOL weaker
TFS = ["15m", "1h", "4h"]

TF_BAR_US = {
    "5m": 5 * 60 * 1_000_000,
    "15m": 15 * 60 * 1_000_000,
    "1h": 3600 * 1_000_000,
    "4h": 4 * 3600 * 1_000_000,
}
# Max hold horizon in bars per TF (~10h for 15m, ~40h for 1h, ~7d for 4h)
TF_MAX_HOLD_BARS = {"15m": 40, "1h": 40, "4h": 42}

# Cols to exclude — match W3_train_ml.py
EXCLUDE_COLS = {
    "open", "high", "low", "close", "volume", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote",
    "open_time", "ts_us", "asset", "tf", "source",
    "symbol_id", "period_id",
}
EXCLUDE_PREFIXES = ("time_period_",)
HIGH_NAN_COLS = {"hl_oi", "hl_funding_rate", "hl_funding_annualized",
                 "hl_funding_z", "pivot_high", "pivot_low"}

BASE_NOTIONAL = 250.0
LEVERAGE = 1.0
TRAIN_YEARS = 2
TEST_MONTHS = 6


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def load_panel(asset: str, tf: str) -> pd.DataFrame:
    pq = PANELS_DIR / f"hl_panel_{asset}_{tf}.parquet"
    if not pq.exists():
        return pd.DataFrame()
    df = pd.read_parquet(pq).sort_values("open_time").reset_index(drop=True)
    # Trim to last 5 years for memory + recency
    cutoff = df["open_time"].max() - pd.DateOffset(years=5)
    return df.loc[df["open_time"] >= cutoff].reset_index(drop=True)


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


def build_targets(df: pd.DataFrame) -> pd.Series:
    close = df["close"].astype(float)
    ret_1 = close.shift(-1) / close - 1.0
    y1 = (ret_1 > 0).astype(int)
    y1.iloc[-1] = -1
    return y1


def select_features(df: pd.DataFrame) -> pd.DataFrame:
    drop_cols = set()
    for c in df.columns:
        if c in EXCLUDE_COLS or c in HIGH_NAN_COLS:
            drop_cols.add(c)
        elif any(c.startswith(p) for p in EXCLUDE_PREFIXES):
            drop_cols.add(c)
    feats = df.drop(columns=list(drop_cols), errors="ignore").copy()
    if "regime_label" in feats.columns:
        feats = pd.concat([
            feats.drop(columns=["regime_label"]),
            pd.get_dummies(feats["regime_label"], prefix="regime"),
        ], axis=1)
    obj_cols = [c for c in feats.columns if feats[c].dtype.kind == "O"]
    if obj_cols:
        feats = feats.drop(columns=obj_cols, errors="ignore")
    for c in feats.columns:
        if feats[c].isna().any():
            med = feats[c].median()
            feats[c] = feats[c].fillna(med if not np.isnan(med) else 0.0)
    feats = feats.replace([np.inf, -np.inf], 0.0)
    return feats.astype("float32")


def build_walk_forward_splits(df: pd.DataFrame, n_windows: int = 4):
    t_max = df["open_time"].max()
    splits = []
    test_end = t_max
    for _ in range(n_windows):
        test_start = test_end - pd.DateOffset(months=TEST_MONTHS)
        train_end = test_start
        train_start = train_end - pd.DateOffset(years=TRAIN_YEARS)
        if train_start < df["open_time"].min():
            break
        splits.append((train_start, train_end, test_start, test_end))
        test_end = test_end - pd.DateOffset(months=TEST_MONTHS)
    return list(reversed(splits))


# ---------------------------------------------------------------------------
# Model trainers
# ---------------------------------------------------------------------------

def get_model_kwargs(tf: str) -> tuple[dict, dict, dict]:
    """Return (rf_kwargs, lgb_kwargs, xgb_kwargs) sized to TF."""
    if tf == "15m":
        rf = dict(n_estimators=150, max_depth=8, min_samples_leaf=100)
        lg = dict(n_estimators=300, max_depth=4, learning_rate=0.05,
                  subsample=0.8, colsample_bytree=0.8, num_leaves=15)
        xg = dict(n_estimators=200, max_depth=4, learning_rate=0.05,
                  subsample=0.8, colsample_bytree=0.8,
                  tree_method="hist", eval_metric="auc")
    else:  # 1h, 4h
        rf = dict(n_estimators=200, max_depth=8, min_samples_leaf=50)
        lg = dict(n_estimators=400, max_depth=4, learning_rate=0.05,
                  subsample=0.8, colsample_bytree=0.8, num_leaves=15)
        xg = dict(n_estimators=300, max_depth=4, learning_rate=0.05,
                  subsample=0.8, colsample_bytree=0.8,
                  tree_method="hist", eval_metric="auc")
    return rf, lg, xg


def train_lgb(X, y, kwargs, seed=42):
    m = lgb.LGBMClassifier(**kwargs, random_state=seed, n_jobs=-1, verbose=-1)
    m.fit(X, y)
    return m


def train_rf(X, y, kwargs, seed=42):
    m = RandomForestClassifier(**kwargs, random_state=seed, n_jobs=-1)
    m.fit(X, y)
    return m


def train_xgb(X, y, kwargs, seed=42):
    m = xgb.XGBClassifier(**kwargs, random_state=seed, n_jobs=-1,
                          use_label_encoder=False, verbosity=0)
    m.fit(X, y)
    return m


# ---------------------------------------------------------------------------
# Signal builders — convert probs to (signal_us, direction, exit_us) df
# ---------------------------------------------------------------------------

def build_f1_signals(
    df_test: pd.DataFrame,
    proba_up: np.ndarray,
    tf: str,
    p_long: float = 0.55,
    p_short: float = 0.45,
    use_ema_stack: bool = True,
) -> tuple[pd.DataFrame, np.ndarray]:
    """F1 — prob-gated + sized.

    Generate signals when prob crosses threshold AND tr_ema_stack_score agrees.
    Exit when prob flips back across 0.5 OR after TF_MAX_HOLD_BARS time stop.
    Returns (signals_df, size_multiplier_arr) where size_multiplier is in
    [0, 1] used to scale notional per trade.
    """
    n = len(df_test)
    assert len(proba_up) == n
    ts = pd.to_datetime(df_test["open_time"], utc=True)
    us = (ts.astype("int64") // 1_000).astype("int64").to_numpy()
    stack = df_test["tr_ema_stack_score"].to_numpy() if "tr_ema_stack_score" in df_test.columns else np.zeros(n)
    bar_us = TF_BAR_US[tf]
    max_hold = TF_MAX_HOLD_BARS[tf]

    long_mask = (proba_up > p_long) & ((stack > 0) if use_ema_stack else True)
    short_mask = (proba_up < p_short) & ((stack < 0) if use_ema_stack else True)

    sigs: list[dict] = []
    sizes: list[float] = []
    i = 0
    while i < n:
        if long_mask[i]:
            # Find prob-flip exit (next bar where prob <= 0.5)
            j = i + 1
            flip_idx = -1
            while j < n and j < i + max_hold + 1:
                if proba_up[j] <= 0.5:
                    flip_idx = j
                    break
                j += 1
            exit_i = flip_idx if flip_idx != -1 else min(n - 1, i + max_hold)
            exit_us_val = int(us[exit_i])
            size_mult = float(np.clip(abs(proba_up[i] - 0.5) * 4.0, 0.0, 1.0))
            sigs.append({
                "signal_us": int(us[i]), "direction": "LONG",
                "exit_us": exit_us_val,
            })
            sizes.append(size_mult)
            i = exit_i + 1  # don't re-enter while in trade
            continue
        elif short_mask[i]:
            j = i + 1
            flip_idx = -1
            while j < n and j < i + max_hold + 1:
                if proba_up[j] >= 0.5:
                    flip_idx = j
                    break
                j += 1
            exit_i = flip_idx if flip_idx != -1 else min(n - 1, i + max_hold)
            exit_us_val = int(us[exit_i])
            size_mult = float(np.clip(abs(proba_up[i] - 0.5) * 4.0, 0.0, 1.0))
            sigs.append({
                "signal_us": int(us[i]), "direction": "SHORT",
                "exit_us": exit_us_val,
            })
            sizes.append(size_mult)
            i = exit_i + 1
            continue
        i += 1
    return pd.DataFrame(sigs), np.array(sizes, dtype=float)


def build_f2_signals(
    df_test: pd.DataFrame,
    proba_rf: np.ndarray,
    proba_lgb: np.ndarray,
    proba_xgb: np.ndarray,
    tf: str,
    p_long: float = 0.52,
    p_short: float = 0.48,
) -> tuple[pd.DataFrame, np.ndarray]:
    """F2 — 2-of-3 ensemble vote.

    Each model votes LONG if its prob > p_long, SHORT if < p_short, else 0.
    Need 2-of-3 same non-zero direction to fire.
    Size = avg of 3 probs, scaled |avg-0.5|*4 like F1.
    """
    n = len(df_test)
    ts = pd.to_datetime(df_test["open_time"], utc=True)
    us = (ts.astype("int64") // 1_000).astype("int64").to_numpy()
    max_hold = TF_MAX_HOLD_BARS[tf]
    avg_prob = (proba_rf + proba_lgb + proba_xgb) / 3.0

    vote_rf = np.where(proba_rf > p_long, 1, np.where(proba_rf < p_short, -1, 0))
    vote_lgb = np.where(proba_lgb > p_long, 1, np.where(proba_lgb < p_short, -1, 0))
    vote_xgb = np.where(proba_xgb > p_long, 1, np.where(proba_xgb < p_short, -1, 0))

    vote_sum = vote_rf + vote_lgb + vote_xgb
    fire_long = vote_sum >= 2
    fire_short = vote_sum <= -2

    sigs: list[dict] = []
    sizes: list[float] = []
    i = 0
    while i < n:
        if fire_long[i]:
            j = i + 1
            flip_idx = -1
            while j < n and j < i + max_hold + 1:
                # Exit when ensemble vote flips to short OR avg_prob <= 0.5
                if (vote_sum[j] <= -2) or (avg_prob[j] <= 0.5):
                    flip_idx = j
                    break
                j += 1
            exit_i = flip_idx if flip_idx != -1 else min(n - 1, i + max_hold)
            size_mult = float(np.clip(abs(avg_prob[i] - 0.5) * 4.0, 0.0, 1.0))
            sigs.append({"signal_us": int(us[i]), "direction": "LONG",
                         "exit_us": int(us[exit_i])})
            sizes.append(size_mult)
            i = exit_i + 1
            continue
        elif fire_short[i]:
            j = i + 1
            flip_idx = -1
            while j < n and j < i + max_hold + 1:
                if (vote_sum[j] >= 2) or (avg_prob[j] >= 0.5):
                    flip_idx = j
                    break
                j += 1
            exit_i = flip_idx if flip_idx != -1 else min(n - 1, i + max_hold)
            size_mult = float(np.clip(abs(avg_prob[i] - 0.5) * 4.0, 0.0, 1.0))
            sigs.append({"signal_us": int(us[i]), "direction": "SHORT",
                         "exit_us": int(us[exit_i])})
            sizes.append(size_mult)
            i = exit_i + 1
            continue
        i += 1
    return pd.DataFrame(sigs), np.array(sizes, dtype=float)


def build_f3_signals(
    df_test: pd.DataFrame,
    feature: str,
    tf: str,
    z_thr: float = 1.5,
    sign: int = +1,
    use_ema_stack: bool = True,
    roll_window: int = 240,
) -> pd.DataFrame:
    """F3 — single-feature z-score rule.

    sign=+1: z>+thr → LONG; z<-thr → SHORT (momentum)
    sign=-1: z>+thr → SHORT; z<-thr → LONG (fade)
    Combined with ema_stack_score gate. Exit = time stop.
    """
    if feature not in df_test.columns:
        return pd.DataFrame(columns=["signal_us", "direction", "exit_us"])
    n = len(df_test)
    ts = pd.to_datetime(df_test["open_time"], utc=True)
    us = (ts.astype("int64") // 1_000).astype("int64").to_numpy()
    x = df_test[feature].astype(float)
    mu = x.rolling(roll_window, min_periods=max(50, roll_window // 4)).mean()
    sd = x.rolling(roll_window, min_periods=max(50, roll_window // 4)).std()
    z = ((x - mu) / sd.replace(0, np.nan)).to_numpy()
    stack = df_test["tr_ema_stack_score"].to_numpy() if "tr_ema_stack_score" in df_test.columns else np.zeros(n)

    bar_us = TF_BAR_US[tf]
    max_hold = TF_MAX_HOLD_BARS[tf]

    long_dir = "LONG" if sign > 0 else "SHORT"
    short_dir = "SHORT" if sign > 0 else "LONG"

    sigs: list[dict] = []
    i = 0
    while i < n:
        if not np.isnan(z[i]):
            if z[i] > z_thr and ((stack[i] >= 0) if use_ema_stack else True):
                exit_i = min(n - 1, i + max_hold)
                sigs.append({"signal_us": int(us[i]), "direction": long_dir,
                             "exit_us": int(us[exit_i])})
                i = exit_i + 1
                continue
            elif z[i] < -z_thr and ((stack[i] <= 0) if use_ema_stack else True):
                exit_i = min(n - 1, i + max_hold)
                sigs.append({"signal_us": int(us[i]), "direction": short_dir,
                             "exit_us": int(us[exit_i])})
                i = exit_i + 1
                continue
        i += 1
    return pd.DataFrame(sigs)


# ---------------------------------------------------------------------------
# Backtest helper — applies position sizing via per-trade notional
# ---------------------------------------------------------------------------

def run_backtest_sized(
    klines: pd.DataFrame, funding: pd.DataFrame, signals: pd.DataFrame,
    asset: str, size_multipliers: np.ndarray | None,
    cfg: HyperliquidConfig, base_notional: float = BASE_NOTIONAL,
) -> tuple[pd.DataFrame, dict]:
    """Run backtest with per-signal sizing. If size_multipliers is None, all
    trades use base_notional."""
    if len(signals) == 0:
        return run_backtest(klines, funding, signals, asset,
                            notional_usd=base_notional, leverage=LEVERAGE,
                            cfg=cfg)
    if size_multipliers is None or len(size_multipliers) != len(signals):
        return run_backtest(klines, funding, signals, asset,
                            notional_usd=base_notional, leverage=LEVERAGE,
                            cfg=cfg)
    # Per-trade run; collect rows then aggregate
    all_trades = []
    # Strategy: hl_engine doesn't support per-row notional, so loop in groups
    # by unique multiplier (typically ~10 buckets due to clip+rounding).
    mult_rounded = np.round(size_multipliers, 3)
    for mult in np.unique(mult_rounded):
        if mult <= 0:
            continue
        mask = mult_rounded == mult
        sig_sub = signals.loc[mask].reset_index(drop=True)
        if len(sig_sub) == 0:
            continue
        notional = base_notional * float(mult)
        trades, _ = run_backtest(klines, funding, sig_sub, asset,
                                 notional_usd=notional, leverage=LEVERAGE,
                                 cfg=cfg)
        all_trades.append(trades)
    if not all_trades:
        return run_backtest(klines, funding, signals.iloc[:0], asset,
                            notional_usd=base_notional, leverage=LEVERAGE,
                            cfg=cfg)
    trades_df = pd.concat(all_trades, ignore_index=True).sort_values("signal_us").reset_index(drop=True)
    # Recompute summary
    n = len(trades_df)
    pnl = trades_df["pnl_net_usd"].to_numpy()
    wins = int((pnl > 0).sum())
    sharpe = float("nan")
    if pnl.std() > 0:
        sharpe = float((pnl.mean() / pnl.std()) * np.sqrt(252))
    cum = np.cumsum(pnl)
    peaks = np.maximum.accumulate(cum)
    dd = cum - peaks
    max_dd = float(dd.min()) if len(dd) else 0.0
    stats = {
        "asset": asset, "n_trades": n, "n_wins": wins,
        "win_rate": (wins / n) if n else float("nan"),
        "total_pnl_usd": float(pnl.sum()),
        "avg_pnl_usd": float(pnl.mean()) if n else float("nan"),
        "sharpe": sharpe, "max_dd_usd": max_dd,
        "avg_funding_paid": float(trades_df["funding_paid_usd"].mean()) if n else 0.0,
        "avg_fees_paid": float((trades_df["fee_in_usd"] + trades_df["fee_out_usd"]).mean()) if n else 0.0,
        "avg_bars_held": float(trades_df["bars_held"].mean()) if n else float("nan"),
        "n_end_of_data": int((trades_df["exit_reason"] == "end_of_data").sum()) if n else 0,
    }
    return trades_df, stats


def sharpe_annualized(trades_df: pd.DataFrame, tf: str) -> float:
    """Per-trade Sharpe annualized to TF's bars/year scale."""
    if len(trades_df) < 2:
        return float("nan")
    pnl = trades_df["pnl_net_usd"].to_numpy()
    if pnl.std() == 0:
        return float("nan")
    bars_per_year = {
        "15m": 365 * 24 * 4, "1h": 365 * 24, "4h": 365 * 6,
    }[tf]
    # Bars-per-trade approx
    avg_bars = max(float(trades_df["bars_held"].mean()), 1.0)
    trades_per_year = bars_per_year / avg_bars
    return float((pnl.mean() / pnl.std()) * np.sqrt(trades_per_year))


# ---------------------------------------------------------------------------
# Per-asset/TF/window orchestrator
# ---------------------------------------------------------------------------

def run_window_f1(
    asset: str, tf: str, win_idx: int,
    df: pd.DataFrame, feats: pd.DataFrame, y: pd.Series,
    tr_mask: pd.Series, te_mask: pd.Series,
    lgb_kwargs: dict, klines: pd.DataFrame, funding: pd.DataFrame,
    cfg: HyperliquidConfig, shuffle_labels: bool = False,
) -> dict:
    X_train = feats.loc[tr_mask].to_numpy()
    X_test = feats.loc[te_mask].to_numpy()
    y_train = y.loc[tr_mask].to_numpy()
    y_test = y.loc[te_mask].to_numpy()
    if shuffle_labels:
        rng = np.random.default_rng(123)
        y_train = y_train.copy()
        rng.shuffle(y_train)
    model = train_lgb(X_train, y_train, lgb_kwargs)
    p_test = model.predict_proba(X_test)[:, 1]
    try:
        auc = float(roc_auc_score(y_test, p_test))
    except Exception:
        auc = float("nan")
    df_test = df.loc[te_mask].reset_index(drop=True)
    sigs, sizes = build_f1_signals(df_test, p_test, tf)
    trades, stats = run_backtest_sized(klines, funding, sigs, asset, sizes, cfg)
    return {
        "strategy": "F1_prob_sized" + ("_shuffle" if shuffle_labels else ""),
        "asset": asset, "tf": tf, "window": win_idx, "auc": auc,
        "n_signals": int(len(sigs)), **stats,
        "sharpe_ann": sharpe_annualized(trades, tf),
    }


def run_window_f2(
    asset: str, tf: str, win_idx: int,
    df: pd.DataFrame, feats: pd.DataFrame, y: pd.Series,
    tr_mask: pd.Series, te_mask: pd.Series,
    rf_kwargs: dict, lgb_kwargs: dict, xgb_kwargs: dict,
    klines: pd.DataFrame, funding: pd.DataFrame, cfg: HyperliquidConfig,
) -> dict:
    X_train = feats.loc[tr_mask].to_numpy()
    X_test = feats.loc[te_mask].to_numpy()
    y_train = y.loc[tr_mask].to_numpy()
    y_test = y.loc[te_mask].to_numpy()
    rf = train_rf(X_train, y_train, rf_kwargs)
    lg = train_lgb(X_train, y_train, lgb_kwargs)
    xg = train_xgb(X_train, y_train, xgb_kwargs)
    p_rf = rf.predict_proba(X_test)[:, 1]
    p_lg = lg.predict_proba(X_test)[:, 1]
    p_xg = xg.predict_proba(X_test)[:, 1]
    try:
        ens_auc = float(roc_auc_score(y_test, (p_rf + p_lg + p_xg) / 3.0))
    except Exception:
        ens_auc = float("nan")
    df_test = df.loc[te_mask].reset_index(drop=True)
    sigs, sizes = build_f2_signals(df_test, p_rf, p_lg, p_xg, tf)
    trades, stats = run_backtest_sized(klines, funding, sigs, asset, sizes, cfg)
    return {
        "strategy": "F2_ensemble",
        "asset": asset, "tf": tf, "window": win_idx, "auc": ens_auc,
        "n_signals": int(len(sigs)), **stats,
        "sharpe_ann": sharpe_annualized(trades, tf),
    }


def run_window_f3(
    asset: str, tf: str, win_idx: int,
    df: pd.DataFrame, te_mask: pd.Series, top_feature: str,
    klines: pd.DataFrame, funding: pd.DataFrame, cfg: HyperliquidConfig,
) -> list[dict]:
    """F3 — z-score rule on top feature, tested at z_thr={1.0, 1.5}, sign={+,-}."""
    rows = []
    df_test = df.loc[te_mask].reset_index(drop=True)
    for z_thr in (1.0, 1.5):
        for sgn, sgn_name in [(+1, "momentum"), (-1, "fade")]:
            sigs = build_f3_signals(df_test, top_feature, tf, z_thr=z_thr, sign=sgn)
            trades, stats = run_backtest_sized(klines, funding, sigs, asset, None, cfg)
            rows.append({
                "strategy": f"F3_{top_feature}_z{z_thr}_{sgn_name}",
                "asset": asset, "tf": tf, "window": win_idx, "auc": float("nan"),
                "n_signals": int(len(sigs)), **stats,
                "sharpe_ann": sharpe_annualized(trades, tf),
                "feature": top_feature, "z_thr": z_thr, "sign": sgn_name,
            })
    return rows


def run_for_asset_tf(asset: str, tf: str, top_feature: str | None) -> list[dict]:
    print(f"\n=== {asset} {tf} ===", flush=True)
    df = load_panel(asset, tf)
    if df.empty:
        print(f"  panel missing, skipping")
        return []
    klines = klines_from_panel(df)
    funding = load_funding(asset)
    y = build_targets(df)
    feats = select_features(df)
    splits = build_walk_forward_splits(df, n_windows=4)
    rf_kwargs, lgb_kwargs, xgb_kwargs = get_model_kwargs(tf)
    cfg = HyperliquidConfig()

    rows: list[dict] = []
    for win_idx, (tr_start, tr_end, te_start, te_end) in enumerate(splits):
        tr_mask = (df["open_time"] >= tr_start) & (df["open_time"] < tr_end) & (y != -1)
        te_mask = (df["open_time"] >= te_start) & (df["open_time"] < te_end) & (y != -1)
        if tr_mask.sum() < 1000 or te_mask.sum() < 500:
            continue
        if len(np.unique(y.loc[tr_mask])) < 2 or len(np.unique(y.loc[te_mask])) < 2:
            continue

        t0 = time.time()
        # F1
        try:
            r = run_window_f1(asset, tf, win_idx, df, feats, y, tr_mask, te_mask,
                              lgb_kwargs, klines, funding, cfg)
            rows.append(r)
            print(f"  win{win_idx} F1: n={r.get('n_trades',0):4d} pnl=${r.get('total_pnl_usd',0):+8.1f} "
                  f"wr={r.get('win_rate',float('nan')):.3f} shp_ann={r.get('sharpe_ann',float('nan')):+.2f} "
                  f"auc={r.get('auc',float('nan')):.3f}", flush=True)
        except Exception as e:
            print(f"  win{win_idx} F1: FAIL {e}")

        # F1 label-shuffle (G4) — only last window
        if win_idx == len(splits) - 1:
            try:
                r = run_window_f1(asset, tf, win_idx, df, feats, y, tr_mask, te_mask,
                                  lgb_kwargs, klines, funding, cfg, shuffle_labels=True)
                rows.append(r)
                print(f"  win{win_idx} F1_SHUF: n={r.get('n_trades',0):4d} pnl=${r.get('total_pnl_usd',0):+8.1f} "
                      f"shp_ann={r.get('sharpe_ann',float('nan')):+.2f} auc={r.get('auc',float('nan')):.3f}",
                      flush=True)
            except Exception as e:
                print(f"  win{win_idx} F1_SHUF: FAIL {e}")

        # F2
        try:
            r = run_window_f2(asset, tf, win_idx, df, feats, y, tr_mask, te_mask,
                              rf_kwargs, lgb_kwargs, xgb_kwargs, klines, funding, cfg)
            rows.append(r)
            print(f"  win{win_idx} F2: n={r.get('n_trades',0):4d} pnl=${r.get('total_pnl_usd',0):+8.1f} "
                  f"wr={r.get('win_rate',float('nan')):.3f} shp_ann={r.get('sharpe_ann',float('nan')):+.2f} "
                  f"auc={r.get('auc',float('nan')):.3f}", flush=True)
        except Exception as e:
            print(f"  win{win_idx} F2: FAIL {e}")

        # F3 — only if top_feature provided
        if top_feature:
            try:
                for r in run_window_f3(asset, tf, win_idx, df, te_mask, top_feature,
                                       klines, funding, cfg):
                    rows.append(r)
                    print(f"  win{win_idx} {r['strategy']}: n={r.get('n_trades',0):4d} "
                          f"pnl=${r.get('total_pnl_usd',0):+8.1f} "
                          f"shp_ann={r.get('sharpe_ann',float('nan')):+.2f}", flush=True)
            except Exception as e:
                print(f"  win{win_idx} F3: FAIL {e}")

        print(f"  win{win_idx} done in {time.time()-t0:.1f}s", flush=True)
    return rows


# ---------------------------------------------------------------------------
# Summary aggregation
# ---------------------------------------------------------------------------

def aggregate_summary(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Aggregate across windows per (asset, tf, strategy)
    grp_cols = ["asset", "tf", "strategy"]
    agg = df.groupby(grp_cols).agg(
        n_windows=("window", "count"),
        sum_pnl=("total_pnl_usd", "sum"),
        sum_trades=("n_trades", "sum"),
        mean_sharpe_ann=("sharpe_ann", "mean"),
        min_sharpe_ann=("sharpe_ann", "min"),
        n_positive_pnl_windows=("total_pnl_usd", lambda s: (s > 0).sum()),
        mean_win_rate=("win_rate", "mean"),
        mean_avg_pnl=("avg_pnl_usd", "mean"),
        mean_auc=("auc", "mean"),
        sum_funding=("avg_funding_paid", "sum"),
        sum_fees=("avg_fees_paid", "sum"),
    ).reset_index()
    agg["all_windows_pos_pnl"] = agg["n_positive_pnl_windows"] == agg["n_windows"]
    agg["quality_pass"] = (agg["mean_sharpe_ann"] > 1.0) & agg["all_windows_pos_pnl"]
    return agg.sort_values("sum_pnl", ascending=False)


def main():
    # Read top-1 feature per (asset, tf) from W3
    imp_path = W3_DIR / "W3_feature_importance.csv"
    top_feature_map: dict[tuple[str, str], str] = {}
    if imp_path.exists():
        imp = pd.read_csv(imp_path)
        for (a, tf), g in imp.groupby(["asset", "tf"]):
            top = g.sort_values("mean_importance", ascending=False).head(1)
            if len(top):
                top_feature_map[(a, tf)] = top["feature"].iloc[0]
        print(f"Loaded top features for {len(top_feature_map)} cells")
    else:
        print("WARN: W3_feature_importance.csv not found — skipping F3")

    all_rows: list[dict] = []
    for asset in ASSETS:
        for tf in TFS:
            top_feat = top_feature_map.get((asset, tf))
            try:
                rows = run_for_asset_tf(asset, tf, top_feat)
                all_rows.extend(rows)
            except Exception as e:
                print(f"  {asset} {tf}: FAIL {e}")
            # Incremental write
            df = pd.DataFrame(all_rows)
            df.to_csv(OUT_DIR / "F_results.csv", index=False)
            summary = aggregate_summary(all_rows)
            summary.to_csv(OUT_DIR / "F_summary.csv", index=False)

    print(f"\n{'='*60}")
    print(f"Wrote {len(all_rows)} rows -> F_results.csv")
    summary = aggregate_summary(all_rows)
    print(f"\nSummary by (asset, tf, strategy):")
    cols = ["asset", "tf", "strategy", "n_windows", "sum_trades", "sum_pnl",
            "mean_sharpe_ann", "min_sharpe_ann", "n_positive_pnl_windows",
            "mean_win_rate", "mean_auc", "all_windows_pos_pnl", "quality_pass"]
    print(summary[cols].to_string(index=False))

    print("\nQuality-pass rows (mean Sharpe ann > 1.0 AND all 4 windows positive):")
    qp = summary.loc[summary["quality_pass"]]
    if len(qp):
        print(qp[cols].to_string(index=False))
    else:
        print("  (none)")


if __name__ == "__main__":
    main()
