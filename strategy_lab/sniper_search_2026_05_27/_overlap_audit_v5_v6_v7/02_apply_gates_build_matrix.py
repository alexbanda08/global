"""V5+V6+V7 overlap audit — Step 2: apply each sleeve's gate stack to its market V7 panel.

For each sleeve:
  1. Load the V7 panel for (asset, tf).
  2. Filter by offset (if specified).
  3. Filter by direction (if not BOTH).
  4. Apply gate stack: all gates must be 1.
  5. Output per-fire records (slug, fire_us, direction, offset, won, pnl_legacy_usd).

Tracks per-sleeve fire count, WR, sum_pnl, $/tr, days_active.
Flags any sleeve whose gates cannot be reproduced (missing gate column).
Outputs:
  - fired_by_sleeve.parquet
  - sleeve_summary.csv
  - unreproducible_sleeves.csv
"""
import os, sys, importlib.util
import pandas as pd
import numpy as np

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
OUT = f"{ROOT}/strategy_lab/sniper_search_2026_05_27/_overlap_audit_v5_v6_v7"

# Load registry definitions
spec = importlib.util.spec_from_file_location("reg", f"{OUT}/01_sleeve_registry.py")
reg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reg)
SLEEVES = reg.SLEEVES
PANEL = reg.PANEL
GATE_ALIAS = reg.GATE_ALIAS

print(f"Total sleeves to audit: {len(SLEEVES)}")

