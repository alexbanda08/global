"""
Weighted-voting scoring vs Binary AND-gate baselines.
2026-05-26.

For each top-7 hybrid_v1 sleeve:
  TASK 1: restrict to fires where the BASE sleeve trigger fires (the prefix s6_5m / s15_5m / s7-equivalent on the right asset/offset_bin).
  TASK 2: build weighted score (Ridge / EN / Logistic / PolyLR) on continuous features.
  TASK 3: compare lockbox performance vs hybrid_v1 baseline (AND-gates).
  TASK 4: extract feature weights.
  TASK 5: polynomial-degree-2 interactions explicitly.
  TASK 6: calibration (isotonic).
  TASK 7: 3-way split (train/val/lockbox) bootstrap.
  TASK 8: weighted score AS extra gate.

Output:
  weighted_models_results.csv  (one row per (sleeve, model_variant, split) with metrics)
  feature_weights.csv          (one row per (sleeve, model, feature) with weight)
  hybrid_v8_lockbox.csv        (lockbox metrics: AND vs WS vs WS+AND)
  calibration_plots/*.csv      (predicted vs actual WR per bin)
  bootstrap_results.csv        (500-shuffle bootstrap on lockbox)
"""

import os, sys, json, warnings, hashlib
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
from pathlib import Path

from sklearn.linear_model import Ridge, ElasticNet, LogisticRegression
from sklearn.preprocessing import StandardScaler, PolynomialFeatures
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import log_loss

OUT = Path(r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/weighted_voting_2026_05_26")
OUT.mkdir(parents=True, exist_ok=True)
MASTER = r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/master_gate_features_v2.parquet"

# 6 baseline sleeves from deep_stack_3way_validation.csv (we'll add a 7th below)
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
    {"sleeve": "S7_BTC_5m_base",  "asset": "BTC", "tf": "5m", "offset_bin": None,  # all offsets / wider
     "sleeve_prefix": "s15_5m",  # S7 = full TR-stack on S15 in this panel
     # g_tr_stack_full_with NOT in panel; use g_tr_stack_with (next-best)
     "gates": ["g_tr_stack_with","g_tr_above_ema800","g_ribbon_agrees","g_tight_ribbon","g_stoch_with","g_tr_above_ema200"]},
    # 7th sleeve: SOL S15 60-150 (next-best per deep_stack)
    {"sleeve": "SOL_S15_60_150",  "asset": "SOL", "tf": "5m", "offset_bin": "60-150",
     "sleeve_prefix": "s15_5m",
     "gates": ["g_ribbon_agrees","g_stoch_with","g_bb_pos_with","g_cci_with"]},
]

# Continuous features to use. user-listed; some not in panel (queue_position_top, ribbon_lead_slope_bps).
# Replace missing with closest available.
CONT_FEATURES = [
    # microprice (skew + change)
    "mp_skew", "mp_weighted_skew", "mp_skew_change_500ms", "mp_up_dev_bps", "mp_dn_dev_bps",
    "mp_imbalance", "mp_weighted_imbalance",
    # Lee-Mykland
    "L_stat",
    # Hawkes
    "hawkes_lambda_imbalance", "hawkes_lambda_total",
    # vol / Hurst / trend
    "rv_ratio_60_to_3600", "hurst_300s", "hurst_100s", "hurst_900s",
    "trend_slope_30m", "rv_60s", "rv_300s",
    # microstructure
    "up_imb5", "dn_imb5", "up_imb25", "dn_imb25",
    "up_queue_top_bid", "up_micro_dev_bps", "dn_micro_dev_bps",
    "up_bid_slope", "up_ask_slope", "dn_bid_slope", "dn_ask_slope",
    "up_imb5_change_500ms", "up_quote_intensity_5s",
    # ribbon
    "ribbon_alignment_pct", "ribbon_compression_bps",
    # ADX
    "adx_14", "plus_di_14", "minus_di_14",
    # dev
    "vwap_since_open_bps",
    # mfi / stoch / cci / bb_pos (continuous form)
    "mfi_60s", "stoch_k_60s", "stoch_d_60s", "cci_60s", "bb_pos_60s", "bb_width_60s",
    # ofi
    "ofi_skew_l1_30s", "mlofi_skew_l5_30s", "mlofi_skew_l5_60s", "mlofi_skew_l25_30s",
    # rsi/cvd
    "rsi_14", "cvd",
    # vpin
    "vpin_value", "vpin_zscore",
    # as-uncertainty
    "as_uncertainty", "as_skew",
]

