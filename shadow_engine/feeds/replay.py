"""Replay feed: drives events from canonical parquets in chronological order.

Used for shadow validation by replaying historical L25 + trades + resolutions.
Emits the same events that a live WS feed would: SlugActive, L25Update,
TradePrint, OrderFill, SlugResolved.

Note: in replay mode we don't have "our" orders on the book, so we SIMULATE
fills based on incoming TradePrint events:
- If a taker SELL prints at price <= our active BID price → we get filled
  (subject to a queue-share approximation)
- If a taker BUY prints at price >= our active ASK price → fill

Useful for:
- Validating strategy logic end-to-end
- Comparing realized vs simulated decisions
- Reproducing the acc_simulator.py backtest results
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterator, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from ..base import (
    SlugActive, L25Update, L25Snapshot, TradePrint, OrderFill, SlugResolved,
    Side,
)


class ReplayFeed:
    """Iterator over events from historical data.

    Usage:
        feed = ReplayFeed(cell="btc_5m", slug_rank=(50, 150))
        for event in feed:
            # dispatch to runner
            ...
    """

    def __init__(self, cell: str, slug_rank: tuple = (50, 150),
                 n_slugs: Optional[int] = None,
                 use_full_trades: bool = True):
        """
        Args:
            cell: e.g. "btc_5m", "btc_15m"
            slug_rank: pick slugs ranked by opportunity count (start, end)
            n_slugs: max number of slugs to replay (None = use slug_rank)
            use_full_trades: load trades_polymarket for fill simulation
        """
        self.cell = cell
        self.asset = cell.split("_")[0]
        self.tf = cell.split("_")[1]
        self.slug_rank = slug_rank
        self.n_slugs = n_slugs
        self.use_full_trades = use_full_trades

        self._slugs: list[str] = []
        self._loaded = False

    def _load(self):
        """Load slug list + opportunities + trades + resolutions."""
        if self._loaded:
            return
        self._loaded = True

        from load import load_resolutions

        R = ROOT / "data" / "v4" / "canonical" / "_results"
        op = pd.read_parquet(R / f"mint_and_sell_v2_{self.cell}_2026_05_16" / "opportunities.parquet")
        res = load_resolutions(assets=[self.asset.upper()], timeframes=[self.tf])[["slug","outcome"]].drop_duplicates(subset="slug")
        op = op.merge(res, on="slug", how="inner")

        tr_path = ROOT / "data" / "v4" / "canonical" / "trades_polymarket" / f"{self.asset}.parquet"
        tr_slugs = set(pd.read_parquet(tr_path, columns=["slug"])["slug"].unique())
        op = op[op.slug.isin(tr_slugs)].reset_index(drop=True)

        # Pick slugs by opportunity count rank
        counts = op.groupby("slug").size().sort_values(ascending=False)
        picked = counts.iloc[self.slug_rank[0]:self.slug_rank[1]].index.tolist()
        if self.n_slugs:
            picked = picked[:self.n_slugs]
        self._slugs = picked

        self._op = op[op.slug.isin(picked)].sort_values("ts").reset_index(drop=True)
        self._res = res[res.slug.isin(picked)].drop_duplicates("slug").set_index("slug")

        if self.use_full_trades:
            self._trades = pd.read_parquet(
                tr_path, columns=["timestamp_us","slug","outcome","price","size","side"]
            )
            self._trades = self._trades[self._trades.slug.isin(picked)].sort_values("timestamp_us").reset_index(drop=True)
        else:
            self._trades = pd.DataFrame()

    def __iter__(self) -> Iterator:
        """Replay events in chronological order across all picked slugs."""
        self._load()

        # Strategy: process slug-by-slug (simpler than fully-interleaved global timeline).
        # For each slug:
        #   1. Emit SlugActive
        #   2. Emit L25Updates (from opportunities ticks)
        #   3. Interleave TradePrints (from trades parquet)
        #   4. Emit SlugResolved at slot_end
        # This means slugs are processed serially. For better realism, future
        # version should fully interleave by timestamp.

        for slug in self._slugs:
            slot_start_s = int(slug.rsplit("-", 1)[1])
            slot_start_us = slot_start_s * 1_000_000
            window_s = 300 if self.tf == "5m" else 900
            slot_end_us = (slot_start_s + window_s) * 1_000_000

            outcome_str = self._res.loc[slug, "outcome"]
            outcome = Side.from_str(outcome_str)

            yield SlugActive(
                slug=slug,
                asset=self.asset,
                tf=self.tf,
                slot_start_us=slot_start_us,
                slot_end_us=slot_end_us,
                condition_id=None,  # not in our cache for shadow
            )

            sub_op = self._op[self._op.slug == slug]
            if self.use_full_trades:
                sub_tr = self._trades[self._trades.slug == slug]
            else:
                sub_tr = pd.DataFrame()

            # Interleave op ticks (L25Updates) and trades (TradePrints) by ts
            op_events = [(int(r.ts), "L25", r) for r in sub_op.itertuples(index=False)]
            tr_events = []
            if len(sub_tr):
                for r in sub_tr.itertuples(index=False):
                    out = Side.from_str(r.outcome)
                    tr_events.append((int(r.timestamp_us), "TRADE",
                                       (out, float(r.price), float(r.size), r.side)))
            all_events = sorted(op_events + tr_events, key=lambda x: x[0])

            for ts_us, kind, payload in all_events:
                if kind == "L25":
                    # opportunities row has flat (bid_up, ask_up, size_up, bid_dn, ...) — build snapshots
                    r = payload
                    up_snap = L25Snapshot(
                        slug=slug, outcome=Side.UP, ts_us=ts_us,
                        ask_prices=[float(r.ask_up)], ask_sizes=[float(r.size_up)],
                        bid_prices=[float(r.bid_up)], bid_sizes=[float(r.size_up)],  # bid size proxy
                    )
                    dn_snap = L25Snapshot(
                        slug=slug, outcome=Side.DOWN, ts_us=ts_us,
                        ask_prices=[float(r.ask_dn)], ask_sizes=[float(r.size_dn)],
                        bid_prices=[float(r.bid_dn)], bid_sizes=[float(r.size_dn)],
                    )
                    yield L25Update(slug=slug, ts_us=ts_us, up=up_snap, dn=dn_snap)
                elif kind == "TRADE":
                    out, price, size, taker_side = payload
                    yield TradePrint(
                        slug=slug, outcome=out, ts_us=ts_us,
                        price=price, size=size, taker_side=taker_side,
                    )

            yield SlugResolved(slug=slug, outcome=outcome, settlement_ts_us=slot_end_us + 1)
