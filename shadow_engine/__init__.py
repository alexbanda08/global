"""Shadow engine for Polymarket maker bots.

Pure-Python implementation for shadow mode validation. Designed so the strategy
logic stays in Python (easy iteration) while the hot path can be swapped to
Rust later via PyO3.

Modules:
- base: shared types (events, decisions, slug state)
- strategies: ACC-M, ACC-H, MAS implementations
- feeds: replay (historical) and live (Polymarket WS) data sources
- perf: latency instrumentation
- runner: orchestrator that dispatches events to strategies

Quickstart:
    from shadow_engine.runner import ShadowRunner
    from shadow_engine.strategies.acc_m import AccMStrategy
    from shadow_engine.feeds.replay import ReplayFeed

    feed = ReplayFeed(cell="btc_5m", slug_rank=(50, 150))
    strategy = AccMStrategy(config={"POST_SIZE": 5, "wallet_seed_usdc": 50})
    runner = ShadowRunner(feeds=[feed], strategies=[strategy])
    runner.run()
"""

__version__ = "0.1.0"
