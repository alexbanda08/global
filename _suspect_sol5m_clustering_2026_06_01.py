import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd, numpy as np

V7 = "strategy_lab/sniper_search_2026_05_27/sol_5m_v7/_panel_sol_5m_v7.parquet"
V8 = "strategy_lab/sniper_search_2026_05_27/sol_5m_v8/_panel_sol_5m_v8.parquet"

p7 = pd.read_parquet(V7)
p8 = pd.read_parquet(V8)
print("V7 panel:", p7.shape, " V8 panel:", p8.shape)

g7 = ["g_btc_trend_30m_with","g_cci_extreme_with","g_hurst_reverting"]
g8 = ["g_btc_f7_against","g_cci_extreme_with","g_hurst_reverting","g_mfi_strong_with"]
print("V7 gates present:", [c for c in g7 if c in p7.columns], "missing:", [c for c in g7 if c not in p7.columns])
print("V8 gates present:", [c for c in g8 if c in p8.columns], "missing:", [c for c in g8 if c not in p8.columns])

def fires(p, gates):
    m = np.ones(len(p), dtype=bool)
    for g in gates:
        m &= (p[g].astype(int).values == 1)
    f = p[m].copy()
    f["day"] = pd.to_datetime(f["fire_us"], unit="us").dt.strftime("%Y-%m-%d")
    return f

print("\ncols of interest:", [c for c in p7.columns if c in ("fire_us","slot_start_us","fire_offset_s","direction","won","outcome")])

for name, p, gates in [("V7_S1", p7, g7), ("V8_S1", p8, g8)]:
    f = fires(p, gates)
    print(f"\n===== {name}: {gates} =====")
    print(f"total fires (full window): {len(f)}")
    if len(f)==0:
        continue
    print(f"date range: {pd.to_datetime(f.fire_us.min(),unit='us')} -> {pd.to_datetime(f.fire_us.max(),unit='us')}")
    daily = f.groupby("day").size().sort_index()
    full_days = pd.date_range(daily.index.min(), daily.index.max(), freq="D").strftime("%Y-%m-%d")
    daily = daily.reindex(full_days, fill_value=0)
    print("daily fire histogram:")
    for d,c in daily.items():
        print(f"  {d}: {int(c):3d} {'#'*int(c)}")
    n_days=len(daily); n_fires=int(daily.sum()); n_zero=int((daily==0).sum())
    cv = daily.std()/daily.mean() if daily.mean()>0 else float('nan')
    top3 = int(daily.sort_values(ascending=False).head(3).sum())
    print(f"\n  days={n_days} zero-days={n_zero} mean/day={n_fires/n_days:.2f} max/day={int(daily.max())}")
    print(f"  CV(std/mean)={cv:.2f}  poisson-expected-CV~{1/np.sqrt(n_fires/n_days):.2f}")
    print(f"  top-3-days = {top3}/{n_fires} = {100*top3/n_fires:.0f}% of all fires")
    ft = np.sort(f.fire_us.values); gaps_h = np.diff(ft)/1e6/3600
    if len(gaps_h):
        print(f"  inter-fire gaps(h): median={np.median(gaps_h):.2f} mean={gaps_h.mean():.2f} max={gaps_h.max():.2f}")
    if "fire_offset_s" in f.columns:
        print("  offset dist:", dict(f.fire_offset_s.value_counts().sort_index()))
    # how many fires would land in a recent comparable window length (last 2.625 days of bt)
    cut = ft.max() - int(2.625*86400*1e6)
    print(f"  fires in last 2.625d of backtest window: {(ft>=cut).sum()}")
