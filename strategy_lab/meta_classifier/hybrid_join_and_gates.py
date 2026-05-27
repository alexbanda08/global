"""Build joined RF+TR+TA+Markov feature matrices and binary gate columns
for hybrid AND-gate search.

Outputs:
  data/v4/canonical/_results/s15_joined_all.parquet
  data/v4/canonical/_results/s6_joined_all.parquet
  data/v4/canonical/_results/v15m_joined_all.parquet

Each output has the original fire rows + RF + TR + TA + Markov features
+ binary gate columns prefixed `g_*` (1 if condition with bet direction).
"""
from __future__ import annotations
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"
TR_PANEL = RES / "traders_reality_1s.parquet"


def asof_tr_overlay(fires: pd.DataFrame, tr: pd.DataFrame) -> pd.DataFrame:
    """Causal asof merge of TR panel onto fires (ts_us = fire_us - 1s).

    fires already may have a ts_us column from upstream join — we drop it
    before the asof merge to avoid the 'ts_us not unique' error.
    """
    fires = fires.copy()
    if "ts_us" in fires.columns:
        fires = fires.drop(columns=["ts_us"])
    fires["ts_us"] = (fires["fire_us"].astype("int64") - 1_000_000)
    # avoid colliding column names from tr_panel onto fires
    tr_cols = [c for c in tr.columns if c not in ("asset", "ts_us")]
    drop_dups = [c for c in tr_cols if c in fires.columns]
    if drop_dups:
        rename_map = {c: (f"tr_{c}" if not c.startswith("tr_") else c) for c in drop_dups}
        tr = tr.rename(columns=rename_map)
        tr_cols = [c for c in tr.columns if c not in ("asset", "ts_us")]
    parts = []
    for asset in ("BTC", "ETH", "SOL"):
        f_a = fires[fires.asset == asset].sort_values("ts_us")
        if len(f_a) == 0:
            continue
        t_a = tr[tr.asset == asset][["ts_us"] + tr_cols].sort_values("ts_us")
        merged = pd.merge_asof(
            f_a, t_a, on="ts_us", direction="backward", tolerance=10_000_000
        )
        parts.append(merged)
    out = pd.concat(parts, ignore_index=True)
    return out


def build_s15_joined() -> pd.DataFrame:
    """S1.5 (5m): join ta_markov + rf + tr."""
    print("[s15] loading ta_markov_rf + tr...")
    a = pd.read_parquet(RES / "s15_with_ta_markov_rf.parquet")
    b = pd.read_parquet(RES / "s15_with_tr.parquet")
    print(f"  ta_markov_rf: {a.shape}")
    print(f"  with_tr:      {b.shape}")
    # b has 97 cols, a has 66; drop duplicate cols from b before merge
    keep_b = [c for c in b.columns if c not in a.columns or c in ("slug", "fire_us")]
    b_keep = b[keep_b]
    print(f"  b cols kept after dedup: {len(keep_b)}")
    out = a.merge(b_keep, on=["slug", "fire_us"], how="left")
    print(f"  joined: {out.shape}")
    return out


def build_s6_joined() -> pd.DataFrame:
    """S6 (5m spike): join with_rf + with_tr.

    s6 has rows duplicated by `definition` (D1/D2/D3); merge keys must include
    (slug, fire_us, definition) to avoid cross-product blow-up.
    """
    print("[s6] loading with_rf + with_tr...")
    a = pd.read_parquet(RES / "s6_with_rf.parquet")
    b = pd.read_parquet(RES / "s6_with_tr.parquet")
    print(f"  with_rf: {a.shape}")
    print(f"  with_tr: {b.shape}")
    keys = ["slug", "fire_us", "definition"]
    keep_b = [c for c in b.columns if c not in a.columns or c in keys]
    b_keep = b[keep_b]
    print(f"  b cols kept after dedup: {len(keep_b)}")
    out = a.merge(b_keep, on=keys, how="left")
    print(f"  joined: {out.shape}")
    return out


def build_v15m_joined() -> pd.DataFrame:
    """v15m (15m S7): start from with_ta_markov_rf, overlay TR via asof."""
    print("[v15m] loading ta_markov_rf...")
    a = pd.read_parquet(RES / "v15m_with_ta_markov_rf.parquet")
    print(f"  ta_markov_rf: {a.shape}")
    print("[v15m] loading TR panel...")
    tr = pd.read_parquet(TR_PANEL)
    print(f"  TR: {tr.shape}")
    print("[v15m] asof overlay TR onto fires (fire_us - 1s)...")
    out = asof_tr_overlay(a, tr)
    print(f"  joined: {out.shape}")
    return out


