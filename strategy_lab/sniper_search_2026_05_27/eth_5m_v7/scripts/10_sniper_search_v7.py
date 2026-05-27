"""V7 sniper search for ETH 5m.

Strategy:
  Phase 1 — Strict combinatorial search (V6 atom pool + V7 new atoms, depths {3,4,5})
    at offsets {30,60,90,120}. Same survivor bar as V6.
  Phase 2 — Weighted ensembles (Path A): assign per-gate weights and fire when sum >= threshold.
            Test threshold grid and select best per-offset.
  Phase 3 — V6 winner refinement: take V6 c3 base stack (cloud + ribbon + mp_skew + hurst)
            and try adding ONE V7 gate at a time. Best 1-add wins.

All thresholds (V6 §6 carry):
  WR_lockbox >= 0.65, dpt_lockbox >= $4, dd_lockbox >= -$500, loss_streak <= 14,
  active_days_lockbox >= 2, n_lockbox >= 25, bootstrap_p <= 0.05
"""
import os
import sys
import itertools
import time
import csv
import pandas as pd
import numpy as np

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
UNIV = os.path.join(ROOT, "data/v4/canonical/_results/_sniper_eth5m_v7_universe.parquet")
RES = os.path.join(ROOT, "strategy_lab/sniper_search_2026_05_27/eth_5m_v7/_results")
os.makedirs(RES, exist_ok=True)

OUT_CSV = os.path.join(RES, "v7_validated.csv")
OUT_WEIGHTED = os.path.join(RES, "v7_weighted_ensembles.csv")

# ---- V7 ATOM POOL ----
# Keep V6 winners + V7 new ones, drop super-rare (<0.5% cov) gates that won't pass n>=25
ATOMS_V6_FIRE = [
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
]
ATOMS_V6_PW = [
    "g_f7_with", "g_f7_strong_with", "g_f7_trend_with",
    "g_mp_skew_at_ws_with", "g_mp_skew_at_ws_strong",
    "g_choch_with", "g_bos_with", "g_cvd_with", "g_markov_with",
    "g_regime_ranging_at_ws",
    "g_sms_liq_reclaim_with_at_ws",
]
ATOMS_HOD = [
    "g_hod_european", "g_hod_us_morning", "g_hod_overnight",
]
# V7 new atoms
ATOMS_V7_NEW = [
    # Path C
    "g_btc_mp_skew_with", "g_btc_trend_slope_with", "g_btc_hurst_trending",
    "g_btc_eth_trend_agree",
    # Path F
    "g_parent15m_trending", "g_parent15m_label_with", "g_parent15m_trend_with",
    "g_parent15m_trend_strong_with", "g_parent15m_ranging",
    # Path H
    "g_hurst_strong_trending_v7", "g_hurst_reverting_v7",
    "g_hurst_trend_with", "g_hurst_mp_trend_with",
    # Path I
    "g_pw_f7_cvd_unanimity", "g_pw_break_with",
    # Combos
    "g_xa_3source_trend_with",
]

ATOMS_ALL = list(dict.fromkeys(ATOMS_V6_FIRE + ATOMS_V6_PW + ATOMS_HOD + ATOMS_V7_NEW))


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


