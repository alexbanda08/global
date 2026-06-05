import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd, numpy as np

p7 = pd.read_parquet("strategy_lab/sniper_search_2026_05_27/sol_5m_v7/_panel_sol_5m_v7.parquet")
p8 = pd.read_parquet("strategy_lab/sniper_search_2026_05_27/sol_5m_v8/_panel_sol_5m_v8.parquet")

for nm,p in [("V7",p7),("V8",p8)]:
    has_cci = "cci_60s" in p.columns
    print(f"{nm}: has cci_60s col? {has_cci}; g_cci_extreme_with pass-rate={p['g_cci_extreme_with'].mean()*100:.2f}%")
    if has_cci:
        d_up = p.direction=="UP"; d_dn=p.direction=="DOWN"
        cci = p["cci_60s"]
        g100 = (((cci>100)&d_up)|((cci<-100)&d_dn)).fillna(False)
        g150 = (((cci>150)&d_up)|((cci<-150)&d_dn)).fillna(False)
        # match panel gate to which threshold?
        pg = p["g_cci_extreme_with"].astype(int).values==1
        print(f"   panel g matches |CCI|>100: {(pg==g100.values).mean()*100:.1f}%   matches |CCI|>150: {(pg==g150.values).mean()*100:.1f}%")
        print(f"   cci_60s notna={cci.notna().mean()*100:.1f}%  >100-rate={g100.mean()*100:.2f}%  >150-rate={g150.mean()*100:.2f}%")

# Re-evaluate full conjunction under BOTH cci thresholds (live uses 150)
def conj(p, base_gates, cci_thr):
    d_up=p.direction=="UP"; d_dn=p.direction=="DOWN"; cci=p["cci_60s"]
    gcci=(((cci>cci_thr)&d_up)|((cci<-cci_thr)&d_dn)).fillna(False).values
    m=gcci.copy()
    for g in base_gates: m=m & (p[g].astype(int).values==1)
    return m

for nm,p,base in [("V7_S1",p7,["g_btc_trend_30m_with","g_hurst_reverting"]),
                  ("V8_S1",p8,["g_btc_f7_against","g_hurst_reverting","g_mfi_strong_with"])]:
    n100=conj(p,base,100).sum(); n150=conj(p,base,150).sum()
    print(f"\n{nm} full conjunction fires (full bt window): |CCI|>100(panel/backtest)={n100}  |CCI|>150(LIVE thr)={n150}  shrink={100*(1-n150/max(n100,1)):.0f}%")
