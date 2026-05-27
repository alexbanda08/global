"""Exhaustive 3-5 gate combinations over a curated atom list.
Avoid beam search pruning issues. Brute-force over ~20 atoms × C(20,k) for k=3,4,5."""
import sys, os, json, itertools, time
import pandas as pd
import numpy as np

UNIV = "data/v4/canonical/_results/_sniper_eth5m_v3_universe.parquet"
RES = "strategy_lab/sniper_search_2026_05_27/eth_5m/_results"

# Curated atoms — high single-gate WR + complementary microstructure / regime gates
ATOMS = [
    # high single-gate WR
    "g_tr_stack_with", "g_tr_above_ema200", "g_tr_above_ema50", "g_tr_above_cloud",
    "g_tr_above_ema800", "g_ribbon_agrees", "g_bb_pos_with", "g_cci_with", "g_mfi_with",
    "g_rf_with", "g_rf_strong", "g_rf_fresh",
    # microstructure
    "g_mp_skew_with", "g_mp_skew_strong_with", "g_mp_no_extreme",
    "g_imb5_with", "g_imb5_strong_with",
    # SMS / liquidity
    "g_sms_liq_reclaim_with", "g_sms_no_liquidity_above",
    # session
    "g_tr_in_active_session", "g_tr_within_adr",
    # regime (limited)
    "g_vol_regime_normal_or_high",
    "g_hurst_trending",
]

BOOK_GATE = "g_book_depth_supports_250"
BOOK_GATE_25 = "g_book_depth_supports_25"

OFFSETS = [30, 60, 90, 120, 150, 180]

def metrics(sub, stake=25.0):
    if len(sub) == 0:
        return None
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
    day_pnl = {d: pnl[days_arr == d] for d in unique_days}
    by_day = np.array([day_pnl[d].sum() for d in unique_days])
    sharpe = (by_day.mean() / by_day.std() * np.sqrt(365)) if (by_day.std() > 0 and len(by_day) > 1) else 0.0
    return dict(
        n=len(sub), wr=float(won.mean()), sum=float(pnl.sum()),
        dpt=float(pnl.mean()), dd=dd, loss_streak=mxls,
        sharpe=sharpe, active_days=len(unique_days),
    )

def bootstrap_p(sub, stake=25.0, n_iter=1000, seed=42):
    if len(sub) < 5:
        return 1.0
    pnl = sub["pnl_legacy_usd"].values * (stake/25.0)
    days_arr = pd.to_datetime(sub["fire_us"].values, unit="us").date
    unique_days = sorted(set(days_arr))
    if len(unique_days) < 2 or pnl.mean() <= 0:
        return 1.0
    day_pnl = {d: pnl[days_arr == d] for d in unique_days}
    day_list = [day_pnl[d] for d in unique_days]
    rng = np.random.default_rng(seed)
    means = np.empty(n_iter)
    for i in range(n_iter):
        idx = rng.integers(0, len(day_list), size=len(day_list))
        means[i] = np.concatenate([day_list[j] for j in idx]).mean()
    return float((means <= 0).mean())

