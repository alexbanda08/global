"""Look at all_validated.csv and find the actual strict survivors.
The strict test needs n_lockbox >= 5 AND active_days_lockbox >= 2 AND sharpe >= 2."""
import pandas as pd, numpy as np
RES = "strategy_lab/sniper_search_2026_05_27/eth_5m/_results"
res = pd.read_csv(f"{RES}/all_validated.csv")
print(f"total: {len(res)}")
print(f"have active_days >= 2: {(res['active_days_lockbox'] >= 2).sum()}")
print(f"have WR_lockbox >= 0.75: {(res['wr_lockbox'] >= 0.75).sum()}")
print(f"have n_lockbox >= 5: {(res['n_lockbox'] >= 5).sum()}")
print(f"have dpt_lockbox_25 >= 3: {(res['dpt_lockbox_25'] >= 3).sum()}")
print(f"have dpt_lockbox_25 >= 0: {(res['dpt_lockbox_25'] >= 0).sum()}")
print(f"have sharpe_lockbox >= 2: {(res['sharpe_lockbox'] >= 2).sum()}")
print(f"have boot_p_lockbox <= 0.05: {(res['boot_p_lockbox'] <= 0.05).sum()}")

m = (res['n_lockbox'] >= 5) & (res['active_days_lockbox'] >= 2) & (res['wr_lockbox'] >= 0.75) & (res['dpt_lockbox_25'] >= 3.0)
print(f"\nn>=5 + active>=2 + WR>=0.75 + $/tr>=3: {m.sum()}")
print()
print(res[m].sort_values("dpt_lockbox_25", ascending=False).head(20)[
    ["sleeve_id","n_train","wr_train","dpt_train_25","n_val","wr_val","dpt_val_25",
     "n_lockbox","wr_lockbox","dpt_lockbox_25","dd_lockbox_25","ls_lockbox",
     "sharpe_lockbox","active_days_lockbox","boot_p_lockbox","dpt_lockbox_250","sum_lockbox_250"]
].to_string())

print()
print("== Full strict pass ==")
m2 = m & (res['ls_lockbox'] <= 6) & (res['dd_lockbox_25'] >= -300) & (res['sharpe_lockbox'] >= 2) & (res['boot_p_lockbox'] <= 0.05)
print(f"count: {m2.sum()}")
print(res[m2].sort_values("dpt_lockbox_25", ascending=False).head(15)[
    ["sleeve_id","n_lockbox","wr_lockbox","dpt_lockbox_25","sum_lockbox_25","dd_lockbox_25",
     "ls_lockbox","sharpe_lockbox","active_days_lockbox","boot_p_lockbox","dpt_lockbox_250","sum_lockbox_250"]
].to_string())
