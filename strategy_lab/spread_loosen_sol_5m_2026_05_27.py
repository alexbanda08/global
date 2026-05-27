"""
SPREAD-LOOSEN PER-SLEEVE BACKTEST — SOL 5m sleeves
Compare same-token bid-ask spread filter: 0.025 vs 0.030

Methodology:
  1. Load combined SOL 5m fire universe (REF s6 + prefix + OOS parquets)
     These already contain gate-feature columns (g_rf_with, g_cci_with, etc.)
     and pnl_legacy_usd computed at spread=0.025 with subsample_1hz=True.
  2. Gate approximations: production sleeves use gates not in backtest panel
     (g_rf_strict_align, g_tr_partial_stack_with, g_depth_250_strict, etc.).
     We approximate each sleeve with the closest available backtest gate combo.
     See GATE_MAP notes below for mapping rationale.
  3. For spread comparison: re-load L25 at subsample_1hz=False (10Hz, native)
     per CLAUDE.md. Run fill_at_book at BOTH 0.025 and 0.030.
  4. Gate-filter + compute metrics per sleeve at both thresholds.
  5. Write SPREAD_LOOSEN_SIM_SOL_5M_2026_05_27.md

Key constraints (per CLAUDE.md + task):
  - $5 notional (LegacyConfig)
  - LegacyConfig (2%-on-profit fees)
  - subsample_1hz=False
  - Same-token bid-ask spread: ask0 - bid0 (fill_at_book built-in)
"""
from __future__ import annotations

import gc
import math
import sys
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

from load import load_orderbook_l25_streaming  # noqa
from engine_v2 import LegacyConfig, fill_at_book, hold_pnl  # noqa

SPREAD_OLD = 0.025
SPREAD_NEW = 0.030
NOTIONAL = 5.0
RES_DIR = ROOT / "data" / "v4" / "canonical" / "_results"
FW_DIR = RES_DIR / "_full_window_2026_05_26"
OUT_MD = ROOT / "strategy_lab" / "reports" / "SPREAD_LOOSEN_SIM_SOL_5M_2026_05_27.md"

# ---------------------------------------------------------------------------
# Sleeve definitions — production names → gate approximations
# ---------------------------------------------------------------------------
# Production gate → closest backtest gate mapping:
#   g_rf_strict_align(SOL)      → g_rf_with         (RF aligned same direction)
#   g_tr_partial_stack_with(SOL)→ g_tr_stack_with    (partial EMA stack)
#   g_tr_above_ema200(SOL)      → g_tr_above_ema200  (identical)
#   g_tr_above_pp(SOL)          → g_tr_above_pp      (identical)
#   g_depth_250_strict          → (no equivalent - depth gate not in panel; skip)
#   g_dir_up                    → direction_pick=UP
#   g_hod_us_afternoon          → g_tr_in_active_session (proxy: active session)
#   g_tr_in_active_session(SOL) → g_tr_in_active_session
#   g_cci_with                  → g_cci_with          (identical)
#   g_mfi_with                  → g_mfi_with          (identical)
#   g_tr_above_ema800(SOL)      → g_tr_above_ema800   (identical)
#   g_vwap_lt_mid               → (no direct equiv; skip)
#   F7 RSI gate                 → (not in panel; skip)
#   BTC trend gate              → (not in panel; skip)
#   Hurst reversion             → (not in panel; skip)

@dataclass
class SleeveSpec:
    name: str              # production sleeve_id suffix
    offsets: tuple         # (min_offset_s, max_offset_s)
    gates: list            # gate column names to require == 1
    direction: str = "BOTH"  # UP, DOWN, or BOTH
    note: str = ""

