import pandas as pd, numpy as np, sys
sys.path.insert(0, r'C:/Users/alexandre bandarra/Desktop/global/strategy_lab/directional')
from scalp_fill_lib_2026_06_10 import boot

R = pd.read_parquet(r'C:/Users/alexandre bandarra/Desktop/global/strategy_lab/wallet_hunt/cache/_b945_ladder_sim.parquet')
days = (R.ss.max() - R.ss.min()) / 86400
print(f"rows={len(R)}  days={days:.0f}")

print()
print(f"{'Cell':<14} {'pct_both':>9} {'pf':>6} {'pvs_med':>8} {'pct_lt1':>8} {'pct_lt98':>9} {'pair_per_w':>11} {'res_per_w':>10} {'net_per_w':>10} {'CI_lo':>8} {'CI_hi':>8} {'ex_top2':>8}")
print("-"*110)

for lname in ('L1','L3'):
    for fmodel in ('fifo','prop'):
        tag = f"{lname}_{fmodel}"
        both = (R[f"{tag}_q_up"] > 1e-9) & (R[f"{tag}_q_dn"] > 1e-9)
        any_ = (R[f"{tag}_q_up"] > 1e-9) | (R[f"{tag}_q_dn"] > 1e-9)
        total_pairs  = R[f"{tag}_pairs"].sum()
        total_filled = (R[f"{tag}_q_up"] + R[f"{tag}_q_dn"]).sum()
        pf = total_pairs / total_filled if total_filled > 0 else 0.0
        pvs_vals = R.loc[both, f"{tag}_pvs"].dropna()
        pvs_med  = pvs_vals.median() if len(pvs_vals) else float('nan')
        pct_lt1  = (pvs_vals < 1.0).mean() if len(pvs_vals) else float('nan')
        pct_lt98 = (pvs_vals < 0.98).mean() if len(pvs_vals) else float('nan')
        net_pnl  = R.loc[any_, f"{tag}_net_pnl"]
        pnl_pair = R.loc[both, f"{tag}_paired_pnl"]
        pnl_res  = R.loc[both, f"{tag}_residual_pnl"]
        lo, hi   = boot(net_pnl.values) if len(net_pnl) > 5 else (float('nan'), float('nan'))
        if len(net_pnl) > 2:
            ex2 = np.sort(net_pnl.values)[:-2].mean()
        else:
            ex2 = float('nan')
        print(f"{tag:<14} {both.mean():>9.1%} {pf:>6.1%} {pvs_med:>8.4f} {pct_lt1:>8.1%} {pct_lt98:>9.1%} {pnl_pair.mean():>11.4f} {pnl_res.mean():>10.4f} {net_pnl.mean():>10.4f} {lo:>8.4f} {hi:>8.4f} {ex2:>8.4f}")

print()
print("--- b945 GT (r2, 1562 slugs): ~77% both | 44% pf | 0.970 pvs | ~77%<1 | 47%<0.98 | +22.71 paired | -18.78 res | +4.23 net ---")

print()
print("=== GO/NO-GO (pre-registered) ===")
any_pass = False
for lname in ('L1','L3'):
    tag = f"{lname}_fifo"
    both = (R[f"{tag}_q_up"] > 1e-9) & (R[f"{tag}_q_dn"] > 1e-9)
    any_ = (R[f"{tag}_q_up"] > 1e-9) | (R[f"{tag}_q_dn"] > 1e-9)
    pvs_vals = R.loc[both, f"{tag}_pvs"].dropna()
    pvs_med  = pvs_vals.median() if len(pvs_vals) else float('nan')
    pf = R[f"{tag}_pairs"].sum() / (R[f"{tag}_q_up"] + R[f"{tag}_q_dn"]).sum() if (R[f"{tag}_q_up"] + R[f"{tag}_q_dn"]).sum() > 0 else 0
    net_pnl = R.loc[any_, f"{tag}_net_pnl"]
    lo, hi  = boot(net_pnl.values) if len(net_pnl) > 5 else (float('nan'), float('nan'))
    g_pvs, g_pf, g_ci = (pvs_med <= 0.98), (pf >= 0.44), (lo > 0)
    verdict = "PASS" if (g_pvs and g_pf and g_ci) else "FAIL"
    print(f"  {tag}: pvs_med={pvs_med:.4f}({'ok' if g_pvs else 'FAIL'}) pf={pf:.1%}({'ok' if g_pf else 'FAIL'}) CI=[{lo:+.4f},{hi:+.4f}]({'ok' if g_ci else 'FAIL'}) -> {verdict}")
    if g_pvs and g_pf and g_ci:
        any_pass = True

print()
print("GATE: GO" if any_pass else "GATE: NO-GO -- infra+rebate moat, not replicable.")
