"""Spread-loosen sim: ETH 5m + 15m sleeves, 0.020 vs 0.025 same-token bid-ask filter.

Usage: C:/Python314/python.exe strategy_lab/spread_loosen_sim_eth_2026_05_27.py

Output: strategy_lab/reports/SPREAD_LOOSEN_SIM_ETH_2026_05_27.md
"""
from __future__ import annotations

import math
import sys
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

from data.v4.canonical.load import load_orderbook_l25_streaming
from strategy_lab.engine_v2 import (
    LegacyConfig, fill_at_book, hold_pnl, find_book_strict
)

NOTIONAL = 5.0  # $5 stake
SPREAD_CURR = 0.020
SPREAD_PROP = 0.025
REPORT_PATH = ROOT / "strategy_lab" / "reports" / "SPREAD_LOOSEN_SIM_ETH_2026_05_27.md"

import dataclasses
cfg = dataclasses.replace(LegacyConfig(), notional_usd=NOTIONAL)

# ---------------------------------------------------------------------------
# Sleeve definitions: name → (source, gate_stack or None)
# Source: 'fbsleeve' uses fired_by_sleeve.parquet with sleeve_id filter
#         'v8_5m'    uses eth5m_v8_universe with gate string
#         'v8_15m'   uses eth_15m_enriched_v8 with gate string
# ---------------------------------------------------------------------------

@dataclass
class SleeveSpec:
    display_name: str
    source: str             # 'fbsleeve', 'v8_5m', 'v8_15m'
    sleeve_id: str = ""     # for fbsleeve
    gate_stack: str = ""    # for v8_*
    tf: str = "5m"


SLEEVES: list[SleeveSpec] = [
    # ---- ETH 5m V5 ----
    SleeveSpec("poly_sniper_v5_eth_5m_tr200_mp_sms_active_off120",       "fbsleeve", sleeve_id="ETH_5M_TR200_MP_SMS_ACTIVE_OFF120_V5",    tf="5m"),
    SleeveSpec("poly_sniper_v5_eth_5m_tr200_mp_mpnx_sms_off120",         "fbsleeve", sleeve_id="ETH_5M_TR200_MP_MPNX_SMS_OFF120_V5",      tf="5m"),
    SleeveSpec("poly_sniper_v5_eth_5m_cloud_mp_sms_active_off120",       "fbsleeve", sleeve_id="ETH_5M_CLOUD_MP_SMS_ACTIVE_OFF120_V5",    tf="5m"),
    # ---- ETH 5m V6 ----
    SleeveSpec("poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_v6",         "fbsleeve", sleeve_id="ETH_5M_CLOUD_RIBBON_MP_HURST_V6",         tf="5m"),
    SleeveSpec("poly_sniper_v5_eth_5m_v5repl_off120_v6",                 "fbsleeve", sleeve_id="ETH_5M_V5_REPL_OFF120_V6",               tf="5m"),
    SleeveSpec("poly_sniper_v5_eth_5m_bb_mp_hurst_band_v6",              "fbsleeve", sleeve_id="ETH_5M_BB_MP_HURST_BAND_V6",             tf="5m"),
    # ---- ETH 5m V7 ----
    SleeveSpec("poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7",            "fbsleeve", sleeve_id="ETH_5M_V7_C1_CLOUD_VWAP_HURST_MP",       tf="5m"),
    SleeveSpec("poly_sniper_v5_eth_5m_ema50_hurst_parent15mrang_v7",     "fbsleeve", sleeve_id="ETH_5M_V7_C2_EMA50_HURST_PARENT_RANGING", tf="5m"),
    SleeveSpec("poly_sniper_v5_eth_5m_v6c3_parent15mrang_v7",            "fbsleeve", sleeve_id="ETH_5M_V7_C3_V6C3_PARENT_RANGING",       tf="5m"),
    SleeveSpec("poly_sniper_v5_eth_5m_ema200_vwap_regimerang_xa3_v7",    "fbsleeve", sleeve_id="ETH_5M_V7_C4_XA_3SOURCE_PARENT_RANGING", tf="5m"),
    # ---- ETH 5m V8 (from eth5m_v8_universe) ----
    SleeveSpec("poly_sniper_v5_eth_5m_k_hurst_ts_cci_tod_euus_v8",       "v8_5m",
               gate_stack="g_hurst_trend_with&g_trend_slope_with&g_cci_with&g_tod_europe_us_window", tf="5m"),
    SleeveSpec("poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8",     "v8_5m",
               gate_stack="g_tr_above_ema50&g_hurst_trending&g_grandparent_trend_with", tf="5m"),
    SleeveSpec("poly_sniper_v5_eth_5m_lq_ema50_hurst_grandparent_prev15m_v8", "v8_5m",
               gate_stack="g_tr_above_ema50&g_hurst_trend_with&g_grandparent_trend_with&g_q_prev15m_agrees", tf="5m"),
    # ---- ETH 15m V5 ----
    SleeveSpec("poly_sniper_v5_eth_15m_trstack_vwap_vol_offearly",       "fbsleeve", sleeve_id="ETH_15M_TRSTACK_VWAP_VOL_OFFEARLY_V5",   tf="15m"),
    SleeveSpec("poly_sniper_v5_eth_15m_trstack_vwap_offearly",           "fbsleeve", sleeve_id="ETH_15M_TRSTACK_VWAP_OFFEARLY_V5",       tf="15m"),
    # ---- ETH 15m V6 ----
    SleeveSpec("poly_sniper_v5_eth_15m_trstack_vwap_vol_offearly_band_v6", "fbsleeve", sleeve_id="ETH_15M_TRSTACK_VWAP_VOL_OFFEARLY_BAND_V6", tf="15m"),
    SleeveSpec("poly_sniper_v5_eth_15m_pw_trendslope_trstack_offearly_v6", "fbsleeve", sleeve_id="ETH_15M_PW_TRENDSLOPE_TRSTACK_VWAP_VOL_OFFEARLY_V6", tf="15m"),
    # ---- ETH 15m V7 ----
    SleeveSpec("poly_sniper_v5_eth_15m_pi_btc15m_trend_v7",              "fbsleeve", sleeve_id="ETH_15M_V7_PI_S1_BTC_15M_TREND",         tf="15m"),
    # ---- ETH 15m V8 (from eth_15m_enriched_v8) ----
    SleeveSpec("poly_sniper_v5_eth_15m_baseline_v7_top_replicate_v8",    "v8_15m",
               gate_stack="g_tr_stack_full_with&g_above_1h_dailyvwap_with&g_offset_early&g_vol_high&g_pw_btc_15m_trend_with", tf="15m"),
    SleeveSpec("poly_sniper_v5_eth_15m_pj_btc_and_sol_trend_sep_v8",     "v8_15m",
               gate_stack="g_tr_stack_full_with&g_above_1h_dailyvwap_with&g_offset_early&g_vol_high&g_pw_btc_15m_trend_with&g_pw_sol_15m_trend_with", tf="15m"),
]


