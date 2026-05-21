"""
Per-cell aggregation. A "cell" = unique (sleeve_id, signal, hour_bucket, dow_group).
Each cell's per-event PnL for {KEEP, INVERT, SKIP} is precomputed.

Used by the GA: each cell is a gene with 3-way categorical action.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class Cell:
    cell_id: str
    sleeve_id: str
    signal: str
    hour_bucket: str
    dow_group: str
    asset: str
    family: str
    # Per-action stats (computed from events in this cell):
    n: int
    win_same: float
    pnl_same: float
    pnl_invert: float
    pnl_skip: float = 0.0


def build_cell_index(events: pd.DataFrame, min_n: int = 20) -> tuple[list[Cell], dict]:
    """
    Aggregate events to cells. Drops cells with n < min_n.
    Returns (cells, events_by_cell) where events_by_cell maps cell_id -> event idx list.
    """
    grp = events.groupby("cell_id")
    cells = []
    events_by_cell = {}
    for cid, g in grp:
        if len(g) < min_n:
            continue
        cell = Cell(
            cell_id=cid,
            sleeve_id=g.sleeve_id.iloc[0],
            signal=g.signal.iloc[0],
            hour_bucket=g.hour_bucket.iloc[0],
            dow_group=g.dow_group.iloc[0],
            asset=g.asset.iloc[0],
            family=g.family.iloc[0],
            n=len(g),
            win_same=float(g.won.mean()),
            pnl_same=float(g.pnl_same.sum()),
            pnl_invert=float(g.pnl_invert.sum()),
        )
        cells.append(cell)
        events_by_cell[cid] = g.index.tolist()
    return cells, events_by_cell


def cell_baseline(cells: list[Cell]) -> dict:
    """
    Baseline: for each cell pick max(pnl_same, pnl_invert, pnl_skip).
    Returns per-action totals + the chosen action per cell.
    """
    totals = {"KEEP": 0.0, "INVERT": 0.0, "SKIP": 0.0, "BEST": 0.0}
    per_cell_choice = {}
    n_chosen_keep = n_chosen_invert = n_chosen_skip = 0
    for c in cells:
        options = {"KEEP": c.pnl_same, "INVERT": c.pnl_invert, "SKIP": 0.0}
        best_action = max(options, key=options.get)
        totals["KEEP"] += c.pnl_same
        totals["INVERT"] += c.pnl_invert
        totals["BEST"] += options[best_action]
        per_cell_choice[c.cell_id] = best_action
        if best_action == "KEEP": n_chosen_keep += 1
        elif best_action == "INVERT": n_chosen_invert += 1
        else: n_chosen_skip += 1
    totals["n_cells"] = len(cells)
    totals["n_keep"] = n_chosen_keep
    totals["n_invert"] = n_chosen_invert
    totals["n_skip"] = n_chosen_skip
    return {"totals": totals, "per_cell_choice": per_cell_choice}