SLEEVES = [
    # V5 sleeves (deployed, high-volume)
    SleeveSpec(
        "poly_sniper_v5_sol_5m_depth_up_hod_session",
        offsets=(15, 120),
        gates=["g_tr_in_active_session"],  # g_depth_250_strict not in panel; g_hod → g_tr_in_active_session
        direction="UP",
        note="depth+hod+session → g_tr_in_active_session proxy; g_depth_250_strict absent",
    ),
    SleeveSpec(
        "poly_sniper_v5_sol_5m_rf_tr_pp_mid",
        offsets=(60, 210),
        gates=["g_rf_with", "g_tr_above_ema200", "g_tr_above_pp", "g_tr_stack_with"],
        direction="BOTH",
        note="g_rf_strict_align→g_rf_with, g_tr_partial_stack_with→g_tr_stack_with",
    ),
    SleeveSpec(
        "poly_sniper_v5_sol_5m_rf_tr_partial_mid",
        offsets=(60, 210),
        gates=["g_rf_with", "g_tr_stack_with"],
        direction="BOTH",
        note="g_rf_strict_align→g_rf_with, g_tr_partial_stack_with→g_tr_stack_with",
    ),
    # V6 sleeves
    SleeveSpec(
        "poly_sniper_v5_sol_5m_cci_f7_mfi_partial_vwap_v6",
        offsets=(15, 210),
        gates=["g_cci_with", "g_mfi_with", "g_tr_stack_with"],
        direction="BOTH",
        note="F7 RSI gate not in panel; vwap_lt_mid not in panel; g_tr_partial→g_tr_stack",
    ),
    SleeveSpec(
        "poly_sniper_v5_sol_5m_f7_mp_ema200_vwap_v6",
        offsets=(15, 210),
        gates=["g_tr_above_ema200", "g_tr_stack_with"],
        direction="BOTH",
        note="F7 gate+mp not in panel; vwap_lt_mid not in panel",
    ),
    SleeveSpec(
        "poly_sniper_v5_sol_5m_f7_mfi_ema200_vwap_v6",
        offsets=(15, 210),
        gates=["g_mfi_with", "g_tr_above_ema200", "g_tr_stack_with"],
        direction="BOTH",
        note="F7 gate not in panel; vwap_lt_mid not in panel",
    ),
    # V7 sleeves
    SleeveSpec(
        "poly_sniper_v5_sol_5m_btctrend_cci_hurstrev_v7",
        offsets=(15, 210),
        gates=["g_cci_with", "g_tr_stack_with"],
        direction="BOTH",
        note="BTC trend gate not in panel; Hurst rev not in panel",
    ),
    SleeveSpec(
        "poly_sniper_v5_sol_5m_btcf7_f7overb_ema800_vwap_v7",
        offsets=(15, 210),
        gates=["g_tr_above_ema800", "g_tr_stack_with"],
        direction="BOTH",
        note="BTC F7 + F7 overbought not in panel; vwap not in panel",
    ),
    # V8 sleeves
    SleeveSpec(
        "poly_sniper_v5_sol_5m_btcf7against_cci_hurstrev_mfi_v8",
        offsets=(15, 210),
        gates=["g_cci_with", "g_mfi_with", "g_tr_stack_with"],
        direction="BOTH",
        note="BTC F7 against + Hurst not in panel",
    ),
    SleeveSpec(
        "poly_sniper_v5_sol_5m_j_2asset_trending_cci_rf_ema200_v8",
        offsets=(15, 210),
        gates=["g_cci_with", "g_rf_with", "g_tr_above_ema200"],
        direction="BOTH",
        note="2-asset trending (BTC+SOL) not in panel",
    ),
]


# ---------------------------------------------------------------------------
# Load existing fire universe (SOL 5m only)
# ---------------------------------------------------------------------------

