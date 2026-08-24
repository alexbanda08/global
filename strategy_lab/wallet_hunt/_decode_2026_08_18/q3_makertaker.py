"""Q3 — MAKER vs TAKER, medido (nao inferido).

/trades?takerOnly=true devolve SO os fills em que a carteira cruzou o spread.
Metodo: puxar N paginas de takerOnly=true, definir a janela temporal coberta,
e comparar com TODOS os fills (activity TRADE) na MESMA janela.
   fracao_taker_usd = usd(takerOnly) / usd(todos os fills na janela)
Tambem: MAKER_REBATE (so acumula a makers) como confirmacao independente.
"""
import json, time, urllib.request, os
import pandas as pd, numpy as np
OUT=r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/wallet_hunt/_decode_2026_08_18"
W={"PBot-6":"0x21d0a97aac03917e752857a551bbe5103a00e8d7",
   "PBot-2":"0x095fd7cc9ddf7110586d1bda3974eccc52155f24",
   "PBot-3":"0x74a2b82f079e12bcc25cd0d479f17979fb62e32f",
   "PBot-5":"0x1b58d3de60d7f9e1aefdc9449e8d3733ea096f11",
   "b945":"0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68",
   "b27":"0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82"}
def get(u):
    r=urllib.request.Request(u,headers={"User-Agent":"curl/8"})
    return json.loads(urllib.request.urlopen(r,timeout=30).read())
print("="*106)
print("Q3 — fracao TAKER (cruza o spread) vs MAKER (ordem em repouso preenchida)")
print("="*106)
print(f"{'wallet':8s} {'n_taker':>8s} {'janela h':>9s} {'usd_taker':>11s} {'usd_total':>11s} {'%taker_usd':>11s} {'px_taker':>9s} {'px_todos':>9s} {'rebates$':>10s}")
for nm,w in W.items():
    tk=[]
    for off in range(0,3500,500):
        try: b=get(f"https://data-api.polymarket.com/trades?user={w}&takerOnly=true&limit=500&offset={off}")
        except Exception as e: print("  err",nm,e); b=[]
        if not b: break
        tk+=b
        if len(b)<500: break
        time.sleep(0.2)
    if not tk: print(f"{nm:8s} sem dados taker"); continue
    td=pd.DataFrame(tk)
    td=td[td.slug.str.contains("updown",na=False)]
    lo,hi=td.timestamp.min(),td.timestamp.max()
    td["usd"]=td.size_.astype(float)*td.price.astype(float) if "size_" in td else td["size"].astype(float)*td["price"].astype(float)
    f=pd.read_parquet(os.path.join(OUT,f"fills_{nm}.parquet"))
    win=f[(f.ts>=lo)&(f.ts<=hi)]
    try:
        rb=get(f"https://data-api.polymarket.com/activity?user={w}&type=MAKER_REBATE&limit=500")
        reb=sum(float(r.get("usdcSize") or 0) for r in rb)
    except Exception: reb=float("nan")
    tot=win.usd.sum()
    print(f"{nm:8s} {len(td):8d} {(hi-lo)/3600:8.1f}h {td.usd.sum():11,.0f} {tot:11,.0f} "
          f"{100*td.usd.sum()/tot if tot>0 else float('nan'):10.1f}% {td.usd.sum()/td['size'].astype(float).sum():9.4f} "
          f"{win.usd.sum()/win.sh.sum() if win.sh.sum()>0 else float('nan'):9.4f} {reb:10,.0f}")
    time.sleep(0.3)
print()
print("NOTA: usd_total vem do cache local (ate 08-13); se a janela taker for mais recente que o cache,")
print("      a linha fica sem denominador valido — ver 'janela h' e usd_total==0.")
