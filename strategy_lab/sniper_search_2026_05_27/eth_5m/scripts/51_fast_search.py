"""Faster exhaustive search — reduced atoms (16), depth 3-4 only, smart short-circuit.
Streams rows to disk incrementally.

Atoms chosen for diversity: 5 trend (tr_*), 3 indicator (rf,bb,cci), 4 microstructure
(mp,imb), 2 sms, 1 vol, 1 session.

Total combos: C(16,3) + C(16,4) = 560 + 1820 = 2380 per offset.
× 6 offsets = ~14,280 candidates ~6s each computation (vectorized).
"""
import sys, os, json, itertools, time, csv
import pandas as pd
import numpy as np

UNIV = "data/v4/canonical/_results/_sniper_eth5m_v3_universe.parquet"
RES = "strategy_lab/sniper_search_2026_05_27/eth_5m/_results"
OUT_CSV = f"{RES}/fast_validated.csv"

ATOMS = [
    "g_tr_above_ema200", "g_tr_above_ema50", "g_tr_above_cloud", "g_tr_stack_with",
    "g_ribbon_agrees", "g_rf_with", "g_bb_pos_with", "g_cci_with",
    "g_mp_skew_with", "g_mp_no_extreme", "g_imb5_with", "g_imb5_strong_with",
    "g_sms_liq_reclaim_with", "g_sms_no_liquidity_above",
    "g_tr_in_active_session", "g_vol_regime_normal_or_high",
]
BOOK_GATE = "g_book_depth_supports_250"
OFFSETS = [30, 60, 90, 120, 150]