# ---------------------------------------------------------------------------
# Load fire universes
# ---------------------------------------------------------------------------
log("Loading fired_by_sleeve.parquet (V5/V6/V7)...")
FBS_PATH = ROOT / "strategy_lab" / "sniper_search_2026_05_27" / "_overlap_audit_v5_v6_v7" / "fired_by_sleeve.parquet"
fbs = pd.read_parquet(FBS_PATH)
fbs_eth = fbs[fbs["asset"] == "ETH"].copy()
log(f"  fired_by_sleeve ETH rows: {len(fbs_eth)}, sleeves: {fbs_eth['sleeve_id'].nunique()}")

log("Loading ETH 5m v8 universe...")
ETH5M_V8_PATH = ROOT / "data" / "v4" / "canonical" / "_results" / "_sniper_eth5m_v8_universe.parquet"
eth5m_v8 = pd.read_parquet(ETH5M_V8_PATH, columns=[
    "slug", "fire_us", "direction", "won", "pnl_legacy_usd", "entry_vwap",
    "g_hurst_trend_with", "g_trend_slope_with", "g_cci_with", "g_tod_europe_us_window",
    "g_tr_above_ema50", "g_hurst_trending", "g_grandparent_trend_with",
    "g_q_prev15m_agrees",
])
log(f"  ETH 5m v8 universe: {len(eth5m_v8)} rows")

log("Loading ETH 15m v8 enriched...")
ETH15M_V8_PATH = ROOT / "strategy_lab" / "sniper_search_2026_05_27" / "eth_15m_v8" / "eth_15m_enriched_v8.parquet"
eth15m_v8 = pd.read_parquet(ETH15M_V8_PATH, columns=[
    "slug", "fire_us", "direction", "won", "pnl_legacy_usd", "entry_vwap",
    "g_tr_stack_full_with", "g_above_1h_dailyvwap_with", "g_offset_early",
    "g_vol_high", "g_pw_btc_15m_trend_with", "g_pw_sol_15m_trend_with",
    "g_2a_btc_sol_trend_with",
])
log(f"  ETH 15m v8 enriched: {len(eth15m_v8)} rows")


