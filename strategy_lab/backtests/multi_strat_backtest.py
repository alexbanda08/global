"""
Multi-strategy backtest engine — runs ACC-M, ACC-PC, ACC-H, MAS on the SAME
slug data in a single pass. Designed to compare per-slug PnL against ACTUAL
reference-wallet behavior.

Run:
    py -3 -X utf8 strategy_lab/backtests/multi_strat_backtest.py \
        --slugs-from-csv strategy_lab/backtests/_wallet_profile_per_slug_agg.csv \
        --wallet-filter 0x04b6d7e9 \
        --max-slugs 100

Outputs:
    strategy_lab/backtests/_multi_strat_per_slug.csv
    strategy_lab/backtests/_multi_strat_summary.json
"""
from __future__ import annotations
import argparse
import gc
import json
import sys
import time
from collections import deque
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

OUT_DIR = ROOT / "strategy_lab" / "backtests"
OUT_DIR.mkdir(exist_ok=True)

L25_BASELINE = ROOT / "data/v4/refresh_2026_05_06/cache/btc_orderbook_L25.parquet"
L25_DELTA    = ROOT / "data/v4/refresh_2026_05_16/cache/btc_orderbook_L25_delta.parquet"
L25_PRE      = ROOT / "data/v4/refresh_2026_05_16/cache_pre/btc_orderbook_L25_pre_apr22.parquet"
TRADES = ROOT / "data/v4/canonical/trades_polymarket/btc.parquet"

FEE_RATE = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS)


@dataclass
class StratConfig:
    name: str = "ACC-M"
    post_size: float = 5.0
    bid_lift: float = 0.0           # cents above best_bid for our BID
    min_bid_price: float = 0.05
    max_bid_price: float = 0.95
    max_sum_bids: float = 1.00
    max_spread_per_leg: float = 0.05
    cancel_threshold: float = 0.03
    max_order_age_s: float = 20
    max_imbalance: float = 5.0
    absolute_max_inv: float = 50.0
    merge_threshold_pairs: float = 5.0
    stop_posting_offset_s: float = 270.0
    # ACC-PC
    enable_pc_taker: bool = False
    pc_max_pair_cost: float = 0.97
    pc_min_time_before_taker_s: float = 30
    pc_cvd_threshold: float = -1e18   # default disabled
    # ACC-H V3f
    enable_h_taker: bool = False
    h_rule_a: bool = True
    h_rule_b: bool = True
    h_rule_c: bool = True
    h_rule_d: bool = True
    h_max_taker_price: float = 0.50
    h_min_ask_drop_60s: float = 0.03
    h_min_trade_drop_5s: float = 0.02
    h_early_slot_end_s: float = 60
    h_buy_vol_threshold_60s: float = 50.0
    h_max_taker_per_slug: int = 30
    h_min_s_between_taker: float = 5
    # MAS
    enable_mas: bool = False
    mas_pre_mint_pairs: float = 30.0  # pairs to mint at slug start
    mas_min_sum_asks: float = 1.005
    mas_ask_lift: float = 0.0
    mas_max_ask_age_s: float = 30
    # PAT (Pair-Arb Taker) — market-buy both sides when sum_asks cheap
    enable_pat: bool = False
    pat_take_size: float = 20.0
    pat_max_pair_cost: float = 0.97   # only fire if (ask_up + ask_dn + fees) < this
    pat_min_s_between_fires: float = 5.0
    pat_max_fires_per_slug: int = 10
    pat_min_book_depth_each_side: float = 5.0  # need shares available at best ask
    pat_max_book_depth_filter: float = 1e9   # skip slug if depth > X (selection signal)
    pat_min_time_after_open_s: float = 5.0


def make_config(name: str, **kwargs) -> StratConfig:
    cfg = StratConfig(name=name)
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


@dataclass
class SideState:
    side: str
    inv: float = 0.0
    cost_paid: float = 0.0
    cash_received: float = 0.0  # for MAS sells
    rebate_income: float = 0.0
    taker_fees: float = 0.0
    n_pat_fires: int = 0
    last_pat_fire_us: int = 0
    open_bid_price: float | None = None
    open_bid_size_remaining: float = 0.0
    open_bid_posted_us: int = 0
    open_bid_queue_ahead: float = 0.0
    open_ask_price: float | None = None
    open_ask_size_remaining: float = 0.0
    open_ask_posted_us: int = 0
    open_ask_queue_ahead: float = 0.0
    n_taker_buys: int = 0
    last_taker_us: int = 0
    n_maker_bid_fills: int = 0
    n_maker_ask_fills: int = 0
    best_bid: float = 0.0
    best_ask: float = 1.0
    bid_size_at_best: float = 0.0
    ask_size_at_best: float = 0.0
    last_book_us: int = 0
    # CVD + ask history + trade history for V3f / ACC-PC
    cvd_window: deque = field(default_factory=lambda: deque())
    ask_history_60s: deque = field(default_factory=lambda: deque())
    trade_prices_5s: deque = field(default_factory=lambda: deque())
    buy_vol_60s: deque = field(default_factory=lambda: deque())


