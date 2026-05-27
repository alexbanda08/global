"""Quick schema inspect."""
import pandas as pd
import sys

s15 = pd.read_parquet(r'C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical\_results\s15_with_ta.parquet')
s6 = pd.read_parquet(r'C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical\_results\s6_with_ta.parquet')

print("=== S15 ===")
print("shape:", s15.shape)
print("cols:")
for c in sorted(s15.columns.tolist()):
    print("  ", c, str(s15[c].dtype))
print()
print("=== S6 ===")
print("shape:", s6.shape)
print("cols:")
for c in sorted(s6.columns.tolist()):
    print("  ", c, str(s6[c].dtype))
print()
print("=== S15 sample ===")
print(s15.head(3).to_string())
print()
print("=== S6 sample ===")
print(s6.head(3).to_string())
