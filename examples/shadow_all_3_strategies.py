"""Run ACC-M + ACC-H + MAS side by side on the same slugs.

Three strategies, three independent state machines, three log files.
Demonstrates that MAS (asks) and ACC (bids) coexist on the same wallet
without conflict.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shadow_engine.feeds import ReplayFeed
from shadow_engine.strategies import AccMStrategy, AccHStrategy, MasStrategy
from shadow_engine.runner import ShadowRunner


def main():
    feed = ReplayFeed(
        cell="btc_5m",
        slug_rank=(50, 100),
        use_full_trades=True,
    )

    acc_m = AccMStrategy(config={"cells": ["btc_5m"], "wallet_seed_usdc": 50.0})
    acc_h = AccHStrategy(config={"cells": ["btc_5m"], "wallet_seed_usdc": 50.0})
    mas = MasStrategy(config={"cells": ["btc_5m"], "wallet_seed_usdc": 100.0, "PRE_MINT_USDC": 30.0})

    runner = ShadowRunner(
        feeds=[feed],
        strategies=[acc_m, acc_h, mas],
        log_dir=ROOT / "shadow_logs",
        sim_fill_queue_share=True,
    )

    print(f"3-strategy shadow: ACC-M + ACC-H + MAS on btc_5m, slugs 50-100")
    print(f"  ACC-M wallet: $50 (post BIDs, expect tokens IN, merge for cash)")
    print(f"  ACC-H wallet: $50 (post BIDs + market-BUY on dips)")
    print(f"  MAS   wallet: $100 ($30 pre-mint per slug, post ASKs)")
    print()
    runner.run(progress_every=10)

    print(f"\n=== Strategy comparison ===")
    print(f"{'Strategy':<10s} | {'Start':>8s} | {'Final':>8s} | {'PnL':>8s}")
    for name, strat, seed in [
        ("ACC-M", acc_m, 50.0),
        ("ACC-H", acc_h, 50.0),
        ("MAS",   mas,   100.0),
    ]:
        delta = strat.wallet_balance - seed
        print(f"{name:<10s} | ${seed:>6.2f} | ${strat.wallet_balance:>6.2f} | ${delta:>+6.2f}")


if __name__ == "__main__":
    main()
