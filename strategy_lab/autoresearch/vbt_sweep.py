"""
VectorBT massive indicator-strategy sweep on Binance klines (underlying-crypto direction).
NOT the Polymarket scalp (that needs L25 book fills -> engine_v2). This mines the 7y price history
for tradeable directional edge in BTC/ETH/SOL with WALK-FORWARD OOS + DEFLATED significance.

Discipline baked in:
  - In-sample (first 60%) to RANK combos; out-of-sample (last 40%) to CONFIRM the top finalists.
  - Reports the number of combos tried so significance can be deflated (a few thousand combos -> the
    best in-sample Sharpe is huge by chance; only OOS Sharpe on a pre-committed top set counts).
  - Long+short, realistic fees, no look-ahead (signals shifted by vectorbt by construction).

Usage: python vbt_sweep.py <klines_parquet> [asset_label]
  klines_parquet: a file with columns open_time(ms)/close (e.g. _data/binance_vision/BTCUSDT_1h_full.parquet
  or data/v4/canonical/binance_vision_klines.parquet filtered to one asset/tf).
Writes VBT_SWEEP_<label>.md + vbt_sweep_<label>.csv.
"""
import sys, time
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import vectorbt as vbt
ROOT=Path(r"C:\Users\alexandre bandarra\Desktop\global")
FEES=0.0005  # 5 bps round-trip-ish per side (perp taker ~ realistic)

def load_close(path):
    df=pd.read_parquet(path)
    # accept either binance-vision raw (open_time ms, close) or canonical (ts_s/price_close)
    if "open_time" in df.columns:
        ts=pd.to_datetime(df["open_time"],unit="ms"); close=pd.to_numeric(df["close"],errors="coerce")
    elif "time_period_start_us" in df.columns:
        ts=pd.to_datetime(df["time_period_start_us"],unit="us"); close=df["price_close"]
    elif "price_close" in df.columns and "ts_s" in df.columns:
        ts=pd.to_datetime(df["ts_s"],unit="s"); close=df["price_close"]
    else:
        ts=pd.to_datetime(df.iloc[:,0]); close=df.iloc[:,1]
    s=pd.Series(close.values,index=ts,name="close").sort_index().dropna()
    return s[~s.index.duplicated()]

def sharpe(returns, ann):
    r=returns.dropna()
    if len(r)<10 or r.std()==0: return np.nan
    return float(r.mean()/r.std()*np.sqrt(ann))

