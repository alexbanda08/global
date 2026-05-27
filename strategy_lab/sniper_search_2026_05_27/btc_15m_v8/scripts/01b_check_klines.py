"""Check klines loader signature and how to get 1h grandparent."""
import pandas as pd, sys, os
ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
sys.path.insert(0, f"{ROOT}/data/v4/canonical")
from load import load_klines
import inspect
print("load_klines signature:", inspect.signature(load_klines))

# default
k = load_klines("BTC")
print("BTC default cols:", list(k.columns)[:10])
print("BTC rows:", len(k))
print("min:", k.iloc[0])
print("max:", k.iloc[-1])

# look for tf field
if 'tf' in k.columns:
    print("tf values:", k.tf.unique())
elif 'interval' in k.columns:
    print("intervals:", k.interval.unique())

# Look at canonical klines parquet structure directly
import glob
files = glob.glob(f"{ROOT}/data/v4/canonical/klines_1m*.parquet")
print("klines files:", files[:5])
files = glob.glob(f"{ROOT}/data/v4/canonical/*klines*.parquet")
print("all kline files:", files)
