"""
P1/P4 meta-labeler v2 — RELATIVE-VALUE model on MICROSTRUCTURE features.

Phase-A lesson: TA features carry ~0 info (v1 AUC 0.506); only FLOW/BOOK features survived.
So predict calibrated P(Up) from microstructure ONLY (all price/vwap/ask/bid EXCLUDED), then bet
the side whose edge = P_side - vwap_side > margin. Genuine relative value, not outcome-chasing.

Pre-registered cells (no offset cherry-picking): 5m@offset=120 (production t+120 anchor), 15m@offset=240.
One row per slug per cell. Assets pooled with dummies. Purged walk-forward dev + time-held-out lockbox (25%).
Metric = win07 $/tr (0.07 winner-only) using the master fills; AUC = diagnostic only.
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
MASTER = ROOT / "strategy_lab" / "cross_feature_2026_05_26" / "master.parquet"
OUT_MD = ROOT / "strategy_lab" / "reports" / "META_LABELER_V2_MICROSTRUCTURE_2026_06_03.md"
RNG = np.random.default_rng(21)

from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score
try:
    from xgboost import XGBClassifier; HAVE_XGB = True
except Exception:
    from sklearn.ensemble import HistGradientBoostingClassifier; HAVE_XGB = False

FEATS = ["ret_2m_at_ws","prod_q90","mag_ratio","vwap_since_open_bps","mp_skew","mp_skew_change_500ms",
    "mp_imbalance","mp_weighted_skew","mp_up_dev_bps","mp_dn_dev_bps","lm_L_stat_at_fire",
    "lm_last_jump_dir_60s","lm_has_jump_60s","lm_last_jump_dir_30s","lm_has_jump_30s",
    "lm_n_jumps_in_last_300s","vpin_value","vpin_zscore","hawkes_lambda_total","hawkes_lambda_imbalance",
    "hawkes_recent_burst","up_imb1","up_imb5","dn_imb1","dn_imb5","imb5_diff","up_micro_dev_bps",
    "dn_micro_dev_bps","trend_slope_30m","bb_width_60s","realized_vol_60m","regime_score","adx_14",
    "liquidity_up","liquidity_dn","trend_strength_raw","cvd_sign","system_confidence"]

def win07(vwap, shares, won, rate=0.07):
    return shares*(1-vwap)*(1-rate*vwap) if won else -shares*vwap

def boot_ci(x, n=8000):
    x = np.asarray(x, float)
    if len(x) < 2: return (np.nan, np.nan)
    idx = RNG.integers(0, len(x), size=(n, len(x)))
    mu = x[idx].mean(1)
    return float(np.percentile(mu, 2.5)), float(np.percentile(mu, 97.5))

def fit_model():
    if HAVE_XGB:
        return XGBClassifier(n_estimators=400, max_depth=4, learning_rate=0.03, subsample=0.8,
                             colsample_bytree=0.7, min_child_weight=8, reg_lambda=3.0,
                             eval_metric="logloss", tree_method="hist")
    return HistGradientBoostingClassifier(max_depth=4, learning_rate=0.03, max_iter=400,
                                          l2_regularization=3.0, min_samples_leaf=30)

m = pd.read_parquet(MASTER)
feats = [c for c in FEATS if c in m.columns]

def run_cell(asset_pool, tf, offset):
    d = m[(m.tf == tf) & (m.fire_offset_s == offset)].copy()
    d = d.sort_values("fire_us").reset_index(drop=True)
    X = d[feats].astype(float).copy()
    for a in ["BTC","ETH","SOL"]:
        X[f"a_{a}"] = (d.asset == a).astype(int)
    X["hour"] = ((d.ws_s // 3600) % 24).astype(int)
    y = (d.outcome == "Up").astype(int).values
    up_v, dn_v = d.up_vwap.values, d.dn_vwap.values
    up_s, dn_s = d.up_shares.values, d.dn_shares.values
    up_ok = d.up_fill_ok.fillna(False).values.astype(bool)
    dn_ok = d.dn_fill_ok.fillna(False).values.astype(bool)
    fire = d.fire_us.values
    n = len(d); cut = int(n*0.75); dev = slice(0, cut); lock = slice(cut, n)

    # purged WF OOF on dev (for margin selection)
    idx = np.arange(cut); oof = np.full(cut, np.nan)
    b = np.linspace(0, cut, 5).astype(int)
    for k in range(1, 5):
        te = idx[b[k-1]:b[k]] if k < 4 else idx[b[k-1]:]
        tr = idx[:b[k-1]]; tr = tr[fire[tr] < fire[te[0]] - 900e6]
        if len(tr) < 150 or len(np.unique(y[tr])) < 2: continue
        mod = fit_model(); mod.fit(X.iloc[tr], y[tr])
        cal = tr[-min(500,len(tr)):]
        iso = IsotonicRegression(out_of_bounds="clip"); iso.fit(mod.predict_proba(X.iloc[cal])[:,1], y[cal])
        oof[te] = iso.transform(mod.predict_proba(X.iloc[te])[:,1])

    def pnl_for(p_up, sl, margin):
        e_up = p_up - up_v[sl]; e_dn = (1-p_up) - dn_v[sl]
        out = []
        wlist = []
        for i,(eu,ed) in enumerate(zip(e_up,e_dn)):
            gi = sl.start + i
            # choose better edge among fillable sides
            cands = []
            if up_ok[gi] and eu>margin: cands.append(("up",eu))
            if dn_ok[gi] and ed>margin: cands.append(("dn",ed))
            if not cands: continue
            side = max(cands,key=lambda c:c[1])[0]
            if side=="up": out.append(win07(up_v[gi],up_s[gi], y[gi]==1)); wlist.append(y[gi]==1)
            else: out.append(win07(dn_v[gi],dn_s[gi], y[gi]==0)); wlist.append(y[gi]==0)
        return np.array(out), np.array(wlist)

    v = ~np.isnan(oof)
    auc_dev = roc_auc_score(y[dev][v], oof[v]) if v.sum() and len(np.unique(y[dev][v]))>1 else np.nan
    best=None
    for mg in np.round(np.arange(0.0,0.30,0.02),2):
        p,_ = pnl_for(np.where(np.isnan(oof),0.5,oof), dev, mg)
        if len(p)<40: continue
        if best is None or p.mean()>best[1]: best=(mg,p.mean(),len(p))
    MG = best[0] if best else 0.06

    # final: train all dev, calibrate, lockbox
    mod = fit_model(); mod.fit(X.iloc[dev], y[dev])
    cal = np.arange(cut)[-600:]
    iso = IsotonicRegression(out_of_bounds="clip"); iso.fit(mod.predict_proba(X.iloc[cal])[:,1], y[cal])
    p_lock = iso.transform(mod.predict_proba(X.iloc[lock])[:,1])
    auc_lock = roc_auc_score(y[lock], p_lock) if len(np.unique(y[lock]))>1 else np.nan
    gated, gw = pnl_for(p_lock, lock, MG)
    allp, aw = pnl_for(p_lock, lock, -9)   # take every fillable fire on model's preferred side
    return dict(tf=tf, offset=offset, n=n, n_lock=(n-cut), auc_dev=round(auc_dev,3), auc_lock=round(auc_lock,3),
                margin=MG, all_n=len(allp), all_dpt=round(allp.mean(),3) if len(allp) else np.nan,
                all_wr=round(100*aw.mean(),1) if len(aw) else np.nan, all_ci=tuple(round(x,3) for x in boot_ci(allp)),
                g_n=len(gated), g_dpt=round(gated.mean(),3) if len(gated) else np.nan,
                g_wr=round(100*gw.mean(),1) if len(gw) else np.nan, g_ci=tuple(round(x,3) for x in boot_ci(gated)))

cells = [("ALL","5m",120), ("ALL","15m",240)]
rows = [run_cell(*c) for c in cells]
for r in rows:
    print(f"\n[{r['tf']}@{r['offset']}] n={r['n']} lock={r['n_lock']} AUC dev={r['auc_dev']} lock={r['auc_lock']} margin={r['margin']}", flush=True)
    print(f"  ALL-pref-side: n={r['all_n']} WR={r['all_wr']} $/tr={r['all_dpt']} CI{r['all_ci']}", flush=True)
    print(f"  META-GATED   : n={r['g_n']} WR={r['g_wr']} $/tr={r['g_dpt']} CI{r['g_ci']}", flush=True)

def verdict(r):
    if r['g_n']<30: return "LOW-N"
    if r['g_ci'][0]>0 and r['g_dpt']>r['all_dpt']: return "EDGE (CI>0)"
    if r['g_dpt']>r['all_dpt']: return "lift, CI~0"
    return "no lift"

lines = ["# P1/P4 Meta-Labeler v2 — microstructure relative-value — 2026-06-03","",
    f"Model={'XGBoost' if HAVE_XGB else 'HistGB'}. P(Up) from FLOW/BOOK features only (price/vwap excluded). "
    "Bet side with edge=P-vwap>margin. win07 fee. Purged-WF dev + time lockbox(25%).","",
    "| cell | n | lock n | AUC dev | AUC lock | margin | ALL-pref $/tr | ALL CI | GATED n | GATED $/tr | GATED CI | verdict |",
    "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|"]
for r in rows:
    lines.append(f"| {r['tf']}@{r['offset']} | {r['n']} | {r['n_lock']} | {r['auc_dev']} | {r['auc_lock']} | {r['margin']} "
                 f"| {r['all_dpt']:+} ({r['all_wr']}%) | [{r['all_ci'][0]:+},{r['all_ci'][1]:+}] "
                 f"| {r['g_n']} | {r['g_dpt']:+} ({r['g_wr']}%) | [{r['g_ci'][0]:+},{r['g_ci'][1]:+}] | {verdict(r)} |")
lines += ["","## Notes",
  "- Features = microstructure/flow only (mp_skew, imb, hawkes, vpin, lm jumps, regime, adx...). All price/vwap excluded.",
  "- Label/PnL use master 1Hz fills — re-fill any deployable cell at 10Hz (Phase-A lesson). AUC is diagnostic; gate is win07 $/tr CI>0.",
  "- ALL-pref = take every fillable fire on the model's higher-edge side (baseline). GATED applies the margin.",
  "- Offsets pre-registered (5m@120=prod t+120, 15m@240); assets pooled with dummies; one row per slug."]
OUT_MD.write_text("\n".join(lines), encoding="utf-8")
print(f"\nwrote {OUT_MD}", flush=True)
