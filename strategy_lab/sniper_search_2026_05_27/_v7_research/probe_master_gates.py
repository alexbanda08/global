"""Quick probe of master_gate_features_v2 schema."""
import pandas as pd
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

p = r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/master_gate_features_v2.parquet"
df = pd.read_parquet(p)
print(f"master_gate_features_v2: {len(df):,} rows")
print(f"  cols ({len(df.columns)}):")
for c in df.columns:
    print(f"   {c}")
print(f"  asset uniq: {df['asset'].unique() if 'asset' in df.columns else 'na'}")
print(f"  tf uniq: {df['tf'].unique() if 'tf' in df.columns else 'na'}")
print(f"  fire_offset_s uniq: {sorted(df['fire_offset_s'].unique()) if 'fire_offset_s' in df.columns else 'na'}")
print(df.head(2))
