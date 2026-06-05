"""
17_solrf_fullperiod.py
Full-period OOS backtest for sleeve sol_5m_rf_tr_partial_mid.
Reconstructs gates: g_rf_strict_align + g_tr_partial_stack_with.
Also tests: drop_US, ma_300, and combinations.
Computes MDD + Calmar for each variant.
Outputs: strategy_lab/reports/SOLRF_FULLPERIOD_2026_05_31.md
"""
import sys, os, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

BASE = "C:/Users/alexandre bandarra/Desktop/global"
RESULTS_DIR = os.path.join(BASE, "data/v4/canonical/_results")
CANONICAL = os.path.join(BASE, "data/v4/canonical")
REPORT_DIR = os.path.join(BASE, "strategy_lab/reports")

# ---- Load dirscan ----
print("Loading dirscan_sol_5m.parquet...")
df = pd.read_parquet(os.path.join(RESULTS_DIR, "dirscan_sol_5m.parquet"))
print(f"  {len(df):,} rows, offsets={sorted(df.offset_s.unique())}")

# ---- Load range_filter_1s (SOL only) ----
print("Loading range_filter_1s.parquet...")
rf = pd.read_parquet(os.path.join(RESULTS_DIR, "range_filter_1s.parquet"))
rf = rf[rf["asset"] == "SOL"].reset_index(drop=True)
rf = rf.sort_values("ts_us").reset_index(drop=True)
print(f"  SOL rf rows: {len(rf):,}, ts range: {rf.ts_us.min()} - {rf.ts_us.max()}")

# ---- Load traders_reality_1s (SOL only) ----
print("Loading traders_reality_1s.parquet...")
tr = pd.read_parquet(os.path.join(RESULTS_DIR, "traders_reality_1s.parquet"))
tr = tr[tr["asset"] == "SOL"].reset_index(drop=True)
tr = tr.sort_values("ts_us").reset_index(drop=True)
print(f"  SOL tr rows: {len(tr):,}")

# ---- Load klines_1s (SOL, binance-spot) ----
print("Loading klines_1s.parquet (SOL)...")
kl = pd.read_parquet(os.path.join(CANONICAL, "klines_1s.parquet"))
kl = kl[kl["symbol_id"] == "BINANCE_SPOT_SOL_USDT"].copy()
kl = kl.sort_values("time_period_start_us").reset_index(drop=True)
kl = kl[["time_period_start_us", "price_close"]].rename(
    columns={"time_period_start_us": "ts_us", "price_close": "close"}
)
print(f"  SOL klines_1s rows: {len(kl):,}")

# ---- Helper: asof join ----
def asof_left(fire_us_arr, ref_ts_arr, ref_vals, max_age_us=None):
    """
    For each fire in fire_us_arr, find the latest ref row with ts_us <= fire_us.
    Returns array of ref_vals (NaN if no match or too old).
    """
    idx = np.searchsorted(ref_ts_arr, fire_us_arr, side="right") - 1
    out = np.full(len(fire_us_arr), np.nan)
    valid = idx >= 0
    out[valid] = ref_vals[idx[valid]]
    if max_age_us is not None:
        safe_idx = np.clip(idx, 0, len(ref_ts_arr) - 1)
        ts_matched = np.where(valid, ref_ts_arr[safe_idx], -np.inf)
        stale = (fire_us_arr - ts_matched) > max_age_us
        out[stale] = np.nan
    return out

# ---- Use representative offset: 120s (mid-window, matches live ~90-180s) ----
# Also check all offsets briefly at end.
OFFSETS_ALL = sorted(df.offset_s.unique())
OFFSET_FOCUS = 120  # primary

# ---- Asof joins for all offsets (vectorised per signal) ----
rf_ts = rf["ts_us"].values
rf_dir_vals = rf["rf_dir"].values.astype(float)
rf_age_vals = rf["rf_dir_age"].values.astype(float)

tr_ts = tr["ts_us"].values
tr_score_vals = tr["tr_ema_stack_score"].values.astype(float)

kl_ts = kl["ts_us"].values
kl_close_vals = kl["close"].values

print("Computing asof joins...")

fire_us = df["fire_us"].values