# ---------------------------------------------------------------------------
# Build per-sleeve fire DataFrames (slug, fire_us, direction, won, pnl_legacy_25)
# ---------------------------------------------------------------------------
def apply_gate_stack(df: pd.DataFrame, gate_stack: str) -> pd.DataFrame:
    gates = gate_stack.split("&")
    mask = pd.Series(True, index=df.index)
    for g in gates:
        g = g.strip()
        if g not in df.columns:
            log(f"  WARNING: gate '{g}' not in df columns, skipping")
            continue
        mask = mask & (df[g].astype(bool))
    return df[mask].copy()


def get_sleeve_fires(spec: SleeveSpec) -> pd.DataFrame:
    """Returns df with cols: slug, fire_us, direction, won, pnl_25"""
    if spec.source == "fbsleeve":
        sub = fbs_eth[fbs_eth["sleeve_id"] == spec.sleeve_id].copy()
        sub = sub.rename(columns={"pnl_legacy_usd": "pnl_25"})[
            ["slug", "fire_us", "direction", "won", "pnl_25"]
        ]
        return sub
    elif spec.source == "v8_5m":
        sub = apply_gate_stack(eth5m_v8, spec.gate_stack)
        sub = sub.rename(columns={"pnl_legacy_usd": "pnl_25"})[
            ["slug", "fire_us", "direction", "won", "pnl_25", "entry_vwap"]
        ]
        return sub
    elif spec.source == "v8_15m":
        sub = apply_gate_stack(eth15m_v8, spec.gate_stack)
        sub = sub.rename(columns={"pnl_legacy_usd": "pnl_25"})[
            ["slug", "fire_us", "direction", "won", "pnl_25", "entry_vwap"]
        ]
        return sub
    else:
        raise ValueError(f"Unknown source: {spec.source}")


# ---------------------------------------------------------------------------
# Collect all unique slugs across all ETH sleeves → load L25 once
# ---------------------------------------------------------------------------
log("Collecting unique ETH slugs across all sleeves...")
all_slugs: set[str] = set()
sleeve_fires: dict[str, pd.DataFrame] = {}

for spec in SLEEVES:
    df = get_sleeve_fires(spec)
    sleeve_fires[spec.display_name] = df
    all_slugs.update(df["slug"].unique())

log(f"  Total unique ETH slugs: {len(all_slugs)}")

log("Loading L25 ETH at subsample_1hz=False (native 10Hz)...")
books = load_orderbook_l25_streaming(
    "eth",
    slugs=all_slugs,
    subsample_1hz=False,
)
log(f"  L25 loaded: {len(books)} (slug, outcome) pairs")


# ---------------------------------------------------------------------------
# Per-fire spread lookup and fill at $5
# ---------------------------------------------------------------------------
def compute_spread_and_fill(
    slug: str,
    direction: str,
    fire_us: int,
    won: int,
    books: dict,
    cfg: LegacyConfig,
) -> dict:
    """Returns dict with ask0, bid0, spread, fill_curr, fill_prop (fill dicts or None)."""
    outcome = direction  # "Up" or "Down" — but let's normalize
    # Polymarket outcome keys: "Up" or "Down"
    outcome_key = "Up" if direction.upper() in ("UP", "UP") else "Down"

    # Try both capitalizations
    book = None
    for oc in [outcome_key, direction, direction.capitalize(), direction.upper(), direction.lower()]:
        rec = books.get((slug, oc))
        if rec is not None:
            book = rec
            break

    if book is None:
        return {"ask0": np.nan, "bid0": np.nan, "spread": np.nan,
                "fill_curr": None, "fill_prop": None}

    ts_arr, ap_arr, asz_arr, bp_arr, bsz_arr = book
    # Build books_idx expected by fill_at_book: {(slug, outcome): (ts, ap, asz, bp, bsz)}
    books_idx = {(slug, oc): book
                 for oc in [outcome_key, direction, direction.capitalize(), direction.upper(), direction.lower()]
                 if books.get((slug, oc)) is not None}

    # Get raw book for spread
    raw = find_book_strict(books_idx, slug, oc, int(fire_us),
                           max_staleness_us=cfg.max_book_staleness_us)
    if raw is None:
        return {"ask0": np.nan, "bid0": np.nan, "spread": np.nan,
                "fill_curr": None, "fill_prop": None}

    ask0 = float(raw["ap"][0]) if len(raw["ap"]) and math.isfinite(raw["ap"][0]) else np.nan
    bid0 = float(raw["bp"][0]) if len(raw["bp"]) and math.isfinite(raw["bp"][0]) else np.nan
    spread = (ask0 - bid0) if math.isfinite(ask0) and math.isfinite(bid0) else np.nan

    # Fill at current threshold (0.020)
    fill_curr = fill_at_book(books_idx, slug, oc, int(fire_us),
                              cfg=cfg, spread_filter=SPREAD_CURR, notional_usd=NOTIONAL)
    # Fill at proposed threshold (0.025)
    fill_prop = fill_at_book(books_idx, slug, oc, int(fire_us),
                              cfg=cfg, spread_filter=SPREAD_PROP, notional_usd=NOTIONAL)
    return {
        "ask0": ask0, "bid0": bid0, "spread": spread,
        "fill_curr": fill_curr, "fill_prop": fill_prop,
    }