# Splits (matching R5/R4)
TRAIN_END = pd.Timestamp("2026-05-15")
VAL_END   = pd.Timestamp("2026-05-22")

# ------------------------------------------------------------
def load_panel():
    print("Loading master panel...")
    df = pd.read_parquet(MASTER)
    df["ts"] = pd.to_datetime(df["fire_us"]/1e6, unit="s")
    df["split"] = np.where(df["ts"]<TRAIN_END, "train",
                  np.where(df["ts"]<VAL_END,   "val", "lockbox"))
    df["dir_sign"] = np.where(df["direction"].astype(str).str.upper()=="UP", 1.0, -1.0)
    print(f"  rows: {len(df):,}")
    print(f"  split counts: {df['split'].value_counts().to_dict()}")
    return df


def direction_sign_features(df, base_cols):
    """For directional features, flip sign if direction is DOWN so weights have consistent meaning."""
    # Features that depend on bet direction: skews, imbalances, OFI, etc.
    dir_dep = {
        "mp_skew", "mp_weighted_skew", "mp_skew_change_500ms",
        "mp_imbalance", "mp_weighted_imbalance",
        "up_imb5", "up_imb25", "up_micro_dev_bps", "up_bid_slope", "up_ask_slope",
        "up_imb5_change_500ms",
        "dn_imb5", "dn_imb25", "dn_micro_dev_bps", "dn_bid_slope", "dn_ask_slope",
        "hawkes_lambda_imbalance",
        "ofi_skew_l1_30s", "mlofi_skew_l5_30s", "mlofi_skew_l5_60s", "mlofi_skew_l25_30s",
        "trend_slope_30m", "as_skew",
        "vwap_since_open_bps", "cvd",
        "mfi_60s",  # 0-100 around 50
        "stoch_k_60s", "stoch_d_60s",
        "cci_60s",
        "bb_pos_60s",  # 0-1 centered at 0.5
        "rsi_14",
    }
    feats = pd.DataFrame(index=df.index)
    for c in base_cols:
        if c not in df.columns:
            continue
        v = pd.to_numeric(df[c], errors="coerce")
        if c in dir_dep:
            # center first for 0-100 indicators
            if c in ("mfi_60s","stoch_k_60s","stoch_d_60s","rsi_14"):
                v = v - 50.0
            elif c == "bb_pos_60s":
                v = v - 0.5
            v = v * df["dir_sign"]
        feats[c] = v
    return feats


def slice_baseline(df, spec):
    """Sleeve panel restricted to fires where the BASE sleeve trigger fires.

    The base trigger here = same prefix sleeve_id, asset, offset_bin filter. The
    'base_gates AND' is the binary baseline; we do NOT filter by it here — we
    keep all the rows where the underlying sleeve fired so the weighted model
    can choose to score amongst these.

    For comparison vs hybrid_v1 baseline, we recompute that on the same slice.
    """
    sub = df[(df["asset"]==spec["asset"]) & (df["tf"]==spec["tf"])].copy()
    sub = sub[sub["sleeve_id"].astype(str).str.startswith(spec["sleeve_prefix"])].copy()
    if spec["offset_bin"] is not None:
        sub = sub[sub["offset_bin"]==spec["offset_bin"]].copy()
    # dedupe by (slug, fire_us) — same fire may match multiple sleeve_id rows
    sub = sub.drop_duplicates(subset=["slug","fire_us","direction"]).reset_index(drop=True)
    return sub


