"""Single-gate scan: which individual atoms lift WR / $/tr on the full panel?

Output: _single_gate_scan.csv with per-gate stats.
"""
import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np
from pathlib import Path

OUT = Path("strategy_lab/sniper_search_2026_05_27/sol_5m")
p = pd.read_parquet(OUT / "_panel_sol_5m_gated.parquet")
print(f"Panel: {len(p)} rows; baseline WR={p['won'].mean():.4f}, $/tr={p['pnl_legacy_usd'].mean():.4f}", flush=True)

gates = [c for c in p.columns if c.startswith('g_') and c not in ('g_R1_sum',)]
n0 = len(p); wr0 = p['won'].mean(); dpt0 = p['pnl_legacy_usd'].mean()

rows = []
for g in gates:
    mask = p[g] == 1
    n = int(mask.sum())
    if n < 10: continue
    wr = p.loc[mask, 'won'].mean()
    dpt = p.loc[mask, 'pnl_legacy_usd'].mean()
    rows.append({
        'gate': g,
        'n': n,
        'pct': n / n0,
        'wr': wr,
        'wr_lift_pp': (wr - wr0) * 100,
        'dpt_25': dpt,
        'dpt_lift': dpt - dpt0,
        'sum_pnl': p.loc[mask, 'pnl_legacy_usd'].sum(),
    })

res = pd.DataFrame(rows).sort_values('dpt_25', ascending=False)
res.to_csv(OUT / "_single_gate_scan.csv", index=False)
print("\nTop 25 by $/tr:")
print(res.head(25).to_string(index=False))
print("\nTop 25 by WR lift:")
print(res.sort_values('wr_lift_pp', ascending=False).head(25).to_string(index=False))