def load_fire_universe() -> pd.DataFrame:
    """Combine REF s6, prefix, OOS for SOL 5m."""
    print("[load] Loading existing fire parquets...", flush=True)

    # OOS: May 21 → May 25
    oos = pd.read_parquet(FW_DIR / "oos_fires_SOL_5m.parquet")
    oos = oos[oos["asset"] == "SOL"].copy()
    oos["tf"] = "5m"
    print(f"  OOS: {len(oos):,} rows, {oos.slug.nunique()} slugs")

    # Prefix: Apr 24 → Apr 30
    prefix = pd.read_parquet(FW_DIR / "prefix_fires.parquet")
    prefix = prefix[(prefix["asset"] == "SOL") & (prefix["tf"] == "5m")].copy()
    print(f"  Prefix: {len(prefix):,} rows, {prefix.slug.nunique()} slugs")

    # REF s6: May 1 → May 21
    s6 = pd.read_parquet(RES_DIR / "s6_joined_all.parquet")
    sol_ref = s6[s6["asset"] == "SOL"].copy()
    sol_ref["tf"] = "5m"
    # REF doesn't have slot_end_us; won is derived from outcome
    if "won" not in sol_ref.columns:
        if "outcome" in sol_ref.columns and "direction" in sol_ref.columns:
            sol_ref["won"] = (
                ((sol_ref["direction"] == "UP") & (sol_ref["outcome"] == "Up")) |
                ((sol_ref["direction"] == "DOWN") & (sol_ref["outcome"] == "Down"))
            ).astype(int)
    # Normalize slot_start_us column name
    if "slot_start_s" in sol_ref.columns and "slot_start_us" not in sol_ref.columns:
        sol_ref["slot_start_us"] = sol_ref["slot_start_s"] * 1_000_000
    if "slot_end_s" in sol_ref.columns and "slot_end_us" not in sol_ref.columns:
        sol_ref["slot_end_us"] = sol_ref["slot_end_s"] * 1_000_000
    if "fire_us" not in sol_ref.columns and "fire_s" in sol_ref.columns:
        sol_ref["fire_us"] = (sol_ref["fire_s"] * 1_000_000).astype("int64")
    print(f"  REF s6 SOL: {len(sol_ref):,} rows, {sol_ref.slug.nunique()} slugs")

    # Common columns
    common = [
        "asset", "slug", "tf", "fire_us", "fire_offset_s", "direction",
        "outcome", "slot_start_us", "won", "pnl_legacy_usd",
        "g_rf_with", "g_tr_above_ema200", "g_tr_above_pp", "g_tr_stack_with",
        "g_tr_above_ema800", "g_tr_in_active_session", "g_cci_with", "g_mfi_with",
        "g_bb_pos_with", "g_ribbon_agrees", "g_tr_above_ema50",
    ]

    pieces = []
    for df in [oos, prefix, sol_ref]:
        cols = [c for c in common if c in df.columns]
        pieces.append(df[cols].copy())

    combined = pd.concat(pieces, ignore_index=True)
    combined = combined.drop_duplicates(["slug", "fire_us", "direction"])
    combined = combined.sort_values("fire_us").reset_index(drop=True)
    print(f"  Combined: {len(combined):,} rows, {combined.slug.nunique()} slugs, "
          f"dates: {pd.to_datetime(combined.fire_us.min(), unit='us')} → "
          f"{pd.to_datetime(combined.fire_us.max(), unit='us')}", flush=True)
    return combined


# ---------------------------------------------------------------------------
# Load L25 books for all unique slugs at 10Hz
# ---------------------------------------------------------------------------

def load_books(slugs: set) -> dict:
    print(f"\n[L25] Loading {len(slugs)} slugs at native 10Hz...", flush=True)
    t0 = time.time()
    books = load_orderbook_l25_streaming("sol", slugs=slugs, subsample_1hz=False)
    print(f"  Done: {len(books)} (slug,side) pairs in {time.time()-t0:.1f}s", flush=True)
    return books


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def compute_metrics(pnl_arr: np.ndarray, won_arr: np.ndarray) -> dict:
    n = len(pnl_arr)
    if n == 0:
        return {"n": 0, "wr": float("nan"), "dpt": float("nan"),
                "total_pnl": 0.0, "max_dd": float("nan"), "tstat": float("nan")}
    wr = float(won_arr.mean())
    dpt = float(pnl_arr.mean())
    total = float(pnl_arr.sum())
    cum = np.cumsum(pnl_arr)
    peak = np.maximum.accumulate(cum)
    max_dd = float((peak - cum).max())
    if n >= 2 and pnl_arr.std() > 0:
        t, _ = scipy_stats.ttest_1samp(pnl_arr, 0)
        tstat = float(t)
    else:
        tstat = float("nan")
    return {"n": n, "wr": wr, "dpt": dpt, "total_pnl": total,
            "max_dd": max_dd, "tstat": tstat}


