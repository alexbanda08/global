"""Replay feed using REAL L25 books (not opportunities.parquet ask-only).

Validates strategy logic against authentic L25 bid + ask depth, so the
fill simulator can compute proper queue-share fills.

vs ReplayFeed (replay.py):
- replay.py: uses opportunities.parquet which has size_up/size_dn = ASK size only
  (bid size proxied with ask size — inaccurate for ACC strategies)
- replay_l25.py: uses orderbook_l25/<asset>.parquet via load_orderbook_l25_streaming
  (real bid + ask + 25-level depth — accurate for ACC strategies)

Use this for validation runs after the core strategy is wired.
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
    SlugActive, L25Update, L25Snapshot, TradePrint, SlugResolved, Side,
)


class ReplayFeedL25:
    """L25-direct replay using canonical orderbook_l25 parquets."""

    def __init__(self, cell: str, slug_rank: tuple = (50, 150),
                 n_slugs: Optional[int] = None):
        self.cell = cell
        self.asset = cell.split("_")[0]
        self.tf = cell.split("_")[1]
        self.window_s = 300 if self.tf == "5m" else 900
        self.slug_rank = slug_rank
        self.n_slugs = n_slugs
        self._loaded = False
        self._slugs: list[str] = []

    def _load(self):
        if self._loaded:
            return
        self._loaded = True

        from load import load_resolutions, load_orderbook_l25_streaming

        # Pick slugs by opportunity count rank (same as ReplayFeed)
        R = ROOT / "data" / "v4" / "canonical" / "_results"
        op = pd.read_parquet(R / f"mint_and_sell_v2_{self.cell}_2026_05_16" / "opportunities.parquet")
        res = load_resolutions(assets=[self.asset.upper()], timeframes=[self.tf])[["slug","outcome"]].drop_duplicates(subset="slug")
        op = op.merge(res, on="slug", how="inner")

        tr_path = ROOT / "data" / "v4" / "canonical" / "trades_polymarket" / f"{self.asset}.parquet"
        tr_slugs = set(pd.read_parquet(tr_path, columns=["slug"])["slug"].unique())
        op = op[op.slug.isin(tr_slugs)].reset_index(drop=True)
        counts = op.groupby("slug").size().sort_values(ascending=False)
        picked = counts.iloc[self.slug_rank[0]:self.slug_rank[1]].index.tolist()
        if self.n_slugs:
            picked = picked[:self.n_slugs]
        self._slugs = picked

        self._res = res[res.slug.isin(picked)].drop_duplicates("slug").set_index("slug")

        # Load L25 books for picked slugs (subsample_1hz to control memory)
        print(f"  [replay_l25] loading L25 for {len(picked)} slugs from orderbook_l25/{self.asset}.parquet...")
        self._l25 = load_orderbook_l25_streaming(self.asset, slugs=set(picked), subsample_1hz=True)
        # _l25 is dict[(slug, outcome_str)] = (ts_arr, ap, asz, bp, bsz)
        print(f"  [replay_l25] loaded {len(self._l25)} (slug, outcome) book streams")

        # Load trades parquet
        self._trades = pd.read_parquet(
            tr_path, columns=["timestamp_us","slug","outcome","price","size","side"]
        )
        self._trades = self._trades[self._trades.slug.isin(picked)].sort_values("timestamp_us").reset_index(drop=True)
        print(f"  [replay_l25] loaded {len(self._trades):,} trades on picked slugs")

    def __iter__(self) -> Iterator:
        self._load()

        for slug in self._slugs:
            slot_start_s = int(slug.rsplit("-", 1)[1])
            slot_start_us = slot_start_s * 1_000_000
            slot_end_us = (slot_start_s + self.window_s) * 1_000_000

            outcome_str = self._res.loc[slug, "outcome"]
            outcome = Side.from_str(outcome_str)

            yield SlugActive(
                slug=slug, asset=self.asset, tf=self.tf,
                slot_start_us=slot_start_us, slot_end_us=slot_end_us,
            )

            # Build unified timeline: L25 ticks (both sides) + trades
            up_rec = self._l25.get((slug, "Up"))
            dn_rec = self._l25.get((slug, "Down"))
            if up_rec is None or dn_rec is None:
                yield SlugResolved(slug=slug, outcome=outcome, settlement_ts_us=slot_end_us + 1)
                continue

            up_ts, up_ap, up_asz, up_bp, up_bsz = up_rec
            dn_ts, dn_ap, dn_asz, dn_bp, dn_bsz = dn_rec

            # Build "pseudo-paired" L25 updates by merging the timelines (use whichever side ticked).
            # For each unique ts in either side, emit an L25Update using the most recent state for each side.
            all_ts = np.unique(np.concatenate([up_ts, dn_ts]))

            # Build index arrays for "as-of" lookup
            up_idx = np.searchsorted(up_ts, all_ts, side="right") - 1
            dn_idx = np.searchsorted(dn_ts, all_ts, side="right") - 1

            # Trades for this slug, sorted by ts
            sub_tr = self._trades[self._trades.slug == slug]

            # Interleave L25 ticks + trades
            l25_events = [(int(t), "L25", i) for i, t in enumerate(all_ts)]
            tr_events = [(int(r.timestamp_us), "TRADE",
                          (Side.from_str(r.outcome), float(r.price), float(r.size), r.side))
                         for r in sub_tr.itertuples(index=False)]
            all_events = sorted(l25_events + tr_events, key=lambda x: x[0])

            for ts_us, kind, payload in all_events:
                if kind == "L25":
                    idx = payload
                    ui = up_idx[idx]
                    di = dn_idx[idx]
                    if ui < 0 or di < 0:
                        continue   # no data yet for one side
                    up_snap = L25Snapshot(
                        slug=slug, outcome=Side.UP, ts_us=ts_us,
                        ask_prices=list(up_ap[ui]),
                        ask_sizes=list(up_asz[ui]),
                        bid_prices=list(up_bp[ui]),
                        bid_sizes=list(up_bsz[ui]),
                    )
                    dn_snap = L25Snapshot(
                        slug=slug, outcome=Side.DOWN, ts_us=ts_us,
                        ask_prices=list(dn_ap[di]),
                        ask_sizes=list(dn_asz[di]),
                        bid_prices=list(dn_bp[di]),
                        bid_sizes=list(dn_bsz[di]),
                    )
                    yield L25Update(slug=slug, ts_us=ts_us, up=up_snap, dn=dn_snap)
                else:
                    out, price, size, taker_side = payload
                    yield TradePrint(
                        slug=slug, outcome=out, ts_us=ts_us,
                        price=price, size=size, taker_side=taker_side,
                    )

            yield SlugResolved(slug=slug, outcome=outcome, settlement_ts_us=slot_end_us + 1)
