"""
ACC-PC backtest — head-to-head vs ACC-M on real BTC 5m slugs.

Reads raw L25 parquets (event-level, NOT 1Hz subsampled) + trades parquet.
For each slug runs both strategies in parallel and produces per-slug PnL diff.

Run:
    py -3 -X utf8 strategy_lab/backtests/acc_pc_backtest.py

Output:
    strategy_lab/backtests/_acc_pc_results.csv
    strategy_lab/backtests/_acc_pc_summary.json
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
TRADES = ROOT / "data/v4/canonical/trades_polymarket/btc.parquet"

FEE_RATE = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS)
CLOB_MIN = 5.0


# ============================================================================
# Configuration
# ============================================================================

@dataclass
class StratConfig:
    # Posting
    post_size: float = 5.0
    min_bid_price: float = 0.05
    max_bid_price: float = 0.95
    max_sum_bids: float = 1.00
    max_spread_per_leg: float = 0.05

    # Cancel
    cancel_threshold: float = 0.03   # 3¢
    max_order_age_s: float = 20

    # Inventory
    max_imbalance: float = 5.0       # ACC-M strict
    absolute_max_inv: float = 50.0

    # Merge
    merge_threshold_pairs: float = 5.0

    # Slug timing
    stop_posting_offset_s: float = 270.0   # 30s before close
    merge_at_close_offset_s: float = 270.0


@dataclass
class ACCPCConfig(StratConfig):
    # Additional ACC-PC params
    max_imbalance: float = 10.0      # looser — taker rebalances
    enable_taker: bool = True
    max_pair_cost: float = 0.97
    min_time_before_taker_s: float = 30
    min_spread_to_taker: float = 0.02  # if (ask - our_bid) <= this, BID will fill — skip taker
    cvd_window_s: float = 30
    cvd_min_threshold: float = 0     # only take if cvd_lagging > 0
    max_taker_per_slug: int = 20
    min_s_between_taker: float = 5


# ============================================================================
# Per-side strategy state
# ============================================================================

@dataclass
class SideState:
    side: str             # 'Up' or 'Down'
    inv: float = 0.0      # filled shares
    cost_paid: float = 0.0
    rebate_income: float = 0.0
    taker_fees: float = 0.0
    # open BID order
    open_bid_price: float | None = None
    open_bid_size_remaining: float = 0.0
    open_bid_posted_us: int = 0
    open_bid_queue_ahead: float = 0.0  # FIFO: shares ahead of us in queue at our price
    # taker state
    n_taker_fills: int = 0
    last_taker_us: int = 0
    # latest book
    best_bid: float = 0.0
    best_ask: float = 1.0
    bid_size_at_best: float = 0.0
    last_book_us: int = 0
    # CVD tracking — buyer aggression on this side (taker BUYs - taker SELLs)
    cvd_window: deque = field(default_factory=lambda: deque())


@dataclass
class SlugResult:
    slug: str
    outcome_truth: str
    n_events: int
    n_l25: int
    n_trades: int
    span_s: float

    # ACC-M baseline
    accm_inv_up: float = 0
    accm_inv_dn: float = 0
    accm_cost: float = 0
    accm_rebates: float = 0
    accm_taker_fees: float = 0
    accm_cash_recovered: float = 0
    accm_leftover_redeemed_usd: float = 0
    accm_leftover_burned_usd: float = 0
    accm_pnl: float = 0
    accm_n_merges: int = 0
    accm_pairs_merged: float = 0
    accm_n_maker_fills_up: int = 0
    accm_n_maker_fills_dn: int = 0
    accm_n_taker_buys_up: int = 0
    accm_n_taker_buys_dn: int = 0

    # ACC-PC variant
    accpc_inv_up: float = 0
    accpc_inv_dn: float = 0
    accpc_cost: float = 0
    accpc_rebates: float = 0
    accpc_taker_fees: float = 0
    accpc_cash_recovered: float = 0
    accpc_leftover_redeemed_usd: float = 0
    accpc_leftover_burned_usd: float = 0
    accpc_pnl: float = 0
    accpc_n_merges: int = 0
    accpc_pairs_merged: float = 0
    accpc_n_maker_fills_up: int = 0
    accpc_n_maker_fills_dn: int = 0
    accpc_n_taker_buys_up: int = 0
    accpc_n_taker_buys_dn: int = 0


# ============================================================================
# Data loading
# ============================================================================

def list_btc_5m_slugs(window_start_us: int, window_end_us: int,
                      limit: int | None = None,
                      sample: str = "even") -> list[tuple[str, str]]:
    """Pull list of (slug, outcome_truth) for BTC 5m from chainlink resolutions
    within the canonical baseline window.

    sample: 'head' (first N), 'even' (evenly-spaced across window), 'random' (seeded)
    """
    res = load_resolutions(assets=["BTC"], timeframes=["5m"])
    res = res[(res.slot_start_us >= window_start_us) &
              (res.slot_start_us < window_end_us)]
    res = res.sort_values("slot_start_us").reset_index(drop=True)
    if limit and len(res) > limit:
        if sample == "head":
            res = res.head(limit)
        elif sample == "even":
            # Evenly-spaced indices across the window
            idx = np.linspace(0, len(res) - 1, limit).astype(int)
            res = res.iloc[idx].reset_index(drop=True)
        else:  # random
            res = res.sample(n=limit, random_state=42).reset_index(drop=True)
    return list(zip(res.slug.tolist(), res.outcome.tolist()))


def load_slug_l25(parquet_path: Path, slug: str) -> dict[str, np.ndarray]:
    """Return dict[outcome]: structured book events."""
    pf = pq.ParquetFile(str(parquet_path))
    target_arr = pa.array([slug])
    cols = ["timestamp_us", "slug", "outcome",
            "bid_price_0", "bid_size_0", "ask_price_0", "ask_size_0",
            "bid_price_1", "bid_size_1", "ask_price_1", "ask_size_1"]

    parts = []
    for rg_idx in range(pf.metadata.num_row_groups):
        rg = pf.read_row_group(rg_idx, columns=cols)
        mask = pc.is_in(rg.column("slug"), value_set=target_arr)
        if pc.sum(mask).as_py() == 0:
            continue
        rg = rg.filter(mask)
        parts.append(rg.to_pandas())

    if not parts:
        return {}
    df = pd.concat(parts, ignore_index=True).sort_values("timestamp_us")
    out = {}
    for oc, grp in df.groupby("outcome", observed=True):
        # Replace NaN with 0 to avoid downstream NaN propagation
        bp = np.nan_to_num(grp["bid_price_0"].values.astype(np.float64), nan=0.0)
        bs = np.nan_to_num(grp["bid_size_0"].values.astype(np.float64), nan=0.0)
        ap = np.nan_to_num(grp["ask_price_0"].values.astype(np.float64), nan=0.0)
        asz = np.nan_to_num(grp["ask_size_0"].values.astype(np.float64), nan=0.0)
        out[oc] = {
            "ts": grp["timestamp_us"].values.astype(np.int64),
            "bp0": bp,
            "bs0": bs,
            "ap0": ap,
            "as0": asz,
        }
    return out


def load_slug_trades(slug: str) -> dict[str, pd.DataFrame]:
    """Return dict[outcome]: trades DataFrame sorted by ts."""
    pf = pq.ParquetFile(str(TRADES))
    target_arr = pa.array([slug])
    parts = []
    for rg_idx in range(pf.metadata.num_row_groups):
        rg = pf.read_row_group(rg_idx, columns=[
            "timestamp_us", "slug", "outcome", "price", "size", "side"
        ])
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
    out = {oc: grp.reset_index(drop=True) for oc, grp in df.groupby("outcome")}
    return out


# ============================================================================
# Strategy logic
# ============================================================================

def update_cvd(ss: SideState, ts_us: int, side: str, size: float,
               window_s: float = 30.0):
    """Append a trade to CVD window, evict old."""
    delta = size if side == "BUY" else -size
    ss.cvd_window.append((ts_us, delta))
    cutoff = ts_us - int(window_s * 1_000_000)
    while ss.cvd_window and ss.cvd_window[0][0] < cutoff:
        ss.cvd_window.popleft()


def cvd_value(ss: SideState) -> float:
    return sum(d for _, d in ss.cvd_window)


def should_post_bid(ss: SideState, other_ss: SideState, cfg: StratConfig,
                    now_us: int, slot_start_us: int, slot_dur_s: int) -> tuple[bool, float]:
    """Return (should_post, price)."""
    # Stop near close
    elapsed_s = (now_us - slot_start_us) / 1_000_000
    if elapsed_s > cfg.stop_posting_offset_s:
        return False, 0.0
    # Have a valid book?
    if ss.best_bid <= 0 or ss.best_ask <= 0:
        return False, 0.0
    # Spread filter
    if (ss.best_ask - ss.best_bid) > cfg.max_spread_per_leg:
        return False, 0.0
    # Edge filter
    sum_bids = ss.best_bid + other_ss.best_bid
    if sum_bids >= cfg.max_sum_bids:
        return False, 0.0
    # Price band
    px = ss.best_bid
    if not (cfg.min_bid_price <= px <= cfg.max_bid_price):
        return False, 0.0
    # Inventory balance (ACC-M strict, ACC-PC looser)
    if ss.inv > other_ss.inv + cfg.max_imbalance:
        return False, 0.0
    # Absolute cap
    if ss.inv >= cfg.absolute_max_inv:
        return False, 0.0
    return True, px


def should_cancel_bid(ss: SideState, cfg: StratConfig, now_us: int) -> bool:
    if ss.open_bid_price is None:
        return False
    # Displacement
    if abs(ss.open_bid_price - ss.best_bid) >= cfg.cancel_threshold:
        return True
    # Age
    age_s = (now_us - ss.open_bid_posted_us) / 1_000_000
    if age_s >= cfg.max_order_age_s:
        return True
    return False


def check_pc_taker(ss_lagging: SideState, ss_leading: SideState,
                    cfg: ACCPCConfig, now_us: int, slot_start_us: int) -> bool:
    """ACC-PC reactive taker — fire only when imbalanced + cheap + filters pass."""
    if not cfg.enable_taker:
        return False
    if ss_leading.inv < 1.0:
        return False  # nothing to pair-complete
    imbalance = ss_leading.inv - ss_lagging.inv
    if imbalance < 1.0:
        return False  # already balanced

    # Time filter — let BIDs work first
    elapsed_s = (now_us - slot_start_us) / 1_000_000
    if elapsed_s < cfg.min_time_before_taker_s:
        return False

    # Rate limit
    if ss_lagging.n_taker_fills >= cfg.max_taker_per_slug:
        return False
    if (now_us - ss_lagging.last_taker_us) < cfg.min_s_between_taker * 1_000_000:
        return False

    # Edge filter — pair cost must be < $0.97
    if ss_leading.inv <= 0:
        return False
    ask = ss_lagging.best_ask
    if not (ask > 0 and ask < 1):
        return False
    avg_leading = ss_leading.cost_paid / ss_leading.inv
    fee_per_share = poly_taker_fee_per_share(ask, fee_rate=FEE_RATE)
    pair_cost = avg_leading + ask + fee_per_share
    if pair_cost >= cfg.max_pair_cost or pair_cost <= 0:
        return False

    # Spread filter — if our BID is close to ask, BID will fill — don't take
    if ss_lagging.open_bid_price is not None:
        spread_to_take = ss_lagging.best_ask - ss_lagging.open_bid_price
        if spread_to_take <= cfg.min_spread_to_taker:
            return False

    # CVD filter — only take if buyers dominate (BID won't fill)
    cvd = cvd_value(ss_lagging)
    if cvd <= cfg.cvd_min_threshold:
        return False

    return True


# ============================================================================
# Slug simulator
# ============================================================================

def simulate_slug(slug: str, outcome_truth: str,
                  l25: dict, trades: dict,
                  slot_start_us: int, slot_end_us: int,
                  use_taker: bool,
                  cvd_threshold: float = 0.0,
                  no_cvd: bool = False,
                  max_pair_cost: float = 0.97) -> dict:
    """Simulate one slug with one config. Returns metrics dict."""
    if not use_taker:
        cfg = StratConfig()
    else:
        cfg = ACCPCConfig()
        cfg.cvd_min_threshold = cvd_threshold
        cfg.max_pair_cost = max_pair_cost
        if no_cvd:
            cfg.cvd_min_threshold = -1e18  # effectively disabled

    ss_up = SideState(side="Up")
    ss_dn = SideState(side="Down")
    ss = {"Up": ss_up, "Down": ss_dn}

    cash_recovered = 0.0
    n_merges = 0
    pairs_merged = 0.0
    n_taker_buys = {"Up": 0, "Down": 0}
    n_maker_fills = {"Up": 0, "Down": 0}

    # Merge events from both outcomes + trades into one sorted timeline
    # Event format: (ts_us, kind, outcome, ...payload)
    events = []
    n_l25 = 0
    n_trades = 0
    for oc, data in l25.items():
        for i in range(len(data["ts"])):
            events.append((int(data["ts"][i]), 0, oc, i))  # kind 0 = L25
            n_l25 += 1
    for oc, df in trades.items():
        for r in df.itertuples(index=False):
            events.append((int(r.timestamp_us), 1, oc,
                            float(r.price), float(r.size), r.side))
            n_trades += 1

    events.sort(key=lambda e: (e[0], e[1]))  # ts asc, L25 before trades for same ts

    # CVD per side over a 30s rolling window of TAKER trades
    # (positive = takers BUYING on that side, negative = takers SELLING)

    # Time bounds
    if not events:
        return {"empty": True}
    t0 = events[0][0]
    t_end_us = slot_end_us  # use actual slot close

    for ev in events:
        ts_us = ev[0]
        kind = ev[1]
        oc = ev[2]
        if ts_us > t_end_us:
            break

        side_ss = ss[oc]
        other_ss = ss["Down" if oc == "Up" else "Up"]

        if kind == 0:
            # L25 update — update best bid/ask (guard NaN/missing)
            i = ev[3]
            data = l25[oc]
            bp = float(data["bp0"][i])
            ap = float(data["ap0"][i])
            bs = float(data["bs0"][i])
            if not (bp > 0 and ap > 0 and bp < ap):
                # Skip update if book is degenerate/empty
                continue
            side_ss.best_bid = bp
            side_ss.best_ask = ap
            side_ss.bid_size_at_best = bs if bs > 0 else 1.0
            side_ss.last_book_us = ts_us

            # 1. Cancel check
            if should_cancel_bid(side_ss, cfg, ts_us):
                side_ss.open_bid_price = None
                side_ss.open_bid_size_remaining = 0.0
                side_ss.open_bid_queue_ahead = 0.0

            # 2. Post check
            if side_ss.open_bid_price is None:
                ok, px = should_post_bid(side_ss, other_ss, cfg, ts_us,
                                          slot_start_us, 300)
                if ok:
                    side_ss.open_bid_price = px
                    side_ss.open_bid_size_remaining = cfg.post_size
                    side_ss.open_bid_posted_us = ts_us
                    # FIFO queue position: shares ahead of us = visible_size at our price
                    # (if our price == best_bid, that's the FULL queue; we join at the back)
                    side_ss.open_bid_queue_ahead = max(side_ss.bid_size_at_best, 0.0)

            # 3. ACC-PC taker check (only on L25 updates — every tick)
            if use_taker:
                # Identify lagging side (the one with LESS inventory)
                if other_ss.inv > side_ss.inv:
                    lag, lead = side_ss, other_ss
                else:
                    lag, lead = other_ss, side_ss

                if check_pc_taker(lag, lead, cfg, ts_us, slot_start_us):
                    # Market buy on the lagging side
                    ask = lag.best_ask
                    imbalance = lead.inv - lag.inv
                    size = min(imbalance, cfg.post_size)  # take just enough to pair
                    fee_per_share = poly_taker_fee_per_share(ask, fee_rate=FEE_RATE)
                    cost = size * ask
                    fee = size * fee_per_share
                    lag.inv += size
                    lag.cost_paid += cost
                    lag.taker_fees += fee
                    lag.n_taker_fills += 1
                    lag.last_taker_us = ts_us
                    n_taker_buys[lag.side] += 1

        elif kind == 1:
            # Trade — update CVD + simulate maker fill if applicable
            price, size, side = ev[3], ev[4], ev[5]
            side_upper = side.upper() if isinstance(side, str) else ""
            update_cvd(side_ss, ts_us, side_upper, size, window_s=30.0)

            # Maker BID fill: taker SELLs at <= our BID price (FIFO queue model)
            if (side_upper == "SELL" and
                side_ss.open_bid_price is not None and
                price <= side_ss.open_bid_price + 1e-9 and
                side_ss.open_bid_size_remaining > 0):

                # FIFO: first the queue ahead of us consumes the trade
                trade_remaining = size
                if side_ss.open_bid_queue_ahead > 0:
                    consumed = min(side_ss.open_bid_queue_ahead, trade_remaining)
                    side_ss.open_bid_queue_ahead -= consumed
                    trade_remaining -= consumed

                # Whatever's left we can fill (up to our remaining size)
                if trade_remaining > 0.001 and side_ss.open_bid_size_remaining > 0:
                    fill_size = min(side_ss.open_bid_size_remaining, trade_remaining)
                    fill_price = side_ss.open_bid_price
                    side_ss.inv += fill_size
                    side_ss.cost_paid += fill_size * fill_price
                    rebate = fill_size * poly_maker_rebate_per_share(
                        fill_price, fee_rate=FEE_RATE
                    )
                    side_ss.rebate_income += rebate
                    side_ss.open_bid_size_remaining -= fill_size
                    n_maker_fills[oc] += 1
                    if side_ss.open_bid_size_remaining < 0.001:
                        side_ss.open_bid_price = None
                        side_ss.open_bid_size_remaining = 0.0
                        side_ss.open_bid_queue_ahead = 0.0

        # Merge trigger
        pairs = min(ss_up.inv, ss_dn.inv)
        if pairs >= cfg.merge_threshold_pairs:
            merge_n = pairs
            ss_up.inv -= merge_n
            ss_dn.inv -= merge_n
            cash_recovered += merge_n * 1.0
            n_merges += 1
            pairs_merged += merge_n

    # End-of-slug
    # Force merge any remaining paired
    pairs = min(ss_up.inv, ss_dn.inv)
    if pairs > 0:
        ss_up.inv -= pairs
        ss_dn.inv -= pairs
        cash_recovered += pairs * 1.0
        n_merges += 1
        pairs_merged += pairs

    # Redeem leftover on winning side, lose leftover on losing side
    redeemed = 0.0
    burned = 0.0
    if outcome_truth == "Up":
        if ss_up.inv > 0:
            redeemed = ss_up.inv * 1.0
            cash_recovered += redeemed
        if ss_dn.inv > 0:
            burned = ss_dn.cost_paid * (ss_dn.inv / max(ss_dn.inv, 1))  # cost of unredeemed
    elif outcome_truth == "Down":
        if ss_dn.inv > 0:
            redeemed = ss_dn.inv * 1.0
            cash_recovered += redeemed
        if ss_up.inv > 0:
            burned = ss_up.cost_paid * (ss_up.inv / max(ss_up.inv, 1))

    total_cost = ss_up.cost_paid + ss_dn.cost_paid
    total_rebates = ss_up.rebate_income + ss_dn.rebate_income
    total_fees = ss_up.taker_fees + ss_dn.taker_fees
    pnl = cash_recovered + total_rebates - total_cost - total_fees

    return {
        "inv_up": ss_up.inv,
        "inv_dn": ss_dn.inv,
        "cost": total_cost,
        "rebates": total_rebates,
        "taker_fees": total_fees,
        "cash_recovered": cash_recovered,
        "leftover_redeemed_usd": redeemed,
        "leftover_burned_usd": burned,  # cost of shares on losing side at slug close
        "pnl": pnl,
        "n_merges": n_merges,
        "pairs_merged": pairs_merged,
        "n_maker_fills_up": n_maker_fills["Up"],
        "n_maker_fills_dn": n_maker_fills["Down"],
        "n_taker_buys_up": n_taker_buys["Up"],
        "n_taker_buys_dn": n_taker_buys["Down"],
    }


def run_slug(slug: str, outcome_truth: str,
              window_start_us: int, window_end_us: int,
              cvd_threshold: float = 0.0,
              no_cvd: bool = False,
              max_pair_cost: float = 0.97) -> SlugResult | None:
    """Run both strategies on one slug."""
    # Slot start = slug suffix in seconds
    try:
        slot_start_us = int(slug.rsplit("-", 1)[1]) * 1_000_000
    except Exception:
        return None
    slot_end_us = slot_start_us + 300 * 1_000_000  # 5m slug

    if not (window_start_us <= slot_start_us <= window_end_us):
        return None

    l25 = load_slug_l25(L25_BASELINE, slug)
    if not l25 or "Up" not in l25 or "Down" not in l25:
        return None
    trades = load_slug_trades(slug)
    # OK even if no trades

    res_accm = simulate_slug(slug, outcome_truth, l25, trades,
                              slot_start_us, slot_end_us, use_taker=False)
    res_accpc = simulate_slug(slug, outcome_truth, l25, trades,
                                slot_start_us, slot_end_us, use_taker=True,
                                cvd_threshold=cvd_threshold,
                                no_cvd=no_cvd,
                                max_pair_cost=max_pair_cost)
    if res_accm.get("empty") or res_accpc.get("empty"):
        return None

    span = (slot_end_us - slot_start_us) / 1_000_000
    n_l25 = sum(len(v["ts"]) for v in l25.values())
    n_tr = sum(len(v) for v in trades.values()) if trades else 0

    return SlugResult(
        slug=slug, outcome_truth=outcome_truth,
        n_events=n_l25 + n_tr, n_l25=n_l25, n_trades=n_tr, span_s=span,
        accm_inv_up=res_accm["inv_up"],
        accm_inv_dn=res_accm["inv_dn"],
        accm_cost=res_accm["cost"],
        accm_rebates=res_accm["rebates"],
        accm_taker_fees=res_accm["taker_fees"],
        accm_cash_recovered=res_accm["cash_recovered"],
        accm_leftover_redeemed_usd=res_accm.get("leftover_redeemed_usd", 0),
        accm_leftover_burned_usd=res_accm.get("leftover_burned_usd", 0),
        accm_pnl=res_accm["pnl"],
        accm_n_merges=res_accm["n_merges"],
        accm_pairs_merged=res_accm["pairs_merged"],
        accm_n_maker_fills_up=res_accm["n_maker_fills_up"],
        accm_n_maker_fills_dn=res_accm["n_maker_fills_dn"],
        accm_n_taker_buys_up=res_accm["n_taker_buys_up"],
        accm_n_taker_buys_dn=res_accm["n_taker_buys_dn"],
        accpc_inv_up=res_accpc["inv_up"],
        accpc_inv_dn=res_accpc["inv_dn"],
        accpc_cost=res_accpc["cost"],
        accpc_rebates=res_accpc["rebates"],
        accpc_taker_fees=res_accpc["taker_fees"],
        accpc_cash_recovered=res_accpc["cash_recovered"],
        accpc_leftover_redeemed_usd=res_accpc.get("leftover_redeemed_usd", 0),
        accpc_leftover_burned_usd=res_accpc.get("leftover_burned_usd", 0),
        accpc_pnl=res_accpc["pnl"],
        accpc_n_merges=res_accpc["n_merges"],
        accpc_pairs_merged=res_accpc["pairs_merged"],
        accpc_n_maker_fills_up=res_accpc["n_maker_fills_up"],
        accpc_n_maker_fills_dn=res_accpc["n_maker_fills_dn"],
        accpc_n_taker_buys_up=res_accpc["n_taker_buys_up"],
        accpc_n_taker_buys_dn=res_accpc["n_taker_buys_dn"],
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-slugs", type=int, default=50,
                     help="Number of BTC 5m slugs to backtest")
    ap.add_argument("--start-utc", type=str, default="2026-04-24",
                     help="Start date (UTC) for slug selection")
    ap.add_argument("--end-utc", type=str, default="2026-05-05",
                     help="End date (UTC) for slug selection")
    ap.add_argument("--cvd-threshold", type=float, default=0.0,
                     help="CVD filter threshold for ACC-PC (lower = more permissive)")
    ap.add_argument("--no-cvd", action="store_true",
                     help="Disable CVD filter for ACC-PC")
    ap.add_argument("--max-pair-cost", type=float, default=0.97,
                     help="ACC-PC max pair cost threshold")
    args = ap.parse_args()

    # Convert dates → us
    t_start_us = int(pd.Timestamp(args.start_utc, tz="UTC").timestamp()) * 1_000_000
    t_end_us   = int(pd.Timestamp(args.end_utc, tz="UTC").timestamp()) * 1_000_000

    print(f"Window: {args.start_utc} → {args.end_utc}")
    print(f"Looking for BTC 5m slugs (max {args.n_slugs})...")
    slugs = list_btc_5m_slugs(t_start_us, t_end_us, limit=args.n_slugs)
    print(f"Selected {len(slugs)} slugs.")

    results: list[SlugResult] = []
    t0 = time.time()
    for i, (slug, outcome) in enumerate(slugs):
        t_slug = time.time()
        try:
            r = run_slug(slug, outcome, t_start_us, t_end_us,
                          cvd_threshold=args.cvd_threshold,
                          no_cvd=args.no_cvd,
                          max_pair_cost=args.max_pair_cost)
        except Exception as e:
            print(f"  [{i+1}/{len(slugs)}] {slug}  ERROR: {e}")
            continue
        if r is None:
            print(f"  [{i+1}/{len(slugs)}] {slug}  SKIP (no data)")
            continue
        dt = (time.time() - t_slug) * 1000
        results.append(r)
        print(f"  [{i+1}/{len(slugs)}] {slug} {outcome:<4} | "
              f"ACC-M ${r.accm_pnl:+.4f} ({r.accm_n_maker_fills_up}+{r.accm_n_maker_fills_dn}f) "
              f"| ACC-PC ${r.accpc_pnl:+.4f} ({r.accpc_n_taker_buys_up}+{r.accpc_n_taker_buys_dn}t)  "
              f"diff ${r.accpc_pnl - r.accm_pnl:+.4f}  {dt:.0f}ms",
              flush=True)
        gc.collect()

    if not results:
        print("No results.")
        return

    # Aggregate
    df = pd.DataFrame([r.__dict__ for r in results])
    df["pnl_diff"] = df["accpc_pnl"] - df["accm_pnl"]
    df["accm_total_buys"] = df["accm_n_maker_fills_up"] + df["accm_n_maker_fills_dn"]
    df["accpc_total_buys"] = (
        df["accpc_n_maker_fills_up"] + df["accpc_n_maker_fills_dn"] +
        df["accpc_n_taker_buys_up"] + df["accpc_n_taker_buys_dn"]
    )

    df.to_csv(OUT_DIR / "_acc_pc_results.csv", index=False)

    # Leftover loss = burned cost on losing side at slug close (before redeem)
    summary = {
        "n_slugs": len(df),
        "config": {
            "cvd_threshold": args.cvd_threshold,
            "no_cvd": args.no_cvd,
            "max_pair_cost": args.max_pair_cost,
        },
        "accm": {
            "mean_pnl_per_slug": float(df.accm_pnl.mean()),
            "median_pnl_per_slug": float(df.accm_pnl.median()),
            "sum_pnl": float(df.accm_pnl.sum()),
            "pct_profitable": float((df.accm_pnl > 0).mean() * 100),
            "mean_fills_per_slug": float(df.accm_total_buys.mean()),
            "mean_merges_per_slug": float(df.accm_n_merges.mean()),
            "mean_pairs_merged": float(df.accm_pairs_merged.mean()),
            "mean_cost": float(df.accm_cost.mean()),
            "mean_rebates": float(df.accm_rebates.mean()),
            "mean_cash_recovered": float(df.accm_cash_recovered.mean()),
            "mean_leftover_redeemed_usd": float(df.accm_leftover_redeemed_usd.mean()),
            "mean_leftover_burned_usd": float(df.accm_leftover_burned_usd.mean()),
        },
        "accpc": {
            "mean_pnl_per_slug": float(df.accpc_pnl.mean()),
            "median_pnl_per_slug": float(df.accpc_pnl.median()),
            "sum_pnl": float(df.accpc_pnl.sum()),
            "pct_profitable": float((df.accpc_pnl > 0).mean() * 100),
            "mean_fills_per_slug": float(df.accpc_total_buys.mean()),
            "mean_merges_per_slug": float(df.accpc_n_merges.mean()),
            "mean_taker_buys_per_slug": float(
                (df.accpc_n_taker_buys_up + df.accpc_n_taker_buys_dn).mean()
            ),
            "n_slugs_with_taker_fire": int(
                ((df.accpc_n_taker_buys_up + df.accpc_n_taker_buys_dn) > 0).sum()
            ),
            "mean_pairs_merged": float(df.accpc_pairs_merged.mean()),
            "mean_cost": float(df.accpc_cost.mean()),
            "mean_rebates": float(df.accpc_rebates.mean()),
            "mean_cash_recovered": float(df.accpc_cash_recovered.mean()),
            "mean_leftover_redeemed_usd": float(df.accpc_leftover_redeemed_usd.mean()),
            "mean_leftover_burned_usd": float(df.accpc_leftover_burned_usd.mean()),
            "mean_taker_fees": float(df.accpc_taker_fees.mean()),
        },
        "diff": {
            "mean_pnl_diff": float(df.pnl_diff.mean()),
            "median_pnl_diff": float(df.pnl_diff.median()),
            "pct_slugs_accpc_better": float((df.pnl_diff > 0).mean() * 100),
            "pct_slugs_accpc_same": float((df.pnl_diff.abs() < 0.001).mean() * 100),
            "pct_slugs_accpc_worse": float((df.pnl_diff < -0.001).mean() * 100),
        },
        "total_runtime_s": time.time() - t0,
    }
    (OUT_DIR / "_acc_pc_summary.json").write_text(json.dumps(summary, indent=2))

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
