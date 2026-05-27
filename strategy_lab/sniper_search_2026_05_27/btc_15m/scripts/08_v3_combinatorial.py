"""V3 combinatorial sniper search for BTC 15m.

Exhaustive 2- and 3-gate combinatorial across a curated subset of gates.
Per-offset, per-direction.

Saves only combos that pass sniper on lockbox.
"""
import os, sys, time, itertools
import numpy as np
import pandas as pd

RES = "data/v4/canonical/_results"
IN = f"{RES}/sniper_btc15m_v3_gated.parquet"
OUT_DIR = "strategy_lab/sniper_search_2026_05_27/btc_15m"

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)


log("loading panel")
df = pd.read_parquet(IN)
df["fire_date"] = pd.to_datetime(df["fire_us"], unit="us", utc=True)
df = df[(df["trend_slope_30m"].notna()) & (df["mp_skew"].notna())].copy()
df = df[(df["entry_vwap"] >= 0.10) & (df["entry_vwap"] <= 0.90)].copy()
df = df.sort_values("fire_us").reset_index(drop=True)
log(f"rows: {len(df)}, days: {df.fire_date.dt.date.nunique()}")

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

LO_DAYS = (LOCK_END - VAL_END).days
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


# Curated atoms for combinatorial
# Drop dead/redundant
DROP = {"g_within_dev", "g_dev_extreme", "g_regime_trending", "g_regime_breakout",
        "g_regime_compressing", "g_tight_ribbon", "g_tr_in_active_session"}

ALL_G = sorted([c for c in df.columns if c.startswith("g_") and c not in DROP])
ALL_G = [g for g in ALL_G if df[g].sum() > 0]
log(f"candidate atoms: {len(ALL_G)}")


# Phase 1: per-offset, per-direction, 2-gate combos
log("Phase 1: 2-gate combos per (offset, dir)")
survivors = []
total_tested = 0
for off in sorted(df.fire_offset_s.unique()):
    for dir_val in ["UP", "DOWN", "BOTH"]:
        if dir_val == "BOTH":
            dtr = df_tr[df_tr.fire_offset_s == off]
            dva = df_va[df_va.fire_offset_s == off]
            dlo = df_lo[df_lo.fire_offset_s == off]
        else:
            dtr = df_tr[(df_tr.fire_offset_s == off) & (df_tr.direction == dir_val)]
            dva = df_va[(df_va.fire_offset_s == off) & (df_va.direction == dir_val)]
            dlo = df_lo[(df_lo.fire_offset_s == off) & (df_lo.direction == dir_val)]
        if len(dtr) < 100:
            continue
        for g1, g2 in itertools.combinations(ALL_G, 2):
            total_tested += 1
            m_tr = metrics(dtr, [g1, g2])
            if m_tr is None or m_tr["n"] < 50:
                continue
            # Cheap pre-filter on train
            if m_tr["wr"] < 0.60 or m_tr["dpt"] < 1.5:
                continue
            m_lo = metrics(dlo, [g1, g2])
            if m_lo is None: continue
            # Sniper check
            if m_lo["n"] < 10 or m_lo["n"] > 65: continue
            if m_lo["unique_days"] < 4: continue
            if m_lo["wr"] < 0.75: continue
            if m_lo["dpt"] < 3.0: continue
            if m_lo["max_dd"] > 300.0: continue
            if m_lo["loss_streak"] > 6: continue
            if m_lo["sharpe"] < 2.0: continue
            m_va = metrics(dva, [g1, g2])
            survivors.append(dict(
                offset=off, direction=dir_val, gates=[g1, g2],
                train_n=m_tr["n"], train_wr=m_tr["wr"], train_dpt=m_tr["dpt"],
                val_n=m_va["n"] if m_va else 0,
                val_wr=m_va["wr"] if m_va else np.nan,
                val_dpt=m_va["dpt"] if m_va else np.nan,
                lock_n=m_lo["n"], lock_wr=m_lo["wr"], lock_dpt=m_lo["dpt"],
                lock_dd=m_lo["max_dd"], lock_streak=m_lo["loss_streak"],
                lock_days=m_lo["unique_days"], lock_sharpe=m_lo["sharpe"],
                sum_25_28d=m_lo["sum_pnl"] * SCALE_28D,
            ))
log(f"Phase 1: tested {total_tested}, survivors (pre-bootstrap): {len(survivors)}")


