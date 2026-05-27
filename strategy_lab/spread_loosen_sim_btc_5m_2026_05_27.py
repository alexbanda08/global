"""
Spread-loosen impact simulation: BTC 5m sleeves
0.020 -> 0.025 same-token bid-ask spread filter

For each of the 8 target V5 sleeves:
  1. "Current" (0.020): metrics from _sniper_btc_5m_enriched.parquet (already computed)
  2. "Proposed" (0.025): current + newly admitted fires in (0.020, 0.025] spread

Strategy:
- Build full raw fire grid: BTC 5m resolutions x [30,60,90,120,150,180,210,240,270]s offsets x 2 directions
- Subtract v8-enriched fires (those that passed 0.020) to get "rejected candidates"
- For each rejected candidate, load L25 book and check spread
- Keep those with spread in (0.020, 0.025] -- "borderline" fires
- Compute their PnL with LegacyConfig
- Merge gate columns from v8+v7 universes onto borderline fires
- For each sleeve: apply gate filter to borderline fires, combine with current fires, compute metrics
"""
from __future__ import annotations

import gc
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

from load import (
    load_resolutions,
    load_orderbook_l25_streaming,
)
from engine_v2 import LegacyConfig, fill_at_book, hold_pnl

ASSET = "BTC"
TF = "5m"
WINDOW_S = 300
OFFSETS = [30, 60, 90, 120, 150, 180, 210, 240, 270]
SPREAD_CURRENT = 0.020
SPREAD_PROPOSED = 0.025
NOTIONAL = 5.0  # $5 stake per task spec

RES_DIR = ROOT / "data" / "v4" / "canonical" / "_results"
ENR_PATH = RES_DIR / "_sniper_btc_5m_enriched.parquet"
V7_UNIV_PATH = ROOT / "strategy_lab" / "sniper_search_2026_05_27" / "btc_5m_v7" / "_sandbox" / "universe_v7.parquet"
V8_UNIV_PATH = ROOT / "strategy_lab" / "sniper_search_2026_05_27" / "btc_5m_v8" / "_sandbox" / "universe_v8.parquet"
BORDERLINE_CACHE = RES_DIR / "_spread_loosen_borderline_btc5m.parquet"
OUT_DIR = ROOT / "strategy_lab" / "reports"
OUT_DIR.mkdir(parents=True, exist_ok=True)

cfg = LegacyConfig(notional_usd=NOTIONAL)

# ---------------------------------------------------------------------------
# Sleeve definitions: live name -> gate columns that must ALL == 1
# ---------------------------------------------------------------------------
SLEEVES = {
    "poly_sniper_v5_btc_5m_ts_mpskew_s6_0_60": {
        "gates": ["g_mp_skew_with"],
        "offsets": list(range(0, 61, 15)),   # s6 offset range 0-60
        "universe": "v8",
    },
    "poly_sniper_v5_btc_5m_ts_mpskew_any_off30": {
        "gates": ["g_mp_skew_with"],
        "offsets": [30],
        "universe": "v8",
    },
    "poly_sniper_v5_btc_5m_parent15m_slope_ts_mpnx_v7": {
        "gates": ["g_parent_15m_slope_with", "g_trend_slope_strong_with", "g_mp_no_extreme"],
        "offsets": None,  # any
        "universe": "v8",
    },
    "poly_sniper_v5_btc_5m_slotend_ofi_ts_v7": {
        "gates": ["g_slot_end_ofi_with", "g_trend_slope_strong_with"],
        "offsets": None,  # late offsets per v7 brief
        "universe": "v7",
    },
    "poly_sniper_v5_btc_5m_parent15m_notrang_ts_mpskew_v7": {
        "gates": ["g_parent_15m_not_ranging", "g_trend_slope_strong_with", "g_mp_skew_with"],
        "offsets": None,
        "universe": "v8",
    },
    "poly_sniper_v5_btc_5m_l_1hrf_imb5_rf_v8": {
        "gates": ["g_1h_rf_with", "g_imb5_strong_with", "g_rf_with"],
        "offsets": None,
        "universe": "v8",
    },
    "poly_sniper_v5_btc_5m_l_1hrf_imb5_ribbon_v8": {
        "gates": ["g_1h_rf_with", "g_imb5_strong_with", "g_ribbon_agrees"],
        "offsets": None,
        "universe": "v8",
    },
    "poly_sniper_v5_btc_5m_q_parent15mslope_ts_imb5_v8": {
        "gates": ["g_parent_15m_slope_with", "g_trend_slope_strong_with", "g_imb5_strong_with"],
        "offsets": None,
        "universe": "v8",
    },
}


