"""LightGBM stacker — predict P(outcome=Up) per market-segment from the
hybrid feature panel + R2/R3 microstructure/SMS/regime/vol/DRZ/QR features.

Time-based split:
  - Train : 2026-04-24 00:00 -> 2026-05-14 00:00  (~20d)
  - Val   : 2026-05-14 00:00 -> 2026-05-21 00:00  (7d)  -- threshold tuned + early stop here
  - Lock  : 2026-05-21 00:00 -> 2026-05-25 19:10  (~5d) -- single touch
Outcome: chainlink. Direction at deploy is implied by the ML prob:
   if P_up > p_up_threshold:   bet 'Up'  with fill at up_vwap
   if P_up < p_dn_threshold:   bet 'Down' with fill at dn_vwap
PnL via engine_v2.LegacyConfig (2%-on-profit-only).
"""

import os, sys, json, math, datetime as dt
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.isotonic import IsotonicRegression

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "strategy_lab"))
sys.path.insert(0, os.path.join(ROOT, "data", "v4", "canonical"))

RESULTS = os.path.join(ROOT, "data", "v4", "canonical", "_results")
ML_OUT  = os.path.join(RESULTS, "ml_lightgbm")
os.makedirs(ML_OUT, exist_ok=True)

# ----------------------------------------------------------------------- splits
TRAIN_END_US = int(dt.datetime(2026, 5, 14, 0, 0, 0, tzinfo=dt.timezone.utc).timestamp() * 1_000_000)
VAL_END_US   = int(dt.datetime(2026, 5, 21, 0, 0, 0, tzinfo=dt.timezone.utc).timestamp() * 1_000_000)


