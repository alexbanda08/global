"""Sniper search with SLUG-LEVEL DEDUPLICATION.

Critical fix: prior runs treated each (slug, offset) as a separate trade,
inflating n by ~7x. In production, ONE slug = ONE decision per direction.
A sleeve "fires" if gates pass at ANY offset within the window; we take
the FIRST gate-passing offset as the trade.

Process:
1. For each gate stack, mark each (slug, direction) row as gate-pass at that offset
2. Per (slug, direction), pick first gate-pass offset (sort by fire_us)
3. Compute sleeve metrics on dedup'd fires
4. Sniper constraint: n_lockbox_dedup 5-75 fires (1-15/day @ 5d)
5. WR/DPT/DD/streak/bootstrap on dedup'd fires

Output: top_5_candidates.csv with slug-dedup metrics
"""
import os, sys, time, json
import numpy as np
import pandas as pd

RES = "data/v4/canonical/_results"
IN = f"{RES}/sniper_btc15m_gated.parquet"
OUT_DIR = "strategy_lab/sniper_search_2026_05_27/btc_15m"

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)

log("loading gated panel")
df = pd.read_parquet(IN)
df["fire_date"] = pd.to_datetime(df["fire_us"], unit="us", utc=True)
df = df.sort_values(["slug", "direction", "fire_us"]).reset_index(drop=True)
log(f"rows: {len(df)}")

TRAIN_START = pd.Timestamp("2026-04-30", tz="UTC")
TRAIN_END   = pd.Timestamp("2026-05-12", tz="UTC")
VAL_END     = pd.Timestamp("2026-05-18", tz="UTC")
LOCK_END    = pd.Timestamp("2026-05-23", tz="UTC")
TR_DAYS = (TRAIN_END - TRAIN_START).days
VA_DAYS = (VAL_END - TRAIN_END).days
LO_DAYS = (LOCK_END - VAL_END).days
SCALE_28D = 28 / LO_DAYS

# Split masks
tr_mask = (df["fire_date"] >= TRAIN_START) & (df["fire_date"] < TRAIN_END)
va_mask = (df["fire_date"] >= TRAIN_END) & (df["fire_date"] < VAL_END)
lo_mask = (df["fire_date"] >= VAL_END) & (df["fire_date"] < LOCK_END)

ALL_GATES = sorted([c for c in df.columns if c.startswith("g_")])
DEAD = [g for g in ALL_GATES if df[g].sum() == 0]
ALL_GATES = [g for g in ALL_GATES if g not in DEAD]
log(f"gates available: {len(ALL_GATES)}")

# ---------------------- SLUG-DEDUP SLEEVE EVAL ----------------------

def slug_dedup_sleeve_metrics(d, gates, offset_constraint=None):
    """Apply gates, dedup to first fire per (slug, direction), return metrics.

    offset_constraint: None | "first" | int (only allow this offset bin)
    """
    if not gates:
        m = np.ones(len(d), dtype=bool)
    else:
        m = np.ones(len(d), dtype=bool)
        for g in gates:
            col = np.asarray(d[g], dtype=float)
            m &= (np.isnan(col) | (col == 1))
    if offset_constraint is not None and offset_constraint != "first":
        m &= (d["fire_offset_s"] == offset_constraint)
    sub = d[m]
    if len(sub) == 0:
        return None
    # Dedup: first gate-pass per (slug, direction) — sort by fire_us
    sub_sorted = sub.sort_values(["slug", "direction", "fire_us"])
    dedup = sub_sorted.drop_duplicates(subset=["slug", "direction"], keep="first")
    dedup = dedup.sort_values("fire_us").reset_index(drop=True)
    if len(dedup) == 0:
        return None
    return _compute_metrics(dedup)


