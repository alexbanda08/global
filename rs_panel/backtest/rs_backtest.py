#!/usr/bin/env python3
"""ALT/BTC Relative-Strength — cross-sectional backtest (STANDALONE).

Turns the RS-panel concept into systematic strategies and backtests them on
Binance daily spot klines. NOT connected to any live system / HL strategy.

Tests 3 strategy forms × signal sweep × momentum|contrarian × daily|weekly,
net of perp costs, causal (signal_t -> return t..t+1), with a train/test split.

Honesty notes (printed in report):
 - Survivorship: only currently-listed coins -> upward bias (esp. long-only).
 - Multiple testing: we scan a grid; the BEST in-sample is optimistic. Trust the
   OOS (test-split) column + cost sensitivity, not the in-sample max.
 - Funding/borrow ignored (v1); costs are taker+slippage round-trip bps on turnover.
"""
import json, math, os, time, urllib.request, urllib.error, sys
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "_klines_1d.parquet")
API = "https://api.binance.com/api/v3/klines"
LEN = 200
COINS = ["BTC","ETH","SOL","BNB","XRP","DOGE","ADA","AVAX","LINK","DOT","LTC","BCH",
 "TRX","NEAR","APT","SUI","ARB","OP","INJ","TIA","SEI","ATOM","FIL","RUNE","AAVE",
 "UNI","ENA","WLD","ORDI","LDO","STX","CRV","JUP","TAO","FET","RENDER","PYTH"]

def fetch_daily(sym, limit=1000):
    url=f"{API}?symbol={sym}USDT&interval=1d&limit={limit}"
    for a in range(3):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"rs-bt/1.0"})
            with urllib.request.urlopen(req,timeout=20) as r: rows=json.load(r)
            return pd.Series({pd.Timestamp(int(k[0]),unit="ms"):float(k[4]) for k in rows})
        except urllib.error.HTTPError as e:
            if e.code==400: return None
            time.sleep(1+a)
        except Exception: time.sleep(1+a)
    return None

def load_panel():
    if os.path.exists(CACHE):
        df=pd.read_parquet(CACHE)
        print(f"loaded cache {CACHE}  {df.shape}")
        return df
    cols={}
    for c in COINS:
        s=fetch_daily(c); time.sleep(0.08)
        if s is None or len(s)<LEN+30: print(f"  skip {c}"); continue
        cols[c]=s; print(f"  {c}: {len(s)} bars")
    df=pd.DataFrame(cols).sort_index()
    df.to_parquet(CACHE)
    print(f"cached {CACHE}  {df.shape}")
    return df

def sharpe(r, ppy=365):
    r=r.dropna()
    if r.std()==0 or len(r)<10: return 0.0
    return r.mean()/r.std()*math.sqrt(ppy)

def maxdd(eq):
    return float((eq/eq.cummax()-1).min())

def ann_ret(r, ppy=365):
    r=r.dropna()
    return float((1+r).prod()**(ppy/max(len(r),1))-1)

def metrics(r, ppy=365):
    r=r.fillna(0.0); eq=(1+r).cumprod()
    return dict(ann=ann_ret(r,ppy), shp=sharpe(r,ppy), dd=maxdd(eq),
                hit=float((r>0).mean()), n=int((r!=0).sum()))

def run():
    df=load_panel()
    btc=df["BTC"]; alts=[c for c in df.columns if c!="BTC"]
    ratio=df[alts].div(btc,axis=0)                       # alt/BTC
    r_usd=df[alts].pct_change().shift(-1)                # fwd USD return t->t+1
    r_rel=ratio.pct_change().shift(-1)                   # fwd alt/BTC return (long alt/short BTC)

    # ---- signals (causal: use values at t to trade t->t+1) ----
    sma=ratio.rolling(LEN).mean(); ema=ratio.ewm(span=LEN,adjust=False).mean()
    sig={}
    for L in (7,14,30,60,90): sig[f"mom{L}"]=ratio.pct_change(L)
    sig["score2"]=(ratio>sma).astype(int)+(ratio>ema).astype(int)   # daily 0-2 RS score
    sig["abv200"]=(ratio>sma).astype(float)

    dates=df.index
    split=dates[int(len(dates)*0.70)]                    # 70/30 time split

    COST_BPS=8.0    # round-trip taker+slippage per name flip (HL perp ~realistic)
    def cost(weights_prev, weights_now):
        # turnover = sum |Δweight|; cost applied as bps on turnover
        idx=weights_prev.index.union(weights_now.index)
        wp=weights_prev.reindex(idx).fillna(0); wn=weights_now.reindex(idx).fillna(0)
        return (wp-wn).abs().sum()*COST_BPS/1e4

    def backtest(signame, form, K, contrarian, weekly):
        s=sig[signame]
        rebal = (np.arange(len(dates))%7==0) if weekly else np.ones(len(dates),bool)
        prev=pd.Series(dtype=float); rets=[]; idxs=[]; turn=[]
        cur=pd.Series(dtype=float)
        for i,dt in enumerate(dates):
            if i>=len(dates)-1: break
            if rebal[i]:
                row=s.loc[dt].dropna()
                # need enough names with a defined signal + a valid MA window
                row=row[np.isfinite(row.values)]
                if len(row)< max(2*K,6): cur=pd.Series(dtype=float)
                else:
                    rk=row.sort_values(ascending=contrarian)   # contrarian: long the weak
                    top=rk.index[-K:]; bot=rk.index[:K]
                    if form=="ls":      cur=pd.concat([pd.Series(1/K,top),pd.Series(-1/K,bot)])
                    elif form=="vsbtc": cur=pd.Series(1/K,top)        # uses r_rel (already short BTC)
                    else:               cur=pd.Series(1/K,top)        # long-only, uses r_usd
            ret_src = r_rel if form=="vsbtc" else r_usd
            day = (cur*ret_src.loc[dt].reindex(cur.index)).sum() if len(cur) else 0.0
            c = cost(prev,cur) if rebal[i] else 0.0
            rets.append(day-c); idxs.append(dt); turn.append((prev.reindex(cur.index.union(prev.index)).fillna(0)-cur.reindex(cur.index.union(prev.index)).fillna(0)).abs().sum() if rebal[i] else 0.0)
            prev=cur
        r=pd.Series(rets,index=idxs)
        tr=pd.Series(turn,index=idxs)
        full=metrics(r); tr_m=metrics(r[r.index<split]); te_m=metrics(r[r.index>=split])
        return dict(sig=signame,form=form,K=K,side=("contra" if contrarian else "mom"),
                    freq=("wk" if weekly else "d"),
                    shp=full["shp"], ann=full["ann"], dd=full["dd"],
                    shp_tr=tr_m["shp"], shp_te=te_m["shp"], ann_te=te_m["ann"],
                    turn=float(tr.mean()), r=r)

    results=[]
    forms=["ls","vsbtc","long"]
    Ks=[3,5,8]
    for form in forms:
        for signame in ["mom14","mom30","mom60","mom90","score2"]:
            for contrarian in (False,True):
                for weekly in (False,True):
                    for K in Ks:
                        try: results.append(backtest(signame,form,K,contrarian,weekly))
                        except Exception as e: pass
    res=pd.DataFrame([{k:v for k,v in r.items() if k!="r"} for r in results])
    res=res.sort_values("shp_te",ascending=False)
    return df, res, results