# Phase 2: 3-gate combos per (offset, dir) — only if we have <5 survivors
if len(survivors) < 50:
    log("Phase 2: 3-gate combos (sample with strong train_wr seeds)")
    # Seed gates that show >=55% WR alone on train
    seed_gates = []
    for g in ALL_G:
        m_tr = metrics(df_tr, [g])
        if m_tr is None: continue
        if m_tr["wr"] >= 0.51 and m_tr["dpt"] > 0:
            seed_gates.append((g, m_tr["wr"], m_tr["n"]))
    # Take top 25 by (wr * sqrt(n))
    seed_gates.sort(key=lambda x: x[1] * np.sqrt(x[2]), reverse=True)
    SEEDS = [s[0] for s in seed_gates[:25]]
    log(f"  seeds: {SEEDS[:10]}...")
    for off in sorted(df.fire_offset_s.unique()):
        for dir_val in ["UP", "DOWN", "BOTH"]:
            if dir_val == "BOTH":
                dtr = df_tr[df_tr.fire_offset_s == off]
                dva = df_va[df_va.fire_offset_s == off]
                dlo = df_lo[df_lo.fire_offset_s == off]
            else:
                dtr = df_tr[(df_tr.fire_offset_s == off) & (df_tr.direction == dir_val)]
                dva = df_va[(df_va.fire_offset_s == off) & (df_va.direction == dir_val)]
                dlo = df_lo[(df_lo.fire_offset_s == off) & (df_lo.direction == dir_val)]
            if len(dtr) < 100: continue
            for g1, g2, g3 in itertools.combinations(SEEDS, 3):
                m_tr = metrics(dtr, [g1, g2, g3])
                if m_tr is None or m_tr["n"] < 30:
                    continue
                if m_tr["wr"] < 0.60 or m_tr["dpt"] < 1.5:
                    continue
                m_lo = metrics(dlo, [g1, g2, g3])
                if m_lo is None: continue
                if m_lo["n"] < 10 or m_lo["n"] > 65: continue
                if m_lo["unique_days"] < 4: continue
                if m_lo["wr"] < 0.75: continue
                if m_lo["dpt"] < 3.0: continue
                if m_lo["max_dd"] > 300.0: continue
                if m_lo["loss_streak"] > 6: continue
                if m_lo["sharpe"] < 2.0: continue
                m_va = metrics(dva, [g1, g2, g3])
                survivors.append(dict(
                    offset=off, direction=dir_val, gates=[g1, g2, g3],
                    train_n=m_tr["n"], train_wr=m_tr["wr"], train_dpt=m_tr["dpt"],
                    val_n=m_va["n"] if m_va else 0,
                    val_wr=m_va["wr"] if m_va else np.nan,
                    val_dpt=m_va["dpt"] if m_va else np.nan,
                    lock_n=m_lo["n"], lock_wr=m_lo["wr"], lock_dpt=m_lo["dpt"],
                    lock_dd=m_lo["max_dd"], lock_streak=m_lo["loss_streak"],
                    lock_days=m_lo["unique_days"], lock_sharpe=m_lo["sharpe"],
                    sum_25_28d=m_lo["sum_pnl"] * SCALE_28D,
                ))
log(f"after Phase 2: survivors (pre-bootstrap): {len(survivors)}")


# Phase 3: ALL offsets, 2-3 gate combos
log("Phase 3: ALL offsets, 2-3 gate combos")
for dir_val in ["UP", "DOWN", "BOTH"]:
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
        if m_lo["n"] < 10 or m_lo["n"] > 65: continue
        if m_lo["unique_days"] < 4: continue
        if m_lo["wr"] < 0.75: continue
        if m_lo["dpt"] < 3.0: continue
        if m_lo["max_dd"] > 300.0: continue
        if m_lo["loss_streak"] > 6: continue
        if m_lo["sharpe"] < 2.0: continue
        m_va = metrics(dva, [g1, g2])
        survivors.append(dict(
            offset="ALL", direction=dir_val, gates=[g1, g2],
            train_n=m_tr["n"], train_wr=m_tr["wr"], train_dpt=m_tr["dpt"],
            val_n=m_va["n"] if m_va else 0,
            val_wr=m_va["wr"] if m_va else np.nan,
            val_dpt=m_va["dpt"] if m_va else np.nan,
            lock_n=m_lo["n"], lock_wr=m_lo["wr"], lock_dpt=m_lo["dpt"],
            lock_dd=m_lo["max_dd"], lock_streak=m_lo["loss_streak"],
            lock_days=m_lo["unique_days"], lock_sharpe=m_lo["sharpe"],
            sum_25_28d=m_lo["sum_pnl"] * SCALE_28D,
        ))
log(f"after Phase 3: total survivors: {len(survivors)}")


# Phase 4: Bootstrap p
log("Phase 4: bootstrap p")
df_surv = pd.DataFrame(survivors)
if len(df_surv) == 0:
    log("NO SURVIVORS — nothing to bootstrap")
else:
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
    df_surv["gate_stack_str"] = df_surv["gates"].apply(lambda x: "+".join(x))
    df_surv = df_surv.sort_values(["bootstrap_p", "lock_sharpe"], ascending=[True, False])
    df_surv.to_csv(f"{OUT_DIR}/v3_combinatorial_all.csv", index=False)
    log(f"saved {len(df_surv)} survivors")
    print()
    print("=== Top 20 by bootstrap p ===")
    cols = ["gate_stack_str", "offset", "direction", "train_n", "train_wr", "val_n", "val_wr",
            "lock_n", "lock_wr", "lock_dpt", "lock_dd", "lock_streak", "lock_days",
            "lock_sharpe", "bootstrap_p", "sum_25_28d"]
    print(df_surv[cols].head(20).to_string())

    # Final: bootstrap p <= 0.05
    final = df_surv[df_surv["bootstrap_p"] <= 0.05].copy()
    log(f"final after bootstrap p<=0.05: {len(final)}")
    final.to_csv(f"{OUT_DIR}/v3_final_candidates.csv", index=False)
log("DONE")
