"""
Fast full-universe backtest.

Single-pass parquet streaming: read every L25 row group ONCE, dispatching events
to all in-flight slugs simultaneously. Same for trades. ~10x faster than the
per-slug scanner.

Runs all 4 strategies (ACC-M-sz20, PAT+ACC-M HYBRID, MAS, ACC-PC) on every
BTC slug in the canonical window. Output: per-slug CSV.

NO 1HZ SUBSAMPLING. Reads raw parquets directly via pq.ParquetFile.read_row_group().
Does NOT use canonical/load.py:load_orderbook_l25_streaming (which has
subsample_1hz=True default). Verified: dt p50 = 33-74ms across sample slugs,
96-98% sub-second intervals. Full event-level resolution.

Usage:
    py -3 -X utf8 strategy_lab/backtests/fast_full_backtest.py --asset btc --tf 5m
"""
from __future__ import annotations
import argparse
import json
import sys
import time
import gc
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

from fees import (
    poly_taker_fee_per_share,
    poly_maker_rebate_per_share,
    DEFAULT_CRYPTO_FEE_BPS,
    bps_to_rate,
)
from load import load_resolutions

FEE_RATE = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS)
OUT_DIR = ROOT / "strategy_lab" / "backtests"
OUT_DIR.mkdir(exist_ok=True)


L25_SOURCES = {
    # FULL window: Apr 22 → May 19. Use the DENSER refreshes:
    #   _06 (base, Apr 22 → May 6, 28M rows)
    #   _16 (delta, May 6 → May 14, 19.5M rows — denser than _12's 12.5M)
    #   _19 (delta, May 16 → May 19, 7.5M rows)
    # Gap: May 14 22:01 → May 16 00:00 (~26h). We lose ~310 BTC 5m slugs (~1 day).
    # Prior attempt with _12 instead of _16 had PAT firing on only 5-10% of slugs
    # in May 7-14 → _12 is a sparser delta. Use _16 + _19.
    "btc": [
        ROOT / "data/v4/refresh_2026_05_06/cache/btc_orderbook_L25.parquet",        # Apr 22 → May 6
        ROOT / "data/v4/refresh_2026_05_16/cache/btc_orderbook_L25_delta.parquet",  # May 6 → May 14
        ROOT / "data/v4/refresh_2026_05_19/cache/btc_orderbook_L25_delta.parquet",  # May 16 → May 19
    ],
    "eth": [
        ROOT / "data/v4/refresh_2026_05_06/cache/eth_orderbook_L25.parquet",
        ROOT / "data/v4/refresh_2026_05_16/cache/eth_orderbook_L25_delta.parquet",
        ROOT / "data/v4/refresh_2026_05_19/cache/eth_orderbook_L25_delta.parquet",
    ],
    "sol": [
        ROOT / "data/v4/refresh_2026_05_06/cache/sol_orderbook_L25.parquet",
        ROOT / "data/v4/refresh_2026_05_16/cache/sol_orderbook_L25_delta.parquet",
        ROOT / "data/v4/refresh_2026_05_19/cache/sol_orderbook_L25_delta.parquet",
    ],
}

TRADES = {
    "btc": ROOT / "data/v4/canonical/trades_polymarket/btc.parquet",
    "eth": ROOT / "data/v4/canonical/trades_polymarket/eth.parquet",
    "sol": ROOT / "data/v4/canonical/trades_polymarket/sol.parquet",
}


# ============================================================================
# Strategy state and config (simplified — only the strategies we care about)
# ============================================================================

@dataclass
class StratCfg:
    name: str
    post_size: float = 20.0
    max_imbalance: float = 10.0
    absolute_max_inv: float = 100.0
    cancel_threshold: float = 0.03
    max_order_age_s: float = 20.0
    merge_threshold_pairs: float = 5.0
    stop_posting_offset_s: float = 270.0  # default 5m
    min_bid_price: float = 0.05
    max_bid_price: float = 0.95
    max_sum_bids: float = 1.00
    max_spread_per_leg: float = 0.05
    # PAT
    enable_pat: bool = False
    pat_take_size: float = 20.0
    pat_max_pair_cost: float = 1.00
    pat_min_s_between_fires: float = 5.0
    pat_max_fires_per_slug: int = 10
    pat_min_book_depth_each_side: float = 5.0
    pat_min_time_after_open_s: float = 5.0
    # MAS
    enable_mas: bool = False
    mas_pre_mint_pairs: float = 30.0
    mas_min_sum_asks: float = 1.005
    # ACC-PC
    enable_pc: bool = False
    pc_max_pair_cost: float = 0.97
    pc_min_time_before_taker_s: float = 30
    pc_cvd_threshold: float = 0
    pc_max_taker_per_slug: int = 5