def evict_window(dq: deque, ts_us: int, window_s: float):
    cutoff = ts_us - int(window_s * 1_000_000)
    while dq and dq[0][0] < cutoff:
        dq.popleft()


# =============================================================================
# Data loaders (cached per slug)
# =============================================================================

_L25_SOURCES = [L25_PRE, L25_BASELINE, L25_DELTA]


def load_slug_l25(slug: str) -> dict[str, dict]:
    """Try each L25 source, return first one that has data for this slug."""
    target_arr = pa.array([slug])
    cols = ["timestamp_us", "slug", "outcome",
            "bid_price_0", "bid_size_0", "ask_price_0", "ask_size_0",
            "bid_price_1", "bid_size_1", "ask_price_1", "ask_size_1"]
    parts = []
    for src in _L25_SOURCES:
        if not src.exists():
            continue
        try:
            pf = pq.ParquetFile(str(src))
        except Exception:
            continue
        for rg_idx in range(pf.metadata.num_row_groups):
            try:
                rg = pf.read_row_group(rg_idx, columns=cols)
            except Exception:
                continue
            mask = pc.is_in(rg.column("slug"), value_set=target_arr)
            if pc.sum(mask).as_py() == 0:
                continue
            rg = rg.filter(mask)
            parts.append(rg.to_pandas())
    if not parts:
        return {}
    df = pd.concat(parts, ignore_index=True).sort_values("timestamp_us").drop_duplicates(["timestamp_us", "outcome"])
    out = {}
    for oc, grp in df.groupby("outcome", observed=True):
        bp = np.nan_to_num(grp["bid_price_0"].values.astype(np.float64), nan=0.0)
        bs = np.nan_to_num(grp["bid_size_0"].values.astype(np.float64), nan=0.0)
        ap = np.nan_to_num(grp["ask_price_0"].values.astype(np.float64), nan=0.0)
        asz = np.nan_to_num(grp["ask_size_0"].values.astype(np.float64), nan=0.0)
        out[oc] = {
            "ts": grp["timestamp_us"].values.astype(np.int64),
            "bp0": bp, "bs0": bs, "ap0": ap, "as0": asz,
        }
    return out


def load_slug_trades(slug: str) -> dict[str, pd.DataFrame]:
    target_arr = pa.array([slug])
    pf = pq.ParquetFile(str(TRADES))
    parts = []
    for rg_idx in range(pf.metadata.num_row_groups):
        try:
            rg = pf.read_row_group(rg_idx, columns=["timestamp_us", "slug", "outcome",
                                                      "price", "size", "side"])
        except Exception:
            continue
        mask = pc.is_in(rg.column("slug"), value_set=target_arr)
        if pc.sum(mask).as_py() == 0:
            continue
        rg = rg.filter(mask)
        parts.append(rg.to_pandas())
    if not parts:
        return {}
    df = pd.concat(parts, ignore_index=True).sort_values("timestamp_us")
    df["price"] = df["price"].astype(float)
    df["size"] = df["size"].astype(float)
    out = {oc: g.reset_index(drop=True) for oc, g in df.groupby("outcome", observed=True)}
    return out


# =============================================================================
# Core fill logic (shared)
# =============================================================================

def post_bid(ss: SideState, cfg: StratConfig, ts_us: int, lift: float = 0.0):
    """Post a maker BID at best_bid + lift."""
    ss.open_bid_price = ss.best_bid + lift
    ss.open_bid_size_remaining = cfg.post_size
    ss.open_bid_posted_us = ts_us
    # Queue: if we lift above best_bid, we're at front of queue (0 ahead)
    # Otherwise we join at the back
    ss.open_bid_queue_ahead = 0.0 if lift > 0 else max(ss.bid_size_at_best, 0.0)


def post_ask(ss: SideState, cfg: StratConfig, ts_us: int, lift: float = 0.0):
    ss.open_ask_price = ss.best_ask - lift
    ss.open_ask_size_remaining = cfg.post_size
    ss.open_ask_posted_us = ts_us
    ss.open_ask_queue_ahead = 0.0 if lift > 0 else max(ss.ask_size_at_best, 0.0)


def cancel_bid(ss: SideState):
    ss.open_bid_price = None
    ss.open_bid_size_remaining = 0.0
    ss.open_bid_queue_ahead = 0.0


def cancel_ask(ss: SideState):
    ss.open_ask_price = None
    ss.open_ask_size_remaining = 0.0
    ss.open_ask_queue_ahead = 0.0


def can_post_bid(ss: SideState, other_ss: SideState, cfg: StratConfig,
                  now_us: int, slot_start_us: int) -> tuple[bool, float]:
    elapsed_s = (now_us - slot_start_us) / 1_000_000
    if elapsed_s > cfg.stop_posting_offset_s:
        return False, 0.0
    if not (ss.best_bid > 0 and ss.best_ask > ss.best_bid):
        return False, 0.0
    if (ss.best_ask - ss.best_bid) > cfg.max_spread_per_leg:
        return False, 0.0
    sum_bids = ss.best_bid + other_ss.best_bid
    if sum_bids >= cfg.max_sum_bids:
        return False, 0.0
    target_px = ss.best_bid + cfg.bid_lift
    if not (cfg.min_bid_price <= target_px <= cfg.max_bid_price):
        return False, 0.0
    if ss.inv > other_ss.inv + cfg.max_imbalance:
        return False, 0.0
    if ss.inv >= cfg.absolute_max_inv:
        return False, 0.0
    return True, target_px


