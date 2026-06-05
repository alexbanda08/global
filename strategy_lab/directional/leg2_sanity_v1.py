"""
leg2_sanity_v1.py — sanity check the leg-2 dwell=0 finding.

Two cross-checks, no event detection:
 1. Across the WHOLE window (every 1Hz grid point with both sides), what is the
    absolute MIN of (best_ask_up + best_ask_dn)? If this is never < 0.97, the
    dwell=0 result is genuine (book is simply never lockable), not a code bug.
 2. Distribution of best_ask_up + best_ask_dn (top-of-book, not walked) — show
    p1/p5/p25/p50. Confirms cross-token sum is pinned just above $1.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_resolutions, load_orderbook_l25_streaming  # noqa: E402

WIN = {"5m": 300, "15m": 900}
UNIVERSE = [("BTC", "5m"), ("BTC", "15m"), ("SOL", "15m"), ("ETH", "15m")]
NSL = 120


def best_ask(arr):
    ts, ap, asz, bp, bsz = arr
    a = ap[:, 0].astype(float)
    a = np.where((a > 0) & (a < 1), a, np.nan)
    return ts.astype(np.int64), a


def asof_idx(ts, t):
    return int(np.searchsorted(ts, int(t), side="right")) - 1


def run():
    res = load_resolutions(); res["slug"] = res["slug"].astype(str)
    rows = []
    all_sums = []
    for asset, tf in UNIVERSE:
        pref = f"{asset.lower()}-updown-{tf}-"
        sub = res[(res.ticker == asset) & (res.timeframe == tf)]
        sub = sub[sub.slug.str.startswith(pref)].copy()
        if sub.empty:
            continue
        sub["ss"] = sub.slug.str.rsplit("-", n=1).str[-1].astype(np.int64)
        sub = sub.sort_values("ss").tail(NSL)
        slugs = set(sub.slug)
        win_s = WIN[tf]
        books = load_orderbook_l25_streaming(asset.lower(), slugs=slugs, subsample_1hz=False)
        mins = []
        for slug in slugs:
            up = books.get((slug, "Up")); dn = books.get((slug, "Down"))
            if up is None or dn is None:
                continue
            uts, ua = best_ask(up); dts, da = best_ask(dn)
            ss = int(slug.rsplit("-", 1)[1])
            grid = np.arange(ss, ss + win_s) * 1_000_000
            uu = np.array([ua[asof_idx(uts, t)] if asof_idx(uts, t) >= 0 else np.nan for t in grid])
            dd = np.array([da[asof_idx(dts, t)] if asof_idx(dts, t) >= 0 else np.nan for t in grid])
            s = uu + dd
            s = s[np.isfinite(s)]
            if len(s) >= 20:
                mins.append(float(s.min()))
                all_sums.append(s)
        if mins:
            rows.append(dict(asset=asset, tf=tf, n_slug=len(mins),
                             min_sum_ever=round(float(np.min(mins)), 4),
                             med_of_per_slug_min=round(float(np.median(mins)), 4),
                             frac_slugs_min_lt_097=round(float(np.mean(np.array(mins) < 0.97)), 4)))
        print(f"[{asset} {tf}] slugs={len(mins)}", flush=True)
    flat = np.concatenate(all_sums)
    print("\nPER-CELL min complete-set sum (top-of-book):")
    print(pd.DataFrame(rows).to_string(index=False))
    print("\nPOOLED top-of-book sum percentiles (all grid points):")
    for q in [0.1, 1, 5, 25, 50]:
        print(f"  p{q}: {np.percentile(flat, q):.4f}")
    print(f"  absolute min: {flat.min():.4f}   frac < 0.97: {(flat<0.97).mean():.5f}   frac < 1.00: {(flat<1.0).mean():.5f}")


if __name__ == "__main__":
    run()
