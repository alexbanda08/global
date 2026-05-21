"""
Strategy E — L25 book microstructure (top-5 imbalance + mid drift + slope).

Tests whether top-5 bid/ask imbalance on the Up-side book predicts settlement.
5 setups x 4 cutoffs x {spread filter on/off} sweep, per-asset reporting.

Outputs:
  - per-setup per-asset CSV/markdown summary
  - 3 example trades demonstrating no-lookahead (book_ts < entry_us)
  - special focus on late-entry 15m markets

Run:  py -3 -X utf8 strategy_lab/discovery_2026_05_16/strat_E_book_micro.py
"""
from __future__ import annotations
import sys
import time
import json
import gc
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

from harness import (  # type: ignore
    NOTIONAL, FEE_RATE, SPREAD_FILTER, WINDOW_S,
    get_klines, hold_pnl_no_book, walk_asks, load_book_subset,
)
from load import (  # type: ignore
    load_resolutions, asof_strict, slug_to_ws_s,
)

OUT_DIR = HERE
EXAMPLES = []   # collected proof-of-no-lookahead samples


# ---------------------------------------------------------------------------
# Feature computation
# ---------------------------------------------------------------------------

def _book_at(books: dict, slug: str, side: str, ts_us: int):
    key = (slug, side)
    if key not in books:
        return None
    ts, ap, asz, bp, bsz = books[key]
    i = int(np.searchsorted(ts, ts_us, side="right") - 1)
    if i < 0:
        return None
    return ts[i], ap[i], asz[i], bp[i], bsz[i]


def top5_imbalance(bsz_top5: np.ndarray, asz_top5: np.ndarray) -> float:
    b = float(np.nansum(bsz_top5))
    a = float(np.nansum(asz_top5))
    tot = a + b
    if tot <= 0:
        return np.nan
    return b / tot


def mid_price(ap0: float, bp0: float) -> float:
    if not (np.isfinite(ap0) and np.isfinite(bp0)):
        return np.nan
    return 0.5 * (ap0 + bp0)


def slope_impact(prices: np.ndarray, sizes: np.ndarray, d_small: float, d_large: float):
    """Return (vwap_small - vwap_large)  i.e. the price IMPACT going from $small to $large.
    Negative-ish if book is flat (impact small); large positive when book is sparse.
    Returns nan if cannot walk to d_large.
    """
    vw_s, _, _, under_s = walk_asks(prices, sizes, d_small)
    vw_l, _, _, under_l = walk_asks(prices, sizes, d_large)
    if under_s or under_l or not np.isfinite(vw_s) or not np.isfinite(vw_l):
        return np.nan
    return vw_l - vw_s   # >0 means buying more pushed price up = book sparse


def compute_features_for_market(
    books: dict, slug: str, entry_us: int, side: str = "Up",
):
    """Return dict with features at entry_us using Up-side book.
       side controls which outcome's book to read.
    """
    snap = _book_at(books, slug, side, entry_us)
    if snap is None:
        return None
    ts_now, ap, asz, bp, bsz = snap
    # Top-5 imbalance
    imb = top5_imbalance(bsz[:5], asz[:5])
    # Mid now
    m_now = mid_price(ap[0], bp[0])
    # Mid 30s ago
    snap_30 = _book_at(books, slug, side, entry_us - 30_000_000)
    if snap_30 is None:
        m_30 = np.nan
    else:
        _, ap30, _, bp30, _ = snap_30
        m_30 = mid_price(ap30[0], bp30[0])
    drift_30s = (m_now - m_30) if (np.isfinite(m_now) and np.isfinite(m_30)) else np.nan
    # Slope
    sl = slope_impact(ap, asz, 100.0, 1000.0)
    # Spread
    sp = (ap[0] - bp[0]) if (np.isfinite(ap[0]) and np.isfinite(bp[0])) else np.nan
    return {
        "book_ts_us": int(ts_now),
        "imb_up": float(imb),
        "mid_now": float(m_now),
        "mid_30s_ago": float(m_30),
        "drift_30s": float(drift_30s),
        "slope_100_1000": float(sl),
        "spread": float(sp),
        "ap0": float(ap[0]) if np.isfinite(ap[0]) else np.nan,
        "bp0": float(bp[0]) if np.isfinite(bp[0]) else np.nan,
    }


# ---------------------------------------------------------------------------
# Universe + entry-us computation per setup
# ---------------------------------------------------------------------------

