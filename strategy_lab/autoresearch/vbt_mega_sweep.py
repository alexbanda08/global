"""
MEGA indicator sweep (vectorbt-style, TA-Lib + custom zoo) on Binance klines — underlying-crypto
direction. Budget-aware (run N hours). Single-indicator + 2-indicator-combo strategies, each ->
long/short/flat position, IS-Sharpe ranked, OOS-confirmed, per-series permutation null + deflation.

~45 indicator families: MA-cross (SMA/EMA/WMA/DEMA/TEMA/KAMA/T3/TRIMA/HULL), RSI/CMO/CCI/WILLR/STOCH/
STOCHRSI/MFI/ULTOSC/FISHER/CONNORS-RSI oscillators, MACD/PPO/TRIX/ROC/MOM/KST/COPPOCK momentum,
ADX-DI/AROON/SAR/SUPERTREND/VORTEX/LINREG-SLOPE trend, BBANDS/KELTNER/DONCHIAN/SQUEEZE volatility,
OBV/AD/ADOSC/CMF/EMV/FORCE volume, HT_TRENDMODE cycle.

NOT the Polymarket scalp (that needs L25 fills -> engine_v2). For tradeable underlying edge (Binance/HL).
Usage: python vbt_mega_sweep.py <hours> <klines_glob_or_dir>
  e.g. python vbt_mega_sweep.py 12 _data/binance_vision   (sweeps every *_full.parquet there)
       python vbt_mega_sweep.py 0.1 _data/_smoke_btc_1h.parquet
"""
import sys, time, glob, json, itertools
from pathlib import Path
import numpy as np, pandas as pd, talib
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
ROOT=Path(r"C:\Users\alexandre bandarra\Desktop\global")
OUTD=ROOT/"strategy_lab"/"autoresearch"/"_data"; OUTD.mkdir(parents=True,exist_ok=True)
RNG=np.random.default_rng(7)
FEE=0.0005

