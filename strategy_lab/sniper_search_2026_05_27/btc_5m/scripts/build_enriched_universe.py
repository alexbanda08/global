"""Build BTC 5m enriched universe.

Start with v3 fires (144,061 fires, 33d). Join master_gate_features_v2 by (slug, fire_us)
to bring in R3/R4/R5/SMS/Microprice/Vol/Hurst/Hawkes/VPIN/LM gates and features.

Output: data/v4/canonical/_results/_sniper_btc_5m_enriched.parquet
"""
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(r"C:/Users/alexandre bandarra/Desktop/global")
V3 = ROOT / "data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_BTC_5m_full_v3.parquet"
MG = ROOT / "data/v4/canonical/_results/master_gate_features_v2.parquet"
OUT = ROOT / "data/v4/canonical/_results/_sniper_btc_5m_enriched.parquet"

print("Loading v3 fires...")
v3 = pd.read_parquet(V3)
print(f"  v3: n={len(v3):,}, cols={len(v3.columns)}")

print("Loading master_gate_features_v2 (BTC 5m subset)...")
mg = pd.read_parquet(MG)
mg = mg[(mg["asset"] == "BTC") & (mg["tf"] == "5m")].copy()
print(f"  mg: n={len(mg):,}, cols={len(mg.columns)}")

# Join keys
# v3 has: slug, fire_us, ws_s, fire_offset_s
# mg has: slug, fire_us, fire_offset_s

# Detect new cols in MG vs v3
v3_cols = set(v3.columns)
mg_only_cols = [c for c in mg.columns if c not in v3_cols]
print(f"\nCols only in mg: {len(mg_only_cols)}")
# Drop join keys
join_keys = ["slug", "fire_us"]
mg_join = mg[join_keys + mg_only_cols].copy()

print("Merging on (slug, fire_us)...")
out = v3.merge(mg_join, on=join_keys, how="left", suffixes=("", "_mg"))
print(f"  merged: n={len(out):,}, cols={len(out.columns)}")

# Coverage check
in_mg = out["regime_label"].notna()  # one of the MG-only cols
print(f"  Fires with MG enrichment: n={in_mg.sum():,} / {len(out):,} ({in_mg.mean()*100:.1f}%)")

# Coerce gate cols
g_cols = [c for c in out.columns if c.startswith("g_")]
print(f"\nGate cols total: {len(g_cols)}")
for c in g_cols:
    out[c] = out[c].fillna(0).astype(np.int8)

# fire_date
out["fire_dt"] = pd.to_datetime(out["fire_us"], unit="us", utc=True)
out["fire_date"] = out["fire_dt"].dt.date

# Save
print(f"\nWriting {OUT}...")
out.to_parquet(OUT, index=False)
print(f"  done. size={OUT.stat().st_size / 1e6:.1f} MB")

# Quick prevalences for some new gates
print("\nKey gate prevalences (full v3 universe):")
for g in ["g_mp_no_extreme", "g_mp_skew_with", "g_mp_change_with",
         "g_lm_high_stat", "g_hawkes_imbalance_with", "g_hl_liq_cascade_with",
         "g_vol_high", "g_vol_contracting", "g_vol_expanding",
         "g_hurst_trending", "g_hurst_reverting",
         "g_trend_slope_with", "g_trend_slope_strong_with",
         "g_imb5_strong_with", "g_imb_change_with", "g_queue_top_high",
         "g_book_slope_steep_against", "g_flow_with_and_no_whale",
         "g_coinbase_basis_extreme_against", "g_markov_with",
         "g_vwap_ge_50_le_85", "g_lm_extreme_against",
         "g_within_dev", "g_dev_extreme"]:
    if g in out.columns:
        n_on = int(out[g].sum())
        wr_g = out.loc[out[g] == 1, "won"].mean() if n_on > 0 else 0.0
        dpt_g = out.loc[out[g] == 1, "pnl_legacy_usd"].mean() if n_on > 0 else 0.0
        print(f"  {g:40s} on={n_on:>7,}/{len(out):,} ({n_on/len(out)*100:5.2f}%)  wr={wr_g:.3f}  $/tr={dpt_g:+.3f}")
