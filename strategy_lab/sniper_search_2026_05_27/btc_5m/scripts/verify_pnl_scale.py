"""Verify pnl_legacy_usd scale in v3 fires and master_gate_features_v2."""
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(r"C:/Users/alexandre bandarra/Desktop/global")
V3 = ROOT / "data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_BTC_5m_full_v3.parquet"
MG = ROOT / "data/v4/canonical/_results/master_gate_features_v2.parquet"

v3 = pd.read_parquet(V3, columns=["pnl_legacy_usd", "won", "outcome", "direction"])
print(f"V3 BTC 5m: n={len(v3):,}")
print(f"  won mean: {v3['won'].mean():.4f}")
print(f"  pnl_legacy_usd:  mean={v3['pnl_legacy_usd'].mean():.4f}, min={v3['pnl_legacy_usd'].min():.4f}, max={v3['pnl_legacy_usd'].max():.4f}")
# When won == 0, pnl_legacy_usd values
lost = v3[v3["won"] == 0]
won = v3[v3["won"] == 1]
print(f"  LOST rows: n={len(lost):,}, pnl mean={lost['pnl_legacy_usd'].mean():.4f}, min={lost['pnl_legacy_usd'].min():.4f}, max={lost['pnl_legacy_usd'].max():.4f}")
print(f"  WON rows:  n={len(won):,}, pnl mean={won['pnl_legacy_usd'].mean():.4f}, min={won['pnl_legacy_usd'].min():.4f}, max={won['pnl_legacy_usd'].max():.4f}")
print()
print("Sample of lost pnl_legacy_usd values:", lost["pnl_legacy_usd"].head(10).tolist())
print("Sample of won pnl_legacy_usd values:", won["pnl_legacy_usd"].head(10).tolist())
print()

mg = pd.read_parquet(MG, columns=["pnl_legacy_usd", "won", "asset", "tf"])
mg = mg[(mg["asset"] == "BTC") & (mg["tf"] == "5m")]
print(f"MG BTC 5m: n={len(mg):,}")
print(f"  pnl_legacy_usd:  mean={mg['pnl_legacy_usd'].mean():.4f}")
lost_mg = mg[mg["won"] == 0]
won_mg = mg[mg["won"] == 1]
print(f"  LOST n={len(lost_mg):,}, pnl mean={lost_mg['pnl_legacy_usd'].mean():.4f}, min={lost_mg['pnl_legacy_usd'].min():.4f}, max={lost_mg['pnl_legacy_usd'].max():.4f}")
print(f"  WON  n={len(won_mg):,}, pnl mean={won_mg['pnl_legacy_usd'].mean():.4f}, min={won_mg['pnl_legacy_usd'].min():.4f}, max={won_mg['pnl_legacy_usd'].max():.4f}")
