"""V3 sniper search for BTC 15m.

Uses sniper_btc15m_v3_gated.parquet (33d v3 fires with 84 gates).

Effective window: 28d (regime panel intersection: Apr 28 - May 25).
Split: train 18d / val 6d / lockbox 4d.

Sniper constraints applied on LOCKBOX:
- n in [10, 65] (n_cap 500 over 32d -> ~65 per 4d lockbox)
- min_unique_days >= 4 (rejects single-day winners)
- WR >= 0.75
- $/tr >= 3
- max DD <= 300
- max loss streak <= 6
- daily Sharpe >= 2
- bootstrap p <= 0.05

Plus baseline filter: entry_vwap in [0.10, 0.90] to kill lottery-ticket fat tails.

Search phases:
A) Per-offset single-gate baselines (warm start)
B) Per-offset + per-direction greedy combos (depth <= 8)
C) Cross-offset greedy combos
D) Pre-window anchor variants (use ws_s features only, fire-time offset bins)
E) Strict-stack combinatorics around the best families

Output: top_5_candidates.csv + SNIPER_BTC_15M_REPORT.md
"""
import os, sys, time, json
from collections import defaultdict
import numpy as np
import pandas as pd

RES = "data/v4/canonical/_results"
IN = f"{RES}/sniper_btc15m_v3_gated.parquet"
OUT_DIR = "strategy_lab/sniper_search_2026_05_27/btc_15m"

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)

log("loading gated panel")
df = pd.read_parquet(IN)
df["fire_date"] = pd.to_datetime(df["fire_us"], unit="us", utc=True)
df = df.sort_values("fire_us").reset_index(drop=True)
log(f"rows: {len(df)}, date {df.fire_date.min()} to {df.fire_date.max()}")

# Effective window (regime + microprice both present)
mask_eff = df["trend_slope_30m"].notna() & df["mp_skew"].notna()
df = df[mask_eff].copy().reset_index(drop=True)
log(f"after effective-window mask: {len(df)}, days = {df.fire_date.dt.date.nunique()}")

# Apply baseline vwap filter (kill lottery tickets)
df = df[(df["entry_vwap"] >= 0.10) & (df["entry_vwap"] <= 0.90)].copy().reset_index(drop=True)
log(f"after entry_vwap in [0.10, 0.90]: {len(df)}, days = {df.fire_date.dt.date.nunique()}")


# Date range available
DATE_MIN = df["fire_date"].dt.date.min()
DATE_MAX = df["fire_date"].dt.date.max()
log(f"effective date range: {DATE_MIN} to {DATE_MAX}")

# 3-way split: train 18 / val 6 / lockbox 4 on 28d effective
TRAIN_START = pd.Timestamp("2026-04-28", tz="UTC")
TRAIN_END   = pd.Timestamp("2026-05-16", tz="UTC")   # 18d
VAL_END     = pd.Timestamp("2026-05-22", tz="UTC")   # 6d
LOCK_END    = pd.Timestamp("2026-05-26", tz="UTC")   # 4d
TR_DAYS = (TRAIN_END - TRAIN_START).days
VA_DAYS = (VAL_END - TRAIN_END).days
LO_DAYS = (LOCK_END - VAL_END).days
log(f"split: train {TR_DAYS}d ({TRAIN_START.date()}-{TRAIN_END.date()}), "
    f"val {VA_DAYS}d ({TRAIN_END.date()}-{VAL_END.date()}), "
    f"lockbox {LO_DAYS}d ({VAL_END.date()}-{LOCK_END.date()})")

tr_mask = (df.fire_date >= TRAIN_START) & (df.fire_date < TRAIN_END)
va_mask = (df.fire_date >= TRAIN_END) & (df.fire_date < VAL_END)
lo_mask = (df.fire_date >= VAL_END) & (df.fire_date < LOCK_END)
df_tr = df[tr_mask].copy()
df_va = df[va_mask].copy()
df_lo = df[lo_mask].copy()
log(f"split sizes: train={len(df_tr)} val={len(df_va)} lockbox={len(df_lo)}")
log(f"lockbox unique days: {df_lo.fire_date.dt.date.nunique()}")

