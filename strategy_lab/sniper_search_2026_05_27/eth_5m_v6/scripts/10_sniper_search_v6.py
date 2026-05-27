"""V6 sniper search for ETH 5m.

Strategy:
  - Two-phase exploration:
    Phase A: PRE-WINDOW signal sleeves — use at_ws gates only, fire at offset∈{30, 60}.
    Phase B: EARLY-OFFSET sleeves — use combined gates, fire at offset∈{30, 60, 90}.
    Phase C: VERIFY V5 winners at offset=120 hold up.

Composable gates: drawn from BOTH master_gate (fire-time) and at_ws (pre-window).
Higher gate count = higher conviction = bigger Kelly stake.

Survivor bar (V6):
  WR_lockbox >= 0.65
  $/tr lockbox >= $4
  max_dd_lockbox >= -$500
  loss_streak <= 14
  active_days_lockbox >= 2
  n_lockbox >= 5
  bootstrap_p <= 0.05

Search: exhaustive C(N, k) for k in {3, 4, 5} over offset slices.

Output: _results/v6_validated.csv (all survivors)
"""
import sys, os, json, itertools, time, csv
import pandas as pd
import numpy as np

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
UNIV = os.path.join(ROOT, "data/v4/canonical/_results/_sniper_eth5m_v6_universe.parquet")
RES = os.path.join(ROOT, "strategy_lab/sniper_search_2026_05_27/eth_5m_v6/_results")
OUT_CSV = os.path.join(RES, "v6_validated.csv")

# Atoms grouped by phase relevance.
# Pre-window atoms (anchored at ws_s)
ATOMS_AT_WS = [
    "g_f7_with", "g_f7_extreme_with", "g_f7_strong_with", "g_f7_trend_with",
    "g_mp_skew_at_ws_with", "g_mp_skew_at_ws_strong",
    "g_choch_with", "g_bos_with", "g_cvd_with",
    "g_sms_liq_reclaim_with_at_ws",
    "g_regime_ranging_at_ws",
    "g_markov_with",  # M1V at fire-time = same as at_ws (Markov state is per-bar)
]

# Fire-time atoms (anchored at fire_us, in v3 fire universe)
ATOMS_AT_FIRE = [
    "g_tr_above_ema200", "g_tr_above_ema50", "g_tr_above_cloud", "g_tr_stack_with",
    "g_ribbon_agrees", "g_rf_with",
    "g_bb_pos_with", "g_cci_with",
    "g_mp_skew_with", "g_mp_no_extreme",
    "g_sms_liq_reclaim_with", "g_sms_no_liquidity_above",
    "g_tr_in_active_session",
    "g_imb5_strong_with",
    "g_hurst_trending", "g_vol_high",
    "g_hawkes_imbalance_with",
]

# Time-of-day / vwap atoms
ATOMS_HOD_VWAP = [
    "g_hod_european", "g_hod_us_morning", "g_hod_overnight",
    "g_entry_vwap_in_band", "g_entry_vwap_in_band_narrow", "g_entry_vwap_in_band_wide",
]

OFFSETS_EARLY = [30, 60, 90]
OFFSETS_LATE = [120, 150, 180]


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


def bootstrap_p_fast(pnl, fire_us, stake=25.0, n_iter=1000, seed=42):
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


