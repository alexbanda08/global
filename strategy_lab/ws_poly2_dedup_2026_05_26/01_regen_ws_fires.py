"""
Regenerate per-fire WS-poly2 predictions for the 7 sleeves TT tested.
Save (sleeve_id, slug, fire_us, direction, predicted_proba, would_fire, pnl_usd, won, outcome, asset, tf, offset_bin)
to ws_poly2_fires_per_sleeve.parquet (long format).

For each sleeve and each model variant (ridge, elastic_net, logistic_l2, logistic_poly2):
- Train on train split (<2026-05-15)
- Tune threshold on val (2026-05-15 - 2026-05-22) to maximize sum_pnl
- Score lockbox (2026-05-22 - 2026-05-25 19:14 UTC)
- For each lockbox fire, save: sleeve_id, model, slug, fire_us, direction, proba, would_fire (proba>=threshold), pnl, won

Best model per sleeve picked from TT's `best_per_sleeve.csv` for the "headline" WS fire universe.
We also save FULL window predictions (not just lockbox) so we can compute 28d-comparable numbers.
"""
import os, sys, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge, ElasticNet, LogisticRegression
from sklearn.preprocessing import StandardScaler, PolynomialFeatures

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
MASTER = f"{ROOT}/data/v4/canonical/_results/master_gate_features_v2.parquet"
OUT = f"{ROOT}/strategy_lab/ws_poly2_dedup_2026_05_26"
os.makedirs(OUT, exist_ok=True)

# ----------------------------------------------------------------
# TT's 7 sleeves (copied from build_weighted_models.py)
# ----------------------------------------------------------------
BASELINE_SLEEVES = [
    {"sleeve": "BTC_S6_60_150",   "asset": "BTC", "tf": "5m", "offset_bin": "60-150",
     "sleeve_prefix": "s6_5m",
     "gates": ["g_cci_with","g_stoch_with","g_rf_with","g_tr_above_ema50","g_ribbon_agrees"]},
    {"sleeve": "ETH_S6_60_150",   "asset": "ETH", "tf": "5m", "offset_bin": "60-150",
     "sleeve_prefix": "s6_5m",
     "gates": ["g_cci_with","g_bb_pos_with","g_ribbon_agrees"]},
    {"sleeve": "SOL_S6_60_150",   "asset": "SOL", "tf": "5m", "offset_bin": "60-150",
     "sleeve_prefix": "s6_5m",
     "gates": ["g_mfi_with","g_within_dev","g_bb_pos_with","g_ribbon_agrees"]},
    {"sleeve": "BTC_S15_150_240", "asset": "BTC", "tf": "5m", "offset_bin": "150-240",
     "sleeve_prefix": "s15_5m",
     "gates": ["g_tr_above_pp","g_ribbon_agrees","g_stoch_with","g_tight_ribbon"]},
    {"sleeve": "ETH_S15_150_240", "asset": "ETH", "tf": "5m", "offset_bin": "150-240",
     "sleeve_prefix": "s15_5m",
     "gates": ["g_ribbon_agrees","g_tr_above_ema200","g_stoch_with","g_bb_pos_with","g_cci_with"]},
    {"sleeve": "S7_BTC_5m_base",  "asset": "BTC", "tf": "5m", "offset_bin": None,
     "sleeve_prefix": "s15_5m",
     "gates": ["g_tr_stack_with","g_tr_above_ema800","g_ribbon_agrees","g_tight_ribbon","g_stoch_with","g_tr_above_ema200"]},
    {"sleeve": "SOL_S15_60_150",  "asset": "SOL", "tf": "5m", "offset_bin": "60-150",
     "sleeve_prefix": "s15_5m",
     "gates": ["g_ribbon_agrees","g_stoch_with","g_bb_pos_with","g_cci_with"]},
]

