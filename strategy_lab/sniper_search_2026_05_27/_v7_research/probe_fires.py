"""Check fire universe structure for 2-leg straddle viability."""
import pandas as pd
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

fp = r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_BTC_5m_full_v3.parquet"
df = pd.read_parquet(fp, columns=['slug', 'slot_start_us', 'slot_end_us', 'fire_offset_s', 'fire_us', 'direction', 'outcome', 'won', 'entry_vwap', 'pnl_legacy_usd'])
print(f"BTC 5m fires: {len(df):,}")
print(f"  direction.uniq: {df['direction'].unique()}")
print(f"  fire_offset_s.uniq: {sorted(df['fire_offset_s'].unique())}")

# how many slugs per offset?
print(f"\nSlugs × offset × direction:")
print(df.groupby(['fire_offset_s', 'direction'])['slug'].nunique().head(20))

# For 2-leg: for a given slug, we need BOTH UP and DOWN fire at chosen offsets
# Check if same slug has both directions
slug_dir_offsets = df.groupby(['slug', 'fire_offset_s', 'direction']).size().unstack(fill_value=0)
print(f"\nSlugs with BOTH UP+DOWN at offset 30: {((slug_dir_offsets.xs(30, level='fire_offset_s')['UP']>0) & (slug_dir_offsets.xs(30, level='fire_offset_s')['DOWN']>0)).sum() if 30 in df['fire_offset_s'].unique() else 'na'}")

# entry_vwap stats
print(f"\nentry_vwap stats:")
print(df['entry_vwap'].describe())
print(f"  NaN count: {df['entry_vwap'].isna().sum()}")
print(f"  pnl_legacy_usd describe:")
print(df['pnl_legacy_usd'].describe())
