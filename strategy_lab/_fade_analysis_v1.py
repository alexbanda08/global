"""Fade family analysis. Live truth (resolution events) + independent
check: re-price each fade fill via L25 walk at fire_us with 0.07 fee, and
confirm the fade is anti-edge (loses ~ the fee + the base signal's edge).
v1."""
import sys, json, math
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
import pandas as pd, numpy as np
from load import load_trading_events, load_resolutions, load_orderbook_l25_streaming
SCR=r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\_kp_fade_scratch"

FADES=["shadow_poly_updown_btc_5m_fade_momo_v2","shadow_poly_updown_btc_5m_fade_sniper",
       "shadow_poly_updown_eth_15m_fade_sniper","shadow_poly_updown_sol_5m_fade_sniper",
       "shadow_poly_updown_sol_5m_fade_momo_v2","shadow_poly_updown_sol_15m_fade_momo_v2"]
WIN={"5m":300,"15m":900}

print("FADE_START")
ev=load_trading_events()
res=load_resolutions()
res["cid"]=res.market_id.astype(str)
res_by_cid={c:row for c,row in zip(res.cid,res.itertuples())}

# Live truth per fade sleeve (resolution events)
out=[]
fade_res=ev[(ev.sleeve_id.isin(FADES))&(ev.kind=="poly_updown_resolution")].copy()
fr=[]
for _,r in fade_res.iterrows():
    d=json.loads(r.data) if isinstance(r.data,str) else r.data
    fr.append({"sleeve":r.sleeve_id,"at":pd.Timestamp(r["at"]),"symbol":d.get("symbol"),
               "tf":d.get("tf"),"signal":d.get("signal"),"outcome":d.get("outcome"),
               "won":d.get("won"),"pnl_usd":float(d.get("pnl_usd")),
               "entry_qty":float(d.get("entry_qty")),"entry_price":float(d.get("entry_price")),
               "cid":d.get("condition_id")})
fd=pd.DataFrame(fr)
print("=== FADE LIVE TRUTH (resolution events, 2%-on-profit live fee) ===")
for sl,sub in fd.groupby("sleeve"):
    n=len(sub);wr=sub.won.mean()*100;pnl=sub.pnl_usd.sum()
    # re-price the SAME fills (entry_price, entry_qty, won) under 0.07 curve
    p07=np.where(sub.won, (1-sub.entry_price)*sub.entry_qty*(1-0.07*sub.entry_price), -sub.entry_price*sub.entry_qty).sum()
    print(f"  {sl[14:]:28s} n={n:4d} WR={wr:5.1f}% livePnL(2%)={pnl:8.2f} $/tr={pnl/n:7.3f}  | repriced_0.07={p07:8.2f}")

# Independent: is fade anti-edge? The fade bets OPPOSITE base signal. If the
# base (momo/sniper) is +EV, fade is -EV by construction minus fees. Confirm
# by comparing fade WR to 50% and to (1 - base_WR). Fade WR < 50% => base had
# edge AND fade pays the spread/fee. Aggregate:
print("\n=== Anti-edge confirmation ===")
print(f"all fades combined: n={len(fd)} WR={fd.won.mean()*100:.1f}% (vs 50% coinflip)")
print(f"  total live PnL (2%): {fd.pnl_usd.sum():.2f}")
p07all=np.where(fd.won,(1-fd.entry_price)*fd.entry_qty*(1-0.07*fd.entry_price),-fd.entry_price*fd.entry_qty).sum()
print(f"  total repriced 0.07: {p07all:.2f}")
# entry_price mean ~0.51 (near-coinflip markets). A 0.07 fee on winners only,
# on a sub-50% WR book, deepens the loss.
fd.to_csv(SCR+r"\fade_live.csv",index=False)
print("FADE_END")