CONT_FEATURES = [
    "mp_skew","mp_weighted_skew","mp_skew_change_500ms","mp_up_dev_bps","mp_dn_dev_bps",
    "mp_imbalance","mp_weighted_imbalance",
    "L_stat",
    "hawkes_lambda_imbalance","hawkes_lambda_total",
    "rv_ratio_60_to_3600","hurst_300s","hurst_100s","hurst_900s",
    "trend_slope_30m","rv_60s","rv_300s",
    "up_imb5","dn_imb5","up_imb25","dn_imb25",
    "up_queue_top_bid","up_micro_dev_bps","dn_micro_dev_bps",
    "up_bid_slope","up_ask_slope","dn_bid_slope","dn_ask_slope",
    "up_imb5_change_500ms","up_quote_intensity_5s",
    "ribbon_alignment_pct","ribbon_compression_bps",
    "adx_14","plus_di_14","minus_di_14",
    "vwap_since_open_bps",
    "mfi_60s","stoch_k_60s","stoch_d_60s","cci_60s","bb_pos_60s","bb_width_60s",
    "ofi_skew_l1_30s","mlofi_skew_l5_30s","mlofi_skew_l5_60s","mlofi_skew_l25_30s",
    "rsi_14","cvd",
    "vpin_value","vpin_zscore",
    "as_uncertainty","as_skew",
]

DIR_DEP = {
    "mp_skew","mp_weighted_skew","mp_skew_change_500ms","mp_imbalance","mp_weighted_imbalance",
    "up_imb5","up_imb25","up_micro_dev_bps","up_bid_slope","up_ask_slope","up_imb5_change_500ms",
    "dn_imb5","dn_imb25","dn_micro_dev_bps","dn_bid_slope","dn_ask_slope",
    "hawkes_lambda_imbalance","ofi_skew_l1_30s","mlofi_skew_l5_30s","mlofi_skew_l5_60s","mlofi_skew_l25_30s",
    "trend_slope_30m","as_skew","vwap_since_open_bps","cvd",
    "mfi_60s","stoch_k_60s","stoch_d_60s","cci_60s","bb_pos_60s","rsi_14",
}

TRAIN_END = pd.Timestamp("2026-05-15")
VAL_END   = pd.Timestamp("2026-05-22")

def direction_sign_features(df, base_cols):
    feats = pd.DataFrame(index=df.index)
    for c in base_cols:
        if c not in df.columns:
            continue
        v = pd.to_numeric(df[c], errors="coerce")
        if c in DIR_DEP:
            if c in ("mfi_60s","stoch_k_60s","stoch_d_60s","rsi_14"):
                v = v - 50.0
            elif c == "bb_pos_60s":
                v = v - 0.5
            v = v * df["dir_sign"]
        feats[c] = v
    return feats

def slice_baseline(df, spec):
    sub = df[(df["asset"]==spec["asset"]) & (df["tf"]==spec["tf"])].copy()
    sub = sub[sub["sleeve_id"].astype(str).str.startswith(spec["sleeve_prefix"])].copy()
    if spec["offset_bin"] is not None:
        sub = sub[sub["offset_bin"]==spec["offset_bin"]].copy()
    sub = sub.drop_duplicates(subset=["slug","fire_us","direction"]).reset_index(drop=True)
    return sub

def find_best_threshold(scores, pnl, threshold_candidates):
    best = None
    for t in threshold_candidates:
        m = scores >= t
        n = int(m.sum())
        if n < 30:
            continue
        sp = float(pnl[m].sum())
        if (best is None) or (sp > best["sum_pnl"]):
            best = {"threshold": float(t), "n": n, "sum_pnl": sp}
    if best is None:
        return {"threshold": 0.0, "n": 0, "sum_pnl": 0.0}
    return best


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
print("Loading master panel...")
df = pd.read_parquet(MASTER)
df["ts"] = pd.to_datetime(df["fire_us"]/1e6, unit="s")
df["split"] = np.where(df["ts"]<TRAIN_END, "train",
              np.where(df["ts"]<VAL_END,   "val", "lockbox"))