def can_post_ask(ss: SideState, other_ss: SideState, cfg: StratConfig,
                  now_us: int, slot_start_us: int) -> tuple[bool, float]:
    elapsed_s = (now_us - slot_start_us) / 1_000_000
    if elapsed_s > cfg.stop_posting_offset_s:
        return False, 0.0
    if not (ss.best_ask > 0 and ss.best_ask < 1 and ss.best_bid > 0):
        return False, 0.0
    sum_asks = ss.best_ask + other_ss.best_ask
    if sum_asks <= cfg.mas_min_sum_asks:
        return False, 0.0
    target_px = ss.best_ask - cfg.mas_ask_lift
    if ss.inv < cfg.post_size:  # need inventory to sell
        return False, 0.0
    return True, target_px


def should_cancel_bid(ss: SideState, cfg: StratConfig, now_us: int) -> bool:
    if ss.open_bid_price is None:
        return False
    if abs(ss.open_bid_price - ss.best_bid) >= cfg.cancel_threshold:
        return True
    if (now_us - ss.open_bid_posted_us) / 1_000_000 >= cfg.max_order_age_s:
        return True
    return False


def should_cancel_ask(ss: SideState, cfg: StratConfig, now_us: int) -> bool:
    if ss.open_ask_price is None:
        return False
    if abs(ss.open_ask_price - ss.best_ask) >= cfg.cancel_threshold:
        return True
    if (now_us - ss.open_ask_posted_us) / 1_000_000 >= cfg.mas_max_ask_age_s:
        return True
    return False


def fill_bid_from_trade(ss: SideState, price: float, size: float):
    """Maker BID gets filled by a taker SELL (FIFO queue)."""
    if ss.open_bid_price is None or price > ss.open_bid_price + 1e-9:
        return
    trade_remaining = size
    if ss.open_bid_queue_ahead > 0:
        consumed = min(ss.open_bid_queue_ahead, trade_remaining)
        ss.open_bid_queue_ahead -= consumed
        trade_remaining -= consumed
    if trade_remaining > 0.001 and ss.open_bid_size_remaining > 0:
        fill = min(ss.open_bid_size_remaining, trade_remaining)
        fp = ss.open_bid_price
        ss.inv += fill
        ss.cost_paid += fill * fp
        ss.rebate_income += fill * poly_maker_rebate_per_share(fp, fee_rate=FEE_RATE)
        ss.open_bid_size_remaining -= fill
        ss.n_maker_bid_fills += 1
        if ss.open_bid_size_remaining < 0.001:
            cancel_bid(ss)


def fill_ask_from_trade(ss: SideState, price: float, size: float):
    """Maker ASK gets filled by a taker BUY (FIFO queue)."""
    if ss.open_ask_price is None or price < ss.open_ask_price - 1e-9:
        return
    trade_remaining = size
    if ss.open_ask_queue_ahead > 0:
        consumed = min(ss.open_ask_queue_ahead, trade_remaining)
        ss.open_ask_queue_ahead -= consumed
        trade_remaining -= consumed
    if trade_remaining > 0.001 and ss.open_ask_size_remaining > 0:
        fill = min(ss.open_ask_size_remaining, trade_remaining)
        fp = ss.open_ask_price
        ss.inv -= fill
        ss.cash_received += fill * fp
        ss.rebate_income += fill * poly_maker_rebate_per_share(fp, fee_rate=FEE_RATE)
        ss.open_ask_size_remaining -= fill
        ss.n_maker_ask_fills += 1
        if ss.open_ask_size_remaining < 0.001:
            cancel_ask(ss)


# =============================================================================
# V3f composite taker trigger (for ACC-H)
# =============================================================================

def check_v3f(ss: SideState, other_ss: SideState, cfg: StratConfig,
               ts_us: int, slot_start_us: int) -> bool:
    if not cfg.enable_h_taker:
        return False
    if ss.inv >= cfg.absolute_max_inv:
        return False
    if ss.n_taker_buys >= cfg.h_max_taker_per_slug:
        return False
    if (ts_us - ss.last_taker_us) < cfg.h_min_s_between_taker * 1_000_000:
        return False
    if not (ss.best_ask > 0 and ss.best_ask < 1):
        return False

    current_ask = ss.best_ask

    # Rule A: discount-capture
    if cfg.h_rule_a and current_ask < cfg.h_max_taker_price:
        if len(ss.ask_history_60s) >= 10:
            asks = [a for _, a in ss.ask_history_60s if a > 0]
            if asks:
                median_ask = float(np.median(asks))
                if (median_ask - current_ask) >= cfg.h_min_ask_drop_60s:
                    return True

    # Rule B: sharp-drop on own-side trade prices
    if cfg.h_rule_b and len(ss.trade_prices_5s) >= 3:
        max_recent = max(p for _, p in ss.trade_prices_5s)
        if (max_recent - current_ask) >= cfg.h_min_trade_drop_5s:
            return True

    # Rule C: early-slot, no prior fill
    if cfg.h_rule_c:
        offset_s = (ts_us - slot_start_us) / 1_000_000
        if 0 <= offset_s <= cfg.h_early_slot_end_s:
            if ss.n_maker_bid_fills == 0 and ss.n_taker_buys == 0:
                return True

    # Rule D: buy-pressure then dip
    if cfg.h_rule_d and len(ss.trade_prices_5s) >= 1:
        buy_vol = sum(v for _, v in ss.buy_vol_60s)
        if buy_vol > cfg.h_buy_vol_threshold_60s:
            max_recent = max(p for _, p in ss.trade_prices_5s) if ss.trade_prices_5s else 0
            if (max_recent - current_ask) >= 0.001:
                return True
    return False


