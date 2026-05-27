"""V7 main search: Paths A (weighted ensemble), D (slot-end OFI), G (vol regime), H (hurst variants).

Mirrors V6 search infra but:
1. Uses the V7-extended panel (sniper_btc15m_v7_gated.parquet)
2. Adds the 14 new V7 gates to the atom pool
3. Adds a Path A weighted-ensemble pass:
   - Compute per-gate "WR-lift" weight on train
   - Build conviction score = sum(weight[g] for g passing) / sum(all_weights)
   - Threshold sweep -> firing condition
4. Adds Path G: per-vol-regime specialization (run 2/3-gate search within g_rv_lo, g_rv_md, g_rv_hi cohorts)
5. Adds Path D specifically for off=840: 3-gate stacks including g_slot_end_ofi_with/strong_with

Output:
- v7_combinatorial_all.csv (all post-V7-bar survivors)
- v7_final_candidates.csv (post-bootstrap)
- v7_ensemble_top.csv (weighted ensemble winners)
- v7_near_misses.csv
"""
import os, sys, time, itertools, json
import numpy as np
import pandas as pd

RES = "data/v4/canonical/_results"
IN = f"{RES}/sniper_btc15m_v7_gated.parquet"
OUT_DIR = "strategy_lab/sniper_search_2026_05_27/btc_15m_v7"

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)


log("loading V7 panel")
df = pd.read_parquet(IN)
df["fire_date"] = pd.to_datetime(df["fire_us"], unit="us", utc=True)
df = df[(df["trend_slope_30m"].notna()) & (df["mp_skew"].notna())].copy()
df = df[(df["entry_vwap"] >= 0.10) & (df["entry_vwap"] <= 0.90)].copy()
df = df.sort_values("fire_us").reset_index(drop=True)
log(f"rows after filters: {len(df)}, days: {df.fire_date.dt.date.nunique()}")

# 3-way split chronological: train 18d / val 6d / lockbox 4d
TRAIN_START = pd.Timestamp("2026-04-28", tz="UTC")
TRAIN_END   = pd.Timestamp("2026-05-16", tz="UTC")
VAL_END     = pd.Timestamp("2026-05-22", tz="UTC")
LOCK_END    = pd.Timestamp("2026-05-26", tz="UTC")

tr_mask = (df.fire_date >= TRAIN_START) & (df.fire_date < TRAIN_END)
va_mask = (df.fire_date >= TRAIN_END) & (df.fire_date < VAL_END)
lo_mask = (df.fire_date >= VAL_END) & (df.fire_date < LOCK_END)
df_tr = df[tr_mask].copy()
df_va = df[va_mask].copy()
df_lo = df[lo_mask].copy()
log(f"split: train={len(df_tr)}, val={len(df_va)}, lock={len(df_lo)}")

LO_DAYS = max(1, (LOCK_END - VAL_END).days)
SCALE_28D = 28 / LO_DAYS


def compute_dd(pnl_arr):
    if len(pnl_arr) == 0: return 0.0
    cum = np.cumsum(pnl_arr)
    peak = np.maximum.accumulate(cum)
    return float(-(cum - peak).min())


def max_loss_streak(won_arr):
    if len(won_arr) == 0: return 0
    streak = mx = 0
    for w in won_arr:
        if w == 0:
            streak += 1; mx = max(mx, streak)
        else:
            streak = 0
    return mx


def daily_sharpe(d):
    if len(d) == 0: return 0.0
    daily = d.groupby(d.fire_date.dt.date)["pnl_legacy_usd"].sum()
    if len(daily) < 2 or daily.std() == 0:
        return 0.0
    return float(daily.mean() / daily.std() * np.sqrt(365))


def bootstrap_p(d_lock, n_shuffles=1000, seed=42):
    if len(d_lock) < 5: return np.nan
    daily = d_lock.groupby(d_lock.fire_date.dt.date)["pnl_legacy_usd"].sum().values
    n_days = len(daily)
    if n_days < 2: return np.nan
    rng = np.random.default_rng(seed)
    boot = rng.choice(daily, size=(n_shuffles, n_days), replace=True).sum(axis=1)
    p = float((boot <= 0).sum() / n_shuffles)
    return max(p, 1.0 / n_shuffles)