def evaluate_lockbox(scores, won, pnl, threshold):
    """Given a score (higher=more likely win) and a threshold, compute metrics on the subset where score>=threshold."""
    mask = scores >= threshold
    n = int(mask.sum())
    if n == 0:
        return {"n":0, "wr":0.0, "dpt":0.0, "sum_pnl":0.0}
    return {"n": n,
            "wr": float(won[mask].mean()),
            "dpt": float(pnl[mask].mean()),
            "sum_pnl": float(pnl[mask].sum())}


def find_best_threshold(scores, won, pnl, threshold_candidates):
    """Find threshold that maximizes sum_pnl on val. Constrain minimum n=30 for stability."""
    best = None
    for t in threshold_candidates:
        m = scores >= t
        n = int(m.sum())
        if n < 30:
            continue
        sp = float(pnl[m].sum())
        if (best is None) or (sp > best["sum_pnl"]):
            best = {"threshold": float(t), "n":n, "wr":float(won[m].mean()),
                    "dpt":float(pnl[m].mean()), "sum_pnl":sp}
    if best is None:
        return {"threshold": 0.0, "n":0, "wr":0.0, "dpt":0.0, "sum_pnl":0.0}
    return best


def bootstrap_pnl(scores, won, pnl, threshold, n_boot=500, rng=None):
    """500-shuffle bootstrap: resample with replacement, compute sum_pnl at threshold, p = frac sum<=0."""
    rng = rng or np.random.default_rng(42)
    mask = scores >= threshold
    if mask.sum() < 5:
        return {"n":int(mask.sum()), "p_value":1.0, "ci_low":0.0, "ci_high":0.0}
    sample_pnl = pnl[mask] if isinstance(pnl, np.ndarray) else pnl[mask].values
    n = len(sample_pnl)
    sums = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, n)
        sums[i] = sample_pnl[idx].sum()
    p = float((sums <= 0).mean())
    ci_low, ci_high = float(np.percentile(sums, 2.5)), float(np.percentile(sums, 97.5))
    return {"n": int(n), "p_value": p, "ci_low": ci_low, "ci_high": ci_high}


# ------------------------------------------------------------
def fit_and_score_models(X_tr, y_tr, X_val, y_val, X_lock):
    """Fit four model variants. Return dict of score arrays for each variant on val and lockbox."""
    out = {}

    # Scale on train
    scaler = StandardScaler()
    Xtr_s = scaler.fit_transform(X_tr)
    Xval_s = scaler.transform(X_val)
    Xlock_s = scaler.transform(X_lock)

    # 1. Ridge
    ridge = Ridge(alpha=10.0, random_state=42)
    ridge.fit(Xtr_s, y_tr)
    out["ridge"] = {
        "val": ridge.predict(Xval_s),
        "lockbox": ridge.predict(Xlock_s),
        "coefs": dict(zip(X_tr.columns, ridge.coef_)),
        "intercept": float(ridge.intercept_),
    }

    # 2. Elastic Net
    en = ElasticNet(alpha=0.01, l1_ratio=0.5, random_state=42, max_iter=5000)
    en.fit(Xtr_s, y_tr)
    out["elastic_net"] = {
        "val": en.predict(Xval_s),
        "lockbox": en.predict(Xlock_s),
        "coefs": dict(zip(X_tr.columns, en.coef_)),
        "intercept": float(en.intercept_),
    }

    # 3. Logistic regression (L2)
    lr = LogisticRegression(C=1.0, max_iter=2000, random_state=42)
    lr.fit(Xtr_s, y_tr)
    out["logistic_l2"] = {
        "val": lr.predict_proba(Xval_s)[:,1],
        "lockbox": lr.predict_proba(Xlock_s)[:,1],
        "coefs": dict(zip(X_tr.columns, lr.coef_[0])),
        "intercept": float(lr.intercept_[0]),
    }

    # 4. Polynomial deg-2 logistic (interactions only to keep dimensionality manageable)
    try:
        poly = PolynomialFeatures(degree=2, interaction_only=True, include_bias=False)
        Xtr_p = poly.fit_transform(Xtr_s)
        Xval_p = poly.transform(Xval_s)
        Xlock_p = poly.transform(Xlock_s)
        # ridge-regularize hard given the dim blow-up
        lr_poly = LogisticRegression(C=0.1, max_iter=2000, random_state=42)
        lr_poly.fit(Xtr_p, y_tr)
        feat_names = poly.get_feature_names_out(X_tr.columns)
        out["logistic_poly2"] = {
            "val": lr_poly.predict_proba(Xval_p)[:,1],
            "lockbox": lr_poly.predict_proba(Xlock_p)[:,1],
            "coefs": dict(zip(feat_names, lr_poly.coef_[0])),
            "intercept": float(lr_poly.intercept_[0]),
        }
    except Exception as e:
        print(f"  poly2 failed: {e}")

    return out


