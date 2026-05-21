"""Phase-1 fixed sizing — flat $25 per fire."""

from __future__ import annotations

from ..conventions import NOTIONAL_USD


def fixed_size(balance: float = 0.0, **_kwargs) -> float:
    """Return the flat per-fire notional. `balance` is accepted (and ignored)
    for interface compatibility with the future confidence-scaled sizer."""
    return float(NOTIONAL_USD)