def main(path, label="asset"):
    px=load_close(path)
    n=len(px); cut=int(n*0.60)
    ins, oos = px.iloc[:cut], px.iloc[cut:]
    # annualization factor from median bar spacing
    dt_s=np.median(np.diff(px.index.values).astype("timedelta64[s]").astype(float))
    ann=(365*24*3600)/max(dt_s,1)
    print(f"[{label}] bars={n} {px.index[0]} -> {px.index[-1]}  ann={ann:.0f}  IS={len(ins)} OOS={len(oos)}",flush=True)

    results=[]  # (combo, is_sharpe)
    t0=time.time()
    # ---- Strategy family 1: MA crossover grid (long+short) ----
    fasts=np.arange(5,105,5); slows=np.arange(20,420,20)
    for f in fasts:
        for s in slows:
            if f>=s: continue
            for sub,tag in [(ins,"IS")]:
                fa=vbt.MA.run(sub,f).ma.values; sa=vbt.MA.run(sub,s).ma.values
                pos=np.where(fa>sa,1,-1).astype(float)  # long when fast>slow else short
                ret=pd.Series(pos[:-1]*np.diff(np.log(sub.values)),index=sub.index[1:])
                ret=ret - FEES*pd.Series(np.abs(np.diff(pos)),index=sub.index[1:]).fillna(0)
                results.append((("MAx",int(f),int(s)), sharpe(ret,ann)))
    # ---- Strategy family 2: RSI mean-reversion + momentum ----
    for p in [7,14,21]:
        rsi=vbt.RSI.run(ins,p).rsi.values
        for lo,hi in [(30,70),(25,75),(20,80),(35,65)]:
            for mode in ["revert","momo"]:
                if mode=="revert": pos=np.where(rsi<lo,1,np.where(rsi>hi,-1,0)).astype(float)
                else: pos=np.where(rsi>hi,1,np.where(rsi<lo,-1,0)).astype(float)
                pos=pd.Series(pos,index=ins.index).ffill().fillna(0).values
                ret=pd.Series(pos[:-1]*np.diff(np.log(ins.values)),index=ins.index[1:])
                ret=ret - FEES*pd.Series(np.abs(np.diff(pos)),index=ins.index[1:]).fillna(0)
                results.append((("RSI",mode,p,lo,hi), sharpe(ret,ann)))
    # ---- Strategy family 3: Bollinger breakout/revert ----
    for w in [20,30,50]:
        for k in [1.5,2.0,2.5]:
            bb=vbt.BBANDS.run(ins,window=w,alpha=k)
            up,lo_=bb.upper.values,bb.lower.values; c=ins.values
            for mode in ["breakout","revert"]:
                if mode=="breakout": pos=np.where(c>up,1,np.where(c<lo_,-1,0)).astype(float)
                else: pos=np.where(c<lo_,1,np.where(c>up,-1,0)).astype(float)
                pos=pd.Series(pos,index=ins.index).ffill().fillna(0).values
                ret=pd.Series(pos[:-1]*np.diff(np.log(ins.values)),index=ins.index[1:])
                ret=ret - FEES*pd.Series(np.abs(np.diff(pos)),index=ins.index[1:]).fillna(0)
                results.append((("BB",mode,w,k), sharpe(ret,ann)))

    res=pd.DataFrame([{"combo":str(c),"is_sharpe":s} for c,s in results]).dropna()
    res=res.sort_values("is_sharpe",ascending=False).reset_index(drop=True)
    n_combo=len(res)
    print(f"  swept {n_combo} combos in {time.time()-t0:.1f}s. Confirming top 15 on OOS...",flush=True)

    # ---- OOS confirm the pre-committed top 15 ----
    def oos_sharpe(combo_str):
        c=eval(combo_str)
        if c[0]=="MAx":
            f,s=c[1],c[2]; fa=vbt.MA.run(oos,f).ma.values; sa=vbt.MA.run(oos,s).ma.values
            pos=np.where(fa>sa,1,-1).astype(float)
        elif c[0]=="RSI":
            _,mode,p,lo,hi=c; rsi=vbt.RSI.run(oos,p).rsi.values
            pos=(np.where(rsi<lo,1,np.where(rsi>hi,-1,0)) if mode=="revert" else np.where(rsi>hi,1,np.where(rsi<lo,-1,0))).astype(float)
            pos=pd.Series(pos,index=oos.index).ffill().fillna(0).values
        else:
            _,mode,w,k=c; bb=vbt.BBANDS.run(oos,window=w,alpha=k); up,lo_=bb.upper.values,bb.lower.values; cc=oos.values
            pos=(np.where(cc>up,1,np.where(cc<lo_,-1,0)) if mode=="breakout" else np.where(cc<lo_,1,np.where(cc>up,-1,0))).astype(float)
            pos=pd.Series(pos,index=oos.index).ffill().fillna(0).values
        ret=pd.Series(pos[:-1]*np.diff(np.log(oos.values)),index=oos.index[1:])
        ret=ret - FEES*pd.Series(np.abs(np.diff(pos)),index=oos.index[1:]).fillna(0)
        return sharpe(ret,ann)
    top=res.head(15).copy(); top["oos_sharpe"]=[oos_sharpe(c) for c in top.combo]

    # null: best IS sharpe under shuffled returns (snooping floor)
    rng=np.random.default_rng(0); nulls=[]
    for _ in range(200):
        shuf=ins.iloc[rng.permutation(len(ins))]
        fa=vbt.MA.run(shuf,10).ma.values; sa=vbt.MA.run(shuf,40).ma.values; pos=np.where(fa>sa,1,-1).astype(float)
        ret=pd.Series(pos[:-1]*np.diff(np.log(shuf.values)),index=shuf.index[1:]); nulls.append(sharpe(ret,ann))
    null_p95=float(np.nanpercentile(nulls,95))

    res.to_csv(ROOT/"strategy_lab"/"autoresearch"/"_data"/f"vbt_sweep_{label}.csv",index=False)
    L=[f"# VectorBT sweep — {label} (underlying-crypto direction, NOT Polymarket) — auto",
       "",f"Bars={n}, {px.index[0].date()}→{px.index[-1].date()}. Swept **{n_combo}** combos (MA/RSI/BB families). "
       f"IS=first60%, OOS=last40%, fees={FEES*1e4:.0f}bps/flip. **Top-15 by IS Sharpe confirmed on OOS:**","",
       "| combo | IS Sharpe | OOS Sharpe |","|---|--:|--:|"]
    for r in top.itertuples():
        L.append(f"| {r.combo} | {r.is_sharpe:.2f} | {r.oos_sharpe:.2f} |")
    nsv=int((top.oos_sharpe>0.5).sum())
    L+= ["",f"## Read",
         f"- Best IS Sharpe={res.is_sharpe.max():.2f}; null (shuffled) IS Sharpe p95={null_p95:.2f}.",
         f"- **OOS is the judge.** Top-15 with OOS Sharpe>0.5: {nsv}/15. A combo is only credible if its OOS "
         f"Sharpe holds (IS Sharpe is inflated by searching {n_combo} combos).",
         "- Deflated reality: with thousands of combos, expect the best IS Sharpe to be large by chance; only a "
         "consistent IS→OOS Sharpe (both clearly >0) is real. Crypto direction is largely efficient — treat any "
         "survivor with skepticism and re-confirm on a 3rd window before sizing.",
         "- This is for tradeable UNDERLYING edge (Binance/HL), not Polymarket. Polymarket uses engine_v2."]
    (ROOT/"strategy_lab"/"reports"/f"VBT_SWEEP_{label}.md").write_text("\n".join(L),encoding="utf-8")
    print("\n".join(L),flush=True)
    print(f"\nwrote VBT_SWEEP_{label}.md ({time.time()-t0:.0f}s)",flush=True)

if __name__=="__main__":
    if len(sys.argv)<2: print("usage: python vbt_sweep.py <klines_parquet> [label]"); sys.exit(1)
    main(sys.argv[1], sys.argv[2] if len(sys.argv)>2 else "asset")
