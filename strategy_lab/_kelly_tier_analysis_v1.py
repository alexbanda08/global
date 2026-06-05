"""Decompose kelly edge: sizing vs base signal. Join live resolutions to
signal features via timestamp+symbol+direction. Compute per-tier WR & PnL,
and a flat-$25 counterfactual. v1."""
import sys, json
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
import pandas as pd
import numpy as np

from load import load_trading_events
SCR = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\_kp_fade_scratch"

print("KTIER_START")
ev = load_trading_events()
# Kelly resolutions
res = ev[(ev.sleeve_id=="shadow_poly_updown_ALL_5m_phase1_kelly") & (ev.kind=="poly_updown_resolution")].copy()
rr = []
for _, r in res.iterrows():
    d = json.loads(r.data) if isinstance(r.data,str) else r.data
    rr.append({"ts": pd.Timestamp(r["at"]), "symbol": d.get("symbol"), "signal": d.get("signal"),
               "won": d.get("won"), "pnl_usd": float(d.get("pnl_usd")), "entry_qty": float(d.get("entry_qty")),
               "entry_price": float(d.get("entry_price")), "tf": d.get("tf")})
rdf = pd.DataFrame(rr).sort_values("ts").reset_index(drop=True)

# Kelly fired signals (carry fair_edge_bp + kelly_mult + notional)
sig = ev[(ev.sleeve_id=="shadow_poly_updown_ALL_5m_phase1_kelly") & (ev.kind=="poly_updown_signal")].copy()
ss = []
for _, r in sig.iterrows():
    d = json.loads(r.data) if isinstance(r.data,str) else r.data
    if d.get("signal") in ("UP","DOWN"):
        ss.append({"ts": pd.Timestamp(r["at"]), "symbol": d.get("symbol"), "signal": d.get("signal"),
                   "fair_edge_bp": float(d.get("fair_edge_bp")) if d.get("fair_edge_bp") is not None else np.nan,
                   "kelly_mult": float(d.get("kelly_mult")) if d.get("kelly_mult") is not None else np.nan,
                   "kelly_rule": d.get("kelly_rule"),
                   "notional": float(d.get("kelly_notional_usd")) if d.get("kelly_notional_usd") is not None else np.nan})
sdf = pd.DataFrame(ss).sort_values("ts").reset_index(drop=True)

# Join sig->res by nearest ts within +30min, same symbol+signal.
rdf["sig_fe"]=np.nan; rdf["sig_mult"]=np.nan; rdf["sig_rule"]=None
sdf_idx = {(sym,sg): sub.sort_values("ts") for (sym,sg),sub in sdf.groupby(["symbol","signal"])}
for i,row in rdf.iterrows():
    key=(row.symbol,row.signal)
    if key not in sdf_idx: continue
    cand = sdf_idx[key]
    before = cand[(cand["ts"] <= row["ts"]) & (cand["ts"] >= row["ts"] - pd.Timedelta(minutes=30))]
    if len(before):
        m = before.iloc[-1]
        rdf.loc[i,"sig_fe"]=m.fair_edge_bp; rdf.loc[i,"sig_mult"]=m.kelly_mult; rdf.loc[i,"sig_rule"]=m.kelly_rule

matched = rdf["sig_mult"].notna().sum()
print(f"resolutions={len(rdf)} matched_to_signal={matched}")

# Derive mult from entry_qty: base ~ $25/price => qty25 = 25/price; mult = round(qty/qty25)
rdf["qty25"] = 25.0/rdf.entry_price
rdf["mult_from_qty"] = (rdf.entry_qty/rdf.qty25).round()
print("mult_from_qty dist:", rdf.mult_from_qty.value_counts(dropna=False).to_dict())

# Per-tier (use mult_from_qty as authoritative since it's in the actual fill)
print("\n=== PER-TIER LIVE (mult from entry_qty) ===")
for mlt,sub in rdf.groupby("mult_from_qty"):
    n=len(sub); wr=sub.won.mean()*100; pnl=sub.pnl_usd.sum()
    # flat-$25 counterfactual: pnl scales 1/mult (same WR, same prices, just smaller stake)
    flat_pnl = (sub.pnl_usd/mlt).sum() if mlt>0 else np.nan
    print(f"  mult={mlt:.0f}: n={n:4d} WR={wr:5.1f}%  livePnL={pnl:8.2f}  $/tr={pnl/n:7.3f}  flat25_PnL={flat_pnl:8.2f}  flat25_$/tr={flat_pnl/n:7.3f}")

# Overall flat-$25 counterfactual
tot_live = rdf.pnl_usd.sum()
tot_flat = (rdf.pnl_usd/rdf.mult_from_qty.replace(0,1)).sum()
print(f"\nTOTAL live (kelly-sized) PnL = {tot_live:.2f}  |  flat-$25 counterfactual PnL = {tot_flat:.2f}")
print(f"Overall WR = {rdf.won.mean()*100:.1f}%  n={len(rdf)}")

# WR by tier tells us if HIGH fair_edge tiers actually have higher WR (signal edge) or not
print("\n=== Is the edge in the SIGNAL (WR rises with tier) or just SIZING? ===")
for mlt,sub in rdf.groupby("mult_from_qty"):
    print(f"  mult={mlt:.0f}: WR={sub.won.mean()*100:5.1f}%  meanFE={sub.sig_fe.mean():8.1f}bp  $/tr_per_$25unit={(sub.pnl_usd/mlt/sub.entry_qty*sub.qty25).mean() if mlt>0 else float('nan'):.4f}")
rdf.to_csv(SCR+r"\kelly_tier_joined.csv", index=False)
print("KTIER_END")
