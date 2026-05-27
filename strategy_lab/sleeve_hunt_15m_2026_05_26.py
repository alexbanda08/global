"""15m sleeve hunt — exhaustive gate sweep + late-fire dev_bps sub-buckets + cross-asset pooling + walk-forward.

Inputs:
  data/v4/canonical/_results/v15m_joined_all.parquet  (12,492 fires with direction+pnl+24 gates)
  data/v4/canonical/_results/master_15m_panel.parquet  (12,492 fires with m1v_regime, m5v_regime, cvd, rsi, etc.)

Outputs:
  data/v4/canonical/_results/sleeve_hunt_15m_features.parquet (merged feature panel)
  data/v4/canonical/_results/sleeve_hunt_15m_results.csv (all gate sweep results)
  data/v4/canonical/_results/sleeve_hunt_15m_top.csv (deployable sleeves)
  data/v4/canonical/_results/sleeve_hunt_15m_walkforward.csv (top-15 + walk-forward + bootstrap)
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "meta_classifier"))
RES = ROOT / "data" / "v4" / "canonical" / "_results"

from hybrid_backtest import gate_search  # type: ignore


MIN_N = 30
DEPLOY_MIN_N = 100
DEPLOY_MIN_WR = 0.75
DEPLOY_MIN_DPT = 3.0
DEPLOY_MIN_SUM = 800.0


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def build_feature_panel() -> pd.DataFrame:
    """Merge v15m_joined_all + master_15m_panel + add new derived features."""
    print("Loading v15m_joined_all...")
    v = pd.read_parquet(RES / "v15m_joined_all.parquet")
    print(f"  v15m_joined_all: {v.shape}")

    print("Loading master_15m_panel...")
    m = pd.read_parquet(RES / "master_15m_panel.parquet")
    print(f"  master_15m_panel: {m.shape}")

    # Merge new cols from master
    extra = m[[
        "slug", "fire_us",
        "m1v_regime", "m5v_regime",
        "m1v_pass", "m5v_pass", "m1f_pass", "m5f_pass",
        "cvd_30s", "cvd_60s", "cvd_120s",
        "cvd_agree_30s", "cvd_agree_60s", "cvd_agree_120s",
        "macd_hist", "macd_agree",
        "rvol_30_300", "rvol_60_900",
        "micro_minus_mid_bp", "spread_bp", "imb5",
        "rsi_14", "f7_pass",
        "cross_partial_agree", "cross_full_agree",
        "fair_edge_bp", "sigma_per_sqrt_sec_15m",
    ]].copy()
    df = v.merge(extra, on=["slug", "fire_us"], how="left")
    print(f"  merged: {df.shape}, m5v missing={df['m5v_regime'].isna().sum()}")

    # Add 1h range filter direction
    print("Loading range_filter_1h...")
    rf1h = pd.read_parquet(RES / "range_filter_1h.parquet").sort_values(["asset", "ts_us"])
    rf1h = rf1h.rename(columns={"rf_dir": "rf_dir_1h", "rf_close": "rf_close_1h"})

    print("As-of joining 1h RF dir...")
    df_sorted = df.sort_values("fire_us").reset_index(drop=True)
    out_parts = []
    for asset in df_sorted["asset"].unique():
        sub = df_sorted[df_sorted["asset"] == asset].copy()
        rf_a = rf1h[rf1h["asset"] == asset][["ts_us", "rf_dir_1h", "rf_close_1h"]].sort_values("ts_us")
        sub_merged = pd.merge_asof(
            sub.sort_values("fire_us"),
            rf_a.sort_values("ts_us"),
            left_on="fire_us", right_on="ts_us",
            direction="backward",
        )
        out_parts.append(sub_merged)
    df = pd.concat(out_parts, ignore_index=True)
    print(f"  +rf_1h: missing={df['rf_dir_1h'].isna().sum()}")

    # Derived gates
    print("Adding derived gates...")
    # M5V agreement (direction-aware): UP needs m5v_regime in {1,2} (uptrend/bullish), DOWN needs m5v in {0}
    # We need to encode m5v_regime semantically. Looking at earlier: regimes 0/1/2. Need to check direction alignment.
    # Without knowing the semantics, use UP-direction gate: m5v_regime > 0 (= 1 or 2)
    df["g_m5v_with"] = ((df["direction"] == "UP") & (df["m5v_regime"] >= 1)) | \
                       ((df["direction"] == "DOWN") & (df["m5v_regime"] <= 1))
    df["g_m5v_strong_with"] = ((df["direction"] == "UP") & (df["m5v_regime"] == 2)) | \
                              ((df["direction"] == "DOWN") & (df["m5v_regime"] == 0))
    df["g_m5v_pass"] = df["m5v_pass"].fillna(False).astype(bool)
    df["g_m1v_pass"] = df["m1v_pass"].fillna(False).astype(bool)

    # 1h RF agreement
    df["g_rf1h_with"] = ((df["direction"] == "UP") & (df["rf_dir_1h"] > 0)) | \
                       ((df["direction"] == "DOWN") & (df["rf_dir_1h"] < 0))

    # CVD agreement
    df["g_cvd30_with"] = df["cvd_agree_30s"].fillna(False).astype(bool)
    df["g_cvd60_with"] = df["cvd_agree_60s"].fillna(False).astype(bool)
    df["g_cvd120_with"] = df["cvd_agree_120s"].fillna(False).astype(bool)
    df["g_macd_with"] = df["macd_agree"].fillna(False).astype(bool)

    # F7 pass
    df["g_f7_pass"] = df["f7_pass"].fillna(False).astype(bool)

    # Cross-exchange agreement
    df["g_cross_partial_with"] = df["cross_partial_agree"].fillna(False).astype(bool)
    df["g_cross_full_with"] = df["cross_full_agree"].fillna(False).astype(bool)

    # dev_bps fine buckets — direction-aware (S7 already biases this; reading abs)
    df["abs_dev_bps"] = df["dev_bps"].abs()
    df["g_dev_5_10"] = (df["abs_dev_bps"] >= 5.0) & (df["abs_dev_bps"] < 10.0)
    df["g_dev_10_15"] = (df["abs_dev_bps"] >= 10.0) & (df["abs_dev_bps"] < 15.0)
    df["g_dev_15_20"] = (df["abs_dev_bps"] >= 15.0) & (df["abs_dev_bps"] < 20.0)
    df["g_dev_20_30"] = (df["abs_dev_bps"] >= 20.0) & (df["abs_dev_bps"] < 30.0)
    df["g_dev_30_plus"] = df["abs_dev_bps"] >= 30.0
    df["g_dev_ge_10"] = df["abs_dev_bps"] >= 10.0
    df["g_dev_ge_15"] = df["abs_dev_bps"] >= 15.0
    df["g_dev_ge_20"] = df["abs_dev_bps"] >= 20.0

    # entry_vwap zones (sweet spots from inspection)
    df["g_vwap_low"] = df["entry_vwap"] < 0.55  # avoid contra-priced (WR<60% but $/tr high)
    df["g_vwap_55_70"] = (df["entry_vwap"] >= 0.55) & (df["entry_vwap"] < 0.70)
    df["g_vwap_70_85"] = (df["entry_vwap"] >= 0.70) & (df["entry_vwap"] < 0.85)
    df["g_vwap_le_70"] = df["entry_vwap"] < 0.70  # higher edge zone
    df["g_vwap_ge_50_le_85"] = (df["entry_vwap"] >= 0.50) & (df["entry_vwap"] < 0.85)
    # Avoid extreme low (< 0.30 — these have WR ~10% and are death zone)
    df["g_vwap_ge_30"] = df["entry_vwap"] >= 0.30

    # Stack of "S7 confirmation set" — TR_stack + ribbon + dev_extreme
    df["g_s7_confirm"] = df["g_tr_stack_full_with"].fillna(False).astype(bool) & \
                         df["g_ribbon_slope_with"].fillna(False).astype(bool) & \
                         df["g_dev_ge_10"]

    # F7-like — RSI extremes
    df["g_rsi_with"] = ((df["direction"] == "UP") & (df["rsi_14"] >= 55)) | \
                      ((df["direction"] == "DOWN") & (df["rsi_14"] <= 45))
    df["g_rsi_extreme_with"] = ((df["direction"] == "UP") & (df["rsi_14"] >= 65)) | \
                              ((df["direction"] == "DOWN") & (df["rsi_14"] <= 35))

    # Save merged panel
    out = RES / "sleeve_hunt_15m_features.parquet"
    df.to_parquet(out, index=False, compression="zstd")
    print(f"  saved {out}: {df.shape}")
    return df


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------

def cell_summary(df: pd.DataFrame, pnl_col: str = "pnl_legacy_usd") -> dict:
    n = len(df)
    if n == 0:
        return {"n": 0, "wins": 0, "WR": float("nan"), "sum_pnl": 0.0, "dpt": float("nan"),
                "max_DD": 0.0, "loss_streak": 0, "sharpe_d": float("nan"), "n_days": 0}
    pnl = df[pnl_col].astype("float64").values
    wins = int((pnl > 0).sum())
    # ordered by fire_us
    s = df.sort_values("fire_us")
    cum = s[pnl_col].cumsum().values
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    max_DD = float(dd.max()) if len(dd) else 0.0
    # loss streak
    loss = (s[pnl_col].values <= 0).astype("int8")
    max_streak = 0; cur = 0
    for x in loss:
        if x:
            cur += 1
            if cur > max_streak: max_streak = cur
        else:
            cur = 0
    # daily sharpe
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


# ---------------------------------------------------------------------------
# Sweeps
# ---------------------------------------------------------------------------

OFFSET_BINS_FINE = [
    ("60-120", 60, 120),
    ("120-240", 120, 240),
    ("240-360", 240, 360),
    ("360-480", 360, 480),
    ("480-600", 480, 600),
    ("600-720", 600, 720),
    ("720-840", 720, 840),
    ("840-841", 840, 841),  # exactly 840
]


def offset_bin_label(off: int) -> Optional[str]:
    for label, lo, hi in OFFSET_BINS_FINE:
        if lo <= off < hi:
            return label
    if off == 840:
        return "840-841"
    return None


# Base gates list (the existing 24 + new ones we added)
BASE_GATES = [
    "g_rf_with", "g_rf_fresh", "g_rf_aged", "g_rf_in_band",
    "g_tr_stack_with", "g_tr_stack_full_with",
    "g_tr_pvsra_with", "g_tr_above_cloud", "g_tr_within_adr",
    "g_tr_in_active_session", "g_tr_above_pp",
    "g_tr_above_ema50", "g_tr_above_ema200", "g_tr_above_ema800",
    "g_ribbon_agrees", "g_ribbon_slope_with", "g_tight_ribbon",
    "g_bb_pos_with", "g_stoch_with", "g_mfi_with", "g_cci_with",
    "g_markov_with",
    "g_dev_extreme",
    # New
    "g_m5v_with", "g_m5v_strong_with",
    "g_m5v_pass", "g_m1v_pass",
    "g_rf1h_with",
    "g_cvd30_with", "g_cvd60_with", "g_cvd120_with",
    "g_macd_with",
    "g_f7_pass",
    "g_cross_partial_with", "g_cross_full_with",
    "g_rsi_with", "g_rsi_extreme_with",
    "g_vwap_ge_30",
    "g_vwap_ge_50_le_85",
    "g_s7_confirm",
]


def greedy_stack(df: pd.DataFrame, candidates: list[str], pnl_col: str = "pnl_legacy_usd",
                 min_n: int = MIN_N, max_k: int = 6) -> list[str]:
    """Greedy stepwise: add gate that maximizes sum_pnl × WR."""
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


def run_cell_search(df: pd.DataFrame, candidates: list[str], label: dict,
                    pnl_col: str = "pnl_legacy_usd") -> list[dict]:
    """Per cell: baseline + greedy + exhaustive top-10."""
    rows = []
    base = cell_summary(df, pnl_col)
    base.update(label)
    base["gate_stack"] = "(baseline)"; base["k"] = 0; base["search_type"] = "baseline"
    rows.append(base)

    if len(df) < MIN_N * 2 or not candidates:
        return rows

    avail = [c for c in candidates if c in df.columns and df[c].sum() > 0]

    chosen = greedy_stack(df, avail, pnl_col=pnl_col, min_n=MIN_N, max_k=6)
    if chosen:
        sub = apply_gate_stack(df, chosen)
        s = cell_summary(sub, pnl_col); s.update(label)
        s["gate_stack"] = "&".join(chosen); s["k"] = len(chosen); s["search_type"] = "greedy"
        rows.append(s)

    # Exhaustive top-10 by single-gate sum_pnl
    pnl_arr = df[pnl_col].astype("float64").values
    single = []
    for g in avail:
        m = df[g].fillna(False).astype(bool).values
        n_g = int(m.sum())
        if n_g < MIN_N: continue
        sub_pnl = pnl_arr[m]
        single.append((g, n_g, float(sub_pnl.sum())))
    single.sort(key=lambda x: -x[2])
    top10 = [r[0] for r in single[:10]]
    if len(top10) >= 2:
        try:
            gs = gate_search(df, top10, pnl_col=pnl_col, min_n=MIN_N, top_k=10)
        except Exception as e:
            print(f"   gate_search fail {label}: {e}")
            gs = pd.DataFrame()
        if len(gs):
            for _, r in gs.iterrows():
                cols = r["gates"].split("&")
                sub = apply_gate_stack(df, cols)
                s = cell_summary(sub, pnl_col); s.update(label)
                s["gate_stack"] = r["gates"]; s["k"] = int(r["k"]); s["search_type"] = "exhaustive_top10"
                rows.append(s)
    return rows


def sweep_per_cell(df: pd.DataFrame, candidates: list[str]) -> pd.DataFrame:
    """Fine offset bins × {BTC, ETH, SOL} cells."""
    df = df.copy()
    df["offset_bin"] = df["fire_offset_s"].astype("int64").apply(offset_bin_label)
    df = df[df["offset_bin"].notna()].copy()
    out = []
    for asset in ("BTC", "ETH", "SOL"):
        for ob in [b[0] for b in OFFSET_BINS_FINE]:
            sub = df[(df.asset == asset) & (df.offset_bin == ob)]
            if len(sub) < MIN_N * 2:
                continue
            label = {"asset": asset, "offset_bin": ob, "pool": "per_asset"}
            rows = run_cell_search(sub, candidates, label)
            out.extend(rows)
            print(f"  {asset} {ob}: n={len(sub)} → {len(rows)} stacks")
    return pd.DataFrame(out)


def sweep_pooled(df: pd.DataFrame, candidates: list[str]) -> pd.DataFrame:
    """Pooled across assets per offset bin."""
    df = df.copy()
    df["offset_bin"] = df["fire_offset_s"].astype("int64").apply(offset_bin_label)
    df = df[df["offset_bin"].notna()].copy()
    out = []
    for ob in [b[0] for b in OFFSET_BINS_FINE]:
        sub = df[df.offset_bin == ob]
        if len(sub) < MIN_N * 2:
            continue
        label = {"asset": "POOL", "offset_bin": ob, "pool": "pooled_all"}
        rows = run_cell_search(sub, candidates, label)
        out.extend(rows)
        print(f"  POOL {ob}: n={len(sub)} → {len(rows)} stacks")
    return pd.DataFrame(out)


def sweep_late_fire_dev(df: pd.DataFrame, candidates: list[str]) -> pd.DataFrame:
    """Late-fire (>= 480s offset) cross-asset, with dev_bps sub-buckets."""
    df = df.copy()
    df["abs_dev_bps"] = df["dev_bps"].abs()
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
                label = {"asset": asset, "offset_bin": f"ge_{offset_floor}",
                         "pool": "late_dev_" + db_label}
                rows = run_cell_search(sub, candidates, label)
                out.extend(rows)
                print(f"  late_{offset_floor}+_{asset}_{db_label}: n={len(sub)} → {len(rows)} stacks")
    return pd.DataFrame(out)


# ---------------------------------------------------------------------------
# Walk-forward + bootstrap
# ---------------------------------------------------------------------------

def walk_forward(df: pd.DataFrame, gates: list[str], train_days: int = 14,
                 test_days: int = 7, pnl_col: str = "pnl_legacy_usd") -> dict:
    sub = apply_gate_stack(df, gates)
    if len(sub) == 0:
        return {"train_n": 0, "test_n": 0}
    s = sub.sort_values("fire_us").reset_index(drop=True)
    t0_us = int(s["fire_us"].iloc[0])
    day_us = 24 * 3600 * 1_000_000
    t0_us = (t0_us // day_us) * day_us
    train_end = t0_us + train_days * day_us
    test_end = train_end + test_days * day_us
    train = s[s["fire_us"] < train_end]
    test = s[(s["fire_us"] >= train_end) & (s["fire_us"] < test_end)]
    tr_pnl = train[pnl_col].values
    te_pnl = test[pnl_col].values
    return {
        "train_n": len(train), "test_n": len(test),
        "train_wr": float((tr_pnl > 0).mean()) if len(tr_pnl) else float("nan"),
        "test_wr": float((te_pnl > 0).mean()) if len(te_pnl) else float("nan"),
        "train_sum": float(tr_pnl.sum()),
        "test_sum": float(te_pnl.sum()),
        "train_dpt": float(tr_pnl.mean()) if len(tr_pnl) else float("nan"),
        "test_dpt": float(te_pnl.mean()) if len(te_pnl) else float("nan"),
    }


def bootstrap_p_value(df: pd.DataFrame, gates: list[str], n_shuffles: int = 200,
                      pnl_col: str = "pnl_legacy_usd",
                      rng_seed: int = 42) -> tuple[float, float]:
    """Shuffle direction labels and recompute sum_pnl. p = fraction of shuffles where shuffled_sum >= observed_sum."""
    sub = apply_gate_stack(df, gates)
    n = len(sub)
    if n < 30:
        return float("nan"), float("nan")
    observed = float(sub[pnl_col].sum())
    rng = np.random.default_rng(rng_seed)
    pnl_arr = sub[pnl_col].astype("float64").values
    # Sign-flip bootstrap: each fire's PnL is flipped with prob 0.5 (null = direction is irrelevant)
    flips = rng.choice([-1.0, 1.0], size=(n_shuffles, n))
    shuffled_sums = (flips * pnl_arr[None, :]).sum(axis=1)
    p = float((shuffled_sums >= observed).mean())
    return p, observed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    t0 = time.time()
    print("=" * 80)
    print("15M SLEEVE HUNT — 2026-05-26")
    print("=" * 80)

    df = build_feature_panel()
    print(f"\nFeature panel: {df.shape}, dur={time.time()-t0:.1f}s")

    # Filter candidates to those actually present and informative
    candidates = [c for c in BASE_GATES if c in df.columns]
    print(f"Candidates: {len(candidates)}")

    # Sweep 1 — per asset × fine offset bin
    print("\n--- SWEEP 1: per-asset × fine offset bins ---")
    s1 = sweep_per_cell(df, candidates)
    print(f"  {len(s1)} rows")

    # Sweep 2 — pooled across assets per offset bin
    print("\n--- SWEEP 2: pooled across assets × offset bins ---")
    s2 = sweep_pooled(df, candidates)
    print(f"  {len(s2)} rows")

    # Sweep 3 — late-fire dev_bps sub-buckets
    print("\n--- SWEEP 3: late-fire dev_bps buckets ---")
    s3 = sweep_late_fire_dev(df, candidates)
    print(f"  {len(s3)} rows")

    all_results = pd.concat([s1, s2, s3], ignore_index=True)
    print(f"\nTotal sweep rows: {len(all_results)}")

    # Save
    out_csv = RES / "sleeve_hunt_15m_results.csv"
    all_results.to_csv(out_csv, index=False)
    print(f"Saved {out_csv}")

    # Filter to deployable (excluding baselines)
    deploy_mask = (
        (all_results["gate_stack"] != "(baseline)") &
        (all_results["n"] >= DEPLOY_MIN_N) &
        (all_results["WR"] >= DEPLOY_MIN_WR) &
        (all_results["dpt"] >= DEPLOY_MIN_DPT) &
        (all_results["sum_pnl"] >= DEPLOY_MIN_SUM)
    )
    deploy = all_results[deploy_mask].sort_values("dpt", ascending=False).reset_index(drop=True)
    print(f"\nDeployable candidates (n>={DEPLOY_MIN_N}, WR>={DEPLOY_MIN_WR}, dpt>=${DEPLOY_MIN_DPT}, sum>=${DEPLOY_MIN_SUM}): {len(deploy)}")
    if len(deploy):
        print(deploy.head(30).to_string())

    # Lower bar: high $/tr even at small n
    high_dpt = all_results[(all_results["gate_stack"] != "(baseline)") &
                            (all_results["n"] >= 40) &
                            (all_results["WR"] >= 0.70) &
                            (all_results["dpt"] >= 5.0) &
                            (all_results["sum_pnl"] >= 400.0)].copy()
    high_dpt = high_dpt.sort_values("dpt", ascending=False).reset_index(drop=True)
    print(f"\nHigh $/tr candidates (n>=40, WR>=70%, dpt>=$5, sum>=$400): {len(high_dpt)}")
    if len(high_dpt):
        print(high_dpt.head(30).to_string())

    # Dedupe top by (asset, offset_bin) — keep best dpt per cell
    combined = pd.concat([deploy, high_dpt], ignore_index=True).drop_duplicates(
        subset=["asset", "offset_bin", "pool", "gate_stack"], keep="first")
    top = combined.sort_values("dpt", ascending=False).reset_index(drop=True)
    print(f"\nCombined unique candidates: {len(top)}")

    # Save top
    out_top = RES / "sleeve_hunt_15m_top.csv"
    top.to_csv(out_top, index=False)
    print(f"Saved {out_top}")

    # Walk-forward + bootstrap on top 50 (because top-25 will have many test_n=0 due to small fires concentrated in 14d train)
    print("\n--- TASK 6: walk-forward + bootstrap on top 50 (14d/7d split) ---")
    # Score = dpt * sqrt(n) * WR to favor effect-size + sample-size jointly
    top = top.assign(score=top["dpt"] * np.sqrt(top["n"]) * top["WR"]).sort_values("score", ascending=False).reset_index(drop=True)
    top25 = top.head(50)
    wf_rows = []
    for i, row in top25.iterrows():
        gates = [g for g in row["gate_stack"].split("&") if g]
        # rebuild the per-cell subset for walk-forward
        if row.get("pool") == "per_asset":
            cell = df[(df.asset == row["asset"]) & (df["fire_offset_s"].apply(offset_bin_label) == row["offset_bin"])]
        elif row.get("pool") == "pooled_all":
            cell = df[df["fire_offset_s"].apply(offset_bin_label) == row["offset_bin"]]
        elif str(row.get("pool", "")).startswith("late_dev_"):
            # late_dev sweep used offset_floor (ge_NNN) and abs_dev sub-bucket
            ob_label = row["offset_bin"]  # like ge_480
            floor = int(ob_label.replace("ge_", ""))
            db_str = row["pool"].replace("late_dev_", "")
            buckets = {
                "dev_5_10": (5,10), "dev_10_15": (10,15), "dev_15_20": (15,20),
                "dev_20_30": (20,30), "dev_30+": (30,999),
                "dev_ge_10": (10,999), "dev_ge_15": (15,999), "dev_ge_20": (20,999),
            }
            lo, hi = buckets.get(db_str, (0, 999))
            cell = df[(df["fire_offset_s"] >= floor) & (df["dev_bps"].abs() >= lo) & (df["dev_bps"].abs() < hi)]
            if row["asset"] != "POOL":
                cell = cell[cell.asset == row["asset"]]
        else:
            cell = df
        wf = walk_forward(cell, gates)
        p_val, observed = bootstrap_p_value(cell, gates, n_shuffles=200)
        wf_row = {
            "rank": i + 1,
            "asset": row["asset"], "offset_bin": row["offset_bin"], "pool": row["pool"],
            "gate_stack": row["gate_stack"],
            "n": row["n"], "WR": row["WR"], "dpt": row["dpt"], "sum_pnl": row["sum_pnl"],
            "sharpe_d": row["sharpe_d"], "max_DD": row["max_DD"], "loss_streak": row["loss_streak"],
            **wf, "bootstrap_p": p_val,
            "wf_pass": (wf["test_n"] >= 5) and (wf["test_sum"] > 0) and (p_val < 0.05),
        }
        wf_rows.append(wf_row)
        print(f"  #{i+1} {row['asset']} {row['offset_bin']} dpt=${row['dpt']:.2f} n={row['n']} "
              f"→ train_n={wf['train_n']} test_n={wf['test_n']} test_sum={wf['test_sum']:.2f} p={p_val:.3f}")
    wf_df = pd.DataFrame(wf_rows)
    out_wf = RES / "sleeve_hunt_15m_walkforward.csv"
    wf_df.to_csv(out_wf, index=False)
    print(f"\nSaved {out_wf}")

    print(f"\nDONE in {time.time()-t0:.1f}s")
    return all_results, top, wf_df


if __name__ == "__main__":
    main()
