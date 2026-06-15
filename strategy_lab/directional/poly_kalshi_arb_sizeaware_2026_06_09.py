"""GAP #2: Poly x Kalshi 15m deep-dip arb — SIZE-AWARE fill check.
The signal (set-cost<0.95) is already CI>0; the open question is FILL DEPTH.
Kalshi ask depth via complementarity (canonical best-level sizes):
  buy Kalshi NO  (costA leg) lifts the YES bid book -> fillable contracts = yes_bid_size
  buy Kalshi YES (costB leg) lifts the NO  bid book -> fillable contracts = no_bid_size
Poly leg fill = L25 ask0 size (shares). A dip is FILLABLE if min(poly_units, kalshi_units) >= THRESH (~$5).
"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
from load import load_resolutions, load_orderbook_l25_streaming
CANON = ROOT / "data/v4/canonical"
THRESH_UNITS = 5.0      # ~$5 (1 contract/share ~ $0.5-1). DIP cost threshold:
DIP = 0.95

km = pd.read_parquet(CANON / "kalshi_markets.parquet")
ko = pd.read_parquet(CANON / "kalshi_orderbook.parquet").dropna(subset=["yes_ask", "no_ask"])
km = km[km.status == "finalized"].copy(); km["A"] = km.asset
res = load_resolutions(assets=["BTC","ETH","SOL"], timeframes=["15m"])
res = res[res.outcome.isin(["Up","Down"])].drop_duplicates("slug"); res["min_key"]=(res.slot_start_us//60_000_000)
rows=[]
for a in ["BTC","ETH","SOL"]:
    kma=km[km.A==a].copy(); kma["min_key"]=(kma.open_time_us//60_000_000); rr=res[res.ticker==a]
    rows.append(kma.merge(rr[["slug","slot_start_us","slot_end_us","outcome","min_key"]],on="min_key",how="inner"))
M=pd.concat(rows,ignore_index=True); M["kal_up"]=(M.result=="yes"); M["poly_up"]=(M.outcome=="Up")
print(f"matched finalized windows={len(M)}", flush=True)

ko=ko.sort_values("time_us"); kidx={mt:g for mt,g in ko.groupby("market_ticker")}
recs=[]
for a in ["BTC","ETH","SOL"]:
    Ma=M[M.A==a]; slugs=set(Ma.slug)
    if not slugs: continue
    books=load_orderbook_l25_streaming(a.lower(), slugs=slugs, subsample_1hz=True)
    for _,r in Ma.iterrows():
        kq=kidx.get(r.market_ticker)
        if kq is None or not len(kq): continue
        bu=books.get((r.slug,"Up")); bd=books.get((r.slug,"Down"))
        if bu is None or bd is None: continue
        ut,uap,uasz=bu[0],bu[1][:,0],bu[2][:,0]; dt,dap,dasz=bd[0],bd[1][:,0],bd[2][:,0]
        kt=kq.time_us.values; kya=kq.yes_ask.values; kna=kq.no_ask.values
        kyb=kq.yes_bid_size.values; knb=kq.no_bid_size.values   # complementary ask depth
        win=(kt>=r.slot_start_us)&(kt<=r.slot_end_us)
        kt,kya,kna,kyb,knb=kt[win],kya[win],kna[win],kyb[win],knb[win]
        if not len(kt): continue
        iu=np.clip(np.searchsorted(ut,kt,"right")-1,0,len(uap)-1); idn=np.clip(np.searchsorted(dt,kt,"right")-1,0,len(dap)-1)
        ok=(np.searchsorted(ut,kt,"right")>0)&(np.searchsorted(dt,kt,"right")>0)
        pu=np.where(ok,uap[iu],np.nan); pus=np.where(ok,uasz[iu],0.0)
        pdn=np.where(ok,dap[idn],np.nan); pds=np.where(ok,dasz[idn],0.0)
        costA=pu+kna; costB=kya+pdn                       # A: polyUp+kalshiNo ; B: kalshiYes+polyDown
        # fillable units per leg-set (min of the two legs' depth)
        fillA=np.minimum(pus, knb)     # poly Up ask shares ; kalshi No fill = no_bid_size(=knb)? see note
        fillB=np.minimum(pds, kyb)
        # NOTE complementarity: buy Kalshi NO lifts YES-bid -> yes_bid_size(kyb); buy Kalshi YES lifts NO-bid -> no_bid_size(knb)
        fillA=np.minimum(pus, kyb); fillB=np.minimum(pds, knb)
        cbest=np.where(costA<=costB,costA,costB); fbest=np.where(costA<=costB,fillA,fillB)
        m=np.isfinite(cbest)
        cbest,fbest=cbest[m],fbest[m]
        if not len(cbest): continue
        dip=cbest<DIP
        recs.append(dict(asset=a,slug=r.slug,mt=r.market_ticker,poly_up=bool(r.poly_up),kal_up=bool(r.kal_up),
            n=len(cbest), n_dip=int(dip.sum()),
            dip_fill_med=float(np.median(fbest[dip])) if dip.any() else np.nan,
            dip_fill_max=float(fbest[dip].max()) if dip.any() else np.nan,
            dip_fillable_5=int((dip & (fbest>=THRESH_UNITS)).sum()),
            min_cost=float(cbest.min())))
    del books
D=pd.DataFrame(recs)
D.to_parquet(ROOT/"strategy_lab/directional/_results/poly_kalshi_arb_sizeaware_2026_06_09.parquet")
print(f"\nwindows w/ both books={len(D)}")
wd=D[D.n_dip>0]
print(f"windows that EVER dip <{DIP}: {len(wd)} ({len(wd)/len(D)*100:.0f}%)")
print(f"  of dips, median fillable units: {wd.dip_fill_med.median():.1f}  (THRESH={THRESH_UNITS})")
print(f"  windows with >=1 dip fillable at >= {THRESH_UNITS} units: {(wd.dip_fillable_5>0).sum()} ({(wd.dip_fillable_5>0).mean()*100:.0f}% of dipping windows)")
tot_dip=D.n_dip.sum(); tot_fill=D.dip_fillable_5.sum()
print(f"  total dip quote-events={tot_dip}  fillable(>= {THRESH_UNITS}u)={tot_fill} ({tot_fill/max(tot_dip,1)*100:.0f}%)")
print(f"\nVERDICT: arb is real-capacity if a meaningful %% of dips are fillable at >= {THRESH_UNITS} units; phantom if ~0%.")
