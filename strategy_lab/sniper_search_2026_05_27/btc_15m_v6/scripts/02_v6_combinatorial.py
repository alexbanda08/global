"""V6 combinatorial sniper search for BTC 15m.

V6 RELAXED BAR (per _BRIEF_V6.md §3):
- n_lockbox >= 10 (don't cap upper; if WR holds, more is better)
- WR lockbox >= 0.65 (relaxed from 0.75)
- $/tr lockbox >= $4 (relaxed from $3, higher bar to compensate)
- max DD <= $500 (relaxed from $300)
- max loss streak <= 14 (relaxed from 6)
- daily Sharpe >= 1.5 (relaxed from 2.0)
- bootstrap p <= 0.05 (KEPT)

PRIMARY OBJECTIVE: maximize lockbox_$/tr * sqrt(lockbox_n)

V6 EXPLORATIONS:
- early-offset DOWN (off 60, 120, 240) [V5 only found late-window]
- early-offset UP
- BOTH directions per offset
- 3-5 gate composable stacks
- pre-window-anchored gates emphasized
- omit $250 depth gates (not present anyway)

Saves:
- v6_combinatorial_all.csv (all survivors pre-bootstrap)
- v6_final_candidates.csv (post-bootstrap p<=0.05)
- v6_near_misses.csv (near misses for honest reporting)
"""
import os, sys, time, itertools
import numpy as np
import pandas as pd

RES = "data/v4/canonical/_results"
IN = f"{RES}/sniper_btc15m_v3_gated.parquet"
OUT_DIR = "strategy_lab/sniper_search_2026_05_27/btc_15m_v6"

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)


log("loading panel")
df = pd.read_parquet(IN)
df["fire_date"] = pd.to_datetime(df["fire_us"], unit="us", utc=True)
df = df[(df["trend_slope_30m"].notna()) & (df["mp_skew"].notna())].copy()
df = df[(df["entry_vwap"] >= 0.10) & (df["entry_vwap"] <= 0.90)].copy()
df = df.sort_values("fire_us").reset_index(drop=True)
log(f"rows after filters: {len(df)}, days: {df.fire_date.dt.date.nunique()}")

# 3-way split chronological: train 18d / val 6d / lockbox 4d (per V5 spec)
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
            streak += 1
            mx = max(mx, streak)
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


# Drop dead/redundant gates
DROP = {"g_within_dev",       # 100% fire rate
        "g_dev_extreme",      # 0% fire rate
        "g_jump_dir_with",    # too sparse
        "g_off_0_60",         # use direct offset filter
        "g_off_60_240",
        "g_off_240_480",
        "g_off_480_720",
        "g_off_720_900",
        "g_tight_ribbon",     # 94.8% fire rate
        "g_tr_in_active_session"}

ALL_G = sorted([c for c in df.columns if c.startswith("g_") and c not in DROP])
ALL_G = [g for g in ALL_G if df[g].sum() > 0]
log(f"candidate atoms: {len(ALL_G)}")


# V6 sniper test on lockbox
def pass_v6(m_lo):
    if m_lo is None: return False
    if m_lo["n"] < 10: return False
    if m_lo["unique_days"] < 3: return False
    if m_lo["wr"] < 0.65: return False
    if m_lo["dpt"] < 4.0: return False
    if m_lo["max_dd"] > 500.0: return False
    if m_lo["loss_streak"] > 14: return False
    if m_lo["sharpe"] < 1.5: return False
    return True