@dataclass
class SideState:
    side: str
    inv: float = 0.0
    cost_paid: float = 0.0
    cash_received: float = 0.0
    rebate: float = 0.0
    taker_fees: float = 0.0
    open_bid: float | None = None
    open_bid_remaining: float = 0.0
    open_bid_posted_us: int = 0
    open_bid_queue_ahead: float = 0.0
    open_ask: float | None = None
    open_ask_remaining: float = 0.0
    open_ask_posted_us: int = 0
    open_ask_queue_ahead: float = 0.0
    best_bid: float = 0.0
    best_ask: float = 1.0
    bid_size_at_best: float = 0.0
    ask_size_at_best: float = 0.0
    n_maker_bid_fills: int = 0
    n_maker_ask_fills: int = 0
    n_pat_fires: int = 0
    last_pat_us: int = 0
    n_pc_takers: int = 0
    last_pc_us: int = 0
    cvd_window: list = field(default_factory=list)


@dataclass
class SlugState:
    slug: str
    slot_start_us: int
    slot_end_us: int
    outcome_truth: str
    up: SideState
    dn: SideState
    cash_recovered: float = 0.0
    n_merges: int = 0
    pairs_merged: float = 0.0
    mint_cost: float = 0.0
    leftover_redeemed: float = 0.0
    finalized: bool = False


def fresh_slug_state(slug: str, slot_start_us: int, slot_end_us: int,
                      outcome_truth: str, cfg: StratCfg) -> SlugState:
    s = SlugState(slug=slug, slot_start_us=slot_start_us, slot_end_us=slot_end_us,
                   outcome_truth=outcome_truth,
                   up=SideState("Up"), dn=SideState("Down"))
    if cfg.enable_mas:
        s.up.inv = cfg.mas_pre_mint_pairs
        s.dn.inv = cfg.mas_pre_mint_pairs
        s.mint_cost = cfg.mas_pre_mint_pairs
    return s


def evict_cvd(dq: list, now_us: int, window_s: float = 30.0):
    cutoff = now_us - int(window_s * 1_000_000)
    while dq and dq[0][0] < cutoff:
        dq.pop(0)


# ============================================================================
# Per-event handlers
# ============================================================================

def handle_l25(state: SlugState, oc: str, ts_us: int,
                bp: float, bs: float, ap: float, asz: float, cfg: StratCfg):
    side_ss = state.up if oc == "Up" else state.dn
    other_ss = state.dn if oc == "Up" else state.up
    if not (bp > 0 and ap > bp and ap < 1):
        return
    side_ss.best_bid = bp
    side_ss.best_ask = ap
    side_ss.bid_size_at_best = bs if bs > 0 else 1.0
    side_ss.ask_size_at_best = asz if asz > 0 else 1.0

    if cfg.enable_mas:
        # MAS: cancel + post ASK
        if side_ss.open_ask is not None:
            if abs(side_ss.open_ask - ap) >= cfg.cancel_threshold or \
               (ts_us - side_ss.open_ask_posted_us) / 1e6 >= 30:
                side_ss.open_ask = None
                side_ss.open_ask_remaining = 0
        if side_ss.open_ask is None and side_ss.inv >= cfg.post_size:
            elapsed_s = (ts_us - state.slot_start_us) / 1e6
            if elapsed_s <= cfg.stop_posting_offset_s:
                sum_asks = side_ss.best_ask + other_ss.best_ask
                if sum_asks > cfg.mas_min_sum_asks:
                    side_ss.open_ask = ap
                    side_ss.open_ask_remaining = cfg.post_size
                    side_ss.open_ask_posted_us = ts_us
                    side_ss.open_ask_queue_ahead = max(side_ss.ask_size_at_best, 0)
    else:
        # ACC-M base: cancel + post BID
        if side_ss.open_bid is not None:
            if abs(side_ss.open_bid - bp) >= cfg.cancel_threshold or \
               (ts_us - side_ss.open_bid_posted_us) / 1e6 >= cfg.max_order_age_s:
                side_ss.open_bid = None
                side_ss.open_bid_remaining = 0
        if side_ss.open_bid is None:
            elapsed_s = (ts_us - state.slot_start_us) / 1e6
            if elapsed_s <= cfg.stop_posting_offset_s and \
               (side_ss.best_ask - side_ss.best_bid) <= cfg.max_spread_per_leg:
                sum_bids = side_ss.best_bid + other_ss.best_bid
                if sum_bids < cfg.max_sum_bids and \
                   side_ss.inv <= other_ss.inv + cfg.max_imbalance and \
                   side_ss.inv < cfg.absolute_max_inv and \
                   cfg.min_bid_price <= bp <= cfg.max_bid_price:
                    side_ss.open_bid = bp
                    side_ss.open_bid_remaining = cfg.post_size
                    side_ss.open_bid_posted_us = ts_us
                    side_ss.open_bid_queue_ahead = max(side_ss.bid_size_at_best, 0)

    # PAT taker (overlay)
    if cfg.enable_pat:
        check_and_fire_pat(state, ts_us, cfg)

    # ACC-PC taker
    if cfg.enable_pc:
        check_and_fire_pc(state, ts_us, cfg)


