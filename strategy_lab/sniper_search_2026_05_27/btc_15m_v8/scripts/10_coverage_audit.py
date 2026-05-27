"""Audit coverage on every gate column. Identify which gates have stale/NaN-derived data on May 23-26.
Output: list of FULL-COVERAGE gates safe for V8 search."""
import os, sys
import numpy as np
import pandas as pd

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
RES = f"{ROOT}/data/v4/canonical/_results"
PANEL = f"{RES}/sniper_btc15m_v8_gated.parquet"
OUTDIR = f"{ROOT}/strategy_lab/sniper_search_2026_05_27/btc_15m_v8"

df = pd.read_parquet(PANEL)
df['fire_date'] = pd.to_datetime(df.fire_us, unit='us', utc=True)
df['day'] = df.fire_date.dt.date

# Audit gates: a gate is "stale" if its sum on May 23-26 is suspiciously low
late = df[df.fire_date >= pd.Timestamp("2026-05-23", tz="UTC")].copy()
late_n = len(late)
early = df[df.fire_date < pd.Timestamp("2026-05-23", tz="UTC")].copy()
early_n = len(early)
print(f"Early period (Apr 24 - May 22): {early_n} fires")
print(f"Late period (May 23 - May 26):  {late_n} fires")
print()

gate_cols = [c for c in df.columns if c.startswith('g_')]
audit = []
for g in gate_cols:
    early_fr = (early[g]==1).sum() / early_n if early_n else 0
    late_fr = (late[g]==1).sum() / late_n if late_n else 0
    # ratio of late vs early; if much lower → stale
    if early_fr > 0:
        ratio = late_fr / early_fr
    else:
        ratio = np.nan
    audit.append({'gate':g, 'early_n':int((early[g]==1).sum()), 'late_n':int((late[g]==1).sum()),
                  'early_fr':early_fr, 'late_fr':late_fr, 'late_ratio':ratio})
adf = pd.DataFrame(audit).sort_values('late_ratio')
print("Suspicious (low late_ratio = stale): top 30")
print(adf.head(30).to_string(index=False))
print()
print("Healthy (late_ratio > 0.5): count =", (adf.late_ratio > 0.5).sum())
print("Stale  (late_ratio < 0.3): count =", (adf.late_ratio < 0.3).sum())

# Save healthy gates list
healthy = adf[adf.late_ratio > 0.5].gate.tolist()
print(f"\nHealthy gate count: {len(healthy)}")
# Save
adf.to_csv(f"{OUTDIR}/v8_gate_coverage_audit.csv", index=False)
print(f"saved audit: {OUTDIR}/v8_gate_coverage_audit.csv")
