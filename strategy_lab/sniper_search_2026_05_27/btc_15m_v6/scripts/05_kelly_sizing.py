"""V6 Kelly sizing + variable-stake PnL simulation for top 5 BTC 15m sleeves.

We use TWO conviction-to-stake methods per V6 brief §1:
- Method 1: full-Kelly @ 0.5× fraction (not 0.25× — needed for these slim edges)
- Method 2: linear interpolation by bucket (L=$5, M=$15, H=$25)

Bucket = # extras passing (Option B from brief).

For each sleeve:
1. Find extras = candidate composable gates not in the base stack
2. Compute conviction per fire = sum of extras passing
3. Bucket: L (0-3), M (4-6), H (7+ extras passing)
4. Train-bucket WR -> Kelly stake per bucket (fraction 0.5)
5. Run variable-stake PnL sim on lockbox

Output:
- kelly_stake_table_{sleeve_id}.csv (per sleeve)
- cumulative_pnl_kelly_vs_const_{sleeve_id}.png (per sleeve)
- update top_5_candidates_v6.csv with sum_25_28d_kelly
"""
import os, sys, time
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RES = "data/v4/canonical/_results"
OUT_DIR = "strategy_lab/sniper_search_2026_05_27/btc_15m_v6"
IN_PANEL = f"{RES}/sniper_btc15m_v3_gated.parquet"

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)


log("loading panel")
df = pd.read_parquet(IN_PANEL)
df["fire_date"] = pd.to_datetime(df["fire_us"], unit="us", utc=True)
df = df[(df["trend_slope_30m"].notna()) & (df["mp_skew"].notna())].copy()
df = df[(df["entry_vwap"] >= 0.10) & (df["entry_vwap"] <= 0.90)].copy()
df = df.sort_values("fire_us").reset_index(drop=True)


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

STAKE_MIN = 5.0
STAKE_MAX = 25.0
KELLY_FRAC = 0.5   # half-Kelly (0.25 was too conservative for these slim edges)

# Candidate extra-gate menu (for conviction scoring). Strong, well-fired gates.
EXTRA_GATE_MENU = [
    "g_tr_above_ema800", "g_tr_above_ema200", "g_tr_above_ema50",
    "g_tr_above_cloud", "g_tr_above_pp",
    "g_regime_stack_with", "g_regime_stack_full_with",
    "g_rf_with", "g_rf_strong", "g_ribbon_slope_with",
    "g_mp_skew_with", "g_mp_skew_strong_with",
    "g_hawkes_imbalance_with", "g_hawkes_imb_loose_with",
    "g_imb5_with", "g_imb5_strong_with",
    "g_f7_rsi_with", "g_f7_rsi_strong_with",
    "g_trend_slope_with", "g_trend_slope_strong_with",
    "g_di_agrees", "g_sms_trend_with",
    "g_lm_high_stat", "g_vol_expanding", "g_vol_contracting",
    "g_vpin_calm",
    "g_vwap_15_85", "g_vwap_20_80", "g_vwap_25_75",
]


def kelly_stake_from_p(p, vwap_median, kelly_fraction=KELLY_FRAC,
                       stake_min=STAKE_MIN, stake_max=STAKE_MAX):
    """Translate (p, vwap) into a $5-$25 stake using fractional Kelly."""
    if vwap_median <= 0 or vwap_median >= 1:
        return stake_min
    b = (1.0 - vwap_median) * 0.98 / vwap_median
    if b <= 0:
        return stake_min
    f_full = (p * b - (1.0 - p)) / b
    if f_full <= 0:
        return stake_min
    # Stake = kelly_fraction * f_full * bankroll (bankroll = $25 max single stake)
    raw = kelly_fraction * f_full * stake_max
    return float(np.clip(raw, stake_min, stake_max))


def apply_gates(d, gates):
    if len(d) == 0:
        return d
    m = np.ones(len(d), dtype=bool)
    for g in gates:
        m &= (d[g].values == 1)
    return d[m]


def filter_offset_dir(d, off, dir_val):
    if off == "ALL":
        if dir_val == "BOTH":
            return d
        return d[d.direction == dir_val]
    off_i = int(off) if str(off).isdigit() else int(off)
    if dir_val == "BOTH":
        return d[d.fire_offset_s == off_i]
    return d[(d.fire_offset_s == off_i) & (d.direction == dir_val)]


# Load top 5 candidates
top5 = pd.read_csv(f"{OUT_DIR}/top_5_candidates_v6.csv")
log(f"top 5 sleeves loaded: {len(top5)}")

kelly_uplift_summary = []
LO_DAYS = max(1, (LOCK_END - VAL_END).days)
SCALE_28D = 28 / LO_DAYS