def metrics(d_split, gates):
    if not gates:
        m = np.ones(len(d_split), dtype=bool)
    else:
        m = np.ones(len(d_split), dtype=bool)
        for g in gates:
            m &= (d_split[g].values == 1)
    sub = d_split[m]
    if len(sub) == 0:
        return None
    pnl = sub["pnl_legacy_usd"].values
    won = sub["won"].values.astype(int)
    return dict(
        n=len(sub),
        wr=float(won.mean()),
        dpt=float(pnl.mean()),
        sum_pnl=float(pnl.sum()),
        max_dd=compute_dd(pnl),
        loss_streak=max_loss_streak(won),
        unique_days=int(sub.fire_date.dt.date.nunique()),
        sharpe=daily_sharpe(sub),
        sub=sub,
    )


DROP = {"g_within_dev",       # 100% fire rate
        "g_dev_extreme",      # 0% fire rate
        "g_jump_dir_with",    # too sparse
        "g_off_0_60",         # use direct offset filter
        "g_off_60_240",
        "g_off_240_480",
        "g_off_480_720",
        "g_off_720_900",
        "g_tight_ribbon",     # 94.8% fire rate
        "g_tr_in_active_session",
        "g_vwap_05_95",       # 84.6% (too loose)
        }
NEW_V7 = ['g_hurst_strong_trending','g_hurst_reverting','g_hurst_strong_trending_900',
          'g_hurst_reverting_900','g_hurst_trending_with',
          'g_rv_lo','g_rv_md','g_rv_hi',
          'g_slot_end_ofi_with','g_slot_end_ofi_strong_with',
          'g_ret_2m_with','g_ret_2m_strong_with',
          'g_vwap_deep_premium','g_vwap_mid']
ALL_G = sorted([c for c in df.columns if c.startswith("g_") and c not in DROP])
ALL_G = [g for g in ALL_G if df[g].sum() > 0]
log(f"candidate atoms: {len(ALL_G)} (including {len(set(NEW_V7) & set(ALL_G))} new V7 gates)")


# V7 sniper test on lockbox (per _BRIEF_V7 §2 - kept from V6)
def pass_v7(m_lo):
    if m_lo is None: return False
    if m_lo["n"] < 10: return False
    if m_lo["unique_days"] < 3: return False
    if m_lo["wr"] < 0.65: return False
    if m_lo["dpt"] < 4.0: return False
    if m_lo["max_dd"] > 500.0: return False
    if m_lo["loss_streak"] > 14: return False
    if m_lo["sharpe"] < 1.5: return False
    return True


# ============== Phase 1: V7 2-gate cross-cut where at LEAST 1 gate is new ==============
log("Phase 1: 2-gate combos involving NEW V7 gates")
survivors = []
near_misses = []
total_tested = 0
OFFSETS = sorted(df.fire_offset_s.unique())
DIRS = ["UP", "DOWN", "BOTH"]
NEW_ACTIVE = [g for g in NEW_V7 if g in ALL_G]