SCALE_28D = 28 / LO_DAYS


# Gate columns
ALL_GATES = sorted([c for c in df.columns if c.startswith("g_")])
# Drop dead gates
DEAD = [g for g in ALL_GATES if df[g].sum() == 0]
ALL_GATES = [g for g in ALL_GATES if g not in DEAD]
log(f"gates available: {len(ALL_GATES)} (dropped dead: {len(DEAD)})")


def gate_mask(d, gates):
    """Boolean mask: all gates ON."""
    if not gates:
        return np.ones(len(d), dtype=bool)
    arr = np.ones(len(d), dtype=bool)
    for g in gates:
        col = d[g].values
        arr &= (col == 1)
    return arr


def compute_dd(pnl_arr):
    if len(pnl_arr) == 0:
        return 0.0
    cum = np.cumsum(pnl_arr)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    return float(-dd.min())


def max_loss_streak(won_arr):
    if len(won_arr) == 0:
        return 0
    streak = mx = 0
    for w in won_arr:
        if w == 0:
            streak += 1
            mx = max(mx, streak)
        else:
            streak = 0
    return mx


def daily_sharpe(d):
    if len(d) == 0:
        return 0.0
    daily = d.groupby(d.fire_date.dt.date)["pnl_legacy_usd"].sum()
    if len(daily) < 2 or daily.std() == 0:
        return 0.0
    return float(daily.mean() / daily.std() * np.sqrt(365))


def bootstrap_p(d_lock, n_shuffles=1000, seed=42):
    """Daily-clustered bootstrap p (H0: mean daily PnL <= 0)."""
    if len(d_lock) < 5:
        return np.nan
    daily = d_lock.groupby(d_lock.fire_date.dt.date)["pnl_legacy_usd"].sum().values
    n_days = len(daily)
    if n_days < 2:
        return np.nan
    rng = np.random.default_rng(seed)
    boot = rng.choice(daily, size=(n_shuffles, n_days), replace=True).sum(axis=1)
    p = float((boot <= 0).sum() / n_shuffles)
    return max(p, 1.0 / n_shuffles)


def metrics(d_split, gates):
    m = gate_mask(d_split, gates)
    sub = d_split[m].copy()
    n = len(sub)
    if n == 0:
        return None
    sub = sub.sort_values("fire_us").reset_index(drop=True)
    won_arr = sub["won"].values.astype(int)
    pnl_arr = sub["pnl_legacy_usd"].values.astype(float)
    return dict(
        n=n,
        wr=float(np.mean(won_arr)),
        dpt=float(pnl_arr.mean()),
        sum_pnl=float(pnl_arr.sum()),
        max_dd=compute_dd(pnl_arr),
        loss_streak=max_loss_streak(won_arr),
        unique_days=int(sub.fire_date.dt.date.nunique()),
        sharpe=daily_sharpe(sub),
    )


def passes_sniper(m_lock, min_n=10, max_n=65, min_days=4, min_wr=0.75,
                  min_dpt=3.0, max_dd=300.0, max_streak=6, min_sharpe=2.0):
    """Check sniper thresholds on lockbox metrics."""
    if m_lock is None: return False
    if m_lock["n"] < min_n: return False
    if m_lock["n"] > max_n: return False
    if m_lock["unique_days"] < min_days: return False
    if m_lock["wr"] < min_wr: return False
    if m_lock["dpt"] < min_dpt: return False
    if m_lock["max_dd"] > max_dd: return False
    if m_lock["loss_streak"] > max_streak: return False
    if m_lock["sharpe"] < min_sharpe: return False
    return True


