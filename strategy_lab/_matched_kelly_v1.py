"""Match my kelly backtest fires to live kelly fires on the SAME slot, and
compare fair_edge_bp / direction / entry_vwap to pin the divergence source.
Restrict bt to slots that LIVE actually evaluated (5m, ALL assets), and
compare the fire decision + PnL on the intersection. v1."""
import sys, json, math
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
import pandas as pd, numpy as np
from load import load_trading_events, load_resolutions
SCR=r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\_kp_fade_scratch"

print("MATCH_START")
# Live kelly resolutions carry condition_id -> map to canonical slug + slot_start
ev=load_trading_events()
res=load_resolutions(); res["cid"]=res.market_id.astype(str)
cid2slug=dict(zip(res.cid,res.slug)); cid2ss=dict(zip(res.cid,res.slot_start_us))

kres=ev[(ev.sleeve_id=="shadow_poly_updown_ALL_5m_phase1_kelly")&(ev.kind=="poly_updown_resolution")].copy()
live=[]
for _,r in kres.iterrows():
    d=json.loads(r.data) if isinstance(r.data,str) else r.data
    cid=d.get("condition_id")
    live.append({"cid":cid,"slug":cid2slug.get(cid),"symbol":d.get("symbol"),"signal":d.get("signal"),
                 "won":d.get("won"),"pnl_usd":float(d.get("pnl_usd")),"entry_price":float(d.get("entry_price")),
                 "entry_qty":float(d.get("entry_qty"))})
L=pd.DataFrame(live)
L_slugs=set(L.slug.dropna())
print(f"live kelly resolved slugs: {len(L_slugs)}")

# My bt
bt=pd.read_csv(SCR+r"\bt_kelly_prewindow.csv")
btk=bt[bt.sleeve=="kelly"].copy()
bt_slugs=set(btk.slug)
print(f"bt kelly fired slugs: {len(bt_slugs)}")
inter=L_slugs & bt_slugs
print(f"intersection (both fired same slug): {len(inter)}")
print(f"live-only (bt missed): {len(L_slugs-bt_slugs)}  bt-only (live didn't fire): {len(bt_slugs-L_slugs)}")

# On intersection: do directions agree? compare entry_price (live) vs vwap (bt)
Lm=L[L.slug.isin(inter)].set_index("slug")
btm=btk[btk.slug.isin(inter)].drop_duplicates("slug").set_index("slug")
j=Lm.join(btm,lsuffix="_live",rsuffix="_bt")
dir_agree=(j.signal.str.upper()==j.direction.str.upper()).mean()
print(f"\nintersection n={len(j)}  direction agreement={dir_agree*100:.1f}%")
print(f"live entry_price mean={j.entry_price.mean():.4f}  bt vwap mean={j.vwap.mean():.4f}  (bt-live={j.vwap.mean()-j.entry_price.mean():+.4f})")
print(f"live WR={j.won_live.mean()*100:.1f}%  bt WR={j.won_bt.mean()*100:.1f}%")
print(f"live PnL(on inter)={j.pnl_usd.sum():.2f}  bt PnL_07(on inter)={j.pnl.sum():.2f}")
# mult agreement
print(f"\nmult agreement: live tier derived from qty; bt mult col")
print("MATCH_END")