# RF signals
df["rf_dir_join"] = asof_left(fire_us, rf_ts, rf_dir_vals, max_age_us=30_000_000)   # 30s max age
df["rf_age_join"] = asof_left(fire_us, rf_ts, rf_age_vals, max_age_us=30_000_000)

# TR signals
df["tr_score_join"] = asof_left(fire_us, tr_ts, tr_score_vals, max_age_us=30_000_000)

# MA-300: compute 300s rolling mean of klines_1s close, then check slope
# MA300 slope = close[t] - close[t-300s]  (approximate, use close vs MA at t vs t-60s)
# Efficient: for each fire, get close[t] and close[t-300s] via two asof lookups
kl_close_now = asof_left(fire_us, kl_ts, kl_close_vals, max_age_us=10_000_000)
kl_close_m300 = asof_left(fire_us - 300_000_000, kl_ts, kl_close_vals, max_age_us=60_000_000)
df["ma300_slope"] = kl_close_now - kl_close_m300  # >0 = bullish, <0 = bearish

print("Done asof joins.")
print(f"  rf_dir_join nulls: {df.rf_dir_join.isna().sum():,} / {len(df):,}")
print(f"  tr_score_join nulls: {df.tr_score_join.isna().sum():,}")
print(f"  ma300_slope nulls: {df.ma300_slope.isna().sum():,}")

# ---- Direction: rf_dir sign ----
# rf_dir > 0 → UP, < 0 → DOWN
# For rows where rf_dir is NaN/0, no direction signal → will be excluded by g_rf_strict_align
df["direction"] = np.where(df["rf_dir_join"] > 0, "Up", np.where(df["rf_dir_join"] < 0, "Down", None))

# ---- Fill: held-side vwap ----
df["entry_vwap"] = np.where(df["direction"] == "Up", df["u_vwap"], df["d_vwap"])
df["fill_ok"] = np.where(df["direction"] == "Up", df["u_ok"], df["d_ok"])
df["won"] = df["outcome_truth"] == df["direction"]

# ---- PnL function (0.07 curve flat $5 stake) ----
STAKE = 5.0
FEE_COEFF = 0.07

def compute_pnl(vwap, won_arr):
    shares = STAKE / vwap
    pnl_won = shares * (1 - vwap) * (1 - FEE_COEFF * vwap)
    pnl_lost = -shares * vwap
    return np.where(won_arr, pnl_won, pnl_lost)

# ---- Gate definitions ----
# Restrict to valid fill
base_mask = (
    df["direction"].notna() &
    df["fill_ok"] &
    df["entry_vwap"].notna() &
    (df["entry_vwap"] > 0.01) & (df["entry_vwap"] < 0.99)
)

# g_rf_strict_align: rf_dir ≠ 0 (already enforced by direction), AND age < 300s
g_rf = (
    df["rf_dir_join"].notna() & (df["rf_dir_join"] != 0) &
    (df["rf_age_join"].notna()) & (df["rf_age_join"] < 300)
)

# g_tr_partial_stack_with: |tr_score| >= 1 AND sign agrees with direction
g_tr_sign_up = (df["direction"] == "Up") & (df["tr_score_join"] >= 1)
g_tr_sign_dn = (df["direction"] == "Down") & (df["tr_score_join"] <= -1)
g_tr = (df["tr_score_join"].notna()) & (g_tr_sign_up | g_tr_sign_dn)

