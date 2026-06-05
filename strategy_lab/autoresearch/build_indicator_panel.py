"""
Build full TA-indicator panel per asset on 1m Binance klines (causal). Writes
strategy_lab/autoresearch/_data/indicators_{asset}.parquet with ts_s + every indicator.
Sampled asof ws_s later. Uses TA-Lib + custom (SuperTrend, Keltner, CMF, EMV).
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
import talib
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT/"data"/"v4"/"canonical"))
from load import load_klines  # noqa
OUTD = ROOT/"strategy_lab"/"autoresearch"/"_data"; OUTD.mkdir(parents=True, exist_ok=True)

def supertrend(h,l,c,period=10,mult=3.0):
    atr=talib.ATR(h,l,c,period); hl2=(h+l)/2
    ub=hl2+mult*atr; lb=hl2-mult*atr
    st=np.full(len(c),np.nan); dir_=np.ones(len(c))
    fub=ub.copy(); flb=lb.copy()
    for i in range(1,len(c)):
        if np.isnan(atr[i]): continue
        fub[i]=ub[i] if (ub[i]<fub[i-1] or c[i-1]>fub[i-1]) else fub[i-1]
        flb[i]=lb[i] if (lb[i]>flb[i-1] or c[i-1]<flb[i-1]) else flb[i-1]
        if c[i]>fub[i-1]: dir_[i]=1
        elif c[i]<flb[i-1]: dir_[i]=-1
        else: dir_[i]=dir_[i-1]
        st[i]=flb[i] if dir_[i]==1 else fub[i]
    return st,dir_

def cmf(h,l,c,v,n=20):
    rng=(h-l); rng[rng==0]=np.nan
    mfv=(((c-l)-(h-c))/rng)*v
    s_mfv=pd.Series(mfv).rolling(n).sum().values
    s_v=pd.Series(v).rolling(n).sum().values
    return s_mfv/np.where(s_v==0,np.nan,s_v)

def emv(h,l,v,n=14):
    hl2=(h+l)/2; dist=np.concatenate([[np.nan],np.diff(hl2)])
    rng=(h-l)
    box=(v/1e8)/np.where(rng==0,np.nan,rng)
    e=dist/np.where(box==0,np.nan,box)
    return pd.Series(e).rolling(n).mean().values

for asset in ["BTC","ETH","SOL"]:
    k=load_klines(asset, source="binance-spot-ws", period_id="1MIN").sort_values("ts_s").reset_index(drop=True)
    o=k.price_open.to_numpy(float); h=k.price_high.to_numpy(float); l=k.price_low.to_numpy(float)
    c=k.price_close.to_numpy(float); v=k.volume_traded.to_numpy(float); ts=k.ts_s.to_numpy()
    d=pd.DataFrame({"ts_s":ts})
    # momentum / trend
    d["rsi14"]=talib.RSI(c,14); d["rsi7"]=talib.RSI(c,7)
    d["adx14"]=talib.ADX(h,l,c,14); d["plus_di"]=talib.PLUS_DI(h,l,c,14); d["minus_di"]=talib.MINUS_DI(h,l,c,14)
    d["cci20"]=talib.CCI(h,l,c,20); d["willr14"]=talib.WILLR(h,l,c,14)
    k_,dst=talib.STOCH(h,l,c,fastk_period=14,slowk_period=3,slowd_period=3); d["stoch_k"]=k_; d["stoch_d"]=dst
    macd,macds,macdh=talib.MACD(c,12,26,9); d["macd_hist"]=macdh; d["macd"]=macd
    d["mom10"]=talib.MOM(c,10); d["roc10"]=talib.ROC(c,10)
    d["sar"]=talib.SAR(h,l); d["sar_dist"]=(c-d["sar"])/c
    st,stdir=supertrend(h,l,c); d["supertrend_dir"]=stdir; d["supertrend_dist"]=(c-st)/c
    # vol / range
    d["atr14"]=talib.ATR(h,l,c,14); d["natr14"]=talib.NATR(h,l,c,14)
    d["stddev20"]=talib.STDDEV(c,20,1); d["realvol60"]=pd.Series(np.log(c)).diff().rolling(60).std().values*np.sqrt(60)
    ub,mb,lb=talib.BBANDS(c,20,2,2); d["bb_pctb"]=(c-lb)/np.where((ub-lb)==0,np.nan,(ub-lb)); d["bb_bw"]=(ub-lb)/mb
    ema20=talib.EMA(c,20); katr=talib.ATR(h,l,c,20)
    d["keltner_pos"]=(c-ema20)/np.where(katr==0,np.nan,2*katr)
    # volume
    d["obv"]=talib.OBV(c,v); d["obv_slope"]=pd.Series(d["obv"]).diff(10).values
    d["cmf20"]=cmf(h,l,c,v,20); d["emv14"]=emv(h,l,v,14)
    d["vol_z"]=(v-pd.Series(v).rolling(60).mean().values)/ (pd.Series(v).rolling(60).std().values+1e-9)
    # ema stack
    for p in [9,21,50,200]:
        e=talib.EMA(c,p); d[f"px_vs_ema{p}"]=(c-e)/e
    # returns
    for m in [1,5,15,60]:
        d[f"ret{m}m"]=pd.Series(np.log(c)).diff(m).values
    d.to_parquet(OUTD/f"indicators_{asset.lower()}.parquet", index=False)
    print(f"{asset}: {len(d)} bars, {d.shape[1]-1} indicators -> indicators_{asset.lower()}.parquet", flush=True)
print("done", flush=True)
