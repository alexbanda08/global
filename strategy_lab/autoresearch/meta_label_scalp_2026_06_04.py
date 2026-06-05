"""
CPCV + META-LABEL the EXIT-SCALP  (HANDOFF 2026-06-04 step D-1).

Question: does a meta-model on CAUSAL fire-time features sharpen take/skip on the
confirmed exit-scalp edge beyond the hand-tuned `delta_bps>=5` cut — validated
OUT-OF-FOLD with purged Combinatorial CV, and does it survive PBO + Deflated Sharpe?

Pre-registered (locked before seeing OOF):
  universe : BTC+ETH, entry_vwap < 0.55  (the 'buy-cheap' edge zone)
  features : 61 causal = indicators(37)+clob(22)+entry(2). physics+path EXCLUDED (leak/no-lift).
  label    : ml4t meta_labels(signal=+1, return=pnl45, thr=0); sample weight = |pnl45|
  model    : L2 logistic (C=0.3) on standardized feats. gate proba>=0.5 (fixed).
             LightGBM reported SECONDARY (counts as extra trial -> deflated).
  cv       : ml4t CombinatorialCV(n_groups=8, n_test_groups=2)=28 purged/embargoed paths.
  judge    : per-trade t + bootstrap CI ; PBO over threshold grid ; DSR on daily gated returns.

Baselines to beat (in-sample full-window, BTC+ETH):
  all-take vwap<0.55 : n=780  pnl45=+2.71
  hand d>=5 cell     : n=118  pnl45=+5.56
"""
import sys, json, warnings
import numpy as np, pandas as pd
import polars as pl
warnings.filterwarnings("ignore")
np.random.seed(0)

from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from lightgbm import LGBMClassifier

from ml4t.engineer.labeling import meta_labels
from ml4t.diagnostic.splitters.combinatorial import CombinatorialCV
from ml4t.diagnostic.evaluation.stats.backtest_overfitting import compute_pbo
from ml4t.diagnostic.evaluation.stats.deflated_sharpe_ratio import (
    deflated_sharpe_ratio, deflated_sharpe_ratio_from_statistics,
)

EXIT = "pnl45"               # the confirmed exit (+45s >= +60s per audit)
FG = json.load(open(r"strategy_lab\autoresearch\_data\feature_groups.json"))
FEATS = FG["indicators"] + FG["clob"] + FG["entry"]   # 61 causal
print(f"features: {len(FEATS)} causal (physics+path excluded)")

# ---- load universe ----
m = pd.read_parquet(r"strategy_lab\autoresearch\_data\master_features.parquet")
m = m[m.asset.isin(["BTC", "ETH"])].copy()
m = m[m.entry_vwap < 0.55].copy()
m = m.sort_values("fire_us").reset_index(drop=True)
n = len(m)
print(f"universe n={n}  pnl45 all-take={m[EXIT].mean():+.3f}  won={m.won.mean():.3f}")

# ---- label via ml4t meta_labels ----
pf = pl.DataFrame({"signal": np.ones(n, dtype=np.int64), "ret": m[EXIT].values})
ml = meta_labels(pf, signal_col="signal", return_col="ret", threshold=0.0)
y = ml["meta_label"].to_numpy().astype(int)
print(f"label rate (pnl45>0) = {y.mean():.3f}")

X = m[FEATS].astype(float).values
ret = m[EXIT].values                      # per-trade $ pnl at +45s
w = np.abs(ret) + 1e-6                     # return-weighted (Lopez de Prado)
days = pd.to_datetime(m.fire_us, unit="us").dt.floor("D").values

def daily_sharpe(mask):
    """Daily-aggregated $ PnL Sharpe of the gated subset (0 on no-trade days within span)."""
    d = pd.Series(ret[mask], index=pd.to_datetime(m.fire_us[mask], unit="us").dt.floor("D"))
    dd = d.groupby(level=0).sum()
    full = pd.date_range(dd.index.min(), dd.index.max(), freq="D")
    dd = dd.reindex(full, fill_value=0.0)
    if dd.std(ddof=1) == 0 or len(dd) < 3:
        return np.nan, dd.values
    return dd.mean() / dd.std(ddof=1), dd.values