# ---------------------------------------------------------------------------
# Per-sleeve simulation
# ---------------------------------------------------------------------------

def simulate_sleeve(
    sleeve: SleeveSpec,
    df: pd.DataFrame,
    books: dict,
    cfg,
) -> dict:
    """Run fill_at_book at both spread thresholds for this sleeve."""
    t0 = time.time()

    # Filter to sleeve's offset range + direction + gates
    m = (
        (df["fire_offset_s"] >= sleeve.offsets[0]) &
        (df["fire_offset_s"] <= sleeve.offsets[1])
    )
    if sleeve.direction == "UP":
        m &= (df["direction"] == "UP")
    elif sleeve.direction == "DOWN":
        m &= (df["direction"] == "DOWN")

    for g in sleeve.gates:
        if g in df.columns:
            m &= (df[g] == 1)
        else:
            print(f"  WARNING: gate '{g}' not in dataframe — treating as pass-all")

    sub = df[m].copy()
    if len(sub) == 0:
        print(f"  {sleeve.name}: 0 candidates after gate filter — skip")
        return None

    # Re-run fill_at_book at both spread thresholds (10Hz books)
    rows_025 = []
    rows_030 = []
    n_no_book = 0
    n_processed = 0

    for r in sub.itertuples(index=False):
        slug = r.slug
        direction = r.direction.capitalize()
        fire_us = int(r.fire_us)
        outcome = r.outcome
        won_up = (outcome == "Up")
        won_dn = (outcome == "Down")
        won = won_up if direction == "Up" else won_dn

        f025 = fill_at_book(books, slug, direction, fire_us,
                            cfg=cfg, spread_filter=SPREAD_OLD, notional_usd=NOTIONAL)
        f030 = fill_at_book(books, slug, direction, fire_us,
                            cfg=cfg, spread_filter=SPREAD_NEW, notional_usd=NOTIONAL)

        if f025 is None and f030 is None:
            n_no_book += 1
        n_processed += 1

        if f025 is not None:
            pnl = hold_pnl(f025, won=won, cfg=cfg)
            rows_025.append({"pnl": pnl, "won": int(won), "slug": slug,
                              "fire_us": fire_us, "spread": f025.get("ask0", 0) - f025.get("bid0", 0)})

        if f030 is not None:
            pnl = hold_pnl(f030, won=won, cfg=cfg)
            rows_030.append({"pnl": pnl, "won": int(won), "slug": slug,
                              "fire_us": fire_us, "spread": f030.get("ask0", 0) - f030.get("bid0", 0)})

    elapsed = time.time() - t0
    print(f"  {sleeve.name}: {n_processed} candidates, "
          f"{len(rows_025)} placed@0.025, {len(rows_030)} placed@0.030 "
          f"({n_no_book} no-book), {elapsed:.1f}s", flush=True)

    def to_arrays(rows):
        if not rows:
            return np.array([]), np.array([])
        return (np.array([r["pnl"] for r in rows], dtype=float),
                np.array([r["won"] for r in rows], dtype=float))

    p025, w025 = to_arrays(rows_025)
    p030, w030 = to_arrays(rows_030)

    m025 = compute_metrics(p025, w025)
    m030 = compute_metrics(p030, w030)
    return {"sleeve": sleeve.name, "m025": m025, "m030": m030,
            "n_candidates": n_processed, "n_no_book": n_no_book}


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

RECOMMENDATION_THRESH_WR_DELTA = -0.02   # WR drop tolerance
RECOMMENDATION_THRESH_DPT_DELTA = -0.10  # $/tr drop tolerance