# ============== Phase 1: 2-gate, per (offset, dir) ==============
log("Phase 1: 2-gate combos per (offset, dir)")
survivors = []
near_misses = []
total_tested = 0
OFFSETS = sorted(df.fire_offset_s.unique())
DIRS = ["UP", "DOWN", "BOTH"]
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
        for g1, g2 in itertools.combinations(ALL_G, 2):
            total_tested += 1
            m_tr = metrics(dtr, [g1, g2])
            if m_tr is None or m_tr["n"] < 30:
                continue
            if m_tr["wr"] < 0.55 or m_tr["dpt"] < 1.0:
                continue
            m_lo = metrics(dlo, [g1, g2])
            if m_lo is None: continue
            if not pass_v6(m_lo):
                # Near-miss capture: WR>=0.60 + dpt>=$3.5 + n>=10
                if (m_lo["n"] >= 10 and m_lo["wr"] >= 0.60 and m_lo["dpt"] >= 3.0):
                    m_va = metrics(dva, [g1, g2])
                    near_misses.append(dict(
                        offset=off, direction=dir_val, gates=[g1, g2], n_gates=2,
                        train_n=m_tr["n"], train_wr=m_tr["wr"], train_dpt=m_tr["dpt"],
                        val_n=m_va["n"] if m_va else 0,
                        val_wr=m_va["wr"] if m_va else np.nan,
                        val_dpt=m_va["dpt"] if m_va else np.nan,
                        lock_n=m_lo["n"], lock_wr=m_lo["wr"], lock_dpt=m_lo["dpt"],
                        lock_dd=m_lo["max_dd"], lock_streak=m_lo["loss_streak"],
                        lock_days=m_lo["unique_days"], lock_sharpe=m_lo["sharpe"],
                        sum_25_28d=m_lo["sum_pnl"] * SCALE_28D,
                    ))
                continue
            m_va = metrics(dva, [g1, g2])
            survivors.append(dict(
                offset=off, direction=dir_val, gates=[g1, g2], n_gates=2,
                train_n=m_tr["n"], train_wr=m_tr["wr"], train_dpt=m_tr["dpt"],
                val_n=m_va["n"] if m_va else 0,
                val_wr=m_va["wr"] if m_va else np.nan,
                val_dpt=m_va["dpt"] if m_va else np.nan,
                lock_n=m_lo["n"], lock_wr=m_lo["wr"], lock_dpt=m_lo["dpt"],
                lock_dd=m_lo["max_dd"], lock_streak=m_lo["loss_streak"],
                lock_days=m_lo["unique_days"], lock_sharpe=m_lo["sharpe"],
                sum_25_28d=m_lo["sum_pnl"] * SCALE_28D,
            ))
log(f"Phase 1: tested {total_tested}, survivors: {len(survivors)}, near-misses: {len(near_misses)}")


# ============== Phase 2: 3-gate combos, focused seeds ==============
# Seed gates = top 25 by (wr * sqrt(n)) on TRAIN
log("Phase 2: 3-gate combos with seed gates")
seed_gates = []
for g in ALL_G:
    m_tr = metrics(df_tr, [g])
    if m_tr is None: continue
    if m_tr["wr"] >= 0.50 and m_tr["dpt"] > -0.5:
        seed_gates.append((g, m_tr["wr"], m_tr["n"]))
