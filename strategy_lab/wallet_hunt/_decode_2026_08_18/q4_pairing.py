"""Q4 — PAREAMENTO: dentro da mesma carteira ou ENTRE carteiras da frota?
+ Q5 limpo: EV do RESIDUAL (perna nua) separado do par."""
import pandas as pd, numpy as np, os, itertools
OUT=r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/wallet_hunt/_decode_2026_08_18"
NAMES=["PBot-6","PBot-2","PBot-3","PBot-5","b945","b27"]
F={nm:pd.read_parquet(os.path.join(OUT,f"fills_{nm}.parquet")) for nm in NAMES}
R={nm:pd.read_parquet(os.path.join(OUT,f"redeems_{nm}.parquet")) for nm in NAMES}

# ---- mapa GLOBAL de vencedores (uniao das 6; b27 faz merge -> a sua redencao nao serve) ----
win={}
for nm in NAMES:
    f,r=F[nm],R[nm]; maxred=r.ts.max()
    red=r.groupby("cond").sh.sum()
    pos=f.groupby(["slug","cond","outcome"]).sh.sum().unstack(fill_value=0.0)
    for c in ("Up","Down"):
        if c not in pos: pos[c]=0.0
    pos=pos.reset_index()
    pos["slot"]=pos.slug.str.rsplit("-",n=1).str[-1].astype(int)
    pos["wl"]=np.where(pos.slug.str.contains("-5m-"),300,900)
    pos=pos[pos.slot+pos.wl<maxred-3600]
    pos["red"]=pos.cond.map(red).fillna(0.0)
    for _,p in pos.iterrows():
        if p.slug in win: continue
        if p.red>0.01:
            # so aceitar se a redencao bate claramente um dos lados (evita ruido de merge)
            du,dd=abs(p.red-p.Up),abs(p.red-p.Down)
            if min(du,dd)<0.02*max(p.red,1) and abs(du-dd)>0.01*max(p.red,1):
                win[p.slug]="Up" if du<dd else "Down"
        elif (p.Up>0)!=(p.Down>0):
            win[p.slug]="Down" if p.Up>0 else "Up"
W=pd.Series(win,name="winner"); W.index.name="slug"
print(f"mapa global de vencedores: {len(W):,} janelas resolvidas (uniao das 6 carteiras)\n")

def book(df):
    """agrega por janela -> par / residual"""
    g=df.groupby(["slug","outcome"]).agg(sh=("sh","sum"),usd=("usd","sum")).unstack(fill_value=0.0)
    up,dn=g[("sh","Up")],g[("sh","Down")]; uu,ud=g[("usd","Up")],g[("usd","Down")]
    b=pd.DataFrame({"up":up,"dn":dn,"uu":uu,"ud":ud})
    b["pair"]=np.minimum(b.up,b.dn); b["res"]=(b.up-b.dn).abs()
    b["res_side"]=np.where(b.up>b.dn,"Up","Down")
    with np.errstate(invalid="ignore",divide="ignore"):
        b["vu"]=np.where(b.up>0,b.uu/b.up,np.nan); b["vd"]=np.where(b.dn>0,b.ud/b.dn,np.nan)
    b["pvs"]=b.vu+b.vd
    return b

print("="*118)
print("Q4a — PAREAMENTO POR CARTEIRA (todas as janelas de cada uma)")
print("="*118)
print(f"{'wallet':8s} {'janelas':>8s} {'2 lados':>8s} {'par sh':>10s} {'resid sh':>10s} {'par:res':>8s} {'pvs medio':>10s} {'margem/par':>11s}")
B={}
for nm in NAMES:
    b=book(F[nm]); B[nm]=b
    two=100*((b.up>0)&(b.dn>0)).mean()
    pv=b.loc[(b.up>0)&(b.dn>0),"pvs"]
    pvw=(b.pair*b.pvs).sum()/b.pair.sum()
    print(f"{nm:8s} {len(b):8,d} {two:7.1f}% {b.pair.sum():10,.0f} {b.res.sum():10,.0f} "
          f"{b.pair.sum()/max(b.res.sum(),1):8.2f} {pvw:10.4f} {100*(1-pvw):9.2f}c")

