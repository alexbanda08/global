"""Inspect enriched wallet parquets for slug-mapped fills."""
import pandas as pd
from pathlib import Path

WDIR = Path(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache\0x04b6d7e9")

for f in ["trades_chain_enriched.parquet", "per_leg_chain.parquet",
          "per_leg.parquet", "markets.parquet", "fills.parquet",
          "fills_book_decoded.parquet"]:
    p = WDIR / f
    try:
        df = pd.read_parquet(p)
        print(f"\n=== {f}  rows={len(df)}")
        print(f"  cols: {list(df.columns)}")
        print(df.head(2).to_string(max_colwidth=40))
    except Exception as e:
        print(f"{f}  ERR  {e}")