def check_and_fire_pat(state: SlugState, ts_us: int, cfg: StratCfg):
    up, dn = state.up, state.dn
    if not (0 < up.best_ask < 1 and 0 < dn.best_ask < 1):
        return
    last_fire = max(up.last_pat_us, dn.last_pat_us)
    if (ts_us - last_fire) < cfg.pat_min_s_between_fires * 1e6:
        return
    if up.n_pat_fires >= cfg.pat_max_fires_per_slug:
        return
    elapsed_s = (ts_us - state.slot_start_us) / 1e6
    if elapsed_s < cfg.pat_min_time_after_open_s:
        return
    if up.ask_size_at_best < cfg.pat_min_book_depth_each_side or \
       dn.ask_size_at_best < cfg.pat_min_book_depth_each_side:
        return
    fee_up = poly_taker_fee_per_share(up.best_ask, fee_rate=FEE_RATE)
    fee_dn = poly_taker_fee_per_share(dn.best_ask, fee_rate=FEE_RATE)
    pair_cost = up.best_ask + dn.best_ask + fee_up + fee_dn
    if pair_cost >= cfg.pat_max_pair_cost or pair_cost <= 0:
        return
    if up.inv >= cfg.absolute_max_inv or dn.inv >= cfg.absolute_max_inv:
        return

    # Fire
    take_size = min(cfg.pat_take_size, up.ask_size_at_best, dn.ask_size_at_best)
    if take_size < cfg.pat_min_book_depth_each_side:
        return
    up.inv += take_size
    up.cost_paid += take_size * up.best_ask
    up.taker_fees += take_size * fee_up
    dn.inv += take_size
    dn.cost_paid += take_size * dn.best_ask
    dn.taker_fees += take_size * fee_dn
    up.n_pat_fires += 1
    dn.n_pat_fires += 1
    up.last_pat_us = ts_us
    dn.last_pat_us = ts_us
    up.ask_size_at_best -= take_size
    dn.ask_size_at_best -= take_size
    # Immediate merge
    pairs = take_size
    up.inv -= pairs
    dn.inv -= pairs
    state.cash_recovered += pairs * 1.0
    state.n_merges += 1
    state.pairs_merged += pairs


def check_and_fire_pc(state: SlugState, ts_us: int, cfg: StratCfg):
    up, dn = state.up, state.dn
    if up.inv < dn.inv:
        lag, lead = up, dn
    else:
        lag, lead = dn, up
    if lead.inv < 1.0 or (lead.inv - lag.inv) < 1.0:
        return
    elapsed_s = (ts_us - state.slot_start_us) / 1e6
    if elapsed_s < cfg.pc_min_time_before_taker_s:
        return
    if lag.n_pc_takers >= cfg.pc_max_taker_per_slug:
        return
    if (ts_us - lag.last_pc_us) < 5 * 1e6:
        return
    if not (0 < lag.best_ask < 1):
        return
    avg_lead = lead.cost_paid / lead.inv
    fee = poly_taker_fee_per_share(lag.best_ask, fee_rate=FEE_RATE)
    pair_cost = avg_lead + lag.best_ask + fee
    if pair_cost >= cfg.pc_max_pair_cost or pair_cost <= 0:
        return
    if lag.open_bid is not None and (lag.best_ask - lag.open_bid) <= 0.02:
        return
    cvd = sum(d for _, d in lag.cvd_window)
    if cvd <= cfg.pc_cvd_threshold:
        return

    # Fire
    take_size = min(cfg.post_size, lead.inv - lag.inv)
    lag.inv += take_size
    lag.cost_paid += take_size * lag.best_ask
    lag.taker_fees += take_size * fee
    lag.n_pc_takers += 1
    lag.last_pc_us = ts_us


