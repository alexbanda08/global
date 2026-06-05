"""
OVERNIGHT GPU model search (fills ~12h). Repeatedly trains different kline DIRECTION models
(arch x seq x hidden x layers x horizon x feature-subset), each on 8.8y klines (pre-poly only),
and judges EACH by whether it BEATS THE POLY PRICE (relative-value) on the poly lockbox.

Discipline: kline model trained only before 2026-03-15 (poly weeks = OOS). For each config, margin is
chosen on poly-DEV and the metric is poly-LOCKBOX RV-gated $/tr + bootstrap CI. Deflation: report how many
configs tried (best lockbox CI>0 among N is suspect -> the different-window OOS is the final judge).
Checkpoints every config to gpu_search_log.jsonl; writes GPU_MODEL_SEARCH.md at the end / on budget.

Usage: python gpu_model_search.py <hours>
"""
import sys, time, json
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import os
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF","expandable_segments:True")
import torch, torch.nn as nn, talib
from sklearn.isotonic import IsotonicRegression
ROOT=Path(r"C:\Users\alexandre bandarra\Desktop\global")
KD=ROOT/"strategy_lab"/"autoresearch"/"_data"/"binance_vision"
POLY=ROOT/"strategy_lab"/"cross_feature_2026_05_26"/"master.parquet"
OUTD=ROOT/"strategy_lab"/"autoresearch"/"_data"; LOG=OUTD/"gpu_search_log.jsonl"
DEV="cuda" if torch.cuda.is_available() else "cpu"
CUTOFF=pd.Timestamp("2026-03-15"); CUTOFF_S=int(CUTOFF.timestamp()); RNG=np.random.default_rng(int(time.time())%99999)
HOURS=float(sys.argv[1]) if len(sys.argv)>1 else 12.0
CELLS=[("BTC","5m"),("ETH","5m"),("SOL","5m"),("BTC","15m"),("ETH","15m"),("SOL","15m")]
FEATNAMES=["lr","rsi","atr","roc","espread","rvol"]

def build_series(asset,tf):
    f=KD/f"{asset}USDT_{tf}_full.parquet"
    if not f.exists(): return None
    d=pd.read_parquet(f); d["ts"]=pd.to_datetime(d.open_time,unit="ms"); d=d.sort_values("ts").drop_duplicates("ts")
    c=d.close.values.astype(float);h=d.high.values.astype(float);l=d.low.values.astype(float)
    lr=np.r_[0,np.diff(np.log(c))]
    rsi=np.nan_to_num(talib.RSI(c,14)/100.0); atr=np.nan_to_num(talib.ATR(h,l,c,14)/c)
    roc=np.nan_to_num(talib.ROC(c,10)/100.0); e50,e200=talib.EMA(c,50),talib.EMA(c,200)
    esp=np.nan_to_num((e50-e200)/c); rv=pd.Series(lr).rolling(50).std().bfill().values
    F=np.column_stack([lr,rsi,atr,roc,esp,np.nan_to_num(np.tanh(rv*50))]).astype(np.float32)
    ts=d.ts.values.astype("datetime64[s]").astype(np.int64); logc=np.log(c)
    return dict(F=F,ts=ts,logc=logc,n=len(c))

class Net(nn.Module):
    def __init__(s,nf,arch,hid,layers):
        super().__init__()
        s.rnn=(nn.LSTM if arch=="lstm" else nn.GRU)(nf,hid,layers,batch_first=True,dropout=0.2 if layers>1 else 0.0)
        s.h=nn.Sequential(nn.Linear(hid,24),nn.ReLU(),nn.Dropout(0.2),nn.Linear(24,1))
    def forward(s,x): o,_=s.rnn(x); return s.h(o[:,-1,:]).squeeze(-1)

