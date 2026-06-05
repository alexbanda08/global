"""
16 — ETH sleeves: sweep ALL g_* columns as candidate NEW add-gates (both-half holdout),
compute MAX DRAWDOWN (base vs gated), full-period universe Apr24-May26.
"""
import pandas as pd, os, numpy as np
RES=r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical\_results"
def pnl07(vwap, won):
    vwap=np.asarray(vwap,float); won=np.asarray(won,bool); sh=5.0/np.clip(vwap,1e-3,None)
    return np.where(won, sh*(1-vwap)*(1-0.07*vwap), -sh*vwap)
def mdd(pnl_series):  # chronological cumulative; returns (MDD$, Calmar)
    c=np.cumsum(pnl_series); peak=np.maximum.accumulate(c); dd=peak-c
    m=float(dd.max()) if len(dd) else 0.0
    tot=float(c[-1]) if len(c) else 0.0
    return m, (tot/m if m>0 else float('inf'))
SLEEVES={
 "eth_cloud_ribbon_v6": ("_sniper_eth5m_v6_universe",["g_tr_above_cloud","g_ribbon_agrees","g_mp_skew_with","g_hurst_trending"],[60]),
 "eth_bb_mp_hurst_v6":  ("_sniper_eth5m_v6_universe",["g_bb_pos_with","g_mp_skew_with","g_hurst_trending","g_entry_vwap_in_band"],[60]),
 "eth_l_ema50_grandparent_v8":("_sniper_eth5m_v8_universe",["g_tr_above_ema50","g_hurst_trending","g_grandparent_trend_with"],[60]),
}
def both_half_lift(f, mask):
    f=f.sort_values("fire_us"); mid=len(f)//2
    h1,h2=f.iloc[:mid],f.iloc[mid:]
    b=f["pnl"].mean()
    sub=f[mask.reindex(f.index).fillna(False)]
    if len(sub)<40: return None
    g=sub["pnl"].mean()
    d1=h1[mask.reindex(h1.index).fillna(False)]["pnl"].mean()-h1["pnl"].mean()
    d2=h2[mask.reindex(h2.index).fillna(False)]["pnl"].mean()-h2["pnl"].mean()
    return dict(n=len(sub), gmean=round(g,3), lift=round(g-b,3), d1=round(d1,3), d2=round(d2,3),
                both=(d1>0 and d2>0), total=round(sub["pnl"].sum(),1))
for name,(panel,gates,offs) in SLEEVES.items():
    df=pd.read_parquet(os.path.join(RES,panel+".parquet"))
    present=[g for g in gates if g in df.columns]
    m=np.ones(len(df),bool)
    for g in present: m&=df[g].fillna(False).astype(bool)
    m&=df["fire_offset_s"].isin(offs)
    f=df[m].copy().sort_values("fire_us")
    f["pnl"]=pnl07(f["entry_vwap"], f["won"].astype(bool))
    base_total=f["pnl"].sum(); base_m,base_cal=mdd(f["pnl"].values)
    # entry_vwap<=0.70 gated
    g70=f[f["entry_vwap"]<=0.70]; g70m,g70cal=mdd(g70["pnl"].values)
    print(f"\n#### {name}  base n={len(f)} WR={100*f['won'].mean():.1f}% total=${base_total:.0f} MDD=${base_m:.0f} Calmar={base_cal:.2f}")
    print(f"   +entry_vwap<=0.70: n={len(g70)} total=${g70['pnl'].sum():.0f} MDD=${g70m:.0f} Calmar={g70cal:.2f}")
    # sweep all g_* add-gates not in base
    gcands=[c for c in df.columns if c.startswith("g_") and c not in present]
    rows=[]
    for g in gcands:
        try: mask=df[g].fillna(False).astype(bool) & m
        except: continue
        sub=f[df[g].reindex(f.index).fillna(False).astype(bool)]
        if len(sub)<40: continue
        r=both_half_lift(f, df[g].astype(bool))
        if r is None or not r["both"]: continue
        mm,cal=mdd(sub["pnl"].values)
        rows.append(dict(gate=g, n=r["n"], lift=r["lift"], total=r["total"], wr=round(100*sub["won"].mean(),1),
                         mdd=round(mm,0), calmar=round(cal,2)))
    out=pd.DataFrame(rows).sort_values("total",ascending=False)
    print(f"   NEW gates (both-half +, n>=40), top by total — base Calmar {base_cal:.2f}:")
    print(out.head(12).to_string(index=False) if len(out) else "     none")