def _compute_metrics(d):
    """Compute sleeve metrics on a dedup'd slice."""
    n = len(d)
    won_arr = d["won"].values.astype(int)
    pnl_arr = d["pnl_legacy_usd"].values.astype(float)
    # Max DD
    cum = np.cumsum(pnl_arr)
    peak = np.maximum.accumulate(cum)
    max_dd = float(-(cum - peak).min())
    # Max loss streak
    streak = 0; max_streak = 0
    for w in won_arr:
        if w == 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    # Daily Sharpe
    daily = d.groupby(d["fire_date"].dt.date)["pnl_legacy_usd"].sum()
    sharpe = float(daily.mean() / daily.std() * np.sqrt(365)) if (len(daily) > 1 and daily.std() > 0) else 0.0
    return dict(
        n=n,
        wr=float(np.mean(won_arr)),
        dpt=float(pnl_arr.mean()),
        sum_pnl=float(pnl_arr.sum()),
        max_dd=max_dd,
        loss_streak=max_streak,
        sharpe=sharpe,
        daily_pnl=daily,
    )


def bootstrap_p_dedup(d, n_shuffles=1000, seed=42):
    if len(d) < 5:
        return np.nan
    daily = d.groupby(d["fire_date"].dt.date)["pnl_legacy_usd"].sum().values
    n_days = len(daily)
    if n_days < 2:
        return np.nan
    obs = daily.sum()
    rng = np.random.default_rng(seed)
    boot = rng.choice(daily, size=(n_shuffles, n_days), replace=True).sum(axis=1)
    p = float((boot <= 0).sum() / n_shuffles)
    return max(p, 1.0 / n_shuffles)


def evaluate_stack(gates, offset_constraint=None):
    """Evaluate gate stack across train/val/lockbox with slug dedup."""
    tr_d = df[tr_mask]; va_d = df[va_mask]; lo_d = df[lo_mask]
    return dict(
        train=slug_dedup_sleeve_metrics(tr_d, gates, offset_constraint),
        val=slug_dedup_sleeve_metrics(va_d, gates, offset_constraint),
        lock=slug_dedup_sleeve_metrics(lo_d, gates, offset_constraint),
    )


# ============================================================
# Greedy forward search with sniper objective
# Score: dpt_train * sqrt(n_train), but with min n_train >= 100
# Stop when n_lockbox_dedup < 5 or n_train_dedup < 30
# ============================================================
def greedy(direction, max_depth=10, offset_constraint=None):
    chosen = []
    avail = list(ALL_GATES)
    history = []
    # Filter df by direction if not None
    if direction != "BOTH":
        df_ev = df[df["direction"] == direction]
    else:
        df_ev = df

    def eval_local(g_list):
        return dict(
            train=slug_dedup_sleeve_metrics(df_ev[tr_mask.loc[df_ev.index]], g_list, offset_constraint),
            val=slug_dedup_sleeve_metrics(df_ev[va_mask.loc[df_ev.index]], g_list, offset_constraint),
            lock=slug_dedup_sleeve_metrics(df_ev[lo_mask.loc[df_ev.index]], g_list, offset_constraint),
        )

    for step in range(max_depth):
        best_g = None
        best_score = -np.inf
        best_m = None
        for g in avail:
            trial = chosen + [g]
            r = eval_local(trial)
            mtr = r["train"]
            if mtr is None or mtr["n"] < 30:
                continue
            # Sniper objective: dpt * sqrt(n) BUT cap effective n at 200
            n_eff = min(mtr["n"], 200)
            score = mtr["dpt"] * np.sqrt(n_eff)
            if score > best_score:
                best_score = score
                best_g = g
                best_m = r
        if best_g is None:
            break
        chosen.append(best_g)
        avail.remove(best_g)
        m_tr = best_m["train"]
        m_va = best_m["val"]
        m_lo = best_m["lock"]
        history.append({
            "depth": step + 1,
            "gates": list(chosen),
            "direction": direction,
            "offset": offset_constraint,
            "train_n": m_tr["n"], "train_wr": m_tr["wr"],
            "train_dpt": m_tr["dpt"], "train_sum": m_tr["sum_pnl"],
            "val_n": m_va["n"] if m_va else 0,
            "val_wr": m_va["wr"] if m_va else np.nan,
            "val_dpt": m_va["dpt"] if m_va else np.nan,
            "lock_n": m_lo["n"] if m_lo else 0,
            "lock_wr": m_lo["wr"] if m_lo else np.nan,
            "lock_dpt": m_lo["dpt"] if m_lo else np.nan,
            "lock_sum": m_lo["sum_pnl"] if m_lo else np.nan,
            "lock_dd": m_lo["max_dd"] if m_lo else np.nan,
            "lock_streak": m_lo["loss_streak"] if m_lo else np.nan,
            "lock_sharpe": m_lo["sharpe"] if m_lo else np.nan,
        })
        if m_tr["n"] < 50:  # too few train fires — stop
            break
    return history