def recommend(m025: dict, m030: dict) -> str:
    if m030["n"] == 0:
        return "KEEP"
    dn = m030["n"] - m025["n"]
    dwr = (m030["wr"] - m025["wr"]) if (not math.isnan(m025["wr"]) and not math.isnan(m030["wr"])) else 0
    ddpt = (m030["dpt"] - m025["dpt"]) if (not math.isnan(m025["dpt"]) and not math.isnan(m030["dpt"])) else 0
    if dn == 0:
        return "KEEP"  # no new fires added
    if dwr < RECOMMENDATION_THRESH_WR_DELTA and ddpt < RECOMMENDATION_THRESH_DPT_DELTA:
        return "KEEP"
    if dwr >= 0 and ddpt >= 0:
        return "LOOSEN"
    return "LOOSEN_WITH_CAVEAT"


def fmt(v, fmt_str=".3f"):
    if math.isnan(v):
        return "n/a"
    return format(v, fmt_str)


def generate_report(results: list) -> str:
    lines = []
    lines.append("# SPREAD-LOOSEN SIMULATION — SOL 5m Sleeves")
    lines.append("")
    lines.append(f"**Date:** 2026-05-27  **Spread: {SPREAD_OLD} → {SPREAD_NEW}**  **Notional:** $5  **Fee model:** LegacyConfig (2%-on-profit)")
    lines.append("")
    lines.append("## Methodology")
    lines.append("")
    lines.append("- **Fire universe:** combined REF (s6_joined_all, May 1–21) + prefix_fires (Apr 24–30) + oos_fires_SOL_5m (May 21–25)")
    lines.append("- **Books:** `load_orderbook_l25_streaming('sol', subsample_1hz=False)` — native 10Hz per CLAUDE.md")
    lines.append("- **Spread metric:** same-token bid-ask `ask0 - bid0` on the BUY-side token (per `engine_v2.fill_at_book`)")
    lines.append("- **Gate approximations:** production gates mapped to closest backtest-panel equivalents (see table Notes column)")
    lines.append("  - `g_rf_strict_align` → `g_rf_with`")
    lines.append("  - `g_tr_partial_stack_with` → `g_tr_stack_with`")
    lines.append("  - `g_depth_250_strict` → not available (treated as pass-all)")
    lines.append("  - `g_hod_us_afternoon` → `g_tr_in_active_session` (proxy)")
    lines.append("  - F7/BTC-trend/Hurst gates → not available (treated as pass-all)")
    lines.append("- **Note:** gate approximations make absolute metrics unreliable vs live; **delta metrics (PROPOSED vs CURRENT) remain valid** since same fires are tested at both thresholds")
    lines.append("")

    valid = [r for r in results if r is not None]
    n_improve = 0
    n_degrade = 0
    n_neutral = 0
    deltas = []

    for r in valid:
        m025 = r["m025"]
        m030 = r["m030"]
        dn = m030["n"] - m025["n"]
        dwr = (m030["wr"] - m025["wr"]) if not (math.isnan(m025.get("wr", float("nan"))) or math.isnan(m030.get("wr", float("nan")))) else float("nan")
        ddpt = (m030["dpt"] - m025["dpt"]) if not (math.isnan(m025.get("dpt", float("nan"))) or math.isnan(m030.get("dpt", float("nan")))) else float("nan")
        dpnl = m030["total_pnl"] - m025["total_pnl"]
        rec = recommend(m025, m030)
        if dn > 0:
            if rec == "LOOSEN":
                n_improve += 1
            elif rec == "KEEP":
                n_degrade += 1
            else:
                n_neutral += 1
        else:
            n_neutral += 1
        deltas.append((r["sleeve"], dn, dwr if not math.isnan(dwr) else 0, ddpt if not math.isnan(ddpt) else 0, dpnl, rec))

    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Sleeves tested: {len(valid)} / {len(results)}")
    lines.append(f"- Sleeves that IMPROVE (new fires with positive delta metrics): {n_improve}")
    lines.append(f"- Sleeves NEUTRAL (no new fires or marginal): {n_neutral}")
    lines.append(f"- Sleeves that DEGRADE (new fires hurt metrics): {n_degrade}")
    lines.append("")
    if deltas:
        ranked_by_dpnl = sorted(deltas, key=lambda x: x[4], reverse=True)
        lines.append("**Top 3 PnL gainers from loosening:**")
        for s, dn, dwr, ddpt, dpnl, rec in ranked_by_dpnl[:3]:
            lines.append(f"  - `{s}`: Δn=+{dn}, ΔWR={dwr:+.1%}, Δ$/tr={ddpt:+.3f}, ΔPnL={dpnl:+.2f} → {rec}")
        lines.append("")
        lines.append("**Top 3 PnL losers from loosening:**")
        for s, dn, dwr, ddpt, dpnl, rec in ranked_by_dpnl[-3:]:
            lines.append(f"  - `{s}`: Δn=+{dn}, ΔWR={dwr:+.1%}, Δ$/tr={ddpt:+.3f}, ΔPnL={dpnl:+.2f} → {rec}")
    lines.append("")

    lines.append("## Per-Sleeve Comparison Table")
    lines.append("")
    lines.append("| Sleeve | n_old | WR_old | $/tr_old | PnL_old | DD_old | n_new | WR_new | $/tr_new | PnL_new | DD_new | Δn | ΔWR | Δ$/tr | ΔPnL | ΔDD | REC |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")

    for r in valid:
        m0 = r["m025"]
        m1 = r["m030"]
        dn = m1["n"] - m0["n"]
        dwr = (m1["wr"] - m0["wr"]) if not (math.isnan(m0["wr"]) or math.isnan(m1["wr"])) else float("nan")
        ddpt = (m1["dpt"] - m0["dpt"]) if not (math.isnan(m0["dpt"]) or math.isnan(m1["dpt"])) else float("nan")
        dpnl = m1["total_pnl"] - m0["total_pnl"]
        ddd = (m1["max_dd"] - m0["max_dd"]) if not (math.isnan(m0["max_dd"]) or math.isnan(m1["max_dd"])) else float("nan")
        rec = recommend(m0, m1)
        name_short = r["sleeve"].replace("poly_sniper_v5_sol_5m_", "")
        row = (
            f"| `{name_short}` "
            f"| {m0['n']} | {fmt(m0['wr'], '.1%')} | {fmt(m0['dpt'], '+.3f')} "
            f"| {fmt(m0['total_pnl'], '+.2f')} | {fmt(m0['max_dd'], '.2f')} "
            f"| {m1['n']} | {fmt(m1['wr'], '.1%')} | {fmt(m1['dpt'], '+.3f')} "
            f"| {fmt(m1['total_pnl'], '+.2f')} | {fmt(m1['max_dd'], '.2f')} "
            f"| {dn:+d} | {fmt(dwr, '+.1%')} | {fmt(ddpt, '+.3f')} "
            f"| {dpnl:+.2f} | {fmt(ddd, '+.2f')} | **{rec}** |"
        )
        lines.append(row)

    lines.append("")
    lines.append("## Gate Approximation Notes")
    lines.append("")
    lines.append("| Sleeve | Approx Gates Used | Production Gates (not in panel) |")
    lines.append("|---|---|---|")
    for sl in SLEEVES:
        name_short = sl.name.replace("poly_sniper_v5_sol_5m_", "")
        lines.append(f"| `{name_short}` | {', '.join(sl.gates) or '(none)'} | {sl.note} |")
    lines.append("")
    lines.append("**Important:** Absolute WR/$/tr numbers are NOT directly comparable to production live PnL because:")
    lines.append("1. Gate approximations let through more fires than production (especially v6/v7/v8 which have F7/BTC-trend/Hurst gates)")
    lines.append("2. The delta metrics (Δn, ΔWR, Δ$/tr, ΔPnL) between 0.025 and 0.030 are valid — same fires tested both ways")
    lines.append("3. A positive ΔPnL means the marginal fires (spread in 0.025–0.030] add value")
    lines.append("")
    lines.append("## Recommendation Summary")
    lines.append("")
    lines.append("| Sleeve | Recommendation | Rationale |")
    lines.append("|---|---|---|")
    for r in valid:
        m0 = r["m025"]
        m1 = r["m030"]
        dn = m1["n"] - m0["n"]
        rec = recommend(m0, m1)
        dwr = (m1["wr"] - m0["wr"]) if not (math.isnan(m0["wr"]) or math.isnan(m1["wr"])) else float("nan")
        ddpt = (m1["dpt"] - m0["dpt"]) if not (math.isnan(m0["dpt"]) or math.isnan(m1["dpt"])) else float("nan")
        name_short = r["sleeve"].replace("poly_sniper_v5_sol_5m_", "")
        if dn == 0:
            rationale = "No new fires added at wider filter"
        elif rec == "LOOSEN":
            rationale = f"Δn=+{dn} fires, ΔWR={fmt(dwr,'+.1%')}, Δ$/tr={fmt(ddpt,'+.3f')} — marginal fires improve/maintain quality"
        elif rec == "KEEP":
            rationale = f"Δn=+{dn} fires but ΔWR={fmt(dwr,'+.1%')}, Δ$/tr={fmt(ddpt,'+.3f')} — quality degrades"
        else:
            rationale = f"Δn=+{dn} fires, mixed signal ΔWR={fmt(dwr,'+.1%')}, Δ$/tr={fmt(ddpt,'+.3f')}"
        lines.append(f"| `{name_short}` | **{rec}** | {rationale} |")
    lines.append("")
    lines.append("---")
    lines.append(f"*Generated 2026-05-27 by spread_loosen_sol_5m_2026_05_27.py*")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    t_total = time.time()
    print("=" * 70)
    print("SPREAD-LOOSEN SOL 5m BACKTEST  2026-05-27")
    print("=" * 70)

    # 1. Load combined fire universe
    df = load_fire_universe()
    sol_df = df[df["asset"] == "SOL"].copy()
    print(f"\nFire universe: {len(sol_df):,} SOL 5m rows")

    # 2. Load L25 books for all slugs
    all_slugs = set(sol_df["slug"].unique())
    print(f"Unique slugs: {len(all_slugs)}")
    books = load_books(all_slugs)

    # 3. Simulate each sleeve
    cfg = LegacyConfig()
    results = []
    print("\n" + "=" * 70)
    print("Running per-sleeve simulation...")
    print("=" * 70)
    for sl in SLEEVES:
        print(f"\n[{sl.name}]")
        r = simulate_sleeve(sl, sol_df, books, cfg)
        results.append(r)

    # 4. Generate report
    print("\n" + "=" * 70)
    print("Generating report...")
    report = generate_report(results)
    OUT_MD.write_text(report, encoding="utf-8")
    print(f"Report written to: {OUT_MD}")

    # 5. Console summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    valid = [r for r in results if r is not None]
    for r in valid:
        m0 = r["m025"]
        m1 = r["m030"]
        dn = m1["n"] - m0["n"]
        dwr = (m1["wr"] - m0["wr"]) if not (math.isnan(m0["wr"]) or math.isnan(m1["wr"])) else float("nan")
        ddpt = (m1["dpt"] - m0["dpt"]) if not (math.isnan(m0["dpt"]) or math.isnan(m1["dpt"])) else float("nan")
        dpnl = m1["total_pnl"] - m0["total_pnl"]
        rec = recommend(m0, m1)
        name_short = r["sleeve"].replace("poly_sniper_v5_sol_5m_", "")
        wr_str = f"{m0['wr']:.1%}→{m1['wr']:.1%}" if not (math.isnan(m0["wr"]) or math.isnan(m1["wr"])) else "n/a"
        print(f"  {name_short[:40]:40s} n={m0['n']}→{m1['n']} (Δ{dn:+d}) "
              f"WR={wr_str} dpt={fmt(m0['dpt'],'+.3f')}→{fmt(m1['dpt'],'+.3f')} "
              f"ΔPnL={dpnl:+.2f}  [{rec}]")

    print(f"\nTotal elapsed: {time.time()-t_total:.1f}s")


if __name__ == "__main__":
    main()
