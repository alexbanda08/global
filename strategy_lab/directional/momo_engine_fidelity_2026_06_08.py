"""
ENGINE FIDELITY CHECK for btc_15m_momo_HOLD_f7: replay the EXACT canonical L25 book at each LIVE fire
(fire_us = suffix+120) and compare my $25 ask-walk vwap to live's actual fill (entry_price). If they match
per-fire -> my fill engine is faithful and live fills are real; if my walk is systematically higher -> the
L25-walk over-charges vs live ws_mirror (the source of the 0.77 vs 0.646 gap). Tests engine_v2.fill_at_book
variants (LiveMimic latency, spread off) + a raw top-of-ask vs full-$25-walk to isolate the cause.
"""
import sys, math
from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0,str(ROOT/"data/v4/canonical")); sys.path.insert(0,str(ROOT/"strategy_lab"))
from load import load_orderbook_l25_streaming
from engine_v2 import LiveMimicConfig, LegacyConfig, fill_at_book

L=pd.read_csv(ROOT/"strategy_lab/directional/_results/momo_btc15m_live_matched.csv",
              names=["slug","sig","live_entry","won","outcome"])
L=L.dropna(subset=["slug","sig","live_entry"]).copy()
L=L[L.slug.astype(str).str.match(r"^btc-updown-15m-\d+$")].copy()
L["live_entry"]=pd.to_numeric(L.live_entry,errors="coerce"); L=L.dropna(subset=["live_entry"])
L["W"]=L.slug.apply(lambda s:int(s.rsplit("-",1)[1]))
L["fire_us"]=(L.W+120)*1_000_000
L["date"]=pd.to_datetime(L.W,unit="s",utc=True).dt.date
print(f"matched live fires: {len(L)}  date {L.date.min()}..{L.date.max()}  mean live_entry={L.live_entry.mean():.3f}")

slugs=set(L.slug)
mn=int(L.W.min())*1_000_000; mx=(int(L.W.max())+1000)*1_000_000
books=load_orderbook_l25_streaming("btc",slugs=slugs,subsample_1hz=False,min_ts_us=mn,max_ts_us=mx)
print(f"L25 loaded for {len(books)} (slug,outcome) keys")

cfgL=LiveMimicConfig(); rows=[]
for r in L.itertuples(index=False):
    oc="Up" if r.sig=="UP" else "Down"
    # full $25 ask-walk with live-mimic latency, no spread reject (momo has no spread gate)
    f=fill_at_book(books,r.slug,oc,int(r.fire_us),cfg=cfgL,notional_usd=25.0,spread_filter=1.0)
    bt_vwap=float(f["vwap"]) if f else np.nan
    # raw top-of-ask at fire (level-0 ask) for comparison
    key=(r.slug,oc); top=np.nan; b0=np.nan
    if key in books:
        ts,ap,asz,bp,bsz=books[key]
        j=np.searchsorted(ts,int(r.fire_us),"right")-1
        if 0<=j<len(ts):
            top=float(ap[j][0]) if np.isfinite(ap[j][0]) else np.nan
            b0=float(bp[j][0]) if np.isfinite(bp[j][0]) else np.nan
    rows.append(dict(slug=r.slug,date=r.date,sig=r.sig,live_entry=float(r.live_entry),
                     bt_walk_vwap=bt_vwap,top_ask=top,top_bid=b0,
                     mid=(top+b0)/2 if np.isfinite(top) and np.isfinite(b0) else np.nan))
D=pd.DataFrame(rows)
D["gap_walk"]=D.bt_walk_vwap-D.live_entry
D["gap_topask"]=D.top_ask-D.live_entry
nfill=D.bt_walk_vwap.notna().sum()
print(f"\nfilled by L25 walk: {nfill}/{len(D)}")
print(f"mean live_entry   = {D.live_entry.mean():.3f}")
print(f"mean bt_walk_vwap = {D.bt_walk_vwap.mean():.3f}  (gap vs live = {D.gap_walk.mean():+.3f})")
print(f"mean top_ask      = {D.top_ask.mean():.3f}  (gap vs live = {D.gap_topask.mean():+.3f})")
print(f"mean top_bid      = {D.top_bid.mean():.3f}   mean mid = {D['mid'].mean():.3f}")
print(f"\n-- gap_walk (bt_walk - live_entry) distribution --")
print(f"  median {D.gap_walk.median():+.3f}  p10 {D.gap_walk.quantile(.1):+.3f}  p90 {D.gap_walk.quantile(.9):+.3f}")
print(f"  |gap|<0.03: {(D.gap_walk.abs()<0.03).mean()*100:.0f}%   bt within [bid,ask] of live: n/a")
print("\n-- by month (live_entry vs bt_walk_vwap vs top_ask) --")
D["ym"]=pd.to_datetime(D.date).dt.strftime("%Y-%m")
print(D.groupby("ym").agg(n=("slug","size"),live=("live_entry","mean"),
    bt_walk=("bt_walk_vwap","mean"),top_ask=("top_ask","mean"),top_bid=("top_bid","mean")).round(3).to_string())
print("\n-- worst 8 mismatches --")
print(D.reindex(D.gap_walk.abs().sort_values(ascending=False).index)[["date","sig","live_entry","bt_walk_vwap","top_ask","top_bid"]].head(8).to_string(index=False))
D.to_parquet(ROOT/"strategy_lab/directional/_results/momo_engine_fidelity_2026_06_08.parquet")
print("\nREAD: if bt_walk_vwap ~ live_entry (gap~0) -> engine faithful, live fills real. If bt_walk >> live (gap>+0.1)")
print("-> the $25 L25-walk over-charges vs live's actual fill (live got top-of-book / smaller effective size / better book).")