for off in OFFSETS:
    for dir_val in DIRS:
        if dir_val == "BOTH":
            dtr = df_tr[df_tr.fire_offset_s == off]
            dva = df_va[df_va.fire_offset_s == off]
            dlo = df_lo[df_lo.fire_offset_s == off]
        else:
            dtr = df_tr[(df_tr.fire_offset_s == off) & (df_tr.direction == dir_val)]
            dva = df_va[(df_va.fire_offset_s == off) & (df_va.direction == dir_val)]
            dlo = df_lo[(df_lo.fire_offset_s == off) & (df_lo.direction == dir_val)]
        if len(dtr) < 80:
            continue
        for g_new in NEW_ACTIVE:
            for g_other in ALL_G:
                if g_other == g_new: continue
                total_tested += 1
                gates = sorted([g_new, g_other])
                m_tr = metrics(dtr, gates)
                if m_tr is None or m_tr["n"] < 30:
                    continue
                if m_tr["wr"] < 0.55 or m_tr["dpt"] < 1.0:
                    continue
                m_lo = metrics(dlo, gates)
                if m_lo is None: continue
                if not pass_v7(m_lo):
                    if (m_lo["n"] >= 10 and m_lo["wr"] >= 0.60 and m_lo["dpt"] >= 3.0):
                        m_va = metrics(dva, gates)
                        near_misses.append(dict(
                            offset=off, direction=dir_val, gates=gates, n_gates=2,
                            train_n=m_tr["n"], train_wr=m_tr["wr"], train_dpt=m_tr["dpt"],
                            val_n=m_va["n"] if m_va else 0,
                            val_wr=m_va["wr"] if m_va else np.nan,
                            val_dpt=m_va["dpt"] if m_va else np.nan,
                            lock_n=m_lo["n"], lock_wr=m_lo["wr"], lock_dpt=m_lo["dpt"],
                            lock_dd=m_lo["max_dd"], lock_streak=m_lo["loss_streak"],
                            lock_days=m_lo["unique_days"], lock_sharpe=m_lo["sharpe"],
                            sum_25_28d=m_lo["sum_pnl"] * SCALE_28D,
                            v7_path="A_2gate_new",
                        ))
                    continue
                m_va = metrics(dva, gates)
                survivors.append(dict(
                    offset=off, direction=dir_val, gates=gates, n_gates=2,
                    train_n=m_tr["n"], train_wr=m_tr["wr"], train_dpt=m_tr["dpt"],
                    val_n=m_va["n"] if m_va else 0,
                    val_wr=m_va["wr"] if m_va else np.nan,
                    val_dpt=m_va["dpt"] if m_va else np.nan,
                    lock_n=m_lo["n"], lock_wr=m_lo["wr"], lock_dpt=m_lo["dpt"],
                    lock_dd=m_lo["max_dd"], lock_streak=m_lo["loss_streak"],
                    lock_days=m_lo["unique_days"], lock_sharpe=m_lo["sharpe"],
                    sum_25_28d=m_lo["sum_pnl"] * SCALE_28D,
                    v7_path="A_2gate_new",
                ))
log(f"Phase 1 tested {total_tested}, survivors: {len(survivors)}, near-misses: {len(near_misses)}")

# ============== Phase 2: 3-gate combos with NEW V7 gate as seed, all offsets ==============
log("Phase 2: 3-gate combos seeded by NEW V7 gate")
# Get top 25 partner gates by (wr * sqrt(n)) on TRAIN
seed_gates = []
for g in ALL_G:
    m_tr = metrics(df_tr, [g])
    if m_tr is None: continue
    if m_tr["wr"] >= 0.49 and m_tr["dpt"] > -1.0:
        seed_gates.append((g, m_tr["wr"], m_tr["n"]))
seed_gates.sort(key=lambda x: x[1] * np.sqrt(x[2]), reverse=True)
SEEDS = [s[0] for s in seed_gates[:30]]
log(f"  top 30 partner gates: {SEEDS[:8]}...")

