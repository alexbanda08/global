import pandas as pd, os
B=r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\_opt_2026_05_30\_results"
def rd(f):
    p=os.path.join(B,f); return pd.read_csv(p) if os.path.exists(p) else None
fg=rd("final_gated_configs.csv"); ext=rd("external_gates.csv"); hl=rd("hedge_late_sweep.csv")
pd.set_option("display.width",260); pd.set_option("display.max_colwidth",60)
print("FG_COLS", list(fg.columns) if fg is not None else None)
print("EXT_COLS", list(ext.columns) if ext is not None else None)
print("HL_COLS", list(hl.columns) if hl is not None else None)
if fg is not None:
    c=[x for x in ["sleeve","base_n","base_wr","base_total","base_mean","stack","gated_n","gated_total","gated_mean","ci_lo"] if x in fg.columns]
    print("\n@@FINAL_GATED@@")
    print(fg[c].round(3).to_string(index=False))
if hl is not None:
    print("\n@@HEDGE_LATE_ROBUST@@")
    w=hl[hl.beats==True].sort_values("delta_total",ascending=False)
    if len(w): print(w.groupby("sleeve").first().reset_index()[["sleeve","base_total","frac","late_s","delta_total","cilo","wf_h1","wf_h2"]].round(3).to_string(index=False))
    print("HL_TESTED", sorted(hl.sleeve.unique()))
    print("@@HEDGE_LATE_HURTS_OR_NONE@@", sorted(set(hl.sleeve.unique())-set(hl[hl.beats==True].sleeve.unique())))
if ext is not None:
    print("\n@@EXTERNAL@@")
    print(ext.to_string(index=False))
