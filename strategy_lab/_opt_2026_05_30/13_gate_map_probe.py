import pandas as pd, os, numpy as np, pyarrow.parquet as pq
RES=r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical\_results"
def gcols(p):
    return [c for c in [f.name for f in pq.ParquetFile(p).schema_arrow] if c.startswith("g_")]
for f in ["_sniper_btc_5m_enriched","_sniper_eth5m_v6_universe","_sniper_eth5m_v7_universe","_sniper_eth5m_v8_universe","sniper_btc15m_master"]:
    p=os.path.join(RES,f+".parquet")
    if os.path.exists(p): print(f"\n@@{f} g_cols:", gcols(p))
    else: print(f"\n@@{f}: MISSING")

# structure + fidelity probe on eth_cloud_ribbon_mp_hurst_v6: g_tr_above_cloud & g_ribbon_agrees & g_mp_skew_with & g_hurst_trending, offset 60
p=os.path.join(RES,"_sniper_eth5m_v6_universe.parquet")
df=pd.read_parquet(p)
print("\n@@eth5m_v6 cols sample:", [c for c in df.columns if c in ('direction','fire_offset_s','outcome','won','entry_vwap','pnl_legacy_usd','up_vwap','dn_vwap','up_shares','dn_shares','fire_us')])
print("direction vals:", df['direction'].value_counts().to_dict() if 'direction' in df else 'NA')
print("offset vals:", df['fire_offset_s'].value_counts().head(12).to_dict())
gset=['g_tr_above_cloud','g_ribbon_agrees','g_mp_skew_with','g_hurst_trending']
have=[g for g in gset if g in df.columns]; print("gates present:", have)
m=np.ones(len(df),bool)
for g in have: m &= df[g].fillna(False).astype(bool)
m &= (df['fire_offset_s']==60)
fires=df[m]
print(f"FULL-PERIOD fires: n={len(fires)} WR={100*fires['won'].mean():.1f}% sum_pnl_legacy={fires['pnl_legacy_usd'].sum():.1f}")
fires=fires.assign(d=pd.to_datetime(fires['fire_us'],unit='us'))
liveov=fires[fires.d>=pd.Timestamp('2026-05-24')]
print(f"  live-overlap (>=May24): n={len(liveov)} WR={100*liveov['won'].mean():.1f}%  (live actual was ~72.6% n84)")
print("  weekly WR/n:")
fires['wk']=fires.d.dt.isocalendar().week
print(fires.groupby('wk').agg(n=('won','size'),wr=('won',lambda x:round(100*x.mean(),1)),pnl=('pnl_legacy_usd','sum')).round(1).to_string())
