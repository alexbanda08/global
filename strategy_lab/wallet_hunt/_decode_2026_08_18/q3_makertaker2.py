"""Q3 corrigido — taker share medido no MESMO endpoint e na MESMA janela temporal.

/trades?takerOnly=true  -> so os fills em que a carteira CRUZOU o spread
/trades                 -> todos os fills
Ambos com a mesma semantica de linha. Recorta-se a janela coberta pela pagina
'todos' (a mais curta) e conta-se o taker dentro dela.
"""
import json, time, urllib.request
import pandas as pd, numpy as np
W={"PBot-6":"0x21d0a97aac03917e752857a551bbe5103a00e8d7",
   "PBot-2":"0x095fd7cc9ddf7110586d1bda3974eccc52155f24",
   "PBot-3":"0x74a2b82f079e12bcc25cd0d479f17979fb62e32f",
   "PBot-5":"0x1b58d3de60d7f9e1aefdc9449e8d3733ea096f11",
   "b945":"0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68",
   "b27":"0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82"}
def get(u):
    r=urllib.request.Request(u,headers={"User-Agent":"curl/8"})
    return json.loads(urllib.request.urlopen(r,timeout=30).read())
def pull(w, taker, pages=7):
    o=[]
    for off in range(0,pages*500,500):
        u=f"https://data-api.polymarket.com/trades?user={w}&limit=500&offset={off}"+("&takerOnly=true" if taker else "")
        try: b=get(u)
        except Exception as e: print("   err",e); break
        if not b: break
        o+=b
        if len(b)<500: break
        time.sleep(0.2)
    d=pd.DataFrame(o)
    if len(d)==0: return d
    d=d[d.slug.astype(str).str.contains("updown",na=False)].copy()
    d["sz"]=d["size"].astype(float); d["pr"]=d["price"].astype(float); d["usd"]=d.sz*d.pr
    d["k"]=d.transactionHash.astype(str)+"|"+d.asset.astype(str)+"|"+d.sz.round(4).astype(str)
    return d
print("="*112)
print("Q3 — TAKER SHARE, mesma fonte (/trades) e mesma janela temporal")
print("="*112)
print(f"{'wallet':8s} {'janela':>8s} {'n_tot':>7s} {'n_tk':>6s} {'%taker_n':>9s} {'%taker_usd':>11s} {'px_taker':>9s} {'px_maker':>9s} {'diff':>7s}")
for nm,w in W.items():
    a=pull(w,False); t=pull(w,True)
    if len(a)==0 or len(t)==0: print(f"{nm:8s} sem dados"); continue
    lo,hi=a.timestamp.min(),a.timestamp.max()
    tt=t[(t.timestamp>=lo)&(t.timestamp<=hi)]
    tks=set(tt.k)
    mk=a[~a.k.isin(tks)]
    tk=a[a.k.isin(tks)]
    nt=len(a); ntk=len(tk)
    pxt=tk.usd.sum()/tk.sz.sum() if tk.sz.sum()>0 else float("nan")
    pxm=mk.usd.sum()/mk.sz.sum() if mk.sz.sum()>0 else float("nan")
    print(f"{nm:8s} {(hi-lo)/3600:7.1f}h {nt:7d} {ntk:6d} {100*ntk/nt:8.1f}% {100*tk.usd.sum()/a.usd.sum():10.1f}% "
          f"{pxt:9.4f} {pxm:9.4f} {pxt-pxm:+7.4f}")
    time.sleep(0.3)
print()
print("interpretacao: px_taker >> px_maker  =>  o leg TAKER e a perna CARA (completar par),")
print("               px_taker << px_maker  =>  o leg TAKER e a perna BARATA (varrer descontos).")
