"""Q2(direcao) + Q5(selecao adversa) via FITA CRUZADA das 6 wallets.

Fita: para cada slug constroi-se uma serie P(Up) juntando os prints das 6 carteiras
(px se outcome==Up, 1-px se Down). Para cada fill exclui-se a PROPRIA carteira.
  move_pre  = P_up(t-) - P_up(t-60)      -> o lado estava a cair ou a subir ANTES
  move_post = P_up(t+60) - P_up(t+)      -> selecao adversa DEPOIS
Sinal orientado ao lado comprado: +Up, -Down.
"""
import pandas as pd, numpy as np, os
OUT = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/wallet_hunt/_decode_2026_08_18"
NAMES = ["PBot-6","PBot-2","PBot-3","PBot-5","b945","b27"]

d = []
for nm in NAMES:
    f = pd.read_parquet(os.path.join(OUT, f"fills_{nm}.parquet"))
    f["wl_name"] = nm
    d.append(f[["wl_name","slug","ts","dt","frac","outcome","px","sh","usd","tf","coin"]])
A = pd.concat(d, ignore_index=True)
A["pup"] = np.where(A.outcome.eq("Up"), A.px, 1.0 - A.px)
A["sgn"] = np.where(A.outcome.eq("Up"), 1.0, -1.0)
print(f"fita total: {len(A):,} prints em {A.slug.nunique():,} slugs")

res = []
for slug, g in A.groupby("slug", sort=False):
    if len(g) < 8: continue
    g = g.sort_values("ts")
    ts = g.ts.values.astype(np.int64); pu = g.pup.values; wl = g.wl_name.values
    n = len(g)
    # medias moveis por carteira excluida: usar soma total - soma da propria carteira
    for i in range(n):
        pass
    res.append((slug, g))
# vectorizado: para cada print i, media dos prints de OUTRAS carteiras em janelas
rows = []
for slug, g in res:
    ts = g.ts.values.astype(np.int64); pu = g.pup.values
    wl = g.wl_name.values; n = len(ts)
    lo60 = np.searchsorted(ts, ts-60, "left");  cur_l = np.searchsorted(ts, ts, "left")
    cur_r = np.searchsorted(ts, ts, "right");   hi60 = np.searchsorted(ts, ts+60, "right")
    csum = np.concatenate([[0.0], np.cumsum(pu)])
    def wmean(a, b):
        cnt = b - a
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(cnt > 0, (csum[b]-csum[a])/np.maximum(cnt,1), np.nan), cnt
    pre_old, c1 = wmean(lo60, cur_l)      # [t-60, t)
    post,    c2 = wmean(cur_r, hi60)      # (t, t+60]
    near_now,c3 = wmean(np.maximum(cur_l-3,0), cur_l)   # ultimos 3 prints antes de t
    ok = (c1 >= 2) & (c2 >= 2)
    if not ok.any(): continue
    sub = g.iloc[ok].copy()
    sub["pre_old"] = pre_old[ok]; sub["post_new"] = post[ok]; sub["near"] = near_now[ok]
    rows.append(sub)
T = pd.concat(rows, ignore_index=True)
T["move_pre"]  = (T.pup - T.pre_old)  * T.sgn * 100      # centavos, lado comprado
T["move_post"] = (T.post_new - T.pup) * T.sgn * 100
T.to_parquet(os.path.join(OUT, "tape_joined.parquet"))
print(f"fills com contexto de fita (>=2 prints antes e depois em +-60s): {len(T):,}\n")

print("="*104)
print("Q2e — O LADO COMPRADO ESTAVA A CAIR OU A SUBIR? (move_pre = variacao do lado nos 60s ANTERIORES, centavos)")
print("Q5  — SELECAO ADVERSA: move_post = variacao do lado nos 60s SEGUINTES (negativo = comprou e caiu)")
print("="*104)
print(f"{'wallet':8s} {'n':>8s} | {'move_pre':>9s} {'%a_cair':>8s} | {'move_post':>10s} {'%cai_dps':>9s} {'se':>6s} {'t':>7s}")
for nm in NAMES:
    s = T[T.wl_name == nm]
    if len(s) < 50: continue
    mp, mq = s.move_pre.mean(), s.move_post.mean()
    se = s.move_post.std()/np.sqrt(len(s))
    print(f"{nm:8s} {len(s):8,d} | {mp:8.2f}c {100*(s.move_pre<0).mean():7.1f}% | "
          f"{mq:9.2f}c {100*(s.move_post<0).mean():8.1f}% {se:5.2f}c {mq/se:6.1f}")

print()
print("Q5b — selecao adversa POR FASE da janela (move_post medio, centavos)")
PH=[(-1e9,-120,"pre<-2m"),(-120,0,"pre -2..0"),(0,.25,"0-25%"),(.25,.5,"25-50%"),(.5,.75,"50-75%"),(.75,1.,"75-100%")]
print(f"{'wallet':8s} |" + "".join(f"{p[2]:>12s}" for p in PH))
for nm in NAMES:
    s = T[T.wl_name==nm]; cells=[]
    for lo,hi,_ in PH:
        z = s[(s.dt>=lo)&(s.dt<hi)] if hi<=0 else s[(s.frac>=lo)&(s.frac<hi)&(s.dt>=0)]
        cells.append(f"{z.move_post.mean():.2f}c({len(z)//1000}k)" if len(z)>200 else "   -   ")
    print(f"{nm:8s} |" + "".join(f"{c:>12s}" for c in cells))

print()
print("Q5c — CONTROLO: media de move_post sobre TODA a fita (o vies de compra-empurra-preco)")
print(f"   toda a fita: move_post medio = {T.move_post.mean():.3f}c   move_pre medio = {T.move_pre.mean():.3f}c   n={len(T):,}")
print("   (todos os prints sao COMPRAS de bots maker; a fita tem vies altista estrutural — ler as")
print("    diferencas ENTRE carteiras, nao o nivel absoluto)")
