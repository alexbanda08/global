"""ROI SEM VIES: amostra aleatoria de janelas, fills puxados COMPLETOS (sem o dedup destrutivo).

O cache tinha compras truncadas e redencoes completas -> ROI inflacionado.
Aqui puxa-se janela a janela com start/end, sem colapsar linhas identicas.
"""
import json, urllib.request, time, os, sys
import pandas as pd, numpy as np
OUT=r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/wallet_hunt/_decode_2026_08_18"
W={"PBot-6":"0x21d0a97aac03917e752857a551bbe5103a00e8d7",
   "b945":"0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68",
   "PBot-5":"0x1b58d3de60d7f9e1aefdc9449e8d3733ea096f11"}
NSAMP=int(sys.argv[1]) if len(sys.argv)>1 else 200
def get(u):
    for a in range(4):
        try:
            r=urllib.request.Request(u,headers={"User-Agent":"curl/8"})
            return json.loads(urllib.request.urlopen(r,timeout=30).read())
        except Exception as e:
            time.sleep(1.5*(a+1))
    return []
def pull(w,typ,t0,t1):
    o=[]
    for off in range(0,4000,500):
        b=get(f"https://data-api.polymarket.com/activity?user={w}&type={typ}&limit=500&offset={off}&start={t0}&end={t1}")
        if not b: break
        o+=b
        if len(b)<500: break
        time.sleep(0.12)
    return o
rng=np.random.default_rng(11)
print("="*104)
print(f"ROI RE-MEDIDO com fills completos — amostra de {NSAMP} janelas por carteira")
print("="*104)
for nm,w in W.items():
    f=pd.read_parquet(os.path.join(OUT,f"fills_{nm}.parquet"))
    r=pd.read_parquet(os.path.join(OUT,f"redeems_{nm}.parquet"))
    tend=r.ts.max()-3600; t0=f.ts.min()+86400
    cand=sorted({(s,int(sl),int(wl)) for s,sl,wl in zip(f.slug,f.slot,f.wl) if sl>=t0 and sl+wl<tend})
    pick=[cand[i] for i in rng.choice(len(cand),min(NSAMP,len(cand)),replace=False)]
    rows=[]
    for i,(slug,slot,wl) in enumerate(pick):
        tr=pull(w,"TRADE",slot-4000,slot+wl+60)
        tr=[t for t in tr if t.get("slug")==slug and t.get("side")=="BUY"]
        rd=pull(w,"REDEEM",slot+wl,slot+wl+90000)
        rd=[x for x in rd if x.get("slug")==slug]
        if not tr: continue
        buy=sum(float(t["usdcSize"]) for t in tr)
        sh={"Up":0.0,"Down":0.0}
        for t in tr:
            if t.get("outcome") in sh: sh[t["outcome"]]+=float(t["size"])
        red=sum(float(x.get("usdcSize") or 0) for x in rd)
        winrows=[x for x in rd if float(x.get("usdcSize") or 0)>0]
        winner=winrows[0].get("outcome") if winrows else None
        rows.append(dict(slug=slug,buy=buy,red=red,up=sh["Up"],dn=sh["Down"],winner=winner,
                         redsh=sum(float(x.get("size") or 0) for x in winrows)))
        if (i+1)%50==0: print(f"   {nm}: {i+1}/{len(pick)}",flush=True)
    d=pd.DataFrame(rows)
    d["heldwin"]=np.where(d.winner.eq("Up"),d.up,np.where(d.winner.eq("Down"),d.dn,0.0))
    d["pnl"]=d.red-d.buy
    comp=d.heldwin.sum()/max(d.redsh.sum(),1e-9)
    n=len(d); rngb=np.random.default_rng(3)
    B=[(d.pnl.values[i].sum()/d.buy.values[i].sum()) for i in (rngb.integers(0,n,n) for _ in range(2000))]
    lo,hi=np.percentile(B,[2.5,97.5])
    d.to_parquet(os.path.join(OUT,f"trueroi_{nm}.parquet"))
    print(f"\n{nm}: n={n} janelas | buy ${d.buy.sum():,.0f} | red ${d.red.sum():,.0f} | "
          f"PnL ${d.pnl.sum():,.0f} | ROI {100*d.pnl.sum()/d.buy.sum():+.2f}% "
          f"[CI95 {100*lo:+.2f}%, {100*hi:+.2f}%]")
    print(f"   completude do lado vencedor (detido/redimido) = {comp:.4f}  (1.00 = fills completos)")
    print(f"   janelas lucrativas {100*(d.pnl>0).mean():.1f}% | capital/janela mediano ${d.buy.median():,.0f}\n")