df["dir_sign"] = np.where(df["direction"].astype(str).str.upper()=="UP", 1.0, -1.0)
print(f"  rows: {len(df):,}  splits: {df['split'].value_counts().to_dict()}")

all_fires = []  # long-format per-fire predictions
all_thresh = []  # tuned thresholds + meta

for spec in BASELINE_SLEEVES:
    print(f"\n=== {spec['sleeve']} ===")
    sub = slice_baseline(df, spec)
    print(f"  base sleeve rows (after dedupe): {len(sub):,}")

    splits = {s: sub[sub["split"]==s].reset_index(drop=True) for s in ("train","val","lockbox")}

    # Build directional features
    feats_all = direction_sign_features(sub, CONT_FEATURES)
    nn = feats_all.notna().sum()
    keep = nn[nn > 0.25*len(sub)].index.tolist()
    feats_all = feats_all[keep]
    print(f"  features kept: {len(keep)}")

    feats_train_raw = feats_all.loc[sub["split"]=="train"]
    med = feats_train_raw.median()
    feats_imp = feats_all.fillna(med).fillna(0.0)

    Xtr = feats_imp.loc[sub["split"]=="train"].reset_index(drop=True)
    Xval = feats_imp.loc[sub["split"]=="val"].reset_index(drop=True)
    Xlock = feats_imp.loc[sub["split"]=="lockbox"].reset_index(drop=True)
    ytr = splits["train"]["won_int"].astype(int).values
    yval = splits["val"]["won_int"].astype(int).values
    ylock = splits["lockbox"]["won_int"].astype(int).values
    pnl_val = splits["val"]["pnl_legacy_usd"].values
    pnl_lock = splits["lockbox"]["pnl_legacy_usd"].values

    if len(Xtr) < 200 or len(Xval) < 50 or len(Xlock) < 50:
        print("  SKIP: insufficient rows")
        continue

    # Scale
    scaler = StandardScaler()
    Xtr_s = scaler.fit_transform(Xtr)
    Xval_s = scaler.transform(Xval)
    Xlock_s = scaler.transform(Xlock)
    Xall_s = scaler.transform(feats_imp)  # for full-window predictions too

    # ----------- 4 models -----------
    models = {}

    # 1. Ridge
    ridge = Ridge(alpha=10.0, random_state=42)
    ridge.fit(Xtr_s, ytr)
    models["ridge"] = {
        "val": ridge.predict(Xval_s),
        "lockbox": ridge.predict(Xlock_s),
        "all": ridge.predict(Xall_s),
    }
    # 2. ElasticNet
    en = ElasticNet(alpha=0.01, l1_ratio=0.5, random_state=42, max_iter=5000)
    en.fit(Xtr_s, ytr)
    models["elastic_net"] = {
        "val": en.predict(Xval_s),
        "lockbox": en.predict(Xlock_s),
        "all": en.predict(Xall_s),
    }
    # 3. LogReg L2
    lr = LogisticRegression(C=1.0, max_iter=2000, random_state=42)
    lr.fit(Xtr_s, ytr)
    models["logistic_l2"] = {
        "val": lr.predict_proba(Xval_s)[:,1],
        "lockbox": lr.predict_proba(Xlock_s)[:,1],
        "all": lr.predict_proba(Xall_s)[:,1],
    }
    # 4. LogReg Poly2 (interactions only)
    try:
        poly = PolynomialFeatures(degree=2, interaction_only=True, include_bias=False)
        Xtr_p = poly.fit_transform(Xtr_s)
        Xval_p = poly.transform(Xval_s)
        Xlock_p = poly.transform(Xlock_s)
        Xall_p = poly.transform(Xall_s)
        lr_poly = LogisticRegression(C=0.1, max_iter=2000, random_state=42)
        lr_poly.fit(Xtr_p, ytr)
        models["logistic_poly2"] = {
            "val": lr_poly.predict_proba(Xval_p)[:,1],
            "lockbox": lr_poly.predict_proba(Xlock_p)[:,1],
            "all": lr_poly.predict_proba(Xall_p)[:,1],
        }
    except Exception as e:
        print(f"  poly2 failed: {e}")

    # ----------- threshold tuning per model on val -----------
    for mname, m in models.items():
        score_val = m["val"]
        score_lock = m["lockbox"]
        score_all = m["all"]
        qs = np.unique(np.quantile(score_val, np.linspace(0.05, 0.95, 19)))
        best = find_best_threshold(score_val, pnl_val, qs)
        th = best["threshold"]

        # save thresholds
        all_thresh.append({
            "sleeve": spec["sleeve"], "model": mname,
            "threshold": th,
            "val_n": best["n"], "val_sum_pnl": best["sum_pnl"],
        })

        # Build long-format fires for this sleeve/model
        # Combine all splits (full window)
        out_df = sub[["asset","tf","slug","fire_us","direction","outcome","won","won_int","pnl_legacy_usd","offset_bin","fire_offset_s","ts","split","dir_sign"]].copy()
        out_df["sleeve"] = spec["sleeve"]
        out_df["model"] = mname
        out_df["proba"] = score_all
        out_df["threshold"] = th
        out_df["would_fire"] = (out_df["proba"] >= th).astype(int)
        all_fires.append(out_df)

    n_lock_lr2 = int(((models["logistic_l2"]["lockbox"] >= all_thresh[-3]["threshold"])).sum()) if "logistic_l2" in models else 0
    n_lock_poly2 = int(((models["logistic_poly2"]["lockbox"] >= all_thresh[-1]["threshold"])).sum()) if "logistic_poly2" in models else 0
    print(f"  lockbox firing: LR-L2 n={n_lock_lr2}  Poly2 n={n_lock_poly2}")