def handle_trade(state: SlugState, oc: str, ts_us: int, price: float,
                  size: float, side: str, cfg: StratCfg):
    side_ss = state.up if oc == "Up" else state.dn
    other_ss = state.dn if oc == "Up" else state.up
    side_upper = side.upper() if isinstance(side, str) else ""
    # CVD tracking
    if cfg.enable_pc:
        delta = size if side_upper == "BUY" else -size
        side_ss.cvd_window.append((ts_us, delta))
        evict_cvd(side_ss.cvd_window, ts_us, 30.0)

    # MAS: taker BUYs hit our ASKs
    if cfg.enable_mas and side_upper == "BUY":
        if side_ss.open_ask is not None and price >= side_ss.open_ask - 1e-9 and side_ss.open_ask_remaining > 0:
            trade_rem = size
            if side_ss.open_ask_queue_ahead > 0:
                used = min(side_ss.open_ask_queue_ahead, trade_rem)
                side_ss.open_ask_queue_ahead -= used
                trade_rem -= used
            if trade_rem > 0.001:
                fill = min(side_ss.open_ask_remaining, trade_rem)
                fp = side_ss.open_ask
                side_ss.inv -= fill
                side_ss.cash_received += fill * fp
                side_ss.rebate += fill * poly_maker_rebate_per_share(fp, fee_rate=FEE_RATE)
                side_ss.open_ask_remaining -= fill
                side_ss.n_maker_ask_fills += 1
                if side_ss.open_ask_remaining < 0.001:
                    side_ss.open_ask = None
                    side_ss.open_ask_queue_ahead = 0
    # ACC-M: taker SELLs hit our BIDs
    elif not cfg.enable_mas and side_upper == "SELL":
        if side_ss.open_bid is not None and price <= side_ss.open_bid + 1e-9 and side_ss.open_bid_remaining > 0:
            trade_rem = size
            if side_ss.open_bid_queue_ahead > 0:
                used = min(side_ss.open_bid_queue_ahead, trade_rem)
                side_ss.open_bid_queue_ahead -= used
                trade_rem -= used
            if trade_rem > 0.001:
                fill = min(side_ss.open_bid_remaining, trade_rem)
                fp = side_ss.open_bid
                side_ss.inv += fill
                side_ss.cost_paid += fill * fp
                side_ss.rebate += fill * poly_maker_rebate_per_share(fp, fee_rate=FEE_RATE)
                side_ss.open_bid_remaining -= fill
                side_ss.n_maker_bid_fills += 1
                if side_ss.open_bid_remaining < 0.001:
                    side_ss.open_bid = None
                    side_ss.open_bid_queue_ahead = 0

    # Merge trigger (after fills update inventory)
    if not cfg.enable_mas:
        pairs = min(state.up.inv, state.dn.inv)
        if pairs >= cfg.merge_threshold_pairs:
            state.up.inv -= pairs
            state.dn.inv -= pairs
            state.cash_recovered += pairs * 1.0
            state.n_merges += 1
            state.pairs_merged += pairs


def finalize_slug(state: SlugState, cfg: StratCfg) -> dict:
    if not cfg.enable_mas:
        pairs = min(state.up.inv, state.dn.inv)
        if pairs > 0:
            state.up.inv -= pairs
            state.dn.inv -= pairs
            state.cash_recovered += pairs * 1.0
            state.n_merges += 1
            state.pairs_merged += pairs
    if state.outcome_truth == "Up":
        if state.up.inv > 0:
            state.leftover_redeemed = state.up.inv * 1.0
            state.cash_recovered += state.leftover_redeemed
    elif state.outcome_truth == "Down":
        if state.dn.inv > 0:
            state.leftover_redeemed = state.dn.inv * 1.0
            state.cash_recovered += state.leftover_redeemed

    cost = state.up.cost_paid + state.dn.cost_paid + state.mint_cost
    cash_in = state.up.cash_received + state.dn.cash_received + state.cash_recovered
    rebates = state.up.rebate + state.dn.rebate
    fees = state.up.taker_fees + state.dn.taker_fees
    pnl = cash_in + rebates - cost - fees
    state.finalized = True
    return {
        "slug": state.slug,
        "outcome_truth": state.outcome_truth,
        "pnl": pnl,
        "cost": cost,
        "cash_in": cash_in,
        "rebates": rebates,
        "fees": fees,
        "leftover_redeemed": state.leftover_redeemed,
        "n_merges": state.n_merges,
        "pairs_merged": state.pairs_merged,
        "n_maker_bid_up": state.up.n_maker_bid_fills,
        "n_maker_bid_dn": state.dn.n_maker_bid_fills,
        "n_maker_ask_up": state.up.n_maker_ask_fills,
        "n_maker_ask_dn": state.dn.n_maker_ask_fills,
        "n_pat_up": state.up.n_pat_fires,
        "n_pat_dn": state.dn.n_pat_fires,
    }


