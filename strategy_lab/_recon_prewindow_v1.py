"""Reconcile live prewindow S3/S4 fired signals: offsets, gates, feature
distributions vs my backtest. v1."""
import sys, json
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
import pandas as pd, numpy as np
from load import load_trading_events
SCR=r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\_kp_fade_scratch"

print("RECONPW_START")
ev=load_trading_events()
for sleeve,label in [("shadow_poly_updown_ALL_5m_S3_prewindow","S3"),
                     ("shadow_poly_updown_ALL_15m_S4_prewindow","S4")]:
    sig=ev[(ev.sleeve_id==sleeve)&(ev.kind=="poly_updown_signal")].copy()
    fired=[];allrows=[]
    for _,r in sig.iterrows():
        d=json.loads(r.data) if isinstance(r.data,str) else r.data
        allrows.append(d)
        if d.get("signal") in ("UP","DOWN"): fired.append(d)
    print(f"\n==== {label} ({sleeve}) ====")
    print(f"total signal events={len(allrows)}  fired(UP/DOWN)={len(fired)}")
    if allrows:
        print("entry_phase dist (all):", pd.Series([d.get('entry_phase') for d in allrows]).value_counts().to_dict())
        print("reason dist (all):", pd.Series([d.get('reason') for d in allrows]).value_counts().head(8).to_dict())
        print("data keys:", list(allrows[0].keys()))
    if fired:
        fd=pd.DataFrame(fired)
        for c in ("fair_edge_bp","vwap_dev_bps","cvd_30s","cvd_60s","macd_hist","fair_up","tau_s"):
            if c in fd: fd[c]=pd.to_numeric(fd[c],errors="coerce")
        print("fired by symbol:", fd.symbol.value_counts().to_dict())
        print("fired fair_edge_bp: mean=%.1f min=%.1f max=%.1f"%(fd.fair_edge_bp.mean(),fd.fair_edge_bp.min(),fd.fair_edge_bp.max()))
        if "vwap_dev_bps" in fd: print("fired |vwap_dev|: mean=%.2f"%fd.vwap_dev_bps.abs().mean())
        print("fired tau_s sample:", fd.tau_s.dropna().head(5).tolist() if "tau_s" in fd else "n/a")
print("RECONPW_END")