def boot_ci(vals, n_boot=5000):
    idx = np.random.randint(0, len(vals), size=(n_boot, len(vals)))
    means = vals[idx].mean(axis=1)
    return np.percentile(means, [2.5, 97.5])

def fit_predict(model_name, Xtr, ytr, wtr, Xte):
    if model_name == "logit":
        sc = StandardScaler().fit(Xtr)
        clf = LogisticRegression(C=0.3, max_iter=2000, class_weight=None)
        clf.fit(sc.transform(Xtr), ytr, sample_weight=wtr)
        return clf.predict_proba(sc.transform(Xte))[:, 1]
    else:  # gbm
        clf = LGBMClassifier(n_estimators=200, num_leaves=7, max_depth=3,
                             min_child_samples=30, subsample=0.8, colsample_bytree=0.6,
                             reg_lambda=5.0, learning_rate=0.03, random_state=0, verbose=-1)
        clf.fit(Xtr, ytr, sample_weight=wtr)
        return clf.predict_proba(Xte)[:, 1]

# median-impute on TRAIN only (leakage-safe)
def impute(Xtr, Xte):
    med = np.nanmedian(Xtr, axis=0)
    med = np.where(np.isfinite(med), med, 0.0)
    Xtr2 = np.where(np.isfinite(Xtr), Xtr, med)
    Xte2 = np.where(np.isfinite(Xte), Xte, med)
    return Xtr2, Xte2

# ---- Combinatorial Purged CV ----
cv = CombinatorialCV(n_groups=8, n_test_groups=2, embargo_pct=0.01)
splits = list(cv.split(X))
print(f"CPCV paths: {len(splits)} (C(8,2)=28 expected)")

THRESH = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65]   # threshold grid (for PBO/deflation)

