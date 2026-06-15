"""
WANG-TRANSFORM binary pricing calibration  —  2026-06-11
Idea (Yang 2026 SSRN / oracle3): a binary's market price is the true probability distorted by a risk
premium: p_mkt = g(p_true) with g(u) = Phi(Phi^-1(u) + lam). Fit the distortion on OUR markets and ask:
  (1) what does the calibration curve (trade price vs realized win rate) look like per coin/tf/time-into-window?
  (2) fitted (a,b) of probit model  won ~ Phi(a + b*Phi^-1(p))  -> lam=-a/b at b; b!=1 = slope miscalibration.
  (3) practical: Wang fair value of an entry at ask 'ev' -> does the residual (fair - ev) GATE the corrected
      scalp fires better than the raw <0.55 band?
DATA: production window (Apr 22 -> Jun 11) poly trades x chainlink resolutions = FRESH (not the burned BBO window).
Gate-test fires: _results/scalp_oos_bbo_fires_fixed_2026_06_10*.parquet (Mar30-Apr21, corrected harness) — the
lam used on them comes from the DISJOINT production window.
"""
import sys, glob, math, warnings
from pathlib import Path
import numpy as np, pandas as pd
from scipy.stats import norm
from scipy.optimize import minimize_scalar
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global"); CANON = ROOT / "data/v4/canonical"
sys.path.insert(0, str(CANON))
from load import load_resolutions

OUT = []
def log(s): print(s, flush=True); OUT.append(s)

res = load_resolutions()
res = res[res.outcome.isin(["Up", "Down"])][["slug", "outcome", "timeframe"]].drop_duplicates("slug")
res = res.rename(columns={"outcome": "res_outcome"})
log(f"resolutions: {len(res)}  tfs={res.timeframe.value_counts().to_dict()}")

frames = []
for coin in ["btc", "eth", "sol"]:
    t = pd.read_parquet(CANON / f"trades_polymarket/{coin}.parquet",
                        columns=["timestamp_us", "slug", "outcome", "price", "size"])
    t = t[(t.price > 0.01) & (t.price < 0.99)]
    t["coin"] = coin.upper()
    t = t.merge(res, on="slug", how="inner")
    # time into window from slug suffix
    ss = t.slug.str.rsplit("-", n=1).str[1].astype("int64") * 1_000_000
    tf_s = np.where(t.timeframe == "5m", 300, np.where(t.timeframe == "15m", 900, 0))
    frac = (t.timestamp_us - ss) / 1e6 / np.where(tf_s == 0, np.nan, tf_s)
    t["tfrac"] = frac
    t = t[(t.tfrac >= 0) & (t.tfrac <= 1) & t.timeframe.isin(["5m", "15m"])]
    t["won"] = (t.outcome == t.res_outcome)
    frames.append(t[["coin", "timeframe", "price", "size", "won", "tfrac"]])
    log(f"{coin}: {len(t)} usable trades")
T = pd.concat(frames, ignore_index=True); del frames
log(f"TOTAL trades: {len(T)}")

def probit_fit(df):
    """fit won ~ Phi(a + b*Phi^-1(p)) by MLE on a,b (coarse grid + refine)."""
    z = norm.ppf(df.price.values.clip(0.01, 0.99)); y = df.won.values.astype(float)
    def nll(ab):
        a, b = ab
        q = norm.cdf(a + b * z).clip(1e-6, 1 - 1e-6)
        return -(y * np.log(q) + (1 - y) * np.log(1 - q)).mean()
    from scipy.optimize import minimize
    r = minimize(nll, x0=[0.0, 1.0], method="Nelder-Mead")
    return r.x

log("\n===== CALIBRATION: price bin vs realized WR (pooled, by tf) =====")
bins = np.arange(0.05, 1.0, 0.05)
for tf in ["5m", "15m"]:
    d = T[T.timeframe == tf]
    d = d.assign(bin=pd.cut(d.price, bins))
    g = d.groupby("bin", observed=True).agg(n=("won", "size"), wr=("won", "mean"), p=("price", "mean"))
    g = g[g.n >= 500]
    log(f"\n-- {tf} --   (mispricing = wr - p; >0 means underpriced)")
    for b, r in g.iterrows():
        log(f"  p={r.p:.3f}  wr={r.wr:.3f}  mis={r.wr - r.p:+.3f}  n={int(r.n)}")

