"""Q2: a que PRECO compram — barato (azarao) ou caro (favorito)?"""
import pandas as pd, numpy as np, os
OUT = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/wallet_hunt/_decode_2026_08_18"
NAMES = ["PBot-6","PBot-2","PBot-3","PBot-5","b945","b27"]
store = {nm: pd.read_parquet(os.path.join(OUT, f"fills_{nm}.parquet")) for nm in NAMES}

BINS = [0,.10,.20,.30,.40,.50,.60,.70,.80,.90,1.01]
LAB  = ["<.10",".10-.20",".20-.30",".30-.40",".40-.50",".50-.60",".60-.70",".70-.80",".80-.90",">.90"]

print("="*112)
print("Q2a — DISTRIBUICAO DE PRECO DE ENTRADA (%% das SHARES compradas por bucket de preco)")
print("="*112)
print(f"{'wallet':8s} {'vwap':>7s} {'sh(M)':>7s} |" + "".join(f"{l:>9s}" for l in LAB) + f" |{'%sh<0.50':>9s}")
for nm in NAMES:
    df = store[nm]; b = pd.cut(df.px, BINS, right=False, labels=LAB)
    g = df.groupby(b, observed=False).sh.sum(); tot = g.sum()
    print(f"{nm:8s} {df.usd.sum()/df.sh.sum():7.4f} {tot/1e6:7.2f} |" +
          "".join(f"{100*v/tot:8.1f}%" for v in g.values) +
          f" |{100*df.loc[df.px<0.50,'sh'].sum()/tot:8.1f}%")

print()
print("Q2b — PRECO MEDIO (vwap) POR FASE DA JANELA — sobe ou desce ao longo da vida?")
PH = [(-1e9,-300,"pre <-5m"),(-300,-120,"pre -5..-2m"),(-120,0,"pre -2..0m"),
      (0,.2,"in 0-20%"),(.2,.4,"20-40%"),(.4,.6,"40-60%"),(.6,.8,"60-80%"),(.8,1.0,"80-100%")]
print(f"{'wallet':8s} |" + "".join(f"{p[2]:>13s}" for p in PH))
for nm in NAMES:
    df = store[nm]; cells=[]
    for lo,hi,_ in PH:
        s = df[(df.dt>=lo)&(df.dt<hi)] if hi<=0 else df[(df.frac>=lo)&(df.frac<hi)&(df.dt>=0)]
        cells.append(f"{s.usd.sum()/s.sh.sum():.4f}" if s.sh.sum()>0 else "  -  ")
    print(f"{nm:8s} |" + "".join(f"{c:>13s}" for c in cells))

print()
print("Q2c — %% das SHARES no lado BARATO (px<0.50) POR FASE — 'compram o azarao mais tarde?'")
print(f"{'wallet':8s} |" + "".join(f"{p[2]:>13s}" for p in PH))
for nm in NAMES:
    df = store[nm]; cells=[]
    for lo,hi,_ in PH:
        s = df[(df.dt>=lo)&(df.dt<hi)] if hi<=0 else df[(df.frac>=lo)&(df.frac<hi)&(df.dt>=0)]
        cells.append(f"{100*s.loc[s.px<0.5,'sh'].sum()/s.sh.sum():.1f}%" if s.sh.sum()>0 else "  -  ")
    print(f"{nm:8s} |" + "".join(f"{c:>13s}" for c in cells))

print()
print("Q2d — DENTRO DA JANELA, compram o lado LEVE (o que eles proprios tem menos) ou o PESADO?")
print("      metrica: para cada fill em t, a posicao acumulada do MESMO lado vs a do lado oposto ate t-1")
for nm in NAMES:
    df = store[nm].sort_values(["slug","ts"]).copy()
    # acumulado por slug+outcome ANTES do fill
    df["cum_same"] = df.groupby(["slug","outcome"]).sh.cumsum() - df.sh
    tot_by_slug = df.groupby(["slug"]).sh.cumsum() - df.sh
    df["cum_opp"] = tot_by_slug - df["cum_same"]
    m = df[(df.cum_same+df.cum_opp) > 0]
    late = m[m.frac>=0.6]; early = m[(m.frac>=0)&(m.frac<0.4)]
    f = lambda s: 100*s.loc[s.cum_same < s.cum_opp,"usd"].sum()/s.usd.sum() if len(s) else float('nan')
    print(f"  {nm:8s} %USD comprando o lado LEVE:  cedo(0-40%) {f(early):5.1f}%   tarde(60-100%) {f(late):5.1f}%   (n_late={len(late)})")