def assemble_panel(tf: str) -> pd.DataFrame:
    """Join hybrid features + vol/Hurst + microstructure + SMS + regime + DRZ + QR.

    Time-series panels (SMS / regime / QR) are joined via backward asof on bar
    timestamp (ts_us) per asset.
    """
    print(f"\n[assemble {tf}] loading hybrid_features...")
    hf = pd.read_parquet(os.path.join(RESULTS, f"hybrid_features_{tf}.parquet"))
    n0 = len(hf)

    # --- vol/Hurst (already at fire_us)
    vh = pd.read_parquet(os.path.join(RESULTS, f"vol_hurst_at_fire_{tf}.parquet"))
    vh_keep = ["asset", "slug", "fire_offset_s"] + [c for c in vh.columns if c.startswith(("rv_", "hurst_", "gk_", "vol_regime", "g_vol_", "g_hurst_", "g_rv_"))]
    vh_keep = [c for c in vh_keep if c not in ("fire_us", "outcome")]
    vh = vh[vh_keep].drop_duplicates(["asset", "slug", "fire_offset_s"])
    hf = hf.merge(vh, on=["asset", "slug", "fire_offset_s"], how="left", suffixes=("", "_vh"))

    # --- microstructure (at fire_us)
    ms = pd.read_parquet(os.path.join(RESULTS, "microstructure_panel.parquet"))
    ms = ms[ms["tf"] == tf]
    ms_drop = ["tf", "outcome", "ws_s", "up_ask0", "up_bid0", "dn_ask0", "dn_bid0",
               "up_fill_ok", "dn_fill_ok", "up_vwap", "up_shares", "up_usd",
               "dn_vwap", "dn_shares", "dn_usd", "up_mid", "dn_mid", "fire_us"]
    ms_keep = ["asset", "slug", "fire_offset_s"] + [c for c in ms.columns if c not in ms_drop and c not in ("asset", "slug", "fire_offset_s")]
    ms = ms[ms_keep].drop_duplicates(["asset", "slug", "fire_offset_s"])
    hf = hf.merge(ms, on=["asset", "slug", "fire_offset_s"], how="left", suffixes=("", "_ms"))

    # --- DRZ (at fire_us)
    drz = pd.read_parquet(os.path.join(RESULTS, f"drz_panel_{tf}.parquet"))
    drz_keep = ["asset", "slug", "fire_offset_s"] + [c for c in drz.columns if c.startswith("drz_")]
    drz = drz[drz_keep].drop_duplicates(["asset", "slug", "fire_offset_s"])
    hf = hf.merge(drz, on=["asset", "slug", "fire_offset_s"], how="left")

    # --- SMS (bar-level, asof on ws_s)
    sms = pd.read_parquet(os.path.join(RESULTS, f"sms_panel_{tf}.parquet"))
    sms_keep = ["asset", "ts_us"] + ["cvd", "cvd_level", "cvd_sign", "liquidity_up", "liquidity_dn",
                                      "trend_1m", "trend_5m", "trend_15m", "trend_30m", "trend_1h", "trend_4h",
                                      "trend_strength_raw", "trend_strength_pct", "system_confidence",
                                      "bars_since_bos_buy", "bars_since_bos_sell", "bars_since_choch_buy",
                                      "bars_since_choch_sell", "rsi_14"]
    sms_keep = [c for c in sms_keep if c in sms.columns]
    sms = sms[sms_keep].drop_duplicates(["asset", "ts_us"]).sort_values(["asset", "ts_us"])
    sms = sms.rename(columns={c: f"sms_{c}" for c in sms.columns if c not in ("asset", "ts_us")})

    # asof join — ws_s -> microseconds
    hf["ws_us"] = (hf["ws_s"] * 1_000_000).astype("int64")
    hf = hf.sort_values(["asset", "ws_us"])
    sms = sms.rename(columns={"ts_us": "_sms_ts_us"})
    parts = []
    for asset, g in hf.groupby("asset", sort=False):
        s = sms[sms["asset"] == asset].sort_values("_sms_ts_us")
        m = pd.merge_asof(g.sort_values("ws_us"), s.drop(columns=["asset"]),
                          left_on="ws_us", right_on="_sms_ts_us", direction="backward",
                          tolerance=900 * 1_000_000)  # within 15 min
        parts.append(m)
    hf = pd.concat(parts, ignore_index=True).drop(columns=["_sms_ts_us"], errors="ignore")

    # --- Regime panel (bar-level, asof)
    reg = pd.read_parquet(os.path.join(RESULTS, f"regime_panel_{tf}.parquet"))
    reg_keep = ["asset", "ts_us", "adx_14", "plus_di_14", "minus_di_14", "atr_14",
                "tr_ema_stack_score", "ribbon_alignment_pct", "bb_width_60s",
                "realized_vol_60m", "range_compression", "trend_slope_30m",
                "regime_label", "regime_score"]
    reg_keep = [c for c in reg_keep if c in reg.columns]
    reg = reg[reg_keep].drop_duplicates(["asset", "ts_us"]).sort_values(["asset", "ts_us"])
    reg = reg.rename(columns={c: f"reg_{c}" for c in reg.columns if c not in ("asset", "ts_us")})
    reg = reg.rename(columns={"ts_us": "_reg_ts_us"})
    parts = []
    for asset, g in hf.groupby("asset", sort=False):
        r = reg[reg["asset"] == asset].sort_values("_reg_ts_us")
        m = pd.merge_asof(g.sort_values("ws_us"), r.drop(columns=["asset"]),
                          left_on="ws_us", right_on="_reg_ts_us", direction="backward",
                          tolerance=900 * 1_000_000)
        parts.append(m)
    hf = pd.concat(parts, ignore_index=True).drop(columns=["_reg_ts_us"], errors="ignore")

    # --- QR (bar-level, asof)
    try:
        qr = pd.read_parquet(os.path.join(RESULTS, f"qr_panel_{tf}.parquet"))
        qr_keep = ["asset", "ts_us", "bull_align", "bear_align", "ribbon_state", "bullish_emas", "bearish_emas",
                   "ribbon_aligned", "current_spread", "ribbon_expanding", "bars_above", "bars_below",
                   "price_consistent", "market_regime", "market_health", "volume_ratio",
                   "momentum_consistency", "signal_confidence"]
        qr_keep = [c for c in qr_keep if c in qr.columns]
        qr = qr[qr_keep].drop_duplicates(["asset", "ts_us"]).sort_values(["asset", "ts_us"])
        qr = qr.rename(columns={c: f"qr_{c}" for c in qr.columns if c not in ("asset", "ts_us")})
        qr = qr.rename(columns={"ts_us": "_qr_ts_us"})
        parts = []
        for asset, g in hf.groupby("asset", sort=False):
            q = qr[qr["asset"] == asset].sort_values("_qr_ts_us")
            m = pd.merge_asof(g.sort_values("ws_us"), q.drop(columns=["asset"]),
                              left_on="ws_us", right_on="_qr_ts_us", direction="backward",
                              tolerance=900 * 1_000_000)
            parts.append(m)
        hf = pd.concat(parts, ignore_index=True).drop(columns=["_qr_ts_us"], errors="ignore")
    except Exception as e:
        print(f"[assemble {tf}] qr skipped: {e}")

    # --- Coerce object-dtype categorical features to category dtype for LGB
    for c in ["sms_cvd_sign", "reg_regime_label", "qr_ribbon_state", "qr_market_regime",
              "qr_market_health", "qr_bull_align", "qr_bear_align", "qr_ribbon_aligned",
              "qr_ribbon_expanding", "qr_price_consistent"]:
        if c in hf.columns:
            hf[c] = hf[c].astype("category")

    # vol_regime might also be a string
    if "vol_regime" in hf.columns:
        hf["vol_regime"] = hf["vol_regime"].astype("category")

    # Some hybrid features may be strings/categories
    for c in hf.columns:
        if hf[c].dtype == "object" and c not in ("asset", "slug", "tf", "outcome"):
            try:
                hf[c] = hf[c].astype("category")
            except Exception:
                pass

    print(f"[assemble {tf}] merged: {len(hf)} rows ({len(hf)-n0:+d} from joins), {len(hf.columns)} cols")
    return hf


