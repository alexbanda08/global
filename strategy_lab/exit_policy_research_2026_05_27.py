"""
Exit policy backtest — 2026-05-27
Tests HOLD / HEDGE_LATE / HEDGE_REVERSAL / SELL_TP_0.85 / SELL_SL_0.30
on top-10 sleeves (sampled 200 fires each) from fired_by_sleeve.parquet.

Fee model: LegacyConfig (2% on profit only) — matches production shadow.
Book data: canonical L25 at NATIVE 10Hz (subsample_1hz=False).
"""
from __future__ import annotations

import sys, math, random, time
from pathlib import Path
from collections import defaultdict
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path("C:/Users/alexandre bandarra/Desktop/global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "data/v4/canonical"))

from engine_v2 import (
    LegacyConfig, fill_at_book, hold_pnl, sell_pnl,
    find_book_strict, sell_at_bid_partial,
)
from load import load_resolutions, load_orderbook_l25_streaming

# ── constants ─────────────────────────────────────────────────────────────────
FIRED_BY_SLEEVE = ROOT / "strategy_lab/sniper_search_2026_05_27/_overlap_audit_v5_v6_v7/fired_by_sleeve.parquet"
SAMPLE_N = 200
RANDOM_SEED = 42
cfg = LegacyConfig()

# TP/SL thresholds
TP_THRESHOLD = 0.85     # sell when vwap >= 0.85
SL_THRESHOLD = 0.30     # sell when vwap <= 0.30
HEDGE_REVERSAL_DROP = 0.15   # sell when vwap drops > 0.15 from fill
HEDGE_LATE_FRACTION = 0.7    # consider losing if current_vwap < fill_vwap * 0.70
LATE_OFFSET_S = 60           # 60s before slot_end

POLICIES = ["HOLD", "HEDGE_LATE", "HEDGE_REVERSAL", "SELL_TP_0_85", "SELL_SL_0_30"]


# ── helpers ───────────────────────────────────────────────────────────────────

def _sell_at_ts(books_idx: dict, slug: str, outcome: str, target_us: int,
                shares: float, cfg: LegacyConfig) -> Optional[tuple[float, float, float]]:
    """Return (sell_vwap, sell_shares, sell_usd) by walking bids. None if no book."""
    book = find_book_strict(books_idx, slug, outcome, target_us,
                            max_staleness_us=cfg.max_book_staleness_us)
    if book is None:
        return None
    bp, bsz = book["bp"], book["bsz"]
    bid_p = [float(x) for x in bp]
    bid_s = [float(x) for x in bsz]
    sv, ss, su = sell_at_bid_partial(bid_p, bid_s, shares)
    if ss <= 0:
        return None
    return (sv, ss, su)


def simulate_fire_all_policies(
    books_idx: dict,
    slug: str,
    outcome: str,
    fire_us: int,
    fire_offset_s: int,
    slot_end_us: int,
    won: bool,
    window_s: int,
) -> dict:
    """
    Returns dict policy->pnl for a single fire, or None values if no fill.
    """
    # Step 1: entry fill at fire_us (LegacyConfig: 0ms latency)
    fill = fill_at_book(books_idx, slug, outcome, fire_us, cfg=cfg)
    if fill is None:
        return {p: None for p in POLICIES}

    fill_vwap = fill["vwap"]
    shares = fill["shares"]
    results = {}

    # HOLD
    results["HOLD"] = hold_pnl(fill, won=won, cfg=cfg)

    # ─── For sell policies: scan book snapshots between fire_us+1 and slot_end_us ───
    rec = books_idx.get((slug, outcome))
    if rec is None:
        # No book data at all — fall back to HOLD for all sell policies
        for p in POLICIES:
            if p != "HOLD":
                results[p] = results["HOLD"]
        return results

    ts_arr = rec[0]  # sorted array of timestamps
    # Find all snapshots in (fire_us, slot_end_us)
    lo = int(np.searchsorted(ts_arr, fire_us, side="right"))
    hi = int(np.searchsorted(ts_arr, slot_end_us, side="left"))
    snap_range = ts_arr[lo:hi+1]  # timestamps to scan

    # Pre-compute late threshold timestamp
    late_threshold_us = slot_end_us - LATE_OFFSET_S * 1_000_000

    # ─── HEDGE_LATE ───────────────────────────────────────────────────────────
    # At 60s before slot_end, check vwap. If losing badly, sell.
    hedge_late_pnl = results["HOLD"]  # default: hold
    late_ts = late_threshold_us
    late_sell = _sell_at_ts(books_idx, slug, outcome, late_ts, shares, cfg)
    if late_sell is not None:
        sv, ss, su = late_sell
        # "losing" = current bid side vwap < fill_vwap * 0.70
        if sv < fill_vwap * HEDGE_LATE_FRACTION:
            hedge_late_pnl = sell_pnl(fill, sv, ss, su, cfg=cfg)
    results["HEDGE_LATE"] = hedge_late_pnl

    # ─── HEDGE_REVERSAL ───────────────────────────────────────────────────────
    hedge_rev_pnl = results["HOLD"]  # default: hold
    for snap_ts in snap_range:
        book = find_book_strict(books_idx, slug, outcome, int(snap_ts),
                                max_staleness_us=cfg.max_book_staleness_us)
        if book is None:
            continue
        # use best bid as proxy for current value
        best_bid = float(book["bp"][0]) if len(book["bp"]) and math.isfinite(book["bp"][0]) else None
        if best_bid is None:
            continue
        if fill_vwap - best_bid > HEDGE_REVERSAL_DROP:
            sv_r, ss_r, su_r = sell_at_bid_partial(
                [float(x) for x in book["bp"]], [float(x) for x in book["bsz"]], shares
            )
            if ss_r > 0:
                hedge_rev_pnl = sell_pnl(fill, sv_r, ss_r, su_r, cfg=cfg)
            break  # trigger at first qualifying snapshot
    results["HEDGE_REVERSAL"] = hedge_rev_pnl

    # ─── SELL_TP_0_85 ─────────────────────────────────────────────────────────
    tp_pnl = results["HOLD"]
    for snap_ts in snap_range:
        book = find_book_strict(books_idx, slug, outcome, int(snap_ts),
                                max_staleness_us=cfg.max_book_staleness_us)
        if book is None:
            continue
        best_bid = float(book["bp"][0]) if len(book["bp"]) and math.isfinite(book["bp"][0]) else None
        if best_bid is None:
            continue
        if best_bid >= TP_THRESHOLD:
            sv_t, ss_t, su_t = sell_at_bid_partial(
                [float(x) for x in book["bp"]], [float(x) for x in book["bsz"]], shares
            )
            if ss_t > 0:
                tp_pnl = sell_pnl(fill, sv_t, ss_t, su_t, cfg=cfg)
            break
    results["SELL_TP_0_85"] = tp_pnl

    # ─── SELL_SL_0_30 ─────────────────────────────────────────────────────────
    sl_pnl = results["HOLD"]
    for snap_ts in snap_range:
        book = find_book_strict(books_idx, slug, outcome, int(snap_ts),
                                max_staleness_us=cfg.max_book_staleness_us)
        if book is None:
            continue
        best_bid = float(book["bp"][0]) if len(book["bp"]) and math.isfinite(book["bp"][0]) else None
        if best_bid is None:
            continue
        if best_bid <= SL_THRESHOLD:
            sv_s, ss_s, su_s = sell_at_bid_partial(
                [float(x) for x in book["bp"]], [float(x) for x in book["bsz"]], shares
            )
            if ss_s > 0:
                sl_pnl = sell_pnl(fill, sv_s, ss_s, su_s, cfg=cfg)
            break
    results["SELL_SL_0_30"] = sl_pnl

    return results


def run_sleeve(sleeve_id: str, fires: pd.DataFrame, resolutions: pd.DataFrame) -> dict:
    """Run all 5 policies for a single sleeve's sampled fires."""
    # Sample up to SAMPLE_N
    if len(fires) > SAMPLE_N:
        fires = fires.sample(SAMPLE_N, random_state=RANDOM_SEED)

    asset = fires["asset"].iloc[0].lower()
    tf = fires["tf"].iloc[0]
    window_s = 300 if tf == "5m" else 900

    # Get slugs needed
    slugs = set(fires["slug"].tolist())

    # Join with resolutions to get slot_end_us
    res_sub = resolutions[resolutions["slug"].isin(slugs)][["slug", "slot_end_us", "slot_start_us"]].drop_duplicates("slug")
    fires = fires.merge(res_sub, on="slug", how="left")
    missing_res = fires["slot_end_us"].isna().sum()
    fires = fires.dropna(subset=["slot_end_us"])
    if len(fires) == 0:
        return {"sleeve_id": sleeve_id, "n_fires": 0, "n_missing_res": missing_res}

    fires["slot_end_us"] = fires["slot_end_us"].astype(int)

    # Time range for L25 load
    min_ts = int(fires["fire_us"].min())
    max_ts = int(fires["slot_end_us"].max())

    print(f"  Loading L25 for {asset.upper()} {len(slugs)} slugs [{len(fires)} fires]...")
    t0 = time.time()
    books_idx = load_orderbook_l25_streaming(
        asset, slugs=slugs, subsample_1hz=False,
        min_ts_us=min_ts - 120_000_000,   # 2min buffer before earliest fire
        max_ts_us=max_ts + 60_000_000,
    )
    print(f"    L25 loaded in {time.time()-t0:.1f}s, {len(books_idx)} (slug,outcome) pairs")

    # Accumulate per-policy PnL lists
    policy_pnls = {p: [] for p in POLICIES}
    n_no_fill = 0

    for _, row in fires.iterrows():
        slug = row["slug"]
        direction = row["direction"]
        fire_us = int(row["fire_us"])
        slot_end_us = int(row["slot_end_us"])
        won = bool(row["won"])
        fire_offset_s = int(row["fire_offset_s"])

        outcome = direction  # "Up" or "Down" per Polymarket convention
        # Normalize: fired_by_sleeve uses "UP"/"DOWN", L25 uses "Up"/"Down"
        if outcome.upper() == "UP":
            outcome = "Up"
        elif outcome.upper() == "DOWN":
            outcome = "Down"

        r = simulate_fire_all_policies(
            books_idx, slug, outcome, fire_us,
            fire_offset_s, slot_end_us, won, window_s
        )
        if r["HOLD"] is None:
            n_no_fill += 1
            continue
        for p in POLICIES:
            if r[p] is not None:
                policy_pnls[p].append(r[p])

    n_valid = len(policy_pnls["HOLD"])
    print(f"    {n_valid} valid fills, {n_no_fill} no-fill skips")

    if n_valid == 0:
        return {"sleeve_id": sleeve_id, "n_fires": 0, "error": "all no-fill"}

    result = {"sleeve_id": sleeve_id, "asset": asset.upper(), "tf": tf, "n_fires": n_valid}
    for p in POLICIES:
        arr = np.array(policy_pnls[p])
        result[f"{p}_wr"] = float((arr > 0).mean())
        result[f"{p}_mean"] = float(arr.mean())
        result[f"{p}_total"] = float(arr.sum())

    return result


def main():
    print("Loading fired_by_sleeve...")
    df = pd.read_parquet(FIRED_BY_SLEEVE)

    # Dedup by (sleeve_id, slug, fire_us) — some sleeves have repeated rows
    df = df.drop_duplicates(subset=["sleeve_id", "slug", "fire_us"])

    top10 = df["sleeve_id"].value_counts().head(10).index.tolist()
    print(f"Top 10 sleeves: {top10}")

    print("Loading resolutions...")
    resolutions = load_resolutions()

    all_results = []
    for i, sleeve_id in enumerate(top10):
        print(f"\n[{i+1}/10] {sleeve_id}")
        fires = df[df["sleeve_id"] == sleeve_id].copy()
        t0 = time.time()
        result = run_sleeve(sleeve_id, fires, resolutions)
        result["elapsed_s"] = time.time() - t0
        all_results.append(result)
        print(f"  done in {result.get('elapsed_s', 0):.1f}s")

    results_df = pd.DataFrame(all_results)
    out_path = ROOT / "strategy_lab/reports/exit_policy_results_2026_05_27.csv"
    results_df.to_csv(out_path, index=False)
    print(f"\nResults saved to {out_path}")
    print(results_df.to_string())
    return results_df


if __name__ == "__main__":
    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)
    results = main()
