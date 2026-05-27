"""Generate conviction-bucket histograms for each top 5 V6 sleeve.

Shows the # extras passing per fire distribution and per-bucket WR.
"""
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RES = "data/v4/canonical/_results"
OUT_DIR = "strategy_lab/sniper_search_2026_05_27/btc_15m_v6"

df = pd.read_parquet(f"{RES}/sniper_btc15m_v3_gated.parquet")
df["fire_date"] = pd.to_datetime(df["fire_us"], unit="us", utc=True)
df = df[(df["trend_slope_30m"].notna()) & (df["mp_skew"].notna())].copy()
df = df[(df["entry_vwap"] >= 0.10) & (df["entry_vwap"] <= 0.90)].copy()
df = df.sort_values("fire_us").reset_index(drop=True)

LOCK_END    = pd.Timestamp("2026-05-26", tz="UTC")
VAL_END     = pd.Timestamp("2026-05-22", tz="UTC")
df_lo = df[(df.fire_date >= VAL_END) & (df.fire_date < LOCK_END)].copy()

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
    "g_vpin_calm", "g_vwap_15_85", "g_vwap_20_80", "g_vwap_25_75",
]


def apply_gates(d, gates):
    m = np.ones(len(d), dtype=bool)
    for g in gates:
        m &= (d[g].values == 1)
    return d[m]


def filter_offset_dir(d, off, dir_val):
    off_i = int(off)
    if dir_val == "BOTH":
        return d[d.fire_offset_s == off_i]
    return d[(d.fire_offset_s == off_i) & (d.direction == dir_val)]


top5 = pd.read_csv(f"{OUT_DIR}/top_5_candidates_v6.csv")

fig, axes = plt.subplots(len(top5), 2, figsize=(14, 4*len(top5)))
for i, (_, row) in enumerate(top5.iterrows()):
    sleeve_id = row["sleeve_id"]
    base_gates = row["gate_stack"].split("+")
    off = row["offset"]
    dir_val = row["direction"]
    cell = filter_offset_dir(df_lo, off, dir_val)
    base = apply_gates(cell, base_gates)
    extras = [g for g in EXTRA_GATE_MENU if g not in set(base_gates) and g in df.columns]
    extras_use = []
    for g in extras:
        if len(base) == 0: continue
        fr = base[g].mean()
        if 0.10 <= fr <= 0.85:
            extras_use.append(g)
    extras_use = extras_use[:12]

    base = base.copy()
    if extras_use:
        base["conviction"] = sum(base[g].values for g in extras_use)
    else:
        base["conviction"] = 0

    ax1 = axes[i, 0] if len(top5) > 1 else axes[0]
    ax2 = axes[i, 1] if len(top5) > 1 else axes[1]

    # Distribution of conviction
    if len(base) > 0:
        max_c = max(int(base["conviction"].max()), 12)
        bins = np.arange(-0.5, max_c + 1, 1)
        ax1.hist(base["conviction"], bins=bins, edgecolor="black", color="steelblue", alpha=0.7)
        ax1.set_xlabel("Conviction (# extras passing)")
        ax1.set_ylabel("# fires (lockbox)")
        ax1.set_title(f"{sleeve_id}\nConviction distribution (n_lockbox={len(base)})")
        ax1.grid(True, alpha=0.3)

        # WR per conviction bucket
        wr_by_bucket = base.groupby("conviction")["won"].agg(["count", "mean"])
        ax2.bar(wr_by_bucket.index, wr_by_bucket["mean"], color="darkgreen", alpha=0.7, edgecolor="black")
        ax2.set_xlabel("Conviction bucket")
        ax2.set_ylabel("WR")
        ax2.set_ylim(0, 1)
        ax2.axhline(0.5, color="red", linestyle="--", linewidth=0.5)
        ax2.set_title(f"WR per conviction (counts annotated)")
        ax2.grid(True, alpha=0.3)
        for x, (cnt, wr) in zip(wr_by_bucket.index, wr_by_bucket.values):
            ax2.text(x, wr + 0.02, f"n={cnt}\nwr={wr:.2f}", ha="center", fontsize=8)

fig.tight_layout()
fig.savefig(f"{OUT_DIR}/conviction_histograms_top5.png", dpi=100, bbox_inches="tight")
print(f"wrote {OUT_DIR}/conviction_histograms_top5.png")
