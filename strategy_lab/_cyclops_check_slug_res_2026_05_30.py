"""Confirm slug format + resolution window coverage vs cyclops dates."""
import sys, io
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from load import load_resolutions
import pandas as pd, datetime as dt
print("CHECK_SLUG_RES_2026_05_30 OUTPUT")
res = load_resolutions(assets=["BTC"], timeframes=["5m"])
print("BTC 5m resolutions rows:", len(res))
print("cols:", list(res.columns))
print("\nsample slugs:")
for s in res["slug"].head(5):
    print("  ", s)
res = res.copy()
res["slot_dt"] = pd.to_datetime(res["slot_start_us"], unit="us", utc=True)
print("\nslot_start range:", res["slot_dt"].min(), "->", res["slot_dt"].max())
print("outcome dist:", res["outcome"].value_counts().to_dict())
# verify slug suffix == slot_start_us/1e6
res["suf"] = res["slug"].str.rsplit("-", n=1).str[-1].astype("int64")
res["ss_s"] = res["slot_start_us"] // 1_000_000
print("suffix==slot_start_s match:", (res["suf"]==res["ss_s"]).mean())
print("strike/settle cols present:", "strike_price" in res.columns, "settlement_price" in res.columns)