def universe(asset: str, tf: str, max_markets: int | None = None) -> pd.DataFrame:
    res = load_resolutions(assets=[asset], timeframes=[tf])
    res = res.dropna(subset=["outcome"]).reset_index(drop=True)
    # Filter to markets where L25 likely exists (Apr 22 onward).
    cutoff_us = int(pd.Timestamp("2026-04-22", tz="UTC").timestamp() * 1_000_000)
    res = res[res.slot_start_us >= cutoff_us].copy()
    if max_markets is not None and len(res) > max_markets:
        # Spread sample uniformly across time
        idx = np.linspace(0, len(res) - 1, max_markets).astype(int)
        res = res.iloc[idx].reset_index(drop=True)
    return res


def setup_entries(res: pd.DataFrame, setup: str) -> np.ndarray:
    """Return array of entry_us for each row in res, per setup definition."""
    if setup == "1_5m_ws120":
        return np.array([(slug_to_ws_s(s, "5m") + 120) * 1_000_000
                         for s in res.slug.values], dtype=np.int64)
    if setup == "2_5m_late":
        return (res.slot_end_us.values - 60_000_000).astype(np.int64)
    if setup == "3_15m_late60":
        return (res.slot_end_us.values - 60_000_000).astype(np.int64)
    if setup == "4_15m_late180":
        return (res.slot_end_us.values - 180_000_000).astype(np.int64)
    if setup == "5_5m_combined":
        return np.array([(slug_to_ws_s(s, "5m") + 120) * 1_000_000
                         for s in res.slug.values], dtype=np.int64)
    raise ValueError(setup)


SETUP_TF = {
    "1_5m_ws120":   "5m",
    "2_5m_late":    "5m",
    "3_15m_late60": "15m",
    "4_15m_late180":"15m",
    "5_5m_combined":"5m",
}


def signal_from_imbalance(imb: float, cutoff: float) -> str:
    if not np.isfinite(imb):
        return "SKIP"
    hi = cutoff
    lo = 1.0 - cutoff
    if imb > hi:
        return "UP"
    if imb < lo:
        return "DOWN"
    return "SKIP"


def signal_combined(imb: float, drift: float, cutoff: float) -> str:
    if not np.isfinite(imb) or not np.isfinite(drift):
        return "SKIP"
    hi = cutoff
    lo = 1.0 - cutoff
    if imb > hi and drift > 0:
        return "UP"
    if imb < lo and drift < 0:
        return "DOWN"
    return "SKIP"


# ---------------------------------------------------------------------------
# Feature builder per (asset, tf, setup) — batched book loads
# ---------------------------------------------------------------------------

BATCH_SIZE = 500


def build_features(asset: str, tf: str, setup: str, max_markets: int | None = None) -> pd.DataFrame:
    """Compute features at the setup's entry_us for every market.
    Returns DataFrame with: slug, ticker, timeframe, slot_start_us, slot_end_us,
                            outcome, entry_us, imb_up, drift_30s, slope, spread, ap0, bp0, book_ts_us.
    """
    res = universe(asset, tf, max_markets=max_markets)
    if len(res) == 0:
        return pd.DataFrame()
    entries = setup_entries(res, setup)
    res = res.copy()
    res["entry_us"] = entries

    out_rows = []
    n = len(res)
    n_batches = (n + BATCH_SIZE - 1) // BATCH_SIZE
    for bi in range(n_batches):
        lo, hi = bi * BATCH_SIZE, min((bi + 1) * BATCH_SIZE, n)
        sub = res.iloc[lo:hi]
        slugs = set(sub.slug.values)
        t0 = time.time()
        books = load_book_subset(asset, slugs)
        for _, row in sub.iterrows():
            feats = compute_features_for_market(books, row.slug, int(row.entry_us), side="Up")
            if feats is None:
                continue
            out_rows.append({
                "slug": row.slug,
                "ticker": row.ticker,
                "timeframe": row.timeframe,
                "slot_start_us": int(row.slot_start_us),
                "slot_end_us": int(row.slot_end_us),
                "outcome": row.outcome,
                "entry_us": int(row.entry_us),
                **feats,
            })
        del books
        gc.collect()
        print(f"  [{asset} {tf} {setup}] batch {bi+1}/{n_batches}  "
              f"slugs={len(slugs)}  +{len(out_rows)}rows  {time.time()-t0:.1f}s",
              flush=True)
    return pd.DataFrame(out_rows)


# ---------------------------------------------------------------------------
# Backtest a feature-frame with a signal function
# ---------------------------------------------------------------------------

