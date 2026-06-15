#!/usr/bin/env python3
"""Pre-registered single-hypothesis test + regime gate + DSR(N=1).

HYPOTHESIS (fixed before this run; direction CORRECTED after catching the
label-swap bug in rs_backtest.py):
  Cross-sectional MOMENTUM in alt/BTC relative strength:
    weekly, dollar-neutral, LONG the K=8 strongest-RS alts, SHORT the 8 weakest,
    signal = daily RS score2 (ratio vs SMA200 + vs EMA200, 0..2),
    REGIME GATE (first-principles, untuned): trade only when BTC is in an
    uptrend (BTC close > BTC SMA50); otherwise flat. (Cross-sectional momentum
    is a risk-on/trend phenomenon -> expect it to pay when BTC trends up.)

DSR at N=1 == PSR(SR*=0): no multiple-testing deflation, because we commit to ONE
config. CAVEAT printed: the base config was originally surfaced by a 180-config
grid, so N=1 is the OPTIMISTIC bound; truly-honest N>1. We also block-bootstrap
the Sharpe CI (robust to the fat tails) and show gated vs ungated vs opposite-gate
so the gate's effect is visible (we do NOT switch to a better-looking gate).
"""
import math, os
import numpy as np, pandas as pd
from rs_backtest import load_panel

LEN=200; K=8; COST_BPS=8.0
def Phi(x): return 0.5*(1.0+math.erf(x/math.sqrt(2.0)))
def sr_daily(x):
    x=np.asarray(x,float); x=x[~np.isnan(x)]
    return 0.0 if (len(x)<5 or x.std(ddof=1)==0) else x.mean()/x.std(ddof=1)
def psr0(x):
    x=np.asarray(x,float); x=x[~np.isnan(x)]; T=len(x); sr=sr_daily(x)
    mu=x.mean(); sd=x.std(ddof=1); g3=((x-mu)**3).mean()/sd**3; g4=((x-mu)**4).mean()/sd**4
    denom=math.sqrt(max(1e-12,1-g3*sr+(g4-1)/4.0*sr*sr))
    return Phi(sr*math.sqrt(T-1)/denom), sr*math.sqrt(365), g3, g4
def mets(r):
    r=r.fillna(0.0); eq=(1+r).cumprod(); dd=float((eq/eq.cummax()-1).min())
    return dict(shp=sr_daily(r.values)*math.sqrt(365), ann=float((1+r).prod()**(365/max(len(r),1))-1),
                dd=dd, hit=float((r[r!=0]>0).mean()) if (r!=0).any() else 0.0, days=int((r!=0).sum()))

def build():
    df=load_panel()
    btc=df["BTC"]; alts=[c for c in df.columns if c!="BTC"]
    ratio=df[alts].div(btc,axis=0)
    sma=ratio.rolling(LEN).mean(); ema=ratio.ewm(span=LEN,adjust=False).mean()
    score2=(ratio>sma).astype(int)+(ratio>ema).astype(int)
    r_usd=df[alts].pct_change().shift(-1)
    regime_up=(btc>btc.rolling(50).mean())
    dates=df.index; rebal=np.arange(len(dates))%7==0
    def run(gate):
        prev=pd.Series(dtype=float); cur=pd.Series(dtype=float); rets=[]; idx=[]; expo=[]
        for i,dt in enumerate(dates):
            if i>=len(dates)-1: break
            on = True if gate is None else bool(gate.loc[dt])
            if rebal[i]:
                if not on: cur=pd.Series(dtype=float)
                else:
                    row=score2.loc[dt].dropna(); row=row[np.isfinite(row.values)]
                    if len(row)<2*K: cur=pd.Series(dtype=float)
                    else:
                        rk=row.sort_values()                       # ascending: weak..strong
                        strong=rk.index[-K:]; weak=rk.index[:K]     # EXPLICIT momentum:
                        cur=pd.concat([pd.Series(1/K,strong),pd.Series(-1/K,weak)])  # long strong, short weak
                u=prev.reindex(prev.index.union(cur.index)).fillna(0)
                v=cur.reindex(prev.index.union(cur.index)).fillna(0)
                c=(u-v).abs().sum()*COST_BPS/1e4
            else: c=0.0
            day=(cur*r_usd.loc[dt].reindex(cur.index)).sum() if len(cur) else 0.0
            rets.append(day-c); idx.append(dt); expo.append(1 if len(cur) else 0); prev=cur
        return pd.Series(rets,index=idx), np.mean(expo)
    g,eg=run(regime_up); u,eu=run(None); o,eo=run(~regime_up)
    return dict(gated=g,ungated=u,opp=o,exp_g=eg,exp_u=eu,exp_o=eo,dates=dates)