def _add_gates(df: pd.DataFrame) -> pd.DataFrame:
    """Compute g_* binary 0/1 gate columns. All evaluated WRT bet direction."""
    d = df.copy()
    dir_up = (d["direction"] == "UP")
    dir_dn = (d["direction"] == "DOWN")

    def g(cond) -> np.ndarray:
        return cond.fillna(False).astype("int8").values

    # --- RF gates ---
    if "rf_dir" in d.columns:
        rf_with = ((d["rf_dir"] > 0) & dir_up) | ((d["rf_dir"] < 0) & dir_dn)
        d["g_rf_with"] = g(rf_with)
        if "rf_dir_age" in d.columns:
            d["g_rf_fresh"] = g(rf_with & (d["rf_dir_age"].abs() <= 30))
            d["g_rf_aged"] = g(rf_with & (d["rf_dir_age"].abs() > 30))
        if "rf_dist_bps" in d.columns:
            d["g_rf_strong"] = g(rf_with & (d["rf_dist_bps"].abs() > 10))
        if "rf_band_pos" in d.columns:
            # price closer to mid (away from band) -> conviction
            d["g_rf_in_band"] = g(rf_with & (d["rf_band_pos"].between(0.0, 1.0)))

    # --- TR gates ---
    if "tr_ema_stack_score" in d.columns:
        d["g_tr_stack_with"] = g(
            ((d["tr_ema_stack_score"] >= 1) & dir_up)
            | ((d["tr_ema_stack_score"] <= -1) & dir_dn)
        )
        d["g_tr_stack_full_with"] = g(
            ((d["tr_ema_stack_score"] == 2) & dir_up)
            | ((d["tr_ema_stack_score"] == -2) & dir_dn)
        )
    if "tr_pvsra" in d.columns:
        d["g_tr_pvsra_with"] = g(
            ((d["tr_pvsra"] > 0) & dir_up) | ((d["tr_pvsra"] < 0) & dir_dn)
        )
    if "ema_cloud_pos" in d.columns:
        # cloud_pos > 1 = price above upper cloud (ema5 above ema13). <0 = below lower.
        d["g_tr_above_cloud"] = g(
            ((d["ema_cloud_pos"] > 1.0) & dir_up) | ((d["ema_cloud_pos"] < 0.0) & dir_dn)
        )
    if "tr_within_adr" in d.columns:
        d["g_tr_within_adr"] = g(d["tr_within_adr"] > 0)
    # active session (any)
    if all(c in d.columns for c in ("tr_in_london", "tr_in_ny", "tr_eu_brinks", "tr_us_brinks")):
        d["g_tr_in_active_session"] = g(
            (d["tr_in_london"] > 0)
            | (d["tr_in_ny"] > 0)
            | (d["tr_eu_brinks"] > 0)
            | (d["tr_us_brinks"] > 0)
        )
    if "tr_above_pp" in d.columns:
        # tr_above_pp is 1 if close > PP, 0 otherwise
        d["g_tr_above_pp"] = g(
            ((d["tr_above_pp"] > 0) & dir_up) | ((d["tr_above_pp"] == 0) & dir_dn)
        )
    # close vs ema50/ema200/ema800 (continuation direction)
    if "tr_close_vs_ema50" in d.columns:
        d["g_tr_above_ema50"] = g(
            ((d["tr_close_vs_ema50"] > 0) & dir_up) | ((d["tr_close_vs_ema50"] < 0) & dir_dn)
        )
    if "tr_close_vs_ema200" in d.columns:
        d["g_tr_above_ema200"] = g(
            ((d["tr_close_vs_ema200"] > 0) & dir_up) | ((d["tr_close_vs_ema200"] < 0) & dir_dn)
        )
    if "tr_close_vs_ema800" in d.columns:
        d["g_tr_above_ema800"] = g(
            ((d["tr_close_vs_ema800"] > 0) & dir_up) | ((d["tr_close_vs_ema800"] < 0) & dir_dn)
        )

    # --- TA ribbon / momentum gates ---
    if "ribbon_color" in d.columns:
        # 1,4 = bullish-shade; 2,3 = bearish-shade (per existing pattern)
        d["g_ribbon_agrees"] = g(
            (d["ribbon_color"].isin([1, 4]) & dir_up)
            | (d["ribbon_color"].isin([2, 3]) & dir_dn)
        )
    if "ribbon_lead_slope_bps" in d.columns:
        d["g_ribbon_slope_with"] = g(
            ((d["ribbon_lead_slope_bps"] > 0) & dir_up)
            | ((d["ribbon_lead_slope_bps"] < 0) & dir_dn)
        )
    if "ribbon_compression_bps" in d.columns:
        # used as a SUPPLEMENTAL filter — fire after compression -> any direction
        d["g_tight_ribbon"] = g(d["ribbon_compression_bps"] < 2.0)
    if "bb_pos_60s" in d.columns:
        d["g_bb_pos_with"] = g(
            ((d["bb_pos_60s"] > 0.5) & dir_up) | ((d["bb_pos_60s"] < 0.5) & dir_dn)
        )
    if "stoch_k_60s" in d.columns:
        d["g_stoch_with"] = g(
            ((d["stoch_k_60s"] > 50) & dir_up) | ((d["stoch_k_60s"] < 50) & dir_dn)
        )
    if "mfi_60s" in d.columns:
        d["g_mfi_with"] = g(
            ((d["mfi_60s"] > 50) & dir_up) | ((d["mfi_60s"] < 50) & dir_dn)
        )
    if "cci_60s" in d.columns:
        d["g_cci_with"] = g(
            ((d["cci_60s"] > 0) & dir_up) | ((d["cci_60s"] < 0) & dir_dn)
        )

    # --- Markov ---
    if "m1v" in d.columns:
        # m1v values: -1 / 0 / +1 typically (regime sign). guard for NaN
        d["g_markov_with"] = g(
            ((d["m1v"] > 0) & dir_up) | ((d["m1v"] < 0) & dir_dn)
        )

    # --- dev/vwap deviation gates ---
    dev_col = "dev_bps_vwap" if "dev_bps_vwap" in d.columns else (
        "dev_bps" if "dev_bps" in d.columns else (
            "dev_bps_15m" if "dev_bps_15m" in d.columns else None))
    if dev_col is not None:
        d["g_within_dev"] = g(
            (d[dev_col].abs() > 5.0)
            & (((d[dev_col] > 0) & dir_up) | ((d[dev_col] < 0) & dir_dn))
        )
        d["g_dev_extreme"] = g(
            (d[dev_col].abs() > 15.0)
            & (((d[dev_col] > 0) & dir_up) | ((d[dev_col] < 0) & dir_dn))
        )

    return d