# ----------------------------------------------------------- feature list builder
DROP_LEAK = {
    # leak risk — these contain or describe the outcome
    "outcome", "settle_price", "strike_price",
    "up_fill_ok", "dn_fill_ok", "up_vwap", "up_shares", "up_usd",
    "dn_vwap", "dn_shares", "dn_usd", "up_ask0", "up_bid0", "up_book_dt_us",
    "dn_ask0", "dn_bid0", "dn_book_dt_us",
    # ML-internal derivations
    "y_up", "pnl_up_per1", "pnl_dn_per1",
    # microstructure-panel leak columns (these are pnl-from-microstructure already at the same fire)
    "pnl_up", "pnl_dn",
    # ID columns
    "asset", "slug", "tf", "ws_us",
    # the regime gate "pass_*" column from hybrid_features is a pre-tuned filter — not a feature
}


def _feat_cols(df: pd.DataFrame) -> list[str]:
    cols = []
    for c in df.columns:
        if c in DROP_LEAK:
            continue
        if c.startswith("pass_"):
            continue
        cols.append(c)
    return cols


def _set_pnl(df: pd.DataFrame, fee_rate: float = 0.02) -> pd.DataFrame:
    """Compute pnl per row for both Up and Down side using LegacyConfig (2%-on-profit)."""
    up_qty = np.where(df["up_vwap"] > 0, 1.0 / df["up_vwap"], 0.0)
    dn_qty = np.where(df["dn_vwap"] > 0, 1.0 / df["dn_vwap"], 0.0)
    won_if_up = (df["outcome"] == "Up").astype(float).values
    won_if_dn = (df["outcome"] == "Down").astype(float).values

    # PnL per $1 stake on Up side
    # Win: (1/vwap - 1) * (1 - fee). Loss: -1.
    pnl_up_win = (up_qty * 1.0 - 1.0) * (1.0 - fee_rate)
    pnl_dn_win = (dn_qty * 1.0 - 1.0) * (1.0 - fee_rate)

    pnl_up = np.where(won_if_up == 1.0, pnl_up_win, -1.0)
    pnl_dn = np.where(won_if_dn == 1.0, pnl_dn_win, -1.0)

    # Mask invalid fills as 0 PnL (will be excluded at firing time)
    pnl_up = np.where(df["up_fill_ok"].astype(bool).values, pnl_up, np.nan)
    pnl_dn = np.where(df["dn_fill_ok"].astype(bool).values, pnl_dn, np.nan)

    df = df.copy()
    df["pnl_up_per1"] = pnl_up
    df["pnl_dn_per1"] = pnl_dn
    df["y_up"] = (df["outcome"] == "Up").astype(int)
    return df


