import os, glob, pyarrow.parquet as pq, pandas as pd, numpy as np
RES=r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical\_results"
# list candidate universe/enriched/sniper panels
cands=[f for f in glob.glob(os.path.join(RES,"*.parquet"))
       if any(k in os.path.basename(f).lower() for k in ["sniper","universe","enriched","dirscan","gate_features"])]
print("CANDIDATES:")
for f in sorted(cands): print("  ", os.path.basename(f), f"{os.path.getsize(f)//1024//1024}MB")
def info(p):
    if not os.path.exists(p): print(f"\n##{os.path.basename(p)}: MISSING"); return
    pf=pq.ParquetFile(p); cols=[f.name for f in pf.schema_arrow]
    tc=next((c for c in ['fire_us','ts_us','slot_start_us'] if c in cols),None)
    mn=mx=None
    if tc:
        for b in pf.iter_batches(batch_size=200000, columns=[tc]):
            v=b.column(tc).to_numpy()
            if len(v): mn=int(v.min()) if mn is None else min(mn,int(v.min())); mx=int(v.max()) if mx is None else max(mx,int(v.max()))
    print(f"\n##{os.path.basename(p)} rows={pf.metadata.num_rows:,} ncols={len(cols)}")
    if mn: print("  range:", pd.to_datetime(mn,unit='us',errors='coerce'),"->",pd.to_datetime(mx,unit='us',errors='coerce'))
    # asset coverage + key gate cols present
    has=[c for c in cols if c in ('asset','slug','fire_offset_s','entry_vwap','outcome','won','pnl_legacy_usd',
         'up_vwap','dn_vwap','up_ask0','dn_ask0','up_shares','dn_shares','strike_price','settle_price',
         'g_rf_with','g_tr_partial_stack_with','g_tr_stack_with','g_cci_with','g_cci_strong_with','g_mfi_with',
         'g_f7_with','g_tr_above_ema200','g_tr_above_ema800','g_tr_above_ema50','g_hod_european','hour_utc',
         'g_parent_15m_not_ranging','g_trend_slope_strong_with','g_trend_slope_with','g_mp_skew_with',
         'g_imb5_strong_with','g_dir_down','g_vwap_premium','g_btc_f7_with','g_hurst_trending','g_entry_vwap_in_band',
         'g_vwap_ge_50_le_85','g_rf_strict_align','g_tr_partial_stack')]
    print("  KEYCOLS:", has)
    if 'asset' in cols:
        a=pf.read(columns=['asset']).to_pandas()['asset'].value_counts().to_dict()
        print("  ASSETS:", a)
for f in sorted(cands): info(f)