print()
print("="*118)
print("Q4b — TESTE DECISIVO: agregar livros de varias carteiras na MESMA janela e re-parear")
print("="*118)
COMB=[("PBot-2+3",["PBot-2","PBot-3"]),("PBot-2+5",["PBot-2","PBot-5"]),
      ("PBot-2+3+5",["PBot-2","PBot-3","PBot-5"]),
      ("frota PBot 2/3/5/6",["PBot-2","PBot-3","PBot-5","PBot-6"]),
      ("PBot-6+2",["PBot-6","PBot-2"]),
      ("TODAS as 6",NAMES)]
print(f"{'combinacao':22s} {'janelas':>8s} | {'par(soma indiv)':>16s} {'res(soma indiv)':>16s} {'ratio':>7s} | {'par(agregado)':>14s} {'res(agregado)':>14s} {'ratio':>7s} | {'Delta res':>10s}")
for lbl,ws in COMB:
    slugs=set.intersection(*[set(B[w].index) for w in ws])
    if not slugs: continue
    pi=sum(B[w].loc[list(slugs&set(B[w].index)),"pair"].sum() for w in ws)
    ri=sum(B[w].loc[list(slugs&set(B[w].index)),"res"].sum() for w in ws)
    agg=book(pd.concat([F[w][F[w].slug.isin(slugs)] for w in ws],ignore_index=True))
    pa,ra=agg.pair.sum(),agg.res.sum()
    print(f"{lbl:22s} {len(slugs):8,d} | {pi:16,.0f} {ri:16,.0f} {pi/max(ri,1):7.2f} | {pa:14,.0f} {ra:14,.0f} {pa/max(ra,1):7.2f} | {100*(ra-ri)/max(ri,1):+9.1f}%")

print()
print("="*118)
print("Q4c/Q5g — DECOMPOSICAO: o par e o residual, SEPARADOS (o par nao tem risco de direcao)")
print("           EV_par/share = 1 - pvs   |   EV_resid/share = WR_resid - vwap_resid")
print("="*118)
print(f"{'wallet':8s} {'par sh':>10s} {'1-pvs':>8s} {'$ do par':>10s} | {'res sh':>9s} {'vwap_res':>9s} {'WR_res':>8s} {'EV_res/sh':>10s} {'$ do res':>10s} | {'% lucro do par':>15s}")
for nm in NAMES:
    b=B[nm].join(W,how="inner")
    if len(b)<100: print(f"{nm:8s} n<100"); continue
    pvw=(b.pair*b.pvs).sum()/b.pair.sum(); pair_usd=(b.pair*(1-b.pvs)).sum()
    r=b[b.res>0.01].copy()
    r["vres"]=np.where(r.res_side=="Up",r.vu,r.vd)
    r["won"]=(r.res_side==r.winner).astype(float)
    vwr=(r.res*r.vres).sum()/r.res.sum(); wrr=(r.res*r.won).sum()/r.res.sum()
    res_usd=(r.res*(r.won-r.vres)).sum()
    tot=pair_usd+res_usd
    print(f"{nm:8s} {b.pair.sum():10,.0f} {100*(1-pvw):6.2f}c {pair_usd:10,.0f} | {r.res.sum():9,.0f} {vwr:9.4f} {100*wrr:7.2f}% "
          f"{100*(wrr-vwr):+9.2f}c {res_usd:10,.0f} | {100*pair_usd/tot if tot!=0 else float('nan'):14.1f}%")
print()
print("NOTA b27: faz 21k MERGE em 2.5d -> as suas redencoes nao identificam o vencedor;")
print("          aqui o vencedor vem do mapa GLOBAL (outras carteiras), o que o recupera.")