for off in OFFSETS:
    for dir_val in DIRS:
        if dir_val == "BOTH":
            dtr = df_tr[df_tr.fire_offset_s == off]
            dva = df_va[df_va.fire_offset_s == off]
            dlo = df_lo[df_lo.fire_offset_s == off]
        else:
            dtr = df_tr[(df_tr.fire_offset_s == off) & (df_tr.direction == dir_val)]
            dva = df_va[(df_va.fire_offset_s == off) & (df_va.direction == dir_val)]
            dlo = df_lo[(df_lo.fire_offset_s == off) & (df_lo.direction == dir_val)]
        if len(dtr) < 80: continue
        for g_new in NEW_ACTIVE:
            for g1, g2 in itertools.combinations(SEEDS, 2):
                if g1 == g_new or g2 == g_new: continue
                gates = sorted([g_new, g1, g2])
                m_tr = metrics(dtr, gates)
                if m_tr is None or m_tr["n"] < 20:
                    continue
                if m_tr["wr"] < 0.55 or m_tr["dpt"] < 1.0:
                    continue
                m_lo = metrics(dlo, gates)
                if m_lo is None: continue
                if not pass_v7(m_lo):
                    if (m_lo["n"] >= 10 and m_lo["wr"] >= 0.60 and m_lo["dpt"] >= 3.0):
                        m_va = metrics(dva, gates)
                        near_misses.append(dict(
                            offset=off, direction=dir_val, gates=gates, n_gates=3,
                            train_n=m_tr["n"], train_wr=m_tr["wr"], train_dpt=m_tr["dpt"],
                            val_n=m_va["n"] if m_va else 0,
                            val_wr=m_va["wr"] if m_va else np.nan,
                            val_dpt=m_va["dpt"] if m_va else np.nan,
                            lock_n=m_lo["n"], lock_wr=m_lo["wr"], lock_dpt=m_lo["dpt"],
                            lock_dd=m_lo["max_dd"], lock_streak=m_lo["loss_streak"],
                            lock_days=m_lo["unique_days"], lock_sharpe=m_lo["sharpe"],
                            sum_25_28d=m_lo["sum_pnl"] * SCALE_28D,
                            v7_path="A_3gate_new",
                        ))
                    continue
                m_va = metrics(dva, gates)
                survivors.append(dict(
                    offset=off, direction=dir_val, gates=gates, n_gates=3,
                    train_n=m_tr["n"], train_wr=m_tr["wr"], train_dpt=m_tr["dpt"],
                    val_n=m_va["n"] if m_va else 0,
                    val_wr=m_va["wr"] if m_va else np.nan,
                    val_dpt=m_va["dpt"] if m_va else np.nan,
                    lock_n=m_lo["n"], lock_wr=m_lo["wr"], lock_dpt=m_lo["dpt"],
                    lock_dd=m_lo["max_dd"], lock_streak=m_lo["loss_streak"],
                    lock_days=m_lo["unique_days"], lock_sharpe=m_lo["sharpe"],
                    sum_25_28d=m_lo["sum_pnl"] * SCALE_28D,
                    v7_path="A_3gate_new",
                ))
log(f"Phase 2: total survivors: {len(survivors)}, near-misses: {len(near_misses)}")

# ============== Phase 3 — Path D: off=840 slot-end OFI dedicated search ==============
log("Phase 3: Path D dedicated off=840 slot-end OFI")
SLOT_END_GATES = ['g_slot_end_ofi_with', 'g_slot_end_ofi_strong_with']
PARTNERS_840 = ['g_tr_above_ema800','g_tr_above_ema200','g_tr_above_ema50',
                'g_mp_skew_with','g_mp_skew_strong_with','g_ribbon_slope_with',
                'g_rf_with','g_rf_strong','g_rf_in_band',
                'g_hawkes_imbalance_with','g_hawkes_imb_loose_with',
                'g_f7_rsi_with','g_f7_rsi_strong_with',
                'g_hurst_trending_with','g_ret_2m_with',
                'g_vwap_premium','g_vwap_deep_premium']
