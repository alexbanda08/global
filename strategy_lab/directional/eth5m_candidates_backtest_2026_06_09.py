"""In-sample backtest (Apr24->May26, v8 universe, precomputed real gates, 0.07 fee) of the
candidate ETH-5m sleeves + the grandparent v8 anchor (which has live fires). Compare
backtest vs shadow(forward) vs live to answer 'does the backtest match'."""
import os, numpy as np, pandas as pd
ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
U = os.path.join(ROOT, r"data\v4\canonical\_results\_sniper_eth5m_v8_universe.parquet")
STAKE, FEE = 5.0, 0.07

SLEEVES = {
    "v8_grandparent(LIVE)": ["g_tr_above_ema50", "g_hurst_trending", "g_grandparent_trend_with"],
    "v6c3_parent15mrang_v7": ["g_tr_above_cloud", "g_ribbon_agrees", "g_mp_skew_with", "g_hurst_trending", "g_parent15m_ranging"],
    "cloud_ribbon_V10":      ["g_tr_above_cloud", "g_ribbon_agrees", "g_mp_skew_with", "g_hurst_trending", "g_tr_above_pp"],
    "cloud_ribbon_v6":       ["g_tr_above_cloud", "g_ribbon_agrees", "g_mp_skew_with", "g_hurst_trending"],
    "cloud_vwap_v7":         ["g_tr_above_cloud", "g_entry_vwap_in_band", "g_hurst_mp_trend_with"],
}

df = pd.read_parquet(U)
off = "fire_offset_s" if "fire_offset_s" in df.columns else "offset_s"
d = df[df[off] == 60].copy()
fcol = "fire_us" if "fire_us" in d.columns else "ws_s_us"
d = d[d["entry_vwap"].notna() & (d["entry_vwap"] > 0.001) & (d["entry_vwap"] < 0.999)].copy()
d["won"] = d["won"].astype(bool)
d["pnl"] = [ (STAKE/v)*(1-v)*(1-FEE*v) if w else -STAKE for w, v in zip(d["won"], d["entry_vwap"]) ]

cols = set(d.columns)
def metrics(x):
    if len(x)==0: return None
    s=x.sort_values(fcol); p=s["pnl"].to_numpy()
    cum=np.cumsum(p); mdd=float((cum-np.maximum.accumulate(cum)).min())
    return len(s), float(s["won"].mean()), float(p.mean()), float(p.sum()), mdd, (p.sum()/abs(mdd) if mdd<0 else float("inf"))

print("=== IN-SAMPLE BACKTEST (Apr24->May26, v8 universe, real gate cols, 0.07 fee, $5) ===")
print("%-24s %5s %5s %7s %8s %7s %6s  gates" % ("sleeve","n","WR","$/tr","total","MaxDD","Calmr"))
for name, gates in SLEEVES.items():
    miss=[g for g in gates if g not in cols]
    if miss:
        print(f"{name:24s}  MISSING COLS: {miss}"); continue
    mask=np.ones(len(d), bool)
    for g in gates:
        mask &= (d[g].fillna(0).astype(int)==1).to_numpy()
    m=metrics(d[mask])
    if m: print("%-24s %5d %4.0f%% %+7.3f %+8.1f %7.1f %6.2f  %s" % (name,m[0],m[1]*100,m[2],m[3],m[4],m[5]," + ".join(g.replace('g_','') for g in gates)))