# ---------------------------------------------------------------------------
# Metrics helpers
# ---------------------------------------------------------------------------

def compute_metrics(pnl_series: pd.Series) -> dict:
    n = len(pnl_series)
    if n == 0:
        return dict(n=0, wr=float("nan"), mean_dpt=float("nan"),
                    total_pnl=float("nan"), max_dd=float("nan"), t_stat=float("nan"))
    wins = (pnl_series > 0).sum()
    wr = wins / n
    mean_dpt = pnl_series.mean()
    total_pnl = pnl_series.sum()
    cum = pnl_series.cumsum().values
    peak = np.maximum.accumulate(cum)
    dd = (peak - cum)
    max_dd = float(dd.max()) if len(dd) > 0 else 0.0
    std = pnl_series.std()
    t_stat = mean_dpt / (std / math.sqrt(n)) if (std > 0 and n > 1) else float("nan")
    return dict(n=int(n), wr=round(float(wr), 4), mean_dpt=round(float(mean_dpt), 4),
                total_pnl=round(float(total_pnl), 2), max_dd=round(max_dd, 2),
                t_stat=round(float(t_stat), 3) if not math.isnan(t_stat) else float("nan"))


# ---------------------------------------------------------------------------
# Load existing universes
# ---------------------------------------------------------------------------
print("[1/5] Loading enriched universe (v8) ...", flush=True)
enr = pd.read_parquet(ENR_PATH)
enr_btc5m = enr[(enr["asset"] == ASSET) & (enr["tf"] == TF)].copy()
print(f"  v8 enriched BTC 5m: {len(enr_btc5m):,} fires (already passed spread=0.020)")

# Load v8 sandbox universe which has additional gate columns (g_1h_rf_with, g_parent_15m_*, etc.)
print("[1a] Loading v8 sandbox universe for extra gate columns ...", flush=True)
v8u = pd.read_parquet(V8_UNIV_PATH)
extra_gate_cols_v8 = [c for c in v8u.columns if c.startswith("g_") and c not in enr_btc5m.columns]
print(f"  Extra gate cols from v8 sandbox: {extra_gate_cols_v8}")
if extra_gate_cols_v8:
    v8u_key = v8u[["fire_us", "slug", "direction"] + extra_gate_cols_v8].drop_duplicates(["fire_us", "slug", "direction"])
    enr_btc5m = enr_btc5m.merge(v8u_key, on=["fire_us", "slug", "direction"], how="left")
    for c in extra_gate_cols_v8:
        enr_btc5m[c] = enr_btc5m[c].fillna(0).astype(np.int8)
    print(f"  After merge: {len(enr_btc5m):,}")

print("[1b] Loading v7 universe for g_slot_end_ofi_with ...", flush=True)
v7u = pd.read_parquet(V7_UNIV_PATH)
v7u_btc5m = v7u[(v7u["asset"] == ASSET) & (v7u["tf"] == TF)].copy() if "asset" in v7u.columns else v7u.copy()
# v7 universe uses fire_us + slug as key
v7_ofi = v7u_btc5m[["fire_us", "slug", "direction", "g_slot_end_ofi_with"]].drop_duplicates(
    ["fire_us", "slug", "direction"])
print(f"  v7 BTC 5m: {len(v7u_btc5m):,} fires")

# Merge g_slot_end_ofi_with into enriched
if "g_slot_end_ofi_with" not in enr_btc5m.columns:
    enr_btc5m = enr_btc5m.merge(v7_ofi, on=["fire_us", "slug", "direction"], how="left")
    enr_btc5m["g_slot_end_ofi_with"] = enr_btc5m["g_slot_end_ofi_with"].fillna(0).astype(np.int8)

