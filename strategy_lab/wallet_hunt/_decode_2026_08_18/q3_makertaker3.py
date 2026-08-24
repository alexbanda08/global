"""Q3 — taker share pelo metodo das TAXAS (o do relatorio, agora para as 6 carteiras).

takerOnly=true  -> N fills taker num intervalo T_tk  => taxa taker = N/T_tk
takerOnly=false -> N fills (todos)  num intervalo T_all => taxa total = N/T_all
   fracao_taker = (N/T_tk) / (N/T_all) = T_all / T_tk
Robusto a paginacao: so precisa dos intervalos cobertos pelo mesmo N.
"""
import json, time, urllib.request
import pandas as pd
W={"PBot-6":"0x21d0a97aac03917e752857a551bbe5103a00e8d7",
   "PBot-2":"0x095fd7cc9ddf7110586d1bda3974eccc52155f24",
   "PBot-3":"0x74a2b82f079e12bcc25cd0d479f17979fb62e32f",
   "PBot-5":"0x1b58d3de60d7f9e1aefdc9449e8d3733ea096f11",
   "b945":"0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68",
   "b27":"0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82"}
def get(u):
    r=urllib.request.Request(u,headers={"User-Agent":"curl/8"})
    return json.loads(urllib.request.urlopen(r,timeout=30).read())
print("="*118)
print("Q3 — MAKER vs TAKER pelas TAXAS (mesmo N de fills, intervalos comparados)")
print("="*118)
print(f"{'wallet':8s} | {'N':>5s} {'T_taker':>9s} {'T_todos':>9s} {'%TAKER':>8s} {'%MAKER':>8s} | {'px_taker':>9s} {'px_todos':>9s} {'diff':>8s} | {'lado_taker'}")
for nm,w in W.items():
    rows={}
    for flag in ("true","false"):
        try: b=get(f"https://data-api.polymarket.com/trades?user={w}&takerOnly={flag}&limit=500")
        except Exception as e: print(f"{nm} err {e}"); b=[]
        d=pd.DataFrame(b)
        if len(d): d=d[d.slug.astype(str).str.contains("updown",na=False)].copy()
        rows[flag]=d
    tk,al=rows["true"],rows["false"]
    if len(tk)<50 or len(al)<50: print(f"{nm:8s} | amostra insuficiente tk={len(tk)} all={len(al)}"); continue
    N=min(len(tk),len(al))
    tk=tk.sort_values("timestamp",ascending=False).head(N); al=al.sort_values("timestamp",ascending=False).head(N)
    Ttk=(tk.timestamp.max()-tk.timestamp.min())/3600; Tal=(al.timestamp.max()-al.timestamp.min())/3600
    frac=Tal/Ttk if Ttk>0 else float("nan")
    for d in (tk,al):
        d["sz"]=d["size"].astype(float); d["usd"]=d.sz*d["price"].astype(float)
    pxt=tk.usd.sum()/tk.sz.sum(); pxa=al.usd.sum()/al.sz.sum()
    side="CARA (completa par)" if pxt>pxa+0.02 else ("BARATA (varre desconto)" if pxt<pxa-0.02 else "~igual")
    print(f"{nm:8s} | {N:5d} {Ttk:8.1f}h {Tal:8.1f}h {100*frac:7.1f}% {100*(1-frac):7.1f}% | {pxt:9.4f} {pxa:9.4f} {pxt-pxa:+8.4f} | {side}")
    time.sleep(0.4)
