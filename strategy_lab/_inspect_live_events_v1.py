"""Inspect live trading.events for kelly/prewindow/fade shadow sleeves. v1."""
import sys, json
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
import pandas as pd
import numpy as np
pd.set_option("display.width", 200); pd.set_option("display.max_columns", 40)

from load import load_trading_events

print("LIVEEVT_START")
ev = load_trading_events()
print("kinds:", ev.kind.value_counts().head(20).to_dict())
# shadow sleeves of interest
mask = ev.sleeve_id.astype(str).str.contains("phase1_kelly|S3_prewindow|S4_prewindow|fade_momo|fade_sniper", na=False, regex=True)
sub = ev[mask].copy()
print("\nshadow-sleeve events by sleeve_id x kind:")
print(sub.groupby(["sleeve_id","kind"]).size().to_string())
print("\nat range (shadow):", pd.to_datetime(sub["at"].min()), "->", pd.to_datetime(sub["at"].max()))
# Look at one resolution row's data JSON to understand schema
res = sub[sub.kind.astype(str).str.contains("resolution", na=False)]
print("\nresolution kinds present:", res.kind.unique().tolist() if len(res) else "NONE")
if len(res):
    r0 = res.iloc[0]
    print("sample sleeve_id:", r0.sleeve_id, "at:", pd.to_datetime(r0["at"]))
    d = json.loads(r0.data) if isinstance(r0.data, str) else r0.data
    print("data keys:", list(d.keys()))
    print("data sample:", {k: d[k] for k in list(d.keys())[:30]})
# Also kelly signal data
sig = sub[(sub.sleeve_id.astype(str).str.contains("phase1_kelly")) & (sub.kind.astype(str).str.contains("signal"))]
print("\nkelly signal n:", len(sig))
if len(sig):
    d = json.loads(sig.iloc[0].data) if isinstance(sig.iloc[0].data, str) else sig.iloc[0].data
    print("kelly signal data keys:", list(d.keys()))
    print("kelly signal sample:", {k: d[k] for k in list(d.keys())[:40]})
print("LIVEEVT_END")
