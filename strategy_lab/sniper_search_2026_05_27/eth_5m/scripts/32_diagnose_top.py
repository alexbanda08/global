"""Diagnose the top candidates: per-day distribution on lockbox + sharpe + bootstrap."""
import pandas as pd, numpy as np

UNIV = "data/v4/canonical/_results/_sniper_eth5m_v3_universe.parquet"
df = pd.read_parquet(UNIV)

# Top candidates from prior analysis
TOPS = [
    # ($25-only? = no, $250-capable since they require g_book_depth_supports_250)
    ("eth5m|off_120|g_ribbon_agrees&g_sms_liq_reclaim_with&g_sms_no_liquidity_above&g_tr_above_cloud&g_book_depth_supports_250", 120),
    ("eth5m|off_120|g_ribbon_agrees&g_sms_liq_reclaim_with&g_tr_above_cloud&g_book_depth_supports_250", 120),
    ("eth5m|off_120|g_mp_skew_with&g_sms_liq_reclaim_with&g_sms_no_liquidity_above&g_tr_above_ema200", 120),  # $25-only
    ("eth5m|off_120|g_ribbon_agrees&g_sms_liq_reclaim_with&g_tr_above_ema200&g_book_depth_supports_250", 120),
    ("eth5m|off_120|g_rf_fresh&g_ribbon_agrees&g_sms_liq_reclaim_with&g_tr_above_ema200&g_book_depth_supports_250", 120),
    ("eth5m|off_90|g_ribbon_agrees&g_sms_liq_reclaim_with&g_sms_no_liquidity_above&g_tr_above_ema200&g_tr_above_ema50&g_book_depth_supports_250", 90),
]

train_days = set(d for d in sorted(df["day"].unique())[:-11])
val_days = set(sorted(df["day"].unique())[-11:-5])
lockbox_days = set(sorted(df["day"].unique())[-5:])
print(f"Train days: {len(train_days)}   Val days: {len(val_days)}   Lockbox days: {sorted(lockbox_days)}")

for sleeve_id, offset in TOPS:
    gates = sleeve_id.split("|")[-1].split("&")
    print()
    print("="*80)
    print(f"Sleeve: {sleeve_id}")
    print(f"  gates: {gates}")
    pool = df[df["fire_offset_s"] == offset]
    m = np.ones(len(pool), dtype=bool)
    for g in gates:
        m &= (pool[g].astype("float").fillna(0).values >= 1)
    sub = pool[m]
    print(f"  Total over 33d: n={len(sub)}, WR={sub['won'].mean():.3f}, $/tr=${sub['pnl_legacy_usd'].mean():+.3f}, sum=${sub['pnl_legacy_usd'].sum():+.2f}")
    for split_name, days in [("train", train_days), ("val", val_days), ("lockbox", lockbox_days)]:
        s = sub[sub["day"].isin(days)]
        n = len(s)
        if n == 0:
            print(f"  {split_name:8s} n=0")
            continue
        wr = s["won"].mean()
        dpt = s["pnl_legacy_usd"].mean()
        ssum = s["pnl_legacy_usd"].sum()
        n_days_active = s["day"].nunique()
        # daily PnL
        by_day = s.groupby("day")["pnl_legacy_usd"].sum()
        daily_mean = by_day.mean()
        daily_std = by_day.std()
        sharpe = (daily_mean / daily_std * np.sqrt(365)) if (daily_std and daily_std > 0) else 0.0
        print(f"  {split_name:8s} n={n:4d}  WR={wr:.3f}  $/tr=${dpt:+.2f}  sum=${ssum:+.2f}  active_days={n_days_active}  daily_mean=${daily_mean:.2f}  std=${daily_std:.2f}  sharpe={sharpe:.2f}")
        # loss streak
        ord_won = s.sort_values("fire_us")["won"].values
        cur, mx = 0, 0
        for w in ord_won:
            if not w:
                cur += 1
                mx = max(mx, cur)
            else:
                cur = 0
        print(f"           max_loss_streak={mx}")
        # max DD
        ord_pnl = s.sort_values("fire_us")["pnl_legacy_usd"].values
        if len(ord_pnl) > 0:
            cum = np.cumsum(ord_pnl)
            peak = np.maximum.accumulate(cum)
            dd = (cum - peak).min()
            print(f"           max_dd_25=${dd:.2f}")
        # bootstrap (paired daily)
        if len(by_day) >= 2:
            pnls = s["pnl_legacy_usd"].values
            day_vals = s["day"].values
            day_pnls = [s[s["day"] == d]["pnl_legacy_usd"].values for d in sorted(s["day"].unique())]
            obs_mean = pnls.mean()
            rng = np.random.default_rng(42)
            n_iter = 1000
            means = np.empty(n_iter)
            for i in range(n_iter):
                idx = rng.integers(0, len(day_pnls), size=len(day_pnls))
                flat = np.concatenate([day_pnls[j] for j in idx])
                means[i] = flat.mean()
            p = (means <= 0).mean()
            print(f"           bootstrap_p(mean<=0) = {p:.4f}  (obs_mean={obs_mean:+.3f})")
