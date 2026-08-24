import pandas as pd, numpy as np, os
OUT=r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/wallet_hunt/_decode_2026_08_18"
nm="PBot-6"
f=pd.read_parquet(os.path.join(OUT,f"fills_{nm}.parquet"))
r=pd.read_parquet(os.path.join(OUT,f"redeems_{nm}.parquet"))
t0=f.ts.min()+86400; tend=r.ts.max()-3600
f=f[(f.slot>=t0)&(f.slot+f.wl<tend)]
slugs=set(f.slug)
print(f"janelas na amostra de trades: {len(slugs):,}")
rr=r[r.slug.isin(slugs)]
print(f"linhas de REDEEM nessas janelas: {len(rr):,}  (usd>0: {(rr.usd>0).sum():,} | usd==0: {(rr.usd<=0).sum():,})")
print(f"janelas COM alguma linha redeem: {rr.slug.nunique():,}")
print(f"janelas COM linha usd>0:         {rr[rr.usd>0].slug.nunique():,}")
print(f"janelas SEM qualquer redeem:     {len(slugs)-rr.slug.nunique():,}")
# das janelas com redeem usd>0, quantas tem 2 linhas usd>0 (os dois lados!?)
g=rr[rr.usd>0].groupby("slug").size()
print(f"  dessas, com 2+ linhas usd>0: {(g>1).sum():,}")
# quanto USD esta em janelas sem trade correspondente
print(f"\nred_usd em janelas DA amostra: {rr.usd.sum():,.0f}")
print(f"red_usd TOTAL do ficheiro:      {r.usd.sum():,.0f}")
# comparar shares: posicao vencedora inferida vs shares redimidas
pos=f.groupby(["slug","outcome"]).sh.sum().unstack(fill_value=0.0)
for c in ("Up","Down"):
    if c not in pos: pos[c]=0.0
w=rr[rr.usd>0].drop_duplicates("slug").set_index("slug")
j=pos.join(w[["outcome","sh","usd"]].rename(columns={"outcome":"winner","sh":"red_sh","usd":"red_usd"}),how="left")
j["held_win"]=np.where(j.winner.eq("Up"),j.Up,np.where(j.winner.eq("Down"),j.Down,0.0))
k=j[j.winner.notna()]
print(f"\njanelas com vencedor: {len(k):,}")
print(f"  shares detidas do lado vencedor (da amostra de trades): {k.held_win.sum():,.0f}")
print(f"  shares efectivamente redimidas:                          {k.red_sh.sum():,.0f}")
print(f"  racio redimido/detido: {k.red_sh.sum()/k.held_win.sum():.3f}")
d=(k.red_sh-k.held_win)
print(f"  janelas onde redimiu MAIS do que comprou na amostra: {(d>1).sum():,}  (excesso total {d[d>1].sum():,.0f} sh)")
print(f"  janelas onde redimiu MENOS: {(d<-1).sum():,} (defice {d[d<-1].sum():,.0f} sh)")
print()
print("top 5 janelas por excesso:")
print(k.assign(exc=d).nlargest(5,"exc")[["Up","Down","winner","red_sh","held_win","exc"]].to_string())
