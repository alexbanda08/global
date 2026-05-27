"""Verify what stake pnl_legacy_usd is computed at."""
import pandas as pd, numpy as np
df = pd.read_parquet("data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_ETH_5m_full_v3.parquet")
w = df[df["won"] == 1].head(3)
l = df[df["won"] == 0].head(3)
print("== WON sample (won=1)")
print(w[["direction","entry_vwap","won","pnl_legacy_usd"]].to_string())
print()
print("== LOST sample")
print(l[["direction","entry_vwap","won","pnl_legacy_usd"]].to_string())
print()
print("Theoretical fit at $25:")
for _, r in w.head(3).iterrows():
    v = r["entry_vwap"]; theo = (25.0 / v) * (1 - v) * 0.98
    obs = r["pnl_legacy_usd"]
    print("  WON vwap={0:.3f}  obs={1:.4f}  theo25={2:.4f}".format(v, obs, theo))
for _, r in l.head(3).iterrows():
    v = r["entry_vwap"]; obs = r["pnl_legacy_usd"]
    print("  LOST vwap={0:.3f}  obs={1:.4f}  theo25=-25".format(v, obs))
print()
print("Theoretical fit at $1:")
for _, r in w.head(3).iterrows():
    v = r["entry_vwap"]; theo = (1.0 / v) * (1 - v) * 0.98
    obs = r["pnl_legacy_usd"]
    print("  WON vwap={0:.3f}  obs={1:.4f}  theo1={2:.4f}".format(v, obs, theo))
print()
print("avg won pnl: {0:.4f}".format(df[df["won"] == 1]["pnl_legacy_usd"].mean()))
print("avg lost pnl: {0:.4f}".format(df[df["won"] == 0]["pnl_legacy_usd"].mean()))
print("WR: {0:.4f}".format(df["won"].mean()))
