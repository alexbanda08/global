"""Find the mp_skew sleeve in the validated list and inspect."""
import pandas as pd, numpy as np
RES = "strategy_lab/sniper_search_2026_05_27/eth_5m/_results"
res = pd.read_csv(f"{RES}/all_validated.csv")

mask = res["sleeve_id"].str.contains("g_mp_skew_with") & res["sleeve_id"].str.contains("g_sms_liq_reclaim_with") & res["sleeve_id"].str.contains("g_sms_no_liquidity_above") & res["sleeve_id"].str.contains("g_tr_above_ema200")
print(f"matches: {mask.sum()}")
print(res[mask][["sleeve_id","n_lockbox","wr_lockbox","dpt_lockbox_25","dd_lockbox_25","ls_lockbox","sharpe_lockbox","active_days_lockbox","boot_p_lockbox","dpt_lockbox_250"]].to_string())

# Top by dpt_lockbox_25 in general (relaxed):
print("\n== Top 25 by dpt_lockbox_25 (all candidates, n_lockbox >= 5) ==")
m = (res["n_lockbox"] >= 5) & (res["dpt_lockbox_25"] >= 1.0)
top = res[m].sort_values("dpt_lockbox_25", ascending=False).head(25)
for _, r in top.iterrows():
    print(f"  WR_l={r['wr_lockbox']:.3f} $/tr={r['dpt_lockbox_25']:+.2f} n={r['n_lockbox']} ad={int(r['active_days_lockbox'])} dd=${r['dd_lockbox_25']:.0f} ls={int(r['ls_lockbox'])} sh={r['sharpe_lockbox']:.1f} p={r['boot_p_lockbox']:.3f}")
    print(f"    {r['sleeve_id']}")
