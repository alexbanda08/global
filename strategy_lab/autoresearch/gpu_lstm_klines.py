"""
GPU LSTM/GRU sequence model on Binance klines (underlying-crypto direction). Uses the RTX 3060.
Tests whether a deep sequence net finds tradeable structure the indicator sweep can't. Honest:
walk-forward OOS + buy&hold benchmark + the strategy Sharpe is the judge (not train accuracy).

NOT the Polymarket scalp. For underlying edge (Binance/HL).
Usage: python gpu_lstm_klines.py <klines_parquet> [label] [epochs]
"""
import sys, time
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import torch, torch.nn as nn
ROOT=Path(r"C:\Users\alexandre bandarra\Desktop\global")
DEV="cuda" if torch.cuda.is_available() else "cpu"
SEQ=64; HORIZON=1; BATCH=512

def load(path):
    df=pd.read_parquet(path)
    if "open_time" in df: ts=pd.to_datetime(df.open_time,unit="ms"); c=pd.to_numeric(df["close"],errors="coerce"); h=pd.to_numeric(df["high"],errors="coerce"); l=pd.to_numeric(df["low"],errors="coerce"); v=pd.to_numeric(df["volume"],errors="coerce")
    else: ts=pd.to_datetime(df.time_period_start_us,unit="us"); c=df.price_close; h=df.price_high; l=df.price_low; v=df.volume_traded
    d=pd.DataFrame({"ts":ts,"c":c,"h":h,"l":l,"v":v}).dropna().sort_values("ts").drop_duplicates("ts")
    return d

class Net(nn.Module):
    def __init__(s,nf,hid=64,layers=2):
        super().__init__(); s.lstm=nn.LSTM(nf,hid,layers,batch_first=True,dropout=0.2); s.head=nn.Sequential(nn.Linear(hid,32),nn.ReLU(),nn.Dropout(0.2),nn.Linear(32,1))
    def forward(s,x): o,_=s.lstm(x); return s.head(o[:,-1,:]).squeeze(-1)

def main():
    path=sys.argv[1]; label=sys.argv[2] if len(sys.argv)>2 else "asset"; EP=int(sys.argv[3]) if len(sys.argv)>3 else 12
    d=load(path); c=d.c.values.astype(np.float64)
    if len(c)<3000: print(f"[{label}] too few bars ({len(c)})"); return
    lr=np.diff(np.log(c));
    # features per bar: logret, rolling vol, rsi-ish, range, volume z
    import talib
    rsi=talib.RSI(c,14)/100.0; atr=talib.ATR(d.h.values,d.l.values,c,14)/c
    vz=(d.v.values-pd.Series(d.v.values).rolling(50).mean().values)/(pd.Series(d.v.values).rolling(50).std().values+1e-9)
    mom=talib.ROC(c,10)/100.0
    feat=np.column_stack([np.r_[0,lr], np.nan_to_num(rsi), np.nan_to_num(atr), np.nan_to_num(np.tanh(vz)), np.nan_to_num(mom)])
    n=len(c); ann=np.sqrt(365*24)  # rough (works for hourly; scaled per series only for display)
    # build sequences: X[i] = feat[i-SEQ:i], y[i]=sign(logret[i]) (next-bar)
    Xs,ys,idx=[],[],[]
    for i in range(SEQ, n-1):
        Xs.append(feat[i-SEQ:i]); ys.append(1.0 if lr[i]>0 else 0.0); idx.append(i)
    X=np.asarray(Xs,dtype=np.float32); y=np.asarray(ys,dtype=np.float32); idx=np.asarray(idx)
    # standardize features on train portion
    cut1=int(len(X)*0.70); cut2=int(len(X)*0.85)
    mu=X[:cut1].reshape(-1,X.shape[2]).mean(0); sd=X[:cut1].reshape(-1,X.shape[2]).std(0)+1e-6
    Xn=(X-mu)/sd
    tX=torch.tensor(Xn).to(DEV); tY=torch.tensor(y).to(DEV)
    net=Net(X.shape[2]).to(DEV); opt=torch.optim.Adam(net.parameters(),lr=1e-3,weight_decay=1e-5); lossf=nn.BCEWithLogitsLoss()
    print(f"[{label}] dev={DEV} bars={n} seqs={len(X)} feats={X.shape[2]} train={cut1} val={cut2-cut1} test={len(X)-cut2}",flush=True)
    t0=time.time(); best=1e9; patience=0
    for ep in range(EP):
        net.train(); perm=torch.randperm(cut1,device=DEV)
        for b in range(0,cut1,BATCH):
            bi=perm[b:b+BATCH]; opt.zero_grad(); out=net(tX[bi]); loss=lossf(out,tY[bi]); loss.backward(); opt.step()
        net.eval()
        with torch.no_grad():
            vlogit=net(tX[cut1:cut2]); vloss=lossf(vlogit,tY[cut1:cut2]).item()
            vacc=((torch.sigmoid(vlogit)>0.5).float()==tY[cut1:cut2]).float().mean().item()
        if vloss<best-1e-4: best=vloss; patience=0; best_state={k:vv.clone() for k,vv in net.state_dict().items()}
        else: patience+=1
        print(f"  ep{ep} val_loss={vloss:.4f} val_acc={vacc:.3f} ({time.time()-t0:.0f}s)",flush=True)
        if patience>=3: break
    net.load_state_dict(best_state); net.eval()
    with torch.no_grad():
        p_test=torch.sigmoid(net(tX[cut2:])).cpu().numpy()
    yt=y[cut2:]; lr_test=lr[idx[cut2:]]
    acc=float(((p_test>0.5)==(yt>0.5)).mean())
    # OOS long/short strategy: position = sign(p-0.5); confidence gate
    pos=np.where(p_test>0.55,1,np.where(p_test<0.45,-1,0)).astype(float)
    ret=pos*lr_test - 0.0005*np.abs(np.r_[pos[0],np.diff(pos)])
    sharpe=float(ret.mean()/(ret.std()+1e-9)*ann) if ret.std()>0 else 0.0
    bh=float(lr_test.mean()/(lr_test.std()+1e-9)*ann)
    L=[f"# GPU LSTM — {label} (underlying-crypto direction) — auto","",
       f"Device={DEV}. SEQ={SEQ}, next-bar direction. Walk-forward train70/val15/**test15** (held out).","",
       f"- Test directional accuracy: **{acc:.3f}** (0.50 = coin-flip)",
       f"- OOS strategy Sharpe (pos=conf>0.55, 5bps): **{sharpe:.2f}**   vs buy&hold Sharpe {bh:.2f}",
       f"- n_test={len(yt)}, trades={int(np.sum(np.abs(np.diff(pos))>0))}","",
       "## Read","- acc≈0.50 and Sharpe≈0 => deep net finds NO tradeable direction (efficient), consistent with the indicator sweep.",
       "- Only a clearly >0.5 acc AND OOS Sharpe>buy&hold that holds on a 2nd asset/window is real. Re-confirm before sizing."]
    (ROOT/"strategy_lab"/"reports"/f"GPU_LSTM_{label}.md").write_text("\n".join(L),encoding="utf-8")
    print("\n".join(L),flush=True); print(f"\nwrote GPU_LSTM_{label}.md ({time.time()-t0:.0f}s)",flush=True)

if __name__=="__main__": main()