def split_3way(df: pd.DataFrame):
    tr = df[df["fire_us"] < TRAIN_END_US].copy()
    va = df[(df["fire_us"] >= TRAIN_END_US) & (df["fire_us"] < VAL_END_US)].copy()
    lo = df[df["fire_us"] >= VAL_END_US].copy()
    return tr, va, lo


def tune_thresholds(p_val, df_val):
    """Sweep p_up_threshold (> p_up -> bet Up) and p_dn_threshold (< p_dn -> bet Down).
    Maximize sum_pnl on val."""
    grid = np.arange(0.50, 0.85, 0.01)
    best = (-1e9, 0.55, 0.45)
    for p_up in grid:
        for p_dn in np.arange(0.15, 0.50, 0.01):
            sel_up = p_val > p_up
            sel_dn = p_val < p_dn
            up_pnl = df_val.loc[sel_up, "pnl_up_per1"]
            dn_pnl = df_val.loc[sel_dn, "pnl_dn_per1"]
            tot = up_pnl.dropna().sum() + dn_pnl.dropna().sum()
            n = int((up_pnl.notna()).sum() + (dn_pnl.notna()).sum())
            if n < 20:
                continue
            if tot > best[0]:
                best = (tot, p_up, p_dn)
    return best


def apply_sleeve(p, df, p_up, p_dn):
    sel_up = p > p_up
    sel_dn = p < p_dn

    rows = []
    for sel, side, pnl_col in [(sel_up, "Up", "pnl_up_per1"), (sel_dn, "Down", "pnl_dn_per1")]:
        idx = df.index[sel]
        pnl = df.loc[idx, pnl_col]
        # drop NaN (failed fills)
        keep = pnl.notna()
        pnl = pnl[keep]
        rows.append({
            "side": side,
            "n": int(len(pnl)),
            "wins": int(((side == "Up") & (df.loc[pnl.index, "outcome"] == "Up")).sum() if side == "Up" else ((df.loc[pnl.index, "outcome"] == "Down")).sum()),
            "sum_pnl": float(pnl.sum()),
        })
    n_tot = sum(r["n"] for r in rows)
    w_tot = sum(r["wins"] for r in rows)
    pnl_tot = sum(r["sum_pnl"] for r in rows)

    # Combined per-trade frame for bootstrap
    up_idx = df.index[sel_up]
    dn_idx = df.index[sel_dn]
    up_pnl = df.loc[up_idx, "pnl_up_per1"].dropna()
    dn_pnl = df.loc[dn_idx, "pnl_dn_per1"].dropna()
    all_pnl = pd.concat([up_pnl, dn_pnl]).reset_index(drop=True)

    return {
        "n": n_tot,
        "wins": w_tot,
        "wr": (w_tot / n_tot) if n_tot else 0.0,
        "sum_pnl": pnl_tot,
        "pnl_per_trade": (pnl_tot / n_tot) if n_tot else 0.0,
        "n_up": rows[0]["n"], "n_dn": rows[1]["n"],
        "per_trade_pnl": all_pnl.values.tolist(),
    }


def bootstrap_p(per_trade, n_shuffles=200, baseline=0.0):
    """Two-sided p: prob that mean of shuffled signs >= observed."""
    if len(per_trade) == 0:
        return float("nan")
    x = np.array(per_trade, dtype=float)
    obs = x.mean()
    rng = np.random.default_rng(42)
    ge = 0
    for _ in range(n_shuffles):
        # randomize sign — null is "PnL = 0 per trade on average"
        signs = rng.choice([1, -1], size=len(x))
        s = (x * signs).mean()
        if abs(s) >= abs(obs - baseline):
            ge += 1
    return ge / n_shuffles


