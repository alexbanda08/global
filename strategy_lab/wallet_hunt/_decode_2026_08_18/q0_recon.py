"""Reconciliar as duas contabilidades por carteira:
  (A) CAIXA  : pnl = soma(redeem_usd) - soma(buy_usd)      [metodo dos relatorios]
  (B) EV/sh  : pnl = soma_sh( ganhou ? 1 : 0 ) - soma(buy_usd)
Se A != B, ha redencoes de compras FORA da amostra de trades (a amostra REDEEM cobre
mais tempo que a amostra TRADE por causa do cap de 120k) -> o headline sobrestima.
"""
import pandas as pd, numpy as np, os, time
OUT=r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/wallet_hunt/_decode_2026_08_18"
NAMES=["PBot-6","PBot-2","PBot-3","PBot-5","b945","b27"]
print(f"{'wallet':8s} | {'TRADE de..ate':>26s} | {'REDEEM de..ate':>26s} | {'buy_usd':>11s} {'red_usd':>11s} {'(A) caixa':>11s} | {'(B) EV/sh':>11s} | {'gap':>10s}")
for nm in NAMES:
    f=pd.read_parquet(os.path.join(OUT,f"fills_{nm}.parquet"))
    r=pd.read_parquet(os.path.join(OUT,f"redeems_{nm}.parquet"))
    ft=lambda t: time.strftime("%m-%d %H:%M",time.gmtime(t))
    maxred=r.ts.max()
    # janelas liquidadas e presentes na amostra de TRADES
    fs=f.copy(); fs["end"]=fs.slot+fs.wl
    ok=set(fs.loc[fs.end<maxred-3600,"slug"])
    fb=f[f.slug.isin(ok)]; rb=r[r.slug.isin(ok)]
    buy=fb.usd.sum(); red=rb.usd.sum()
    # (B)
    redsh=rb.groupby("cond").sh.sum()
    pos=fb.groupby(["slug","cond","outcome"]).sh.sum().unstack(fill_value=0.0)
    for c in ("Up","Down"):
        if c not in pos: pos[c]=0.0
    pos=pos.reset_index(); pos["red"]=pos.cond.map(redsh).fillna(0.0)
    winsh=np.where(pos.red>0.01,
        np.where((pos.red-pos.Up).abs()<(pos.red-pos.Down).abs(),pos.Up,pos.Down),
        np.where(pos.Up>0,0.0,0.0))
    B=winsh.sum()-buy
    print(f"{nm:8s} | {ft(f.ts.min())+' .. '+ft(f.ts.max()):>26s} | {ft(r.ts.min())+' .. '+ft(r.ts.max()):>26s} | "
          f"{buy:11,.0f} {red:11,.0f} {red-buy:11,.0f} | {B:11,.0f} | {red-buy-B:+10,.0f}")
print()
print("gap>0 => a carteira redimiu shares compradas ANTES do inicio da amostra de trades")
print("        (o cap de 120k trades trunca as compras mas nao as redencoes) => headline inflacionado.")