for _, row in top5.iterrows():
    sleeve_id = row["sleeve_id"]
    base_gates = row["gate_stack"].split("+")
    off = row["offset"]
    dir_val = row["direction"]
    log(f"\n=== {sleeve_id}: offset={off} dir={dir_val} gates={base_gates} ===")

    tr_cell = filter_offset_dir(df_tr, off, dir_val)
    va_cell = filter_offset_dir(df_va, off, dir_val)
    lo_cell = filter_offset_dir(df_lo, off, dir_val)
    tr_base = apply_gates(tr_cell, base_gates)
    va_base = apply_gates(va_cell, base_gates)
    lo_base = apply_gates(lo_cell, base_gates)
    log(f"  base fires: train={len(tr_base)}, val={len(va_base)}, lock={len(lo_base)}")

    # Use ALL extras for richer conviction signal
    extras = [g for g in EXTRA_GATE_MENU if g not in set(base_gates) and g in df.columns]
    extras_meaningful = []
    for g in extras:
        if len(tr_base) == 0: continue
        fr = tr_base[g].mean()
        if 0.10 <= fr <= 0.85:
            extras_meaningful.append((g, fr))
    extras_meaningful.sort(key=lambda x: abs(x[1] - 0.5))
    extras_use = [g for g, _ in extras_meaningful[:12]]
    log(f"  extras used (n={len(extras_use)}): {extras_use}")

    if not extras_use:
        log(f"  SKIP: no meaningful extras")
        continue

    def add_conviction(d):
        if len(d) == 0:
            return d
        d = d.copy()
        d["conviction"] = sum(d[g].values for g in extras_use)
        return d
    tr_base = add_conviction(tr_base)
    va_base = add_conviction(va_base)
    lo_base = add_conviction(lo_base)

    # Bucket: L (conv 0-3), M (4-6), H (7+)
    def bucket(d):
        d = d.copy()
        b = np.full(len(d), "L", dtype="<U1")
        c = d["conviction"].values
        b[(c >= 4) & (c <= 6)] = "M"
        b[c >= 7] = "H"
        d["bucket"] = b
        return d
    tr_base = bucket(tr_base)
    va_base = bucket(va_base)
    lo_base = bucket(lo_base)

    # Stake table from TRAIN buckets
    stake_table = []
    bucket_to_stake_kelly = {}
    bucket_to_stake_linear = {"L": 5.0, "M": 15.0, "H": 25.0}
    for b in ["L", "M", "H"]:
        tr_sub = tr_base[tr_base["bucket"] == b]
        va_sub = va_base[va_base["bucket"] == b]
        lo_sub = lo_base[lo_base["bucket"] == b]
        if len(tr_sub) == 0:
            stake_table.append(dict(bucket=b, n_train=0, wr_train=np.nan,
                                    vwap_median=np.nan, stake_kelly_50=STAKE_MIN,
                                    stake_linear=bucket_to_stake_linear[b],
                                    n_val=len(va_sub), wr_val=va_sub["won"].mean() if len(va_sub) else np.nan,
                                    n_lock=len(lo_sub), wr_lock=lo_sub["won"].mean() if len(lo_sub) else np.nan))
            bucket_to_stake_kelly[b] = STAKE_MIN
            continue
        wr_tr = tr_sub["won"].mean()
        vwap_med = tr_sub["entry_vwap"].median()
        stake_k = kelly_stake_from_p(wr_tr, vwap_med, kelly_fraction=KELLY_FRAC)
        bucket_to_stake_kelly[b] = stake_k
        wr_va = va_sub["won"].mean() if len(va_sub) > 0 else np.nan
        wr_lo = lo_sub["won"].mean() if len(lo_sub) > 0 else np.nan
        stake_table.append(dict(
            bucket=b,
            n_train=len(tr_sub), wr_train=wr_tr,
            vwap_median=vwap_med, stake_kelly_50=stake_k,
            stake_linear=bucket_to_stake_linear[b],
            n_val=len(va_sub), wr_val=wr_va,
            n_lock=len(lo_sub), wr_lock=wr_lo,
        ))

    st_df = pd.DataFrame(stake_table)
    st_df.to_csv(f"{OUT_DIR}/kelly_stake_table_{sleeve_id}.csv", index=False)
    log(f"  Stake table:\n{st_df.to_string()}")

    # Simulate variable-stake PnL on lockbox: Kelly + Linear vs constant
    lo_base = lo_base.sort_values("fire_us").reset_index(drop=True)
    stakes_kelly = []
    stakes_linear = []
    pnl_kelly = []
    pnl_linear = []
    pnl_const = []
    for _, fire in lo_base.iterrows():
        b = fire["bucket"]
        sk = bucket_to_stake_kelly.get(b, STAKE_MIN)
        sl = bucket_to_stake_linear[b]
        pnl_kelly.append(fire["pnl_legacy_usd"] * (sk / 25.0))
        pnl_linear.append(fire["pnl_legacy_usd"] * (sl / 25.0))
        pnl_const.append(fire["pnl_legacy_usd"])
        stakes_kelly.append(sk)
        stakes_linear.append(sl)
    pnl_kelly = np.array(pnl_kelly)
    pnl_linear = np.array(pnl_linear)
    pnl_const = np.array(pnl_const)
    sum_kelly = pnl_kelly.sum()
    sum_linear = pnl_linear.sum()
    sum_const = pnl_const.sum()
    sum_kelly_28d = sum_kelly * SCALE_28D
    sum_linear_28d = sum_linear * SCALE_28D
    sum_const_28d = sum_const * SCALE_28D
    log(f"  Lockbox sum (n={len(pnl_const)}):")
    log(f"    const $25:   ${sum_const:>8.2f}  (28d: ${sum_const_28d:.2f})")
    log(f"    kelly 0.5×:  ${sum_kelly:>8.2f}  (28d: ${sum_kelly_28d:.2f}) avg_stake=${np.mean(stakes_kelly):.2f}")
    log(f"    linear:      ${sum_linear:>8.2f}  (28d: ${sum_linear_28d:.2f}) avg_stake=${np.mean(stakes_linear):.2f}")

    # PnL DD
    def compute_dd(arr):
        if len(arr) == 0: return 0.0
        cum = np.cumsum(arr)
        peak = np.maximum.accumulate(cum)
        return float(-(cum - peak).min())
    dd_const = compute_dd(pnl_const)
    dd_kelly = compute_dd(pnl_kelly)
    dd_linear = compute_dd(pnl_linear)
    log(f"  DD: const=${dd_const:.2f}  kelly=${dd_kelly:.2f}  linear=${dd_linear:.2f}")

    kelly_uplift_summary.append(dict(
        sleeve_id=sleeve_id,
        sum_const_lock=sum_const,
        sum_kelly_lock=sum_kelly,
        sum_linear_lock=sum_linear,
        sum_const_28d=sum_const_28d,
        sum_kelly_28d=sum_kelly_28d,
        sum_linear_28d=sum_linear_28d,
        avg_stake_kelly=float(np.mean(stakes_kelly)),
        avg_stake_linear=float(np.mean(stakes_linear)),
        dd_const=dd_const, dd_kelly=dd_kelly, dd_linear=dd_linear,
        kelly_uplift_pct=(sum_kelly - sum_const) / max(abs(sum_const), 1) * 100,
        linear_uplift_pct=(sum_linear - sum_const) / max(abs(sum_const), 1) * 100,
    ))

    # Plot
    fig, ax = plt.subplots(1, 1, figsize=(10, 5))
    ax.plot(np.cumsum(pnl_const), label=f"Const $25 sum=${sum_const:.2f}", linewidth=2)
    ax.plot(np.cumsum(pnl_linear), label=f"Linear bucket sum=${sum_linear:.2f}", linewidth=2)
    ax.plot(np.cumsum(pnl_kelly), label=f"Kelly 0.5× sum=${sum_kelly:.2f}", linewidth=2)
    ax.axhline(0, color="grey", linewidth=0.5)
    ax.set_xlabel("Fire #")
    ax.set_ylabel("Cumulative PnL ($)")
    ax.set_title(f"{sleeve_id}: stake methods (n={len(pnl_const)}, off={off}, {dir_val})")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(f"{OUT_DIR}/cumulative_pnl_kelly_vs_const_{sleeve_id}.png", dpi=100)
    plt.close()

log("\nUpdating top_5 csv with Kelly results")
kelly_df = pd.DataFrame(kelly_uplift_summary)
log(f"\n=== Kelly uplift summary ===\n{kelly_df.to_string()}")
kelly_df.to_csv(f"{OUT_DIR}/kelly_uplift_summary.csv", index=False)

# Update top5 with kelly + linear sums
top5_orig = pd.read_csv(f"{OUT_DIR}/top_5_candidates_v6.csv")
if "sum_25_28d_kelly" in top5_orig.columns:
    top5_orig = top5_orig.drop(columns=["sum_25_28d_kelly"])
top5_merged = top5_orig.merge(
    kelly_df[["sleeve_id", "sum_kelly_28d", "sum_linear_28d", "avg_stake_kelly", "avg_stake_linear"]],
    on="sleeve_id", how="left",
)
top5_merged["sum_25_28d_kelly"] = top5_merged["sum_kelly_28d"]
top5_merged.to_csv(f"{OUT_DIR}/top_5_candidates_v6.csv", index=False)
log("UPDATED top_5_candidates_v6.csv with Kelly + Linear stake metrics")

log("DONE")
