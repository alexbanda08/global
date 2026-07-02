"""T3 — SHORT-SIDE overround scan (never run). Mirror of the dead long-side (sum_ask<1).
Short side = sum of best BIDS > 1: you can split USDC->Up+Down ($1, fee-free mint) then SELL both
at their bids; if bid_up+bid_down > 1 + costs you lock the overround. Paper appendix H: 'more profit'.
Measure FREQUENCY (sum_bid>1), MAGNITUDE (excess), and DEPTH ($ sellable) on full-book we already have.
Pre-registered: raw>1.00 and >1.02 (clears ~2% round-trip). Compare vs long-side sum_ask<1.00/<0.98 (sanity).
Up/Down are snapshotted together (same ts) -> align by asof. Hang-proof, bounded sample.
"""
import sys, time
sys.path.insert(0, "data/v4/canonical")
import numpy as np, pandas as pd
from load import load_resolutions, load_orderbook_l25_streaming

NPC=int(sys.argv[1]) if len(sys.argv)>1 else 25  # slugs per (coin,tf) cell
t0=time.time()

def best_bid(bp_row, bs_row):
    for i in range(bp_row.shape[0]):
        if np.isfinite(bp_row[i]) and bp_row[i]>0 and np.isfinite(bs_row[i]) and bs_row[i]>0:
            return bp_row[i], bs_row[i]
    return np.nan, 0.0
def best_ask(ap_row, asz_row):
    for i in range(ap_row.shape[0]):
        if np.isfinite(ap_row[i]) and ap_row[i]>0 and np.isfinite(asz_row[i]) and asz_row[i]>0:
            return ap_row[i], asz_row[i]
    return np.nan, 0.0

rows=[]
for coin in ["BTC","ETH","SOL"]:
    res=load_resolutions(assets=[coin]).drop_duplicates("slug")
    res=res[res.slot_start_us>=int(pd.Timestamp("2026-05-15",tz="UTC").timestamp()*1e6)]
    sample=[]
    for tf in ["15m","5m"]:
        d=res[res.timeframe==tf].sort_values("slot_start_us"); sl=d.slug.tolist()
        step=max(1,len(sl)//NPC); sample+=[(s,tf) for s in sl[::step][:NPC]]
    smap=dict(zip(res.slug,res.slot_start_us))
    bks=load_orderbook_l25_streaming(coin.lower(),slugs={s for s,_ in sample},subsample_1hz=False)
    print(f"{coin}: {len(sample)} slugs, {len(bks)} series t={time.time()-t0:.0f}s",flush=True)
    for slug,tf in sample:
        ru=bks.get((slug,"Up")); rd=bks.get((slug,"Down"))
        if ru is None or rd is None or len(ru[0])<5 or len(rd[0])<5: continue
        tu,apu,aszu,bpu,bsu=ru; td,apd,aszd,bpd,bsd=rd
        tu=tu.astype(np.int64); td=td.astype(np.int64)
        for i in range(len(tu)):
            j=int(np.searchsorted(td,tu[i],"right"))-1
            if j<0: continue
            bbu,szbu=best_bid(bpu[i],bsu[i]); bbd,szbd=best_bid(bpd[j],bsd[j])
            bau,szau=best_ask(apu[i],aszu[i]); bad,szad=best_ask(apd[j],aszd[j])
            if np.isfinite(bbu) and np.isfinite(bbd):
                # sellable: how many $ you could sell into both bids (limited by min share depth)
                sell_sh=min(szbu,szbd); sumbid=bbu+bbd
                rows.append(dict(coin=coin,tf=tf,sumbid=sumbid,sell_sh=sell_sh,
                                 sumask=(bau+bad) if (np.isfinite(bau) and np.isfinite(bad)) else np.nan,
                                 buy_sh=min(szau,szad) if (np.isfinite(bau) and np.isfinite(bad)) else 0.0))
R=pd.DataFrame(rows)
print("="*72)
print(f"snaps {len(R):,} | t={time.time()-t0:.0f}s")
def report(g,lab):
    n=len(g)
    if n==0: print(f"  {lab}: (none)"); return
    sb=g.sumbid.to_numpy()
    p1=100*(sb>1.0).mean(); p102=100*(sb>1.02).mean()
    exc=sb[sb>1.0]-1.0
    # depth $ when >1.02: excess * sellable shares (shares ~= $ at price~ , notional = sell_sh*1 since pair pays $1)
    hot=g[g.sumbid>1.02]
    dep=(hot.sumbid-1.0)*hot.sell_sh  # $ locked per pair-set * sets sellable
    sa=g.sumask.to_numpy(); sa=sa[np.isfinite(sa)]
    pa1=100*(sa<1.0).mean() if len(sa) else 0; pa98=100*(sa<0.98).mean() if len(sa) else 0
    print(f"  {lab}: n={n:>6,} | SHORT sum_bid>1.00 {p1:5.1f}% >1.02 {p102:4.1f}% medExc {np.median(exc) if len(exc) else 0:+.3f} "
          f"medDepth$@>1.02 {np.median(dep) if len(dep) else 0:5.1f} | LONG sum_ask<1.00 {pa1:4.1f}% <0.98 {pa98:4.1f}%")
print("PER COIN x TF (short-side sum_bid vs long-side sum_ask):")
for coin in ["BTC","ETH","SOL"]:
    for tf in ["5m","15m"]:
        report(R[(R.coin==coin)&(R.tf==tf)], f"{coin} {tf}")
print("\nPOOLED:")
report(R,"ALL")
hot=R[R.sumbid>1.02]
if len(hot):
    print(f"\nsum_bid>1.02 episodes: {len(hot):,} snaps; median sellable {hot.sell_sh.median():.0f} sh; "
          f"median $ locked/set {(hot.sumbid-1).median():.3f}; est $/hot-snap {((hot.sumbid-1)*hot.sell_sh).median():.1f}")
print(f"\nVERDICT: short-side is {'WORTH a fill-realism test' if 100*(R.sumbid>1.02).mean()>2 else 'RARE — likely dead like long-side'} "
      f"(>1.02 freq {100*(R.sumbid>1.02).mean():.1f}%)")
print(f"t={time.time()-t0:.0f}s")