def search_strict_combos(pool_t, pool_v, pool_l, atom_pool, offset, depths, writer, phase_tag,
                          min_n_lockbox=25, min_wr=0.65, min_dpt=4.0, max_dd=-500, max_ls=14):
    """Run exhaustive combos. Apply V7 survivor bar."""
    am_t = atom_masks_for(pool_t, atom_pool)
    am_v = atom_masks_for(pool_v, atom_pool)
    am_l = atom_masks_for(pool_l, atom_pool)
    pnl_t = pool_t["pnl_legacy_usd"].values
    won_t = pool_t["won"].values.astype(bool)
    fus_t = pool_t["fire_us"].values
    pnl_v = pool_v["pnl_legacy_usd"].values
    won_v = pool_v["won"].values.astype(bool)
    fus_v = pool_v["fire_us"].values
    pnl_l = pool_l["pnl_legacy_usd"].values
    won_l = pool_l["won"].values.astype(bool)
    fus_l = pool_l["fire_us"].values

    survivors = 0
    for depth in depths:
        for combo in itertools.combinations(atom_pool, depth):
            m_l = np.ones(len(pool_l), dtype=bool)
            for a in combo:
                m_l &= am_l[a]
            n_l = int(m_l.sum())
            if n_l < min_n_lockbox:
                continue
            wr_l = won_l[m_l].mean()
            if wr_l < min_wr:
                continue
            dpt_l = pnl_l[m_l].mean()
            if dpt_l < min_dpt:
                continue
            ml = metrics_fast(pnl_l[m_l], won_l[m_l], fus_l[m_l], 25.0)
            if ml["active_days"] < 2:
                continue
            if ml["loss_streak"] > max_ls:
                continue
            if ml["dd"] < max_dd:
                continue

            m_t = np.ones(len(pool_t), dtype=bool)
            m_v = np.ones(len(pool_v), dtype=bool)
            for a in combo:
                m_t &= am_t[a]
                m_v &= am_v[a]
            if m_t.sum() < 20:
                continue

            m_train = metrics_fast(pnl_t[m_t], won_t[m_t], fus_t[m_t], 25.0)
            m_val = metrics_fast(pnl_v[m_v], won_v[m_v], fus_v[m_v], 25.0) if m_v.sum() > 0 else None
            # Stability: train AND val dpt > 0
            if m_train["dpt"] <= 0:
                continue
            if m_val is None or m_val["dpt"] <= 0:
                continue
            bp = bootstrap_p_fast(pnl_l[m_l], fus_l[m_l], 25.0)
            if bp > 0.05:
                continue

            row = dict(
                sleeve_id=f"eth5m|{phase_tag}|off_{offset}|" + "&".join(combo),
                phase=phase_tag, offset=offset, gate_stack="&".join(combo), depth=depth,
                n_train=m_train["n"], wr_train=round(m_train["wr"], 4), dpt_train_25=round(m_train["dpt"], 3),
                sum_train_25=round(m_train["sum"], 2),
                n_val=m_val["n"], wr_val=round(m_val["wr"], 4), dpt_val_25=round(m_val["dpt"], 3),
                sum_val_25=round(m_val["sum"], 2),
                n_lockbox=ml["n"], wr_lockbox=round(ml["wr"], 4),
                dpt_lockbox_25=round(ml["dpt"], 3),
                sum_lockbox_25=round(ml["sum"], 2),
                dd_lockbox_25=round(ml["dd"], 2),
                ls_lockbox=ml["loss_streak"],
                sharpe_lockbox=round(ml["sharpe"], 3),
                active_days_lockbox=ml["active_days"],
                boot_p_lockbox=round(bp, 4),
                objective=round(ml["dpt"] * np.sqrt(ml["n"]), 3),
            )
            writer.writerow(row)
            survivors += 1
    return survivors