# =============================================================================
# ACC-PC pair-completion check
# =============================================================================

def check_pc(ss_lag: SideState, ss_lead: SideState, cfg: StratConfig,
              ts_us: int, slot_start_us: int) -> bool:
    if not cfg.enable_pc_taker:
        return False
    if ss_lead.inv < 1.0:
        return False
    if (ss_lead.inv - ss_lag.inv) < 1.0:
        return False
    elapsed_s = (ts_us - slot_start_us) / 1_000_000
    if elapsed_s < cfg.pc_min_time_before_taker_s:
        return False
    if ss_lag.n_taker_buys >= 20:
        return False
    if (ts_us - ss_lag.last_taker_us) < 5 * 1_000_000:
        return False
    ask = ss_lag.best_ask
    if not (ask > 0 and ask < 1):
        return False
    avg_lead = ss_lead.cost_paid / ss_lead.inv
    fee = poly_taker_fee_per_share(ask, fee_rate=FEE_RATE)
    pair_cost = avg_lead + ask + fee
    if pair_cost >= cfg.pc_max_pair_cost or pair_cost <= 0:
        return False
    # Spread filter
    if ss_lag.open_bid_price is not None:
        if (ss_lag.best_ask - ss_lag.open_bid_price) <= 0.02:
            return False
    # CVD filter
    cvd = sum(d for _, d in ss_lag.cvd_window)
    if cvd <= cfg.pc_cvd_threshold:
        return False
    return True


# =============================================================================
# PAT (Pair-Arb Taker) check
# =============================================================================

def check_pat(ss_up: SideState, ss_dn: SideState, cfg: StratConfig,
               ts_us: int, slot_start_us: int) -> bool:
    """Both sides must be ready: cheap pair + book depth + rate-limited."""
    if not cfg.enable_pat:
        return False
    # Need valid books
    if not (0 < ss_up.best_ask < 1 and 0 < ss_dn.best_ask < 1):
        return False

    # Rate limit (combined across both sides)
    last_fire = max(ss_up.last_pat_fire_us, ss_dn.last_pat_fire_us)
    if (ts_us - last_fire) < cfg.pat_min_s_between_fires * 1_000_000:
        return False
    if ss_up.n_pat_fires >= cfg.pat_max_fires_per_slug:
        return False

    # Time after open (let book stabilize)
    elapsed_s = (ts_us - slot_start_us) / 1_000_000
    if elapsed_s < cfg.pat_min_time_after_open_s:
        return False

    # Book depth required to fill our size cheap (top-of-book only)
    if ss_up.ask_size_at_best < cfg.pat_min_book_depth_each_side:
        return False
    if ss_dn.ask_size_at_best < cfg.pat_min_book_depth_each_side:
        return False

    # Selection signal: skip slug if book is too thick
    total_depth = ss_up.ask_size_at_best + ss_dn.ask_size_at_best
    if total_depth > cfg.pat_max_book_depth_filter:
        return False

    # Edge filter — pair cost must be < threshold
    ask_up = ss_up.best_ask
    ask_dn = ss_dn.best_ask
    fee_up = poly_taker_fee_per_share(ask_up, fee_rate=FEE_RATE)
    fee_dn = poly_taker_fee_per_share(ask_dn, fee_rate=FEE_RATE)
    pair_cost = ask_up + ask_dn + fee_up + fee_dn
    if pair_cost >= cfg.pat_max_pair_cost or pair_cost <= 0:
        return False

    # Inventory cap (don't over-accumulate even though we merge fast)
    if ss_up.inv >= cfg.absolute_max_inv or ss_dn.inv >= cfg.absolute_max_inv:
        return False

    return True


# =============================================================================
# Main per-slug simulator (one strategy)
# =============================================================================