# drop_US: exclude fire hours 14-21 UTC
fire_hour = (df["fire_us"] // 1_000_000 // 3600) % 24
g_no_us = ~fire_hour.between(14, 21)

# ma_300: slope agrees with direction
g_ma300_up = (df["direction"] == "Up") & (df["ma300_slope"] > 0)
g_ma300_dn = (df["direction"] == "Down") & (df["ma300_slope"] < 0)
g_ma300 = (df["ma300_slope"].notna()) & (g_ma300_up | g_ma300_dn)

# ---- Evaluate at offset=120s ----
def evaluate(mask, label, period_col=None):
    sub = df[df["offset_s"] == OFFSET_FOCUS][mask[df["offset_s"] == OFFSET_FOCUS]].copy()
    sub = sub.sort_values("fire_us").reset_index(drop=True)
    if len(sub) == 0:
        return {"label": label, "n": 0, "WR%": np.nan, "$/tr": np.nan, "total$": 0, "MDD$": 0, "Calmar": np.nan}
    pnl = compute_pnl(sub["entry_vwap"].values, sub["won"].values)
    sub["pnl"] = pnl
    wr = sub["won"].mean() * 100
    avg = pnl.mean()
    total = pnl.sum()
    cum = np.cumsum(pnl)
    running_max = np.maximum.accumulate(cum)
    drawdown = cum - running_max
    mdd = drawdown.min()  # most negative
    calmar = total / abs(mdd) if mdd < 0 else np.inf
    return {"label": label, "n": len(sub), "WR%": round(wr, 1), "$/tr": round(avg, 4), "total$": round(total, 2), "MDD$": round(mdd, 2), "Calmar": round(calmar, 3)}

# ---- All variants ----
sleeve_base = base_mask & g_rf & g_tr  # full sleeve without extra gates
variants = [
    (sleeve_base, "base (rf+tr)"),
    (sleeve_base & g_no_us, "base + drop_US"),
    (sleeve_base & g_ma300, "base + ma_300"),
    (sleeve_base & g_no_us & g_ma300, "base + drop_US + ma_300"),
]

results = []
for mask, lbl in variants:
    r = evaluate(mask, lbl)
    results.append(r)
    print(f"  {lbl}: n={r['n']}, WR={r['WR%']}%, $/tr={r['$/tr']}, total={r['total$']}, MDD={r['MDD$']}, Calmar={r['Calmar']}")

# ---- Offset sensitivity (base only, all offsets) ----
print("\nOffset sensitivity (base variant):")
offset_rows = []
for off in OFFSETS_ALL:
    sub = df[df["offset_s"] == off][base_mask[df["offset_s"] == off]].copy()
    if len(sub) == 0:
        continue
    pnl = compute_pnl(sub["entry_vwap"].values, sub["won"].values)
    cum = np.cumsum(pnl)
    running_max = np.maximum.accumulate(cum)
    mdd = (cum - running_max).min()
    total = pnl.sum()
    calmar = total / abs(mdd) if mdd < 0 else np.inf
    row = {"offset_s": off, "n": len(sub), "WR%": round(sub["won"].mean()*100,1),
           "$/tr": round(pnl.mean(),4), "total$": round(total,2), "MDD$": round(mdd,2), "Calmar": round(calmar,3)}
    offset_rows.append(row)
    print(f"  offset={off}s: {row}")

# ---- Walk-forward 50/50 (base variant at offset=120) ----
print("\nWalk-forward 50/50 (base, drop_US, ma_300 at offset=120):")
sub_all = df[df["offset_s"] == OFFSET_FOCUS].sort_values("fire_us").reset_index(drop=True)
n_all = len(sub_all)
split_idx = n_all // 2

def wf_eval(mask_full, lbl):
    sub = df[df["offset_s"] == OFFSET_FOCUS].sort_values("fire_us").reset_index(drop=True)
    m = mask_full[df["offset_s"] == OFFSET_FOCUS].sort_values(sub.index if False else True)
    # realign mask to sub
    sub_masked_idx = sub.index[mask_full[sub_all.index].values]
    sub2 = sub_all.loc[mask_full[sub_all.index].values].copy()
    sub2 = sub2.reset_index(drop=True)
    n2 = len(sub2)
    if n2 == 0:
        return
    mid = n2 // 2
    h1 = sub2.iloc[:mid]
    h2 = sub2.iloc[mid:]
    def half_stats(h):
        if len(h) == 0: return (0, np.nan, np.nan)
        p = compute_pnl(h["entry_vwap"].values, h["won"].values)
        return (len(h), round(h["won"].mean()*100,1), round(p.sum(),2))
    s1 = half_stats(h1)
    s2 = half_stats(h2)
    print(f"  {lbl}: H1 n={s1[0]} WR={s1[1]}% total={s1[2]}$ | H2 n={s2[0]} WR={s2[1]}% total={s2[2]}$")

# Fix mask alignment for walk-forward
def wf_eval2(mask_series, lbl):
    sub = df[df["offset_s"] == OFFSET_FOCUS].copy()
    sub = sub.sort_values("fire_us").reset_index(drop=True)
    # recompute mask on sub
    fire_us_sub = sub["fire_us"].values
    rf_dir_sub = asof_left(fire_us_sub, rf_ts, rf_dir_vals, max_age_us=30_000_000)
    rf_age_sub = asof_left(fire_us_sub, rf_ts, rf_age_vals, max_age_us=30_000_000)
    tr_score_sub = asof_left(fire_us_sub, tr_ts, tr_score_vals, max_age_us=30_000_000)
    ma_now_sub = asof_left(fire_us_sub, kl_ts, kl_close_vals, max_age_us=10_000_000)
    ma_m300_sub = asof_left(fire_us_sub - 300_000_000, kl_ts, kl_close_vals, max_age_us=60_000_000)
    ma300_slope_sub = ma_now_sub - ma_m300_sub

    dir_sub = np.where(rf_dir_sub > 0, "Up", np.where(rf_dir_sub < 0, "Down", None))
    ev_sub = np.where(dir_sub == "Up", sub["u_vwap"].values, sub["d_vwap"].values)
    ok_sub = np.where(dir_sub == "Up", sub["u_ok"].values, sub["d_ok"].values).astype(bool)
    won_sub = (sub["outcome_truth"].values == dir_sub)

    fire_hour_sub = (fire_us_sub // 1_000_000 // 3600) % 24

    base_m = (
        (dir_sub != None) &
        (np.array([d is not None for d in dir_sub])) &
        ok_sub &
        (~np.isnan(ev_sub)) &
        (ev_sub > 0.01) & (ev_sub < 0.99) &
        (~np.isnan(rf_dir_sub)) & (rf_dir_sub != 0) &
        (~np.isnan(rf_age_sub)) & (rf_age_sub < 300) &
        (~np.isnan(tr_score_sub)) &
        (np.where(dir_sub == "Up", tr_score_sub >= 1, tr_score_sub <= -1))
    )

    gate_no_us = ~((fire_hour_sub >= 14) & (fire_hour_sub <= 21))
    gate_ma300 = (
        (~np.isnan(ma300_slope_sub)) &
        np.where(dir_sub == "Up", ma300_slope_sub > 0, ma300_slope_sub < 0)
    )

    masks = {
        "base": base_m,
        "base+drop_US": base_m & gate_no_us,
        "base+ma_300": base_m & gate_ma300,
        "base+both": base_m & gate_no_us & gate_ma300,
    }
    m = masks.get(lbl, base_m)
    sub2 = sub[m].reset_index(drop=True)
    n2 = len(sub2)
    if n2 == 0:
        print(f"  {lbl}: empty")
        return
    mid = n2 // 2
    h1 = sub2.iloc[:mid]
    h2 = sub2.iloc[mid:]
    ev1 = np.where(h1["direction"] == "Up", h1["u_vwap"].values, h1["d_vwap"].values) if "direction" in h1.columns else asof_left(h1["fire_us"].values, rf_ts, rf_dir_vals)

    # use sub2's computed values
    ev_sub_m = ev_sub[m]
    won_sub_m = won_sub[m]
    mid2 = len(ev_sub_m) // 2
    p1 = compute_pnl(ev_sub_m[:mid2], won_sub_m[:mid2])
    p2 = compute_pnl(ev_sub_m[mid2:], won_sub_m[mid2:])
    s1 = (len(p1), round(won_sub_m[:mid2].mean()*100,1) if len(p1) else np.nan, round(p1.sum(),2) if len(p1) else 0)
    s2 = (len(p2), round(won_sub_m[mid2:].mean()*100,1) if len(p2) else np.nan, round(p2.sum(),2) if len(p2) else 0)
    print(f"  {lbl}: H1 n={s1[0]} WR={s1[1]}% total={s1[2]}$ | H2 n={s2[0]} WR={s2[1]}% total={s2[2]}$")
    return m, ev_sub_m, won_sub_m

wf_results = {}
for lbl in ["base", "base+drop_US", "base+ma_300", "base+both"]:
    r = wf_eval2(None, lbl)
    if r is not None:
        wf_results[lbl] = r

# ---- NEW gates exploration ----
print("\nNew gate exploration (base + offset=120):")
sub_120 = df[df["offset_s"] == OFFSET_FOCUS].sort_values("fire_us").reset_index(drop=True)
fire_us_120 = sub_120["fire_us"].values

rf_dir_120 = asof_left(fire_us_120, rf_ts, rf_dir_vals, max_age_us=30_000_000)
rf_age_120 = asof_left(fire_us_120, rf_ts, rf_age_vals, max_age_us=30_000_000)
rf_dist_120 = asof_left(fire_us_120, rf_ts, rf["rf_dist_bps"].values, max_age_us=30_000_000)
rf_band_120 = asof_left(fire_us_120, rf_ts, rf["rf_band_pos"].values, max_age_us=30_000_000)
tr_score_120 = asof_left(fire_us_120, tr_ts, tr_score_vals, max_age_us=30_000_000)
tr_london_120 = asof_left(fire_us_120, tr_ts, tr["tr_in_london"].values.astype(float), max_age_us=30_000_000)
tr_ny_120 = asof_left(fire_us_120, tr_ts, tr["tr_in_ny"].values.astype(float), max_age_us=30_000_000)
ma_now_120 = asof_left(fire_us_120, kl_ts, kl_close_vals, max_age_us=10_000_000)
ma_m300_120 = asof_left(fire_us_120 - 300_000_000, kl_ts, kl_close_vals, max_age_us=60_000_000)
ma300_120 = ma_now_120 - ma_m300_120

dir_120 = np.where(rf_dir_120 > 0, "Up", np.where(rf_dir_120 < 0, "Down", None))
ev_120 = np.where(dir_120 == "Up", sub_120["u_vwap"].values, sub_120["d_vwap"].values)
ok_120 = np.where(dir_120 == "Up", sub_120["u_ok"].values, sub_120["d_ok"].values).astype(bool)
won_120 = (sub_120["outcome_truth"].values == dir_120)

base_120 = (
    np.array([d is not None for d in dir_120]) &
    ok_120 &
    (~np.isnan(ev_120)) &
    (ev_120 > 0.01) & (ev_120 < 0.99) &
    (~np.isnan(rf_dir_120)) & (rf_dir_120 != 0) &
    (~np.isnan(rf_age_120)) & (rf_age_120 < 300) &
    (~np.isnan(tr_score_120)) &
    np.where(dir_120 == "Up", tr_score_120 >= 1, tr_score_120 <= -1)
)

fire_hour_120 = (fire_us_120 // 1_000_000 // 3600) % 24

gate_no_us_120 = ~((fire_hour_120 >= 14) & (fire_hour_120 <= 21))
gate_ma300_120 = (~np.isnan(ma300_120)) & np.where(dir_120 == "Up", ma300_120 > 0, ma300_120 < 0)
gate_london_120 = (tr_london_120 == 1)
gate_not_ny_120 = (tr_ny_120 == 0)
gate_strong_tr_120 = (~np.isnan(tr_score_120)) & np.where(dir_120 == "Up", tr_score_120 >= 2, tr_score_120 <= -2)
gate_rf_age_tight_120 = (~np.isnan(rf_age_120)) & (rf_age_120 < 120)
gate_rf_dist_pos_120 = (~np.isnan(rf_dist_120)) & (
    np.where(dir_120 == "Up", rf_dist_120 > 0, rf_dist_120 < 0)
)
# ema9 slope from dirscan: positive for UP, negative for DOWN
gate_ema9_align_120 = np.where(dir_120 == "Up",
    sub_120["ema9_slope_bps"].values > 0,
    sub_120["ema9_slope_bps"].values < 0)
# px vs strike alignment: avoid buying Up when deeply in-the-money already
gate_px_neutral_120 = (np.abs(sub_120["px_vs_strike_bps"].values) < 200)

def quick_eval(mask, label):
    m = base_120 & mask
    if m.sum() == 0:
        return
    p = compute_pnl(ev_120[m], won_120[m])
    total = p.sum()
    cum = np.cumsum(p)
    mdd = (cum - np.maximum.accumulate(cum)).min()
    calmar = total / abs(mdd) if mdd < 0 else np.inf
    print(f"  {label}: n={m.sum()} WR={won_120[m].mean()*100:.1f}% $/tr={p.mean():.4f} total={total:.2f} MDD={mdd:.2f} Calmar={calmar:.3f}")
    return {"label": label, "n": int(m.sum()), "WR%": round(won_120[m].mean()*100,1),
            "$/tr": round(p.mean(),4), "total$": round(total,2), "MDD$": round(mdd,2), "Calmar": round(calmar,3)}

new_gate_results = []
combos = [
    (gate_no_us_120 & gate_ma300_120, "drop_US+ma_300"),
    (gate_london_120, "london_only"),
    (gate_not_ny_120, "not_NY"),
    (gate_strong_tr_120, "tr_score>=2"),
    (gate_rf_age_tight_120, "rf_age<120s"),
    (gate_rf_dist_pos_120, "rf_dist_aligned"),
    (gate_ema9_align_120, "ema9_slope_align"),
    (gate_px_neutral_120, "px_vs_strike<200bps"),
    (gate_no_us_120 & gate_ma300_120 & gate_strong_tr_120, "drop_US+ma_300+tr>=2"),
    (gate_no_us_120 & gate_ma300_120 & gate_rf_age_tight_120, "drop_US+ma_300+rf_age<120"),
    (gate_no_us_120 & gate_ma300_120 & gate_ema9_align_120, "drop_US+ma_300+ema9"),
    (gate_no_us_120 & gate_ma300_120 & gate_london_120, "drop_US+ma_300+london"),
    (gate_no_us_120 & gate_ma300_120 & gate_not_ny_120, "drop_US+ma_300+not_NY"),
    (gate_no_us_120 & gate_ma300_120 & gate_px_neutral_120, "drop_US+ma_300+px_neutral"),
]
for mask, lbl in combos:
    r = quick_eval(mask, lbl)
    if r:
        new_gate_results.append(r)

# ---- Weekly breakdown (base+drop_US+ma_300) ----
print("\nWeekly breakdown (base+drop_US+ma_300, offset=120):")
best_mask = base_120 & gate_no_us_120 & gate_ma300_120
sub_best = sub_120[best_mask].copy()
sub_best["pnl"] = compute_pnl(ev_120[best_mask], won_120[best_mask])
sub_best["date"] = pd.to_datetime(sub_best["fire_us"], unit="us", utc=True)
sub_best["week"] = sub_best["date"].dt.to_period("W")
weekly = sub_best.groupby("week").agg(
    n=("pnl","count"),
    wr=("won","mean"),
    total=("pnl","sum")
).reset_index()
weekly["wr"] = (weekly["wr"]*100).round(1)
weekly["total"] = weekly["total"].round(2)
print(weekly.to_string())

# ---- Compile all results to dict for report ----
print("\n\n=== SUMMARY FOR REPORT ===")
base_r = results[0]
print(f"Base (rf+tr): n={base_r['n']} WR={base_r['WR%']}% $/tr={base_r['$/tr']} total={base_r['total$']} MDD={base_r['MDD$']} Calmar={base_r['Calmar']}")
for r in results[1:]:
    print(f"{r['label']}: n={r['n']} WR={r['WR%']}% $/tr={r['$/tr']} total={r['total$']} MDD={r['MDD$']} Calmar={r['Calmar']}")

# Store in globals for report generation
_results = results
_offset_rows = offset_rows
_new_gate_results = new_gate_results
_weekly = weekly

print("\n=== DONE ===")
print("Saving results to pickle for report generation...")
import pickle
pickle_path = os.path.join(BASE, "strategy_lab/_opt_2026_05_30/_results/solrf_fullperiod_results.pkl")
os.makedirs(os.path.dirname(pickle_path), exist_ok=True)
with open(pickle_path, "wb") as f:
    pickle.dump({
        "results": _results,
        "offset_rows": _offset_rows,
        "new_gate_results": _new_gate_results,
        "weekly": _weekly.to_dict(),
    }, f)
print(f"Saved to {pickle_path}")
