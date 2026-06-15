"""
MID-WINDOW lag-taker POC — does the Binance->token lag edge persist past the window OPEN?
Open scalp fires at slot_start+5s. Here we fire at a GRID of offsets across the 15m window and measure $/tr
at each. If mid-window offsets also show $/tr>0 (CI>0), the lag edge is NOT open-only -> a mid-window strategy
exists that is ALSO executable on Kalshi (Kalshi market is live+deep mid-window; only the open is blocked).

Per offset t (sec after slot_start): lag = |binance-1s 5s return over [t-5s,t]|; lead=sign(ret); gate |ret|*1e4>=3.
Entry = $25 at lead best_ask (asof t+85ms, top-of-book, size-capped, spread<=0.05). Exit = SELL lead best_bid @ t+60.
Cells: ALL filled / gated entry<0.55 / gated & delta>=5. Bucketed by offset. BBO Mar30-Apr21 (clean OOS window).
CAVEAT: BBO top-of-book (no L25 walk) -> entry slightly optimistic. POC only; rigor (OOS-split+DSR) if it passes.
"""
import sys, warnings, os
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
from load import load_orderbook_bbo
CANON = ROOT / "data/v4/canonical"
SPREAD = 0.05; STAKE = 25.0; LAT_US = 85_000
COINS = os.environ.get("MW_COINS", "BTC,ETH").split(",")
OFFSETS = [5, 120, 240, 360, 480, 600, 720]   # sec after slot_start; +60 exit stays in-window (<=780<900)
WIN = ("2026-03-30", "2026-04-21")

def unified_1s(coin):
    sym = f"BINANCE_SPOT_{coin.upper()}_USDT"
    df = pd.read_parquet(CANON/"klines_1s.parquet", columns=["symbol_id","time_period_start_us","price_close"],
                         filters=[("symbol_id","==",sym)]).sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    return df.time_period_start_us.values.astype("int64"), df.price_close.values.astype(float)
def asof(ts,v,t):
    i=np.searchsorted(ts,t,"right")-1; return np.where(i>=0, v[np.clip(i,0,len(v)-1)], np.nan)
def boot(v,nb=5000):
    v=np.asarray(v)
    if len(v)<5: return (np.nan,np.nan)
    i=np.random.randint(0,len(v),(nb,len(v))); return tuple(np.percentile(v[i].mean(1),[2.5,97.5]))
def bpnl(sell,ev,sh): return (sell-ev)*sh - 0.015*sh*(ev*(1-ev)+sell*(1-sell))