# ------------------------------------------------------------
def calibration_table(y_true, y_pred, n_bins=10):
    """Return dataframe of bin -> predicted mean / actual mean / count."""
    edges = np.quantile(y_pred, np.linspace(0,1,n_bins+1))
    edges = np.unique(edges)
    if len(edges) < 3:
        return pd.DataFrame()
    bins = np.searchsorted(edges, y_pred, side="right") - 1
    bins = np.clip(bins, 0, len(edges)-2)
    rows = []
    for b in range(len(edges)-1):
        m = bins==b
        if m.sum()==0: continue
        rows.append({"bin":b, "low":edges[b], "high":edges[b+1],
                     "n":int(m.sum()),
                     "pred_mean":float(y_pred[m].mean()),
                     "actual_mean":float(y_true[m].mean())})
    return pd.DataFrame(rows)


# ------------------------------------------------------------
def hybrid_v1_metrics(sub_split, gates):
    """Compute the binary AND baseline on the slice."""
    mask = pd.Series(True, index=sub_split.index)
    for g in gates:
        if g not in sub_split.columns:
            mask &= False
            continue
        mask &= sub_split[g].fillna(0).astype(bool)
    n = int(mask.sum())
    if n == 0:
        return {"n":0,"wr":0.0,"dpt":0.0,"sum_pnl":0.0}
    return {"n":n,
            "wr":float(sub_split.loc[mask,"won_int"].mean()),
            "dpt":float(sub_split.loc[mask,"pnl_legacy_usd"].mean()),
            "sum_pnl":float(sub_split.loc[mask,"pnl_legacy_usd"].sum())}


