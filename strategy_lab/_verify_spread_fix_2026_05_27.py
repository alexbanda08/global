"""
Small-sample verification: prove (or disprove) live cross-token spread filter is the
cause of V5 0-placements.

For each spread-blocked fire, fetch L25 book on the BUY side at fire_us and compute:
  - cross_spread_live = abs(up_vwap - (1 - dn_vwap))     [what production computed]
  - bidask_spread_new = ap[0] - bp[0] on buy-side token  [what the fix would compute]
  - filter = 0.02 (BTC/ETH) or 0.025 (SOL)
  - would_pass = bidask_spread_new <= filter
"""
from __future__ import annotations
import json
import random
import sys
from pathlib import Path
from collections import defaultdict
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data" / "v4" / "canonical"))
from load import load_orderbook_l25_streaming  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
JSONL = ROOT / "strategy_lab" / "_v5_live_2026_05_27.jsonl"

# L25 latest cutoff per asset (from inspection above; use 13:20 UTC = safe lowest)
L25_CUTOFF_US = 1779884405_000000  # 2026-05-27 13:20 UTC

# Asset-specific spread cap (TV config)
FILTER = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}

# --- Load all spread-blocked fires within L25 coverage --------------------------
fires_all = []
with open(JSONL) as f:
    for line in f:
        d = json.loads(line)
        sr = d.get("skip_reason") or ""
        if not sr.startswith("spread_too_wide_"):
            continue
        if d["fire_us"] > L25_CUTOFF_US:
            continue
        fires_all.append(d)

print(f"Spread-blocked fires within L25 coverage: {len(fires_all)}")

# Sample 100 randomly (seeded)
random.seed(42)
sample = random.sample(fires_all, k=min(100, len(fires_all)))
print(f"Sampled: {len(sample)}")

# Group by (asset, slug) for batched L25 load
by_asset_slug: dict[tuple[str, str], list[dict]] = defaultdict(list)
for r in sample:
    by_asset_slug[(r["asset"], r["slug"])].append(r)
print(f"Unique (asset,slug) combos: {len(by_asset_slug)}")

# Pre-group slugs by asset for one streaming call per asset
slugs_by_asset: dict[str, set[str]] = defaultdict(set)
for (a, s), _ in by_asset_slug.items():
    slugs_by_asset[a].add(s)

# Bound the time window: across all sampled fires
fire_us_list = [r["fire_us"] for r in sample]
min_fire = min(fire_us_list)
max_fire = max(fire_us_list)
window_pad = 60_000_000  # 60s
min_ts = min_fire - window_pad
max_ts = max_fire + 5_000_000

# --- Load L25 per asset ---------------------------------------------------------
books_by_asset: dict[str, dict] = {}
for asset, slugs in slugs_by_asset.items():
    print(f"Loading L25 for {asset} ({len(slugs)} slugs)...")
    books = load_orderbook_l25_streaming(
        asset.lower(),
        slugs=slugs,
        subsample_1hz=False,  # native 10Hz per CLAUDE.md
        min_ts_us=min_ts,
        max_ts_us=max_ts,
    )
    books_by_asset[asset] = books
    print(f"  loaded {len(books)} (slug, outcome) keys")

# --- Verify each fire -----------------------------------------------------------
results = []
for r in sample:
    asset = r["asset"]
    slug = r["slug"]
    direction = r["direction"]  # 'UP' or 'DOWN'
    fire_us = r["fire_us"]
    snap = r.get("l25_book_snapshot") or {}
    up_v = snap.get("up_vwap")
    dn_v = snap.get("dn_vwap")
    cross_live = abs(up_v - (1 - dn_v)) if (up_v is not None and dn_v is not None) else None

    # Buy side outcome name in L25 keys: usually 'Up' / 'Down'
    buy_outcome = "Up" if direction.upper() == "UP" else "Down"

    books = books_by_asset.get(asset, {})
    key = (slug, buy_outcome)
    rec = books.get(key)
    if rec is None:
        # outcome label might be different — try lowercase
        for k in books.keys():
            if k[0] == slug and k[1].lower() == buy_outcome.lower():
                rec = books[k]
                key = k
                break

    bidask_new = None
    ts_used = None
    if rec is not None:
        ts_us, ap, asz, bp, bsz = rec
        # find latest snap at or before fire_us
        idx = np.searchsorted(ts_us, fire_us, side="right") - 1
        if idx >= 0:
            a0 = ap[idx, 0]
            b0 = bp[idx, 0]
            if a0 > 0 and b0 > 0:
                bidask_new = float(a0 - b0)
                ts_used = int(ts_us[idx])

    filt = FILTER.get(asset, 0.02)
    would_pass = (bidask_new is not None) and (bidask_new <= filt)

    results.append({
        "asset": asset,
        "slug": slug,
        "direction": direction,
        "fire_us": fire_us,
        "buy_outcome": buy_outcome,
        "cross_spread_live": cross_live,
        "bidask_spread_new": bidask_new,
        "filter": filt,
        "would_pass": would_pass,
        "book_age_s": (fire_us - ts_used) / 1e6 if ts_used else None,
        "found_book": rec is not None,
    })

# --- Stats ----------------------------------------------------------------------
total = len(results)
with_book = [r for r in results if r["found_book"]]
without_book = total - len(with_book)
passes = [r for r in with_book if r["would_pass"]]
fails = [r for r in with_book if not r["would_pass"]]

print(f"\n=== AGGREGATE ===")
print(f"total sampled fires: {total}")
print(f"L25 book found: {len(with_book)}")
print(f"L25 book NOT found: {without_book}")
if with_book:
    pct_pass = 100 * len(passes) / len(with_book)
    print(f"would_pass: {len(passes)} ({pct_pass:.1f}%)")
    print(f"would_fail (genuinely thin): {len(fails)} ({100*len(fails)/len(with_book):.1f}%)")

# Per asset
print("\n=== PER ASSET ===")
for asset in ["BTC", "ETH", "SOL"]:
    rs = [r for r in with_book if r["asset"] == asset]
    if not rs:
        continue
    ps = [r for r in rs if r["would_pass"]]
    fs = [r for r in rs if not r["would_pass"]]
    spreads = [r["bidask_spread_new"] for r in rs if r["bidask_spread_new"] is not None]
    med = float(np.median(spreads)) if spreads else None
    mean = float(np.mean(spreads)) if spreads else None
    print(f"{asset}: n={len(rs)}, pass={len(ps)} ({100*len(ps)/len(rs):.1f}%), "
          f"median_bidask={med:.4f}, mean_bidask={mean:.4f}, filter={FILTER[asset]:.3f}")

# Examples (10)
print("\n=== EXAMPLES (first 10) ===")
for r in with_book[:10]:
    print(f"  {r['asset']:3} {r['direction']:4} slug={r['slug'][-32:]:<32} "
          f"old={r['cross_spread_live']:.4f} new={r['bidask_spread_new']:.4f} "
          f"filt={r['filter']:.3f} pass={r['would_pass']} age={r['book_age_s']:.1f}s")

# Save full
out_p = ROOT / "strategy_lab" / "_spread_fix_verify_results.json"
with open(out_p, "w") as f:
    json.dump(results, f, indent=2)
print(f"\nSaved: {out_p}")