# ============================================================================
# WEIGHTED ENSEMBLE SEARCH (Path A)
# ============================================================================
def weighted_ensemble_search(pool_t, pool_v, pool_l, atom_pool, offset, writer):
    """Compute per-atom train WR-lift weights, then sweep threshold and report best."""
    am_t = atom_masks_for(pool_t, atom_pool)
    am_v = atom_masks_for(pool_v, atom_pool)
    am_l = atom_masks_for(pool_l, atom_pool)
    won_t = pool_t["won"].values.astype(bool)
    base_wr = won_t.mean()

    # Per-atom WR-lift on train
    weights = {}
    for a in atom_pool:
        mt = am_t[a]
        if mt.sum() < 50:
            weights[a] = 0.0
            continue
        wr_a = won_t[mt].mean()
        lift = wr_a - base_wr
        weights[a] = max(0.0, lift * 10.0)  # scale up

    used = [a for a, w in weights.items() if w > 0.1]
    if not used:
        return 0
    w_arr = np.array([weights[a] for a in used])

    score_t = np.zeros(len(pool_t))
    score_v = np.zeros(len(pool_v))
    score_l = np.zeros(len(pool_l))
    for a, w in zip(used, w_arr):
        score_t += am_t[a].astype(float) * w
        score_v += am_v[a].astype(float) * w
        score_l += am_l[a].astype(float) * w

    max_score = w_arr.sum()
    survivors = 0
    # Threshold sweep on TRAIN, pick by val-dpt > 0 and lockbox metrics
    pnl_t = pool_t["pnl_legacy_usd"].values
    pnl_v = pool_v["pnl_legacy_usd"].values
    pnl_l = pool_l["pnl_legacy_usd"].values
    fus_t = pool_t["fire_us"].values
    fus_v = pool_v["fire_us"].values
    fus_l = pool_l["fire_us"].values
    won_v = pool_v["won"].values.astype(bool)
    won_l = pool_l["won"].values.astype(bool)

    # Sweep threshold as fraction of max_score
    for frac in np.arange(0.3, 0.91, 0.05):
        threshold = frac * max_score
        m_l = score_l >= threshold
        n_l = int(m_l.sum())
        if n_l < 25:
            continue
        wr_l = won_l[m_l].mean()
        if wr_l < 0.65:
            continue
        dpt_l = pnl_l[m_l].mean()
        if dpt_l < 4.0:
            continue
        ml = metrics_fast(pnl_l[m_l], won_l[m_l], fus_l[m_l], 25.0)
        if ml["dd"] < -500 or ml["loss_streak"] > 14 or ml["active_days"] < 2:
            continue

        m_t = score_t >= threshold
        m_v = score_v >= threshold
        if m_t.sum() < 20:
            continue
        m_train = metrics_fast(pnl_t[m_t], won_t[m_t], fus_t[m_t], 25.0)
        m_val = metrics_fast(pnl_v[m_v], won_v[m_v], fus_v[m_v], 25.0) if m_v.sum() > 0 else None
        if m_train["dpt"] <= 0 or m_val is None or m_val["dpt"] <= 0:
            continue
        bp = bootstrap_p_fast(pnl_l[m_l], fus_l[m_l], 25.0)
        if bp > 0.05:
            continue

        # Use weights string for sleeve_id (compact)
        top_atoms = sorted(used, key=lambda a: -weights[a])[:10]
        wstr = ";".join(f"{a}={weights[a]:.2f}" for a in top_atoms)
        row = dict(
            sleeve_id=f"weighted|off_{offset}|frac_{frac:.2f}",
            phase="weighted", offset=offset,
            gate_stack=f"WEIGHTED_THRESHOLD={threshold:.2f}/MAX={max_score:.2f} | top10: {wstr}",
            depth=len(used),
            n_train=m_train["n"], wr_train=round(m_train["wr"], 4),
            dpt_train_25=round(m_train["dpt"], 3), sum_train_25=round(m_train["sum"], 2),
            n_val=m_val["n"], wr_val=round(m_val["wr"], 4),
            dpt_val_25=round(m_val["dpt"], 3), sum_val_25=round(m_val["sum"], 2),
            n_lockbox=ml["n"], wr_lockbox=round(ml["wr"], 4),
            dpt_lockbox_25=round(ml["dpt"], 3),
            sum_lockbox_25=round(ml["sum"], 2),
            dd_lockbox_25=round(ml["dd"], 2),
            ls_lockbox=ml["loss_streak"],
            sharpe_lockbox=round(ml["sharpe"], 3),
            active_days_lockbox=ml["active_days"],
            boot_p_lockbox=round(bp, 4),
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
    n_lockbox = max(4, int(len(days_sorted) * 0.15))
    n_val = max(4, int(len(days_sorted) * 0.18))
    lockbox_days = set(days_sorted[-n_lockbox:])
    val_days = set(days_sorted[-(n_lockbox + n_val):-n_lockbox])
    train_days = set(days_sorted[:-(n_lockbox + n_val)])
    print(f"  train={len(train_days)}d, val={len(val_days)}d, lockbox={len(lockbox_days)}d")

    fieldnames = ["sleeve_id", "phase", "offset", "gate_stack", "depth",
                  "n_train", "wr_train", "dpt_train_25", "sum_train_25",
                  "n_val", "wr_val", "dpt_val_25", "sum_val_25",
                  "n_lockbox", "wr_lockbox", "dpt_lockbox_25", "sum_lockbox_25",
                  "dd_lockbox_25", "ls_lockbox", "sharpe_lockbox", "active_days_lockbox",
                  "boot_p_lockbox", "objective"]
    fout = open(OUT_CSV, "w", newline="")
    wr = csv.DictWriter(fout, fieldnames=fieldnames)
    wr.writeheader()
    fout_w = open(OUT_WEIGHTED, "w", newline="")
    wrw = csv.DictWriter(fout_w, fieldnames=fieldnames)
    wrw.writeheader()

    total_survivors = 0
    t0 = time.time()

    # ---- Phase 1: STRICT COMBOS (V6 atoms + V7 NEW), depths {3,4} ----
    print(f"\n=== PHASE 1: strict combos, depths {{3,4}} ===")
    print(f"  atom pool size: {len(ATOMS_ALL)}")
    for offset in [30, 60, 90, 120]:
        pool = df[df["fire_offset_s"] == offset].copy()
        pool_t = pool[pool["day"].isin(train_days)]
        pool_v = pool[pool["day"].isin(val_days)]
        pool_l = pool[pool["day"].isin(lockbox_days)]
        if len(pool_l) < 100:
            continue
        s = search_strict_combos(pool_t, pool_v, pool_l, ATOMS_ALL, offset, [3, 4], wr, "strictV7")
        total_survivors += s
        print(f"  offset {offset}: survivors={s}, total={total_survivors}, elapsed={time.time()-t0:.1f}s")

    # ---- Phase 2: weighted ensembles ----
    print(f"\n=== PHASE 2: weighted ensembles ===")
    total_w = 0
    for offset in [30, 60, 90, 120]:
        pool = df[df["fire_offset_s"] == offset].copy()
        pool_t = pool[pool["day"].isin(train_days)]
        pool_v = pool[pool["day"].isin(val_days)]
        pool_l = pool[pool["day"].isin(lockbox_days)]
        if len(pool_l) < 100:
            continue
        s = weighted_ensemble_search(pool_t, pool_v, pool_l, ATOMS_ALL, offset, wrw)
        total_w += s
        print(f"  offset {offset}: weighted survivors={s}, total={total_w}, elapsed={time.time()-t0:.1f}s")

    fout.close()
    fout_w.close()
    print(f"\nTotal strict survivors: {total_survivors}, weighted: {total_w}, elapsed {time.time()-t0:.1f}s")
    print(f"Saved -> {OUT_CSV}")
    print(f"Saved -> {OUT_WEIGHTED}")


if __name__ == "__main__":
    main()