def pnl_from_fill(fill: dict | None, won: int, cfg: LegacyConfig) -> float | None:
    if fill is None:
        return None
    return hold_pnl(fill, won=bool(won), cfg=cfg)


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------
def metrics(pnls: list[float]) -> dict:
    if len(pnls) == 0:
        return {"n": 0, "wr": np.nan, "mean_dpt": np.nan, "total_pnl": np.nan,
                "max_dd": np.nan, "tstat": np.nan}
    arr = np.array(pnls, dtype=float)
    n = len(arr)
    won = np.sum(arr > 0)
    wr = won / n
    mean_dpt = arr.mean()
    total = arr.sum()
    # Max drawdown
    cum = np.cumsum(arr)
    running_max = np.maximum.accumulate(cum)
    dd = cum - running_max
    max_dd = float(dd.min())
    # t-stat
    if n >= 2:
        from scipy import stats as spst
        tstat, _ = spst.ttest_1samp(arr, 0)
    else:
        tstat = np.nan
    return {"n": n, "wr": wr, "mean_dpt": mean_dpt, "total_pnl": total,
            "max_dd": max_dd, "tstat": tstat}


# ---------------------------------------------------------------------------
# Main loop: process each sleeve
# ---------------------------------------------------------------------------
results: list[dict] = []

for spec in SLEEVES:
    fires_df = sleeve_fires[spec.display_name]
    log(f"Processing {spec.display_name}: {len(fires_df)} fires")

    pnls_curr: list[float] = []
    pnls_prop: list[float] = []
    n_book_miss = 0
    n_spread_nan = 0

    for _, row in fires_df.iterrows():
        slug = row["slug"]
        direction = str(row["direction"])
        fire_us = int(row["fire_us"])
        won = int(row["won"])

        # Normalize direction
        oc = "Up" if direction.upper() in ("UP",) else "Down"

        # Build books_idx for this slug/outcome
        key = (slug, oc)
        if key not in books:
            # Try other casing
            for oc_try in [direction, direction.lower(), direction.capitalize()]:
                if (slug, oc_try) in books:
                    oc = oc_try
                    key = (slug, oc)
                    break
            else:
                n_book_miss += 1
                continue

        books_idx = {key: books[key]}

        # Spread from raw book
        raw = find_book_strict(books_idx, slug, oc, fire_us,
                               max_staleness_us=cfg.max_book_staleness_us)
        if raw is None:
            n_book_miss += 1
            continue

        ap = raw["ap"]
        bp = raw["bp"]
        ask0 = float(ap[0]) if len(ap) > 0 and math.isfinite(float(ap[0])) else np.nan
        bid0 = float(bp[0]) if len(bp) > 0 and math.isfinite(float(bp[0])) else np.nan
        if not (math.isfinite(ask0) and math.isfinite(bid0)):
            n_spread_nan += 1
            continue

        spread = ask0 - bid0

        # Current filter (0.020)
        if spread <= SPREAD_CURR:
            fill = fill_at_book(books_idx, slug, oc, fire_us,
                                cfg=cfg, spread_filter=None, notional_usd=NOTIONAL)
            if fill is not None:
                p = hold_pnl(fill, won=bool(won), cfg=cfg)
                pnls_curr.append(p)

        # Proposed filter (0.025)
        if spread <= SPREAD_PROP:
            fill = fill_at_book(books_idx, slug, oc, fire_us,
                                cfg=cfg, spread_filter=None, notional_usd=NOTIONAL)
            if fill is not None:
                p = hold_pnl(fill, won=bool(won), cfg=cfg)
                pnls_prop.append(p)

    mc = metrics(pnls_curr)
    mp = metrics(pnls_prop)
    delta_n = mp["n"] - mc["n"]
    delta_pnl = (mp["total_pnl"] or 0) - (mc["total_pnl"] or 0)

    log(f"  curr_n={mc['n']} ({n_book_miss} book_miss, {n_spread_nan} spread_nan) | prop_n={mp['n']} | delta_n=+{delta_n}")

    results.append({
        "sleeve": spec.display_name,
        "tf": spec.tf,
        # Current
        "c_n": mc["n"], "c_wr": mc["wr"], "c_dpt": mc["mean_dpt"],
        "c_pnl": mc["total_pnl"], "c_dd": mc["max_dd"], "c_t": mc["tstat"],
        # Proposed
        "p_n": mp["n"], "p_wr": mp["wr"], "p_dpt": mp["mean_dpt"],
        "p_pnl": mp["total_pnl"], "p_dd": mp["max_dd"], "p_t": mp["tstat"],
        # Delta
        "delta_n": delta_n, "delta_pnl": delta_pnl,
        "n_book_miss": n_book_miss, "n_spread_nan": n_spread_nan,
    })

