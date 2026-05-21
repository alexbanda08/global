"""
book_filters.py — backtest realism filters stolen from PMXT.

Stolen from `evan-kolberg/prediction-market-backtesting` v4.1-alpha
`build_replay_experiment(..., min_book_events=25, probability_window=256)`.

## Why this matters

Markets with very few book updates over the prediction window produce
**artificially good backtest fills**: a single deep snapshot mid-window gets
treated as live liquidity for the entire 5/15 minute period, but in reality
that book was stale and the actual fillable depth was much smaller.

PMXT filters out markets with `< 25` book events in the replay window before
running any strategy on them. We adopt the same threshold.

## Usage

```python
from strategy_lab.book_filters import (
    count_book_events,
    filter_by_min_book_events,
)

# Pre-filter a universe of slugs
keep_slugs = filter_by_min_book_events(
    slugs=df.slug.tolist(),
    asset="btc",
    window_start_us=df.ws_s.values * 1_000_000,
    window_end_us=df.slot_end_us.values,
    min_events=25,
)
```
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_MIN_BOOK_EVENTS: int = 25       # PMXT's default
DEFAULT_PROBABILITY_WINDOW: int = 256   # PMXT's default; rolling window for prob estimates


def count_book_events(
    book_loader_output: dict,
    slug: str,
    outcome: str,
    window_start_us: int,
    window_end_us: int,
) -> int:
    """Count L25 book snapshots inside [window_start_us, window_end_us] for a
    (slug, outcome) pair from `load_orderbook_l25_streaming` output."""
    key = (slug, outcome)
    rec = book_loader_output.get(key)
    if rec is None:
        return 0
    ts_us = rec[0]   # tuple (ts_us[N], ap[N,25], asz[N,25], bp[N,25], bsz[N,25])
    if len(ts_us) == 0:
        return 0
    mask = (ts_us >= int(window_start_us)) & (ts_us <= int(window_end_us))
    return int(mask.sum())


def filter_by_min_book_events(
    df: pd.DataFrame,
    books: dict,
    *,
    slug_col: str = "slug",
    window_start_col: str = "ws_s",
    window_end_col: str = "slot_end_us",
    min_events: int = DEFAULT_MIN_BOOK_EVENTS,
    outcome_col: str | None = None,
) -> pd.DataFrame:
    """Drop rows with fewer than `min_events` book updates in the window.

    Required columns:
      - slug                  (str)
      - ws_s                  (int seconds — multiplied by 1e6 internally)
      - slot_end_us           (int microseconds)
      - outcome OR outcome_col (optional; if None, takes max across Up+Down)

    Returns a copy with rows passing the filter.
    """
    out = df.copy()
    out["_n_events"] = 0
    win_start_us = (out[window_start_col].astype("int64") * 1_000_000).values
    win_end_us = out[window_end_col].astype("int64").values

    for i, slug in enumerate(out[slug_col].astype(str).values):
        if outcome_col is not None:
            n = count_book_events(books, slug, str(out.iloc[i][outcome_col]),
                                  int(win_start_us[i]), int(win_end_us[i]))
        else:
            up = count_book_events(books, slug, "Up",
                                   int(win_start_us[i]), int(win_end_us[i]))
            down = count_book_events(books, slug, "Down",
                                     int(win_start_us[i]), int(win_end_us[i]))
            n = max(up, down)
        out.iat[i, out.columns.get_loc("_n_events")] = n

    kept = out[out["_n_events"] >= int(min_events)].copy()
    print(f"book-events filter: kept {len(kept)}/{len(out)} rows "
          f"(min={min_events}, median_events={int(out['_n_events'].median())})")
    return kept
