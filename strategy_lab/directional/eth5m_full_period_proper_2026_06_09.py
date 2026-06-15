"""PROPER full-period sleeve comparison (quant-grade).
- BACKTEST: Apr24->May26, v8 universe (real production gate columns), fee07 winner-only
  (verified identical to shadow accounting: 260/260 reconcile).
- SHADOW (true OOS): full window May27->Jun9, per-fire pnl from VPS3 logs.
- Bootstrap 95% CI on $/tr for both; deterioration % with significance.
- DSR via ml4t on shadow daily PnL, n_trials=25 (sleeves in the fleet sweep).

Run: C:/Python314/python.exe strategy_lab/directional/eth5m_full_period_proper_2026_06_09.py
"""
from __future__ import annotations
import os, datetime as dt
import numpy as np, pandas as pd

ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
U = os.path.join(ROOT, r"data\v4\canonical\_results\_sniper_eth5m_v8_universe.parquet")
SHADOW = os.path.join(ROOT, r"migration_2026_06_08\shadow_full.csv")
STAKE, FEE, NTRIALS = 5.0, 0.07, 25

SLEEVES = {
    "v8_grandparent": ["g_tr_above_ema50", "g_hurst_trending", "g_grandparent_trend_with"],
    "v10_grandparent": ["g_tr_above_ema50", "g_hurst_trending", "g_grandparent_trend_with", "g_sms_no_liquidity_above"],
    "v6c3_v7": ["g_tr_above_cloud", "g_ribbon_agrees", "g_mp_skew_with", "g_hurst_trending", "g_parent15m_ranging"],
    "cloud_ribbon_V10": ["g_tr_above_cloud", "g_ribbon_agrees", "g_mp_skew_with", "g_hurst_trending", "g_tr_above_pp"],
    "cloud_ribbon_v6": ["g_tr_above_cloud", "g_ribbon_agrees", "g_mp_skew_with", "g_hurst_trending"],
    "cloud_vwap_v7": ["g_tr_above_cloud", "g_entry_vwap_in_band", "g_hurst_mp_trend_with"],
}

rng = np.random.default_rng(42)


def boot_ci(x, n=4000):
    x = np.asarray(x, float)
    if len(x) < 5:
        return (np.nan, np.nan)
    m = np.array([x[rng.integers(0, len(x), len(x))].mean() for _ in range(n)])
    m.sort()
    return float(m[int(0.025 * n)]), float(m[int(0.975 * n)])


def dsr_daily(fire_us, pnl, n_trials):
    df = pd.DataFrame({"d": (np.asarray(fire_us) // 86_400_000_000), "p": pnl})
    byday = df.groupby("d")["p"].sum().to_numpy()
    if len(byday) < 4 or byday.std() == 0:
        return np.nan
    sr = byday.mean() / byday.std()
    try:
        from ml4t.diagnostic.evaluation.stats.deflated_sharpe_ratio import (
            deflated_sharpe_ratio_from_statistics as f)
        from scipy.stats import skew, kurtosis
        # variance of trial SRs unknown -> estimator variance approx (1+SR^2/2)/n
        var_tr = (1.0 + 0.5 * sr * sr) / len(byday)
        r = f(observed_sharpe=float(sr), n_samples=len(byday), n_trials=n_trials,
              variance_trials=float(var_tr), skewness=float(skew(byday)),
              excess_kurtosis=float(kurtosis(byday, fisher=True)))
        return float(getattr(r, "dsr", getattr(r, "probability", r)))
    except Exception as e:
        return np.nan


# ---------- backtest (full in-sample period) ----------
df = pd.read_parquet(U)
off = "fire_offset_s" if "fire_offset_s" in df.columns else "offset_s"
fcol = "fire_us"
d = df[df[off] == 60].copy()
d = d[d["entry_vwap"].notna() & (d["entry_vwap"] > 0.001) & (d["entry_vwap"] < 0.999)].copy()
d["won"] = d["won"].astype(bool)
d["pnl"] = np.where(d["won"], (STAKE / d["entry_vwap"]) * (1 - d["entry_vwap"]) * (1 - FEE * d["entry_vwap"]), -STAKE)
cols = set(d.columns)

# ---------- shadow (full OOS) ----------
sh = pd.read_csv(SHADOW)
sh_lo = dt.datetime.utcfromtimestamp(sh["fire_us"].min() / 1e6)
sh_hi = dt.datetime.utcfromtimestamp(sh["fire_us"].max() / 1e6)

print(f"BACKTEST window: Apr24 -> May26 (universe, in-sample, fee07)")
print(f"SHADOW window  : {sh_lo:%b%d} -> {sh_hi:%b%d} (true OOS, production engine, fee07 verified)\n")
hdr = ("sleeve", "BT n", "BT WR", "BT $/tr [CI]", "SH n", "SH WR", "SH $/tr [CI]", "deterior", "sig?", "DSR_sh")
print("%-17s %5s %5s %22s %5s %5s %22s %9s %5s %6s" % hdr)

rows = []
for name, gates in SLEEVES.items():
    miss = [g for g in gates if g not in cols]
    bt = None
    if not miss:
        m = np.ones(len(d), bool)
        for g in gates:
            m &= (d[g].fillna(0).astype(int) == 1).to_numpy()
        x = d[m]
        if len(x):
            lo_, hi_ = boot_ci(x["pnl"].to_numpy())
            bt = dict(n=len(x), wr=x["won"].mean(), m=x["pnl"].mean(), lo=lo_, hi=hi_)
    s = sh[sh["tag"] == name]
    shd = None
    if len(s):
        lo_, hi_ = boot_ci(s["pnl"].to_numpy())
        shd = dict(n=len(s), wr=s["won"].mean(), m=s["pnl"].mean(), lo=lo_, hi=hi_,
                   dsr=dsr_daily(s["fire_us"].to_numpy(), s["pnl"].to_numpy(), NTRIALS))
    det = sig = ""
    if bt and shd:
        det = f"{(shd['m']/bt['m']-1)*100:+.0f}%" if bt["m"] > 0 else "n/a"
        # significant deterioration iff shadow CI excludes the backtest mean
        sig = "YES" if (shd["hi"] < bt["m"]) else "no"
    print("%-17s %5s %5s %22s %5s %5s %22s %9s %5s %6s" % (
        name,
        bt["n"] if bt else "-", f"{bt['wr']*100:.0f}%" if bt else "-",
        f"{bt['m']:+.3f} [{bt['lo']:+.2f},{bt['hi']:+.2f}]" if bt else "-",
        shd["n"] if shd else "-", f"{shd['wr']*100:.0f}%" if shd else "-",
        f"{shd['m']:+.3f} [{shd['lo']:+.2f},{shd['hi']:+.2f}]" if shd else "-",
        det, sig,
        f"{shd['dsr']:.2f}" if shd and np.isfinite(shd.get('dsr', np.nan)) else "-"))
    rows.append((name, bt, shd))

print("\nNotes: deterioration normal band = -5%..-30% (project prior). 'sig?'=shadow CI95")
print("upper bound below backtest mean (real deterioration beyond noise). DSR n_trials=25.")
