"""Extract per-fire live truth + signal features for shadow sleeves.
Writes two CSVs: live resolutions (PnL truth) and kelly signal features.
v1."""
import sys, json
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
import pandas as pd
import numpy as np

from load import load_trading_events

OUT = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\maker_arb_audit"  # reuse scratch? no
OUT = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\_kp_fade_scratch"
import os; os.makedirs(OUT, exist_ok=True)

print("EXTRACT_START")
ev = load_trading_events()
SLEEVES = [
    "shadow_poly_updown_ALL_5m_phase1_kelly",
    "shadow_poly_updown_ALL_5m_S3_prewindow",
    "shadow_poly_updown_ALL_15m_S4_prewindow",
    "shadow_poly_updown_btc_5m_fade_momo_v2",
    "shadow_poly_updown_btc_5m_fade_sniper",
    "shadow_poly_updown_eth_15m_fade_sniper",
    "shadow_poly_updown_sol_5m_fade_sniper",
    "shadow_poly_updown_sol_5m_fade_momo_v2",
    "shadow_poly_updown_sol_15m_fade_momo_v2",
]

# --- RESOLUTIONS (live PnL truth) ---
res = ev[(ev.sleeve_id.isin(SLEEVES)) & (ev.kind == "poly_updown_resolution")].copy()
rows = []
for _, r in res.iterrows():
    d = json.loads(r.data) if isinstance(r.data, str) else r.data
    rows.append({
        "sleeve_id": r.sleeve_id,
        "at": r["at"],
        "event_id": r.get("event_id", None),
        "tf": d.get("tf"), "symbol": d.get("symbol"), "signal": d.get("signal"),
        "outcome": d.get("outcome"), "won": d.get("won"),
        "pnl_usd": float(d.get("pnl_usd")) if d.get("pnl_usd") is not None else None,
        "entry_qty": float(d.get("entry_qty")) if d.get("entry_qty") is not None else None,
        "entry_price": float(d.get("entry_price")) if d.get("entry_price") is not None else None,
        "condition_id": d.get("condition_id"),
        "price_source": d.get("price_source"),
        "fill_event_id": d.get("fill_event_id"),
    })
rdf = pd.DataFrame(rows)
rdf.to_csv(OUT + r"\live_resolutions.csv", index=False)
print("live_resolutions rows:", len(rdf))
print("\nPer-sleeve live truth (from resolution events):")
g = rdf.groupby("sleeve_id").agg(
    n=("pnl_usd","size"),
    wins=("won","sum"),
    wr=("won","mean"),
    pnl=("pnl_usd","sum"),
    avg_qty=("entry_qty","mean"),
    avg_px=("entry_price","mean"),
).reset_index()
g["wr"] = (g["wr"]*100).round(1)
g["pnl"] = g["pnl"].round(2)
g["dpt"] = (g["pnl"]/g["n"]).round(3)
print(g.to_string())

# --- KELLY SIGNAL FEATURES (fired only) ---
ksig = ev[(ev.sleeve_id == "shadow_poly_updown_ALL_5m_phase1_kelly") & (ev.kind == "poly_updown_signal")].copy()
krows = []
for _, r in ksig.iterrows():
    d = json.loads(r.data) if isinstance(r.data, str) else r.data
    if d.get("signal") in ("UP","DOWN"):
        krows.append({
            "at": r["at"], "tf": d.get("tf"), "symbol": d.get("symbol"),
            "signal": d.get("signal"), "fair_edge_bp": d.get("fair_edge_bp"),
            "kelly_mult": d.get("kelly_mult"), "kelly_rule": d.get("kelly_rule"),
            "kelly_notional_usd": d.get("kelly_notional_usd"),
            "cvd_30s": d.get("cvd_30s"), "macd_hist": d.get("macd_hist"),
            "rvol_30_300": d.get("rvol_30_300"), "vwap_dev_bps": d.get("vwap_dev_bps"),
            "fair_up": d.get("fair_up"), "entry_phase": d.get("entry_phase"),
        })
kdf = pd.DataFrame(krows)
kdf.to_csv(OUT + r"\kelly_fired_signals.csv", index=False)
print("\nkelly fired signals:", len(kdf))
if len(kdf):
    kdf["kelly_mult"] = pd.to_numeric(kdf["kelly_mult"], errors="coerce")
    print("kelly_mult dist:", kdf["kelly_mult"].value_counts(dropna=False).to_dict())
    print("kelly_rule dist:", kdf["kelly_rule"].value_counts(dropna=False).to_dict())
print("EXTRACT_END")
