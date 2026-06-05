import pandas as pd, os, pyarrow.parquet as pq, numpy as np
RES=r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical\_results"
def cov(p,label,tcols=('fire_us','ts_us','slot_start_us','fire_s','at_us')):
    if not os.path.exists(p): print(f"\n##{label}: MISSING"); return
    pf=pq.ParquetFile(p); n=pf.metadata.num_rows; cols=[f.name for f in pf.schema_arrow]
    # find a time col, scan all row groups for min/max
    tc=next((c for c in tcols if c in cols),None)
    mn=mx=None
    if tc:
        for b in pf.iter_batches(batch_size=100000, columns=[tc]):
            v=b.column(tc).to_numpy(); v=v[np.isfinite(v)] if v.dtype.kind=='f' else v
            if len(v):
                lo,hi=int(v.min()),int(v.max())
                mn=lo if mn is None else min(mn,lo); mx=hi if mx is None else max(mx,hi)
        u=1e6 if mn and mn>1e12 else (1 if mn and mn>1e8 else 1e6)
        rngs=f"{pd.to_datetime(mn/ (1e6 if mn>1e15 else 1),unit='s' if mn<1e12 else 'us',errors='coerce')}"
    print(f"\n##{label} rows={n:,} ncols={len(cols)} tcol={tc} min={mn} max={mx}")
    if mn: print("   range:", pd.to_datetime(mn,unit='us',errors='coerce'),"->",pd.to_datetime(mx,unit='us',errors='coerce'))
    print("   cols:", cols)
for f,l in [("_sniper_eth5m_v6_universe","ETH5m_v6_universe"),
            ("_sniper_eth5m_v8_universe","ETH5m_v8_universe"),
            ("sniper_btc15m_master","BTC15m_master"),
            ("sniper_btc15m_gated","BTC15m_gated"),
            ("dirscan_sol_5m","dirscan_sol_5m"),
            ("master_gate_features_v2","master_gate_features_v2"),
            ("vol_hurst_at_fire_5m","vol_hurst_5m"),
            ("master_5m_panel","master_5m_panel_FULLRANGE")]:
    cov(os.path.join(RES,f+".parquet"),l)
