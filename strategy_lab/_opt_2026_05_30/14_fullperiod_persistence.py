"""
14 — Full-period (Apr 24 -> May 26) persistence test on the sniper UNIVERSE panels.
TWO questions:
 (A) Base-sleeve overfit decay: universe is the GA TRAINING set (in-sample) -> high by construction.
     We report in-sample WR/EV + weekly buckets to expose instability (the real OOS is the live window).
 (B) MY GATE persistence (the legit OOS test): my gates were fit on the LIVE window (May 27-31).
     Testing them on the Apr 24-May 26 universe = OUT-OF-SAMPLE for my gates. Does the lift hold?
PnL recomputed on the 0.07 curve, flat $5 (shares=5/entry_vwap).
"""
import pandas as pd, os, numpy as np
RES=r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical\_results"

def pnl07(vwap, won):
    vwap=np.asarray(vwap,float); won=np.asarray(won,bool)
    sh=5.0/np.clip(vwap,1e-3,None)
    return np.where(won, sh*(1-vwap)*(1-0.07*vwap), -sh*vwap)

# sleeve -> (panel, gate cols, offset(s))  [gates AND'd; reconstruction approximate where noted]
SLEEVES={
 "eth_cloud_ribbon_v6":      ("_sniper_eth5m_v6_universe",["g_tr_above_cloud","g_ribbon_agrees","g_mp_skew_with","g_hurst_trending"],[60]),
 "eth_bb_mp_hurst_v6":       ("_sniper_eth5m_v6_universe",["g_bb_pos_with","g_mp_skew_with","g_hurst_trending","g_entry_vwap_in_band"],[60]),
 "eth_cloud_vwap_v7":        ("_sniper_eth5m_v7_universe",["g_tr_above_cloud","g_entry_vwap_in_band","g_hurst_mp_trend_with"],[60]),
 "eth_l_ema50_grandparent_v8":("_sniper_eth5m_v8_universe",["g_tr_above_ema50","g_hurst_trending","g_grandparent_trend_with"],[60]),
 "btc_parent15m_notrang_v7": ("_sniper_btc_5m_enriched",["g_trend_slope_strong_with","g_mp_skew_with"],[30,60,90,120,150,180,210,240,270]),
 "btc_l_1hrf_imb5_ribbon_v8":("_sniper_btc_5m_enriched",["g_rf_with","g_imb5_strong_with","g_ribbon_agrees"],[120,150,180,210,240,270]),
 "btc_q_parent15m_imb5_v8":  ("_sniper_btc_5m_enriched",["g_imb5_strong_with","g_trend_slope_strong_with"],[120,150,180,210,240,270]),
 "btc_ts_mpskew_off30":      ("_sniper_btc_5m_enriched",["g_trend_slope_with","g_mp_skew_with"],[30]),
}
LIVE={ # live OOS reference (May 27-31): (n, WR%, total$)
 "eth_cloud_ribbon_v6":(84,72.6,14),"eth_bb_mp_hurst_v6":(107,72.9,50),
 "eth_cloud_vwap_v7":(93,71.0,32),"eth_l_ema50_grandparent_v8":(78,73.1,72),
 "btc_parent15m_notrang_v7":(176,76.7,5),"btc_l_1hrf_imb5_ribbon_v8":(506,74.5,-139),
 "btc_q_parent15m_imb5_v8":(1232,66.6,-930),"btc_ts_mpskew_off30":(120,54.2,-93),
}

def mean_ci(p):
    p=np.asarray(p,float);
    if len(p)<10: return np.nan,np.nan
    rng=np.random.default_rng(0); idx=rng.integers(0,len(p),(2000,len(p)))
    return p.mean(), np.percentile(p[idx].mean(1),2.5)

rows=[]; gate_rows=[]
for name,(panel,gates,offs) in SLEEVES.items():
    p=os.path.join(RES,panel+".parquet")
    if not os.path.exists(p): print(f"SKIP {name}: no panel"); continue
    df=pd.read_parquet(p)
    present=[g for g in gates if g in df.columns]; missing=[g for g in gates if g not in df.columns]
    m=np.ones(len(df),bool)
    for g in present: m&=df[g].fillna(False).astype(bool)
    m&=df["fire_offset_s"].isin(offs)
    f=df[m].copy()
    if len(f)==0: print(f"{name}: 0 fires (gates {present} missing {missing})"); continue
    f["pnl"]=pnl07(f["entry_vwap"], f["won"].astype(bool))
    f["d"]=pd.to_datetime(f["fire_us"],unit="us"); f["wk"]=f["d"].dt.isocalendar().week.astype(int)
    if "hour_utc" in f: f["hr"]=f["hour_utc"]
    else: f["hr"]=f["d"].dt.hour
    mn,cl=mean_ci(f["pnl"].values)
    lv=LIVE.get(name,(0,0,0))
    rows.append(dict(sleeve=name, gates=("+".join(present))+("  MISS:"+",".join(missing) if missing else ""),
        IS_n=len(f), IS_wr=round(100*f["won"].mean(),1), IS_mean=round(mn,3), IS_total=round(f["pnl"].sum(),1),
        IS_cilo=round(cl,3), live_n=lv[0], live_wr=lv[1], live_total=lv[2]))
    # weekly
    wk=f.groupby("wk").agg(n=("pnl","size"),wr=("won",lambda x:round(100*x.mean(),1)),tot=("pnl",lambda x:round(x.sum(),1))).reset_index()
    wk["sleeve"]=name
    # --- MY GATE persistence (OOS = this universe period) ---
    for gn,mask in [("entry_vwap<=0.70", f["entry_vwap"]<=0.70),
                    ("drop_US(hr!14-21)", ~f["hr"].between(14,21)),
                    ("vsum<=1.30", (f.get("up_vwap",pd.Series(np.nan,index=f.index))+f.get("dn_vwap",pd.Series(np.nan,index=f.index)))<=1.30)]:
        sub=f[mask.fillna(False)]
        if len(sub)<20 or sub["pnl"].isna().all(): continue
        gate_rows.append(dict(sleeve=name, gate=gn, base_mean=round(f["pnl"].mean(),3),
            gated_n=len(sub), gated_mean=round(sub["pnl"].mean(),3),
            lift=round(sub["pnl"].mean()-f["pnl"].mean(),3), gated_total=round(sub["pnl"].sum(),1)))
    print(f"[{name}] IS n={len(f)} wr={100*f['won'].mean():.1f}% total=${f['pnl'].sum():.0f}  weeks:", wk[["wk","n","wr","tot"]].to_dict("records"))

R=pd.DataFrame(rows); R.to_csv(os.path.join(os.path.dirname(RES),"_results","..","..","..","strategy_lab","_opt_2026_05_30","_results","fullperiod_base.csv") if False else r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\_opt_2026_05_30\_results\fullperiod_base.csv",index=False)
G=pd.DataFrame(gate_rows); G.to_csv(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\_opt_2026_05_30\_results\fullperiod_gate_persist.csv",index=False)
pd.set_option("display.width",240)
print("\n=== (A) BASE: in-sample (universe Apr24-May26) vs live OOS (May27-31) ===")
print(R[["sleeve","IS_n","IS_wr","IS_mean","IS_total","IS_cilo","live_n","live_wr","live_total"]].to_string(index=False))
print("\n=== (B) MY-GATE persistence on the universe period (OOS for my gates) ===")
print(G.to_string(index=False))
