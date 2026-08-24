"""Q2(direcao)+Q5(selecao adversa) — estimador LIMPO, fita POR TOKEN.

Porque os 2 anteriores estavam errados: juntar prints de Up e de Down numa serie P(Up)
mistura bid_up (compras de Up) com ask_up (=1-bid_dn, compras de Down). O 'movimento'
media entao a COMPOSICAO da fita, nao o preco -> espelhava o desconto de cada carteira.

Aqui a fita e por (slug, outcome): so compras do MESMO token, todas bids do mesmo token.
Exclui-se sempre a propria carteira. Unidades: centavos do preco DESSE token.
  move_pre  = fita[t-45,t)  - fita[t-120,t-45)
  move_post = fita(t,t+60]  - fita[t-60,t)
Positivo = o lado que compraram SUBIU.
"""
import pandas as pd, numpy as np, os
OUT=r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/wallet_hunt/_decode_2026_08_18"
NAMES=["PBot-6","PBot-2","PBot-3","PBot-5","b945","b27"]
d=[]
for nm in NAMES:
    f=pd.read_parquet(os.path.join(OUT,f"fills_{nm}.parquet")); f["wl_name"]=nm
    d.append(f[["wl_name","slug","ts","dt","frac","outcome","px","sh","usd","tf","coin"]])
A=pd.concat(d,ignore_index=True)
WIDX={nm:i for i,nm in enumerate(NAMES)}; A["wi"]=A.wl_name.map(WIDX)

out=[]
for (slug,oc), g in A.groupby(["slug","outcome"], sort=False):
    if len(g)<12: continue
    g=g.sort_values("ts"); ts=g.ts.values.astype(np.int64); px=g.px.values; wi=g.wi.values; n=len(ts)
    cs=np.concatenate([[0.0],np.cumsum(px)]); cn=np.arange(n+1,dtype=float)
    csw=np.zeros((6,n+1)); cnw=np.zeros((6,n+1))
    for k in range(6):
        m=(wi==k).astype(float); csw[k,1:]=np.cumsum(px*m); cnw[k,1:]=np.cumsum(m)
    def mean_seg(a,b):
        s=np.empty(n); c=np.empty(n)
        for k in range(6):
            m=wi==k
            if not m.any(): continue
            s[m]=cs[b[m]]-cs[a[m]]-(csw[k,b[m]]-csw[k,a[m]])
            c[m]=cn[b[m]]-cn[a[m]]-(cnw[k,b[m]]-cnw[k,a[m]])
        with np.errstate(invalid="ignore",divide="ignore"):
            return np.where(c>0,s/np.maximum(c,1),np.nan), c
    iA=np.searchsorted(ts,ts-120,"left"); iB=np.searchsorted(ts,ts-45,"left")
    iC=np.searchsorted(ts,ts-60,"left");  iL=np.searchsorted(ts,ts,"left")
    iR=np.searchsorted(ts,ts,"right");    iP=np.searchsorted(ts,ts+60,"right")
    p_old,c1=mean_seg(iA,iB); p_now,c2=mean_seg(iB,iL)
    p_bef,c3=mean_seg(iC,iL); p_aft,c4=mean_seg(iR,iP)
    ok=(c1>=2)&(c2>=2)&(c3>=2)&(c4>=2)
    if not ok.any(): continue
    s=g.iloc[ok].copy()
    s["move_pre"]=(p_now[ok]-p_old[ok])*100
    s["move_post"]=(p_aft[ok]-p_bef[ok])*100
    s["disc"]=(p_bef[ok]-s.px.values)*100          # compra abaixo da fita do MESMO token
    out.append(s)
T=pd.concat(out,ignore_index=True); T.to_parquet(os.path.join(OUT,"tape3.parquet"))
bpre,bpost=T.move_pre.mean(),T.move_post.mean()
print(f"n com contexto limpo (fita do MESMO token, outras carteiras): {len(T):,}")
print(f"BASE da fita: move_pre {bpre:+.2f}c  move_post {bpost:+.2f}c\n")
print("="*108)
print(f"{'wallet':8s} {'n':>7s} | {'move_pre':>9s} {'vs base':>8s} {'%cai':>6s} | {'move_post':>10s} {'vs base':>8s} {'se':>6s} {'t':>7s} | {'desconto':>9s}")
print("="*108)
for nm in NAMES:
    s=T[T.wl_name==nm]
    if len(s)<200: continue
    se=s.move_post.std()/np.sqrt(len(s))
    print(f"{nm:8s} {len(s):7,d} | {s.move_pre.mean():8.2f}c {s.move_pre.mean()-bpre:7.2f}c {100*(s.move_pre<0).mean():5.1f}% |"
          f" {s.move_post.mean():9.2f}c {s.move_post.mean()-bpost:7.2f}c {se:5.2f}c {(s.move_post.mean()-bpost)/se:6.1f} | {s.disc.mean():8.2f}c")
print()
print("VALIDACAO do estimador: correlacao desconto <-> move_post por carteira")
print("  (se |r| for alto, o estimador ainda esta contaminado pelo nivel de preco proprio)")
for nm in NAMES:
    s=T[T.wl_name==nm]
    if len(s)<200: continue
    print(f"  {nm:8s} r(disc, move_post) = {np.corrcoef(s.disc, s.move_post)[0,1]:+.3f}")
print()
print("Q5b — move_post (vs base) POR FASE")
PH=[(-1e9,-120,"pre<-2m"),(-120,0,"pre-2..0"),(0,.25,"0-25%"),(.25,.5,"25-50%"),(.5,.75,"50-75%"),(.75,1.,"75-100%")]
print(f"{'wallet':8s} |"+"".join(f"{p[2]:>13s}" for p in PH))
for nm in NAMES:
    s=T[T.wl_name==nm]; c=[]
    for lo,hi,_ in PH:
        z=s[(s.dt>=lo)&(s.dt<hi)] if hi<=0 else s[(s.frac>=lo)&(s.frac<hi)&(s.dt>=0)]
        c.append(f"{z.move_post.mean()-bpost:+.2f}c/{len(z)//1000}k" if len(z)>300 else "   -   ")
    print(f"{nm:8s} |"+"".join(f"{x:>13s}" for x in c))
print()
print("Q2f — move_pre POR FASE (negativo = compram o lado que esta a CAIR)")
print(f"{'wallet':8s} |"+"".join(f"{p[2]:>13s}" for p in PH))
for nm in NAMES:
    s=T[T.wl_name==nm]; c=[]
    for lo,hi,_ in PH:
        z=s[(s.dt>=lo)&(s.dt<hi)] if hi<=0 else s[(s.frac>=lo)&(s.frac<hi)&(s.dt>=0)]
        c.append(f"{z.move_pre.mean()-bpre:+.2f}c" if len(z)>300 else "   -   ")
    print(f"{nm:8s} |"+"".join(f"{x:>13s}" for x in c))
