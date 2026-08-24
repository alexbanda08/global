"""Q5 (versao decisiva) — SELECAO ADVERSA MEDIDA NO DESFECHO.

Para quem segura ate a liquidacao, 'selecao adversa' = a WR realizada ficar ABAIXO
do preco pago. Verdade = redencoes (nenhuma destas carteiras vende).
Vencedor por janela: o token cujo total comprado bate o total redimido (cash-truth).
EV/share = WR_ponderada_por_share - vwap.
CI agrupado POR JANELA (todos os fills de uma janela partilham um vencedor).
"""
import pandas as pd, numpy as np, os
OUT=r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/wallet_hunt/_decode_2026_08_18"
NAMES=["PBot-6","PBot-2","PBot-3","PBot-5","b945","b27"]

def winners(nm):
    f=pd.read_parquet(os.path.join(OUT,f"fills_{nm}.parquet"))
    r=pd.read_parquet(os.path.join(OUT,f"redeems_{nm}.parquet"))
    maxred=r.ts.max()
    red=r.groupby("cond").sh.sum()
    pos=f.groupby(["slug","cond","outcome"]).sh.sum().unstack(fill_value=0.0)
    for c in ("Up","Down"):
        if c not in pos: pos[c]=0.0
    pos=pos.reset_index()
    pos["slot"]=pos.slug.str.rsplit("-",n=1).str[-1].astype(int)
    pos["wl"]=np.where(pos.slug.str.contains("-5m-"),300,900)
    pos=pos[pos.slot+pos.wl < maxred-3600]           # so janelas ja liquidadas+redimidas
    pos["red"]=pos.cond.map(red).fillna(0.0)
    win=np.where(pos.red>0.01,
                 np.where((pos.red-pos.Up).abs()<(pos.red-pos.Down).abs(),"Up","Down"),
                 np.where(pos.Up>0,"Down","Up"))
    amb=(pos.red<=0.01)&(pos.Up>0)&(pos.Down>0)
    pos["winner"]=win
    return f, pos.loc[~amb,["slug","winner"]], len(pos), amb.sum()

print("="*118)
print("Q5d — CALIBRACAO: WR realizada vs preco pago (ponderado por SHARES). EV/share = WR - vwap.")
print("      Se WR < preco => selecao adversa. Se WR ~ preco => mercado calibrado, sem edge de direcao.")
print("="*118)
print(f"{'wallet':8s} {'janelas':>8s} {'M sh':>6s} {'vwap':>7s} {'WR_sh':>7s} {'EV/sh':>8s} {'CI95 (cluster janela)':>24s} {'ROI':>7s} {'amb':>5s}")
CAL={}
for nm in NAMES:
    f,w,nw,amb=winners(nm)
    m=f.merge(w,on="slug",how="inner")
    m["won"]=(m.outcome==m.winner).astype(float)
    sh=m.sh.values; won=m.won.values; usd=m.usd.values
    vwap=usd.sum()/sh.sum(); wr=(won*sh).sum()/sh.sum(); ev=wr-vwap
    # bootstrap por JANELA
    g=m.groupby("slug").apply(lambda x: pd.Series({"sh":x.sh.sum(),"usd":x.usd.sum(),"wsh":(x.won*x.sh).sum()}), include_groups=False)
    rng=np.random.default_rng(7); B=[]
    S=g.sh.values; U=g.usd.values; W=g.wsh.values; n=len(g)
    for _ in range(600):
        i=rng.integers(0,n,n); B.append(W[i].sum()/S[i].sum() - U[i].sum()/S[i].sum())
    lo,hi=np.percentile(B,[2.5,97.5])
    CAL[nm]=m
    print(f"{nm:8s} {len(w):8,d} {sh.sum()/1e6:6.2f} {vwap:7.4f} {100*wr:6.2f}% {100*ev:+7.2f}c "
          f"[{100*lo:+6.2f}c,{100*hi:+6.2f}c]  {100*ev/vwap:+6.2f}% {amb:5d}")

print()
print("Q5e — CALIBRACAO POR BUCKET DE PRECO (o mercado esta calibrado? ha selecao adversa localizada?)")
BINS=[0,.15,.25,.35,.45,.55,.65,.75,.85,1.01]
LAB=["<.15",".15-.25",".25-.35",".35-.45",".45-.55",".55-.65",".65-.75",".75-.85",">.85"]
print(f"{'wallet':8s} |"+"".join(f"{l:>12s}" for l in LAB))
print(f"{'':8s} |"+"".join(f"{'EV/sh (n)':>12s}" for l in LAB))
for nm in NAMES:
    m=CAL[nm]; b=pd.cut(m.px,BINS,right=False,labels=LAB); c=[]
    for l in LAB:
        z=m[b==l]
        if z.sh.sum()<3000: c.append("     -      "); continue
        ev=(z.won*z.sh).sum()/z.sh.sum() - z.usd.sum()/z.sh.sum()
        c.append(f"{100*ev:+5.1f}c({len(z)//1000}k)")
    print(f"{nm:8s} |"+"".join(f"{x:>12s}" for x in c))

print()
print("Q5f — EV/share POR FASE DA JANELA (onde e que cada uma ganha e onde e que perde)")
PH=[(-1e9,-300,"pre<-5m"),(-300,-120,"pre-5..-2m"),(-120,0,"pre-2..0m"),(0,.25,"0-25%"),(.25,.5,"25-50%"),(.5,.75,"50-75%"),(.75,1.,"75-100%")]
print(f"{'wallet':8s} |"+"".join(f"{p[2]:>14s}" for p in PH))
for nm in NAMES:
    m=CAL[nm]; c=[]
    for lo,hi,_ in PH:
        z=m[(m.dt>=lo)&(m.dt<hi)] if hi<=0 else m[(m.frac>=lo)&(m.frac<hi)&(m.dt>=0)]
        if z.sh.sum()<3000: c.append("      -       "); continue
        ev=(z.won*z.sh).sum()/z.sh.sum()-z.usd.sum()/z.sh.sum()
        c.append(f"{100*ev:+5.1f}c/{z.sh.sum()/1e3:.0f}k")
    print(f"{nm:8s} |"+"".join(f"{x:>14s}" for x in c))