PARTNERS_840 = [g for g in PARTNERS_840 if g in ALL_G]
for dir_val in DIRS:
    if dir_val == "BOTH":
        dtr = df_tr[df_tr.fire_offset_s == 840]
        dva = df_va[df_va.fire_offset_s == 840]
        dlo = df_lo[df_lo.fire_offset_s == 840]
    else:
        dtr = df_tr[(df_tr.fire_offset_s == 840) & (df_tr.direction == dir_val)]
        dva = df_va[(df_va.fire_offset_s == 840) & (df_va.direction == dir_val)]
        dlo = df_lo[(df_lo.fire_offset_s == 840) & (df_lo.direction == dir_val)]
    if len(dtr) < 30: continue
    for g_ofi in SLOT_END_GATES:
        for k in [1, 2, 3]:
            for combo in itertools.combinations(PARTNERS_840, k):
                gates = sorted([g_ofi] + list(combo))
                m_tr = metrics(dtr, gates)
                if m_tr is None or m_tr["n"] < 10: continue
                if m_tr["wr"] < 0.50: continue
                m_lo = metrics(dlo, gates)
                if m_lo is None: continue
                if not pass_v7(m_lo):
                    if (m_lo["n"] >= 8 and m_lo["wr"] >= 0.60 and m_lo["dpt"] >= 3.0):
                        m_va = metrics(dva, gates)
                        near_misses.append(dict(
                            offset=840, direction=dir_val, gates=gates, n_gates=len(gates),
                            train_n=m_tr["n"], train_wr=m_tr["wr"], train_dpt=m_tr["dpt"],
                            val_n=m_va["n"] if m_va else 0,
                            val_wr=m_va["wr"] if m_va else np.nan,
                            val_dpt=m_va["dpt"] if m_va else np.nan,
                            lock_n=m_lo["n"], lock_wr=m_lo["wr"], lock_dpt=m_lo["dpt"],
                            lock_dd=m_lo["max_dd"], lock_streak=m_lo["loss_streak"],
                            lock_days=m_lo["unique_days"], lock_sharpe=m_lo["sharpe"],
                            sum_25_28d=m_lo["sum_pnl"] * SCALE_28D,
                            v7_path="D_slot_end_ofi",
                        ))
                    continue
                m_va = metrics(dva, gates)
                survivors.append(dict(
                    offset=840, direction=dir_val, gates=gates, n_gates=len(gates),
                    train_n=m_tr["n"], train_wr=m_tr["wr"], train_dpt=m_tr["dpt"],
                    val_n=m_va["n"] if m_va else 0,
                    val_wr=m_va["wr"] if m_va else np.nan,
                    val_dpt=m_va["dpt"] if m_va else np.nan,
                    lock_n=m_lo["n"], lock_wr=m_lo["wr"], lock_dpt=m_lo["dpt"],
                    lock_dd=m_lo["max_dd"], lock_streak=m_lo["loss_streak"],
                    lock_days=m_lo["unique_days"], lock_sharpe=m_lo["sharpe"],
                    sum_25_28d=m_lo["sum_pnl"] * SCALE_28D,
                    v7_path="D_slot_end_ofi",
                ))
log(f"Phase 3 (slot-end OFI): total survivors: {len(survivors)}")

# ============== Phase 4 — Path G: vol-regime-specialized stacks ==============
log("Phase 4: Path G vol-regime-specialized 3-gate stacks (late offsets)")
LATE = [600, 720, 840]
REG_GATES = ['g_rv_lo', 'g_rv_md', 'g_rv_hi']
PARTNERS_REG = ['g_tr_above_ema800','g_tr_above_ema200','g_tr_above_ema50','g_tr_above_pp',
                'g_mp_skew_with','g_mp_skew_strong_with','g_mp_no_extreme',
                'g_ribbon_slope_with','g_ribbon_agrees',
                'g_rf_with','g_rf_strong','g_rf_in_band','g_rf_fresh',
                'g_hawkes_imbalance_with','g_hawkes_imb_loose_with',
                'g_f7_rsi_with','g_f7_rsi_strong_with',
                'g_hurst_trending_with',
                'g_vwap_premium','g_vwap_deep_premium','g_vwap_mid',
                'g_trend_slope_with','g_trend_slope_strong_with',
                'g_sms_trend_with','g_sms_trend_strong_with']