# ============================================================
# Phase A: Per-offset single-gate baselines
# ============================================================
log("Phase A: single-gate baselines per offset")
results = []
for off in sorted(df.fire_offset_s.unique()):
    d_tr_o = df_tr[df_tr.fire_offset_s == off]
    d_va_o = df_va[df_va.fire_offset_s == off]
    d_lo_o = df_lo[df_lo.fire_offset_s == off]
    for g_col in ALL_GATES:
        m_tr = metrics(d_tr_o, [g_col])
        if m_tr is None or m_tr["n"] < 30:
            continue
        m_va = metrics(d_va_o, [g_col])
        m_lo = metrics(d_lo_o, [g_col])
        if m_lo is None:
            continue
        results.append({
            "sleeve_id": f"offA_{off}_{g_col}",
            "offset": off, "direction": "BOTH", "gates": [g_col],
            "train_n": m_tr["n"], "train_wr": m_tr["wr"], "train_dpt": m_tr["dpt"],
            "val_n": m_va["n"] if m_va else 0, "val_wr": m_va["wr"] if m_va else np.nan,
            "lock_n": m_lo["n"], "lock_wr": m_lo["wr"], "lock_dpt": m_lo["dpt"],
            "lock_dd": m_lo["max_dd"], "lock_streak": m_lo["loss_streak"],
            "lock_days": m_lo["unique_days"], "lock_sharpe": m_lo["sharpe"],
        })
df_pA = pd.DataFrame(results)
log(f"Phase A results: {len(df_pA)}")


# ============================================================
# Phase B + C greedy
# ============================================================
def greedy_forward(d_train, d_val, d_lock, gates_avail, max_depth=8, min_n_train=50):
    """Greedy adds: pick gate maximizing dpt * sqrt(n) on TRAIN with monotonic constraint."""
    chosen = []
    candidates = list(gates_avail)
    history = []
    for step in range(max_depth):
        best_g = None
        best_score = -np.inf
        best_metrics = None
        for g in candidates:
            trial = chosen + [g]
            m_tr = metrics(d_train, trial)
            if m_tr is None or m_tr["n"] < min_n_train:
                continue
            # Reject if WR drops below 0.55 or train_dpt below 1.0
            if m_tr["wr"] < 0.55 or m_tr["dpt"] < 1.0:
                continue
            score = m_tr["dpt"] * np.sqrt(m_tr["n"])
            if score > best_score:
                best_score = score
                best_g = g
                best_metrics = m_tr
        if best_g is None:
            break
        chosen.append(best_g)
        candidates.remove(best_g)
        m_va = metrics(d_val, chosen)
        m_lo = metrics(d_lock, chosen)
        history.append({
            "depth": step + 1, "gates": list(chosen),
            "train_n": best_metrics["n"], "train_wr": best_metrics["wr"],
            "train_dpt": best_metrics["dpt"],
            "val_n": m_va["n"] if m_va else 0,
            "val_wr": m_va["wr"] if m_va else np.nan,
            "val_dpt": m_va["dpt"] if m_va else np.nan,
            "lock_n": m_lo["n"] if m_lo else 0,
            "lock_wr": m_lo["wr"] if m_lo else np.nan,
            "lock_dpt": m_lo["dpt"] if m_lo else np.nan,
            "lock_dd": m_lo["max_dd"] if m_lo else np.nan,
            "lock_streak": m_lo["loss_streak"] if m_lo else np.nan,
            "lock_days": m_lo["unique_days"] if m_lo else 0,
            "lock_sharpe": m_lo["sharpe"] if m_lo else 0,
        })
        if best_metrics["n"] < 80:
            break
    return history