def simulate_one(slug: str, outcome_truth: str, l25: dict, trades: dict,
                  slot_start_us: int, slot_end_us: int,
                  cfg: StratConfig) -> dict:
    ss_up = SideState(side="Up")
    ss_dn = SideState(side="Down")
    ss_map = {"Up": ss_up, "Down": ss_dn}

    cash_recovered = 0.0
    leftover_redeemed = 0.0
    leftover_burned_cost = 0.0
    n_merges = 0
    pairs_merged = 0.0
    n_v3f_a = n_v3f_b = n_v3f_c = n_v3f_d = 0

    # MAS upfront mint
    mint_cost = 0.0
    if cfg.enable_mas:
        mint_pairs = cfg.mas_pre_mint_pairs
        ss_up.inv = mint_pairs
        ss_dn.inv = mint_pairs
        mint_cost = mint_pairs * 1.0  # $1 per pair

    # Build event timeline
    events = []
    for oc, data in l25.items():
        for i in range(len(data["ts"])):
            events.append((int(data["ts"][i]), 0, oc, i))
    for oc, df in trades.items():
        for r in df.itertuples(index=False):
            events.append((int(r.timestamp_us), 1, oc,
                            float(r.price), float(r.size), r.side))
    events.sort(key=lambda e: (e[0], e[1]))

    if not events:
        return {"empty": True}

    for ev in events:
        ts_us, kind, oc = ev[0], ev[1], ev[2]
        if ts_us > slot_end_us:
            break
        side_ss = ss_map[oc]
        other_ss = ss_map["Down" if oc == "Up" else "Up"]

        if kind == 0:
            # L25 update
            i = ev[3]
            data = l25[oc]
            bp = float(data["bp0"][i])
            ap = float(data["ap0"][i])
            bs = float(data["bs0"][i])
            asz = float(data["as0"][i])
            if not (bp > 0 and ap > 0 and bp < ap):
                continue
            side_ss.best_bid = bp
            side_ss.best_ask = ap
            side_ss.bid_size_at_best = bs if bs > 0 else 1.0
            side_ss.ask_size_at_best = asz if asz > 0 else 1.0
            side_ss.last_book_us = ts_us

            # Track ask history for V3f
            if cfg.enable_h_taker:
                side_ss.ask_history_60s.append((ts_us, ap))
                evict_window(side_ss.ask_history_60s, ts_us, 60.0)

            # MAS: post ASK
            if cfg.enable_mas:
                if should_cancel_ask(side_ss, cfg, ts_us):
                    cancel_ask(side_ss)
                if side_ss.open_ask_price is None:
                    ok, px = can_post_ask(side_ss, other_ss, cfg, ts_us, slot_start_us)
                    if ok:
                        post_ask(side_ss, cfg, ts_us, lift=cfg.mas_ask_lift)
            else:
                # ACC-M / ACC-PC / ACC-H: post BID
                if should_cancel_bid(side_ss, cfg, ts_us):
                    cancel_bid(side_ss)
                if side_ss.open_bid_price is None:
                    ok, px = can_post_bid(side_ss, other_ss, cfg, ts_us, slot_start_us)
                    if ok:
                        # Override post price to lifted value
                        side_ss.best_bid_unused = ss_up.best_bid  # noqa
                        old_bid = side_ss.best_bid
                        side_ss.best_bid = px  # temp set for post_bid call
                        post_bid(side_ss, cfg, ts_us, lift=cfg.bid_lift)
                        side_ss.best_bid = old_bid

            # ACC-H V3f taker
            if cfg.enable_h_taker:
                if check_v3f(side_ss, other_ss, cfg, ts_us, slot_start_us):
                    ask = side_ss.best_ask
                    size = cfg.post_size
                    if side_ss.inv + size <= cfg.absolute_max_inv:
                        fee = poly_taker_fee_per_share(ask, fee_rate=FEE_RATE) * size
                        side_ss.inv += size
                        side_ss.cost_paid += size * ask
                        side_ss.taker_fees += fee
                        side_ss.n_taker_buys += 1
                        side_ss.last_taker_us = ts_us

            # ACC-PC taker check
            if cfg.enable_pc_taker:
                if other_ss.inv > side_ss.inv:
                    lag, lead = side_ss, other_ss
                else:
                    lag, lead = other_ss, side_ss
                if check_pc(lag, lead, cfg, ts_us, slot_start_us):
                    ask = lag.best_ask
                    imbalance = lead.inv - lag.inv
                    size = min(imbalance, cfg.post_size)
                    fee = poly_taker_fee_per_share(ask, fee_rate=FEE_RATE) * size
                    lag.inv += size
                    lag.cost_paid += size * ask
                    lag.taker_fees += fee
                    lag.n_taker_buys += 1
                    lag.last_taker_us = ts_us

            # PAT (Pair-Arb Taker) — market-buy BOTH sides when pair cost cheap
            if cfg.enable_pat:
                if check_pat(ss_up, ss_dn, cfg, ts_us, slot_start_us):
                    take_size = cfg.pat_take_size
                    # Cap size by available depth on each side
                    take_size = min(take_size, ss_up.ask_size_at_best,
                                     ss_dn.ask_size_at_best)
                    if take_size >= cfg.pat_min_book_depth_each_side:
                        ask_up_v = ss_up.best_ask
                        ask_dn_v = ss_dn.best_ask
                        fee_up_v = poly_taker_fee_per_share(ask_up_v, fee_rate=FEE_RATE)
                        fee_dn_v = poly_taker_fee_per_share(ask_dn_v, fee_rate=FEE_RATE)
                        # Buy Up
                        ss_up.inv += take_size
                        ss_up.cost_paid += take_size * ask_up_v
                        ss_up.taker_fees += take_size * fee_up_v
                        ss_up.n_pat_fires += 1
                        ss_up.last_pat_fire_us = ts_us
                        # Buy Down
                        ss_dn.inv += take_size
                        ss_dn.cost_paid += take_size * ask_dn_v
                        ss_dn.taker_fees += take_size * fee_dn_v
                        ss_dn.n_pat_fires += 1
                        ss_dn.last_pat_fire_us = ts_us
                        # Decrement book depth (since we consumed it)
                        ss_up.ask_size_at_best -= take_size
                        ss_dn.ask_size_at_best -= take_size
                        # Immediate merge — paired by construction
                        pairs = take_size
                        ss_up.inv -= pairs
                        ss_dn.inv -= pairs
                        cash_recovered += pairs * 1.0
                        n_merges += 1
                        pairs_merged += pairs

        elif kind == 1:
            # Trade — update CVD + ask history + simulate fills
            price, size, side = ev[3], ev[4], ev[5]
            side_upper = side.upper() if isinstance(side, str) else ""
            # CVD: BUY size positive, SELL size negative (from market POV)
            delta = size if side_upper == "BUY" else -size
            side_ss.cvd_window.append((ts_us, delta))
            evict_window(side_ss.cvd_window, ts_us, 30.0)

            side_ss.trade_prices_5s.append((ts_us, price))
            evict_window(side_ss.trade_prices_5s, ts_us, 5.0)

            if side_upper == "BUY":
                side_ss.buy_vol_60s.append((ts_us, size))
                evict_window(side_ss.buy_vol_60s, ts_us, 60.0)

            if cfg.enable_mas:
                # MAS: taker BUY hits our ASK
                if side_upper == "BUY":
                    fill_ask_from_trade(side_ss, price, size)
            else:
                # ACC-*: taker SELL hits our BID
                if side_upper == "SELL":
                    fill_bid_from_trade(side_ss, price, size)

        # Merge trigger (skip MAS — no merge mid-slug)
        if not cfg.enable_mas:
            pairs = min(ss_up.inv, ss_dn.inv)
            if pairs >= cfg.merge_threshold_pairs:
                ss_up.inv -= pairs
                ss_dn.inv -= pairs
                cash_recovered += pairs * 1.0
                n_merges += 1
                pairs_merged += pairs

    # End-of-slug
    if not cfg.enable_mas:
        pairs = min(ss_up.inv, ss_dn.inv)
        if pairs > 0:
            ss_up.inv -= pairs
            ss_dn.inv -= pairs
            cash_recovered += pairs * 1.0
            n_merges += 1
            pairs_merged += pairs

    # Redeem winning leftover
    if outcome_truth == "Up":
        if ss_up.inv > 0:
            leftover_redeemed += ss_up.inv * 1.0
            cash_recovered += leftover_redeemed
        if ss_dn.inv > 0:
            avg_dn = (ss_dn.cost_paid + (cfg.mas_pre_mint_pairs if cfg.enable_mas else 0)) / max(ss_dn.inv, 1)
            leftover_burned_cost = ss_dn.inv * (avg_dn if avg_dn > 0 and avg_dn < 2 else 0.5)
    elif outcome_truth == "Down":
        if ss_dn.inv > 0:
            leftover_redeemed += ss_dn.inv * 1.0
            cash_recovered += leftover_redeemed
        if ss_up.inv > 0:
            avg_up = (ss_up.cost_paid + (cfg.mas_pre_mint_pairs if cfg.enable_mas else 0)) / max(ss_up.inv, 1)
            leftover_burned_cost = ss_up.inv * (avg_up if avg_up > 0 and avg_up < 2 else 0.5)

    total_cost = ss_up.cost_paid + ss_dn.cost_paid + mint_cost
    total_cash_in = ss_up.cash_received + ss_dn.cash_received + cash_recovered
    total_rebates = ss_up.rebate_income + ss_dn.rebate_income
    total_fees = ss_up.taker_fees + ss_dn.taker_fees
    pnl = total_cash_in + total_rebates - total_cost - total_fees

    return {
        "strategy": cfg.name,
        "n_maker_bid_up": ss_up.n_maker_bid_fills,
        "n_maker_bid_dn": ss_dn.n_maker_bid_fills,
        "n_maker_ask_up": ss_up.n_maker_ask_fills,
        "n_maker_ask_dn": ss_dn.n_maker_ask_fills,
        "n_taker_up": ss_up.n_taker_buys,
        "n_taker_dn": ss_dn.n_taker_buys,
        "inv_up": ss_up.inv,
        "inv_dn": ss_dn.inv,
        "cost_paid": total_cost,
        "cash_received": total_cash_in,
        "rebates": total_rebates,
        "taker_fees": total_fees,
        "leftover_redeemed": leftover_redeemed,
        "leftover_burned_cost": leftover_burned_cost,
        "n_merges": n_merges,
        "pairs_merged": pairs_merged,
        "pnl": pnl,
    }