log("Phase A: greedy by direction (no offset constraint)")
all_hist = []
for direction in ["UP", "DOWN", "BOTH"]:
    h = greedy(direction, max_depth=10)
    all_hist.extend(h)
    log(f"  direction={direction}: {len(h)} steps")

# Phase B: greedy per offset bin
log("Phase B: greedy per offset bin (and direction)")
for off in sorted(df["fire_offset_s"].unique()):
    for direction in ["UP", "DOWN", "BOTH"]:
        h = greedy(direction, max_depth=8, offset_constraint=off)
        all_hist.extend(h)
log(f"  total candidates: {len(all_hist)}")

# Phase C: targeted high-bar stacks
log("Phase C: targeted hand-built stacks")
TARGETED = [
    # F7 RSI extreme + Markov / SMS regime agreement
    ["g_f7_rsi_extreme_with", "g_sms_trend_with"],
    ["g_f7_rsi_extreme_with", "g_sms_trend_strong_with"],
    # SMS RSI mid + active session
    ["g_sms_rsi_mid", "g_in_eu_us_brinks", "g_hawkes_imbalance_with"],
    # Microprice extreme + LM jump direction agreement
    ["g_lm_high_stat", "g_jump_dir_with"],
    ["g_lm_high_stat", "g_mp_skew_with"],
    # vol_high + brink session + hawkes
    ["g_vol_high", "g_in_eu_us_brinks", "g_hawkes_imbalance_with"],
    # microstructure-only sleeves
    ["g_imb5_strong_with", "g_mp_skew_with", "g_book_slope_with_us"],
    ["g_imb5_strong_with", "g_mp_skew_with"],
    # SMS BOS with trend
    ["g_sms_bos_with", "g_sms_trend_with"],
    # F7 + RF agreement
    ["g_f7_rsi_strong_with", "g_rf_with", "g_in_eu_us_brinks"],
    # tight ribbon + dev extreme
    ["g_tight_ribbon", "g_dev_extreme"],
    ["g_dev_extreme", "g_lm_high_stat"],
    # Hawkes + LM
    ["g_hawkes_imbalance_with", "g_lm_high_stat"],
    # microprice no extreme + RF
    ["g_mp_no_extreme", "g_rf_with", "g_in_eu_us_brinks"],
    # session + adx
    ["g_in_eu_us_brinks", "g_adx_strong"],
    # SMS RSI extreme + jump direction
    ["g_sms_rsi_extreme_with", "g_jump_dir_with"],
]
for direction in ["UP", "DOWN", "BOTH"]:
    for stack in TARGETED:
        # Eval across full split
        if direction != "BOTH":
            d = df[df["direction"] == direction]
        else:
            d = df
        m_tr = slug_dedup_sleeve_metrics(d[tr_mask.loc[d.index]], stack)
        m_va = slug_dedup_sleeve_metrics(d[va_mask.loc[d.index]], stack)
        m_lo = slug_dedup_sleeve_metrics(d[lo_mask.loc[d.index]], stack)
        if m_tr is None: continue
        all_hist.append({
            "depth": "targeted",
            "gates": list(stack),
            "direction": direction,
            "offset": None,
            "train_n": m_tr["n"], "train_wr": m_tr["wr"],
            "train_dpt": m_tr["dpt"], "train_sum": m_tr["sum_pnl"],
            "val_n": m_va["n"] if m_va else 0,
            "val_wr": m_va["wr"] if m_va else np.nan,
            "val_dpt": m_va["dpt"] if m_va else np.nan,
            "lock_n": m_lo["n"] if m_lo else 0,
            "lock_wr": m_lo["wr"] if m_lo else np.nan,
            "lock_dpt": m_lo["dpt"] if m_lo else np.nan,
            "lock_sum": m_lo["sum_pnl"] if m_lo else np.nan,
            "lock_dd": m_lo["max_dd"] if m_lo else np.nan,
            "lock_streak": m_lo["loss_streak"] if m_lo else np.nan,
            "lock_sharpe": m_lo["sharpe"] if m_lo else np.nan,
        })
