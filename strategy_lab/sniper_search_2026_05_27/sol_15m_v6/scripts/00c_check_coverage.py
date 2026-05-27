"""Check how master_gate_features_v2 covers SOL 15m fires."""
import os, sys
import pandas as pd
ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
os.chdir(ROOT)

# Load both
fires = pd.read_parquet("data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_SOL_15m_full_v3.parquet")
master = pd.read_parquet("data/v4/canonical/_results/master_gate_features_v2.parquet")

print(f"Fires: {len(fires):,}, unique fire_us: {fires['fire_us'].nunique():,}")
m_sol_15m = master[(master['asset']=='SOL') & (master['tf']=='15m')].copy()
print(f"Master SOL/15m: {len(m_sol_15m):,}, unique fire_us: {m_sol_15m['fire_us'].nunique():,}")
print(f"Master SOL/15m offsets: {sorted(m_sol_15m['fire_offset_s'].unique())}")
print(f"Master SOL/15m date range: {pd.to_datetime(m_sol_15m['fire_us'].min(), unit='us').date()} to {pd.to_datetime(m_sol_15m['fire_us'].max(), unit='us').date()}")

# Try join on (slug, fire_us, direction)
m_key = m_sol_15m[['slug','fire_us','direction']].copy()
f_key = fires[['slug','fire_us','direction']].copy()
print(f"\n  Inner join on (slug, fire_us, direction): {len(f_key.merge(m_key, on=['slug','fire_us','direction'], how='inner')):,}")
# Try on (fire_us, direction) ignoring slug
print(f"  Inner join on (fire_us, direction): {len(f_key.merge(m_key, on=['fire_us','direction'], how='inner')):,}")
# Coverage by offset_s
print("\n  Coverage by fire_offset_s:")
for off in sorted(fires['fire_offset_s'].unique()):
    f = fires[fires['fire_offset_s']==off]
    m_off = m_sol_15m[m_sol_15m['fire_offset_s']==off]
    overlap = len(f[f['fire_us'].isin(m_off['fire_us'])])
    print(f"    offset={off}: fires={len(f):,} master={len(m_off):,} overlap={overlap:,}")

# check non-null rates on master gates
gates_to_check = ['g_trend_slope_with','g_markov_with','g_vol_high','g_hawkes_imbalance_with','g_lm_high_stat','g_mp_no_extreme','f7_rsi_at_ws','vwap_since_open_bps','regime_label','vol_regime']
print(f"\n  Non-null rates on master (SOL 15m, n={len(m_sol_15m)}):")
for g in gates_to_check:
    if g in m_sol_15m.columns:
        nn = m_sol_15m[g].notna().sum()
        if m_sol_15m[g].dtype in (int, 'int64', 'int32', 'int8', 'float64', 'float32') or m_sol_15m[g].dtype == bool:
            try:
                m = m_sol_15m[g].mean()
                print(f"    {g}: notna={nn:,} mean={m:.4f}")
            except Exception:
                vc = m_sol_15m[g].value_counts()
                print(f"    {g}: notna={nn:,} unique_top={vc.head(3).to_dict()}")
        else:
            print(f"    {g}: notna={nn:,} dtype={m_sol_15m[g].dtype}")