log("Phase B: greedy per (offset, direction)")
phaseB = []
for off in sorted(df.fire_offset_s.unique()):
    d_tr_o = df_tr[df_tr.fire_offset_s == off]
    d_va_o = df_va[df_va.fire_offset_s == off]
    d_lo_o = df_lo[df_lo.fire_offset_s == off]
    if len(d_tr_o) < 100:
        continue
    for dir_val in ["UP", "DOWN"]:
        dtr = d_tr_o[d_tr_o.direction == dir_val]
        dva = d_va_o[d_va_o.direction == dir_val]
        dlo = d_lo_o[d_lo_o.direction == dir_val]
        if len(dtr) < 50:
            continue
        hist = greedy_forward(dtr, dva, dlo, ALL_GATES, max_depth=8)
        for h in hist:
            h["offset"] = off
            h["direction"] = dir_val
            phaseB.append(h)
df_pB = pd.DataFrame(phaseB)
log(f"Phase B candidates: {len(df_pB)}")


log("Phase C: greedy across all offsets, per direction")
phaseC = []
for dir_val in ["UP", "DOWN", "BOTH"]:
    if dir_val == "BOTH":
        dtr, dva, dlo = df_tr, df_va, df_lo
    else:
        dtr = df_tr[df_tr.direction == dir_val]
        dva = df_va[df_va.direction == dir_val]
        dlo = df_lo[df_lo.direction == dir_val]
    if len(dtr) < 50:
        continue
    hist = greedy_forward(dtr, dva, dlo, ALL_GATES, max_depth=8)
    for h in hist:
        h["offset"] = "ALL"
        h["direction"] = dir_val
        phaseC.append(h)
df_pC = pd.DataFrame(phaseC)
log(f"Phase C candidates: {len(df_pC)}")