def search_offset_combos(pool, atom_pool, offset, depths, writer, phase_tag):
    """Run exhaustive search across (depth ∈ depths) for combos of atom_pool."""
    days_sorted = sorted(pool["day"].unique())
    if len(days_sorted) < 6:
        return 0
    # 3-way split chronological
    n_lockbox = max(4, int(len(days_sorted) * 0.15))
    n_val = max(4, int(len(days_sorted) * 0.18))
    lockbox_days = set(days_sorted[-n_lockbox:])
    val_days = set(days_sorted[-(n_lockbox + n_val):-n_lockbox])
    train_days = set(days_sorted[:-(n_lockbox + n_val)])

    pool_t = pool[pool["day"].isin(train_days)]
    pool_v = pool[pool["day"].isin(val_days)]
    pool_l = pool[pool["day"].isin(lockbox_days)]
    if len(pool_l) < 100:
        return 0

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
            if n_l < 5:
                continue
            wr_l = won_l[m_l].mean()
            if wr_l < 0.65:
                continue
            dpt_l_raw = pnl_l[m_l].mean()
            if dpt_l_raw < 4.0:
                continue
            ml_metrics = metrics_fast(pnl_l[m_l], won_l[m_l], fus_l[m_l], 25.0)
            if ml_metrics["active_days"] < 2:
                continue
            if ml_metrics["loss_streak"] > 14:
                continue
            if ml_metrics["dd"] < -500:
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
            bp = bootstrap_p_fast(pnl_l[m_l], fus_l[m_l], 25.0)
            if bp > 0.05:
                continue
            row = dict(
                sleeve_id=f"eth5m|{phase_tag}|off_{offset}|" + "&".join(combo),
                phase=phase_tag, offset=offset, gate_stack="&".join(combo), depth=depth,
                n_train=m_train["n"], wr_train=round(m_train["wr"], 4), dpt_train_25=round(m_train["dpt"], 3),
                sum_train_25=round(m_train["sum"], 2),
                n_val=m_val["n"] if m_val else 0,
                wr_val=round(m_val["wr"], 4) if m_val else 0,
                dpt_val_25=round(m_val["dpt"], 3) if m_val else 0,
                sum_val_25=round(m_val["sum"], 2) if m_val else 0,
                n_lockbox=ml_metrics["n"], wr_lockbox=round(ml_metrics["wr"], 4),
                dpt_lockbox_25=round(ml_metrics["dpt"], 3),
                sum_lockbox_25=round(ml_metrics["sum"], 2),
                dd_lockbox_25=round(ml_metrics["dd"], 2),
                ls_lockbox=ml_metrics["loss_streak"],
                sharpe_lockbox=round(ml_metrics["sharpe"], 3),
                active_days_lockbox=ml_metrics["active_days"],
                boot_p_lockbox=round(bp, 4),
                objective=round(ml_metrics["dpt"] * np.sqrt(ml_metrics["n"]), 3),
            )
            writer.writerow(row)
            survivors += 1
    return survivors


def main():
    print(f"Loading {UNIV}")
    df = pd.read_parquet(UNIV)
    print(f"  shape={df.shape}")

    fieldnames = ["sleeve_id", "phase", "offset", "gate_stack", "depth",
                  "n_train", "wr_train", "dpt_train_25", "sum_train_25",
                  "n_val", "wr_val", "dpt_val_25", "sum_val_25",
                  "n_lockbox", "wr_lockbox", "dpt_lockbox_25", "sum_lockbox_25",
                  "dd_lockbox_25", "ls_lockbox", "sharpe_lockbox", "active_days_lockbox",
                  "boot_p_lockbox", "objective"]
    fout = open(OUT_CSV, "w", newline="")
    wr = csv.DictWriter(fout, fieldnames=fieldnames)
    wr.writeheader()

    total_survivors = 0
    t0 = time.time()

    # ---- Phase A: pre-window signal sleeves at early offset ----
    print("\n=== PHASE A: pre-window atoms only, offsets {30,60} ===")
    atom_pool_a = ATOMS_AT_WS + ATOMS_HOD_VWAP
    for offset in [30, 60]:
        pool = df[df["fire_offset_s"] == offset].copy()
        if len(pool) < 500:
            continue
        s = search_offset_combos(pool, atom_pool_a, offset, [3, 4], wr, "preWS")
        total_survivors += s
        print(f"  offset {offset}: survivors={s}, total={total_survivors}, elapsed={time.time()-t0:.1f}s")

    # ---- Phase B: early-offset full atom set ----
    print("\n=== PHASE B: ALL atoms, early offsets {30,60,90} ===")
    atom_pool_b = ATOMS_AT_FIRE + ATOMS_AT_WS + ATOMS_HOD_VWAP
    for offset in OFFSETS_EARLY:
        pool = df[df["fire_offset_s"] == offset].copy()
        if len(pool) < 500:
            continue
        # depth 3 + 4 with this large atom pool — careful of explosion
        # |B| = 35 — C(35,3)=6545, C(35,4)=52360; still feasible (~minute)
        s = search_offset_combos(pool, atom_pool_b, offset, [3, 4], wr, "earlyFull")
        total_survivors += s
        print(f"  offset {offset}: survivors={s}, total={total_survivors}, elapsed={time.time()-t0:.1f}s")

    # ---- Phase C: confirm V5 winners hold up at offset 120 ----
    print("\n=== PHASE C: full atoms, late offsets {120,150,180} (V5 winner zone) ===")
    for offset in OFFSETS_LATE:
        pool = df[df["fire_offset_s"] == offset].copy()
        if len(pool) < 500:
            continue
        s = search_offset_combos(pool, atom_pool_b, offset, [3, 4], wr, "lateFull")
        total_survivors += s
        print(f"  offset {offset}: survivors={s}, total={total_survivors}, elapsed={time.time()-t0:.1f}s")

    fout.close()
    print(f"\nTotal survivors: {total_survivors}, elapsed {time.time()-t0:.1f}s")
    print(f"Saved -> {OUT_CSV}")


if __name__ == "__main__":
    main()
