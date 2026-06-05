"""
23 — Deep-dive btc_15m_ema50_ema800_off600_down: live/shadow fire fidelity + entry-price edge analysis.
Q: are cheap DOWN entries (low entry_vwap = market says DOWN unlikely) an EDGE or a LEAK?
   For a DOWN bet, entry_vwap = market-implied P(DOWN). If realized WR > entry_vwap -> +edge in that bucket.
"""
import pandas as pd, numpy as np, json, os, collections
ROOT=r"C:\Users\alexandre bandarra\Desktop\global"
EV=os.path.join(ROOT,r"data\v4\canonical\trading_events_30d.parquet")
df=pd.read_parquet(EV, columns=["at","sleeve_id","kind","data"])
m=df.sleeve_id.str.contains("btc_15m_ema50_ema800_off600_down", na=False)
sub=df[m & (df.kind=="poly_updown_resolution")].copy()
print("sleeves matched:", sub.sleeve_id.value_counts().to_dict())
def J(d):
    if isinstance(d,dict): return d
    try: return json.loads(d)
    except: return {}
def f(x):
    try: return float(x)
    except: return np.nan
recs=[]; gatekeys=collections.Counter(); exit_types=collections.Counter()
for at,sid,data in zip(sub["at"],sub["sleeve_id"],sub["data"]):
    d=J(data)
    ge=d.get("gates_evaluated") or {}
    gatekeys.update(ge.keys())
    exit_types.update([d.get("exit_type")])
    recs.append(dict(at=pd.Timestamp(at), sleeve=sid, slug=d.get("slug"),
        direction=d.get("direction") or d.get("signal"), outcome=d.get("outcome"),
        won=bool(d.get("won")), pnl=f(d.get("pnl_usd")), entry=f(d.get("fill_vwap")),
        shares=f(d.get("fill_shares")), placed=f(d.get("placed_size_usd")),
        offset=d.get("fire_offset_s"), all_gates=d.get("all_gates_passed"),
        exit_type=d.get("exit_type"), gates=tuple(sorted(ge.keys())),
        up_v=f((d.get("l25_book_snapshot") or {}).get("up_vwap")),
        dn_v=f((d.get("l25_book_snapshot") or {}).get("dn_vwap"))))
R=pd.DataFrame(recs).sort_values("at")
print("\n=== FIDELITY ===")
print("gate keys seen (should = spec g_dir_down/g_tr_above_ema50/g_tr_above_ema800):", dict(gatekeys))
print("distinct gate-sets:", R.gates.value_counts().to_dict())
print("all_gates_passed:", R.all_gates.value_counts(dropna=False).to_dict())
print("exit_types:", dict(exit_types))
print("direction:", R.direction.value_counts().to_dict(), " offsets:", R.offset.value_counts().to_dict())

# focus on the base sleeve (hold-to-resolve), exclude _H hedge variant for clean edge read
base=R[R.sleeve.str.endswith("off600_down")].copy()
print(f"\n=== BASE sleeve (hold) n={len(base)} WR={100*base.won.mean():.1f}% total=${base.pnl.sum():.1f} mean=${base.pnl.mean():.3f} ===")
print("entry_vwap distribution:", base.entry.describe(percentiles=[.05,.1,.25,.5,.75,.9,.95]).round(3).to_dict())

print("\n=== ENTRY-PRICE BUCKETS (DOWN bet: entry=implied P(DOWN); edge = WR - entry) ===")
bins=[0,0.15,0.30,0.50,0.70,0.85,0.95,1.01]
base["bkt"]=pd.cut(base.entry,bins=bins)
g=base.groupby("bkt",observed=True).agg(n=("won","size"),wr=("won",lambda x:round(100*x.mean(),1)),
    mean_entry=("entry",lambda x:round(x.mean(),3)), mean_pnl=("pnl",lambda x:round(x.mean(),3)),
    total=("pnl",lambda x:round(x.sum(),1))).reset_index()
g["implied_pct"]=(g.mean_entry*100).round(1)
g["edge_pp"]=(g.wr-g.implied_pct).round(1)
print(g.to_string(index=False))

print("\n=== 12 CHEAPEST entries (the 'crazy' contrarian DOWN bets) ===")
ch=base.nsmallest(12,"entry")[["at","slug","entry","won","pnl","up_v","dn_v"]]
print(ch.to_string(index=False))

# optimization: entry floor sweep
print("\n=== OPTIMIZATION: entry_vwap floor (skip cheap DOWN lottery) ===")
for fl in [0.0,0.15,0.30,0.50,0.60,0.70]:
    s=base[base.entry>=fl]
    print(f"  entry>= {fl:.2f}: n={len(s):3d} WR={100*s.won.mean():.1f}% total=${s.pnl.sum():7.1f} mean=${s.pnl.mean():.3f}")
base.to_parquet(os.path.join(ROOT,r"strategy_lab\_opt_2026_05_30\_results\ema_down_fires.parquet"),index=False)