# ============================================================
# Phase D: anchored "early-window contrarian / hawkes / mp_no_extreme" stacks
# Test the high-bar gate stacks per brief §7 Path C
# ============================================================
log("Phase D: high-bar stacks (deliberate sniper stacks)")
HIGH_BAR_STACKS = [
    # Per brief Path C examples
    ["g_dev_extreme", "g_lm_high_stat", "g_hawkes_imbalance_with", "g_tr_stack_full_with"],
    ["g_lm_extreme_stat", "g_hawkes_imb_strong_with", "g_tr_stack_with"],
    ["g_mp_skew_strong_with", "g_imb5_strong_with", "g_trend_slope_with"],
    ["g_mp_no_extreme", "g_trend_slope_with", "g_hawkes_imbalance_with"],
    ["g_mp_no_extreme", "g_trend_slope_with", "g_regime_trending_with"],
    ["g_mp_no_extreme", "g_trend_slope_strong_with", "g_hawkes_imbalance_with"],
    ["g_trend_slope_strong_with", "g_di_agrees", "g_adx_trending"],
    ["g_trend_slope_strong_with", "g_di_agrees", "g_hawkes_imbalance_with"],
    ["g_trend_slope_strong_with", "g_regime_trending_with"],
    ["g_trend_slope_strong_with", "g_regime_trending_with", "g_mp_no_extreme"],
    ["g_regime_trending_with", "g_mp_no_extreme"],
    ["g_regime_trending_with", "g_mp_no_extreme", "g_imb5_strong_with"],
    ["g_regime_trending_with", "g_hawkes_imb_strong_with"],
    ["g_trend_slope_with", "g_mp_no_extreme", "g_imb5_strong_with"],
    ["g_f7_rsi_extreme_with", "g_trend_slope_with"],
    ["g_f7_rsi_extreme_against", "g_mp_no_extreme"],  # mean-reversion
    ["g_f7_rsi_extreme_against", "g_lm_high_stat"],   # contrarian after jump
    ["g_lm_jump_against", "g_mp_no_extreme"],          # mean-reversion after jump
    ["g_sms_trend_strong_with", "g_mp_no_extreme", "g_trend_slope_with"],
    ["g_sms_trend_with", "g_sms_rsi_with", "g_sms_cvd_with"],
    ["g_hawkes_imb_strong_with", "g_mp_no_extreme", "g_vpin_calm"],
    ["g_hawkes_imb_strong_with", "g_mp_no_extreme", "g_trend_slope_with"],
    ["g_hawkes_imb_strong_with", "g_trend_slope_strong_with"],
    ["g_imb5_strong_with", "g_mp_skew_with"],
    ["g_imb5_strong_with", "g_mp_skew_with", "g_trend_slope_with"],
    ["g_tr_stack_full_with", "g_trend_slope_with", "g_mp_no_extreme"],
    ["g_tr_stack_full_with", "g_regime_trending_with"],
    ["g_vwap_premium", "g_trend_slope_with", "g_regime_trending_with"],
    ["g_vwap_25_75", "g_trend_slope_with"],
    ["g_vwap_25_75", "g_hawkes_imbalance_with", "g_mp_no_extreme"],
    # Adding direction-flipper for early offsets
    ["g_off_0_60", "g_hawkes_imbalance_with", "g_mp_no_extreme"],
    ["g_off_0_60", "g_trend_slope_strong_with"],
    ["g_off_0_60", "g_f7_rsi_extreme_with"],
    # Late-window stacks
    ["g_off_720_900", "g_trend_slope_strong_with", "g_mp_no_extreme"],
    ["g_off_720_900", "g_hawkes_imb_strong_with"],
]
phaseD = []
for stack in HIGH_BAR_STACKS:
    # Filter stacks that include gates not in panel
    if any(g not in ALL_GATES for g in stack):
        missing = [g for g in stack if g not in ALL_GATES]
        # print(f"  SKIP (missing {missing}): {stack}")
        continue
    for dir_val in ["UP", "DOWN", "BOTH"]:
        if dir_val == "BOTH":
            dtr, dva, dlo = df_tr, df_va, df_lo
        else:
            dtr = df_tr[df_tr.direction == dir_val]
            dva = df_va[df_va.direction == dir_val]
            dlo = df_lo[df_lo.direction == dir_val]
        m_tr = metrics(dtr, stack)
        m_va = metrics(dva, stack)
        m_lo = metrics(dlo, stack)
        if m_tr is None or m_tr["n"] < 30:
            continue
        if m_lo is None:
            continue
        phaseD.append({
            "depth": len(stack), "gates": stack, "offset": "ALL", "direction": dir_val,
            "train_n": m_tr["n"], "train_wr": m_tr["wr"], "train_dpt": m_tr["dpt"],
            "val_n": m_va["n"] if m_va else 0,
            "val_wr": m_va["wr"] if m_va else np.nan,
            "val_dpt": m_va["dpt"] if m_va else np.nan,
            "lock_n": m_lo["n"], "lock_wr": m_lo["wr"], "lock_dpt": m_lo["dpt"],
            "lock_dd": m_lo["max_dd"], "lock_streak": m_lo["loss_streak"],
            "lock_days": m_lo["unique_days"], "lock_sharpe": m_lo["sharpe"],
        })
df_pD = pd.DataFrame(phaseD)
log(f"Phase D candidates: {len(df_pD)}")


# ============================================================
# Combine all phases
# ============================================================
all_cands = []
# Phase A -> dict format normalize
for _, r in df_pA.iterrows():
    all_cands.append({
        "depth": 1, "gates": r["gates"], "offset": r["offset"], "direction": r["direction"],
        "train_n": r["train_n"], "train_wr": r["train_wr"], "train_dpt": r["train_dpt"],
        "val_n": r["val_n"], "val_wr": r["val_wr"], "val_dpt": np.nan,
        "lock_n": r["lock_n"], "lock_wr": r["lock_wr"], "lock_dpt": r["lock_dpt"],
        "lock_dd": r["lock_dd"], "lock_streak": r["lock_streak"],
        "lock_days": r["lock_days"], "lock_sharpe": r["lock_sharpe"],
    })
all_cands.extend(phaseB)
all_cands.extend(phaseC)
all_cands.extend(phaseD)
log(f"total candidates: {len(all_cands)}")


