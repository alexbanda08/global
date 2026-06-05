"""Inspect schemas + coverage for kelly/prewindow/fade backtest. v1."""
import sys, json
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
import pyarrow.parquet as pq
import pandas as pd
import numpy as np

CANON = r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical"

def schema_and_span(path, ts_col_candidates):
    pf = pq.ParquetFile(path)
    sch = pf.schema_arrow
    cols = [f.name for f in sch]
    print(f"\n=== {path.split(chr(92))[-1]} ===")
    print("nrows:", pf.metadata.num_rows, "row_groups:", pf.num_row_groups)
    print("cols:", cols)
    # find a ts col
    tcol = None
    for c in ts_col_candidates:
        if c in cols:
            tcol = c; break
    if tcol:
        # read just that col
        t = pq.read_table(path, columns=[tcol])[tcol].to_pandas()
        mn, mx = int(t.min()), int(t.max())
        # detect us vs s
        div = 1_000_000 if mn > 1e15 else 1
        print(f"  {tcol}: min={pd.to_datetime(mn/div, unit='s')} max={pd.to_datetime(mx/div, unit='s')}")
    return cols

print("PYINSPECT_START_MARKER")
schema_and_span(CANON+r"\klines_1s.parquet", ["time_period_start_us","timestamp_us","ts_s"])
cols_ta = schema_and_span(CANON+r"\_results\ta_indicators_1s.parquet", ["time_period_start_us","timestamp_us","ts_s","ts"])
# Print MACD-related cols
macd_cols = [c for c in cols_ta if any(k in c.lower() for k in ["macd","ema","signal","sig"])]
print("MACD/EMA cols in ta_indicators_1s:", macd_cols[:50])
schema_and_span(CANON+r"\resolutions_from_rtds.parquet", ["slot_start_us"])
print("PYINSPECT_END_MARKER")
