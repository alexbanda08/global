"""Why did V6 S1 lockbox = WR 83.9% n=87 but full-eligible re-test n=186 WR 81.7%?
And why does replacing V6 f7 with V7 f7 (full coverage) collapse the stack?"""
import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np

p = pd.read_parquet("strategy_lab/sniper_search_2026_05_27/sol_5m_v7/_panel_sol_5m_v7.parquet")
p = p[(p['entry_vwap'] < 0.998) & (p['g_book_depth_supports_25'] == 1)].copy()

# V6 stack with V6 f7
v6 = (p['g_f7_rsi_with'] == 1) & (p['g_cci_strong_with'] == 1) & (p['g_mfi_with'] == 1) & \
     (p['g_tr_partial_stack_with'] == 1) & (p['g_vwap_in_45_85'] == 1)
print(f"V6 S1 (V6 f7 gate): n={v6.sum()}, wr={p[v6]['won'].mean():.4f}, dpt=${p[v6]['pnl_legacy_usd'].mean():.4f}")
print(f"  date range fired: {pd.to_datetime(p[v6]['fire_us'].min(),unit='us')} -> {pd.to_datetime(p[v6]['fire_us'].max(),unit='us')}")

# V6 f7 actually populated
v6f7_present = p['f7_rsi_at_ws'].notna()
print(f"\nV6 f7 populated: {v6f7_present.mean()*100:.1f}%")
print(f"  date range with V6 f7 data: {pd.to_datetime(p[v6f7_present]['fire_us'].min(),unit='us')} -> {pd.to_datetime(p[v6f7_present]['fire_us'].max(),unit='us')}")

# So when g_f7_rsi_with == 1, V6 f7 was non-null (positive) so the filter only matches those
# (mostly later dates where mgf join was OK)
v6_v7_compare = p[v6 & p['f7_rsi_at_ws_v7'].notna()].copy()
print(f"\nV6-stack fires with V7 f7 also available: {len(v6_v7_compare)}")

# Compare V6 vs V7 f7 RSI VALUES on V6-stack fires
v6_rsi = v6_v7_compare['f7_rsi_at_ws']
v7_rsi = v6_v7_compare['f7_rsi_at_ws_v7']
diff = (v6_rsi - v7_rsi).abs()
print(f"  median |diff|: {diff.median():.2f}, p95 diff: {diff.quantile(0.95):.2f}")
print(f"  V6 RSI mean: {v6_rsi.mean():.2f}, V7 RSI mean: {v7_rsi.mean():.2f}")

# RSI vs direction on V6 stack
print(f"\nV6 stack fires direction distribution: {p[v6]['direction'].value_counts().to_dict()}")

# Look at v6 sub for V6 f7 extreme: is g_f7_rsi_oversold (V6) ON for UP direction?
v6up = p[v6 & (p['direction']=='UP')]
print(f"V6 stack UP: n={len(v6up)}, mean V6 RSI: {v6up['f7_rsi_at_ws'].mean():.2f}, V7 RSI: {v6up['f7_rsi_at_ws_v7'].mean():.2f}")
v6dn = p[v6 & (p['direction']=='DOWN')]
print(f"V6 stack DOWN: n={len(v6dn)}, mean V6 RSI: {v6dn['f7_rsi_at_ws'].mean():.2f}, V7 RSI: {v6dn['f7_rsi_at_ws_v7'].mean():.2f}")

# Maybe the V6 f7 gate was effectively filtering by date (later window) PLUS a true RSI signal
# Test: V6 S1 stack on the SAME date range as V6 f7 coverage (May 1 - May 22) using V7 f7
late = p[(p['fire_us'] >= int(pd.Timestamp('2026-05-01').timestamp() * 1e6)) &
         (p['fire_us'] < int(pd.Timestamp('2026-05-22').timestamp() * 1e6))]
print(f"\nLate window (May 1 - May 22) eligible: {len(late)}")
v7s1_late = (late['g_f7_v7_with'] == 1) & (late['g_cci_strong_with'] == 1) & (late['g_mfi_with'] == 1) & \
            (late['g_tr_partial_stack_with'] == 1) & (late['g_vwap_in_45_85'] == 1)
print(f"V7 S1 stack on late window: n={v7s1_late.sum()}, wr={late[v7s1_late]['won'].mean():.4f}, dpt=${late[v7s1_late]['pnl_legacy_usd'].mean():.4f}")
