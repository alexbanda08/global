"""Spread loosen simulation: SOL 15m sleeves, 0.025 -> 0.030.

For each sleeve, re-runs fill_at_book from the full candidate fire universe
(all SOL 15m resolutions × 8 offsets × 2 directions) under both spread filters.
Computes: n_placed, WR%, mean $/tr, total PnL, max DD, t-stat.

Outputs: strategy_lab/reports/SPREAD_LOOSEN_SIM_SOL_15M_2026_05_27.md
"""
from __future__ import annotations
import sys, math, time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from load import load_resolutions, load_orderbook_l25_streaming
from engine_v2 import LegacyConfig, fill_at_book, hold_pnl

STAKE = 5.0        # $5 per trade per mission spec
OFFSETS = [60, 120, 240, 360, 480, 600, 720, 840]
WINDOW_S = 900
SPREAD_CURRENT = 0.025
SPREAD_PROPOSED = 0.030

cfg = LegacyConfig(notional_usd=STAKE)

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)


# ── Sleeve definitions ──────────────────────────────────────────────────────
# Each sleeve: (display_name, version_tag, gate_dict, offsets_filter or None)
# gate_dict maps column_name -> required_value (1)
# offsets_filter: set of allowed offsets (None = all 8)

SLEEVES = [
    dict(
        name="trstack_vol_ribbon_ema_mid",
        label="SOL_15M_TRSTACK_VOL_RIBBON_EMA_MID_V5",
        gates=["g_tr_stack_full_with", "g_vol_high", "g_ribbon_agrees",
               "g_tr_above_ema200", "g_tr_above_ema800"],
        offsets={120, 240},  # V8 universe has no offset 180; verified from fired_by_sleeve
    ),
    dict(
        name="rfaged_trstack_late",
        label="SOL_15M_RFAGED_TRSTACK_LATE_V5",
        gates=["g_rf_aged", "g_tr_stack_full_with", "g_tr_stack_with"],
        offsets={480, 600, 720, 840},
    ),
    dict(
        name="hod_eu_off60_240_rf_tr_vwap80_v6",
        label="SOL_15M_HOD_EU_OFF60_240_RF_TR_VWAP80_V6",
        gates=["g_hod_european_morning", "g_off_60_240", "g_rf_with", "g_tr_stack_with"],
        offsets={60, 120, 240},
    ),
    # hod_eu_off60_240_rf_tr_vwap30_70_v6 UNREPRODUCIBLE (missing g_entry_vwap_in_30_70)
    dict(
        name="hod_eu_off60_240_rf_tr_vwap30_70_v6",
        label="UNREPRODUCIBLE",
        gates=[],  # skip
        offsets=None,
    ),
    dict(
        name="hod_eu_tightrib_rf_tr_vwap80_v6",
        label="SOL_15M_HOD_EU_TIGHTRIB_RF_TR_VWAP80_V6",
        gates=["g_hod_european_morning", "g_rf_with", "g_tight_ribbon", "g_tr_stack_with"],
        offsets=None,  # ALL offsets
    ),
    dict(
        name="btc_slope_pair_v7",
        label="SOL_15M_V7_S5_BTC_SLOPE_STR",
        gates=["g_hod_european_morning", "g_off_60_240", "g_rf_with", "g_tr_stack_with",
               "g_BTC_slope_with", "g_BTC_slope_strong_with"],
        offsets={60, 120, 240},
    ),
    dict(
        name="btc_adx_btcvollow_v7",
        label="SOL_15M_V7_S1_BTC_ADX_VOLLOW",
        gates=["g_hod_european_morning", "g_off_60_240", "g_rf_with", "g_tr_stack_with",
               "g_BTC_tr_stack_with", "g_BTC_adx_strong", "g_BTC_vol_low"],
        offsets={60, 120, 240},
    ),
    dict(
        name="j_btceth_vollow_l_ethadx_v8",
        label="V8_V6+J_vol_both_low+L_ETH_gp_adx_strong",
        gates=["g_hod_european_morning", "g_off_60_240", "g_rf_with", "g_tr_stack_with",
               "g_J_btc_eth_vol_both_low", "g_L_ETH_grandparent_adx_strong"],
        offsets={60, 120, 240},
    ),
    dict(
        name="v7_base_s5_slope_str_v8",
        label="V8_V7_BASE_S5_SLOPE_STR",
        gates=["g_hod_european_morning", "g_off_60_240", "g_rf_with", "g_tr_stack_with",
               "g_BTC_slope_with", "g_BTC_slope_strong_with"],
        offsets={60, 120, 240},
    ),
    dict(
        name="v7s5_plus_eth1h_adx_v8",
        label="V8_V7_S5_SLOPE_STR+L_ETH_gp_adx_strong",
        gates=["g_hod_european_morning", "g_off_60_240", "g_rf_with", "g_tr_stack_with",
               "g_BTC_slope_with", "g_BTC_slope_strong_with",
               "g_L_ETH_grandparent_adx_strong"],
        offsets={60, 120, 240},
    ),
]