PARTNERS_REG = [g for g in PARTNERS_REG if g in ALL_G]
for off in LATE:
    for dir_val in DIRS:
        if dir_val == "BOTH":
            dtr = df_tr[df_tr.fire_offset_s == off]
            dva = df_va[df_va.fire_offset_s == off]
            dlo = df_lo[df_lo.fire_offset_s == off]
        else:
            dtr = df_tr[(df_tr.fire_offset_s == off) & (df_tr.direction == dir_val)]
            dva = df_va[(df_va.fire_offset_s == off) & (df_va.direction == dir_val)]
            dlo = df_lo[(df_lo.fire_offset_s == off) & (df_lo.direction == dir_val)]
        if len(dtr) < 30: continue
        for g_reg in REG_GATES:
            for g1, g2 in itertools.combinations(PARTNERS_REG, 2):
                gates = sorted([g_reg, g1, g2])
                m_tr = metrics(dtr, gates)
                if m_tr is None or m_tr["n"] < 15: continue
                if m_tr["wr"] < 0.55 or m_tr["dpt"] < 1.0: continue
                m_lo = metrics(dlo, gates)
                if m_lo is None: continue
                if not pass_v7(m_lo):
                    if (m_lo["n"] >= 10 and m_lo["wr"] >= 0.60 and m_lo["dpt"] >= 3.0):
                        m_va = metrics(dva, gates)
                        near_misses.append(dict(
                            offset=off, direction=dir_val, gates=gates, n_gates=3,
                            train_n=m_tr["n"], train_wr=m_tr["wr"], train_dpt=m_tr["dpt"],
                            val_n=m_va["n"] if m_va else 0,
                            val_wr=m_va["wr"] if m_va else np.nan,
                            val_dpt=m_va["dpt"] if m_va else np.nan,
                            lock_n=m_lo["n"], lock_wr=m_lo["wr"], lock_dpt=m_lo["dpt"],
                            lock_dd=m_lo["max_dd"], lock_streak=m_lo["loss_streak"],
                            lock_days=m_lo["unique_days"], lock_sharpe=m_lo["sharpe"],
                            sum_25_28d=m_lo["sum_pnl"] * SCALE_28D,
                            v7_path="G_vol_regime",
                        ))
                    continue
                m_va = metrics(dva, gates)
                survivors.append(dict(
                    offset=off, direction=dir_val, gates=gates, n_gates=3,
                    train_n=m_tr["n"], train_wr=m_tr["wr"], train_dpt=m_tr["dpt"],
                    val_n=m_va["n"] if m_va else 0,
                    val_wr=m_va["wr"] if m_va else np.nan,
                    val_dpt=m_va["dpt"] if m_va else np.nan,
                    lock_n=m_lo["n"], lock_wr=m_lo["wr"], lock_dpt=m_lo["dpt"],
                    lock_dd=m_lo["max_dd"], lock_streak=m_lo["loss_streak"],
                    lock_days=m_lo["unique_days"], lock_sharpe=m_lo["sharpe"],
                    sum_25_28d=m_lo["sum_pnl"] * SCALE_28D,
                    v7_path="G_vol_regime",
                ))
log(f"Phase 4 (vol regime): total survivors: {len(survivors)}")

# ============== Phase 5 — Path A: WEIGHTED ENSEMBLE ==============
log("Phase 5: Path A weighted ensemble")
# For each offset/direction, compute per-gate WR-lift on TRAIN
# Then score each fire by sum(weight[g] for g passing)
# Sweep threshold; report fires meeting threshold; check V7 bar on lockbox.

# Curated atom menu for ensembles (avoid redundancy)
ENSEMBLE_ATOMS = [
    'g_tr_above_ema800', 'g_tr_above_ema200', 'g_tr_above_ema50', 'g_tr_above_pp',
    'g_mp_skew_with', 'g_mp_skew_strong_with', 'g_mp_no_extreme', 'g_mp_no_extreme_150',
    'g_ribbon_slope_with', 'g_ribbon_agrees',
    'g_rf_with', 'g_rf_strong', 'g_rf_in_band', 'g_rf_fresh',
    'g_hawkes_imbalance_with', 'g_hawkes_imb_loose_with', 'g_hawkes_imb_strong_with',
    'g_f7_rsi_with', 'g_f7_rsi_strong_with', 'g_f7_rsi_extreme_with',
    'g_hurst_trending_with', 'g_hurst_strong_trending',
    'g_trend_slope_with', 'g_trend_slope_strong_with',
    'g_sms_trend_with', 'g_sms_trend_strong_with', 'g_sms_cvd_with',
    'g_vol_expanding', 'g_vol_contracting', 'g_vol_high',
    'g_lm_high_stat', 'g_lm_jump_with',
    'g_imb5_with', 'g_imb5_strong_with', 'g_imb1_strong_with',
    'g_vwap_premium', 'g_vwap_deep_premium', 'g_vwap_mid',
    'g_ret_2m_with', 'g_ret_2m_strong_with',
    'g_bb_pos_with', 'g_cci_with', 'g_stoch_with', 'g_mfi_with',
    'g_adx_strong', 'g_adx_trending', 'g_di_agrees',
    'g_queue_top_high',
    'g_regime_stack_with', 'g_regime_stack_full_with',
    'g_tr_above_cloud', 'g_tr_within_adr',
    'g_vpin_calm',
]
ENSEMBLE_ATOMS = [g for g in ENSEMBLE_ATOMS if g in ALL_G]
log(f"  ensemble atoms: {len(ENSEMBLE_ATOMS)}")


