"""
momo_HOLD_f7 — rigor (permutation, walk-forward, DSR) + BACKTEST vs LIVE comparison.
Inputs: momo_f7_bt_alltrades_2026_06_08.parquet (backtest) + momo_f7_live_fires.csv (live shadow, dedup metric).
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats
ROOT=Path(r"C:\Users\alexandre bandarra\Desktop\global"); RES=ROOT/"strategy_lab/directional/_results"
np.random.seed(0)
BT=pd.read_parquet(RES/"momo_f7_bt_alltrades_2026_06_08.parquet")
BT["date"]=pd.to_datetime(BT.fire_us,unit="us",utc=True)
LV=pd.read_csv(RES/"momo_f7_live_fires.csv").rename(columns={"pnl_usd":"pnl","entry_price":"ev","signal":"sig"})
LV["won"]=LV.won.astype(str).str.lower().isin(["true","1","t","yes"])
LV["pnl"]=pd.to_numeric(LV.pnl,errors="coerce"); LV["ev"]=pd.to_numeric(LV.ev,errors="coerce")
LV=LV.dropna(subset=["pnl"])
LV["dt"]=pd.to_datetime(pd.to_numeric(LV["fire_at_us"],errors="coerce"),unit="us",utc=True)
LIVE_LO=pd.Timestamp("2026-05-21",tz="UTC")

def boot(v,nb=5000):
    v=np.asarray(v); i=np.random.randint(0,len(v),(nb,len(v))); return tuple(np.percentile(v[i].mean(1),[2.5,97.5]))
def line(g,col):
    v=g[col].values; n=len(v)
    if n<3: return dict(n=n,wr=np.nan,tr=np.nan,tot=np.nan,vw=np.nan,lo=np.nan,hi=np.nan)
    lo,hi=boot(v)
    return dict(n=n,wr=100*g.won.mean(),tr=v.mean(),tot=v.sum(),
                vw=(g.ev.mean() if 'ev' in g else g.entry_vwap.mean()),lo=lo,hi=hi)

print("="*96)
print("BACKTEST vs LIVE — momo_HOLD_f7  (BT pnl_07 / LIVE dedup pnl_usd, both 0.07 fee, $25)")
print("="*96)
hdr=f"{'sleeve / window':<42}{'n':>4}{'WR%':>7}{'$/tr':>8}{'total':>9}{'vwap':>7}  {'CI95':>18}"
for coin in ["btc","eth","sol"]:
    sid=f"poly_updown_{coin}_15m_momo_HOLD_f7"
    bt=BT[BT.sleeve_id==sid]; btl=bt[bt.date>=LIVE_LO]; lv=LV[LV.sleeve_id==sid]
    print("\n"+hdr)
    for lab,g,c in [("BT full Apr22-Jun8",bt,"pnl_07"),("BT live-window May21+",btl,"pnl_07"),("LIVE shadow May21-Jun8",lv,"pnl")]:
        s=line(g,c)
        ci=f"[{s['lo']:+.2f},{s['hi']:+.2f}]" if np.isfinite(s['lo']) else "-"
        print(f"  {coin.upper()} {lab:<36}{s['n']:>4}{s['wr']:>7.1f}{s['tr']:>+8.2f}{s['tot']:>+9.1f}{s['vw']:>7.3f}  {ci:>18}")

# ---- RIGOR on full backtest (per coin) ----
print("\n"+"="*96); print("RIGOR (full-window backtest)"); print("="*96)
for coin in ["btc","eth","sol"]:
    sid=f"poly_updown_{coin}_15m_momo_HOLD_f7"; g=BT[BT.sleeve_id==sid].sort_values("fire_us")
    v=g.pnl_07.values; n=len(v)
    if n<10: print(f"  {coin.upper()}: n={n} too few"); continue
    # permutation: shuffle won -> recompute pnl under random direction-correctness, null $/tr
    base=v.mean()
    # null: randomly flip each trade's outcome (won<->lost) keeping vwap; pnl under random 50/50 direction
    vw=g.entry_vwap.values; sh=25.0/vw
    win_pnl=sh*(1-vw)*(1-0.07*vw); los_pnl=-sh*vw
    perm=[]
    for _ in range(5000):
        w=np.random.rand(n)<0.5
        perm.append(np.where(w,win_pnl,los_pnl).mean())
    perm=np.array(perm); p_perm=(perm>=base).mean()
    # walk-forward: 4 chronological folds, OOS $/tr
    folds=np.array_split(np.arange(n),4); wf=[v[f].mean() for f in folds]
    # DSR: Sharpe of per-trade pnl, deflate for n_trials (momo family ~18 sleeves searched)
    sr=v.mean()/v.std(ddof=1) if v.std()>0 else np.nan
    try:
        from ml4t.diagnostic.evaluation.stats.deflated_sharpe_ratio import deflated_sharpe_ratio_from_statistics
        dsr=deflated_sharpe_ratio_from_statistics(observed_sr=sr, n_trials=18, n_obs=n,
              skew=float(stats.skew(v)), kurtosis=float(stats.kurtosis(v,fisher=False)), sr_benchmark=0.0)
        dsr_s=f"{float(dsr):.3f}"
    except Exception as e:
        dsr_s=f"n/a({type(e).__name__})"
    print(f"\n  {coin.upper()} n={n} $/tr={base:+.3f}")
    print(f"    permutation p(>=base under random dir)= {p_perm:.4f}  ({'SIG' if p_perm<0.05 else 'NS'})")
    print(f"    walk-forward 4 folds $/tr: "+" ".join(f"{x:+.2f}" for x in wf)+f"  (pos folds {sum(x>0 for x in wf)}/4)")
    print(f"    per-trade Sharpe={sr:.3f}  DSR(n_trials=18)={dsr_s}")

# ---- weekly alignment (BT live-window vs LIVE) ----
print("\n"+"="*96); print("WEEKLY ALIGNMENT (BT live-window vs LIVE)"); print("="*96)
for coin in ["btc","eth","sol"]:
    sid=f"poly_updown_{coin}_15m_momo_HOLD_f7"
    btl=BT[(BT.sleeve_id==sid)&(BT.date>=LIVE_LO)].copy(); lv=LV[LV.sleeve_id==sid].copy()
    btl["wk"]=btl.date.dt.isocalendar().week; lv["wk"]=lv.dt.dt.isocalendar().week
    b=btl.groupby("wk").agg(bt_n=("won","size"),bt_wr=("won",lambda x:round(100*x.mean(),0)),bt_tr=("pnl_07",lambda x:round(x.mean(),2)))
    l=lv.groupby("wk").agg(lv_n=("won","size"),lv_wr=("won",lambda x:round(100*x.mean(),0)),lv_tr=("pnl",lambda x:round(x.mean(),2)))
    m=b.join(l,how="outer")
    print(f"\n  {coin.upper()}:"); print(m.to_string())
print("\nREAD: live confirms backtest only if BT-live-window WR/$/tr ~ LIVE on the SAME weeks. Large WR gap = fire-set/fill mismatch.")