def backtest_signal(feat: pd.DataFrame, setup: str, cutoff: float, spread_filter: bool,
                    flat_entry: float = 0.5) -> dict:
    if len(feat) == 0:
        return {"n_fires": 0, "hit_rate": np.nan, "pnl_total": np.nan,
                "n_eval": 0, "fire_rate": np.nan}
    df = feat.copy()
    if spread_filter:
        sp_max = df.ticker.map(SPREAD_FILTER).fillna(0.02)
        df = df[df["spread"].fillna(1.0) <= sp_max]
    if setup == "5_5m_combined":
        df["signal"] = [signal_combined(i, d, cutoff)
                        for i, d in zip(df["imb_up"], df["drift_30s"])]
    else:
        df["signal"] = [signal_from_imbalance(i, cutoff) for i in df["imb_up"]]
    fired = df[df["signal"].isin(("UP", "DOWN"))].copy()
    n_eval = len(df)
    n_fires = len(fired)
    if n_fires == 0:
        return {"n_fires": 0, "hit_rate": np.nan, "pnl_total": 0.0,
                "n_eval": int(n_eval), "fire_rate": 0.0}
    fired["won"] = (fired["signal"].str.upper() == fired["outcome"].str.upper()).astype(int)
    hit = float(fired["won"].mean())
    fired["pnl"] = fired.apply(
        lambda r: hold_pnl_no_book(r["signal"], r["outcome"], flat_entry), axis=1
    )
    pnl = float(fired["pnl"].sum())
    return {
        "n_fires": int(n_fires),
        "n_eval": int(n_eval),
        "fire_rate": n_fires / n_eval,
        "hit_rate": hit,
        "pnl_total": pnl,
        "_fired": fired,
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

ASSETS = ["BTC", "ETH", "SOL"]
SETUPS = ["1_5m_ws120", "2_5m_late", "3_15m_late60", "4_15m_late180", "5_5m_combined"]
CUTOFFS = [0.55, 0.60, 0.65, 0.70]


def main(max_markets_per_asset: int = 2000):
    all_results = []
    feature_cache: dict[tuple[str, str], pd.DataFrame] = {}

    for setup in SETUPS:
        tf = SETUP_TF[setup]
        for asset in ASSETS:
            key = (asset, setup)
            t0 = time.time()
            print(f"\n=== Build features: {asset} {tf} setup={setup} ===", flush=True)
            feat = build_features(asset, tf, setup, max_markets=max_markets_per_asset)
            print(f"   built {len(feat)} feature rows in {time.time()-t0:.0f}s", flush=True)
            if len(feat) == 0:
                continue
            feature_cache[key] = feat
            # Collect 1-2 no-lookahead samples from this (asset, setup) once
            if len(EXAMPLES) < 6 and "book_ts_us" in feat.columns:
                # pick first row where entry_us > book_ts_us (which should ALL be)
                ok = feat[feat["book_ts_us"] < feat["entry_us"]].head(1)
                if len(ok):
                    r = ok.iloc[0]
                    EXAMPLES.append({
                        "asset": asset, "setup": setup, "slug": r["slug"],
                        "book_ts_us": int(r["book_ts_us"]),
                        "entry_us": int(r["entry_us"]),
                        "delta_s": (r["entry_us"] - r["book_ts_us"]) / 1e6,
                        "imb_up": float(r["imb_up"]),
                        "outcome": r["outcome"],
                    })

            for cutoff in CUTOFFS:
                for sp_flag in (False, True):
                    r = backtest_signal(feat, setup, cutoff, sp_flag)
                    r_clean = {k: v for k, v in r.items() if not k.startswith("_")}
                    all_results.append({
                        "asset": asset, "tf": tf, "setup": setup,
                        "cutoff": cutoff, "spread_filter": sp_flag,
                        **r_clean,
                    })

    df_res = pd.DataFrame(all_results)
    out_csv = OUT_DIR / "strat_E_results.csv"
    df_res.to_csv(out_csv, index=False)
    print(f"\nWrote {out_csv}")

    # No-lookahead examples
    ex_path = OUT_DIR / "strat_E_no_lookahead_examples.json"
    with open(ex_path, "w", encoding="utf-8") as f:
        json.dump(EXAMPLES, f, indent=2, default=str)
    print(f"Wrote {ex_path}")
    return df_res, feature_cache


if __name__ == "__main__":
    df_res, feature_cache = main(max_markets_per_asset=2000)
    # Top configs preview
    qual = df_res[df_res["n_fires"] >= 200].copy()
    if len(qual):
        qual = qual.sort_values("pnl_total", ascending=False).head(15)
        print("\nTop configs (n_fires >= 200, by pnl@0.5):")
        print(qual.to_string(index=False))
    else:
        print("\nNo configs reached n_fires>=200 threshold.")