# Build per-slug-direction gate lookup for borderline fire enrichment
# Features at ws_s are constant per slug (independent of fire_us offset)
# So we can use ANY fire from same slug as proxy for gate values
all_gate_cols = [c for c in enr_btc5m.columns if c.startswith("g_")]
# Take first occurrence per (slug, direction) for fast lookup
enr_slug_gates = enr_btc5m.groupby(["slug", "direction"])[all_gate_cols].first().reset_index()
print(f"  After merge: {len(enr_btc5m):,} fires with g_slot_end_ofi_with")

# ---------------------------------------------------------------------------
# Build raw fire grid from resolutions
# ---------------------------------------------------------------------------
print("[2/5] Building raw fire grid ...", flush=True)
res = load_resolutions()
res_btc5m = res[res["ticker"] == "BTC"].copy()
print(f"  BTC 5m resolutions: {len(res_btc5m):,}")

# Build all (slug, fire_us, direction) combos
fire_rows = []
for _, r in res_btc5m.iterrows():
    ss = int(r["slot_start_us"])
    for off in OFFSETS:
        fu = ss + off * 1_000_000
        if fu > int(r["slot_end_us"]):
            continue
        for direction in ["UP", "DOWN"]:
            fire_rows.append({
                "slug": r["slug"],
                "slot_start_us": ss,
                "slot_end_us": int(r["slot_end_us"]),
                "fire_us": fu,
                "fire_offset_s": off,
                "direction": direction,
                "outcome": str(r["outcome"]),
                "ws_s": ss // 1_000_000 - WINDOW_S,
            })

raw_fires = pd.DataFrame(fire_rows)
print(f"  Raw fire candidates: {len(raw_fires):,}")

# Fires in enriched (passed spread=0.020)
passed_key = set(zip(enr_btc5m["fire_us"], enr_btc5m["slug"], enr_btc5m["direction"]))
raw_fires["_passed_020"] = raw_fires.apply(
    lambda r: (r["fire_us"], r["slug"], r["direction"]) in passed_key, axis=1
)
rejected_fires = raw_fires[~raw_fires["_passed_020"]].copy()
print(f"  Rejected at spread=0.020: {len(rejected_fires):,} candidates")

# ---------------------------------------------------------------------------
# Load L25 books for rejected fires and check spread
# ---------------------------------------------------------------------------
print("[3/5] Checking spread for rejected fires (loading L25 books) ...", flush=True)

if BORDERLINE_CACHE.exists():
    print(f"  Loading borderline fires from cache: {BORDERLINE_CACHE}")
    border_rows_df = pd.read_parquet(BORDERLINE_CACHE)
    borderline_rows = border_rows_df.to_dict("records")
    print(f"  Loaded {len(borderline_rows):,} borderline fires from cache")