log("All sleeves processed. Writing report...")


# ---------------------------------------------------------------------------
# Write Markdown report
# ---------------------------------------------------------------------------
def fmt(x, fmt_str):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "N/A"
    return format(x, fmt_str)


lines: list[str] = []
lines.append("# SPREAD-LOOSEN SIM: ETH 5m + 15m Sleeves")
lines.append(f"\n**Generated:** 2026-05-27  |  **Stake:** $5  |  **Fees:** LegacyConfig (2% on profit)  |  **L25:** native 10Hz")
lines.append(f"**Current filter:** same-token bid-ask ≤ 0.020  |  **Proposed:** ≤ 0.025")
lines.append(f"\nBook miss / spread NaN fires are excluded from both scenarios.")
lines.append("\n---\n")

# ETH 5m table
lines.append("## ETH 5m Sleeves\n")
hdr = (
    "| Sleeve | curr_n | curr_WR | curr_$/tr | curr_PnL | curr_DD | curr_t |"
    " prop_n | prop_WR | prop_$/tr | prop_PnL | prop_DD | prop_t |"
    " Δn | ΔPNL | Verdict |"
)
sep = "|" + "|".join(["-"*8]*15) + "|"
lines.append(hdr)
lines.append(sep)

for r in results:
    if r["tf"] != "5m":
        continue
    # Verdict
    if r["c_n"] == 0 and r["p_n"] == 0:
        verdict = "NO_DATA"
    elif r["p_n"] - r["c_n"] == 0:
        verdict = "NO_CHANGE"
    else:
        # Loosen if: delta_pnl > 0 OR (delta_n > 0 AND p_wr >= c_wr * 0.97)
        p_wr = r["p_wr"] if r["p_wr"] is not None and math.isfinite(r["p_wr"]) else 0
        c_wr = r["c_wr"] if r["c_wr"] is not None and math.isfinite(r["c_wr"]) else 0
        if r["delta_pnl"] > 0 and p_wr >= c_wr * 0.97:
            verdict = "LOOSEN"
        elif r["delta_pnl"] > 0 and p_wr < c_wr * 0.97:
            verdict = "CAUTION"
        elif r["delta_n"] > 0 and r["delta_pnl"] <= 0:
            verdict = "KEEP"
        else:
            verdict = "KEEP"

    sname = r["sleeve"].replace("poly_sniper_v5_eth_5m_", "")
    lines.append(
        f"| {sname} "
        f"| {fmt(r['c_n'], 'd')} | {fmt(r['c_wr'], '.1%')} | {fmt(r['c_dpt'], '+.3f')} "
        f"| {fmt(r['c_pnl'], '+.2f')} | {fmt(r['c_dd'], '.2f')} | {fmt(r['c_t'], '+.2f')} "
        f"| {fmt(r['p_n'], 'd')} | {fmt(r['p_wr'], '.1%')} | {fmt(r['p_dpt'], '+.3f')} "
        f"| {fmt(r['p_pnl'], '+.2f')} | {fmt(r['p_dd'], '.2f')} | {fmt(r['p_t'], '+.2f')} "
        f"| +{r['delta_n']} | {fmt(r['delta_pnl'], '+.2f')} | **{verdict}** |"
    )

