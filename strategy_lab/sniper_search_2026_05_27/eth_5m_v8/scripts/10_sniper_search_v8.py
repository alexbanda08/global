"""V8 sniper search for ETH 5m.

V8 brief: full 32.7d window with 60/20/20 splits, atom pool extends V7 with:
- Path J: SOL trend, 2-asset BTC+SOL, 3-asset confluence
- Path K: TOD buckets
- Path Q: ETH 15m PREVIOUS slot winner / 2-bar streak
- Path L: 1h grandparent proxy + MTF unanimity

Strategy:
  Phase 1 — Strict combinatorial search at depths {3,4,5} with V7 winners + V8 new atoms
  Phase 2 — TOD-conditioning: pick V7 winners and partition by each TOD bucket → report per-bucket metrics
  Phase 3 — V7 winner refinement: take V7 c1, c2, c5 and try adding ONE V8 gate at a time

Bar: WR_lockbox >= 0.65 (or 55% if dpt>=10), dpt_lockbox >= $4, dd_lockbox >= -$500,
     loss_streak <= 14, active_days_lockbox >= 2, n_lockbox >= 25, bootstrap_p_lockbox <= 0.05
"""
import os
import sys
import itertools
import time
import csv
import pandas as pd
import numpy as np

ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
UNIV = os.path.join(ROOT, r"data\v4\canonical\_results\_sniper_eth5m_v8_universe.parquet")
RES = os.path.join(ROOT, r"strategy_lab\sniper_search_2026_05_27\eth_5m_v8\_results")
os.makedirs(RES, exist_ok=True)

OUT_CSV = os.path.join(RES, "v8_validated.csv")
OUT_TOD = os.path.join(RES, "v8_tod_partitioned.csv")
OUT_REFINE = os.path.join(RES, "v8_v7_refinement.csv")

# ---- V8 ATOM POOL ----
# V7 winners + V7 best atoms + V8 new
ATOMS_V7_WINNERS = [
    "g_tr_above_cloud", "g_tr_above_ema50", "g_tr_above_ema200",
    "g_entry_vwap_in_band", "g_entry_vwap_in_band_narrow", "g_entry_vwap_in_band_wide",
    "g_ribbon_agrees",
    "g_mp_skew_with", "g_mp_no_extreme",
    "g_hurst_trending", "g_hurst_mp_trend_with", "g_hurst_trend_with",
    "g_hurst_strong_trending_v7",
    "g_parent15m_ranging", "g_parent15m_trend_with", "g_parent15m_trending",
    "g_parent15m_label_with",
    "g_regime_ranging_at_ws",
    "g_xa_3source_trend_with",
    "g_btc_trend_slope_with", "g_btc_eth_trend_agree", "g_btc_mp_skew_with",
    "g_trend_slope_with",
    "g_tr_in_active_session", "g_tr_within_adr",
    "g_imb5_strong_with",
    "g_sms_no_liquidity_above",
    "g_rf_with", "g_rf_in_band",
    "g_vol_high", "g_vol_med",
    "g_hawkes_imbalance_with",
    "g_f7_with",
    "g_cci_with",
]

# V8 new atoms — Path J/K/Q/L
ATOMS_V8_NEW = [
    # Path J — 2-asset confluence
    "g_sol_trend_slope_with", "g_sol_mp_skew_with",
    "g_2a_btc_sol_trend_with", "g_2a_btc_sol_mp_with",
    "g_3a_unanimity_trend", "g_3a_unanimity_full",
    # Path K — TOD
    "g_tod_asia_morning", "g_tod_european_morning",
    "g_tod_us_afternoon", "g_tod_us_evening",
    "g_tod_europe_us_window",
    # Path Q
    "g_q_prev15m_agrees", "g_q_15m_streak_agrees",
    # Path L
    "g_grandparent_trend_with", "g_grandparent_strong_trend_with", "g_l_mtf_unanimity",
]

ATOMS_ALL = list(dict.fromkeys(ATOMS_V7_WINNERS + ATOMS_V8_NEW))


def metrics_fast(pnl, won, fire_us, stake=25.0):
    if len(pnl) == 0:
        return None
    pnl_s = pnl * (stake / 25.0)
    ord_idx = np.argsort(fire_us)
    pnl_o = pnl_s[ord_idx]
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
    unique_days, day_idx = np.unique(days_arr, return_inverse=True)
    by_day = np.bincount(day_idx, weights=pnl_s)
    sharpe = (by_day.mean() / by_day.std() * np.sqrt(365)) if (by_day.std() > 0 and len(by_day) > 1) else 0.0
    return dict(
        n=len(pnl_s), wr=float(won.mean()), sum=float(pnl_s.sum()),
        dpt=float(pnl_s.mean()), dd=dd, loss_streak=mxls,
        sharpe=float(sharpe), active_days=len(unique_days),
    )


