"""
W3 ML meta-classifier pipeline for HL feature panels.

For each (asset, TF):
  1) Load panel, build target y_next = sign(close[t+1] - close[t]) and y_next_3
  2) Drop price/leakage cols, fill NaN, exclude high-NaN cols
  3) Walk-forward (4 windows, train 2y / test 6m, slide 6m)
  4) Train RF + LightGBM (LGB stands in for XGBoost; same gradient-boosted family)
  5) Permutation importance on test set
  6) Aggregate metrics + top features
  7) G4 permutation test: shuffle labels, retrain, confirm AUC drops to ~0.5

Outputs:
  - W3_walkforward_results.csv      (per-asset, per-TF, per-window, per-model)
  - W3_feature_importance.csv       (mean across windows)
  - W3_g4_permutation_test.csv      (label shuffle baseline)
"""
from __future__ import annotations

import os
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

# Force unbuffered output
os.environ["PYTHONUNBUFFERED"] = "1"
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import (
    accuracy_score, log_loss, precision_score, recall_score, roc_auc_score,
)

import lightgbm as lgb

REPO = Path(__file__).resolve().parents[3]
PANELS_DIR = REPO / "strategy_lab" / "hl_research_2026_05_26" / "panels"
OUT_DIR = REPO / "strategy_lab" / "hl_research_2026_05_26" / "wave2"
OUT_DIR.mkdir(parents=True, exist_ok=True)

ASSETS = ["BTC", "ETH", "SOL"]
TFS = ["5m", "15m", "1h", "4h"]

# Bar period in microseconds for each TF
TF_BAR_US = {
    "5m": 5 * 60 * 1_000_000,
    "15m": 15 * 60 * 1_000_000,
    "1h": 3600 * 1_000_000,
    "4h": 4 * 3600 * 1_000_000,
}

# Cols to exclude from features (leakage / metadata / price levels)
EXCLUDE_COLS = {
    "open", "high", "low", "close", "volume", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote",
    "open_time", "ts_us", "asset", "tf", "source",
    "symbol_id", "period_id",
    # also drop everything that contains time_period_*
}

EXCLUDE_PREFIXES = ("time_period_",)

# High-NaN cols to permanently drop
HIGH_NAN_COLS = {"hl_oi", "hl_funding_rate", "hl_funding_annualized", "hl_funding_z",
                 "pivot_high", "pivot_low"}


