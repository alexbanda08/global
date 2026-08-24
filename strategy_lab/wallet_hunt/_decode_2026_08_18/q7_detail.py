import pandas as pd, numpy as np, os
OUT=r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/wallet_hunt/_decode_2026_08_18"
print("="*100)
print("Q1d — PBot-6: perfil da PRE-ABERTURA ao segundo (%% do USD)")
print("="*100)
f=pd.read_parquet(os.path.join(OUT,"fills_PBot-6.parquet")); tot=f.usd.sum()
for lo,hi in [(-3600,-600),(-600,-300),(-300,-240),(-240,-180),(-180,-120),(-120,-90),(-90,-60),(-60,-30),(-30,-15),(-15,-5),(-5,0)]:
    s=f[(f.dt>=lo)&(f.dt<hi)]
    print(f"  [{lo:+5d}s,{hi:+5d}s)  {100*s.usd.sum()/tot:5.2f}% do USD   n={len(s):6d}  vwap {s.usd.sum()/s.sh.sum() if s.sh.sum()>0 else 0:.4f}")
print(f"  pos-abertura (dt>=0)   {100*f.loc[f.dt>=0,'usd'].sum()/tot:5.2f}% do USD   n={(f.dt>=0).sum():6d}  vwap {f.loc[f.dt>=0,'usd'].sum()/f.loc[f.dt>=0,'sh'].sum():.4f}")
print()
print("="*100)
print("Q1e — REGRA DE ARRANQUE de cada carteira: primeiro fill relativo a abertura (dt do 1o fill por janela)")
print("="*100)
print(f"{'wallet':8s} {'janelas':>8s} | {'min':>7s} {'p1':>7s} {'p5':>7s} {'p25':>7s} {'p50':>7s} {'p75':>7s} {'p95':>7s} | {'%janelas 1o fill <60s':>22s}")
for nm in ["PBot-6","PBot-2","PBot-3","PBot-5","b945","b27"]:
    d=pd.read_parquet(os.path.join(OUT,f"fills_{nm}.parquet"))
    d5=d[d.tf=="5m"]
    if len(d5)<100: continue
    fi=d5.groupby("slug").dt.min()
    q=lambda p: np.percentile(fi,p)
    print(f"{nm:8s} {len(fi):8,d} | {fi.min():6.0f}s {q(1):6.0f}s {q(5):6.0f}s {q(25):6.0f}s {q(50):6.0f}s {q(75):6.0f}s {q(95):6.0f}s | {100*(fi<60).mean():21.1f}%")
print()
print("="*100)
print("Q2g — PBot-6 pre-abertura: desconto REAL vs o mid do nosso livro (14-18 Ago)")
print("="*100)
X=pd.read_parquet(os.path.join(OUT,"book_join.parquet"))
for nm in ["PBot-6","PBot-2","PBot-3","PBot-5"]:
    s=X[X.wl==nm]
    if len(s)<200: continue
    pre=s[s.dt<0]; ino=s[s.dt>=0]
    fmt=lambda z: f"{z.vs_mid.mean():+6.2f}c (n={len(z):5d}, vwap {z.usd.sum()/z.sh.sum():.4f})" if len(z)>50 else "  -  "
    print(f"  {nm:8s} pre-abertura: {fmt(pre)}   |  dentro da janela: {fmt(ino)}")
print("  (vs_mid = mid - preco pago; positivo = comprou ABAIXO do mid)")
