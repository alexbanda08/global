"""Run all 3 strategies with the L25-CALIBRATED feed (real bid sizes).

Compare PnL against the old replay (ask-size proxy) to see if calibration changes things.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shadow_engine.feeds import ReplayFeedL25
from shadow_engine.strategies import AccMStrategy, AccHStrategy, MasStrategy
from shadow_engine.runner import ShadowRunner


def main():
    feed = ReplayFeedL25(
        cell="btc_5m",
        slug_rank=(50, 100),
    )

    acc_m = AccMStrategy(config={"cells": ["btc_5m"], "wallet_seed_usdc": 50.0})
    acc_h = AccHStrategy(config={"cells": ["btc_5m"], "wallet_seed_usdc": 50.0})
    mas = MasStrategy(config={"cells": ["btc_5m"], "wallet_seed_usdc": 100.0, "PRE_MINT_USDC": 30.0})

    runner = ShadowRunner(
        feeds=[feed],
        strategies=[acc_m, acc_h, mas],
        log_dir=ROOT / "shadow_logs_l25",
        sim_fill_queue_share=True,
    )

    print(f"L25-CALIBRATED shadow: 3 strategies on btc_5m, slugs 50-100")
    print(f"  Using REAL bid sizes from orderbook_l25/btc.parquet")
    print()
    runner.run(progress_every=10)

    print(f"\n=== Calibrated PnL ===")
    print(f"{'Strategy':<10s} | {'Start':>8s} | {'Final':>8s} | {'PnL':>8s}")
    for name, strat, seed in [
        ("ACC-M", acc_m, 50.0),
        ("ACC-H", acc_h, 50.0),
        ("MAS",   mas,   100.0),
    ]:
        delta = strat.wallet_balance - seed
        marker = "✅" if delta > 0 else "❌"
        print(f"{name:<10s} | ${seed:>6.2f} | ${strat.wallet_balance:>6.2f} | ${delta:>+6.2f} {marker}")


if __name__ == "__main__":
    main()