def train_cell(series,cfg):
    F=series["F"][:,cfg["feat"]]; ts=series["ts"]; logc=series["logc"]; n=series["n"]
    SEQ=cfg["seq"]; H=cfg["hor"]
    Xs=[];ys=[];ix=[]
    for i in range(SEQ,n-H):
        Xs.append(F[i-SEQ:i]); ys.append(1.0 if (logc[i+H]-logc[i])>0 else 0.0); ix.append(i)
    if len(Xs)<6000: return None
    X=np.asarray(Xs,dtype=np.float32);Y=np.asarray(ys,dtype=np.float32);ix=np.asarray(ix)
    is_tr=ts[ix]<CUTOFF_S; tr=np.where(is_tr)[0]; ap=np.where(~is_tr)[0]
    if len(tr)<5000 or len(ap)<40: return None
    mu=X[tr].reshape(-1,X.shape[2]).mean(0);sd=X[tr].reshape(-1,X.shape[2]).std(0)+1e-6;Xn=(X-mu)/sd
    vcut=int(len(tr)*0.9);trn,val=tr[:vcut],tr[vcut:]
    tX=torch.from_numpy(Xn);tY=torch.from_numpy(Y)   # stay on CPU; batch to GPU (bounds VRAM)
    net=Net(X.shape[2],cfg["arch"],cfg["hid"],cfg["lay"]).to(DEV)
    opt=torch.optim.Adam(net.parameters(),1e-3,weight_decay=1e-5);lf=nn.BCEWithLogitsLoss()
    def vloss(idxs):
        tot=0.0;ntot=0
        with torch.no_grad():
            for b in range(0,len(idxs),4096):
                bi=idxs[b:b+4096]; tot+=lf(net(tX[bi].to(DEV)),tY[bi].to(DEV)).item()*len(bi);ntot+=len(bi)
        return tot/max(ntot,1)
    def predict(idxs):
        out=[]
        with torch.no_grad():
            for b in range(0,len(idxs),4096):
                out.append(torch.sigmoid(net(tX[idxs[b:b+4096]].to(DEV))).cpu().numpy())
        return np.concatenate(out) if out else np.array([])
    best=1e9;bs=None;pat=0
    for ep in range(cfg["ep"]):
        net.train();perm=RNG.permutation(trn)
        for b in range(0,len(trn),2048):
            bi=perm[b:b+2048];opt.zero_grad();lf(net(tX[bi].to(DEV)),tY[bi].to(DEV)).backward();opt.step()
        net.eval();vl=vloss(val)
        if vl<best-1e-4:best=vl;pat=0;bs={k:vv.clone() for k,vv in net.state_dict().items()}
        else:pat+=1
        if pat>=2: break
    net.load_state_dict(bs);net.eval()
    pv=predict(val);pa=predict(ap)
    iso=IsotonicRegression(out_of_bounds="clip");iso.fit(pv,Y[val]);pa=iso.transform(pa)
    acc=float(((pa>0.5)==(Y[ap]>0.5)).mean())
    del net,tX,tY
    if DEV=="cuda": torch.cuda.empty_cache()
    return dict(ts=ts[ix[ap]],pup=pa,acc=acc)

def boot(x,nb=4000):
    x=np.asarray(x,float);x=x[np.isfinite(x)]
    if len(x)<8: return (np.nan,np.nan)
    b=x[RNG.integers(0,len(x),(nb,len(x)))].mean(1);return float(np.percentile(b,2.5)),float(np.percentile(b,97.5))

def poly_eval(cellpred):
    m=pd.read_parquet(POLY).drop_duplicates("slug")
    m=m[m.up_vwap.notna()&m.dn_vwap.notna()].copy(); m["up_win"]=(m.outcome=="Up").astype(int)
    m["mP"]=np.nan
    for (a,tf),r in cellpred.items():
        sel=(m.asset==a)&(m.tf==tf)
        if not sel.any() or r is None: continue
        wss=m.loc[sel,"ws_s"].values.astype(np.int64); pos=np.searchsorted(r["ts"],wss,side="right")-1
        vals=np.where(pos>=0, r["pup"][np.clip(pos,0,len(r["pup"])-1)], np.nan)
        m.loc[sel,"mP"]=np.where(pos>=0,vals,np.nan)
    d=m[m.mP.notna()].sort_values("fire_us").reset_index(drop=True)
    if len(d)<200: return None
    cut=int(len(d)*0.7); dev=d.iloc[:cut]; lk=d.iloc[cut:]
    def rv(dd,mg):
        out=[]
        for r in dd.itertuples():
            eu=r.mP-r.up_vwap; ed=(1-r.mP)-r.dn_vwap
            if eu>mg and eu>=ed: out.append((1-r.up_vwap)*(1-0.07*r.up_vwap) if r.up_win else -r.up_vwap)
            elif ed>mg: out.append((1-r.dn_vwap)*(1-0.07*r.dn_vwap) if (1-r.up_win) else -r.dn_vwap)
        return np.array(out)*25.0
    best=None
    for mg in np.round(np.arange(0.0,0.18,0.02),2):
        p=rv(dev,mg)
        if len(p)<25: continue
        if best is None or p.mean()>best[1]: best=(mg,p.mean(),len(p))
    mg=best[0] if best else 0.04
    plk=rv(lk,mg); ci=boot(plk)
    accs=[r["acc"] for r in cellpred.values() if r]
    return dict(margin=mg,lk_n=len(plk),lk_dpt=round(float(plk.mean()) if len(plk) else float("nan"),3),
                lk_ci=(round(ci[0],2),round(ci[1],2)),mean_acc=round(float(np.mean(accs)),3) if accs else None)

