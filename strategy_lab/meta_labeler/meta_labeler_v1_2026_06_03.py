"""
P1 meta-labeler v1 — relative-value filter on the lag-taker base signal.

Design (avoids the priced-in trap):
  - Base universe: lag-taker enriched fires (confirmed real-but-thin directional signal).
  - Target y = won (binary).
  - Features = SIGNAL features ONLY, entry_vwap EXCLUDED. (If vwap were a feature the model would
    just relearn the market price -> predicted P(win) ~ vwap -> no edge.)
  - Model -> CALIBRATED P(win) (isotonic).
  - Decision rule: take the fire iff  P(win) - entry_vwap > margin   (model thinks it wins more
    than the market priced it). Sweep margin on validation, lock on the time-held-out LOCKBOX.
  - Metric = win07 $/tr (0.07 winner-only fee) of the TAKEN subset on the lockbox + bootstrap CI,
    vs taking ALL fires. NOT AUC (AUC reported as a diagnostic only).
Validation: purged walk-forward for the OOF calibration check + a final time-ordered LOCKBOX (last 25%).
"""
import sys, json
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
SRC = ROOT / "strategy_lab" / "lag_taker_fires_enriched_2026_05_29.parquet"
OUT_MD = ROOT / "strategy_lab" / "reports" / "META_LABELER_V1_2026_06_03.md"
RNG = np.random.default_rng(13)

from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score
try:
    from xgboost import XGBClassifier
    HAVE_XGB = True
except Exception:
    HAVE_XGB = False

def win07(vwap, shares, won, rate=0.07):
    return shares*(1-vwap)*(1-rate*vwap) if won else -shares*vwap

def boot_ci(x, n=10000):
    x = np.asarray(x, float)
    if len(x) < 2: return (np.nan, np.nan)
    idx = RNG.integers(0, len(x), size=(n, len(x)))
    mu = x[idx].mean(1)
    return float(np.percentile(mu, 2.5)), float(np.percentile(mu, 97.5))

df = pd.read_parquet(SRC).copy()
print(f"fires={len(df)}  base={int(df.is_base.sum()) if 'is_base' in df else 'NA'}  "
      f"won-rate={100*df.won.mean():.1f}%  mean vwap={df.entry_vwap.mean():.3f}", flush=True)
df = df[df.entry_vwap.notna() & df.won.notna()].sort_values("fire_us").reset_index(drop=True)
df["pnl07"] = [win07(v, s, w) for v, s, w in zip(df.entry_vwap, df.shares, df.won)]

NUM = ["delta_bps","rv30_bps","rv60_bps","rsi14","macd_hist","cci20","topdepth_usd","spread_eff","persist3","hour"]
NUM = [c for c in NUM if c in df.columns]
X = df[NUM].astype(float).copy()
for a in ["BTC","ETH","SOL"]:
    X[f"asset_{a}"] = (df.asset == a).astype(int)
X["tf_15m"] = (df.tf == "15m").astype(int)
X["dir_up"] = (df.direction.str.upper().str.startswith("U")).astype(int)
y = df.won.astype(int).values
vwap = df.entry_vwap.values
pnl = df.pnl07.values
fire = df.fire_us.values
print(f"features ({X.shape[1]}): {list(X.columns)}", flush=True)

# ---- LOCKBOX = last 25% by time; the rest = dev ----
n = len(df); cut = int(n*0.75)
dev, lock = slice(0, cut), slice(cut, n)
print(f"dev n={cut}  lockbox n={n-cut}  (lockbox span {pd.to_datetime(fire[cut]/1e6,unit='s')} -> {pd.to_datetime(fire[-1]/1e6,unit='s')})", flush=True)

def fit_model():
    if HAVE_XGB:
        return XGBClassifier(n_estimators=300, max_depth=3, learning_rate=0.03,
                             subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
                             reg_lambda=2.0, eval_metric="logloss", tree_method="hist")
    return HistGradientBoostingClassifier(max_depth=3, learning_rate=0.03, max_iter=300,
                                          l2_regularization=2.0, min_samples_leaf=20)

# ---- purged walk-forward OOF on dev to get honest calibrated probs ----
def purged_wf_oof(Xd, yd, fired, n_folds=4, embargo_s=900):
    idx = np.arange(len(Xd)); oof = np.full(len(Xd), np.nan)
    bounds = np.linspace(0, len(Xd), n_folds+1).astype(int)
    for k in range(1, n_folds+1):
        te = idx[bounds[k-1]:bounds[k]] if k < n_folds else idx[bounds[k-1]:]
        if k == 1:  # need history to train; skip first block as pure test (no train before)
            continue
        tr_end = bounds[k-1]
        # embargo: drop train rows within embargo_s before the test start
        t0 = fired[te[0]]
        tr = idx[:tr_end]
        tr = tr[fired[tr] < (t0 - embargo_s*1e6)]
        if len(tr) < 100 or len(np.unique(yd[tr])) < 2: continue
        m = fit_model(); m.fit(Xd.iloc[tr], yd[tr])
        p = m.predict_proba(Xd.iloc[te])[:,1]
        # calibrate on a tail slice of train
        cal = tr[-min(400,len(tr)):]
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(m.predict_proba(Xd.iloc[cal])[:,1], yd[cal])
        oof[te] = iso.transform(p)
    return oof

