"""Reconcile live kelly signal features vs my recompute on matched slots.
Checks: does stored fair_edge_bp match the leg used for kelly_mult? What is
the live fire offset? How many live fires actually had books? v1."""
import sys, json
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
import pandas as pd, numpy as np
from load import load_trading_events
SCR=r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\_kp_fade_scratch"

print("RECON_START")
ev=load_trading_events()
sig=ev[(ev.sleeve_id=="shadow_poly_updown_ALL_5m_phase1_kelly")&(ev.kind=="poly_updown_signal")].copy()
rows=[]
for _,r in sig.iterrows():
    d=json.loads(r.data) if isinstance(r.data,str) else r.data
    if d.get("signal") in ("UP","DOWN"):
        rows.append({k:d.get(k) for k in ("tf","symbol","signal","fair_edge_bp","kelly_mult","kelly_rule",
                     "cvd_30s","macd_hist","rvol_30_300","vwap_dev_bps","fair_up","s_now","strike","tau_s")})
k=pd.DataFrame(rows)
for c in ("fair_edge_bp","kelly_mult","vwap_dev_bps","fair_up","cvd_30s","rvol_30_300","macd_hist"):
    k[c]=pd.to_numeric(k[c],errors="coerce")
print("live kelly fired n:",len(k))
# Relationship: kelly_mult tier should follow fair_edge_bp on the SIGNED leg.
print("\nstored fair_edge_bp by kelly_mult tier:")
print(k.groupby("kelly_mult").fair_edge_bp.agg(["count","mean","min","max"]).to_string())
# Is stored fair_edge_bp the UP-leg always? check sign vs direction
print("\nfair_edge_bp sign by signal direction (mean):")
print(k.groupby("signal").fair_edge_bp.mean().to_string())
# vwap_dev sign vs signal: dev>0 => UP
print("\nvwap_dev_bps sign vs signal direction:")
print(pd.crosstab(k.signal, np.sign(k.vwap_dev_bps)).to_string())
# rule distribution
print("\nkelly_rule by tier:")
print(pd.crosstab(k.kelly_mult,k.kelly_rule).to_string())
# Tier 4 requires the LEG fair_edge>3000. Recompute leg-fe from fair_up + (need entry_vwap).
# We don't have entry_vwap stored, but fair_edge_bp stored should already be leg-correct if controller flipped.
# Check: for DOWN signals, is stored fe = ((1-fair_up)-entry)? i.e. derive entry implied.
# entry_implied_UP = fair_up - fe/1e4 ; entry_implied_DOWN = (1-fair_up) - fe/1e4
k["entry_impl"]=np.where(k.signal=="UP", k.fair_up - k.fair_edge_bp/1e4, (1-k.fair_up) - k.fair_edge_bp/1e4)
print("\nimplied entry_vwap by tier (should be ~0.45-0.55 plausible prices):")
print(k.groupby("kelly_mult").entry_impl.agg(["mean","min","max"]).to_string())
print("RECON_END")