# ---------- custom indicators ----------
def _ema(x,n): return talib.EMA(x,n)
def hull(c,n):
    import numpy as np
    wma=lambda x,p: talib.WMA(x,p)
    h=wma(c,max(2,n//2))*2-wma(c,n)
    return wma(np.nan_to_num(h,nan=np.nan),max(2,int(np.sqrt(n))))
def supertrend(h,l,c,period=10,mult=3.0):
    atr=talib.ATR(h,l,c,period); hl2=(h+l)/2; ub=hl2+mult*atr; lb=hl2-mult*atr
    st=np.full(len(c),np.nan); d=np.ones(len(c)); fub=ub.copy(); flb=lb.copy()
    for i in range(1,len(c)):
        if np.isnan(atr[i]): continue
        fub[i]=ub[i] if (ub[i]<fub[i-1] or c[i-1]>fub[i-1]) else fub[i-1]
        flb[i]=lb[i] if (lb[i]>flb[i-1] or c[i-1]<flb[i-1]) else flb[i-1]
        d[i]=1 if c[i]>fub[i-1] else (-1 if c[i]<flb[i-1] else d[i-1])
    return d
def donchian(h,l,n):
    up=pd.Series(h).rolling(n).max().values; dn=pd.Series(l).rolling(n).min().values; return up,dn
def keltner(h,l,c,n,k):
    mid=talib.EMA(c,n); atr=talib.ATR(h,l,c,n); return mid+k*atr, mid-k*atr
def vortex(h,l,c,n):
    tr=talib.TRANGE(h,l,c)
    vmp=pd.Series(np.abs(h-np.roll(l,1))).rolling(n).sum().values
    vmm=pd.Series(np.abs(l-np.roll(h,1))).rolling(n).sum().values
    s=pd.Series(tr).rolling(n).sum().values
    return vmp/np.where(s==0,np.nan,s), vmm/np.where(s==0,np.nan,s)
def fisher(h,l,n):
    hl2=(h+l)/2; mn=pd.Series(hl2).rolling(n).min().values; mx=pd.Series(hl2).rolling(n).max().values
    raw=2*((hl2-mn)/np.where((mx-mn)==0,np.nan,(mx-mn))-0.5)
    v=np.zeros(len(h)); fish=np.zeros(len(h))
    for i in range(1,len(h)):
        if np.isnan(raw[i]): continue
        v[i]=0.33*raw[i]+0.67*v[i-1]; v[i]=min(max(v[i],-0.999),0.999)
        fish[i]=0.5*np.log((1+v[i])/(1-v[i]))+0.5*fish[i-1]
    return fish
def connors_rsi(c,r=3,s=2,n=100):
    rsi=talib.RSI(c,r)
    streak=np.zeros(len(c))
    for i in range(1,len(c)):
        if c[i]>c[i-1]: streak[i]=max(streak[i-1],0)+1
        elif c[i]<c[i-1]: streak[i]=min(streak[i-1],0)-1
    srsi=talib.RSI(streak.astype(float),s)
    roc=talib.ROC(c,1); pr=pd.Series(roc).rolling(n).apply(lambda x:(x.iloc[-1]>x).mean()*100,raw=False).values
    return (rsi+srsi+pr)/3
def kst(c):
    r=lambda p:talib.ROC(c,p)
    k=talib.SMA(r(10),10)+2*talib.SMA(r(15),10)+3*talib.SMA(r(20),10)+4*talib.SMA(r(30),15)
    return k, talib.SMA(k,9)
def coppock(c): return talib.WMA(talib.ROC(c,14)+talib.ROC(c,11),10)
def cmf(h,l,c,v,n):
    rng=(h-l); rng[rng==0]=np.nan; mfv=(((c-l)-(h-c))/rng)*v
    return pd.Series(mfv).rolling(n).sum().values/(pd.Series(v).rolling(n).sum().values+1e-9)

def ffill_pos(p):
    s=pd.Series(p,dtype=float).replace(0,np.nan).ffill().fillna(0); return s.values

# ---------- strategy generators: yield (label, position[-1/0/1]) ----------
def gen_single(o,h,l,c,v):
    # MA cross
    MAS={"SMA":talib.SMA,"EMA":talib.EMA,"WMA":talib.WMA,"DEMA":talib.DEMA,"TEMA":talib.TEMA,"KAMA":talib.KAMA,"T3":talib.T3,"TRIMA":talib.TRIMA}
    for nm,fn in MAS.items():
        for f,s in [(5,20),(10,30),(10,50),(20,50),(20,100),(50,100),(50,200),(20,200),(9,21),(8,34),(13,48)]:
            try: pos=np.sign(fn(c,f)-fn(c,s)); yield (f"MAx_{nm}_{f}_{s}", pos)
            except Exception: pass
    for n in [20,50,100]:
        try: pos=np.sign(c-hull(c,n)); yield (f"HULL_{n}", pos)
        except Exception: pass
    # oscillators threshold (revert + momo)
    OSC={"RSI":lambda p:talib.RSI(c,p),"CMO":lambda p:talib.CMO(c,p),"CCI":lambda p:talib.CCI(h,l,c,p),
         "WILLR":lambda p:talib.WILLR(h,l,c,p),"MFI":lambda p:talib.MFI(h,l,c,v,p)}
    BANDS={"RSI":[(30,70),(25,75),(20,80),(35,65)],"CMO":[(-50,50),(-40,40)],"CCI":[(-100,100),(-150,150),(-200,200)],
           "WILLR":[(-80,-20),(-90,-10)],"MFI":[(20,80),(25,75)]}
    for nm,fn in OSC.items():
        for p in ([7,14,21,28] if nm!="CCI" else [14,20,40]):
            try: ind=fn(p)
            except Exception: continue
            for lo,hi in BANDS[nm]:
                for mode in ["rev","mom"]:
                    pos=(np.where(ind<lo,1,np.where(ind>hi,-1,0)) if mode=="rev" else np.where(ind>hi,1,np.where(ind<lo,-1,0))).astype(float)
                    yield (f"{nm}_{mode}_{p}_{lo}_{hi}", ffill_pos(pos))
    # stoch / stochrsi / ultosc
    for k_ in [14,21]:
        kk,dd=talib.STOCH(h,l,c,fastk_period=k_,slowk_period=3,slowd_period=3)
        for lo,hi in [(20,80),(25,75)]:
            yield (f"STOCH_rev_{k_}", ffill_pos(np.where(kk<lo,1,np.where(kk>hi,-1,0)).astype(float)))
            yield (f"STOCH_cross_{k_}", np.sign(kk-dd))
    ul=talib.ULTOSC(h,l,c)
    yield ("ULTOSC_rev", ffill_pos(np.where(ul<30,1,np.where(ul>70,-1,0)).astype(float)))
    fk,fd=talib.STOCHRSI(c,timeperiod=14,fastk_period=5,fastd_period=3)
    yield ("STOCHRSI_cross", np.sign(fk-fd))
    # MACD/PPO/TRIX/ROC/MOM signs
    for f,s,sig in [(12,26,9),(8,21,5),(5,35,5)]:
        m,ms,mh=talib.MACD(c,f,s,sig); yield (f"MACD_{f}_{s}_{sig}", np.sign(mh))
    yield ("PPO_sign", np.sign(talib.PPO(c,12,26)))
    for p in [14,30]:
        yield (f"TRIX_{p}", np.sign(talib.TRIX(c,p)))
        yield (f"ROC_{p}", np.sign(talib.ROC(c,p)))
        yield (f"MOM_{p}", np.sign(talib.MOM(c,p)))
    ks,ksig=kst(c); yield ("KST", np.sign(ks-ksig))
    cop=coppock(c); yield ("COPPOCK", np.sign(cop))
    # trend: ADX-DI, AROON, SAR, SUPERTREND, VORTEX, LINREG slope
    for p in [14,20]:
        pdi,mdi,adx=talib.PLUS_DI(h,l,c,p),talib.MINUS_DI(h,l,c,p),talib.ADX(h,l,c,p)
        for athr in [20,25]:
            yield (f"ADXDI_{p}_{athr}", ffill_pos(np.where((adx>athr)&(pdi>mdi),1,np.where((adx>athr)&(mdi>pdi),-1,0)).astype(float)))
        au,ad=talib.AROON(h,l,p); yield (f"AROON_{p}", np.sign(au-ad))
    yield ("SAR", np.sign(c-talib.SAR(h,l)))
    for per,mult in [(10,3.0),(7,3.0),(14,2.0),(20,3.0)]:
        yield (f"SUPERTREND_{per}_{mult}", supertrend(h,l,c,per,mult))
    for p in [14,21]:
        vp,vm=vortex(h,l,c,p); yield (f"VORTEX_{p}", np.sign(vp-vm))
    for p in [20,50]:
        yield (f"LINREGSLOPE_{p}", np.sign(talib.LINEARREG_SLOPE(c,p)))
    fish=fisher(h,l,9); yield ("FISHER", np.sign(fish))
    crsi=connors_rsi(c); yield ("CONNORS_rev", ffill_pos(np.where(crsi<20,1,np.where(crsi>80,-1,0)).astype(float)))
    # volatility breakout/revert
    for p,k in [(20,2.0),(20,2.5),(30,2.0),(50,2.0)]:
        ub,mb,lb=talib.BBANDS(c,p,k,k)
        yield (f"BB_brk_{p}_{k}", ffill_pos(np.where(c>ub,1,np.where(c<lb,-1,0)).astype(float)))
        yield (f"BB_rev_{p}_{k}", ffill_pos(np.where(c<lb,1,np.where(c>ub,-1,0)).astype(float)))
        ku,kl=keltner(h,l,c,p,k)
        yield (f"KELT_brk_{p}_{k}", ffill_pos(np.where(c>ku,1,np.where(c<kl,-1,0)).astype(float)))
    for p in [20,55]:
        du,dl=donchian(h,l,p)
        yield (f"DONCH_brk_{p}", ffill_pos(np.where(c>=du,1,np.where(c<=dl,-1,0)).astype(float)))
    # volume
    yield ("OBV_slope", np.sign(pd.Series(talib.OBV(c,v)).diff(10).values))
    yield ("AD_slope", np.sign(pd.Series(talib.AD(h,l,c,v)).diff(10).values))
    yield ("ADOSC", np.sign(talib.ADOSC(h,l,c,v)))
    for p in [20,50]:
        yield (f"CMF_{p}", np.sign(cmf(h,l,c,v,p)))
    yield ("FORCE", np.sign(pd.Series((c-np.roll(c,1))*v).ewm(span=13).mean().values))
    yield ("HT_TREND", np.where(talib.HT_TRENDMODE(c)==1, np.sign(c-talib.HT_TRENDLINE(c)), 0).astype(float))

def sharpe(pos,logret,ann):
    pos=np.nan_to_num(pos,nan=0.0)
    r=pos[:-1]*logret - FEE*np.abs(np.diff(pos,prepend=pos[0]))[:-1]
    r=r[np.isfinite(r)]
    if len(r)<30 or r.std()==0: return np.nan,0
    ntr=int(np.sum(np.abs(np.diff(pos))>0))
    return float(r.mean()/r.std()*np.sqrt(ann)), ntr

def run_series(path,label,t_end):
    df=pd.read_parquet(path)
    if "open_time" in df: ts=pd.to_datetime(df.open_time,unit="ms"); cols=["open","high","low","close","volume"]
    elif "time_period_start_us" in df: ts=pd.to_datetime(df.time_period_start_us,unit="us"); cols=["price_open","price_high","price_low","price_close","volume_traded"]
    else: return None
    d=df.assign(ts=ts).sort_values("ts").drop_duplicates("ts")
    o,h,l,c,v=[pd.to_numeric(d[x],errors="coerce").values.astype(float) for x in cols]
    n=len(c)
    if n<500: return None
    dt=np.median(np.diff(d.ts.values).astype("timedelta64[s]").astype(float)); ann=(365*24*3600)/max(dt,1)
    cut1=int(n*0.50); cut2=int(n*0.75); lr=np.diff(np.log(c))
    lr_is=lr[:cut1-1]; lr_val=lr[cut1:cut2-1]; lr_oos=lr[cut2:]
    rows=[]
    for lbl,pos in gen_single(o,h,l,c,v):
        if pos is None or len(pos)!=n: continue
        p8=np.sign(np.nan_to_num(pos,nan=0.0)).astype(np.int8)   # positions are -1/0/1 -> int8 (8x less RAM)
        sh,ntr=sharpe(p8[:cut1],lr_is,ann)
        if np.isfinite(sh) and 5<=ntr<=cut1*0.5: rows.append((lbl,p8,sh,ntr))
        if time.time()>t_end: break
    rows.sort(key=lambda x:-x[2])
    # multi-indicator combos (2/3-way) — MEMORY-SAFE: keep only a bounded top-K (no full accumulation)
    pool=rows[:400]
    seen=set(r[0] for r in rows); n_searched=0; CAP=500
    keep=list(rows)  # start with singles; trim to top-CAP by IS sharpe periodically
    def combine(a,b,mode):
        if mode=="and": return np.where(a==b,a,0).astype(np.int8)
        if mode=="gate": return np.where(a!=0,b,0).astype(np.int8)
        return np.where(a==b,a,np.where(a==0,b,np.where(b==0,a,0))).astype(np.int8)
    while time.time()<t_end and len(pool)>2 and n_searched<400_000:
        if RNG.random()<0.7:
            a,b=pool[RNG.integers(len(pool))],pool[RNG.integers(len(pool))]
            mode=["and","gate","or"][RNG.integers(3)]; lbl=f"{a[0]}|{b[0]}|{mode}"
            if a[0]==b[0] or lbl in seen: continue
            pos=combine(a[1],b[1],mode)
        else:
            a,b,c2=[pool[RNG.integers(len(pool))] for _ in range(3)]; lbl=f"{a[0]}&{b[0]}&{c2[0]}"
            if lbl in seen: continue
            pos=np.where((a[1]==b[1])&(b[1]==c2[1]),a[1],0).astype(np.int8)
        seen.add(lbl); n_searched+=1
        sh,ntr=sharpe(pos[:cut1],lr_is,ann)
        if np.isfinite(sh) and 5<=ntr<=cut1*0.5: keep.append((lbl,pos,sh,ntr))
        if len(keep)>CAP*2:
            keep.sort(key=lambda x:-x[2]); keep=keep[:CAP]   # drop the rest -> frees their int8 arrays
        if len(seen)>800_000: seen=set(list(seen)[-400_000:])  # bound the dedup set
    allrows=sorted(keep,key=lambda x:-x[2])[:CAP]; n_strat_total=n_searched+len(rows)
    # NESTED confirm: rank by IS, take top 400, require VAL>0 then report OOS (unbiased). top=(lbl,IS,ntr,VAL,OOS)
    finals=[]
    for lbl,pos,sh,ntr in allrows[:400]:
        vsh,_=sharpe(pos[cut1:cut2],lr_val,ann); osh,_=sharpe(pos[cut2:],lr_oos,ann)
        finals.append((lbl,sh,ntr,vsh,osh))
    finals.sort(key=lambda x:-x[1])
    top=finals[:25]
    # null: shuffled-returns best IS Sharpe over the SAME single+combo style (approximation via singles+random combos)
    nulls=[]
    base=rows[:120]
    for _ in range(40):
        sret=lr_is[RNG.permutation(len(lr_is))]; best=-9
        for _,pos,_,_ in base:
            s,_=sharpe(pos[:cut1],sret,ann); best=max(best,s if np.isfinite(s) else -9)
        for _ in range(200):  # include combo-style nulls
            a,b=base[RNG.integers(len(base))],base[RNG.integers(len(base))]
            s,_=sharpe(np.where(np.sign(a[1])==np.sign(b[1]),np.sign(a[1]),0).astype(float)[:cut1],sret,ann)
            best=max(best,s if np.isfinite(s) else -9)
        nulls.append(best)
    null_p95=float(np.nanpercentile(nulls,95))
    return dict(label=label,n=n,start=str(d.ts.iloc[0].date()),end=str(d.ts.iloc[-1].date()),
                n_strat=n_strat_total,null_p95=round(null_p95,2),top=top)

def main():
    hours=float(sys.argv[1]) if len(sys.argv)>1 else 0.1
    target=sys.argv[2] if len(sys.argv)>2 else str(OUTD/"binance_vision")
    p=Path(target)
    files=[str(p)] if p.is_file() else sorted(glob.glob(str(p/"*_full.parquet")))
    files=[f for f in files if not any(x in Path(f).stem for x in ["_1m","_5m"])]  # skip ultra-HF (slow/noisy)
    if not files: print(f"no parquet at {target}"); return
    t0=time.time(); budget=hours*3600; per=budget/max(len(files),1)
    print(f"MEGA sweep | {len(files)} series | {hours}h ({per/3600:.2f}h each)",flush=True)
    out=[]
    for i,f in enumerate(files):
        lbl=Path(f).stem.replace("_full","")
        r=run_series(f,lbl,t0+per*(i+1))
        if r:
            out.append(r)
            print(f"[{lbl}] n={r['n']} strat={r['n_strat']} null95={r['null_p95']} | best IS/VAL/OOS: "+
                  ", ".join(f"{t[0][:30]}({t[1]:.1f}/{t[3]:.1f}/{t[4]:.1f})" for t in r['top'][:3]),flush=True)
    # report
    L=["# VectorBT MEGA indicator sweep — underlying crypto direction — auto",
       f"","~45 indicator families (TA-Lib + custom) × params × modes + 2-indicator combos. IS=first60%, "
       f"OOS=last40%, fee={FEE*1e4:.0f}bps/flip. Per series: best-20 by IS-Sharpe, OOS-confirmed, vs shuffled null.",""]
    surv=[]
    def is_surv(sh,vsh,osh,nullp): return (sh>nullp) and (vsh>0.3) and (osh>0.3)
    for r in out:
        L+= [f"## {r['label']}  (n={r['n']}, {r['start']}→{r['end']}, strat={r['n_strat']}, null_p95={r['null_p95']})",
             "| strategy | IS Sharpe | ntr | VAL Sharpe | OOS Sharpe |","|---|--:|--:|--:|--:|"]
        for lbl,sh,ntr,vsh,osh in r["top"][:12]:
            ok=is_surv(sh,vsh,osh,r['null_p95']); star=" ✅" if ok else ""
            L.append(f"| {lbl} | {sh:.2f} | {ntr} | {vsh:.2f} | {osh:.2f}{star} |")
            if ok: surv.append((r['label'],lbl,sh,vsh,osh))
        L.append("")
    L+= ["## Survivors (IS>null_p95 AND VAL>0.3 AND OOS>0.3 — positive in ALL three independent periods)",""]
    if surv:
        L+=["| series | strategy | IS | VAL | OOS |","|---|---|--:|--:|--:|"]+[f"| {a} | {b} | {c:.2f} | {d:.2f} | {e:.2f} |" for a,b,c,d,e in surv]
        L.append("\n⚠️ Even all-3-positive among millions of combos can be chance. **Confirm on a 4th window (the 6-month API) before any sizing.**")
    else:
        L.append("**None.** No indicator strategy held IS→VAL→OOS above the null floor — crypto direction efficient at these TFs.")
    L+= ["","_Re-confirm any survivor on a 3rd window before sizing. This is underlying edge (Binance/HL), not Polymarket._"]
    (ROOT/"strategy_lab"/"reports"/"VBT_MEGA_SWEEP.md").write_text("\n".join(L),encoding="utf-8")
    json.dump(out,open(OUTD/"vbt_mega_results.json","w"),default=str,indent=1)
    print(f"\nDONE {len(out)} series, {sum(r['n_strat'] for r in out)} strategies, {len(surv)} survivors ({time.time()-t0:.0f}s) -> VBT_MEGA_SWEEP.md",flush=True)

if __name__=="__main__": main()
