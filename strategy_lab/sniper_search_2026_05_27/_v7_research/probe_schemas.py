"""Probe panel schemas for V7 research."""
import pandas as pd
from datetime import datetime, timezone

panels = {
    "microprice_btc": r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/microprice_2026_05_26/micro_price_panel_btc.parquet",
    "microprice_eth": r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/microprice_2026_05_26/micro_price_panel_eth.parquet",
    "microprice_sol": r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/microprice_2026_05_26/micro_price_panel_sol.parquet",
    "rf_1s": r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/range_filter_1s.parquet",
    "tr_1s": r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/traders_reality_1s.parquet",
    "regime_5m": r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/regime_panel_5m_v2_fixed.parquet",
    "regime_15m": r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/regime_panel_15m_v2_fixed.parquet",
}

for name, p in panels.items():
    try:
        df = pd.read_parquet(p)
        print(f"=== {name} ===")
        print(f"  rows: {len(df):,}")
        print(f"  cols ({len(df.columns)}): {list(df.columns)}")
        ts_cols = [c for c in df.columns if 'ts' in c.lower() or '_us' in c.lower() or 'time' in c.lower()]
        print(f"  ts cols: {ts_cols[:5]}")
        asset_cols = [c for c in df.columns if 'asset' in c.lower() or 'symbol' in c.lower()]
        print(f"  asset cols: {asset_cols[:3]}")
        if len(asset_cols):
            print(f"  asset uniq: {df[asset_cols[0]].unique()[:5]}")
        if ts_cols:
            tc = ts_cols[0]
            mn, mx = df[tc].min(), df[tc].max()
            if df[tc].dtype.kind in 'iuf' and mx > 1e15:
                mnd = datetime.fromtimestamp(mn/1e6, timezone.utc)
                mxd = datetime.fromtimestamp(mx/1e6, timezone.utc)
                print(f"  ts range ({tc}): {mnd} → {mxd}")
        print(f"  head:\n{df.head(2)}\n")
    except Exception as e:
        print(f"=== {name} FAIL ===  {e}\n")
