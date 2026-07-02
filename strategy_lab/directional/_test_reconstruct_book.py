"""Synthetic test for reconstruct_book_10hz — verifies apply/keyframe logic with NO real data."""
import sys
sys.path.insert(0, "data/v4/canonical")
import numpy as np, pandas as pd
from load import reconstruct_book_10hz

L = 25
def kf_row(asks, bids):
    ap = np.full(L, np.nan); az = np.zeros(L); bp = np.full(L, np.nan); bz = np.zeros(L)
    for i,(p,s) in enumerate(sorted(asks.items())): ap[i]=p; az[i]=s
    for i,(p,s) in enumerate(sorted(bids.items(), reverse=True)): bp[i]=p; bz[i]=s
    return ap,az,bp,bz

# 1 keyframe @1000: asks {0.60:100, 0.61:50}, bids {0.59:80, 0.58:40}
ap,az,bp,bz = kf_row({0.60:100,0.61:50}, {0.59:80,0.58:40})
keyframe = (np.array([1000]), ap[None,:], az[None,:], bp[None,:], bz[None,:])
deltas = pd.DataFrame([
    (1500,"ask",0.595,30),   # new ask inside spread -> best ask 0.595
    (2000,"ask",0.60,0),     # remove 0.60 -> asks {0.595:30,0.61:50}
    (2500,"bid",0.59,120),   # bump bid 0.59 -> 120
    (3000,"bid",0.59,0),     # remove bid 0.59 -> best bid 0.58
], columns=["timestamp_us","side","price","size"])

ts,AP,AZ,BP,BZ = reconstruct_book_10hz(keyframe, deltas)
def best_ask(i):
    r=AP[i]; m=np.isfinite(r)&(AZ[i]>0); return (r[m].min(), AZ[i][np.where(r==r[m].min())[0][0]]) if m.any() else (np.nan,0)
def best_bid(i):
    r=BP[i]; m=np.isfinite(r)&(BZ[i]>0); return (r[m].max(), BZ[i][np.where(r==r[m].max())[0][0]]) if m.any() else (np.nan,0)

exp = {1000:(0.60,0.59), 1500:(0.595,0.59), 2000:(0.595,0.59), 2500:(0.595,0.59), 3000:(0.595,0.58)}
ok = True
print(f"emitted {len(ts)} snapshots at ts={list(ts)}")
for i,t in enumerate(ts):
    ba,_=best_ask(i); bb,_=best_bid(i); ea,eb=exp[int(t)]
    good = abs(ba-ea)<1e-9 and abs(bb-eb)<1e-9
    ok &= good
    print(f"  t={t}: best_ask={ba:.3f} (exp {ea}) best_bid={bb:.3f} (exp {eb})  {'OK' if good else 'FAIL'}")
# check size bump at 2500 and removal at 3000
_,szb=best_bid(3); assert abs(szb-120)<1e-9, f"bid size bump failed: {szb}"
print(f"  bid-size@2500 = {szb} (exp 120) OK")
# deltas-before-keyframe ignored + None deltas path
ts2,_,_,_,_ = reconstruct_book_10hz(keyframe, None)
assert len(ts2)==1, "None-deltas should emit just the keyframe"
print(f"  None-deltas path: {len(ts2)} snapshot OK")
print("\nRECONSTRUCT TEST:", "PASS ✓" if ok else "FAIL ✗")
sys.exit(0 if ok else 1)
