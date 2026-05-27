"""
Re-validate top sniper candidates with extra rigor:
  - Sub-window stability within lockbox (split lockbox in half)
  - Bootstrap p with 3 different seeds (consistency check)
  - Visualize cumulative PnL
  - Re-check against per-day distribution

Identify TRULY robust candidates from the 2068 passers.
"""
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(r"C:/Users/alexandre bandarra/Desktop/global")
OUT  = ROOT / "strategy_lab/sniper_search_2026_05_27/btc_5m"
MG = ROOT / "data/v4/canonical/_results/master_gate_features_v2.parquet"

ASSET, TF = "BTC", "5m"
PNL_SCALE = 1.0

# Load universe
df = pd.read_parquet(MG)
df = df[(df["asset"]==ASSET) & (df["tf"]==TF)].sort_values("fire_us").reset_index(drop=True)
df["fire_dt"] = pd.to_datetime(df["fire_us"], unit="us", utc=True)
df["fire_date"] = df["fire_dt"].dt.date
g_cols = [c for c in df.columns if c.startswith("g_")]
for c in g_cols:
    df[c] = df[c].fillna(0).astype(np.int8)
df["won_int"] = df["won_int"].fillna(0).astype(np.int8)

# Load all candidates
cands = pd.read_csv(OUT / "all_candidates.csv")
passers = cands[cands["pass"]].copy()
print(f"Total passers: {len(passers)}")

# Split utility
def split_24_8(df):
    ts_min = df["fire_us"].min()
    ts_max = df["fire_us"].max()
    span = ts_max - ts_min
    cut1 = ts_min + int(span * 15.0 / 24.8)
    cut2 = ts_min + int(span * 20.0 / 24.8)
    tr = df[df["fire_us"] < cut1].copy()
    va = df[(df["fire_us"] >= cut1) & (df["fire_us"] < cut2)].copy()
    lb = df[df["fire_us"] >= cut2].copy()
    return tr, va, lb, cut1, cut2

tr, va, lb, cut1, cut2 = split_24_8(df)
ts_max = df["fire_us"].max()
# Split lockbox in half
lb_mid = (cut2 + ts_max) // 2
print(f"Lockbox span: {pd.to_datetime(cut2, unit='us', utc=True)} -> {pd.to_datetime(ts_max, unit='us', utc=True)}")
print(f"  half1: ends {pd.to_datetime(lb_mid, unit='us', utc=True)}")
print(f"  half2: starts after {pd.to_datetime(lb_mid, unit='us', utc=True)}")
print()


def mask_from_stack(df, stack_str):
    """Apply gate stack string to df. Returns bool mask."""
    gates = stack_str.split("+")
    m = np.ones(len(df), dtype=bool)
    for g in gates:
        if g in df.columns:
            m &= (df[g].values == 1)
        else:
            return None  # unknown gate
    return m


def slice_with_filter(df, mask, filter_fn=None):
    """Apply mask + optional additional filter (e.g., offset bin)."""
    if filter_fn is None:
        return df[mask]
    keep = mask & filter_fn(df)
    return df[keep]


def evaluate_subwindow_stability(df, mask, anchor):
    """Within lockbox, split in half and check both halves are positive."""
    sub_lb = df[mask & df["fire_us"].between(cut2, ts_max, inclusive="both")]
    h1 = sub_lb[sub_lb["fire_us"] < lb_mid]
    h2 = sub_lb[sub_lb["fire_us"] >= lb_mid]
    out = dict(
        lb_total_n=len(sub_lb),
        lb_h1_n=len(h1),
        lb_h2_n=len(h2),
        lb_h1_wr=h1["won_int"].mean() if len(h1) else 0,
        lb_h2_wr=h2["won_int"].mean() if len(h2) else 0,
        lb_h1_dpt=h1["pnl_legacy_usd"].mean() * PNL_SCALE if len(h1) else 0,
        lb_h2_dpt=h2["pnl_legacy_usd"].mean() * PNL_SCALE if len(h2) else 0,
    )
    return out


def bootstrap_p(sub_lb, n_iter=1000, seed=42):
    if len(sub_lb) < 5:
        return 1.0
    rng = np.random.default_rng(seed)
    pnl = sub_lb["pnl_legacy_usd"].values * PNL_SCALE
    fd = sub_lb["fire_date"].values
    from collections import defaultdict
    by_day = defaultdict(list)
    for p, d in zip(pnl, fd):
        by_day[d].append(p)
    days = list(by_day.keys())
    arrs = [np.array(by_day[d]) for d in days]
    n_days = len(arrs)
    if n_days < 2:
        return 1.0
    boot_means = np.empty(n_iter)
    for i in range(n_iter):
        idx = rng.integers(0, n_days, n_days)
        pooled = np.concatenate([arrs[j] for j in idx])
        boot_means[i] = pooled.mean() if len(pooled) else 0.0
    return float((boot_means <= 0).mean())


