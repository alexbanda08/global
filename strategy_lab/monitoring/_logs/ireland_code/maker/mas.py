"""Phase 30 Plan 04 — MAS (Mint-And-Sell maker mirror).

Port of `TV_DEPLOY_SPEC_MAS_2026_05_18.md` decision rules. Unlike ACC-M
(BID-only paired arb) and ACC-H (composite taker), MAS pre-mints a pair of
(up, dn) shares via CTF.splitPosition on slug activation, then posts ASKs
at the current best_ask on each side. Captures the structural mispricing
where ``sum_asks > $1.00`` (mirror image of ACC-M's ``sum_bids < $1.00``).

MAS is NOT present in shadow_engine — there is no Python reference
implementation. The port source is the deploy spec directly. The on-chain
mint tx + the redeem tx are wrapped by Plan 30-10's `poly_maker_loop`
(not here). This module emits only Decision[]; the loop reuses
`poly_mint_sell_v2/onchain_executor.py:split_position` (mint) and
`redeem_positions` (redeem). When the splitPosition receipt lands, the
loop emits a synthetic OrderFill with order_id = `"MAS-MINT-<slug>"` so
that this module's state can flip inv_up + inv_dn to the post-mint values
without coupling to the chain layer.

State machine (per spec §2):
    SlugActive       → emit MINT Decision; SlugState seeded with zero inv
    L25Update        → for each held side, emit POST_ASK if no open ask
                        already exists on that side
    OrderFill        → if order_id starts "MAS-MINT-" → set inv_up =
                        inv_dn = mas_per_slug_usdc (mint settled).
                        Otherwise → ASK fill: decrement inv on side,
                        accumulate cash_received + (if maker) rebate
    SlugResolved     → emit REDEEM Decision for winner-side residual
                        (loser side is worthless — no REDEEM)
    TradePrint       → ignored (MAS doesn't react to trade prints;
                        only ACC-H does)

CLAUDE.md invariants honored:

- inv #4 (closed-bar): event handlers receive only closed L25 snapshots
  from BookMirror (snapshot boundary enforced upstream).
- inv #10 (secrets): ``structlog.get_logger(__name__)`` at module top;
  the global ``redact_secrets_processor`` catches HEX_PRIVKEY leaks.
- inv #13 (TV-native data): pure-function module — no imports from
  ``engine.*``, ``venues.polymarket.client``, ``asyncpg``, ``httpx``,
  ``web3``, ``aiohttp``, ``requests``, or ``poly_mint_sell_v2``
  (the on-chain mint tx wrapping happens in Plan 30-10's loop, NOT here).

Trading invariants (TV_DEPLOY_SPEC_MAS §3 + CLAUDE.md inv #1, #2):

- ``MIN_POST_SHARES`` (read from settings) = 5 — CLOB minimum. No posts below.
- ``_MIN_PRICE`` = Decimal("0.01") — CLOB minimum tick floor. Even if
  best_ask comes through as 0 (degenerate book), the post price is
  clamped up to 1¢.
- Post size = min(inventory_on_side, 2 × MIN_POST_SHARES) — keep per-tick
  flow small per spec §6 (50-150 ask posts per slug); larger size emerges
  via REPEATED ticks as the dedup filter releases on each fill.
- One open ASK per side max (dedup) — verified by Test 9. Phase 30 spec
  CANCEL rules (3¢ displacement / 20s age) live in `poly_maker_loop`'s
  dispatcher per Plan 30-10; this module focuses on the pure decision
  rules (post + redeem + state mgmt).
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from backend.app.strategies.polymarket.maker.base import (
    MakerStrategyBase,
    _next_order_id,
    maker_rebate,
    quantize_price,
    taker_fee,
)
from backend.app.strategies.polymarket.maker.types import (
    Decision,
    L25Update,
    OpenOrder,
    OrderFill,
    SlugActive,
    SlugResolved,
    SlugState,
    TradePrint,
)

if TYPE_CHECKING:  # pragma: no cover — type-only imports
    from backend.app.core.config import Settings

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Module constants (TV_DEPLOY_SPEC_MAS §3 — not operator-tunable)
# ---------------------------------------------------------------------------

#: CLOB minimum price increment / floor — every POST_ASK clamped to >= 0.01.
_MIN_PRICE = Decimal("0.01")

#: Multiplier on min_post_shares for the per-tick post size cap.
#: Spec §6: 50-150 ask posts per slug for the average run → keep per-tick
#: flow small; the slug-wide volume emerges from many small posts.
_POST_SIZE_MAX_MULT = Decimal("2")

#: Order-ID prefix marking a synthetic mint-confirmation event.
#: Plan 30-10's loop fabricates an OrderFill with this prefix once the
#: CTF.splitPosition receipt lands, allowing MAS to flip inv_up + inv_dn
#: to the post-mint values without coupling to the chain layer.
_MINT_CONFIRM_PREFIX = "MAS-MINT-"


# ---------------------------------------------------------------------------
# MasStrategy
# ---------------------------------------------------------------------------

class MasStrategy(MakerStrategyBase):
    """Pure mint-and-sell maker mirror.

    Lifecycle:
      1. ``on_slug_active(evt)``        → emit MINT Decision; seed SlugState
                                          (inv zero — mint settles async)
      2. ``on_l25_update(evt)``         → for each held side with inventory,
                                          emit POST_ASK at quantized
                                          best_ask (dedup: 1 open ASK
                                          per side max)
      3. ``on_order_fill(evt)``         → if MAS-MINT-* prefix → set inv;
                                          else ASK fill: decrement inv,
                                          accumulate cash + rebate,
                                          remove order
      4. ``on_trade_print(evt)``        → ignored (MAS doesn't react to
                                          trade prints; only ACC-H does)
      5. ``on_slug_resolved(evt)``      → emit REDEEM for winner residual
                                          (loser side worthless, no REDEEM)

    Attributes:
        code        : "MAS" — class-level identity used in order IDs.
        config      : Pydantic Settings — read tv_poly_maker_* fields only.
        asset       : "ETH" / "SOL" (D-05: MAS runs on ETH 5m+15m, SOL 5m+15m).
        tf          : "5m" / "15m".
        slug_states : dict[slug, SlugState] — per-slug mutable state.
    """

    code = "MAS"

    def __init__(self, settings: "Settings", asset: str, tf: str) -> None:
        self.config = settings
        self.asset = asset
        self.tf = tf
        self.slug_states: dict[str, SlugState] = {}
        self._order_counter = 0
        # Cross-restart re-mint defense (cf. seed_inventory docstring): the
        # engine boot path may scan today's CSV for prior MINT rows and stash
        # the recovered inventory here. on_slug_active checks this BEFORE
        # minting -- if present, calls seed_inventory + skips the mint (the
        # previous process already minted; chain has the shares).
        # Cleared per-slug on use. Empty when no recovery applies.
        self._pending_csv_recovery: dict[str, tuple[Decimal, Decimal]] = {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _next_local_oid(self) -> str:
        """Build the next local order ID like ``MAS-00000001``."""
        self._order_counter += 1
        return _next_order_id(self.code, self._order_counter)

    # ==================================================================
    # Event handlers (5 abstract methods)
    # ==================================================================

    def on_slug_active(self, evt: SlugActive) -> list[Decision]:
        """Emit single MINT Decision; seed SlugState with zero inventory.

        The on-chain mint tx is wrapped by Plan 30-10's loop. Once the
        splitPosition receipt lands, the loop emits a synthetic
        OrderFill(order_id="MAS-MINT-<slug>"), which this module handles
        in ``on_order_fill`` to flip inv_up + inv_dn to the post-mint
        values.

        **Double-mint defense** (CLAUDE.md inv #2 — partial / repeated
        fills are state-machine hazards): if a SlugState already exists
        for this slug, treat as "already minted within this process" and
        emit NO additional MINT — return ``[]``. The bug this guards: a
        broken upstream dedup in ``poly_maker_loop._slug_discovery_tick``
        firing SlugActive twice for the same slug would otherwise cause
        a second on-chain ``split_position`` call in LIVE mode (double
        capital deploy). The pure-Python idempotency here is a defense
        layer; the primary cross-restart defense is the loop's chain
        balance probe (``LiveOnChainExecutor.get_ctf_balance``) which
        calls ``seed_inventory`` instead of ``on_slug_active`` whenever
        on-chain shares are already held.
        """
        if evt.slug in self.slug_states:
            # Idempotent — already saw SlugActive for this slug in this
            # process. Do NOT reset state and do NOT emit another MINT.
            log.warning(
                "mas.on_slug_active.duplicate_skipped",
                slug=evt.slug,
                inv_up=str(self.slug_states[evt.slug].inv_up),
                inv_dn=str(self.slug_states[evt.slug].inv_dn),
            )
            return []

        # Cross-restart re-mint defense: if the engine boot loader stashed prior
        # inventory for this slug (read from today's shadow_log CSV), seed state
        # from the stash + skip the mint. The previous process already paid the
        # mint cost ($30 per slug per MAS); minting again would double-deploy.
        recovered = self._pending_csv_recovery.pop(evt.slug, None)
        if recovered is not None:
            inv_up, inv_dn = recovered
            self.seed_inventory(evt, inv_up, inv_dn)
            log.info(
                "mas.on_slug_active.recovered_from_csv",
                slug=evt.slug,
                inv_up=str(inv_up),
                inv_dn=str(inv_dn),
                reason="prior_process_already_minted",
            )
            return []

        self.slug_states[evt.slug] = SlugState(
            slug=evt.slug,
            condition_id=evt.condition_id,
            token_id_up=evt.token_id_up,
            token_id_dn=evt.token_id_dn,
            asset=evt.asset,
            tf=evt.tf,
            slug_active_ts_us=evt.ts_us,
        )
        amount = self.config.tv_poly_maker_mas_per_slug_usdc
        return [
            Decision(
                ts_us=evt.ts_us,
                strategy=self.code,
                slug=evt.slug,
                asset=evt.asset,
                tf=evt.tf,
                action="MINT",
                side=None,
                price=None,
                size=amount,
                order_id=None,
                trigger_reason="mint_initial",
            )
        ]

    def seed_inventory(
        self,
        evt: SlugActive,
        inv_up: Decimal,
        inv_dn: Decimal,
    ) -> None:
        """Pre-seed SlugState with on-chain inventory; do NOT emit any Decision.

        Used by ``poly_maker_loop._slug_discovery_tick`` when a CTF
        ``balanceOf`` probe at slug discovery reveals that a prior
        tv-engine process already minted shares for this slug. Without
        this seeding, the next ``on_slug_active`` for the same slug (post
        in-memory state loss across restart) would call
        ``split_position`` a second time → DOUBLE-DEPLOY capital in LIVE
        mode (~$1779284881 / 30 USDC observed on vps_ireland 2026-05-20).

        The seeded state participates in the normal lifecycle from this
        point forward: ``on_l25_update`` posts ASKs against ``inv_*``;
        ``on_order_fill`` decrements; ``on_slug_resolved`` redeems.

        Args:
            evt: The SlugActive event the loop received from gamma. We
                use it as the condition_id / token_id_* / asset / tf
                source so the seeded state is byte-identical to what an
                ``on_slug_active`` call would have produced.
            inv_up: On-chain ``CTF.balanceOf(wallet, token_id_up)`` →
                Decimal share-count.
            inv_dn: On-chain ``CTF.balanceOf(wallet, token_id_dn)`` →
                Decimal share-count.

        No-op if a SlugState for this slug already exists (idempotent —
        double-discovery within one process is harmless).
        """
        if evt.slug in self.slug_states:
            return
        state = SlugState(
            slug=evt.slug,
            condition_id=evt.condition_id,
            token_id_up=evt.token_id_up,
            token_id_dn=evt.token_id_dn,
            asset=evt.asset,
            tf=evt.tf,
            slug_active_ts_us=evt.ts_us,
        )
        state.inv_up = inv_up
        state.inv_dn = inv_dn
        # cash_spent reflects the original mint cost. Since we discover
        # this across-restart, the original mint cost was paid in the
        # previous process; track it here so the dashboard PnL aligns
        # with the actual capital deployed.
        if inv_up > 0 or inv_dn > 0:
            state.cash_spent = max(inv_up, inv_dn)
        self.slug_states[evt.slug] = state
        log.info(
            "mas.seed_inventory.from_chain",
            slug=evt.slug,
            inv_up=str(inv_up),
            inv_dn=str(inv_dn),
        )

    def on_l25_update(self, evt: L25Update) -> list[Decision]:
        """Emit POST_ASK for the ticked side IF inventory > 0 + no open ask."""
        state = self.slug_states.get(evt.slug)
        if state is None:
            return []

        # Inventory check for the ticked side.
        inv_on_side = state.inv_up if evt.side == "up" else state.inv_dn
        if inv_on_side <= 0:
            return []

        # Dedup — at most ONE open ASK per side at a time. The dispatcher
        # (poly_maker_loop, Plan 30-10) handles CANCEL on 3¢ displacement
        # or 20s age. This module just refuses to double-post.
        for oo in state.open_orders.values():
            if oo.side == evt.side:
                return []

        # Need a best_ask to post against.
        if not evt.asks:
            return []
        best_ask = evt.asks[0][0]

        # Quantize to 1¢ tick + clamp to the _MIN_PRICE floor (defensive
        # against degenerate best_ask=0 frames).
        price = max(_MIN_PRICE, quantize_price(best_ask))

        # Size: small per-tick chunks; bounded by inventory + a 2× cap on
        # MIN_POST_SHARES. Larger total per-slug volume emerges from
        # many repeated posts as fills clear the open-ask slot.
        min_post = self.config.tv_poly_maker_min_post_shares
        cap = min_post * _POST_SIZE_MAX_MULT
        size = min(inv_on_side, cap)
        # Floor at min_post — never post below the CLOB minimum.
        if size < min_post:
            size = min_post

        order_id = self._next_local_oid()
        state.open_orders[order_id] = OpenOrder(
            order_id=order_id,
            side=evt.side,
            price=price,
            size=size,
            ts_posted_us=evt.ts_us,
        )

        return [
            Decision(
                ts_us=evt.ts_us,
                strategy=self.code,
                slug=evt.slug,
                asset=state.asset,
                tf=state.tf,
                action="POST_ASK",
                side=evt.side,
                price=price,
                size=size,
                order_id=order_id,
                trigger_reason="post_ask_inventory",
            )
        ]

    def on_trade_print(self, evt: TradePrint) -> list[Decision]:
        """MAS ignores trade prints (only ACC-H consumes them)."""
        return []

    def on_order_fill(self, evt: OrderFill) -> list[Decision]:
        """Branch by order_id prefix.

        - ``MAS-MINT-*`` prefix → synthetic mint-confirmation from Plan
          30-10. Sets inv_up = inv_dn = ``mas_per_slug_usdc`` (each USDC
          dollar splits into 1 up + 1 dn share via CTF.splitPosition).
          The mint cost is recorded as ``cash_spent``.

        - Any other prefix → regular ASK fill. Decrement inv on side,
          accumulate cash_received += price*size, accumulate maker
          rebate if applicable, remove the local order, bump n_fills.
          Unknown order_id → log WARNING + return [].
        """
        state = self.slug_states.get(evt.slug)
        if state is None:
            return []

        # Branch 1: synthetic mint-confirmation event.
        if evt.order_id.startswith(_MINT_CONFIRM_PREFIX):
            amount = self.config.tv_poly_maker_mas_per_slug_usdc
            state.inv_up = amount
            state.inv_dn = amount
            # Record the mint cost (1 USDC per pair) as cash_spent — the
            # slug-level PnL is computed at the dashboard layer as
            # cash_received + redemption - cash_spent.
            state.cash_spent += amount
            return []

        # Branch 2: regular ASK fill.
        order = state.open_orders.get(evt.order_id)
        if order is None:
            log.warning(
                "mas.fill.unknown_order_id",
                slug=evt.slug,
                order_id=evt.order_id,
                size=str(evt.size),
                price=str(evt.price),
            )
            return []

        if evt.side == "up":
            state.inv_up -= evt.size
        else:
            state.inv_dn -= evt.size

        state.cash_received += evt.price * evt.size
        if evt.is_maker:
            # Maker rebate accounting — 20% of the equivalent taker fee.
            state.rebates_received += maker_rebate(taker_fee(evt.price)) * evt.size
        else:
            # Defensive: a non-maker fill on an ASK shouldn't normally
            # occur (we're the resting order), but if it does, accumulate
            # the taker fee for accounting symmetry with ACC-M.
            state.taker_fees_paid += taker_fee(evt.price) * evt.size

        del state.open_orders[evt.order_id]
        state.n_fills += 1

        return []

    def on_slug_resolved(self, evt: SlugResolved) -> list[Decision]:
        """Emit REDEEM Decision for the winner-side residual.

        Loser-side residual is worthless (no REDEEM). If both inv are zero
        (no mint ever settled / everything sold + nothing redeemed), return
        []. Mirrors the spec §3.4 logic verbatim.
        """
        state = self.slug_states.get(evt.slug)
        if state is None:
            return []

        winner_inv = state.inv_up if evt.winner == "up" else state.inv_dn
        if winner_inv <= 0:
            return []

        return [
            Decision(
                ts_us=evt.ts_us,
                strategy=self.code,
                slug=evt.slug,
                asset=state.asset,
                tf=state.tf,
                action="REDEEM",
                side=evt.winner,
                price=None,
                size=winner_inv,
                order_id=None,
                trigger_reason="redeem_winner_residual",
            )
        ]


def recover_mas_state_from_csv(
    mas_strategy: "MasStrategy",
    csv_path: Path,
) -> int:
    """Boot helper — pre-seed MAS strategy with today's CSV mint history.

    Cross-restart re-mint defense. After a tv-engine restart, MAS's in-memory
    ``slug_states`` is empty. When gamma's discovery loop re-fires SlugActive
    for an active slug, MAS would normally mint AGAIN -- but the previous
    process already paid the mint cost (shadow: $30 logged; live: $30 on-chain).

    This function scans today's `mas_<date>.csv` for MAS-MINT-* rows matching
    the strategy's (asset, tf) cell. For each unique slug it finds, it
    stashes the latest inventory snapshot in ``mas_strategy._pending_csv_recovery``.
    When ``on_slug_active`` later fires for that slug, MAS reads from the stash
    and calls ``seed_inventory`` instead of minting.

    Args:
        mas_strategy: The MasStrategy instance to seed (one per cell).
        csv_path: Path to today's mas CSV (e.g. /var/log/tv/maker/mas_2026-05-20.csv).
            Missing/empty file is a no-op.

    Returns:
        Number of slugs queued for recovery (0 if no prior mints found).
    """
    import csv as _csv

    if not csv_path.exists():
        return 0

    asset_upper = mas_strategy.asset.upper()
    tf = mas_strategy.tf
    # Group: slug -> (latest_ts_us, inv_up, inv_dn)
    latest: dict[str, tuple[int, Decimal, Decimal]] = {}
    try:
        with csv_path.open("r", newline="") as fh:
            reader = _csv.DictReader(fh)
            for r in reader:
                if (r.get("strategy") or "") != "MAS":
                    continue
                if (r.get("asset") or "").upper() != asset_upper:
                    continue
                if (r.get("tf") or "") != tf:
                    continue
                slug = r.get("slug") or ""
                if not slug:
                    continue
                inv_up_s = r.get("inv_up") or ""
                inv_dn_s = r.get("inv_dn") or ""
                if not inv_up_s or not inv_dn_s:
                    continue
                try:
                    ts_us = int(r.get("ts_us") or "0")
                    inv_up = Decimal(inv_up_s)
                    inv_dn = Decimal(inv_dn_s)
                except (ValueError, ArithmeticError):
                    continue
                existing = latest.get(slug)
                if existing is None or ts_us > existing[0]:
                    latest[slug] = (ts_us, inv_up, inv_dn)
    except OSError:
        log.exception(
            "mas.recover_mas_state_from_csv.read_failed",
            path=str(csv_path),
        )
        return 0

    queued = 0
    for slug, (_ts, inv_up, inv_dn) in latest.items():
        if inv_up <= 0 and inv_dn <= 0:
            continue  # Slug was minted and fully sold/redeemed -- no recovery
        mas_strategy._pending_csv_recovery[slug] = (inv_up, inv_dn)
        queued += 1
        log.info(
            "mas.recover_mas_state_from_csv.queued",
            slug=slug,
            inv_up=str(inv_up),
            inv_dn=str(inv_dn),
            asset=asset_upper,
            tf=tf,
        )

    if queued > 0:
        log.info(
            "mas.recover_mas_state_from_csv.summary",
            n_slugs_queued=queued,
            asset=asset_upper,
            tf=tf,
            csv_path=str(csv_path),
        )
    return queued


__all__ = ["MasStrategy", "recover_mas_state_from_csv"]
