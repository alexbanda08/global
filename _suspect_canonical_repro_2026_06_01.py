"""Reproduce the 2 SUSPECT SOL-5m gate conjunctions on CANONICAL data, in the LIVE window
(May 29 00:00 -> May 31 14:15 UTC), at LIVE thresholds:
  V7_S1: g_btc_trend_30m_with & g_cci_extreme_with(|CCI|>150) & g_hurst_reverting(<0.40)
  V8_S1: g_btc_f7_against & g_cci_extreme_with(|CCI|>150) & g_hurst_reverting & g_mfi_strong_with
CCI computed LIVE-EXACT: 60-bar 1s lookback, typical-price dedup (skip flat 1s bars), |CCI|>150.
"""
import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, "data/v4/canonical")
import pandas as pd, numpy as np
from load import load_klines_1s, load_klines, load_resolutions

LIVE_START = int(pd.Timestamp("2026-05-29 00:00:00").value // 1000)  # us
LIVE_END   = int(pd.Timestamp("2026-05-31 14:15:00").value // 1000)
WINDOW_S = 300
OFFSETS = [30,60,90,120,150,180,210,240,270]
CCI_EXTREME_THR = 150.0; HURST_REV_THR = 0.40
MFI_UP=60.0; MFI_DN=40.0; F7_OB=70.0; F7_OS=30.0; BTC30_THR=0.0015

# ---- SOL 5m fire universe in live window (from resolutions slots) ----
r = load_resolutions(['SOL'])
r = r[(r['timeframe'].astype(str).str.contains('5m|300|5MIN', case=False, na=False)) |
      (r['slot_end_us']-r['slot_start_us']).between(280_000_000,320_000_000)]
r = r[(r['slot_start_us']>=LIVE_START)&(r['slot_start_us']<=LIVE_END)].copy()
print(f"SOL 5m slots in live window: {len(r)}")
slots = np.sort(r['slot_start_us'].unique())
print(f"unique slots: {len(slots)}  span {pd.to_datetime(slots.min(),unit='us')} -> {pd.to_datetime(slots.max(),unit='us')}")

# Build fire grid: each slot x each offset x {UP,DOWN}. ws_s = slot_start - 300. fire_us = (ws_s+offset)*1e6
rows=[]
for ss_us in slots:
    ws_s = ss_us//1_000_000 - WINDOW_S
    for off in OFFSETS:
        fire_us = (ws_s + off)*1_000_000
        for d in ('UP','DOWN'):
            rows.append((ss_us, ws_s, off, fire_us, d))
g = pd.DataFrame(rows, columns=['slot_start_us','ws_s','offset','fire_us','direction'])
print(f"total fire-evals (slot x offset x dir): {len(g)}")

# ---- LIVE-EXACT 1s CCI for SOL ----
k1 = load_klines_1s('SOL')[['time_period_start_us','price_high','price_low','price_close']].dropna()
k1 = k1.sort_values('time_period_start_us').drop_duplicates('time_period_start_us').reset_index(drop=True)
k1 = k1[(k1['time_period_start_us']>=LIVE_START-200_000_000)&(k1['time_period_start_us']<=LIVE_END)]
h=k1['price_high'].to_numpy(float); l=k1['price_low'].to_numpy(float); c=k1['price_close'].to_numpy(float)
tp=(h+l+c)/3.0; ts=k1['time_period_start_us'].to_numpy()
# live: skip flat bars (tp==prev_tp). Build deduped tp stream + its ts.
keep=np.ones(len(tp),bool); prev=None
for i in range(len(tp)):
    if prev is not None and tp[i]==prev: keep[i]=False
    else: prev=tp[i]
tpd=tp[keep]; tsd=ts[keep]
# rolling 60-bar CCI on deduped tp
LB=60; cci=np.full(len(tpd),np.nan)
for i in range(LB-1,len(tpd)):
    w=tpd[i-LB+1:i+1]; sma=w.mean(); md=np.abs(w-sma).mean()
    cci[i]= (tpd[i]-sma)/(0.015*md) if md!=0 else np.nan
print(f"SOL 1s bars={len(tp)} deduped(non-flat)={len(tpd)} cci_valid={np.isfinite(cci).sum()}")

def asof(ts_arr,val_arr,q):  # largest ts <= q
    idx=np.searchsorted(ts_arr,q,side='right')-1; out=np.full(len(q),np.nan)
    v=idx>=0; out[v]=val_arr[idx[v]]; return out
# live lookup epsilon: ts_us <= fire_us - 1_000_000
g['cci_60s']=asof(tsd, cci, g['fire_us'].values-1_000_000)

# ---- BTC 30m trend at ws_s (1m klines, matches backtest g_btc_trend_30m_with) ----
def closes_1m(a):
    kk=load_klines(a,source='binance-spot-ws',period_id='1MIN')[['time_period_start_us','price_close']].dropna()
    kk=kk.sort_values('time_period_start_us').drop_duplicates('time_period_start_us')
    return (kk['time_period_start_us'].to_numpy()//1_000_000).astype('int64'), kk['price_close'].to_numpy(float)
bts,bcl=closes_1m('BTC')
ws=g['ws_s'].values
cur=asof(bts,bcl,ws); prev30=asof(bts,bcl,ws-1800)
g['btc_ret_30m']=(cur-prev30)/prev30

# ---- BTC F7 RSI(7) simple-mean Wilder at ws_s ----
def f7(a):
    t,c=closes_1m(a); rsi=np.full(len(c),np.nan); P=7; d=np.diff(c)
    for i in range(P,len(c)):
        gg=d[i-P:i]; up=np.where(gg>0,gg,0).mean(); dn=np.where(gg<0,-gg,0).mean()
        rsi[i]=100.0 if dn==0 else 100-100/(1+up/dn)
    return t,rsi
bt,brsi=f7('BTC'); g['btc_f7']=asof(bt,brsi,ws)

# ---- SOL hurst_300s at fire (from canonical vol_hurst panel) ----
vh=pd.read_parquet("data/v4/canonical/_results/vol_hurst_at_fire_5m.parquet")
vh=vh[vh['asset']=='SOL'][['fire_us','fire_offset_s','hurst_300s']].drop_duplicates(['fire_us','fire_offset_s'])
print("vol_hurst max fire_us:", pd.to_datetime(vh['fire_us'].max(),unit='us'))
g=g.merge(vh.rename(columns={'fire_offset_s':'offset'}), on=['fire_us','offset'], how='left')

# ---- SOL MFI_60s live-exact (1s, 60-bar) ----
vol=load_klines_1s('SOL')[['time_period_start_us','price_high','price_low','price_close','volume_traded']].dropna()
vol=vol.sort_values('time_period_start_us').drop_duplicates('time_period_start_us')
vol=vol[(vol['time_period_start_us']>=LIVE_START-200_000_000)&(vol['time_period_start_us']<=LIVE_END)].reset_index(drop=True)
hh=vol['price_high'].to_numpy(float);ll=vol['price_low'].to_numpy(float);cc2=vol['price_close'].to_numpy(float)
vv=vol['volume_traded'].to_numpy(float); tp2=(hh+ll+cc2)/3.0; rf=tp2*vv; ts2=vol['time_period_start_us'].to_numpy()
mfi=np.full(len(tp2),np.nan)
for i in range(LB,len(tp2)):
    pos=neg=0.0
    for j in range(i-LB+1,i+1):
        if tp2[j]>tp2[j-1]: pos+=rf[j]
        elif tp2[j]<tp2[j-1]: neg+=rf[j]
    mfi[i]= (100.0 if neg==0 else 100-100/(1+pos/neg)) if (pos+neg)>0 else np.nan
g['mfi_60s']=asof(ts2,mfi,g['fire_us'].values-1_000_000)

# ---- evaluate gates at LIVE thresholds ----
up=g.direction=='UP'; dn=g.direction=='DOWN'
g['g_cci_extreme']=np.where(g.cci_60s.notna(),
    ((g.cci_60s>CCI_EXTREME_THR)&up)|((g.cci_60s<-CCI_EXTREME_THR)&dn), False)
g['g_hurst_rev']=(g.hurst_300s<HURST_REV_THR).fillna(False)
g['g_btc_trend_30m']=(((g.btc_ret_30m>BTC30_THR)&up)|((g.btc_ret_30m<-BTC30_THR)&dn)).fillna(False)
g['g_btc_f7_against']=(((g.btc_f7>F7_OB)&dn)|((g.btc_f7<F7_OS)&up)).fillna(False)
g['g_mfi_strong']=(((g.mfi_60s>MFI_UP)&up)|((g.mfi_60s<MFI_DN)&dn)).fillna(False)

print("\n--- per-gate live-window canonical pass rates (of",len(g),"evals) ---")
for c in ['g_cci_extreme','g_hurst_rev','g_btc_trend_30m','g_btc_f7_against','g_mfi_strong']:
    print(f"  {c}: {g[c].sum()} ({100*g[c].mean():.2f}%)")
print(f"  cci_60s notna: {g.cci_60s.notna().mean()*100:.1f}%   hurst notna: {g.hurst_300s.notna().mean()*100:.1f}%   mfi notna: {g.mfi_60s.notna().mean()*100:.1f}%")

v7 = g['g_btc_trend_30m'] & g['g_cci_extreme'] & g['g_hurst_rev']
v8 = g['g_btc_f7_against'] & g['g_cci_extreme'] & g['g_hurst_rev'] & g['g_mfi_strong']
print(f"\n==== CANONICAL CONJUNCTION FIRES (live window {pd.to_datetime(LIVE_START,unit='us').date()} -> {pd.to_datetime(LIVE_END,unit='us').date()}, ~2.6d) ====")
print(f"  V7_S1 (btc_trend_30m & cci>150 & hurst<0.40):          {int(v7.sum())}")
print(f"  V8_S1 (btc_f7_against & cci>150 & hurst<0.40 & mfi):   {int(v8.sum())}")
# also at backtest cci>100 for comparison
g['g_cci100']=np.where(g.cci_60s.notna(),((g.cci_60s>100)&up)|((g.cci_60s<-100)&dn),False)
v7b=g['g_btc_trend_30m']&g['g_cci100']&g['g_hurst_rev']
v8b=g['g_btc_f7_against']&g['g_cci100']&g['g_hurst_rev']&g['g_mfi_strong']
print(f"  [at backtest cci>100]: V7={int(v7b.sum())}  V8={int(v8b.sum())}")
