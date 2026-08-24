import pandas as pd, numpy as np, os
OUT=r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/wallet_hunt/_decode_2026_08_18"
for nm in ["PBot-6","b945","b27","PBot-5"]:
    r=pd.read_parquet(os.path.join(OUT,f"redeems_{nm}.parquet"))
    g=r.groupby("cond").agg(n=("sh","size"), npos=("usd",lambda s:(s>0).sum()), nz=("usd",lambda s:(s<=0).sum()))
    print(f"{nm:8s} conds={len(g):6,d}  linhas/cond: {g.n.value_counts().head(3).to_dict()}  "
          f"| conds com EXACTAMENTE 1 linha usdc>0: {100*(g.npos==1).mean():5.1f}%  | com linha usdc==0: {100*(g.nz>0).mean():5.1f}%")
print()
print("=> confirma: cada resgate emite a perna VENCEDORA (usdcSize=size) e a PERDEDORA (usdcSize=0).")
print("   O vencedor e o `outcome` da linha com usdcSize>0. Somar `size` das duas linhas e um BUG.")
print()
r=pd.read_parquet(os.path.join(OUT,"redeems_PBot-6.parquet"))
ex=r[r.cond==r.cond.iloc[0]]
print("exemplo (uma condition):"); print(ex[["outcome","sh","usd"]].to_string(index=False))