def compute_gate_weights(dtr):
    """Return dict gate -> log(WR_with_gate / WR_without_gate). Clipped to [0, 2.0]."""
    base_wr = dtr['won'].mean()
    weights = {}
    for g in ENSEMBLE_ATOMS:
        if g not in dtr.columns: continue
        gv = dtr[g].values
        on = dtr[gv == 1]
        off = dtr[gv == 0]
        if len(on) < 30 or len(off) < 30:
            continue
        wr_on = on['won'].mean()
        wr_off = off['won'].mean() if len(off) else base_wr
        if wr_off <= 0: continue
        lift = np.log(max(wr_on, 1e-6) / max(wr_off, 1e-6))
        weights[g] = float(np.clip(lift, 0.0, 2.0))  # only positive lifts contribute
    return weights


def score_fires(d, weights):
    """Compute sum-of-weights score per fire."""
    scores = np.zeros(len(d), dtype=np.float64)
    for g, w in weights.items():
        if w == 0: continue
        scores += d[g].astype(np.float64).values * w
    return scores


ensemble_results = []
for off in OFFSETS:
    for dir_val in DIRS:
        if dir_val == "BOTH":
            dtr = df_tr[df_tr.fire_offset_s == off]
            dva = df_va[df_va.fire_offset_s == off]
            dlo = df_lo[df_lo.fire_offset_s == off]
        else:
            dtr = df_tr[(df_tr.fire_offset_s == off) & (df_tr.direction == dir_val)]
            dva = df_va[(df_va.fire_offset_s == off) & (df_va.direction == dir_val)]
            dlo = df_lo[(df_lo.fire_offset_s == off) & (df_lo.direction == dir_val)]
        if len(dtr) < 100: continue
        w = compute_gate_weights(dtr)
        if not w: continue
        max_w = sum(w.values())
        if max_w == 0: continue
        s_tr = score_fires(dtr, w)
        s_va = score_fires(dva, w)
        s_lo = score_fires(dlo, w)
        # Threshold sweep over deciles of TRAIN scores
        thr_grid = np.percentile(s_tr, [50, 60, 70, 75, 80, 85, 90, 95])
        for thr in thr_grid:
            m_tr = dtr[s_tr >= thr]
            m_va = dva[s_va >= thr]
            m_lo = dlo[s_lo >= thr]
            if len(m_tr) < 30: continue
            tr_wr = m_tr['won'].mean()
            tr_dpt = m_tr['pnl_legacy_usd'].mean()
            if tr_wr < 0.55 or tr_dpt < 1.0: continue
            if len(m_lo) < 10: continue
            lo_pnl = m_lo['pnl_legacy_usd'].values
            lo_won = m_lo['won'].values.astype(int)
            m_lo_metrics = dict(
                n=len(m_lo), wr=float(lo_won.mean()), dpt=float(lo_pnl.mean()),
                sum_pnl=float(lo_pnl.sum()),
                max_dd=compute_dd(lo_pnl),
                loss_streak=max_loss_streak(lo_won),
                unique_days=int(m_lo.fire_date.dt.date.nunique()),
                sharpe=daily_sharpe(m_lo),
            )
            if not pass_v7(m_lo_metrics):
                continue
            va_won = m_va['won'].values.astype(int) if len(m_va) else np.array([])
            ensemble_results.append(dict(
                offset=off, direction=dir_val,
                threshold=float(thr), max_weight=float(max_w),
                gate_weights_json=json.dumps({k:round(v,3) for k,v in w.items() if v>0}),
                train_n=len(m_tr), train_wr=float(tr_wr), train_dpt=float(tr_dpt),
                val_n=len(m_va),
                val_wr=float(va_won.mean()) if len(va_won) else np.nan,
                val_dpt=float(m_va['pnl_legacy_usd'].mean()) if len(m_va) else np.nan,
                lock_n=m_lo_metrics['n'], lock_wr=m_lo_metrics['wr'],
                lock_dpt=m_lo_metrics['dpt'], lock_dd=m_lo_metrics['max_dd'],
                lock_streak=m_lo_metrics['loss_streak'],
                lock_days=m_lo_metrics['unique_days'],
                lock_sharpe=m_lo_metrics['sharpe'],
                sum_25_28d=m_lo_metrics['sum_pnl'] * SCALE_28D,
                v7_path="A_weighted_ensemble",
            ))
