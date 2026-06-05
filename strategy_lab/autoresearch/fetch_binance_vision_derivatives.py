"""
Binance Vision DERIVATIVES history for BTC/ETH/SOL (futures USDⓈ-M), disk-safe.
Pulls: futures um klines (basis), fundingRate (monthly), daily metrics (OI + long/short ratios).
Streams zip -> parquet -> deletes zip. Idempotent. 404 auto-skip.

Output under: strategy_lab/autoresearch/_data/binance_vision_deriv/
Usage: python fetch_binance_vision_derivatives.py
"""
import sys, io, zipfile, time
from pathlib import Path
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd, requests
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
ROOT=Path(__file__).resolve().parent/"_data"/"binance_vision_deriv"; ROOT.mkdir(parents=True,exist_ok=True)
B="https://data.binance.vision/data/futures/um"
SYMS=["BTCUSDT","ETHUSDT","SOLUSDT"]
KL_TFS=["1h","4h","1d"]; START_Y=2020
KCOLS=["open_time","open","high","low","close","volume","close_time","quote_vol","trades","tbb","tbq","ignore"]

def months(y0):
    t=date.today()
    for y in range(y0,t.year+1):
        for m in range(1,13):
            if date(y,m,1)>t: return
            yield y,m
def days(y0):
    d=date(y0,1,1); t=date.today()
    while d<=t: yield d; d+=timedelta(days=1)

def fetch(url):
    r=requests.get(url,timeout=60)
    if r.status_code!=200: return None
    z=zipfile.ZipFile(io.BytesIO(r.content)); return pd.read_csv(z.open(z.namelist()[0]),header=None)

def kline(sym,tf,y,m):
    out=ROOT/"klines"/sym/tf/f"{sym}-{tf}-{y}-{m:02d}.parquet"
    if out.exists(): return "skip"
    df=fetch(f"{B}/monthly/klines/{sym}/{tf}/{sym}-{tf}-{y}-{m:02d}.zip")
    if df is None: return "404"
    df=df.iloc[:,:12]; df.columns=KCOLS
    if str(df.iloc[0,0]).lower().startswith("open"): df=df.iloc[1:]
    out.parent.mkdir(parents=True,exist_ok=True); df.drop(columns=["ignore"]).to_parquet(out,index=False); return "ok"

def funding(sym,y,m):
    out=ROOT/"funding"/sym/f"{sym}-fundingRate-{y}-{m:02d}.parquet"
    if out.exists(): return "skip"
    df=fetch(f"{B}/monthly/fundingRate/{sym}/{sym}-fundingRate-{y}-{m:02d}.zip")
    if df is None: return "404"
    if str(df.iloc[0,0]).lower().startswith("calc"): df=df.iloc[1:]
    out.parent.mkdir(parents=True,exist_ok=True); df.to_parquet(out,index=False); return "ok"

def metrics(sym,d):
    out=ROOT/"metrics"/sym/f"{sym}-metrics-{d}.parquet"
    if out.exists(): return "skip"
    df=fetch(f"{B}/daily/metrics/{sym}/{sym}-metrics-{d}.zip")
    if df is None: return "404"
    if str(df.iloc[0,0]).lower().startswith("create"): df=df.iloc[1:]
    out.parent.mkdir(parents=True,exist_ok=True); df.to_parquet(out,index=False); return "ok"

def main():
    jobs=[]
    for s in SYMS:
        for tf in KL_TFS:
            for y,m in months(START_Y): jobs.append((kline,(s,tf,y,m)))
        for y,m in months(START_Y): jobs.append((funding,(s,y,m)))
        for d in days(2020): jobs.append((metrics,(s,str(d))))
    print(f"deriv pull: {len(jobs)} files (klines+funding+metrics)",flush=True)
    t0=time.time(); c={"ok":0,"skip":0,"404":0,"err":0}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs={ex.submit(fn,*a):None for fn,a in jobs}
        for i,f in enumerate(as_completed(futs)):
            try: c[f.result()]+=1
            except Exception: c["err"]+=1
            if (i+1)%500==0: print(f"  {i+1}/{len(jobs)} {c} ({time.time()-t0:.0f}s)",flush=True)
    # consolidate
    for kind in ["klines","funding","metrics"]:
        for s in SYMS:
            base=ROOT/kind/s
            parts=list(base.rglob("*.parquet")) if base.exists() else []
            if not parts: continue
            big=pd.concat([pd.read_parquet(p) for p in parts],ignore_index=True)
            big.to_parquet(ROOT/f"{s}_{kind}_full.parquet",index=False)
            print(f"  {s} {kind}: {len(big):,} rows -> {s}_{kind}_full.parquet",flush=True)
    print(f"DONE {c} ({time.time()-t0:.0f}s)",flush=True)

if __name__=="__main__": main()
