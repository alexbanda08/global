"""
SAME-MARKET MERGE SCAN (proper, corrected dedup metric) — is there mergeable uplift across running sleeves?
Input: fleet_cofire_12d.csv = one deduped row per (sleeve, market): sleeve_id, cid, sig(UP/DOWN/NA), pnl, won.
(pnl from the resolution row, signal from the fire row, deduped once per market = the dashboard metric.)
Tests: (1) per-sleeve solo baselines; (2) CONSENSUS voting — does requiring more sleeves to agree on a market's
direction raise WR/$/tr?; (3) PAIRWISE agreement uplift vs each solo (properly deduped — the thing the loose
agent got wrong). $/tr comparable only within same notional -> restrict $/tr merges to the $5 sniper_v5 family.
"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
D = pd.read_csv(ROOT/"strategy_lab/directional/_results/fleet_cofire_12d.csv")
D = D[D.sig.isin(["UP","DOWN"])].copy()
D = D.dropna(subset=["won","pnl"])
D["won"]=D.won.astype(int)
# true market outcome per cid (recover from any row): UP if (sig=UP & won) or (sig=DOWN & !won)
D["mkt_up"] = ((D.sig=="UP")&(D.won==1)) | ((D.sig=="DOWN")&(D.won==0))
outcome = D.groupby("cid").mkt_up.first()
print(f"directional fires: {len(D)}  markets: {D.cid.nunique()}  sleeves: {D.sleeve_id.nunique()}")

def boot(v,nb=4000):
    v=np.asarray(v)
    if len(v)<5: return (np.nan,np.nan)
    i=np.random.randint(0,len(v),(nb,len(v))); return tuple(np.percentile(v[i].mean(1),[2.5,97.5]))
def stat(v):
    v=np.asarray(v)
    if len(v)<5: return (len(v),np.nan,np.nan,np.nan,np.nan)
    t=v.mean()/v.std(ddof=1)*np.sqrt(len(v)) if v.std()>0 else np.nan; lo,hi=boot(v)
    return (len(v),v.mean(),t,lo,hi)

# ---- solo baselines (all sleeves with n>=40) ----
print("\n===== SOLO baselines (n>=40, by $/tr) =====")
solo={}
for sl,g in D.groupby("sleeve_id"):
    if len(g)<40: continue
    n,m,t,lo,hi=stat(g.pnl.values); solo[sl]=(n,m,t,g.won.mean())
top=sorted(solo.items(), key=lambda kv:-kv[1][1])
for sl,(n,m,t,wr) in top[:8]:  print(f"  +{m:+.3f}/tr t={t:+.2f} n={n:4d} wr={wr:.2f}  {sl[:55]}")
print("  ...")
for sl,(n,m,t,wr) in top[-5:]: print(f"  {m:+.3f}/tr t={t:+.2f} n={n:4d} wr={wr:.2f}  {sl[:55]}")

# ---- CONSENSUS voting (restrict to $5 sniper_v5 for comparable notional) ----
S = D[D.sleeve_id.str.startswith("poly_sniper_v5")].copy()
print(f"\n===== CONSENSUS voting (sniper_v5 $5 fleet, {S.cid.nunique()} markets) =====")
rows=[]
for cid,g in S.groupby("cid"):
    nu=(g.sig=="UP").sum(); nd=(g.sig=="DOWN").sum()
    if nu==nd: continue                         # no majority
    maj = "UP" if nu>nd else "DOWN"
    agree=g[g.sig==maj]; k=len(agree); margin=abs(nu-nd)
    pnl=agree.pnl.mean()                          # consensus trade pnl = mean of agreeing sleeves (same notional)
    won=int(outcome[cid]==(maj=="UP"))
    rows.append((cid,maj,k,margin,pnl,won))
C=pd.DataFrame(rows,columns=["cid","maj","k","margin","pnl","won"])
print(f"  consensus markets (with a majority): {len(C)}")
print("  -- by NUMBER of agreeing sleeves (k) --")
for lo_k,hi_k,lab in [(1,1,"k=1 (lone)"),(2,3,"k=2-3"),(4,6,"k=4-6"),(7,100,"k>=7")]:
    s=C[(C.k>=lo_k)&(C.k<=hi_k)]; n,m,t,blo,bhi=stat(s.pnl.values)
    wr=s.won.mean() if len(s) else np.nan
    print(f"    {lab:10s} n={n:4d} $/tr={m:+.3f} t={t:+.2f} CI=[{blo:+.3f},{bhi:+.3f}] WR={wr:.2f}")
print("  READ: if $/tr & WR RISE with k -> consensus merge has uplift; if flat/declining -> agreement is priced-in.")

# ---- PAIRWISE agreement uplift (proper dedup; candidates = positive-solo sniper_v5, n>=60) ----
cand=[sl for sl,(n,m,t,wr) in solo.items() if sl.startswith("poly_sniper_v5") and m>0 and n>=60]
print(f"\n===== PAIRWISE agreement uplift ({len(cand)} positive sniper_v5 candidates, n>=60) =====")
piv={sl:S[S.sleeve_id==sl].set_index("cid")[["sig","pnl"]] for sl in cand}
res=[]
for i in range(len(cand)):
    for j in range(i+1,len(cand)):
        a,b=cand[i],cand[j]; A=piv[a]; B=piv[b]
        common=A.index.intersection(B.index)
        if len(common)<30: continue
        agree=[c for c in common if A.loc[c,"sig"]==B.loc[c,"sig"]]
        if len(agree)<30: continue
        # merged $/tr = mean of the two legs on agreement markets (both same dir, same $5 notional)
        mp=np.array([(A.loc[c,"pnl"]+B.loc[c,"pnl"])/2 for c in agree])
        n,m,t,lo,hi=stat(mp)
        solo_a=solo[a][1]; solo_b=solo[b][1]; best=max(solo_a,solo_b)
        res.append((a,b,n,m,t,lo,hi,best,m-best,len(common)))
res.sort(key=lambda r:-r[8])
print("  top pairs by uplift vs best-solo (agree minus best-solo):")
print(f"  {'pair':<58} n_agree  agree$/tr  t   bestSolo  uplift")
for a,b,n,m,t,lo,hi,best,up,nco in res[:10]:
    nm=f"{a.replace('poly_sniper_v5_','')[:26]}+{b.replace('poly_sniper_v5_','')[:26]}"
    flag="SIG+" if lo>0 else "ns"
    print(f"  {nm:<58} {n:4d}   {m:+.3f}  {t:+.2f}  {best:+.3f}  {up:+.3f} {flag}")
print(f"\n  pairs evaluated: {len(res)}; pairs with uplift>0 AND agree-CI>0 AND uplift>0.10: "
      f"{sum(1 for r in res if r[5]>0 and r[8]>0.10)}")
print("READ: a real merge = agree$/tr beats BOTH solos by a margin, CI>0, with non-trivial n. Else merging is null.")
