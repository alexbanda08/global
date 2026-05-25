"""Inspect V2 per-cell parquet — check if per-leg PnLs exist."""
import pandas as pd
import os

base = r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical\_results\mint_and_sell_v2_btc_5m_2026_05_16"
for fn in os.listdir(base):
    p = os.path.join(base, fn)
    if fn.endswith('.parquet'):
        df = pd.read_parquet(p)
        print(f"\n=== {fn} ===")
        print("shape:", df.shape)
        print("cols:", df.columns.tolist())
        print("head 3:")
        print(df.head(3).to_string())
    elif fn.endswith('.csv'):
        df = pd.read_csv(p)
        print(f"\n=== {fn} ===")
        print("shape:", df.shape)
        print("cols:", df.columns.tolist())
        print("head:")
        print(df.head(5).to_string())