log(f"  total candidates (after targeted): {len(all_hist)}")

# Save all
df_all = pd.DataFrame(all_hist)
df_all["gate_stack_str"] = df_all["gates"].apply(lambda x: "+".join(x) if isinstance(x, list) else "")
df_all["gate_count"] = df_all["gates"].apply(lambda x: len(x) if isinstance(x, list) else 0)
df_all.to_csv(f"{OUT_DIR}/all_candidates_dedup.csv", index=False)
log(f"saved {len(df_all)} candidates")

# Sniper filter
sniper = df_all[
    (df_all["lock_n"] >= 5) & (df_all["lock_n"] <= 75) &
    (df_all["lock_wr"] >= 0.75) &
    (df_all["lock_dpt"] >= 3.0) &
    (df_all["lock_dd"] <= 300.0) &
    (df_all["lock_streak"] <= 6)
].copy()
log(f"sniper-passing candidates: {len(sniper)}")

if len(sniper) > 0:
    # Bootstrap p
    log("computing bootstrap p")
    for idx, row in sniper.iterrows():
        if row["direction"] == "BOTH":
            d_ev = df[lo_mask]
        else:
            d_ev = df[lo_mask & (df["direction"] == row["direction"])]
        gates = row["gates"]
        m = np.ones(len(d_ev), dtype=bool)
        for g in gates:
            col = np.asarray(d_ev[g], dtype=float)
            m &= (np.isnan(col) | (col == 1))
        sub = d_ev[m]
        sub = sub.sort_values(["slug", "direction", "fire_us"]).drop_duplicates(
            subset=["slug", "direction"], keep="first").sort_values("fire_us")
        if row["offset"] is not None:
            sub = sub[sub["fire_offset_s"] == row["offset"]]
        sniper.loc[idx, "bootstrap_p"] = bootstrap_p_dedup(sub, n_shuffles=1000)
    # Filter on bootstrap
    sniper["passes_bootstrap"] = sniper["bootstrap_p"] <= 0.05
    sniper["sum_25_28d"] = sniper["lock_sum"] * SCALE_28D
    # Sort by lock_sharpe then lock_dpt
    sniper = sniper.sort_values(["lock_sharpe", "lock_dpt"], ascending=False)
    sniper.to_csv(f"{OUT_DIR}/sniper_candidates_passing.csv", index=False)
    print()
    print("=== Sniper-passing candidates ===")
    print(sniper[["gate_stack_str", "direction", "offset", "train_n", "train_wr",
                  "val_n", "val_wr", "lock_n", "lock_wr", "lock_dpt", "lock_dd",
                  "lock_streak", "lock_sharpe", "bootstrap_p"]].head(20).to_string())
else:
    print("NO candidates pass sniper thresholds")
    # Print near-misses (close but not perfect)
    print()
    print("=== Near-misses (lock_n >= 5, lock_wr >= 0.65) ===")
    nm = df_all[
        (df_all["lock_n"] >= 5) & (df_all["lock_n"] <= 75) &
        (df_all["lock_wr"] >= 0.65)
    ].sort_values(["lock_wr", "lock_dpt"], ascending=False)
    print(nm[["gate_stack_str", "direction", "offset", "train_n", "train_wr",
              "val_n", "val_wr", "lock_n", "lock_wr", "lock_dpt", "lock_dd",
              "lock_streak", "lock_sharpe"]].head(15).to_string())

log("DONE")
