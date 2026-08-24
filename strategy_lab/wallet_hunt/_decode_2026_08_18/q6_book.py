"""Q3+Q5 com LIVRO REAL: fills das carteiras (14-18 Ago) x ladder_tick da Ireland (5s).

Para cada fill determina-se, com o livro nesse instante:
  maker  : px <= best_bid  (a ordem estava em repouso e foi atingida)
  taker  : px >= best_ask  (cruzou o spread)
  dentro : bid < px < ask  (dentro do spread — maker que melhorou o bid)
E o movimento POSTERIOR do mid desse lado a +30s e +60s (selecao adversa real).
"""
import json, re, os
import pandas as pd, numpy as np
OUT=r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/wallet_hunt/_decode_2026_08_18"
SLUG=re.compile(r"^(btc|eth)-updown-(5m|15m)-(\d+)$")
NAMES=["PBot-6","PBot-2","PBot-3","PBot-5"]
tk=pd.read_parquet(os.path.join(OUT,"ticks5s.parquet"))
tk["mid_up"]=(tk.bbu+tk.bau)/2; tk["mid_dn"]=(tk.bbd+tk.bad)/2
T={s:g.sort_values("sec5").reset_index(drop=True) for s,g in tk.groupby("slug")}
print(f"livro: {len(tk):,} snapshots 5s / {len(T):,} slugs (14-18 Ago, Ireland ladder_tick)\n")

rows=[]
for nm in NAMES:
    p=os.path.join(OUT,f"recent_TRADE_{nm}.json")
    if not os.path.exists(p): continue
    for t in json.load(open(p)):
        m=SLUG.match(t.get("slug") or "")
        if not m or t.get("side")!="BUY" or t.get("outcome") not in ("Up","Down"): continue
        rows.append((nm,t["slug"],t["timestamp"],int(m.group(3)),m.group(2),t["outcome"],
                     float(t["size"]),float(t["usdcSize"]),float(t["price"])))
F=pd.DataFrame(rows,columns=["wl","slug","ts","slot","tf","outcome","sh","usd","px"])
F["wlen"]=F.tf.map({"5m":300,"15m":900}); F["dt"]=F.ts-F.slot; F["frac"]=F.dt/F.wlen
print("fills recentes por carteira:", F.wl.value_counts().to_dict())
F=F[F.slug.isin(T)]
print(f"fills com livro correspondente: {len(F):,}\n")

def lookup(slug, sec, col):
    g=T[slug]; i=np.searchsorted(g.sec5.values, sec, "right")-1
    return g[col].values[i] if 0<=i<len(g) else np.nan
recs=[]
for slug,g in F.groupby("slug"):
    b=T[slug]; sec=b.sec5.values
    i0=np.searchsorted(sec, (g.ts.values//5)*5, "right")-1
    i30=np.searchsorted(sec, (g.ts.values//5)*5+30, "right")-1
    i60=np.searchsorted(sec, (g.ts.values//5)*5+60, "right")-1
    ok=(i0>=0)&(i60>=0)&(i60<len(sec))
    s=g[ok].copy(); i0,i30,i60=i0[ok],i30[ok],i60[ok]
    up=s.outcome.eq("Up").values
    s["bid"]=np.where(up,b.bbu.values[i0],b.bbd.values[i0])
    s["ask"]=np.where(up,b.bau.values[i0],b.bad.values[i0])
    s["mid"]=np.where(up,b.mid_up.values[i0],b.mid_dn.values[i0])
    s["mid30"]=np.where(up,b.mid_up.values[i30],b.mid_dn.values[i30])
    s["mid60"]=np.where(up,b.mid_up.values[i60],b.mid_dn.values[i60])
    recs.append(s)
X=pd.concat(recs,ignore_index=True).dropna(subset=["bid","ask","mid60"])
X["cls"]=np.where(X.px<=X.bid+1e-9,"maker",np.where(X.px>=X.ask-1e-9,"taker","dentro"))
X["adv30"]=(X.mid30-X.mid)*100; X["adv60"]=(X.mid60-X.mid)*100
X["vs_mid"]=(X.mid-X.px)*100
X.to_parquet(os.path.join(OUT,"book_join.parquet"))
print("="*112)
print("Q3(livro) — CLASSIFICACAO DE CADA FILL contra o melhor bid/ask no instante")
print("="*112)
print(f"{'wallet':8s} {'n':>7s} | {'%MAKER':>8s} {'%dentro':>8s} {'%TAKER':>8s} | {'px-mid maker':>13s} {'px-mid taker':>13s} | {'spread medio':>13s}")
for nm in NAMES:
    s=X[X.wl==nm]
    if len(s)<100: continue
    c=s.cls.value_counts(normalize=True)
    mk=s[s.cls=="maker"]; tkr=s[s.cls=="taker"]
    print(f"{nm:8s} {len(s):7,d} | {100*c.get('maker',0):7.1f}% {100*c.get('dentro',0):7.1f}% {100*c.get('taker',0):7.1f}% | "
          f"{-mk.vs_mid.mean():12.2f}c {-tkr.vs_mid.mean():12.2f}c | {100*(s.ask-s.bid).mean():12.2f}c")
print()
print("="*112)
print("Q5(livro) — SELECAO ADVERSA REAL: variacao do MID do lado comprado apos o fill (centavos)")
print("="*112)
print(f"{'wallet':8s} {'n':>7s} | {'+30s':>8s} {'+60s':>8s} {'se60':>6s} {'t':>7s} | {'maker +60s':>11s} {'taker +60s':>11s}")
for nm in NAMES:
    s=X[X.wl==nm]
    if len(s)<100: continue
    se=s.adv60.std()/np.sqrt(len(s))
    mk=s[s.cls=="maker"]; tkr=s[s.cls=="taker"]
    print(f"{nm:8s} {len(s):7,d} | {s.adv30.mean():+7.2f}c {s.adv60.mean():+7.2f}c {se:5.2f}c {s.adv60.mean()/se:6.1f} | "
          f"{mk.adv60.mean():+10.2f}c {tkr.adv60.mean() if len(tkr)>30 else float('nan'):+10.2f}c")
print()
print("Q5(livro) por FASE — adv60 (centavos)")
PH=[(-1e9,-120,"pre<-2m"),(-120,0,"pre-2..0"),(0,.25,"0-25%"),(.25,.5,"25-50%"),(.5,.75,"50-75%"),(.75,1.,"75-100%")]
print(f"{'wallet':8s} |"+"".join(f"{p[2]:>13s}" for p in PH))
for nm in NAMES:
    s=X[X.wl==nm]; c=[]
    for lo,hi,_ in PH:
        z=s[(s.dt>=lo)&(s.dt<hi)] if hi<=0 else s[(s.frac>=lo)&(s.frac<hi)&(s.dt>=0)]
        c.append(f"{z.adv60.mean():+.2f}c/{len(z)}" if len(z)>150 else "     -      ")
    print(f"{nm:8s} |"+"".join(f"{x:>13s}" for x in c))
print()
print("Q3(livro) — %MAKER por FASE")
print(f"{'wallet':8s} |"+"".join(f"{p[2]:>13s}" for p in PH))
for nm in NAMES:
    s=X[X.wl==nm]; c=[]
    for lo,hi,_ in PH:
        z=s[(s.dt>=lo)&(s.dt<hi)] if hi<=0 else s[(s.frac>=lo)&(s.frac<hi)&(s.dt>=0)]
        c.append(f"{100*(z.cls=='maker').mean():.0f}%/{len(z)}" if len(z)>150 else "     -      ")
    print(f"{nm:8s} |"+"".join(f"{x:>13s}" for x in c))
