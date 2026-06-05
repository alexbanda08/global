"""Sleeve manifest introspection (Phase 23 · D-11/D-12/D-13/D-14/D-15).

Single source of truth for the ``GET /sleeves`` endpoint. Computes
``mode = 'live' | 'shadow'`` per request from the tri-state truth table:

    live  ⇔  registered ∧ engine_armed ∧ bundle_present ∧ ¬bundle.paused
              ∧ wallet_known ∧ wallet_balance ≥ bundle.total_size_usd

    shadow ⇔  any of the above is false; the ``reason`` field names
              the first failing condition (D-13).

NO new DB column. NO Redis cache. The mode is always fresh, recomputed
on every request — D-13. The frontend re-fetches on the WS
``sleeve_mode_changed`` event (D-14) which is published from the engine
side when the bundle balance crosses the threshold or the pause toggle
flips.

D-15 invariant — defense-in-depth: live-mode requires engine-armed AND
wallet-connected AND wallet-funded. The engine flag alone is not enough;
this module is the AND gate.

CLAUDE invariant #13 — read-only Storedata: this module does NOT query
``public.*``. All inputs are passed in by the caller (the API layer).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final, Literal

from backend.app.engine.bundles import Bundle, find_bundle_for_sleeve

logger = logging.getLogger(__name__)

Mode = Literal["live", "shadow"]

# Phase 30 — maker-arb sleeve prefixes. Canonical form is
# ``poly_<strat>_<asset>_<tf>_shadow``; ``_resolve_timeframe`` parses the
# embedded TF token via prefix-driven slicing (acc_m/acc_h have a 3-token
# prefix → tf=parts[4]; mas has a 1-token prefix after ``poly`` → tf=parts[3]).
MAKER_PREFIXES: Final[tuple[str, ...]] = (
    "poly_acc_m_",
    "poly_mas_",
    "poly_acc_h_",
    # Phase 31 — NEW shadow sleeves (TV_AGENT_CHANGES §4 + §5).
    "poly_acc_pc_",
    "poly_pat_shadow_",
)

# Phase 35 — sniper-v5 sleeve prefixes. Canonical form is
# ``poly_sniper_v5_<asset>_<tf>_<descriptor>``. Single-prefix family —
# all 16 sleeves share the same root token. ``_resolve_timeframe`` parses
# parts[3] as the tf token for every sniper-v5 sleeve_id.
SNIPER_V5_PREFIXES: Final[tuple[str, ...]] = ("poly_sniper_v5_",)


@dataclass(frozen=True)
class SleeveManifestEntry:
    """One row in the ``GET /sleeves`` response."""

    sleeve_id: str
    venue: str  # 'HL' | 'POLY'
    bundle_id: str | None
    mode: Mode
    reason: str  # enum-ish; never free text. CLAUDE inv #9 satisfied.
    timeframe: str | None  # display-friendly, e.g. '5m', '15m', '4h', '1w'
    # Phase 33 (D-03) — Operator-deprecated sleeves. True when sleeve_id
    # appears in TV_POLY_DEPRECATED_SLEEVES (CSV). The dashboard renders
    # these with [DEPRECATED] chip + grayed body in a separate collapsed
    # "Deprecated" section; they are excluded from active aggregations
    # (D-11). Default False keeps every existing instantiation valid.
    deprecated: bool = False


def compute_mode(
    *,
    registered: bool,
    bundle: Bundle | None,
    wallet_balance_usd: float | None,
    engine_armed: bool,
) -> tuple[Mode, str]:
    """Return ``(mode, reason)`` per the D-13/D-15 truth table.

    Reason codes (enum-like; consumed by the operator UI as tooltip text):
        not_registered, engine_not_armed, no_bundle, bundle_paused,
        wallet_unknown, bundle_unfunded, ok
    """
    if not registered:
        return "shadow", "not_registered"
    if not engine_armed:
        return "shadow", "engine_not_armed"
    if bundle is None:
        return "shadow", "no_bundle"
    if bundle.paused:
        return "shadow", "bundle_paused"
    if wallet_balance_usd is None:
        return "shadow", "wallet_unknown"
    if wallet_balance_usd < bundle.total_size_usd:
        return "shadow", "bundle_unfunded"
    return "live", "ok"


def _tf_seconds_to_label(seconds: int | None) -> str | None:
    """Render an ``int`` second count as a display label (e.g. ``5m``).

    Returns ``None`` when the input is ``None`` so the API surface can
    distinguish "no timeframe known" (e.g. an unregistered sleeve_id)
    from a known timeframe.
    """
    if seconds is None:
        return None
    if seconds % (7 * 24 * 3600) == 0:
        return f"{seconds // (7 * 24 * 3600)}w"
    if seconds % (24 * 3600) == 0:
        return f"{seconds // (24 * 3600)}d"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def _resolve_timeframe(
    sleeve_id: str, sleeve_timeframes: dict[str, int]
) -> str | None:
    """Resolve a sleeve_id's display timeframe.

    Priority:
      1. Direct lookup in ``sleeve_timeframes`` (V52 / V24 keys land here).
      2. Fallback parse of the sleeve_id's middle token for Polymarket sleeves
         in the canonical ``poly_updown_<sym>_<tf>_<mode>`` form
         (``backend/app/api/bots.py:45-75``). The ``<tf>`` token is already
         a display label (``5m``, ``15m``).
      3. ``None`` when neither path resolves (HL sleeve not in the registry,
         or a malformed sleeve_id).
    """
    direct = sleeve_timeframes.get(sleeve_id)
    if direct is not None:
        return _tf_seconds_to_label(direct)
    if sleeve_id.startswith("poly_updown_"):
        # canonical form: poly_updown_<sym>_<tf>_<mode>
        parts = sleeve_id.split("_")
        if len(parts) >= 5:
            tf = parts[3]  # '5m' or '15m'
            if tf in {"5m", "15m"}:
                return tf
    # Phase 30 — maker-arb sleeves. Canonical form is
    # ``poly_<strat>_<asset>_<tf>_shadow``. The TF token's index depends on
    # the strategy-code arity:
    #   * ``poly_acc_m_btc_15m_shadow`` → 6 parts, tf=parts[4]
    #   * ``poly_acc_h_btc_5m_shadow``  → 6 parts, tf=parts[4]
    #   * ``poly_mas_eth_5m_shadow``    → 5 parts, tf=parts[3]
    if sleeve_id.startswith(("poly_acc_m_", "poly_acc_h_", "poly_acc_pc_")):
        parts = sleeve_id.split("_")
        # Phase C V2: 7-part form ``poly_acc_m_v2_<asset>_<tf>_shadow``
        # has tf at parts[5]. V1 6-part form has tf at parts[4].
        if len(parts) >= 7 and parts[3] == "v2":
            tf = parts[5]
            if tf in {"5m", "15m"}:
                return tf
        if len(parts) >= 6:
            tf = parts[4]
            if tf in {"5m", "15m"}:
                return tf
    elif sleeve_id.startswith("poly_mas_"):
        parts = sleeve_id.split("_")
        # Phase C V2: 6-part form ``poly_mas_v2_<asset>_<tf>_shadow``
        # has tf at parts[4]. V1 5-part form has tf at parts[3].
        if len(parts) >= 6 and parts[2] == "v2":
            tf = parts[4]
            if tf in {"5m", "15m"}:
                return tf
        if len(parts) >= 5:
            tf = parts[3]
            if tf in {"5m", "15m"}:
                return tf
    elif sleeve_id.startswith("poly_pat_shadow_"):
        # Format: poly_pat_shadow_<asset>_<tf>_shadow → 6 parts, tf=parts[4]
        parts = sleeve_id.split("_")
        if len(parts) >= 6:
            tf = parts[4]
            if tf in {"5m", "15m"}:
                return tf
    # Phase 35 — sniper-v5 sleeves. Canonical form is
    # ``poly_sniper_v5_<asset>_<tf>_<descriptor>``. The tf is parts[4]
    # because the ``poly_sniper_v5`` prefix consumes parts[0..2] and the
    # asset (btc/eth/sol) consumes parts[3]:
    #   ``poly_sniper_v5_btc_5m_ts_mpskew_any_off30`` →
    #     ['poly','sniper','v5','btc','5m','ts','mpskew','any','off30']
    #   parts[4] = '5m'.
    if sleeve_id.startswith("poly_sniper_v5_"):
        parts = sleeve_id.split("_")
        if len(parts) >= 5:
            tf = parts[4]
            if tf in {"5m", "15m"}:
                return tf
    # fast_taker — ``poly_fast_taker_<config>_<merge>_<sym>_<tf>``; tf is the
    # trailing token (the config descriptor sits before sym/tf).
    if sleeve_id.startswith("poly_fast_taker_"):
        parts = sleeve_id.split("_")
        if len(parts) >= 6:
            tf = parts[-1]
            if tf in {"5m", "15m"}:
                return tf
    # Phase 38 — Kalshi sniper sleeves. Canonical form is
    # ``kalshi_sniper_<asset>_<tf>_<descriptor>``; the ``kalshi_sniper``
    # prefix consumes parts[0..1] and the asset parts[2], so tf=parts[3]:
    #   ``kalshi_sniper_btc_15m_ema50_ema800_off600_down`` →
    #     ['kalshi','sniper','btc','15m',...] → parts[3] = '15m'.
    if sleeve_id.startswith("kalshi_sniper_"):
        parts = sleeve_id.split("_")
        if len(parts) >= 4:
            tf = parts[3]
            if tf in {"5m", "15m"}:
                return tf
    return None


def _maker_arb_sleeve_id(strat_code: str, asset: str, tf: str) -> str:
    """Build the canonical maker-arb sleeve_id.

    >>> _maker_arb_sleeve_id("ACC-M", "BTC", "15m")
    'poly_acc_m_btc_15m_shadow'
    >>> _maker_arb_sleeve_id("MAS", "SOL", "5m")
    'poly_mas_sol_5m_shadow'
    """
    return (
        f"poly_{strat_code.lower().replace('-', '_')}"
        f"_{asset.lower()}_{tf}_shadow"
    )


def introspect_sleeves(
    *,
    poly_sleeve_ids: tuple[str, ...],
    hl_sleeve_ids: tuple[str, ...],
    bundles: list[Bundle],
    poly_wallet_usd: float | None,
    hl_wallet_usd: float | None,
    engine_armed: bool,
    sleeve_timeframes: dict[str, int],
    kalshi_sleeve_ids: tuple[str, ...] = (),
    kalshi_live_sleeve_ids: frozenset[str] = frozenset(),
) -> list[SleeveManifestEntry]:
    """Build the canonical sleeve manifest.

    The caller injects engine state; this function performs no I/O and
    has no global lookups. That keeps it trivially testable.

    Args:
        poly_sleeve_ids: canonical Poly sleeve_ids (suffix-bearing form,
                         e.g. ``poly_updown_btc_5m_volume``).
        hl_sleeve_ids:   canonical HL sleeve_ids (e.g. ``V52-ETH``,
                         ``CCI_ETH_P3``).
        bundles:         loaded ``Bundle`` records from
                         ``engine.bundles.load_bundles``.
        poly_wallet_usd: cached Poly USDC balance, or ``None`` if unknown
                         (60s poll cadence per D-16).
        hl_wallet_usd:   cached HL clearinghouse balance, or ``None``.
        engine_armed:    whether the BarEngine has armed for live fire.
        sleeve_timeframes: mapping of sleeve_id → seconds (canonical
                           ``backend.app.engine.sleeve_timeframes`` map).

    Returns:
        List of ``SleeveManifestEntry`` — Poly first, then HL — preserving
        the canonical ordering of the input tuples (which the dashboard
        smoke tests rely on for sentinel grep).
    """
    # Phase 33 (D-04) — Lazy-import deprecation set from bots to avoid
    # circular import. The set is module-level frozenset, populated once
    # at bots.py import from the TV_POLY_DEPRECATED_SLEEVES CSV.
    from backend.app.api.bots import _DEPRECATED_POLY_UPDOWN_SLEEVE_IDS

    # Phase 37 Wave 5 — the TV_POLY_DEPRECATED_HIDE wipe-mode toggle is RETIRED.
    # Deprecated sleeves are ALWAYS re-added to the manifest with
    # ``deprecated=True`` so they stay enumerable + searchable and render in the
    # OverviewView "Deprecated" section (which DOES exist — DASHBOARD tab on
    # /terminal). They are excluded from the active grid + aggregations by the
    # frontend (``applyFilters`` early-returns on ``sleeve.deprecated``), so
    # surfacing them no longer clutters the operator's live view. Lifecycle is
    # now a registry ``status`` (live | deprecated | archived), not a wipe flag.
    #
    # Phase 33 (D-04) — Deprecated sleeves are pre-filtered OUT of
    # poly_sleeve_ids by bots._resolve_poly_updown_sleeve_ids() (D-05), so we
    # re-add them here. Dedup while preserving order.
    poly_sleeve_ids_all: tuple[str, ...]
    if _DEPRECATED_POLY_UPDOWN_SLEEVE_IDS:
        existing = set(poly_sleeve_ids)
        extra = tuple(
            sid for sid in _DEPRECATED_POLY_UPDOWN_SLEEVE_IDS
            if sid not in existing
        )
        poly_sleeve_ids_all = poly_sleeve_ids + extra
    else:
        poly_sleeve_ids_all = poly_sleeve_ids

    out: list[SleeveManifestEntry] = []
    for sid in poly_sleeve_ids_all:
        b = find_bundle_for_sleeve(bundles, sid)
        mode, reason = compute_mode(
            registered=True,
            bundle=b,
            wallet_balance_usd=poly_wallet_usd,
            engine_armed=engine_armed,
        )
        out.append(
            SleeveManifestEntry(
                sleeve_id=sid,
                venue="POLY",
                bundle_id=b.bundle_id if b else None,
                mode=mode,
                reason=reason,
                timeframe=_resolve_timeframe(sid, sleeve_timeframes),
                deprecated=(sid in _DEPRECATED_POLY_UPDOWN_SLEEVE_IDS),
            )
        )
    for sid in hl_sleeve_ids:
        b = find_bundle_for_sleeve(bundles, sid)
        mode, reason = compute_mode(
            registered=True,
            bundle=b,
            wallet_balance_usd=hl_wallet_usd,
            engine_armed=engine_armed,
        )
        out.append(
            SleeveManifestEntry(
                sleeve_id=sid,
                venue="HL",
                bundle_id=b.bundle_id if b else None,
                mode=mode,
                reason=reason,
                timeframe=_resolve_timeframe(sid, sleeve_timeframes),
            )
        )
    # Phase 38 — Kalshi sleeves. Same updown class, new venue. Kalshi's
    # live/shadow state is NOT gated by a Poly bundle/wallet (no Kalshi bundle,
    # no Kalshi wallet probe yet); it is driven by the engine's D-06 live config
    # (tv_kalshi_mode=='live' AND tv_kalshi_live_enabled AND sleeve_id ∈
    # tv_kalshi_live_sleeve_ids). The caller resolves that set and passes it in
    # as ``kalshi_live_sleeve_ids`` so the card truthfully shows LIVE on
    # real-money sleeves (operator-safety: a "shadow" label on a live sleeve is
    # dangerous). Everything else stays shadow via the standard truth table.
    for sid in kalshi_sleeve_ids:
        b = find_bundle_for_sleeve(bundles, sid)
        if sid in kalshi_live_sleeve_ids:
            mode, reason = "live", "ok"
        else:
            mode, reason = compute_mode(
                registered=True,
                bundle=b,
                wallet_balance_usd=None,  # Kalshi shadow has no wallet gate yet
                engine_armed=engine_armed,
            )
        out.append(
            SleeveManifestEntry(
                sleeve_id=sid,
                venue="KALSHI",
                bundle_id=b.bundle_id if b else None,
                mode=mode,
                reason=reason,
                timeframe=_resolve_timeframe(sid, sleeve_timeframes),
            )
        )
    return out


__all__ = [
    "MAKER_PREFIXES",
    "Mode",
    "SNIPER_V5_PREFIXES",
    "SleeveManifestEntry",
    "_maker_arb_sleeve_id",
    "compute_mode",
    "introspect_sleeves",
]
