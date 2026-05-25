"""Inspect V2 CVD overlay CSV — columns, dtypes, head, summaries."""
import pandas as pd
import numpy as np

path = r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical\_results\mint_and_sell_cvd_overlay.csv"
df = pd.read_csv(path)
print("SHAPE:", df.shape)
print("COLS:", df.columns.tolist())
print("\nDTYPES:")
print(df.dtypes)
print("\nHEAD 3:")
print(df.head(3).to_string())
print("\nNULLS by column:")
print(df.isnull().sum())
print("\nNUMERIC describe:")
print(df.describe().T)

for c in ('asset', 'tf', 'maker_side', 'side', 'leg', 'outcome', 'maker_taker'):
    if c in df.columns:
        print(f"\nUNIQUE {c}:")
        print(df[c].value_counts(dropna=False).head(20))