# ============================================================
def main():
    df = load_panel()

    all_results = []
    all_weights = []
    all_calib = []
    all_boot = []
    all_hybrid_v8 = []

    for spec in BASELINE_SLEEVES:
        print(f"\n=== {spec['sleeve']} ===")
        sub = slice_baseline(df, spec)
        print(f"  base sleeve rows (after dedupe): {len(sub):,}")

        # split per row
        splits = {s: sub[sub["split"]==s].reset_index(drop=True) for s in ("train","val","lockbox")}
        for s, d in splits.items():
            print(f"  {s}: n={len(d)}, wr={d['won_int'].mean():.3f} sum_pnl=${d['pnl_legacy_usd'].sum():.0f}")

        # Build directional features per split
        feats_all = direction_sign_features(sub, CONT_FEATURES)
        # Drop cols that are entirely null OR have very high NA rate
        nn = feats_all.notna().sum()
        keep = nn[nn > 0.25*len(sub)].index.tolist()  # at least 25% coverage
        feats_all = feats_all[keep]
        print(f"  features kept (>25% cov): {len(keep)}")

        # Impute NA with train median
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
            print("  SKIP: insufficient rows in some split")
            continue

        # === Binary AND baseline (hybrid_v1) on each split for reference ===
        for s_name, d_split in splits.items():
            hv = hybrid_v1_metrics(d_split, spec["gates"])
            hv.update({"sleeve": spec["sleeve"], "variant": "hybrid_v1_AND",
                       "split": s_name, "threshold": np.nan, "boot_p": np.nan,
                       "n_universe": len(d_split)})
            all_results.append(hv)

        # === Fit weighted models ===
        models = fit_and_score_models(Xtr, ytr, Xval, yval, Xlock)

        # Pre-compute hybrid_v1 lockbox count for top-N comparison
        v1_lock_metrics = hybrid_v1_metrics(splits["lockbox"], spec["gates"])
        n_match = v1_lock_metrics["n"]

        # For each model: tune threshold on val, evaluate on lockbox
        for mname, m in models.items():
            score_val = m["val"]
            score_lock = m["lockbox"]
            # threshold candidates: 21 quantiles of val scores
            qs = np.quantile(score_val, np.linspace(0.05, 0.95, 19))
            qs = np.unique(qs)
            best = find_best_threshold(score_val, yval, pnl_val, qs)
            # eval val + lockbox at this threshold
            ev_train = evaluate_lockbox(m.get("train_dummy", np.zeros(0)), ytr, splits["train"]["pnl_legacy_usd"].values, best["threshold"]) if False else None
            ev_val = evaluate_lockbox(score_val, yval, pnl_val, best["threshold"])
            ev_lock = evaluate_lockbox(score_lock, ylock, pnl_lock, best["threshold"])

            # bootstrap
            boot = bootstrap_pnl(score_lock, ylock, pnl_lock, best["threshold"])

            all_results.append({"sleeve": spec["sleeve"], "variant": mname, "split":"val",
                                "n": ev_val["n"], "wr": ev_val["wr"], "dpt": ev_val["dpt"],
                                "sum_pnl": ev_val["sum_pnl"],
                                "threshold": best["threshold"], "boot_p": np.nan,
                                "n_universe": len(Xval)})
            all_results.append({"sleeve": spec["sleeve"], "variant": mname, "split":"lockbox",
                                "n": ev_lock["n"], "wr": ev_lock["wr"], "dpt": ev_lock["dpt"],
                                "sum_pnl": ev_lock["sum_pnl"],
                                "threshold": best["threshold"], "boot_p": boot["p_value"],
                                "n_universe": len(Xlock)})
            # Top-N (same throughput as hybrid_v1) for fair comparison
            if n_match > 0 and n_match < len(score_lock):
                topN_threshold = float(np.quantile(score_lock, 1.0 - n_match/len(score_lock)))
                ev_topN = evaluate_lockbox(score_lock, ylock, pnl_lock, topN_threshold)
                all_results.append({"sleeve": spec["sleeve"], "variant": f"{mname}_topN",
                                    "split":"lockbox",
                                    "n": ev_topN["n"], "wr": ev_topN["wr"], "dpt": ev_topN["dpt"],
                                    "sum_pnl": ev_topN["sum_pnl"],
                                    "threshold": topN_threshold, "boot_p": np.nan,
                                    "n_universe": len(Xlock)})

            # weights
            for fname, w in m["coefs"].items():
                all_weights.append({"sleeve": spec["sleeve"], "model": mname,
                                    "feature": fname, "weight": float(w)})
            # bootstrap row
            all_boot.append({"sleeve": spec["sleeve"], "model": mname,
                             "threshold": best["threshold"],
                             "n_lock": boot["n"], "boot_p": boot["p_value"],
                             "ci_low": boot["ci_low"], "ci_high": boot["ci_high"]})

            # calibration on val (for prob-models only)
            if mname in ("logistic_l2","logistic_poly2"):
                ct = calibration_table(yval, score_val)
                if not ct.empty:
                    ct["sleeve"] = spec["sleeve"]; ct["model"] = mname
                    all_calib.append(ct)

        # === TASK 8: weighted-score AS extra gate on top of hybrid_v1 ===
        # use logistic_l2 (interpretable) as gate
        m_l2 = models["logistic_l2"]
        score_val = m_l2["val"]; score_lock = m_l2["lockbox"]
        # threshold tuned on val for max sum_pnl ABOVE hybrid_v1
        gate_v1_val = pd.Series(True, index=range(len(splits["val"])))
        for g in spec["gates"]:
            if g in splits["val"].columns:
                gate_v1_val &= splits["val"][g].reset_index(drop=True).fillna(0).astype(bool)
            else:
                gate_v1_val &= False
        gate_v1_lock = pd.Series(True, index=range(len(splits["lockbox"])))
        for g in spec["gates"]:
            if g in splits["lockbox"].columns:
                gate_v1_lock &= splits["lockbox"][g].reset_index(drop=True).fillna(0).astype(bool)
            else:
                gate_v1_lock &= False

        # Within gate-v1 val, tune logistic threshold
        sv_within = score_val[gate_v1_val.values]
        yv_within = yval[gate_v1_val.values]
        pv_within = pnl_val[gate_v1_val.values]
        if len(sv_within) >= 50:
            qs = np.quantile(sv_within, np.linspace(0.05, 0.95, 19))
            qs = np.unique(qs)
            best_combo = find_best_threshold(sv_within, yv_within, pv_within, qs)
            # apply to lockbox
            sl_within = score_lock[gate_v1_lock.values]
            yl_within = ylock[gate_v1_lock.values]
            pl_within = pnl_lock[gate_v1_lock.values]
            combo_lock = evaluate_lockbox(sl_within, yl_within, pl_within, best_combo["threshold"])
            # vs hybrid_v1 on lockbox
            v1_lock = hybrid_v1_metrics(splits["lockbox"], spec["gates"])
            all_hybrid_v8.append({
                "sleeve": spec["sleeve"],
                "variant": "hybrid_v8_WS_gate",
                "threshold": best_combo["threshold"],
                "n_v1": v1_lock["n"], "wr_v1": v1_lock["wr"], "dpt_v1": v1_lock["dpt"], "sum_v1": v1_lock["sum_pnl"],
                "n_combo": combo_lock["n"], "wr_combo": combo_lock["wr"], "dpt_combo": combo_lock["dpt"], "sum_combo": combo_lock["sum_pnl"],
                "delta_sum": combo_lock["sum_pnl"] - v1_lock["sum_pnl"],
                "delta_wr": combo_lock["wr"] - v1_lock["wr"],
                "delta_dpt": combo_lock["dpt"] - v1_lock["dpt"],
            })

    # Save
    df_res = pd.DataFrame(all_results)
    df_res.to_csv(OUT/"weighted_models_results.csv", index=False)
    print(f"\nSaved {OUT/'weighted_models_results.csv'} ({len(df_res)} rows)")

    df_w = pd.DataFrame(all_weights)
    df_w.to_csv(OUT/"feature_weights.csv", index=False)
    print(f"Saved {OUT/'feature_weights.csv'} ({len(df_w)} rows)")

    df_b = pd.DataFrame(all_boot)
    df_b.to_csv(OUT/"bootstrap_results.csv", index=False)
    print(f"Saved {OUT/'bootstrap_results.csv'} ({len(df_b)} rows)")

    df_h = pd.DataFrame(all_hybrid_v8)
    df_h.to_csv(OUT/"hybrid_v8_lockbox.csv", index=False)
    print(f"Saved {OUT/'hybrid_v8_lockbox.csv'} ({len(df_h)} rows)")

    if all_calib:
        df_c = pd.concat(all_calib, ignore_index=True)
        df_c.to_csv(OUT/"calibration_table.csv", index=False)
        print(f"Saved {OUT/'calibration_table.csv'} ({len(df_c)} rows)")

    print("\nDone.")


if __name__ == "__main__":
    main()
