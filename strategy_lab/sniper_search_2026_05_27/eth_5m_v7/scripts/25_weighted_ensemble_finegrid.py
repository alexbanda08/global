"""Weighted ensemble (Path A) with finer threshold + per-atom weight using TRAIN dpt-lift."""
import os
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
UNIV = os.path.join(ROOT, "data/v4/canonical/_results/_sniper_eth5m_v7_universe.parquet")
RES = os.path.join(ROOT, "strategy_lab/sniper_search_2026_05_27/eth_5m_v7/_results")
PLOT_DIR = os.path.join(ROOT, "strategy_lab/sniper_search_2026_05_27/eth_5m_v7")

# Same atom pool as 10_sniper_search_v7
ATOMS_ALL = [
    "g_tr_above_ema200", "g_tr_above_ema50", "g_tr_above_cloud", "g_tr_stack_with",
    "g_ribbon_agrees", "g_rf_with",
    "g_bb_pos_with", "g_cci_with", "g_mfi_with", "g_stoch_with",
    "g_mp_skew_with", "g_mp_no_extreme",
    "g_sms_liq_reclaim_with", "g_sms_no_liquidity_above",
    "g_tr_in_active_session", "g_tr_above_pp", "g_tr_within_adr",
    "g_imb5_strong_with", "g_imb_change_with",
    "g_hurst_trending", "g_vol_high", "g_vol_med",
    "g_hawkes_imbalance_with",
    "g_entry_vwap_in_band", "g_entry_vwap_in_band_narrow", "g_entry_vwap_in_band_wide",
    "g_trend_slope_with",
    "g_vwap_ge_50_le_85",
    "g_f7_with", "g_f7_strong_with", "g_f7_trend_with",
    "g_mp_skew_at_ws_with", "g_mp_skew_at_ws_strong",
    "g_choch_with", "g_bos_with", "g_cvd_with", "g_markov_with",
    "g_regime_ranging_at_ws",
    "g_sms_liq_reclaim_with_at_ws",
    "g_hod_european", "g_hod_us_morning", "g_hod_overnight",
    "g_btc_mp_skew_with", "g_btc_trend_slope_with", "g_btc_hurst_trending",
    "g_btc_eth_trend_agree",
    "g_parent15m_trending", "g_parent15m_label_with", "g_parent15m_trend_with",
    "g_parent15m_trend_strong_with", "g_parent15m_ranging",
    "g_hurst_strong_trending_v7", "g_hurst_reverting_v7",
    "g_hurst_trend_with", "g_hurst_mp_trend_with",
    "g_pw_f7_cvd_unanimity", "g_pw_break_with",
    "g_xa_3source_trend_with",
]


