"""Full validation pass — load all_candidates, recompute metrics with correct bootstrap,
then filter against the full sniper profile."""
import pandas as pd, numpy as np
import os

UNIV = "data/v4/canonical/_results/_sniper_eth5m_v3_universe.parquet"
RES = "strategy_lab/sniper_search_2026_05_27/eth_5m/_results"

df = pd.read_parquet(UNIV)
all_c = pd.read_csv(f"{RES}/all_candidates.csv")

# Splits
days_sorted = sorted(df["day"].unique())
lockbox_days = set(days_sorted[-5:])
val_days = set(days_sorted[-11:-5])
train_days = set(days_sorted[:-11])

def parse_id(sid):
    parts = sid.split("|")
    return parts[1], parts[2].split("&")

def metrics(sub, stake=25.0):
    if len(sub) == 0:
        return dict(n=0)
    pnl = sub["pnl_legacy_usd"].values * (stake/25.0)
    won = sub["won"].values
    ord_idx = np.argsort(sub["fire_us"].values)
    pnl_o = pnl[ord_idx]; won_o = won[ord_idx]
    cum = np.cumsum(pnl_o); peak = np.maximum.accumulate(cum)
    dd = float((cum - peak).min())
    cur, mxls = 0, 0
    for w in won_o:
        if not w:
            cur += 1
            mxls = max(mxls, cur)
        else:
            cur = 0
    days_arr = pd.to_datetime(sub["fire_us"].values, unit="us").date
    unique_days = sorted(set(days_arr))
    day_pnls_map = {d: pnl[days_arr == d] for d in unique_days}
    by_day = np.array([day_pnls_map[d].sum() for d in unique_days])
    sharpe_active = (by_day.mean() / by_day.std() * np.sqrt(365)) if (by_day.std() > 0 and len(by_day) > 1) else 0.0
    # bootstrap p (one-sided, p = fraction <= 0)
    obs_mean = pnl.mean()
    if obs_mean > 0 and len(unique_days) >= 2:
        day_list = [day_pnls_map[d] for d in unique_days]
        rng = np.random.default_rng(42)
        n_iter = 1000
        means = np.empty(n_iter)
        for i in range(n_iter):
            idx = rng.integers(0, len(day_list), size=len(day_list))
            flat = np.concatenate([day_list[j] for j in idx])
            means[i] = flat.mean()
        p = float((means <= 0).mean())
    else:
        p = 1.0
    return dict(
        n=len(sub), wr=float(won.mean()), sum=float(pnl.sum()),
        dpt=float(pnl.mean()), dd=dd, loss_streak=mxls,
        sharpe=float(sharpe_active), active_days=len(unique_days),
        boot_p=p,
    )

# For each candidate, recompute val+lockbox with correct bootstrap
rows = []
for _, c in all_c.iterrows():
    sid = c["sleeve_id"]
    ob, gates = parse_id(sid)
    # Pool
    if ob.startswith("bin_"):
        pool = df[df["offset_bin"] == ob.replace("bin_", "")]
    elif ob.startswith("off_"):
        pool = df[df["fire_offset_s"] == int(ob.replace("off_", ""))]
    else:
        continue
    mask = np.ones(len(pool), dtype=bool)
    valid = True
    for g in gates:
        if g not in pool.columns:
            valid = False; break
        mask &= (pool[g].astype("float").fillna(0).values >= 1)
    if not valid:
        continue
    sub = pool[mask]
    # Per split
    sub_t = sub[sub["day"].isin(train_days)]
    sub_v = sub[sub["day"].isin(val_days)]
    sub_l = sub[sub["day"].isin(lockbox_days)]
    m_t = metrics(sub_t, 25.0)
    m_v = metrics(sub_v, 25.0)
    m_l_25 = metrics(sub_l, 25.0)
    m_l_250 = metrics(sub_l, 250.0)
    row = dict(
        sleeve_id=sid,
        offset_label=ob,
        gate_stack="&".join(gates),
        depth=len(gates),
        # train
        n_train=m_t["n"], wr_train=m_t["wr"], dpt_train_25=m_t.get("dpt",0),
        # val
        n_val=m_v["n"], wr_val=m_v["wr"], dpt_val_25=m_v.get("dpt",0),
        sharpe_val=m_v.get("sharpe",0), dd_val_25=m_v.get("dd",0), ls_val=m_v.get("loss_streak",0),
        # lockbox @ $25
        n_lockbox=m_l_25["n"], wr_lockbox=m_l_25["wr"], dpt_lockbox_25=m_l_25.get("dpt",0),
        sum_lockbox_25=m_l_25.get("sum",0), dd_lockbox_25=m_l_25.get("dd",0),
        ls_lockbox=m_l_25.get("loss_streak",0), sharpe_lockbox=m_l_25.get("sharpe",0),
        active_days_lockbox=m_l_25.get("active_days",0),
        boot_p_lockbox=m_l_25.get("boot_p",1.0),
        # lockbox @ $250
        dpt_lockbox_250=m_l_250.get("dpt",0),
        sum_lockbox_250=m_l_250.get("sum",0), dd_lockbox_250=m_l_250.get("dd",0),
    )
    rows.append(row)

res = pd.DataFrame(rows).drop_duplicates(subset=["sleeve_id"])
res.to_csv(f"{RES}/all_validated.csv", index=False)
print(f"== unique sleeves validated: {len(res)}")
print(f"   train spans {len(train_days)}d  val {len(val_days)}d  lockbox {len(lockbox_days)}d")

