"""
CHAINED: (Phase A) GPU-train a calibrated next-window DIRECTION model + REGIME on 8.8y Binance klines,
trained ONLY on data BEFORE the poly window -> (Phase B) auto-apply to Polymarket up/down as:
  (1) RELATIVE-VALUE / mispricing: bet when model P(up) deviates from the poly price (up_vwap) by > margin
  (2) REGIME GATE: stratify poly outcomes/PnL by uptrend/downtrend/chop regime
Judged on the REAL poly outcome + win07 fee, lockbox split. Genuine OOS (kline model never saw the poly weeks).

Usage: python gpu_kline_to_poly.py [epochs]
Writes KLINE_TO_POLY_2026_06_03.md.
"""
import sys, time, json
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import torch, torch.nn as nn, talib
ROOT=Path(r"C:\Users\alexandre bandarra\Desktop\global")
KD=ROOT/"strategy_lab"/"autoresearch"/"_data"/"binance_vision"
POLY=ROOT/"strategy_lab"/"cross_feature_2026_05_26"/"master.parquet"
OUT=ROOT/"strategy_lab"/"reports"/"KLINE_TO_POLY_2026_06_03.md"
DEV="cuda" if torch.cuda.is_available() else "cpu"
SEQ=48; EPOCHS=int(sys.argv[1]) if len(sys.argv)>1 else 12
TRAIN_CUTOFF=pd.Timestamp("2026-03-15")   # kline model trains only before this; poly weeks are after = OOS
RNG=np.random.default_rng(0)

def feats_and_regime(c,h,l,v):
    lr=np.r_[0,np.diff(np.log(c))]
    rsi=np.nan_to_num(talib.RSI(c,14)/100.0)
    atr=np.nan_to_num(talib.ATR(h,l,c,14)/c)
    roc=np.nan_to_num(talib.ROC(c,10)/100.0)
    e50,e200=talib.EMA(c,50),talib.EMA(c,200)
    espread=np.nan_to_num((e50-e200)/c)
    rv=pd.Series(lr).rolling(50).std().bfill().values
    F=np.column_stack([lr,rsi,atr,roc,espread,np.nan_to_num(np.tanh(rv*50))]).astype(np.float32)
    # regime: trend = sign(ema50-ema200); vol tercile
    trend=np.where(np.nan_to_num(e50-e200)>0,1,-1)
    vt=pd.Series(rv); q1,q2=vt.quantile([0.33,0.66])
    volb=np.where(rv<=q1,0,np.where(rv<=q2,1,2))
    return F,trend,volb

class Net(nn.Module):
    def __init__(s,nf,hid=48):
        super().__init__(); s.l=nn.LSTM(nf,hid,2,batch_first=True,dropout=0.2); s.h=nn.Sequential(nn.Linear(hid,24),nn.ReLU(),nn.Dropout(0.2),nn.Linear(24,1))
    def forward(s,x): o,_=s.l(x); return s.h(o[:,-1,:]).squeeze(-1)

def iso_fit(p,y):
    from sklearn.isotonic import IsotonicRegression
    m=IsotonicRegression(out_of_bounds="clip"); m.fit(p,y); return m

