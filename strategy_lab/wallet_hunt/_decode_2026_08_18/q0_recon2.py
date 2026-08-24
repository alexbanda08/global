"""Reconciliacao LIMPA: so janelas inteiramente DENTRO da amostra de trades,
e vencedor = outcome da linha de REDEEM com usdcSize>0 (corrige o bug de somar as 2 pernas).
   (A) caixa   = red_usd - buy_usd
   (B) shares  = shares_vencedoras - buy_usd
Se A==B, a contabilidade fecha e o ROI e fiavel."""
import pandas as pd, numpy as np, os
OUT=r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/wallet_hunt/_decode_2026_08_18"
NAMES=["PBot-6","PBot-2","PBot-3","PBot-5","b945","b27"]
print(f"{'wallet':8s} {'janelas':>8s} {'buy_usd':>10s} {'red_usd':>10s} | {'(A)caixa':>10s} {'ROI_A':>7s} | {'(B)shares':>10s} {'ROI_B':>7s} | {'A-B':>9s} {'merges':>7s}")
RES={}
for nm in NAMES:
    f=pd.read_parquet(os.path.join(OUT,f"fills_{nm}.parquet"))
    r=pd.read_parquet(os.path.join(OUT,f"redeems_{nm}.parquet"))
    t0=f.ts.min()+86400            # margem: 1 dia apos o inicio da amostra de trades
    tend=r.ts.max()-3600
    f=f[(f.slot>=t0)&(f.slot+f.wl<tend)]
    slugs=set(f.slug); r=r[r.slug.isin(slugs)]
    buy=f.usd.sum(); red=r.usd.sum()
    rw=r[r.usd>0]                                    # perna vencedora
    winner=rw.drop_duplicates("slug").set_index("slug").outcome
    pos=f.groupby(["slug","outcome"]).sh.sum().unstack(fill_value=0.0)
    for c in ("Up","Down"):
        if c not in pos: pos[c]=0.0
    pos=pos.join(winner.rename("winner"))
    # janelas sem linha vencedora => o lado que tinha perdeu (redimiu 0)
    hasw=pos.winner.notna()
    winsh=np.where(hasw, np.where(pos.winner.eq("Up"),pos.Up,pos.Down), 0.0).sum()
    RES[nm]=(f,pos,winner)
    print(f"{nm:8s} {len(pos):8,d} {buy:10,.0f} {red:10,.0f} | {red-buy:10,.0f} {100*(red-buy)/buy:6.2f}% | "
          f"{winsh-buy:10,.0f} {100*(winsh-buy)/buy:6.2f}% | {red-buy-(winsh-buy):+9,.0f} "
          f"{'sim' if nm in ('b27','PBot-2','PBot-3') else 'nao':>7s}")
print()
print("Nota: para b27/PBot-2/PBot-3 (que fazem MERGE) o caixa (A) NAO fecha por construcao —")
print("      o merge devolve $1 por par sem passar por REDEEM. (B) tambem falha (o par merged")
print("      nao aparece como shares vencedoras). Para essas, o par tem de ser contado a parte.")
print()
print("="*104)
print("(C) contabilidade COMPLETA que fecha para todas: par(merge ou redeem) + residual")
print("    pnl = par_sh*(1-pvs) + res_sh*(ganhou - vwap_res)   [o par vale $1 quer se faca merge quer nao]")
print("="*104)
print(f"{'wallet':8s} {'janelas':>8s} {'buy_usd':>10s} {'par_sh':>10s} {'res_sh':>10s} {'pnl_par':>10s} {'pnl_res':>10s} {'PNL':>10s} {'ROI':>7s}")
for nm in NAMES:
    f,pos,winner=RES[nm]
    g=f.groupby(["slug","outcome"]).agg(sh=("sh","sum"),usd=("usd","sum")).unstack(fill_value=0.0)
    up,dn=g[("sh","Up")],g[("sh","Down")]; uu,ud=g[("usd","Up")],g[("usd","Down")]
    pair=np.minimum(up,dn); res=(up-dn).abs(); rside=np.where(up>dn,"Up","Down")
    vu=np.where(up>0,uu/up,0.0); vd=np.where(dn>0,ud/dn,0.0)
    pvs=vu+vd; vres=np.where(up>dn,vu,vd)
    w=winner.reindex(g.index)
    won=np.where(w.isna(), 0.0, (w.values==rside).astype(float))
    ok=w.notna().values | (res.values>0)
    pnl_pair=(pair*(1-pvs)).sum(); pnl_res=(res.values*(won-vres)).sum()
    buy=f.usd.sum()
    print(f"{nm:8s} {len(g):8,d} {buy:10,.0f} {pair.sum():10,.0f} {res.sum():10,.0f} {pnl_pair:10,.0f} {pnl_res:10,.0f} "
          f"{pnl_pair+pnl_res:10,.0f} {100*(pnl_pair+pnl_res)/buy:6.2f}%")