def train_one(df_tr, df_va, df_lo, feats, asset_label):
    print(f"\n[{asset_label}] train={len(df_tr)} val={len(df_va)} lock={len(df_lo)} feats={len(feats)}")

    X_tr = df_tr[feats]
    y_tr = df_tr["y_up"].values
    X_va = df_va[feats]
    y_va = df_va["y_up"].values
    X_lo = df_lo[feats]
    y_lo = df_lo["y_up"].values

    cat_feats = [c for c in feats if str(X_tr[c].dtype) == "category"]

    train_set = lgb.Dataset(X_tr, label=y_tr, categorical_feature=cat_feats, free_raw_data=False)
    val_set = lgb.Dataset(X_va, label=y_va, categorical_feature=cat_feats, reference=train_set, free_raw_data=False)

    params = dict(
        objective="binary",
        metric="binary_logloss",
        learning_rate=0.05,
        num_leaves=31,
        min_data_in_leaf=50,
        feature_fraction=0.8,
        bagging_fraction=0.8,
        bagging_freq=5,
        verbose=-1,
        seed=42,
    )

    booster = lgb.train(
        params,
        train_set,
        num_boost_round=200,
        valid_sets=[val_set],
        valid_names=["val"],
        callbacks=[lgb.early_stopping(stopping_rounds=20, verbose=False), lgb.log_evaluation(period=0)],
    )
    print(f"[{asset_label}] best iter = {booster.best_iteration}")

    p_tr = booster.predict(X_tr, num_iteration=booster.best_iteration)
    p_va = booster.predict(X_va, num_iteration=booster.best_iteration)
    p_lo = booster.predict(X_lo, num_iteration=booster.best_iteration)

    # Tune thresholds on val
    best = tune_thresholds(p_va, df_va)
    print(f"[{asset_label}] thresholds  p_up={best[1]:.2f}  p_dn={best[2]:.2f}  val_sum_pnl=${best[0]:.2f}")

    val_res = apply_sleeve(p_va, df_va, best[1], best[2])
    lo_res = apply_sleeve(p_lo, df_lo, best[1], best[2])
    boot_p = bootstrap_p(lo_res["per_trade_pnl"])

    # Importance
    imp_split = booster.feature_importance(importance_type="split")
    imp_gain = booster.feature_importance(importance_type="gain")
    imp_df = pd.DataFrame({"feature": feats, "split": imp_split, "gain": imp_gain}).sort_values("gain", ascending=False)

    # Calibration
    # Bin val P(up) into 10 buckets and compute actual Up rate per bucket
    cal = pd.DataFrame({"p": p_va, "y": y_va})
    cal["bin"] = pd.cut(cal["p"], bins=np.arange(0.0, 1.05, 0.05), include_lowest=True)
    calib_va = cal.groupby("bin").agg(n=("y", "size"), mean_p=("p", "mean"), actual=("y", "mean")).reset_index()

    # Isotonic recalibration on val
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso.fit(p_va, y_va)
    p_lo_iso = iso.transform(p_lo)
    # Tune thresholds on val using calibrated probs
    p_va_iso = iso.transform(p_va)
    best_iso = tune_thresholds(p_va_iso, df_va)
    val_iso = apply_sleeve(p_va_iso, df_va, best_iso[1], best_iso[2])
    lo_iso  = apply_sleeve(p_lo_iso, df_lo, best_iso[1], best_iso[2])
    boot_p_iso = bootstrap_p(lo_iso["per_trade_pnl"])

    return {
        "label": asset_label,
        "n_train": len(df_tr), "n_val": len(df_va), "n_lock": len(df_lo),
        "best_iter": booster.best_iteration,
        "p_up": best[1], "p_dn": best[2],
        "val": {k: v for k, v in val_res.items() if k != "per_trade_pnl"},
        "lockbox": {k: v for k, v in lo_res.items() if k != "per_trade_pnl"} | {"boot_p": boot_p},
        "lockbox_iso": {k: v for k, v in lo_iso.items() if k != "per_trade_pnl"} | {"boot_p": boot_p_iso, "p_up": best_iso[1], "p_dn": best_iso[2]},
        "importance": imp_df,
        "calibration": calib_va,
        "booster": booster,
        "iso": iso,
        "p_lo": p_lo,
        "df_lo": df_lo[["asset", "slug", "fire_offset_s", "fire_us", "outcome", "ret_2m_at_ws", "up_vwap", "dn_vwap"]].assign(p_up=p_lo, p_up_iso=p_lo_iso),
    }


