"""
Download FULL Binance Vision spot-kline history for BTC/ETH/SOL (up to 7y), disk-safe.
Streams each monthly zip -> parquet -> DELETES the zip immediately (never accumulates raw zips).
Idempotent: skips months already converted. 404 on early months auto-skips.

Output: strategy_lab/autoresearch/_data/binance_vision/{SYM}/{TF}/{SYM}-{TF}-YYYY-MM.parquet
Usage:  python fetch_binance_vision_history.py [tfs comma] [start_year]
  e.g.  python fetch_binance_vision_history.py 1h,4h,1d 2017
        python fetch_binance_vision_history.py 1m,5m,15m,1h,4h,1d 2017   (BIG — watch disk)
"""
import sys, io, zipfile, time
from pathlib import Path
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd, requests
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
ROOT=Path(__file__).resolve().parent/"_data"/"binance_vision"; ROOT.mkdir(parents=True,exist_ok=True)
BASE="https://data.binance.vision/data/spot/monthly/klines"
SYMS=["BTCUSDT","ETHUSDT","SOLUSDT"]
TFS=(sys.argv[1].split(",") if len(sys.argv)>1 else ["1h","4h","1d"])
START_Y=int(sys.argv[2]) if len(sys.argv)>2 else 2017
COLS=["open_time","open","high","low","close","volume","close_time","quote_vol","trades","taker_buy_base","taker_buy_quote","ignore"]

def months(y0):
    today=date.today()
    for y in range(y0, today.year+1):
        for m in range(1,13):
            if date(y,m,1)>today: return
            yield y,m

def one(sym,tf,y,m):
    out=ROOT/sym/tf/f"{sym}-{tf}-{y}-{m:02d}.parquet"
    if out.exists(): return ("skip",out)
    url=f"{BASE}/{sym}/{tf}/{sym}-{tf}-{y}-{m:02d}.zip"
    try:
        r=requests.get(url,timeout=60)
        if r.status_code!=200: return ("404",url)
        z=zipfile.ZipFile(io.BytesIO(r.content))
        df=pd.read_csv(z.open(z.namelist()[0]),header=None)
        df=df.iloc[:,:12]; df.columns=COLS
        # some months have a header row
        if str(df.iloc[0,0]).lower().startswith("open"): df=df.iloc[1:]
        for c in ["open","high","low","close","volume","quote_vol","taker_buy_base","taker_buy_quote"]:
            df[c]=pd.to_numeric(df[c],errors="coerce")
        df["open_time"]=pd.to_numeric(df["open_time"],errors="coerce").astype("int64")
        df["trades"]=pd.to_numeric(df["trades"],errors="coerce")
        df=df.drop(columns=["ignore"])
        out.parent.mkdir(parents=True,exist_ok=True)
        df.to_parquet(out,index=False)   # zip bytes are freed here; nothing written to disk but the parquet
        return ("ok",out)
    except Exception as e:
        return ("err",f"{url} {e}")

def main():
    jobs=[(s,tf,y,m) for s in SYMS for tf in TFS for (y,m) in months(START_Y)]
    print(f"Binance Vision pull: {SYMS} TFs={TFS} from {START_Y} -> {len(jobs)} month-files",flush=True)
    t0=time.time(); ok=skip=miss=err=0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs={ex.submit(one,*j):j for j in jobs}
        for i,f in enumerate(as_completed(futs)):
            st,_=f.result()
            ok+=st=="ok"; skip+=st=="skip"; miss+=st=="404"; err+=st=="err"
            if (i+1)%200==0:
                print(f"  {i+1}/{len(jobs)}  ok={ok} skip={skip} 404={miss} err={err}  ({time.time()-t0:.0f}s)",flush=True)
    # consolidate per sym/tf into one parquet for easy loading
    for s in SYMS:
        for tf in TFS:
            d=ROOT/s/tf
            parts=sorted(d.glob(f"{s}-{tf}-*.parquet")) if d.exists() else []
            if not parts: continue
            big=pd.concat([pd.read_parquet(p) for p in parts],ignore_index=True).sort_values("open_time").drop_duplicates("open_time")
            big.to_parquet(ROOT/f"{s}_{tf}_full.parquet",index=False)
            print(f"  consolidated {s} {tf}: {len(big):,} bars -> {s}_{tf}_full.parquet "
                  f"({pd.to_datetime(big.open_time.min(),unit='ms').date()} -> {pd.to_datetime(big.open_time.max(),unit='ms').date()})",flush=True)
    print(f"\nDONE ok={ok} skip={skip} 404={miss} err={err} ({time.time()-t0:.0f}s)",flush=True)

if __name__=="__main__":
    main()