def build_targets(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Build next-bar and 3-bar forward direction (1 = UP, 0 = DOWN/FLAT)."""
    close = df["close"].astype(float)
    ret_1 = close.shift(-1) / close - 1.0
    ret_3 = close.shift(-3) / close - 1.0
    y1 = (ret_1 > 0).astype(int)
    y3 = (ret_3 > 0).astype(int)
    # Mark last rows where shift produces NaN
    y1.iloc[-1] = -1
    y3.iloc[-3:] = -1
    return y1, y3


def select_features(df: pd.DataFrame) -> pd.DataFrame:
    """Return feature DataFrame with leakage cols removed and categoricals one-hot."""
    drop_cols = set()
    for c in df.columns:
        if c in EXCLUDE_COLS or c in HIGH_NAN_COLS:
            drop_cols.add(c)
            continue
        if any(c.startswith(p) for p in EXCLUDE_PREFIXES):
            drop_cols.add(c)
    feats = df.drop(columns=list(drop_cols), errors="ignore").copy()

    # One-hot regime_label (3 buckets)
    if "regime_label" in feats.columns:
        feats = pd.concat([
            feats.drop(columns=["regime_label"]),
            pd.get_dummies(feats["regime_label"], prefix="regime"),
        ], axis=1)

    # qr_state, qr_regime, ribbon_color, pvsra_class are categorical ints — leave as-is
    # Drop any remaining object dtype cols
    obj_cols = [c for c in feats.columns if feats[c].dtype.kind == "O"]
    if obj_cols:
        feats = feats.drop(columns=obj_cols, errors="ignore")

    # Fill NaN with column median (preserves shape, robust to outliers)
    for c in feats.columns:
        if feats[c].isna().any():
            med = feats[c].median()
            feats[c] = feats[c].fillna(med if not np.isnan(med) else 0.0)

    # Replace inf with NaN then 0
    feats = feats.replace([np.inf, -np.inf], 0.0)
    return feats.astype("float32")


def build_walk_forward_splits(
    df: pd.DataFrame,
    n_windows: int = 4,
    train_years: int = 2,
    test_months: int = 6,
    slide_months: int = 6,
) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    """Return list of (train_start, train_end, test_start, test_end) timestamps.

    For each TF panel that spans 2017-2026, anchor the LAST test window on the
    data end and slide backwards. Returns up to `n_windows` non-overlapping
    test segments (overlapping train segments allowed since we re-train).
    """
    t_max = df["open_time"].max()
    splits: list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]] = []
    test_end = t_max
    for _ in range(n_windows):
        test_start = test_end - pd.DateOffset(months=test_months)
        train_end = test_start
        train_start = train_end - pd.DateOffset(years=train_years)
        if train_start < df["open_time"].min():
            break
        splits.append((train_start, train_end, test_start, test_end))
        test_end = test_end - pd.DateOffset(months=slide_months)
    return list(reversed(splits))  # chronological order


def train_eval_window(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_test: np.ndarray,
    y_test: np.ndarray,
    feature_names: list[str],
    rf_kwargs: dict,
    lgb_kwargs: dict,
    do_permutation_importance: bool = True,
    n_repeats: int = 3,
    rng_seed: int = 42,
) -> dict:
    """Train RF + LGB on one window, return metrics + importance."""
    res: dict = {}

    # --- RandomForest ---
    rf = RandomForestClassifier(**rf_kwargs, random_state=rng_seed, n_jobs=-1)
    rf.fit(X_train, y_train)
    p_rf = rf.predict_proba(X_test)[:, 1]
    pred_rf = (p_rf > 0.5).astype(int)
    res["rf_auc"] = float(roc_auc_score(y_test, p_rf))
    res["rf_acc"] = float(accuracy_score(y_test, pred_rf))
    res["rf_prec"] = float(precision_score(y_test, pred_rf, zero_division=0))
    res["rf_rec"] = float(recall_score(y_test, pred_rf, zero_division=0))
    res["rf_logloss"] = float(log_loss(y_test, np.clip(p_rf, 1e-6, 1 - 1e-6)))

    # --- LightGBM ---
    lgb_model = lgb.LGBMClassifier(**lgb_kwargs, random_state=rng_seed, n_jobs=-1, verbose=-1)
    lgb_model.fit(X_train, y_train)
    p_lgb = lgb_model.predict_proba(X_test)[:, 1]
    pred_lgb = (p_lgb > 0.5).astype(int)
    res["lgb_auc"] = float(roc_auc_score(y_test, p_lgb))
    res["lgb_acc"] = float(accuracy_score(y_test, pred_lgb))
    res["lgb_prec"] = float(precision_score(y_test, pred_lgb, zero_division=0))
    res["lgb_rec"] = float(recall_score(y_test, pred_lgb, zero_division=0))
    res["lgb_logloss"] = float(log_loss(y_test, np.clip(p_lgb, 1e-6, 1 - 1e-6)))

    # --- Probability-sized Sharpe-ex-fees ---
    # Use LGB probs as position size; only trade when |p - 0.5| > 0.05
    edge = p_lgb - 0.5
    # +1 LONG, -1 SHORT
    pos = np.sign(edge) * (np.abs(edge) > 0.05).astype(float)
    # Realized direction in {-1, +1}
    realized = np.where(y_test == 1, +1.0, -1.0)
    # Per-bar return: pos * realized * 1 (unit pnl per direction)
    pnl_seq = pos * realized
    n_trades = int((pos != 0).sum())
    res["lgb_n_trades"] = n_trades
    if n_trades > 5 and pnl_seq.std() > 0:
        res["lgb_sharpe_oos"] = float(pnl_seq.mean() / pnl_seq.std() * np.sqrt(252))
    else:
        res["lgb_sharpe_oos"] = float("nan")

    # Same for RF
    edge_rf = p_rf - 0.5
    pos_rf = np.sign(edge_rf) * (np.abs(edge_rf) > 0.05).astype(float)
    pnl_rf = pos_rf * realized
    n_trades_rf = int((pos_rf != 0).sum())
    res["rf_n_trades"] = n_trades_rf
    if n_trades_rf > 5 and pnl_rf.std() > 0:
        res["rf_sharpe_oos"] = float(pnl_rf.mean() / pnl_rf.std() * np.sqrt(252))
    else:
        res["rf_sharpe_oos"] = float("nan")

    # --- Permutation importance (on LGB; cheaper than RF and equally informative) ---
    importance_rows: list[dict] = []
    if do_permutation_importance:
        try:
            perm = permutation_importance(
                lgb_model, X_test, y_test, scoring="roc_auc",
                n_repeats=n_repeats, random_state=rng_seed, n_jobs=-1,
            )
            for fn, m, s in zip(feature_names, perm.importances_mean, perm.importances_std):
                importance_rows.append({
                    "feature": fn,
                    "perm_importance_mean": float(m),
                    "perm_importance_std": float(s),
                })
        except Exception as e:
            print(f"   [warn] permutation_importance failed: {e}")

    res["_importance"] = importance_rows
    return res


def run_for_panel(asset: str, tf: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Train + eval on one (asset, TF) panel. Returns:
      walkforward_df, importance_df, g4_df
    """
    pq = PANELS_DIR / f"hl_panel_{asset}_{tf}.parquet"
    if not pq.exists():
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    df = pd.read_parquet(pq).sort_values("open_time").reset_index(drop=True)

    # 5m is too large; subsample (still O(900k rows). For training feasibility,
    # restrict to last 4 years = ~420k bars. Same logic for 15m if needed.
    if tf == "5m":
        cutoff = df["open_time"].max() - pd.DateOffset(years=4)
        df = df.loc[df["open_time"] >= cutoff].reset_index(drop=True)
    elif tf == "15m":
        cutoff = df["open_time"].max() - pd.DateOffset(years=5)
        df = df.loc[df["open_time"] >= cutoff].reset_index(drop=True)

    y1, y3 = build_targets(df)
    feats = select_features(df)
    feature_names = feats.columns.tolist()
    base_rate_1 = float(y1.loc[y1 != -1].mean())
    base_rate_3 = float(y3.loc[y3 != -1].mean())

    # Scale model size to TF to keep runtime tractable.
    # 5m panels have ~420k rows = trained 4× on each window with RF + LGB + perm imp.
    if tf == "5m":
        rf_kwargs = dict(n_estimators=100, max_depth=8, min_samples_leaf=200)
        lgb_kwargs = dict(n_estimators=200, max_depth=4, learning_rate=0.05, subsample=0.8,
                          colsample_bytree=0.8, num_leaves=15)
        perm_repeats = 1
    elif tf == "15m":
        rf_kwargs = dict(n_estimators=200, max_depth=8, min_samples_leaf=100)
        lgb_kwargs = dict(n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.8,
                          colsample_bytree=0.8, num_leaves=15)
        perm_repeats = 2
    else:
        rf_kwargs = dict(n_estimators=300, max_depth=8, min_samples_leaf=50)
        lgb_kwargs = dict(n_estimators=500, max_depth=4, learning_rate=0.05, subsample=0.8,
                          colsample_bytree=0.8, num_leaves=15)
        perm_repeats = 2

    splits = build_walk_forward_splits(df, n_windows=4)
    print(f"  {asset} {tf}: rows={len(df)}, n_features={len(feature_names)}, "
          f"base_rate_y1={base_rate_1:.3f}, base_rate_y3={base_rate_3:.3f}, "
          f"n_windows={len(splits)}", flush=True)

    rows: list[dict] = []
    importance_rows: list[dict] = []
    g4_rows: list[dict] = []

    for win_idx, (tr_start, tr_end, te_start, te_end) in enumerate(splits):
        for target_name, y in [("y_next", y1), ("y_next_3", y3)]:
            # mask: valid target only
            tr_mask = (df["open_time"] >= tr_start) & (df["open_time"] < tr_end) & (y != -1)
            te_mask = (df["open_time"] >= te_start) & (df["open_time"] < te_end) & (y != -1)
            X_train = feats.loc[tr_mask].to_numpy()
            X_test = feats.loc[te_mask].to_numpy()
            y_train = y.loc[tr_mask].to_numpy()
            y_test = y.loc[te_mask].to_numpy()
            if len(X_train) < 1000 or len(X_test) < 500:
                continue
            if len(np.unique(y_train)) < 2 or len(np.unique(y_test)) < 2:
                continue

            t0 = time.time()
            try:
                res = train_eval_window(
                    X_train, y_train, X_test, y_test,
                    feature_names, rf_kwargs, lgb_kwargs,
                    do_permutation_importance=(target_name == "y_next"),  # only for y_next to save time
                    n_repeats=perm_repeats,
                )
            except Exception as e:
                print(f"   [warn] window {win_idx} {target_name} train failed: {e}", flush=True)
                continue
            elapsed = time.time() - t0
            print(f"    win{win_idx} {target_name}: rf_auc={res['rf_auc']:.3f} "
                  f"lgb_auc={res['lgb_auc']:.3f} lgb_acc={res['lgb_acc']:.3f} "
                  f"({elapsed:.1f}s)", flush=True)

            importance_rows_win = res.pop("_importance")
            for imp in importance_rows_win:
                importance_rows.append({
                    "asset": asset, "tf": tf, "target": target_name, "window": win_idx,
                    **imp,
                })

            row = {
                "asset": asset, "tf": tf, "target": target_name, "window": win_idx,
                "train_start": tr_start, "train_end": tr_end,
                "test_start": te_start, "test_end": te_end,
                "n_train": int(len(X_train)), "n_test": int(len(X_test)),
                "n_features": len(feature_names),
                "base_rate_y": float(y_test.mean()),
                **res,
            }
            rows.append(row)

            # --- G4 permutation test: shuffle y_train labels, retrain LGB, check AUC ---
            if target_name == "y_next" and win_idx == len(splits) - 1:  # only last window
                rng = np.random.default_rng(123)
                y_train_shuf = y_train.copy()
                rng.shuffle(y_train_shuf)
                try:
                    lgb_shuf = lgb.LGBMClassifier(**lgb_kwargs, random_state=42,
                                                  n_jobs=-1, verbose=-1)
                    lgb_shuf.fit(X_train, y_train_shuf)
                    p_shuf = lgb_shuf.predict_proba(X_test)[:, 1]
                    auc_shuf = float(roc_auc_score(y_test, p_shuf))
                except Exception as e:
                    auc_shuf = float("nan")
                g4_rows.append({
                    "asset": asset, "tf": tf, "target": target_name, "window": win_idx,
                    "real_auc": res["lgb_auc"],
                    "shuffled_auc": auc_shuf,
                    "auc_drop": res["lgb_auc"] - auc_shuf,
                })

    wf_df = pd.DataFrame(rows)
    imp_df = pd.DataFrame(importance_rows)
    g4_df = pd.DataFrame(g4_rows)
    return wf_df, imp_df, g4_df


def _write_progressive(all_wf: list, all_imp: list, all_g4: list) -> None:
    """Write CSVs incrementally so partial results survive interruption."""
    if all_wf:
        wf = pd.concat(all_wf, ignore_index=True)
        wf.to_csv(OUT_DIR / "W3_walkforward_results.csv", index=False)
    if all_imp:
        imp = pd.concat(all_imp, ignore_index=True)
        imp.to_csv(OUT_DIR / "W3_feature_importance_raw.csv", index=False)
        agg = imp.groupby(["asset", "tf", "feature"]).agg(
            mean_importance=("perm_importance_mean", "mean"),
            std_importance=("perm_importance_mean", "std"),
            n_windows=("perm_importance_mean", "count"),
        ).reset_index().sort_values(["asset", "tf", "mean_importance"], ascending=[True, True, False])
        agg.to_csv(OUT_DIR / "W3_feature_importance.csv", index=False)
    if all_g4:
        g4 = pd.concat(all_g4, ignore_index=True)
        g4.to_csv(OUT_DIR / "W3_g4_permutation_test.csv", index=False)


def main():
    all_wf: list[pd.DataFrame] = []
    all_imp: list[pd.DataFrame] = []
    all_g4: list[pd.DataFrame] = []

    # Process by TF first to get fast results early (1h/4h cheap, 5m slow).
    asset_tf = [(a, tf) for tf in ["1h", "4h", "15m", "5m"] for a in ASSETS]
    for i, (asset, tf) in enumerate(asset_tf):
        t0 = time.time()
        print(f"\n=== [{i+1}/{len(asset_tf)}] {asset} {tf} ===", flush=True)
        try:
            wf_df, imp_df, g4_df = run_for_panel(asset, tf)
        except Exception as e:
            print(f"  FAIL: {e}", flush=True)
            continue
        if len(wf_df):
            all_wf.append(wf_df)
        if len(imp_df):
            all_imp.append(imp_df)
        if len(g4_df):
            all_g4.append(g4_df)
        elapsed = time.time() - t0
        print(f"  [{asset} {tf} done in {elapsed:.1f}s; cumulative={i+1}/{len(asset_tf)}]", flush=True)
        # Incremental write so partial results are preserved
        _write_progressive(all_wf, all_imp, all_g4)

    _write_progressive(all_wf, all_imp, all_g4)
    print(f"\nAll done. WF rows={sum(len(d) for d in all_wf)}, "
          f"imp rows={sum(len(d) for d in all_imp)}, "
          f"g4 rows={sum(len(d) for d in all_g4)}", flush=True)


if __name__ == "__main__":
    main()