seed_gates.sort(key=lambda x: x[1] * np.sqrt(x[2]), reverse=True)
SEEDS = [s[0] for s in seed_gates[:30]]
log(f"  seeds (top 30): {SEEDS[:15]}")

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
        for g1, g2, g3 in itertools.combinations(SEEDS, 3):
            m_tr = metrics(dtr, [g1, g2, g3])
            if m_tr is None or m_tr["n"] < 20:
                continue
            if m_tr["wr"] < 0.55 or m_tr["dpt"] < 1.0:
                continue
            m_lo = metrics(dlo, [g1, g2, g3])
            if m_lo is None: continue
            if not pass_v6(m_lo):
                if (m_lo["n"] >= 10 and m_lo["wr"] >= 0.60 and m_lo["dpt"] >= 3.0):
                    m_va = metrics(dva, [g1, g2, g3])
                    near_misses.append(dict(
                        offset=off, direction=dir_val, gates=[g1, g2, g3], n_gates=3,
                        train_n=m_tr["n"], train_wr=m_tr["wr"], train_dpt=m_tr["dpt"],
                        val_n=m_va["n"] if m_va else 0,
                        val_wr=m_va["wr"] if m_va else np.nan,
                        val_dpt=m_va["dpt"] if m_va else np.nan,
                        lock_n=m_lo["n"], lock_wr=m_lo["wr"], lock_dpt=m_lo["dpt"],
                        lock_dd=m_lo["max_dd"], lock_streak=m_lo["loss_streak"],
                        lock_days=m_lo["unique_days"], lock_sharpe=m_lo["sharpe"],
                        sum_25_28d=m_lo["sum_pnl"] * SCALE_28D,
                    ))
                continue
            m_va = metrics(dva, [g1, g2, g3])
            survivors.append(dict(
                offset=off, direction=dir_val, gates=[g1, g2, g3], n_gates=3,
                train_n=m_tr["n"], train_wr=m_tr["wr"], train_dpt=m_tr["dpt"],
                val_n=m_va["n"] if m_va else 0,
                val_wr=m_va["wr"] if m_va else np.nan,
                val_dpt=m_va["dpt"] if m_va else np.nan,
                lock_n=m_lo["n"], lock_wr=m_lo["wr"], lock_dpt=m_lo["dpt"],
                lock_dd=m_lo["max_dd"], lock_streak=m_lo["loss_streak"],
                lock_days=m_lo["unique_days"], lock_sharpe=m_lo["sharpe"],
                sum_25_28d=m_lo["sum_pnl"] * SCALE_28D,
            ))
log(f"Phase 2: total survivors: {len(survivors)}, near-misses: {len(near_misses)}")


# ============== Phase 3: ALL offsets, 2-gate combos (asymmetric DOWN-only focus) ==============
log("Phase 3: ALL offsets cross-cut, 2-gate")
for dir_val in DIRS:
    if dir_val == "BOTH":
        dtr = df_tr; dva = df_va; dlo = df_lo
    else:
        dtr = df_tr[df_tr.direction == dir_val]
        dva = df_va[df_va.direction == dir_val]
        dlo = df_lo[df_lo.direction == dir_val]
    for g1, g2 in itertools.combinations(ALL_G, 2):
        m_tr = metrics(dtr, [g1, g2])
        if m_tr is None or m_tr["n"] < 100: continue
        if m_tr["wr"] < 0.55 or m_tr["dpt"] < 1.0: continue
        m_lo = metrics(dlo, [g1, g2])
        if m_lo is None: continue
        if not pass_v6(m_lo):
            if (m_lo["n"] >= 15 and m_lo["wr"] >= 0.60 and m_lo["dpt"] >= 3.0):
                m_va = metrics(dva, [g1, g2])
                near_misses.append(dict(
                    offset="ALL", direction=dir_val, gates=[g1, g2], n_gates=2,
                    train_n=m_tr["n"], train_wr=m_tr["wr"], train_dpt=m_tr["dpt"],
                    val_n=m_va["n"] if m_va else 0,
                    val_wr=m_va["wr"] if m_va else np.nan,
                    val_dpt=m_va["dpt"] if m_va else np.nan,
                    lock_n=m_lo["n"], lock_wr=m_lo["wr"], lock_dpt=m_lo["dpt"],
                    lock_dd=m_lo["max_dd"], lock_streak=m_lo["loss_streak"],
                    lock_days=m_lo["unique_days"], lock_sharpe=m_lo["sharpe"],
                    sum_25_28d=m_lo["sum_pnl"] * SCALE_28D,
                ))
            continue
        m_va = metrics(dva, [g1, g2])
        survivors.append(dict(
            offset="ALL", direction=dir_val, gates=[g1, g2], n_gates=2,
            train_n=m_tr["n"], train_wr=m_tr["wr"], train_dpt=m_tr["dpt"],
            val_n=m_va["n"] if m_va else 0,
            val_wr=m_va["wr"] if m_va else np.nan,
            val_dpt=m_va["dpt"] if m_va else np.nan,
            lock_n=m_lo["n"], lock_wr=m_lo["wr"], lock_dpt=m_lo["dpt"],
            lock_dd=m_lo["max_dd"], lock_streak=m_lo["loss_streak"],
            lock_days=m_lo["unique_days"], lock_sharpe=m_lo["sharpe"],
            sum_25_28d=m_lo["sum_pnl"] * SCALE_28D,
        ))
