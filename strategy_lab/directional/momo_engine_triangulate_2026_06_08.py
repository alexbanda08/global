"""
TRIANGULATE the true fill for btc_15m_momo_HOLD_f7 live fires: compare
  (1) live entry_price (what the live PnL used)
  (2) L25 book ask at fire_us (+ time-gap to nearest snapshot, to catch stale reads)
  (3) ACTUAL executed Polymarket trades near W+120 (ground truth of what the token really traded at)
If live_entry tracks the real traded price -> live fills real. If live_entry is ~0.50 regardless of the
real traded price -> the live entry_price (and thus the live PnL) is a placeholder artifact.
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0,str(ROOT/"data/v4/canonical")); sys.path.insert(0,str(ROOT/"strategy_lab"))
from load import load_orderbook_l25_streaming
CANON=ROOT/"data/v4/canonical"

L=pd.read_csv(ROOT/"strategy_lab/directional/_results/momo_btc15m_live_matched.csv",
              names=["slug","sig","live_entry","won","outcome"])
L=L[L.slug.astype(str).str.match(r"^btc-updown-15m-\d+$")].copy()
L["live_entry"]=pd.to_numeric(L.live_entry,errors="coerce"); L=L.dropna(subset=["live_entry"])
L["W"]=L.slug.apply(lambda s:int(s.rsplit("-",1)[1])); L["fire_us"]=(L.W+120)*1_000_000
L["oc"]=np.where(L.sig=="UP","Up","Down")
print(f"matched fires: {len(L)}  {pd.to_datetime(L.W.min(),unit='s')}..{pd.to_datetime(L.W.max(),unit='s')}")
slugs=set(L.slug)

# (2) L25 ask + snapshot gap
books=load_orderbook_l25_streaming("btc",slugs=slugs,subsample_1hz=False,
        min_ts_us=int(L.W.min())*1_000_000,max_ts_us=(int(L.W.max())+1000)*1_000_000)
# (3) actual executed trades on the signal token near W+120
tr=pd.read_parquet(CANON/"trades_polymarket"/"btc.parquet",
        columns=["slug","outcome","timestamp_us","price"],
        filters=[("slug","in",slugs)])
print(f"L25 keys {len(books)}; poly trades rows {len(tr)}")
trg={k:(g.timestamp_us.values.astype('int64'),g.price.values.astype(float)) for k,g in tr.groupby(["slug","outcome"])}

rows=[]
for r in L.itertuples(index=False):
    key=(r.slug,r.oc); l25=np.nan; gap=np.nan
    if key in books:
        ts,ap,asz,bp,bsz=books[key]; j=np.searchsorted(ts,int(r.fire_us),"right")-1
        if 0<=j<len(ts):
            l25=float(ap[j][0]); gap=abs(int(ts[j])-int(r.fire_us))/1e6
    # actual traded price in [W+60, W+180] window on the signal token
    real=np.nan; nrt=0
    if key in trg:
        tt,pp=trg[key]; lo=np.searchsorted(tt,(r.W+60)*1_000_000,"left"); hi=np.searchsorted(tt,(r.W+180)*1_000_000,"right")
        seg=pp[lo:hi]; seg=seg[np.isfinite(seg)]
        if len(seg): real=float(np.median(seg)); nrt=len(seg)
    rows.append(dict(slug=r.slug,date=str(pd.to_datetime(r.W,unit='s').date()),sig=r.sig,
                     live_entry=float(r.live_entry),l25_ask=l25,l25_gap_s=gap,real_trade=real,n_real=nrt))
D=pd.DataFrame(rows)
print(f"\nfires with real poly trades in [W+60,W+180]: {D.real_trade.notna().sum()}/{len(D)}")
print(f"mean live_entry={D.live_entry.mean():.3f}  mean l25_ask={D.l25_ask.mean():.3f}  mean real_trade={D.real_trade.mean():.3f}")
print(f"L25 snapshot gap to fire: median {D.l25_gap_s.median():.0f}s  p90 {D.l25_gap_s.quantile(.9):.0f}s  (large => stale read)")
print("\n-- correlation of live_entry with the REAL traded price --")
sub=D.dropna(subset=["real_trade"])
if len(sub)>5:
    print(f"  corr(live_entry, real_trade) = {np.corrcoef(sub.live_entry,sub.real_trade)[0,1]:.3f}")
    print(f"  corr(l25_ask,    real_trade) = {np.corrcoef(sub.dropna(subset=['l25_ask']).l25_ask,sub.dropna(subset=['l25_ask']).real_trade)[0,1]:.3f}" if sub.l25_ask.notna().sum()>5 else "")
    print(f"  mean |live_entry - real_trade| = {(sub.live_entry-sub.real_trade).abs().mean():.3f}")
    print(f"  mean |l25_ask   - real_trade| = {(sub.dropna(subset=['l25_ask']).l25_ask-sub.dropna(subset=['l25_ask']).real_trade).abs().mean():.3f}")
print("\n-- sample: live_entry vs real traded price vs L25 (where real trades exist), sorted by |live-real| --")
sub=sub.assign(d=(sub.live_entry-sub.real_trade).abs()).sort_values("d",ascending=False)
print(sub[["date","sig","live_entry","real_trade","l25_ask","l25_gap_s","n_real"]].head(12).to_string(index=False))
D.to_parquet(ROOT/"strategy_lab/directional/_results/momo_engine_triangulate_2026_06_08.parquet")
print("\nREAD: if live_entry tracks real_trade (corr>0.8, |gap| small) -> live fills REAL. If live_entry~0.50 flat")
print("while real_trade swings (low corr) -> live entry_price is a PLACEHOLDER and the live PnL is fictitious.")