# ============================================================================
# Single-pass orchestrator
# ============================================================================

def run_strategy_on_universe(asset: str, slug_to_meta: dict,
                              cfg: StratCfg) -> list[dict]:
    """Run ONE strategy across all slugs by streaming parquets ONCE."""
    print(f"\n=== Running {cfg.name} on {len(slug_to_meta)} slugs ({asset}) ===", flush=True)
    t0 = time.time()

    # Initialize all slug states
    slug_states: dict[str, SlugState] = {}
    for slug, meta in slug_to_meta.items():
        slot_start_us = int(meta["slot_start_s"]) * 1_000_000
        tf_s = meta["tf_s"]
        slot_end_us = slot_start_us + tf_s * 1_000_000
        slug_states[slug] = fresh_slug_state(slug, slot_start_us, slot_end_us,
                                              meta["outcome"], cfg)

    # Phase 1: Stream L25 events using bulk filter (much faster)
    t_l25_start = time.time()
    n_l25_events = 0
    slug_set = pa.array(sorted(slug_states.keys()))
    for src_idx, src in enumerate(L25_SOURCES.get(asset, [])):
        if not src.exists():
            continue
        try:
            pf = pq.ParquetFile(str(src))
        except Exception:
            continue
        print(f"    Loading {src.name} ({pf.metadata.num_row_groups} row groups)...", flush=True)
        n_rg = pf.metadata.num_row_groups
        for rg_idx in range(n_rg):
            try:
                rg = pf.read_row_group(rg_idx, columns=[
                    "timestamp_us", "slug", "outcome",
                    "bid_price_0", "bid_size_0", "ask_price_0", "ask_size_0",
                ])
            except Exception:
                continue
            # Filter by slug at table level (vectorized)
            mask = pc.is_in(rg.column("slug"), value_set=slug_set)
            if pc.sum(mask).as_py() == 0:
                continue
            rg = rg.filter(mask)
            # Convert to pandas in bulk (fastest path)
            df = rg.to_pandas()
            for slug, grp_df in df.groupby("slug", observed=True, sort=False):
                state = slug_states.get(slug)
                if state is None or state.finalized:
                    continue
                # Process events in-order
                ts_arr = grp_df["timestamp_us"].values.astype(np.int64)
                oc_arr = grp_df["outcome"].values
                bp_arr = np.nan_to_num(grp_df["bid_price_0"].values.astype(np.float64), nan=0.0)
                bs_arr = np.nan_to_num(grp_df["bid_size_0"].values.astype(np.float64), nan=0.0)
                ap_arr = np.nan_to_num(grp_df["ask_price_0"].values.astype(np.float64), nan=0.0)
                asz_arr = np.nan_to_num(grp_df["ask_size_0"].values.astype(np.float64), nan=0.0)
                for i in range(len(ts_arr)):
                    ts = int(ts_arr[i])
                    if ts > state.slot_end_us:
                        break  # df sorted by ts? if not, fall through (skip is fine)
                    handle_l25(state, oc_arr[i], ts, float(bp_arr[i]), float(bs_arr[i]),
                               float(ap_arr[i]), float(asz_arr[i]), cfg)
                    n_l25_events += 1
            if rg_idx % 20 == 19:
                print(f"      rg {rg_idx+1}/{n_rg}  events={n_l25_events:,}  elapsed={time.time()-t_l25_start:.0f}s", flush=True)
        del pf
        gc.collect()
    print(f"  L25 phase: {n_l25_events:,} events in {time.time()-t_l25_start:.0f}s", flush=True)

    # Phase 2: Stream trades (bulk filter)
    t_tr_start = time.time()
    n_trade_events = 0
    trades_src = TRADES.get(asset)
    if trades_src and trades_src.exists():
        pf = pq.ParquetFile(str(trades_src))
        print(f"    Loading {trades_src.name} ({pf.metadata.num_row_groups} row groups)...", flush=True)
        n_rg = pf.metadata.num_row_groups
        for rg_idx in range(n_rg):
            try:
                rg = pf.read_row_group(rg_idx, columns=[
                    "timestamp_us", "slug", "outcome", "price", "size", "side"
                ])
            except Exception:
                continue
            mask = pc.is_in(rg.column("slug"), value_set=slug_set)
            if pc.sum(mask).as_py() == 0:
                continue
            rg = rg.filter(mask)
            df = rg.to_pandas()
            for slug, grp_df in df.groupby("slug", observed=True, sort=False):
                state = slug_states.get(slug)
                if state is None or state.finalized:
                    continue
                ts_arr = grp_df["timestamp_us"].values.astype(np.int64)
                oc_arr = grp_df["outcome"].values
                px_arr = grp_df["price"].values.astype(np.float64)
                sz_arr = grp_df["size"].values.astype(np.float64)
                side_arr = grp_df["side"].values
                for i in range(len(ts_arr)):
                    ts = int(ts_arr[i])
                    if ts > state.slot_end_us:
                        continue
                    handle_trade(state, oc_arr[i], ts, float(px_arr[i]),
                                  float(sz_arr[i]), side_arr[i], cfg)
                    n_trade_events += 1
            if rg_idx % 10 == 9:
                print(f"      rg {rg_idx+1}/{n_rg}  events={n_trade_events:,}  elapsed={time.time()-t_tr_start:.0f}s", flush=True)
        del pf
        gc.collect()
    print(f"  Trade phase: {n_trade_events:,} events in {time.time()-t_tr_start:.0f}s", flush=True)

    # Phase 3: Finalize
    results = []
    for slug, state in slug_states.items():
        if state.up.cost_paid + state.dn.cost_paid + state.mint_cost == 0:
            # No activity — skip (slug had no fills)
            continue
        r = finalize_slug(state, cfg)
        r["strategy"] = cfg.name
        results.append(r)
    print(f"  Total wall-clock: {time.time()-t0:.0f}s; {len(results)} slugs had activity", flush=True)
    return results


