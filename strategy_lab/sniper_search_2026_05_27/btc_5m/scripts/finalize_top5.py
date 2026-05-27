"""
Finalize the top 5 BTC 5m sniper candidates from robust_candidates.csv.

For each:
  - Build cumulative PnL PNG (full window with train/val/lockbox markers)
  - Compute per-day fire histogram
  - Compute final metric row matching brief §9 spec

Output:
  top_5_candidates.csv (clean schema per brief)
  cumulative_pnl_<id>.png for each
  per_day_fires_<id>.png for each
"""
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import re

ROOT = Path(r"C:/Users/alexandre bandarra/Desktop/global")
OUT  = ROOT / "strategy_lab/sniper_search_2026_05_27/btc_5m"
MG = ROOT / "data/v4/canonical/_results/master_gate_features_v2.parquet"

PNL_SCALE = 1.0

df = pd.read_parquet(MG)
df = df[(df["asset"]=="BTC") & (df["tf"]=="5m")].sort_values("fire_us").reset_index(drop=True)
df["fire_dt"] = pd.to_datetime(df["fire_us"], unit="us", utc=True)
df["fire_date"] = df["fire_dt"].dt.date
g_cols = [c for c in df.columns if c.startswith("g_")]
for c in g_cols:
    df[c] = df[c].fillna(0).astype(np.int8)

robust = pd.read_csv(OUT / "robust_candidates.csv")
print(f"Robust candidates: {len(robust)}")

# Top 5 by rank_score
top5 = robust.sort_values("rank_score", ascending=False).head(5).reset_index(drop=True)
print()
print("Top 5 selected (by rank_score):")
print(top5[["sleeve_id","gate_stack","n_lockbox","wr_lockbox","dpt_25_lockbox","max_dd_25_lockbox","loss_streak_lockbox","sharpe_lockbox","bootstrap_p_max","rank_score"]].to_string(index=False))

ts_min = df["fire_us"].min()
ts_max = df["fire_us"].max()
span = ts_max - ts_min
cut1 = ts_min + int(span * 15.0/24.8)
cut2 = ts_min + int(span * 20.0/24.8)


def mask_from_stack(df, stack_str):
    m = np.ones(len(df), dtype=bool)
    for g in stack_str.split("+"):
        if g in df.columns:
            m &= (df[g].values == 1)
    return m


def parse_anchor(sleeve_id):
    if sleeve_id.startswith("offset_") and "|" in sleeve_id:
        head = sleeve_id.split("|")[0]
        if head.startswith("offset_s"):
            o = int(head[len("offset_s"):])
            return lambda df: df["fire_offset_s"].values == o, head
        elif head.startswith("offset_"):
            b = head[len("offset_"):]
            return lambda df: df["offset_bin"].values == b, head
    if "+r" in sleeve_id and sleeve_id.split("|")[0].startswith(("s15_", "s6_")):
        sleeve_part = sleeve_id.split("+r")[0]
        return lambda df, sp=sleeve_part: df["sleeve_id"].str.startswith(sp + "|").values, sleeve_part
    return None, sleeve_id


def safe_id(s):
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", s)[:80]