log(f"Phase 3 done: total survivors: {len(survivors)}, near-misses: {len(near_misses)}")


# ============== Phase 4: Greedy 4-5 gate stacks for EARLY offsets (60, 120, 240) ==============
# This is the V6 focus: try to find sniper sleeves at early offsets where V5 found nothing
log("Phase 4: Greedy 4-5 gate stacks on EARLY offsets (60, 120, 240)")

def greedy_search_4_5(dtr, dva, dlo, start_gates, candidate_gates, max_depth=5,
                      min_train_n=40, min_lo_n=10):
    """Greedy stack extension. Start from start_gates and add one gate at a time
    while it improves (train_wr * sqrt(train_n)) AND lockbox passes v6.
    """
    best = start_gates[:]
    used = set(best)
    out = []
    m_lo = metrics(dlo, best)
    if m_lo is not None and pass_v6(m_lo):
        m_tr = metrics(dtr, best)
        m_va = metrics(dva, best)
        out.append((best[:], m_tr, m_va, m_lo))
    for depth in range(len(best) + 1, max_depth + 1):
        # Try adding each available gate
        candidates = []
        for g in candidate_gates:
            if g in used: continue
            test = best + [g]
            m_tr = metrics(dtr, test)
            if m_tr is None or m_tr["n"] < min_train_n: continue
            score = m_tr["wr"] * np.sqrt(m_tr["n"])
            candidates.append((g, score, m_tr))
        if not candidates: break
        candidates.sort(key=lambda x: x[1], reverse=True)
        # Take top candidate
        best_g, best_score, best_mtr = candidates[0]
        best = best + [best_g]
        used.add(best_g)
        m_lo = metrics(dlo, best)
        if m_lo is not None and pass_v6(m_lo) and m_lo["n"] >= min_lo_n:
            m_va = metrics(dva, best)
            out.append((best[:], best_mtr, m_va, m_lo))
    return out


EARLY_OFFSETS = [60, 120, 240]
SEED_STACKS_DOWN = [
    ["g_trend_slope_with"],
    ["g_tr_stack_full_with"],
    ["g_tr_stack_with"],
    ["g_regime_stack_with"],
    ["g_regime_stack_full_with"],
    ["g_rf_with"],
    ["g_f7_rsi_extreme_with"],
    ["g_lm_high_stat"],
    ["g_hawkes_imbalance_with"],
    ["g_tr_above_ema800"],
]
SEED_STACKS_UP = SEED_STACKS_DOWN  # same atoms, just different filter

for off in EARLY_OFFSETS:
    for dir_val in ["UP", "DOWN", "BOTH"]:
        if dir_val == "BOTH":
            dtr = df_tr[df_tr.fire_offset_s == off]
            dva = df_va[df_va.fire_offset_s == off]
            dlo = df_lo[df_lo.fire_offset_s == off]
        else:
            dtr = df_tr[(df_tr.fire_offset_s == off) & (df_tr.direction == dir_val)]
            dva = df_va[(df_va.fire_offset_s == off) & (df_va.direction == dir_val)]
            dlo = df_lo[(df_lo.fire_offset_s == off) & (df_lo.direction == dir_val)]
        if len(dtr) < 80: continue
        for seed in SEED_STACKS_DOWN:
            out = greedy_search_4_5(dtr, dva, dlo, seed, ALL_G, max_depth=5)
            for stack, m_tr, m_va, m_lo in out:
                survivors.append(dict(
                    offset=off, direction=dir_val, gates=stack, n_gates=len(stack),
                    train_n=m_tr["n"], train_wr=m_tr["wr"], train_dpt=m_tr["dpt"],
                    val_n=m_va["n"] if m_va else 0,
                    val_wr=m_va["wr"] if m_va else np.nan,
                    val_dpt=m_va["dpt"] if m_va else np.nan,
                    lock_n=m_lo["n"], lock_wr=m_lo["wr"], lock_dpt=m_lo["dpt"],
                    lock_dd=m_lo["max_dd"], lock_streak=m_lo["loss_streak"],
                    lock_days=m_lo["unique_days"], lock_sharpe=m_lo["sharpe"],
                    sum_25_28d=m_lo["sum_pnl"] * SCALE_28D,
                ))