# =============================================================================
# Orchestrator
# =============================================================================

def run_slug(slug: str, outcome_truth: str, configs: list[StratConfig]) -> dict:
    try:
        slot_start_us = int(slug.rsplit("-", 1)[1]) * 1_000_000
    except Exception:
        return {"skipped": "bad_slug"}
    # Detect 5m vs 15m
    if "-5m-" in slug:
        slot_dur_s = 300
    elif "-15m-" in slug:
        slot_dur_s = 900
    else:
        slot_dur_s = 300
    slot_end_us = slot_start_us + slot_dur_s * 1_000_000

    l25 = load_slug_l25(slug)
    if not l25 or "Up" not in l25 or "Down" not in l25:
        return {"skipped": "no_l25"}
    trades = load_slug_trades(slug)

    out = {"slug": slug, "outcome_truth": outcome_truth,
           "slot_start_s": slot_start_us // 1_000_000,
           "tf": "5m" if slot_dur_s == 300 else "15m"}
    for cfg in configs:
        r = simulate_one(slug, outcome_truth, l25, trades,
                          slot_start_us, slot_end_us, cfg)
        if r.get("empty"):
            continue
        for k, v in r.items():
            if k != "strategy":
                out[f"{cfg.name}.{k}"] = v
    return out


def default_configs() -> list[StratConfig]:
    return [
        make_config("ACC-M"),
        make_config("ACC-M-lift1c", bid_lift=0.01),
        make_config("ACC-PC", enable_pc_taker=True, pc_cvd_threshold=-1e18,
                     pc_max_pair_cost=0.99, max_imbalance=10),
        make_config("ACC-H", enable_h_taker=True, max_imbalance=10),
        make_config("MAS", enable_mas=True, mas_pre_mint_pairs=30,
                     mas_min_sum_asks=1.005),
    ]


