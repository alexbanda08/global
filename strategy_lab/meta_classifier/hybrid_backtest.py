"""Backtest harness for Range-Filter-DW + Traders-Reality hybrid sleeves.

Pure-function harness so callers (notebooks, sweep scripts) can build any
`entry_rule(row) -> "UP" | "DOWN" | None` and re-run instantly on the cached
fire universe + feature panel.

Stack contract:
  - `fire_universe` = output of `hybrid_fire_universe_build.py` (one row per
    (asset, slug, fire_offset_s)). Pre-computed L25 fills for both UP and DOWN
    legs at `engine_v2.LegacyConfig`. We DO NOT re-walk books here.
  - `feature_panel` = joined RF + TR + TA + F7-RSI + Markov-M1V features at
    `fire_us`. Must contain at minimum the slug/fire_us pair so we can merge.
  - `entry_rule(row)` runs row-by-row. Return None to skip the fire.
  - `config` = `engine_v2.LegacyConfig()` (2%-on-profit-only fee — matches
    production behavior per the 2026-05-22 reconciliation, see CLAUDE.md).

Conventions: ws_s anchor on previous slot; outcome from chainlink (canonical).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

# These are kept lightweight imports — the harness shouldn't pull in book
# streamers etc. for an in-memory backtest.
from engine_v2 import LegacyConfig, EngineConfig  # noqa: E402


# ---------------------------------------------------------------------------
# Core simulation primitive — uses pre-computed fills from the fire universe.
# ---------------------------------------------------------------------------

def _pnl_legacy_2pct_on_profit(shares: float, vwap: float, won: bool,
                                fee_pct: float = 0.02) -> float:
    """Hold-to-settle PnL with legacy 2%-on-profit fee model.

    Mirrors `engine_v2.hold_pnl` for cfg.fee_model='legacy_2pct_on_profit',
    but operates on (shares, vwap) directly so we don't need to round-trip
    through a fill dict (the fire universe persists shares + vwap, not the
    full L25 snapshot).
    """
    usd_in = float(shares) * float(vwap)
    if won:
        gross = float(shares) * 1.0 - usd_in
        if gross > 0:
            return gross * (1.0 - fee_pct)
        return gross
    return -usd_in


def run_hybrid_backtest(
    fire_universe: pd.DataFrame,
    feature_panel: pd.DataFrame | None,
    entry_rule: Callable[[pd.Series], str | None],
    config: EngineConfig | None = None,
    name: str = "hybrid",
    join_keys: tuple[str, ...] = ("slug", "fire_us"),
) -> dict:
    """Run an entry_rule against the cached fire universe.

    fire_universe must have, per row:
      asset, slug, fire_offset_s, ws_s, slot_start_us, slot_end_us, fire_us,
      strike_price, settle_price, outcome ('Up'|'Down'),
      up_vwap, up_shares, up_usd, up_ask0, up_bid0, up_fill_ok,
      dn_vwap, dn_shares, dn_usd, dn_ask0, dn_bid0, dn_fill_ok,
      mag_ratio (|ret_2m_at_ws| / threshold), vwap_since_open_bps

    feature_panel is OPTIONAL — if provided, joined on join_keys (default
    slug + fire_us). entry_rule sees the merged row.

    Returns dict:
      {
        "name": str,
        "per_fire": pd.DataFrame,   # one row per FIRED trade
        "summary": dict,            # n, wins, WR, sum_pnl, dollar_per_trade,
                                    # max_DD, max_loss_streak, sharpe_per_day
        "skipped_no_signal": int,
        "skipped_no_fill": int,
      }
    """
    if config is None:
        config = LegacyConfig()
    if config.fee_model != "legacy_2pct_on_profit":
        # We intentionally only support legacy in this harness, since the
        # fire universe persists VWAP/shares without entry-fee accounting.
        # For poly_taker_curve, use engine_v2.hold_pnl with fee_in directly.
        raise NotImplementedError(
            f"hybrid_backtest only supports legacy_2pct_on_profit currently; "
            f"got {config.fee_model!r}. Add fee_in column to fire universe to extend."
        )

    df = fire_universe
    if feature_panel is not None and len(feature_panel):
        keys = list(join_keys)
        df = df.merge(feature_panel, on=keys, how="left", suffixes=("", "_feat"))

    rows = []
    skipped_no_signal = 0
    skipped_no_fill = 0

    # Vectorize where possible — but entry_rule is user-supplied so we iterate.
    for r in df.itertuples(index=False):
        rd = r._asdict()
        # Quick reject if neither side filled (book missing both ways).
        up_ok = bool(rd.get("up_fill_ok", False))
        dn_ok = bool(rd.get("dn_fill_ok", False))
        if not (up_ok or dn_ok):
            skipped_no_fill += 1
            continue
        direction = entry_rule(pd.Series(rd))
        if direction is None:
            skipped_no_signal += 1
            continue
        direction = str(direction).upper()
        if direction not in ("UP", "DOWN"):
            skipped_no_signal += 1
            continue
        # Side-specific fill must be present.
        if direction == "UP" and not up_ok:
            skipped_no_fill += 1
            continue
        if direction == "DOWN" and not dn_ok:
            skipped_no_fill += 1
            continue

        if direction == "UP":
            vwap = float(rd["up_vwap"]); shares = float(rd["up_shares"])
        else:
            vwap = float(rd["dn_vwap"]); shares = float(rd["dn_shares"])

        outcome = str(rd.get("outcome", "")).title()  # 'Up'/'Down'
        won = (direction == "UP" and outcome == "Up") or \
              (direction == "DOWN" and outcome == "Down")

        pnl = _pnl_legacy_2pct_on_profit(shares, vwap, won, fee_pct=config.legacy_fee_pct)

        rows.append({
            "asset": rd.get("asset"),
            "slug": rd.get("slug"),
            "tf": rd.get("tf"),
            "ws_s": rd.get("ws_s"),
            "fire_offset_s": rd.get("fire_offset_s"),
            "fire_us": rd.get("fire_us"),
            "signal": direction,
            "outcome": outcome,
            "won": won,
            "vwap": vwap,
            "shares": shares,
            "pnl": pnl,
        })

    per_fire = pd.DataFrame(rows)
    summary = _summarize(per_fire, name=name)
    return {
        "name": name,
        "per_fire": per_fire,
        "summary": summary,
        "skipped_no_signal": int(skipped_no_signal),
        "skipped_no_fill": int(skipped_no_fill),
    }


def _summarize(per_fire: pd.DataFrame, name: str = "") -> dict:
    """Aggregate fire records → headline stats. NaN-safe on empty input."""
    n = len(per_fire)
    if n == 0:
        return {
            "name": name, "n": 0, "wins": 0, "WR": float("nan"),
            "sum_pnl": 0.0, "dollar_per_trade": float("nan"),
            "max_DD": 0.0, "max_loss_streak": 0,
            "sharpe_per_day": float("nan"), "n_days": 0,
        }
    pnl = per_fire["pnl"].astype("float64")
    wins = int((pnl > 0).sum())
    sum_pnl = float(pnl.sum())

    # max drawdown on cumulative pnl, ordered by fire_us
    sub = per_fire.sort_values("fire_us")
    cum = sub["pnl"].cumsum().values
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    max_DD = float(dd.max()) if len(dd) else 0.0

    # max consecutive loss streak (pnl <= 0)
    loss = (sub["pnl"].values <= 0).astype("int8")
    max_streak = 0; cur = 0
    for x in loss:
        if x:
            cur += 1
            if cur > max_streak: max_streak = cur
        else:
            cur = 0

    # daily sharpe (per-day pnl mean / std × sqrt(N_days)). UTC days.
    day = pd.to_datetime(sub["fire_us"], unit="us", utc=True).dt.floor("D")
    daily = sub.assign(_day=day).groupby("_day")["pnl"].sum()
    n_days = int(daily.shape[0])
    sharpe = float("nan")
    if n_days > 1:
        mu = float(daily.mean()); sig = float(daily.std(ddof=1))
        sharpe = mu / sig * math.sqrt(n_days) if sig and sig > 0 else float("nan")

    return {
        "name": name, "n": n, "wins": wins,
        "WR": wins / n,
        "sum_pnl": sum_pnl,
        "dollar_per_trade": sum_pnl / n,
        "max_DD": max_DD,
        "max_loss_streak": int(max_streak),
        "sharpe_per_day": sharpe,
        "n_days": n_days,
    }


# ---------------------------------------------------------------------------
# Walk-forward split: first N days train, last M days test, by fire_us.
# ---------------------------------------------------------------------------

def walk_forward_split(
    df: pd.DataFrame,
    train_days: int = 20,
    test_days: int = 8,
    by: str = "fire_us",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split df into (train, test) by UTC day on column `by` (microseconds).

    The split uses the earliest day in df as day 0:
      train = days [0, train_days)
      test  = days [train_days, train_days + test_days)

    Returns sorted copies. If `df` spans fewer days than requested, the test
    set may be empty — caller should verify with `len(test_df)`.
    """
    if by not in df.columns:
        raise KeyError(f"missing column {by!r}; got {list(df.columns)[:8]}...")
    if len(df) == 0:
        return df.copy(), df.copy()
    s = df.sort_values(by).reset_index(drop=True)
    t0_us = int(s[by].iloc[0])
    day_us = 24 * 3600 * 1_000_000
    # round t0 down to UTC day boundary
    t0_us = (t0_us // day_us) * day_us
    train_end_us = t0_us + train_days * day_us
    test_end_us = train_end_us + test_days * day_us
    train = s[s[by] < train_end_us].copy()
    test = s[(s[by] >= train_end_us) & (s[by] < test_end_us)].copy()
    return train, test


# ---------------------------------------------------------------------------
# Exhaustive AND-gate search over boolean columns.
# ---------------------------------------------------------------------------

def gate_search(
    df: pd.DataFrame,
    gate_columns: list[str],
    pnl_col: str = "pnl",
    min_n: int = 30,
    top_k: int = 20,
) -> pd.DataFrame:
    """Try every non-empty subset of `gate_columns` as an AND-conjunction.

    For each subset:
      mask = AND of (df[c] == 1 / True) for c in subset
      record n, wins, WR, sum_pnl, dollar_per_trade

    Returns the top-k subsets by sum_pnl that satisfy n >= min_n.

    `gate_columns` must be boolean-like (0/1 / True/False). Missing values are
    treated as False. With K gates we explore 2**K - 1 subsets — keep K <= 12
    or runtime explodes (4095 subsets × n_rows).
    """
    K = len(gate_columns)
    if K == 0:
        return pd.DataFrame()
    if K > 14:
        raise ValueError(f"gate_search would explore {2**K - 1} subsets; "
                          f"reduce gate_columns to <= 14 (got {K}).")

    missing = [c for c in gate_columns if c not in df.columns]
    if missing:
        raise KeyError(f"missing gate columns: {missing}")

    # cache the boolean arrays for speed
    masks = {c: df[c].fillna(False).astype(bool).values for c in gate_columns}
    pnl_arr = df[pnl_col].astype("float64").values

    rows = []
    for bits in range(1, 1 << K):
        cols = [gate_columns[i] for i in range(K) if (bits >> i) & 1]
        # AND mask
        m = masks[cols[0]].copy()
        for c in cols[1:]:
            m &= masks[c]
        n = int(m.sum())
        if n < min_n:
            continue
        sub_pnl = pnl_arr[m]
        wins = int((sub_pnl > 0).sum())
        rows.append({
            "gates": "&".join(cols),
            "k": len(cols),
            "n": n,
            "wins": wins,
            "WR": wins / n,
            "sum_pnl": float(sub_pnl.sum()),
            "dollar_per_trade": float(sub_pnl.sum() / n),
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out = out.sort_values("sum_pnl", ascending=False).head(top_k).reset_index(drop=True)
    return out


# ---------------------------------------------------------------------------
# Smoke test — confirms import-clean.
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Tiny synthetic fire universe.
    fu = pd.DataFrame([
        {"asset": "BTC", "slug": "x-5m-1778500300", "tf": "5m", "ws_s": 1778500000,
         "fire_offset_s": 60, "fire_us": (1778500300 + 60) * 1_000_000,
         "outcome": "Up",
         "up_vwap": 0.55, "up_shares": 45.0, "up_usd": 25.0, "up_fill_ok": True,
         "dn_vwap": 0.45, "dn_shares": 55.0, "dn_usd": 25.0, "dn_fill_ok": True,
         "mag_ratio": 1.4},
        {"asset": "BTC", "slug": "x-5m-1778500600", "tf": "5m", "ws_s": 1778500300,
         "fire_offset_s": 60, "fire_us": (1778500600 + 60) * 1_000_000,
         "outcome": "Down",
         "up_vwap": 0.62, "up_shares": 40.0, "up_usd": 25.0, "up_fill_ok": True,
         "dn_vwap": 0.38, "dn_shares": 65.0, "dn_usd": 25.0, "dn_fill_ok": True,
         "mag_ratio": 1.7},
    ])
    rule = lambda r: "UP" if r["mag_ratio"] > 1.5 else "DOWN"
    out = run_hybrid_backtest(fu, None, rule, name="smoke")
    print("smoke summary:", out["summary"])
    print("per_fire:")
    print(out["per_fire"])

    # walk-forward split
    tr, te = walk_forward_split(fu, train_days=1, test_days=1)
    print(f"\nwalk_forward: train={len(tr)} test={len(te)}")

    # gate search
    fu["g1"] = (fu["mag_ratio"] > 1.3).astype("int8")
    fu["g2"] = (fu["outcome"] == "Up").astype("int8")
    # we need a pnl col for the search; cheat with a constant for the smoke
    fu["pnl"] = [1.0, -2.0]
    gs = gate_search(fu, ["g1", "g2"], min_n=1, top_k=3)
    print("\ngate_search:")
    print(gs)
