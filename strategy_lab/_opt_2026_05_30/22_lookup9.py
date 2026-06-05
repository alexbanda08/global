import pandas as pd, numpy as np, os
OUTD=r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\_opt_2026_05_30\_results"
R=pd.read_parquet(os.path.join(OUTD,"all_sleeve_fires.parquet"))
TARGETS=[
 "eth_5m_tr200_mp_sms_active_off120","btc_15m_ts_trstack_off600_down",
 "btc_15m_ema50_ema800_off600_down","eth_5m_v5repl_off120_v6",
 "btc_15m_vwapprem_ema50_mpskew_off600_v6","btc_5m_parent15m_slope_ts_mpnx_v7",
 "eth_5m_l_ema50_hurst_grandparent_v8","sol_5m_b1_polyflow_aligned_v9","sol_5m_down_b1_500_v9"]
R["at"]=pd.to_datetime(R["at"])
rows=[]
for suf in TARGETS:
    sub=R[R.sleeve.str.endswith(suf)]
    if len(sub)==0:
        rows.append(dict(sleeve=suf, n=0, note="NO RESOLUTIONS in 21d window")); continue
    pnl=sub.pnl.values
    up=sub[sub.direction.isin(["UP","Up"])]; dn=sub[sub.direction.isin(["DOWN","Down"])]
    rows.append(dict(sleeve=suf, n=len(sub), wr=round(100*sub.won.mean(),1),
        dpt=round(np.nanmean(pnl),3), total=round(np.nansum(pnl),1),
        std=round(np.nanstd(pnl),2), sharpe=round(np.nanmean(pnl)/np.nanstd(pnl),3) if np.nanstd(pnl)>0 else 0,
        ppd=round(np.nanmean(sub.ppd),4),
        nUP=len(up), nDN=len(dn), wrUP=round(100*up.won.mean(),1) if len(up) else None,
        wrDN=round(100*dn.won.mean(),1) if len(dn) else None,
        start=sub["at"].min().strftime("%m-%d"), end=sub["at"].max().strftime("%m-%d")))
df=pd.DataFrame(rows)
pd.set_option("display.width",240)
print(df.to_string(index=False))