def main():
    panels = {tf: assemble_panel(tf) for tf in ("5m", "15m")}

    # Add PnL
    for tf in panels:
        panels[tf] = _set_pnl(panels[tf])

    results = {}
    all_lockbox_rows = []
    feature_summary = {}
    calibration_summary = {}

    for tf in ("5m", "15m"):
        df = panels[tf]
        for asset in ("BTC", "ETH", "SOL"):
            sub = df[df["asset"] == asset].copy()
            # Need both pnl options to be present or NaN — but we keep rows even with one side bad.
            # Drop rows where BOTH pnl options are NaN (no fill either side)
            sub = sub.dropna(subset=["pnl_up_per1", "pnl_dn_per1"], how="all").reset_index(drop=True)
            feats = _feat_cols(sub)
            # Drop features that are ALL nan in train
            tr, va, lo = split_3way(sub)
            keep_feats = [f for f in feats if not tr[f].isna().all()]
            print(f"\n=== {asset} {tf}: feats={len(keep_feats)} (dropped {len(feats)-len(keep_feats)} all-NaN cols)")
            if len(tr) < 200 or len(va) < 50 or len(lo) < 50:
                print(f"  SKIP (too small)")
                continue
            r = train_one(tr, va, lo, keep_feats, f"{asset}_{tf}")
            results[f"{asset}_{tf}"] = r
            feature_summary[f"{asset}_{tf}"] = r["importance"].head(20).copy()
            calibration_summary[f"{asset}_{tf}"] = r["calibration"]

            # Append per-fire predictions
            df_pred = r["df_lo"].copy()
            df_pred["model"] = f"{asset}_{tf}"
            all_lockbox_rows.append(df_pred)

            # Compute the actual lockbox fires (those that pass thresholds)
            pred_up = df_pred["p_up_iso"] > r["lockbox_iso"]["p_up"]
            pred_dn = df_pred["p_up_iso"] < r["lockbox_iso"]["p_dn"]
            df_pred["sleeve_side"] = np.where(pred_up, "Up", np.where(pred_dn, "Down", ""))

    # ---------------- write outputs ----------------
    summary_rows = []
    for k, r in results.items():
        v = r["val"]; l = r["lockbox"]; li = r["lockbox_iso"]
        summary_rows.append({
            "model": k,
            "n_train": r["n_train"], "n_val": r["n_val"], "n_lock": r["n_lock"],
            "best_iter": r["best_iter"],
            "p_up": round(r["p_up"], 3), "p_dn": round(r["p_dn"], 3),
            "val_n": v["n"], "val_wr": round(v["wr"], 4), "val_sum_pnl": round(v["sum_pnl"], 3), "val_per_tr": round(v["pnl_per_trade"], 5),
            "lock_n": l["n"], "lock_wr": round(l["wr"], 4), "lock_sum_pnl": round(l["sum_pnl"], 3), "lock_per_tr": round(l["pnl_per_trade"], 5), "lock_boot_p": round(l["boot_p"], 3),
            "iso_p_up": round(li["p_up"], 3), "iso_p_dn": round(li["p_dn"], 3),
            "iso_lock_n": li["n"], "iso_lock_wr": round(li["wr"], 4), "iso_lock_sum_pnl": round(li["sum_pnl"], 3), "iso_lock_per_tr": round(li["pnl_per_trade"], 5), "iso_boot_p": round(li["boot_p"], 3),
        })
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(os.path.join(RESULTS, "ml_lightgbm_lockbox.csv"), index=False)
    print("\n=== SUMMARY ===")
    print(summary.to_string(index=False))

    # Save importance per model
    for k, imp in feature_summary.items():
        imp.to_csv(os.path.join(ML_OUT, f"importance_{k}.csv"), index=False)
    # Save calibration
    for k, cal in calibration_summary.items():
        cal.to_csv(os.path.join(ML_OUT, f"calibration_{k}.csv"), index=False)

    # Save per-fire lockbox predictions
    if all_lockbox_rows:
        combo = pd.concat(all_lockbox_rows, ignore_index=True)
        combo.to_parquet(os.path.join(ML_OUT, "lockbox_predictions.parquet"))

    # Persist results dict (lightweight) for downstream comparison
    import pickle
    with open(os.path.join(ML_OUT, "results.pkl"), "wb") as f:
        save_dict = {k: {kk: vv for kk, vv in v.items() if kk not in ("booster", "iso")} for k, v in results.items()}
        pickle.dump(save_dict, f)

    return results


if __name__ == "__main__":
    main()
