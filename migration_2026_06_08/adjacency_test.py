"""Adjacency overfit test: in-sample backtest TAIL (universe, May21-26) vs OOS shadow HEAD
(May27-Jun1) for the candidates. Adjacent days => regime ~constant => any gap = overfit.
Backtest part here; shadow part printed for the operator to fetch from VPS3 (separate)."""
import os, numpy as np, pandas as pd, datetime as dt
ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
U = os.path.join(ROOT, r"data\v4\canonical\_results\_sniper_eth5m_v8_universe.parquet")
STAKE, FEE = 5.0, 0.07
SLEEVES = {
    "v8_grandparent": ["g_tr_above_ema50", "g_hurst_trending", "g_grandparent_trend_with"],
    "v6c3_parent15mrang_v7": ["g_tr_above_cloud", "g_ribbon_agrees", "g_mp_skew_with", "g_hurst_trending", "g_parent15m_ranging"],
    "cloud_ribbon_V10": ["g_tr_above_cloud", "g_ribbon_agrees", "g_mp_skew_with", "g_hurst_trending", "g_tr_above_pp"],
    "cloud_ribbon_v6": ["g_tr_above_cloud", "g_ribbon_agrees", "g_mp_skew_with", "g_hurst_trending"],
    "cloud_vwap_v7": ["g_tr_above_cloud", "g_entry_vwap_in_band", "g_hurst_mp_trend_with"],
}
df = pd.read_parquet(U)
off = "fire_offset_s" if "fire_offset_s" in df.columns else "offset_s"
fcol = "fire_us" if "fire_us" in df.columns else "ws_s_us"
d = df[df[off] == 60].copy()
d = d[d["entry_vwap"].notna() & (d["entry_vwap"] > 0.001) & (d["entry_vwap"] < 0.999)].copy()
d["won"] = d["won"].astype(bool)
d["pnl"] = [(STAKE/v)*(1-v)*(1-FEE*v) if w else -STAKE for w, v in zip(d["won"], d["entry_vwap"])]
cols = set(d.columns)
# tail window: last 5 days of the universe (May 21 -> May 26)
hi = int(d[fcol].max()); lo = hi - 5*86_400_000_000
print("backtest TAIL window:", dt.datetime.utcfromtimestamp(lo/1e6).strftime("%m-%d"), "->",
      dt.datetime.utcfromtimestamp(hi/1e6).strftime("%m-%d"))
print("%-22s %5s %5s %8s %8s" % ("sleeve", "n", "WR", "$/tr", "total"))
for name, gates in SLEEVES.items():
    if any(g not in cols for g in gates):
        print(f"{name:22s} missing cols"); continue
    m = np.ones(len(d), bool)
    for g in gates:
        m &= (d[g].fillna(0).astype(int) == 1).to_numpy()
    x = d[m & (d[fcol] >= lo)]
    if len(x) == 0:
        print(f"{name:22s} 0 fires in tail"); continue
    p = x["pnl"].to_numpy()
    print("%-22s %5d %4.0f%% %+8.3f %+8.1f" % (name, len(x), x["won"].mean()*100, p.mean(), p.sum()))
