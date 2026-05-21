"""Generate a BROKEN shadow log — pair_cost > 1.00 and PnL crash."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path
import numpy as np
import pandas as pd

OUT = Path(__file__).parent / "_logs"
OUT.mkdir(parents=True, exist_ok=True)

rng = np.random.default_rng(99)

rows = []
slot_start_us = 1_778_770_000_000_000
n_slugs = 80
n_firing = int(n_slugs * 0.48)
firing_idx = set(rng.choice(n_slugs, n_firing, replace=False).tolist())

for si in range(n_slugs):
    slug = f"btc-updown-5m-{1778770000 + si * 300}"
    ts0 = slot_start_us + si * 300_000_000

    for _ in range(int(rng.integers(60, 100))):
        rows.append({"ts_us": ts0, "action": "POST_BID",
                     "trigger_reason": "post_initial_bid", "slug": slug,
                     "side": rng.choice(["Up", "Down"]), "price": 0.5, "size": 20})

    for _ in range(int(rng.integers(8, 20))):
        rows.append({"ts_us": ts0, "action": "FILL",
                     "trigger_reason": "maker_bid_hit", "slug": slug,
                     "side": rng.choice(["Up", "Down"]), "price": 0.5,
                     "size": 20, "filled_size": 20})

    if si in firing_idx:
        for _ in range(int(rng.choice([1, 2]))):
            # BUG: half of fires exceed 1.00 cap → should flag RED
            pair_cost = float(rng.uniform(0.93, 1.04))
            # Frequent partial fills (50%) → should flag RED
            up_filled = 20
            dn_filled = 20 if rng.uniform() > 0.5 else 0
            rows.append({"ts_us": ts0, "action": "TAKE",
                         "trigger_reason": f"pat_pair_cost={pair_cost:.4f}",
                         "slug": slug, "side": "BOTH", "price": pair_cost,
                         "size": 20, "up_filled": up_filled,
                         "dn_filled": dn_filled, "pair_cost": pair_cost})

    # Slug-complete with NEGATIVE PnL avg (broken strategy)
    pnl = float(rng.normal(-3.0, 5.0))
    rows.append({"ts_us": ts0 + 300_000_000, "action": "LOG_SLUG_COMPLETE",
                 "trigger_reason": "slug_resolved", "slug": slug,
                 "outcome_truth": rng.choice(["Up", "Down"]), "pnl": round(pnl, 4)})

df = pd.DataFrame(rows)
csv_path = OUT / "acc-m_2026-05-22_BROKEN.csv"
df.to_csv(csv_path, index=False)
print(f"Wrote BROKEN synthetic log: {csv_path}  ({len(df):,} rows)\n")

result = subprocess.run(
    [sys.executable, "-X", "utf8",
     str(Path(__file__).parent / "shadow_monitor.py"),
     "--csv", str(csv_path)],
    capture_output=False,
)
sys.exit(result.returncode)
