"""Phase 30 — PreSignedPool skeleton (D-16).

SKELETON ONLY. Phase 30 shadow mode never calls `lookup_by_price` — the
`poly_maker_loop` dispatcher (Plan 30-10) gates real invocation behind
`settings.tv_poly_maker_presigned_pool_enabled` (default `False`).

Full implementation lands in Phase 30.1 (live promotion):
  - `warmup()` pre-signs N prices × 2 sides × N cells at T-30s pre-slug.
  - `lookup_by_price()` returns the pre-signed EIP-712 order matching
    `(slug, side, price)` for O(1) submission via
    `PolymarketClient._submit_order`.

This module is deliberately minimal:
  - No signing-material constructor args (Phase 30.1 adds those).
  - No `side` validation (Phase 30.1 enforces `Side ∈ {"up", "dn"}`).
  - No warmup ledger / cleanup / staleness checks (all Phase 30.1).
  - The `_pool` dict is the single storage slot the next phase fills in.

Anchors:
  - 30-CONTEXT.md D-16: "Pre-signed pool: skeleton-only in Plan 30-09."
  - 30-RESEARCH.md §"Pre-signed pool design": rationale for the API shape.
  - 30-PATTERNS.md §presigned_pool.py: verbatim skeleton.
  - CLAUDE.md invariant #10: structlog imported at module top.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

import structlog

log = structlog.get_logger(__name__)


class PreSignedPool:
    """Phase 30 D-16 SKELETON ONLY. Full implementation in Phase 30.1.

    Phase 30 shadow mode: this class is constructed at engine boot (Plan
    30-10), but neither `warmup()` nor `lookup_by_price()` is ever called —
    `settings.tv_poly_maker_presigned_pool_enabled` defaults `False`, and
    the dispatcher's gate skips the lookup path entirely.

    Phase 30.1 live promotion flips two flags together:
      - `tv_poly_maker_shadow_mode=False` (real order submission), AND
      - `tv_poly_maker_presigned_pool_enabled=True` (use this pool).
    Both controls are required — the T-30-09-02 mitigation in plan 30-09.

    The `Any` typing on `lookup_by_price` is intentional: Phase 30.1 will
    introduce a `SignedOrder` dataclass (probably with `repr=False` on the
    signature field per CLAUDE invariant #10) and refine the return type
    then. Pinning a concrete return type today would lock in a shape we
    haven't designed yet.
    """

    def __init__(self) -> None:
        # (slug, side, price) → pre-signed EIP-712 order. Empty in skeleton
        # form. Phase 30.1's warmup() populates this at T-30s pre-slug.
        self._pool: dict[tuple[str, str, Decimal], Any] = {}

    def lookup_by_price(self, slug: str, side: str, price: Decimal) -> Any:
        """Returns the pre-signed EIP-712 order matching `(slug, side, price)`.

        Phase 30 skeleton: ALWAYS raises `NotImplementedError`. Never called
        in shadow mode — the dispatcher's settings gate short-circuits before
        reaching this path. If a misconfiguration ever calls it, the raise
        ensures no on-chain or order-submission side-effect occurs.

        Phase 30.1: returns the matching signed order from `self._pool`, or
        `None` if no pre-signed cell covers the requested price. The caller
        (poly_maker_loop) then either submits the signed order directly to
        the CLOB or falls back to on-demand signing.
        """
        raise NotImplementedError(
            "Phase 30 ships skeleton only per D-16; Phase 30.1 wires real signing."
        )

    async def warmup(self, slug: str, prices: list[Decimal]) -> None:
        """Pre-signs `prices × 2 sides × N cells` at T-30s pre-slug.

        Phase 30 skeleton: ALWAYS raises `NotImplementedError`. Phase 30.1:
        signs via `py_clob_client_v2.create_order(...)` for each `(side,
        price)` pair, then writes the resulting EIP-712 blobs into
        `self._pool` keyed by `(slug, side, price)`. The warmup completes
        before the slug goes "active" so the loop can submit pre-signed
        orders with O(1) lookup overhead on the hot path.
        """
        raise NotImplementedError("Phase 30 ships skeleton only per D-16.")
