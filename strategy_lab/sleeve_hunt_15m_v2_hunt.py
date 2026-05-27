"""15m sleeve hunt v2 — full 32d window with strict 3-way validation.

Splits:
  Train:   May 1-14 (first 14 days)
  Val:     May 15-21 (7 days)
  Lockbox: May 22-25 (4 days)

Per cell: greedy stack on Train, then test on Val. If Val passes, test on
Lockbox. Final deployable = pass all 3.

Inputs:  data/v4/canonical/_results/sleeve_hunt_15m_full_features.parquet
Outputs:
  data/v4/canonical/_results/sleeve_hunt_15m_v2_all.csv
  data/v4/canonical/_results/sleeve_hunt_15m_v2_deployable.csv
  data/v4/canonical/_results/sleeve_hunt_15m_v2_r2_confirmation.csv
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"
sys.path.insert(0, str(ROOT / "strategy_lab"))


# ---------------------------------------------------------------------------
# Splits
# ---------------------------------------------------------------------------

TRAIN_END_US = int(pd.Timestamp("2026-05-15T00:00:00Z").value // 1000)
VAL_END_US = int(pd.Timestamp("2026-05-22T00:00:00Z").value // 1000)
LOCKBOX_END_US = int(pd.Timestamp("2026-05-26T00:00:00Z").value // 1000)


def split_train_val_lockbox(df: pd.DataFrame):
    train = df[df["fire_us"] < TRAIN_END_US]
    val = df[(df["fire_us"] >= TRAIN_END_US) & (df["fire_us"] < VAL_END_US)]
    lockbox = df[(df["fire_us"] >= VAL_END_US) & (df["fire_us"] < LOCKBOX_END_US)]
    return train, val, lockbox


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def cell_summary(df: pd.DataFrame, pnl_col: str = "pnl_legacy_usd") -> dict:
    n = len(df)
    if n == 0:
        return {"n": 0, "wins": 0, "WR": float("nan"), "sum_pnl": 0.0,
                "dpt": float("nan"), "max_DD": 0.0, "loss_streak": 0,
                "sharpe_d": float("nan"), "n_days": 0}
    pnl = df[pnl_col].astype("float64").values
    wins = int((pnl > 0).sum())
    s = df.sort_values("fire_us")
    cum = s[pnl_col].cumsum().values
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    max_DD = float(dd.max()) if len(dd) else 0.0
    loss = (s[pnl_col].values <= 0).astype("int8")
    max_streak = 0; cur = 0
    for x in loss:
        if x:
            cur += 1
            if cur > max_streak: max_streak = cur
        else:
            cur = 0
    day = pd.to_datetime(s["fire_us"], unit="us", utc=True).dt.floor("D")
    daily = s.assign(_day=day).groupby("_day")[pnl_col].sum()
    n_days = int(daily.shape[0])
    sharpe = float("nan")
    if n_days > 1:
        mu = float(daily.mean()); sig = float(daily.std(ddof=1))
        sharpe = mu / sig * math.sqrt(n_days) if sig and sig > 0 else float("nan")
    return {"n": n, "wins": wins, "WR": wins / n, "sum_pnl": float(pnl.sum()),
            "dpt": float(pnl.mean()), "max_DD": max_DD, "loss_streak": int(max_streak),
            "sharpe_d": sharpe, "n_days": n_days}


def apply_gate_stack(df: pd.DataFrame, gates: list[str]) -> pd.DataFrame:
    if not gates:
        return df
    mask = np.ones(len(df), dtype=bool)
    for g in gates:
        if g not in df.columns:
            return df.iloc[:0]
        mask &= df[g].fillna(False).astype(bool).values
    return df.iloc[mask]


def bootstrap_p_value(pnl: np.ndarray, n_shuffles: int = 500,
                       rng_seed: int = 42) -> float:
    n = len(pnl)
    if n < 20:
        return float("nan")
    observed = float(pnl.sum())
    rng = np.random.default_rng(rng_seed)
    # Sign-flip bootstrap: null is direction irrelevant
    flips = rng.choice([-1.0, 1.0], size=(n_shuffles, n))
    shuffled_sums = (flips * pnl[None, :]).sum(axis=1)
    p = float((shuffled_sums >= observed).mean())
    return p


# ---------------------------------------------------------------------------
# Offset bins
# ---------------------------------------------------------------------------

OFFSET_BINS = [
    ("60-120", 60, 120),
    ("120-240", 120, 240),
    ("240-360", 240, 360),
    ("360-480", 360, 480),
    ("480-600", 480, 600),
    ("600-720", 600, 720),
    ("720-840", 720, 840),
    ("ge_840", 840, 841),
]


def offset_bin_label(off: int) -> str:
    for label, lo, hi in OFFSET_BINS:
        if lo <= off < hi:
            return label
    if off == 840:
        return "ge_840"
    return None


# ---------------------------------------------------------------------------
# Greedy gate search
# ---------------------------------------------------------------------------

MIN_N_TRAIN = 30
MIN_N_CELL = 50  # need at least 50 train fires per cell


def greedy_stack(df: pd.DataFrame, candidates: list[str],
                  pnl_col: str = "pnl_legacy_usd",
                  min_n: int = MIN_N_TRAIN, max_k: int = 5) -> list[str]:
    chosen: list[str] = []
    remaining = [c for c in candidates if c in df.columns]
    pnl_arr = df[pnl_col].astype("float64").values
    mask = np.ones(len(df), dtype=bool)
    best_sum = float(pnl_arr.sum())
    while remaining and len(chosen) < max_k:
        best_gate = None
        best_score = -1e18
        best_sum_new = best_sum
        for g in remaining:
            m_g = df[g].fillna(False).astype(bool).values
            m_new = mask & m_g
            n_new = int(m_new.sum())
            if n_new < min_n:
                continue
            pnl_new = pnl_arr[m_new]
            wins = int((pnl_new > 0).sum())
            sum_pnl = float(pnl_new.sum())
            wr = wins / n_new
            # Score: sum_pnl * WR favours high-WR + edge
            score = sum_pnl * wr
            if score > best_score:
                best_score = score
                best_gate = g
                best_sum_new = sum_pnl
        if best_gate is None or best_sum_new <= best_sum:
            break
        chosen.append(best_gate)
        remaining.remove(best_gate)
        mask &= df[best_gate].fillna(False).astype(bool).values
        best_sum = best_sum_new
    return chosen


def run_train_val_lockbox(df_train, df_val, df_lockbox, candidates,
                            label, full_pool=None,
                            pnl_col: str = "pnl_legacy_usd"):
    """Greedy-search on train (multiple seeds), validate on val, lockbox.

    Multi-seed greedy: also try locking-in each top-3 single-gate as the first
    step (instead of always picking the global-best). Yields up to 4 stacks
    per cell.

    Returns list of dicts per cell.
    """
    rows = []
    # Baseline
    s_train = cell_summary(df_train, pnl_col)
    s_val = cell_summary(df_val, pnl_col)
    s_lb = cell_summary(df_lockbox, pnl_col)
    base = {**label, "gate_stack": "(baseline)", "k": 0}
    for prefix, st in (("train", s_train), ("val", s_val), ("lockbox", s_lb)):
        for k, v in st.items():
            base[f"{prefix}_{k}"] = v
    rows.append(base)

    if len(df_train) < MIN_N_CELL or not candidates:
        return rows

    # Greedy on train
    avail = [c for c in candidates if c in df_train.columns and df_train[c].sum() > 0]
    if not avail:
        return rows

    # Top-3 single-gate seeds — sort by sum_pnl
    pnl_arr = df_train[pnl_col].astype("float64").values
    singles = []
    for g in avail:
        m = df_train[g].fillna(False).astype(bool).values
        if m.sum() < MIN_N_TRAIN:
            continue
        p = pnl_arr[m]
        singles.append((g, m.sum(), p.sum(), (p > 0).mean()))
    singles.sort(key=lambda x: -(x[2] * x[3]))
    seeds = [None] + [s[0] for s in singles[:3]]

    stacks_seen = set()
    for seed in seeds:
        if seed is None:
            chosen = greedy_stack(df_train, avail, pnl_col=pnl_col,
                                    min_n=MIN_N_TRAIN, max_k=5)
        else:
            # Force-start with seed
            chosen = [seed]
            remaining = [c for c in avail if c != seed]
            mask = df_train[seed].fillna(False).astype(bool).values
            best_sum = float(pnl_arr[mask].sum())
            while remaining and len(chosen) < 5:
                best_gate = None
                best_score = -1e18
                best_sum_new = best_sum
                for g in remaining:
                    m_g = df_train[g].fillna(False).astype(bool).values
                    m_new = mask & m_g
                    n_new = int(m_new.sum())
                    if n_new < MIN_N_TRAIN:
                        continue
                    pnl_new = pnl_arr[m_new]
                    wins = int((pnl_new > 0).sum())
                    sum_pnl = float(pnl_new.sum())
                    wr = wins / n_new
                    score = sum_pnl * wr
                    if score > best_score:
                        best_score = score
                        best_gate = g
                        best_sum_new = sum_pnl
                if best_gate is None or best_sum_new <= best_sum:
                    break
                chosen.append(best_gate)
                remaining.remove(best_gate)
                mask &= df_train[best_gate].fillna(False).astype(bool).values
                best_sum = best_sum_new
        if not chosen:
            continue
        key = "&".join(sorted(chosen))
        if key in stacks_seen:
            continue
        stacks_seen.add(key)

        tr_sub = apply_gate_stack(df_train, chosen)
        val_sub = apply_gate_stack(df_val, chosen)
        lb_sub = apply_gate_stack(df_lockbox, chosen)
        s_train = cell_summary(tr_sub, pnl_col)
        s_val = cell_summary(val_sub, pnl_col)
        s_lb = cell_summary(lb_sub, pnl_col)
        p_lockbox = bootstrap_p_value(lb_sub[pnl_col].values) if s_lb["n"] >= 15 else float("nan")
        p_val = bootstrap_p_value(val_sub[pnl_col].values) if s_val["n"] >= 15 else float("nan")

        row = {**label, "gate_stack": "&".join(chosen), "k": len(chosen),
                "seed": seed if seed else "global_greedy"}
        for prefix, st in (("train", s_train), ("val", s_val), ("lockbox", s_lb)):
            for k, v in st.items():
                row[f"{prefix}_{k}"] = v
        row["val_p"] = p_val
        row["lockbox_p"] = p_lockbox
        # Pass criteria — stricter now
        row["val_pass"] = (s_val["n"] >= 15 and s_val["sum_pnl"] > 0 and s_val["WR"] >= 0.65)
        row["lockbox_pass"] = (s_lb["n"] >= 10 and s_lb["sum_pnl"] > 0 and
                                 s_lb["WR"] >= 0.60 and (np.isnan(p_lockbox) or p_lockbox < 0.10))
        row["deployable"] = row["val_pass"] and row["lockbox_pass"]
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Main hunt — per (asset, offset_bin) cell + pooled + late-fire dev buckets
# ---------------------------------------------------------------------------

# Gate candidate priors — use ONLY common gates (available on both R2 + lockbox)
COMMON_CANDIDATES = [
    # Regime panel gates (15m)
    "g_adx_strong", "g_adx_extreme",
    "g_di_with",
    "g_tr_stack_with", "g_tr_stack_full_with",
    "g_ribbon_high_align", "g_ribbon_med_align",
    "g_bb_compressed", "g_bb_wide",
    "g_vol_high", "g_vol_low", "g_vol_expanding",
    "g_range_compressed",
    "g_trend_slope_with", "g_trend_slope_strong_with",
    "g_regime_trend", "g_regime_range", "g_regime_vol",
    # dev / vwap zones
    "g_dev_5_10", "g_dev_10_15", "g_dev_15_20", "g_dev_20_30", "g_dev_30_plus",
    "g_dev_ge_10", "g_dev_ge_15", "g_dev_ge_20",
    "g_dev_extreme", "g_within_dev",
    "g_vwap_low", "g_vwap_55_70", "g_vwap_70_85", "g_vwap_le_70",
    "g_vwap_ge_50_le_85", "g_vwap_ge_30",
]


def sweep_per_cell(df: pd.DataFrame, candidates: list[str]) -> pd.DataFrame:
    df = df.copy()
    df["offset_bin"] = df["fire_offset_s"].astype("int64").apply(offset_bin_label)
    df = df[df["offset_bin"].notna()].copy()
    out = []
    for asset in ("BTC", "ETH", "SOL"):
        for ob, _, _ in OFFSET_BINS:
            sub = df[(df.asset == asset) & (df.offset_bin == ob)]
            if len(sub) < MIN_N_CELL:
                continue
            tr, vl, lb = split_train_val_lockbox(sub)
            if len(tr) < MIN_N_CELL:
                continue
            label = {"asset": asset, "offset_bin": ob, "pool": "per_asset",
                      "n_total": len(sub), "n_train": len(tr), "n_val": len(vl),
                      "n_lockbox": len(lb)}
            rows = run_train_val_lockbox(tr, vl, lb, candidates, label)
            out.extend(rows)
            print(f"  {asset} {ob}: total={len(sub)} train={len(tr)} val={len(vl)} lb={len(lb)} → {len(rows)} stacks")
    return pd.DataFrame(out)


def sweep_pooled(df: pd.DataFrame, candidates: list[str]) -> pd.DataFrame:
    df = df.copy()
    df["offset_bin"] = df["fire_offset_s"].astype("int64").apply(offset_bin_label)
    df = df[df["offset_bin"].notna()].copy()
    out = []
    for ob, _, _ in OFFSET_BINS:
        sub = df[df.offset_bin == ob]
        if len(sub) < MIN_N_CELL:
            continue
        tr, vl, lb = split_train_val_lockbox(sub)
        if len(tr) < MIN_N_CELL:
            continue
        label = {"asset": "POOL", "offset_bin": ob, "pool": "pooled_all",
                  "n_total": len(sub), "n_train": len(tr), "n_val": len(vl),
                  "n_lockbox": len(lb)}
        rows = run_train_val_lockbox(tr, vl, lb, candidates, label)
        out.extend(rows)
        print(f"  POOL {ob}: total={len(sub)} train={len(tr)} val={len(vl)} lb={len(lb)} → {len(rows)} stacks")
    return pd.DataFrame(out)


def sweep_late_dev(df: pd.DataFrame, candidates: list[str]) -> pd.DataFrame:
    df = df.copy()
    df["abs_dev_bps"] = df["dev_bps"].abs() if "dev_bps" in df.columns else 0
    out = []
    dev_buckets = [
        ("dev_5_10", 5.0, 10.0), ("dev_10_15", 10.0, 15.0),
        ("dev_15_20", 15.0, 20.0), ("dev_20_30", 20.0, 30.0),
        ("dev_30+", 30.0, 999.0),
        ("dev_ge_10", 10.0, 999.0), ("dev_ge_15", 15.0, 999.0),
        ("dev_ge_20", 20.0, 999.0),
    ]
    for offset_floor in [480, 600, 720, 840]:
        for asset in ("BTC", "ETH", "SOL", "POOL"):
            for db_label, lo, hi in dev_buckets:
                sub = df[(df.fire_offset_s >= offset_floor) &
                          (df["abs_dev_bps"] >= lo) & (df["abs_dev_bps"] < hi)]
                if asset != "POOL":
                    sub = sub[sub.asset == asset]
                if len(sub) < 30:
                    continue
                tr, vl, lb = split_train_val_lockbox(sub)
                if len(tr) < 25:
                    continue
                label = {"asset": asset, "offset_bin": f"ge_{offset_floor}",
                          "pool": "late_dev_" + db_label,
                          "n_total": len(sub), "n_train": len(tr),
                          "n_val": len(vl), "n_lockbox": len(lb)}
                rows = run_train_val_lockbox(tr, vl, lb, candidates, label)
                out.extend(rows)
    return pd.DataFrame(out)


# ---------------------------------------------------------------------------
# R2 confirmation
# ---------------------------------------------------------------------------

def confirm_r2_sleeves(df_full: pd.DataFrame, r2_path: Path) -> pd.DataFrame:
    """For each R2 deployable, evaluate its gate stack:
    - Full R2 stack on R2 window (May 1-21): "ref_repro"
    - For OOS lockbox: try (a) full stack if all gates present in lockbox,
      else (b) only the COMMON gate subset that exists on both windows.
    """
    # Which gates are "lockbox-valid" — i.e. exist + have at least 1 True in lockbox
    lockbox_data = df_full[df_full["window"] == "lockbox"]
    lockbox_gates = set()
    for c in lockbox_data.columns:
        if c.startswith("g_"):
            # In our concat we padded missing gates as False. A gate has 0 True
            # in lockbox if it was R2-only. Use this to detect actually-available.
            if lockbox_data[c].fillna(False).astype(bool).sum() > 0:
                lockbox_gates.add(c)
    print(f"  Lockbox-valid gates: {len(lockbox_gates)}")

    r2 = pd.read_csv(r2_path)
    print(f"\n[R2 confirmation] {len(r2)} R2 sleeves")
    out = []
    for i, row in r2.iterrows():
        gates = [g for g in row["gate_stack"].split("&") if g]
        asset = row["asset"]; ob = row["offset_bin"]; pool = row["pool"]

        # Reconstruct cell on FULL panel
        df_full2 = df_full.copy()
        df_full2["ob"] = df_full2["fire_offset_s"].astype("int64").apply(offset_bin_label)
        if pool == "per_asset":
            sub = df_full2[(df_full2.asset == asset) & (df_full2.ob == ob)].copy()
        elif pool == "pooled_all":
            sub = df_full2[df_full2.ob == ob].copy()
        elif str(pool).startswith("late_dev_"):
            db_str = pool.replace("late_dev_", "")
            buckets = {
                "dev_5_10": (5,10), "dev_10_15": (10,15), "dev_15_20": (15,20),
                "dev_20_30": (20,30), "dev_30+": (30,999),
                "dev_ge_10": (10,999), "dev_ge_15": (15,999), "dev_ge_20": (20,999),
                "devgeto10": (10,999),
            }
            lo, hi = buckets.get(db_str, (0, 999))
            floor = int(ob.replace("ge_", ""))
            sub = df_full2.copy()
            sub["abs_dev_bps"] = sub["dev_bps"].abs() if "dev_bps" in sub.columns else 0
            sub = sub[(sub["fire_offset_s"] >= floor) &
                       (sub["abs_dev_bps"] >= lo) & (sub["abs_dev_bps"] < hi)]
            if asset != "POOL":
                sub = sub[sub.asset == asset]
        else:
            sub = df_full2

        # Identify lockbox-only-valid subset of gates
        # R2-only gates: NOT in lockbox_gates → can't filter on lockbox
        r2_only = [g for g in gates if g not in lockbox_gates]
        common = [g for g in gates if g in lockbox_gates]

        # Reproduce on R2 part only — should match the R2 csv numbers
        r2_subset = sub[sub["window"] == "R2_train_val"]
        r2_gated = apply_gate_stack(r2_subset, gates)
        s_r2 = cell_summary(r2_gated)

        # Train/val on R2 portion
        train_r2 = r2_gated[r2_gated["fire_us"] < TRAIN_END_US]
        val_r2 = r2_gated[r2_gated["fire_us"] >= TRAIN_END_US]
        s_train = cell_summary(train_r2)
        s_val = cell_summary(val_r2)

        # Lockbox: use only common gates if there are any R2-only
        lockbox_subset = sub[sub["window"] == "lockbox"]
        lockbox_eval_gates = common if r2_only else gates
        lockbox_gated = apply_gate_stack(lockbox_subset, lockbox_eval_gates)
        s_lb = cell_summary(lockbox_gated)
        p_lb = bootstrap_p_value(lockbox_gated["pnl_legacy_usd"].values) if s_lb["n"] >= 20 else np.nan

        # Status
        # If ALL R2 gates available in lockbox, we can validate properly.
        # If some R2 gates dropped, the test is on a relaxed stack — note as
        # "BACKGATE_TEST" since we're effectively diluting the original sleeve.
        backgate_test = bool(r2_only)
        if s_lb["n"] < 5:
            status = "INSUFFICIENT_LOCKBOX_N"
        elif s_lb["sum_pnl"] > 0 and s_lb["WR"] >= 0.65:
            status = "CONFIRMED" + ("_BACKGATE" if backgate_test else "")
        elif s_lb["sum_pnl"] > 0 and s_lb["WR"] >= 0.55:
            status = "DEGRADED" + ("_BACKGATE" if backgate_test else "")
        else:
            status = "FAILED_OOS" + ("_BACKGATE" if backgate_test else "")

        out.append({
            "sleeve_id": row["sleeve_id"], "asset": asset, "offset_bin": ob,
            "pool": pool, "gate_stack": row["gate_stack"],
            "ref_n": row["n"], "ref_WR": row["WR"], "ref_dpt": row["dpt"],
            "ref_sum": row["sum_pnl"],
            "lockbox_eval_gates": "&".join(lockbox_eval_gates) if lockbox_eval_gates else "",
            "r2_only_gates_dropped": "&".join(r2_only),
            "status": status,
            "r2_repro_n": s_r2["n"], "r2_repro_WR": s_r2["WR"],
            "r2_repro_dpt": s_r2["dpt"], "r2_repro_sum": s_r2["sum_pnl"],
            "train_n": s_train["n"], "train_WR": s_train["WR"],
            "train_dpt": s_train["dpt"], "train_sum": s_train["sum_pnl"],
            "val_n": s_val["n"], "val_WR": s_val["WR"],
            "val_dpt": s_val["dpt"], "val_sum": s_val["sum_pnl"],
            "lockbox_n": s_lb["n"], "lockbox_WR": s_lb["WR"],
            "lockbox_dpt": s_lb["dpt"], "lockbox_sum": s_lb["sum_pnl"],
            "lockbox_p": p_lb,
        })
    return pd.DataFrame(out)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    t0 = time.time()
    print("=" * 80)
    print("SLEEVE HUNT 15M V2 — FULL WINDOW (32d) WITH STRICT 3-WAY VALIDATION")
    print("=" * 80)

    df = pd.read_parquet(RES / "sleeve_hunt_15m_full_features.parquet")
    print(f"\nFull panel: {df.shape}")
    print(f"by window: {df['window'].value_counts().to_dict()}")
    ts = pd.to_datetime(df["fire_us"], unit="us", utc=True)
    print(f"span: {ts.min()} -> {ts.max()}")

    tr, vl, lb = split_train_val_lockbox(df)
    print(f"\nSplit sizes:")
    print(f"  Train (< May 15): {len(tr):,}")
    print(f"  Val   (May 15-21): {len(vl):,}")
    print(f"  Lockbox (May 22-25): {len(lb):,}")

    candidates = [c for c in COMMON_CANDIDATES if c in df.columns]
    print(f"\nCommon candidates: {len(candidates)}")

    # Sweep 1
    print("\n--- SWEEP 1: per-asset × offset bin ---")
    s1 = sweep_per_cell(df, candidates)
    print(f"  {len(s1)} rows")

    # Sweep 2
    print("\n--- SWEEP 2: pooled ---")
    s2 = sweep_pooled(df, candidates)
    print(f"  {len(s2)} rows")

    # Sweep 3
    print("\n--- SWEEP 3: late-fire dev buckets ---")
    s3 = sweep_late_dev(df, candidates)
    print(f"  {len(s3)} rows")

    all_results = pd.concat([s1, s2, s3], ignore_index=True)
    print(f"\nTotal: {len(all_results)} rows")
    out_all = RES / "sleeve_hunt_15m_v2_all.csv"
    all_results.to_csv(out_all, index=False)
    print(f"Saved {out_all}")

    # Deployable filter
    if "deployable" in all_results.columns:
        deploy = all_results[(all_results["deployable"] == True) &
                              (all_results["gate_stack"] != "(baseline)")].copy()
        print(f"\nDeployable (val_pass + lockbox_pass): {len(deploy)}")
        deploy = deploy.sort_values("lockbox_dpt", ascending=False).reset_index(drop=True)
        out_dep = RES / "sleeve_hunt_15m_v2_deployable.csv"
        deploy.to_csv(out_dep, index=False)
        print(f"Saved {out_dep}")
        if len(deploy):
            print(deploy[["asset","offset_bin","pool","gate_stack",
                          "n_total","train_n","train_WR","train_dpt",
                          "val_n","val_WR","val_dpt",
                          "lockbox_n","lockbox_WR","lockbox_dpt","lockbox_p"]].head(20).to_string())

    # R2 confirmation
    print("\n" + "=" * 80)
    print("R2 CONFIRMATION — testing 37 R2 sleeves on full 32d window + lockbox")
    print("=" * 80)
    r2_conf = confirm_r2_sleeves(df, RES / "sleeve_hunt_15m_deployable.csv")
    out_r2 = RES / "sleeve_hunt_15m_v2_r2_confirmation.csv"
    r2_conf.to_csv(out_r2, index=False)
    print(f"Saved {out_r2}")
    print("\nStatus breakdown:")
    print(r2_conf["status"].value_counts())

    print(f"\n=== DONE in {time.time()-t0:.1f}s ===")


if __name__ == "__main__":
    main()
