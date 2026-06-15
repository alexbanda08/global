"""GROUND TRUTH on exit policy for the momalign BTC-5m scalp.
Re-walk L25 fine bid-path (every 2s) for the candidate fires; compare exit policies:
  pure45         : sell at bid@+45s
  stop10         : if bid ever <= entry-0.10 within 45s -> sell at (entry-0.10); else bid@+45s
  tp65           : if bid ever >= 0.65 within 45s -> sell at 0.65; else bid@+45s
  tp65_stop10    : whichever of TP/stop hits FIRST within 45s; else bid@+45s
PnL: 0.07 both legs (taker). Split IS(60%)/OOS(40%) by time. Bootstrap CI.

Candidate = midwindow cache rows: BTC 5m, offset in {30,60}, vwap<0.55, |lag| in [3,12],
sign(lag)==sign(mom30)  (the OOS-positive cell).
"""
import sys, math
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT/"strategy_lab")); sys.path.insert(0, str(ROOT/"data"/"v4"/"canonical"))
from engine_v2 import LiveMimicConfig, find_book_strict, sell_at_bid_partial  # noqa
from load import load_orderbook_l25_streaming  # noqa
cfg = LiveMimicConfig(); LAT = 85_000; STOP = 0.10; TP = 0.65; HORIZON = 45
np.random.seed(2)

C = pd.read_parquet(r"strategy_lab\directional\_results\midwindow_scalp_cache_2026_06_09.parquet")
d = C[(C.asset=="BTC")&(C.tf=="5m")&(C.offset.isin([30,60]))&(C.entry_vwap<0.55)
      &(C.abs_lag.between(3,12))&(np.sign(C.lag_bps)==np.sign(C.mom30))].copy()
d = d.sort_values("e_us").reset_index(drop=True)
print(f"candidate fires={len(d)}  slugs={d.slug.nunique()}", flush=True)

def bid_at(books, slug, tok, ts_us, shares):
    bk = find_book_strict(books, slug, tok, int(ts_us)+LAT, max_staleness_us=cfg.max_book_staleness_us)
    if bk is None: return np.nan
    bp, bs = bk.get("bp"), bk.get("bsz")
    if bp is None or not len(bp): return np.nan
    vw, fsh, _ = sell_at_bid_partial(np.asarray(bp,float), np.asarray(bs,float), shares)
    return vw if fsh>0 else np.nan

# re-walk fine path per slug-batch
recs = []
slugs = sorted(d.slug.unique())
for b0 in range(0, len(slugs), 300):
    bs = set(slugs[b0:b0+300]); sub = d[d.slug.isin(bs)]
    tmin = int(sub.e_us.min())-5_000_000; tmax = int(sub.e_us.max())+60_000_000
    books = load_orderbook_l25_streaming("btc", slugs=bs, subsample_1hz=False, min_ts_us=tmin, max_ts_us=tmax)
    for r in sub.itertuples():
        ev, sh = float(r.entry_vwap), float(r.shares); tok = r.tok
        stop_px = ev - STOP
        stop_dt = tp_dt = np.nan
        t = 0
        while t <= HORIZON:
            b = bid_at(books, r.slug, tok, int(r.e_us)+t*1_000_000, sh)
            if math.isfinite(b):
                if math.isnan(stop_dt) and b <= stop_px: stop_dt = t
                if math.isnan(tp_dt) and b >= TP: tp_dt = t
            t += 2
        b45 = bid_at(books, r.slug, tok, int(r.e_us)+HORIZON*1_000_000, sh)
        recs.append(dict(e_us=int(r.e_us), ev=ev, sh=sh, won=bool(r.won),
                         b45=b45, stop_dt=stop_dt, tp_dt=tp_dt))
    del books
F = pd.DataFrame(recs)
print(f"walked={len(F)}  have_b45={F.b45.notna().sum()}", flush=True)

def pnl(ev, sell, sh): return (sell-ev)*sh - 0.07*sh*ev*(1-ev) - 0.07*sh*sell*(1-sell)
def hold(won, ev, sh): return np.where(won, sh*(1-ev)*(1-0.07*ev), -sh*ev)

ev=F.ev.values; sh=F.sh.values; won=F.won.values.astype(bool)
b45=F.b45.values; sd=F.stop_dt.values; td=F.tp_dt.values
fb = np.where(np.isfinite(b45), pnl(ev,b45,sh), hold(won,ev,sh))   # fallback: sell @45 or hold
def policy(kind):
    sell = b45.copy()
    if kind=="pure45":
        return fb
    if kind=="stop10":
        s = np.where(np.isfinite(sd), pnl(ev, ev-STOP, sh), fb); return s
    if kind=="tp65":
        s = np.where(np.isfinite(td), pnl(ev, TP, sh), fb); return s
    if kind=="tp65_stop10":
        stop_first = np.isfinite(sd) & (~np.isfinite(td) | (sd<=td))
        tp_first   = np.isfinite(td) & (~np.isfinite(sd) | (td<sd))
        s = fb.copy()
        s = np.where(stop_first, pnl(ev, ev-STOP, sh), s)
        s = np.where(tp_first,   pnl(ev, TP, sh), s)
        return s
def boot(v,nb=5000):
    if len(v)<8: return (np.nan,np.nan)
    idx=np.random.randint(0,len(v),(nb,len(v))); return tuple(np.percentile(v[idx].mean(1),[2.5,97.5]))
def show(v,name):
    t=v.mean()/v.std(ddof=1)*np.sqrt(len(v)) if (len(v)>1 and v.std()>0) else np.nan
    lo,hi=boot(v); print(f"  {name:14s} n={len(v):3d} $/tr={v.mean():+.3f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}] {'POS' if lo>0 else '.'}")

cut=int(len(F)*0.6)
P={k:policy(k) for k in ["pure45","stop10","tp65","tp65_stop10"]}
print(f"\nstop-hit rate={np.isfinite(sd).mean():.2f}  tp-hit rate={np.isfinite(td).mean():.2f}")
for split,sl in [("ALL",slice(None)),("IS",slice(0,cut)),("OOS",slice(cut,None))]:
    print(f"\n----- {split} (n={len(ev[sl])}) -----")
    for k in P: show(P[k][sl], k)
    # paired diff stop vs pure
    diff=P["stop10"][sl]-P["pure45"][sl]; lo,hi=boot(diff)
    print(f"  stop10 - pure45: mean={diff.mean():+.3f} CI=[{lo:+.3f},{hi:+.3f}] {'stop helps' if lo>0 else ('stop hurts' if hi<0 else 'ns')}")
F.to_parquet(r"strategy_lab\directional\_results\momalign_exit_path_2026_06_09.parquet", index=False)