def main():
    print("=" * 72)
    print("HYBRID GATE BUILDER — joining RF + TR + TA + Markov + computing gates")
    print("=" * 72)
    t0 = time.time()

    # S1.5 5m
    print("\n--- S1.5 5m ---")
    s15 = build_s15_joined()
    s15 = _add_gates(s15)
    out_s15 = RES / "s15_joined_all.parquet"
    s15.to_parquet(out_s15, index=False, compression="zstd")
    print(f"  wrote {out_s15} ({os.path.getsize(out_s15)/1024/1024:.1f} MB)")

    # S6 5m spike
    print("\n--- S6 5m spike ---")
    s6 = build_s6_joined()
    s6 = _add_gates(s6)
    out_s6 = RES / "s6_joined_all.parquet"
    s6.to_parquet(out_s6, index=False, compression="zstd")
    print(f"  wrote {out_s6} ({os.path.getsize(out_s6)/1024/1024:.1f} MB)")

    # v15m S7
    print("\n--- v15m S7 ---")
    v15m = build_v15m_joined()
    v15m = _add_gates(v15m)
    out_v15m = RES / "v15m_joined_all.parquet"
    v15m.to_parquet(out_v15m, index=False, compression="zstd")
    print(f"  wrote {out_v15m} ({os.path.getsize(out_v15m)/1024/1024:.1f} MB)")

    # quick gate counts summary
    for name, df in [("s15", s15), ("s6", s6), ("v15m", v15m)]:
        gates = [c for c in df.columns if c.startswith("g_")]
        counts = {c: int(df[c].sum()) for c in gates}
        print(f"\n[{name}] gate ones counts (n_total={len(df)}):")
        for c, k in sorted(counts.items(), key=lambda x: -x[1]):
            print(f"  {c}: {k} ({k/len(df)*100:.1f}%)")

    print(f"\nDONE in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