# ============================================================
# Apply sniper filter to LOCKBOX
# ============================================================
def lockbox_metrics_dict(d):
    return dict(n=d["lock_n"], wr=d["lock_wr"], dpt=d["lock_dpt"],
                max_dd=d["lock_dd"], loss_streak=d["lock_streak"],
                unique_days=d["lock_days"], sharpe=d["lock_sharpe"])


survivors = []
for c in all_cands:
    if c["lock_n"] is None or pd.isna(c["lock_wr"]):
        continue
    m_lock = lockbox_metrics_dict(c)
    if passes_sniper(m_lock):
        survivors.append(c)
log(f"survivors (pass sniper on lockbox): {len(survivors)}")


# ============================================================
# Bootstrap p
# ============================================================
log("computing bootstrap p for survivors")
for c in survivors:
    if c["offset"] == "ALL":
        if c["direction"] == "BOTH":
            d_lo = df_lo
        else:
            d_lo = df_lo[df_lo.direction == c["direction"]]
    else:
        d_lo = df_lo[(df_lo.fire_offset_s == c["offset"]) &
                     (df_lo.direction == c["direction"])]
    m = gate_mask(d_lo, c["gates"])
    sub = d_lo[m].copy()
    c["bootstrap_p"] = bootstrap_p(sub, n_shuffles=1000)
    c["sum_25_28d"] = sub["pnl_legacy_usd"].sum() * SCALE_28D

final = [c for c in survivors if c.get("bootstrap_p", 1.0) <= 0.05]
log(f"final candidates after bootstrap p<=0.05: {len(final)}")


# ============================================================
# Save all candidates + top 5
# ============================================================
df_all = pd.DataFrame(survivors)
if len(df_all):
    df_all["gate_stack_str"] = df_all["gates"].apply(lambda x: "+".join(x))
df_all.to_csv(f"{OUT_DIR}/v3_sniper_candidates_all.csv", index=False)

df_final = pd.DataFrame(final)
if len(df_final):
    df_final["gate_stack_str"] = df_final["gates"].apply(lambda x: "+".join(x))
    df_final["gate_count"] = df_final["gates"].apply(len)
    df_final = df_final.sort_values(["lock_sharpe", "lock_dpt"], ascending=False)
    df_final.head(20).to_csv(f"{OUT_DIR}/v3_top_candidates.csv", index=False)
    print()
    print("=== Top candidates ===")
    cols = ["gate_stack_str", "offset", "direction", "train_n", "train_wr", "train_dpt",
            "val_n", "val_wr", "lock_n", "lock_wr", "lock_dpt",
            "lock_dd", "lock_streak", "lock_days", "lock_sharpe",
            "bootstrap_p", "sum_25_28d"]
    print(df_final[cols].head(20).to_string())
else:
    log("WARNING: no survivors. Will write near-miss table.")
    # Save near-misses: pass 3 of 7
    near = []
    for c in all_cands:
        if c["lock_n"] is None or pd.isna(c["lock_wr"]):
            continue
        score = 0
        if c["lock_n"] >= 10 and c["lock_n"] <= 65: score += 1
        if c["lock_days"] >= 4: score += 1
        if c["lock_wr"] >= 0.75: score += 1
        if c["lock_dpt"] >= 3.0: score += 1
        if c["lock_dd"] <= 300.0: score += 1
        if c["lock_streak"] <= 6: score += 1
        if c["lock_sharpe"] >= 2.0: score += 1
        if score >= 5:
            c["pass_count"] = score
            near.append(c)
    df_near = pd.DataFrame(near)
    if len(df_near):
        df_near["gate_stack_str"] = df_near["gates"].apply(lambda x: "+".join(x))
        df_near = df_near.sort_values(["pass_count", "lock_sharpe"], ascending=False)
        df_near.head(30).to_csv(f"{OUT_DIR}/v3_near_misses.csv", index=False)
        log(f"wrote {len(df_near)} near-misses")
log("DONE")