else:
    t0 = time.time()
    rejected_slugs = set(rejected_fires["slug"].unique())
    print(f"  Unique slugs to load: {len(rejected_slugs):,}")

    borderline_rows = []
    slugs_list = sorted(rejected_slugs)
    batch_size = 500

    for batch_start in range(0, len(slugs_list), batch_size):
        batch_slugs = set(slugs_list[batch_start:batch_start + batch_size])
        try:
            books = load_orderbook_l25_streaming(
                ASSET.lower(), slugs=batch_slugs, subsample_1hz=False
            )
        except Exception as e:
            print(f"  WARNING: book load failed for batch {batch_start}: {e}")
            continue

        batch_fires = rejected_fires[rejected_fires["slug"].isin(batch_slugs)]

        for _, row in batch_fires.iterrows():
            fire_us = int(row["fire_us"])
            slug = row["slug"]
            direction = row["direction"]
            outcome_str = row["outcome"]

            outcome = "Up" if direction == "UP" else "Down"

            # Try fill at proposed spread
            fill_025 = fill_at_book(
                books, slug, outcome, fire_us,
                cfg=cfg, spread_filter=SPREAD_PROPOSED, notional_usd=NOTIONAL
            )
            if fill_025 is None:
                continue

            # Check it fails at current (should, since it was rejected)
            fill_020 = fill_at_book(
                books, slug, outcome, fire_us,
                cfg=cfg, spread_filter=SPREAD_CURRENT, notional_usd=NOTIONAL
            )
            if fill_020 is not None:
                # Shouldn't happen since it was "rejected", skip
                continue

            # Compute PnL
            won = (direction == "UP" and outcome_str == "Up") or \
                  (direction == "DOWN" and outcome_str == "Down")
            pnl = hold_pnl(fill_025, won=won, cfg=cfg)
            if math.isnan(pnl):
                continue

            borderline_rows.append({
                "slug": slug,
                "fire_us": fire_us,
                "fire_offset_s": int(row["fire_offset_s"]),
                "direction": direction,
                "slot_start_us": int(row["slot_start_us"]),
                "slot_end_us": int(row["slot_end_us"]),
                "outcome": outcome_str,
                "won": int(won),
                "pnl_legacy_usd": pnl,
                "ask0": fill_025.get("ask0", float("nan")),
                "bid0": fill_025.get("bid0", float("nan")),
                "entry_vwap": fill_025.get("vwap", float("nan")),
            })

        del books
        gc.collect()
        elapsed = time.time() - t0
        print(f"  batch {batch_start+batch_size}/{len(slugs_list)} done | "
              f"borderline so far: {len(borderline_rows):,} | {elapsed:.0f}s", flush=True)

    print(f"\n  Borderline fires (0.020, 0.025]: {len(borderline_rows):,} total")
    # Save cache
    if borderline_rows:
        cache_df = pd.DataFrame(borderline_rows)
        cache_df.to_parquet(BORDERLINE_CACHE, index=False)
        print(f"  Saved borderline cache to {BORDERLINE_CACHE}")

# ---------------------------------------------------------------------------
# Enrich borderline fires with gate columns
# ---------------------------------------------------------------------------
print("[4/5] Enriching borderline fires with gate columns ...", flush=True)

if borderline_rows:
    border_df = pd.DataFrame(borderline_rows)

    # Enrich borderline fires with gate columns via (slug, direction) join
    # Gate values are computed at ws_s (same for all offsets in a slug)
    # So ANY fire from same slug has the same gate values for slow-changing features
    # This is approximate for microstructure gates (imb5, mp_skew) but conservative
    gate_cols_all = [c for c in enr_btc5m.columns if c.startswith("g_")]

    border_df = border_df.merge(enr_slug_gates, on=["slug", "direction"], how="left")

    # For g_slot_end_ofi_with from v7: same approach
    if "g_slot_end_ofi_with" not in border_df.columns or border_df["g_slot_end_ofi_with"].isna().any():
        v7_slug_gates = v7u_btc5m.groupby(["slug", "direction"])["g_slot_end_ofi_with"].first().reset_index()
        border_df = border_df.merge(v7_slug_gates, on=["slug", "direction"], how="left",
                                     suffixes=("", "_v7"))
        if "g_slot_end_ofi_with_v7" in border_df.columns:
            border_df["g_slot_end_ofi_with"] = border_df["g_slot_end_ofi_with"].fillna(
                border_df["g_slot_end_ofi_with_v7"])
            border_df = border_df.drop(columns=["g_slot_end_ofi_with_v7"])

    # Fill missing gate cols with 0 (slugs not in enriched at all = no book data = likely noise)
    for gc_col in gate_cols_all:
        if gc_col in border_df.columns:
            border_df[gc_col] = border_df[gc_col].fillna(0).astype(np.int8)
        else:
            border_df[gc_col] = np.int8(0)

    # Check match rate on a key gate
    test_gate = "g_rf_with"
    match_pct = (border_df[test_gate] != 0).mean() if test_gate in border_df.columns else 0
    slugs_matched = border_df["slug"].isin(set(enr_btc5m["slug"])).mean()
    print(f"  Borderline fires with gate info: {len(border_df):,}")
    print(f"  Slug match rate vs enriched: {slugs_matched:.1%}")
    print(f"  Borderline WR: {border_df['won'].mean():.3f}")
    print(f"  Borderline mean dpt ($5): {border_df['pnl_legacy_usd'].mean():.3f}")
else:
    border_df = pd.DataFrame()
    print("  No borderline fires found")