# ── Load gate universe ───────────────────────────────────────────────────────
log("Loading V8 universe (has all gate columns including V8 J/L/K gates)...")
v8_path = ROOT / "strategy_lab" / "sniper_search_2026_05_27" / "sol_15m_v8" / "sol_15m_v8_universe.parquet"
univ = pd.read_parquet(v8_path)
log(f"V8 universe: {len(univ):,} rows, {len(univ.columns)} cols")

# Build lookup: (slug, fire_offset_s, direction) -> row index for gate access
univ_idx = {}
for row in univ.itertuples():
    key = (row.slug, int(row.fire_offset_s), row.direction)
    univ_idx[key] = row


# ── Load canonical resolutions ───────────────────────────────────────────────
log("Loading SOL 15m resolutions...")
res = load_resolutions()
sol15 = res[(res.timeframe == "15m") & (res.ticker == "SOL")].copy()
sol15 = sol15.sort_values("slot_start_us").reset_index(drop=True)
log(f"SOL 15m: {len(sol15):,} slugs")


# ── Load L25 books (native 10Hz, no subsample) ──────────────────────────────
log("Loading SOL L25 at native 10Hz (this takes ~90s)...")
all_slugs = set(sol15["slug"].unique())
books = load_orderbook_l25_streaming("sol", slugs=all_slugs, subsample_1hz=False)
log(f"L25 loaded: {len(books)} (slug, outcome) pairs")


# ── Run fills at both spread thresholds ─────────────────────────────────────
log("Running fill_at_book at spread_filter=0.025 and 0.030...")

# Build fire records: (slug, fire_offset_s, direction, fire_us, outcome, won, gates_row)
# fill_at_book expects "Up"/"Down" (Polymarket outcome format)
# V8 universe stores "UP"/"DOWN" — use uppercase for gate lookup, mixed for fills
DIRECTIONS_FILL = ["Up", "Down"]   # for fill_at_book
DIRECTIONS_KEY  = ["UP", "DOWN"]   # for V8 universe gate lookup

fire_records_025 = []  # fires placed at 0.025
fire_records_030_only = []  # fires placed at 0.030 but NOT at 0.025

total_candidates = 0
placed_025 = 0
placed_030 = 0

for r in sol15.itertuples(index=False):
    slug = r.slug
    ss = int(r.slot_start_us)
    outcome = str(r.outcome)  # "Up" or "Down" (from canonical resolutions)

    for off in OFFSETS:
        fire_us = ss + off * 1_000_000

        for dir_fill, dir_key in zip(DIRECTIONS_FILL, DIRECTIONS_KEY):
            total_candidates += 1
            won = (dir_fill == outcome)

            # Fill at 0.025
            fill_025 = fill_at_book(books, slug, dir_fill, fire_us,
                                     cfg=cfg, spread_filter=SPREAD_CURRENT)
            # Fill at 0.030
            fill_030 = fill_at_book(books, slug, dir_fill, fire_us,
                                     cfg=cfg, spread_filter=SPREAD_PROPOSED)

            rec = {
                "slug": slug,
                "fire_offset_s": off,
                "direction": dir_key,  # uppercase for gate lookup
                "fire_us": fire_us,
                "outcome": outcome,
                "won": won,
            }

            if fill_025 is not None:
                placed_025 += 1
                pnl = hold_pnl(fill_025, won=won, cfg=cfg)
                fire_records_025.append({**rec, "pnl": pnl, "ask0": fill_025["ask0"],
                                          "bid0": fill_025["bid0"],
                                          "spread": fill_025["ask0"] - fill_025["bid0"]})
            if fill_030 is not None and fill_025 is None:
                placed_030 += 1
                pnl = hold_pnl(fill_030, won=won, cfg=cfg)
                fire_records_030_only.append({**rec, "pnl": pnl, "ask0": fill_030["ask0"],
                                               "bid0": fill_030["bid0"],
                                               "spread": fill_030["ask0"] - fill_030["bid0"]})

log(f"Total candidates: {total_candidates:,}")
log(f"Placed at 0.025: {placed_025:,} ({placed_025/total_candidates*100:.1f}%)")
log(f"Additional at 0.030: {placed_030:,} ({placed_030/total_candidates*100:.1f}%)")