def metrics(pnl, won, fire_us):
    if len(pnl) == 0:
        return dict(n=0, wr=0, sum=0, dpt=0, dd=0, loss_streak=0, sharpe=0, active_days=0)
    ord_idx = np.argsort(fire_us)
    pnl_o = pnl[ord_idx]
    won_o = won[ord_idx]
    cum = np.cumsum(pnl_o)
    peak = np.maximum.accumulate(cum)
    dd = float((cum - peak).min())
    cur, mxls = 0, 0
    for w in won_o:
        if not w:
            cur += 1
            mxls = max(mxls, cur)
        else:
            cur = 0
    days_arr = (fire_us // 86_400_000_000).astype(np.int64)
    uniq, idx = np.unique(days_arr, return_inverse=True)
    by_day = np.bincount(idx, weights=pnl)
    sharpe = (by_day.mean() / by_day.std() * np.sqrt(365)) if (by_day.std() > 0 and len(by_day) > 1) else 0.0
    return dict(n=int(len(pnl)), wr=float(won.mean()), sum=float(pnl.sum()),
                dpt=float(pnl.mean()), dd=dd, loss_streak=mxls,
                sharpe=float(sharpe), active_days=int(len(uniq)))


def bootstrap_p(pnl, fire_us, n_iter=500, seed=42):
    if len(pnl) < 5 or pnl.mean() <= 0:
        return 1.0
    days_arr = (fire_us // 86_400_000_000).astype(np.int64)
    uniq, idx = np.unique(days_arr, return_inverse=True)
    if len(uniq) < 2:
        return 1.0
    by_day = [pnl[idx == i] for i in range(len(uniq))]
    rng = np.random.default_rng(seed)
    means = np.empty(n_iter)
    for i in range(n_iter):
        sel = rng.integers(0, len(by_day), size=len(by_day))
        means[i] = np.concatenate([by_day[j] for j in sel]).mean()
    return float((means <= 0).mean())


def main():
    df = pd.read_parquet(UNIV)
    df["day"] = pd.to_datetime(df["fire_us"], unit="us").dt.date
    days_sorted = sorted(df["day"].unique())
    n_lockbox = max(4, int(len(days_sorted) * 0.15))
    n_val = max(4, int(len(days_sorted) * 0.18))
    lockbox = set(days_sorted[-n_lockbox:])
    val = set(days_sorted[-(n_lockbox + n_val):-n_lockbox])
    train = set(days_sorted[:-(n_lockbox + n_val)])

    rows = []
    for offset in [30, 60, 90, 120]:
        pool = df[df["fire_offset_s"] == offset].copy()
        pool_t = pool[pool["day"].isin(train)]
        pool_v = pool[pool["day"].isin(val)]
        pool_l = pool[pool["day"].isin(lockbox)]
        if len(pool_l) < 100:
            continue

        # Per-atom TRAIN dpt-lift (use $25 PnL directly)
        base_dpt = pool_t["pnl_legacy_usd"].mean()
        weights = {}
        for a in ATOMS_ALL:
            if a not in pool_t.columns:
                weights[a] = 0.0
                continue
            mt = (pool_t[a].fillna(0).astype(float).values >= 1.0)
            if mt.sum() < 100:
                weights[a] = 0.0
                continue
            dpt_a = pool_t["pnl_legacy_usd"].values[mt].mean()
            lift = dpt_a - base_dpt
            weights[a] = max(0.0, lift)

        used = [a for a, w in weights.items() if w > 0.5]  # min lift $0.50 per trade
        if not used:
            continue
        w_arr = np.array([weights[a] for a in used])

        score_t = np.zeros(len(pool_t))
        score_v = np.zeros(len(pool_v))
        score_l = np.zeros(len(pool_l))
        for a, w in zip(used, w_arr):
            score_t += (pool_t[a].fillna(0).astype(float).values >= 1.0).astype(float) * w
            score_v += (pool_v[a].fillna(0).astype(float).values >= 1.0).astype(float) * w
            score_l += (pool_l[a].fillna(0).astype(float).values >= 1.0).astype(float) * w

        # Finer threshold sweep (absolute, in dollars of weighted-lift)
        max_score = w_arr.sum()
        print(f"\n=== off={offset} | atoms used={len(used)} | max_score=${max_score:.2f} ===")
        # Print top 10 weights
        sorted_w = sorted(zip(used, w_arr), key=lambda kv: -kv[1])[:10]
        for a, w in sorted_w:
            print(f"  {a}: ${w:.2f}")

        for thr_frac in np.arange(0.15, 0.91, 0.025):
            thr = thr_frac * max_score
            m_l = score_l >= thr
            n_l = int(m_l.sum())
            if n_l < 25:
                continue
            won_l = pool_l["won"].values.astype(bool)[m_l]
            pnl_l = pool_l["pnl_legacy_usd"].values[m_l]
            fus_l = pool_l["fire_us"].values[m_l]
            ml = metrics(pnl_l, won_l, fus_l)
            if ml["wr"] < 0.65 or ml["dpt"] < 4.0 or ml["dd"] < -500 or ml["loss_streak"] > 14:
                continue

            m_t = score_t >= thr
            m_v = score_v >= thr
            if m_t.sum() < 20:
                continue
            mt = metrics(pool_t["pnl_legacy_usd"].values[m_t], pool_t["won"].values.astype(bool)[m_t], pool_t["fire_us"].values[m_t])
            mv = metrics(pool_v["pnl_legacy_usd"].values[m_v], pool_v["won"].values.astype(bool)[m_v], pool_v["fire_us"].values[m_v])
            if mt["dpt"] <= 0 or mv["dpt"] <= 0:
                continue
            bp = bootstrap_p(pnl_l, fus_l)
            if bp > 0.05:
                continue

            rows.append(dict(
                offset=offset, thr_frac=round(thr_frac, 3), thr_abs=round(thr, 2), n_atoms=len(used),
                n_train=mt["n"], wr_train=round(mt["wr"], 4), dpt_train=round(mt["dpt"], 3), sum_train=round(mt["sum"], 2),
                n_val=mv["n"], wr_val=round(mv["wr"], 4), dpt_val=round(mv["dpt"], 3), sum_val=round(mv["sum"], 2),
                n_lockbox=ml["n"], wr_lockbox=round(ml["wr"], 4), dpt_lockbox=round(ml["dpt"], 3),
                sum_lockbox=round(ml["sum"], 2), dd_lockbox=round(ml["dd"], 2),
                ls_lockbox=ml["loss_streak"], sharpe_lockbox=round(ml["sharpe"], 2), boot_p=round(bp, 4),
                objective=round(ml["dpt"] * np.sqrt(ml["n"]), 3),
                sum_28d=round(mt["sum"] + mv["sum"] + ml["sum"], 2),
            ))

    rows_df = pd.DataFrame(rows)
    if rows_df.empty:
        print("\nNo weighted ensemble survived")
        return
    print(f"\nWeighted ensemble survivors: {len(rows_df)}")
    print("\nTOP 10 by sum_28d:")
    print(rows_df.sort_values("sum_28d", ascending=False).head(10).to_string())
    print("\nTOP 10 by objective:")
    print(rows_df.sort_values("objective", ascending=False).head(10).to_string())
    rows_df.to_csv(os.path.join(RES, "weighted_ensembles_finegrid.csv"), index=False)
    print(f"\nSaved -> weighted_ensembles_finegrid.csv")


if __name__ == "__main__":
    main()
