"""Event feeds — produce events from historical parquets or live WS.

Modules:
- replay: drives events from canonical parquets (for backtesting / shadow validation)
- live: (future) connects to Polymarket WS for real-time
"""
from .replay import ReplayFeed
from .replay_l25 import ReplayFeedL25

__all__ = ["ReplayFeed", "ReplayFeedL25"]
