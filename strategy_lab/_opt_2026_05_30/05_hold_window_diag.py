"""
05 — Diagnose the actual HOLD WINDOW (fire_us -> resolution) per sleeve.
Determines whether exit/hedge policies are even structurally possible.
Uses load_resolutions for authoritative slot_end, plus slug-suffix derivation,
plus L25 book timestamp span for a few slugs.
"""
import sys, os
import pandas as pd, numpy as np
ROOT=r"C:\Users\alexandre bandarra\Desktop\global"
sys.path.insert(0, os.path.join(ROOT,"data/v4/canonical"))
from load import load_resolutions, load_orderbook_l25_streaming

fr=pd.read_parquet(os.path.join(ROOT,r"strategy_lab\_opt_2026_05_30\_results\fires_resolved_all.parquet"))
fr=fr[fr.fire_us.notna()].copy()
fr["fire_s"]=fr.fire_us.astype(float)/1e6
fr["slug_suffix"]=fr.slug.astype(str).str.rsplit("-",n=1).str[-1].astype(float)
fr["win_s"]=np.where(fr.tf=="5m",300,900)
# candidate resolution boundaries
fr["res_suffix_plus_win"]=fr.slug_suffix+fr.win_s
fr["off_from_suffix"]=fr.fire_s-fr.slug_suffix

print("=== fire_us vs slug_suffix per sleeve (hold-window inference) ===")
g=fr.groupby("sleeve").agg(
    n=("fire_s","size"),
    tf=("tf","first"),
    med_off_from_suffix=("off_from_suffix","median"),
    med_fire_offset_s=("fire_offset_s","median"),
).reset_index()
# hold to (suffix+win): how many seconds between fire and that boundary
fr["hold_to_suffixwin"]=fr.res_suffix_plus_win-fr.fire_s
h=fr.groupby("sleeve").hold_to_suffixwin.median().rename("med_hold_to_(suffix+win)")
g=g.merge(h,on="sleeve")
print(g.to_string(index=False))

# Authoritative slot_end from resolutions for a sample
print("\n=== join to load_resolutions for authoritative slot_end (sample 3 sleeves) ===")
res=load_resolutions()
print("resolutions cols:", list(res.columns)[:20])
slugcol = "slug" if "slug" in res.columns else None
endcol = [c for c in res.columns if "slot_end" in c or c=="end_us" or "resolve" in c.lower()]
startcol=[c for c in res.columns if "slot_start" in c]
print("slot_end-ish cols:", endcol, "slot_start-ish:", startcol)
if slugcol and endcol:
    ec=endcol[0]
    sample=fr[fr.sleeve.isin(["sol_5m_rf_tr_partial_mid","ALL_5m_phase1_kelly","btc_15m_ema50_ema800_off600_down"])]
    m=sample.merge(res[[slugcol,ec]].drop_duplicates(slugcol),on="slug",how="left")
    m["hold_s"]=(m[ec].astype(float)-m.fire_us.astype(float))/1e6
    print(m.groupby("sleeve").agg(n=("hold_s","size"),
          med_hold_s=("hold_s","median"),
          p10=("hold_s",lambda x:np.nanpercentile(x,10)),
          p90=("hold_s",lambda x:np.nanpercentile(x,90)),
          na=("hold_s",lambda x:x.isna().sum())).to_string())

# L25 book span for 2 BTC slugs around a fire
print("\n=== L25 book ts span vs fire_us (2 BTC slugs) ===")
btc=fr[(fr.asset=="BTC")&(fr.fire_us.notna())].head(2)
if len(btc):
    slugs=set(btc.slug)
    fmin=int(btc.fire_us.min())-600_000_000; fmax=int(btc.fire_us.max())+1200_000_000
    books=load_orderbook_l25_streaming("btc",slugs=slugs,subsample_1hz=False,min_ts_us=fmin,max_ts_us=fmax)
    for _,r in btc.iterrows():
        for oc in ["Up","Down"]:
            rec=books.get((r.slug,oc))
            if rec is not None:
                ts=rec[0]
                print(f"  {r.slug} {oc} dir={r.direction}: fire_s={r.fire_s:.0f} book[{ts.min()/1e6:.0f}..{ts.max()/1e6:.0f}] nsnap={len(ts)} span_after_fire_s={(ts.max()-r.fire_us)/1e6:.0f}")
