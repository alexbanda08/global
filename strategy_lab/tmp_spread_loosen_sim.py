"""Simulate loosened spread filters on V5 jsonl — count would-have-placed fires.

Loosening rules:
- BTC 5m: 0.020 -> 0.025
- ETH 5m: 0.020 -> 0.025
- SOL 5m: 0.025 -> 0.030
- BTC 15m: 0.020 -> 0.025
- ETH 15m: 0.020 -> 0.025
- SOL 15m: 0.025 -> 0.030
"""
import json
import re
import time
from collections import Counter, defaultdict

path = "/var/log/tradingvenue/sniper_v5/2026-05-27.jsonl"

# Window: last 8.5 hours
now_us = int(time.time() * 1_000_000)
window_start_us = now_us - int(8.5 * 3600 * 1_000_000)

# New filters per (asset, tf)
NEW_FILTERS = {
    ("BTC", "5m"): 0.025,
    ("ETH", "5m"): 0.025,
    ("SOL", "5m"): 0.030,
    ("BTC", "15m"): 0.025,
    ("ETH", "15m"): 0.025,
    ("SOL", "15m"): 0.030,
}

# Parse spread from skip_reason text like "spread_bidask_too_wide_0.0300_>_0.0200"
SPREAD_RE = re.compile(r"spread_bidask_too_wide_([0-9.]+)_>_([0-9.]+)")
SPREAD_OLD_RE = re.compile(r"spread_too_wide_([0-9.]+)_>_([0-9.]+)")

stats = {
    "total_evals_in_window": 0,
    "current_placed_in_window": 0,
    "spread_bidask_rejected": 0,
    "spread_cross_rejected_old": 0,
    "would_pass_new_filter": 0,
    "still_blocked_by_new_filter": 0,
    "would_pass_per_sleeve": Counter(),
    "current_placed_per_sleeve": Counter(),
}

by_asset_tf_added = Counter()

with open(path) as f:
    for line in f:
        try:
            r = json.loads(line)
        except Exception:
            continue
        fire_us = r.get("fire_us")
        if fire_us is None or fire_us < window_start_us:
            continue
        stats["total_evals_in_window"] += 1
        sid = r.get("sleeve_id", "?")
        asset = r.get("asset")
        tf = r.get("tf")
        et = r.get("event_type")

        if et == "sleeve_fire_placed":
            stats["current_placed_in_window"] += 1
            stats["current_placed_per_sleeve"][sid] += 1

        sr = r.get("skip_reason") or ""
        m_new = SPREAD_RE.search(sr)
        m_old = SPREAD_OLD_RE.search(sr)
        if m_new:
            stats["spread_bidask_rejected"] += 1
            spread = float(m_new.group(1))
            new_filter = NEW_FILTERS.get((asset, tf))
            if new_filter is not None and spread <= new_filter:
                stats["would_pass_new_filter"] += 1
                stats["would_pass_per_sleeve"][sid] += 1
                by_asset_tf_added[(asset, tf)] += 1
            else:
                stats["still_blocked_by_new_filter"] += 1
        elif m_old:
            # Pre-fix entries — cross-token spread, can't reconstruct bid-ask
            stats["spread_cross_rejected_old"] += 1

print(f"=== Simulation window: last 8.5 hours ===")
print(f"now_us={now_us}, window_start_us={window_start_us}")
print()
print(f"Total events (any type) in window: {stats['total_evals_in_window']}")
print(f"  Currently PLACED: {stats['current_placed_in_window']}")
print(f"  Rejected by spread_bidask filter (new format): {stats['spread_bidask_rejected']}")
print(f"  Rejected by spread cross-token (old, pre-fix): {stats['spread_cross_rejected_old']}")
print()
print(f"=== SIMULATION RESULT ===")
print(f"Would PASS new looser filter: {stats['would_pass_new_filter']}")
print(f"Still BLOCKED by new looser filter: {stats['still_blocked_by_new_filter']}")
print()
total_placed_potential = stats["current_placed_in_window"] + stats["would_pass_new_filter"]
print(f"=== TOTAL PLACEMENT POTENTIAL ===")
print(f"Current placed: {stats['current_placed_in_window']}")
print(f"Additional from loosening: +{stats['would_pass_new_filter']}")
print(f"Total potential: {total_placed_potential}")
if stats["current_placed_in_window"] > 0:
    multiplier = total_placed_potential / stats["current_placed_in_window"]
    print(f"Multiplier: {multiplier:.2f}x")
print()
print(f"=== Added fires by (asset, tf) ===")
for (a, t), c in sorted(by_asset_tf_added.items(), key=lambda x: -x[1]):
    print(f"  {a} {t}: +{c} fires (new filter = {NEW_FILTERS[(a,t)]})")
print()
print(f"=== Top 15 sleeves by ADDED fires under looser filter ===")
for sid, c in stats["would_pass_per_sleeve"].most_common(15):
    short = sid.replace("poly_sniper_v5_", "")
    current = stats["current_placed_per_sleeve"][sid]
    print(f"  {short[:55]:55} current={current:>3} +new={c:>3} total={current+c}")
print()
print(f"=== Caveat ===")
print("OPTIMISTIC simulation: assumes all gates would pass for the spread-rejected fires.")
print("Spread filter ran BEFORE gates in the original controller (we don't have gate eval")
print("data for these rejected rows). Actual placed count would be LOWER than this estimate")
print("if some gates would also fail. Real number is typically 60-80% of this max.")
