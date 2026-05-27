"""Verify Bug #2 fix: regime panel anchored at bar END (causal merge_asof).

Methodology: Take 1000 randomly sampled fire rows (slug, fire_us, asset, tf),
asof-join to v1 (bar START) and v2 (bar END) regime panels.
Compare regime_label mismatch rate. For v1, ~20% should differ from a 'causal
prior bar' baseline (computed by subtracting tf_seconds from fire_us). For v2,
mismatch rate should be ~0% (the bar END key already guarantees causality).
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import pandas as pd
import numpy as np

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

ROOT = Path(r"C:/Users/alexandre bandarra/Desktop/global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"

# Read OOS fires (BTC 5m, fixed-9-offset) as the fire universe
fires = pd.read_parquet(RES / "_full_window_2026_05_26" / "oos_fires_BTC_5m_v2_fixed.parquet",
                        columns=["asset", "slug", "fire_us", "fire_offset_s", "direction"])
fires = fires.drop_duplicates(["slug", "fire_us"]).reset_index(drop=True)

# Sample 1000 fires
rng = np.random.default_rng(42)
samp = fires.sample(n=min(1000, len(fires)), random_state=42).reset_index(drop=True).copy()

# v1: bar START keying
r1 = pd.read_parquet(RES / "regime_panel_5m_v1_original.parquet")
r1_btc = r1[r1.asset == "BTC"].sort_values("ts_us")[["ts_us", "regime_label", "regime_score", "adx_14"]].reset_index(drop=True)

# v2: bar END keying
r2 = pd.read_parquet(RES / "regime_panel_5m_v2_fixed.parquet")
r2_btc = r2[r2.asset == "BTC"].sort_values("ts_us")[["ts_us", "regime_label", "regime_score", "adx_14"]].reset_index(drop=True)

# Causal reference: same as v1 but shift fire_us back by 5 minutes (= one bar)
# = "the bar that ENDED before fire_us"
TF_US = 5 * 60 * 1_000_000

samp = samp.sort_values("fire_us").reset_index(drop=True)

# v1 join: backward asof on fire_us
m1 = pd.merge_asof(
    samp.copy(), r1_btc,
    left_on="fire_us", right_on="ts_us",
    direction="backward", tolerance=24*3600*1_000_000,
).rename(columns={"regime_label": "v1_label", "ts_us": "v1_ts_us"})

# v1 CAUSAL reference: shift fire_us back by 1 bar
m1c = pd.merge_asof(
    samp.copy().assign(causal_lookup=lambda d: d.fire_us - TF_US),
    r1_btc,
    left_on="causal_lookup", right_on="ts_us",
    direction="backward", tolerance=24*3600*1_000_000,
).rename(columns={"regime_label": "v1c_label", "ts_us": "v1c_ts_us"})

# v2 join: backward asof on fire_us (should be causal by construction)
m2 = pd.merge_asof(
    samp.copy(), r2_btc,
    left_on="fire_us", right_on="ts_us",
    direction="backward", tolerance=24*3600*1_000_000,
).rename(columns={"regime_label": "v2_label", "ts_us": "v2_ts_us"})

# Compose
joined = samp.copy()
joined["v1_label"] = m1["v1_label"].values
joined["v1c_label"] = m1c["v1c_label"].values
joined["v2_label"] = m2["v2_label"].values

# Mismatch rates
v1_vs_causal_mismatch = (joined.v1_label != joined.v1c_label).mean()
v2_vs_causal_mismatch = (joined.v2_label != joined.v1c_label).mean()
v1_vs_v2 = (joined.v1_label != joined.v2_label).mean()

print(f"BTC 5m fires sampled: {len(joined):,}")
print(f"v1 (leaky bar START) vs v1_causal (prior bar): {v1_vs_causal_mismatch:.3%} mismatch")
print(f"v2 (bar END fix)     vs v1_causal (prior bar): {v2_vs_causal_mismatch:.3%} mismatch")
print(f"v1 vs v2 mismatch                            : {v1_vs_v2:.3%}")
print()
print("Interpretation:")
print("  v1 vs causal-prior-bar mismatch should be ~20% (the leak Agent BB found).")
print("  v2 vs causal-prior-bar mismatch should be ~0% (now causal by construction).")
print()
print(joined[["fire_us", "v1_label", "v1c_label", "v2_label"]].head(10).to_string(index=False))