def build_slug_universe(asset: str, tfs: list[str]) -> dict:
    """Build {slug: {outcome, slot_start_s, tf_s}} from canonical resolutions."""
    res = load_resolutions(assets=[asset.upper()], timeframes=tfs)
    universe = {}
    for _, row in res.iterrows():
        slug = row["slug"]
        tf = row["timeframe"]
        tf_s = 300 if tf == "5m" else 900
        universe[slug] = {
            "outcome": row["outcome"],
            "slot_start_s": int(row["slot_start_us"] // 1_000_000),
            "tf_s": tf_s,
        }
    return universe


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default="btc", choices=["btc", "eth", "sol"])
    ap.add_argument("--tfs", default="5m,15m")
    ap.add_argument("--max-slugs", type=int, default=0,
                     help="0 = all slugs in universe; otherwise cap")
    ap.add_argument("--strategies", default="ACC-M-sz20,PAT+ACC-M,MAS,ACC-PC")
    ap.add_argument("--out-suffix", default="full")
    args = ap.parse_args()

    tfs = args.tfs.split(",")
    print(f"Building slug universe for {args.asset.upper()} {tfs}...", flush=True)
    universe = build_slug_universe(args.asset, tfs)
    print(f"  found {len(universe)} slugs in universe", flush=True)
    if args.max_slugs and args.max_slugs < len(universe):
        # Take evenly-spaced sample
        slugs = sorted(universe.keys(), key=lambda s: universe[s]["slot_start_s"])
        idx = np.linspace(0, len(slugs)-1, args.max_slugs).astype(int)
        slugs = [slugs[i] for i in idx]
        universe = {s: universe[s] for s in slugs}
        print(f"  capped to {len(universe)} slugs", flush=True)

    # Build strategy configs
    strat_map = {
        "ACC-M-sz5":   StratCfg(name="ACC-M-sz5",  post_size=5),
        "ACC-M-sz20":  StratCfg(name="ACC-M-sz20", post_size=20),
        "ACC-M-sz50":  StratCfg(name="ACC-M-sz50", post_size=50),
        "ACC-M-sz100": StratCfg(name="ACC-M-sz100",post_size=100),
        "PAT+ACC-M":   StratCfg(name="PAT+ACC-M",  post_size=20, enable_pat=True,
                                  pat_take_size=20, pat_max_pair_cost=1.00),
        # Timing variants — sweep pat_min_time_after_open_s (default 5s in baseline)
        "PAT+ACC-M-t0":  StratCfg(name="PAT+ACC-M-t0",  post_size=20, enable_pat=True,
                                    pat_take_size=20, pat_max_pair_cost=1.00,
                                    pat_min_time_after_open_s=0.0),
        "PAT+ACC-M-t2":  StratCfg(name="PAT+ACC-M-t2",  post_size=20, enable_pat=True,
                                    pat_take_size=20, pat_max_pair_cost=1.00,
                                    pat_min_time_after_open_s=2.0),
        "PAT+ACC-M-t10": StratCfg(name="PAT+ACC-M-t10", post_size=20, enable_pat=True,
                                    pat_take_size=20, pat_max_pair_cost=1.00,
                                    pat_min_time_after_open_s=10.0),
        "PAT+ACC-M-t15": StratCfg(name="PAT+ACC-M-t15", post_size=20, enable_pat=True,
                                    pat_take_size=20, pat_max_pair_cost=1.00,
                                    pat_min_time_after_open_s=15.0),
        "PAT+ACC-M-t30": StratCfg(name="PAT+ACC-M-t30", post_size=20, enable_pat=True,
                                    pat_take_size=20, pat_max_pair_cost=1.00,
                                    pat_min_time_after_open_s=30.0),
        "PAT+ACC-M-t60": StratCfg(name="PAT+ACC-M-t60", post_size=20, enable_pat=True,
                                    pat_take_size=20, pat_max_pair_cost=1.00,
                                    pat_min_time_after_open_s=60.0),
        "PAT+ACC-M-t90": StratCfg(name="PAT+ACC-M-t90", post_size=20, enable_pat=True,
                                    pat_take_size=20, pat_max_pair_cost=1.00,
                                    pat_min_time_after_open_s=90.0),
        "PAT+ACC-M-t120": StratCfg(name="PAT+ACC-M-t120", post_size=20, enable_pat=True,
                                    pat_take_size=20, pat_max_pair_cost=1.00,
                                    pat_min_time_after_open_s=120.0),
        "PAT+ACC-M-t180": StratCfg(name="PAT+ACC-M-t180", post_size=20, enable_pat=True,
                                    pat_take_size=20, pat_max_pair_cost=1.00,
                                    pat_min_time_after_open_s=180.0),
        "PAT+ACC-M-t210": StratCfg(name="PAT+ACC-M-t210", post_size=20, enable_pat=True,
                                    pat_take_size=20, pat_max_pair_cost=1.00,
                                    pat_min_time_after_open_s=210.0),
        # Co-sweep: tighter pair_cost cap at t=210 baseline
        "PAT+ACC-M-t210-pc097": StratCfg(name="PAT+ACC-M-t210-pc097", post_size=20, enable_pat=True,
                                    pat_take_size=20, pat_max_pair_cost=0.97,
                                    pat_min_time_after_open_s=210.0),
        "PAT+ACC-M-t210-pc098": StratCfg(name="PAT+ACC-M-t210-pc098", post_size=20, enable_pat=True,
                                    pat_take_size=20, pat_max_pair_cost=0.98,
                                    pat_min_time_after_open_s=210.0),
        "PAT+ACC-M-t210-pc099": StratCfg(name="PAT+ACC-M-t210-pc099", post_size=20, enable_pat=True,
                                    pat_take_size=20, pat_max_pair_cost=0.99,
                                    pat_min_time_after_open_s=210.0),
        # Co-sweep: relax max_fires_per_slug + faster rate at t=210
        "PAT+ACC-M-t210-f30": StratCfg(name="PAT+ACC-M-t210-f30", post_size=20, enable_pat=True,
                                    pat_take_size=20, pat_max_pair_cost=1.00,
                                    pat_min_time_after_open_s=210.0,
                                    pat_max_fires_per_slug=30, pat_min_s_between_fires=2.0),
        # Co-sweep: bigger take size at t=210
        "PAT+ACC-M-t210-sz50": StratCfg(name="PAT+ACC-M-t210-sz50", post_size=20, enable_pat=True,
                                    pat_take_size=50, pat_max_pair_cost=1.00,
                                    pat_min_time_after_open_s=210.0),
        # COMBO: tighter cap + more fires + bigger size at t=210
        "PAT+ACC-M-t210-COMBO": StratCfg(name="PAT+ACC-M-t210-COMBO", post_size=20, enable_pat=True,
                                    pat_take_size=50, pat_max_pair_cost=0.98,
                                    pat_min_time_after_open_s=210.0,
                                    pat_max_fires_per_slug=30, pat_min_s_between_fires=2.0),
        # AGGRESSIVE: max everything
        "PAT+ACC-M-t210-AGG": StratCfg(name="PAT+ACC-M-t210-AGG", post_size=20, enable_pat=True,
                                    pat_take_size=100, pat_max_pair_cost=0.97,
                                    pat_min_time_after_open_s=210.0,
                                    pat_max_fires_per_slug=50, pat_min_s_between_fires=1.0),
        # COMBO at t=5 baseline (for ETH/SOL where timing peak is at baseline)
        "PAT+ACC-M-t5-COMBO": StratCfg(name="PAT+ACC-M-t5-COMBO", post_size=20, enable_pat=True,
                                    pat_take_size=50, pat_max_pair_cost=0.98,
                                    pat_min_time_after_open_s=5.0,
                                    pat_max_fires_per_slug=30, pat_min_s_between_fires=2.0),
        "PAT+ACC-M-t600-COMBO": StratCfg(name="PAT+ACC-M-t600-COMBO", post_size=20, enable_pat=True,
                                    pat_take_size=50, pat_max_pair_cost=0.98,
                                    pat_min_time_after_open_s=600.0,
                                    stop_posting_offset_s=870.0,
                                    pat_max_fires_per_slug=30, pat_min_s_between_fires=2.0),
        # SMALLER take but more fires (capital-efficient)
        "PAT+ACC-M-t210-sz10-f30": StratCfg(name="PAT+ACC-M-t210-sz10-f30", post_size=20, enable_pat=True,
                                    pat_take_size=10, pat_max_pair_cost=1.00,
                                    pat_min_time_after_open_s=210.0,
                                    pat_max_fires_per_slug=30, pat_min_s_between_fires=2.0),
        "PAT+ACC-M-t240": StratCfg(name="PAT+ACC-M-t240", post_size=20, enable_pat=True,
                                    pat_take_size=20, pat_max_pair_cost=1.00,
                                    pat_min_time_after_open_s=240.0),
        "PAT+ACC-M-t360": StratCfg(name="PAT+ACC-M-t360", post_size=20, enable_pat=True,
                                    pat_take_size=20, pat_max_pair_cost=1.00,
                                    pat_min_time_after_open_s=360.0,
                                    stop_posting_offset_s=870.0),
        "PAT+ACC-M-t480": StratCfg(name="PAT+ACC-M-t480", post_size=20, enable_pat=True,
                                    pat_take_size=20, pat_max_pair_cost=1.00,
                                    pat_min_time_after_open_s=480.0,
                                    stop_posting_offset_s=870.0),
        "PAT+ACC-M-t600": StratCfg(name="PAT+ACC-M-t600", post_size=20, enable_pat=True,
                                    pat_take_size=20, pat_max_pair_cost=1.00,
                                    pat_min_time_after_open_s=600.0,
                                    stop_posting_offset_s=870.0),
        "PAT+ACC-M-t720": StratCfg(name="PAT+ACC-M-t720", post_size=20, enable_pat=True,
                                    pat_take_size=20, pat_max_pair_cost=1.00,
                                    pat_min_time_after_open_s=720.0,
                                    stop_posting_offset_s=870.0),
        "MAS":         StratCfg(name="MAS-pre30",  post_size=5, enable_mas=True,
                                  mas_pre_mint_pairs=30, mas_min_sum_asks=1.005),
        "ACC-PC":      StratCfg(name="ACC-PC",     post_size=20, enable_pc=True,
                                  max_imbalance=20, pc_max_pair_cost=0.97),
    }
    selected = [strat_map[n] for n in args.strategies.split(",") if n in strat_map]
    print(f"Strategies: {[s.name for s in selected]}", flush=True)

    all_results = []
    for cfg in selected:
        rs = run_strategy_on_universe(args.asset, universe, cfg)
        all_results.extend(rs)

    if not all_results:
        print("No results.")
        return

    df = pd.DataFrame(all_results)
    out_csv = OUT_DIR / f"_fast_full_{args.asset}_{args.out_suffix}.csv"
    df.to_csv(out_csv, index=False)

    # Summary
    summary = {}
    for cfg in selected:
        sub = df[df["strategy"] == cfg.name]
        if sub.empty:
            continue
        summary[cfg.name] = {
            "n_slugs_with_activity": len(sub),
            "mean_pnl": float(sub["pnl"].mean()),
            "median_pnl": float(sub["pnl"].median()),
            "sum_pnl": float(sub["pnl"].sum()),
            "pct_positive": float((sub["pnl"] > 0).mean() * 100),
            "stddev": float(sub["pnl"].std()),
        }
    (OUT_DIR / f"_fast_full_{args.asset}_{args.out_suffix}_summary.json").write_text(
        json.dumps(summary, indent=2)
    )

    print()
    print("=" * 100)
    print("SUMMARY")
    print("=" * 100)
    for name, s in sorted(summary.items(), key=lambda x: -x[1]["mean_pnl"]):
        print(f"  {name:20s}  n={s['n_slugs_with_activity']:>5}  "
              f"mean=${s['mean_pnl']:+7.3f}  med=${s['median_pnl']:+7.3f}  "
              f"sum=${s['sum_pnl']:+9.0f}  pos={s['pct_positive']:.0f}%  "
              f"sd=${s['stddev']:.2f}")


if __name__ == "__main__":
    main()