# ETH 15m table
lines.append("\n## ETH 15m Sleeves\n")
lines.append(hdr)
lines.append(sep)

for r in results:
    if r["tf"] != "15m":
        continue
    if r["c_n"] == 0 and r["p_n"] == 0:
        verdict = "NO_DATA"
    elif r["p_n"] - r["c_n"] == 0:
        verdict = "NO_CHANGE"
    else:
        p_wr = r["p_wr"] if r["p_wr"] is not None and math.isfinite(r["p_wr"]) else 0
        c_wr = r["c_wr"] if r["c_wr"] is not None and math.isfinite(r["c_wr"]) else 0
        if r["delta_pnl"] > 0 and p_wr >= c_wr * 0.97:
            verdict = "LOOSEN"
        elif r["delta_pnl"] > 0 and p_wr < c_wr * 0.97:
            verdict = "CAUTION"
        elif r["delta_n"] > 0 and r["delta_pnl"] <= 0:
            verdict = "KEEP"
        else:
            verdict = "KEEP"

    sname = r["sleeve"].replace("poly_sniper_v5_eth_15m_", "")
    lines.append(
        f"| {sname} "
        f"| {fmt(r['c_n'], 'd')} | {fmt(r['c_wr'], '.1%')} | {fmt(r['c_dpt'], '+.3f')} "
        f"| {fmt(r['c_pnl'], '+.2f')} | {fmt(r['c_dd'], '.2f')} | {fmt(r['c_t'], '+.2f')} "
        f"| {fmt(r['p_n'], 'd')} | {fmt(r['p_wr'], '.1%')} | {fmt(r['p_dpt'], '+.3f')} "
        f"| {fmt(r['p_pnl'], '+.2f')} | {fmt(r['p_dd'], '.2f')} | {fmt(r['p_t'], '+.2f')} "
        f"| +{r['delta_n']} | {fmt(r['delta_pnl'], '+.2f')} | **{verdict}** |"
    )

# Summary
lines.append("\n---\n")
lines.append("## Summary\n")
loosen_5m = [r for r in results if r["tf"] == "5m" and
             r.get("delta_n", 0) > 0 and r.get("delta_pnl", -99) > 0 and
             (r.get("p_wr", 0) or 0) >= (r.get("c_wr", 1) or 1) * 0.97]
loosen_15m = [r for r in results if r["tf"] == "15m" and
              r.get("delta_n", 0) > 0 and r.get("delta_pnl", -99) > 0 and
              (r.get("p_wr", 0) or 0) >= (r.get("c_wr", 1) or 1) * 0.97]
lines.append(f"- **ETH 5m LOOSEN:** {len(loosen_5m)}/{sum(1 for r in results if r['tf']=='5m')} sleeves")
lines.append(f"- **ETH 15m LOOSEN:** {len(loosen_15m)}/{sum(1 for r in results if r['tf']=='15m')} sleeves")

if loosen_5m:
    lines.append("\n**LOOSEN candidates (5m):**")
    for r in loosen_5m:
        sname = r["sleeve"].replace("poly_sniper_v5_eth_5m_", "")
        lines.append(f"- {sname}: +{r['delta_n']} fires, ΔPNL={fmt(r['delta_pnl'], '+.2f')}, WR {fmt(r['c_wr'],'.1%')}→{fmt(r['p_wr'],'.1%')}")
if loosen_15m:
    lines.append("\n**LOOSEN candidates (15m):**")
    for r in loosen_15m:
        sname = r["sleeve"].replace("poly_sniper_v5_eth_15m_", "")
        lines.append(f"- {sname}: +{r['delta_n']} fires, ΔPNL={fmt(r['delta_pnl'], '+.2f')}, WR {fmt(r['c_wr'],'.1%')}→{fmt(r['p_wr'],'.1%')}")

lines.append(f"\n_Simulation completed in {time.time()-t0:.0f}s_")

REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
log(f"Report written: {REPORT_PATH}")