log("\n===== PROBIT (a,b) fits: won ~ Phi(a + b*Phi^-1(p)) =====")
log("  b=1,a=0 => perfectly calibrated. lam (Wang) = a at b=1. b<1 => longshots overpriced/favorites underpriced.")
FITS = {}
for key, d in [("ALL", T)] + [(f"{c}", T[T.coin == c]) for c in ["BTC", "ETH", "SOL"]] + \
               [(f"{tf}", T[T.timeframe == tf]) for tf in ["5m", "15m"]] + \
               [("early t<1/3", T[T.tfrac < 1/3]), ("mid", T[(T.tfrac >= 1/3) & (T.tfrac < 2/3)]), ("late t>2/3", T[T.tfrac >= 2/3])]:
    if len(d) < 5000: continue
    a, b = probit_fit(d.sample(min(len(d), 400_000), random_state=0))
    FITS[key] = (a, b)
    log(f"  {key:12s} a={a:+.4f} b={b:.4f}  n={len(d)}")

# fair value function from the EARLY-window fit (the scalp fires at +5s = early)
a_e, b_e = FITS.get("early t<1/3", FITS["ALL"])
def wang_fair(p):  # estimated true P(win) for a token priced p
    return norm.cdf(a_e + b_e * norm.ppf(np.clip(p, 0.01, 0.99)))

log(f"\n===== Wang fair value (early-window fit a={a_e:+.4f} b={b_e:.4f}) for entry asks =====")
for p in [0.30, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70]:
    log(f"  ask={p:.2f} -> fair={wang_fair(p):.3f}  residual={wang_fair(p) - p:+.3f}")

# ---- gate test on the corrected scalp fires (disjoint window) ----
ff = glob.glob(str(ROOT / "strategy_lab/directional/_results/scalp_oos_bbo_fires_fixed_2026_06_10*.parquet"))
if ff:
    F = pd.concat([pd.read_parquet(f) for f in ff], ignore_index=True).drop_duplicates(["coin", "fire_us"])
    F = F[F.ev < 0.55]
    F["resid"] = wang_fair(F.ev.values) - F.ev.values
    def boot(v, nb=4000):
        v = np.asarray(v); v = v[np.isfinite(v)]
        if len(v) < 5: return (np.nan, np.nan)
        i = np.random.randint(0, len(v), (nb, len(v))); return tuple(np.percentile(v[i].mean(1), [2.5, 97.5]))
    def cell(v):
        v = np.asarray(v); v = v[np.isfinite(v)]
        if len(v) < 5: return f"n={len(v):4d}(few)"
        t = v.mean() / v.std(ddof=1) * np.sqrt(len(v)) if v.std() > 0 else np.nan
        lo, hi = boot(v); return f"n={len(v):4d} $/tr={v.mean():+.3f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}]"
    log(f"\n===== GATE TEST on corrected scalp fires (gated <0.55, n={len(F)}) — Wang residual terciles =====")
    q = F.resid.quantile([1/3, 2/3]).values
    for lab, sel in [("LOW resid", F.resid <= q[0]), ("MID", (F.resid > q[0]) & (F.resid <= q[1])), ("HIGH resid", F.resid > q[1])]:
        log(f"  {lab:10s} {cell(F[sel].pnl60.values)}")
    log("  (HIGH residual = Wang says most underpriced. If HIGH >> LOW with CI>0 on both, the lens adds signal.)")
else:
    log("no corrected fires parquet found — skip gate test")

(ROOT / "strategy_lab/directional/_results/wang_transform_2026_06_11.txt").write_text("\n".join(OUT), encoding="utf-8")
print("\nsaved results txt")