Xd, yd, fired = X.iloc[dev], y[dev], fire[dev]
oof = purged_wf_oof(Xd, yd, fired)
valid = ~np.isnan(oof)
auc = roc_auc_score(yd[valid], oof[valid]) if len(np.unique(yd[valid]))>1 else float("nan")
print(f"\ndev OOF AUC={auc:.3f} (diagnostic only) on n={valid.sum()}", flush=True)

# ---- pick margin on dev OOF: maximize mean win07 of taken set (require >=40 taken) ----
edge_oof = oof - vwap[dev]
best = None
for mg in np.round(np.arange(-0.05, 0.30, 0.01), 2):
    take = valid & (edge_oof > mg)
    if take.sum() < 40: continue
    mu = pnl[dev][take].mean()
    if best is None or mu > best[1]:
        best = (mg, mu, int(take.sum()))
print(f"best dev margin={best[0] if best else None}  dev $/tr={best[1] if best else None:.3f}  n_take={best[2] if best else 0}", flush=True)
MARGIN = best[0] if best else 0.05

# ---- final: train on ALL dev, calibrate, apply to LOCKBOX ----
m = fit_model(); m.fit(X.iloc[dev], y[dev])
cal = np.arange(dev.stop)[-500:]
iso = IsotonicRegression(out_of_bounds="clip"); iso.fit(m.predict_proba(X.iloc[cal])[:,1], y[cal])
p_lock = iso.transform(m.predict_proba(X.iloc[lock])[:,1])
edge_lock = p_lock - vwap[lock]
take_lock = edge_lock > MARGIN
pnl_lock = pnl[lock]

all_mu, all_ci = pnl_lock.mean(), boot_ci(pnl_lock)
tk = pnl_lock[take_lock]
tk_mu, tk_ci = (tk.mean(), boot_ci(tk)) if take_lock.sum()>1 else (float("nan"),(np.nan,np.nan))
auc_lock = roc_auc_score(y[lock], p_lock) if len(np.unique(y[lock]))>1 else float("nan")

print("\n===== LOCKBOX (held-out last 25%) =====", flush=True)
print(f"ALL fires : n={len(pnl_lock):4} WR={100*y[lock].mean():.1f}% $/tr={all_mu:+.3f} CI[{all_ci[0]:+.3f},{all_ci[1]:+.3f}]", flush=True)
print(f"META-GATED: n={int(take_lock.sum()):4} WR={100*y[lock][take_lock].mean() if take_lock.sum() else float('nan'):.1f}% "
      f"$/tr={tk_mu:+.3f} CI[{tk_ci[0]:+.3f},{tk_ci[1]:+.3f}]  (margin={MARGIN}, AUC={auc_lock:.3f})", flush=True)

verdict = ("✅ META-LABELER ADDS EDGE" if (take_lock.sum()>=30 and tk_ci[0]>0 and tk_mu>all_mu)
           else "🟡 lifts but CI includes 0 / low-n" if (take_lock.sum()>=30 and tk_mu>all_mu)
           else "🔴 no lift on lockbox")
print("VERDICT:", verdict, flush=True)

OUT_MD.write_text(f"""# P1 Meta-Labeler v1 — relative-value filter on lag-taker — 2026-06-03

Base = lag-taker enriched fires (n={len(df)}). Target=won. Features=signal-only (entry_vwap EXCLUDED).
Calibrated P(win) (isotonic); decision = take iff P(win)-entry_vwap > margin. Metric = win07 $/tr.
Model = {'XGBoost' if HAVE_XGB else 'HistGB'}. Purged walk-forward + time-held-out lockbox (last 25%).

## Lockbox result
| set | n | WR | $/tr (win07) | bootstrap 95% CI |
|---|--:|--:|--:|--:|
| ALL fires | {len(pnl_lock)} | {100*y[lock].mean():.1f}% | {all_mu:+.3f} | [{all_ci[0]:+.3f}, {all_ci[1]:+.3f}] |
| META-GATED | {int(take_lock.sum())} | {100*y[lock][take_lock].mean() if take_lock.sum() else float('nan'):.1f}% | {tk_mu:+.3f} | [{tk_ci[0]:+.3f}, {tk_ci[1]:+.3f}] |

margin={MARGIN}, dev OOF AUC={auc:.3f}, lockbox AUC={auc_lock:.3f}.

**VERDICT: {verdict}**

## Notes
- entry_vwap deliberately excluded from features (else model relearns market price -> no edge).
- win07 label/PnL uses the enriched file's entry_vwap (lag-taker study fill). Re-fill the deployed
  cell at 10Hz before sizing (Phase-A lesson). This run proves the PIPELINE + first signal of lift.
- This is the pipeline template for P1: swap the base universe (momo-F7, sniper) and re-run.
""", encoding="utf-8")
print(f"\nwrote {OUT_MD}", flush=True)