def main():
    df, res, results = run()
    span=f"{df.index.min().date()} -> {df.index.max().date()}  ({len(df)} days, {df.shape[1]} coins)"
    # report
    top=res.head(15)
    lines=[]
    lines.append("# ALT/BTC Relative-Strength — Backtest Results\n")
    lines.append(f"_Binance daily spot, {span}. Causal (signal_t -> return t..t+1). "
                 f"Cost {8.0}bps round-trip on turnover. 70/30 time split. "
                 f"Standalone — not linked to any live/HL strategy._\n")
    lines.append("## Strategy forms")
    lines.append("- **ls** = long top-K / short bottom-K perps, dollar-neutral (RS factor, market-neutral)")
    lines.append("- **vsbtc** = long top-K alts, funded short BTC (return measured in BTC terms)")
    lines.append("- **long** = long-only top-K alts (carries market beta)\n")
    lines.append("## Top 15 configs by OUT-OF-SAMPLE Sharpe (test split)\n")
    cols=["form","sig","side","freq","K","shp_tr","shp_te","ann_te","dd","turn"]
    hdr="| "+" | ".join(cols)+" |"; sep="|"+"|".join(["---"]*len(cols))+"|"
    lines.append(hdr); lines.append(sep)
    for _,r in top.iterrows():
        lines.append("| "+" | ".join(
            (f"{r[c]:.2f}" if isinstance(r[c],float) else str(r[c])) for c in cols)+" |")
    # best overall verdict
    best=res.iloc[0]
    lines.append("\n## Read")
    lines.append(f"- Best OOS config: **{best['form']} / {best['sig']} / {best['side']} / "
                 f"{best['freq']} / K={best['K']}** — train Sharpe {best['shp_tr']:.2f}, "
                 f"**test Sharpe {best['shp_te']:.2f}**, test ann {best['ann_te']*100:.1f}%, maxDD {best['dd']*100:.0f}%.")
    surv = (res['shp_te']>0.5).mean()
    lines.append(f"- Of {len(res)} configs, {(res['shp_te']>0).mean()*100:.0f}% have positive OOS Sharpe, "
                 f"{surv*100:.0f}% > 0.5. (If ~half are >0 and the in-sample max barely survives OOS, the 'edge' is mostly noise.)")
    lines.append("- ⚠️ Survivorship bias: only currently-listed coins — inflates **long-only** most, **ls** least.")
    lines.append("- ⚠️ Multiple testing: this is a grid scan; the top row is the luckiest. Pre-register one config "
                 "and forward/OOS test it before trusting. Next step: DSR/CPCV (ml4t) on the chosen config.")
    open(os.path.join(HERE,"RS_BACKTEST_RESULTS.md"),"w",encoding="utf-8").write("\n".join(lines))
    # console digest
    print("\n=== span:",span)
    print("=== TOP 12 by OOS Sharpe ===")
    print(res.head(12)[["form","sig","side","freq","K","shp_tr","shp_te","ann_te","dd","turn"]].to_string(index=False))
    print(f"\nconfigs positive OOS: {(res['shp_te']>0).mean()*100:.0f}%  | >0.5: {(res['shp_te']>0.5).mean()*100:.0f}%")
    print("wrote RS_BACKTEST_RESULTS.md")

if __name__=="__main__":
    main()
