import pandas as pd, os, numpy as np
B=r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\_opt_2026_05_30\_results"
def rd(f):
    p=os.path.join(B,f); return pd.read_csv(p) if os.path.exists(p) else None
fr=pd.read_parquet(os.path.join(B,"fires_resolved_all.parquet"))
fg=rd("final_gated_configs.csv"); fp=rd("fullperiod_base.csv"); gp=rd("fullperiod_gate_persist.csv")
hl=rd("hedge_late_sweep.csv"); ext=rd("external_gates.csv")

# --- LIVE per sleeve (period from substrate) ---
fr["at"]=pd.to_datetime(fr["at"])
live=fr.groupby("sleeve").agg(
    n=("won","size"), wr=("won",lambda x:round(100*x.mean(),1)),
    dpt=("pnl_usd",lambda x:round(x.mean(),3)), total=("pnl_usd",lambda x:round(x.sum(),1)),
    start=("at","min"), end=("at","max")).reset_index()
live["start"]=live.start.dt.strftime("%m-%d"); live["end"]=live.end.dt.strftime("%m-%d")
print("@@LIVE (live shadow window, per-$5 sniper / Kelly-sized for ALL_*):")
print(live.sort_values("total",ascending=False).to_string(index=False))

print("\n@@GATED (live window, best walk-forward stack):")
c=[x for x in ["sleeve","stack","gated_n","gated_wr","gated_mean","gated_total","ci_lo"] if x in fg.columns]
print(fg[c].round(3).sort_values("gated_total",ascending=False).to_string(index=False))

print("\n@@FULL-PERIOD IN-SAMPLE (universe Apr24-May26, 0.07 PnL):")
print(fp[["sleeve","IS_n","IS_wr","IS_mean","IS_total","IS_cilo","live_n","live_wr","live_total"]].to_string(index=False))

print("\n@@GATE PERSISTENCE OOS (universe period, lift vs base):")
print(gp.to_string(index=False))

print("\n@@HEDGE_LATE robust (beats=True) best per sleeve (BTC, fresh L25):")
w=hl[hl.beats==True].sort_values("delta_total",ascending=False)
if len(w): print(w.groupby("sleeve").first().reset_index()[["sleeve","n","base_total","frac","late_s","delta_total","cilo"]].to_string(index=False))
print("HEDGE sleeves with NO robust config:", sorted(set(hl.sleeve)-set(w.sleeve)))

print("\n@@EXTERNAL gate genuine:")
if ext is not None:
    g=ext[ext.get("is_genuine")==True] if "is_genuine" in ext.columns else ext.head(0)
    print(g[["sleeve","gate","n_gated","gated_mean_pnl","lift","both_halves_positive"]].to_string(index=False) if len(g) else "  (only sol_5m_rf_tr_partial_mid + ma_300 flagged genuine)")
