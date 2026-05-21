"""Generate a synthetic shadow log and run shadow_monitor.py against it."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path
import numpy as np
import pandas as pd

OUT = Path(__file__).parent / "_logs"
OUT.mkdir(parents=True, exist_ok=True)

rng = np.random.default_rng(42)

rows = []
slot_start_us = 1_778_770_000_000_000
n_slugs = 80
n_firing = int(n_slugs * 0.48)  # match backtest 48.8% fire rate
firing_idx = set(rng.choice(n_slugs, n_firing, replace=False).tolist())

for si in range(n_slugs):
    slug = f"btc-updown-5m-{1778770000 + si * 300}"
    ts0 = slot_start_us + si * 300_000_000
    slot_end_us = ts0 + 300_000_000

    # POST_BID rows — ~60-100 per slug
    n_posts = int(rng.integers(60, 100))
    for _ in range(n_posts):
        rows.append({
            "ts_us": ts0 + int(rng.integers(1_000_000, 300_000_000)),
            "action": "POST_BID",
            "trigger_reason": "post_initial_bid",
            "slug": slug,
            "side": rng.choice(["Up", "Down"]),
            "price": round(float(rng.uniform(0.40, 0.55)), 4),
            "size": 20,
        })

    # CANCEL rows — ~15
    for _ in range(int(rng.integers(10, 25))):
        rows.append({
            "ts_us": ts0 + int(rng.integers(1_000_000, 300_000_000)),
            "action": "CANCEL",
            "trigger_reason": rng.choice(["cancel_displaced_3c", "cancel_age_20s"]),
            "slug": slug,
            "side": rng.choice(["Up", "Down"]),
            "price": round(float(rng.uniform(0.40, 0.55)), 4),
            "size": 20,
        })

    # FILL rows — ~15 per slug
    for _ in range(int(rng.integers(10, 22))):
        rows.append({
            "ts_us": ts0 + int(rng.integers(1_000_000, 300_000_000)),
            "action": "FILL",
            "trigger_reason": "maker_bid_hit",
            "slug": slug,
            "side": rng.choice(["Up", "Down"]),
            "price": round(float(rng.uniform(0.40, 0.55)), 4),
            "size": 20,
            "filled_size": int(rng.choice([5, 10, 15, 20])),
        })

    # TAKE rows — 0-2 per firing slug
    if si in firing_idx:
        n_takes = int(rng.choice([1, 1, 1, 2]))
        for _ in range(n_takes):
            pair_cost = float(rng.uniform(0.93, 0.999))
            up_filled = 20
            dn_filled = 20 if rng.uniform() > 0.05 else int(rng.choice([0, 10]))  # 5% partial
            rows.append({
                "ts_us": ts0 + int(rng.integers(5_000_000, 290_000_000)),
                "action": "TAKE",
                "trigger_reason": f"pat_pair_cost={pair_cost:.4f}",
                "slug": slug,
                "side": "BOTH",
                "price": pair_cost,
                "size": 20,
                "up_filled": up_filled,
                "dn_filled": dn_filled,
                "pair_cost": pair_cost,
            })

    # MERGE rows
    for _ in range(int(rng.integers(2, 6))):
        rows.append({
            "ts_us": ts0 + int(rng.integers(10_000_000, 290_000_000)),
            "action": "MERGE",
            "trigger_reason": "merge_paired_>=5",
            "slug": slug,
            "side": "BOTH",
            "size": int(rng.integers(5, 20)),
        })

    # LOG_SLUG_COMPLETE row — one per slug
    # Backtest mean across all slugs = $7.79, mean on firing = $15.95
    if si in firing_idx:
        pnl = float(rng.normal(15.95, 13.0))
    else:
        pnl = float(rng.normal(0.0, 1.0))
    rows.append({
        "ts_us": slot_end_us,
        "action": "LOG_SLUG_COMPLETE",
        "trigger_reason": "slug_resolved",
        "slug": slug,
        "outcome_truth": rng.choice(["Up", "Down"]),
        "pnl": round(pnl, 4),
    })

df = pd.DataFrame(rows)
csv_path = OUT / "acc-m_2026-05-21.csv"
df.to_csv(csv_path, index=False)
print(f"Wrote synthetic log: {csv_path}  ({len(df):,} rows, {n_slugs} slugs)")

# Run the monitor
print("\nRunning shadow_monitor.py...\n")
result = subprocess.run(
    [sys.executable, "-X", "utf8",
     str(Path(__file__).parent / "shadow_monitor.py"),
     "--csv", str(csv_path)],
    capture_output=False,
)
sys.exit(result.returncode)