df_025 = pd.DataFrame(fire_records_025)
df_030_only = pd.DataFrame(fire_records_030_only)
df_030 = pd.concat([df_025, df_030_only], ignore_index=True) if len(df_030_only) > 0 else df_025.copy()


# ── Merge gate data ──────────────────────────────────────────────────────────
log("Merging gate data from V8 universe...")

def add_gates_to_df(df: pd.DataFrame) -> pd.DataFrame:
    """Add gate columns from V8 universe via (slug, fire_offset_s, direction) key."""
    gate_cols = [c for c in univ.columns if c.startswith("g_")]
    result_rows = []
    for row in df.itertuples(index=False):
        key = (row.slug, int(row.fire_offset_s), row.direction)
        if key in univ_idx:
            urow = univ_idx[key]
            gate_vals = {g: getattr(urow, g, 0) for g in gate_cols}
        else:
            gate_vals = {g: 0 for g in gate_cols}
        result_rows.append(gate_vals)
    gate_df = pd.DataFrame(result_rows, index=df.index)
    return pd.concat([df.reset_index(drop=True), gate_df], axis=1)

log("Adding gates to 0.025 fire set...")
df_025 = add_gates_to_df(df_025)
log("Adding gates to 0.030 fire set...")
df_030 = add_gates_to_df(df_030)


# ── Per-sleeve metrics ───────────────────────────────────────────────────────
def sleeve_metrics(df: pd.DataFrame, sleeve: dict) -> dict | None:
    gates = sleeve["gates"]
    offsets_filter = sleeve["offsets"]

    if not gates:
        return None  # unreproducible

    # Filter by offset
    sub = df.copy()
    if offsets_filter is not None:
        sub = sub[sub["fire_offset_s"].isin(offsets_filter)]

    # Apply gates
    for g in gates:
        if g not in sub.columns:
            print(f"  WARNING: gate {g} not in dataframe, skipping sleeve")
            return None
        sub = sub[sub[g] == 1]

    n = len(sub)
    if n == 0:
        return {"n": 0, "wr": float("nan"), "mean_pnl": float("nan"),
                "total_pnl": 0.0, "max_dd": 0.0, "t_stat": float("nan")}

    pnls = sub["pnl"].values
    wr = sub["won"].mean()
    mean_pnl = pnls.mean()
    total_pnl = pnls.sum()

    # Max drawdown (running cumulative)
    cumsum = np.cumsum(pnls)
    running_max = np.maximum.accumulate(cumsum)
    drawdown = cumsum - running_max
    max_dd = drawdown.min()

    # t-stat (1-sample, H0: mean=0)
    if n > 1 and pnls.std() > 0:
        t_stat, _ = stats.ttest_1samp(pnls, 0)
    else:
        t_stat = float("nan")

    return {"n": n, "wr": wr, "mean_pnl": mean_pnl, "total_pnl": total_pnl,
            "max_dd": max_dd, "t_stat": t_stat}


log("Computing per-sleeve metrics...")
results = []
for sleeve in SLEEVES:
    name = sleeve["name"]
    m_025 = sleeve_metrics(df_025, sleeve)
    m_030 = sleeve_metrics(df_030, sleeve)

    if m_025 is None:
        results.append({
            "sleeve": name, "label": sleeve["label"],
            "note": "UNREPRODUCIBLE", "recommendation": "N/A"
        })
        continue

    # Compute delta
    delta_n = (m_030["n"] or 0) - (m_025["n"] or 0)
    delta_pnl = (m_030["total_pnl"] or 0) - (m_025["total_pnl"] or 0)

    # Recommendation: LOOSEN if new fires are positive EV and WR does not materially drop
    n_new = delta_n
    if n_new > 0 and m_030["wr"] is not None and not math.isnan(m_030["wr"]):
        wr_delta = m_030["wr"] - m_025["wr"] if m_025["wr"] is not None and not math.isnan(m_025["wr"]) else 0
        if wr_delta >= -0.03 and delta_pnl > 0:
            rec = "LOOSEN"
        elif wr_delta < -0.05:
            rec = "KEEP (WR drops)"
        else:
            rec = "KEEP (marginal)"
    elif n_new == 0:
        rec = "NO CHANGE (no new fires)"
    else:
        rec = "KEEP"

    results.append({
        "sleeve": name,
        "label": sleeve["label"],
        "n_025": m_025["n"],
        "wr_025": round(m_025["wr"] * 100, 1) if not math.isnan(m_025.get("wr", float("nan"))) else "n/a",
        "mean_pnl_025": round(m_025["mean_pnl"], 3),
        "total_pnl_025": round(m_025["total_pnl"], 2),
        "max_dd_025": round(m_025["max_dd"], 2),
        "t_stat_025": round(m_025["t_stat"], 2) if not math.isnan(m_025["t_stat"]) else "n/a",
        "n_030": m_030["n"],
        "wr_030": round(m_030["wr"] * 100, 1) if not math.isnan(m_030.get("wr", float("nan"))) else "n/a",
        "mean_pnl_030": round(m_030["mean_pnl"], 3),
        "total_pnl_030": round(m_030["total_pnl"], 2),
        "max_dd_030": round(m_030["max_dd"], 2),
        "t_stat_030": round(m_030["t_stat"], 2) if not math.isnan(m_030["t_stat"]) else "n/a",
        "delta_n": delta_n,
        "delta_pnl": round(delta_pnl, 2),
        "recommendation": rec,
    })