def sample_cfg():
    k=int(RNG.integers(3,7)); feat=sorted(RNG.choice(6,k,replace=False).tolist())
    return dict(arch=str(RNG.choice(["lstm","gru"])),seq=int(RNG.choice([32,48,64])),
                hid=int(RNG.choice([32,48,64])),lay=int(RNG.choice([1,2])),hor=int(RNG.choice([1,2,3])),
                ep=int(RNG.choice([6,8,10])),feat=feat)

def main():
    print(f"GPU model search | {HOURS}h | dev={DEV}",flush=True)
    series={c:build_series(*c) for c in CELLS}; series={k:v for k,v in series.items() if v}
    print(f"loaded {len(series)} cells",flush=True)
    t0=time.time(); results=[]; ncfg=0
    while time.time()-t0 < HOURS*3600:
        cfg=sample_cfg(); ncfg+=1
        try:
            cp={c:train_cell(series[c],cfg) for c in series}
            ev=poly_eval(cp)
        except Exception as e:
            ev=None; print(f"  cfg{ncfg} err {str(e)[:80]}",flush=True)
            try:
                import torch as _t
                if _t.cuda.is_available(): _t.cuda.empty_cache()
            except Exception: pass
        if ev:
            row={"cfg":cfg,**ev,"i":ncfg,"t":round(time.time()-t0)}
            results.append(row)
            with open(LOG,"a") as fh: fh.write(json.dumps(row,default=str)+"\n")
            tag="✅" if (ev["lk_ci"][0]>0 and ev["lk_dpt"]>0) else ""
            print(f"  cfg{ncfg} acc={ev['mean_acc']} polyLK $/tr={ev['lk_dpt']} CI{ev['lk_ci']} n={ev['lk_n']} {tag} ({row['t']}s)",flush=True)
        if ncfg%5==0:
            best=sorted([r for r in results if np.isfinite(r['lk_dpt'])],key=lambda r:-r['lk_dpt'])[:1]
            if best: print(f"  ...{ncfg} configs, best polyLK $/tr={best[0]['lk_dpt']} CI{best[0]['lk_ci']}",flush=True)
    # report
    R=sorted([r for r in results if np.isfinite(r['lk_dpt'])],key=lambda r:-r['lk_dpt'])
    surv=[r for r in R if r['lk_ci'][0]>0 and r['lk_dpt']>0]
    L=[f"# Overnight GPU model search — kline→poly relative-value — 2026-06-03","",
       f"Trained **{ncfg}** model configs (arch×seq×hidden×layers×horizon×features) on 8.8y klines (pre-{CUTOFF.date()}); "
       f"each judged by **poly-LOCKBOX relative-value $/tr** (does it beat the poly price?). Device={DEV}.","",
       "## Top 15 configs by poly-lockbox $/tr","| arch | seq | hid | lay | hor | acc | polyLK $/tr | CI | n |","|---|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for r in R[:15]:
        c=r["cfg"]; L.append(f"| {c['arch']} | {c['seq']} | {c['hid']} | {c['lay']} | {c['hor']} | {r['mean_acc']} | {r['lk_dpt']:+} | [{r['lk_ci'][0]:+},{r['lk_ci'][1]:+}] | {r['lk_n']} |")
    L+= ["",f"## Survivors (poly-lockbox CI>0 AND $/tr>0): {len(surv)}/{ncfg}",""]
    if surv:
        L.append("⚠️ With "+str(ncfg)+" configs searched, a few CI>0 by chance. The different-window OOS (6-month API) is the only proof. Best candidates:")
        for r in surv[:8]:
            c=r["cfg"]; L.append(f"- {c['arch']} seq{c['seq']} h{c['hid']} L{c['lay']} hor{c['hor']} feat{c['feat']}: $/tr {r['lk_dpt']:+} CI{r['lk_ci']} (acc {r['mean_acc']})")
    else:
        L.append("**None beat the poly price with CI>0.** The kline model does not find exploitable poly mispricing — "
                 "poly up/down is efficiently priced vs an 8.8y-trained direction model. Edge stays in execution (exit-scalp).")
    (ROOT/"strategy_lab"/"reports"/"GPU_MODEL_SEARCH.md").write_text("\n".join(L),encoding="utf-8")
    print("\n".join(L[:40]),flush=True); print(f"\nDONE {ncfg} configs, {len(surv)} survivors ({(time.time()-t0)/3600:.1f}h)",flush=True)

if __name__=="__main__": main()