# Apply sniper profile (interpret strictly per brief):
# n / 32d in [50, 500]  -- approximate as n_lockbox >= 5 (1/day) up to 500
# WR_lockbox >= 0.75
# $/tr_25 >= 3
# max_dd_25 >= -300
# loss_streak <= 6
# sharpe >= 2.0
# boot_p <= 0.05
m_strict_25 = (
    (res["n_lockbox"] >= 5) & (res["n_lockbox"] <= 500) &
    (res["wr_lockbox"] >= 0.75) &
    (res["dpt_lockbox_25"] >= 3.0) &
    (res["dd_lockbox_25"] >= -300.0) &
    (res["ls_lockbox"] <= 6) &
    (res["sharpe_lockbox"] >= 2.0) &
    (res["boot_p_lockbox"] <= 0.05)
)
print(f"\nSTRICT sniper pass at $25: {m_strict_25.sum()}")

# At $250: same WR thresholds but scale dd allowance proportionally
m_strict_250 = (
    (res["n_lockbox"] >= 5) & (res["n_lockbox"] <= 500) &
    (res["wr_lockbox"] >= 0.75) &
    (res["dpt_lockbox_250"] >= 30.0) &  # $3 × 10
    (res["dd_lockbox_250"] >= -3000.0) &  # $300 × 10
    (res["ls_lockbox"] <= 6) &
    (res["sharpe_lockbox"] >= 2.0) &
    (res["boot_p_lockbox"] <= 0.05) &
    res["sleeve_id"].str.contains("g_book_depth_supports_250")
)
print(f"STRICT sniper pass at $250: {m_strict_250.sum()}")

# Save rosters
roster_25 = res[m_strict_25 & ~res["sleeve_id"].str.contains("g_book_depth_supports")].sort_values("dpt_lockbox_25", ascending=False)
roster_25_with_depth_25 = res[m_strict_25 & res["sleeve_id"].str.contains("g_book_depth_supports_25\\b", regex=True)].sort_values("dpt_lockbox_25", ascending=False)
roster_250 = res[m_strict_250].sort_values("dpt_lockbox_250", ascending=False)
print(f"  pure $25 (no depth gate): {len(roster_25)}")
print(f"  $25 with g_book_depth_supports_25 only: {len(roster_25_with_depth_25)}")
print(f"  $250-capable: {len(roster_250)}")

print()
print("== Top 15 pure $25 ==")
cols_show = ["sleeve_id","n_train","wr_train","dpt_train_25","n_val","wr_val","dpt_val_25",
             "n_lockbox","wr_lockbox","dpt_lockbox_25","sum_lockbox_25","dd_lockbox_25",
             "ls_lockbox","sharpe_lockbox","active_days_lockbox","boot_p_lockbox"]
for _, r in roster_25.head(15).iterrows():
    print(f"  WR={r['wr_lockbox']:.3f} $/tr={r['dpt_lockbox_25']:+.2f} n={r['n_lockbox']} dd=${r['dd_lockbox_25']:.0f} ls={int(r['ls_lockbox'])} sh={r['sharpe_lockbox']:.1f} ad={int(r['active_days_lockbox'])} p={r['boot_p_lockbox']:.3f} | v WR={r['wr_val']:.3f} n={r['n_val']} $/tr={r['dpt_val_25']:+.2f}")
    print(f"    {r['sleeve_id']}")

print()
print("== Top 15 $250-capable ==")
for _, r in roster_250.head(15).iterrows():
    print(f"  WR={r['wr_lockbox']:.3f} $/tr_250={r['dpt_lockbox_250']:+.2f} n={r['n_lockbox']} dd_250=${r['dd_lockbox_250']:.0f} ls={int(r['ls_lockbox'])} sh={r['sharpe_lockbox']:.1f} ad={int(r['active_days_lockbox'])} p={r['boot_p_lockbox']:.3f}")
    print(f"    {r['sleeve_id']}")

# Save top rosters
roster_25.head(15).to_csv(f"{RES}/roster_25_top.csv", index=False)
roster_250.head(15).to_csv(f"{RES}/roster_250_top.csv", index=False)
print()
print(f"wrote: {RES}/roster_25_top.csv  ({len(roster_25)} pass)")
print(f"       {RES}/roster_250_top.csv ({len(roster_250)} pass)")

# Near miss tracking (relaxed)
m_relax_25 = (
    (res["n_lockbox"] >= 5) &
    (res["wr_lockbox"] >= 0.7) &
    (res["dpt_lockbox_25"] >= 2.0)
)
nm = res[m_relax_25 & ~m_strict_25].sort_values("dpt_lockbox_25", ascending=False)
print(f"\nNear-misses (relaxed WR>=0.7 dpt>=2 but not strict pass): {len(nm)}")
for _, r in nm.head(10).iterrows():
    fail = []
    if r["wr_lockbox"] < 0.75: fail.append(f"WR={r['wr_lockbox']:.2f}<0.75")
    if r["dpt_lockbox_25"] < 3: fail.append(f"$/tr={r['dpt_lockbox_25']:.2f}<3")
    if r["dd_lockbox_25"] < -300: fail.append(f"dd={r['dd_lockbox_25']:.0f}<-300")
    if r["ls_lockbox"] > 6: fail.append(f"ls={r['ls_lockbox']}>6")
    if r["sharpe_lockbox"] < 2.0: fail.append(f"sh={r['sharpe_lockbox']:.1f}<2")
    if r["boot_p_lockbox"] > 0.05: fail.append(f"p={r['boot_p_lockbox']:.2f}>0.05")
    print(f"  fail: {','.join(fail)}")
    print(f"    {r['sleeve_id']}")
