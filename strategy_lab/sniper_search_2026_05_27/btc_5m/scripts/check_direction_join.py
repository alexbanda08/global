"""Investigate v3 fire universe vs MG selection.

Q: Does the v3 fire universe include both directions (UP and DOWN) per slug?
   Does master_gate select one direction per (slug, fire_us)?
"""
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(r"C:/Users/alexandre bandarra/Desktop/global")
V3 = ROOT / "data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_BTC_5m_full_v3.parquet"
MG = ROOT / "data/v4/canonical/_results/master_gate_features_v2.parquet"

v3 = pd.read_parquet(V3, columns=["slug","fire_us","fire_offset_s","direction","outcome","won"])
print(f"v3: n={len(v3):,}")
print(v3.head())
print()
# direction split
print("v3 direction value_counts:")
print(v3["direction"].value_counts())
print()
# multi-direction per (slug, fire_us)?
grp = v3.groupby(["slug","fire_us"]).size().value_counts()
print(f"v3 unique (slug, fire_us) counts of rows: {grp}")
print()

# Check (slug, fire_us, fire_offset_s) uniqueness
grp2 = v3.groupby(["slug","fire_us","fire_offset_s","direction"]).size().value_counts()
print(f"v3 unique (slug, fire_us, fire_offset_s, direction) counts: {grp2}")
print()

# MG
mg = pd.read_parquet(MG, columns=["slug","fire_us","fire_offset_s","direction","outcome","won","asset","tf","sleeve_id"])
mg = mg[(mg["asset"]=="BTC") & (mg["tf"]=="5m")]
print(f"mg BTC 5m: n={len(mg):,}")
print(mg.head())
print()
print("mg direction value_counts:")
print(mg["direction"].value_counts())
print()
print(f"unique sleeve_id in mg: {mg['sleeve_id'].nunique()}")
print(mg["sleeve_id"].value_counts().head(20))
print()
grpm = mg.groupby(["slug","fire_us"]).size().value_counts()
print(f"mg unique (slug, fire_us) counts of rows: {grpm}")
grpm2 = mg.groupby(["slug","fire_us","fire_offset_s","direction"]).size().value_counts()
print(f"mg unique (slug, fire_us, fire_offset_s, direction) counts: {grpm2}")