def size_sweep_configs() -> list[StratConfig]:
    """Size sweep: ACC-M at different POST_SIZE + MAS at different pre-mint."""
    return [
        make_config("ACC-M-sz5",  post_size=5),
        make_config("ACC-M-sz10", post_size=10),
        make_config("ACC-M-sz20", post_size=20),
        make_config("ACC-M-sz50", post_size=50),
        make_config("ACC-M-sz5-imb10",  post_size=5, max_imbalance=10),
        make_config("ACC-M-sz10-imb10", post_size=10, max_imbalance=10),
        make_config("ACC-M-sz20-imb10", post_size=20, max_imbalance=10),
        make_config("MAS-pre30",  enable_mas=True, mas_pre_mint_pairs=30,  mas_min_sum_asks=1.005),
        make_config("MAS-pre100", enable_mas=True, mas_pre_mint_pairs=100, mas_min_sum_asks=1.005),
        make_config("MAS-pre200", enable_mas=True, mas_pre_mint_pairs=200, mas_min_sum_asks=1.005),
        make_config("MAS-pre100-tight", enable_mas=True, mas_pre_mint_pairs=100, mas_min_sum_asks=1.02),
    ]


def big_sweep_configs() -> list[StratConfig]:
    """Bigger sizes + MAS + variants."""
    return [
        make_config("ACC-M-sz20", post_size=20),
        make_config("ACC-M-sz50", post_size=50),
        make_config("ACC-M-sz100", post_size=100),
        make_config("ACC-M-sz200", post_size=200),
        make_config("ACC-M-sz50-tight",  post_size=50, max_imbalance=2, merge_threshold_pairs=2),
        make_config("ACC-M-sz50-loose",  post_size=50, max_imbalance=20, merge_threshold_pairs=10),
        make_config("ACC-M-sz50-mergehot",post_size=50, max_imbalance=5, merge_threshold_pairs=10),
        make_config("MAS-pre50",  enable_mas=True, mas_pre_mint_pairs=50,  mas_min_sum_asks=1.005),
        make_config("MAS-pre200-tight", enable_mas=True, mas_pre_mint_pairs=200, mas_min_sum_asks=1.02),
        make_config("MAS-pre500", enable_mas=True, mas_pre_mint_pairs=500, mas_min_sum_asks=1.005),
    ]


