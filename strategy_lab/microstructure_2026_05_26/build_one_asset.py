"""Build per-asset micro panel (call with asset as argv)."""
import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from build_micro_panel import process_asset, OUT_DIR, WORK
import pandas as pd

if __name__ == "__main__":
    asset = sys.argv[1].upper()
    print(f"START: {asset}", flush=True)
    fr5 = pd.read_parquet(OUT_DIR / "hybrid_fire_universe_5m.parquet")
    fr15 = pd.read_parquet(OUT_DIR / "hybrid_fire_universe_15m.parquet")
    fires = pd.concat([fr5, fr15], ignore_index=True)
    sub = fires[fires.asset == asset].copy()
    df = process_asset(asset, sub)
    out_p = WORK / f"micro_panel_{asset.lower()}.parquet"
    df.to_parquet(out_p)
    print(f"DONE: saved {out_p} ({len(df)} rows)", flush=True)