def bootstrap_p_fast(pnl, fire_us, stake=25.0, n_iter=500, seed=42):
    if len(pnl) < 5:
        return 1.0
    pnl_s = pnl * (stake / 25.0)
    if pnl_s.mean() <= 0:
        return 1.0
    days_arr = (fire_us // 86_400_000_000).astype(np.int64)
    unique_days, day_idx = np.unique(days_arr, return_inverse=True)
    if len(unique_days) < 2:
        return 1.0
    day_pnls = [pnl_s[day_idx == i] for i in range(len(unique_days))]
    rng = np.random.default_rng(seed)
    means = np.empty(n_iter)
    for i in range(n_iter):
        idx = rng.integers(0, len(day_pnls), size=len(day_pnls))
        means[i] = np.concatenate([day_pnls[j] for j in idx]).mean()
    return float((means <= 0).mean())


def atom_masks_for(df, atoms):
    out = {}
    for a in atoms:
        if a in df.columns:
            out[a] = (df[a].astype("float").fillna(0).values >= 1.0)
        else:
            out[a] = np.zeros(len(df), dtype=bool)
    return out


def passes_bar(ml, m_train, m_val, bp, min_n=25):
    """V8 survivor bar: tiered WR/dpt + DD/ls + stability."""
    if ml is None or ml["n"] < min_n:
        return False
    if ml["dpt"] < 4.0:
        return False
    if ml["wr"] < 0.55 and ml["dpt"] < 10.0:
        return False
    if ml["wr"] < 0.65 and ml["dpt"] < 4.0:
        return False
    if ml["dd"] < -500 or ml["loss_streak"] > 14 or ml["active_days"] < 2:
        return False
    if m_train is None or m_train["dpt"] <= 0:
        return False
    if m_val is None or m_val["dpt"] <= 0:
        return False
    if bp > 0.05:
        return False
    return True


def search_strict_combos(pool_t, pool_v, pool_l, pool_full, atom_pool, offset, depths, writer, phase_tag,
                          days_lockbox, days_full,
                          min_n=25):
    am_t = atom_masks_for(pool_t, atom_pool)
    am_v = atom_masks_for(pool_v, atom_pool)
    am_l = atom_masks_for(pool_l, atom_pool)
    am_f = atom_masks_for(pool_full, atom_pool)
    pnl_t = pool_t["pnl_legacy_usd"].values
    won_t = pool_t["won"].values.astype(bool)
    fus_t = pool_t["fire_us"].values
    pnl_v = pool_v["pnl_legacy_usd"].values
    won_v = pool_v["won"].values.astype(bool)
    fus_v = pool_v["fire_us"].values
    pnl_l = pool_l["pnl_legacy_usd"].values
    won_l = pool_l["won"].values.astype(bool)
    fus_l = pool_l["fire_us"].values
    pnl_f = pool_full["pnl_legacy_usd"].values
    won_f = pool_full["won"].values.astype(bool)
    fus_f = pool_full["fire_us"].values

    survivors = 0
    for depth in depths:
        for combo in itertools.combinations(atom_pool, depth):
            m_l = np.ones(len(pool_l), dtype=bool)
            for a in combo:
                m_l &= am_l[a]
            n_l = int(m_l.sum())
            if n_l < min_n:
                continue
            wr_l = won_l[m_l].mean()
            # quick reject before metrics
            if wr_l < 0.55:
                continue
            ml = metrics_fast(pnl_l[m_l], won_l[m_l], fus_l[m_l], 25.0)
            if ml["dpt"] < 4.0:
                continue
            if ml["dd"] < -500 or ml["loss_streak"] > 14 or ml["active_days"] < 2:
                continue
            m_t = np.ones(len(pool_t), dtype=bool)
            m_v = np.ones(len(pool_v), dtype=bool)
            for a in combo:
                m_t &= am_t[a]
                m_v &= am_v[a]
            if m_t.sum() < 15 or m_v.sum() < 5:
                continue
            m_train = metrics_fast(pnl_t[m_t], won_t[m_t], fus_t[m_t], 25.0)
            m_val = metrics_fast(pnl_v[m_v], won_v[m_v], fus_v[m_v], 25.0)
            bp = bootstrap_p_fast(pnl_l[m_l], fus_l[m_l], 25.0)
            if not passes_bar(ml, m_train, m_val, bp, min_n):
                continue

            # full-window metric (apples-to-apples projection)
            m_f = np.ones(len(pool_full), dtype=bool)
            for a in combo:
                m_f &= am_f[a]
            m_full = metrics_fast(pnl_f[m_f], won_f[m_f], fus_f[m_f], 25.0)

            # projections
            proj_32d_lock = (ml["dpt"] * ml["n"] / max(days_lockbox, 1e-9)) * 32.66
            proj_full = (m_full["dpt"] * m_full["n"] / max(days_full, 1e-9)) * 32.66 if m_full else 0.0
            proj_honest = min(proj_32d_lock, proj_full)

            row = dict(
                sleeve_id=f"eth5m|{phase_tag}|off_{offset}|d{depth}|" + "&".join(combo),
                phase=phase_tag, offset=offset, depth=depth, gate_stack="&".join(combo),
                n_train=m_train["n"], wr_train=round(m_train["wr"], 4), dpt_25_train=round(m_train["dpt"], 3),
                sum_25_train=round(m_train["sum"], 2),
                n_val=m_val["n"], wr_val=round(m_val["wr"], 4), dpt_25_val=round(m_val["dpt"], 3),
                sum_25_val=round(m_val["sum"], 2),
                n_lockbox=ml["n"], wr_lockbox=round(ml["wr"], 4),
                dpt_25_lockbox=round(ml["dpt"], 3),
                sum_25_lockbox=round(ml["sum"], 2),
                dd_25_lockbox=round(ml["dd"], 2),
                loss_streak=ml["loss_streak"],
                sharpe=round(ml["sharpe"], 3),
                active_days_lockbox=ml["active_days"],
                bootstrap_p_lockbox=round(bp, 4),
                n_full=m_full["n"] if m_full else 0,
                wr_full=round(m_full["wr"], 4) if m_full else 0.0,
                dpt_25_full=round(m_full["dpt"], 3) if m_full else 0.0,
                sum_25_full=round(m_full["sum"], 2) if m_full else 0.0,
                proj_32d=round(proj_32d_lock, 2),
                proj_full=round(proj_full, 2),
                proj_honest=round(proj_honest, 2),
                objective=round(ml["dpt"] * np.sqrt(ml["n"]), 3),
            )
            writer.writerow(row)
            survivors += 1
    return survivors


def main():
    print(f"Loading {UNIV}")
    df = pd.read_parquet(UNIV)
    print(f"  shape={df.shape}")

    df["day"] = pd.to_datetime(df["fire_us"], unit="us").dt.date
    days_sorted = sorted(df["day"].unique())
    n_total = len(days_sorted)
    # V8 brief: 60/20/20
    n_train = int(n_total * 0.60)
    n_val = int(n_total * 0.20)
    n_lockbox = n_total - n_train - n_val
    train_days = set(days_sorted[:n_train])
    val_days = set(days_sorted[n_train:n_train + n_val])
    lockbox_days = set(days_sorted[n_train + n_val:])
    days_lockbox = len(lockbox_days)
    days_full = n_total

    print(f"  days total={n_total}, train={n_train}d, val={n_val}d, lockbox={n_lockbox}d")
    print(f"  lockbox span: {min(lockbox_days)} -> {max(lockbox_days)}")
    print(f"  atom pool size: {len(ATOMS_ALL)}")

    fieldnames = ["sleeve_id", "phase", "offset", "depth", "gate_stack",
                  "n_train", "wr_train", "dpt_25_train", "sum_25_train",
                  "n_val", "wr_val", "dpt_25_val", "sum_25_val",
                  "n_lockbox", "wr_lockbox", "dpt_25_lockbox", "sum_25_lockbox",
                  "dd_25_lockbox", "loss_streak", "sharpe", "active_days_lockbox",
                  "bootstrap_p_lockbox",
                  "n_full", "wr_full", "dpt_25_full", "sum_25_full",
                  "proj_32d", "proj_full", "proj_honest", "objective"]
    fout = open(OUT_CSV, "w", newline="")
    wr = csv.DictWriter(fout, fieldnames=fieldnames)
    wr.writeheader()

    total_survivors = 0
    t0 = time.time()

    # ---- Phase 1: STRICT COMBOS, depths {3,4} ----
    print(f"\n=== PHASE 1: strict combos, depths {{3, 4}} ===")
    for offset in [30, 60, 90, 120]:
        pool = df[df["fire_offset_s"] == offset].copy()
        pool_t = pool[pool["day"].isin(train_days)]
        pool_v = pool[pool["day"].isin(val_days)]
        pool_l = pool[pool["day"].isin(lockbox_days)]
        if len(pool_l) < 100:
            continue
        s = search_strict_combos(pool_t, pool_v, pool_l, pool, ATOMS_ALL, offset, [3, 4], wr,
                                  "strictV8", days_lockbox, days_full)
        total_survivors += s
        print(f"  offset {offset}: survivors={s}, total={total_survivors}, elapsed={time.time()-t0:.1f}s")

    fout.close()
    print(f"\n=== TOTAL PHASE 1 survivors: {total_survivors}, elapsed={time.time()-t0:.1f}s ===")
    print(f"Saved -> {OUT_CSV}")


if __name__ == "__main__":
    main()
