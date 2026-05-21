"""Run ACC-M and ACC-H side by side on the same slugs.

Tests if the discount-capture + sharp-drop + early-slot taker rules add
positive PnL compared to pure pair-arb maker.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shadow_engine.feeds import ReplayFeed
from shadow_engine.strategies import AccMStrategy, AccHStrategy
from shadow_engine.runner import ShadowRunner


def main():
    feed = ReplayFeed(
        cell="btc_5m",
        slug_rank=(50, 100),
        use_full_trades=True,
    )

    acc_m = AccMStrategy(config={
        "cells": ["btc_5m"],
        "wallet_seed_usdc": 50.0,
    })
    acc_h = AccHStrategy(config={
        "cells": ["btc_5m"],
        "wallet_seed_usdc": 50.0,
    })

    runner = ShadowRunner(
        feeds=[feed],
        strategies=[acc_m, acc_h],
        log_dir=ROOT / "shadow_logs",
        sim_fill_queue_share=True,
    )

    print(f"Running ACC-M vs ACC-H side-by-side on btc_5m, slugs rank 50-100")
    print()
    runner.run(progress_every=10)

    print(f"\n=== ACC-M (pure maker pair-arb) ===")
    print(f"  Final wallet: ${acc_m.wallet_balance:.2f}")
    print(f"  PnL: ${acc_m.wallet_balance - 50.0:+.2f}")

    print(f"\n=== ACC-H (maker + composite taker trigger) ===")
    print(f"  Final wallet: ${acc_h.wallet_balance:.2f}")
    print(f"  PnL: ${acc_h.wallet_balance - 50.0:+.2f}")

    delta = acc_h.wallet_balance - acc_m.wallet_balance
    print(f"\nACC-H vs ACC-M delta: ${delta:+.2f}")
    if delta > 0:
        print(f"  ✅ Hybrid taker module ADDS value (+${delta:.2f})")
    elif delta < 0:
        print(f"  ⚠️ Hybrid taker module SUBTRACTS value ({delta:.2f}) — recalibrate filters")
    else:
        print(f"  → No difference (taker rules not firing in this sample)")


if __name__ == "__main__":
    main()