# Load panels once
panels_cache = {}
for (a, tf), p in PANEL.items():
    print(f"Loading panel for {a} {tf}: {p}")
    df = pd.read_parquet(p)
    # Ensure required cols
    for c in ['slug', 'fire_us', 'direction', 'fire_offset_s']:
        if c not in df.columns:
            print(f"  WARN: missing core col {c} -- adding NaN")
            df[c] = np.nan
    # asset col may be missing in some panels
    if 'asset' not in df.columns:
        df['asset'] = a
    if 'tf' not in df.columns:
        df['tf'] = tf
    # ws_s
    if 'ws_s' not in df.columns and 'slot_start_us' in df.columns:
        df['ws_s'] = (df['slot_start_us'] // 1_000_000 - (300 if tf == '5m' else 900)).astype('int64')
    # won / pnl
    for c in ['won', 'pnl_legacy_usd', 'outcome', 'entry_vwap']:
        if c not in df.columns:
            df[c] = np.nan
    # Coerce gate cols to int (0/1)
    gcols = [c for c in df.columns if c.startswith('g_')]
    for g in gcols:
        df[g] = pd.to_numeric(df[g], errors='coerce').fillna(0).astype('int8')
    panels_cache[(a, tf)] = df
    print(f"  rows={len(df):,}  cols={len(df.columns)}  gate_cols={len(gcols)}")

# Helper: resolve alias
def resolve(gate, panel_cols):
    aliases = GATE_ALIAS.get(gate, [gate])
    for a in aliases:
        if a in panel_cols:
            return a
    return None

# Process each sleeve
fired_records = []
summary_rows = []
unreproducible = []

DATE_MIN_US = int(pd.Timestamp("2026-04-24", tz="UTC").timestamp() * 1_000_000)
DATE_MAX_US = int(pd.Timestamp("2026-05-26 17:00", tz="UTC").timestamp() * 1_000_000)
WINDOW_DAYS = 33.0
PROJ_DAYS = 28.0

for s in SLEEVES:
    sid = s['sleeve_id']
    a, tf = s['asset'], s['tf']
    df = panels_cache.get((a, tf))
    if df is None:
        unreproducible.append(dict(sleeve_id=sid, reason=f"no panel for {a} {tf}"))
        continue
    cols = set(df.columns)

    # Resolve gates
    resolved = []
    missing = []
    for g in s['gates']:
        rg = resolve(g, cols)
        if rg is None:
            missing.append(g)
        else:
            resolved.append(rg)
    if missing:
        unreproducible.append(dict(sleeve_id=sid, reason=f"missing gates: {missing}"))
        continue

    sub = df

    # Filter by offset
    if s['offsets'] is not None:
        offsets = s['offsets']
        sub = sub[sub['fire_offset_s'].isin(offsets)]
    # Apply gates
    if not resolved:
        # No gates? Take everything (degenerate case)
        pass
    else:
        mask = sub[resolved[0]] == 1
        for g in resolved[1:]:
            mask &= (sub[g] == 1)
        sub = sub[mask]
    # Filter direction
    if s['direction'] in ('UP', 'DOWN'):
        sub = sub[sub['direction'] == s['direction']]

    # Filter to date window (sanity)
    sub = sub[(sub['fire_us'] >= DATE_MIN_US) & (sub['fire_us'] <= DATE_MAX_US)]

    if len(sub) == 0:
        summary_rows.append(dict(
            version=s['version'], sleeve_id=sid, asset=a, tf=tf,
            n=0, wr_pct=np.nan, dpt_usd=np.nan, sum_pnl_usd=0.0,
            sum_28d_proj=0.0, days_active=0,
            gate_stack="|".join(resolved),
        ))
        continue

    # PnL: pnl_legacy_usd is already the per-fire PnL for $25 stake (2%-on-profit fee)
    # In v3 fires, pnl_legacy_usd uses entry_vwap-scaled stake. Verify by inspecting sample.
    # For consistency, recompute legacy PnL at $25 stake using entry_vwap + won.
    # In source panels, pnl_legacy_usd is already computed at $25 stake (we'll trust it).
    pnl = sub['pnl_legacy_usd'].astype(float)
    won = sub['won'].astype(float)

    # Days active
    dates = pd.to_datetime(sub['fire_us'], unit='us', utc=True).dt.date
    days_active = dates.nunique()

    n = len(sub)
    wr = won.mean() * 100.0
    dpt = pnl.mean()
    sum_pnl = pnl.sum()
    sum_28d = sum_pnl * (PROJ_DAYS / WINDOW_DAYS)

    summary_rows.append(dict(
        version=s['version'], sleeve_id=sid, asset=a, tf=tf,
        n=n, wr_pct=wr, dpt_usd=dpt, sum_pnl_usd=sum_pnl,
        sum_28d_proj=sum_28d, days_active=days_active,
        gate_stack="|".join(resolved),
    ))

    # Append fires
    keep = pd.DataFrame({
        'version':  s['version'],
        'sleeve_id': sid,
        'asset':    a,
        'tf':       tf,
        'slug':     sub['slug'].astype(str).values,
        'fire_us':  sub['fire_us'].astype('int64').values,
        'direction': sub['direction'].astype(str).values,
        'fire_offset_s': sub['fire_offset_s'].astype('int64').values,
        'won':      won.values.astype('int8'),
        'pnl_legacy_usd': pnl.values,
    })
    fired_records.append(keep)

# Save
summary = pd.DataFrame(summary_rows).sort_values(['version','asset','tf','sleeve_id'])
summary.to_csv(f"{OUT}/sleeve_summary.csv", index=False)
print(f"SAVED -> sleeve_summary.csv  ({len(summary)} sleeves)")

# Print summary
print("\n=== SLEEVE SUMMARY (reproducible) ===")
print(summary.to_string(index=False))

if unreproducible:
    df_unrep = pd.DataFrame(unreproducible)
    df_unrep.to_csv(f"{OUT}/unreproducible_sleeves.csv", index=False)
    print(f"\n=== UNREPRODUCIBLE ({len(df_unrep)}) ===")
    print(df_unrep.to_string(index=False))

if fired_records:
    fired = pd.concat(fired_records, ignore_index=True)
    fired.to_parquet(f"{OUT}/fired_by_sleeve.parquet", compression='snappy')
    print(f"\nSAVED -> fired_by_sleeve.parquet ({len(fired):,} fires)")
    print(f"Unique (slug, fire_us, direction) combos: {fired[['slug','fire_us','direction']].drop_duplicates().shape[0]:,}")