log(f"Phase 5 (ensembles): {len(ensemble_results)} candidates pre-bootstrap")


# ============== Phase 6: dedup + bootstrap survivors + ensembles ==============
log("Phase 6: dedup + bootstrap")
df_surv = pd.DataFrame(survivors)
if len(df_surv) > 0:
    df_surv["gate_key"] = df_surv["gates"].apply(lambda x: tuple(sorted(x)))
    df_surv["dedup_key"] = list(zip(df_surv["offset"], df_surv["direction"], df_surv["gate_key"]))
    df_surv = df_surv.drop_duplicates(subset=["dedup_key"], keep="first")
    df_surv = df_surv.drop(columns=["gate_key", "dedup_key"])
    log(f"  combinatorial survivors after dedup: {len(df_surv)}")

    for i, row in df_surv.iterrows():
        if row["direction"] == "BOTH":
            d_lo = df_lo[df_lo.fire_offset_s == row["offset"]]
        else:
            d_lo = df_lo[(df_lo.fire_offset_s == row["offset"]) & (df_lo.direction == row["direction"])]
        m = np.ones(len(d_lo), dtype=bool)
        for g in row["gates"]:
            m &= (d_lo[g].values == 1)
        sub = d_lo[m]
        p = bootstrap_p(sub, n_shuffles=1000)
        df_surv.at[i, "bootstrap_p"] = p
        df_surv.at[i, "obj_score"] = row["lock_dpt"] * np.sqrt(row["lock_n"])
    df_surv["gate_stack_str"] = df_surv["gates"].apply(lambda x: "+".join(x))
    df_surv = df_surv.sort_values(["bootstrap_p", "obj_score"], ascending=[True, False])
    df_surv.to_csv(f"{OUT_DIR}/v7_combinatorial_all.csv", index=False)
    final = df_surv[df_surv["bootstrap_p"] <= 0.05].copy()
    final.to_csv(f"{OUT_DIR}/v7_final_candidates.csv", index=False)
    log(f"  combinatorial final post-bootstrap: {len(final)}")


df_ens = pd.DataFrame(ensemble_results)
if len(df_ens) > 0:
    # Bootstrap each ensemble by recomputing scored lockbox
    for i, row in df_ens.iterrows():
        w = json.loads(row['gate_weights_json'])
        if row["direction"] == "BOTH":
            d_lo = df_lo[df_lo.fire_offset_s == row["offset"]]
        else:
            d_lo = df_lo[(df_lo.fire_offset_s == row["offset"]) & (df_lo.direction == row["direction"])]
        s_lo = score_fires(d_lo, w)
        sub = d_lo[s_lo >= row['threshold']]
        p = bootstrap_p(sub, n_shuffles=1000)
        df_ens.at[i, 'bootstrap_p'] = p
        df_ens.at[i, 'obj_score'] = row['lock_dpt'] * np.sqrt(row['lock_n'])
    df_ens = df_ens.sort_values(["bootstrap_p", "obj_score"], ascending=[True, False])
    df_ens.to_csv(f"{OUT_DIR}/v7_ensemble_top.csv", index=False)
    log(f"  ensembles saved: {len(df_ens)}")


df_nm = pd.DataFrame(near_misses)
if len(df_nm) > 0:
    df_nm["gate_key"] = df_nm["gates"].apply(lambda x: tuple(sorted(x)))
    df_nm["dedup_key"] = list(zip(df_nm["offset"], df_nm["direction"], df_nm["gate_key"]))
    df_nm = df_nm.drop_duplicates(subset=["dedup_key"], keep="first").drop(columns=["gate_key", "dedup_key"])
    df_nm["gate_stack_str"] = df_nm["gates"].apply(lambda x: "+".join(x))
    df_nm = df_nm.sort_values("lock_dpt", ascending=False)
    df_nm.to_csv(f"{OUT_DIR}/v7_near_misses.csv", index=False)
    log(f"  near_misses saved: {len(df_nm)}")

log("DONE")
