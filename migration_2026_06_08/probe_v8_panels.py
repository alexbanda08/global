import os, datetime as dt
import pyarrow.parquet as pq
import pandas as pd
ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
RES = os.path.join(ROOT, r"data\v4\canonical\_results")


def span(p):
    try:
        f = pq.ParquetFile(p)
        n = f.metadata.num_rows
        names = f.schema.names
        c = next((x for x in ("ws_s_us", "fire_us", "ts_us", "slot_start_us") if x in names), None)
        rng = ""
        if c:
            v = pd.read_parquet(p, columns=[c])[c].dropna()
            if len(v):
                lo, hi = int(v.min()), int(v.max())
                div = 1_000_000 if lo > 1e14 else 1
                rng = f"{dt.datetime.utcfromtimestamp(lo/div):%Y-%m-%d}..{dt.datetime.utcfromtimestamp(hi/div):%Y-%m-%d}[{c}]"
        return n, rng, names
    except Exception as e:
        return None, f"ERR {str(e)[:60]}", []


print("=== key panels for eth_5m v8/v10 reproduction ===")
for name in ["_sniper_eth5m_v8_universe.parquet", "_sniper_eth5m_v7_universe.parquet",
             "regime_panel_5m_v2_fixed.parquet", "regime_panel_15m_v2_fixed.parquet",
             "microprice_panel.parquet", "dirscan_eth_5m.parquet", "dirscan_eth_15m.parquet"]:
    p = os.path.join(RES, name)
    if os.path.exists(p):
        n, rng, _ = span(p)
        mt = dt.datetime.utcfromtimestamp(os.path.getmtime(p))
        print(f"  {name:42s} rows={n} {rng} mtime={mt:%Y-%m-%d}")
    else:
        print(f"  {name:42s} MISSING")

p = os.path.join(RES, "_sniper_eth5m_v8_universe.parquet")
if os.path.exists(p):
    cols = pq.ParquetFile(p).schema.names
    need = ["g_tr_above_ema50", "g_hurst_trending", "g_grandparent_trend_with",
            "g_sms_no_liquidity_above", "direction", "won", "pnl", "pnl_usd",
            "entry_vwap", "fill_vwap", "ws_s_us", "slug", "offset_s", "offset"]
    print("\n=== v8 universe needed columns ===")
    for c in need:
        print(f"  {c:32s} {'YES' if c in cols else 'no'}")
    print("\n  g_ cols:", [c for c in cols if c.startswith("g_")][:20])
    print("  all non-g cols:", [c for c in cols if not c.startswith("g_")][:40])
