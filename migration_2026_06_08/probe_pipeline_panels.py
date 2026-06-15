import os, datetime as dt
import pyarrow.parquet as pq
import pandas as pd
ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
RES = os.path.join(ROOT, r"data\v4\canonical\_results")


def cov(name):
    p = os.path.join(RES, name)
    if not os.path.exists(p):
        return f"{name:42s} MISSING"
    f = pq.ParquetFile(p)
    names = f.schema.names
    c = next((x for x in ("ts_us", "fire_us", "slot_start_us", "ws_s_us") if x in names), None)
    rng = ""
    if c:
        v = pd.read_parquet(p, columns=[c])[c].dropna()
        if len(v):
            lo, hi = int(v.min()), int(v.max())
            d = 1_000_000 if lo > 1e14 else 1
            rng = f"{dt.datetime.utcfromtimestamp(lo/d):%m-%d}->{dt.datetime.utcfromtimestamp(hi/d):%m-%d}"
    mt = dt.datetime.utcfromtimestamp(os.path.getmtime(p))
    return f"{name:42s} rows={f.metadata.num_rows:>9} {rng:14s} mtime={mt:%m-%d}"


for n in ["ta_indicators_1s.parquet", "regime_panel_5m.parquet", "regime_panel_5m_v2_fixed.parquet",
          "regime_panel_15m_v2_fixed.parquet", "vol_hurst_at_fire_5m.parquet", "microprice_panel.parquet",
          "_sniper_eth5m_v3_universe.parquet", "_sniper_eth5m_v6_universe.parquet",
          "master_gate_features_v2.parquet"]:
    print(cov(n))

# canonical raw coverage (what we CAN rebuild over)
import sys
sys.path.insert(0, os.path.join(ROOT, "data", "v4", "canonical"))
print("\n--- canonical raw coverage (rebuild ceiling) ---")
for f, col in [("klines_1s.parquet", "time_period_start_us"), ("resolutions.parquet", None)]:
    p = os.path.join(ROOT, "data", "v4", "canonical", f)
    if os.path.exists(p):
        print(cov.__wrapped__ if False else f, os.path.getsize(p) // 1_000_000, "MB", os.path.exists(p))
