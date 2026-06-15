"""
Per-TIMEFRAME (5m vs 15m) scalp exit config analysis.
Answers: which TF switches TP->maker-exit, which keeps pure-taker +60; keep stop-loss?; fixed exit time per TF.
Gated scalp BTC/ETH, entry_vwap<0.55. Maker fill = first BUY trade>=target in [fire,fire+60] (optimistic, no queue).
Fees: taker sell 0.07*p*(1-p)/sh ; maker rebate 0.20*0.07*p*(1-p)/sh.
"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
CANON = ROOT / "data/v4/canonical"

c = pd.read_parquet(ROOT / "strategy_lab/directional/_results/scalp_hedge_physics_cache_2026_06_03.parquet")
c = c[(c.asset.isin(["BTC", "ETH"])) & (c.filled == 1) & (c.entry_vwap < 0.55)].copy()
lf = pd.read_parquet(ROOT / "strategy_lab/lag_taker_fires_oos_2026_06_01.parquet")[["slug","direction"]].drop_duplicates("slug")
c = c.merge(lf, on="slug", how="left").dropna(subset=["direction"])
print(f"gated scalp fires (BTC/ETH, vwap<0.55) w/ direction: {len(c)}  tf={c.tf.value_counts().to_dict()}")

tk  = lambda p: 0.07 * p * (1 - p)
reb = lambda p: 0.20 * 0.07 * p * (1 - p)

# buy-trade tape per (slug,outcome) for maker-fill
recs = []
for a in ["btc","eth"]:
    ca = c[c.asset == a.upper()]
    if not len(ca): continue
    t = pd.read_parquet(CANON/"trades_polymarket"/f"{a}.parquet",
                        columns=["slug","outcome","timestamp_us","price","side"],
                        filters=[("slug","in",set(ca.slug)),("side","in",{"buy","BUY"})]).sort_values("timestamp_us")
    g = {k:(v.timestamp_us.values, v.price.values) for k,v in t.groupby(["slug","outcome"])}
    for _, r in ca.iterrows():
        ev, sh, lead, tf = r.entry_vwap, r.shares, r.direction, r.tf
        b60 = pd.to_numeric(pd.Series([r.bid_60]),errors="coerce").iloc[0]
        b60 = float(b60) if np.isfinite(b60) else (1.0 if r.won else 0.0)
        fire = int(r.fire_us)
        ts_px = g.get((r.slug, lead))
        rec = dict(tf=tf, asset=a.upper(), slug=r.slug, ev=ev, sh=sh, won=bool(r.won), b60=b60)
        rec["taker60"] = (b60-ev)*sh - tk(b60)*sh
        mk_flag = {}
        for tgt in [0.60,0.62,0.65]:
            mk = np.nan
            if ts_px is not None:
                tt,pp = ts_px; lo=np.searchsorted(tt,fire,"right"); hi=np.searchsorted(tt,fire+60_000_000,"right")
                seg=pp[lo:hi]
                if np.any(seg >= tgt-1e-9): mk = tgt
            mk_flag[tgt] = mk
            rec[f"maker_{round(tgt*100)}"] = ((mk-ev)*sh + reb(mk)*sh) if np.isfinite(mk) else ((b60-ev)*sh - tk(b60)*sh)
        # STOP-LOSS eval: bid path min over [+30,+60]; stop@ ev-0.10 -> taker-sell at stop level
        bids = [pd.to_numeric(pd.Series([r[f"bid_{k}"]]),errors="coerce").iloc[0] for k in [30,45,60]]
        bids = [x for x in bids if np.isfinite(x)]
        stop_lvl = ev - 0.10
        hit_stop = len(bids)>0 and min(bids) <= stop_lvl
        # pure +60 NO stop already = taker60. with-stop: if stop hit, exit at stop_lvl (approx) else bid_60
        for slip in [0.0, 0.03, 0.06]:   # slippage into falling book (optimistic->harsh)
            if hit_stop:
                sell = max(stop_lvl - slip, 0.01)
                rec[f"taker60_stop_s{int(slip*100)}"] = (sell-ev)*sh - tk(sell)*sh
            else:
                rec[f"taker60_stop_s{int(slip*100)}"] = rec["taker60"]
        rec["taker60_stop"] = rec["taker60_stop_s0"]
        # COMBO maker@0.60 winner-exit + stop@-0.10 loser-cut (15m best maker target)
        mk60_filled = np.isfinite(mk_flag.get(0.60, np.nan))
        if mk60_filled:
            rec["maker60_stop"] = (0.60-ev)*sh + reb(0.60)*sh
        elif hit_stop:
            sell = max(stop_lvl, 0.01); rec["maker60_stop"] = (sell-ev)*sh - tk(sell)*sh
        else:
            rec["maker60_stop"] = rec["taker60"]
        # fixed-time profile
        for k in [30,45,60,75,90,120]:
            b = pd.to_numeric(pd.Series([r[f"bid_{k}"]]),errors="coerce").iloc[0]
            b = float(b) if np.isfinite(b) else (1.0 if r.won else 0.0)
            rec[f"t{k}"] = (b-ev)*sh - tk(b)*sh
        recs.append(rec)
D = pd.DataFrame(recs)

def boot(v,nb=5000):
    v=np.asarray(v);
    if len(v)<2 or v.std()==0: return (v.mean(),v.mean())
    i=np.random.randint(0,len(v),(nb,len(v))); return tuple(np.percentile(v[i].mean(1),[2.5,97.5]))
def stat(v):
    v=np.asarray(v); t=v.mean()/v.std(ddof=1)*np.sqrt(len(v)) if v.std()>0 else float("nan"); lo,hi=boot(v)
    return v.mean(),t,lo,hi

for tf in ["5m","15m"]:
    d=D[D.tf==tf]
    print(f"\n========== TF={tf}  n={len(d)} ==========")
    print("  -- fixed-time exit profile ($/tr, t) --")
    for k in [30,45,60,75,90,120]:
        m,t,lo,hi=stat(d[f"t{k}"]); print(f"    +{k:>3}s  ${m:+.3f}  t={t:+.2f}  CI=[{lo:+.3f},{hi:+.3f}]")
    print("  -- exit policies --")
    for col,lab in [("taker60","(1) pure taker +60"),
                    ("taker60_stop_s0","(1b) taker+60 +STOP slip0"),("taker60_stop_s3","(1b) taker+60 +STOP slip3c"),
                    ("taker60_stop_s6","(1b) taker+60 +STOP slip6c"),
                    ("maker_60","(3) maker@0.60+fb"),("maker_62","(3) maker@0.62+fb"),("maker_65","(3) maker@0.65+fb"),
                    ("maker60_stop","(4) maker@0.60 + STOP combo")]:
        m,t,lo,hi=stat(d[col]); print(f"    {lab:30s} ${m:+.3f}  t={t:+.2f}  CI=[{lo:+.3f},{hi:+.3f}]")
    print("  -- paired diffs vs pure taker+60 --")
    for col in ["maker_60","maker_62","maker_65","taker60_stop_s0","taker60_stop_s3","taker60_stop_s6","maker60_stop"]:
        diff=(d[col]-d["taker60"]).values; lo,hi=boot(diff)
        sig="SIG+" if lo>0 else ("SIG-" if hi<0 else "ns")
        print(f"    {col:14s} - taker60: {diff.mean():+.4f}  CI=[{lo:+.4f},{hi:+.4f}]  {sig}")
    # stop trigger rate
    n_stop=(d["taker60_stop"]!=d["taker60"]).sum()
    print(f"  stop-loss triggered on {n_stop}/{len(d)} ({100*n_stop/len(d):.1f}%)")
