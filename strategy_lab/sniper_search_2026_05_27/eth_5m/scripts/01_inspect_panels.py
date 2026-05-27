"""Inspect feature panel schemas + ETH 5m coverage for joinable features."""
import pandas as pd, numpy as np
import os

R = "data/v4/canonical/_results"

panels = {
    "microprice": f"{R}/microprice_panel.parquet",
    "microstructure": f"{R}/microstructure_panel.parquet",
    "regime_5m_v2": f"{R}/regime_panel_5m_v2_fixed.parquet",
    "master_gate_v2": f"{R}/master_gate_features_v2.parquet",
    "vol_hurst_5m": f"{R}/vol_hurst_at_fire_5m.parquet",
    "hawkes": f"{R}/hawkes_panel.parquet",
    "vpin": f"{R}/vpin_panel.parquet",
    "lee_mykland": f"{R}/lee_mykland_panel.parquet",
    "ta_indicators_1s": f"{R}/ta_indicators_1s.parquet",
    "range_filter_1s": f"{R}/range_filter_1s.parquet",
    "traders_reality_1s": f"{R}/traders_reality_1s.parquet",
    "sms_5m_v2": f"{R}/sms_panel_5m_v2_fixed.parquet",
    "hybrid_5m": f"{R}/hybrid_features_5m.parquet",
}

for name, p in panels.items():
    if not os.path.exists(p):
        print(f"== {name} MISSING ({p})")
        continue
    try:
        df = pd.read_parquet(p)
        # filter ETH 5m if applicable
        sub = df
        if "asset" in df.columns:
            sub = sub[sub["asset"] == "ETH"]
        if "tf" in df.columns:
            sub = sub[sub["tf"] == "5m"]
        cols = list(df.columns)
        gcols = [c for c in cols if c.startswith("g_")]
        # figure out time column
        tcol = None
        for c in ["fire_us", "ts_us", "slot_start_us", "ws_s", "timestamp_us"]:
            if c in cols:
                tcol = c
                break
        trng = ""
        if tcol and len(sub):
            try:
                if "us" in tcol:
                    trng = f"{pd.to_datetime(sub[tcol].min(),unit='us')} -> {pd.to_datetime(sub[tcol].max(),unit='us')}"
                else:
                    trng = f"{pd.to_datetime(sub[tcol].min(),unit='s')} -> {pd.to_datetime(sub[tcol].max(),unit='s')}"
            except Exception as e:
                trng = f"ERR {e}"
        size_mb = os.path.getsize(p) / 1e6
        print(f"== {name} ({size_mb:.1f} MB) rows_total={len(df):,} eth5m={len(sub):,} cols={len(cols)} gcols={len(gcols)}")
        print(f"   tcol={tcol} {trng}")
        print(f"   first 25 cols: {cols[:25]}")
        if gcols:
            print(f"   gcols: {gcols[:30]}")
    except Exception as e:
        print(f"== {name} ERROR: {e}")
