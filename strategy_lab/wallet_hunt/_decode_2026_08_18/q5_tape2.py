"""Q2(direcao)+Q5(selecao adversa) — estimador CORRIGIDO.

Problema do 1o estimador: comparava o preco PROPRIO do fill com a media da fita,
misturando 'direcao do movimento' com 'a carteira negoceia a um nivel diferente'.

Correcao: o movimento e medido SO NA FITA e EXCLUINDO os prints da propria carteira:
  move_pre  = fita[t-30,t)  - fita[t-90,t-30)     (o lado subia/caia antes do fill)
  move_post = fita(t,t+60]  - fita[t-60,t)        (para onde foi depois do fill)
orientado ao lado comprado (+Up / -Down), em centavos.
"""
import pandas as pd, numpy as np, os
OUT = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/wallet_hunt/_decode_2026_08_18"
NAMES = ["PBot-6","PBot-2","PBot-3","PBot-5","b945","b27"]
d=[]
for nm in NAMES:
    f = pd.read_parquet(os.path.join(OUT, f"fills_{nm}.parquet")); f["wl_name"]=nm
    d.append(f[["wl_name","slug","ts","dt","frac","outcome","px","sh","usd","tf","coin"]])
A = pd.concat(d, ignore_index=True)
A["pup"] = np.where(A.outcome.eq("Up"), A.px, 1.0-A.px)
A["sgn"] = np.where(A.outcome.eq("Up"), 1.0, -1.0)
WIDX = {nm:i for i,nm in enumerate(NAMES)}
A["wi"] = A.wl_name.map(WIDX)

out=[]
for slug, g in A.groupby("slug", sort=False):
    if len(g)<12: continue
    g = g.sort_values("ts")
    ts = g.ts.values.astype(np.int64); pu = g.pup.values; wi = g.wi.values; n=len(ts)
    # cumsum global e por carteira -> permite excluir a propria carteira
    cs  = np.concatenate([[0.0], np.cumsum(pu)])
    cn  = np.arange(n+1, dtype=float)
    csw = np.zeros((6, n+1)); cnw = np.zeros((6, n+1))
    for k in range(6):
        m = (wi==k).astype(float)
        csw[k,1:] = np.cumsum(pu*m); cnw[k,1:] = np.cumsum(m)
    def seg(a,b,own):
        s = cs[b]-cs[a] - (csw[own,b]-csw[own,a])
        c = cn[b]-cn[a] - (cnw[own,b]-cnw[own,a])
        return s, c
    i_m90 = np.searchsorted(ts, ts-90,"left"); i_m30 = np.searchsorted(ts, ts-30,"left")
    i_m60 = np.searchsorted(ts, ts-60,"left"); i_l = np.searchsorted(ts, ts,"left")
    i_r   = np.searchsorted(ts, ts,"right");   i_p60= np.searchsorted(ts, ts+60,"right")
    idx = np.arange(n)
    def mean_seg(a,b):
        s = np.empty(n); c = np.empty(n)
        for k in range(6):
            m = wi==k
            if not m.any(): continue
            ss, cc = seg(a[m], b[m], k); s[m]=ss; c[m]=cc
        with np.errstate(invalid="ignore",divide="ignore"):
            return np.where(c>0, s/np.maximum(c,1), np.nan), c
    p_old, c_old = mean_seg(i_m90, i_m30)
    p_now, c_now = mean_seg(i_m30, i_l)
    p_bef, c_bef = mean_seg(i_m60, i_l)
    p_aft, c_aft = mean_seg(i_r,  i_p60)
    ok = (c_old>=2)&(c_now>=2)&(c_bef>=2)&(c_aft>=2)
    if not ok.any(): continue
    s = g.iloc[ok].copy()
    s["move_pre"]  = (p_now[ok]-p_old[ok]) * s.sgn.values * 100
    s["move_post"] = (p_aft[ok]-p_bef[ok]) * s.sgn.values * 100
    s["edge_vs_tape"] = (p_bef[ok] - s.pup.values) * s.sgn.values * 100  # desconto vs fita
    out.append(s)
T = pd.concat(out, ignore_index=True)
T.to_parquet(os.path.join(OUT,"tape2.parquet"))
print(f"fills com contexto limpo (>=2 prints de OUTRAS carteiras em cada segmento): {len(T):,}")
print(f"fita: {len(A):,} prints / {A.slug.nunique():,} slugs\n")

base_pre = T.move_pre.mean(); base_post = T.move_post.mean()
print("="*112)
print("Q2e — DIRECAO: o lado comprado estava a CAIR ou a SUBIR nos 60s antes? (fita, exclui a propria carteira)")
print("Q5  — SELECAO ADVERSA: para onde foi o lado nos 60s DEPOIS do fill")
print("="*112)
print(f"{'wallet':8s} {'n':>8s} | {'move_pre':>9s} {'vs base':>9s} {'%cai':>6s} | {'move_post':>10s} {'vs base':>9s} {'se':>6s} {'t':>7s} | {'desconto':>9s}")
for nm in NAMES:
    s=T[T.wl_name==nm]
    if len(s)<200: continue
    se=s.move_post.std()/np.sqrt(len(s))
    print(f"{nm:8s} {len(s):8,d} | {s.move_pre.mean():8.2f}c {s.move_pre.mean()-base_pre:8.2f}c {100*(s.move_pre<0).mean():5.1f}% | "
          f"{s.move_post.mean():9.2f}c {s.move_post.mean()-base_post:8.2f}c {se:5.2f}c {(s.move_post.mean()-base_post)/se:6.1f} | {s.edge_vs_tape.mean():8.2f}c")
print(f"{'BASE(all)':8s} {len(T):8,d} | {base_pre:8.2f}c {0:8.2f}c {100*(T.move_pre<0).mean():5.1f}% | {base_post:9.2f}c {0:8.2f}c")

print()
print("Q5b — move_post (vs base) POR FASE DA JANELA")
PH=[(-1e9,-120,"pre<-2m"),(-120,0,"pre-2..0"),(0,.25,"0-25%"),(.25,.5,"25-50%"),(.5,.75,"50-75%"),(.75,1.,"75-100%")]
print(f"{'wallet':8s} |"+"".join(f"{p[2]:>13s}" for p in PH))
for nm in NAMES:
    s=T[T.wl_name==nm]; cells=[]
    for lo,hi,_ in PH:
        z=s[(s.dt>=lo)&(s.dt<hi)] if hi<=0 else s[(s.frac>=lo)&(s.frac<hi)&(s.dt>=0)]
        cells.append(f"{z.move_post.mean()-base_post:+.2f}c/{len(z)//1000}k" if len(z)>300 else "   -   ")
    print(f"{nm:8s} |"+"".join(f"{c:>13s}" for c in cells))

print()
print("Q2f — move_pre POR FASE (negativo = compra lado a CAIR)")
print(f"{'wallet':8s} |"+"".join(f"{p[2]:>13s}" for p in PH))
for nm in NAMES:
    s=T[T.wl_name==nm]; cells=[]
    for lo,hi,_ in PH:
        z=s[(s.dt>=lo)&(s.dt<hi)] if hi<=0 else s[(s.frac>=lo)&(s.frac<hi)&(s.dt>=0)]
        cells.append(f"{z.move_pre.mean():+.2f}c" if len(z)>300 else "   -   ")
    print(f"{nm:8s} |"+"".join(f"{c:>13s}" for c in cells))