OOF = {}
for MODEL in ["logit", "gbm"]:
    oof_sum = np.zeros(n); oof_cnt = np.zeros(n)
    is_perf = []; oos_perf = []          # PBO matrices: rows=paths, cols=thresholds
    path_sharpe = []                     # per-path test daily Sharpe @0.5
    for tr, te in splits:
        Xtr, Xte = impute(X[tr], X[te])
        p = fit_predict(MODEL, Xtr, y[tr], w[tr], Xte)
        oof_sum[te] += p; oof_cnt[te] += 1
        # train proba for IS perf
        ptr = fit_predict(MODEL, Xtr, y[tr], w[tr], Xtr)
        is_row = []; oos_row = []
        for t in THRESH:
            mtr = ptr >= t; mte = p >= t
            is_row.append(ret[tr][mtr].mean() if mtr.sum() else -9.9)
            oos_row.append(ret[te][mte].mean() if mte.sum() else -9.9)
        is_perf.append(is_row); oos_perf.append(oos_row)
        mte5 = p >= 0.5
        if mte5.sum() >= 3:
            te_days = pd.Series(ret[te][mte5],
                                index=pd.to_datetime(m.fire_us.values[te][mte5], unit="us").floor("D"))
            dd = te_days.groupby(level=0).sum()
            if len(dd) >= 3 and dd.std(ddof=1) > 0:
                path_sharpe.append(dd.mean() / dd.std(ddof=1))

    oof = np.where(oof_cnt > 0, oof_sum / np.maximum(oof_cnt, 1), np.nan)
    OOF[MODEL] = oof
    valid = oof_cnt > 0
    print(f"\n===== MODEL = {MODEL} =====")
    print(f"OOF coverage: {valid.sum()}/{n} (each ~{int(np.median(oof_cnt[valid]))} preds)")

    # pre-registered gate @0.5
    gate = valid & (oof >= 0.5)
    g_ret = ret[gate]
    base = ret[valid]
    print(f"all-take(valid) : n={valid.sum():4d}  $/tr={base.mean():+.3f}")
    print(f"META gate@0.50  : n={gate.sum():4d}  $/tr={g_ret.mean():+.3f}  won={m.won.values[gate].mean():.3f}")
    if gate.sum() > 5:
        t_stat = g_ret.mean() / g_ret.std(ddof=1) * np.sqrt(len(g_ret))
        ci = boot_ci(g_ret)
        print(f"                  t={t_stat:.2f}  boot95%CI=[{ci[0]:+.3f},{ci[1]:+.3f}]  lift_vs_alltake={g_ret.mean()-base.mean():+.3f}")

    # selectivity-matched delta baseline: pick top-k by delta_bps to match gate n
    k = int(gate.sum())
    dmatch = m.iloc[np.argsort(-m.delta_bps.values)[:k]] if k > 0 else m.iloc[:0]
    print(f"delta-top{k} match: n={len(dmatch):4d}  $/tr={dmatch[EXIT].mean():+.3f}  (meta must beat this to add value)")

    # PBO
    pbo = compute_pbo(np.array(is_perf), np.array(oos_perf))
    print(f"PBO over {len(THRESH)} thresholds: {pbo.pbo:.3f}  (0=no overfit, >0.5=harmful)")

    # DSR — pre-registered (gate@0.5, effective_trials=1) on daily gated returns
    sh, dvals = daily_sharpe(gate)
    if np.isfinite(sh):
        dsr1 = deflated_sharpe_ratio(dvals, frequency="daily", effective_trials=1.0)
        print(f"DSR pre-reg (k_eff=1): daily_Sharpe={sh:.3f} prob={dsr1.probability:.3f} sig={dsr1.is_significant}")
        # deflated for the threshold search (n_trials=len(THRESH), variance from path sharpes)
        vt = float(np.var(path_sharpe)) if len(path_sharpe) > 2 else 0.25
        dsr2 = deflated_sharpe_ratio_from_statistics(
            observed_sharpe=sh, n_samples=len(dvals), n_trials=len(THRESH),
            variance_trials=vt, frequency="daily")
        dsr2c = deflated_sharpe_ratio_from_statistics(
            observed_sharpe=sh, n_samples=len(dvals), n_trials=len(THRESH),
            variance_trials=vt * 4, frequency="daily")
        print(f"DSR deflated (n_trials={len(THRESH)}, vt={vt:.3f}): prob={dsr2.probability:.3f} sig={dsr2.is_significant}"
              f"  | conservative(4x vt): prob={dsr2c.probability:.3f} sig={dsr2c.is_significant}")
        print(f"path daily Sharpes: n={len(path_sharpe)} mean={np.mean(path_sharpe):.3f}" if path_sharpe else "path sharpes: n/a")
    else:
        print("DSR: gated subset too small/degenerate for daily Sharpe")

# ---- SELECTIVITY CURVE: can the model build a better small high-conviction book than 1-feature knobs? ----
# Adversarial: meta-top-k must beat delta-top-k AND vwap-low-top-k at every k to add value.
print("\n===== SELECTIVITY CURVE (OOF $/tr at top-k by score) =====")
print(f"{'k':>4} {'meta_logit':>11} {'meta_gbm':>10} {'delta_top':>10} {'vwap_low':>9}")
order_delta = np.argsort(-m.delta_bps.values)        # highest delta first
order_vwap  = np.argsort(m.entry_vwap.values)         # cheapest first
for k in [60, 100, 118, 150, 200, 300, 400, 500, 641, 780]:
    if k > n: continue
    row = [f"{k:>4}"]
    for mdl in ["logit", "gbm"]:
        ok = np.argsort(-OOF[mdl])[:k]
        row.append(f"{ret[ok].mean():>+11.3f}")
    row.append(f"{ret[order_delta[:k]].mean():>+10.3f}")
    row.append(f"{ret[order_vwap[:k]].mean():>+9.3f}")
    print(" ".join(row))
cell = (m.delta_bps.values >= 5)
print(f"\nhand d>=5 cell: n={cell.sum()} $/tr={ret[cell].mean():+.3f}  (the pre-registered confirmed edge)")
print("READ: if meta columns do not exceed delta_top/vwap_low at matched k, the ML filter adds no edge.")
print("\nDONE.")