# ---------------------------------------------------------------------------
# Per-sleeve analysis
# ---------------------------------------------------------------------------
print("[5/5] Computing per-sleeve metrics ...", flush=True)

results = []

for sleeve_id, spec in SLEEVES.items():
    gates = spec["gates"]
    off_filter = spec["offsets"]
    universe_src = spec["universe"]

    # --- CURRENT (spread=0.020) ---
    cur = enr_btc5m.copy()
    if off_filter is not None:
        cur = cur[cur["fire_offset_s"].isin(off_filter)]

    # Check gates exist
    missing_gates = [g for g in gates if g not in cur.columns]
    if missing_gates:
        print(f"  {sleeve_id}: MISSING gates {missing_gates} - skipping")
        continue

    for g in gates:
        cur = cur[cur[g] == 1]

    metrics_020 = compute_metrics(cur["pnl_legacy_usd"])

    # --- PROPOSED (spread=0.025) ---
    if len(border_df) > 0:
        new_fires = border_df.copy()
        if off_filter is not None:
            new_fires = new_fires[new_fires["fire_offset_s"].isin(off_filter)]

        for g in gates:
            if g in new_fires.columns:
                new_fires = new_fires[new_fires[g] == 1]
            else:
                new_fires = new_fires.iloc[0:0]  # empty
    else:
        new_fires = pd.DataFrame({"pnl_legacy_usd": []})

    combined_pnl = pd.concat([cur["pnl_legacy_usd"], new_fires["pnl_legacy_usd"]], ignore_index=True)
    metrics_025 = compute_metrics(combined_pnl)

    results.append({
        "sleeve_id": sleeve_id,
        "gates": "+".join(gates),
        # Current (0.020)
        "n_020": metrics_020["n"],
        "wr_020": metrics_020["wr"],
        "mean_dpt_020": metrics_020["mean_dpt"],
        "total_pnl_020": metrics_020["total_pnl"],
        "max_dd_020": metrics_020["max_dd"],
        "t_stat_020": metrics_020["t_stat"],
        # Proposed (0.025)
        "n_025": metrics_025["n"],
        "wr_025": metrics_025["wr"],
        "mean_dpt_025": metrics_025["mean_dpt"],
        "total_pnl_025": metrics_025["total_pnl"],
        "max_dd_025": metrics_025["max_dd"],
        "t_stat_025": metrics_025["t_stat"],
        # Deltas
        "d_n": metrics_025["n"] - metrics_020["n"],
        "d_n_pct": round((metrics_025["n"] - metrics_020["n"]) / max(metrics_020["n"], 1), 3),
        "d_wr": round(metrics_025["wr"] - metrics_020["wr"], 4) if not math.isnan(metrics_025["wr"]) and not math.isnan(metrics_020["wr"]) else float("nan"),
        "d_dpt": round(metrics_025["mean_dpt"] - metrics_020["mean_dpt"], 4) if not math.isnan(metrics_025["mean_dpt"]) and not math.isnan(metrics_020["mean_dpt"]) else float("nan"),
        "d_total_pnl": round(metrics_025["total_pnl"] - metrics_020["total_pnl"], 2) if not math.isnan(metrics_025["total_pnl"]) and not math.isnan(metrics_020["total_pnl"]) else float("nan"),
        "n_borderline_added": len(new_fires),
    })

    print(f"  {sleeve_id.replace('poly_sniper_v5_btc_5m_', '')}: "
          f"n_020={metrics_020['n']} -> n_025={metrics_025['n']} (+{len(new_fires)}) | "
          f"WR: {metrics_020['wr']:.3f} -> {metrics_025['wr']:.3f} | "
          f"dpt: {metrics_020['mean_dpt']:.3f} -> {metrics_025['mean_dpt']:.3f}", flush=True)


# ---------------------------------------------------------------------------
# Save results
# ---------------------------------------------------------------------------
results_df = pd.DataFrame(results)
csv_path = OUT_DIR / "SPREAD_LOOSEN_SIM_BTC_5M_2026_05_27.csv"
results_df.to_csv(csv_path, index=False)
print(f"\nResults saved to {csv_path}")
print(results_df.to_string())
print("\n=== DONE ===")