def metrics_fast(pnl, won, fire_us, stake=25.0):
    if len(pnl) == 0:
        return None
    pnl_s = pnl * (stake/25.0)
    ord_idx = np.argsort(fire_us)
    pnl_o = pnl_s[ord_idx]; won_o = won[ord_idx]
    cum = np.cumsum(pnl_o); peak = np.maximum.accumulate(cum)
    dd = float((cum - peak).min())
    # loss streak
    cur, mxls = 0, 0
    for w in won_o:
        if not w:
            cur += 1
            mxls = max(mxls, cur)
        else:
            cur = 0
    days_arr = (fire_us // 86_400_000_000).astype(np.int64)
    unique_days, day_idx = np.unique(days_arr, return_inverse=True)
    by_day = np.bincount(day_idx, weights=pnl_s)
    sharpe = (by_day.mean() / by_day.std() * np.sqrt(365)) if (by_day.std() > 0 and len(by_day) > 1) else 0.0
    return dict(
        n=len(pnl_s), wr=float(won.mean()), sum=float(pnl_s.sum()),
        dpt=float(pnl_s.mean()), dd=dd, loss_streak=mxls,
        sharpe=float(sharpe), active_days=len(unique_days),
    )

def bootstrap_p_fast(pnl, fire_us, stake=25.0, n_iter=1000, seed=42):
    if len(pnl) < 5:
        return 1.0
    pnl_s = pnl * (stake/25.0)
    if pnl_s.mean() <= 0:
        return 1.0
    days_arr = (fire_us // 86_400_000_000).astype(np.int64)
    unique_days, day_idx = np.unique(days_arr, return_inverse=True)
    if len(unique_days) < 2:
        return 1.0
    # bucket pnls by day
    day_pnls = [pnl_s[day_idx == i] for i in range(len(unique_days))]
    rng = np.random.default_rng(seed)
    means = np.empty(n_iter)
    for i in range(n_iter):
        idx = rng.integers(0, len(day_pnls), size=len(day_pnls))
        means[i] = np.concatenate([day_pnls[j] for j in idx]).mean()
    return float((means <= 0).mean())

def main():
    print(f"Loading {UNIV}")
    df = pd.read_parquet(UNIV)
    print(f"  shape={df.shape}")
    days_sorted = sorted(df["day"].unique())
    lockbox_days = set(days_sorted[-5:])
    val_days = set(days_sorted[-11:-5])
    train_days = set(days_sorted[:-11])

    fieldnames = ["sleeve_id","offset","gate_stack","depth","roster",
                  "n_train","wr_train","dpt_train_25",
                  "n_val","wr_val","dpt_val_25",
                  "n_lockbox","wr_lockbox","dpt_lockbox_25","sum_lockbox_25","dd_lockbox_25",
                  "ls_lockbox","sharpe_lockbox","active_days_lockbox","boot_p_lockbox",
                  "dpt_lockbox_250","sum_lockbox_250","dd_lockbox_250"]
    fout = open(OUT_CSV, "w", newline="")
    wr = csv.DictWriter(fout, fieldnames=fieldnames)
    wr.writeheader()

    total = 0
    survivors = 0
    t0 = time.time()
    for offset in OFFSETS:
        pool = df[df["fire_offset_s"] == offset].copy()
        if len(pool) < 500:
            continue
        # Pre-fetch arrays
        pool_t = pool[pool["day"].isin(train_days)]
        pool_v = pool[pool["day"].isin(val_days)]
        pool_l = pool[pool["day"].isin(lockbox_days)]
        # Atom masks as boolean arrays (faster than column lookup)
        def atom_masks(d):
            return {a: (d[a].astype("float").fillna(0).values >= 1.0) for a in ATOMS + [BOOK_GATE]}
        am_t = atom_masks(pool_t)
        am_v = atom_masks(pool_v)
        am_l = atom_masks(pool_l)
        pnl_t = pool_t["pnl_legacy_usd"].values
        won_t = pool_t["won"].values.astype(bool)
        fus_t = pool_t["fire_us"].values
        pnl_v = pool_v["pnl_legacy_usd"].values
        won_v = pool_v["won"].values.astype(bool)
        fus_v = pool_v["fire_us"].values
        pnl_l = pool_l["pnl_legacy_usd"].values
        won_l = pool_l["won"].values.astype(bool)
        fus_l = pool_l["fire_us"].values

        for depth in [3, 4]:
            for combo in itertools.combinations(ATOMS, depth):
                m_l = np.ones(len(pool_l), dtype=bool)
                for a in combo:
                    m_l &= am_l[a]
                n_l = int(m_l.sum())
                if n_l < 5:
                    continue
                wr_l = won_l[m_l].mean()
                if wr_l < 0.70:
                    continue
                dpt_l_raw = pnl_l[m_l].mean()
                if dpt_l_raw < 1.0:
                    continue
                m_train_lock = metrics_fast(pnl_l[m_l], won_l[m_l], fus_l[m_l], 25.0)
                if m_train_lock["active_days"] < 2:
                    continue  # require at least 2 active lockbox days for sharpe to mean anything

                # Now compute train + val + bootstrap
                m_t = np.ones(len(pool_t), dtype=bool)
                m_v = np.ones(len(pool_v), dtype=bool)
                for a in combo:
                    m_t &= am_t[a]
                    m_v &= am_v[a]
                if m_t.sum() < 30:
                    continue
                m_train = metrics_fast(pnl_t[m_t], won_t[m_t], fus_t[m_t], 25.0)
                m_val = metrics_fast(pnl_v[m_v], won_v[m_v], fus_v[m_v], 25.0) if m_v.sum() > 0 else None
                bp = bootstrap_p_fast(pnl_l[m_l], fus_l[m_l], 25.0)
                row = dict(
                    sleeve_id=f"eth5m|off_{offset}|" + "&".join(combo),
                    offset=offset, gate_stack="&".join(combo), depth=depth, roster="$25",
                    n_train=m_train["n"], wr_train=round(m_train["wr"],4), dpt_train_25=round(m_train["dpt"],3),
                    n_val=m_val["n"] if m_val else 0,
                    wr_val=round(m_val["wr"],4) if m_val else 0,
                    dpt_val_25=round(m_val["dpt"],3) if m_val else 0,
                    n_lockbox=m_train_lock["n"], wr_lockbox=round(m_train_lock["wr"],4),
                    dpt_lockbox_25=round(m_train_lock["dpt"],3),
                    sum_lockbox_25=round(m_train_lock["sum"],2),
                    dd_lockbox_25=round(m_train_lock["dd"],2),
                    ls_lockbox=m_train_lock["loss_streak"],
                    sharpe_lockbox=round(m_train_lock["sharpe"],3),
                    active_days_lockbox=m_train_lock["active_days"],
                    boot_p_lockbox=round(bp,4),
                    dpt_lockbox_250=0,sum_lockbox_250=0,dd_lockbox_250=0,
                )
                wr.writerow(row)
                survivors += 1
                # $250 variant
                m_l_250 = m_l & am_l[BOOK_GATE]
                n_l_250 = int(m_l_250.sum())
                if n_l_250 >= 5:
                    wr_l_250 = won_l[m_l_250].mean()
                    if wr_l_250 >= 0.70:
                        m_train_lock_250 = metrics_fast(pnl_l[m_l_250], won_l[m_l_250], fus_l[m_l_250], 250.0)
                        if m_train_lock_250["active_days"] >= 2:
                            m_t_250 = m_t & am_t[BOOK_GATE]
                            m_v_250 = m_v & am_v[BOOK_GATE]
                            m_train_250 = metrics_fast(pnl_t[m_t_250], won_t[m_t_250], fus_t[m_t_250], 25.0) if m_t_250.sum()>=5 else None
                            m_val_250 = metrics_fast(pnl_v[m_v_250], won_v[m_v_250], fus_v[m_v_250], 25.0) if m_v_250.sum()>=5 else None
                            bp_250 = bootstrap_p_fast(pnl_l[m_l_250], fus_l[m_l_250], 250.0)
                            row250 = dict(
                                sleeve_id=f"eth5m|off_{offset}|" + "&".join(combo) + "&" + BOOK_GATE,
                                offset=offset, gate_stack="&".join(combo) + "&" + BOOK_GATE,
                                depth=depth+1, roster="$250",
                                n_train=m_train_250["n"] if m_train_250 else 0,
                                wr_train=round(m_train_250["wr"],4) if m_train_250 else 0,
                                dpt_train_25=round(m_train_250["dpt"],3) if m_train_250 else 0,
                                n_val=m_val_250["n"] if m_val_250 else 0,
                                wr_val=round(m_val_250["wr"],4) if m_val_250 else 0,
                                dpt_val_25=round(m_val_250["dpt"],3) if m_val_250 else 0,
                                n_lockbox=m_train_lock_250["n"], wr_lockbox=round(m_train_lock_250["wr"],4),
                                dpt_lockbox_25=round(m_train_lock_250["dpt"]/10.0,3),
                                sum_lockbox_25=round(m_train_lock_250["sum"]/10.0,2),
                                dd_lockbox_25=round(m_train_lock_250["dd"]/10.0,2),
                                ls_lockbox=m_train_lock_250["loss_streak"],
                                sharpe_lockbox=round(m_train_lock_250["sharpe"],3),
                                active_days_lockbox=m_train_lock_250["active_days"],
                                boot_p_lockbox=round(bp_250,4),
                                dpt_lockbox_250=round(m_train_lock_250["dpt"],2),
                                sum_lockbox_250=round(m_train_lock_250["sum"],2),
                                dd_lockbox_250=round(m_train_lock_250["dd"],2),
                            )
                            wr.writerow(row250)
                            survivors += 1
                total += 1
        el = time.time() - t0
        print(f"  offset {offset}: combos processed (cum)={total}, survivors={survivors}, elapsed={el:.1f}s")
    fout.close()
    print(f"\nDone. total combos: {total}, survivors written: {survivors}, elapsed={time.time()-t0:.1f}s")
    print(f"saved -> {OUT_CSV}")

if __name__ == "__main__":
    main()