def bootstrap_sharpe(r, block=10, B=2000, seed_offsets=None):
    x=r.values; n=len(x); nb=n//block
    # deterministic block bootstrap (no RNG: cyclic shifts) — avoids banned Random
    srs=[]
    for s in range(B):
        idx=[]
        for b in range(nb):
            start=(s*7+b*13)%(n-block)
            idx.extend(range(start,start+block))
        srs.append(sr_daily(x[idx])*math.sqrt(365))
    srs=np.array(srs)
    return float(np.percentile(srs,5)), float(np.percentile(srs,50)), float(np.percentile(srs,95))

def main():
    R=build()
    g=R["gated"]; n=len(R["dates"])
    split=R["dates"][int(n*0.70)]
    mg=mets(g); mtr=mets(g[g.index<split]); mte=mets(g[g.index>=split])
    p,ann,g3,g4=psr0(g.values)
    lo,med,hi=bootstrap_sharpe(g)
    out=[]; P=out.append
    P("# Pre-registered RS-MOMENTUM + BTC-regime gate — DSR(N=1)\n")
    P("**Hypothesis (single, pre-committed):** weekly dollar-neutral, LONG 8 strongest-RS alts / "
      "SHORT 8 weakest (signal=daily RS score2), traded ONLY when BTC>SMA50 (uptrend). "
      "Direction corrected after catching the rs_backtest.py label-swap.\n")
    P("## Result — gated config")
    P(f"- Sharpe (full): **{mg['shp']:.2f}** ann · ann return {mg['ann']*100:.1f}% · maxDD {mg['dd']*100:.0f}% · "
      f"hit {mg['hit']*100:.0f}% · time-in-market {R['exp_g']*100:.0f}%")
    P(f"- Train Sharpe {mtr['shp']:.2f} · Test (OOS) Sharpe {mte['shp']:.2f}")
    P(f"- Return skew {g3:.2f}, kurtosis {g4:.2f}")
    P(f"- **DSR at N=1 (= PSR vs 0): {p:.3f}**  — bar 0.95 → {'PASS ✅' if p>0.95 else 'FAIL'}")
    P(f"- Block-bootstrap Sharpe 90% CI: **[{lo:.2f}, {hi:.2f}]** (median {med:.2f}) → "
      f"{'CI excludes 0' if lo>0 else 'CI includes 0 (not robust)'}\n")
    P("## Does the gate help? (gated vs ungated vs opposite gate — NOT re-selected)")
    P("| variant | Sharpe ann | maxDD | time-in-mkt |")
    P("|---|---|---|---|")
    for name,key,ex in [("gated (BTC up) — REGISTERED","gated","exp_g"),("ungated (always)","ungated","exp_u"),("opposite (BTC down)","opp","exp_o")]:
        m=mets(R[key]); P(f"| {name} | {m['shp']:.2f} | {m['dd']*100:.0f}% | {R[ex]*100:.0f}% |")
    P("\n## Honest caveats")
    P("- **N=1 is optimistic.** The base config came from a 180-config grid (its DSR there was 0.24). True "
      "pre-registration means committing BEFORE any scan; this is the upper bound, not proof.")
    P("- Survivorship (listed coins only), flat 8bps cost (no HL funding/slippage), 2.7y span only.")
    P("- The proper next gate is a fresh **forward** period or longer survivorship-free history — not another scan.")
    # verdict
    passed = (p>0.95 and lo>0 and mte['shp']>0.5)
    P(f"\n## Verdict: {'Holds as a single hypothesis — promote to a forward/OOS shadow test (do NOT scale yet).' if passed else 'Does not clear the bar even as N=1 — shelve.'}")
    open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"RS_PREREG_DSR.md"),"w",encoding="utf-8").write("\n".join(out))
    # ascii-safe console
    print("\n".join(out).encode("ascii","replace").decode())
    print("\nwrote RS_PREREG_DSR.md")

if __name__=="__main__":
    main()
