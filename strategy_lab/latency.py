"""
latency.py — static latency model for order submission → fill realism.

Stolen from `evan-kolberg/prediction-market-backtesting` v4.1-alpha
`ExecutionModelConfig(latency_model=StaticLatencyConfig(...))`. They use
this with Nautilus's L2_MBP queue-position model. We use simpler ask-walk
fills, so we adopt the latency as a wall-clock offset between the strategy's
decision time (`fire_us`) and the time at which the L25 book is read for
filling.

Numbers below are PMXT's defaults; these are reasonable for a co-located
trader on Polymarket. Real production controller latency depends on:
    1. Decision-to-relay (Python → REST or Goldsky)         ~10-40 ms
    2. Relay-to-CLOB matching                                ~20-80 ms
    3. Server-side risk + signing                            ~5-15 ms
    -------------------------------------------------------------
    Total observed in production logs: median ~75-120 ms

Use `apply_latency(fire_us, kind)` everywhere we look up the L25 book or
re-read a kline for fill modeling.
"""
from __future__ import annotations
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Defaults (PMXT v4.1-alpha numbers — keep in sync with their backtests)
# ---------------------------------------------------------------------------

BASE_LATENCY_MS: float = 75.0    # order submission → ack
INSERT_LATENCY_MS: float = 10.0  # additional time to insert at the venue
UPDATE_LATENCY_MS: float = 5.0   # modify a resting order
CANCEL_LATENCY_MS: float = 5.0   # cancel a resting order

# Effective wall-clock between decision and the moment the book is "live" to
# this trader. We model fill against the book state at this offset.
EFFECTIVE_FILL_LATENCY_MS: float = BASE_LATENCY_MS + INSERT_LATENCY_MS  # 85 ms


@dataclass(frozen=True)
class StaticLatencyConfig:
    """Container matching PMXT's `StaticLatencyConfig` shape. Use the defaults
    via `DEFAULT_LATENCY` unless you have production-measured numbers."""
    base_latency_ms: float = BASE_LATENCY_MS
    insert_latency_ms: float = INSERT_LATENCY_MS
    update_latency_ms: float = UPDATE_LATENCY_MS
    cancel_latency_ms: float = CANCEL_LATENCY_MS

    @property
    def effective_fill_ms(self) -> float:
        return self.base_latency_ms + self.insert_latency_ms


DEFAULT_LATENCY = StaticLatencyConfig()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def apply_latency(
    decision_us: int,
    kind: str = "fill",
    latency: StaticLatencyConfig = DEFAULT_LATENCY,
) -> int:
    """Shift a decision microsecond timestamp by the configured latency.

    kind:
      'fill'   → base + insert  (~85 ms) — for the moment a taker order
                  reaches the book and matches
      'insert' → base + insert  (~85 ms) — for a passive limit insert
      'update' → base + update  (~80 ms)
      'cancel' → base + cancel  (~80 ms)
      'ack'    → base           (~75 ms) — just the round-trip
    """
    if kind in ("fill", "insert"):
        ms = latency.base_latency_ms + latency.insert_latency_ms
    elif kind == "update":
        ms = latency.base_latency_ms + latency.update_latency_ms
    elif kind == "cancel":
        ms = latency.base_latency_ms + latency.cancel_latency_ms
    elif kind == "ack":
        ms = latency.base_latency_ms
    else:
        raise ValueError(f"unknown latency kind {kind!r}; use one of "
                         "fill / insert / update / cancel / ack")
    return int(decision_us) + int(ms * 1_000)


if __name__ == "__main__":
    cfg = DEFAULT_LATENCY
    print(f"base={cfg.base_latency_ms}ms insert={cfg.insert_latency_ms}ms "
          f"effective_fill={cfg.effective_fill_ms}ms")
    fire_us = 1_778_342_400_000_000
    print(f"fire_us            = {fire_us}")
    print(f"  + fill latency   = {apply_latency(fire_us, 'fill')}")
    print(f"  + cancel latency = {apply_latency(fire_us, 'cancel')}")
