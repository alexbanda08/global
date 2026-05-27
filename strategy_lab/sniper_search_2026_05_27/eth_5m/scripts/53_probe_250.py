"""Probe — for top $25 sleeves, what does adding g_book_depth_supports_250 do?
Also try g_book_depth_supports_25 (lighter threshold)."""
import pandas as pd
import numpy as np

UNIV = "data/v4/canonical/_results/_sniper_eth5m_v3_universe.parquet"
RES = "strategy_lab/sniper_search_2026_05_27/eth_5m/_results"

df = pd.read_parquet(UNIV)
days_sorted = sorted(df["day"].unique())
lockbox_days = set(days_sorted[-5:])
val_days = set(days_sorted[-11:-5])
train_days = set(days_sorted[:-11])

# Top $25 sleeve gates
top25_sleeves = [
    ["g_tr_above_ema200","g_mp_skew_with","g_mp_no_extreme","g_sms_liq_reclaim_with"],
    ["g_tr_above_cloud","g_mp_skew_with","g_mp_no_extreme","g_sms_liq_reclaim_with"],
    ["g_tr_above_ema200","g_rf_with","g_mp_skew_with","g_sms_liq_reclaim_with"],
    ["g_tr_above_ema200","g_mp_skew_with","g_sms_liq_reclaim_with","g_tr_in_active_session"],
    ["g_tr_above_ema200","g_bb_pos_with","g_mp_skew_with","g_sms_liq_reclaim_with"],
]

OFFSET = 120
pool = df[df["fire_offset_s"] == OFFSET]

def metrics(sub, stake=25.0):
    if len(sub) == 0:
        return None
    pnl = sub["pnl_legacy_usd"].values * (stake/25.0)
    won = sub["won"].values.astype(bool)
    fus = sub["fire_us"].values
    ord_idx = np.argsort(fus)
    pnl_o = pnl[ord_idx]; won_o = won[ord_idx]
    cum = np.cumsum(pnl_o); peak = np.maximum.accumulate(cum)
    dd = float((cum - peak).min())
    cur, mxls = 0, 0
    for w in won_o:
        if not w:
            cur += 1
            mxls = max(mxls, cur)
        else: cur = 0
    days_arr = (fus // 86_400_000_000).astype(np.int64)
    ud = np.unique(days_arr)
    by_day = pd.Series(pnl).groupby(pd.Series(days_arr)).sum()
    sharpe = (by_day.mean() / by_day.std() * np.sqrt(365)) if (by_day.std() > 0 and len(by_day) > 1) else 0.0
    return dict(n=len(sub), wr=float(won.mean()), sum=float(pnl.sum()),
                dpt=float(pnl.mean()), dd=dd, loss_streak=mxls,
                sharpe=float(sharpe), active_days=len(ud))

def gate_mask(d, gates):
    m = np.ones(len(d), dtype=bool)
    for g in gates:
        m &= (d[g].astype("float").fillna(0).values >= 1)
    return m

for gates in top25_sleeves:
    print()
    print("=" * 80)
    print(f"Base: {gates}")
    for variant_label, extra in [("base $25", []),
                                  ("+g_book_depth_supports_25", ["g_book_depth_supports_25"]),
                                  ("+g_book_depth_supports_250", ["g_book_depth_supports_250"]),
                                  ("+g_book_depth_supports_250_tight", ["g_book_depth_supports_250_tight"])]:
        full = gates + extra
        for split_label, days in [("train", train_days), ("val", val_days), ("lockbox", lockbox_days)]:
            d = pool[pool["day"].isin(days)]
            m = gate_mask(d, full)
            sub = d[m]
            stake = 250.0 if "250" in variant_label else 25.0
            mm = metrics(sub, stake=stake)
            if mm and mm["n"] >= 1:
                print(f"  {variant_label:42s} {split_label:8s} n={mm['n']:4d} WR={mm['wr']:.3f} $/tr=${mm['dpt']:+.2f} sum=${mm['sum']:+.2f} dd=${mm['dd']:.0f} ls={mm['loss_streak']} ad={mm['active_days']} sh={mm['sharpe']:.1f}")
            elif mm:
                print(f"  {variant_label:42s} {split_label:8s} n=0")
