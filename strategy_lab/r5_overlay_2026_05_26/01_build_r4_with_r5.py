"""TASK 1 — Join R5 panels (microprice / Lee-Mykland / Hawkes) to R4 15m full
features panel. Adds R5 gates. Saves r4_15m_with_r5_features.parquet.

Causal anchoring:
- Microprice: direct join by (asset, slug, tf, fire_us) — panel was already sampled
  at fire_us.
- Lee-Mykland (5s panel): merge_asof per asset, backward to fire_us, tolerance 60s.
- Hawkes (1s panel): merge_asof per asset, backward to fire_us, tolerance 5s.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"
OUT_DIR = ROOT / "strategy_lab" / "r5_overlay_2026_05_26"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main():
    t0 = time.time()
    print("=" * 80)
    print("R5 OVERLAY ON R4 — TASK 1: join R5 features causally")
    print("=" * 80)

    # ----- Base: full features panel with R4 gates + direction + PnL -----
    base = pd.read_parquet(RES / "sleeve_hunt_15m_full_features.parquet")
    print(f"\nBase R4 panel: {base.shape}")
    print(f"  window split: {base['window'].value_counts().to_dict()}")
    print(f"  ts range: "
          f"{pd.to_datetime(base['fire_us'].min(), unit='us', utc=True)} -> "
          f"{pd.to_datetime(base['fire_us'].max(), unit='us', utc=True)}")

    # slug is already in base; we just need to add 'tf' (always '15m' for this panel)
    if "tf" not in base.columns:
        base["tf"] = "15m"
    print(f"  slug already in base: dtype={base['slug'].dtype}, non-null="
          f"{base['slug'].notna().sum()}/{len(base)}")

    # ----- 1. MICROPRICE — direct join on fire_us -----
    print("\n[1] Loading microprice panel...")
    mp = pd.read_parquet(RES / "microprice_panel.parquet")
    print(f"  microprice: {mp.shape}")
    # Keep only needed cols + dedupe key
    mp_cols = ["asset", "slug", "tf", "fire_us", "fire_offset_s",
               "mp_up_simple", "mp_dn_simple",
               "mp_up_weighted", "mp_dn_weighted",
               "mp_up_dev_bps", "mp_dn_dev_bps",
               "mp_up_weighted_dev_bps", "mp_dn_weighted_dev_bps",
               "mp_skew", "mp_imbalance",
               "mp_weighted_skew", "mp_weighted_imbalance",
               "mp_up_dev_change_500ms", "mp_dn_dev_change_500ms",
               "mp_skew_500ms", "mp_skew_change_500ms"]
    mp_cols = [c for c in mp_cols if c in mp.columns]
    mp_small = mp[mp_cols].drop_duplicates(
        subset=["asset","slug","tf","fire_us","fire_offset_s"])
    print(f"  microprice deduped: {mp_small.shape}")

    n_before = len(base)
    base = base.merge(mp_small, on=["asset","slug","tf","fire_us","fire_offset_s"],
                       how="left")
    print(f"  after microprice merge: {base.shape} (was {n_before})")
    print(f"  mp coverage: "
          f"mp_skew non-null = {base['mp_skew'].notna().sum()}/{len(base)} "
          f"({base['mp_skew'].notna().mean()*100:.1f}%)")

    # ----- 2. LEE-MYKLAND — merge_asof per asset, backward to fire_us -----
    print("\n[2] Loading Lee-Mykland panel...")
    lm = pd.read_parquet(RES / "lee_mykland_panel.parquet")
    print(f"  lm: {lm.shape}")
    lm = lm.rename(columns={
        "L_stat": "lm_L_stat",
        "is_jump_01": "lm_is_jump_01",
        "is_jump_05": "lm_is_jump_05",
        "is_jump_extreme": "lm_is_jump_extreme",
        "jump_dir_01": "lm_jump_dir_01",
        "jump_dir_05": "lm_jump_dir_05",
        "jump_dir_extreme": "lm_jump_dir_extreme",
        "log_ret": "lm_log_ret",
        "bv_sigma": "lm_bv_sigma",
    })

    parts = []
    for asset, sub in base.groupby("asset", sort=False):
        lmsub = lm[lm["asset"] == asset].sort_values("ts_us").drop(columns=["asset"])
        ssub = sub.sort_values("fire_us")
        merged = pd.merge_asof(
            ssub, lmsub,
            left_on="fire_us", right_on="ts_us",
            direction="backward",
            tolerance=int(60 * 1_000_000),  # 60s tolerance for 5s panel
        )
        parts.append(merged)
    base = pd.concat(parts, ignore_index=True)
    if "ts_us" in base.columns:
        base = base.rename(columns={"ts_us": "lm_anchor_us"})
    print(f"  after LM merge: {base.shape}")
    print(f"  LM coverage: "
          f"lm_L_stat non-null = {base['lm_L_stat'].notna().sum()}/{len(base)} "
          f"({base['lm_L_stat'].notna().mean()*100:.1f}%)")

    # ----- Also need last_jump_dir_60s — derive from jump events within last 60s. -----
    # For each fire, search backward in LM panel for nearest jump in last 60s,
    # then take its direction. Do this per asset, sorted.
    print("\n[2b] Computing last_jump_dir_60s (60s lookback)...")
    parts = []
    for asset, sub in base.groupby("asset", sort=False):
        lmsub = lm[(lm["asset"] == asset) & (lm["lm_is_jump_05"] == True)
                   ].sort_values("ts_us")
        if lmsub.empty:
            sub = sub.copy()
            sub["lm_last_jump_dir_60s"] = 0
            parts.append(sub); continue
        ssub = sub.sort_values("fire_us").copy()
        # merge_asof: pick most-recent jump <= fire_us within 60s
        ljt = pd.merge_asof(
            ssub[["fire_us"]],
            lmsub[["ts_us","lm_jump_dir_05"]].rename(columns={"lm_jump_dir_05":"lm_last_jump_dir_60s"}),
            left_on="fire_us", right_on="ts_us", direction="backward",
            tolerance=int(60 * 1_000_000),
        )
        ssub["lm_last_jump_dir_60s"] = ljt["lm_last_jump_dir_60s"].fillna(0).astype(int).values
        parts.append(ssub)
    base = pd.concat(parts, ignore_index=True)
    print(f"  last_jump_dir_60s computed; nonzero = "
          f"{(base['lm_last_jump_dir_60s']!=0).sum()}")

    # ----- 3. HAWKES — merge_asof per asset, backward 5s -----
    print("\n[3] Loading Hawkes panel...")
    hk = pd.read_parquet(RES / "hawkes_panel.parquet")
    print(f"  hawkes: {hk.shape}")
    hk = hk.rename(columns={
        "lambda_buy": "hk_lambda_buy",
        "lambda_sell": "hk_lambda_sell",
        "lambda_total": "hk_lambda_total",
        "lambda_imbalance": "hk_lambda_imbalance",
        "recent_burst": "hk_recent_burst",
    })

    parts = []
    for asset, sub in base.groupby("asset", sort=False):
        hksub = hk[hk["asset"] == asset].sort_values("ts_us").drop(columns=["asset"])
        ssub = sub.sort_values("fire_us")
        merged = pd.merge_asof(
            ssub, hksub,
            left_on="fire_us", right_on="ts_us",
            direction="backward",
            tolerance=int(5 * 1_000_000),  # 5s for 1s panel
            suffixes=("", "_hk"),
        )
        parts.append(merged)
    base = pd.concat(parts, ignore_index=True)
    if "ts_us_hk" in base.columns:
        base = base.drop(columns=["ts_us_hk"])
    elif "ts_us" in base.columns and "lm_anchor_us" in base.columns:
        base = base.rename(columns={"ts_us": "hk_anchor_us"})
    print(f"  after Hawkes merge: {base.shape}")
    print(f"  HK coverage: "
          f"hk_lambda_imbalance non-null = {base['hk_lambda_imbalance'].notna().sum()}/{len(base)} "
          f"({base['hk_lambda_imbalance'].notna().mean()*100:.1f}%)")

    # ----- 4. BUILD R5 GATES -----
    print("\n[4] Building R5 gates...")
    d = base
    dir_up = (d["direction"] == "UP")
    dir_dn = (d["direction"] == "DOWN")

    # Microprice gates — mp_skew is in bps deviation. Distribution: p25 = -215,
    # p50=0, p75=+211, p90=+679, p95=+1473. So "extreme" = |skew| > 700.
    if "mp_skew" in d.columns:
        # |mp_skew| extreme = >700bps either side → "fight book" / one-sided
        d["g_mp_no_extreme"] = (d["mp_skew"].abs() < 700.0).fillna(False)
        d["g_mp_very_no_extreme"] = (d["mp_skew"].abs() < 250.0).fillna(False)
        # mp_skew_with: positive skew (Up favored) on UP, negative on DOWN
        d["g_mp_with"] = (((d["mp_skew"] > 0) & dir_up) | ((d["mp_skew"] < 0) & dir_dn)).fillna(False)
        d["g_mp_against"] = (((d["mp_skew"] < 0) & dir_up) | ((d["mp_skew"] > 0) & dir_dn)).fillna(False)
        d["g_mp_strong_with"] = (((d["mp_skew"] > 200) & dir_up) | ((d["mp_skew"] < -200) & dir_dn)).fillna(False)
    if "mp_skew_change_500ms" in d.columns:
        # mp_change_with: skew moving toward bet direction in last 500ms.
        # Distribution is mostly 0 (sparse update), p95 = ~30bps.
        d["g_mp_change_with"] = (
            ((d["mp_skew_change_500ms"] > 10) & dir_up) |
            ((d["mp_skew_change_500ms"] < -10) & dir_dn)
        ).fillna(False)
        d["g_mp_change_strong_with"] = (
            ((d["mp_skew_change_500ms"] > 30) & dir_up) |
            ((d["mp_skew_change_500ms"] < -30) & dir_dn)
        ).fillna(False)

    # Lee-Mykland gates
    if "lm_L_stat" in d.columns:
        # |L_stat| > threshold = high statistic → suggests imminent move
        d["g_lm_high_stat"] = (d["lm_L_stat"].abs() > 2.0).fillna(False)
        d["g_lm_low_stat"] = (d["lm_L_stat"].abs() < 1.0).fillna(False)
    if "lm_is_jump_05" in d.columns:
        d["g_lm_jump_05"] = d["lm_is_jump_05"].fillna(False).astype(bool)
    if "lm_jump_dir_05" in d.columns:
        d["g_lm_jump_with"] = (
            ((d["lm_jump_dir_05"] > 0) & dir_up) |
            ((d["lm_jump_dir_05"] < 0) & dir_dn)
        ).fillna(False)
    if "lm_is_jump_extreme" in d.columns and "lm_jump_dir_extreme" in d.columns:
        d["g_lm_extreme_jump"] = d["lm_is_jump_extreme"].fillna(False).astype(bool)
        # KILL gate: don't fire if extreme jump opposes bet direction
        extreme_against = (
            ((d["lm_jump_dir_extreme"] < 0) & dir_up) |
            ((d["lm_jump_dir_extreme"] > 0) & dir_dn)
        ).fillna(False)
        d["g_lm_extreme_against"] = ~extreme_against  # PASS if NOT extreme-against
    if "lm_last_jump_dir_60s" in d.columns:
        d["g_lm_last_jump_with_60s"] = (
            ((d["lm_last_jump_dir_60s"] > 0) & dir_up) |
            ((d["lm_last_jump_dir_60s"] < 0) & dir_dn)
        )

    # Hawkes gates
    if "hk_lambda_imbalance" in d.columns:
        # imbalance: -1 (sell-dominated) ... +1 (buy-dominated)
        d["g_hawkes_imbalance_with"] = (
            ((d["hk_lambda_imbalance"] > 0.10) & dir_up) |
            ((d["hk_lambda_imbalance"] < -0.10) & dir_dn)
        ).fillna(False)
        d["g_hawkes_imbalance_strong_with"] = (
            ((d["hk_lambda_imbalance"] > 0.30) & dir_up) |
            ((d["hk_lambda_imbalance"] < -0.30) & dir_dn)
        ).fillna(False)
    if "hk_recent_burst" in d.columns:
        d["g_hawkes_burst"] = (d["hk_recent_burst"].fillna(0).astype(float) > 0).fillna(False)

    # NOTE: hy_cb_with_dir (HY cross-exchange basis) panel not found among R5 panels.
    # The instructions mention "HY xchg: hy_cb_with_dir (if Agent EE's panel covered 15m)"
    # — checking now.
    if "hy_cb_with_dir" not in d.columns:
        # Look for an xchg or basis panel
        try:
            for cand in ["microstructure_panel.parquet", "as_panel.parquet"]:
                p = RES / cand
                if p.exists():
                    df_cand = pd.read_parquet(p)
                    cols = [c for c in df_cand.columns if "hy" in c.lower() or "basis" in c.lower() or "xchg" in c.lower()]
                    if cols:
                        print(f"  [info] {cand} candidate basis cols: {cols}")
        except Exception as e:
            print(f"  [info] basis-panel scan err: {e}")
        d["g_hy_cb_with_dir"] = False  # placeholder, no-op
        print("  [info] g_hy_cb_with_dir: panel not found → gate inactive")

    # Summary
    new_gates = sorted([c for c in d.columns if c.startswith("g_") and c.startswith(("g_mp_","g_lm_","g_hawkes_","g_hy_"))])
    print(f"\n[5] New R5 gates: {len(new_gates)}")
    for g in new_gates:
        try:
            n_true = int(d[g].fillna(False).astype(bool).sum())
            print(f"  {g:38s}  n_true={n_true:6d}  rate={n_true/len(d)*100:5.1f}%")
        except Exception:
            print(f"  {g:38s}  ERR")

    out_path = RES / "r4_15m_with_r5_features.parquet"
    d.to_parquet(out_path, index=False, compression="zstd")
    print(f"\nSaved {out_path}: {d.shape}")
    print(f"Elapsed {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
