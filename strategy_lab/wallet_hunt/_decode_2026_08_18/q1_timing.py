"""Q1: distribuicao TEMPORAL dos fills (nao so a mediana)."""
import pandas as pd, numpy as np, os
OUT = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/wallet_hunt/_decode_2026_08_18"
NAMES = ["PBot-6","PBot-2","PBot-3","PBot-5","b945","b27"]

BUCKETS = [(-1e9,-1800,"< -30min"), (-1800,-600,"-30..-10min"), (-600,-300,"-10..-5min"),
           (-300,-120,"-5..-2min"), (-120,-30,"-120..-30s"), (-30,0,"-30..0s")]

print("="*100)
print("Q1a — DISTRIBUICAO TEMPORAL, %% do USD comprado por bucket (pre-abertura em segundos; pos = fracao da janela)")
print("="*100)
hdr = f"{'wallet':8s} {'n_fills':>8s} {'usd_tot':>11s} |" + "".join(f"{b[2]:>12s}" for b in BUCKETS) + " |" + \
      "".join(f"{'q'+str(i):>7s}" for i in range(1,11))
print(hdr)
store = {}
for nm in NAMES:
    df = pd.read_parquet(os.path.join(OUT, f"fills_{nm}.parquet"))
    store[nm] = df
    tot = df.usd.sum()
    cells = []
    for lo,hi,_ in BUCKETS:
        cells.append(100*df.loc[(df.dt>=lo)&(df.dt<hi),"usd"].sum()/tot)
    inw = df[(df.frac>=0)&(df.frac<1)]
    dec = []
    for i in range(10):
        dec.append(100*inw.loc[(inw.frac>=i/10)&(inw.frac<(i+1)/10),"usd"].sum()/tot)
    print(f"{nm:8s} {len(df):8d} {tot:11,.0f} |" + "".join(f"{c:11.1f}%" for c in cells) + " |" +
          "".join(f"{d:6.1f}%" for d in dec))

print()
print("Q1b — resumo: %% USD PRE-abertura vs DENTRO da janela vs pos-fecho; percentis do tempo do fill")
print(f"{'wallet':8s} {'pre%':>7s} {'in%':>7s} {'post%':>7s} | {'p5':>8s} {'p25':>8s} {'p50':>8s} {'p75':>8s} {'p95':>8s}  (dt seg, ponderado por USD)")
for nm in NAMES:
    df = store[nm]; tot = df.usd.sum()
    pre = 100*df.loc[df.dt<0,"usd"].sum()/tot
    inw = 100*df.loc[(df.dt>=0)&(df.frac<1),"usd"].sum()/tot
    post= 100*df.loc[df.frac>=1,"usd"].sum()/tot
    d = df.sort_values("dt"); w = d.usd.cumsum()/tot
    q = lambda p: d.dt.values[np.searchsorted(w.values, p)]
    print(f"{nm:8s} {pre:6.1f}% {inw:6.1f}% {post:6.1f}% | " +
          " ".join(f"{q(p):7.0f}s" for p in (.05,.25,.50,.75,.95)))

print()
print("Q1c — dentro da janela, %% USD por minuto-de-vida (5m apenas, para comparar com o nosso ladder btc 5m)")
print(f"{'wallet':8s} {'n_fills5m':>10s} |" + "".join(f"{'m'+str(i):>8s}" for i in range(5)) + f"{'pre5m':>9s}")
for nm in NAMES:
    df = store[nm]; d5 = df[df.tf=="5m"]
    if len(d5)==0: continue
    tot = d5.usd.sum()
    cells=[100*d5.loc[(d5.dt>=60*i)&(d5.dt<60*(i+1)),"usd"].sum()/tot for i in range(5)]
    print(f"{nm:8s} {len(d5):10d} |" + "".join(f"{c:7.1f}%" for c in cells) +
          f"{100*d5.loc[d5.dt<0,'usd'].sum()/tot:8.1f}%")
