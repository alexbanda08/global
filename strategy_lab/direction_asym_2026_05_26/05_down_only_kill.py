"""
TASK 5: DOWN-only / UP-only specialty sleeves.
   For every (asset, tf, offset_bin) compute: WR_UP, dpt_UP, sum_UP vs WR_DOWN, dpt_DOWN, sum_DOWN
   Flag cells where one direction is strongly profitable and the other is not.

TASK 6: KILL gates per direction.
   For g_lm_extreme_against and other reversal/protection gates, test
   whether dropping fires when KILL=1 hurts/helps differently by direction.
"""
import pandas as pd
import numpy as np
from pathlib import Path

PANEL = r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/master_gate_features_v2.parquet"
OUTDIR = Path(r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/direction_asym_2026_05_26")

df = pd.read_parquet(PANEL)
df['fire_date_only'] = df['fire_date'].dt.date
LOCKBOX_START = pd.Timestamp("2026-05-21", tz="UTC").date()
ALL_GATES = [c for c in df.columns if c.startswith("g_")]
for g in ALL_GATES:
    df[g] = df[g].fillna(0).astype(np.int8)

# TASK 5: per (asset, tf, offset_bin, direction) basic stats
key_cols = ['asset', 'tf', 'offset_bin', 'direction']
cell_stats = df.groupby(key_cols).agg(
    n=('won_int','size'),
    WR=('won_int','mean'),
    dpt=('pnl_legacy_usd','mean'),
    sum=('pnl_legacy_usd','sum'),
).round(4).reset_index()

# Pivot side-by-side for direction asymmetry
piv = cell_stats.pivot_table(index=['asset','tf','offset_bin'], columns='direction',
                              values=['n','WR','dpt','sum'])
piv.columns = ['_'.join(c) for c in piv.columns]
piv = piv.reset_index()
piv['dpt_diff'] = piv['dpt_UP'] - piv['dpt_DOWN']
piv['sum_diff'] = piv['sum_UP'] - piv['sum_DOWN']
piv['wr_diff_pp'] = (piv['WR_UP'] - piv['WR_DOWN']) * 100
# Filter to cells where one direction is positive and other near zero/negative
specialty = piv[((piv['sum_UP'] > 100) & (piv['sum_DOWN'] < -100)) |
                ((piv['sum_DOWN'] > 100) & (piv['sum_UP'] < -100))].copy()
specialty['side'] = np.where(specialty['sum_UP'] > specialty['sum_DOWN'], 'UP_specialty', 'DOWN_specialty')
specialty.to_csv(OUTDIR / "specialty_cells.csv", index=False)
print(f"\n=== TASK 5: Specialty cells (one direction profitable, other not) ===")
print(specialty.sort_values('sum_diff', ascending=False, key=abs).to_string())
print(f"\nwrote {OUTDIR/'specialty_cells.csv'}")

# Save full piv
piv.to_csv(OUTDIR / "cell_direction_asym.csv", index=False)
print(f"wrote {OUTDIR/'cell_direction_asym.csv'} (full)")

# TASK 6: KILL gates per direction
# KILL gate = the gate being ON means we should NOT trade.
# Test: gate_off (=0) bets vs gate_on (=1) bets, separately by direction
KILL_CANDIDATES = ['g_lm_extreme_against', 'g_dev_extreme',
                   'g_book_slope_steep_against', 'g_coinbase_basis_extreme_against',
                   'g_hl_liq_cascade_with']
kill_rows = []
for sleeve in df['sleeve_id'].value_counts().head(7).index:
    s = df[df['sleeve_id']==sleeve]
    for direction in ['UP','DOWN']:
        sd = s[s['direction']==direction]
        if len(sd) < 200: continue
        base = dict(n=len(sd), WR=sd['won_int'].mean(), dpt=sd['pnl_legacy_usd'].mean(),
                    sum=sd['pnl_legacy_usd'].sum())
        for g in KILL_CANDIDATES:
            if g not in sd.columns: continue
            on = sd[sd[g]==1]
            off = sd[sd[g]==0]
            if len(on) < 20 or len(off) < 20: continue
            kill_rows.append(dict(
                sleeve=sleeve[:50], direction=direction, kill_gate=g,
                n_on=len(on), WR_on=round(on['won_int'].mean(),4),
                dpt_on=round(on['pnl_legacy_usd'].mean(),3),
                sum_on=round(on['pnl_legacy_usd'].sum(),1),
                n_off=len(off), WR_off=round(off['won_int'].mean(),4),
                dpt_off=round(off['pnl_legacy_usd'].mean(),3),
                sum_off=round(off['pnl_legacy_usd'].sum(),1),
                dpt_diff=round(off['pnl_legacy_usd'].mean()-on['pnl_legacy_usd'].mean(),3),
            ))
kill_df = pd.DataFrame(kill_rows)
kill_df.to_csv(OUTDIR / "kill_gates_per_direction.csv", index=False)
# Show top differential per gate
for g in KILL_CANDIDATES:
    sub = kill_df[kill_df['kill_gate']==g]
    if len(sub)==0: continue
    print(f"\n--- {g} ---")
    print(sub[['sleeve','direction','n_on','dpt_on','n_off','dpt_off','dpt_diff']].to_string())

print(f"\nwrote {OUTDIR/'kill_gates_per_direction.csv'}")