def parse_anchor(sleeve_id):
    """Returns a filter function based on the sleeve_id's anchor encoding."""
    # offset_240-300, offset_s240, sleeve|240-300+r2|..., greedy|... (no offset filter)
    if sleeve_id.startswith("offset_") and "|" in sleeve_id:
        # e.g. offset_240-300|r3 or offset_s240|r2|...
        head = sleeve_id.split("|")[0]
        if head.startswith("offset_s"):
            o = int(head[len("offset_s"):])
            return lambda df: df["fire_offset_s"].values == o, head
        elif head.startswith("offset_"):
            b = head[len("offset_"):]
            return lambda df: df["offset_bin"].values == b, head
    if "+r" in sleeve_id and sleeve_id.split("|")[0].startswith(("s15_", "s6_")):
        # sleeve-conditional, e.g. s15_5m|240-300+r3|gates
        sleeve_part = sleeve_id.split("+r")[0]  # e.g. s15_5m|240-300
        # rebuild like 's15_5m|240-300|...'
        # but actual sleeve_id in df is sleeve_id with extras
        # The original sleeve_id prefix is sleeve_part
        return lambda df, sp=sleeve_part: df["sleeve_id"].str.startswith(sp + "|").values, sleeve_part
    if sleeve_id.startswith("greedy|") or sleeve_id.startswith("single|") or sleeve_id.startswith("stack_"):
        return None, sleeve_id
    return None, sleeve_id


# Score and rank
results = []
for _, row in passers.iterrows():
    sleeve_id = row["sleeve_id"]
    stack = row["gate_stack"]
    mask = mask_from_stack(df, stack)
    if mask is None:
        continue
    parsed = parse_anchor(sleeve_id)
    if parsed[0]:
        anchor_filt, anchor_name = parsed
        mask = mask & anchor_filt(df)
    else:
        anchor_name = sleeve_id
    if mask.sum() < 30:
        continue

    # Sub-window stability
    stab = evaluate_subwindow_stability(df, mask, anchor_name)
    # Multi-seed bootstrap
    sub_lb = df[mask & df["fire_us"].between(cut2, ts_max, inclusive="both")]
    p42 = bootstrap_p(sub_lb, seed=42)
    p7 = bootstrap_p(sub_lb, seed=7)
    p100 = bootstrap_p(sub_lb, seed=20260527)
    p_mean = (p42 + p7 + p100) / 3
    p_max = max(p42, p7, p100)
    # Daily-positive count in lockbox
    daily_lb = sub_lb.groupby("fire_date")["pnl_legacy_usd"].agg(["mean","count"])
    n_days = len(daily_lb)
    n_pos_days = int((daily_lb["mean"] > 0).sum())
    pct_pos_days = n_pos_days / max(n_days, 1)

    results.append({
        **row.to_dict(),
        "lb_h1_n": stab["lb_h1_n"],
        "lb_h2_n": stab["lb_h2_n"],
        "lb_h1_wr": stab["lb_h1_wr"],
        "lb_h2_wr": stab["lb_h2_wr"],
        "lb_h1_dpt": stab["lb_h1_dpt"],
        "lb_h2_dpt": stab["lb_h2_dpt"],
        "bootstrap_p_42": p42,
        "bootstrap_p_7": p7,
        "bootstrap_p_20260527": p100,
        "bootstrap_p_mean": p_mean,
        "bootstrap_p_max": p_max,
        "lb_n_days": n_days,
        "lb_pos_days": n_pos_days,
        "lb_pct_pos_days": pct_pos_days,
    })

res = pd.DataFrame(results)
print(f"Re-validated {len(res)} candidates")

# Apply ROBUST filter:
# - h1 and h2 both WR >= 0.65 and dpt > 0
# - bootstrap p_max <= 0.05 (worst-case across seeds)
# - n_days >= 3 in lockbox
# - n_pos_days >= ceil(n_days * 0.6)
robust = res[
    (res["lb_h1_wr"] >= 0.65) & (res["lb_h2_wr"] >= 0.65) &
    (res["lb_h1_dpt"] > 0) & (res["lb_h2_dpt"] > 0) &
    (res["bootstrap_p_max"] <= 0.05) &
    (res["lb_n_days"] >= 3) &
    (res["lb_pct_pos_days"] >= 0.6)
].copy()
print(f"Robust passers (both halves positive WR, all 3 bootstrap p<=0.05, >=60% positive days): {len(robust)}")
print()

# Deduplicate near-identical candidates by (anchor, sorted gates)
robust["gates_sorted"] = robust["gate_stack"].apply(lambda s: "+".join(sorted(s.split("+"))))
# Also normalize sleeve_id to anchor portion
robust["anchor_norm"] = robust["sleeve_id"].apply(lambda s: s.split("|")[0])
robust = robust.drop_duplicates(subset=["anchor_norm", "gates_sorted"])
print(f"After dedup by (anchor, sorted gates): {len(robust)}")

# Rank
robust["rank_score"] = (
    robust["dpt_25_lockbox"]
    - 0.10 * robust["max_dd_25_lockbox"]
    + 50.0 * (robust["wr_lockbox"] - 0.75)
)
robust = robust.sort_values("rank_score", ascending=False)

cols_show = ["sleeve_id","gate_stack","n_full","n_train","n_val","n_lockbox","n_32d_proj",
             "wr_train","wr_val","wr_lockbox","lb_h1_wr","lb_h2_wr",
             "dpt_25_lockbox","lb_h1_dpt","lb_h2_dpt",
             "max_dd_25_lockbox","loss_streak_lockbox","sharpe_lockbox",
             "bootstrap_p_max","lb_n_days","lb_pos_days","lb_pct_pos_days","rank_score"]
print("Top 20 robust candidates:")
print(robust[cols_show].head(20).to_string(index=False))

robust.to_csv(OUT / "robust_candidates.csv", index=False)
print(f"\nSaved {len(robust)} robust candidates -> robust_candidates.csv")
