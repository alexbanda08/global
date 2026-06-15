#!/usr/bin/env python3
"""DSR + PBO(CSCV) on the pre-registered RS config.

Pre-registered (chosen BEFORE this test, from the grid's low-turnover/low-DD row):
    form=ls, sig=score2, side=contra, freq=weekly, K=8

Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014): deflate the observed Sharpe
for #trials (180), sample length, skew, kurtosis -> P(true SR>0 | selection).
PBO via CSCV (Bailey/Borwein/LdP/Zhu 2015): across all 180 configs, how often the
in-sample best is below-median out-of-sample -> probability the selection is overfit.

No scipy dependency (Phi via erf, inverse-Phi via Acklam).
"""
import math, itertools
import numpy as np, pandas as pd
from rs_backtest import run

CHOSEN = ("ls","score2","contra","wk",8)   # form,sig,side,freq,K
GAMMA = 0.5772156649

def Phi(x): return 0.5*(1.0+math.erf(x/math.sqrt(2.0)))
def Phi_inv(p):  # Acklam rational approximation
    a=[-3.969683028665376e+01,2.209460984245205e+02,-2.759285104469687e+02,1.383577518672690e+02,-3.066479806614716e+01,2.506628277459239e+00]
    b=[-5.447609879822406e+01,1.615858368580409e+02,-1.556989798598866e+02,6.680131188771972e+01,-1.328068155288572e+01]
    c=[-7.784894002430293e-03,-3.223964580411365e-01,-2.400758277161838e+00,-2.549732539343734e+00,4.374664141464968e+00,2.938163982698783e+00]
    d=[7.784695709041462e-03,3.224671290700398e-01,2.445134137142996e+00,3.754408661907416e+00]
    pl=0.02425
    if p<pl:
        q=math.sqrt(-2*math.log(p)); return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5])/((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p>1-pl:
        q=math.sqrt(-2*math.log(1-p)); return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5])/((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q=p-0.5; r=q*q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q/(((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)

def sr_daily(x):
    x=np.asarray(x,float); x=x[~np.isnan(x)]
    return 0.0 if x.std(ddof=1)==0 or len(x)<5 else x.mean()/x.std(ddof=1)

def main():
    df,res,results = run()
    # returns matrix: time x config
    M={}
    chosen_key=None
    for r in results:
        key=(r["form"],r["sig"],r["side"],r["freq"],r["K"])
        M[key]=r["r"]
        if key==CHOSEN: chosen_key=key
    R=pd.DataFrame(M).fillna(0.0)
    N=R.shape[1]
    if chosen_key is None:
        print("chosen config not found"); return
    rc=R[chosen_key].values
    rc=rc[rc!=0] if False else rc  # keep full daily series (zeros = flat days)

    # ---------- DSR ----------
    x=rc[~np.isnan(rc)]
    T=len(x); sr=sr_daily(x)
    mu=x.mean(); sd=x.std(ddof=1)
    g3=float(((x-mu)**3).mean()/sd**3)                 # skew
    g4=float(((x-mu)**4).mean()/sd**4)                 # kurtosis (normal=3)
    # trial sharpes (per-day) across all configs
    trial_sr=np.array([sr_daily(R[k].values) for k in R.columns])
    var_sr=trial_sr.var(ddof=1)
    sr0 = math.sqrt(var_sr)*((1-GAMMA)*Phi_inv(1-1.0/N)+GAMMA*Phi_inv(1-1.0/(N*math.e)))
    def psr(sr_star):
        denom=math.sqrt(max(1e-12,1 - g3*sr + (g4-1)/4.0*sr*sr))
        return Phi((sr-sr_star)*math.sqrt(T-1)/denom)
    psr0=psr(0.0); dsr=psr(sr0)
    ann=sr*math.sqrt(365)

    # ---------- PBO via CSCV ----------
    S=8                                                # even #blocks
    arr=R.values; Tn=arr.shape[0]
    cut=[int(round(i*Tn/S)) for i in range(S+1)]
    blocks=[list(range(cut[i],cut[i+1])) for i in range(S)]
    lambdas=[]
    for comb in itertools.combinations(range(S), S//2):
        is_idx=np.concatenate([blocks[b] for b in comb])
        oos_idx=np.concatenate([blocks[b] for b in range(S) if b not in comb])
        is_sr=np.array([sr_daily(arr[is_idx,j]) for j in range(N)])
        oos_sr=np.array([sr_daily(arr[oos_idx,j]) for j in range(N)])
        n_star=int(np.argmax(is_sr))                   # best in-sample
        # relative OOS rank of n_star (1=worst..N=best)
        rank=(oos_sr<oos_sr[n_star]).sum()+1
        w=rank/(N+1.0)
        w=min(max(w,1e-6),1-1e-6)
        lambdas.append(math.log(w/(1-w)))
    lambdas=np.array(lambdas)
    pbo=float((lambdas<=0).mean())

    # chosen config's own median OOS performance across splits
    j=list(R.columns).index(chosen_key)
    oos_sr_chosen=[]
    for comb in itertools.combinations(range(S), S//2):
        oos_idx=np.concatenate([blocks[b] for b in range(S) if b not in comb])
        oos_sr_chosen.append(sr_daily(arr[oos_idx,j])*math.sqrt(365))
    med_oos_chosen=float(np.median(oos_sr_chosen))

    out=[]
    P=out.append
    P("# DSR + PBO — pre-registered RS config\n")
    P(f"**Config (pre-registered):** `ls / score2 / contra / weekly / K=8`  ·  trials in grid N={N}  ·  T={T} days\n")
    P("## Deflated Sharpe Ratio")
    P(f"- Observed Sharpe: **{ann:.2f}** annualized ({sr:.4f}/day)")
    P(f"- Return skew {g3:.2f}, kurtosis {g4:.2f} (normal=3)")
    P(f"- Trial-Sharpe dispersion across {N} configs: std(SR_day)={math.sqrt(var_sr):.4f}")
    P(f"- Expected-max Sharpe under N trials (SR0): **{sr0*math.sqrt(365):.2f}** annualized")
    P(f"- **PSR(0)** (prob true SR>0, no selection adj): **{psr0:.3f}**")
    P(f"- **DSR** (prob true SR>0 AFTER deflating for {N} trials): **{dsr:.3f}**")
    P(f"  - Pass bar = 0.95.  Verdict: {'PASS ✅ (survives deflation)' if dsr>0.95 else 'FAIL ❌ (Sharpe is explained by selection / not significant)'}\n")
    P("## PBO (CSCV)")
    P(f"- Combinatorial splits: S={S} blocks, {len(lambdas)} train/test combinations")
    P(f"- **PBO = {pbo:.2f}** (probability the in-sample-best config is below-median out-of-sample)")
    P(f"  - <0.5 good, >0.5 overfit.  Verdict: {'OK' if pbo<0.5 else 'OVERFIT ❌'}")
    P(f"- Chosen config median OOS Sharpe across {len(oos_sr_chosen)} splits: **{med_oos_chosen:.2f}** annualized\n")
    P("## Bottom line")
    verdict = (dsr>0.95 and pbo<0.5 and med_oos_chosen>0.5)
    P(f"**{'REAL EDGE — proceed to forward test' if verdict else 'NOT a real edge — do not deploy'}.** "
      f"DSR {dsr:.2f} (bar 0.95), PBO {pbo:.2f} (bar <0.5), chosen-config median OOS Sharpe {med_oos_chosen:.2f}.")
    if not verdict:
        P("\nThe attractive grid-top Sharpe was selection over 180 trials. After deflation and combinatorial "
          "cross-validation it does not hold. Consistent with the §RS_BACKTEST_RESULTS verdict and the project's "
          "prior DSR findings — RS-rank is a monitor, not a systematic edge on this data.")
    open(__file__.replace("rs_dsr.py","RS_DSR_PBO.md"),"w",encoding="utf-8").write("\n".join(out))
    print("\n".join(out))
    print("\nwrote RS_DSR_PBO.md")

if __name__=="__main__":
    main()