def train_predict(asset,tf):
    f=KD/f"{asset}USDT_{tf}_full.parquet"
    if not f.exists(): return None
    d=pd.read_parquet(f); d["ts"]=pd.to_datetime(d.open_time,unit="ms"); d=d.sort_values("ts").drop_duplicates("ts")
    c=d.close.values.astype(float); h=d.high.values.astype(float); l=d.low.values.astype(float); v=d.volume.values.astype(float); ts=d.ts.values
    F,trend,volb=feats_and_regime(c,h,l,v)
    lr=np.r_[0,np.diff(np.log(c))]; y=(np.r_[lr[1:],0]>0).astype(np.float32)  # next-bar up
    # sequences
    Xs=[];ys=[];ix=[]
    for i in range(SEQ,len(c)-1): Xs.append(F[i-SEQ:i]);ys.append(y[i]);ix.append(i)
    X=np.asarray(Xs,dtype=np.float32);Y=np.asarray(ys);ix=np.asarray(ix)
    tcut=pd.Timestamp(TRAIN_CUTOFF).value
    is_train=ts[ix]<np.datetime64(TRAIN_CUTOFF)
    tr=np.where(is_train)[0]; ap=np.where(~is_train)[0]
    if len(tr)<5000 or len(ap)<50: return None
    mu=X[tr].reshape(-1,X.shape[2]).mean(0); sd=X[tr].reshape(-1,X.shape[2]).std(0)+1e-6
    Xn=(X-mu)/sd
    vcut=int(len(tr)*0.9); trn,val=tr[:vcut],tr[vcut:]
    tX=torch.tensor(Xn).to(DEV); tY=torch.tensor(Y).to(DEV)
    net=Net(X.shape[2]).to(DEV); opt=torch.optim.Adam(net.parameters(),1e-3,weight_decay=1e-5); lf=nn.BCEWithLogitsLoss()
    best=1e9;bs=None;pat=0
    for ep in range(EPOCHS):
        net.train(); perm=torch.tensor(RNG.permutation(trn)).to(DEV)
        for b in range(0,len(trn),1024):
            bi=perm[b:b+1024]; opt.zero_grad(); loss=lf(net(tX[bi]),tY[bi]); loss.backward(); opt.step()
        net.eval()
        with torch.no_grad(): vl=lf(net(tX[torch.tensor(val).to(DEV)]),tY[torch.tensor(val).to(DEV)]).item()
        if vl<best-1e-4: best=vl;pat=0;bs={k:vv.clone() for k,vv in net.state_dict().items()}
        else: pat+=1
        if pat>=3: break
    net.load_state_dict(bs); net.eval()
    with torch.no_grad():
        praw_val=torch.sigmoid(net(tX[torch.tensor(val).to(DEV)])).cpu().numpy()
        praw_ap=torch.sigmoid(net(tX[torch.tensor(ap).to(DEV)])).cpu().numpy()
    iso=iso_fit(praw_val,Y[val]); p_ap=iso.transform(praw_ap)
    acc=float(((p_ap>0.5)==(Y[ap]>0.5)).mean())
    # P(up) + regime series over application bars, keyed by bar close ts (seconds)
    bar_ts=ts[ix[ap]].astype("datetime64[s]").astype(np.int64)
    return dict(asset=asset,tf=tf,acc=round(acc,3),n_ap=len(ap),
                ts=bar_ts, pup=p_ap, trend=trend[ix[ap]], volb=volb[ix[ap]])

def win07(p,won): return (1-p)*(1-0.07*p) if won else -p  # per-$1; sign by side handled by caller