def pat_sweep_configs() -> list[StratConfig]:
    """PAT (Pair-Arb Taker) variations + baselines."""
    return [
        # Baselines for comparison
        make_config("ACC-M-sz20", post_size=20),
        # Different pair-cost thresholds — relaxed to find where it actually fires
        make_config("PAT-sz20-c97",  enable_pat=True, pat_take_size=20,
                     pat_max_pair_cost=0.97, post_size=0),
        make_config("PAT-sz20-c98",  enable_pat=True, pat_take_size=20,
                     pat_max_pair_cost=0.98, post_size=0),
        make_config("PAT-sz20-c99",  enable_pat=True, pat_take_size=20,
                     pat_max_pair_cost=0.99, post_size=0),
        make_config("PAT-sz20-c1.00", enable_pat=True, pat_take_size=20,
                     pat_max_pair_cost=1.00, post_size=0),
        make_config("PAT-sz20-c1.01", enable_pat=True, pat_take_size=20,
                     pat_max_pair_cost=1.01, post_size=0),
        # Bigger size
        make_config("PAT-sz50-c1.00", enable_pat=True, pat_take_size=50,
                     pat_max_pair_cost=1.00, post_size=0),
        make_config("PAT-sz100-c1.00",enable_pat=True, pat_take_size=100,
                     pat_max_pair_cost=1.00, post_size=0),
        # Thin-book selection signal (z=-17.86 on xuanxuan008)
        make_config("PAT-sz20-c1.00-thin500", enable_pat=True, pat_take_size=20,
                     pat_max_pair_cost=1.00, pat_max_book_depth_filter=500.0,
                     post_size=0),
        # PAT + ACC-M hybrid
        make_config("PAT+ACC-M-sz20-c1.00", enable_pat=True, pat_take_size=20,
                     pat_max_pair_cost=1.00, post_size=20),
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slugs-from-csv", type=str, default="",
                     help="CSV with 'slug' column (e.g. wallet_profile output)")
    ap.add_argument("--wallet-filter", type=str, default="",
                     help="Only slugs where this wallet was active (matches 'wallet' col)")
    ap.add_argument("--max-slugs", type=int, default=100)
    ap.add_argument("--asset-filter", type=str, default="BTC")
    ap.add_argument("--tf-filter", type=str, default="updown_5m,updown_15m")
    ap.add_argument("--out-suffix", type=str, default="")
    ap.add_argument("--sweep-mode", type=str, default="default",
                     help="default | size (11 configs sweep)")
    args = ap.parse_args()

    # Pick slugs
    if args.slugs_from_csv:
        df = pd.read_csv(args.slugs_from_csv)
        if args.wallet_filter and "wallet" in df.columns:
            df = df[df["wallet"] == args.wallet_filter]
        if args.asset_filter and "asset_sym" in df.columns:
            df = df[df["asset_sym"] == args.asset_filter]
        if args.tf_filter and "mc" in df.columns:
            tfs = set(args.tf_filter.split(","))
            df = df[df["mc"].isin(tfs)]
        slugs_list = df["slug"].drop_duplicates().tolist()[:args.max_slugs]
        # Resolve outcome from resolutions
        res = load_resolutions(assets=["BTC", "ETH", "SOL"])
        slug_to_outcome = dict(zip(res["slug"], res["outcome"]))
        slugs = [(s, slug_to_outcome.get(s, "Up")) for s in slugs_list
                  if s in slug_to_outcome]
    else:
        # default: pick BTC 5m from resolution table evenly
        res = load_resolutions(assets=["BTC"], timeframes=["5m"]).sort_values("slot_start_us")
        idx = np.linspace(0, len(res) - 1, args.max_slugs).astype(int)
        slugs = list(zip(res.iloc[idx]["slug"], res.iloc[idx]["outcome"]))

    if args.sweep_mode == "size":
        configs = size_sweep_configs()
    elif args.sweep_mode == "big":
        configs = big_sweep_configs()
    elif args.sweep_mode == "pat":
        configs = pat_sweep_configs()
    else:
        configs = default_configs()
    print(f"Backtest plan: {len(slugs)} slugs, {len(configs)} strategies ({args.sweep_mode})")
    results = []
    t_start = time.time()
    for i, (slug, outcome) in enumerate(slugs):
        t0 = time.time()
        r = run_slug(slug, outcome, configs)
        if r.get("skipped"):
            print(f"  [{i+1}/{len(slugs)}] {slug} SKIP {r['skipped']}", flush=True)
            continue
        results.append(r)
        dt = (time.time() - t0) * 1000
        pnls = " ".join(
            f"{c.name}={r.get(c.name + '.pnl', float('nan')):+.2f}" for c in configs
        )
        print(f"  [{i+1}/{len(slugs)}] {slug} ({outcome}) {pnls}  {dt:.0f}ms",
              flush=True)
        gc.collect()

    if not results:
        print("no results")
        return

    df = pd.DataFrame(results)
    suffix = f"_{args.out_suffix}" if args.out_suffix else ""
    df.to_csv(OUT_DIR / f"_multi_strat_per_slug{suffix}.csv", index=False)

    # Per-strategy summary
    summary = {"n_slugs": len(df), "runtime_s": time.time() - t_start, "strategies": {}}
    for c in configs:
        prefix = c.name + "."
        col_pnl = f"{c.name}.pnl"
        if col_pnl not in df.columns:
            continue
        s = df[col_pnl].dropna()
        summary["strategies"][c.name] = {
            "mean_pnl": float(s.mean()),
            "median_pnl": float(s.median()),
            "sum_pnl": float(s.sum()),
            "pct_positive": float((s > 0).mean() * 100),
            "stddev": float(s.std()),
        }
    (OUT_DIR / f"_multi_strat_summary{suffix}.json").write_text(
        json.dumps(summary, indent=2)
    )

    print()
    print("=" * 80)
    print(f"SUMMARY ({len(df)} slugs, {time.time()-t_start:.0f}s)")
    print("=" * 80)
    print(json.dumps(summary["strategies"], indent=2))


if __name__ == "__main__":
    main()