res = pd.read_parquet(CANON/"resolutions_hf.parquet")
res = res[res.outcome.isin(["Up","Down"]) & (res.timeframe=="15m")].drop_duplicates("slug")
BCOLS = ["timestamp_us","slug","outcome","best_bid","best_ask","best_bid_size","best_ask_size"]
ALL=[]
lo_ts = pd.Timestamp(WIN[0],tz="UTC").value//1000; hi_ts = pd.Timestamp(WIN[1],tz="UTC").value//1000
for coin in COINS:
    d = res[(res.ticker==coin)&(res.slot_start_us>=lo_ts)&(res.slot_start_us<=hi_ts)].copy()
    if not len(d): print(f"{coin}: no slugs"); continue
    be,bc = unified_1s(coin)
    print(f"\n=== {coin} 15m OOS {WIN[0]}..{WIN[1]}: {len(d)} slots, offsets={OFFSETS} ===", flush=True)
    slugs=d.slug.tolist(); B=120
    for i in range(0,len(slugs),B):
        chunk=d.iloc[i:i+B]
        cmin=int(chunk.slot_start_us.min())-2_000_000; cmax=int(chunk.slot_end_us.max())+2_000_000
        bbo=load_orderbook_bbo(coin, slugs=set(chunk.slug), min_ts_us=cmin, max_ts_us=cmax, columns=BCOLS)
        bk={}
        for (sl,oc),g in bbo.groupby(["slug","outcome"]):
            g=g.sort_values("timestamp_us")
            bk[(sl,oc)]=(g.timestamp_us.values.astype("int64"), g.best_ask.values.astype(float),
                         g.best_bid.values.astype(float), g.best_ask_size.values.astype(float))
        for _,r in chunk.iterrows():
            ss=int(r.slot_start_us); send=int(r.slot_end_us)
            for off in OFFSETS:
                t = ss + off*1_000_000
                rt = asof(be,bc,t)/asof(be,bc,t-5_000_000) - 1.0
                if not np.isfinite(rt): continue
                db = abs(rt)*1e4
                if db < 3.0: continue
                lead = "Up" if rt>0 else "Down"
                key=(r.slug, lead)
                if key not in bk: continue
                ts,ask,bid,asz = bk[key]
                je=np.searchsorted(ts, t+LAT_US, "right")-1
                if je<0 or je>=len(ts): continue
                a0,b0,s0 = ask[je],bid[je],asz[je]
                if not(np.isfinite(a0) and np.isfinite(b0)) or (a0-b0)>SPREAD: continue
                sh=min(STAKE/a0, s0)
                if sh*a0 < STAKE*0.5: continue
                ext=min(t+60_000_000, send)
                jx=np.searchsorted(ts, ext, "right")-1
                won=(rt>0)==(r.outcome=="Up")
                sell = bid[jx] if (0<=jx<len(ts) and np.isfinite(bid[jx])) else (1.0 if won else 0.0)
                # token-lag gate: did the LEAD token already move with binance over [t-5s,t]? if not -> lagging
                jp=np.searchsorted(ts, t-5_000_000+LAT_US, "right")-1
                mid_now=(a0+b0)/2.0
                mid_prev=(ask[jp]+bid[jp])/2.0 if (0<=jp<len(ts) and np.isfinite(ask[jp]) and np.isfinite(bid[jp])) else np.nan
                tok_chg = mid_now-mid_prev   # lead token mid change over the 5s binance-move window
                lagging = np.isfinite(tok_chg) and (tok_chg <= 0.005)   # token barely moved up despite binance up-move
                ALL.append(dict(coin=coin, off=off, ev=a0, delta=db, won=won, pnl60=bpnl(sell,a0,sh),
                                tok_chg=tok_chg, lagging=bool(lagging)))
        del bbo,bk
A=pd.DataFrame(ALL)
A.to_parquet(ROOT/"strategy_lab/directional/_results/scalp_midwindow_2026_06_07.parquet")
def line(sub):
    v=sub.pnl60.values
    if len(v)<5: return f"n={len(v):4d} (few)"
    t=v.mean()/v.std(ddof=1)*np.sqrt(len(v)) if v.std()>0 else np.nan; lo,hi=boot(v)
    return f"n={len(v):4d} $/tr={v.mean():+.3f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}] won={sub.won.mean():.2f}"
print(f"\n===== $/tr BY OFFSET (pooled {'+'.join(COINS)}, 15m) =====")
print(" offset |   ALL filled                                    | GATED entry<0.55")
for off in OFFSETS:
    s=A[A.off==off]; g=s[s.ev<0.55]
    print(f"  +{off:4d}s | {line(s):46s} | {line(g)}")
print("\n  -- gated & delta>=5 by offset --")
for off in OFFSETS:
    g=A[(A.off==off)&(A.ev<0.55)&(A.delta>=5)]
    print(f"  +{off:4d}s | {line(g)}")
print("\n  -- TOKEN-LAG gate (lead token hasn't moved up yet over the 5s binance move) by offset --")
for off in OFFSETS:
    g=A[(A.off==off)&(A.lagging)]
    print(f"  +{off:4d}s | {line(g)}")
print("\n  -- TOKEN-LAG gate + entry<0.55 by offset --")
for off in OFFSETS:
    g=A[(A.off==off)&(A.lagging)&(A.ev<0.55)]
    print(f"  +{off:4d}s | {line(g)}")
print("\n  -- MID-WINDOW pooled (off>=120) lag-gated vs not --")
mid=A[A.off>=120]
print(f"  all mid            | {line(mid)}")
print(f"  mid lagging        | {line(mid[mid.lagging])}")
print(f"  mid NOT lagging    | {line(mid[~mid.lagging])}")
print(f"  mid lagging&<0.55  | {line(mid[mid.lagging&(mid.ev<0.55)])}")
print("\nREAD: if mid-window offsets (>=120) show $/tr>0 CI>0 -> lag edge persists mid-window -> Kalshi-viable strategy.")
print("If only +5s is positive and mid offsets ~0/neg -> edge is open-only (priced-in mid-window). CAVEAT: BBO top-of-book.")