# ----------- save -----------
fires_df = pd.concat(all_fires, ignore_index=True)
thresh_df = pd.DataFrame(all_thresh)

fires_df.to_parquet(f"{OUT}/ws_fires_all_models_all_splits.parquet", compression="snappy")
thresh_df.to_csv(f"{OUT}/ws_thresholds.csv", index=False)
print(f"\nSAVED -> ws_fires_all_models_all_splits.parquet ({len(fires_df):,} rows)")
print(f"SAVED -> ws_thresholds.csv ({len(thresh_df)} rows)")

# Quick sanity check: sum pnl per sleeve x model on lockbox where would_fire=1
print("\n=== SANITY: lockbox sum_pnl per (sleeve, model) where would_fire=1 ===")
lock = fires_df[fires_df["split"]=="lockbox"].copy()
agg = lock[lock["would_fire"]==1].groupby(["sleeve","model"]).agg(
    n=("won_int","size"),
    wr=("won_int","mean"),
    sum_pnl=("pnl_legacy_usd","sum"),
).reset_index()
agg["wr_pct"] = (agg["wr"]*100).round(1)
print(agg[["sleeve","model","n","wr_pct","sum_pnl"]].to_string(index=False))

# Full window sum per (sleeve, model)
print("\n=== SANITY: full-window sum_pnl per (sleeve, model) where would_fire=1 ===")
agg_full = fires_df[fires_df["would_fire"]==1].groupby(["sleeve","model"]).agg(
    n=("won_int","size"),
    wr=("won_int","mean"),
    sum_pnl=("pnl_legacy_usd","sum"),
).reset_index()
agg_full["wr_pct"] = (agg_full["wr"]*100).round(1)
agg_full["sum_28d"] = agg_full["sum_pnl"] * (28/32)
print(agg_full[["sleeve","model","n","wr_pct","sum_pnl","sum_28d"]].to_string(index=False))

print("\nDone.")
