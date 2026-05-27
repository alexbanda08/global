"""TASK 2 — Sample LM panel at every fire_us causally.

For each fire, compute:
  - bars_since_jump_01_60s, bars_since_jump_05_120s
  - last_jump_dir_60s (+1/-1/0)
  - n_jumps_in_last_300s
  - L_stat_at_fire (last L value before fire_us)
  - is_extreme_jump_within_60s, jump_dir_extreme_60s

Strict causal: features at fire_us use bars with ts_us < fire_us only.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
PANEL = ROOT / "data" / "v4" / "canonical" / "_results" / "lee_mykland_panel.parquet"
F5M = ROOT / "data" / "v4" / "canonical" / "_results" / "hybrid_fire_universe_5m.parquet"
F15M = ROOT / "data" / "v4" / "canonical" / "_results" / "hybrid_fire_universe_15m.parquet"
OUT_5M = ROOT / "data" / "v4" / "canonical" / "_results" / "lm_at_fires_5m.parquet"
OUT_15M = ROOT / "data" / "v4" / "canonical" / "_results" / "lm_at_fires_15m.parquet"

LOOKBACK_S_LIST = (30, 60, 120, 300)


def sample_per_asset(panel_a: pd.DataFrame, fires_a: pd.DataFrame, asset: str) -> pd.DataFrame:
    """Vectorized per-asset sampling."""
    panel_a = panel_a.sort_values("ts_us").reset_index(drop=True)
    ts_panel = panel_a["ts_us"].values.astype("int64")
    L = panel_a["L_stat"].values.astype("float32")
    is01 = panel_a["is_jump_01"].values
    is05 = panel_a["is_jump_05"].values
    is_ex = panel_a["is_jump_extreme"].values
    dir01 = panel_a["jump_dir_01"].values.astype("int8")
    dir_ex = panel_a["jump_dir_extreme"].values.astype("int8")
    log_ret = panel_a["log_ret"].values

    fire_us = fires_a["fire_us"].values.astype("int64")

    # For each fire, find last bar with ts <= fire_us (strict causal).
    # ts_panel is bar-close time = end of bar. Use side='right' - 1.
    idx_at = np.searchsorted(ts_panel, fire_us, side="right") - 1

    # Initialize outputs
    n = len(fire_us)
    L_at_fire = np.full(n, np.nan, dtype=np.float32)
    log_ret_at_fire = np.full(n, np.nan, dtype=np.float32)

    bars_since_jump_01_60s = np.full(n, -1, dtype=np.int32)
    bars_since_jump_05_120s = np.full(n, -1, dtype=np.int32)
    last_jump_dir_60s = np.zeros(n, dtype=np.int8)        # +1/-1/0
    last_jump_dir_extreme_60s = np.zeros(n, dtype=np.int8)
    has_jump_30s = np.zeros(n, dtype=bool)
    has_jump_60s = np.zeros(n, dtype=bool)
    has_jump_120s = np.zeros(n, dtype=bool)
    has_jump_extreme_60s = np.zeros(n, dtype=bool)
    last_jump_dir_30s = np.zeros(n, dtype=np.int8)
    last_jump_dir_120s = np.zeros(n, dtype=np.int8)
    last_jump_dir_extreme_120s = np.zeros(n, dtype=np.int8)
    n_jumps_in_last_300s = np.zeros(n, dtype=np.int32)
    n_jumps_extreme_300s = np.zeros(n, dtype=np.int32)

    for i in range(n):
        idx = idx_at[i]
        if idx < 0:
            continue
        L_at_fire[i] = L[idx]
        log_ret_at_fire[i] = log_ret[idx]
        f_us = fire_us[i]

        # bars_since_jump_01_60s: latest 0.01-sig jump within 60s before fire
        # find lo_us = f_us - 60_000_000; window = idx_lo..idx inclusive
        idx_lo_60 = np.searchsorted(ts_panel, f_us - 60_000_000, side="left")
        idx_lo_30 = np.searchsorted(ts_panel, f_us - 30_000_000, side="left")
        idx_lo_120 = np.searchsorted(ts_panel, f_us - 120_000_000, side="left")
        idx_lo_300 = np.searchsorted(ts_panel, f_us - 300_000_000, side="left")

        # is01 in [idx_lo_60, idx]
        if idx_lo_60 <= idx:
            seg = is01[idx_lo_60:idx + 1]
            if seg.any():
                # last True idx (relative)
                rel = np.where(seg)[0]
                last_rel = int(rel[-1])
                bars_since_jump_01_60s[i] = idx - (idx_lo_60 + last_rel)
                last_jump_dir_60s[i] = dir01[idx_lo_60 + last_rel]
                has_jump_60s[i] = True
        if idx_lo_30 <= idx:
            seg = is01[idx_lo_30:idx + 1]
            if seg.any():
                rel = np.where(seg)[0]
                last_jump_dir_30s[i] = dir01[idx_lo_30 + int(rel[-1])]
                has_jump_30s[i] = True

        if idx_lo_120 <= idx:
            seg = is05[idx_lo_120:idx + 1]
            if seg.any():
                rel = np.where(seg)[0]
                last_rel = int(rel[-1])
                bars_since_jump_05_120s[i] = idx - (idx_lo_120 + last_rel)
                has_jump_120s[i] = True
                last_jump_dir_120s[i] = dir01[idx_lo_120 + last_rel]

        if idx_lo_60 <= idx:
            seg_ex = is_ex[idx_lo_60:idx + 1]
            if seg_ex.any():
                rel = np.where(seg_ex)[0]
                last_jump_dir_extreme_60s[i] = dir_ex[idx_lo_60 + int(rel[-1])]
                has_jump_extreme_60s[i] = True

        if idx_lo_120 <= idx:
            seg_ex = is_ex[idx_lo_120:idx + 1]
            if seg_ex.any():
                rel = np.where(seg_ex)[0]
                last_jump_dir_extreme_120s[i] = dir_ex[idx_lo_120 + int(rel[-1])]

        if idx_lo_300 <= idx:
            n_jumps_in_last_300s[i] = int(is01[idx_lo_300:idx + 1].sum())
            n_jumps_extreme_300s[i] = int(is_ex[idx_lo_300:idx + 1].sum())

    fires_a = fires_a.copy()
    fires_a["lm_L_stat_at_fire"] = L_at_fire
    fires_a["lm_log_ret_at_fire"] = log_ret_at_fire
    fires_a["lm_bars_since_jump_01_60s"] = bars_since_jump_01_60s
    fires_a["lm_bars_since_jump_05_120s"] = bars_since_jump_05_120s
    fires_a["lm_last_jump_dir_30s"] = last_jump_dir_30s
    fires_a["lm_last_jump_dir_60s"] = last_jump_dir_60s
    fires_a["lm_last_jump_dir_120s"] = last_jump_dir_120s
    fires_a["lm_has_jump_30s"] = has_jump_30s
    fires_a["lm_has_jump_60s"] = has_jump_60s
    fires_a["lm_has_jump_120s"] = has_jump_120s
    fires_a["lm_has_jump_extreme_60s"] = has_jump_extreme_60s
    fires_a["lm_last_jump_dir_extreme_60s"] = last_jump_dir_extreme_60s
    fires_a["lm_last_jump_dir_extreme_120s"] = last_jump_dir_extreme_120s
    fires_a["lm_n_jumps_in_last_300s"] = n_jumps_in_last_300s
    fires_a["lm_n_jumps_extreme_300s"] = n_jumps_extreme_300s
    return fires_a


def process_universe(path_in: Path, path_out: Path, panel: pd.DataFrame) -> None:
    t0 = time.time()
    fires = pd.read_parquet(path_in)
    print(f"[{path_in.name}] {len(fires):,} fires")
    parts = []
    for asset in ("BTC", "ETH", "SOL"):
        f_a = fires[fires["asset"] == asset]
        p_a = panel[panel["asset"] == asset]
        if len(f_a) == 0:
            continue
        out_a = sample_per_asset(p_a, f_a, asset)
        parts.append(out_a)
        n_with_jump_60s = int(out_a["lm_has_jump_60s"].sum())
        n_with_extreme = int(out_a["lm_has_jump_extreme_60s"].sum())
        print(f"  {asset}: {len(f_a):,} fires, {n_with_jump_60s:,} with jump_01 in 60s, "
              f"{n_with_extreme:,} with extreme jump in 60s")
    out = pd.concat(parts, ignore_index=True)
    out.to_parquet(path_out, index=False)
    print(f"[saved] {path_out} in {time.time()-t0:.1f}s")


def main() -> int:
    print("[1] loading LM panel...")
    panel = pd.read_parquet(PANEL)
    print(f"    {len(panel):,} bars")

    process_universe(F5M, OUT_5M, panel)
    process_universe(F15M, OUT_15M, panel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