def main():
    print(f"Phase A: GPU train ({DEV}) per asset x tf, train<{TRAIN_CUTOFF.date()} -> predict poly weeks (OOS)",flush=True)
    models={}; t0=time.time()
    for asset in ["BTC","ETH","SOL"]:
        for tf in ["5m","15m"]:
            r=train_predict(asset,tf)
            if r: models[(asset,tf)]=r; print(f"  [{asset} {tf}] OOS-bar acc={r['acc']} n={r['n_ap']} ({time.time()-t0:.0f}s)",flush=True)
    # Phase B: apply to poly
    print("Phase B: apply to Polymarket (relative-value vs up_vwap + regime gate)",flush=True)
    m=pd.read_parquet(POLY)
    m=m.drop_duplicates("slug")  # one row per slug
    m["mP_up"]=np.nan; m["regime_trend"]=0; m["regime_vol"]=-1
    for (asset,tf),r in models.items():
        sel=(m.asset==asset)&(m.tf==tf)
        if not sel.any(): continue
        wss=(m.loc[sel,"ws_s"].values).astype(np.int64)
        pos=np.searchsorted(r["ts"], wss, side="right")-1
        ok=pos>=0
        idx=m.index[sel]
        for j,(p,o) in enumerate(zip(pos,ok)):
            if o:
                m.loc[idx[j],"mP_up"]=r["pup"][p]; m.loc[idx[j],"regime_trend"]=r["trend"][p]; m.loc[idx[j],"regime_vol"]=r["volb"][p]
    d=m[m.mP_up.notna() & m.up_vwap.notna() & m.dn_vwap.notna()].copy()
    d["up_win"]=(d.outcome=="Up").astype(int)
    d=d.sort_values("fire_us").reset_index(drop=True)
    n=len(d); cut=int(n*0.75); lock=slice(cut,n)
    print(f"  poly slots with model P(up): {n} (lockbox {n-cut})",flush=True)
    # RELATIVE VALUE: bet UP if mP_up - up_vwap > margin ; bet DOWN if (1-mP_up) - dn_vwap > margin
    def rv_pnl(dd,margin):
        pnls=[];sides=[]
        for r in dd.itertuples():
            eu=r.mP_up - r.up_vwap; ed=(1-r.mP_up) - r.dn_vwap
            if eu>margin and eu>=ed: pnls.append((1-r.up_vwap)*(1-0.07*r.up_vwap) if r.up_win else -r.up_vwap); sides.append(1)
            elif ed>margin: pnls.append((1-r.dn_vwap)*(1-0.07*r.dn_vwap) if (1-r.up_win) else -r.dn_vwap); sides.append(-1)
        return np.array(pnls)*25.0  # $25 notional
    def boot(x,nb=6000):
        x=np.asarray(x,float);x=x[np.isfinite(x)]
        if len(x)<5: return (np.nan,np.nan)
        b=x[RNG.integers(0,len(x),(nb,len(x)))].mean(1);return float(np.percentile(b,2.5)),float(np.percentile(b,97.5))
    # choose margin on dev (first 75%), eval lockbox
    dev=d.iloc[:cut]; lk=d.iloc[cut:]
    best=None
    for mg in np.round(np.arange(0.0,0.20,0.02),2):
        p=rv_pnl(dev,mg)
        if len(p)<30: continue
        if best is None or p.mean()>best[1]: best=(mg,p.mean(),len(p))
    MG=best[0] if best else 0.04
    plk=rv_pnl(lk,MG)
    L=["# Kline-trained model → Polymarket (relative-value + regime) — 2026-06-03","",
       f"Kline DIRECTION model (GPU LSTM, calibrated) trained on 8.8y, ONLY before {TRAIN_CUTOFF.date()}; "
       f"applied to poly weeks (genuine OOS). Device={DEV}.","",
       "## Kline model OOS next-bar accuracy (per asset×tf)","| cell | acc | n |","|---|--:|--:|"]
    for (a,tf),r in models.items(): L.append(f"| {a} {tf} | {r['acc']} | {r['n_ap']} |")
    L+= ["","## (1) Relative-value on Polymarket (bet when model P(up) ≠ poly price by >margin)","",
         f"margin(dev)={MG}, win07 fee, $25.","",
         f"| set | n | $/tr | CI |","|---|--:|--:|--:|"]
    a_all=rv_pnl(lk,-9)  # take every slot on model's preferred side (baseline)
    L.append(f"| lockbox ALL (model side) | {len(a_all)} | {a_all.mean():+.3f} | [{boot(a_all)[0]:+.2f},{boot(a_all)[1]:+.2f}] |")
    L.append(f"| lockbox RV-gated | {len(plk)} | {plk.mean() if len(plk) else float('nan'):+.3f} | [{boot(plk)[0]:+.2f},{boot(plk)[1]:+.2f}] |")
    # (2) regime: does poly outcome favor model in trend regimes?
    L+= ["","## (2) Regime gate — poly UP-rate by kline regime (does regime predict poly direction?)","",
         "| regime | n | poly UP-rate | mean up_vwap |","|---|--:|--:|--:|"]
    for tr,nm in [(1,"uptrend"),(-1,"downtrend")]:
        g=d[d.regime_trend==tr]
        if len(g): L.append(f"| {nm} | {len(g)} | {100*g.up_win.mean():.1f}% | {g.up_vwap.mean():.3f} |")
    for vb,nm in [(0,"low-vol"),(1,"mid-vol"),(2,"high-vol")]:
        g=d[d.regime_vol==vb]
        if len(g): L.append(f"| {nm} | {len(g)} | {100*g.up_win.mean():.1f}% | {g.up_vwap.mean():.3f} |")
    L+= ["","## Read",
         "- Relative-value works ONLY if RV-gated $/tr beats ALL with lockbox CI>0 (model finds poly mispricing).",
         "- Regime gate works if poly UP-rate diverges from mean up_vwap within a regime (kline regime predicts poly).",
         "- Kline next-bar acc≈0.50 expected (efficient); the test is whether the poly PRICE is beatable, not the underlying.",
         "- Confirm any positive on the different-window OOS before sizing."]
    OUT.write_text("\n".join(L),encoding="utf-8")
    print("\n".join(L),flush=True); print(f"\nwrote {OUT} ({time.time()-t0:.0f}s)",flush=True)

if __name__=="__main__": main()