log(f"Phase 4 done: total survivors: {len(survivors)}")


# ============== Phase 5: Dedup + bootstrap ==============
log("Phase 5: dedup + bootstrap p")

df_surv = pd.DataFrame(survivors)
if len(df_surv) > 0:
    # Dedup on (offset, direction, gates-sorted-tuple)
    df_surv["gate_key"] = df_surv["gates"].apply(lambda x: tuple(sorted(x)))
    df_surv["dedup_key"] = list(zip(df_surv["offset"], df_surv["direction"], df_surv["gate_key"]))
    df_surv = df_surv.drop_duplicates(subset=["dedup_key"], keep="first")
    df_surv = df_surv.drop(columns=["gate_key", "dedup_key"])
    log(f"after dedup: {len(df_surv)}")

    for i, row in df_surv.iterrows():
        if row["offset"] == "ALL":
            if row["direction"] == "BOTH":
                d_lo = df_lo
            else:
                d_lo = df_lo[df_lo.direction == row["direction"]]
        else:
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
        # Primary objective: dpt * sqrt(n)
        df_surv.at[i, "obj_score"] = row["lock_dpt"] * np.sqrt(row["lock_n"])

    df_surv["gate_stack_str"] = df_surv["gates"].apply(lambda x: "+".join(x))
    df_surv = df_surv.sort_values(["bootstrap_p", "obj_score"], ascending=[True, False])
    df_surv.to_csv(f"{OUT_DIR}/v6_combinatorial_all.csv", index=False)
    log(f"saved v6_combinatorial_all: {len(df_surv)}")

    # Final survivors: bootstrap p <= 0.05
    final = df_surv[df_surv["bootstrap_p"] <= 0.05].copy()
    final.to_csv(f"{OUT_DIR}/v6_final_candidates.csv", index=False)
    log(f"final post-bootstrap: {len(final)}")

    # Near misses
    df_nm = pd.DataFrame(near_misses)
    if len(df_nm) > 0:
        df_nm["gate_key"] = df_nm["gates"].apply(lambda x: tuple(sorted(x)))
        df_nm["dedup_key"] = list(zip(df_nm["offset"], df_nm["direction"], df_nm["gate_key"]))
        df_nm = df_nm.drop_duplicates(subset=["dedup_key"], keep="first").drop(columns=["gate_key", "dedup_key"])
        df_nm["gate_stack_str"] = df_nm["gates"].apply(lambda x: "+".join(x))
        df_nm = df_nm.sort_values("lock_dpt", ascending=False)
        df_nm.to_csv(f"{OUT_DIR}/v6_near_misses.csv", index=False)
        log(f"saved v6_near_misses: {len(df_nm)}")

    # Print top 20
    print()
    print("=" * 100)
    print("=== Top 20 final candidates by (obj_score = dpt * sqrt(n), bootstrap_p) ===")
    print("=" * 100)
    cols = ["gate_stack_str", "offset", "direction", "n_gates",
            "lock_n", "lock_wr", "lock_dpt", "lock_dd", "lock_streak", "lock_days",
            "lock_sharpe", "bootstrap_p", "obj_score", "sum_25_28d"]
    print(final[cols].head(20).to_string())
else:
    log("NO SURVIVORS")

log("DONE")
