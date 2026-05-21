"""Example: run ACC-M shadow on BTC 5m historical data.

Validates that the strategy logic produces similar PnL to the acc_simulator.py
reference backtest.

Usage:
    py -3 -X utf8 examples/shadow_acc_m_btc_5m.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shadow_engine.feeds import ReplayFeed
from shadow_engine.strategies import AccMStrategy
from shadow_engine.runner import ShadowRunner


def main():
    # Load 50 mid-rank BTC 5m slugs (similar to acc_simulator validation)
    feed = ReplayFeed(
        cell="btc_5m",
        slug_rank=(50, 100),
        use_full_trades=True,
    )

    # ACC-M with test-scale config
    strategy = AccMStrategy(config={
        "cells": ["btc_5m"],
        "wallet_seed_usdc": 50.0,
        "POST_SIZE": 5.0,
        "MAX_IMBALANCE_SHARES": 5.0,
        "ABSOLUTE_MAX_INVENTORY": 50.0,
        "CANCEL_THRESHOLD": 0.03,
        "MAX_ORDER_AGE_S": 20.0,
        "MERGE_THRESHOLD_PAIRS": 5,
        "MAX_SUM_BIDS": 1.00,
        "shadow_mode": True,
    })

    runner = ShadowRunner(
        feeds=[feed],
        strategies=[strategy],
        log_dir=ROOT / "shadow_logs",
        sim_fill_queue_share=True,
    )

    print(f"Starting ACC-M shadow run on btc_5m, slugs rank 50-100")
    print(f"  Wallet seed: ${strategy.config['wallet_seed_usdc']}")
    print(f"  Post size: {strategy.config['POST_SIZE']} shares")
    print(f"  Cancel threshold: ${strategy.config['CANCEL_THRESHOLD']}")
    print()

    runner.run(progress_every=10)

    print(f"\nFinal wallet balance: ${strategy.wallet_balance:.2f}")
    print(f"PnL vs seed: ${strategy.wallet_balance - strategy.config['wallet_seed_usdc']:+.2f}")


if __name__ == "__main__":
    main()
