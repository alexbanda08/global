"""Build R2-specific panel by joining continuous features onto oos_fires_BTC_5m
(which has g_rf_strong & g_within_dev & g_ribbon_agrees).

Output: data/v4/canonical/_results/threshold_panel_r2.parquet
"""
from __future__ import annotations
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    log("Build R2 panel")
    base = pd.read_parquet(RES / "_full_window_2026_05_26" / "oos_fires_BTC_5m.parquet")
    log(f"base shape: {base.shape}")

    keys = ["asset", "slug", "fire_us", "fire_offset_s"]

    # microprice
    mp = pd.read_parquet(RES / "microprice_panel.parquet")
    mp_keep = keys + ["mp_skew", "mp_skew_change_500ms", "mp_skew_500ms"]
    mp = mp[[c for c in mp_keep if c in mp.columns]].drop_duplicates(keys)
    base = base.merge(mp, on=keys, how="left")
    log(f"  + microprice: mp_skew nonnull {base.mp_skew.notna().sum()}")

    # LM
    lm = pd.read_parquet(RES / "lm_at_fires_5m.parquet")
    lm_keep = keys + ["lm_L_stat_at_fire", "lm_last_jump_dir_60s", "lm_has_jump_60s",
                      "lm_has_jump_120s", "lm_n_jumps_in_last_300s"]
    lm = lm[[c for c in lm_keep if c in lm.columns]].drop_duplicates(keys)
    base = base.merge(lm, on=keys, how="left")
    log(f"  + LM: L_stat nonnull {base.lm_L_stat_at_fire.notna().sum()}")

    # hawkes
    h = pd.read_parquet(RES / "vpin_hawkes_at_fires.parquet")
    h_keep = keys + ["hawkes_lambda_imbalance", "hawkes_lambda_total"]
    h = h[[c for c in h_keep if c in h.columns]].drop_duplicates(keys)
    base = base.merge(h, on=keys, how="left")
    log(f"  + hawkes: lambda nonnull {base.hawkes_lambda_imbalance.notna().sum()}")

    # vol/Hurst
    v = pd.read_parquet(RES / "vol_hurst_at_fire_5m.parquet")
    v_keep = keys + ["rv_60s", "rv_300s", "hurst_300s"]
    v = v[[c for c in v_keep if c in v.columns]].drop_duplicates(keys)
    base = base.merge(v, on=keys, how="left")
    log(f"  + vol: rv_60s nonnull {base.rv_60s.notna().sum()}")

    # microstructure
    ms = pd.read_parquet(RES / "microstructure_panel.parquet")
    ms_keep = keys + ["up_imb5", "dn_imb5",
                      "up_queue_top_bid", "dn_queue_top_bid",
                      "up_bid_slope", "up_ask_slope", "dn_bid_slope", "dn_ask_slope",
                      "up_imb5_change_500ms", "dn_imb5_change_500ms"]
    ms = ms[[c for c in ms_keep if c in ms.columns]].drop_duplicates(keys)
    base = base.merge(ms, on=keys, how="left")
    log(f"  + microstructure: up_imb5 nonnull {base.up_imb5.notna().sum()}")

    # vwap is on oos_fires already (vwap_since_open_bps? check)
    if "vwap_since_open_bps" not in base.columns:
        # try from microprice
        mp_full = pd.read_parquet(RES / "microprice_panel.parquet")
        if "vwap_since_open_bps" in mp_full.columns:
            mp_v = mp_full[keys + ["vwap_since_open_bps"]].drop_duplicates(keys)
            base = base.merge(mp_v, on=keys, how="left")
        else:
            # Use lm panel which has it
            lm_full = pd.read_parquet(RES / "lm_at_fires_5m.parquet")
            lm_v = lm_full[keys + ["vwap_since_open_bps"]].drop_duplicates(keys)
            base = base.merge(lm_v, on=keys, how="left")
        log(f"  + vwap_since_open_bps nonnull {base.vwap_since_open_bps.notna().sum()}")

    # Save
    base.to_parquet(RES / "threshold_panel_r2.parquet", index=False, compression="zstd")
    log(f"wrote threshold_panel_r2.parquet: {base.shape}")

    # Summary: R2 gate stack
    r2 = base[(base["g_within_dev"] == 1) & (base["g_rf_strong"] == 1) & (base["g_ribbon_agrees"] == 1)]
    log(f"R2 stack (within_dev & rf_strong & ribbon_agrees): n = {len(r2):,}")
    log(f"  WR={r2.won.mean()*100:.1f}%, sum=${r2.pnl_legacy_usd.sum():.0f}, dpt=${r2.pnl_legacy_usd.mean():.3f}")


if __name__ == "__main__":
    main()