def main():
    print(f"Loading {UNIV}")
    df = pd.read_parquet(UNIV)
    days_sorted = sorted(df["day"].unique())
    lockbox_days = set(days_sorted[-5:])
    val_days = set(days_sorted[-11:-5])
    train_days = set(days_sorted[:-11])
    print(f"  shape={df.shape}, train={len(train_days)}d, val={len(val_days)}d, lockbox={len(lockbox_days)}d")

    # Pre-compute gate-mask matrices per pool
    rows = []
    t0 = time.time()
    total = 0

    for offset in OFFSETS:
        pool = df[df["fire_offset_s"] == offset]
        if len(pool) < 500:
            continue
        # train view
        pool_t = pool[pool["day"].isin(train_days)]
        pool_v = pool[pool["day"].isin(val_days)]
        pool_l = pool[pool["day"].isin(lockbox_days)]

        # Pre-fetch atom masks per pool
        atom_masks_t = {a: pool_t[a].astype("float").fillna(0).values >= 1 for a in ATOMS + [BOOK_GATE, BOOK_GATE_25]}
        atom_masks_v = {a: pool_v[a].astype("float").fillna(0).values >= 1 for a in ATOMS + [BOOK_GATE, BOOK_GATE_25]}
        atom_masks_l = {a: pool_l[a].astype("float").fillna(0).values >= 1 for a in ATOMS + [BOOK_GATE, BOOK_GATE_25]}

        for depth in [3, 4, 5]:
            for combo in itertools.combinations(ATOMS, depth):
                # train mask
                m_t = np.ones(len(pool_t), dtype=bool)
                for a in combo:
                    m_t &= atom_masks_t[a]
                n_t = int(m_t.sum())
                if n_t < 30 or n_t > 5000:
                    continue
                sub_t = pool_t[m_t]
                m_train = metrics(sub_t, 25.0)
                if m_train is None or m_train["wr"] < 0.65 or m_train["dpt"] < -1.5:
                    continue
                # val mask
                m_v = np.ones(len(pool_v), dtype=bool)
                for a in combo:
                    m_v &= atom_masks_v[a]
                sub_v = pool_v[m_v]
                m_val = metrics(sub_v, 25.0)
                # lockbox mask
                m_l = np.ones(len(pool_l), dtype=bool)
                for a in combo:
                    m_l &= atom_masks_l[a]
                sub_l = pool_l[m_l]
                m_lock = metrics(sub_l, 25.0)
                if m_lock is None or m_lock["n"] < 5:
                    continue
                # Filter at lockbox first to short-circuit
                if m_lock["wr"] < 0.7 or m_lock["dpt"] < 1.0:
                    continue
                # $250 variant: stack book-depth gate
                combo_250 = tuple(list(combo) + [BOOK_GATE])
                m_l_250mask = m_l & atom_masks_l[BOOK_GATE]
                sub_l_250 = pool_l[m_l_250mask]
                m_lock_250 = metrics(sub_l_250, 250.0)
                # train/val for 250 variant
                m_t_250 = m_t & atom_masks_t[BOOK_GATE]
                m_v_250 = m_v & atom_masks_v[BOOK_GATE]
                sub_t_250 = pool_t[m_t_250]; sub_v_250 = pool_v[m_v_250]
                m_train_250 = metrics(sub_t_250, 25.0)
                m_val_250 = metrics(sub_v_250, 25.0)
                # bootstrap p for both
                bp_25 = bootstrap_p(sub_l, 25.0)
                bp_250 = bootstrap_p(sub_l_250, 250.0) if (m_lock_250 and m_lock_250["n"] >= 5) else 1.0

                row_25 = dict(
                    sleeve_id=f"eth5m|off_{offset}|" + "&".join(combo),
                    offset=offset, gate_stack="&".join(combo), depth=depth, roster="$25",
                    n_train=m_train["n"], wr_train=m_train["wr"], dpt_train_25=m_train["dpt"],
                    n_val=m_val["n"] if m_val else 0,
                    wr_val=m_val["wr"] if m_val else 0,
                    dpt_val_25=m_val["dpt"] if m_val else 0,
                    n_lockbox=m_lock["n"], wr_lockbox=m_lock["wr"], dpt_lockbox_25=m_lock["dpt"],
                    sum_lockbox_25=m_lock["sum"], dd_lockbox_25=m_lock["dd"],
                    ls_lockbox=m_lock["loss_streak"], sharpe_lockbox=m_lock["sharpe"],
                    active_days_lockbox=m_lock["active_days"],
                    boot_p_lockbox=bp_25,
                )
                rows.append(row_25)
                # $250 row
                if m_lock_250 and m_lock_250["n"] >= 5:
                    row_250 = dict(
                        sleeve_id=f"eth5m|off_{offset}|" + "&".join(combo_250),
                        offset=offset, gate_stack="&".join(combo_250), depth=depth+1, roster="$250",
                        n_train=m_train_250["n"] if m_train_250 else 0,
                        wr_train=m_train_250["wr"] if m_train_250 else 0,
                        dpt_train_25=m_train_250["dpt"] if m_train_250 else 0,
                        n_val=m_val_250["n"] if m_val_250 else 0,
                        wr_val=m_val_250["wr"] if m_val_250 else 0,
                        dpt_val_25=m_val_250["dpt"] if m_val_250 else 0,
                        n_lockbox=m_lock_250["n"], wr_lockbox=m_lock_250["wr"],
                        dpt_lockbox_250=m_lock_250["dpt"],
                        sum_lockbox_250=m_lock_250["sum"], dd_lockbox_250=m_lock_250["dd"],
                        # also $25 at same lockbox set
                        dpt_lockbox_25=m_lock_250["dpt"]/10.0,
                        sum_lockbox_25=m_lock_250["sum"]/10.0,
                        dd_lockbox_25=m_lock_250["dd"]/10.0,
                        ls_lockbox=m_lock_250["loss_streak"],
                        sharpe_lockbox=m_lock_250["sharpe"],
                        active_days_lockbox=m_lock_250["active_days"],
                        boot_p_lockbox=bp_250,
                    )
                    rows.append(row_250)
                total += 1
                if total % 5000 == 0:
                    el = time.time() - t0
                    print(f"  ...processed {total} combos so far, {el:.1f}s, {len(rows)} survivors so far")

    print(f"\nTotal combos: {total}, time: {time.time()-t0:.1f}s")
    print(f"Surviving rows (lockbox WR>=0.7 + dpt>=1): {len(rows)}")
    res = pd.DataFrame(rows)
    res.to_csv(f"{RES}/exhaustive_validated.csv", index=False)
    print(f"saved -> {RES}/exhaustive_validated.csv")

    # Apply strict filter
    def pass_25(r):
        return (r["n_lockbox"] >= 5 and r["n_lockbox"] <= 500 and
                r["wr_lockbox"] >= 0.75 and r["dpt_lockbox_25"] >= 3.0 and
                r["dd_lockbox_25"] >= -300.0 and r["ls_lockbox"] <= 6 and
                r["sharpe_lockbox"] >= 2.0 and r["boot_p_lockbox"] <= 0.05 and
                r["active_days_lockbox"] >= 2 and r["roster"] == "$25")
    def pass_250(r):
        return (r["n_lockbox"] >= 5 and r["n_lockbox"] <= 500 and
                r["wr_lockbox"] >= 0.75 and r.get("dpt_lockbox_250", 0) >= 30.0 and
                r.get("dd_lockbox_250", 0) >= -3000.0 and r["ls_lockbox"] <= 6 and
                r["sharpe_lockbox"] >= 2.0 and r["boot_p_lockbox"] <= 0.05 and
                r["active_days_lockbox"] >= 2 and r["roster"] == "$250")
    res["pass_25"] = res.apply(pass_25, axis=1)
    res["pass_250"] = res.apply(pass_250, axis=1)
    print(f"\n== Strict pass at $25 (active>=2): {res['pass_25'].sum()} ==")
    pp25 = res[res["pass_25"]].sort_values("dpt_lockbox_25", ascending=False)
    for _, r in pp25.head(20).iterrows():
        print(f"  WR={r['wr_lockbox']:.3f} $/tr={r['dpt_lockbox_25']:+.2f} n={r['n_lockbox']} ad={int(r['active_days_lockbox'])} dd=${r['dd_lockbox_25']:.0f} ls={int(r['ls_lockbox'])} sh={r['sharpe_lockbox']:.1f} p={r['boot_p_lockbox']:.3f} | tr WR={r['wr_train']:.3f}/n={r['n_train']} val WR={r['wr_val']:.3f}/n={r['n_val']} $/tr_v={r['dpt_val_25']:+.2f}")
        print(f"    {r['sleeve_id']}")
    print(f"\n== Strict pass at $250 (active>=2): {res['pass_250'].sum()} ==")
    pp250 = res[res["pass_250"]].sort_values("dpt_lockbox_250", ascending=False)
    for _, r in pp250.head(20).iterrows():
        print(f"  WR={r['wr_lockbox']:.3f} $/tr_250={r['dpt_lockbox_250']:+.0f} n={r['n_lockbox']} ad={int(r['active_days_lockbox'])} dd_250=${r['dd_lockbox_250']:.0f} ls={int(r['ls_lockbox'])} sh={r['sharpe_lockbox']:.1f} p={r['boot_p_lockbox']:.3f}")
        print(f"    {r['sleeve_id']}")

if __name__ == "__main__":
    main()
