"""Add entry_vwap-based gates and offset-bin gates.

These are essential because $/tr scales with (1 - entry_vwap):
  - WR 80% at vwap 0.85 -> dpt ~ 0.80*0.15*25 - 0.20*0.85*25 = 3.0 - 4.25 = -1.25
  - WR 80% at vwap 0.50 -> dpt ~ 0.80*0.50*25 - 0.20*0.50*25 = 10 - 2.5 = 7.5
  - WR 80% at vwap 0.30 -> dpt ~ 0.80*0.70*25 - 0.20*0.30*25 = 14 - 1.5 = 12.5

So sniper $/tr >= $3 with high WR almost requires entry_vwap < 0.70.
"""
import os, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np
from pathlib import Path

OUT = Path("strategy_lab/sniper_search_2026_05_27/sol_5m")
p = pd.read_parquet(OUT / "_panel_sol_5m_gated.parquet")
print(f"Panel: {len(p)} rows", flush=True)

def g_(s): return s.fillna(0).astype('int8')

# entry vwap gates
# Note: entry_vwap may be missing (~0%) — let's check
print(f"entry_vwap missing: {p['entry_vwap'].isna().sum()}", flush=True)
print(f"entry_vwap distribution by win:")
print(p.groupby('won')['entry_vwap'].describe())

p['g_ev_le_30'] = g_(p['entry_vwap'] <= 0.30)
p['g_ev_le_40'] = g_(p['entry_vwap'] <= 0.40)
p['g_ev_le_50'] = g_(p['entry_vwap'] <= 0.50)
p['g_ev_le_60'] = g_(p['entry_vwap'] <= 0.60)
p['g_ev_le_70'] = g_(p['entry_vwap'] <= 0.70)
p['g_ev_ge_30'] = g_(p['entry_vwap'] >= 0.30)
p['g_ev_in_30_60'] = g_((p['entry_vwap'] >= 0.30) & (p['entry_vwap'] <= 0.60))
p['g_ev_in_20_50'] = g_((p['entry_vwap'] >= 0.20) & (p['entry_vwap'] <= 0.50))
p['g_ev_in_40_70'] = g_((p['entry_vwap'] >= 0.40) & (p['entry_vwap'] <= 0.70))

# offset bins
p['g_offset_early'] = g_(p['fire_offset_s'] <= 60)
p['g_offset_mid_early'] = g_((p['fire_offset_s'] > 60) & (p['fire_offset_s'] <= 120))
p['g_offset_mid'] = g_((p['fire_offset_s'] > 120) & (p['fire_offset_s'] <= 180))
p['g_offset_mid_late'] = g_((p['fire_offset_s'] > 180) & (p['fire_offset_s'] <= 240))
p['g_offset_late'] = g_(p['fire_offset_s'] > 240)
p['g_offset_le_120'] = g_(p['fire_offset_s'] <= 120)
p['g_offset_ge_180'] = g_(p['fire_offset_s'] >= 180)

# Direction
p['g_dir_up'] = g_(p['direction'] == 'UP')
p['g_dir_dn'] = g_(p['direction'] == 'DOWN')

# Direction x ev (contrarian betting on UP token when below 0.5 — "buy the dog")
p['g_underdog'] = g_(p['entry_vwap'] <= 0.50)
p['g_favorite'] = g_(p['entry_vwap'] >= 0.50)
p['g_strong_underdog'] = g_(p['entry_vwap'] <= 0.40)
p['g_strong_favorite'] = g_(p['entry_vwap'] >= 0.60)

# Save
out = OUT / "_panel_sol_5m_gated.parquet"
p.to_parquet(out, index=False, compression='zstd')
print(f"\nAdded entry_vwap + offset gates")
print(f"Wrote {out} ({os.path.getsize(out)/1024/1024:.1f} MB)")
# Quick view of new gates
new_gates = ['g_ev_le_50', 'g_ev_le_40', 'g_ev_le_30', 'g_ev_in_30_60', 'g_offset_early',
             'g_offset_late', 'g_dir_up', 'g_underdog', 'g_strong_underdog']
for c in new_gates:
    m = p[c]==1
    n = int(m.sum())
    if n == 0: continue
    wr = p.loc[m, 'won'].mean()
    dpt = p.loc[m, 'pnl_legacy_usd'].mean()
    print(f"  {c}: n={n} ({n/len(p)*100:.1f}%) WR={wr:.3f} dpt={dpt:.2f}")
