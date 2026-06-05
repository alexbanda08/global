import pandas as pd, os, glob, pyarrow.parquet as pq
ROOT=r"C:\Users\alexandre bandarra\Desktop\global"
RES=os.path.join(ROOT,"data","v4","canonical","_results")
CAN=os.path.join(ROOT,"data","v4","canonical")
def rng(df,c):
    if c in df.columns:
        v=pd.to_datetime(df[c],unit='us',errors='coerce') if df[c].dtype.kind in 'iuf' else pd.to_datetime(df[c],errors='coerce')
        return f"{v.min()} -> {v.max()}"
    return "n/a"
def show(p, label):
    if not os.path.exists(p): print(f"\n## {label}: MISSING {p}"); return
    try:
        pf=pq.ParquetFile(p); n=pf.metadata.num_rows; cols=[f.name for f in pf.schema_arrow]
        print(f"\n## {label}  rows={n:,}  ncols={len(cols)}")
        print("cols:", cols)
        df=pf.read_row_group(0).to_pandas().head(200)
        for tc in ['ws_s','slot_start_us','timestamp_us','fire_us','at','at_us','end_us']:
            if tc in df.columns: print(f"  time[{tc}]:", rng(df,tc)); break
    except Exception as e:
        print(f"\n## {label}: ERR {e}")
print("=== canonical _results/*.parquet ===")
for f in sorted(glob.glob(os.path.join(RES,"*.parquet"))):
    print("  ", os.path.basename(f), f"{os.path.getsize(f)//1024//1024}MB")
show(os.path.join(RES,"master_5m_panel.parquet"),"master_5m_panel")
show(os.path.join(RES,"master_15m_panel.parquet"),"master_15m_panel")
for fn in ["range_filter_1s","traders_reality_1s","ta_indicators_1s","realized_vol_1s","prod_fills_with_indicators"]:
    show(os.path.join(RES,fn+".parquet"),fn)
# resolutions full-period coverage
import sys; sys.path.insert(0,os.path.join(ROOT,"data/v4/canonical"))
from load import load_resolutions
r=load_resolutions()
r['d']=pd.to_datetime(r['slot_start_us'],unit='us')
print("\n## resolutions: rows",len(r),"range",r['d'].min(),"->",r['d'].max())
print("by asset×tf:", r.groupby([r.ticker.str.extract(r'(btc|eth|sol)',expand=False) if 'ticker' in r.columns else 'na','timeframe']).size().to_dict() if 'timeframe' in r.columns else 'n/a')
