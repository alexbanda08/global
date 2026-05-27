"""Sanity check: V7 gates baseline WR + dpt on train, validate new gate intuition."""
import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np

p = pd.read_parquet("strategy_lab/sniper_search_2026_05_27/sol_5m_v7/_panel_sol_5m_v7.parquet")
print(f"Panel: {p.shape}")

# Eligible
p_e = p[(p['entry_vwap'] < 0.998) & (p['g_book_depth_supports_25'] == 1)].copy()
print(f"Eligible: {len(p_e)}; baseline WR: {p_e['won'].mean():.4f}, baseline $/tr: {p_e['pnl_legacy_usd'].mean():.4f}")

# Sanity: V7 f7 should track V6 f7 where both are non-null
m_v6 = (p_e['f7_rsi_at_ws'].notna())
both = p_e[m_v6 & p_e['f7_rsi_at_ws_v7'].notna()]
if len(both) > 0:
    corr = both[['f7_rsi_at_ws','f7_rsi_at_ws_v7']].corr().iloc[0,1]
    print(f"\nV6 vs V7 f7_rsi correlation (where both present): {corr:.4f}, n={len(both)}")
    diff = (both['f7_rsi_at_ws'] - both['f7_rsi_at_ws_v7']).abs()
    print(f"  median diff: {diff.median():.2f}, p95 diff: {diff.quantile(0.95):.2f}")

# Single-gate scan: which V7 NEW gates have lift on full eligible universe?
new_gates_for_test = [c for c in p_e.columns if c.startswith('g_f7_v7') or c.startswith('g_btc_') or
                       c.startswith('g_hurst_') or c.startswith('g_vol_v7') or c.startswith('g_vol_pct') or
                       c.startswith('g_parent_')]

rows = []
for g in new_gates_for_test:
    m = p_e[g] == 1
    if m.sum() < 50:
        continue
    sub = p_e[m]
    rows.append({'g': g, 'n': len(sub), 'pass_pct': m.mean(),
                 'wr': sub['won'].mean(), 'dpt': sub['pnl_legacy_usd'].mean()})
sg = pd.DataFrame(rows).sort_values('wr', ascending=False)
print(f"\nV7 NEW gates single-gate scan (n>=50):")
print(sg.to_string(index=False))

# Check: V7 f7_with vs V6 f7_with — does V7 reproduce the V6 winner pattern?
v6_winner_filter = (p_e['g_f7_rsi_with'] == 1) & (p_e['g_cci_strong_with'] == 1) & (p_e['g_mfi_with'] == 1) & \
                   (p_e['g_tr_partial_stack_with'] == 1) & (p_e['g_vwap_in_45_85'] == 1)
print(f"\nV6 S1 stack on full eligible: n={v6_winner_filter.sum()}, wr={p_e[v6_winner_filter]['won'].mean():.4f}, dpt=${p_e[v6_winner_filter]['pnl_legacy_usd'].mean():.4f}")

# Replace g_f7_rsi_with with g_f7_v7_with → see if we get more fires with similar economics
v7_test = (p_e['g_f7_v7_with'] == 1) & (p_e['g_cci_strong_with'] == 1) & (p_e['g_mfi_with'] == 1) & \
          (p_e['g_tr_partial_stack_with'] == 1) & (p_e['g_vwap_in_45_85'] == 1)
print(f"V7 S1 stack (with V7 f7): n={v7_test.sum()}, wr={p_e[v7_test]['won'].mean():.4f}, dpt=${p_e[v7_test]['pnl_legacy_usd'].mean():.4f}")
