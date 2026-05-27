"""
Build SOL 15m V6 enriched universe:
- v3 fires (34,886 rows)
- Add ws_s_us, signal_ts, pre-window proxies
- Join regime_panel_15m_v2_fixed (rebuilt g_trend_slope_with)
- Join sms_panel_15m_v2_fixed (Markov M1V state)
- Join master_gate_features_v2 (rare gates: hawkes, LM, flow, mp_change, cb_basis, hl_liq, etc.)
- Join microprice_panel for g_mp_no_extreme, g_mp_change_with
- Compute conviction-related features

Output: sol_15m_v6_universe.parquet
"""
import os, sys
import pandas as pd
import numpy as np

ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
os.chdir(ROOT)
sys.path.insert(0, "data/v4/canonical")

OUT = "strategy_lab/sniper_search_2026_05_27/sol_15m_v6/sol_15m_v6_universe.parquet"

# Load v3 fires
fp = "data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_SOL_15m_full_v3.parquet"
df = pd.read_parquet(fp)
print(f"v3 fires: {len(df):,} rows")

# Compute pre-window anchors
WINDOW_S = 900
df['ws_s_us'] = df['slot_start_us'] - WINDOW_S * 1_000_000  # signal anchor

# Compute fire timestamps for various offsets (we already have fire_us based on fire_offset_s)
# ws_minus_30 = (ws_s - 30) * 1e6
df['ws_minus_30_us'] = df['ws_s_us'] - 30 * 1_000_000
df['ws_minus_60_us'] = df['ws_s_us'] - 60 * 1_000_000

# Direction binary
df['dir_up'] = (df['direction'] == 'UP').astype(int)
df['dir_int'] = np.where(df['direction']=='UP', 1, -1)

# Save initial dt index for diagnostics
print(f"Offsets: {sorted(df['fire_offset_s'].unique())}")
print(f"Date range: {pd.to_datetime(df['slot_start_us'].min(), unit='us').date()} to {pd.to_datetime(df['slot_end_us'].max(), unit='us').date()}")

# ============================================================
# JOIN regime_panel_15m_v2_fixed (rebuild g_trend_slope_with from this)
# ============================================================
reg = pd.read_parquet("data/v4/canonical/_results/regime_panel_15m_v2_fixed.parquet")
print(f"\nregime_panel: {len(reg):,} rows, cols={reg.columns.tolist()[:15]}")
print(f"regime cols full: {reg.columns.tolist()}")
print(f"regime asset/tf: assets={reg['asset'].unique() if 'asset' in reg.columns else 'n/a'}")

# Filter to SOL
reg_sol = reg[reg['asset']=='SOL'].copy() if 'asset' in reg.columns else reg.copy()
print(f"  SOL rows: {len(reg_sol):,}")
print(f"  regime ts col: {[c for c in reg_sol.columns if 'us' in c.lower() or 'ts' in c.lower()][:5]}")