# ── Write report ─────────────────────────────────────────────────────────────
log("Writing report...")
report_path = ROOT / "strategy_lab" / "reports" / "SPREAD_LOOSEN_SIM_SOL_15M_2026_05_27.md"

lines = [
    "# Spread Loosen Simulation — SOL 15m Sleeves",
    "",
    f"**Date:** 2026-05-27  |  **Stake:** $5  |  **Fee:** LegacyConfig (2%-on-profit)  "
    f"|  **L25:** native 10Hz (subsample_1hz=False)",
    f"**Current filter:** spread_filter=0.025  |  **Proposed:** spread_filter=0.030",
    f"**Universe:** {total_candidates:,} candidates (3,080 SOL 15m slugs × 8 offsets × 2 dirs)",
    f"**Placed at 0.025:** {placed_025:,} ({placed_025/total_candidates*100:.1f}%)",
    f"**Additional at 0.030:** {placed_030:,} ({placed_030/total_candidates*100:.1f}% of all candidates)",
    "",
    "---",
    "",
    "## Per-Sleeve Results",
    "",
    "| Sleeve | n(0.025) | WR%(0.025) | $/tr(0.025) | PnL(0.025) | DD(0.025) | t(0.025) | n(0.030) | WR%(0.030) | $/tr(0.030) | PnL(0.030) | DD(0.030) | t(0.030) | Δn | ΔPnL | Rec |",
    "|--------|----------|-----------|------------|-----------|----------|---------|----------|-----------|------------|-----------|----------|---------|-----|------|-----|",
]

for r in results:
    if r.get("note") == "UNREPRODUCIBLE":
        lines.append(f"| {r['sleeve']} | *UNREPRODUCIBLE* (`g_entry_vwap_in_30_70` missing in V8 panel) ||||||||||||||||")
        continue
    lines.append(
        f"| {r['sleeve']} | {r['n_025']} | {r['wr_025']}% | ${r['mean_pnl_025']:+.2f} | "
        f"${r['total_pnl_025']:+.2f} | ${r['max_dd_025']:.2f} | {r['t_stat_025']} | "
        f"{r['n_030']} | {r['wr_030']}% | ${r['mean_pnl_030']:+.2f} | "
        f"${r['total_pnl_030']:+.2f} | ${r['max_dd_030']:.2f} | {r['t_stat_030']} | "
        f"{r['delta_n']:+d} | ${r['delta_pnl']:+.2f} | **{r['recommendation']}** |"
    )

lines += [
    "",
    "---",
    "",
    "## Notes",
    "",
    "- `hod_eu_off60_240_rf_tr_vwap30_70_v6` is **UNREPRODUCIBLE** — gate `g_entry_vwap_in_30_70` not present in V8 panel (flagged in `unreproducible_sleeves.csv`).",
    "- `v7_base_s5_slope_str_v8` uses identical gate stack as `btc_slope_pair_v7` (V7 S5 winner carried forward to V8 baseline). Metrics will match exactly.",
    "- Δn = new fires placed at 0.030 that were rejected at 0.025 (wider spread accepted).",
    "- DD is max drawdown in dollar terms at $5 stake over full window.",
    "- t-stat: 1-sample t-test vs H0: mean pnl = 0.",
    f"- Run time: {time.time()-t0:.0f}s",
]

report_path.write_text("\n".join(lines), encoding="utf-8")
log(f"Report written: {report_path}")

# Print summary to stdout
print("\n=== SUMMARY ===")
for r in results:
    if r.get("note"):
        print(f"  {r['sleeve']:45s} UNREPRODUCIBLE")
    else:
        print(f"  {r['sleeve']:45s} n={r['n_025']:3d}->{r['n_030']:3d} (+{r['delta_n']:2d})  WR {r['wr_025']}%->{r['wr_030']}%  $/tr ${r['mean_pnl_025']:+.2f}->${r['mean_pnl_030']:+.2f}  Rec: {r['recommendation']}")