# Generate plots and finalize
final_rows = []
for i, row in top5.iterrows():
    sid = row["sleeve_id"]
    stack = row["gate_stack"]
    gate_mask = mask_from_stack(df, stack)
    parsed = parse_anchor(sid)
    if parsed[0]:
        anchor_mask = parsed[0](df)
        anchor_name = parsed[1]
        mask = gate_mask & anchor_mask
    else:
        anchor_name = sid
        mask = gate_mask
    sub = df[mask].sort_values("fire_us")
    print(f"\n=== Candidate {i+1}: {sid} ===")
    print(f"  Anchor: {anchor_name}")
    print(f"  Gates: {stack}")
    print(f"  n_full: {len(sub)}")
    print(f"  WR full: {sub['won_int'].mean():.3f}")

    # Cumulative PnL plot
    pnl = sub["pnl_legacy_usd"].values * PNL_SCALE
    cum = np.cumsum(pnl)
    dt = pd.to_datetime(sub["fire_us"], unit="us", utc=True)
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(dt, cum, lw=1.3, color="navy")
    ax.fill_between(dt, cum, 0, where=(cum >= 0), color="green", alpha=0.15)
    ax.fill_between(dt, cum, 0, where=(cum < 0), color="red", alpha=0.15)
    cut1_dt = pd.to_datetime(cut1, unit="us", utc=True)
    cut2_dt = pd.to_datetime(cut2, unit="us", utc=True)
    ax.axvline(cut1_dt, color="gray", ls="--", alpha=0.7, label="train|val")
    ax.axvline(cut2_dt, color="red", ls="--", alpha=0.7, label="val|lockbox")
    ax.set_title(f"#{i+1} {anchor_name} | {stack}\nWR_lb={row['wr_lockbox']:.3f}  $/tr_lb=${row['dpt_25_lockbox']:.2f}  DD_lb=${row['max_dd_25_lockbox']:.2f}  n_lb={int(row['n_lockbox'])}")
    ax.set_xlabel("Date (UTC)")
    ax.set_ylabel("Cumulative PnL ($, $25 stake)")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left")
    fig.autofmt_xdate()
    fig_path = OUT / f"cumulative_pnl_top{i+1}_{safe_id(stack)[:50]}.png"
    fig.savefig(fig_path, dpi=110, bbox_inches="tight")
    plt.close(fig)
    print(f"  PNG: {fig_path.name}")

    # Per-day fire histogram
    sub["fire_date"] = sub["fire_dt"].dt.date
    daily = sub.groupby("fire_date").size()
    fig2, ax2 = plt.subplots(figsize=(11, 4))
    ax2.bar(daily.index, daily.values, color="steelblue")
    rate = len(sub) / 24.8
    ax2.axhline(rate, color="red", ls="--", label=f"avg = {rate:.1f}/day")
    ax2.set_title(f"Per-day fires — #{i+1} {anchor_name} | {stack}")
    ax2.set_xlabel("Date (UTC)")
    ax2.set_ylabel("# fires")
    ax2.grid(alpha=0.3)
    ax2.legend()
    fig2.autofmt_xdate()
    hist_path = OUT / f"per_day_fires_top{i+1}_{safe_id(stack)[:50]}.png"
    fig2.savefig(hist_path, dpi=110, bbox_inches="tight")
    plt.close(fig2)
    print(f"  Histogram PNG: {hist_path.name}")

    final_rows.append({
        "rank": i+1,
        "sleeve_id": sid,
        "anchor": anchor_name,
        "gate_stack": stack,
        "n_train": int(row["n_train"]),
        "n_val": int(row["n_val"]),
        "n_lockbox": int(row["n_lockbox"]),
        "n_32d_proj": float(row["n_32d_proj"]),
        "wr_train": float(row["wr_train"]),
        "wr_val": float(row["wr_val"]),
        "wr_lockbox": float(row["wr_lockbox"]),
        "lb_h1_wr": float(row["lb_h1_wr"]),
        "lb_h2_wr": float(row["lb_h2_wr"]),
        "dpt_25_train": float(row["dpt_25_train"]),
        "dpt_25_val": float(row["dpt_25_val"]),
        "dpt_25_lockbox": float(row["dpt_25_lockbox"]),
        "lb_h1_dpt": float(row["lb_h1_dpt"]),
        "lb_h2_dpt": float(row["lb_h2_dpt"]),
        "sum_25_28d": float(row["sum_25_full"]),  # using 24.8d full window total
        "max_dd_25": float(row["max_dd_25_lockbox"]),
        "loss_streak": int(row["loss_streak_lockbox"]),
        "sharpe": float(row["sharpe_lockbox"]),
        "bootstrap_p_lockbox": float(row["bootstrap_p_max"]),
        "lb_n_days": int(row["lb_n_days"]),
        "lb_pos_days": int(row["lb_pos_days"]),
        "lb_pct_pos_days": float(row["lb_pct_pos_days"]),
        "confidence": "HIGH" if row["bootstrap_p_max"] <= 0.01 and row["lb_pct_pos_days"] >= 0.8 else "MED",
    })

out_top5 = pd.DataFrame(final_rows)
out_top5.to_csv(OUT / "top_5_candidates.csv", index=False)
print(f"\n✓ Saved top_5_candidates.csv ({len(out_top5)} rows)")
print()
print("Final top 5:")
print(out_top5[["rank","sleeve_id","gate_stack","n_lockbox","wr_lockbox","dpt_25_lockbox","max_dd_25","loss_streak","sharpe","bootstrap_p_lockbox","confidence"]].to_string(index=False))
