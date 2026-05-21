"""V3 — control test: did the wallet only fire when ask was cheap, vs at random times?

Compare TAKER fire moments vs RANDOM control samples (same slug, random offsets in window).
The trigger features should differentiate fire moments from non-fire moments.

Also drill: short-side imbalance, cb_other vs take_price relationship.
"""
from __future__ import annotations
import os, sys, time, json, gc
import numpy as np
import pandas as pd
from pathlib import Path

t0 = time.time()
def log(msg): print(f"[{time.time()-t0:6.1f}s] {msg}", flush=True)

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

CACHE  = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "0xeebde7a0"
OUT_DIR = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "0xeebde7a0_taker_decode"
en = pd.read_parquet(OUT_DIR / "enriched_taker_fires_v2.parquet")
log(f"loaded enriched fires: {len(en):,}")

# Drill 1: when wallet was SHORT bought-side (had sold via maker before taker bought back),
# what is the ask compared to recent? And compared to their short price?
# Note: inv_own_before < 0 means wallet was net SHORT the bought side (sold more than bought)
short_mask = en.inv_own_before < -0.5
print(f"\n--- A1. SHORT-SIDE COVER ---")
print(f"% of takes where wallet was SHORT the bought side (inv<-0.5): {short_mask.mean()*100:.1f}%")
print(f"  median imbalance: {(en.inv_own_before - en.inv_other_before).median():.2f}")
print(f"  median own_inv before take: {en.inv_own_before.median():.2f}")
print(f"  median other_inv: {en.inv_other_before.median():.2f}")

# Drill 2: did take_price land near recent min (5s window)?
# If yes -> they're chasing dips
print(f"\n--- A2. TAKE PRICE vs RECENT MIN ---")
near_min = (en.take_price <= en.min_ask_5s + 0.001)
print(f"% take_price within 1c of recent 5s min ask: {near_min.mean()*100:.1f}%")
print(f"% take_price <= min_ask_5s: {(en.take_price <= en.min_ask_5s).mean()*100:.1f}%")
print(f"% take_price > min_ask_5s by >2c (paid up): {(en.take_price > en.min_ask_5s + 0.02).mean()*100:.1f}%")

# Drill 3: cost basis vs take_price relationship
print(f"\n--- A3. COST BASIS RELATIONSHIP ---")
cb_known = en.dropna(subset=["cb_other"]).copy()
cb_known["pair_cost"] = cb_known.take_price + cb_known.cb_other
print(f"n with cb_other present: {len(cb_known):,}")
print(f"take_price vs (1 - cb_other) — i.e., does take_price < (1 - cb_other) [pair < $1 trigger]:")
cb_known["complement_thresh"] = 1.0 - cb_known.cb_other
print(f"  % take_price < (1 - cb_other) [pair<$1]: {(cb_known.take_price < cb_known.complement_thresh).mean()*100:.1f}%")
print(f"  % take_price < (1 - cb_other) - 0.02:    {(cb_known.take_price < cb_known.complement_thresh - 0.02).mean()*100:.1f}%")
print(f"  % take_price < (1 - cb_other) - 0.05:    {(cb_known.take_price < cb_known.complement_thresh - 0.05).mean()*100:.1f}%")
print()
# Conditional medians:
print(f"  median pair_cost when pair<$1 trigger met: {cb_known[cb_known.take_price < cb_known.complement_thresh].pair_cost.median():.3f}")

# Drill 4: bucket take fires by (inv_state, ask_drop_60s)
# Goal: find a single dominant cluster
print(f"\n--- BUCKET ANALYSIS ---")
def bucket_inv(r):
    if r["inv_own_before"] < -0.5: return "SHORT_BOUGHT"
    if r["inv_own_before"] < 0.5 and r["inv_other_before"] > 0.5: return "FLAT_OWN_LONG_OTHER"
    if r["inv_own_before"] > 0.5 and r["inv_other_before"] > 0.5: return "BOTH_LONG"
    if r["inv_own_before"] > 0.5 and r["inv_other_before"] < 0.5: return "LONG_BOUGHT_ONLY"
    return "FLAT_BOTH"
en["bucket"] = en.apply(bucket_inv, axis=1)
print(en.bucket.value_counts())
print()
print("Median take_price + drop by bucket:")
print(en.groupby("bucket").agg(
    n=("take_price","size"),
    med_take=("take_price","median"),
    med_own_ask=("own_best_ask","median"),
    med_drop=("ask_drop_from_60s","median"),
    med_cb_other=("cb_other","median"),
    med_pair_eff=("pair_eff_cost","median"),
).to_string())

# Drill 5: TIME OF FIRE within slot
print(f"\n--- TIME OF FIRE (offset_s relative to slot_start) ---")
print(en.offset_s.describe(percentiles=[.05,.1,.25,.5,.75,.9,.95]).to_string())
print(f"% fired in slot 0-60s (first minute): {((en.offset_s>=0)&(en.offset_s<60)).mean()*100:.1f}%")
print(f"% fired in slot 60-180s: {((en.offset_s>=60)&(en.offset_s<180)).mean()*100:.1f}%")
print(f"% fired in slot 180-300s: {((en.offset_s>=180)&(en.offset_s<=300)).mean()*100:.1f}%")
print(f"% AT or before slot start: {(en.offset_s<=0).mean()*100:.1f}%")

# Final composite trigger candidates
print(f"\n--- FINAL COMPOSITE TRIGGERS ---")
for cond_name, cond_mask in [
    ("ask_drop_60s>3c", en.ask_drop_from_60s>0.03),
    ("ask_drop_60s>5c", en.ask_drop_from_60s>0.05),
    ("pair_eff_cost<1 (when cb known)", en.pair_eff_cost < 1),
    ("pair_eff_cost<0.95", en.pair_eff_cost < 0.95),
    ("inv_other>0 (other side long)", en.inv_other_before > 0.5),
    ("inv_own<inv_other (rebalance)", en.inv_own_before < en.inv_other_before),
    ("(cb_other known) AND take<1-cb_other", (en.cb_other.notna()) & (en.take_price < (1 - en.cb_other))),
    ("take_price < $0.40", en.take_price < 0.40),
    ("take_price < $0.50", en.take_price < 0.50),
    ("take_size <= 10 shares (small)", en.take_size <= 10),
]:
    pct = cond_mask.mean() * 100
    print(f"  {cond_name:55s} -> {pct:5.1f}%  (n={int(cond_mask.sum())})")

# How well does (inv_other>0) AND (take_price < $0.50) capture fires?
m_a = en.inv_other_before > 0.5
m_b = en.take_price < 0.50
print()
print(f"  COMPOSITE: inv_other>0 AND take<$0.50: {(m_a & m_b).mean()*100:.1f}% (n={int((m_a&m_b).sum())})")
print(f"  COMPOSITE: inv_other>0 OR take<$0.50: {(m_a | m_b).mean()*100:.1f}%")
print(f"  COMPOSITE: inv_other>0 AND ask_drop_60s>0: {(m_a & (en.ask_drop_from_60s>0)).mean()*100:.1f}%")

log("DONE")
